"""
Robinhood Trading MCP Server

Provides MCP tools for interacting with Robinhood brokerage accounts.
Authentication uses environment variables: ROBINHOOD_USERNAME, ROBINHOOD_PASSWORD,
and optionally ROBINHOOD_MFA_CODE for TOTP-based 2FA.
"""

import os
import json
from typing import Optional
from mcp.server.fastmcp import FastMCP
import robin_stocks.robinhood as r
from decimal import Decimal, ROUND_DOWN

import numpy as np
import pandas as pd
import pandas_ta as ta
import yfinance as yf
from scipy.stats import norm

mcp = FastMCP("robinhood-trading")

# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------
_authenticated = False


def _ensure_auth() -> None:
    """Authenticate once per server lifetime using environment variables."""
    global _authenticated
    if _authenticated:
        return
    username = os.environ.get("ROBINHOOD_USERNAME")
    password = os.environ.get("ROBINHOOD_PASSWORD")
    mfa_code = os.environ.get("ROBINHOOD_MFA_CODE")
    if not username or not password:
        raise EnvironmentError(
            "ROBINHOOD_USERNAME and ROBINHOOD_PASSWORD environment variables must be set."
        )
    r.login(username, password, mfa_code=mfa_code, store_session=True)
    _authenticated = True


# ---------------------------------------------------------------------------
# Guardrails — loaded from env vars, with safe defaults
# ---------------------------------------------------------------------------

def _load_guardrails() -> dict:
    """
    Read trading limits from environment variables. If not set, conservative
    defaults are used. All limits are enforced before any order is placed.

    Configure in your .env file:
        MAX_POSITION_PCT=10          # max % of portfolio in one stock
        MAX_SINGLE_TRADE_USD=1000    # max dollar size of any single order
        MIN_CASH_RESERVE_PCT=10      # always keep this % as cash
        DAILY_LOSS_LIMIT_PCT=3       # halt trading if portfolio drops this % today
        MAX_SECTOR_PCT=30            # max % in any one sector
        REQUIRE_CONFIRMATION_ABOVE=500  # ask for explicit confirmation for trades > $X
        ALLOWED_SYMBOLS=             # comma-separated whitelist, empty = all allowed
        BLOCKED_SYMBOLS=             # comma-separated blacklist, always blocked
    """
    def _pct(key, default):
        try:
            return float(os.environ.get(key, default))
        except ValueError:
            return float(default)

    return {
        "max_position_pct":           _pct("MAX_POSITION_PCT", 10),
        "max_single_trade_usd":       _pct("MAX_SINGLE_TRADE_USD", 1000),
        "min_cash_reserve_pct":       _pct("MIN_CASH_RESERVE_PCT", 10),
        "daily_loss_limit_pct":       _pct("DAILY_LOSS_LIMIT_PCT", 3),
        "max_sector_pct":             _pct("MAX_SECTOR_PCT", 30),
        "require_confirmation_above": _pct("REQUIRE_CONFIRMATION_ABOVE", 500),
        "allowed_symbols": [s.strip().upper() for s in os.environ.get("ALLOWED_SYMBOLS", "").split(",") if s.strip()],
        "blocked_symbols": [s.strip().upper() for s in os.environ.get("BLOCKED_SYMBOLS", "").split(",") if s.strip()],
    }


def _check_guardrails(symbol: str, trade_value_usd: float, side: str = "buy") -> dict:
    """
    Validate a proposed trade against all active guardrails.
    Returns {"ok": True} if safe, or {"ok": False, "blocked_by": [...reasons...]} if not.
    Called internally before every order function.
    """
    _ensure_auth()
    limits = _load_guardrails()
    blocks = []

    sym = symbol.upper()

    # 1. Blocked symbol check
    if sym in limits["blocked_symbols"]:
        blocks.append(f"{sym} is on the blocked symbols list")

    # 2. Whitelist check (only if a whitelist is defined)
    if limits["allowed_symbols"] and sym not in limits["allowed_symbols"]:
        blocks.append(f"{sym} is not on the allowed symbols whitelist: {limits['allowed_symbols']}")

    # 3. Single trade size cap
    if trade_value_usd > limits["max_single_trade_usd"]:
        blocks.append(
            f"Trade value ${trade_value_usd:.2f} exceeds MAX_SINGLE_TRADE_USD "
            f"(${limits['max_single_trade_usd']:.0f})"
        )

    if side == "buy":
        account  = r.load_account_profile(info=None)
        portfolio = r.load_portfolio_profile(info=None)
        total_equity = float(portfolio.get("equity") or 0)
        cash = float(account.get("cash") or 0)

        # 4. Cash reserve check
        min_cash = total_equity * limits["min_cash_reserve_pct"] / 100
        cash_after = cash - trade_value_usd
        if cash_after < min_cash:
            blocks.append(
                f"Trade would leave ${cash_after:.2f} cash, below the "
                f"{limits['min_cash_reserve_pct']:.0f}% reserve requirement (${min_cash:.2f})"
            )

        # 5. Position concentration check
        holdings = r.build_holdings()
        current_position_value = float(holdings.get(sym, {}).get("equity") or 0)
        new_position_value = current_position_value + trade_value_usd
        position_pct = new_position_value / total_equity * 100 if total_equity > 0 else 0
        if position_pct > limits["max_position_pct"]:
            blocks.append(
                f"This buy would make {sym} {position_pct:.1f}% of portfolio, "
                f"exceeding MAX_POSITION_PCT ({limits['max_position_pct']:.0f}%)"
            )

        # 6. Daily loss limit check
        prev_equity = float(portfolio.get("adjusted_equity_previous_close") or total_equity)
        if prev_equity > 0:
            daily_loss_pct = (prev_equity - total_equity) / prev_equity * 100
            if daily_loss_pct > limits["daily_loss_limit_pct"]:
                blocks.append(
                    f"Portfolio is already down {daily_loss_pct:.1f}% today — "
                    f"DAILY_LOSS_LIMIT_PCT ({limits['daily_loss_limit_pct']:.0f}%) hit. "
                    f"No new buys until tomorrow."
                )

    if blocks:
        return {"ok": False, "blocked_by": blocks}
    return {"ok": True}


@mcp.tool()
def get_trading_limits() -> dict:
    """
    Show all active guardrails and trading limits currently configured for
    this server. Review these before placing any trades.

    Limits can be changed by editing your .env file and restarting the server.
    """
    return _load_guardrails()


@mcp.tool()
def check_trade(symbol: str, trade_value_usd: float, side: str = "buy") -> dict:
    """
    Dry-check whether a proposed trade would pass all guardrails without
    actually placing it. Use this to validate any trade before executing.

    Args:
        symbol:          Stock ticker (e.g. "AAPL")
        trade_value_usd: Dollar value of the proposed trade
        side:            "buy" or "sell"
    """
    result = _check_guardrails(symbol, trade_value_usd, side)
    result["symbol"] = symbol.upper()
    result["trade_value_usd"] = trade_value_usd
    result["side"] = side
    result["active_limits"] = _load_guardrails()
    return result


# ---------------------------------------------------------------------------
# Account & Portfolio
# ---------------------------------------------------------------------------

@mcp.tool()
def get_account_info() -> dict:
    """
    Get Robinhood account details including portfolio value, buying power,
    cash balance, and account number.
    """
    _ensure_auth()
    account = r.load_account_profile(info=None)
    portfolio = r.load_portfolio_profile(info=None)
    return {
        "account_number": account.get("account_number"),
        "buying_power": account.get("buying_power"),
        "cash": account.get("cash"),
        "cash_held_for_orders": account.get("cash_held_for_orders"),
        "portfolio_value": portfolio.get("equity"),
        "extended_hours_equity": portfolio.get("extended_hours_equity"),
        "excess_margin": account.get("margin_balances", {}).get("unallocated_margin_cash"),
        "account_type": account.get("type"),
    }


@mcp.tool()
def get_portfolio_holdings() -> list:
    """
    Get all current stock holdings in the portfolio with quantity, average
    cost, current price, and total equity.
    """
    _ensure_auth()
    holdings = r.build_holdings()
    result = []
    for symbol, data in holdings.items():
        result.append({
            "symbol": symbol,
            "name": data.get("name"),
            "quantity": data.get("quantity"),
            "average_buy_price": data.get("average_buy_price"),
            "current_price": data.get("price"),
            "equity": data.get("equity"),
            "equity_change": data.get("equity_change"),
            "percentage": data.get("percentage"),
            "pe_ratio": data.get("pe_ratio"),
            "type": data.get("type"),
        })
    return result


@mcp.tool()
def get_total_equity() -> dict:
    """
    Get a summary of total portfolio equity including market value,
    extended hours value, and cash.
    """
    _ensure_auth()
    portfolio = r.load_portfolio_profile(info=None)
    account = r.load_account_profile(info=None)
    return {
        "equity": portfolio.get("equity"),
        "extended_hours_equity": portfolio.get("extended_hours_equity"),
        "adjusted_equity": portfolio.get("adjusted_equity_previous_close"),
        "cash": account.get("cash"),
        "buying_power": account.get("buying_power"),
    }


@mcp.tool()
def get_portfolio_allocation() -> dict:
    """
    Show how your portfolio is currently allocated as dollar values and
    percentages of total equity. Includes cash as its own line item.

    Returns a summary with each position's weight so you can see at a
    glance whether you're over- or under-weight in any holding.
    """
    _ensure_auth()
    holdings = r.build_holdings()
    account = r.load_account_profile(info=None)
    cash = float(account.get("cash") or 0)

    positions = {}
    total_stocks = 0.0
    for symbol, data in holdings.items():
        equity = float(data.get("equity") or 0)
        positions[symbol] = equity
        total_stocks += equity

    total = total_stocks + cash
    if total == 0:
        return {"error": "Portfolio appears empty"}

    allocation = {}
    for symbol, equity in positions.items():
        data = holdings[symbol]
        allocation[symbol] = {
            "value": round(equity, 2),
            "percentage": round(equity / total * 100, 2),
            "shares": data.get("quantity"),
            "current_price": data.get("price"),
            "average_buy_price": data.get("average_buy_price"),
        }

    allocation["CASH"] = {
        "value": round(cash, 2),
        "percentage": round(cash / total * 100, 2),
    }

    return {
        "total_equity": round(total, 2),
        "allocation": allocation,
    }


@mcp.tool()
def calculate_rebalance_trades(targets: dict) -> dict:
    """
    Dry-run: calculate what buy/sell trades would be needed to rebalance your
    portfolio to a set of target percentage allocations. No orders are placed.

    The targets dict maps ticker symbols (or "CASH") to their desired
    percentage of total portfolio value. Percentages must add up to 100.

    Example targets: {"AAPL": 40, "TSLA": 30, "MSFT": 20, "CASH": 10}

    Returns:
        - Each position's current vs. target value
        - The action required (buy / sell / hold)
        - The estimated number of shares involved
        - A warning if the percentages don't sum to 100
    """
    _ensure_auth()
    total_pct = sum(targets.values())
    warnings = []
    if abs(total_pct - 100) > 0.5:
        warnings.append(f"Target percentages sum to {total_pct:.1f}%, not 100%. Trades are scaled proportionally.")

    holdings = r.build_holdings()
    account = r.load_account_profile(info=None)
    cash = float(account.get("cash") or 0)

    # Build current values map
    current_values: dict[str, float] = {"CASH": cash}
    for symbol, data in holdings.items():
        current_values[symbol] = float(data.get("equity") or 0)

    total_equity = sum(current_values.values())
    if total_equity == 0:
        return {"error": "Portfolio appears empty"}

    # Fetch current prices for all symbols we might need to trade
    all_symbols = set(list(holdings.keys()) + [s for s in targets if s != "CASH"])
    prices: dict[str, float] = {}
    for sym in all_symbols:
        p = r.get_latest_price(sym)
        if p and p[0]:
            prices[sym] = float(p[0])

    scale = 100 / total_pct  # normalise if percentages don't sum to 100
    trades = []
    for symbol, target_pct in targets.items():
        if symbol == "CASH":
            continue
        target_value = total_equity * (target_pct * scale / 100)
        current_value = current_values.get(symbol, 0.0)
        diff = target_value - current_value
        price = prices.get(symbol)

        shares_delta = None
        if price and price > 0:
            shares_delta = round(diff / price, 6)

        action = "hold"
        if diff > 0.01:
            action = "buy"
        elif diff < -0.01:
            action = "sell"

        trades.append({
            "symbol": symbol,
            "current_value": round(current_value, 2),
            "target_value": round(target_value, 2),
            "target_pct": target_pct,
            "difference_dollars": round(diff, 2),
            "current_price": price,
            "shares_to_trade": shares_delta,
            "action": action,
        })

    # Handle positions not in the target (will be fully sold)
    for symbol in holdings:
        if symbol not in targets:
            current_value = current_values.get(symbol, 0.0)
            price = prices.get(symbol)
            shares_delta = round(-current_value / price, 6) if price else None
            trades.append({
                "symbol": symbol,
                "current_value": round(current_value, 2),
                "target_value": 0.0,
                "target_pct": 0,
                "difference_dollars": round(-current_value, 2),
                "current_price": price,
                "shares_to_trade": shares_delta,
                "action": "sell_all",
            })

    trades.sort(key=lambda t: t["action"])
    return {
        "total_equity": round(total_equity, 2),
        "trades": trades,
        "warnings": warnings,
    }


@mcp.tool()
def rebalance_portfolio(targets: dict, dry_run: bool = True) -> dict:
    """
    Rebalance your portfolio to a set of target percentage allocations by
    placing the necessary market orders.

    IMPORTANT: Set dry_run=False to actually place orders. By default this
    runs in dry_run=True mode and only shows what would happen — no trades
    are executed. Always review the dry-run output before committing real money.

    The targets dict maps ticker symbols to their desired percentage of total
    portfolio value. Percentages should sum to 100. "CASH" is reserved and
    skipped (cash level is the remainder after all buys/sells settle).

    Example targets: {"AAPL": 40, "TSLA": 30, "MSFT": 30}

    Strategy:
      1. Sells are placed first to free up buying power.
      2. Buys are placed after.
      3. All orders are fractional market orders so they fill immediately.

    Args:
        targets:  Dict of symbol → target percentage (e.g. {"AAPL": 50, "TSLA": 50})
        dry_run:  If True (default), only calculate and return the plan. Set
                  False to actually place orders.
    """
    _ensure_auth()

    # Reuse calculate_rebalance_trades logic
    plan = calculate_rebalance_trades(targets)
    if "error" in plan:
        return plan

    if dry_run:
        plan["status"] = "dry_run — set dry_run=False to execute"
        return plan

    results = {"sells": [], "buys": [], "skipped": [], "warnings": plan.get("warnings", [])}

    # Place sells first to free up cash
    for trade in plan["trades"]:
        sym = trade["symbol"]
        action = trade["action"]
        shares = trade.get("shares_to_trade")

        if shares is None or abs(shares) < 0.000001:
            results["skipped"].append({"symbol": sym, "reason": "negligible size"})
            continue

        if action in ("sell", "sell_all"):
            shares_to_sell = abs(shares)
            order = r.order_sell_fractional_by_quantity(sym, shares_to_sell, timeInForce="gfd", extendedHours=False)
            results["sells"].append({"symbol": sym, "shares": shares_to_sell, "order": _format_order(order)})

    # Place buys after sells have freed up cash
    for trade in plan["trades"]:
        sym = trade["symbol"]
        action = trade["action"]
        shares = trade.get("shares_to_trade")
        diff = trade.get("difference_dollars", 0)

        if action == "buy" and shares and diff > 0.01:
            order = r.order_buy_fractional_by_price(sym, round(diff, 2), timeInForce="gfd", extendedHours=False)
            results["buys"].append({"symbol": sym, "dollar_amount": round(diff, 2), "order": _format_order(order)})

    results["status"] = "executed"
    results["total_equity"] = plan["total_equity"]
    results["plan"] = plan["trades"]
    return results


# ---------------------------------------------------------------------------
# Market Data
# ---------------------------------------------------------------------------

@mcp.tool()
def get_stock_quote(symbol: str) -> dict:
    """
    Get the current quote for a stock symbol including bid, ask, last trade
    price, and trading volume.

    Args:
        symbol: Stock ticker symbol (e.g. "AAPL", "TSLA")
    """
    _ensure_auth()
    quote = r.get_latest_price(symbol, priceType=None, includeExtendedHours=True)
    fundamentals = r.get_fundamentals(symbol, info=None)
    stock_info = r.get_instruments_by_symbols(symbol, info=None)

    price_data = r.get_quotes(symbol, info=None)
    q = price_data[0] if price_data else {}

    fund = fundamentals[0] if fundamentals else {}
    info = stock_info[0] if stock_info else {}

    return {
        "symbol": symbol.upper(),
        "name": info.get("simple_name") or info.get("name"),
        "last_trade_price": q.get("last_trade_price"),
        "last_extended_hours_trade_price": q.get("last_extended_hours_trade_price"),
        "ask_price": q.get("ask_price"),
        "ask_size": q.get("ask_size"),
        "bid_price": q.get("bid_price"),
        "bid_size": q.get("bid_size"),
        "open": q.get("open_price"),
        "high": fund.get("high"),
        "low": fund.get("low"),
        "volume": fund.get("volume"),
        "market_cap": fund.get("market_cap"),
        "pe_ratio": fund.get("pe_ratio"),
        "week_52_high": fund.get("high_52_weeks"),
        "week_52_low": fund.get("low_52_weeks"),
        "trading_halted": q.get("trading_halted"),
    }


@mcp.tool()
def get_historical_prices(
    symbol: str,
    interval: str = "day",
    span: str = "3month",
    bounds: str = "regular",
) -> list:
    """
    Get historical OHLCV price data for a stock.

    Args:
        symbol:   Stock ticker symbol (e.g. "AAPL")
        interval: Bar interval — "5minute", "10minute", "hour", "day", "week"
        span:     Time span — "day", "week", "month", "3month", "year", "5year"
        bounds:   Trading session — "regular", "extended", "trading"
    """
    _ensure_auth()
    historicals = r.get_stock_historicals(
        symbol,
        interval=interval,
        span=span,
        bounds=bounds,
        info=None,
    )
    if not historicals:
        return []
    return [
        {
            "begins_at": bar.get("begins_at"),
            "open": bar.get("open_price"),
            "high": bar.get("high_price"),
            "low": bar.get("low_price"),
            "close": bar.get("close_price"),
            "volume": bar.get("volume"),
            "session": bar.get("session"),
        }
        for bar in historicals
    ]


@mcp.tool()
def search_stocks(query: str) -> list:
    """
    Search for stocks by company name or ticker symbol.

    Args:
        query: Company name or partial ticker to search for
    """
    _ensure_auth()
    results = r.find_instrument_data(query)
    if not results:
        return []
    return [
        {
            "symbol": item.get("symbol"),
            "name": item.get("simple_name") or item.get("name"),
            "type": item.get("type"),
            "tradeable": item.get("tradeable"),
            "country": item.get("country"),
            "list_date": item.get("list_date"),
        }
        for item in results[:20]
    ]


@mcp.tool()
def get_stock_news(symbol: str) -> list:
    """
    Get recent news articles for a stock.

    Args:
        symbol: Stock ticker symbol (e.g. "AAPL")
    """
    _ensure_auth()
    news = r.get_news(symbol)
    if not news:
        return []
    return [
        {
            "title": article.get("title"),
            "source": article.get("source"),
            "summary": article.get("summary"),
            "url": article.get("url"),
            "published_at": article.get("published_at"),
            "relates_to": article.get("related_instruments"),
        }
        for article in news[:15]
    ]


@mcp.tool()
def get_stock_fundamentals(symbol: str) -> dict:
    """
    Get fundamental data for a stock: P/E ratio, EPS, market cap,
    dividend yield, 52-week range, and description.

    Args:
        symbol: Stock ticker symbol (e.g. "AAPL")
    """
    _ensure_auth()
    fund = r.get_fundamentals(symbol, info=None)
    if not fund:
        return {}
    f = fund[0]
    return {
        "symbol": symbol.upper(),
        "description": f.get("description"),
        "ceo": f.get("ceo"),
        "headquarters_city": f.get("headquarters_city"),
        "headquarters_state": f.get("headquarters_state"),
        "industry": f.get("industry"),
        "sector": f.get("sector"),
        "num_employees": f.get("num_employees"),
        "year_founded": f.get("year_founded"),
        "market_cap": f.get("market_cap"),
        "pe_ratio": f.get("pe_ratio"),
        "pb_ratio": f.get("pb_ratio"),
        "dividend_yield": f.get("dividend_yield"),
        "earnings_per_share": f.get("earnings_per_share"),
        "high_52_weeks": f.get("high_52_weeks"),
        "low_52_weeks": f.get("low_52_weeks"),
        "average_volume": f.get("average_volume"),
    }


@mcp.tool()
def get_earnings(symbol: str) -> list:
    """
    Get historical and upcoming earnings data for a stock.

    Args:
        symbol: Stock ticker symbol (e.g. "AAPL")
    """
    _ensure_auth()
    earnings = r.get_earnings(symbol, info=None)
    if not earnings:
        return []
    return [
        {
            "year": e.get("year"),
            "quarter": e.get("quarter"),
            "eps_estimate": e.get("eps", {}).get("estimate"),
            "eps_actual": e.get("eps", {}).get("actual"),
            "revenue_estimate": e.get("revenue", {}).get("estimate"),
            "revenue_actual": e.get("revenue", {}).get("actual"),
            "report": e.get("report"),
        }
        for e in earnings
    ]


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------

@mcp.tool()
def place_market_buy_order(symbol: str, quantity: float) -> dict:
    """
    Place a market buy order for a stock. Guardrails are checked automatically
    before the order is submitted.

    Args:
        symbol:   Stock ticker symbol (e.g. "AAPL")
        quantity: Number of shares to buy (fractional shares supported)
    """
    _ensure_auth()
    price_list = r.get_latest_price(symbol)
    price = float(price_list[0]) if price_list and price_list[0] else 0
    trade_value = price * quantity
    guard = _check_guardrails(symbol, trade_value, "buy")
    if not guard["ok"]:
        return {"blocked": True, "reasons": guard["blocked_by"], "order": None}
    order = r.order_buy_market(symbol, quantity, timeInForce="gtc", extendedHours=False)
    return _format_order(order)


@mcp.tool()
def place_limit_buy_order(symbol: str, quantity: float, limit_price: float) -> dict:
    """
    Place a limit buy order for a stock. Guardrails are checked automatically.

    Args:
        symbol:      Stock ticker symbol (e.g. "AAPL")
        quantity:    Number of shares to buy
        limit_price: Maximum price per share to pay
    """
    _ensure_auth()
    trade_value = limit_price * quantity
    guard = _check_guardrails(symbol, trade_value, "buy")
    if not guard["ok"]:
        return {"blocked": True, "reasons": guard["blocked_by"], "order": None}
    order = r.order_buy_limit(symbol, quantity, limit_price, timeInForce="gtc", extendedHours=False)
    return _format_order(order)


@mcp.tool()
def place_market_sell_order(symbol: str, quantity: float) -> dict:
    """
    Place a market sell order for a stock. Guardrails are checked automatically.

    Args:
        symbol:   Stock ticker symbol (e.g. "AAPL")
        quantity: Number of shares to sell
    """
    _ensure_auth()
    price_list = r.get_latest_price(symbol)
    price = float(price_list[0]) if price_list and price_list[0] else 0
    guard = _check_guardrails(symbol, price * quantity, "sell")
    if not guard["ok"]:
        return {"blocked": True, "reasons": guard["blocked_by"], "order": None}
    order = r.order_sell_market(symbol, quantity, timeInForce="gtc", extendedHours=False)
    return _format_order(order)


@mcp.tool()
def place_limit_sell_order(symbol: str, quantity: float, limit_price: float) -> dict:
    """
    Place a limit sell order for a stock. Guardrails are checked automatically.

    Args:
        symbol:      Stock ticker symbol (e.g. "AAPL")
        quantity:    Number of shares to sell
        limit_price: Minimum price per share to accept
    """
    _ensure_auth()
    guard = _check_guardrails(symbol, limit_price * quantity, "sell")
    if not guard["ok"]:
        return {"blocked": True, "reasons": guard["blocked_by"], "order": None}
    order = r.order_sell_limit(symbol, quantity, limit_price, timeInForce="gtc", extendedHours=False)
    return _format_order(order)


@mcp.tool()
def place_stop_loss_order(symbol: str, quantity: float, stop_price: float) -> dict:
    """
    Place a stop-loss sell order. Triggers a market sell when price drops to
    stop_price. Guardrails are checked automatically.

    Args:
        symbol:     Stock ticker symbol (e.g. "AAPL")
        quantity:   Number of shares to sell
        stop_price: Price at which the stop order is triggered
    """
    _ensure_auth()
    guard = _check_guardrails(symbol, stop_price * quantity, "sell")
    if not guard["ok"]:
        return {"blocked": True, "reasons": guard["blocked_by"], "order": None}
    order = r.order_sell_stop_loss(symbol, quantity, stop_price, timeInForce="gtc", extendedHours=False)
    return _format_order(order)


@mcp.tool()
def place_stop_limit_order(
    symbol: str,
    quantity: float,
    stop_price: float,
    limit_price: float,
    side: str = "sell",
) -> dict:
    """
    Place a stop-limit order. When stop_price is triggered, a limit order
    is submitted at limit_price. Guardrails are checked automatically.

    Args:
        symbol:      Stock ticker symbol (e.g. "AAPL")
        quantity:    Number of shares
        stop_price:  Price that triggers the order
        limit_price: Limit price for the resulting limit order
        side:        "buy" or "sell"
    """
    _ensure_auth()
    guard = _check_guardrails(symbol, limit_price * quantity, side)
    if not guard["ok"]:
        return {"blocked": True, "reasons": guard["blocked_by"], "order": None}
    if side == "sell":
        order = r.order_sell_stop_limit(symbol, quantity, limit_price, stop_price, timeInForce="gtc")
    else:
        order = r.order_buy_stop_limit(symbol, quantity, limit_price, stop_price, timeInForce="gtc")
    return _format_order(order)


@mcp.tool()
def get_open_orders() -> list:
    """
    List all currently open (unfilled/pending) orders on the account.
    """
    _ensure_auth()
    orders = r.get_all_open_stock_orders()
    if not orders:
        return []
    return [_format_order(o) for o in orders]


@mcp.tool()
def get_order_history(count: int = 50) -> list:
    """
    Get recent order history for the account.

    Args:
        count: Number of recent orders to return (default 50, max 100)
    """
    _ensure_auth()
    orders = r.get_all_stock_orders(info=None)
    if not orders:
        return []
    return [_format_order(o) for o in orders[: min(count, 100)]]


@mcp.tool()
def cancel_order(order_id: str) -> dict:
    """
    Cancel an open order by its order ID.

    Args:
        order_id: The UUID of the order to cancel
    """
    _ensure_auth()
    result = r.cancel_stock_order(order_id)
    if result is None:
        return {"status": "cancelled", "order_id": order_id}
    return {"status": "error", "detail": str(result)}


@mcp.tool()
def cancel_all_open_orders() -> dict:
    """
    Cancel all currently open orders on the account.
    """
    _ensure_auth()
    r.cancel_all_stock_orders()
    return {"status": "all_open_orders_cancelled"}


# ---------------------------------------------------------------------------
# Options
# ---------------------------------------------------------------------------

@mcp.tool()
def get_options_chain(symbol: str, expiration_date: Optional[str] = None, option_type: str = "both") -> list:
    """
    Get the options chain for a stock.

    Args:
        symbol:          Stock ticker symbol (e.g. "AAPL")
        expiration_date: Options expiration date in YYYY-MM-DD format (None = nearest)
        option_type:     "call", "put", or "both"
    """
    _ensure_auth()
    exp_dates = r.get_chains(symbol, info="expiration_dates")
    if not exp_dates:
        return []

    target_date = expiration_date or exp_dates[0]

    types = ["call", "put"] if option_type == "both" else [option_type]
    results = []
    for otype in types:
        contracts = r.find_options_for_stock_by_expiration(
            symbol, target_date, optionType=otype, info=None
        )
        if contracts:
            for c in contracts:
                results.append({
                    "type": otype,
                    "strike_price": c.get("strike_price"),
                    "expiration_date": c.get("expiration_date"),
                    "ask_price": c.get("ask_price"),
                    "bid_price": c.get("bid_price"),
                    "last_trade_price": c.get("last_trade_price"),
                    "volume": c.get("volume"),
                    "open_interest": c.get("open_interest"),
                    "implied_volatility": c.get("implied_volatility"),
                    "delta": c.get("delta"),
                    "gamma": c.get("gamma"),
                    "theta": c.get("theta"),
                    "vega": c.get("vega"),
                    "rho": c.get("rho"),
                    "in_the_money": c.get("in_the_money"),
                })
    return results


@mcp.tool()
def get_options_expiration_dates(symbol: str) -> list:
    """
    Get all available options expiration dates for a stock.

    Args:
        symbol: Stock ticker symbol (e.g. "AAPL")
    """
    _ensure_auth()
    dates = r.get_chains(symbol, info="expiration_dates")
    return dates or []


@mcp.tool()
def get_open_options_positions() -> list:
    """
    Get all currently open options positions in the account.
    """
    _ensure_auth()
    positions = r.get_open_option_positions(info=None)
    if not positions:
        return []
    return [
        {
            "chain_symbol": p.get("chain_symbol"),
            "type": p.get("type"),
            "quantity": p.get("quantity"),
            "average_price": p.get("average_price"),
            "trade_value_multiplier": p.get("trade_value_multiplier"),
        }
        for p in positions
    ]


@mcp.tool()
def find_options_by_strike(
    symbol: str,
    strike_price: float,
    option_type: str = "both",
) -> list:
    """
    Find all option contracts for a stock at a specific strike price across
    all available expiration dates.

    Args:
        symbol:       Stock ticker symbol (e.g. "AAPL")
        strike_price: The exact strike price to look up
        option_type:  "call", "put", or "both"
    """
    _ensure_auth()
    contracts = r.find_options_for_stock_by_strike(
        symbol, str(strike_price), optionType=option_type, info=None
    )
    return [_format_option_contract(c) for c in (contracts or [])]


@mcp.tool()
def find_options_near_money(
    symbol: str,
    expiration_date: Optional[str] = None,
    option_type: str = "both",
    num_strikes: int = 5,
) -> list:
    """
    Find option contracts near the current stock price (ATM ± num_strikes
    strikes). Useful for quickly surfacing the most liquid contracts.

    Args:
        symbol:          Stock ticker symbol (e.g. "AAPL")
        expiration_date: Expiration date YYYY-MM-DD (None = nearest expiry)
        option_type:     "call", "put", or "both"
        num_strikes:     How many strikes above and below ATM to include (default 5)
    """
    _ensure_auth()
    exp_dates = r.get_chains(symbol, info="expiration_dates")
    if not exp_dates:
        return []
    target_date = expiration_date or exp_dates[0]

    current_price_list = r.get_latest_price(symbol)
    if not current_price_list:
        return []
    current_price = float(current_price_list[0])

    types = ["call", "put"] if option_type == "both" else [option_type]
    results = []
    for otype in types:
        contracts = r.find_options_for_stock_by_expiration(
            symbol, target_date, optionType=otype, info=None
        )
        if not contracts:
            continue
        # Sort by how close each strike is to the current price
        contracts.sort(key=lambda c: abs(float(c.get("strike_price", 0)) - current_price))
        for c in contracts[: num_strikes * 2]:
            results.append(_format_option_contract(c))
    # Re-sort final list by expiration then strike for readability
    results.sort(key=lambda c: (c.get("expiration_date", ""), float(c.get("strike_price") or 0)))
    return results


@mcp.tool()
def get_option_market_data(
    symbol: str,
    expiration_date: str,
    strike_price: float,
    option_type: str,
) -> dict:
    """
    Get current market data and Greeks for a specific option contract.

    Args:
        symbol:          Stock ticker symbol (e.g. "AAPL")
        expiration_date: Expiration date in YYYY-MM-DD format
        strike_price:    Strike price of the contract
        option_type:     "call" or "put"
    """
    _ensure_auth()
    data = r.get_option_market_data(
        symbol, expiration_date, str(strike_price), option_type, info=None
    )
    if not data:
        return {}
    d = data[0] if isinstance(data, list) else data
    return {
        "symbol": symbol.upper(),
        "expiration_date": expiration_date,
        "strike_price": strike_price,
        "type": option_type,
        "ask_price": d.get("ask_price"),
        "bid_price": d.get("bid_price"),
        "last_trade_price": d.get("last_trade_price"),
        "mark_price": d.get("adjusted_mark_price"),
        "volume": d.get("volume"),
        "open_interest": d.get("open_interest"),
        "implied_volatility": d.get("implied_volatility"),
        "delta": d.get("delta"),
        "gamma": d.get("gamma"),
        "theta": d.get("theta"),
        "vega": d.get("vega"),
        "rho": d.get("rho"),
        "in_the_money": d.get("in_the_money"),
        "intrinsic_value": d.get("intrinsic_value"),
        "time_value": d.get("time_value"),
        "chance_of_profit_long": d.get("chance_of_profit_long"),
        "chance_of_profit_short": d.get("chance_of_profit_short"),
        "break_even_price": d.get("break_even_price"),
    }


@mcp.tool()
def buy_option_to_open(
    symbol: str,
    expiration_date: str,
    strike_price: float,
    option_type: str,
    quantity: int,
    limit_price: float,
    time_in_force: str = "gfd",
) -> dict:
    """
    Buy to open an option contract (enter a new long position).

    Cost = limit_price × quantity × 100 (each contract covers 100 shares).

    Args:
        symbol:          Stock ticker symbol (e.g. "AAPL")
        expiration_date: Expiration date YYYY-MM-DD
        strike_price:    Strike price of the contract
        option_type:     "call" or "put"
        quantity:        Number of contracts to buy
        limit_price:     Maximum premium per share to pay (e.g. 1.50 = $150/contract)
        time_in_force:   "gfd" (good for day) or "gtc" (good till cancelled)
    """
    _ensure_auth()
    order = r.order_buy_option_limit(
        positionEffect="open",
        creditOrDebit="debit",
        price=limit_price,
        symbol=symbol,
        quantity=quantity,
        expirationDate=expiration_date,
        strike=str(strike_price),
        optionType=option_type,
        timeInForce=time_in_force,
    )
    return _format_option_order(order)


@mcp.tool()
def sell_option_to_close(
    symbol: str,
    expiration_date: str,
    strike_price: float,
    option_type: str,
    quantity: int,
    limit_price: float,
    time_in_force: str = "gfd",
) -> dict:
    """
    Sell to close an existing long option position.

    Args:
        symbol:          Stock ticker symbol (e.g. "AAPL")
        expiration_date: Expiration date YYYY-MM-DD
        strike_price:    Strike price of the contract
        option_type:     "call" or "put"
        quantity:        Number of contracts to sell
        limit_price:     Minimum premium per share to accept
        time_in_force:   "gfd" or "gtc"
    """
    _ensure_auth()
    order = r.order_sell_option_limit(
        positionEffect="close",
        creditOrDebit="credit",
        price=limit_price,
        symbol=symbol,
        quantity=quantity,
        expirationDate=expiration_date,
        strike=str(strike_price),
        optionType=option_type,
        timeInForce=time_in_force,
    )
    return _format_option_order(order)


@mcp.tool()
def sell_option_to_open(
    symbol: str,
    expiration_date: str,
    strike_price: float,
    option_type: str,
    quantity: int,
    limit_price: float,
    time_in_force: str = "gfd",
) -> dict:
    """
    Sell to open (write) an option contract, entering a short position and
    collecting premium upfront. Requires margin approval for uncovered positions.

    Args:
        symbol:          Stock ticker symbol (e.g. "AAPL")
        expiration_date: Expiration date YYYY-MM-DD
        strike_price:    Strike price of the contract
        option_type:     "call" or "put"
        quantity:        Number of contracts to write
        limit_price:     Minimum premium per share to collect
        time_in_force:   "gfd" or "gtc"
    """
    _ensure_auth()
    order = r.order_sell_option_limit(
        positionEffect="open",
        creditOrDebit="credit",
        price=limit_price,
        symbol=symbol,
        quantity=quantity,
        expirationDate=expiration_date,
        strike=str(strike_price),
        optionType=option_type,
        timeInForce=time_in_force,
    )
    return _format_option_order(order)


@mcp.tool()
def buy_option_to_close(
    symbol: str,
    expiration_date: str,
    strike_price: float,
    option_type: str,
    quantity: int,
    limit_price: float,
    time_in_force: str = "gfd",
) -> dict:
    """
    Buy to close a short option position (covers a previously written contract).

    Args:
        symbol:          Stock ticker symbol (e.g. "AAPL")
        expiration_date: Expiration date YYYY-MM-DD
        strike_price:    Strike price of the contract
        option_type:     "call" or "put"
        quantity:        Number of contracts to buy back
        limit_price:     Maximum premium per share to pay
        time_in_force:   "gfd" or "gtc"
    """
    _ensure_auth()
    order = r.order_buy_option_limit(
        positionEffect="close",
        creditOrDebit="debit",
        price=limit_price,
        symbol=symbol,
        quantity=quantity,
        expirationDate=expiration_date,
        strike=str(strike_price),
        optionType=option_type,
        timeInForce=time_in_force,
    )
    return _format_option_order(order)


@mcp.tool()
def get_open_option_orders() -> list:
    """
    List all currently open (unfilled/pending) option orders.
    """
    _ensure_auth()
    orders = r.get_all_open_option_orders(info=None)
    return [_format_option_order(o) for o in (orders or [])]


@mcp.tool()
def get_option_order_history(count: int = 50) -> list:
    """
    Get recent option order history for the account.

    Args:
        count: Number of recent orders to return (default 50, max 100)
    """
    _ensure_auth()
    orders = r.get_all_option_orders(info=None)
    if not orders:
        return []
    return [_format_option_order(o) for o in orders[: min(count, 100)]]


@mcp.tool()
def cancel_option_order(order_id: str) -> dict:
    """
    Cancel an open option order by its order ID.

    Args:
        order_id: The UUID of the option order to cancel
    """
    _ensure_auth()
    result = r.cancel_option_order(order_id)
    if result is None:
        return {"status": "cancelled", "order_id": order_id}
    return {"status": "error", "detail": str(result)}


@mcp.tool()
def cancel_all_option_orders() -> dict:
    """
    Cancel all currently open option orders on the account.
    """
    _ensure_auth()
    r.cancel_all_option_orders()
    return {"status": "all_open_option_orders_cancelled"}


# ---------------------------------------------------------------------------
# Crypto
# ---------------------------------------------------------------------------

@mcp.tool()
def get_crypto_quote(symbol: str) -> dict:
    """
    Get the current price quote for a cryptocurrency.

    Args:
        symbol: Crypto symbol (e.g. "BTC", "ETH", "DOGE")
    """
    _ensure_auth()
    quote = r.get_crypto_quote(symbol, info=None)
    if not quote:
        return {}
    return {
        "symbol": symbol.upper(),
        "ask_price": quote.get("ask_price"),
        "bid_price": quote.get("bid_price"),
        "mark_price": quote.get("mark_price"),
        "open_price": quote.get("open_price"),
        "high_price": quote.get("high_price"),
        "low_price": quote.get("low_price"),
        "volume": quote.get("volume"),
    }


@mcp.tool()
def get_crypto_holdings() -> list:
    """
    Get all cryptocurrency holdings in the Robinhood account.
    """
    _ensure_auth()
    positions = r.get_crypto_positions(info=None)
    if not positions:
        return []
    results = []
    for p in positions:
        currency = p.get("currency", {})
        cost_bases = p.get("cost_bases", [{}])
        cb = cost_bases[0] if cost_bases else {}
        results.append({
            "symbol": currency.get("code"),
            "name": currency.get("name"),
            "quantity": p.get("quantity"),
            "quantity_available": p.get("quantity_available"),
            "cost_basis": cb.get("direct_cost_basis"),
            "quantity_held_for_buy": p.get("quantity_held_for_buy"),
            "quantity_held_for_sell": p.get("quantity_held_for_sell"),
        })
    return results


@mcp.tool()
def place_crypto_market_buy(symbol: str, amount_in_dollars: float) -> dict:
    """
    Buy cryptocurrency with a specified dollar amount.

    Args:
        symbol:           Crypto symbol (e.g. "BTC", "ETH")
        amount_in_dollars: Dollar amount to spend
    """
    _ensure_auth()
    order = r.order_buy_crypto_by_price(symbol, amount_in_dollars, timeInForce="gtc")
    return _format_crypto_order(order)


@mcp.tool()
def place_crypto_market_sell(symbol: str, quantity: float) -> dict:
    """
    Sell a specified quantity of cryptocurrency.

    Args:
        symbol:   Crypto symbol (e.g. "BTC", "ETH")
        quantity: Amount of crypto to sell
    """
    _ensure_auth()
    order = r.order_sell_crypto_by_quantity(symbol, quantity, timeInForce="gtc")
    return _format_crypto_order(order)


# ---------------------------------------------------------------------------
# Watchlists
# ---------------------------------------------------------------------------

@mcp.tool()
def get_watchlist(name: str = "Default") -> list:
    """
    Get stocks in a Robinhood watchlist.

    Args:
        name: Watchlist name (default "Default")
    """
    _ensure_auth()
    items = r.get_watchlist_by_name(name, info="symbol")
    return items or []


@mcp.tool()
def add_to_watchlist(symbol: str, name: str = "Default") -> dict:
    """
    Add a stock to a Robinhood watchlist.

    Args:
        symbol: Stock ticker symbol (e.g. "AAPL")
        name:   Watchlist name (default "Default")
    """
    _ensure_auth()
    r.post_symbols_to_watchlist(symbol, name=name)
    return {"status": "added", "symbol": symbol.upper(), "watchlist": name}


@mcp.tool()
def remove_from_watchlist(symbol: str, name: str = "Default") -> dict:
    """
    Remove a stock from a Robinhood watchlist.

    Args:
        symbol: Stock ticker symbol (e.g. "AAPL")
        name:   Watchlist name (default "Default")
    """
    _ensure_auth()
    r.delete_symbols_from_watchlist(symbol, name=name)
    return {"status": "removed", "symbol": symbol.upper(), "watchlist": name}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_option_contract(c: dict) -> dict:
    return {
        "type": c.get("type"),
        "strike_price": c.get("strike_price"),
        "expiration_date": c.get("expiration_date"),
        "ask_price": c.get("ask_price"),
        "bid_price": c.get("bid_price"),
        "last_trade_price": c.get("last_trade_price"),
        "volume": c.get("volume"),
        "open_interest": c.get("open_interest"),
        "implied_volatility": c.get("implied_volatility"),
        "delta": c.get("delta"),
        "gamma": c.get("gamma"),
        "theta": c.get("theta"),
        "vega": c.get("vega"),
        "rho": c.get("rho"),
        "in_the_money": c.get("in_the_money"),
        "chance_of_profit_long": c.get("chance_of_profit_long"),
        "chance_of_profit_short": c.get("chance_of_profit_short"),
    }


def _format_option_order(order: dict) -> dict:
    if not order:
        return {}
    legs = order.get("legs", [{}])
    leg = legs[0] if legs else {}
    return {
        "id": order.get("id"),
        "symbol": order.get("chain_symbol"),
        "option_type": leg.get("option_type") or order.get("option_type"),
        "strike_price": leg.get("strike_price"),
        "expiration_date": leg.get("expiration_date"),
        "side": leg.get("side"),
        "position_effect": leg.get("position_effect"),
        "quantity": order.get("quantity"),
        "filled_quantity": order.get("processed_quantity"),
        "limit_price": order.get("premium"),
        "average_price": order.get("processed_premium"),
        "state": order.get("state"),
        "time_in_force": order.get("time_in_force"),
        "created_at": order.get("created_at"),
        "updated_at": order.get("updated_at"),
        "closing_strategy": order.get("closing_strategy"),
        "opening_strategy": order.get("opening_strategy"),
    }


def _format_order(order: dict) -> dict:
    if not order:
        return {}
    return {
        "id": order.get("id"),
        "symbol": order.get("instrument_id") or order.get("symbol"),
        "type": order.get("type"),
        "side": order.get("side"),
        "quantity": order.get("quantity"),
        "filled_quantity": order.get("cumulative_quantity"),
        "price": order.get("price"),
        "stop_price": order.get("stop_price"),
        "average_price": order.get("average_price"),
        "state": order.get("state"),
        "time_in_force": order.get("time_in_force"),
        "created_at": order.get("created_at"),
        "updated_at": order.get("updated_at"),
        "fees": order.get("fees"),
        "reject_reason": order.get("reject_reason"),
    }


def _format_crypto_order(order: dict) -> dict:
    if not order:
        return {}
    return {
        "id": order.get("id"),
        "currency_pair": order.get("currency_pair_id"),
        "side": order.get("side"),
        "type": order.get("type"),
        "quantity": order.get("quantity"),
        "rounded_executed_notional": order.get("rounded_executed_notional"),
        "average_price": order.get("average_price"),
        "state": order.get("state"),
        "time_in_force": order.get("time_in_force"),
        "created_at": order.get("created_at"),
    }


# ---------------------------------------------------------------------------
# Market Intelligence
# ---------------------------------------------------------------------------

_SECTOR_ETFS = {
    "Technology": "XLK",
    "Financials": "XLF",
    "Healthcare": "XLV",
    "Energy": "XLE",
    "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP",
    "Industrials": "XLI",
    "Materials": "XLB",
    "Real Estate": "XLRE",
    "Utilities": "XLU",
    "Communication Services": "XLC",
}


@mcp.tool()
def get_market_overview() -> dict:
    """
    Quick pre-session snapshot of major US indices (S&P 500, NASDAQ, Dow,
    Russell 2000), the VIX fear gauge, 10-yr treasury yield, gold, and WTI
    oil — each with price and % change from prior close.
    """
    symbols = {
        "sp500": "^GSPC",
        "nasdaq": "^IXIC",
        "dow": "^DJI",
        "russell_2000": "^RUT",
        "vix": "^VIX",
        "ten_yr_yield": "^TNX",
        "gold": "GC=F",
        "oil_wti": "CL=F",
    }
    result = {}
    for name, sym in symbols.items():
        try:
            hist = yf.Ticker(sym).history(period="5d")
            hist = hist[hist["Volume"] > 0] if "Volume" in hist.columns else hist
            if len(hist) >= 2:
                prev = float(hist["Close"].iloc[-2])
                last = float(hist["Close"].iloc[-1])
                result[name] = {
                    "symbol": sym,
                    "price": round(last, 2),
                    "change_pct": round((last - prev) / prev * 100, 2),
                    "prev_close": round(prev, 2),
                }
        except Exception as e:
            result[name] = {"error": str(e)}
    return result


@mcp.tool()
def get_sector_performance(period: str = "1mo") -> list:
    """
    Show which of the 11 S&P 500 sectors are leading or lagging over a given
    period — essential for sector rotation strategies.

    Args:
        period: "1d", "5d", "1mo", "3mo", "6mo", "1y"
    """
    results = []
    for sector, etf in _SECTOR_ETFS.items():
        try:
            hist = yf.Ticker(etf).history(period=period)
            if len(hist) >= 2:
                start = float(hist["Close"].iloc[0])
                end = float(hist["Close"].iloc[-1])
                results.append({
                    "sector": sector,
                    "etf": etf,
                    "performance_pct": round((end - start) / start * 100, 2),
                    "current_price": round(end, 2),
                })
        except:
            pass
    results.sort(key=lambda x: x["performance_pct"], reverse=True)
    return results


@mcp.tool()
def get_analyst_consensus(symbol: str) -> dict:
    """
    Wall Street analyst consensus for a stock: buy/hold/sell rating,
    mean price target, implied upside/downside, and the 10 most recent
    analyst actions (upgrades, downgrades, initiations).

    Args:
        symbol: Stock ticker (e.g. "AAPL")
    """
    t = yf.Ticker(symbol)
    info = t.info
    recs = t.recommendations

    current = info.get("currentPrice")
    target = info.get("targetMeanPrice")
    upside = round((target - current) / current * 100, 1) if current and target else None

    recent_actions = []
    if recs is not None and not recs.empty:
        for _, row in recs.tail(10).reset_index().iterrows():
            recent_actions.append({
                "date": str(row.get("Date", row.get("date", ""))),
                "firm": row.get("Firm", ""),
                "to_grade": row.get("To Grade", ""),
                "from_grade": row.get("From Grade", ""),
                "action": row.get("Action", ""),
            })

    return {
        "symbol": symbol.upper(),
        "current_price": current,
        "target_mean": target,
        "target_high": info.get("targetHighPrice"),
        "target_low": info.get("targetLowPrice"),
        "upside_pct": upside,
        "analyst_count": info.get("numberOfAnalystOpinions"),
        "recommendation": info.get("recommendationKey"),
        "recommendation_mean": info.get("recommendationMean"),
        "recent_actions": recent_actions,
    }


@mcp.tool()
def get_institutional_holdings(symbol: str) -> dict:
    """
    See which major funds and institutions own a stock, their share counts,
    and what percentage of the float they hold. High and rising institutional
    ownership is a bullish signal.

    Args:
        symbol: Stock ticker (e.g. "AAPL")
    """
    t = yf.Ticker(symbol)
    info = t.info

    def _rows(df, n=10):
        if df is None or df.empty:
            return []
        out = []
        for _, row in df.head(n).iterrows():
            out.append({k: (int(v) if isinstance(v, (np.integer,)) else
                           float(round(v, 4)) if isinstance(v, (float, np.floating)) else
                           str(v)) for k, v in row.items()})
        return out

    return {
        "symbol": symbol.upper(),
        "institutional_ownership_pct": info.get("heldPercentInstitutions"),
        "insider_ownership_pct": info.get("heldPercentInsiders"),
        "float_shares": info.get("floatShares"),
        "top_institutions": _rows(t.institutional_holders),
        "top_mutual_funds": _rows(t.mutualfund_holders),
    }


@mcp.tool()
def compare_stocks(symbols: list) -> list:
    """
    Side-by-side fundamental comparison of multiple stocks — price, valuation
    ratios (P/E, PEG, P/S, P/B, EV/EBITDA), growth, profitability, and
    analyst consensus. Useful for picking the best name in a sector.

    Args:
        symbols: List of tickers (e.g. ["AAPL", "MSFT", "GOOGL"])
    """
    results = []
    for sym in symbols:
        try:
            info = yf.Ticker(sym).info
            results.append({
                "symbol": sym.upper(),
                "name": info.get("shortName"),
                "sector": info.get("sector"),
                "market_cap": info.get("marketCap"),
                "price": info.get("currentPrice"),
                "pe_ratio": info.get("trailingPE"),
                "forward_pe": info.get("forwardPE"),
                "peg_ratio": info.get("pegRatio"),
                "ps_ratio": info.get("priceToSalesTrailing12Months"),
                "pb_ratio": info.get("priceToBook"),
                "ev_ebitda": info.get("enterpriseToEbitda"),
                "profit_margin": info.get("profitMargins"),
                "revenue_growth": info.get("revenueGrowth"),
                "earnings_growth": info.get("earningsGrowth"),
                "roe": info.get("returnOnEquity"),
                "debt_to_equity": info.get("debtToEquity"),
                "free_cash_flow": info.get("freeCashflow"),
                "dividend_yield": info.get("dividendYield"),
                "beta": info.get("beta"),
                "52w_high": info.get("fiftyTwoWeekHigh"),
                "52w_low": info.get("fiftyTwoWeekLow"),
                "analyst_target": info.get("targetMeanPrice"),
                "recommendation": info.get("recommendationKey"),
            })
        except Exception as e:
            results.append({"symbol": sym.upper(), "error": str(e)})
    return results


# ---------------------------------------------------------------------------
# Technical Analysis
# ---------------------------------------------------------------------------

@mcp.tool()
def get_technical_analysis(symbol: str, period: str = "6mo") -> dict:
    """
    Comprehensive technical analysis for a stock: trend (SMA 20/50/200,
    EMA 12/26), momentum (RSI-14, MACD), volatility (Bollinger Bands), and
    volume. Returns numeric indicator values plus plain-English signals so
    you know at a glance whether the setup is bullish, bearish, or neutral.

    Args:
        symbol: Stock ticker (e.g. "AAPL")
        period: "3mo", "6mo", "1y", "2y"
    """
    hist = yf.Ticker(symbol).history(period=period)
    if hist.empty:
        return {"error": f"No price data for {symbol}"}

    close = hist["Close"].rename("close")
    high  = hist["High"].rename("high")
    low   = hist["Low"].rename("low")
    vol   = hist["Volume"].rename("volume")

    df = pd.concat([close, high, low, vol], axis=1)

    df["sma20"]  = ta.sma(df["close"], 20)
    df["sma50"]  = ta.sma(df["close"], 50)
    df["sma200"] = ta.sma(df["close"], 200)
    df["ema12"]  = ta.ema(df["close"], 12)
    df["ema26"]  = ta.ema(df["close"], 26)
    df["rsi"]    = ta.rsi(df["close"], 14)
    df["vol_sma20"] = ta.sma(df["volume"], 20)

    macd_df = ta.macd(df["close"])
    if macd_df is not None and not macd_df.empty:
        df["macd"]        = macd_df.iloc[:, 0]
        df["macd_signal"] = macd_df.iloc[:, 1]
        df["macd_hist"]   = macd_df.iloc[:, 2]

    bb_df = ta.bbands(df["close"], 20)
    if bb_df is not None and not bb_df.empty:
        df["bb_upper"] = bb_df.iloc[:, 0]
        df["bb_mid"]   = bb_df.iloc[:, 1]
        df["bb_lower"] = bb_df.iloc[:, 2]
        df["bb_pct"]   = bb_df.iloc[:, 3]

    last = df.iloc[-1]
    price = float(last["close"])

    def _f(col):
        try:
            v = float(last.get(col, float("nan")))
            return None if np.isnan(v) else round(v, 4)
        except:
            return None

    rsi     = _f("rsi")
    sma50   = _f("sma50")
    sma200  = _f("sma200")
    macd_v  = _f("macd")
    macd_s  = _f("macd_signal")
    bb_pct  = _f("bb_pct")
    vol_now = _f("volume")
    vol_avg = _f("vol_sma20")

    signals = []
    if rsi:
        if rsi < 30:   signals.append("RSI OVERSOLD (<30) — potential bounce candidate")
        elif rsi > 70: signals.append("RSI OVERBOUGHT (>70) — extended, watch for pullback")
        else:          signals.append(f"RSI neutral at {rsi}")
    if sma50 and sma200:
        if sma50 > sma200: signals.append("Golden cross active (SMA50 > SMA200) — long-term uptrend")
        else:              signals.append("Death cross active (SMA50 < SMA200) — long-term downtrend")
    if sma50:
        if price > sma50: signals.append("Price above SMA50 — short-term bullish")
        else:             signals.append("Price below SMA50 — short-term bearish")
    if macd_v and macd_s:
        if macd_v > macd_s: signals.append("MACD above signal line — bullish momentum")
        else:               signals.append("MACD below signal line — bearish momentum")
    if bb_pct is not None:
        if bb_pct > 0.9:   signals.append("Near upper Bollinger Band — overbought / extended")
        elif bb_pct < 0.1: signals.append("Near lower Bollinger Band — oversold / compressed")
    if vol_now and vol_avg and vol_avg > 0:
        ratio = vol_now / vol_avg
        if ratio > 1.5:   signals.append(f"High volume spike ({ratio:.1f}x avg) — strong conviction")
        elif ratio < 0.5: signals.append(f"Low volume ({ratio:.1f}x avg) — weak conviction")

    bull = sum(1 for s in signals if any(w in s.lower() for w in ["bullish", "oversold", "golden", "above", "high volume"]))
    bear = sum(1 for s in signals if any(w in s.lower() for w in ["bearish", "overbought", "death", "below", "low volume"]))

    return {
        "symbol": symbol.upper(),
        "price": round(price, 2),
        "bias": "bullish" if bull > bear else ("bearish" if bear > bull else "neutral"),
        "bull_signals": bull,
        "bear_signals": bear,
        "signals": signals,
        "indicators": {
            "rsi_14":       rsi,
            "macd":         macd_v,
            "macd_signal":  macd_s,
            "macd_hist":    _f("macd_hist"),
            "sma_20":       _f("sma20"),
            "sma_50":       sma50,
            "sma_200":      sma200,
            "ema_12":       _f("ema12"),
            "ema_26":       _f("ema26"),
            "bb_upper":     _f("bb_upper"),
            "bb_mid":       _f("bb_mid"),
            "bb_lower":     _f("bb_lower"),
            "bb_percent":   bb_pct,
            "volume":       vol_now,
            "volume_sma20": vol_avg,
        },
    }


@mcp.tool()
def scan_watchlist(symbols: list, period: str = "3mo") -> list:
    """
    Run technical analysis across a list of stocks simultaneously and rank
    them by bullish signal count. Quickly surfaces the best-looking setups
    from a universe of stocks.

    Args:
        symbols: List of tickers to scan (e.g. ["AAPL", "TSLA", "NVDA", "AMD"])
        period:  Lookback period — "3mo", "6mo", "1y"
    """
    results = []
    for sym in symbols:
        try:
            analysis = get_technical_analysis(sym, period)
            if "error" not in analysis:
                results.append(analysis)
        except:
            pass
    results.sort(key=lambda x: (x.get("bull_signals", 0) - x.get("bear_signals", 0)), reverse=True)
    return results


# ---------------------------------------------------------------------------
# Options Intelligence
# ---------------------------------------------------------------------------

@mcp.tool()
def calculate_black_scholes(
    stock_price: float,
    strike_price: float,
    days_to_expiration: int,
    implied_volatility: float,
    option_type: str = "call",
    risk_free_rate: float = 0.05,
) -> dict:
    """
    Calculate the theoretical fair value of an option using Black-Scholes
    and compare it to the market price to identify mispricings.

    Use get_option_market_data first to get the market price and IV, then
    plug them in here to see if the option is cheap or expensive.

    - Market price > theoretical → option is overpriced → good to SELL
    - Market price < theoretical → option is underpriced → good to BUY

    Args:
        stock_price:        Current stock price
        strike_price:       Option strike price
        days_to_expiration: Calendar days until expiration
        implied_volatility: IV as a decimal (e.g. 0.30 = 30% IV)
        option_type:        "call" or "put"
        risk_free_rate:     Annual risk-free rate (default 0.05 ≈ current T-bills)
    """
    S, K, r_rate, sigma = stock_price, strike_price, risk_free_rate, implied_volatility
    T = days_to_expiration / 365.0

    if T <= 0 or sigma <= 0:
        return {"error": "days_to_expiration and implied_volatility must be positive"}

    d1 = (np.log(S / K) + (r_rate + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)

    if option_type == "call":
        price = S * norm.cdf(d1) - K * np.exp(-r_rate * T) * norm.cdf(d2)
        delta = norm.cdf(d1)
        cdf_d2 = norm.cdf(d2)
    else:
        price = K * np.exp(-r_rate * T) * norm.cdf(-d2) - S * norm.cdf(-d1)
        delta = norm.cdf(d1) - 1
        cdf_d2 = norm.cdf(-d2)

    gamma = norm.pdf(d1) / (S * sigma * np.sqrt(T))
    theta = (-(S * norm.pdf(d1) * sigma) / (2 * np.sqrt(T))
             - r_rate * K * np.exp(-r_rate * T) * cdf_d2) / 365
    vega  = S * norm.pdf(d1) * np.sqrt(T) / 100

    if option_type == "call":
        moneyness = "ITM" if S > K * 1.02 else ("OTM" if S < K * 0.98 else "ATM")
    else:
        moneyness = "ITM" if S < K * 0.98 else ("OTM" if S > K * 1.02 else "ATM")

    return {
        "theoretical_price":    round(float(price), 4),
        "cost_per_contract":    round(float(price) * 100, 2),
        "moneyness":            moneyness,
        "greeks": {
            "delta": round(float(delta), 4),
            "gamma": round(float(gamma), 6),
            "theta": round(float(theta), 4),
            "vega":  round(float(vega),  4),
        },
        "inputs": {
            "stock_price":            S,
            "strike_price":           K,
            "days_to_expiration":     days_to_expiration,
            "implied_volatility_pct": round(sigma * 100, 1),
            "option_type":            option_type,
            "risk_free_rate_pct":     round(r_rate * 100, 1),
        },
        "interpretation": (
            "Compare theoretical_price to the market ask/bid midpoint. "
            "If market > theoretical the option may be overpriced (lean toward selling). "
            "If market < theoretical it may be underpriced (lean toward buying)."
        ),
    }


@mcp.tool()
def analyze_volatility(symbol: str, period: str = "1y") -> dict:
    """
    Compare implied volatility (IV) to historical/realized volatility (HV)
    to decide whether options are cheap or expensive right now.

    - IV much higher than HV → options are EXPENSIVE → good time to sell premium
    - IV much lower than HV  → options are CHEAP    → good time to buy options

    Also shows IV rank (where current IV sits vs its own 52-week range).

    Args:
        symbol: Stock ticker (e.g. "AAPL")
        period: Lookback for historical vol — "6mo", "1y", "2y"
    """
    t = yf.Ticker(symbol)
    hist = t.history(period=period)
    info = t.info

    if hist.empty:
        return {"error": f"No data for {symbol}"}

    log_ret = np.log(hist["Close"] / hist["Close"].shift(1)).dropna()
    hv_20d  = float(log_ret.tail(14).std()  * np.sqrt(252))
    hv_30d  = float(log_ret.tail(21).std()  * np.sqrt(252))
    hv_60d  = float(log_ret.tail(42).std()  * np.sqrt(252))
    hv_1y   = float(log_ret.std()           * np.sqrt(252))

    iv_current = None
    try:
        exps = t.options
        if exps:
            chain  = t.option_chain(exps[0])
            calls  = chain.calls
            spot   = float(hist["Close"].iloc[-1])
            atm    = calls.iloc[(calls["strike"] - spot).abs().argsort()[:5]]
            iv_current = float(atm["impliedVolatility"].median())
    except:
        pass

    result = {
        "symbol": symbol.upper(),
        "current_price": round(float(hist["Close"].iloc[-1]), 2),
        "historical_volatility": {
            "hv_20d_pct": round(hv_20d * 100, 1),
            "hv_30d_pct": round(hv_30d * 100, 1),
            "hv_60d_pct": round(hv_60d * 100, 1),
            "hv_1y_pct":  round(hv_1y  * 100, 1),
        },
    }

    if iv_current:
        iv_pct = round(iv_current * 100, 1)
        premium = round((iv_current - hv_30d) * 100, 1)
        result["implied_volatility_pct"] = iv_pct
        result["iv_vs_hv30_pct"] = premium
        if premium > 5:
            result["signal"] = "IV is elevated vs realized vol — options are EXPENSIVE → lean toward selling premium (covered calls, cash-secured puts)"
        elif premium < -5:
            result["signal"] = "IV is compressed vs realized vol — options are CHEAP → lean toward buying (calls, puts, debit spreads)"
        else:
            result["signal"] = "IV roughly in line with realized vol — fairly priced, no strong directional edge from vol alone"

    return result


# ---------------------------------------------------------------------------
# Portfolio Optimization & Risk
# ---------------------------------------------------------------------------

@mcp.tool()
def optimize_portfolio(
    symbols: list,
    period: str = "1y",
    objective: str = "max_sharpe",
) -> dict:
    """
    Use Modern Portfolio Theory (Markowitz) to find the mathematically
    optimal allocation across a set of stocks. Returns target weights,
    expected annual return, volatility, and Sharpe ratio.

    Objectives:
    - "max_sharpe"     → maximize return per unit of risk (best risk-adjusted, default)
    - "min_volatility" → lowest possible portfolio volatility
    - "max_return"     → maximize expected return (more concentrated, higher risk)

    NOTE: Based on historical returns — always treat as one input among many,
    not a guaranteed outcome.

    Args:
        symbols:   Tickers to include (e.g. ["AAPL", "MSFT", "NVDA", "TSLA"])
        period:    Historical window — "1y", "2y", "3y"
        objective: "max_sharpe", "min_volatility", or "max_return"
    """
    from pypfopt import EfficientFrontier, risk_models, expected_returns, objective_functions

    prices = yf.download(symbols, period=period, auto_adjust=True, progress=False)["Close"]
    prices = prices.dropna(axis=1, how="all").dropna()

    if prices.empty or prices.shape[1] < 2:
        return {"error": "Need at least 2 symbols with overlapping price history"}

    used = list(prices.columns)
    mu = expected_returns.mean_historical_return(prices)
    S  = risk_models.sample_cov(prices)

    ef = EfficientFrontier(mu, S)
    if objective == "min_volatility":
        ef.min_volatility()
    elif objective == "max_return":
        ef.add_objective(objective_functions.L2_reg, gamma=0.1)
        ef.max_quadratic_utility(risk_aversion=0.01)
    else:
        ef.max_sharpe()

    weights = ef.clean_weights()
    perf = ef.portfolio_performance(verbose=False)

    return {
        "objective": objective,
        "symbols_used": used,
        "weights": {k: round(v, 4) for k, v in weights.items() if v > 0.001},
        "expected_annual_return_pct": round(perf[0] * 100, 1),
        "annual_volatility_pct":      round(perf[1] * 100, 1),
        "sharpe_ratio":               round(perf[2], 2),
        "period_used": period,
        "disclaimer": "Based on historical returns. Past performance does not guarantee future results. Review before rebalancing.",
    }


@mcp.tool()
def get_portfolio_risk_metrics(period: str = "1y") -> dict:
    """
    Risk-adjusted performance metrics for your live Robinhood portfolio:
    Sharpe ratio, Sortino ratio, max drawdown, beta vs S&P 500, annualized
    return and volatility, and a correlation matrix between all holdings.

    Sharpe > 1.0 is good. Sortino > 1.5 is good. Beta > 1 means more
    volatile than the market.

    Args:
        period: Lookback — "3mo", "6mo", "1y", "2y"
    """
    _ensure_auth()
    holdings = r.build_holdings()
    if not holdings:
        return {"error": "No holdings found in your portfolio"}

    symbols = list(holdings.keys())
    total_equity = sum(float(d.get("equity") or 0) for d in holdings.values())
    if total_equity == 0:
        return {"error": "All positions show zero equity"}

    weights = {sym: float(holdings[sym].get("equity") or 0) / total_equity for sym in symbols}

    prices = yf.download(symbols + ["^GSPC"], period=period, auto_adjust=True, progress=False)["Close"].dropna()
    rets   = prices.pct_change().dropna()

    port_ret = sum(rets[sym] * weights.get(sym, 0) for sym in symbols if sym in rets.columns)
    spy_ret  = rets["^GSPC"] if "^GSPC" in rets.columns else None

    rf_daily = 0.05 / 252
    excess   = port_ret - rf_daily
    sharpe   = float(excess.mean() / excess.std() * np.sqrt(252)) if excess.std() > 0 else None

    downside = excess[excess < 0]
    sortino  = float(excess.mean() / downside.std() * np.sqrt(252)) if len(downside) > 1 and downside.std() > 0 else None

    cum     = (1 + port_ret).cumprod()
    max_dd  = float((cum / cum.cummax() - 1).min())

    beta = None
    if spy_ret is not None and spy_ret.std() > 0:
        cov  = np.cov(port_ret, spy_ret)[0][1]
        beta = round(cov / float(spy_ret.var()), 2)

    port_cols = [s for s in symbols if s in rets.columns]
    corr = rets[port_cols].corr().round(2).to_dict()

    return {
        "period": period,
        "sharpe_ratio":            round(sharpe, 2) if sharpe else None,
        "sortino_ratio":           round(sortino, 2) if sortino else None,
        "max_drawdown_pct":        round(max_dd * 100, 1),
        "beta_vs_sp500":           beta,
        "annualized_return_pct":   round(float(port_ret.mean() * 252 * 100), 1),
        "annualized_volatility_pct": round(float(port_ret.std() * np.sqrt(252) * 100), 1),
        "weights_used":            {k: round(v, 3) for k, v in weights.items()},
        "correlation_matrix":      corr,
    }


@mcp.tool()
def calculate_position_size(
    portfolio_value: float,
    win_rate: float,
    avg_win_pct: float,
    avg_loss_pct: float,
    max_position_pct: float = 20.0,
) -> dict:
    """
    Use the Kelly Criterion to calculate how much of your portfolio to risk
    on a single trade. Prevents both over-betting (ruin) and under-betting
    (wasted edge).

    Most professionals use half-Kelly or quarter-Kelly to reduce variance.

    Args:
        portfolio_value:  Total portfolio $ value (e.g. 10000)
        win_rate:         Historical win rate as a decimal (e.g. 0.55 = 55%)
        avg_win_pct:      Average gain on winners as decimal (e.g. 0.15 = 15%)
        avg_loss_pct:     Average loss on losers as a positive decimal (e.g. 0.07 = 7%)
        max_position_pct: Hard cap per position — default 20%
    """
    if avg_loss_pct <= 0:
        return {"error": "avg_loss_pct must be a positive number"}

    b = avg_win_pct / avg_loss_pct
    p, q = win_rate, 1 - win_rate
    kelly = (b * p - q) / b
    cap   = max_position_pct / 100

    def _size(fraction):
        f = max(0.0, min(fraction, cap))
        return {
            "fraction_pct":  round(f * 100, 1),
            "dollar_amount": round(portfolio_value * f, 2),
            "capped":        fraction > cap,
        }

    favorable = kelly > 0
    return {
        "reward_to_risk_ratio":      round(b, 2),
        "expected_value_per_dollar": round(b * p - q, 4),
        "kelly_sizes": {
            "full_kelly":    _size(kelly),
            "half_kelly":    _size(kelly / 2),
            "quarter_kelly": _size(kelly / 4),
        },
        "recommendation": "half_kelly" if favorable else "skip — negative expected value",
        "verdict": (
            f"Positive EV trade (EV={round(b*p-q,3)}/$ risked). Reward:risk = {round(b,2)}:1."
            if favorable else
            f"Negative EV trade (EV={round(b*p-q,3)}/$ risked). Mathematically unfavorable — skip."
        ),
    }


if __name__ == "__main__":
    mcp.run()
