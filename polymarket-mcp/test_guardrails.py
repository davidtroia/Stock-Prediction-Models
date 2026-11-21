"""
Offline tests for the Polymarket MCP guardrails.

These exercise every rejection path without credentials or network access.
Buy-side cases are all constructed to fail a local check first, so the
account-state lookup is never reached (see _check_guardrails).

Run:  python test_guardrails.py       (or: pytest test_guardrails.py)
"""

import os

# Pin a known guardrail config before importing the server.
os.environ.update({
    "MAX_SINGLE_ORDER_USD": "50",
    "MAX_MARKET_EXPOSURE_USD": "100",
    "MAX_TOTAL_EXPOSURE_USD": "500",
    "MIN_CASH_RESERVE_USD": "25",
    "MAX_OPEN_POSITIONS": "10",
    "MIN_PRICE": "0.05",
    "MAX_PRICE": "0.95",
    "MAX_SLIPPAGE_BIPS": "200",
    "BLOCKED_MARKET_SLUGS": "rigged-market,banned-market",
    "BLOCKED_CATEGORIES": "politics",
    "ALLOWED_CATEGORIES": "",
})

import server  # noqa: E402

BUY = "ORDER_INTENT_BUY_LONG"
SELL = "ORDER_INTENT_SELL_LONG"


def _blocked_reasons(result):
    assert result["ok"] is False, f"expected block, got {result}"
    return " | ".join(result["blocked_by"])


def test_price_outside_probability_range_is_rejected():
    for bad_price in (0.0, 1.0, 1.5, -0.2):
        reasons = _blocked_reasons(server._check_guardrails("m", bad_price, 10, SELL))
        assert "outside the valid range" in reasons, reasons


def test_longshot_buy_below_min_price_blocked():
    reasons = _blocked_reasons(server._check_guardrails("m", 0.01, 10, BUY))
    assert "below MIN_PRICE" in reasons, reasons


def test_near_certainty_buy_above_max_price_blocked():
    reasons = _blocked_reasons(server._check_guardrails("m", 0.99, 10, BUY))
    assert "above MAX_PRICE" in reasons, reasons


def test_extreme_price_guard_does_not_block_exits():
    """Selling at 0.99 is taking profit, not a bad buy — must be allowed through
    the extreme-price guard. (Sells skip account checks entirely.)"""
    result = server._check_guardrails("m", 0.99, 10, SELL)
    assert result["ok"] is True, result
    result = server._check_guardrails("m", 0.01, 10, SELL)
    assert result["ok"] is True, result


def test_single_order_notional_cap():
    # 0.60 * 100 = $60 notional, over the $50 cap
    reasons = _blocked_reasons(server._check_guardrails("m", 0.60, 100, SELL))
    assert "exceeds MAX_SINGLE_ORDER_USD" in reasons, reasons

    # 0.40 * 100 = $40, under the cap
    assert server._check_guardrails("m", 0.40, 100, SELL)["ok"] is True


def test_blocked_market_slug():
    reasons = _blocked_reasons(server._check_guardrails("rigged-market", 0.5, 10, SELL))
    assert "blocked markets list" in reasons, reasons


def test_blocked_market_slug_is_case_insensitive():
    reasons = _blocked_reasons(server._check_guardrails("RIGGED-MARKET", 0.5, 10, SELL))
    assert "blocked markets list" in reasons, reasons


def test_blocked_category():
    reasons = _blocked_reasons(
        server._check_guardrails("m", 0.5, 10, SELL, categories=["Politics"])
    )
    assert "blocked categories list" in reasons, reasons


def test_allowed_category_whitelist(monkeypatch_env=None):
    os.environ["ALLOWED_CATEGORIES"] = "sports,economics"
    try:
        # A category outside the whitelist is rejected...
        reasons = _blocked_reasons(
            server._check_guardrails("m", 0.5, 10, SELL, categories=["crypto"])
        )
        assert "not on the allowed categories whitelist" in reasons, reasons
        # ...and one inside it passes.
        assert server._check_guardrails("m", 0.5, 10, SELL, categories=["sports"])["ok"] is True
    finally:
        os.environ["ALLOWED_CATEGORIES"] = ""


def test_multiple_violations_are_all_reported():
    """A blocked slug at an invalid price should report both, not just the first."""
    result = server._check_guardrails("rigged-market", 0.99, 500, BUY)
    reasons = _blocked_reasons(result)
    assert "blocked markets list" in reasons, reasons
    assert "above MAX_PRICE" in reasons, reasons
    assert "exceeds MAX_SINGLE_ORDER_USD" in reasons, reasons


def test_passing_check_returns_risk_math():
    result = server._check_guardrails("m", 0.25, 100, SELL)
    assert result["ok"] is True, result
    assert result["notional_usd"] == 25.0, result


def test_position_exposure_uses_cost_basis():
    positions = [
        {"marketSlug": "a", "quantity": 100, "avgPrice": {"value": "0.40", "currency": "USD"}},
        {"marketSlug": "b", "quantity": 50, "avgPrice": {"value": "0.20", "currency": "USD"}},
        {"marketSlug": "a", "quantity": 25, "avgPrice": {"value": "0.60", "currency": "USD"}},
    ]
    exposure = server._position_exposure(positions)
    assert exposure["by_market"]["a"] == 55.0, exposure  # 40 + 15
    assert exposure["by_market"]["b"] == 10.0, exposure
    assert exposure["total"] == 65.0, exposure


def test_position_exposure_handles_empty_and_malformed():
    assert server._position_exposure([])["total"] == 0.0
    assert server._position_exposure(None)["total"] == 0.0
    # A position with no slug is skipped rather than crashing.
    assert server._position_exposure([{"quantity": 10}])["total"] == 0.0


def test_amount_formatting():
    assert server._amount(0.55) == {"value": "0.55", "currency": "USD"}
    assert server._amount("0.5") == {"value": "0.50", "currency": "USD"}
    assert server._amount(1) == {"value": "1.00", "currency": "USD"}


def test_amount_roundtrip():
    assert server._amount_to_float(server._amount(0.37)) == 0.37
    assert server._amount_to_float(None) == 0.0
    assert server._amount_to_float({}) == 0.0
    assert server._amount_to_float({"value": "not-a-number"}) == 0.0


def test_orders_are_flagged_automatic_by_default():
    os.environ.pop("POLYMARKET_MARK_ORDERS_MANUAL", None)
    assert server._manual_indicator() == "MANUAL_ORDER_INDICATOR_AUTOMATIC"
    os.environ["POLYMARKET_MARK_ORDERS_MANUAL"] = "true"
    try:
        assert server._manual_indicator() == "MANUAL_ORDER_INDICATOR_MANUAL"
    finally:
        os.environ.pop("POLYMARKET_MARK_ORDERS_MANUAL", None)


def test_guardrails_reload_from_env_without_restart():
    """Limits are read at call time, so a changed env var takes effect immediately."""
    assert server._load_guardrails()["max_single_order_usd"] == 50
    os.environ["MAX_SINGLE_ORDER_USD"] = "10"
    try:
        assert server._load_guardrails()["max_single_order_usd"] == 10
        reasons = _blocked_reasons(server._check_guardrails("m", 0.50, 40, SELL))
        assert "exceeds MAX_SINGLE_ORDER_USD" in reasons, reasons
    finally:
        os.environ["MAX_SINGLE_ORDER_USD"] = "50"


def test_malformed_env_falls_back_to_default():
    os.environ["MAX_SINGLE_ORDER_USD"] = "not-a-number"
    try:
        assert server._load_guardrails()["max_single_order_usd"] == 50
    finally:
        os.environ["MAX_SINGLE_ORDER_USD"] = "50"


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    passed = failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS  {name}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL  {name}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR {name}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed, {len(tests)} total")
    raise SystemExit(1 if failed else 0)
