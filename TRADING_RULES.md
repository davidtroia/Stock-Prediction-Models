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
- No entries before 8:50 CT (9:50 ET) unless the owner says so.
- No new entries after 11:00 CT (afternoon theta decay).
- Do not chase a move that already happened.
- Never buy expiring-today options. Use 4+ DTE (weekly or later).

## Entry trigger: opening range breakout
1. Mark the high and low of the first 15 minutes (8:30-8:45 CT). Also note the daily trend and prior-day high/low.
2. Calls: price breaks above the 15-minute range high, holds above VWAP, and breakout volume is at least 1.5x the recent average bar volume.
3. Puts: price breaks below the 15-minute range low, stays below VWAP, same volume test.
4. Skip the day if the opening range is unusually wide (more than about 2x the stock's typical daily ATR) or the break has no volume.
5. Pullback entries are fine: buy a retest of the broken level or VWAP rather than the spike.
6. A failed breakout that falls back into the range is a fade setup in the other direction.

## Entry checklist (all must pass)
1. Check account positions and open orders first. Do not double up on the owner's positions.
2. The opening range trigger above is met and agrees with the daily trend.
3. Option chain sanity:
   - Open interest in the hundreds or more, or solid volume (XSP: looser, volume is usually thin).
   - Bid/ask spread about 10% of mid or less.
   - Neighboring strikes price consistently (no stale or crossed quotes).
   - Near ATM or slightly ITM, delta about 0.40-0.60.
4. Limit order at or near mid.
5. If anything is unclear, skip the trade. No trade is a valid outcome.

## Sizing and daily limits
- Weekly loss limit: $150 by default. The owner suspended it for the week of 10/5; ask or confirm if unclear.
- Per-trade cap: at most 25% of account value (about 3% account risk at a 13% stop).
- Maximum 3 trades per day.
- After 2 losing trades in a day, stop trading for the day. No revenge trades.

## Exits
- Immediately after every fill: GTC stop-limit sell. Stop trigger = fill x 0.87 (13% stop), limit = trigger x about 0.97.
- Scale out: limit sell half the position at about +10%. After it fills, move the stop on the rest to breakeven and let it run.
- With a single contract, sell the whole position at about +10%.
- Early exit on the underlying: close the position if price loses the structure that justified the trade (back inside the opening range, loses VWAP, or makes a lower low on 15M for calls / higher high for puts). The 13% stop stays in place as the hard floor.
- Exit if a trade stalls near breakeven for a long time.
- Default: be flat by 2:45 CT. Hold overnight only if the trade is working and the stop is at breakeven or better.

## Owner's own trades
The owner sometimes trades on their own. Any new open position without a stop gets the same 13% GTC stop-limit.

## Daily schedule (CT)
- 8:20 premarket scan: gaps, news and macro, key levels, prior-day high/low, daily trend, position check. Report a short plan.
- 8:50 entry window: apply the opening range trigger and entry checklist.
- 10:00, 12:00, 2:00 management checks: positions, stops, scale-outs, early-exit rules, and a flat-by-2:45 reminder. New entries only before 11:00 CT.

## Notes
- Scanner (Robinhood "Reversal Plays - Oversold Gap-Down") filters drifted once; restore price >= $20 and avg volume >= 5M before relying on it. The universe above is fixed, so the scanner is optional.
- Individual-stock options on thin underlyings stop out easily at 13%; prefer liquid names.
- The opening-range, sizing and stop ideas come from public trading guides and forum posts. They are unverified, so log results and revisit these rules after a few weeks of trades.
