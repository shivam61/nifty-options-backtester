# Paper Trading Monthly Analysis Template

## Month: [MMM YYYY]

---

## Summary Metrics

| Metric | Value | Target | Status |
|--------|-------|--------|--------|
| **Trades Taken** | [ ] | 0–2 | [ ] |
| **Win Rate** | [ ]% | >= 75% | [ ] |
| **Total P&L** | ₹[ ] | ₹20–50k | [ ] |
| **Largest Win** | ₹[ ] | >= ₹25k | [ ] |
| **Largest Loss** | ₹[ ] | <= ₹-50k | [ ] |
| **Avg Holding Days** | [ ] days | 3 days | [ ] |
| **Avg Profit/Trade** | ₹[ ] | >= ₹25k | [ ] |
| **Account P&L Return %** | [ ]% | 1–3% | [ ] |
| **Account DD** | [ ]% | < 5% | [ ] |

---

## Trade-by-Trade Review

### Trade 1: [Entry Date]

**Entry Details**:
- Signal Date: [ ]
- Entry Time: [ ] IST
- Instrument: Nifty [ ] PE (Strike [ ])
- Bid-Ask at Entry: [ ] - [ ]
- Entry Price: ₹[ ]
- Lots: [ ] × 65
- Capital Deployed: ₹[ ]
- VIX at Entry: [ ]
- ML Signal Score: [ ]

**Exit Details**:
- Exit Date: [ ]
- Exit Time: [ ] IST
- Exit Price: ₹[ ]
- Exit Reason: [ ] (profit_target / stop_loss / DTE_expired / manual)
- Days Held: [ ]
- Gross P&L: ₹[ ]
- Brokerage: ₹[ ]
- Slippage vs Backtest: [ ] bp

**Analysis**:
- Backtest expected P&L: ₹[ ]
- Actual P&L: ₹[ ]
- Deviation: [ ]% (acceptable < 30%)
- Key learnings: [ ]

---

### Trade 2: [Entry Date]

**Entry Details**:
- Signal Date: [ ]
- Entry Time: [ ] IST
- Instrument: Nifty [ ] PE/CE (Strike [ ])
- Bid-Ask at Entry: [ ] - [ ]
- Entry Price: ₹[ ]
- Lots: [ ] × 65
- Capital Deployed: ₹[ ]
- VIX at Entry: [ ]
- ML Signal Score: [ ]

**Exit Details**:
- Exit Date: [ ]
- Exit Time: [ ] IST
- Exit Price: ₹[ ]
- Exit Reason: [ ] (profit_target / stop_loss / DTE_expired / manual)
- Days Held: [ ]
- Gross P&L: ₹[ ]
- Brokerage: ₹[ ]
- Slippage vs Backtest: [ ] bp

**Analysis**:
- Backtest expected P&L: ₹[ ]
- Actual P&L: ₹[ ]
- Deviation: [ ]% (acceptable < 30%)
- Key learnings: [ ]

---

## Missed Signals & Deviations

| Date | Signal | Reason Not Taken | Opportunity Cost | Note |
|------|--------|------------------|------------------|------|
| | | | | |

---

## Market Conditions & VIX Regime

| Week | VIX Range | Regime | Volatility Events | Trade Frequency | Notes |
|------|-----------|--------|-------------------|-----------------|-------|
| Week 1 | [ ]–[ ] | [ ] | [ ] | [ ] | |
| Week 2 | [ ]–[ ] | [ ] | [ ] | [ ] | |
| Week 3 | [ ]–[ ] | [ ] | [ ] | [ ] | |
| Week 4 | [ ]–[ ] | [ ] | [ ] | [ ] | |

---

## Backtest vs Live Comparison

| Metric | Backtest Expected | Actual Live | Variance | Analysis |
|--------|-------------------|-------------|----------|----------|
| Win Rate | 78% | [ ]% | [ ]% | [ ] |
| Avg P&L/Trade | ₹29,528 | ₹[ ] | [ ]% | [ ] |
| Max Loss | ₹-53k | ₹[ ] | [ ]% | [ ] |
| Holding Days | 3 days | [ ] days | [ ]% | [ ] |
| Slippage | 0.75× | [ ]× | [ ]% | [ ] |

---

## Fyers API Performance

| Metric | Target | Actual | Status |
|--------|--------|--------|--------|
| **Order Entry Latency** | < 2 sec | [ ] sec | [ ] |
| **Fill Rate Success %** | 99%+ | [ ]% | [ ] |
| **API Errors** | 0 | [ ] | [ ] |
| **Fill vs Mid-session** | 0.75× slippage | [ ] | [ ] |

---

## Risk Management Checks

- [ ] Max single trade loss: ₹[ ] (target ₹-50k) — **Status: [ ] OK [ ] BREACH**
- [ ] Account DD: [ ]% (target < 15%) — **Status: [ ] OK [ ] BREACH**
- [ ] Concurrent open trades: [ ] (target <= 2) — **Status: [ ] OK [ ] BREACH**
- [ ] Win streak: [ ] wins / [ ] losses in sequence — **Status: [ ] Healthy**
- [ ] Capital deployment: ₹[ ] (target 80% of weekly alloc) — **Status: [ ] OK**

---

## Key Observations

1. **Market Behavior**:
   - [ ]

2. **Model Performance**:
   - [ ]

3. **Execution Quality**:
   - [ ]

4. **Risk Events**:
   - [ ]

---

## Decisions & Next Steps

**Decision**: 
- [ ] Continue Phase 1 (collect more data)
- [ ] Pause (investigate backtest vs live gap)
- [ ] Escalate to Phase 2 (add monthly)

**Recommended Actions**:
1. [ ]
2. [ ]
3. [ ]

**Outstanding Questions**:
1. [ ]

---

## Sign-Off

**Reviewed Date**: [ ]  
**Reviewed By**: [ ]  
**Status**: [ ] Approved [ ] Needs Discussion

---

