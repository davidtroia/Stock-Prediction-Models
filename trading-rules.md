# Robinhood Trading Rules
**Account:** Agentic (••••1596, Cash) | **Last updated:** June 23, 2026

---

## STEP 0 — OVERNIGHT & PRE-MARKET MONITOR
Run before the regular session opens (ideally 7–9 AM CT). Check:

### Index futures
Search for overnight levels of:
- **ES (S&P 500 futures)** — direction and % change from prior settle
- **NQ (NASDAQ 100 futures)** — tech sentiment
- **YM (Dow futures)** — broad market tone
- **RTY (Russell 2000 futures)** — small-cap / risk-on signal

Flag if any index future is down more than **1%** overnight — note the likely cause (macro news, geopolitical event, earnings shock).

### Pre-market equity prices
- Call `get_equity_quotes` for SPY, QQQ, VTI and all held positions
- Use `last_non_reg_trade_price` for the pre-market price
- Calculate pre-market % change vs prior close
- Flag any held position moving more than **±2% pre-market** — investigate news before open

### Overnight macro events to check
- Fed speeches or rate decisions
- Major economic data releases (CPI, NFP, PCE, GDP)
- Geopolitical events (tariffs, sanctions, conflicts)
- Major international market moves (Nikkei, DAX, FTSE, Shanghai)
- Oil / commodities moves that affect sector holdings

### Pre-market tone summary
Classify the open as: **Risk-On** / **Risk-Off** / **Mixed** based on futures + VIX direction, and note which sectors are likely to lead or lag.

---

## STEP 0b — AFTER-HOURS MONITOR
Run after the regular session closes (4 PM ET) and watch through end of extended trading (~8 PM ET).

### After-hours equity prices
- Call `get_equity_quotes` for all held positions — use `last_non_reg_trade_price` for AH price
- Calculate AH % change vs the regular session close
- Flag any held position moving more than **±1.5% after hours** — investigate immediately

### Key AH triggers to watch
- Earnings releases from held companies or major sector peers
- Fed or Treasury announcements
- Geopolitical headlines
- Analyst upgrades/downgrades
- M&A announcements affecting held positions (e.g. deal price revisions, competing bids, deal breaks)
- For merger-arb positions: monitor the **acquirer stock AH** (e.g. KMB for KVUE) — every $1 move in acquirer changes deal value

### After-hours check schedule
- 4:30 PM ET — initial AH snapshot
- 6:00 PM ET — mid-AH check
- 8:00 PM ET — end of extended hours final check
- If a position moves ±1.5% at any check, send a notification immediately

---

## STEP 1 — ACCOUNT STATUS
Call `get_accounts` and `get_portfolio`. Note cash, total equity, and all open positions.

---

## STEP 2 — MARKET OVERVIEW
Call `get_index_quotes` for SPX, NDX, VIX. Call `get_equity_quotes` for SPY, QQQ, VTI.
Note daily change, VIX level, and sector rotation themes. Cross-reference with overnight futures direction from STEP 0.

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

**Tier 1 — Core safe anchors (always scan, relaxed criteria):**
These are the foundation. Screen them every session regardless of market conditions.
Always check price vs 200dMA, unusual options activity, and near-term catalyst before buying.

| Symbol | Type | Why |
|--------|------|-----|
| SPY | ETF | S&P 500 benchmark — always eligible |
| QQQ | ETF | Nasdaq-100 — always eligible |
| VTI | ETF | Total US market — always eligible |
| AAPL | Large-cap | Dividend + growth, world's largest company |
| MSFT | Large-cap | Cloud + AI growth, strong dividend history |
| JPM | Large-cap | Banking bellwether, solid dividend |
| JNJ | Large-cap | Healthcare dividend aristocrat |
| KO | Large-cap | Consumer staples dividend king |
| PG | Large-cap | Consumer staples dividend aristocrat |
| V | Large-cap | Payments growth + dividend |
| XOM | Large-cap | Energy dividend + growth |

For Tier 1 names: the 200dMA rule is a **caution flag**, not an automatic block — if a blue-chip is temporarily below its 200dMA but the thesis is intact and confidence is 8+/10, a small starter position is allowed with a tighter 5% stop.

**Tier 2 — Large-cap or ETF (standard universe):**
- Any large-cap US stock or ETF listed on NYSE or NASDAQ
- All standard buy criteria apply

**Tier 3 — Sub-$20 growth stocks (expanded universe):**
- Share price between **$5.00 and $20.00** (floor raised — avoid illiquid cheap stocks)
- Market cap above **$300M**
- Listed on NYSE or NASDAQ only (no OTC, no pink sheets)
- D/E rule waived for this category
- Positive earnings OR clear revenue growth trajectory
- **Liquidity is critical** — bid-ask spread must be tight (under $0.10 for sub-$10 stocks, under $0.20 for $10–$20 stocks); avoid stocks where the spread is a significant % of price

### Trade priority
1. **Tier 1 core anchors** — SPY, QQQ, VTI, AAPL, MSFT, JPM, JNJ, KO, PG, V, XOM — **always check these first**
2. **Growth + dividend stocks** — steady compounders with income
3. **Growth-only stocks** — allowed with strong thesis and improving momentum
4. **Biotech (swing trade only)** — see biotech rules below; short-term holds only, no overnight thesis changes

### Buy criteria — ALL must be true
- [ ] NYSE or NASDAQ listed
- [ ] Positive earnings (or clear revenue growth trajectory for sub-$20 growth names)
- [ ] Debt-to-equity under **1.5** *(waived for sub-$20 growth stocks)*
- [ ] Revenue growth over last 3 years *(or growth trajectory for sub-$20 names)*
- [ ] Price above **200-day moving average**
- [ ] Relative strength improving vs SPY
- [ ] Average daily volume above **1,000,000 shares**
- [ ] Bid-ask spread is tight relative to price (liquidity check)
- [ ] No earnings report within the next **2 weeks** — do not initiate a position as an earnings play
- [ ] No pending binary event (FDA decision, trial result, single catalyst) that makes this a speculation *(exception: biotech swing trades — see below)*
- [ ] Clear fundamental reason for growth and/or dividend income
- [ ] Not a pending acquisition where the original thesis has already been superseded (merger-arb is a different strategy — flag and re-evaluate)
- [ ] Check **unusual options activity** — high call volume relative to open interest, unusual block trades, or elevated put/call ratio on the stock can be a signal of institutional positioning; flag it as supporting or contradicting the thesis

### Unusual options activity signals
Before any new trade, check option chain for the stock:
- **Bullish signal:** Unusual call volume 2x+ open interest, large blocks on near-term calls, low put/call ratio
- **Bearish signal:** Elevated put volume, deep ITM put buying, sudden spike in implied volatility
- Options activity does not override the fundamental checklist — it is a supporting indicator only
- Do not buy options as the primary trade vehicle (equity positions only per these rules)

### Asset exclusions — Never buy
- OTC / pink sheet stocks
- Stocks under **$5.00** (too cheap, illiquid, spread risk)
- Any stock where the primary thesis is social media momentum (covers meme stocks, Reddit/Twitter hype plays)
- IPOs under **3 months** old
- Stocks up more than **5% today**
- Stocks that dropped significantly with no thesis
- Chinese-listed ADRs with significant geopolitical risk and no profitable operations
- **Biotech as a long-term hold** — biotech is only permitted as a **short swing trade** (see below)

### Biotech swing trade rules (exception only)
Biotech may be traded as a short-term swing trade if ALL of the following are true:
- Stock has existing commercial revenue (not pre-revenue)
- Catalyst is NOT a binary FDA/trial event (no gambling on single decisions)
- Hold period: **1–5 trading days only** — not an overnight thesis hold
- Stop loss: **5%** (tighter than standard 8% — biotech moves fast)
- Position size: no more than **20% of available cash**
- Must have average daily volume above 2,000,000 shares
- Confidence must be **8/10 or higher** to enter

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
