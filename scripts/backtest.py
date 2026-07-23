#!/usr/bin/env python3
"""Honest intraday/overnight rule backtester for the S&P 500 universe.

Reads data/daily.parquet (built by daily_panel.py from 5-min bars: true session
open/close). Tests a family of TRANSPARENT if/else rules and — crucially — the
same baselines that saved the sibling project from fooling itself:

    * SPY buy-and-hold          (is any of this better than doing nothing?)
    * random-K dartboard        (is the edge real or just survivorship/universe?)

Every strategy is simulated net of costs (spread + slippage + commission, in bps
per side, charged on BOTH the entry and the exit — daily-turnover strategies pay
this every day, which is the whole point of the honesty). Nothing here is a
recommendation; it is a measurement.

Rule families (all equal-weight, top/bottom-K by a signal computed only from data
available at the decision bar — no lookahead):

  OVERNIGHT  (enter at close_t, exit at next open — NOT a PDT day-trade):
    overnight_all   buy every liquid name        (the overnight-drift anomaly, broad)
    mr_overnight    buy K most-oversold (RSI2)    (mean reversion, bounce overnight)
    mom_overnight   buy K strongest 5-day movers  (momentum contrast)
    random_overnight  buy K random names          (dartboard)
  ONE-DAY  (enter close_t, exit next close):
    mr_1day         buy K most-oversold, hold 1 full day
  SAME-DAY  (enter open_t, exit close_t — hits PDT 3/wk limit under $25k):
    gap_fade        buy K biggest gap-DOWNS at open, sell at close (reversion)
    gap_mom         buy K biggest gap-UPS at open,   sell at close (continuation)

Usage:
    python scripts/backtest.py                 # full run, default K=10, 5bps/side
    python scripts/backtest.py --k 5 --cost-bps 5
    python scripts/backtest.py --start 2016 --min-dollar-vol 20e6
"""

import argparse
import os
import sys

import numpy as np
import pandas as pd

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
DATA = os.path.join(_ROOT, "data", "daily.parquet")
SPY_DAILY = os.path.join(_ROOT, "..", "sp500-intraday-ranker", "data", "market",
                         "SPY_daily.parquet")

TRADING_DAYS = 252


# ─────────────────────────────────────────────────────────────────────────────
# Data prep: long panel -> wide matrices (date × ticker)
# ─────────────────────────────────────────────────────────────────────────────

def load_wide(min_dollar_vol: float, start: str | None):
    panel = pd.read_parquet(DATA)
    if start:
        panel = panel[panel["date"] >= pd.Timestamp(start)]
    close = panel.pivot(index="date", columns="ticker", values="close").sort_index()
    open_ = panel.pivot(index="date", columns="ticker", values="open").sort_index()
    vol = panel.pivot(index="date", columns="ticker", values="volume").sort_index()

    # SPY benchmark from the sibling's daily cache (it isn't in the 5-min raw dir).
    spy = pd.read_parquet(SPY_DAILY)
    spy.index = pd.to_datetime(spy.index)
    if start:
        spy = spy[spy.index >= pd.Timestamp(start)]
    spy_close = spy["Close"]
    spy_open = spy["Open"]
    # Drop SPY from the tradable universe if it somehow appears there.
    for df in (close, open_, vol):
        if "SPY" in df:
            df.drop(columns="SPY", inplace=True)

    # Point-in-time-ish liquidity gate: 20-day median dollar volume, lagged 1 day
    # so it uses only past information at the decision bar.
    dollar_vol = (close * vol).rolling(20, min_periods=10).median().shift(1)
    liquid = dollar_vol >= min_dollar_vol

    return dict(close=close, open=open_, liquid=liquid,
                spy_close=spy_close, spy_open=spy_open)


def rsi(close: pd.DataFrame, n: int) -> pd.DataFrame:
    """Wilder RSI over `n` sessions, column-wise. RSI2 is the classic MR signal."""
    delta = close.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    roll_up = up.ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
    roll_dn = down.ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
    rs = roll_up / roll_dn.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


# ─────────────────────────────────────────────────────────────────────────────
# Selection + simulation
# ─────────────────────────────────────────────────────────────────────────────

def select_k(signal: pd.DataFrame, k: int, mask: pd.DataFrame,
             largest: bool, valid: pd.DataFrame, seed: int | None = None):
    """Boolean weight matrix: equal weight across the K chosen names per row.

    `signal` ranked per row; `largest` picks top-K else bottom-K. Only names where
    `mask` (liquid) AND `valid` (has a forward return) are eligible. `seed` (for
    the random baseline) ignores the signal and picks K eligible names at random.
    """
    eligible = mask & valid
    sig = signal.where(eligible)
    if seed is not None:
        rng = np.random.default_rng(seed)
        rand = pd.DataFrame(rng.random(sig.shape), index=sig.index, columns=sig.columns)
        sig = rand.where(eligible)
        largest = True
    rank = sig.rank(axis=1, ascending=not largest, method="first")
    chosen = rank <= k
    n = chosen.sum(axis=1)
    w = chosen.div(n.where(n > 0), axis=0).fillna(0.0)
    return w


def simulate(weights: pd.DataFrame, fwd_ret: pd.DataFrame, cost_bps: float):
    """Daily strategy return = basket forward return − round-trip cost.

    cost_bps is per side; a fully-rebalanced daily basket pays it on entry AND
    exit, so 2× per invested day. Days with an empty basket sit in cash (0).
    """
    gross = (weights * fwd_ret).sum(axis=1)
    invested = weights.sum(axis=1) > 0
    cost = invested.astype(float) * (2 * cost_bps / 1e4)
    net = gross - cost
    return net, invested


def stats(ret: pd.Series, invested: pd.Series | None = None) -> dict:
    r = ret.dropna()
    if r.empty:
        return {}
    n = len(r)
    total = (1 + r).prod() - 1
    years = n / TRADING_DAYS
    base = max(1 + total, 1e-9)                       # guard blown-up accounts
    cagr = base ** (1 / years) - 1 if years > 0 else np.nan
    vol = r.std() * np.sqrt(TRADING_DAYS)
    sharpe = (r.mean() / r.std() * np.sqrt(TRADING_DAYS)) if r.std() > 0 else np.nan
    curve = (1 + r).cumprod()
    dd = (curve / curve.cummax() - 1).min()
    days_inv = int(invested.sum()) if invested is not None else n
    hit = (r[r != 0] > 0).mean() if (r != 0).any() else np.nan
    return dict(CAGR=cagr, Sharpe=sharpe, Vol=vol, MaxDD=dd, HitRate=hit,
                DaysInvested=days_inv, AvgBps=r.mean() * 1e4, TotRet=total)


def per_year(ret: pd.Series) -> pd.Series:
    return ret.groupby(ret.index.year).apply(lambda x: (1 + x).prod() - 1)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--k", type=int, default=10, help="Basket size (default 10).")
    ap.add_argument("--cost-bps", type=float, default=5.0,
                    help="Cost per side in bps (spread+slippage+commission). "
                         "Charged on entry AND exit. Default 5.")
    ap.add_argument("--min-dollar-vol", type=float, default=20e6,
                    help="Min 20d median $ volume to be tradable (default $20M).")
    ap.add_argument("--start", default="2016", help="Start year/date (default 2016).")
    ap.add_argument("--rsi-buy", type=float, default=10.0,
                    help="Only enter MR names with RSI2 below this (default 10).")
    args = ap.parse_args()

    w = load_wide(args.min_dollar_vol, args.start)
    close, open_, liquid = w["close"], w["open"], w["liquid"]

    # Forward returns (the thing each holding actually earns).
    overnight = open_.shift(-1) / close - 1          # close_t -> open_{t+1}
    one_day = close.shift(-1) / close - 1            # close_t -> close_{t+1}
    intraday = close / open_ - 1                     # open_t  -> close_t (same day)

    # Signals available at the decision bar.
    rsi2 = rsi(close, 2)                              # low = oversold
    ret_5d = close / close.shift(5) - 1              # momentum
    gap = open_ / close.shift(1) - 1                 # today's open vs prior close

    K, C = args.k, args.cost_bps

    results = {}

    # ---- OVERNIGHT (enter close_t, exit next open) ----
    valid_on = overnight.notna()
    # overnight_all: hold every liquid name (breadth), equal weight.
    all_w = (liquid & valid_on).astype(float)
    all_w = all_w.div(all_w.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0)
    results["overnight_all"] = simulate(all_w, overnight, C)

    mr_mask = liquid & (rsi2 < args.rsi_buy)
    results["mr_overnight"] = simulate(
        select_k(rsi2, K, mr_mask, largest=False, valid=valid_on), overnight, C)
    results["mom_overnight"] = simulate(
        select_k(ret_5d, K, liquid, largest=True, valid=valid_on), overnight, C)
    results["random_overnight"] = simulate(
        select_k(rsi2, K, liquid, largest=False, valid=valid_on, seed=42), overnight, C)

    # ---- ONE-DAY (enter close_t, exit next close) ----
    valid_1d = one_day.notna()
    results["mr_1day"] = simulate(
        select_k(rsi2, K, liquid & (rsi2 < args.rsi_buy), largest=False,
                 valid=valid_1d), one_day, C)

    # ---- SAME-DAY (enter open_t, exit close_t) ----  [PDT-limited under $25k]
    valid_id = intraday.notna()
    # Gap fade: names that gapped DOWN most at the open (buy the dip, exit close).
    results["gap_fade"] = simulate(
        select_k(gap, K, liquid & (gap < 0), largest=False, valid=valid_id),
        intraday, C)
    # Gap momentum: names that gapped UP most (continuation).
    results["gap_mom"] = simulate(
        select_k(gap, K, liquid & (gap > 0), largest=True, valid=valid_id),
        intraday, C)

    # ---- Baseline: SPY buy & hold (close to close) ----
    spy_ret = (w["spy_close"] / w["spy_close"].shift(1) - 1).dropna()

    # ── Report ───────────────────────────────────────────────────────────────
    print("\n" + "=" * 78)
    print(f"  INTRADAY / OVERNIGHT RULE BACKTEST   K={K}  cost={C}bps/side  "
          f"$vol>{args.min_dollar_vol/1e6:.0f}M  since {close.index.min().date()}")
    print("=" * 78)
    print(f"{'strategy':<18}{'CAGR':>8}{'Sharpe':>8}{'MaxDD':>8}"
          f"{'Hit%':>7}{'AvgBps':>8}{'Days':>7}")
    print("-" * 78)

    rows = {}
    for name, (ret, inv) in results.items():
        s = stats(ret, inv)
        rows[name] = ret
        print(f"{name:<18}{s['CAGR']:>7.1%}{s['Sharpe']:>8.2f}{s['MaxDD']:>8.1%}"
              f"{s['HitRate']:>7.1%}{s['AvgBps']:>8.1f}{s['DaysInvested']:>7d}")

    sp = stats(spy_ret)
    print(f"{'SPY buy&hold':<18}{sp['CAGR']:>7.1%}{sp['Sharpe']:>8.2f}"
          f"{sp['MaxDD']:>8.1%}{sp['HitRate']:>7.1%}{sp['AvgBps']:>8.1f}"
          f"{sp['DaysInvested']:>7d}")

    # Per-year for the headline strategies vs SPY.
    print("\nPer-year total return (net):")
    show = ["mr_overnight", "mom_overnight", "random_overnight", "gap_fade",
            "overnight_all"]
    yr = pd.DataFrame({n: per_year(rows[n]) for n in show})
    yr["SPY"] = per_year(spy_ret)
    print((yr * 100).round(1).to_string())

    print("\nNotes:")
    print(" * 'random_overnight' is the dartboard — a strategy must clear it to be real.")
    print(" * overnight/same-day strategies rebalance daily → they pay the cost every")
    print(f"   invested day (2×{C}bps). Try --cost-bps 0 to see the gross edge.")
    print(" * Universe = 721 names from the sibling snapshot; addition dates are NOT")
    print("   point-in-time, so mild survivorship bias remains (the dartboard controls")
    print("   for most of it). This is in-sample across the whole decade — not yet an")
    print("   out-of-sample test.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
