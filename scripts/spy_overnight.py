#!/usr/bin/env python3
"""Overnight-SPY with a trend filter — the one candidate that beats SPY on Sharpe.

Rule: hold SPY OVERNIGHT only (buy at close, sell at next open) — but only when
yesterday's close is above its N-day moving average (skip bear markets). Cash
otherwise. One instrument, so it is commission-free at Schwab and trivial to run
by hand (one buy near the close, one sell at the open).

Because I found this by trying several overlays, it MUST be validated, not just
reported: net of costs, split-sample (is the edge in both halves?), and
parameter sensitivity (does it survive changing the SMA window?). Leverage is
shown because a high-Sharpe / low-vol stream can be scaled to SPY's return.

Usage:
    python scripts/spy_overnight.py
    python scripts/spy_overnight.py --sma 200 --spread-bps 0.5 --leverage 2
"""

import argparse
import os
import sys

import numpy as np
import pandas as pd

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
SPY = os.path.join(_ROOT, "..", "sp500-intraday-ranker", "data", "market",
                   "SPY_daily.parquet")
TD = 252


def describe(r: pd.Series, name: str) -> dict:
    r = r.dropna()
    if r.empty:
        return {}
    ann = r.mean() * TD
    vol = r.std() * np.sqrt(TD)
    sh = r.mean() / r.std() * np.sqrt(TD) if r.std() > 0 else np.nan
    cur = (1 + r).cumprod()
    dd = (cur / cur.cummax() - 1).min()
    tot = (1 + r).prod() - 1
    cagr = max(1 + tot, 1e-9) ** (TD / len(r)) - 1
    print(f"{name:<40} CAGR {cagr:+6.1%}  Sharpe {sh:5.2f}  Vol {vol:5.1%}  MaxDD {dd:6.1%}")
    return dict(CAGR=cagr, Sharpe=sh, Vol=vol, MaxDD=dd)


def build(spread_bps: float, leverage: float, sma: int, margin_rate: float):
    df = pd.read_parquet(SPY)
    df.index = pd.to_datetime(df.index)
    o, c = df["Open"], df["Close"]
    pc = c.shift(1)

    overnight = o / pc - 1                       # close_t -> open_{t+1}
    c2c = c / pc - 1                             # buy & hold
    sma_line = c.rolling(sma).mean()
    in_trend = c.shift(1) > sma_line.shift(1)    # lagged: no lookahead

    # Costs: overnight strat trades 2×/invested day; SPY spread is tiny, $0 comm.
    rt_cost = 2 * spread_bps / 1e4
    borrow = max(leverage - 1.0, 0.0) * margin_rate / TD

    raw = overnight.where(in_trend, 0.0)
    invested = in_trend & overnight.notna()
    strat = leverage * raw - invested.astype(float) * (leverage * rt_cost + borrow)
    return dict(strat=strat, c2c=c2c, overnight=overnight, in_trend=in_trend,
                index=df.index, leverage=leverage, margin_rate=margin_rate)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--sma", type=int, default=200)
    ap.add_argument("--spread-bps", type=float, default=0.5,
                    help="SPY half-spread+slippage per side (default 0.5bp — SPY is "
                         "penny-wide on ~$600). Schwab/IBKR-Lite commission is $0.")
    ap.add_argument("--leverage", type=float, default=1.0)
    ap.add_argument("--margin-rate", type=float, default=0.055)
    args = ap.parse_args()

    b = build(args.spread_bps, args.leverage, args.sma, args.margin_rate)
    strat, c2c = b["strat"], b["c2c"]

    print("=" * 84)
    print(f"  OVERNIGHT SPY + >{args.sma}d SMA filter   "
          f"spread {args.spread_bps}bp/side  leverage {args.leverage}x  "
          f"(net of costs)")
    print("=" * 84)
    describe(strat, f"strategy {args.leverage}x (NET)")
    # Levered buy&hold SPY at the same leverage, for a fair comparison.
    lev_spy = args.leverage * c2c - (max(args.leverage - 1, 0) * args.margin_rate / TD)
    describe(lev_spy, f"SPY buy&hold {args.leverage}x (NET)")
    if args.leverage != 1.0:
        describe(c2c, "SPY buy&hold 1x")

    print("\n--- Robustness: two halves (net, unlevered strat vs SPY) ---")
    strat1 = build(args.spread_bps, 1.0, args.sma, args.margin_rate)["strat"]
    idx = b["index"]
    mid = idx[len(idx) // 2]
    for lab, sl in [("2016 -> " + str(mid.date()), idx <= mid),
                    (str(mid.date()) + " -> 2026", idx > mid)]:
        m = pd.Series(sl, index=idx)
        print(f"  [{lab}]")
        describe(strat1[m.values], "    overnight+trend (net)")
        describe(c2c[m.values], "    SPY buy&hold")

    print("\n--- Parameter sensitivity: SMA window (net, unlevered) ---")
    for n in (100, 150, 200, 250):
        s = build(args.spread_bps, 1.0, n, args.margin_rate)["strat"]
        describe(s, f"  SMA={n}")

    print("\n--- Exposure ---")
    print(f"  in-market {b['in_trend'].mean():.0%} of days "
          f"(cash the rest); ~{b['in_trend'].sum()/ (len(idx)/TD):.0f} invested days/yr")
    return 0


if __name__ == "__main__":
    sys.exit(main())
