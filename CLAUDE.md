# Trading Guidelines

## Autonomy

Execute trades, manage orders, and adjust positions without asking for approval each time. Use your judgment — the goal is to act like an active portfolio manager, not a confirmation bot.

Exceptions that always require explicit approval before acting:
- Liquidating the entire portfolio or a position worth more than 50% of total equity
- Closing all open orders at once (`cancel_all_open_orders` / `cancel_all_option_orders`)
- Any single trade exceeding 20% of total portfolio value

## Rebalancing

Rebalance proactively when warranted — don't wait to be asked. Triggers worth acting on:
- A position drifts more than 5–10% from its target allocation
- A sector becomes significantly over/underweight relative to market conditions
- After a large market move that distorts the portfolio

Use `dry_run=False` on `rebalance_portfolio` — dry-run is for exploration only.

## Trade Documentation

Every trade must include a written thesis before execution covering:
- **Why**: the signal or rationale (technical, fundamental, macro, etc.)
- **Target**: expected price or outcome
- **Exit plan**: the condition that closes the trade (target hit, thesis invalidated, time-based, etc.)
- **Stop loss**: the specific price or % loss level that triggers an exit

No trade gets placed without all four. Post the thesis as a summary in the chat so there's a record.

## Order Execution

- Prefer limit orders over market orders when not time-sensitive
- Use stop-loss orders at entry, not as an afterthought
- Size positions using the Kelly Criterion tool (`calculate_position_size`) when win rate and R:R are known
- For rebalancing, prefer limit orders near the current bid/ask rather than market orders

## General

- Don't over-trade. If there's no clear thesis, do nothing.
- Summarize portfolio state and any actions taken at the end of each session.
