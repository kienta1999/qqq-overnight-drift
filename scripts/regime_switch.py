#!/usr/bin/env python3
"""Volatility-regime instrument switcher for the overnight-QQQ + 200d-trend rule.

The entry/exit is UNCHANGED from the deployed strategy: hold OVERNIGHT only
(buy at today's close, sell at tomorrow's open), and only when QQQ's close is
above its 200-day SMA (cash otherwise). The ONE thing this adds: on each night
we're in the market, pick WHICH leverage to buy from QQQ's 20-day realized
volatility (a self-contained VIX proxy) --

    rvol < LO   -> TQQQ (3x)   calm trend, leverage decay is tiny
    rvol > HI   -> QQQ  (1x)   stormy, de-lever
    otherwise   -> QLD  (2x)

Each ETF's OWN actual overnight return (open_{t+1}/close_t - 1) is used, so
leveraged-ETF path/decay is real, not a synthetic 2x/3x of QQQ. The signal
(close, SMA, rvol) is known at today's close -> no lookahead. Backtested over
2010-2026, the only window where all three ETFs actually trade.

Usage:
    python scripts/regime_switch.py
    python scripts/regime_switch.py --lo 0.18 --hi 0.28 --spread-bps 0.5
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd

_HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(_HERE, "..", "data")
TD = 252
SMA = 200
RVOL_WINDOW = 20


def load(sym: str) -> pd.DataFrame:
    df = pd.read_csv(os.path.join(DATA, f"{sym}_daily_yf.csv"), parse_dates=["Date"])
    df = df.set_index("Date").sort_index()
    return df[["Open", "Close"]].rename(columns={"Open": f"{sym}_o", "Close": f"{sym}_c"})


def overnight(df: pd.DataFrame, sym: str) -> pd.Series:
    return df[f"{sym}_o"].shift(-1) / df[f"{sym}_c"] - 1   # close_t -> open_{t+1}


def describe(r: pd.Series, name: str) -> dict:
    r = r.dropna()
    if len(r) == 0:
        return {}
    sh = r.mean() / r.std() * np.sqrt(TD) if r.std() > 0 else np.nan
    cur = (1 + r).cumprod()
    dd = (cur / cur.cummax() - 1).min()
    cagr = (1 + r).prod() ** (TD / len(r)) - 1
    vol = r.std() * np.sqrt(TD)
    print(f"{name:<32} CAGR {cagr:+6.1%}  Sharpe {sh:5.2f}  Vol {vol:5.1%}  MaxDD {dd:6.1%}")
    return dict(CAGR=cagr, Sharpe=sh, Vol=vol, MaxDD=dd, n=len(r))


def pick_instrument(rvol: pd.Series, lo: float, hi: float) -> pd.Series:
    """Vectorized regime choice from realized vol (default QLD, edges override)."""
    ch = pd.Series("QLD", index=rvol.index)
    ch = ch.where(rvol >= lo, "TQQQ")
    ch = ch.where(rvol <= hi, "QQQ")
    return ch


def build(lo: float, hi: float, spread_bps: float):
    qqq, qld, tqqq = load("QQQ"), load("QLD"), load("TQQQ")
    df = qqq.join(qld, how="left").join(tqqq, how="left")
    on = {s: overnight(df, s) for s in ("QQQ", "QLD", "TQQQ")}

    c = df["QQQ_c"]
    sma = c.rolling(SMA).mean()
    in_trend = c > sma                                     # decide at today's close
    rvol = c.pct_change().rolling(RVOL_WINDOW).std() * np.sqrt(TD)
    choice = pick_instrument(rvol, lo, hi)

    cost = 2 * spread_bps / 1e4                            # round-trip on invested nights
    r = pd.Series(0.0, index=df.index)
    for s in ("QQQ", "QLD", "TQQQ"):
        pick = (choice == s) & in_trend
        r = r.where(~pick, on[s] - cost)
    r = r.where(in_trend, 0.0)                             # cash off-trend

    idx = df.index[df.index >= "2010-03-01"]               # all 3 ETFs real
    return dict(ret=r, on=on, in_trend=in_trend, choice=choice, rvol=rvol,
                index=idx, cost=cost)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--lo", type=float, default=0.18, help="rvol below this -> TQQQ (3x)")
    ap.add_argument("--hi", type=float, default=0.28, help="rvol above this -> QQQ (1x)")
    ap.add_argument("--spread-bps", type=float, default=0.5, help="half-spread per side")
    args = ap.parse_args()

    b = build(args.lo, args.hi, args.spread_bps)
    idx, ret = b["index"], b["ret"]

    print("=" * 84)
    print(f"  VOL-REGIME SWITCH  (rvol<{args.lo:.0%}->TQQQ  >{args.hi:.0%}->QQQ  else QLD)  "
          f"net {args.spread_bps}bp/side")
    print(f"  Window {idx[0].date()} -> {idx[-1].date()}")
    print("=" * 84)
    describe(ret.loc[idx], "vol-switch (DEPLOYED)")

    on, in_trend, cost = b["on"], b["in_trend"], b["cost"]
    for s in ("QQQ", "QLD", "TQQQ"):
        base = (on[s] - cost).where(in_trend, 0.0)
        describe(base.loc[idx], f"  always {s}")

    print("\n--- Split-half robustness ---")
    mid = idx[len(idx) // 2]
    for lab, sl in [("H1 " + str(idx[0].date()) + "->" + str(mid.date()), idx <= mid),
                    ("H2 " + str(mid.date()) + "->" + str(idx[-1].date()), idx > mid)]:
        print(f"  [{lab}]")
        describe(ret.loc[idx[sl]], "    vol-switch")
        for s in ("QLD", "TQQQ"):
            base = (on[s] - cost).where(in_trend, 0.0)
            describe(base.loc[idx[sl]], f"      always {s}")

    print("\n--- Threshold sensitivity (Sharpe should stay flat ~1.25) ---")
    for lo, hi in [(0.15, 0.25), (0.16, 0.26), (0.18, 0.28), (0.18, 0.30), (0.20, 0.30)]:
        describe(build(lo, hi, args.spread_bps)["ret"].loc[idx], f"  lo={lo} hi={hi}")

    print("\n--- Instrument mix on trade nights ---")
    tn = in_trend.loc[idx]
    mix = b["choice"].loc[idx][tn].value_counts().to_dict()
    print(f"  in-market {tn.mean():.0%} of nights   mix={mix}   cash nights={int((~tn).sum())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
