#!/usr/bin/env python3
"""Self-check for the traded rule: run `uv run python scripts/test_strategy.py`."""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backtest import DRAG, load_overnight, strategy_returns
from strategy import RVOL_HI, RVOL_LO, overnight, pick_instrument, signals


def test_regime_thresholds():
    assert pick_instrument(RVOL_LO - 0.01) == "TQQQ"
    assert pick_instrument(RVOL_HI + 0.01) == "QQQ"
    assert pick_instrument((RVOL_LO + RVOL_HI) / 2) == "QLD"
    assert pick_instrument(RVOL_LO) == "QLD" and pick_instrument(RVOL_HI) == "QLD"  # inclusive mid


def test_overnight_is_close_to_next_open():
    bars = pd.DataFrame({"Open": [10.0, 11.0, 12.0], "Close": [10.0, 10.0, 10.0]})
    on = overnight(bars)
    assert abs(on.iloc[0] - 0.1) < 1e-12 and abs(on.iloc[1] - 0.2) < 1e-12
    assert pd.isna(on.iloc[2])          # no return on the last day: no next open


def test_signals_use_no_future_data():
    close = pd.Series(range(1, 400), dtype=float)
    full = signals(close)
    # recomputing on a truncated history must not change any earlier value
    trunc = signals(close.iloc[:300])
    assert full["in_trend"].iloc[:300].equals(trunc["in_trend"])
    assert full["rvol"].iloc[:300].round(12).equals(trunc["rvol"].round(12))


def test_cash_when_off_trend():
    on, close = load_overnight()
    sig = signals(close)
    ret, choice = strategy_returns(on, sig, RVOL_LO, RVOL_HI, cost=0.0)
    assert (ret[~sig["in_trend"]] == 0).all(), "must be flat cash below the 200d SMA"
    assert set(choice.unique()) <= {"QQQ", "QLD", "TQQQ"}
    # on every in-market night the return is exactly the chosen sleeve's overnight
    traded = sig["in_trend"] & ret.notna()
    picked = pd.Series([on[s][d] for d, s in choice[traded].items()], index=choice[traded].index)
    assert (ret[traded] - picked).abs().max() < 1e-12
    assert traded.sum() > 3000, "expected thousands of traded nights"


def test_synthetic_only_fills_pre_inception():
    on, close = load_overnight()
    real_tqqq = overnight(pd.read_csv(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data",
                     "TQQQ_daily_yf.csv"), parse_dates=["Date"]).set_index("Date").sort_index())
    overlap = on["TQQQ"].loc["2011":"2020"]
    assert (overlap - real_tqqq.reindex(overlap.index)).abs().max() < 1e-12
    assert DRAG["TQQQ"] > DRAG["QLD"] > 0


def test_sizing_never_overdraws():
    from execute import shares_for
    # a close 0.4% above the sizing snapshot still fits inside the cash balance
    qty = shares_for(10_000, 90.17, 50.0)
    assert qty == 110 and qty * 90.17 * 1.004 <= 10_000
    assert shares_for(10_000, 20_000, 50.0) == 0          # too expensive -> no order
    assert shares_for(0, 90.0, 50.0) == 0


def test_order_types_are_the_auction_orders():
    from execute import build_order
    buy = build_order("buy", "QLD", 110, "U1")
    assert (buy.action, buy.orderType, buy.tif) == ("BUY", "MOC", "DAY")
    sell = build_order("sell", "QLD", 110, "U1")
    assert (sell.action, sell.orderType, sell.tif) == ("SELL", "MKT", "OPG")
    assert buy.outsideRth is False and sell.account == "U1"


def test_intraday_filters_must_be_lagged_a_day():
    """Tested and rejected: shorting QQQ open->close. Keeping the trap it hid.
    An intraday trade opens at today's OPEN, so its filter can only use data
    through yesterday's close. Unlagged, `close < SMA` peeks at the very close
    it trades into and turns a losing rule into a fake Sharpe 1.9."""
    import pandas as pd
    from backtest import load

    qqq = load("QQQ")
    day = qqq["Close"] / qqq["Open"] - 1                  # today's session
    raw = qqq["Close"] < qqq["Close"].rolling(50).mean()
    lagged = raw.shift(1)
    assert lagged.iloc[5] == raw.iloc[4] and pd.isna(lagged.iloc[0])
    peek = (-day).where(raw.fillna(False), 0.0).loc["2010":]
    honest = (-day).where(lagged.fillna(False), 0.0).loc["2010":]
    assert peek.mean() > 0 > honest.mean()


def test_gold_gap_is_real_and_not_one_funds_nav_quirk():
    """GLD's whole return lives in the close->open gap. Two independent gold
    funds must agree, or the 'gap' is a print artifact rather than a market."""
    from backtest import load
    from strategy import overnight

    for sym in ("GLD", "IAU"):
        bars = load(sym).loc["2005-02-01":]
        on = (1 + overnight(bars).dropna()).prod() - 1
        day = (1 + (bars["Close"] / bars["Open"] - 1)).prod() - 1
        assert on > 3 * abs(day), f"{sym}: overnight {on:.1%} vs intraday {day:.1%}"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
    print("all checks passed")
