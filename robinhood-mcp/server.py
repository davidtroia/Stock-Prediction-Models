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
    Place a market buy order for a stock.

    Args:
        symbol:   Stock ticker symbol (e.g. "AAPL")
        quantity: Number of shares to buy (fractional shares supported)
    """
    _ensure_auth()
    order = r.order_buy_market(symbol, quantity, timeInForce="gtc", extendedHours=False)
    return _format_order(order)


@mcp.tool()
def place_limit_buy_order(symbol: str, quantity: float, limit_price: float) -> dict:
    """
    Place a limit buy order for a stock.

    Args:
        symbol:      Stock ticker symbol (e.g. "AAPL")
        quantity:    Number of shares to buy
        limit_price: Maximum price per share to pay
    """
    _ensure_auth()
    order = r.order_buy_limit(symbol, quantity, limit_price, timeInForce="gtc", extendedHours=False)
    return _format_order(order)


@mcp.tool()
def place_market_sell_order(symbol: str, quantity: float) -> dict:
    """
    Place a market sell order for a stock.

    Args:
        symbol:   Stock ticker symbol (e.g. "AAPL")
        quantity: Number of shares to sell
    """
    _ensure_auth()
    order = r.order_sell_market(symbol, quantity, timeInForce="gtc", extendedHours=False)
    return _format_order(order)


@mcp.tool()
def place_limit_sell_order(symbol: str, quantity: float, limit_price: float) -> dict:
    """
    Place a limit sell order for a stock.

    Args:
        symbol:      Stock ticker symbol (e.g. "AAPL")
        quantity:    Number of shares to sell
        limit_price: Minimum price per share to accept
    """
    _ensure_auth()
    order = r.order_sell_limit(symbol, quantity, limit_price, timeInForce="gtc", extendedHours=False)
    return _format_order(order)


@mcp.tool()
def place_stop_loss_order(symbol: str, quantity: float, stop_price: float) -> dict:
    """
    Place a stop-loss sell order. Triggers a market sell when the price
    falls to or below stop_price.

    Args:
        symbol:     Stock ticker symbol (e.g. "AAPL")
        quantity:   Number of shares to sell
        stop_price: Price at which the stop order is triggered
    """
    _ensure_auth()
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
    Place a stop-limit order. When the stop price is triggered, a limit order
    is submitted at limit_price.

    Args:
        symbol:      Stock ticker symbol (e.g. "AAPL")
        quantity:    Number of shares
        stop_price:  Price that triggers the order
        limit_price: Limit price for the resulting limit order
        side:        "buy" or "sell"
    """
    _ensure_auth()
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


if __name__ == "__main__":
    mcp.run()
