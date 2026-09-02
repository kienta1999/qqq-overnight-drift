#!/usr/bin/env python3
"""Gold miners overnight: hold it, or lever it?

GDX's return is almost entirely in the close->open gap (see scripts/gold.py).
This asks the next question: buy & hold, overnight-only, and if overnight, at
1x (GDX), 2x (NUGT) or 3x (GDXU)?

The honest comparison is EQUAL EXPOSURE, not equal weight. 12.5% in a 2x sleeve
carries the same market exposure as 25% in a 1x sleeve, so the only thing
leverage can add is decay -- and the only way to see it is to hold exposure
fixed and vary the wrapper.

Data hazard: NUGT and JNUG were 3x until 2020, then 2x. The script detects the
change from realized beta instead of trusting a remembered date.

    uv run python scripts/miners.py
    uv run python scripts/miners.py --spread-bps 2
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backtest import (load, load_overnight, show, stats,  # noqa: E402
                      strategy_returns)
from strategy import RVOL_HI, RVOL_LO, overnight, signals  # noqa: E402


def beta(y: pd.Series, x: pd.Series) -> float:
    p = pd.concat([y, x], axis=1, sort=True).dropna()
    return p.cov().iloc[0, 1] / p.iloc[:, 1].var()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--spread-bps", type=float, default=1.0,
                    help="GDX is a penny spread on a ~$95 ETF; levered sleeves are wider")
    args = ap.parse_args()
    c = 2 * args.spread_bps / 1e4

    bars = {s: load(s) for s in ("GDX", "NUGT", "GDXU", "GDXJ")}
    on = {s: overnight(b) for s, b in bars.items()}
    bh = {s: b["Close"].pct_change() for s, b in bars.items()}
    gdx = on["GDX"]

    print("=" * 100)
    print("  1. DATA HYGIENE: what leverage was each sleeve actually running?")
    print("     (realized beta of its overnight return vs GDX's, per year)")
    print("=" * 100)
    print(f"   {'year':<8}{'NUGT':>10}{'GDXU':>10}{'GDXJ':>10}")
    for y in range(2011, 2027):
        w = slice(f"{y}-01-01", f"{y}-12-31")
        row = []
        for s in ("NUGT", "GDXU", "GDXJ"):
            p = pd.concat([on[s].loc[w], gdx.loc[w]], axis=1, sort=True).dropna()
            row.append(f"{beta(on[s].loc[w], gdx.loc[w]):>10.2f}" if len(p) > 50 else f"{'-':>10}")
        print(f"   {y:<8}" + "".join(row))

    print("\n" + "=" * 100)
    print(f"  2. HODL vs OVERNIGHT-ONLY, net {args.spread_bps}bp/side")
    print("=" * 100)
    for s in ("GDX", "GDXJ", "NUGT", "GDXU"):
        start = on[s].dropna().index[0].date()
        print(f"\n   [{s}]  from {start}")
        show(bh[s], "     buy & hold (24h)")
        show(on[s] - c, "     overnight only")
        show((bars[s]["Close"] / bars[s]["Open"] - 1), "     intraday only")

    print("\n" + "=" * 100)
    print("  3. IS THE LEVERAGED WRAPPER WORTH IT? levered sleeve vs a synthetic")
    print("     L x GDX overnight, on the SAME dates -- the gap is the ETF's decay")
    print("=" * 100)
    for s, L in (("NUGT", 2), ("GDXU", 3)):
        # compare only where the sleeve actually ran that leverage
        w = slice("2021-01-01", None)
        real = (on[s] - c).loc[w].dropna()
        b = beta(on[s].loc[w], gdx.loc[w])
        synth = (b * gdx - c).reindex(real.index)
        drag = (real - synth).mean()
        print(f"\n   [{s}] 2021+  realized beta {b:.2f}")
        show(real, f"     real {s} overnight")
        show(synth, f"     synthetic {b:.2f}x GDX overnight")
        print(f"       decay: {drag * 1e4:+.2f}bp/night = {drag * 252 * 100:+.1f}%/yr "
              f"of pure wrapper cost")

    print("\n" + "=" * 100)
    print("  4. THE REAL TEST: EQUAL EXPOSURE in the blend with the deployed QQQ book")
    print("     25% of a 1x sleeve == 12.5% of 2x == 8.3% of 3x. Same bet, three wrappers.")
    print("=" * 100)
    on_q, close_q = load_overnight()
    sig_q = signals(close_q)
    book, _ = strategy_returns(on_q, sig_q, RVOL_LO, RVOL_HI, 1e-5)
    for a in ("2013-01-01", "2021-01-01"):
        print(f"\n   [{a}+]   (GDXU exists only from 2021)")
        show(book.loc[a:], "     100% QQQ book, no miners")
        for target in (0.25, 0.50):
            print(f"     --- {target:.0%} GDX-equivalent exposure ---")
            for s, L in (("GDX", 1), ("NUGT", 2), ("GDXU", 3)):
                wt = target / L
                sl = (on[s] - c).reindex(book.index).fillna(0.0)
                if sl.loc[a:].eq(0).all():
                    continue
                show(((1 - wt) * book + wt * sl).loc[a:],
                     f"       {1-wt:.1%} QQQ / {wt:.1%} {s} ({L}x)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
