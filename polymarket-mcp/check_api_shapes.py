"""
Connectivity and response-shape diagnostic for the Polymarket US API.

Run this once against real credentials before trusting the exposure guardrails.
It prints the FIELD NAMES returned by the balances and positions endpoints so the
mappings in server.py can be confirmed against the live service.

Values are redacted by default — only the shapes are needed. Pass --show-values
if you want the actual numbers printed too.

Usage:
    export POLYMARKET_KEY_ID=...            # or: set -a && source .env && set +a
    export POLYMARKET_SECRET_KEY=...
    python check_api_shapes.py
    python check_api_shapes.py --show-values
"""

import json
import os
import sys

try:
    from polymarket_us import PolymarketUS
except ImportError:
    sys.exit("polymarket-us is not installed. Run: pip install -r requirements.txt")

SHOW_VALUES = "--show-values" in sys.argv


def _redact(obj, depth=0):
    """Replace leaf values with their type name so only structure is shown."""
    if SHOW_VALUES:
        return obj
    if isinstance(obj, dict):
        return {k: _redact(v, depth + 1) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact(v, depth + 1) for v in obj[:1]] + (
            [f"...({len(obj)} total)"] if len(obj) > 1 else []
        )
    return f"<{type(obj).__name__}>"


def _show(label, obj):
    print(f"\n--- {label} ---")
    if isinstance(obj, dict):
        print("top-level keys:", list(obj.keys()))
    print(json.dumps(_redact(obj), indent=2, default=str)[:1200])


def main() -> int:
    print("Polymarket US API diagnostic")
    print("=" * 60)

    # 1. Public endpoint — no credentials, proves network + SDK work.
    print("\n[1/3] Public endpoint (no auth)...")
    try:
        sports = PolymarketUS().sports.list()
        count = len(sports.get("sports", [])) if isinstance(sports, dict) else "?"
        print(f"  OK — reached the gateway, {count} sports returned.")
    except Exception as e:
        print(f"  FAILED: {type(e).__name__}: {e}")
        print("  Network or the gateway is unreachable. Nothing else will work.")
        return 1

    # 2. Credentials
    print("\n[2/3] Credentials...")
    key_id = os.environ.get("POLYMARKET_KEY_ID")
    secret = os.environ.get("POLYMARKET_SECRET_KEY")
    if not key_id or not secret:
        print("  MISSING: set POLYMARKET_KEY_ID and POLYMARKET_SECRET_KEY.")
        print("  From this directory:  set -a && source .env && set +a")
        return 1
    print(f"  key id: {key_id[:8]}...{key_id[-4:]}  secret: {len(secret)} chars")

    client = PolymarketUS(key_id=key_id, secret_key=secret)

    # 3. Authenticated endpoints — the shapes we actually need.
    print("\n[3/3] Authenticated endpoints...")
    try:
        balances = client.account.balances()
    except Exception as e:
        print(f"  FAILED on balances: {type(e).__name__}: {e}")
        print("  Usual causes: wrong secret, or system clock skew (the timestamp")
        print("  is signed, so a badly-off clock fails signature validation).")
        return 1
    _show("account.balances()", balances)

    try:
        positions = client.portfolio.positions({"limit": 5})
    except Exception as e:
        print(f"  FAILED on positions: {type(e).__name__}: {e}")
        return 1
    _show("portfolio.positions()", positions)

    rows = positions.get("positions", []) if isinstance(positions, dict) else []
    if rows:
        print("\n--- one position, key names ---")
        print(list(rows[0].keys()))
    else:
        print("\n(no open positions — position field names can't be confirmed yet)")

    # What server.py currently looks for.
    print("\n" + "=" * 60)
    print("Field mapping check (what server.py expects):")
    bal_keys = set(balances.keys()) if isinstance(balances, dict) else set()
    expected_bal = {"availableBalance", "cash", "buyingPower"}
    hit = bal_keys & expected_bal
    print(f"  balances  : looking for any of {sorted(expected_bal)}")
    print(f"              found -> {sorted(hit) if hit else 'NONE — mapping is WRONG'}")

    if rows:
        pos_keys = set(rows[0].keys())
        expected_pos = {"avgPrice", "avgPx"}
        hit_p = pos_keys & expected_pos
        print(f"  positions : looking for any of {sorted(expected_pos)}")
        print(f"              found -> {sorted(hit_p) if hit_p else 'NONE — mapping is WRONG'}")
        slug_hit = pos_keys & {"marketSlug", "market"}
        print(f"  slug field: found -> {sorted(slug_hit) if slug_hit else 'NONE — mapping is WRONG'}")

    if not hit or (rows and not (set(rows[0].keys()) & {"avgPrice", "avgPx"})):
        print("\n  WARNING: a mapping above is wrong. When that happens the code does")
        print("  not crash — it reads cash/exposure as $0, which makes the exposure")
        print("  guardrails wave everything through. Paste this output back to fix it.")
    else:
        print("\n  All mappings resolved. Exposure guardrails will read real values.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
