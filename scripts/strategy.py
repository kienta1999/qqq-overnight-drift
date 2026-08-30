#!/usr/bin/env python3
"""The deployed rule, in one place, so the daily runner and the backtest can
never drift apart.

    signal:      QQQ close > its 200-day SMA   -> hold OVERNIGHT (close -> next
                 open), else stay in cash.
    instrument:  picked from QQQ's 20-day realized vol (a self-contained VIX
                 proxy) -- calm -> more leverage, stormy -> less.
"""
import numpy as np
import pandas as pd

TD = 252              # trading days per year
SMA_WINDOW = 200
RVOL_WINDOW = 20
RVOL_LO = 0.18        # rvol below this -> TQQQ (3x)
RVOL_HI = 0.28        # rvol above this -> QQQ  (1x)
LEVERAGE = {"QQQ": 1, "QLD": 2, "TQQQ": 3}


def pick_instrument(rvol: float, lo: float = RVOL_LO, hi: float = RVOL_HI) -> str:
    """Vol-regime leverage choice for one night."""
    if rvol < lo:
        return "TQQQ"
    if rvol > hi:
        return "QQQ"
    return "QLD"


def signals(close: pd.Series, sma_window: int = SMA_WINDOW) -> pd.DataFrame:
    """Trend flag and annualized realized vol, both known at that day's close."""
    return pd.DataFrame({
        "in_trend": close > close.rolling(sma_window).mean(),
        "rvol": close.pct_change().rolling(RVOL_WINDOW).std() * np.sqrt(TD),
    })


def overnight(bars: pd.DataFrame) -> pd.Series:
    """Return from today's close to tomorrow's open, indexed by today."""
    return bars["Open"].shift(-1) / bars["Close"] - 1
