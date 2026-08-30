#!/usr/bin/env python3
"""Shared IB Gateway plumbing: host resolution, connect, account snapshot.

WSL -> Windows Gateway networking. Ports: 4002 = Gateway paper, 4001 = live.
Run this file directly to sanity-check the connection without placing anything:

    uv run python scripts/ibkr.py --port 4002       # paper
    uv run python scripts/ibkr.py --port 4001       # live account
"""
import argparse
import socket
import subprocess
import sys

ETFS = ("QQQ", "QLD", "TQQQ")


def resolve_host() -> str:
    """Windows host IP as seen from WSL2 NAT = the default-route gateway.

    Resolved at runtime, not hardcoded: the NAT gateway IP changes on reboot.
    Under mirrored networking (Win11 22H2+) pass --host 127.0.0.1 instead.
    """
    try:
        out = subprocess.check_output(
            "ip route show default | awk '{print $3}'", shell=True, text=True).strip()
        return out or "127.0.0.1"
    except Exception:
        return "127.0.0.1"


def connect(host: str | None, port: int, client_id: int):
    """Connect to the Gateway. Returns (ib, account, is_live, equity)."""
    host = host or resolve_host()
    try:                                    # raw TCP first: separates firewall from API
        socket.create_connection((host, port), timeout=4).close()
    except OSError as e:
        sys.exit(f"🛑 TCP connect to {host}:{port} failed: {e}\n"
                 "   Gateway running and logged in? Windows Firewall open on that "
                 "port? (NAT mode) is the WSL IP in Gateway's Trusted IPs?")
    try:
        from ib_async import IB
    except ImportError:
        sys.exit("ib_async not installed. Run:  uv add ib_async")

    ib = IB()
    try:
        ib.connect(host, port, clientId=client_id, timeout=15)
    except Exception as e:
        sys.exit(f"🛑 API handshake failed: {e}\n"
                 "   Port was open but the API refused. Usual causes: 'Enable ActiveX "
                 "and Socket Clients' off, this clientId already connected "
                 f"(try --client-id {client_id + 79}), or source IP not trusted.")

    acct = ib.managedAccounts()[0]
    equity = float([v for v in ib.accountValues(acct)
                    if v.tag == "NetLiquidation" and v.currency == "USD"][0].value)
    return ib, acct, not acct.startswith("DU"), equity


def held_etf(ib, acct) -> tuple[str | None, float]:
    """The strategy ETF currently held, if any. Returns (symbol, shares)."""
    for pos in ib.positions(acct):
        if (pos.contract.secType == "STK" and pos.contract.symbol in ETFS
                and pos.position != 0):
            return pos.contract.symbol, float(pos.position)
    return None, 0.0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--host", default=None, help="Default: auto-detect WSL->Windows.")
    ap.add_argument("--port", type=int, required=True, help="4002 = paper, 4001 = live")
    ap.add_argument("--client-id", type=int, default=11)
    args = ap.parse_args()

    ib, acct, is_live, equity = connect(args.host, args.port, args.client_id)
    try:
        print("=" * 52)
        print(f"  Account : {acct}")
        print(f"  Mode    : {'*** LIVE — REAL MONEY ***' if is_live else 'PAPER (safe)'}")
        print("=" * 52)
        vals = {v.tag: v.value for v in ib.accountValues(acct) if v.currency in ("USD", "BASE")}
        for tag in ("NetLiquidation", "AvailableFunds", "BuyingPower", "TotalCashValue"):
            if tag in vals:
                print(f"  {tag:<16}: {float(vals[tag]):>15,.2f}")
        sym, qty = held_etf(ib, acct)
        print(f"\n  Strategy position: {f'{qty:.0f} {sym}' if sym else 'FLAT (no ETF held)'}")
        working = [t for t in ib.openTrades() if t.isActive()]
        print(f"  Working orders   : {len(working)}")
        for t in working:
            print(f"    {t.contract.symbol:<6} {t.order.action} {t.order.totalQuantity:g} "
                  f"{t.order.orderType}/{t.order.tif} ({t.orderStatus.status})")
    finally:
        ib.disconnect()
    print("\nPlumbing OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
