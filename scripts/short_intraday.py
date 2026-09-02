#!/usr/bin/env python3
"""Does the mirror trade work? SHORT QQQ during the day (open -> close).

The overnight rule works because QQQ's gains happen at night. That does not
imply the day session is negative -- it only has to be *less positive*. This
script tests the short side directly, unfiltered and under every filter asked
for: only-when-flat (below the 200d), only-when-trending, high vol, below 50d.

Costs: 2 x spread per side, same as the overnight book. No overnight borrow fee
(position opens and closes the same session), but shorts are not free in real
life -- see the note printed at the end.

    uv run python scripts/short_intraday.py
    uv run python scripts/short_intraday.py --spread-bps 1
"""
import argparse
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backtest import load, load_overnight, show, stats  # noqa: E402
from strategy import RVOL_HI, TD, signals  # noqa: E402


def intraday(bars: pd.DataFrame) -> pd.Series:
    """Return from today's open to today's close."""
    return bars["Close"] / bars["Open"] - 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--spread-bps", type=float, default=0.5)
    args = ap.parse_args()
    cost = 2 * args.spread_bps / 1e4

    qqq = load("QQQ")
    day = intraday(qqq)
    close = qqq["Close"]
    sig = signals(close)
    sma50 = close.rolling(50).mean()
    on, _ = load_overnight()
    overnight_long = on["QQQ"]

    print("=" * 96)
    print("  IS THE DAY SESSION ACTUALLY NEGATIVE?  QQQ open -> close, gross")
    print("=" * 96)
    show(day, "   LONG intraday, all days")
    show(overnight_long, "   LONG overnight, all nights (for scale)")
    show(close.pct_change(), "   buy & hold")
    print("\n   intraday by era (gross, long side -- a short earns the negative of this):")
    for a, b in [("1999-01-01", "2002-12-31"), ("2003-01-01", "2009-12-31"),
                 ("2010-01-01", "2019-12-31"), ("2020-01-01", "2026-12-31")]:
        d = day.loc[a:b].dropna()
        cum = (1 + d).prod() - 1
        print(f"     {a[:4]}-{b[:4]}  mean/day {d.mean()*1e4:+6.2f}bp  "
              f"cumulative {cum:+8.1%}  win-rate {(d > 0).mean():.1%}  (n={len(d)})")

    # --- the short variants ---
    # An intraday trade opens at today's OPEN, so every mask can only use
    # information through YESTERDAY's close -> shift(1). Without this the
    # backtest peeks at the close it is trading into.
    flat = (~sig["in_trend"]).shift(1)            # what the overnight book calls cash
    hivol = (sig["rvol"] > RVOL_HI).shift(1)
    below50 = (close < sma50).shift(1)
    filters = [
        ("short EVERY day", pd.Series(True, index=day.index)),
        ("short only when FLAT (< 200d SMA)", flat),
        ("short only when TRENDING (> 200d)", sig["in_trend"].shift(1)),
        ("short only when rvol > 28%", hivol),
        ("short only when < 50d SMA", below50),
        ("short only when < 50d AND < 200d", below50 & flat),
        ("short only when FLAT and rvol > 28%", flat & hivol),
    ]

    print("\n" + "=" * 96)
    print(f"  SHORT-INTRADAY VARIANTS, net {args.spread_bps}bp/side "
          f"(flat days earn 0)")
    print("=" * 96)
    shorts = {}
    for name, mask in filters:
        r = (-day - cost).where(mask.fillna(False), 0.0)
        shorts[name] = r
        show(r, f"   {name}")
        print(f"      active {mask.fillna(False).mean():.0%} of days")

    # --- stacked on the deployed overnight book ---
    print("\n" + "=" * 96)
    print("  THE SAME VARIANTS, SPLIT BY ERA -- does any of it survive out of dot-com?")
    print("=" * 96)
    eras = [("1999-2002", "1999-01-01", "2002-12-31"),
            ("2003-2009", "2003-01-01", "2009-12-31"),
            ("2010-2026", "2010-01-01", "2026-12-31"),
            ("2020-2026", "2020-01-01", "2026-12-31")]
    print(f"   {'variant':<36}" + "".join(f"{e[0]:>22}" for e in eras))
    for name, r in shorts.items():
        cells = []
        for _, a, b in eras:
            st = stats(r.loc[a:b])
            cells.append("n/a".rjust(22) if st is None else
                         f"{st['CAGR']:+7.1%} Sh{st['Sharpe']:5.2f}".rjust(22))
        print(f"   {name:<36}" + "".join(cells))

    print("\n" + "=" * 96)
    print("  STACKED: deployed overnight long (QQQ sleeve only, for a clean read)")
    print("           + each short overlay, same account, net of cost")
    print("=" * 96)
    base = (overnight_long - cost).where(sig["in_trend"], 0.0)
    show(base, "   overnight long alone")
    for name, r in shorts.items():
        show(base + r, f"   + {name}")

    # --- is the one survivor real, or a lucky window? ---
    print("\n" + "=" * 96)
    print("  ROBUSTNESS OF THE ONE SURVIVOR: short the day while QQQ < its N-day SMA")
    print("=" * 96)
    print(f"   {'window':<12}{'2003-2009':>22}{'2010-2026':>22}{'2020-2026':>22}{'active':>9}")
    for n in (20, 30, 50, 75, 100, 150, 200):
        m = (close < close.rolling(n).mean()).shift(1)
        r = (-day - cost).where(m.fillna(False), 0.0)
        cells = []
        for a, b in [("2003-01-01", "2009-12-31"), ("2010-01-01", "2026-12-31"),
                     ("2020-01-01", "2026-12-31")]:
            st = stats(r.loc[a:b])
            cells.append(f"{st['CAGR']:+7.1%} Sh{st['Sharpe']:5.2f}".rjust(22))
        print(f"   {n:<12}" + "".join(cells) + f"{m.mean():>8.0%}")

    print("\n   cost sensitivity, 50d version, 2010-2026 (~85 round trips/yr):")
    for bp in (0.5, 1, 2, 3, 5):
        r = (-day - 2 * bp / 1e4).where(below50.fillna(False), 0.0)
        st = stats(r.loc["2010-01-01":])
        print(f"     {bp:>4}bp/side   CAGR {st['CAGR']:+7.1%}  Sharpe {st['Sharpe']:5.2f}")

    print("\n   year by year, 50d version at 0.5bp/side (short leg only):")
    yr = shorts["short only when < 50d SMA"]
    ann = yr.groupby(yr.index.year).apply(lambda x: (1 + x).prod() - 1)
    print("     " + "  ".join(f"{y}:{v:+6.1%}" for y, v in ann.items() if y >= 2003))

    print("\n" + "=" * 96)
    print("  WHAT A SHORT REALLY COSTS (not modelled above)")
    print("=" * 96)
    print("   - hard-to-borrow/locate fees and short-margin interest on the notional")
    print("   - PDT: 4+ day-trades/week needs $25k equity in a margin account")
    print("   - unlimited-loss tail: a gap-up open you shorted into keeps going")
    print("   - QQQ intraday skew: the worst days are up-days for a short")
    return 0


if __name__ == "__main__":
    sys.exit(main())
