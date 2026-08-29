# Paper Trading Risk Dashboard

**Last Updated**: [Date & Time]

---

## Account Status (Real-Time)

| Parameter | Current | Target | Status |
|-----------|---------|--------|--------|
| **Account Equity** | ₹[ ] | ₹15,00,000 | [ ] |
| **Cumulative P&L** | ₹[ ] | — | [ ] |
| **Daily P&L** | ₹[ ] | — | [ ] |
| **Account DD %** | [ ]% | < 15% | [ ] |
| **Worst DD $** | ₹[ ] | < ₹2,25,000 | [ ] |
| **Win Rate YTD** | [ ]% | >= 75% | [ ] |
| **Trades YTD** | [ ] | 0–20 | [ ] |

---

## Position Exposure

| Position | Entry Date | Entry Price | Current Price | Qty (Lots) | Unrealized P&L | Days Held | Target Exit |
|----------|-----------|------------|--------------|-----------|----------------|-----------|-------------|
| | | ₹ | ₹ | | ₹ | | |
| | | ₹ | ₹ | | ₹ | | |

**Total Open P&L**: ₹[ ]  
**Margin Used**: ₹[ ] / ₹12,00,000 available  
**Remaining Capital**: ₹[ ]

---

## Risk Alerts

### 🔴 Critical (Immediate Action)

- [ ] Account DD > 15% → PAUSE ALL ENTRIES
- [ ] Single trade loss > ₹75,000 → MANUAL EXIT
- [ ] Fyers API down > 1 hour → CLOSE ALL POSITIONS
- [ ] Win rate < 50% over last 5 trades → REVIEW & PAUSE

**Action Required**: [ ] YES [ ] NO

### 🟡 Warning (Monitor Closely)

- [ ] Account DD 10–15% → Reduce size on next entry
- [ ] Single open trade P&L swing > ₹50k → Tighten stop
- [ ] 2+ consecutive losses → Wait for next high-confidence signal
- [ ] API latency > 5 sec → Reduce position size

**Status**: [ ] OK [ ] MONITORING

### 🟢 Normal Operating Range

- [ ] Account DD < 10%
- [ ] Win rate >= 70% over last 5 trades
- [ ] API latency < 2 sec
- [ ] Margin utilization 30–50%

**Status**: [ ] GREEN

---

## Daily Checklist (Execute Before 10:30 AM IST)

- [ ] Check Fyers API connectivity (test order)
- [ ] Review overnight VIX from previous close
- [ ] Check for system maintenance announcements
- [ ] Verify account balance in Fyers
- [ ] Review yesterday's trade outcomes
- [ ] Check economic calendar for today
- [ ] Set phone alarm for 11:00 AM (entry window)
- [ ] Confirm exit targets are set (profit & stop-loss)

---

## Weekly Checkpoint (Every Friday, 4:00 PM)

**Week of**: [ ]

| Metric | Value | Target | Pass/Fail |
|--------|-------|--------|-----------|
| Trades | [ ] | 0–2 | [ ] |
| Win Rate | [ ]% | >= 75% | [ ] |
| P&L | ₹[ ] | ₹5–20k | [ ] |
| Max Loss | ₹[ ] | < ₹-50k | [ ] |
| Account DD | [ ]% | < 10% | [ ] |
| API Issues | [ ] | 0 | [ ] |

**Go/No-Go**: [ ] CONTINUE [ ] PAUSE [ ] ESCALATE

**Notes**: 

---

## Monthly Thresholds (HARD STOPS)

**If ANY of these trigger, PAUSE ALL TRADING immediately:**

1. **Account DD reaches 15%** (loss of ₹2,25,000)
   - Action: Close all open positions, investigate backtest vs live gap
   
2. **3 consecutive losing trades**
   - Action: Pause for 1 week, review ML signals in detail
   
3. **Single trade loss exceeds ₹75,000**
   - Action: Immediate manual exit, reduce size 50% on next trade
   
4. **Win rate drops below 60% over last 10 trades**
   - Action: Pause, investigate market regime change
   
5. **Fyers API experiences > 1 hour downtime**
   - Action: Close all positions, switch to backup broker if available
   
6. **Slippage vs backtest exceeds 50 bp consistently**
   - Action: Reduce position size, investigate fill timing
   
7. **Model P&L deviates > 50% from backtest over 5 trades**
   - Action: Pause, investigate feature drift or market regime change

---

## Monthly Summary (Refresh End of Month)

**Month**: [ ]

| Week | Trades | Wins | Losses | Win % | P&L | Status |
|------|--------|------|--------|-------|-----|--------|
| Week 1 | [ ] | [ ] | [ ] | [ ]% | ₹[ ] | [ ] |
| Week 2 | [ ] | [ ] | [ ] | [ ]% | ₹[ ] | [ ] |
| Week 3 | [ ] | [ ] | [ ] | [ ]% | ₹[ ] | [ ] |
| Week 4 | [ ] | [ ] | [ ] | [ ]% | ₹[ ] | [ ] |
| **Total** | **[ ]** | **[ ]** | **[ ]** | **[ ]%** | **₹[ ]** | **[ ]** |

**Backtest Expected** (6 trades/year = 0.5/month average):
- Expected P&L: ₹14,764 (½ of ₹29,528)
- Expected Win Rate: 78%

**Actual vs Expected**:
- P&L: ₹[ ] vs ₹14,764 ([ ]% variance)
- Win %: [ ]% vs 78% ([ ]pp delta)

**Decision**: [ ] ON TRACK [ ] REVIEW [ ] PAUSE

---

## Escalation Matrix

| Scenario | Trigger | Action | Escalation Level |
|----------|---------|--------|------------------|
| Mild Drawdown | DD 5–10% | Reduce size 25% | Yellow |
| Moderate Drawdown | DD 10–15% | Reduce size 50% | Orange |
| Severe Drawdown | DD > 15% | PAUSE all entries | Red |
| Win Rate Degradation | < 70% over 5 trades | Review signals | Yellow |
| Win Rate Crisis | < 50% over 10 trades | PAUSE, investigate | Red |
| API Failure | Latency > 10 sec | Switch execution | Orange |
| Slippage Drift | > 75 bp avg | Reduce size | Yellow |
| Single Trade Loss | > ₹75k | Manual exit, reduce size | Orange |

---

## Contacts & Resources

**Broker Support**:
- Fyers Support: [ ]
- Fyers API Docs: https://docs.fyers.in/api/

**Backup Plans**:
- Backup Broker: [ ]
- Emergency Exit: Manual via Fyers web platform
- Support Contact: [ ]

**Reference**:
- Backtest Report: docs/
- ML Model: data/.cache/entry_model_v4.pkl
- Strategy Rules: CLAUDE.md

---

**Dashboard Status**: [ ] LIVE [ ] INACTIVE  
**Last Review**: [ ]  
**Next Review**: [ ]

