# Paper Trading Journal — Phase 1 Validation (Run #62)

**Account Setup Date**: 2026-08-29 (14:26 UTC / 19:56 IST)  
**Initial Capital**: ₹25,00,000  
**Strategy**: Weekly IC/PCS (3-day holds) + Monthly (paused)  
**Baseline Model**: Run #62 (11.98% CAGR on 17-year backtest)  
**Target**: Validate ≥75% weekly win rate, capture ₹25k+ avg profit, 15% max DD over 6 months

---

## Account Overview

| Parameter | Value |
|-----------|-------|
| **Initial Capital** | ₹25,00,000 |
| **Allocation: Weekly** | ₹12,50,000 (50%) |
| **Allocation: Monthly** | ₹12,50,000 (50% reserved, paused) |
| **Reserve/Cushion** | ₹0 (100% deployed across both) |
| **Margin per 65-lot trade** | ~₹4–5,00,000 (approx) |
| **Max concurrent trades** | 1–2 positions |
| **Max single trade loss** | ₹50,000 (cap) |
| **Account DD stop-loss** | 15% (₹3,75,000) |

---

## Phase 1: Validation Period (Weeks 1–4)

**Objective**: Confirm that live market conditions match backtest assumptions

### Key Metrics to Validate

| Metric | Backtest | Live Target | Status |
|--------|----------|-------------|--------|
| **Weekly win rate** | 78% | >= 75% | [ ] |
| **Avg profit/trade** | ₹29,528 | >= ₹25,000 | [ ] |
| **Mid-session fill quality** | 11 AM IST + 0.75× slippage | Actual fills logged | [ ] |
| **Trade frequency** | 6/year | 1–2/month pace | [ ] |
| **Max single loss** | ₹-53,255 | Within cap ₹-50k | [ ] |
| **Execution latency** | N/A | < 2 sec Fyers API | [ ] |

---

## Trading Rules (STRICT)

1. **Weekly Only**: No monthly trades during Phase 1
2. **Entry Window**: 11:00–13:00 IST mid-session
3. **Position Size**: Maintain 65-lot base (adjust for capital as needed)
4. **Stop Loss**: Hard 2× credit cap or ₹50k loss (whichever comes first)
5. **Profit Target**: 50% of max profit
6. **Holding Period**: Max 3 trading days
7. **DTE Filter**: Weekly expires in 3–8 DTE window only
8. **VIX Gate**: Skip entry if VIX > 25 AND monthly trade open (N/A for Phase 1)

---

## Monthly Checkpoint (Review Every 30 Days)

### Checkpoint 1: 2026-09-29 (30 days from Aug 29)
- Trades taken: [ ]
- Win rate: [ ]%
- Total P&L: ₹[ ]
- Largest win: ₹[ ]
- Largest loss: ₹[ ]
- Avg hold days: [ ]
- Status: [ ] On track [ ] Needs review [ ] Pause
- Expected: 1–2 trades (low frequency in Sep, holiday season)

**Notes**: First signal expected Mon Sep 8, 11-13 IST (IC setup ~23500/24300, expiry Sep 11)

---

### Checkpoint 2: 2026-10-29 (60 days, final go/no-go)
- Trades taken: [ ]
- Win rate: [ ]%
- Total P&L: ₹[ ]
- Largest win: ₹[ ]
- Largest loss: ₹[ ]
- Avg hold days: [ ]
- Status: [ ] On track [ ] Needs review [ ] Pause
- Target: ≥2–3 trades, ≥75% win rate, max DD <15%

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

## Deviation Log (Trades that deviate from backtest signals)

Use this to track trades that were taken outside the backtest logic or missed backtest opportunities.

| Date | Signal | Action Taken | Reason | P&L | Learning |
|------|--------|--------------|--------|-----|----------|
| | | | | | |

---

## Technical Notes

- **Fyers API Version**: [TBD]
- **Order Type**: IOC (Immediate or Cancel) for tight mid-session fills
- **Slippage Logging**: Every trade logs actual bid-ask at entry + exit
- **Fill Time**: Track latency from signal to fill (target < 2 sec)
- **Hedge Coverage**: Log if any directional hedge taken (e.g., buy 1 ATM call to hedge short put)

---

## Phase Transition Decision

**Criteria to Move to Phase 2 (Add Monthly)**:
- ✅ 10+ weekly trades with >= 75% win rate
- ✅ Average profit >= ₹25k per trade
- ✅ Max DD < 12% (vs ₹2.25L account cap)
- ✅ Fyers API stable (zero API errors)
- ✅ Phase 5 monthly improvements deployed (ML threshold 0.55–0.60)

**Criteria to Pause**:
- ❌ Win rate < 60% over 5 consecutive trades
- ❌ Account DD > 15%
- ❌ Max single loss > ₹75k
- ❌ Fyers API repeated failures

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
- Expected (backtest): 6 trades, 78% win, ₹177k P&L
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
- Holding: 3 days average

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

