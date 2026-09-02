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
from backtest import (load, load_overnight, show, stats,  # noqa: E402
                      strategy_returns)
from strategy import RVOL_HI, RVOL_LO, overnight, signals  # noqa: E402

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

    # --- the miners: an equity that only trades US hours, on a 24h underlying ---
    print("\n" + "=" * 100)
    print("  GOLD MINERS (GDX): the gap is bigger because the underlying moves while the")
    print("  stock cannot. GDX only trades US hours; gold trades all night.")
    print("=" * 100)
    gdx = load("GDX")
    on_gdx, day_gdx = overnight(gdx), gdx["Close"] / gdx["Open"] - 1
    sig_gdx = signals(gdx["Close"])
    A = "2006-05-22"
    show(on_gdx.loc[A:], "     GDX overnight, no filter")
    show((on_gdx - cost).where(sig_gdx["in_trend"], 0.0).loc[A:], "     GDX overnight + own 200d")
    show((on_gdx - cost).where(sig["in_trend"].reindex(gdx.index).fillna(False), 0.0).loc[A:],
         "     GDX overnight + GLD's 200d")
    show(day_gdx.loc[A:], "     GDX intraday")
    show(gdx["Close"].pct_change().loc[A:], "     GDX buy & hold")

    print("\n   is it just levered gold-gap beta?  GDX overnight vs GLD overnight:")
    pair = pd.concat([on_gdx, on_gld.reindex(gdx.index)], axis=1).dropna()
    beta = pair.cov().iloc[0, 1] / pair.iloc[:, 1].var()
    print(f"     beta {beta:.2f}   corr {pair.corr().iloc[0,1]:+.2f}   "
          f"-> GDX's night is roughly a {beta:.1f}x gold-gap position, "
          f"with no leveraged-ETF decay")
    resid = (on_gdx - beta * on_gld.reindex(gdx.index)).dropna()
    show(resid, "     residual: GDX night MINUS its gold-gap beta")
    print(f"       if this is flat, GDX's night is just levered gold; if it pays, "
          f"there is something else in it")

    print(f"\n   {'era':<14}{'GDX overnight':>24}{'+ own 200d':>24}{'GDX intraday':>24}")
    filt_gdx = (on_gdx - cost).where(sig_gdx["in_trend"], 0.0)
    for a, b in [("2006-05-22", "2011-12-31"), ("2012-01-01", "2015-12-31"),
                 ("2016-01-01", "2020-12-31"), ("2021-01-01", "2026-12-31")]:
        cells = []
        for r in (on_gdx, filt_gdx, day_gdx):
            st = stats(r.loc[a:b])
            cells.append(f"{st['CAGR']:+7.1%} Sh{st['Sharpe']:5.2f}".rjust(24))
        print(f"   {a[:4]}-{b[:4]}   " + "".join(cells))

    print("\n   GDX's day session compounds to -19%/yr. Shorting it is unconditional,")
    print("   so there is no filter to peek with -- the QQQ version of this failed:")
    for a, b in [("2006-05-22", "2011-12-31"), ("2012-01-01", "2015-12-31"),
                 ("2016-01-01", "2020-12-31"), ("2021-01-01", "2026-12-31")]:
        st = stats((-day_gdx - cost).loc[a:b])
        d = day_gdx.loc[a:b].dropna()
        print(f"     {a[:4]}-{b[:4]}   short GDX intraday  CAGR {st['CAGR']:+7.1%}  "
              f"Sharpe {st['Sharpe']:5.2f}  MaxDD {st['MaxDD']:+6.1%}   "
              f"(day leg {d.mean()*1e4:+6.1f}bp/day)")
    print("     NOTE: miners are a real borrow -- fees, recalls, and a 33% vol short.")

    # --- is it worth holding alongside the QQQ book? ---
    print("\n" + "=" * 100)
    print("  BLEND with the REAL deployed book (vol-switch QQQ/QLD/TQQQ).")
    print("  Both books trade the same hours, so capital SPLITS -- this is the only")
    print("  form in which gold helped: held simultaneously, not sequentially.")
    print("=" * 100)
    on_q, close_q = load_overnight()
    sig_q = signals(close_q)
    book, _ = strategy_returns(on_q, sig_q, RVOL_LO, RVOL_HI, cost)
    w = slice(MODERN, None)
    sleeves = {
        "GLD": (on_gld - cost).where(sig["in_trend"], 0.0),
        "UGL 2x": (on_ugl - cost).where(sig["in_trend"], 0.0),
        "GDX + own 200d": filt_gdx,
    }
    for name, sleeve in sleeves.items():
        sl = sleeve.reindex(book.index).fillna(0.0)
        c = pd.concat([book.loc[w], sl.loc[w]], axis=1).corr().iloc[0, 1]
        print(f"\n   [{name}]  correlation with the deployed book: {c:+.3f}")
        for wt in (0.0, 0.15, 0.25, 0.40):
            show(((1 - wt) * book + wt * sl).loc[w],
                 f"     {1-wt:.0%} QQQ / {wt:.0%} {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
