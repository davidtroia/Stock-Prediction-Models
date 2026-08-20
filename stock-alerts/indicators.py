"""
Technical indicators used by the alert rules.

Pure pandas/numpy implementations so the alert app stays self-contained and has
no dependency on a brokerage login. The formulas mirror the signals produced by
the robinhood-mcp server's get_technical_analysis tool (Wilder RSI, 12/26/9
MACD, 20/2 Bollinger Bands, simple moving averages).
"""

from __future__ import annotations

import pandas as pd


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's Relative Strength Index."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    out = 100 - (100 / (1 + rs))
    # When there are no losses the RSI is 100 by definition (rs -> inf).
    out = out.where(avg_loss != 0, 100.0)
    return out


def macd(
    close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Return (macd_line, signal_line, histogram)."""
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return macd_line, signal_line, macd_line - signal_line


def sma(close: pd.Series, period: int) -> pd.Series:
    return close.rolling(period).mean()


def bollinger(
    close: pd.Series, period: int = 20, num_std: float = 2.0
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Return (middle, upper, lower) Bollinger Bands."""
    mid = close.rolling(period).mean()
    std = close.rolling(period).std(ddof=0)
    return mid, mid + num_std * std, mid - num_std * std


def last_two(series: pd.Series) -> tuple[float, float]:
    """Previous and current value of a series, as plain floats (NaN-safe)."""
    s = series.dropna()
    if len(s) < 2:
        return float("nan"), float("nan")
    return float(s.iloc[-2]), float(s.iloc[-1])
