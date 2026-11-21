"""
Polymarket US Trading MCP Server

Provides MCP tools for reading Polymarket US prediction markets and trading them.
Authentication uses environment variables: POLYMARKET_KEY_ID and POLYMARKET_SECRET_KEY
(create both at https://polymarket.us/developer).

Market-data tools are public and work without credentials. Account and trading tools
require credentials and are additionally gated by the guardrails below.

Prediction-market pricing model
-------------------------------
A share costs between $0.00 and $1.00 and settles at exactly $0.00 or $1.00.
The price is therefore the market-implied probability of the outcome:

    notional paid  = price * quantity
    max payout     = quantity * $1.00
    max loss (long)= price * quantity          (you cannot lose more than you paid)
    profit if right= (1.00 - price) * quantity

This bounded downside is why the guardrails here are denominated in dollars of
notional rather than the percentage-of-portfolio limits used for equities.
"""

import os
import json
from typing import Optional

from mcp.server.fastmcp import FastMCP
from polymarket_us import (
    PolymarketUS,
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    NotFoundError,
    PolymarketUSError,
    RateLimitError,
)

mcp = FastMCP("polymarket-trading")

# ---------------------------------------------------------------------------
# Client construction
# ---------------------------------------------------------------------------
_public_client: Optional[PolymarketUS] = None
_auth_client: Optional[PolymarketUS] = None


def _public() -> PolymarketUS:
    """Client for public endpoints. Never needs credentials."""
    global _public_client
    if _public_client is None:
        _public_client = PolymarketUS()
    return _public_client


def _authed() -> PolymarketUS:
    """Client for account/trading endpoints. Requires credentials."""
    global _auth_client
    if _auth_client is not None:
        return _auth_client
    key_id = os.environ.get("POLYMARKET_KEY_ID")
    secret_key = os.environ.get("POLYMARKET_SECRET_KEY")
    if not key_id or not secret_key:
        raise EnvironmentError(
            "POLYMARKET_KEY_ID and POLYMARKET_SECRET_KEY environment variables must be "
            "set. Create an API key at https://polymarket.us/developer — the secret is "
            "shown only once."
        )
    _auth_client = PolymarketUS(key_id=key_id, secret_key=secret_key)
    return _auth_client


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def _j(obj) -> str:
    """Serialize an SDK response (TypedDicts are plain dicts at runtime)."""
    return json.dumps(obj, indent=2, default=str)


def _err(e: Exception) -> str:
    """Render an SDK exception as a structured, actionable error payload."""
    kind = {
        AuthenticationError: "authentication_error",
        BadRequestError: "bad_request",
        NotFoundError: "not_found",
        RateLimitError: "rate_limited",
        APITimeoutError: "timeout",
        APIConnectionError: "connection_error",
    }.get(type(e), "error")
    hint = {
        "authentication_error": "Check POLYMARKET_KEY_ID / POLYMARKET_SECRET_KEY. The "
                                "secret is base64-encoded Ed25519 and is shown only once "
                                "at creation.",
        "not_found": "Check the market slug — use search_markets to find the exact slug.",
        "rate_limited": "Back off and retry.",
    }.get(kind)
    out = {"ok": False, "error_type": kind, "message": str(e)}
    if hint:
        out["hint"] = hint
    return _j(out)


def _amount(value: float | str) -> dict:
    """Build the SDK's Amount shape. Prices carry 2dp; USD is the only currency."""
    return {"value": f"{float(value):.2f}", "currency": "USD"}


def _amount_to_float(amount) -> float:
    """Read a possibly-missing Amount back to a float."""
    if not amount:
        return 0.0
    if isinstance(amount, dict):
        try:
            return float(amount.get("value") or 0)
        except (TypeError, ValueError):
            return 0.0
    try:
        return float(amount)
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# Guardrails — loaded from env vars, with safe defaults
# ---------------------------------------------------------------------------

def _load_guardrails() -> dict:
    """
    Read trading limits from environment variables. If not set, conservative
    defaults are used. All limits are enforced before any order is placed.

    Configure in your .env file:
        MAX_SINGLE_ORDER_USD=50       # max notional of any single order
        MAX_MARKET_EXPOSURE_USD=100   # max total notional at risk in one market
        MAX_TOTAL_EXPOSURE_USD=500    # max total notional at risk across all markets
        MIN_CASH_RESERVE_USD=25       # always keep this much cash uncommitted
        DAILY_LOSS_LIMIT_USD=50       # halt new buys after losing this much today
        MAX_OPEN_POSITIONS=10         # max distinct markets held at once
        MIN_PRICE=0.05                # refuse to buy below this implied probability
        MAX_PRICE=0.95                # refuse to buy above this implied probability
        MAX_SLIPPAGE_BIPS=200         # max slippage tolerance on market orders
        ALLOWED_CATEGORIES=           # comma-separated whitelist, empty = all allowed
        BLOCKED_CATEGORIES=           # comma-separated blacklist, always blocked
        BLOCKED_MARKET_SLUGS=         # comma-separated slugs to never trade
    """
    def _num(key, default):
        try:
            return float(os.environ.get(key, default))
        except (TypeError, ValueError):
            return float(default)

    def _csv(key):
        return [s.strip().lower() for s in os.environ.get(key, "").split(",") if s.strip()]

    return {
        "max_single_order_usd":    _num("MAX_SINGLE_ORDER_USD", 50),
        "max_market_exposure_usd": _num("MAX_MARKET_EXPOSURE_USD", 100),
        "max_total_exposure_usd":  _num("MAX_TOTAL_EXPOSURE_USD", 500),
        "min_cash_reserve_usd":    _num("MIN_CASH_RESERVE_USD", 25),
        "daily_loss_limit_usd":    _num("DAILY_LOSS_LIMIT_USD", 50),
        "max_open_positions":      int(_num("MAX_OPEN_POSITIONS", 10)),
        "min_price":               _num("MIN_PRICE", 0.05),
        "max_price":               _num("MAX_PRICE", 0.95),
        "max_slippage_bips":       int(_num("MAX_SLIPPAGE_BIPS", 200)),
        "allowed_categories":      _csv("ALLOWED_CATEGORIES"),
        "blocked_categories":      _csv("BLOCKED_CATEGORIES"),
        "blocked_market_slugs":    _csv("BLOCKED_MARKET_SLUGS"),
    }


def _position_exposure(positions: list) -> dict:
    """
    Map market slug -> dollars currently at risk, and return the total.

    Exposure is cost basis (what was paid), not mark-to-market value, because
    cost basis is the actual maximum loss on a long prediction-market position.
    """
    by_market: dict[str, float] = {}
    for pos in positions or []:
        slug = pos.get("marketSlug") or pos.get("market") or ""
        if not slug:
            continue
        qty = float(pos.get("quantity") or 0)
        avg = _amount_to_float(pos.get("avgPrice") or pos.get("avgPx"))
        by_market[slug] = by_market.get(slug, 0.0) + abs(qty * avg)
    return {"by_market": by_market, "total": sum(by_market.values())}


def _check_guardrails(
    market_slug: str,
    price: float,
    quantity: int,
    intent: str,
    categories: Optional[list] = None,
) -> dict:
    """
    Validate a proposed order against all active guardrails.
    Returns {"ok": True, ...} if safe, or {"ok": False, "blocked_by": [...]} if not.
    Called internally before every order-placing function.
    """
    limits = _load_guardrails()
    blocks = []
    slug = (market_slug or "").lower()
    notional = price * quantity
    is_buy = intent in ("ORDER_INTENT_BUY_LONG", "ORDER_INTENT_BUY_SHORT")

    # 1. Blocked market check
    if slug in limits["blocked_market_slugs"]:
        blocks.append(f"{market_slug} is on the blocked markets list")

    # 2. Category checks
    cats = [str(c).lower() for c in (categories or [])]
    if cats:
        hit = [c for c in cats if c in limits["blocked_categories"]]
        if hit:
            blocks.append(f"Market category {hit} is on the blocked categories list")
        if limits["allowed_categories"] and not any(c in limits["allowed_categories"] for c in cats):
            blocks.append(
                f"Market categories {cats} are not on the allowed categories "
                f"whitelist: {limits['allowed_categories']}"
            )

    # 3. Price sanity — a price outside (0, 1) is not a valid probability
    if not (0.0 < price < 1.0):
        blocks.append(f"Price {price} is outside the valid range (0.00, 1.00)")

    # 4. Extreme-probability guard (buys only — always allowed to exit)
    if is_buy:
        if price < limits["min_price"]:
            blocks.append(
                f"Price {price:.2f} is below MIN_PRICE ({limits['min_price']:.2f}) — "
                f"longshot bets are blocked"
            )
        if price > limits["max_price"]:
            blocks.append(
                f"Price {price:.2f} is above MAX_PRICE ({limits['max_price']:.2f}) — "
                f"paying near-certainty for thin edge is blocked"
            )

    # 5. Single order size cap
    if notional > limits["max_single_order_usd"]:
        blocks.append(
            f"Order notional ${notional:.2f} exceeds MAX_SINGLE_ORDER_USD "
            f"(${limits['max_single_order_usd']:.2f})"
        )

    # Remaining checks need account state, and only constrain new risk.
    # Skipped when the order is already blocked: the verdict cannot change, and
    # a needless network call would add a confusing second failure reason.
    if is_buy and not blocks:
        try:
            client = _authed()
            balances = client.account.balances()
            positions_resp = client.portfolio.positions()
        except Exception as e:
            blocks.append(f"Could not verify account state for guardrails: {e}")
            return {"ok": False, "blocked_by": blocks}

        positions = positions_resp.get("positions", []) if isinstance(positions_resp, dict) else []
        cash = _amount_to_float(
            balances.get("availableBalance") or balances.get("cash") or balances.get("buyingPower")
        )
        exposure = _position_exposure(positions)

        # 6. Cash reserve check
        cash_after = cash - notional
        if cash_after < limits["min_cash_reserve_usd"]:
            blocks.append(
                f"Order would leave ${cash_after:.2f} cash, below the "
                f"MIN_CASH_RESERVE_USD floor (${limits['min_cash_reserve_usd']:.2f})"
            )

        # 7. Per-market exposure cap
        market_after = exposure["by_market"].get(market_slug, 0.0) + notional
        if market_after > limits["max_market_exposure_usd"]:
            blocks.append(
                f"Order would put ${market_after:.2f} at risk in {market_slug}, "
                f"exceeding MAX_MARKET_EXPOSURE_USD (${limits['max_market_exposure_usd']:.2f})"
            )

        # 8. Total exposure cap
        total_after = exposure["total"] + notional
        if total_after > limits["max_total_exposure_usd"]:
            blocks.append(
                f"Order would put ${total_after:.2f} at risk across all markets, "
                f"exceeding MAX_TOTAL_EXPOSURE_USD (${limits['max_total_exposure_usd']:.2f})"
            )

        # 9. Open position count cap — only blocks opening a *new* market
        if market_slug not in exposure["by_market"]:
            if len(exposure["by_market"]) >= limits["max_open_positions"]:
                blocks.append(
                    f"Already holding {len(exposure['by_market'])} markets, at the "
                    f"MAX_OPEN_POSITIONS cap ({limits['max_open_positions']}). "
                    f"Close something before opening a new market."
                )

    if blocks:
        return {"ok": False, "blocked_by": blocks}
    return {
        "ok": True,
        "notional_usd": round(notional, 2),
        "max_loss_usd": round(notional, 2) if is_buy else None,
        "max_payout_usd": round(quantity * 1.0, 2) if is_buy else None,
    }


# ---------------------------------------------------------------------------
# Market data (public — no credentials required)
# ---------------------------------------------------------------------------

@mcp.tool()
def search_markets(query: str, limit: int = 10) -> str:
    """
    Full-text search across Polymarket US markets and events.

    Start here when you know the topic but not the slug — every trading tool is
    keyed by market slug, and this is how you find it.

    Args:
        query: Free-text search, e.g. "super bowl" or "fed rate cut".
        limit: Maximum results to return (default 10).
    """
    try:
        return _j(_public().search.query({"query": query, "limit": limit}))
    except Exception as e:
        return _err(e)


@mcp.tool()
def list_events(
    limit: int = 20,
    active: bool = True,
    closed: bool = False,
    tag_slug: Optional[str] = None,
    volume_min: Optional[float] = None,
    order_by: str = "volume",
    order_direction: str = "desc",
) -> str:
    """
    List events (an event groups related markets, e.g. one game or one election).

    Args:
        limit: Max events to return.
        active: Only currently active events.
        closed: Include closed events.
        tag_slug: Filter by tag, e.g. "politics" or "sports".
        volume_min: Only events with at least this much traded volume.
        order_by: Sort field, e.g. "volume" or "liquidity".
        order_direction: "asc" or "desc".
    """
    params: dict = {
        "limit": limit,
        "active": active,
        "closed": closed,
        "orderBy": [order_by],
        "orderDirection": order_direction,
    }
    if tag_slug:
        params["tagSlug"] = tag_slug
    if volume_min is not None:
        params["volumeMin"] = volume_min
    try:
        return _j(_public().events.list(params))
    except Exception as e:
        return _err(e)


@mcp.tool()
def get_event(slug: str) -> str:
    """
    Fetch one event and all the markets inside it, by slug.

    Args:
        slug: Event slug, e.g. "super-bowl-2026".
    """
    try:
        return _j(_public().events.retrieve_by_slug(slug))
    except Exception as e:
        return _err(e)


@mcp.tool()
def list_markets(
    limit: int = 20,
    active: bool = True,
    closed: bool = False,
    event_slug: Optional[str] = None,
    liquidity_min: Optional[float] = None,
    volume_min: Optional[float] = None,
    order_by: str = "volume",
    order_direction: str = "desc",
) -> str:
    """
    List individual markets, with optional liquidity and volume filters.

    Filtering on liquidity_min is the single most useful screen before trading —
    a market with a wide book will cost more in slippage than most edges are worth.

    Args:
        limit: Max markets to return.
        active: Only currently active markets.
        closed: Include closed markets.
        event_slug: Restrict to markets within one event.
        liquidity_min: Minimum resting liquidity.
        volume_min: Minimum traded volume.
        order_by: Sort field, e.g. "volume" or "liquidity".
        order_direction: "asc" or "desc".
    """
    params: dict = {
        "limit": limit,
        "active": active,
        "closed": closed,
        "orderBy": [order_by],
        "orderDirection": order_direction,
    }
    if event_slug:
        params["eventSlug"] = [event_slug]
    if liquidity_min is not None:
        params["liquidityMin"] = liquidity_min
    if volume_min is not None:
        params["volumeMin"] = volume_min
    try:
        return _j(_public().markets.list(params))
    except Exception as e:
        return _err(e)


@mcp.tool()
def get_market(slug: str) -> str:
    """
    Fetch full detail for one market by slug, including its resolution criteria.

    Args:
        slug: Market slug, e.g. "chiefs-super-bowl".
    """
    try:
        return _j(_public().markets.retrieve_by_slug(slug))
    except Exception as e:
        return _err(e)


@mcp.tool()
def get_book(slug: str) -> str:
    """
    Fetch the full order book (all bid and offer levels) for a market.

    Use this rather than get_quote when order size is large enough to walk the
    book — the top level alone will overstate how much you can actually fill.

    Args:
        slug: Market slug.
    """
    try:
        return _j(_public().markets.book(slug))
    except Exception as e:
        return _err(e)


@mcp.tool()
def get_quote(slug: str) -> str:
    """
    Fetch best bid/offer for a market, annotated with spread and implied probability.

    Returns the raw BBO plus derived fields: spread in cents and in percent,
    the mid price, and the implied probability of each side.

    Args:
        slug: Market slug.
    """
    try:
        bbo = _public().markets.bbo(slug)
    except Exception as e:
        return _err(e)

    bid = _amount_to_float(bbo.get("bestBid"))
    ask = _amount_to_float(bbo.get("bestAsk"))
    out = dict(bbo)
    if bid > 0 and ask > 0:
        mid = (bid + ask) / 2
        spread = ask - bid
        out["derived"] = {
            "mid": round(mid, 4),
            "spread_cents": round(spread * 100, 2),
            "spread_pct_of_mid": round(spread / mid * 100, 2) if mid else None,
            "implied_probability_yes": round(mid, 4),
            "implied_probability_no": round(1 - mid, 4),
            "cost_to_cross_per_100_shares": round(spread * 100, 2),
        }
    return _j(out)


@mcp.tool()
def get_settlement(slug: str) -> str:
    """
    Fetch settlement detail for a market — how and to what value it resolved.

    Args:
        slug: Market slug.
    """
    try:
        return _j(_public().markets.settlement(slug))
    except Exception as e:
        return _err(e)


@mcp.tool()
def list_sports() -> str:
    """List sports available on Polymarket US, for building sports market queries."""
    try:
        return _j(_public().sports.list())
    except Exception as e:
        return _err(e)


@mcp.tool()
def list_series(limit: int = 20) -> str:
    """
    List market series (a series groups recurring events, e.g. a whole season).

    Args:
        limit: Max series to return.
    """
    try:
        return _j(_public().series.list({"limit": limit}))
    except Exception as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Account (requires credentials)
# ---------------------------------------------------------------------------

@mcp.tool()
def get_balances() -> str:
    """Fetch account cash balances and buying power."""
    try:
        return _j(_authed().account.balances())
    except Exception as e:
        return _err(e)


@mcp.tool()
def get_positions(market: Optional[str] = None, limit: int = 50) -> str:
    """
    Fetch open positions.

    Args:
        market: Optional market slug to filter to one market.
        limit: Max positions to return.
    """
    params: dict = {"limit": limit}
    if market:
        params["market"] = market
    try:
        return _j(_authed().portfolio.positions(params))
    except Exception as e:
        return _err(e)


@mcp.tool()
def get_activities(limit: int = 50) -> str:
    """
    Fetch account activity history — fills, settlements, transfers.

    Args:
        limit: Max activity records to return.
    """
    try:
        return _j(_authed().portfolio.activities({"limit": limit}))
    except Exception as e:
        return _err(e)


@mcp.tool()
def list_open_orders(slugs: Optional[list] = None) -> str:
    """
    List currently open (unfilled or partially filled) orders.

    Args:
        slugs: Optional list of market slugs to filter by.
    """
    params: dict = {}
    if slugs:
        params["slugs"] = slugs
    try:
        return _j(_authed().orders.list(params or None))
    except Exception as e:
        return _err(e)


@mcp.tool()
def get_order(order_id: str) -> str:
    """
    Fetch one order by ID, including fill state and average fill price.

    Args:
        order_id: The order's ID.
    """
    try:
        return _j(_authed().orders.retrieve(order_id))
    except Exception as e:
        return _err(e)


@mcp.tool()
def portfolio_summary() -> str:
    """
    Summarize the account: cash, exposure by market, total at risk, and headroom
    remaining under each configured guardrail.

    This is the fastest way to answer "what am I holding and how much room is left?"
    """
    try:
        client = _authed()
        balances = client.account.balances()
        positions_resp = client.portfolio.positions({"limit": 200})
    except Exception as e:
        return _err(e)

    positions = positions_resp.get("positions", []) if isinstance(positions_resp, dict) else []
    limits = _load_guardrails()
    exposure = _position_exposure(positions)
    cash = _amount_to_float(
        balances.get("availableBalance") or balances.get("cash") or balances.get("buyingPower")
    )

    return _j({
        "cash_usd": round(cash, 2),
        "total_at_risk_usd": round(exposure["total"], 2),
        "open_market_count": len(exposure["by_market"]),
        "exposure_by_market": {k: round(v, 2) for k, v in exposure["by_market"].items()},
        "headroom": {
            "total_exposure_remaining_usd": round(
                max(0.0, limits["max_total_exposure_usd"] - exposure["total"]), 2),
            "open_position_slots_remaining": max(
                0, limits["max_open_positions"] - len(exposure["by_market"])),
            "cash_above_reserve_usd": round(
                max(0.0, cash - limits["min_cash_reserve_usd"]), 2),
        },
        "limits": limits,
        "raw_balances": balances,
    })


@mcp.tool()
def get_trading_limits() -> str:
    """
    Show the currently active guardrails and where they come from.

    Every limit is read from an environment variable at call time, so changing a
    value in .env and restarting the server updates it.
    """
    return _j({
        "limits": _load_guardrails(),
        "note": "Set these in .env. All are enforced before any order is placed.",
        "env_vars": [
            "MAX_SINGLE_ORDER_USD", "MAX_MARKET_EXPOSURE_USD", "MAX_TOTAL_EXPOSURE_USD",
            "MIN_CASH_RESERVE_USD", "DAILY_LOSS_LIMIT_USD", "MAX_OPEN_POSITIONS",
            "MIN_PRICE", "MAX_PRICE", "MAX_SLIPPAGE_BIPS",
            "ALLOWED_CATEGORIES", "BLOCKED_CATEGORIES", "BLOCKED_MARKET_SLUGS",
        ],
    })


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

@mcp.tool()
def check_order(market_slug: str, price: float, quantity: int, intent: str = "ORDER_INTENT_BUY_LONG") -> str:
    """
    Run a proposed order through the guardrails WITHOUT sending anything to the
    exchange. Returns the risk math and any blocking reasons.

    Use this to explain why an order would be rejected before attempting it.

    Args:
        market_slug: Market slug.
        price: Limit price per share, 0.00-1.00.
        quantity: Number of shares.
        intent: One of ORDER_INTENT_BUY_LONG, ORDER_INTENT_SELL_LONG,
                ORDER_INTENT_BUY_SHORT, ORDER_INTENT_SELL_SHORT.
    """
    try:
        check = _check_guardrails(market_slug, price, quantity, intent)
    except Exception as e:
        return _err(e)
    return _j({
        "market_slug": market_slug,
        "intent": intent,
        "price": price,
        "quantity": quantity,
        "guardrail_check": check,
    })


@mcp.tool()
def analyze_edge(market_slug: str, your_probability: float, quantity: int = 100) -> str:
    """
    Compare your own probability estimate against the market's implied price and
    report expected value, edge, and Kelly-optimal sizing.

    The market price IS the implied probability, so edge is simply the gap between
    your estimate and that price, net of the spread you must cross to get filled.

    Args:
        market_slug: Market slug.
        your_probability: Your estimate of the outcome, 0.0-1.0.
        quantity: Share count to size the dollar figures against.
    """
    if not (0.0 <= your_probability <= 1.0):
        return _j({"ok": False, "error": "your_probability must be between 0.0 and 1.0"})
    try:
        bbo = _public().markets.bbo(market_slug)
    except Exception as e:
        return _err(e)

    bid = _amount_to_float(bbo.get("bestBid"))
    ask = _amount_to_float(bbo.get("bestAsk"))
    if ask <= 0:
        return _j({"ok": False, "error": "No offer available; market may be closed or empty."})

    p = your_probability
    # To buy YES you pay the ask; that is the real cost of expressing the view.
    cost = ask
    ev_per_share = p * (1.0 - cost) - (1.0 - p) * cost   # = p - cost
    edge = p - cost

    # Kelly for a binary contract bought at `cost` paying 1.0:
    #   b = (1 - cost) / cost  (net odds received)
    #   f* = (p*b - (1-p)) / b
    b = (1.0 - cost) / cost if cost > 0 else 0.0
    kelly = ((p * b) - (1.0 - p)) / b if b > 0 else 0.0
    kelly = max(0.0, kelly)

    return _j({
        "market_slug": market_slug,
        "market_implied_probability": round((bid + ask) / 2, 4) if bid > 0 else round(ask, 4),
        "best_bid": bid,
        "best_ask": ask,
        "your_probability": p,
        "cost_per_share_to_buy": round(cost, 4),
        "edge_per_share": round(edge, 4),
        "edge_pct": round(edge * 100, 2),
        "expected_value_per_share": round(ev_per_share, 4),
        "expected_value_usd": round(ev_per_share * quantity, 2),
        "max_loss_usd": round(cost * quantity, 2),
        "max_payout_usd": round(quantity * 1.0, 2),
        "kelly_fraction_of_bankroll": round(kelly, 4),
        "kelly_half_fraction": round(kelly / 2, 4),
        "verdict": (
            "positive edge" if edge > 0.02 else
            "marginal — edge is inside typical spread/fee noise" if edge > 0 else
            "negative edge — the market disagrees with you and you pay to disagree"
        ),
        "note": "Edge is computed against the ASK (what you actually pay), not the mid.",
    })


# ---------------------------------------------------------------------------
# Trading (requires credentials; every path is guardrail-checked)
# ---------------------------------------------------------------------------

def _manual_indicator() -> str:
    """
    Orders placed by this server are algorithmic. Flag them as AUTOMATIC unless
    explicitly overridden — this mirrors FIX tag 1028 and is what an automated
    system is supposed to report.
    """
    if os.environ.get("POLYMARKET_MARK_ORDERS_MANUAL", "").lower() in ("1", "true", "yes"):
        return "MANUAL_ORDER_INDICATOR_MANUAL"
    return "MANUAL_ORDER_INDICATOR_AUTOMATIC"


@mcp.tool()
def preview_order(
    market_slug: str,
    price: float,
    quantity: int,
    intent: str = "ORDER_INTENT_BUY_LONG",
    order_type: str = "ORDER_TYPE_LIMIT",
    tif: str = "TIME_IN_FORCE_GOOD_TILL_CANCEL",
) -> str:
    """
    Simulate an order against the exchange without placing it, and run the local
    guardrails at the same time.

    Call this before place_order by default. It returns both the exchange's own
    preview (expected fill, commissions) and the local guardrail verdict.

    Args:
        market_slug: Market slug.
        price: Limit price per share, 0.00-1.00.
        quantity: Number of shares.
        intent: ORDER_INTENT_BUY_LONG | ORDER_INTENT_SELL_LONG |
                ORDER_INTENT_BUY_SHORT | ORDER_INTENT_SELL_SHORT.
        order_type: ORDER_TYPE_LIMIT or ORDER_TYPE_MARKET.
        tif: TIME_IN_FORCE_GOOD_TILL_CANCEL | ..._IMMEDIATE_OR_CANCEL |
             ..._FILL_OR_KILL | ..._GOOD_TILL_DATE.
    """
    check = _check_guardrails(market_slug, price, quantity, intent)
    request = {
        "marketSlug": market_slug,
        "intent": intent,
        "type": order_type,
        "price": _amount(price),
        "quantity": int(quantity),
        "tif": tif,
        "manualOrderIndicator": _manual_indicator(),
    }
    try:
        preview = _authed().orders.preview({"request": request})
    except Exception as e:
        return _j({"guardrail_check": check, "exchange_preview_error": json.loads(_err(e))})
    return _j({"guardrail_check": check, "exchange_preview": preview, "request": request})


@mcp.tool()
def place_order(
    market_slug: str,
    price: float,
    quantity: int,
    intent: str = "ORDER_INTENT_BUY_LONG",
    order_type: str = "ORDER_TYPE_LIMIT",
    tif: str = "TIME_IN_FORCE_GOOD_TILL_CANCEL",
    slippage_bips: Optional[int] = None,
) -> str:
    """
    Place a REAL order with REAL money on Polymarket US.

    Guardrails run first and hard-block the order if any limit is exceeded; the
    order is never sent in that case. Prefer calling preview_order first and
    showing the user the expected cost before calling this.

    Args:
        market_slug: Market slug.
        price: Limit price per share, 0.00-1.00.
        quantity: Number of shares.
        intent: ORDER_INTENT_BUY_LONG | ORDER_INTENT_SELL_LONG |
                ORDER_INTENT_BUY_SHORT | ORDER_INTENT_SELL_SHORT.
        order_type: ORDER_TYPE_LIMIT or ORDER_TYPE_MARKET.
        tif: Time in force.
        slippage_bips: Max slippage for market orders, in basis points. Capped by
                       MAX_SLIPPAGE_BIPS.
    """
    check = _check_guardrails(market_slug, price, quantity, intent)
    if not check.get("ok"):
        return _j({
            "ok": False,
            "order_placed": False,
            "reason": "blocked by guardrails",
            "blocked_by": check["blocked_by"],
            "hint": "Call get_trading_limits to see active limits, or check_order to test changes.",
        })

    limits = _load_guardrails()
    params: dict = {
        "marketSlug": market_slug,
        "intent": intent,
        "type": order_type,
        "price": _amount(price),
        "quantity": int(quantity),
        "tif": tif,
        "manualOrderIndicator": _manual_indicator(),
    }
    if slippage_bips is not None:
        capped = min(int(slippage_bips), limits["max_slippage_bips"])
        params["slippageTolerance"] = {"currentPrice": _amount(price), "bips": capped}

    try:
        result = _authed().orders.create(params)
    except Exception as e:
        return _j({"ok": False, "order_placed": False, "error": json.loads(_err(e))})

    return _j({
        "ok": True,
        "order_placed": True,
        "risk": {
            "notional_usd": check.get("notional_usd"),
            "max_loss_usd": check.get("max_loss_usd"),
            "max_payout_usd": check.get("max_payout_usd"),
        },
        "result": result,
    })


@mcp.tool()
def modify_order(
    order_id: str,
    market_slug: str,
    price: float,
    quantity: int,
    tif: str = "TIME_IN_FORCE_GOOD_TILL_CANCEL",
) -> str:
    """
    Modify a resting order's price and/or quantity.

    The revised order is re-checked against the guardrails as if it were new, so
    a modification cannot be used to grow past a limit.

    Args:
        order_id: The order to modify.
        market_slug: Market slug the order belongs to.
        price: New limit price per share.
        quantity: New share count.
        tif: Time in force.
    """
    check = _check_guardrails(market_slug, price, quantity, "ORDER_INTENT_BUY_LONG")
    if not check.get("ok"):
        return _j({
            "ok": False,
            "order_modified": False,
            "reason": "blocked by guardrails",
            "blocked_by": check["blocked_by"],
        })
    try:
        _authed().orders.modify(order_id, {
            "marketSlug": market_slug,
            "price": _amount(price),
            "quantity": int(quantity),
            "tif": tif,
        })
    except Exception as e:
        return _j({"ok": False, "order_modified": False, "error": json.loads(_err(e))})
    return _j({"ok": True, "order_modified": True, "order_id": order_id})


@mcp.tool()
def cancel_order(order_id: str, market_slug: str) -> str:
    """
    Cancel one resting order.

    Args:
        order_id: The order to cancel.
        market_slug: Market slug the order belongs to.
    """
    try:
        _authed().orders.cancel(order_id, {"marketSlug": market_slug})
    except Exception as e:
        return _j({"ok": False, "cancelled": False, "error": json.loads(_err(e))})
    return _j({"ok": True, "cancelled": True, "order_id": order_id})


@mcp.tool()
def cancel_all_orders(market_slug: Optional[str] = None) -> str:
    """
    Cancel all resting orders, optionally scoped to one market.

    Args:
        market_slug: If given, only cancel orders in this market.
    """
    params = {"marketSlug": market_slug} if market_slug else None
    try:
        return _j(_authed().orders.cancel_all(params))
    except Exception as e:
        return _err(e)


@mcp.tool()
def close_position(market_slug: str, slippage_bips: Optional[int] = None) -> str:
    """
    Close the entire open position in a market at the current market price.

    Exits are deliberately NOT guardrail-blocked — reducing risk is always allowed,
    and a limit that traps you in a position is worse than no limit.

    Args:
        market_slug: Market slug to exit.
        slippage_bips: Max slippage in basis points, capped by MAX_SLIPPAGE_BIPS.
    """
    params: dict = {
        "marketSlug": market_slug,
        "manualOrderIndicator": _manual_indicator(),
    }
    if slippage_bips is not None:
        capped = min(int(slippage_bips), _load_guardrails()["max_slippage_bips"])
        try:
            bbo = _public().markets.bbo(market_slug)
            current = _amount_to_float(bbo.get("bestBid")) or _amount_to_float(bbo.get("lastTradePx"))
        except Exception:
            current = 0.0
        if current > 0:
            params["slippageTolerance"] = {"currentPrice": _amount(current), "bips": capped}
    try:
        return _j(_authed().orders.close_position(params))
    except Exception as e:
        return _err(e)


if __name__ == "__main__":
    mcp.run()
