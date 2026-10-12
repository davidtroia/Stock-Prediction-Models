# Trading Rules (Robinhood agentic account)

Re-read this file at the start of every scheduled check. Take the date and time from the firing timestamp, never assume them. The owner trades in US Central time (CT). The market is 8:30-3:00 CT (9:30-4:00 ET). Confirm the market is open today before doing anything (no weekends, no NYSE holidays).

## Mandate
- Full autonomy to trade the agentic account without asking permission each time. Do the work, check it twice before every buy or sell.
- Style: reversal plays plus trend-day scalps. Calls when it is a strong, confirmed trend up. Puts when a gap or run fades. Watch both sides.

## Universe (only these)
AAPL, TSLA, DKNG, QQQ, SPY, XSP. XSP is index-based and cash-settled. Anything else needs the owner to add it.

## Hard no's
- Never touch VIAV.
- Single-leg only. No spreads. No market orders on options (limit only).
- No entries before 9:50 ET / 8:50 CT unless the owner says so.
- Do not chase a move that already happened.
- Never buy expiring-today options. Use 4+ DTE (weekly or later).

## Entry checklist (all must pass)
1. Check account positions and open orders first. Do not double up on the owner's positions.
2. Trend vs fade read using 5/15 minute bars, VWAP, higher highs/lows. Calls only on a clear uptrend that pulls back to VWAP or a rising 15M EMA. Puts only on a confirmed fade.
3. Option chain sanity:
   - Open interest in the hundreds or more, or solid volume (XSP: looser, volume is usually thin).
   - Bid/ask spread about 10% of mid or less.
   - Neighboring strikes price consistently (no stale or crossed quotes).
   - Near ATM or slightly ITM, delta about 0.40-0.60.
4. Limit order at or near mid.
5. If anything is unclear, skip the trade. No trade is a valid outcome.

## Sizing
- Weekly loss limit: $150 by default. The owner suspended it for the week of 10/5; ask or confirm if unclear.
- Per-trade cap: at most 40% of account value (default, owner can change).

## Exits
- Immediately after every fill: GTC stop-limit sell. Stop trigger = fill x 0.87 (13% stop), limit = trigger x about 0.97.
- Scalp target: limit sell at about +10% placed after the fill, unless the trend is strong enough to hold.
- Exit early if the trend breaks (lower low on 15M, loses VWAP) or a trade stalls near breakeven for long.
- Default: be flat by 2:45 CT. Hold overnight only if the trade is working and the stop is at breakeven or better.

## Owner's own trades
The owner sometimes trades on their own. Any new open position without a stop gets the same 13% GTC stop-limit.

## Daily schedule (CT)
- 8:20 premarket scan: gaps, news and macro, key levels, trend vs fade lean, position check. Report a short plan.
- 8:50 entry window: apply the entry checklist.
- 10:00, 12:00, 2:00 management checks: positions, stops, scalp targets, new setups, and a flat-by-2:45 reminder.

## Notes
- Scanner (Robinhood "Reversal Plays - Oversold Gap-Down") filters drifted once; restore price >= $20 and avg volume >= 5M before relying on it. The universe above is fixed, so the scanner is optional.
- Individual-stock options on thin underlyings stop out easily at 13%; prefer liquid names.
