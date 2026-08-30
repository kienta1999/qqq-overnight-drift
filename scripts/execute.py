#!/usr/bin/env python3
"""Place the overnight-QQQ trade on IBKR — staged, one leg per run.

The strategy is two orders a day and nothing else:

    BUY leg   (afternoon, before 15:50 ET)  Market-On-Close, fills at 16:00
    SELL leg  (that evening or before 09:28) Market-On-Open, fills at 09:30

`--leg auto` (default) picks by what you actually hold: FLAT -> buy leg,
holding one of QQQ/QLD/TQQQ -> sell leg. You cannot double-buy, and you cannot
sell what you do not hold. Which ETF to buy comes from scripts/strategy.py, the
same rule the backtest runs; if QQQ is below its 200-day SMA the buy leg is a
no-op and you stay in cash.

Sizing is cash-only, all-in: shares = floor(equity / price), where equity is
NetLiquidation. No margin is ever used — the leverage lives inside the ETF.

Three modes, safest first:
    --mode print   plan only, nothing sent. Needs no order permissions.
    --mode whatif  IBKR returns commission/margin impact; nothing is placed.
    --mode live    places the order. Gated by a --max-notional circuit breaker,
                   a working-order cancel, and (live account) a typed
                   confirmation of the exact account number.

CLI:
    uv run python scripts/execute.py --port 4002                      # paper, plan only
    uv run python scripts/execute.py --port 4001 --mode whatif        # cost preview
    uv run python scripts/execute.py --port 4001 --mode live          # trade
    uv run python scripts/execute.py --port 4001 --leg sell --mode live
"""
import argparse
import math
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ibkr import ETFS, connect, held_etf                    # noqa: E402
from strategy import LEVERAGE, RVOL_HI, RVOL_LO, pick_instrument, signals  # noqa: E402
from today import SIGNAL_SYMBOL, daily_closes, get_client   # noqa: E402

ET = ZoneInfo("America/New_York")
MOC_CUTOFF = (15, 50)          # IBKR stops accepting MOC at 15:50 ET
MOO_CUTOFF = (9, 28)           # OPG orders must be in before the 09:30 auction


def now_et() -> datetime:
    return datetime.now(ET)


def check_clock(leg: str) -> None:
    """Warn loudly when a leg is being placed outside its auction window."""
    t = now_et()
    hm = (t.hour, t.minute)
    if leg == "buy" and hm >= MOC_CUTOFF and t.weekday() < 5:
        print(f"  ⚠ It is {t:%H:%M} ET — past the {MOC_CUTOFF[0]}:{MOC_CUTOFF[1]} MOC "
              f"cutoff. IBKR will likely reject this order.")
    if leg == "sell" and MOO_CUTOFF <= hm < (16, 0) and t.weekday() < 5:
        print(f"  ⚠ It is {t:%H:%M} ET — the 09:30 opening auction has passed. "
              f"This OPG order will queue for the NEXT open, leaving you exposed "
              f"through a full day session. Sell manually instead.")


def signal_now(sma: int) -> tuple[bool, float, str, float]:
    """(in_trend, rvol, instrument, instrument_price) from today's QQQ close."""
    client = get_client()
    close = daily_closes(client, SIGNAL_SYMBOL)
    if len(close) < sma + 1:
        sys.exit(f"Not enough {SIGNAL_SYMBOL} history for a {sma}d average.")
    sig = signals(close, sma).iloc[-1]
    rvol = float(sig["rvol"])
    instrument = pick_instrument(rvol)
    px = (float(close.iloc[-1]) if instrument == SIGNAL_SYMBOL
          else float(daily_closes(client, instrument, days=10).iloc[-1]))
    return bool(sig["in_trend"]), rvol, instrument, px


def shares_for(capital: float, price: float, buffer_bps: float) -> int:
    """Whole shares that fit in `capital`, sized against a padded price.

    The sizing price is a delayed snapshot; the MOC fills at the real close. The
    buffer means a close ABOVE the snapshot still fits in cash instead of
    overdrawing into margin.
    """
    return int(math.floor(capital / (price * (1 + buffer_bps / 1e4))))


def build_order(leg: str, symbol: str, qty: float, account: str):
    """MOC for the buy leg, MKT/OPG (market-on-open) for the sell leg."""
    from ib_async import Order

    o = Order(account=account, outsideRth=False, totalQuantity=qty)
    if leg == "buy":
        o.action, o.orderType, o.tif = "BUY", "MOC", "DAY"
    else:
        o.action, o.orderType, o.tif = "SELL", "MKT", "OPG"
    return o


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--host", default=None, help="Default: auto-detect WSL->Windows.")
    ap.add_argument("--port", type=int, required=True,
                    help="REQUIRED, no default: 4002 = Gateway paper, 4001 = live.")
    ap.add_argument("--client-id", type=int, default=12)
    ap.add_argument("--mode", choices=("print", "whatif", "live"), default="print")
    ap.add_argument("--leg", choices=("auto", "buy", "sell"), default="auto",
                    help="auto (default): flat -> buy, holding -> sell.")
    ap.add_argument("--capital", type=float, default=None,
                    help="Cap the money deployed. Default: full NetLiquidation.")
    ap.add_argument("--buffer-bps", type=float, default=50.0,
                    help="Size against price*(1+buffer) so a close above the sizing "
                         "snapshot cannot overdraw the account (default 50 bps).")
    ap.add_argument("--sma", type=int, default=200)
    ap.add_argument("--max-notional", type=float, default=None,
                    help="Hard cap on buy notional. Default: equity * 1.02.")
    args = ap.parse_args()

    ib, acct, is_live, equity = connect(args.host, args.port, args.client_id)
    try:
        print(f"Account: {acct}  ({'LIVE — REAL MONEY' if is_live else 'paper'})  "
              f"NetLiquidation=${equity:,.2f}   {now_et():%Y-%m-%d %H:%M} ET")
        if equity <= 0:
            sys.exit("🛑 Account has no equity — fund it before trading.")

        held_sym, held_qty = held_etf(ib, acct)
        leg = args.leg if args.leg != "auto" else ("sell" if held_sym else "buy")
        print(f"Position: {f'{held_qty:.0f} {held_sym}' if held_sym else 'FLAT'}"
              f"   ->  {leg.upper()} leg")

        working = [t for t in ib.openTrades() if t.isActive()]
        if working and args.mode != "live":
            print(f"⚠  {len(working)} working order(s) pending — the plan below "
                  f"ignores them. --mode live cancels them first.")

        # ── decide the order ────────────────────────────────────────────────
        if leg == "buy":
            if held_sym:
                sys.exit(f"🛑 Already holding {held_qty:.0f} {held_sym}. The buy leg "
                         f"would double up. Run the sell leg at the open first.")
            in_trend, rvol, symbol, px = signal_now(args.sma)
            regime = ("calm" if rvol < RVOL_LO else "stormy" if rvol > RVOL_HI else "mid")
            print(f"Signal:   {SIGNAL_SYMBOL} {'ABOVE' if in_trend else 'BELOW'} its "
                  f"{args.sma}d SMA   |   20d rvol {rvol:.1%} ({regime}) -> {symbol}")
            if not in_trend:
                print("\n  DECISION: CASH tonight ⚪ — no order. Re-run tomorrow.")
                return 0
            capital = min(equity, args.capital) if args.capital else equity
            qty = shares_for(capital, px, args.buffer_bps)
            if qty < 1:
                sys.exit(f"🛑 ${capital:,.0f} buys 0 shares of {symbol} at ~${px:,.2f}.")
            notional = qty * px
            print(f"\n  BUY {qty} {symbol} ({LEVERAGE[symbol]}x) market-on-close "
                  f"@ ~${px:,.2f}  =  ${notional:,.0f}  "
                  f"({notional / equity:.0%} of equity)")
            if symbol == "TQQQ":
                print("  ⚠ TQQQ is 3x — a ~33% overnight gap in QQQ zeroes it.")
            cap = args.max_notional if args.max_notional is not None else equity * 1.02
            if notional > cap:
                sys.exit(f"\n🛑 ABORT: notional ${notional:,.0f} exceeds cap "
                         f"${cap:,.0f}. Raise --max-notional if intended.")
        else:
            if not held_sym:
                print("\n  Nothing held — no sell leg to place. ⚪")
                return 0
            symbol, qty = held_sym, abs(held_qty)
            print(f"\n  SELL {qty:.0f} {symbol} market-on-open (MKT/OPG) "
                  f"— fills at the 09:30 auction")
        check_clock(leg)

        if args.mode == "print":
            print("\n[print mode] Nothing sent. --mode whatif for IBKR's preview, "
                  "--mode live to place it.")
            return 0

        from ib_async import Stock
        contract = Stock(symbol, "SMART", "USD")
        if not ib.qualifyContracts(contract):
            sys.exit(f"🛑 Could not qualify contract for {symbol}.")
        order = build_order(leg, symbol, qty, acct)

        if args.mode == "whatif":
            st = ib.whatIfOrder(contract, order)
            comm = getattr(st, "commission", None)
            print(f"\n[whatif] {order.action} {qty:g} {symbol} "
                  f"{order.orderType}/{order.tif}")
            print(f"  commission ≈ {comm}   initMarginAfter = "
                  f"{getattr(st, 'initMarginAfter', '?')}   "
                  f"equityWithLoanAfter = {getattr(st, 'equityWithLoanAfter', '?')}")
            print(f"  Open orders queued: {len(ib.openTrades())} (should be 0)")
            return 0

        # ── live ────────────────────────────────────────────────────────────
        if working:
            print(f"\nCancelling {len(working)} working order(s) first:")
            for t in working:
                print(f"  {t.contract.symbol} {t.order.action} {t.order.totalQuantity:g}")
                ib.cancelOrder(t.order)
            for _ in range(20):
                ib.sleep(0.5)
                if not any(t.isActive() for t in ib.openTrades()):
                    break
            if any(t.isActive() for t in ib.openTrades()):
                sys.exit("🛑 ABORT: could not cancel working orders. Clear them in "
                         "Gateway, then re-run.")
            print("  all cancelled.")

        print(f"\n[LIVE] About to place: {order.action} {qty:g} {symbol} "
              f"{order.orderType}/{order.tif} on "
              f"{'LIVE ' if is_live else 'paper '}account {acct}.")
        if is_live:
            resp = input(f"  Type the account number ({acct}) to CONFIRM: ").strip()
            if resp != acct:
                sys.exit("Aborted — confirmation did not match.")
        elif input("  Type YES to place the paper order: ").strip() != "YES":
            sys.exit("Aborted.")

        trade = ib.placeOrder(contract, order)
        ib.sleep(3)
        print(f"\n  {symbol} {order.action} {qty:g} -> {trade.orderStatus.status} "
              f"(filled {trade.orderStatus.filled:g})")
        if leg == "buy":
            print("\n  NEXT: after this fills at 16:00 ET, run the sell leg tonight:")
            print(f"    uv run python scripts/execute.py --port {args.port} "
                  f"--leg sell --mode live")
        print("  Monitor in Gateway. Re-running is safe — it reconciles from "
              "your actual position.")
    finally:
        ib.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(main())
