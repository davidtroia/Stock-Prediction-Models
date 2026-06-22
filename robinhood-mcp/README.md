# Robinhood Trading MCP Server

An [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) server that exposes Robinhood brokerage account operations as tools for AI assistants.

## Prerequisites

- Python 3.10+
- A Robinhood brokerage account

## Installation

```bash
cd robinhood-mcp
pip install -r requirements.txt
```

## Configuration

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
```

| Variable | Required | Description |
|---|---|---|
| `ROBINHOOD_USERNAME` | Yes | Robinhood account email |
| `ROBINHOOD_PASSWORD` | Yes | Robinhood account password |
| `ROBINHOOD_MFA_CODE` | No | Current TOTP code (for 2FA accounts) |

> **Security note:** Credentials are read from environment variables, never passed as tool arguments. Keep your `.env` file out of version control.

## Running the Server

```bash
# Load env and start
export $(cat .env | xargs) && python server.py

# Or with the MCP CLI
mcp run server.py
```

## Claude Desktop / Claude Code Integration

Add to your `claude_desktop_config.json` (or MCP settings):

```json
{
  "mcpServers": {
    "robinhood-trading": {
      "command": "python",
      "args": ["/path/to/robinhood-mcp/server.py"],
      "env": {
        "ROBINHOOD_USERNAME": "your_email@example.com",
        "ROBINHOOD_PASSWORD": "your_password"
      }
    }
  }
}
```

## Available Tools

### Account & Portfolio
| Tool | Description |
|---|---|
| `get_account_info` | Account number, buying power, cash balance, portfolio value |
| `get_portfolio_holdings` | All stock positions with quantity, cost basis, and current value |
| `get_total_equity` | Summary of total equity, extended-hours value, and cash |
| `get_portfolio_allocation` | Current holdings as dollar values and % of total equity (including cash) |
| `calculate_rebalance_trades` | Dry-run: see exactly what trades are needed to hit target allocations |
| `rebalance_portfolio` | Rebalance to target allocations — dry_run=True by default, set False to execute |

### Market Data
| Tool | Description |
|---|---|
| `get_stock_quote` | Real-time bid/ask/last price, volume, and market cap |
| `get_historical_prices` | OHLCV bars with configurable interval and span |
| `search_stocks` | Search instruments by company name or partial ticker |
| `get_stock_fundamentals` | P/E ratio, EPS, dividend yield, sector, description |
| `get_stock_news` | Recent news articles for a symbol |
| `get_earnings` | Historical and upcoming earnings reports |

### Orders — Stocks
| Tool | Description |
|---|---|
| `place_market_buy_order` | Market buy (fills immediately at best available price) |
| `place_limit_buy_order` | Limit buy (fills only at or below your limit price) |
| `place_market_sell_order` | Market sell |
| `place_limit_sell_order` | Limit sell |
| `place_stop_loss_order` | Stop-loss sell (triggers market order when price drops to stop) |
| `place_stop_limit_order` | Stop-limit buy or sell |
| `get_open_orders` | All pending/unfilled orders |
| `get_order_history` | Recent order history |
| `cancel_order` | Cancel a specific order by ID |
| `cancel_all_open_orders` | Cancel every open order at once |

### Market Intelligence
| Tool | Description |
|---|---|
| `get_market_overview` | S&P 500, NASDAQ, Dow, Russell 2000, VIX, 10-yr yield, gold, oil |
| `get_sector_performance` | All 11 S&P 500 sectors ranked by performance for any period |
| `get_analyst_consensus` | Analyst ratings, price targets, implied upside, recent upgrades/downgrades |
| `get_institutional_holdings` | Top institutions and mutual funds holding a stock |
| `compare_stocks` | Side-by-side fundamental comparison of multiple stocks |

### Technical Analysis
| Tool | Description |
|---|---|
| `get_technical_analysis` | RSI, MACD, Bollinger Bands, SMA/EMA, volume — with plain-English signals |
| `scan_watchlist` | Run TA across a list of stocks and rank by bullish signal count |

### Options Intelligence
| Tool | Description |
|---|---|
| `calculate_black_scholes` | Theoretical fair value + Greeks — compare to market price to find mispricings |
| `analyze_volatility` | IV vs historical vol — tells you whether options are cheap or expensive |

### Portfolio Optimization & Risk
| Tool | Description |
|---|---|
| `optimize_portfolio` | Modern Portfolio Theory — finds max-Sharpe, min-vol, or max-return weights |
| `get_portfolio_risk_metrics` | Sharpe, Sortino, max drawdown, beta, annualized return, correlation matrix |
| `calculate_position_size` | Kelly Criterion — how much to bet per trade given your win rate and R:R ratio |

### Options — Discovery
| Tool | Description |
|---|---|
| `get_options_expiration_dates` | Available expiration dates for a symbol |
| `get_options_chain` | Full chain (calls, puts, or both) with Greeks for a given expiry |
| `find_options_by_strike` | All contracts at a specific strike price across all expirations |
| `find_options_near_money` | ATM ± N strikes for rapid liquidity scanning |
| `get_option_market_data` | Live bid/ask, Greeks, IV, break-even, and chance-of-profit for one contract |

### Options — Trading
| Tool | Description |
|---|---|
| `buy_option_to_open` | Buy to open a long call or put position |
| `sell_option_to_close` | Sell to close an existing long position |
| `sell_option_to_open` | Write (sell to open) a call or put — collects premium |
| `buy_option_to_close` | Buy to close a short (written) position |

### Options — Order Management
| Tool | Description |
|---|---|
| `get_open_options_positions` | Current open options positions |
| `get_open_option_orders` | All pending/unfilled option orders |
| `get_option_order_history` | Recent option order history |
| `cancel_option_order` | Cancel a specific option order by ID |
| `cancel_all_option_orders` | Cancel every open option order at once |

### Crypto
| Tool | Description |
|---|---|
| `get_crypto_quote` | Current bid/ask/mark price for a cryptocurrency |
| `get_crypto_holdings` | All crypto positions held |
| `place_crypto_market_buy` | Buy crypto by dollar amount |
| `place_crypto_market_sell` | Sell crypto by quantity |

### Watchlists
| Tool | Description |
|---|---|
| `get_watchlist` | Symbols in a named watchlist |
| `add_to_watchlist` | Add a symbol to a watchlist |
| `remove_from_watchlist` | Remove a symbol from a watchlist |

## Disclaimer

This tool uses Robinhood's unofficial API via `robin_stocks`. Use at your own risk. This is not financial advice. Always verify orders before placing them in a live account.
