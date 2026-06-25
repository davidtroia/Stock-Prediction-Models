## How-to, this model based on [evolution-strategy](https://github.com/huseinzol05/Stock-Prediction-Models/tree/master/agent)

1. You can check [realtime-evolution-strategy.ipynb](realtime-evolution-strategy.ipynb) for to train an evolution strategy to do realtime trading.

I trained the model to learn trading on different stocks,

```python
['TWTR.csv',
 'GOOG.csv',
 'FB.csv',
 'LB.csv',
 'MTDR.csv',
 'CPRT.csv',
 'FSV.csv',
 'TSLA.csv',
 'SINA.csv',
 'GWR.csv']
```

You might want to add more to cover more stochastic patterns.

2. Run [app.py](app.py) to serve the checkpoint model using Flask,

```bash
python3 app.py
```

```text
* Serving Flask app "app" (lazy loading)
* Environment: production
  WARNING: This is a development server. Do not use it in a production deployment.
  Use a production WSGI server instead.
* Debug mode: off
* Running on http://0.0.0.0:8005/ (Press CTRL+C to quit)
```

3. You can check requests example in [request.ipynb](request.ipynb) to get a kickstart.

```bash
curl http://localhost:8005/trade?data=[13.1, 13407500]
```

```python
{'action': 'sell', 'balance': 971.1199990000001, 'investment': '10.224268 %', 'status': 'sell 1 unit, price 16.709999', 'timestamp': '2019-05-26 01:12:10.370206'}
{'action': 'nothing', 'balance': 971.1199990000001, 'status': 'do nothing', 'timestamp': '2019-05-26 01:12:10.376245'}
{'action': 'sell', 'balance': 987.7799990000001, 'investment': '11.066667 %', 'status': 'sell 1 unit, price 16.660000', 'timestamp': '2019-05-26 01:12:10.382282'}
{'action': 'nothing', 'balance': 987.7799990000001, 'status': 'do nothing', 'timestamp': '2019-05-26 01:12:10.388330'}
{'action': 'nothing', 'balance': 987.7799990000001, 'status': 'do nothing', 'timestamp': '2019-05-26 01:12:10.394324'}
{'action': 'sell', 'balance': 1006.1299990000001, 'investment': '18.387097 %', 'status': 'sell 1 unit, price 18.350000', 'timestamp': '2019-05-26 01:12:10.400104'}
{'action': 'nothing', 'balance': 1006.1299990000001, 'status': 'do nothing', 'timestamp': '2019-05-26 01:12:10.405804'}
{'action': 'nothing', 'balance': 1006.1299990000001, 'status': 'do nothing', 'timestamp': '2019-05-26 01:12:10.411531'}
```

## Live Trading with Robinhood MCP

The Flask agent connects to a live Robinhood account via MCP (Model Context Protocol).

### Cloud (claude.ai/code)

The MCP server is already configured at `~/.claude/mcp.json`. Open a session and run `/trade-robinhood` for a single cycle, or `/start-trading-loop` to initialize the agent.

### Claude Desktop (Mac)

**Step 1** — Check your current config:
```bash
cat ~/Library/Application\ Support/Claude/claude_desktop_config.json
```

**Step 2** — Find your local MCP server path:
```bash
find ~ -name "server.py" -path "*/robinhood-mcp/*" 2>/dev/null
```

**Step 3** — Add the Robinhood server to your config (merge with any existing entries):
```json
{
  "mcpServers": {
    "robinhood-trading": {
      "command": "python3",
      "args": ["/path/to/robinhood-mcp/server.py"]
    }
  }
}
```
Replace `/path/to/robinhood-mcp/server.py` with the path from Step 2.

**Step 4** — Fully quit Claude Desktop (menu bar → Claude → Quit), reopen, then type:
> "Get my account info"

If it returns your balance, you're connected. If not, check that the path in Step 2 is correct.

### Morning Routine

1. "Get the market overview" — check indices + VIX
2. "Scan [tickers] for technical setups" — find high-volume unusual movers
3. "Get my portfolio allocation" — know your position
4. Run `/trade-robinhood` to execute a cycle

### Trading Config

Edit [`trading_config.json`](trading_config.json) to change ticker, shares per trade, or timing:
```json
{
  "ticker": "TSLA",
  "shares_per_trade": 1,
  "check_interval_minutes": 60
}
```

## Notes

1. You can use this code to integrate with realtime socket, or any APIs you wanted, imagination is your limit now.
