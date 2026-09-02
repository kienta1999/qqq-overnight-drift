#!/usr/bin/env python3
"""Does the overnight-drift rule work on gold?

Same question as QQQ, asked of GLD: is gold's return concentrated in the
close -> open gap, and does the 200d-SMA + overnight-only rule make comparable
money? Gold has a structural reason to differ -- gold futures trade nearly 24h,
so GLD's gap absorbs the whole Asia/London session, not just news flow.

Sleeves: GLD (1x, 2004-11+), UGL (2x, 2008-12+). IAU is a cross-check that the
gap is real and not one fund's NAV-print quirk. GDX (miners) is the contrast:
an equity that only trades US hours.

    uv run python scripts/gold.py
    uv run python scripts/gold.py --spread-bps 1
"""
import argparse
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backtest import load, load_overnight, show, stats  # noqa: E402
from strategy import overnight, signals  # noqa: E402

COMMON = "2004-11-18"      # GLD inception, the longest window gold gives us
MODERN = "2010-01-01"


def split(sym: str) -> tuple[pd.Series, pd.Series, pd.Series]:
    """(overnight, intraday, buy&hold) daily returns for one ticker."""
    b = load(sym)
    return overnight(b), b["Close"] / b["Open"] - 1, b["Close"].pct_change()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--spread-bps", type=float, default=0.5)
    args = ap.parse_args()
    cost = 2 * args.spread_bps / 1e4

    print("=" * 100)
    print("  WHERE DOES THE RETURN LIVE?  overnight (close->open) vs intraday (open->close)")
    print("=" * 100)
    for sym in ("GLD", "IAU", "UGL", "GDX", "QQQ"):
        on, day, bh = split(sym)
        w = slice(COMMON, None)
        print(f"\n  [{sym}]  from {max(pd.Timestamp(COMMON), on.dropna().index[0]).date()}")
        show(on.loc[w], "     overnight only")
        show(day.loc[w], "     intraday only")
        show(bh.loc[w], "     buy & hold")

    # --- the deployed rule, transplanted onto gold ---
    gld = load("GLD")
    sig = signals(gld["Close"])                    # GLD's own 200d SMA + rvol
    on_gld = overnight(gld)
    on_ugl = overnight(load("UGL")).reindex(gld.index)

    print("\n" + "=" * 100)
    print(f"  THE DEPLOYED RULE ON GOLD: hold overnight only while GLD > its own 200d SMA")
    print(f"  net {args.spread_bps}bp/side; UGL rows start 2008-12 (no synthetic fill)")
    print("=" * 100)
    for label, a in [("since GLD inception", COMMON), ("modern era", MODERN)]:
        print(f"\n  [{label}]  {a} ->")
        for name, r in [("GLD overnight + 200d filter", (on_gld - cost).where(sig["in_trend"], 0.0)),
                        ("UGL overnight + 200d filter", (on_ugl - cost).where(sig["in_trend"], 0.0)),
                        ("GLD overnight, no filter", on_gld - cost),
                        ("GLD intraday + 200d filter",
                         ((gld["Close"] / gld["Open"] - 1) - cost).where(
                             sig["in_trend"].shift(1).fillna(False), 0.0)),
                        ("GLD buy & hold", gld["Close"].pct_change())]:
            show(r.loc[a:], f"     {name}")
        it = sig["in_trend"].loc[a:]
        print(f"     in-market {it.mean():.0%} of nights")

    print("\n" + "=" * 100)
    print("  IS GOLD'S GAP STABLE, AND DOES THE TREND FILTER EARN ITS KEEP?")
    print("=" * 100)
    print(f"   {'era':<14}{'GLD overnight':>24}{'GLD intraday':>24}{'+200d filter':>24}")
    filt = (on_gld - cost).where(sig["in_trend"], 0.0)
    for a, b in [("2004-11-18", "2009-12-31"), ("2010-01-01", "2015-12-31"),
                 ("2016-01-01", "2020-12-31"), ("2021-01-01", "2026-12-31")]:
        cells = []
        for r in (on_gld, gld["Close"] / gld["Open"] - 1, filt):
            st = stats(r.loc[a:b])
            cells.append(f"{st['CAGR']:+7.1%} Sh{st['Sharpe']:5.2f}".rjust(24))
        print(f"   {a[:4]}-{b[:4]}   " + "".join(cells))

    print("\n   trend-filter window sweep on the gold book (since inception):")
    for n in (0, 50, 100, 150, 200, 250):
        m = (gld["Close"] > gld["Close"].rolling(n).mean()) if n else pd.Series(True, index=gld.index)
        show((on_gld - cost).where(m.fillna(False), 0.0), f"     {n or 'no'}d filter")

    # --- is it worth holding alongside the QQQ book? ---
    print("\n" + "=" * 100)
    print("  BLEND: both books trade the same hours, so capital has to be SPLIT, not stacked")
    print("=" * 100)
    on_q, close_q = load_overnight()
    sig_q = signals(close_q)
    qqq_book = (on_q["QQQ"] - cost).where(sig_q["in_trend"], 0.0).reindex(gld.index).fillna(0.0)
    gold_book = (on_gld - cost).where(sig["in_trend"], 0.0).fillna(0.0)
    w = slice(MODERN, None)
    corr = pd.concat([qqq_book.loc[w], gold_book.loc[w]], axis=1).corr().iloc[0, 1]
    print(f"\n  correlation of the two nightly return streams, {MODERN}+: {corr:+.3f}")
    show(qqq_book.loc[w], "     100% QQQ book (1x sleeve)")
    show(gold_book.loc[w], "     100% gold book")
    for wt in (0.25, 0.5):
        show((1 - wt) * qqq_book.loc[w] + wt * gold_book.loc[w],
             f"     {1-wt:.0%} QQQ / {wt:.0%} gold")
    return 0


if __name__ == "__main__":
    sys.exit(main())
