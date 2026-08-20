"""
Alert rule engine.

Each rule is evaluated against a MarketData snapshot and may return a Signal
whose status is either "approaching" (the stock is *about to* meet the
criterion, within a proximity band) or "met" (the criterion is satisfied now).
Returning both states is what lets the app warn you *before* a level is hit, as
well as when it triggers.

Supported rule types (see config.example.yaml for the full schema):
    price_above / price_below   price crossing a level
    pct_move                    large daily percent move up/down
    rsi                         RSI overbought / oversold
    macd_cross                  MACD line crossing its signal line
    ma_cross                    fast SMA crossing a slow SMA (golden/death)
    bollinger                   price touching an upper/lower band
    near_52w_high / near_52w_low   approaching or breaking a 52-week extreme
    volume_spike                volume unusually high vs its average
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

import indicators as ind

APPROACHING = "approaching"
MET = "met"

# Sensible per-rule proximity defaults; each can be overridden per rule in config.
DEFAULTS = {
    "price_proximity_pct": 1.0,   # within 1% of a price level = "approaching"
    "rsi_proximity": 5.0,         # within 5 RSI points of the line
    "pct_move_approach_frac": 0.8,  # 80% of the way to the move threshold
    "cross_converge_pct": 0.3,    # lines within 0.3% of price and narrowing
    "bollinger_proximity_pct": 1.0,
    "band_52w_proximity_pct": 2.0,
    "volume_approach_frac": 0.8,
}


@dataclass
class MarketData:
    symbol: str
    last_price: float
    prev_close: float
    closes: pd.Series
    highs: pd.Series
    lows: pd.Series
    volumes: pd.Series
    year_high: float
    year_low: float
    avg_volume: float
    last_volume: float

    @property
    def day_change_pct(self) -> float:
        if not self.prev_close:
            return 0.0
        return (self.last_price - self.prev_close) / self.prev_close * 100.0


@dataclass
class Signal:
    symbol: str
    rule_id: str
    status: str            # APPROACHING or MET
    message: str
    value: float = 0.0     # current observed value (price, rsi, etc.)
    target: float = 0.0    # the configured threshold
    extra: dict = field(default_factory=dict)

    def key(self) -> str:
        return f"{self.symbol}:{self.rule_id}"


def _cfg(rule: dict, key: str, default):
    val = rule.get(key)
    return default if val is None else val


def rule_id(rule: dict) -> str:
    if rule.get("id"):
        return str(rule["id"])
    parts = [rule.get("type", "rule")]
    for k in ("target", "threshold", "period", "direction", "band", "level", "multiple"):
        if k in rule:
            parts.append(f"{k}={rule[k]}")
    return "_".join(str(p) for p in parts)


# --------------------------------------------------------------------------- #
# Individual rule evaluators. Each returns a Signal or None.
# --------------------------------------------------------------------------- #

def _price_threshold(md: MarketData, rule: dict, above: bool) -> Optional[Signal]:
    target = float(rule["target"])
    prox = float(_cfg(rule, "proximity_pct", DEFAULTS["price_proximity_pct"]))
    price = md.last_price
    rid = rule_id(rule)
    if above:
        if price >= target:
            return Signal(md.symbol, rid, MET, f"{md.symbol} crossed ABOVE ${target:g} (now ${price:g})", price, target)
        if price >= target * (1 - prox / 100):
            return Signal(md.symbol, rid, APPROACHING, f"{md.symbol} approaching ${target:g} from below (now ${price:g})", price, target)
    else:
        if price <= target:
            return Signal(md.symbol, rid, MET, f"{md.symbol} dropped BELOW ${target:g} (now ${price:g})", price, target)
        if price <= target * (1 + prox / 100):
            return Signal(md.symbol, rid, APPROACHING, f"{md.symbol} approaching ${target:g} from above (now ${price:g})", price, target)
    return None


def _pct_move(md: MarketData, rule: dict) -> Optional[Signal]:
    threshold = abs(float(rule["threshold"]))
    direction = _cfg(rule, "direction", "both")  # up | down | both
    frac = float(_cfg(rule, "approach_frac", DEFAULTS["pct_move_approach_frac"]))
    chg = md.day_change_pct
    rid = rule_id(rule)
    if direction == "up" and chg < 0:
        return None
    if direction == "down" and chg > 0:
        return None
    mag = abs(chg)
    arrow = "▲" if chg >= 0 else "▼"
    if mag >= threshold:
        return Signal(md.symbol, rid, MET, f"{md.symbol} {arrow} {chg:+.2f}% today (>= {threshold:g}%)", chg, threshold)
    if mag >= threshold * frac:
        return Signal(md.symbol, rid, APPROACHING, f"{md.symbol} {arrow} {chg:+.2f}% today, nearing {threshold:g}% move", chg, threshold)
    return None


def _rsi(md: MarketData, rule: dict) -> Optional[Signal]:
    period = int(_cfg(rule, "period", 14))
    prox = float(_cfg(rule, "proximity", DEFAULTS["rsi_proximity"]))
    series = ind.rsi(md.closes, period)
    if series.dropna().empty:
        return None
    val = float(series.dropna().iloc[-1])
    rid = rule_id(rule)
    lo = rule.get("oversold")
    hi = rule.get("overbought")
    if lo is not None:
        lo = float(lo)
        if val <= lo:
            return Signal(md.symbol, rid, MET, f"{md.symbol} RSI {val:.1f} oversold (<= {lo:g})", val, lo)
        if val <= lo + prox:
            return Signal(md.symbol, rid, APPROACHING, f"{md.symbol} RSI {val:.1f} nearing oversold ({lo:g})", val, lo)
    if hi is not None:
        hi = float(hi)
        if val >= hi:
            return Signal(md.symbol, rid, MET, f"{md.symbol} RSI {val:.1f} overbought (>= {hi:g})", val, hi)
        if val >= hi - prox:
            return Signal(md.symbol, rid, APPROACHING, f"{md.symbol} RSI {val:.1f} nearing overbought ({hi:g})", val, hi)
    return None


def _cross(md: MarketData, rule: dict, a: pd.Series, b: pd.Series, label: str,
           bullish_word: str, bearish_word: str) -> Optional[Signal]:
    """Shared cross logic for MACD and MA crosses (a crossing b)."""
    direction = _cfg(rule, "direction", "both")  # bullish | bearish | both
    conv = float(_cfg(rule, "converge_pct", DEFAULTS["cross_converge_pct"]))
    prev_a, cur_a = ind.last_two(a)
    prev_b, cur_b = ind.last_two(b)
    if any(pd.isna(x) for x in (prev_a, cur_a, prev_b, cur_b)):
        return None
    prev_diff = prev_a - prev_b
    cur_diff = cur_a - cur_b
    price = md.last_price or 1.0
    rid = rule_id(rule)

    want_bull = direction in ("bullish", "both")
    want_bear = direction in ("bearish", "both")

    if want_bull and prev_diff <= 0 and cur_diff > 0:
        return Signal(md.symbol, rid, MET, f"{md.symbol} {label} {bullish_word} cross", cur_diff, 0.0)
    if want_bear and prev_diff >= 0 and cur_diff < 0:
        return Signal(md.symbol, rid, MET, f"{md.symbol} {label} {bearish_word} cross", cur_diff, 0.0)

    # About to cross: lines converging and within a small band of each other.
    narrowing = abs(cur_diff) < abs(prev_diff)
    within_band = abs(cur_diff) / price * 100 <= conv
    if narrowing and within_band:
        if want_bull and cur_diff < 0:
            return Signal(md.symbol, rid, APPROACHING, f"{md.symbol} {label} converging toward a {bullish_word} cross", cur_diff, 0.0)
        if want_bear and cur_diff > 0:
            return Signal(md.symbol, rid, APPROACHING, f"{md.symbol} {label} converging toward a {bearish_word} cross", cur_diff, 0.0)
    return None


def _macd_cross(md: MarketData, rule: dict) -> Optional[Signal]:
    fast = int(_cfg(rule, "fast", 12))
    slow = int(_cfg(rule, "slow", 26))
    sig = int(_cfg(rule, "signal", 9))
    macd_line, signal_line, _ = ind.macd(md.closes, fast, slow, sig)
    return _cross(md, rule, macd_line, signal_line, "MACD", "bullish", "bearish")


def _ma_cross(md: MarketData, rule: dict) -> Optional[Signal]:
    fast = int(_cfg(rule, "fast", 50))
    slow = int(_cfg(rule, "slow", 200))
    fast_ma = ind.sma(md.closes, fast)
    slow_ma = ind.sma(md.closes, slow)
    return _cross(md, rule, fast_ma, slow_ma, f"{fast}/{slow} SMA", "golden", "death")


def _bollinger(md: MarketData, rule: dict) -> Optional[Signal]:
    period = int(_cfg(rule, "period", 20))
    num_std = float(_cfg(rule, "num_std", 2.0))
    prox = float(_cfg(rule, "proximity_pct", DEFAULTS["bollinger_proximity_pct"]))
    band = _cfg(rule, "band", "lower")  # lower | upper
    mid, upper, lower = ind.bollinger(md.closes, period, num_std)
    if mid.dropna().empty:
        return None
    price = md.last_price
    rid = rule_id(rule)
    if band == "lower":
        lo = float(lower.dropna().iloc[-1])
        if price <= lo:
            return Signal(md.symbol, rid, MET, f"{md.symbol} touched lower Bollinger band (${lo:g}, now ${price:g})", price, lo)
        if price <= lo * (1 + prox / 100):
            return Signal(md.symbol, rid, APPROACHING, f"{md.symbol} nearing lower Bollinger band (${lo:g}, now ${price:g})", price, lo)
    else:
        up = float(upper.dropna().iloc[-1])
        if price >= up:
            return Signal(md.symbol, rid, MET, f"{md.symbol} touched upper Bollinger band (${up:g}, now ${price:g})", price, up)
        if price >= up * (1 - prox / 100):
            return Signal(md.symbol, rid, APPROACHING, f"{md.symbol} nearing upper Bollinger band (${up:g}, now ${price:g})", price, up)
    return None


def _near_52w(md: MarketData, rule: dict, high: bool) -> Optional[Signal]:
    prox = float(_cfg(rule, "proximity_pct", DEFAULTS["band_52w_proximity_pct"]))
    price = md.last_price
    rid = rule_id(rule)
    if high:
        ref = md.year_high
        if not ref:
            return None
        if price >= ref:
            return Signal(md.symbol, rid, MET, f"{md.symbol} at a new 52-week high (${price:g})", price, ref)
        if price >= ref * (1 - prox / 100):
            return Signal(md.symbol, rid, APPROACHING, f"{md.symbol} within {prox:g}% of 52-wk high ${ref:g} (now ${price:g})", price, ref)
    else:
        ref = md.year_low
        if not ref:
            return None
        if price <= ref:
            return Signal(md.symbol, rid, MET, f"{md.symbol} at a new 52-week low (${price:g})", price, ref)
        if price <= ref * (1 + prox / 100):
            return Signal(md.symbol, rid, APPROACHING, f"{md.symbol} within {prox:g}% of 52-wk low ${ref:g} (now ${price:g})", price, ref)
    return None


def _volume_spike(md: MarketData, rule: dict) -> Optional[Signal]:
    multiple = float(_cfg(rule, "multiple", 2.0))
    frac = float(_cfg(rule, "approach_frac", DEFAULTS["volume_approach_frac"]))
    if not md.avg_volume:
        return None
    ratio = md.last_volume / md.avg_volume
    rid = rule_id(rule)
    if ratio >= multiple:
        return Signal(md.symbol, rid, MET, f"{md.symbol} volume {ratio:.1f}x average (>= {multiple:g}x)", ratio, multiple)
    if ratio >= multiple * frac:
        return Signal(md.symbol, rid, APPROACHING, f"{md.symbol} volume {ratio:.1f}x average, nearing {multiple:g}x", ratio, multiple)
    return None


_DISPATCH = {
    "price_above": lambda md, r: _price_threshold(md, r, above=True),
    "price_below": lambda md, r: _price_threshold(md, r, above=False),
    "pct_move": _pct_move,
    "rsi": _rsi,
    "macd_cross": _macd_cross,
    "ma_cross": _ma_cross,
    "bollinger": _bollinger,
    "near_52w_high": lambda md, r: _near_52w(md, r, high=True),
    "near_52w_low": lambda md, r: _near_52w(md, r, high=False),
    "volume_spike": _volume_spike,
}


def evaluate(md: MarketData, rules: list[dict]) -> list[Signal]:
    """Evaluate every rule for one symbol; return the signals that fired."""
    signals: list[Signal] = []
    for rule in rules:
        rtype = rule.get("type")
        fn = _DISPATCH.get(rtype)
        if fn is None:
            continue
        try:
            sig = fn(md, rule)
        except Exception as exc:  # a bad rule must not kill the whole run
            sig = None
            print(f"[warn] rule {rtype} for {md.symbol} raised: {exc}")
        if sig is not None:
            signals.append(sig)
    return signals


def supported_types() -> list[str]:
    return sorted(_DISPATCH.keys())
