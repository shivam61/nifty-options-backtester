# Paper Trading Quick Reference Guide

**Account**: ₹15,00,000 | **Strategy**: Weekly PCS/IC (78% win rate) | **Phase**: 1 (Validation)

---

## Entry Checklist (Before 11:00 AM IST)

- [ ] VIX check — Is VIX in regime for entry?
- [ ] ML signal — Is RegimeAwareLearner score >= 0.50?
- [ ] Capital check — Do we have ₹5L+ available margin?
- [ ] Open positions — Are we at max 2–3 concurrent trades?
- [ ] Fyers API — Is connection live? (test: place dummy order)
- [ ] Mid-session time — Is it 11:00–13:00 IST window?
- [ ] DTE filter — Is weekly expiry 3–8 DTE away?
- [ ] VIX simultaneous gate — Is VIX < 25 if monthly were open? (N/A for Phase 1)

**If ALL checked ✓**: Place order. Size: 65-lot base.

---

## Exit Rules (STRICT)

### Profit Target (EXIT)
- **50% of max profit**: Close immediately when hit
- Example: Max credit ₹10k → Exit at ₹5k profit

### Stop Loss (EXIT)
- **2× credit amount**: Hard cap, no negotiation
- Example: Credit ₹5k → Stop at ₹-10k loss
- Alternative: ₹50k account loss cap (whichever hits first)

### DTE Expiry (EXIT)
- **0 DTE (day of expiry)**: Close all positions by 3:15 PM (15 min before close)
- Example: Weekly expires Friday → Close Friday 3:15 PM latest

### Time-Based Exit
- **Max 3 trading days**: Exit by EOD day 3 if not hit target or stop
- Example: Enter Mon 12 PM → Must exit by Wed EOD

### Manual Exit (Rare)
- **Tail event (VIX > 35)**: Manual judgement call
- **Slippage breakdown**: If fills worse than 2× normal
- **Technical malfunction**: Fyers API down, manual exit needed

---

## Trade Log Example

```
Trade ID: PT-001
Date Entry: 2024-09-16
Entry Time: 12:15 PM IST
Instrument: Nifty 25200 PE
Entry Price: ₹85 (credit taken)
Lots: 1 × 65
Capital Deployed: ₹5,00,000 (approx)
Signal VIX: 18.5
ML Score: 0.58
Expiry DTE: 5
Max Profit: ₹85 × 65 = ₹5,525
Profit Target (50%): ₹2,762
Stop Loss: ₹85 × 2 = ₹170 loss cap = ₹11,050 loss

Date Exit: 2024-09-17
Exit Time: 11:45 AM IST
Exit Price: ₹42.50 (closed at 50% profit target)
Exit Reason: Profit Target Hit
Days Held: 1
Gross P&L: ₹2,762
Brokerage: ₹200
Net P&L: ₹2,562
Win/Loss: WIN
Backtest Expected: ₹29,528
Deviation: -91% (smaller trade)
```

---

## Risk Limits (Daily)

| Limit | Amount | If Breached |
|-------|--------|------------|
| Single trade max loss | ₹50,000 | Manual exit, reduce size |
| Daily account loss | ₹1,00,000 | Pause new entries |
| Account DD | 15% (₹2,25k) | STOP ALL TRADING |
| Concurrent open trades | 3 positions max | Wait for exit |

---

## VIX Regime Guide

| VIX Range | Regime | Weekly Action | Notes |
|-----------|--------|--------------|-------|
| < 14 | Very Low | AGGRESSIVE ENTRY | Best profit potential (₹40k+) |
| 14–18 | Low | NORMAL ENTRY | Good risk/reward |
| 18–22 | Normal | NORMAL ENTRY | Baseline, predictable |
| 22–28 | Elevated | CAUTIOUS ENTRY | Larger stops needed |
| 28–35 | High | TIGHT ENTRIES | Only if high confidence |
| 35+ | Crisis | PAUSE ENTRIES | Risk too high |

---

## Fyers API Execution

**Order Type**: IOC (Immediate or Cancel)  
**Time Bracket**: 11:00–13:00 IST only  
**Fill Target**: Mid-session spot + 0.75× slippage  

**Example**:
- Nifty spot: ₹25,200
- Backtest assumed fill: ₹85 (premium estimated)
- Fyers actual fill: ₹85–₹90 acceptable (within 0.75× slippage)
- Fyers actual fill: ₹100+ (> 1× slippage) → ABORT, wait for better fill

---

## Weekly Checklist (Every Friday 4 PM)

- [ ] **Count trades**: How many weekly trades this week?
- [ ] **Calculate win %**: Wins / (Wins + Losses)
- [ ] **Sum P&L**: Total profit or loss this week
- [ ] **Max loss**: What was the biggest single loss?
- [ ] **Account DD**: Current drawdown % from peak
- [ ] **Compare backtest**: Did actual match backtest expectations?
- [ ] **API issues**: Any downtime or execution failures?
- [ ] **Next week prep**: Any special events or economic data?

**Decision**: Continue Phase 1? Or escalate/pause?

---

## Escalation Protocol

**🟡 Yellow Alert (Monitor Closely)**:
- DD 5–10%
- Win rate < 75% over 5 trades
- Single loss > ₹40k

→ **Action**: Reduce position size 25%, continue with caution

**🟠 Orange Alert (Reduce Risk)**:
- DD 10–15%
- Win rate < 60% over 5 trades
- Single loss > ₹75k

→ **Action**: Reduce position size 50%, pause aggressive entries

**🔴 Red Alert (STOP)**:
- DD > 15%
- Win rate < 50% over 10 trades
- API failure > 1 hour
- 3 consecutive losses

→ **Action**: CLOSE ALL POSITIONS, PAUSE ALL TRADING, investigate

---

## Monthly Milestones (Target)

| Milestone | Target | Expected |
|-----------|--------|----------|
| **Trades** | 0–2 | 1 trade every 15 days |
| **Win Rate** | >= 75% | 1–2 wins out of 1–2 trades |
| **P&L** | ₹5–20k | Average ₹14k/month |
| **Max Loss** | < ₹-50k | Hopefully avoid this |
| **Winning Avg** | ₹30–50k | Per winning trade |
| **Slippage** | 0.75–1× | Match backtest |

**6-Month Target**: ₹85–120k profit (6 trades × ₹14–20k avg)

---

## Backtest vs Live Comparison

**Backtest (Run #60)**:
- Win Rate: 78%
- Avg Profit/Trade: ₹29,528
- Max Loss: ₹-53,255
- Holding: 3 days
- Profit Factor: 5.76

**Live (Phase 1 Goal)**:
- Win Rate: >= 75%
- Avg Profit/Trade: >= ₹25,000
- Max Loss: <= ₹-50,000
- Holding: 2–4 days
- Profit Factor: >= 5.0

**Acceptance Criteria**: Live results within 30% of backtest over 10 trades

---

## Common Mistakes to Avoid

1. ❌ **Entering outside 11:00–13:00 IST window**
   → Mid-session assumption breaks; wider spreads expected

2. ❌ **Oversizing position beyond 65-lot base**
   → Risk grows exponentially; stick to system

3. ❌ **Not exiting at profit target (greedy)**
   → 50% target taken, move on; lock profits

4. ❌ **Holding through stop-loss levels**
   → 2× credit is hard cap; no exceptions

5. ❌ **Entering if capital unavailable**
   → Wait for margin to free up, don't force trade

6. ❌ **Trading during VIX spikes without plan**
   → High VIX needs tighter stops; system not calibrated for it

7. ❌ **Ignoring API latency warnings**
   → > 5 sec latency = reduce size or skip trade

8. ❌ **Not logging trade details in real-time**
   → Memory is fallible; log immediately post-exit

---

## Emergency Exit Procedure

**If Fyers API goes down during open position:**

1. Switch to Fyers **web platform** (backup)
2. Place manual exit order for all open positions
3. Log trade details in TRADES.csv manually
4. Document incident in DAILY_LOG.csv
5. Email broker support with timestamp + positions
6. Do NOT try to re-enter until API is stable 15+ min

**If single trade loss exceeds ₹75,000:**

1. Exit immediately (don't wait for better fill)
2. Document reason (API slippage, tail event, etc.)
3. Reduce next trade size by 50%
4. Review that trade's ML signal score (might have been false positive)

---

## Contact & Resources

| Resource | Link | Purpose |
|----------|------|---------|
| Fyers API Docs | https://docs.fyers.in/api/ | Technical reference |
| Backtest Results | docs/BACKTEST_CHANGELOG.md | Historical performance |
| ML Model | data/.cache/entry_model_v4.pkl | Entry signal generator |
| This Repo | github.com/shivam61/nifty-options-backtester | Full codebase |

---

**Last Updated**: [Date]  
**Prepared By**: System  
**Print this. Keep it handy during 11 AM–1 PM IST window.**

