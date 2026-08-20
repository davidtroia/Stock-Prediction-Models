# Stock Alert App

A standalone Python app that watches a list of stocks and sends you a **Telegram
notification** when one is *about to* meet — or has met — your criteria.

Every rule produces two kinds of alert:

- **⏳ ABOUT TO MEET** — the stock is within a proximity band of your criterion
  (e.g. within 1% of a price target, or RSI within 5 points of oversold). This
  is the early warning.
- **🚨 MET** — the criterion is satisfied right now.

It uses [yfinance](https://pypi.org/project/yfinance/) for market data, so it
needs no brokerage login just to read prices and can run anywhere. The
indicator math (RSI, MACD, Bollinger, SMAs) mirrors the signals in this repo's
`robinhood-mcp` server.

## Supported criteria

| Rule type | Fires when… |
|---|---|
| `price_above` / `price_below` | price crosses a level you set |
| `pct_move` | daily percent move exceeds a threshold (up / down / both) |
| `rsi` | RSI reaches overbought / oversold |
| `macd_cross` | MACD line crosses its signal line (bullish / bearish) |
| `ma_cross` | fast SMA crosses a slow SMA (golden / death cross) |
| `bollinger` | price touches the upper / lower band |
| `near_52w_high` / `near_52w_low` | price approaches or breaks a 52-week extreme |
| `volume_spike` | volume is an unusual multiple of its average |

## Install

```bash
cd stock-alerts
pip install -r requirements.txt
```

## Set up Telegram (one time)

1. In Telegram, message **@BotFather**, send `/newbot`, follow the prompts, and
   copy the **bot token** it gives you.
2. Open a chat with your new bot and send it any message (this lets the bot
   message you back).
3. Get your **chat id**: visit
   `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser and read
   `result[].message.chat.id`, or message **@userinfobot**.
4. Export both:

   ```bash
   export TELEGRAM_BOT_TOKEN="123456:ABC-..."
   export TELEGRAM_CHAT_ID="987654321"
   ```

## Configure your alerts

```bash
cp config.example.yaml config.yaml
# edit config.yaml — add your symbols and rules
```

See `config.example.yaml` for every rule type and its options. Each watch entry
is one symbol with a list of rules. Proximity bands (how early the "about to
meet" alert fires) have sensible defaults and can be overridden per rule.

## Run

```bash
# One pass, then exit — ideal for cron
python app.py --once

# Poll continuously (every 5 minutes here)
python app.py --loop --interval 300

# Print to the console instead of sending (test your rules)
python app.py --once --dry-run

# List the supported rule types
python app.py --list-rule-types
```

### Run on a schedule with cron

Every 5 minutes on weekdays during US market hours (9am–4pm ET ≈ 14:00–21:00 UTC):

```cron
*/5 14-21 * * 1-5  cd /path/to/stock-alerts && \
  TELEGRAM_BOT_TOKEN=xxx TELEGRAM_CHAT_ID=yyy /usr/bin/python app.py --once >> alerts.log 2>&1
```

Set `market_hours_only: true` in the config if you'd rather gate market hours in
the app than in the cron schedule.

## How re-alerting is controlled

The app records what it has already told you in `state.json` and won't resend
the same alert until:

- the **cooldown** window (`cooldown_minutes`, default 60) has elapsed, or
- the status **escalates** from *approaching* to *met* — that always notifies.

Delete `state.json` to reset all alert history.

## Testing

```bash
python test_alerts.py
```

The tests use synthetic price series and run fully offline (no network), and
cover every rule type plus the dedupe/cooldown logic.

## Notes & limitations

- yfinance data is delayed (typically ~15 min) and unofficial — fine for alerts,
  not for execution timing.
- Cross rules (`macd_cross`, `ma_cross`) are point-in-time: run the app on a
  schedule so it evaluates each new bar. The "about to meet" state fires when
  the two lines are converging and within a small band.
- This app only **notifies**; it never places trades.
