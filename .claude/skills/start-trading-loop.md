# Start Trading Loop

Start the automated trading loop that runs every hour during market hours.

## What this does
Runs `/trade-robinhood` on a recurring schedule using the `/loop` skill. The loop checks market hours on each cycle, so trades only execute when the market is open.

## Steps

1. Verify the Flask agent starts correctly:
```bash
cd /home/user/Stock-Prediction-Models/realtime-agent
TICKER=TSLA python3 -c "
import yfinance as yf
import numpy as np
df = yf.download('TSLA', period='5d', interval='1d', progress=False, auto_adjust=True)
print('Data OK, last close:', df['Close'].iloc[-1])
"
```

2. Start the Flask agent server in the background:
```bash
cd /home/user/Stock-Prediction-Models/realtime-agent
TICKER=TSLA nohup python3 app.py > agent.log 2>&1 &
echo "Flask PID: $!"
sleep 10
curl -s http://localhost:8005/
```

3. Report that the server is running and the trading loop is ready.

4. Tell the user: "Flask agent is running. Use `/loop 60m /trade-robinhood` to start the hourly trading loop, or run `/trade-robinhood` once to test a single cycle."
