#!/usr/bin/env python3
"""One table: overnight-only vs buy & hold, at 1x / 2x / 3x, for SPY, QQQ, GDX.

Every row is the SAME window and the SAME cost assumption, so the numbers are
comparable to each other -- which the repo's headline figures are not, since
they use different spreads and different start dates.

Leveraged sleeves that did not exist at the start (UPRO 2009, TQQQ 2010) are
filled before inception with `slope * 1x_overnight - drag`, both calibrated by
OLS on the real overlap. The calibration is printed so you can see how good the
fill is; a corr below ~0.98 would mean the synthetic is not trustworthy.

    uv run python scripts/compare.py
    uv run python scripts/compare.py --spread-bps 0.5
"""
import argparse
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backtest import load, show, stats  # noqa: E402
from strategy import overnight, signals  # noqa: E402

START, END = "2006-05-23", "2026-08-31"
REAL = "2010-02-12"          # first date every sleeve here really trades
FAMILY = {"SPY": ("SPY", "SSO", "UPRO"), "QQQ": ("QQQ", "QLD", "TQQQ")}


def calibrated(base: pd.Series, sym: str, L: int, index) -> tuple[pd.Series, str]:
    """Real overnight return where the ETF exists, calibrated synthetic before."""
    real = overnight(load(sym)).reindex(index)
    both = pd.concat([real, base], axis=1).dropna()
    slope = both.cov().iloc[0, 1] / both.iloc[:, 1].var()
    drag = (both.iloc[:, 0] - slope * both.iloc[:, 1]).mean()
    corr = both.corr().iloc[0, 1]
    note = (f"{sym:<5} {L}x  real from {real.dropna().index[0].date()}  "
            f"slope {slope:.2f}  drag {-drag*1e4:5.2f}bp/night  corr {corr:.3f}")
    return real.where(real.notna(), slope * base + drag), note


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--spread-bps", type=float, default=1.0)
    args = ap.parse_args()
    c = 2 * args.spread_bps / 1e4

    idx = load("SPY").loc[START:END].index
    rows, notes = {}, []
    for base_sym, sleeves in FAMILY.items():
        b = load(base_sym).reindex(idx)
        base_on = overnight(b)
        rows[f"{base_sym} buy & hold"] = (b["Close"].pct_change(), None)
        for L, sym in enumerate(sleeves, start=1):
            if sym == base_sym:
                on, real_from = base_on, idx[0]
            else:
                on, note = calibrated(base_on, sym, L, idx)
                notes.append(note)
                real_from = overnight(load(sym)).dropna().index[0]
            rows[f"{base_sym} overnight {L}x ({sym})"] = (on - c, real_from)
    gdx = load("GDX").reindex(idx)
    rows["GDX overnight 1x"] = (overnight(gdx) - c, idx[0])
    rows["GDX buy & hold"] = (gdx["Close"].pct_change(), None)

    print("Synthetic fill calibration (pre-inception only):")
    for n in notes:
        print("   " + n)

    for label, lo in ((f"FULL {START} -> {END}  (synthetic fill before inception)", START),
                      (f"REAL-ETF ONLY {REAL} -> {END}  (no synthetic anywhere)", REAL)):
        print("\n" + "=" * 92)
        print(f"  {label}   |   net {args.spread_bps}bp/side on every traded night")
        print("=" * 92)
        print(f"  {'strategy':<28}{'CAGR':>9}{'Sharpe':>8}{'Vol':>8}{'MaxDD':>9}"
              f"{'$5,000 becomes':>18}")
        for name, (r, _) in rows.items():
            s = stats(r.loc[lo:END])
            print(f"  {name:<28}{s['CAGR']:>+8.1%}{s['Sharpe']:>8.2f}{s['Vol']:>8.1%}"
                  f"{s['MaxDD']:>+8.1%}{5000 * s['Final']:>17,.0f}")

    print("\n" + "=" * 92)
    print("  AND WITH THE 200d TREND FILTER -- 'our strategy' at each fixed leverage")
    print("=" * 92)
    print(f"  {'strategy':<28}{'CAGR':>9}{'Sharpe':>8}{'Vol':>8}{'MaxDD':>9}"
          f"{'$5,000 becomes':>18}")
    for base_sym, sleeves in FAMILY.items():
        sig = signals(load(base_sym).reindex(idx)["Close"])
        for L, sym in enumerate(sleeves, start=1):
            r, _ = rows[f"{base_sym} overnight {L}x ({sym})"]
            s = stats(r.where(sig["in_trend"], 0.0).loc[START:END])
            print(f"  {base_sym + f' + 200d filter {L}x':<28}{s['CAGR']:>+8.1%}"
                  f"{s['Sharpe']:>8.2f}{s['Vol']:>8.1%}{s['MaxDD']:>+8.1%}"
                  f"{5000 * s['Final']:>17,.0f}")
    sig = signals(load("GDX").reindex(idx)["Close"])
    s = stats(rows["GDX overnight 1x"][0].where(sig["in_trend"], 0.0).loc[START:END])
    print(f"  {'GDX + 200d filter 1x':<28}{s['CAGR']:>+8.1%}{s['Sharpe']:>8.2f}"
          f"{s['Vol']:>8.1%}{s['MaxDD']:>+8.1%}{5000 * s['Final']:>17,.0f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
