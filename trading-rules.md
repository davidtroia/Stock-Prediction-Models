# Robinhood Trading Rules
**Account:** Agentic (••••1596, Cash) | **Last updated:** June 23, 2026

---

## STEP 1 — ACCOUNT STATUS
Call `get_accounts` and `get_portfolio`. Note cash, total equity, and all open positions.

---

## STEP 2 — MARKET OVERVIEW
Call `get_index_quotes` for SPX, NDX, VIX. Call `get_equity_quotes` for SPY, QQQ, VTI.
Note daily change, VIX level, and sector rotation themes.

---

## STEP 3 — RISK CONTROLS
- Account down **3% today** → stop all trading for the session
- Account down **6% this week** → stop all trading for 48 hours
- Total drawdown from peak exceeds **15%** → liquidate ALL positions, log **HUMAN REVIEW REQUIRED**

---

## STEP 4 — REVIEW OPEN POSITIONS
For each held position run the following checks:

### Technical checks
- Call `get_equity_quotes` and `get_equity_historicals` for price vs 200dMA
- **Exit if down 8% from entry** — sell immediately
- **Exit if trailing 10% stop triggered** — sell immediately
- **Sell half if up 20%** from entry
- **Exit if price falls below 200-day MA**

### News & sentiment checks
- Search recent news (last 7 days) for each held symbol
- Flag any: product recalls, revenue guidance cuts, executive changes, lawsuits, macro headwinds
- Check **short interest** — flag if significantly elevated or rising fast
- Check **hedge fund / institutional positioning** (13F changes) — note any major exits or new large buyers

### SEC filing checks
- Review latest **8-K** for material events (M&A, litigation, restatements, guidance)
- Review latest **10-Q** for revenue trend, margin direction, debt changes
- Flag any **pending merger or acquisition** — if deal changes the original thesis, re-evaluate the position
- Flag upcoming **earnings date** — note it in the daily report

### Thesis check
- If the original thesis no longer holds, close the position and explain why in the daily report

---

## STEP 5 — NEW TRADE SCREENING

### Eligible assets
**Large-cap or ETF (primary universe):**
- Large-cap US stock or ETF listed on NYSE or NASDAQ
- SPY, QQQ, VTI always eligible

**Sub-$20 growth stocks (expanded universe):**
- Share price between **$2.00 and $20.00**
- Market cap above **$300M**
- Listed on NYSE or NASDAQ only (no OTC, no pink sheets)
- D/E rule waived for this category
- Positive earnings OR clear revenue growth trajectory

### Buy criteria — ALL must be true
- [ ] NYSE or NASDAQ listed
- [ ] Positive earnings (or clear revenue growth trajectory for sub-$20 growth names)
- [ ] Debt-to-equity under **1.5** *(waived for sub-$20 growth stocks)*
- [ ] Revenue growth over last 3 years *(or growth trajectory for sub-$20 names)*
- [ ] Price above **200-day moving average**
- [ ] Relative strength improving vs SPY
- [ ] Average daily volume above **1,000,000 shares**
- [ ] No earnings report within the next **2 weeks** — do not initiate a position as an earnings play
- [ ] No pending binary event (FDA decision, trial result, single catalyst) that makes this a speculation
- [ ] Clear fundamental reason for growth and/or dividend income
- [ ] Not a pending acquisition where the original thesis has already been superseded (merger-arb is a different strategy — flag and re-evaluate)

### Asset exclusions — Never buy
- OTC / pink sheet stocks
- Stocks under $2.00 (true penny stocks)
- Biotech awaiting a single binary catalyst (FDA decision, Phase 3 readout) — biotech with existing revenue and a diversified pipeline is allowed with a thesis
- Any stock where the primary thesis is social media momentum (covers meme stocks, Reddit/Twitter hype plays)
- IPOs under **3 months** old
- Stocks up more than **5% today**
- Stocks that dropped significantly with no thesis
- Chinese-listed ADRs with significant geopolitical risk and no profitable operations

---

## STEP 6 — BEFORE EVERY TRADE
1. **3-sentence investment thesis** focused on growth and/or dividend income
2. **Identify the key risks** (debt, competition, regulation, macro)
3. **Explain why this beats simply holding SPY**
4. **Check news, short interest, and latest 8-K/10-Q** before entry
5. **Check earnings calendar** — do not buy within 2 weeks of a known earnings date
6. **Rate confidence 1–10** — if below 7, do not trade
7. **Use limit orders only** — never market orders
8. **Never use market orders in the first or last 30 minutes** of the regular trading session

---

## STEP 7 — DAILY REPORT
- List all trades made (symbol, side, quantity, price, thesis, confidence)
- Current P&L on all open positions vs cost basis
- Compare account performance vs SPY for the day
- Note any rules that blocked a trade and why
- Note any news, 8-K, or SEC filing flags on held positions
- Note upcoming earnings dates for held positions
- Note short interest and hedge fund positioning changes for held positions

---

## Active Positions Log

| Date | Symbol | Shares | Entry | Stop Loss | Take Half | 200dMA | Notes |
|------|--------|--------|-------|-----------|-----------|--------|-------|
| 2026-06-23 | KVUE | 5 | $18.40 | $16.93 | $22.08 | $17.26 | KMB acquisition pending H2 2026. Deal value: $3.50 cash + 0.14625 KMB shares. Monitor KMB price daily. CFO sold 3,700 shares Jun 12. Re-evaluate thesis if deal terms change. |
