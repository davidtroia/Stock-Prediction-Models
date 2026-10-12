# Trading Rules (Robinhood agentic account)

Re-read this file at the start of every scheduled check. Take the date and time from the firing timestamp, never assume them. The owner trades in US Central time (CT). The market is 8:30-3:00 CT (9:30-4:00 ET). Confirm the market is open today before doing anything (no weekends, no NYSE holidays).

## Mandate
- Full autonomy to trade the agentic account without asking permission each time. Do the work, check it twice before every buy or sell.
- Style: trend-day breakouts plus fades of small failed gaps. Calls on a confirmed breakout up, puts on a confirmed breakdown or a failed gap-up. Watch both sides.
- Evidence note: most published retail results show long options lose on average (spreads, theta, overpaying). The edge here is selectivity. Skipping a day is a good outcome.

## Universe (only these)
AAPL, TSLA, DKNG, QQQ, SPY, XSP. Anything else needs the owner to add it.
- SPY/QQQ: intraday scalps and holds. Preferred for scalps (tightest spreads).
- XSP: 1-3 day holds only, spread must be $0.10 or less (spreads are wider than SPY, tax treatment is better).
- AAPL/TSLA/DKNG: only with opening-range volume at least 2x normal or a clear catalyst. DKNG spreads are often thin, so check carefully.

## Hard no's
- Never touch VIAV.
- Single-leg only. No spreads. No market orders on options (limit only).
- No entries before 8:50 CT (9:50 ET) unless the owner says so.
- No new entries after 11:00 CT (midday chop and theta).
- Do not chase a move that already happened.
- Never buy options expiring in under 4 days. Never hold into the last 2 DTE.
- No entries on a symbol the day before or day of its earnings, or within 1 hour before FOMC, CPI or NFP releases.
- No contracts priced under $0.30 and no deltas under 0.35.

## Settlement
Robinhood reports the agentic account as "limited margin" (not cash) with a large unsettled_funds balance, which contradicts the older note that it was a cash account. Treat the settlement rules below as a precaution until the owner confirms how the account settles. Option sale proceeds settle the next business day on a true cash account.
- Before every entry, confirm the trade is paid with settled cash (check unsettled_funds from get_accounts). Do not trust "buying power" alone.
- Do not sell a position that was bought with unsettled proceeds until those proceeds settle (good-faith violation). Same-day scalps are only allowed with settled cash that was not just freed by a same-day sale.
- Never use Instant Deposit funds for options.
- Keep a count of good-faith violations. At 1, trade only with settled cash and pause scalping.
- Unverified against Robinhood's own help pages. Verify when possible.

## Repo instructions to follow (CLAUDE.md)
- Before every trade, post a written thesis in chat: why, target, exit plan, stop loss.
- Explicit owner approval is required for any single trade over 20% of total portfolio value, liquidating the whole portfolio, or cancelling all open orders. On a small account this means most one-contract trades need approval, so ask first or use a cheaper contract.

## Entry trigger: opening range breakout
1. Mark the high and low of the first 5 minutes (8:30-8:35 CT) as the breakout levels. Note the 15-minute range, the daily trend and the prior-day high/low.
2. At 10:00 ET, classify the day. Take breakout trades only if the opening range is about 0.25-1.0x the 14-day average for that window, volume is elevated (about 1.5x or more, unproven threshold), and it agrees with the daily trend. Skip if the opening range is as large as a typical full day's range.
3. Calls: price breaks above the range high, holds above VWAP. Puts: breaks below the range low, stays below VWAP.
4. Pullback entries are fine: buy a retest of the broken level or VWAP rather than the spike.
5. Gap fades: only SPY/QQQ gaps under 0.5% (same-day fill rate is high). Do not fade gaps over 1%; they continue more often than they fill. Gaps of 0.5-1% are a coin flip: skip.
6. A failed breakout that falls back into the range is a fade setup in the other direction.

## Entry checklist (all must pass)
1. Check account positions, open orders and settled cash first. Do not double up on the owner's positions.
2. The opening range trigger above is met and agrees with the daily trend.
3. Contract selection:
   - Scalps: delta 0.45-0.60, 4-8 DTE. Holds of 1-3 days: delta 0.55-0.70, 6-8+ DTE.
   - Bid/ask spread at most 5% of mid (DKNG and XSP exceptions above). Open interest in the hundreds or more, or solid volume.
   - Neighboring strikes price consistently (no stale or crossed quotes).
4. Risk fits the sizing rules below. If the cheapest acceptable contract breaks them, skip the trade.
5. Limit order at mid, step toward the ask by $0.01-0.02 every 15-30 seconds for at most 2-3 steps, then cancel.
6. If anything is unclear, skip the trade and log the skip.

## Sizing and limits
- Max loss at the stop: target about 3% of account value, never more than 5% (about $230 of premium per contract at a 13% stop on a $600 account). Skip trades that cannot fit.
- At most 2 open positions at once. Maximum 2 trades per day (settled cash only).
- Daily loss limit: 6% of account value. Stop for the day when hit, and after 2 losing trades.
- Weekly loss limit: $150 by default. The owner suspended it for the week of 10/5; ask or confirm if unclear.
- Drawdown brakes: after a 10% drop from the account high, halve risk per trade. After a 20% drop, stop live trading until the owner reviews.
- Do not re-enter the same symbol within 30 minutes of a stop-out. Never trade to make back a loss.

## Exits
- Immediately after every fill: GTC stop-limit sell. Stop trigger = fill x 0.87 (the owner's 13% stop), limit = trigger x about 0.97. This is the hard floor and stays in place.
- Primary exit is on the underlying: close if price loses the structure that justified the trade (back inside the opening range, loses VWAP, lower low on 5M/15M for calls or higher high for puts).
- Scale out: sell half at about +10%, then move the stop on the rest to breakeven and trail it under the prior 5-minute swing or VWAP. With a single contract, sell all at about +10%.
- Time stop: exit a scalp that is not working (not at least about +5%) within 30-45 minutes. Exit a multi-day hold that has not worked by the end of day 2.
- Be flat by 2:45 CT. Hold overnight only if the trade is working, the stop is at breakeven or better, and the settled-cash rules allow it.
- Note: a 13% stop on a near-the-money option is a small move in the underlying and can trigger on noise or spread. Early exits on the underlying are meant to act first. The owner can switch to an underlying-based stop with a wider backstop if desired.

## Owner's own trades
The owner sometimes trades on their own. Any new open position without a stop gets the same 13% GTC stop-limit. Do not close the owner's positions otherwise unless a rule above says so.

## Journal and review
- Log every trade and every skipped setup in TRADE_JOURNAL.csv (repo root, not committed because it holds real trade data). Columns: trade_id, date, time_in, time_out, underlying, contract, dte, delta, setup_name, regime, news_event, thesis, underlying_entry, underlying_stop, premium_mid_entry, fill_entry, spread_pct, contracts, risk_usd, risk_pct_equity, fill_exit, exit_reason, pnl_usd_net, slippage_usd, r_multiple, minutes_held, rules_followed, notes.
- Friday 2:00 CT check includes a weekly review: trades vs broker fills, win rate, average win and loss in R, expectancy, drawdown, slippage, rule violations, skipped setups.
- Change at most one rule at a time, only at the weekly review, with at least 20 trades between changes. Do not judge the strategy on fewer than 30-50 trades.

## Daily schedule (CT)
- 8:20 premarket scan: gaps and size, news and macro calendar, earnings, key levels, prior-day high/low, daily trend, positions and settled cash. Report a short plan.
- 8:50 entry window: apply the opening range trigger and entry checklist.
- 10:00, 12:00, 2:00 management checks: positions, stops, scale-outs, early exits, time stops, flat-by-2:45 reminder. New entries only before 11:00 CT.

## Notes
- The opening-range, sizing and exit ideas come from public papers (mostly on shares, not options), trading guides and forum posts. They are mostly unverified for long options, so log results and revisit.
- Scanner (Robinhood "Reversal Plays - Oversold Gap-Down") filters drifted once; restore price >= $20 and avg volume >= 5M before relying on it. The universe above is fixed, so the scanner is optional.
