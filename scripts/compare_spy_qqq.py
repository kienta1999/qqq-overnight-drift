#!/usr/bin/env python3
"""Compare the deployed overnight + 200d-trend vol-regime switch on two ETF
families over an IDENTICAL window:

    QQQ family:  QQQ (1x)  / QLD (2x)  / TQQQ (3x)   <- deployed
    SPY family:  SPY (1x)  / SSO (2x)  / UPRO (3x)   <- candidate

Rule is unchanged for both: hold OVERNIGHT only (buy at close, sell next open),
only when the 1x proxy's close is above its 200-day SMA (cash otherwise), and
pick the leverage from the 1x proxy's 20-day realized vol:
    rvol < LO -> 3x    rvol > HI -> 1x    else -> 2x
Each ETF uses its OWN overnight return so leverage decay is real. Window is the
overlap of all six ETFs (UPRO inception is the binding constraint, ~2010).
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

FAMILIES = {
    "QQQ": ("QQQ", "QLD", "TQQQ"),   # 1x, 2x, 3x
    "SPY": ("SPY", "SSO", "UPRO"),
}


def load(sym: str) -> pd.DataFrame:
    df = pd.read_csv(os.path.join(DATA, f"{sym}_daily_yf.csv"), parse_dates=["Date"])
    df = df.set_index("Date").sort_index()
    return df[["Open", "Close"]].rename(columns={"Open": f"{sym}_o", "Close": f"{sym}_c"})


def overnight(df: pd.DataFrame, sym: str) -> pd.Series:
    return df[f"{sym}_o"].shift(-1) / df[f"{sym}_c"] - 1   # close_t -> open_{t+1}


def stats(r: pd.Series) -> dict:
    r = r.dropna()
    if len(r) == 0:
        return {}
    sh = r.mean() / r.std() * np.sqrt(TD) if r.std() > 0 else np.nan
    cur = (1 + r).cumprod()
    dd = (cur / cur.cummax() - 1).min()
    cagr = (1 + r).prod() ** (TD / len(r)) - 1
    vol = r.std() * np.sqrt(TD)
    return dict(CAGR=cagr, Sharpe=sh, Vol=vol, MaxDD=dd, Final=cur.iloc[-1], n=len(r))


def pick_instrument(rvol: pd.Series, lo: float, hi: float, names) -> pd.Series:
    x3, x2, x1 = names[2], names[1], names[0]
    ch = pd.Series(x2, index=rvol.index)
    ch = ch.where(rvol >= lo, x3)
    ch = ch.where(rvol <= hi, x1)
    return ch


def build(family: str, lo: float, hi: float, spread_bps: float) -> dict:
    names = FAMILIES[family]                       # (1x, 2x, 3x)
    frames = {s: load(s) for s in names}
    df = frames[names[0]]
    for s in names[1:]:
        df = df.join(frames[s], how="left")
    on = {s: overnight(df, s) for s in names}

    c = df[f"{names[0]}_c"]                         # 1x proxy drives the signal
    sma = c.rolling(SMA).mean()
    in_trend = c > sma
    rvol = c.pct_change().rolling(RVOL_WINDOW).std() * np.sqrt(TD)
    choice = pick_instrument(rvol, lo, hi, names)

    cost = 2 * spread_bps / 1e4
    r = pd.Series(0.0, index=df.index)
    for s in names:
        pick = (choice == s) & in_trend
        r = r.where(~pick, on[s] - cost)
    r = r.where(in_trend, 0.0)
    return dict(names=names, ret=r, on=on, in_trend=in_trend, choice=choice,
                rvol=rvol, cost=cost, index=df.index)


def common_window(a: dict, b: dict, start: str) -> pd.DatetimeIndex:
    # first date each family's 3x ETF actually has an overnight return
    def first_valid(d):
        x3 = d["names"][2]
        return d["on"][x3].dropna().index.min()
    lo = max(first_valid(a), first_valid(b), pd.Timestamp(start))
    idx = a["index"].intersection(b["index"])
    return idx[idx >= lo]


def fmt(s: dict) -> str:
    return (f"CAGR {s['CAGR']:+6.1%}  Sharpe {s['Sharpe']:5.2f}  "
            f"Vol {s['Vol']:5.1%}  MaxDD {s['MaxDD']:6.1%}  x{s['Final']:6.1f}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--lo", type=float, default=0.18)
    ap.add_argument("--hi", type=float, default=0.28)
    ap.add_argument("--spread-bps", type=float, default=0.5)
    ap.add_argument("--start", default="2010-03-01")
    args = ap.parse_args()

    qqq = build("QQQ", args.lo, args.hi, args.spread_bps)
    spy = build("SPY", args.lo, args.hi, args.spread_bps)
    idx = common_window(qqq, spy, args.start)

    print("=" * 92)
    print(f"  SPY family vs QQQ family  |  vol-switch  rvol<{args.lo:.0%}->3x  "
          f">{args.hi:.0%}->1x  else 2x  |  net {args.spread_bps}bp/side")
    print(f"  Identical window {idx[0].date()} -> {idx[-1].date()}  ({len(idx)} sessions)")
    print("=" * 92)

    rows = []
    for fam, b in [("QQQ", qqq), ("SPY", spy)]:
        sw = stats(b["ret"].loc[idx])
        print(f"{fam}  vol-switch (1/2/3x)   {fmt(sw)}")
        rows.append((f"{fam} vol-switch", sw))
        for i, lev in zip(b["names"], ("1x", "2x", "3x")):
            base = (b["on"][i] - b["cost"]).where(b["in_trend"], 0.0)
            st = stats(base.loc[idx])
            print(f"   always {i:<5}({lev})       {fmt(st)}")
            rows.append((f"{fam} always {i} ({lev})", st))
        print()

    print("--- Split-half robustness (vol-switch) ---")
    mid = idx[len(idx) // 2]
    for fam, b in [("QQQ", qqq), ("SPY", spy)]:
        for lab, sl in [("H1", idx <= mid), ("H2", idx > mid)]:
            st = stats(b["ret"].loc[idx[sl]])
            print(f"  {fam} {lab}  {fmt(st)}")
    print()

    print("--- Instrument mix on trade nights ---")
    for fam, b in [("QQQ", qqq), ("SPY", spy)]:
        tn = b["in_trend"].loc[idx]
        mix = b["choice"].loc[idx][tn].value_counts().to_dict()
        print(f"  {fam}: in-market {tn.mean():.0%} of nights  mix={mix}")

    # machine-readable summary for the writeup
    print("\n### TABLE")
    print(f"{'Strategy':<26}{'CAGR':>8}{'Sharpe':>8}{'Vol':>8}{'MaxDD':>9}{'x-growth':>10}")
    for name, s in rows:
        print(f"{name:<26}{s['CAGR']:>+7.1%}{s['Sharpe']:>8.2f}{s['Vol']:>7.1%}"
              f"{s['MaxDD']:>+8.1%}{s['Final']:>9.1f}x")
    return 0


if __name__ == "__main__":
    sys.exit(main())
