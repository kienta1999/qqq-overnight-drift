#!/usr/bin/env python3
"""Build a daily OHLC panel from the sibling repo's 5-minute bar cache.

We do NOT re-download anything: ranker-5d-sp500 already backfilled 10y of
split-adjusted SIP 5-minute bars for ~721 point-in-time S&P members. This script
collapses each ticker's RTH 5-min bars into one row per session:

    ticker, date, open, high, low, close, volume

where `open`  = Open of the first RTH bar (~09:30 ET)
      `close` = Close of the last  RTH bar (~15:55 ET bar, i.e. the 16:00 close)

That daily open/close split is exactly what the overnight / same-day rules need
(overnight return = next_open/close - 1; intraday return = close/open - 1).

Output: data/daily.parquet (long format), plus data/spy_daily.parquet.

Usage:
    python scripts/daily_panel.py            # build/refresh the panel
    python scripts/daily_panel.py --limit 50 # quick smoke on 50 tickers
"""

import argparse
import os
import sys
import time
from glob import glob

import pandas as pd

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
# The 5-minute cache lives in the sibling repo; we read it, never write to it.
RAW_DIR = os.path.join(_ROOT, "..", "ranker-5d-sp500", "data", "raw")
DATA_DIR = os.path.join(_ROOT, "data")
OUT_PATH = os.path.join(DATA_DIR, "daily.parquet")

ET = "America/New_York"


def bars_to_daily(df: pd.DataFrame) -> pd.DataFrame:
    """Collapse tz-aware UTC 5-min RTH bars into daily OHLCV in ET session dates.

    First bar's Open and last bar's Close per ET calendar day. The cache is
    already RTH-only, so grouping by ET date yields true session open/close.
    """
    if df.empty:
        return pd.DataFrame()
    idx_et = df.index.tz_convert(ET)
    day = idx_et.normalize().tz_localize(None)
    g = df.groupby(day)
    daily = pd.DataFrame({
        "open": g["Open"].first(),
        "high": g["High"].max(),
        "low": g["Low"].min(),
        "close": g["Close"].last(),
        "volume": g["Volume"].sum(),
        "n_bars": g["Close"].count(),
    })
    daily.index.name = "date"
    # Drop stub sessions (half-days / first-listing days with a handful of bars)
    # only when they are extreme; keep >= 10 bars (a real session is ~78).
    daily = daily[daily["n_bars"] >= 10]
    return daily


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--limit", type=int, default=None, help="Only first N tickers.")
    args = ap.parse_args()

    raw = os.path.abspath(RAW_DIR)
    if not os.path.isdir(raw):
        sys.exit(f"5-min cache not found at {raw} — is ranker-5d-sp500 present?")

    files = sorted(glob(os.path.join(raw, "*.parquet")))
    if args.limit:
        files = files[: args.limit]
    print(f"Building daily panel from {len(files)} tickers in {raw}")

    frames = []
    t0 = time.time()
    for i, path in enumerate(files, 1):
        ticker = os.path.splitext(os.path.basename(path))[0]
        try:
            bars = pd.read_parquet(path)
        except Exception as e:
            print(f"  [{ticker}] read failed: {e}")
            continue
        daily = bars_to_daily(bars)
        if daily.empty:
            continue
        daily = daily.reset_index()
        daily.insert(0, "ticker", ticker)
        frames.append(daily)
        if i % 100 == 0:
            print(f"  {i}/{len(files)} ... {time.time() - t0:.0f}s", flush=True)

    panel = pd.concat(frames, ignore_index=True)
    panel = panel.sort_values(["ticker", "date"]).reset_index(drop=True)
    os.makedirs(DATA_DIR, exist_ok=True)
    panel.to_parquet(OUT_PATH, index=False)

    # SPY benchmark, same construction, saved separately for convenience.
    spy = panel[panel["ticker"] == "SPY"]
    if not spy.empty:
        spy.to_parquet(os.path.join(DATA_DIR, "spy_daily.parquet"), index=False)

    print(f"\nWrote {OUT_PATH}")
    print(f"  {panel['ticker'].nunique()} tickers, {len(panel):,} ticker-days")
    print(f"  dates {panel['date'].min().date()} -> {panel['date'].max().date()}")
    print(f"  built in {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
