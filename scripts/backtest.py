#!/usr/bin/env python3
"""Backtest the deployed rule on QQQ's full history, 2000-2026.

Rule (see scripts/strategy.py): hold OVERNIGHT only (buy at today's close, sell
at tomorrow's open) and only while QQQ closes above its 200-day SMA; the
leverage sleeve (QQQ/QLD/TQQQ) is picked from QQQ's 20-day realized vol.

Each ETF's OWN actual overnight return is used wherever the ETF exists (QLD from
2006, TQQQ from 2010), so leveraged-ETF decay is real, not a synthetic 2x/3x.
Before inception the leveraged *payoff* is reconstructed as
    overnight_Lx = L * overnight_QQQ - drag
calibrated on the real-ETF overlap (OLS slope 1.97 / 2.95, corr 0.989 / 0.997).
Every SIGNAL uses real QQQ only, and the crashes are mostly cash nights, so the
synthetic fill barely touches the survival result.

Usage:
    uv run python scripts/backtest.py
    uv run python scripts/backtest.py --lo 0.15 --hi 0.25 --spread-bps 1
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from strategy import (LEVERAGE, RVOL_HI, RVOL_LO, TD, overnight,  # noqa: E402
                      pick_instrument, signals)

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
DRAG = {"QLD": 0.6e-4, "TQQQ": 1.1e-4}     # per-night, from the overlap calibration
DEPLOYED_START = "2010-03-01"              # first date all three ETFs really trade

PERIODS = [
    ("FULL 2000-2026", "2000-01-01", "2026-12-31"),
    ("Dot-com bust 2000-2002", "2000-01-01", "2002-12-31"),
    ("  incl. recovery 2000-2004", "2000-01-01", "2004-12-31"),
    ("GFC 2007-2009", "2007-01-01", "2009-12-31"),
    ("Real-ETF era 2010-2026 (deployed)", DEPLOYED_START, "2026-12-31"),
    ("2022 bear", "2022-01-01", "2022-12-31"),
]


def load(sym: str) -> pd.DataFrame:
    df = pd.read_csv(os.path.join(DATA, f"{sym}_daily_yf.csv"), parse_dates=["Date"])
    return df.set_index("Date").sort_index()


def load_overnight() -> dict[str, pd.Series]:
    """Overnight return per sleeve: real ETF where it exists, calibrated synthetic before."""
    qqq = load("QQQ")
    onq = overnight(qqq)
    on = {"QQQ": onq}
    for s in ("QLD", "TQQQ"):
        real = overnight(load(s)).reindex(qqq.index)
        on[s] = real.where(real.notna(), LEVERAGE[s] * onq - DRAG[s])
    return on, qqq["Close"]


def strategy_returns(on, sig, lo, hi, cost) -> pd.Series:
    """Daily return of the rule: chosen sleeve's overnight minus cost, else cash."""
    choice = sig["rvol"].apply(pick_instrument, args=(lo, hi))
    r = pd.Series(0.0, index=sig.index)
    for s in LEVERAGE:
        r = r.where(~((choice == s) & sig["in_trend"]), on[s] - cost)
    return r.where(sig["in_trend"], 0.0), choice


def stats(r: pd.Series) -> dict | None:
    r = r.dropna()
    if len(r) == 0:
        return None
    cur = (1 + r).cumprod()
    return dict(CAGR=(1 + r).prod() ** (TD / len(r)) - 1,
                Sharpe=r.mean() / r.std() * np.sqrt(TD) if r.std() > 0 else np.nan,
                Vol=r.std() * np.sqrt(TD), MaxDD=(cur / cur.cummax() - 1).min(),
                Final=cur.iloc[-1], n=len(r))


def show(r: pd.Series, label: str) -> dict | None:
    s = stats(r)
    print(f"{label:<34}" + ("no data" if s is None else
          f"CAGR {s['CAGR']:+7.1%}  Sharpe {s['Sharpe']:5.2f}  Vol {s['Vol']:5.1%}  "
          f"MaxDD {s['MaxDD']:7.1%}  x{s['Final']:7.1f}  (n={s['n']})"))
    return s


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--lo", type=float, default=RVOL_LO, help="rvol below this -> TQQQ (3x)")
    ap.add_argument("--hi", type=float, default=RVOL_HI, help="rvol above this -> QQQ (1x)")
    ap.add_argument("--spread-bps", type=float, default=0.5, help="half-spread per side")
    args = ap.parse_args()

    on, close = load_overnight()
    sig = signals(close)
    buyhold = close.pct_change()                     # QQQ buy & hold, the bar to beat
    cost = 2 * args.spread_bps / 1e4                 # round trip on invested nights
    ret, choice = strategy_returns(on, sig, args.lo, args.hi, cost)

    print("=" * 96)
    print("  OVERNIGHT QQQ + 200d TREND, vol-regime leverage switch (QQQ/QLD/TQQQ)")
    print(f"  rvol<{args.lo:.0%}->TQQQ  >{args.hi:.0%}->QQQ  else QLD   |   "
          f"net {args.spread_bps}bp/side")
    print(f"  QLD real from 2006, TQQQ from 2010; calibrated-synthetic before. "
          f"Signals: real QQQ only.")
    print("=" * 96)

    rows = []
    for name, a, b in PERIODS:
        print(f"\n[{name}]  {a} -> {b}")
        rows.append((name, show(ret.loc[a:b], "   vol-switch (deployed)")))
        show(on["QQQ"].loc[a:b], "   overnight QQQ, no trend filter")
        show(buyhold.loc[a:b], "   QQQ buy & hold")
        it = sig["in_trend"].loc[a:b]
        print(f"   in-market {it.mean():.0%} of nights   (cash {1 - it.mean():.0%})")

    dep = ret.index >= DEPLOYED_START
    print(f"\n--- Fixed-instrument comparison, {DEPLOYED_START}+ (real ETF data only) ---")
    for s in LEVERAGE:
        show((on[s] - cost).where(sig["in_trend"], 0.0).loc[dep], f"   always {s}")

    print("\n--- Split-half robustness (deployed era) ---")
    idx = ret.index[dep]
    mid = idx[len(idx) // 2]
    for label, sl in [(f"H1 {idx[0].date()}->{mid.date()}", idx <= mid),
                      (f"H2 {mid.date()}->{idx[-1].date()}", idx > mid)]:
        print(f"  [{label}]")
        show(ret.loc[idx[sl]], "     vol-switch")
        for s in ("QLD", "TQQQ"):
            show((on[s] - cost).where(sig["in_trend"], 0.0).loc[idx[sl]], f"       always {s}")

    print("\n--- Threshold sensitivity (Sharpe should stay flat, not spike at the default) ---")
    for lo, hi in [(0.15, 0.25), (0.16, 0.26), (0.18, 0.28), (0.18, 0.30), (0.20, 0.30)]:
        show(strategy_returns(on, sig, lo, hi, cost)[0].loc[dep], f"   lo={lo} hi={hi}")

    print("\n--- Instrument mix on trade nights (deployed era) ---")
    tn = sig["in_trend"].loc[dep]
    print(f"   in-market {tn.mean():.0%} of nights   "
          f"mix={choice.loc[dep][tn].value_counts().to_dict()}   "
          f"cash nights={int((~tn).sum())}")

    print("\n### SUMMARY")
    print(f"{'Period':<36}{'CAGR':>9}{'Sharpe':>8}{'MaxDD':>9}{'x-growth':>10}")
    for name, s in rows:
        if s:
            print(f"{name:<36}{s['CAGR']:>+8.1%}{s['Sharpe']:>8.2f}"
                  f"{s['MaxDD']:>+8.1%}{s['Final']:>9.1f}x")
    return 0


if __name__ == "__main__":
    sys.exit(main())
