"""
Tests for the alert engine, indicators, and dedupe/cooldown logic.

These use synthetic price series so they run offline (no yfinance / network).
Run with:  python test_alerts.py   (or: pytest test_alerts.py)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import indicators as ind
import rules as R
from state import AlertState


def _series(values):
    idx = pd.date_range("2024-01-01", periods=len(values), freq="D")
    return pd.Series(values, index=idx, dtype=float)


def _md(symbol="TEST", closes=None, last_price=None, prev_close=None,
        year_high=None, year_low=None, avg_volume=1_000_000, last_volume=1_000_000):
    closes = _series(closes if closes is not None else list(np.linspace(100, 110, 60)))
    last_price = closes.iloc[-1] if last_price is None else last_price
    prev_close = closes.iloc[-2] if prev_close is None else prev_close
    return R.MarketData(
        symbol=symbol, last_price=last_price, prev_close=prev_close,
        closes=closes, highs=closes, lows=closes, volumes=_series([avg_volume] * len(closes)),
        year_high=year_high if year_high is not None else float(closes.max()),
        year_low=year_low if year_low is not None else float(closes.min()),
        avg_volume=avg_volume, last_volume=last_volume,
    )


def _one(md, rule):
    sigs = R.evaluate(md, [rule])
    return sigs[0] if sigs else None


results = []


def check(name, cond):
    results.append((name, bool(cond)))
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")


def test_indicators():
    print("indicators:")
    # RSI of a strictly rising series -> 100 (no losses).
    r = ind.rsi(_series(list(range(1, 40))))
    check("rsi all-gains == 100", abs(r.dropna().iloc[-1] - 100.0) < 1e-6)
    # RSI stays within [0, 100].
    noisy = _series(list(100 + np.sin(np.arange(60)) * 5))
    rr = ind.rsi(noisy).dropna()
    check("rsi within bounds", rr.min() >= 0 and rr.max() <= 100)
    macd_line, signal_line, hist = ind.macd(noisy)
    check("macd hist == line-signal", abs((hist - (macd_line - signal_line)).dropna().abs().max()) < 1e-9)


def test_price_rules():
    print("price thresholds:")
    md = _md(last_price=248.0, closes=[248.0] * 60)  # 1% band of 250 = 247.5
    check("price_above approaching", _one(md, {"type": "price_above", "target": 250, "proximity_pct": 1}).status == R.APPROACHING)
    md = _md(last_price=251.0, closes=[251.0] * 60)
    check("price_above met", _one(md, {"type": "price_above", "target": 250}).status == R.MET)
    md = _md(last_price=191.5, closes=[191.5] * 60)  # within 1% above 190 (=191.9)
    check("price_below approaching", _one(md, {"type": "price_below", "target": 190, "proximity_pct": 1}).status == R.APPROACHING)
    md = _md(last_price=189.0, closes=[189.0] * 60)
    check("price_below met", _one(md, {"type": "price_below", "target": 190}).status == R.MET)
    md = _md(last_price=300.0, closes=[300.0] * 60)
    check("price_above far -> no signal", _one(md, {"type": "price_below", "target": 190}) is None)


def test_pct_move():
    print("pct move:")
    md = _md(last_price=95.0, prev_close=100.0)  # -5%
    check("pct_move met down", _one(md, {"type": "pct_move", "threshold": 5, "direction": "down"}).status == R.MET)
    md = _md(last_price=95.8, prev_close=100.0)  # -4.2%, 80% of 5 = 4.0 -> approaching
    check("pct_move approaching", _one(md, {"type": "pct_move", "threshold": 5}).status == R.APPROACHING)
    md = _md(last_price=95.0, prev_close=100.0)
    check("pct_move direction filter", _one(md, {"type": "pct_move", "threshold": 5, "direction": "up"}) is None)


def test_rsi_rule():
    print("rsi rule:")
    falling = _md(closes=list(np.linspace(120, 80, 60)))  # downtrend -> low RSI
    sig = _one(falling, {"type": "rsi", "oversold": 30})
    check("rsi oversold fires", sig is not None and sig.status in (R.APPROACHING, R.MET))
    rising = _md(closes=list(np.linspace(80, 120, 60)))
    sig = _one(rising, {"type": "rsi", "overbought": 70})
    check("rsi overbought fires", sig is not None and sig.status in (R.APPROACHING, R.MET))


def test_ma_cross():
    print("ma cross:")
    # Flat, then a dip, then a final jump so the 5-SMA crosses ABOVE the
    # 20-SMA exactly on the last bar (a golden cross the engine should catch).
    vals = [100.0] * 25 + [95.0] * 10 + [130.0]
    md = _md(closes=vals)
    sig = _one(md, {"type": "ma_cross", "fast": 5, "slow": 20, "direction": "both"})
    check("ma_cross golden cross on last bar", sig is not None and sig.status == R.MET)


def test_bollinger():
    print("bollinger:")
    vals = [100.0] * 59 + [80.0]  # sharp drop below the lower band
    md = _md(closes=vals, last_price=80.0)
    sig = _one(md, {"type": "bollinger", "band": "lower"})
    check("bollinger lower met", sig is not None and sig.status == R.MET)


def test_52w_and_volume():
    print("52w / volume:")
    md = _md(last_price=99.0, year_high=100.0, closes=[99.0] * 60)  # within 2% of high
    check("near_52w_high approaching", _one(md, {"type": "near_52w_high", "proximity_pct": 2}).status == R.APPROACHING)
    md = _md(last_price=101.0, year_high=100.0, closes=[101.0] * 60)
    check("near_52w_high met (new high)", _one(md, {"type": "near_52w_high"}).status == R.MET)
    md = _md(avg_volume=1_000_000, last_volume=2_500_000)
    check("volume_spike met", _one(md, {"type": "volume_spike", "multiple": 2}).status == R.MET)
    md = _md(avg_volume=1_000_000, last_volume=1_700_000)  # 1.7x, 80% of 2x -> approaching
    check("volume_spike approaching", _one(md, {"type": "volume_spike", "multiple": 2}).status == R.APPROACHING)


def test_dedupe():
    print("dedupe/cooldown:")
    st = AlertState(path="", cooldown_minutes=60)
    sig = R.Signal("AAPL", "price_above_250", R.APPROACHING, "msg")
    check("first send allowed", st.should_send(sig, now=1000))
    st.record(sig, now=1000)
    check("immediate resend blocked", not st.should_send(sig, now=1000))
    check("resend blocked within cooldown", not st.should_send(sig, now=1000 + 59 * 60))
    check("resend allowed after cooldown", st.should_send(sig, now=1000 + 61 * 60))
    esc = R.Signal("AAPL", "price_above_250", R.MET, "msg met")
    check("escalation approaching->met always sends", st.should_send(esc, now=1000))


def main():
    for fn in [test_indicators, test_price_rules, test_pct_move, test_rsi_rule,
               test_ma_cross, test_bollinger, test_52w_and_volume, test_dedupe]:
        fn()
    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    print(f"\n{passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
