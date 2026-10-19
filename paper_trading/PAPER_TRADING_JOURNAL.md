# Paper Trading Journal — Phase 1 Validation (Run #66 validation)

**Account Setup Date**: 2026-08-29 (14:26 UTC / 19:56 IST) — pre-restart; nothing before the restart counts
**Phase 1 Forward-Only Restart**: Mon 2026-10-19
**Initial Capital**: ₹25,00,000 (CLI `--capital 2500000`)
**Strategy**: Weekly PCS/IC only. No fixed hold period; exits by rule. Monthly paused.
**Baseline Model**: retrained 2026-10-18, validated by Run #66 (11.98% CAGR, MaxDD 6.2%, Sharpe 0.97 on the 17-year backtest, weekly risk engine OFF); pre-retrain reference Run #60 (12.07%)
**Target**: Validate positive expectancy per lot (backtest ₹3,134), payoff ratio (avg win ÷ avg loss) ≥ ~1.5, no loss worse than the backtest tail (₹-5,326 per lot), DD < 15% over 6 months. Win rate is tracked for information only: for premium selling it is high by construction and says little about risk.

**Note**: Trade #1 (Aug 29 IC) is a SIMULATED back-fill, not a live paper trade, and is excluded from Phase 1 counts. Zero real trades have been taken. Phase 1 counts start on 2026-10-19. See `analysis/ASOF_2026-09-08_DECISION.md` for the earlier as-of run and [RESTART_2026-10-19.md](./RESTART_2026-10-19.md) for the restart procedure.

---

## Account Overview

| Parameter | Value |
|-----------|-------|
| **Initial Capital** | ₹25,00,000 |
| **Allocation: Weekly** | ₹12,50,000 (50% budget) |
| **Allocation: Monthly** | ₹12,50,000 (50%, paused in Phase 1) |
| **Reserve/Cushion** | Not set aside (the CLI budget split is 50/50) |
| **Lot count** | Set by the signal. Weekly lots = max(1, int(`--lots` × 0.5)); with `--lots 30` that is **15** (weekly risk engine OFF in Phase 1, so no risk scaling). Copy the printed count. |
| **Max concurrent trades** | 1 weekly position |
| **Per-trade stop** | 100% of credit collected, or short-strike breach. No ₹ cap per trade. |
| **Account pause rule** | DD ≥ 15% of peak equity (₹3,75,000 from ₹25L) |

---

## Phase 1: Validation Period (Weeks 1–4 from restart)

**Objective**: Confirm that live market conditions match backtest assumptions

### Key Metrics to Validate

| Metric | Backtest | Live Target | Status |
|--------|----------|-------------|--------|
| **Avg P&L per lot (expectancy)** | ₹3,134 | > 0, ideally >= ₹2,500 | [ ] |
| **Payoff ratio (avg win ÷ avg loss)** | 1.92 | >= 1.5 | [ ] |
| **Stop-out rate** | 34% (35/102) | Tracked; compare, do not target | [ ] |
| **Avg profit/trade (₹, 15 lots)** | ₹29,528 | >= ₹25,000 | [ ] |
| **Weekly win rate (informational only)** | 78% | Tracked, not a pass/fail gate | [ ] |
| **Fill quality** | Backtest mid-session fill + 0.75× slippage | Real broker bid/ask logged for every fill | [ ] |
| **Trade frequency** | 6/year | 1–2/month pace | [ ] |
| **Worst weekly loss** | ₹-53,255 (₹-5,326 per lot) | Tracked; stop rule governs (no ₹ cap) | [ ] |
| **Signal-to-fill latency** | N/A | Logged | [ ] |

---

## Trading Rules (STRICT)

1. **Weekly Only**: No monthly trades during Phase 1. Ignore TRACK 1 of the signal output.
2. **Entry Window**: Any time 11:00–13:00 IST while the signal says ENTER.
3. **Position Size**: The lot count the signal prints (`python main.py --mode signal-combined --capital 2500000 --lots 30`). Copy it into TRADES.csv exactly.
4. **Stop Loss**: 100% of credit collected, or a breach of the short strike, as the signal prints. Exit immediately. This is the only stop rule.
5. **Profit Target**: PCS 75% of max profit. IC has no profit target.
6. **Holding Period**: Governed by exit rules, not a day cap. PCS: min hold 2 trading days (as printed). IC: max hold 4 trading days (as printed by the code; pending owner confirmation). Expiry: close by 15:15 IST on expiry day.
7. **DTE Filter**: Weekly expiry 3–8 DTE only (a Mon 10-19 entry selects Tue 2026-10-27, 8 DTE; confirm the printed expiry).
8. **Account Pause**: DD ≥ 15% of peak equity. Close open positions, pause entries, review.
9. **Real Prices Only**: Signal premiums are Black-Scholes estimates (`[BS est]`). Take real bid/ask from the broker for every fill.
10. **Log Every Day**: DAILY_LOG.csv gets a row every trading day, including skips (with a reason code from RESTART section c).

---

## Rule Changes vs Original Template (restart)

**Owner decisions (the only ones the owner has made):**
- (a) Take a real paper entry Mon 2026-10-19 if the signal passes its gates; otherwise log a real SKIP.
- (b) Stop loss = 100% of credit collected (matches the backtest). Drops the 2× and ₹50k stops.
- (c) Size with `--lots 30`; the sizer decides the lot count.
- (d) Weekly risk engine OFF (rule-based weekly gate).
- (e) Code gaps fixed: holiday calendar, IST clock, `.env.local` loading (done in code).

Every other row below is labelled **Fact (code behaviour)**, **Fact (doc fix)**, or **Proposed (audit finding), pending owner confirmation**.

| Old rule | New rule | Reason | Status |
|----------|----------|--------|--------|
| Stop: "hard 2× credit or ₹50k loss, whichever first" | Stop: 100% of credit collected, or short-strike breach | Matches the backtest (`stop_loss_pct = 100`) and the signal's printed stop | **Owner decision (b)** |
| Max single trade loss ₹50k (cap) | No ₹ cap per trade | Dropped with the 2× stop. Backtest worst weekly loss is ₹−53,255, above ₹50k | **Owner decision (b)** |
| Single-loss > ₹75k: exit and halve size; ₹75k pause criterion | Removed. One account pause rule: DD ≥ 15% of peak (₹3,75,000) | One stop rule and one pause rule | Proposed (audit finding), pending owner confirmation |
| "Maintain 65-lot base" | Lot count as printed by the signal (`--lots 30`; weekly = max(1, int(30 × 0.5)) = 15 with the risk engine OFF) | Sizing is engine-driven; the 65 figure was a stale base | **Owner decision (c)** |
| "Max 3 trading days" hold | No day cap. Exits by rule: PCS 75% target; IC none; expiry; IC max hold 4 trading days as printed by the code | A Tue→Tue weekly trade is about 5 trading days, so a 3-day cap cuts it short | Proposed (audit finding), pending owner confirmation (IC 4-day max hold: open question 1) |
| "Monthly track" in Phase 1 | Weekly only; monthly output ignored | The original template already said weekly only; the signal still prints the monthly track | Fact (original template; not a change). Monthly model under investigation |
| "10:00–10:55 pre-market" and "ENTER AT 11:30" | Pre-flight 10:00–10:55; entry any time 11:00–13:00 IST when the signal says ENTER | The signal's own entry-window gate | Fact (code behaviour) |
| REST API steps (`curl localhost:8000/...`) | CLI command plus manual CSV flow | API cannot start at HEAD | Fact (code behaviour) |
| Example expiry 2026-09-04 (a Friday); "Friday close" | Tuesday weekly expiries (e.g. Tue 2026-10-27 for a Mon 10-19 entry). Tue 10-20 holiday moves to Mon 10-19 | Expiry calendar in code (`data/expiry_calendar.py`, `data/nse_holidays.json`) | Fact (code behaviour) |
| Capital ₹15L (docs) | ₹25L, weekly budget ₹12.5L | Documentation inconsistency fix; matches the CLI `--capital 2500000` | Fact (doc fix) |
| Checkpoints 2026-09-29 / 2026-10-29 | 2026-11-18 (30 days) / 2026-12-18 (60 days) | Forward-only restart on 2026-10-19 | Proposed (audit finding), pending owner confirmation |
| Daily ₹1L loss pause; "3 consecutive losses" pause; "win rate < 60% over 10 trades" pause | Demoted to review triggers (not automatic pauses) | Only one pause rule is kept | Proposed (audit finding), pending owner confirmation |

### Open questions for the owner

1. IC max-hold 4 trading days (keep as code prints?)
2. ₹1L daily-loss / 3-consecutive-loss / win-rate<60% triggers: hard pause or review-only? (Suggestion: review-only, and replace the win-rate trigger with rolling expectancy per lot or drawdown, since win rate is not a risk measure for premium selling.)
3. Checkpoint dates (2026-11-18 / 2026-12-18)
4. Slippage formula
5. Strike_Entry/Capital_Deployed formats

---

## Monthly Checkpoint (Review Every 30 Days from Restart)

### Checkpoint 1: 2026-11-18 (30 days from 2026-10-19)
- Trades taken: [ ]
- Win rate: [ ]%
- Total P&L: ₹[ ]
- Largest win: ₹[ ]
- Largest loss: ₹[ ]
- Avg hold days: [ ]
- Status: [ ] On track [ ] Needs review [ ] Pause
- Expected: 1–2 trades (low frequency in the restart window; NSE holidays in late Oct and Nov)

**Notes**: Restart pre-flight on Mon 2026-10-19 is in [RESTART_2026-10-19.md](./RESTART_2026-10-19.md). The first signal run is Mon 10-19; Tue 10-20 is an NSE holiday (Dussehra; verified against NSE's holiday master API on 2026-10-18). Earlier dates in this journal (Sep 8 signal, 2026-09-29 checkpoint) are superseded.

---

### Checkpoint 2: 2026-12-18 (60 days, final go/no-go)
- Trades taken: [ ]
- Win rate: [ ]%
- Total P&L: ₹[ ]
- Largest win: ₹[ ]
- Largest loss: ₹[ ]
- Avg hold days: [ ]
- Status: [ ] On track [ ] Needs review [ ] Pause
- Target: ≥2–3 trades, ≥75% win rate, max DD < 15%

**Notes**: Go/no-go decision to Phase 2 (add monthly track) or extend validation

---

### Checkpoint 3: [Date TBD]
- Trades taken: [ ]
- Win rate: [ ]%
- Total P&L: ₹[ ]
- Largest win: ₹[ ]
- Largest loss: ₹[ ]
- Avg hold days: [ ]
- Status: [ ] On track [ ] Needs review [ ] Pause

**Notes**:

---

### Checkpoint 4: [Date TBD]
- Trades taken: [ ]
- Win rate: [ ]%
- Total P&L: ₹[ ]
- Largest win: ₹[ ]
- Largest loss: ₹[ ]
- Avg hold days: [ ]
- Status: [ ] On track [ ] Needs review [ ] Pause

**Notes**:

---

### Checkpoint 5: [Date TBD]
- Trades taken: [ ]
- Win rate: [ ]%
- Total P&L: ₹[ ]
- Largest win: ₹[ ]
- Largest loss: ₹[ ]
- Avg hold days: [ ]
- Status: [ ] On track [ ] Needs review [ ] Pause

**Notes**:

---

### Checkpoint 6: [Date TBD]
- Trades taken: [ ]
- Win rate: [ ]%
- Total P&L: ₹[ ]
- Largest win: ₹[ ]
- Largest loss: ₹[ ]
- Avg hold days: [ ]
- Status: [ ] On track [ ] Needs review [ ] Pause

**Notes**:

---

## Deviation Log (Skips and Trades That Deviate from Backtest Signals)

Use this for every skip (with its reason code) and for every trade taken outside the signal's rules.

| Date | Signal | Action Taken | Reason | P&L | Learning |
|------|--------|--------------|--------|-----|----------|
| | | | | | |

---

## Technical Notes

- **Broker / data**: Fyers credentials in `.env` or `.env.local` (names only). Real bid/ask from the broker for every fill.
- **API**: NOT USABLE at HEAD. Use the CLI and manual CSVs. Known issues: RESTART section (f).
- **Order Type**: IOC (Immediate or Cancel) for tight mid-session fills
- **Slippage Logging**: Every fill logs the broker bid/ask at entry and the exit fill. Proposed slippage formula (pending owner confirmation): (actual credit − CLI `[BS est]` credit) ÷ CLI credit × 10,000 bp.
- **Fill Time**: Log the time from the signal run to the fill
- **Hedge Coverage**: Log if any directional hedge is taken

---

## Phase Transition Decision

**Criteria to Move to Phase 2 (Add Monthly)**:
- ✅ 10+ weekly trades with >= 75% win rate
- ✅ Average profit >= ₹25k per trade
- ✅ Max DD < 12% of peak
- ✅ Broker and data flow stable (zero outages that affected a trade)
- ✅ Phase 5 monthly improvements deployed (ML threshold 0.55–0.60)

**Criteria to Pause**:
- ❌ Account DD ≥ 15% of peak (₹3,75,000)
- ❌ Repeated broker or data failures
- ❌ Win rate < 60% over 10 trades (review trigger; owner to confirm as a pause)

---

## Post-Phase-1 Review (After 6 months)

**Actual Results**:
- Trades taken: [ ]
- Win rate: [ ]%
- Total P&L: ₹[ ]
- CAGR realized: [ ]%
- Max DD: [ ]%
- Slippage vs backtest: [ ] bp average

**Comparison vs Backtest**:
- Expected (backtest): 6 trades, 78% win, ₹177k P&L per year
- Actual: [ ] trades, [ ]% win, ₹[ ] P&L
- Variance: [ ]% (acceptable < 30%)

**Go/No-Go Decision**:
- [ ] GO — Phase 2 (add monthly)
- [ ] HOLD — Collect more data (next 3 months)
- [ ] NO-GO — Investigate backtest vs live gap (pause trading)

---

## Appendix: Backtest Baseline (Run #60 Reference)

**Weekly Performance (Baseline)**:
- Trades: 102 over 17 years
- Win rate: 78.4%
- Avg P&L/trade: ₹29,528
- Median P&L: ₹10,168
- P90 profit: ₹141,841
- Max loss: ₹-53,255
- Holding: 3 days average (backtest statistic, not a rule)

**Expected Monthly Pace**:
- ~6 trades per year
- ~₹177,168 annual P&L (on ₹12L allocated capital)
- CAGR: ~14.8% on allocated capital

**Monthly Track (Baseline, paused)**:
- Win rate: 52%
- Avg P&L/trade: ₹251
- Total P&L: ₹31,388 (negligible)
- Status: Paused — needs Phase 5 ML improvements before live trading

---
