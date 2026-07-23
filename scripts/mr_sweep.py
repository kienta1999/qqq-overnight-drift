#!/usr/bin/env python3
"""Overnight mean-reversion, sized for a real small account. Answers:
   which K (2 / 5 / 10 / 20 most-oversold) is best given $10k capital and a
   per-ORDER commission, and does it beat SPY buy-and-hold?

Strategy (fixed): at each close, buy the K most-oversold liquid S&P names
(RSI2 < threshold), equal weight, deploying the whole account; sell at the next
open. Not a PDT day-trade (held overnight).

Cost model — the part that matters for a $10k account:
   * commission: a FLAT $/order, charged on every buy AND every sell. A day that
     holds n names costs 2*n*commission (n buys + n sells). At $1/order and
     $10k, K=10 is 20 orders = $20/day = 0.2%/day ≈ 40%/yr in commissions alone.
   * spread/slippage: bps per side on notional (round-trip 2×).
   * commission is charged against CURRENT equity, so the drag is simulated on
     the real (compounding) equity path, not a fixed notional.

Usage:
    python scripts/mr_sweep.py                         # $1/order, $10k, sweep K
    python scripts/mr_sweep.py --commission 0          # IBKR Lite (free US stocks)
    python scripts/mr_sweep.py --capital 25000 --spread-bps 2
"""

import argparse
import os
import sys

import numpy as np
import pandas as pd

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
from backtest import load_wide, rsi, select_k, stats, per_year  # noqa: E402

TRADING_DAYS = 252


def simulate_account(basket_ret: pd.Series, n_names: pd.Series, *,
                     capital: float, commission: float, spread_bps: float,
                     leverage: float = 1.0, margin_rate: float = 0.055):
    """Walk the equity path applying real per-order commission + spread + margin.

    basket_ret = equal-weight gross overnight return of the day's basket.
    n_names    = how many names were actually held that day (may be < K).
    leverage   = gross exposure multiple; >1 borrows (L-1)*equity and pays
                 margin_rate/252 per invested day on the borrowed part. Return
                 and spread both scale by L (you trade L× the notional).
    Returns the net daily-return series (0 on cash days).
    """
    equity = capital
    out = []
    spread = 2 * spread_bps / 1e4          # round-trip spread per unit notional
    for dt in basket_ret.index:
        n = int(n_names.get(dt, 0))
        g = basket_ret.get(dt, np.nan)
        if n == 0 or not np.isfinite(g):
            out.append((dt, 0.0))
            continue
        comm_frac = (2 * n * commission) / equity          # flat $/order, unlevered
        borrow = max(leverage - 1.0, 0.0) * margin_rate / TRADING_DAYS
        net = max(leverage * (g - spread) - comm_frac - borrow, -1.0)
        equity = max(equity * (1 + net), 1e-6)             # floor a blown-up acct
        out.append((dt, net))
    s = pd.Series(dict(out)).sort_index()
    s.index = pd.to_datetime(s.index)
    return s, equity


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--capital", type=float, default=10_000.0)
    ap.add_argument("--commission", type=float, default=1.0,
                    help="$/order (charged on every buy AND sell). 0 = IBKR Lite.")
    ap.add_argument("--spread-bps", type=float, default=3.0,
                    help="Spread+slippage per side, bps (default 3).")
    ap.add_argument("--leverage", type=float, default=1.0,
                    help="Gross exposure multiple (>1 borrows at --margin-rate).")
    ap.add_argument("--margin-rate", type=float, default=0.055,
                    help="Annual margin interest on the borrowed part (IBKR ~5.5%).")
    ap.add_argument("--rsi-buy", type=float, default=10.0)
    ap.add_argument("--min-dollar-vol", type=float, default=20e6)
    ap.add_argument("--start", default="2016")
    ap.add_argument("--ks", default="2,5,10,20")
    args = ap.parse_args()

    w = load_wide(args.min_dollar_vol, args.start)
    close, open_, liquid = w["close"], w["open"], w["liquid"]
    rsi2 = rsi(close, 2)
    overnight = open_.shift(-1) / close - 1
    valid = overnight.notna()
    mask = liquid & (rsi2 < args.rsi_buy)

    spy_ret = (w["spy_close"] / w["spy_close"].shift(1) - 1).dropna()
    spy_s = stats(spy_ret)

    ks = [int(x) for x in args.ks.split(",")]

    print("\n" + "=" * 82)
    print(f"  OVERNIGHT MEAN-REVERSION — sized for ${args.capital:,.0f}, "
          f"${args.commission:.2f}/order, {args.spread_bps:.0f}bps/side spread")
    print(f"  buy K most-oversold (RSI2<{args.rsi_buy:.0f}) at close, sell next open  "
          f"| since {close.index.min().date()}")
    print("=" * 82)
    print(f"{'K':>3}{'CAGR':>9}{'Sharpe':>8}{'MaxDD':>8}{'Hit%':>7}"
          f"{'avgNames':>9}{'orders/yr':>10}{'comm/yr':>9}{'end$':>10}")
    print("-" * 82)

    curves = {}
    for k in ks:
        W = select_k(rsi2, k, mask, largest=False, valid=valid)
        n_names = (W > 0).sum(axis=1)
        basket = (W * overnight).sum(axis=1)          # equal-weight gross
        net, end_equity = simulate_account(
            basket, n_names, capital=args.capital,
            commission=args.commission, spread_bps=args.spread_bps,
            leverage=args.leverage, margin_rate=args.margin_rate)
        s = stats(net, n_names > 0)
        curves[k] = net
        inv_days = int((n_names > 0).sum())
        avg_names = n_names[n_names > 0].mean()
        orders_yr = 2 * n_names.sum() / (len(net) / TRADING_DAYS)
        comm_yr = orders_yr * args.commission
        print(f"{k:>3}{s['CAGR']:>8.1%}{s['Sharpe']:>8.2f}{s['MaxDD']:>8.1%}"
              f"{s['HitRate']:>7.1%}{avg_names:>9.1f}{orders_yr:>10.0f}"
              f"{comm_yr:>8.0f}{end_equity:>10,.0f}")

    print(f"{'SPY':>3}{spy_s['CAGR']:>8.1%}{spy_s['Sharpe']:>8.2f}"
          f"{spy_s['MaxDD']:>8.1%}{spy_s['HitRate']:>7.1%}"
          f"{'—':>9}{'—':>10}{'—':>9}"
          f"{args.capital*(1+spy_s['TotRet']):>10,.0f}")

    beats = [k for k in ks if stats(curves[k])['CAGR'] > spy_s['CAGR']]
    print(f"\nBeats SPY on CAGR: {beats or 'NONE'}   "
          f"(SPY CAGR {spy_s['CAGR']:.1%}, Sharpe {spy_s['Sharpe']:.2f})")
    print("Per-year net total return (%):")
    yr = pd.DataFrame({f"K={k}": per_year(curves[k]) for k in ks})
    yr["SPY"] = per_year(spy_ret)
    print((yr * 100).round(1).to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
