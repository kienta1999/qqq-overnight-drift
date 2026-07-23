#!/usr/bin/env python3
"""Does the overnight-QQQ + 200d-trend vol-switch survive 2000 and 2008?

The deployed backtest only starts 2010-03 because TQQQ's inception is Feb 2010,
so it has never *actually* traded through the dot-com bust or the GFC. This
extends the test back to 1999 by SPLICING:

  * real ETF overnight returns wherever the ETF exists (QLD from 2006, TQQQ
    from 2010), and
  * a synthetic reconstruction before inception:
        overnight_Lx(t) = L * overnight_QQQ(t) - drag_L
    calibrated against the real ETFs in overlap (slope 1.97/2.95, corr
    0.989/0.997): drag = 0.6 bp/night for 2x, 1.1 bp/night for 3x.

The rule is UNCHANGED: overnight-only, only when QQQ close > 200d SMA, leverage
picked from QQQ's 20d realized vol (rvol<LO->3x, >HI->1x, else 2x). The whole
point is to see whether the 200d trend filter keeps us in cash through the
crashes. Real QQQ (from 1999) drives every signal, so the trend/vol logic uses
zero synthetic data -- synthesis only fills the leveraged *payoff* pre-inception.
"""
import os
import sys

import numpy as np
import pandas as pd

_HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(_HERE, "..", "data")
TD, SMA, RVOL_WINDOW = 252, 200, 20
LO, HI, SPREAD_BPS = 0.18, 0.28, 0.5
DRAG = {"QLD": 0.6e-4, "TQQQ": 1.1e-4}   # per-night, from calibration
LEV = {"QQQ": 1, "QLD": 2, "TQQQ": 3}


def load(s):
    d = pd.read_csv(os.path.join(DATA, f"{s}_daily_yf.csv"), parse_dates=["Date"])
    return d.set_index("Date").sort_index()


def overnight(d):
    return d["Open"].shift(-1) / d["Close"] - 1


def stats(r):
    r = r.dropna()
    if len(r) == 0:
        return None
    sh = r.mean() / r.std() * np.sqrt(TD) if r.std() > 0 else np.nan
    cur = (1 + r).cumprod()
    dd = (cur / cur.cummax() - 1).min()
    cagr = (1 + r).prod() ** (TD / len(r)) - 1
    return dict(CAGR=cagr, Sharpe=sh, Vol=r.std() * np.sqrt(TD),
                MaxDD=dd, Final=cur.iloc[-1], n=len(r))


def fmt(s):
    if s is None:
        return "no data"
    return (f"CAGR {s['CAGR']:+7.1%}  Sharpe {s['Sharpe']:5.2f}  Vol {s['Vol']:5.1%}  "
            f"MaxDD {s['MaxDD']:7.1%}  x{s['Final']:7.1f}  (n={s['n']})")


def main():
    qqq = load("QQQ")
    onq = overnight(qqq)
    real = {"QLD": overnight(load("QLD")), "TQQQ": overnight(load("TQQQ"))}

    # spliced overnight return for each leveraged sleeve: real where it exists,
    # synthetic (L*onq - drag) before inception
    on = {"QQQ": onq}
    for s in ("QLD", "TQQQ"):
        synth = LEV[s] * onq - DRAG[s]
        r = real[s].reindex(qqq.index)
        on[s] = r.where(r.notna(), synth)

    c = qqq["Close"]
    sma = c.rolling(SMA).mean()
    in_trend = c > sma
    rvol = c.pct_change().rolling(RVOL_WINDOW).std() * np.sqrt(TD)

    choice = pd.Series("QLD", index=c.index)
    choice = choice.where(rvol >= LO, "TQQQ")
    choice = choice.where(rvol <= HI, "QQQ")

    cost = 2 * SPREAD_BPS / 1e4
    r = pd.Series(0.0, index=c.index)
    for s in ("QQQ", "QLD", "TQQQ"):
        pick = (choice == s) & in_trend
        r = r.where(~pick, on[s] - cost)
    r = r.where(in_trend, 0.0)

    idx = c.index[c.index >= "2000-01-01"]           # need 200d SMA warmup first
    print("=" * 96)
    print("  FULL-HISTORY STRESS TEST  |  overnight + 200d-trend vol-switch (QQQ/QLD/TQQQ)")
    print("  QLD real from 2006, TQQQ real from 2010; synthetic (calibrated) before that.")
    print(f"  Signals use REAL QQQ only.  Window {idx[0].date()} -> {idx[-1].date()}")
    print("=" * 96)

    periods = [
        ("FULL 2000-2026", "2000-01-01", "2026-12-31"),
        ("Dot-com bust 2000-2002", "2000-01-01", "2002-12-31"),
        ("  incl. recovery 2000-2004", "2000-01-01", "2004-12-31"),
        ("GFC 2007-2009", "2007-01-01", "2009-12-31"),
        ("Real-ETF era 2010-2026 (deployed)", "2010-03-01", "2026-12-31"),
        ("2022 bear", "2022-01-01", "2022-12-31"),
    ]
    rows = []
    for name, a, b in periods:
        sl = r.loc[a:b]
        buyhold = onq.loc[a:b]                        # always-overnight-QQQ, no trend filter
        st = stats(sl)
        print(f"\n[{name}]  {a} -> {b}")
        print(f"   vol-switch (trend-filtered)   {fmt(st)}")
        print(f"   buy&hold overnight QQQ        {fmt(stats(buyhold))}")
        # how much of the period were we in cash?
        it = in_trend.loc[a:b]
        print(f"   in-market {it.mean():.0%} of nights   (cash {1-it.mean():.0%})")
        rows.append((name, st))

    # crash draw-down detail: worst equity path during dot-com
    print("\n--- Dot-com equity path (vol-switch) ---")
    dc = r.loc["2000-01-01":"2003-12-31"]
    cur = (1 + dc).cumprod()
    print(f"   peak-to-trough this window: {(cur/cur.cummax()-1).min():+.1%}   "
          f"end value: {cur.iloc[-1]:.2f}x  (started 1.00)")
    ndx_dd = (qqq['Close'].loc["2000-01-01":"2003-12-31"] /
              qqq['Close'].loc["2000-01-01":"2003-12-31"].cummax() - 1).min()
    print(f"   for reference, QQQ itself drew down {ndx_dd:+.1%} over the same window")

    print("\n### TABLE")
    print(f"{'Period':<36}{'CAGR':>9}{'Sharpe':>8}{'MaxDD':>9}{'x-growth':>10}")
    for name, s in rows:
        if s:
            print(f"{name:<36}{s['CAGR']:>+8.1%}{s['Sharpe']:>8.2f}"
                  f"{s['MaxDD']:>+8.1%}{s['Final']:>9.1f}x")
    return 0


if __name__ == "__main__":
    sys.exit(main())
