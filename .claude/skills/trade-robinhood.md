# Robinhood Trading Agent

Execute one full cycle of the live trading loop: get a real-time quote, get a signal from the local ML agent, and execute the trade on Robinhood.

## Steps

### 1. Load config
Read `/home/user/Stock-Prediction-Models/realtime-agent/trading_config.json` to get:
- `ticker` (e.g. TSLA)
- `shares_per_trade`
- `flask_url`
- `log_file`

### 2. Check market hours
Run this to confirm the market is open before doing anything:
```bash
python3 -c "
from datetime import datetime
import pytz
now = datetime.now(pytz.timezone('America/New_York'))
market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)
is_weekday = now.weekday() < 5
is_open = is_weekday and market_open <= now <= market_close
print('OPEN' if is_open else 'CLOSED')
print('time:', now.strftime('%Y-%m-%d %H:%M:%S %Z'))
"
```
If CLOSED, report the status and stop — do not trade.

### 3. Get current quote from Robinhood
Use the `robinhood-trading` MCP tools to fetch the current price and volume for the ticker.

- Look for a tool that gets a stock quote, price, or market data — something like `get_quote`, `get_stock_price`, `get_market_data`, or similar.
- You need: **current close/last price** and **current volume**.
- If you are unsure which tool to use, call the tool that seems most like "get a stock quote" and extract close price and volume from the response.

### 4. Get trade signal from ML agent
The Flask agent must be running on port 8005. Check and start it if needed:

```bash
# Check if running
curl -s http://localhost:8005/ 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print('RUNNING')" 2>/dev/null || echo "NOT_RUNNING"
```

If NOT_RUNNING, start it:
```bash
cd /home/user/Stock-Prediction-Models/realtime-agent
TICKER=<ticker_from_config> nohup python3 app.py > agent.log 2>&1 &
sleep 8
```

Now send the quote to the agent — replace CLOSE and VOLUME with real values:
```bash
curl -s "http://localhost:8005/trade?data=[CLOSE,VOLUME]"
```

Parse the response JSON. The `action` field will be `"buy"`, `"sell"`, or `"nothing"`.

### 5. Execute the trade
Based on the action:

**If `"buy"`:**
- Use the `robinhood-trading` MCP to place a **market buy order** for `shares_per_trade` shares of the ticker.
- Look for a tool like `place_order`, `buy_stock`, `create_order`, or similar.

**If `"sell"`:**
- First check current positions using a tool like `get_positions`, `get_portfolio`, or `get_holdings`.
- Only sell if you actually hold shares of the ticker.
- Place a **market sell order** for `shares_per_trade` shares (or all held shares if fewer than shares_per_trade).

**If `"nothing"`:** 
- No trade. Log it and finish.

### 6. Log the result
Append a JSON record to the log file:
```bash
echo '{"timestamp":"<ISO_TIMESTAMP>","ticker":"<TICKER>","close":<CLOSE>,"volume":<VOLUME>,"signal":"<ACTION>","order_result":"<RESULT_OR_SKIPPED>"}' >> /home/user/Stock-Prediction-Models/realtime-agent/trade_log.jsonl
```

### 7. Report
Print a summary:
- Ticker, current price, signal, action taken (or why skipped)
- Current agent balance from: `curl -s http://localhost:8005/balance`
- Current Robinhood positions for this ticker
