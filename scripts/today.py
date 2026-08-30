#!/usr/bin/env python3
"""Tonight's decision for the overnight-QQQ + 200d-trend strategy.

    IF QQQ's latest close > its 200-day SMA
        -> BUY the picked instrument market-on-close, SELL market-on-open
           tomorrow.
    ELSE
        -> CASH tonight.

The signal is always QQQ's own trend; WHICH instrument to buy comes from QQQ's
20-day realized vol (rvol<18% -> TQQQ 3x, >28% -> QQQ 1x, else QLD 2x).
Run it after ~3:40pm ET, when the day's price is essentially final. It is a
signal tool -- it does NOT place orders.

Usage:
    uv run python scripts/today.py                    # auto-pick, $10k
    uv run python scripts/today.py --capital 5000     # auto, smaller account
    uv run python scripts/today.py --instrument QLD   # force a fixed instrument
"""
import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

import pandas as pd
from alpaca.data.enums import Adjustment, DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from strategy import (LEVERAGE, RVOL_HI, RVOL_LO, SMA_WINDOW,  # noqa: E402
                      pick_instrument, signals)

_ENV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
SIGNAL_SYMBOL = "QQQ"                       # the trend is ALWAYS computed on QQQ


def get_client() -> StockHistoricalDataClient:
    """Alpaca historical-data client; keys from the environment or repo .env."""
    if os.path.exists(_ENV):
        for line in open(_ENV):
            k, _, v = line.strip().partition("=")
            if k and not k.startswith("#") and v:
                os.environ.setdefault(k, v.strip("'\""))
    key, secret = os.environ.get("ALPACA_API_KEY"), os.environ.get("ALPACA_SECRET_KEY")
    if not key or not secret:
        sys.exit("ALPACA_API_KEY / ALPACA_SECRET_KEY not set (free keys: alpaca.markets).")
    return StockHistoricalDataClient(api_key=key, secret_key=secret)


def daily_closes(client: StockHistoricalDataClient, symbol: str, days: int = 430) -> pd.Series:
    """Split-adjusted daily closes. Free-tier SIP needs `end` >= 15 min in the past."""
    end = datetime.now(timezone.utc) - timedelta(minutes=16)
    bars = client.get_stock_bars(StockBarsRequest(
        symbol_or_symbols=symbol, timeframe=TimeFrame.Day, start=end - timedelta(days=days),
        end=end, adjustment=Adjustment.SPLIT, feed=DataFeed.SIP)).df
    if bars.empty:
        sys.exit(f"No bars returned for {symbol}.")
    return bars.loc[symbol]["close"].sort_index()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--capital", type=float, default=10_000.0)
    ap.add_argument("--instrument", choices=("auto", *LEVERAGE), default="auto",
                    help="What to buy. 'auto' (default) picks via the vol regime.")
    ap.add_argument("--sma", type=int, default=SMA_WINDOW)
    args = ap.parse_args()

    client = get_client()
    close = daily_closes(client, SIGNAL_SYMBOL)
    if len(close) < args.sma + 1:
        sys.exit(f"Not enough {SIGNAL_SYMBOL} history for a {args.sma}d average.")

    sig = signals(close, args.sma).iloc[-1]
    px_qqq, latest = float(close.iloc[-1]), close.index[-1]
    sma_now = float(close.rolling(args.sma).mean().iloc[-1])
    rvol = float(sig["rvol"])

    if args.instrument == "auto":
        instrument = pick_instrument(rvol)
        regime = "calm trend" if rvol < RVOL_LO else "stormy" if rvol > RVOL_HI else "mid vol"
    else:
        instrument, regime = args.instrument, "forced by --instrument"
    px = px_qqq if instrument == SIGNAL_SYMBOL else float(
        daily_closes(client, instrument, days=10).iloc[-1])

    print("\n" + "=" * 62)
    print(f"  OVERNIGHT STRATEGY — decision for {latest.date()}")
    print(f"  signal: {SIGNAL_SYMBOL} trend   |   buy: {instrument} "
          f"({LEVERAGE[instrument]}x)")
    print("=" * 62)
    print(f"  {SIGNAL_SYMBOL} close     : {px_qqq:,.2f}")
    print(f"  {args.sma}d average : {sma_now:,.2f}   ({(px_qqq / sma_now - 1) * 100:+.1f}% vs price)")
    print(f"  trend           : {'ABOVE ✅' if sig['in_trend'] else 'BELOW ❌'}")
    print(f"  20d realized vol: {rvol:5.1%}   -> {instrument} ({regime})")
    print("-" * 62)

    if sig["in_trend"]:
        shares = int(args.capital // px)              # ETF leverage is inside the price
        print(f"  DECISION: BUY {instrument}  🟢")
        print(f"    ${args.capital:,.0f} capital -> BUY {shares} {instrument} "
              f"@ ~{px:,.2f}  (~${shares * px:,.0f})")
        if instrument == "TQQQ":
            print("    ⚠ TQQQ is 3x — a ~33% overnight gap in QQQ zeroes it. Size small.")
        print("\n  HOW TO PLACE IT:")
        print(f"    1. Before 3:45pm ET: BUY {shares} {instrument} MARKET-ON-CLOSE (MOC).")
        print(f"    2. Same evening, once filled: SELL {shares} {instrument} "
              f"MARKET-ON-OPEN (MOO).")
        print("    3. Re-run this script tomorrow afternoon.")
    else:
        print(f"  DECISION: CASH tonight  ⚪  ({SIGNAL_SYMBOL} below its {args.sma}d average)")
        print("    Place no trade. Re-run tomorrow — re-enter when QQQ crosses back above.")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
