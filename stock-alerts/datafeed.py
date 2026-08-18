"""
Market data feed.

Wraps yfinance into the MarketData snapshot the rule engine expects. yfinance is
used (instead of the brokerage API) so the alerter needs no login just to read
prices and can run anywhere. This is the only module that touches the network;
the rule engine is pure and unit-tested with synthetic data.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

from rules import MarketData


def build_market_data(symbol: str, period: str = "1y", interval: str = "1d") -> Optional[MarketData]:
    """
    Fetch history for one symbol and assemble a MarketData snapshot.
    Returns None if data can't be retrieved.
    """
    import yfinance as yf  # imported lazily so tests don't require the package

    ticker = yf.Ticker(symbol)
    hist = ticker.history(period=period, interval=interval, auto_adjust=False)
    if hist is None or hist.empty or len(hist) < 2:
        print(f"[warn] no data for {symbol}")
        return None

    closes = hist["Close"].dropna()
    highs = hist["High"].dropna()
    lows = hist["Low"].dropna()
    volumes = hist["Volume"].dropna()

    last_price = float(closes.iloc[-1])
    prev_close = float(closes.iloc[-2])

    # Prefer live fast_info values when available (more current than daily close).
    try:
        fi = ticker.fast_info
        last_price = float(fi.get("last_price", last_price) or last_price)
        prev_close = float(fi.get("previous_close", prev_close) or prev_close)
    except Exception:
        pass

    return MarketData(
        symbol=symbol.upper(),
        last_price=last_price,
        prev_close=prev_close,
        closes=closes,
        highs=highs,
        lows=lows,
        volumes=volumes,
        year_high=float(highs.tail(252).max()),
        year_low=float(lows.tail(252).min()),
        avg_volume=float(volumes.tail(30).mean()) if len(volumes) else 0.0,
        last_volume=float(volumes.iloc[-1]) if len(volumes) else 0.0,
    )
