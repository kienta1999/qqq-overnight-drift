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
ETF_DIR = os.path.join(_ROOT, "data")
SPY_DAILY = os.path.join(_ROOT, "..", "sp500-intraday-ranker", "data", "market",
                         "SPY_daily.parquet")

TRADING_DAYS = 252
SMA_WINDOW = 200                                     # trend filter on QQQ
RVOL_WINDOW = 20                                     # realized-vol regime window


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
# The DEPLOYED strategy: overnight-QQQ + 200d-trend with a vol-regime instrument
# switch (see scripts/regime_switch.py). Trades only 3 ETFs, so it carries NO
# survivorship bias — unlike the 721-name universe rules below. Simulated here
# under the SAME per-side cost convention as every other row for a fair table.
# ─────────────────────────────────────────────────────────────────────────────

def vol_switch(start, cost_bps: float, lo: float = 0.18, hi: float = 0.28):
    """Daily return series of the deployed vol-regime overnight strategy.

    Signal = QQQ's own close vs its 200d SMA (in-market only above it) plus QQQ's
    20d realized vol picking the instrument that night: rvol<lo -> TQQQ (3x),
    rvol>hi -> QQQ (1x), else QLD (2x). Each ETF earns its OWN actual overnight
    return (open_{t+1}/close_t - 1), so leverage decay is real. Cash (0) on
    off-trend nights. Returns (ret, invested) aligned to dates >= `start`.
    """
    def load(sym):
        df = pd.read_csv(os.path.join(ETF_DIR, f"{sym}_daily_yf.csv"),
                         parse_dates=["Date"]).set_index("Date").sort_index()
        return df["Open"].rename(f"{sym}_o"), df["Close"].rename(f"{sym}_c")

    cols = {}
    for s in ("QQQ", "QLD", "TQQQ"):
        o, c = load(s)
        cols[f"{s}_o"], cols[f"{s}_c"] = o, c
    df = pd.concat(cols, axis=1)
    df.columns = list(cols)                          # flatten to plain names

    overnight = {s: df[f"{s}_o"].shift(-1) / df[f"{s}_c"] - 1
                 for s in ("QQQ", "QLD", "TQQQ")}    # close_t -> open_{t+1}

    c = df["QQQ_c"]
    in_trend = c > c.rolling(SMA_WINDOW).mean()      # decided at today's close
    rvol = c.pct_change().rolling(RVOL_WINDOW).std() * np.sqrt(TRADING_DAYS)
    choice = pd.Series("QLD", index=df.index)
    choice = choice.where(rvol >= lo, "TQQQ").where(rvol <= hi, "QQQ")

    cost = 2 * cost_bps / 1e4                         # round-trip on invested nights
    ret = pd.Series(0.0, index=df.index)
    for s in ("QQQ", "QLD", "TQQQ"):
        pick = (choice == s) & in_trend
        ret = ret.where(~pick, overnight[s] - cost)
    ret = ret.where(in_trend, 0.0).where(overnight["QQQ"].notna())   # drop last NaN night

    keep = df.index >= pd.Timestamp(start)
    return ret[keep], (in_trend & keep)[keep]


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
    ap.add_argument("--lo", type=float, default=0.18,
                    help="Vol-switch: QQQ rvol below this -> TQQQ (3x). Default 0.18.")
    ap.add_argument("--hi", type=float, default=0.28,
                    help="Vol-switch: QQQ rvol above this -> QQQ (1x). Default 0.28.")
    ap.add_argument("--etf-cost-bps", type=float, default=0.1,
                    help="Per-side cost for the deployed ETF row ONLY (default 0.1). "
                         "IBKR Lite = $0 commission and MOC/MOO fills clear at the "
                         "auction price (no spread), so ETF cost ~0; the small-cap "
                         "basket rules keep the higher --cost-bps.")
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

    # ---- DEPLOYED strategy: overnight-QQQ + trend + vol-regime switch ----
    # Aligned to the same first date as the universe panel so the whole table
    # covers one identical window. Priced at its OWN realistic cost (--etf-cost-bps):
    # commission-free ETFs filled at the MOC/MOO auction print carry ~no spread,
    # unlike the small-cap baskets below which really do pay ~5bps/side.
    results["qqq_vol_switch"] = vol_switch(
        close.index.min(), args.etf_cost_bps, args.lo, args.hi)

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
    print("  Columns:")
    print("    CAGR   = compound annual growth rate, net of costs (higher better)")
    print("    Sharpe = annualized return / volatility; risk-adjusted edge (>0 = beats cash)")
    print("    MaxDD  = worst peak-to-trough equity drawdown (closer to 0 better)")
    print("    Hit%   = share of invested days that ended positive")
    print("    AvgBps = average net return per invested day, in basis points (1bp=0.01%)")
    print("    Days   = number of days actually holding a position (in-market)")
    print("  Strategies (all net of cost, no lookahead):")
    print("    qqq_vol_switch   DEPLOYED: hold QQQ/QLD/TQQQ overnight only while QQQ is above")
    print("                     its 200d trend; leverage picked from QQQ's 20d realized vol")
    print("    overnight_all    buy EVERY liquid name at close, sell next open (overnight drift)")
    print("    mr_overnight     buy the K most-oversold names (low RSI2), sell next open (bounce)")
    print("    mom_overnight    buy the K strongest 5-day movers, sell next open (momentum)")
    print("    random_overnight buy K RANDOM names overnight -- the dartboard / luck baseline")
    print("    mr_1day          like mr_overnight but hold a full day (close -> next close)")
    print("    gap_fade         buy the K biggest gap-DOWNS at the open, sell same close (revert)")
    print("    gap_mom          buy the K biggest gap-UPS at the open, sell same close (continue)")
    print("    SPY buy&hold     just own SPY the whole time -- the 'do nothing' benchmark")
    print("=" * 78)
    print(f"{'strategy':<18}{'CAGR':>8}{'Sharpe':>8}{'MaxDD':>8}"
          f"{'Hit%':>7}{'AvgBps':>8}{'Days':>7}")
    print("-" * 78)

    rows = {}
    for name, (ret, inv) in results.items():
        s = stats(ret, inv)
        rows[name] = ret
        tag = "  <- DEPLOYED (winner)" if name == "qqq_vol_switch" else ""
        print(f"{name:<18}{s['CAGR']:>7.1%}{s['Sharpe']:>8.2f}{s['MaxDD']:>8.1%}"
              f"{s['HitRate']:>7.1%}{s['AvgBps']:>8.1f}{s['DaysInvested']:>7d}{tag}")

    sp = stats(spy_ret)
    print(f"{'SPY buy&hold':<18}{sp['CAGR']:>7.1%}{sp['Sharpe']:>8.2f}"
          f"{sp['MaxDD']:>8.1%}{sp['HitRate']:>7.1%}{sp['AvgBps']:>8.1f}"
          f"{sp['DaysInvested']:>7d}")

    # Per-year for the headline strategies vs SPY.
    print("\nPer-year total return (net):")
    show = ["qqq_vol_switch", "mr_overnight", "mom_overnight", "random_overnight",
            "gap_fade", "overnight_all"]
    yr = pd.DataFrame({n: per_year(rows[n]) for n in show})
    yr["SPY"] = per_year(spy_ret)
    print((yr * 100).round(1).to_string())

    print("\nNotes:")
    print(" * 'qqq_vol_switch' is THIS repo's deployed strategy (scripts/regime_switch.py):")
    print("   overnight-QQQ + 200d-trend, instrument (QQQ/QLD/TQQQ) picked from QQQ's 20d")
    print("   realized vol. Only 3 ETFs -> no survivorship bias; only in-market above the")
    print(f"   200d trend (see 'Days').")
    print(f" * COSTS DIFFER BY ROW ON PURPOSE. qqq_vol_switch pays {args.etf_cost_bps}bps/side")
    print("   (IBKR Lite = $0 commission; MOC/MOO orders fill at the auction price so there is")
    print("   no spread to cross). ETF expense ratios (QQQ .20% / QLD .95% / TQQQ .84% per yr)")
    print("   are already inside the real ETF prices, so they are NOT subtracted again. The")
    print(f"   small-cap basket rules below pay the full {C}bps/side (real spread on churned names).")
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
