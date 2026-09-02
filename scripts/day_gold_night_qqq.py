#!/usr/bin/env python3
"""Fill the idle half of the day with gold.

The deployed book is invested close -> open and sits in cash all session; on
top of that it sits in cash *entirely* on ~26% of nights (below the 200d). Two
idle pockets. This tests filling them with gold:

  DAY leg    buy GLD at the open, sell at the close, then swap into the QQQ
             sleeve in the same closing auction.
  NIGHT leg  on nights the QQQ book is flat, hold gold overnight instead of cash
             (gold's return is *in* the gap, so this is the pocket that should
             pay -- see scripts/gold.py).

Costs are charged per leg: each leg is a round trip, so a day where both legs
fire pays 4 sides, not 2. The night leg is free of extra sides when it simply
replaces a cash night.

    uv run python scripts/day_gold_night_qqq.py
    uv run python scripts/day_gold_night_qqq.py --spread-bps 1
"""
import argparse
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backtest import (DEPLOYED_START, load, load_overnight,  # noqa: E402
                      show, stats, strategy_returns)
from strategy import RVOL_HI, RVOL_LO, overnight, signals  # noqa: E402

START = "2004-11-18"       # GLD inception


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--lo", type=float, default=RVOL_LO)
    ap.add_argument("--hi", type=float, default=RVOL_HI)
    ap.add_argument("--spread-bps", type=float, default=0.5)
    args = ap.parse_args()
    cost = 2 * args.spread_bps / 1e4                  # one round trip = one leg

    on_q, close_q = load_overnight()
    sig = signals(close_q)
    night, _ = strategy_returns(on_q, sig, args.lo, args.hi, cost)   # the deployed book
    idx = close_q.index

    gld, ugl = load("GLD"), load("UGL")
    gld_day = (gld["Close"] / gld["Open"] - 1).reindex(idx)
    ugl_day = (ugl["Close"] / ugl["Open"] - 1).reindex(idx)
    gld_night = overnight(gld).reindex(idx)
    flat = ~sig["in_trend"]                            # QQQ book is in cash tonight

    # A day leg opens at today's OPEN -> its filter stops at yesterday's close.
    gld_trend = (gld["Close"] > gld["Close"].rolling(200).mean()).reindex(idx).shift(1).fillna(False)

    legs = {
        "day: GLD every day": (gld_day - cost).fillna(0.0),
        "day: UGL (2x) every day": (ugl_day - cost).fillna(0.0),
        "day: GLD only when GLD > its 200d": (gld_day - cost).where(gld_trend, 0.0).fillna(0.0),
        "day: GLD only on QQQ cash days": (gld_day - cost).where(flat.shift(1).fillna(False), 0.0).fillna(0.0),
        "night: GLD on QQQ cash nights": (gld_night - cost).where(flat, 0.0).fillna(0.0),
    }

    print("=" * 100)
    print(f"  EACH LEG ALONE, {START}+, net {args.spread_bps}bp/side (one round trip per leg)")
    print("=" * 100)
    w = slice(START, None)
    show(night.loc[w], "   the deployed QQQ night book")
    for name, r in legs.items():
        show(r.loc[w], f"   {name}")
        active = (r != 0).loc[w].mean()
        print(f"      active {active:.0%} of days")

    print("\n" + "=" * 100)
    print("  STACKED ON THE DEPLOYED BOOK (legs do not overlap in time, so they add)")
    print("=" * 100)
    for label, a in [(f"since GLD inception {START}", START),
                     (f"real-ETF era {DEPLOYED_START}", DEPLOYED_START)]:
        print(f"\n  [{label}]")
        base = night.loc[a:]
        show(base, "     QQQ night book alone (baseline)")
        for name, r in legs.items():
            show(base + r.loc[a:], f"     + {name}")
        best = legs["day: GLD every day"] + legs["night: GLD on QQQ cash nights"]
        show(base + best.loc[a:], "     + BOTH gold legs (fully invested 24/5)")

    print("\n" + "=" * 100)
    print("  THE ONE LEG THAT PAYS: gold overnight on QQQ cash nights, by era")
    print("  (cash nights are bear markets -- exactly when gold is bid, so there is a story)")
    print("=" * 100)
    ugl_night = overnight(ugl).reindex(idx)
    variants = {
        "cash night -> GLD": (gld_night - cost).where(flat, 0.0).fillna(0.0),
        "cash night -> UGL (2x)": (ugl_night - cost).where(flat, 0.0).fillna(0.0),
    }
    print(f"   {'era':<14}{'cash nights':>13}{'QQQ book alone':>26}"
          f"{'+ GLD':>26}{'+ UGL 2x':>26}")
    for a, b in [("2004-11-18", "2009-12-31"), ("2010-01-01", "2015-12-31"),
                 ("2016-01-01", "2020-12-31"), ("2021-01-01", "2026-12-31")]:
        cells = []
        for r in (night, night + variants["cash night -> GLD"],
                  night + variants["cash night -> UGL (2x)"]):
            st = stats(r.loc[a:b])
            cells.append(f"{st['CAGR']:+7.1%} Sh{st['Sharpe']:5.2f} DD{st['MaxDD']:+6.1%}".rjust(26))
        n_cash = int(flat.loc[a:b].sum())
        print(f"   {a[:4]}-{b[:4]}   {n_cash:>10}" + "".join(cells))

    allg = gld_night.loc[START:].dropna()
    cashg = gld_night.where(flat).loc[START:].dropna()
    print(f"\n   is a QQQ-cash night a BETTER gold night?  "
          f"all nights {allg.mean()*1e4:+5.2f}bp vs cash nights {cashg.mean()*1e4:+5.2f}bp "
          f"-- {'yes' if cashg.mean() > allg.mean() else 'NO, there is no crisis premium'}")

    print("\n   the leg on its own, only counting the nights it actually trades:")
    for name, r in variants.items():
        traded = r[flat.fillna(False) & r.ne(0)]
        show(r.loc[START:], f"     {name}")
        print(f"       mean {traded.mean()*1e4:+6.2f}bp/night over {len(traded)} nights, "
              f"win-rate {(traded > 0).mean():.1%}")

    print("\n" + "=" * 100)
    print("  IS THE GOLD DAY SESSION WORTH THE SPREAD? (gross, before any cost)")
    print("=" * 100)
    for a, b in [("2004-11-18", "2009-12-31"), ("2010-01-01", "2015-12-31"),
                 ("2016-01-01", "2020-12-31"), ("2021-01-01", "2026-12-31")]:
        d = gld_day.loc[a:b].dropna()
        n = gld_night.loc[a:b].dropna()
        print(f"   {a[:4]}-{b[:4]}   day {d.mean()*1e4:+6.2f}bp/day   "
              f"night {n.mean()*1e4:+6.2f}bp/night   "
              f"day needs {2*args.spread_bps:.1f}bp to break even")

    print("\n" + "=" * 100)
    print("  WHAT THIS COSTS IN THE REAL WORLD")
    print("=" * 100)
    print("   - the day leg is a DAY TRADE: 4+/week needs $25k equity (PDT rule)")
    print("   - the closing auction now does two orders (sell GLD MOC, buy sleeve MOC)")
    print("   - fully invested 24/5 means gold and QQQ drawdowns can land back to back")
    return 0


if __name__ == "__main__":
    sys.exit(main())
