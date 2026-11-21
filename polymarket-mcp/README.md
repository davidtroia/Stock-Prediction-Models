# Polymarket US Trading MCP Server

An MCP server for reading and trading [Polymarket US](https://polymarket.us) prediction
markets, built on the official `polymarket-us` SDK. Same shape as `robinhood-mcp/`:
credentials and risk limits come from environment variables, and every order path is
guardrail-checked before anything reaches the exchange.

**25 tools** across market data, account, analysis, and trading.

## How prediction-market pricing works

This is the thing to internalize before trading these — the risk model is different from
equities, and the guardrails here are built around it.

A share costs between $0.00 and $1.00 and settles at exactly $0.00 or $1.00. The price
*is* the market-implied probability:

```
notional paid   = price × quantity
max payout      = quantity × $1.00
max loss (long) = price × quantity        ← you cannot lose more than you paid
profit if right = (1.00 − price) × quantity
```

Buying 100 shares at $0.55 costs $55, pays $100 if right, and loses $55 if wrong.

Because downside is bounded by cost, the guardrails are denominated in **dollars of
notional**, not the percentage-of-portfolio limits `robinhood-mcp` uses for equities.
Cost basis is the honest measure of risk here.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env      # then fill in your keys
```

Get credentials at [polymarket.us/developer](https://polymarket.us/developer), signing in
with the same method you used in the app. Identity verification must be approved first.
**The secret key is shown only once** — copy it before closing the dialog.

```bash
POLYMARKET_KEY_ID=...
POLYMARKET_SECRET_KEY=...     # base64-encoded Ed25519 private key
```

Market-data tools work without credentials. Account and trading tools require them.

Register with your MCP client:

```json
{
  "mcpServers": {
    "polymarket-trading": {
      "command": "python",
      "args": ["/path/to/polymarket-mcp/server.py"]
    }
  }
}
```

## Guardrails

Every limit is read from the environment **at call time**, so editing `.env` takes effect
on the next call without a restart. All are enforced before any order is sent.

| Variable | Default | Blocks |
|---|---|---|
| `MAX_SINGLE_ORDER_USD` | 50 | Any one order above this notional |
| `MAX_MARKET_EXPOSURE_USD` | 100 | Total dollars at risk in one market |
| `MAX_TOTAL_EXPOSURE_USD` | 500 | Total dollars at risk across all markets |
| `MIN_CASH_RESERVE_USD` | 25 | Orders that would spend below this cash floor |
| `DAILY_LOSS_LIMIT_USD` | 50 | New buys after losing this much in a day |
| `MAX_OPEN_POSITIONS` | 10 | Opening an 11th distinct market |
| `MIN_PRICE` | 0.05 | Buying longshots below 5¢ |
| `MAX_PRICE` | 0.95 | Buying near-certainties above 95¢ |
| `MAX_SLIPPAGE_BIPS` | 200 | Caps slippage tolerance (capped down, not rejected) |
| `ALLOWED_CATEGORIES` | *(empty)* | Everything outside the whitelist, if set |
| `BLOCKED_CATEGORIES` | *(empty)* | Listed categories |
| `BLOCKED_MARKET_SLUGS` | *(empty)* | Listed market slugs |

Three deliberate design decisions:

- **Exits are never blocked.** `close_position` and sell-side orders bypass the
  extreme-price guard entirely. A risk limit that traps you in a position is worse
  than no limit.
- **Fail closed.** If account state can't be verified, buys are blocked rather than
  allowed through unchecked.
- **All violations reported at once.** A rejected order lists every reason it failed, not
  just the first, so you can fix the request in one pass.

Orders are flagged `MANUAL_ORDER_INDICATOR_AUTOMATIC` (FIX tag 1028 semantics), which is
what an automated system should report. Override with `POLYMARKET_MARK_ORDERS_MANUAL=true`
only if you have a specific reason.

## Tools

### Market data (no credentials needed)
| Tool | Purpose |
|---|---|
| `search_markets` | Full-text search — start here to find a slug |
| `list_events` | List events, filterable by tag/volume |
| `get_event` | One event and all its markets |
| `list_markets` | List markets, filterable by liquidity/volume |
| `get_market` | Full market detail incl. resolution criteria |
| `get_book` | Full order book, all levels |
| `get_quote` | BBO plus derived spread and implied probability |
| `get_settlement` | How a market resolved |
| `list_sports` | Available sports |
| `list_series` | Recurring event series |

### Account
| Tool | Purpose |
|---|---|
| `get_balances` | Cash and buying power |
| `get_positions` | Open positions |
| `get_activities` | Fills, settlements, transfers |
| `list_open_orders` | Resting orders |
| `get_order` | One order by ID |
| `portfolio_summary` | Exposure by market + headroom under each limit |
| `get_trading_limits` | Active guardrail config |

### Analysis
| Tool | Purpose |
|---|---|
| `check_order` | Run guardrails on a hypothetical order, no network |
| `analyze_edge` | Your probability vs market price → EV and Kelly sizing |

### Trading
| Tool | Purpose |
|---|---|
| `preview_order` | Exchange simulation + local guardrail verdict |
| `place_order` | Place a real order (guardrail-blocked) |
| `modify_order` | Re-price/resize a resting order (re-checked) |
| `cancel_order` | Cancel one order |
| `cancel_all_orders` | Cancel all, optionally per-market |
| `close_position` | Exit a market at market price (never blocked) |

## Measuring edge

`analyze_edge` computes edge against the **ask** — what you actually pay — not the mid,
because an edge that only exists at the mid isn't an edge you can trade.

```
edge          = your_probability − ask
EV per share  = your_probability − ask
Kelly f*      = (p·b − (1−p)) / b,   where b = (1 − ask) / ask
```

It reports both full and half Kelly. Half Kelly is the more defensible default —
full Kelly assumes your probability estimate is exactly right, and on prediction markets
it usually isn't.

## Testing

`test_guardrails.py` covers every rejection path with no credentials or network required:

```bash
python test_guardrails.py     # or: pytest test_guardrails.py
```

```
18 passed, 0 failed, 18 total
```

### Live API diagnostic

`check_api_shapes.py` verifies connectivity and confirms the response field names
this server depends on. Run it once against real credentials before trusting the
exposure guardrails:

```bash
set -a && source .env && set +a
python check_api_shapes.py            # values redacted, shapes only
python check_api_shapes.py --show-values
```

It checks a public endpoint first, then auth, then reports whether the balance and
position field mappings resolve. This matters because a wrong mapping does not
crash — it reads cash and exposure as `$0`, which would make
`MAX_MARKET_EXPOSURE_USD`, `MAX_TOTAL_EXPOSURE_USD`, `MIN_CASH_RESERVE_USD` and
`MAX_OPEN_POSITIONS` silently pass everything. The purely local guards
(`MAX_SINGLE_ORDER_USD`, `MIN_PRICE`/`MAX_PRICE`, block lists) are unaffected.

## Notes

- `mcp` is pinned to `<2.0.0` — `FastMCP` was removed in 2.0 in favor of `MCPServer`.
  (`robinhood-mcp/requirements.txt` specifies `mcp[cli]>=1.0.0` unbounded and imports
  `FastMCP`, so a fresh install there will now resolve to 2.0 and fail on import.)
- The SDK signs requests with Ed25519 over `{timestamp}{method}{path}`. Clock skew will
  surface as an `AuthenticationError`.
- Public data comes from `gateway.polymarket.us`; authenticated calls go to
  `api.polymarket.us`.
