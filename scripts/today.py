#!/usr/bin/env python3
"""Today's decision for the overnight-QQQ + 200d-trend strategy.

The rule (validated 1999-2026, see README):
    IF QQQ's latest daily close > its 200-day moving average
        -> BUY the chosen instrument near today's close (market-on-close),
           SELL at tomorrow's open (market-on-open).
    ELSE
        -> stay in CASH tonight.

The SIGNAL is always QQQ's own 200-day trend. The INSTRUMENT is picked
AUTOMATICALLY from QQQ's 20-day realized volatility (a self-contained VIX proxy;
see scripts/regime_switch.py for the backtest, Sharpe 1.25 / +29% CAGR):
    rvol < 18%  -> TQQQ (3x)   calm trend, leverage decay is tiny
    rvol > 28%  -> QQQ  (1x)   stormy, de-lever
    otherwise   -> QLD  (2x)
All held overnight only. You can still force one with --instrument.

Run it any time after ~3:45pm ET (so the day's price is essentially final) up to
the close. It is a signal tool — it does NOT place orders.

Usage:
    python scripts/today.py                        # AUTO-pick instrument, $10k
    python scripts/today.py --capital 2000          # auto, smaller account
    python scripts/today.py --instrument QLD        # force 2x (override the picker)
"""

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

# Reuse the sibling's Alpaca client (same keys live in this repo's .env too).
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "..", "sp500-intraday-ranker", "scripts"))
from alpaca_client import get_client, BAR_1DAY, fetch_bars  # noqa: E402

SMA_WINDOW = 200
RVOL_WINDOW = 20              # trading days for realized-vol regime
RVOL_LO = 0.18               # rvol below -> TQQQ (3x)
RVOL_HI = 0.28               # rvol above -> QQQ (1x)
SIGNAL_SYMBOL = "QQQ"          # the trend is ALWAYS computed on QQQ
LEVERAGE = {"QQQ": 1, "QLD": 2, "TQQQ": 3}


def pick_instrument(rvol: float, lo: float = RVOL_LO, hi: float = RVOL_HI) -> str:
    """Vol-regime instrument choice (see scripts/regime_switch.py)."""
    if rvol < lo:
        return "TQQQ"
    if rvol > hi:
        return "QQQ"
    return "QLD"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--capital", type=float, default=10_000.0)
    ap.add_argument("--instrument", choices=("auto", "QQQ", "QLD", "TQQQ"), default="auto",
                    help="What to buy. 'auto' (default) picks via the vol regime; "
                         "QQQ=1x, QLD=2x, TQQQ=3x force a fixed instrument.")
    ap.add_argument("--margin", type=float, default=1.0,
                    help="EXTRA retail margin on top (default 1.0 = none). Stacking "
                         "margin on a leveraged ETF is dangerous — leave at 1.0.")
    ap.add_argument("--sma", type=int, default=SMA_WINDOW)
    args = ap.parse_args()

    client = get_client()
    start = datetime.now(timezone.utc) - timedelta(days=430)

    # Signal from QQQ; price for sizing from the chosen instrument.
    qqq = fetch_bars(client, SIGNAL_SYMBOL, BAR_1DAY, start)
    if qqq is None or len(qqq) < args.sma + 1:
        sys.exit(f"Not enough {SIGNAL_SYMBOL} history for a {args.sma}d average.")
    qqq = qqq.sort_index()
    close = qqq["Close"]
    sma_now = float(close.rolling(args.sma).mean().iloc[-1])
    px_qqq = float(close.iloc[-1])
    latest_dt = close.index[-1]
    above = px_qqq > sma_now
    margin_pct = (px_qqq / sma_now - 1) * 100

    # 20-day realized vol (annualized) -> instrument regime.
    rvol = float(close.pct_change().rolling(RVOL_WINDOW).std().iloc[-1] * (252 ** 0.5))
    if args.instrument == "auto":
        instrument = pick_instrument(rvol)
        regime = ("CALM" if rvol < RVOL_LO else "STORMY" if rvol > RVOL_HI else "MID")
    else:
        instrument = args.instrument
        regime = "FORCED"

    if instrument == SIGNAL_SYMBOL:
        instr_px = px_qqq
    else:
        instr = fetch_bars(client, instrument, BAR_1DAY, start)
        if instr is None or instr.empty:
            sys.exit(f"Could not fetch {instrument} price.")
        instr_px = float(instr.sort_index()["Close"].iloc[-1])

    lev = LEVERAGE[instrument] * args.margin
    regime_note = {"CALM": "calm trend", "MID": "mid vol", "STORMY": "stormy",
                   "FORCED": "forced by --instrument"}[regime]

    print("\n" + "=" * 62)
    print(f"  OVERNIGHT STRATEGY — decision for {latest_dt.date()}")
    print(f"  signal: {SIGNAL_SYMBOL} trend   |   buy: {instrument} "
          f"({LEVERAGE[instrument]}x built-in, {lev:g}x total exposure)")
    print("=" * 62)
    print(f"  {SIGNAL_SYMBOL} close     : {px_qqq:,.2f}")
    print(f"  {args.sma}d average : {sma_now:,.2f}   ({margin_pct:+.1f}% vs price)")
    print(f"  trend           : {'ABOVE ✅' if above else 'BELOW ❌'}")
    print(f"  20d realized vol: {rvol:5.1%}   -> {instrument} ({regime_note})")
    print("-" * 62)

    if above:
        shares = int((args.capital * args.margin) // instr_px)   # ETF leverage is in the price
        actual = shares * instr_px
        print(f"  DECISION: BUY {instrument}  🟢   (effective {lev:g}x exposure)")
        print(f"    ${args.capital:,.0f} capital -> BUY {shares} {instrument} "
              f"@ ~{instr_px:,.2f}  (~${actual:,.0f})")
        if instrument == "TQQQ":
            print("    ⚠ TQQQ is 3x — a ~33% overnight gap in QQQ zeroes it. Size small.")
        if args.margin > 1.0:
            print(f"    ⚠ --margin {args.margin} stacks retail margin ON a leveraged "
                  f"ETF — {lev:g}x total. Very high risk.")
        print()
        print("  HOW TO PLACE IT:")
        print(f"    1. Near today's close (~3:55pm ET): BUY {shares} {instrument}")
        print(f"       as a MARKET-ON-CLOSE (MOC) order.")
        print(f"    2. At tomorrow's open (9:30am ET): SELL {shares} {instrument}")
        print(f"       as a MARKET-ON-OPEN (MOO) order.")
        print("    3. Re-run this script tomorrow afternoon.")
    else:
        print(f"  DECISION: CASH tonight  ⚪  ({SIGNAL_SYMBOL} below its {args.sma}d average)")
        print("    Place no trade. Re-run tomorrow — re-enter once QQQ crosses back")
        print("    above the average.")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
