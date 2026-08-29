# Paper Trading Setup Checklist

**Objective**: Get ready for live trading in 2 weeks  
**Initial Capital**: ₹15,00,000  
**Strategy**: Weekly PCS/IC only  
**Start Date**: [Fill this]  
**Target Live Date**: [Fill this + 14 days]

---

## Week 1: Setup & Preparation

### Day 1: Read Documentation (2 hours)
- [ ] Read `paper_trading/README.md` (overview, 15 min)
- [ ] Read `PAPER_TRADING_JOURNAL.md` (rules, checkpoints, 30 min)
- [ ] Read `QUICK_REFERENCE.md` (trading cheat sheet, 20 min)
- [ ] Print QUICK_REFERENCE.md (laminate if possible)
- [ ] Skim all CSV templates (5 min)

**Checkpoint**: Understand the framework. Ask clarifying questions now.

### Day 2–3: Fyers Account Setup (4 hours)
- [ ] Open Fyers account with ₹15L capital
  - Contact: https://fyers.in/
  - Required: PAN, Aadhaar, bank account
  - Account type: Individual (not corporate)
  - Segment: F&O (derivatives)
  
- [ ] Set up 2FA (SMS + email)
- [ ] Enable withdrawal disable mode (security)
- [ ] Request Fyers API access
  - Developer portal: https://developers.fyers.in/
  - Generate API keys
  - Note Client ID & API Secret (keep safe)
  
- [ ] Download Fyers mobile app + web platform
- [ ] Deposit ₹15L to account (may take 1–2 business days)

**Checkpoint**: Account funded, API credentials ready, API access confirmed.

### Day 4: Verify Models & Data
- [ ] Check baseline models exist:
  ```bash
  ls -la data/.cache/entry_model_v4.pkl  # RegimeAwareLearner
  ls -la data/.cache/exit_model.pkl      # ExitStrategyEngine
  ```
  Both files should be present and recent (< 1 week old)

- [ ] Review backtest baseline (Run #60):
  - Read: docs/BACKTEST_COMBINED_MODE.md
  - Confirm: 12.07% CAGR, 78% win rate, ₹29,528 avg P&L/trade

- [ ] Verify capital allocation plan:
  - Weekly: ₹12,00,000 (80%)
  - Monthly: ₹0 (paused)
  - Reserve: ₹3,00,000 (20%)

**Checkpoint**: Baseline models confirmed, allocation verified.

### Day 5–7: Fyers API Testing (6 hours)

**Test 1: API Connection**
```python
# Pseudo-code to test:
from fyers_api import fyersModel

client = fyersModel.FyersModel(
    client_id="YOUR_CLIENT_ID",
    api_secret="YOUR_API_SECRET",
    grant_type="password",
    scope=["full_access"],
    redirect_uri="http://localhost:3000",
    state="sample_state"
)

# Get login URL
print(client.get_login_url())
# → Copy URL to browser, authorize, capture auth code
client.set_token("AUTH_CODE")

# Test: Get account info
profile = client.get_profile()
print(f"Account Equity: {profile['equity']}")
print(f"Available Margin: {profile['available_margin']}")
```

- [ ] Test order placement (practice order):
  ```python
  # Place test IOC order for Nifty PE
  order_data = {
      "symbol": "NSE:NIFTYIT50JUL25PE18400",  # Example
      "qty": 1,
      "price": 100,
      "order_type": "MARKET",
      "time_in_force": "IOC",
      "side": "BUY"  # Just for test
  }
  response = client.place_order(order_data)
  print(response)
  
  # Then cancel it immediately
  ```

- [ ] Measure API latency:
  - Target: < 2 seconds from order creation to fill
  - Log 5–10 test orders, time each
  - Average latency should be < 1 sec (ISC exchange is fast)

- [ ] Test order cancellation:
  - Place order, wait 1 sec, cancel
  - Verify instant cancellation

**Checkpoint**: API works, latency < 2 sec, orders placed & cancelled successfully.

### Day 5–7: Set Up Tracking

- [ ] Fill all date fields in spreadsheets:
  - TRADES.csv: First row header (already done)
  - DAILY_LOG.csv: First row header (already done)
  - PAPER_TRADING_JOURNAL.md: Fill 6 checkpoint dates (30 days apart)

- [ ] Create calendar reminders:
  - 10:55 AM (weekdays): "Pre-market checklist" (5 min before entry window)
  - 4:30 PM (weekdays): "Log day's trades"
  - 4:00 PM (Fridays): "Weekly checkpoint"
  - 1st of each month: "Monthly ANALYSIS.md review"

- [ ] Set up notifications:
  - Email alert if account DD > 10%
  - SMS alert if single loss > ₹40k
  - Test alerts with dummy events

**Checkpoint**: All templates filled, reminders set, alerts active.

---

## Week 2: Rules Review & Simulation

### Day 8–9: Deep Dive Rules (3 hours)

**Entry Rules**:
- [ ] Memorize entry checklist (QUICK_REFERENCE.md)
  - [ ] VIX check — regime for entry?
  - [ ] ML signal >= 0.50?
  - [ ] Capital available (₹5L+ margin)?
  - [ ] Open positions < 3?
  - [ ] Fyers API live?
  - [ ] 11:00–13:00 IST window?
  - [ ] DTE 3–8?

**Exit Rules**:
- [ ] Profit target = 50% of max profit → EXIT immediately
- [ ] Stop loss = 2× credit amount → EXIT immediately
- [ ] DTE = 0 (expiry day) → EXIT by 3:15 PM
- [ ] Time = 3 trading days max → EXIT by EOD
- [ ] Manual only for tail events (VIX > 35)

**Risk Limits** (HARD STOPS):
- [ ] Single trade max loss: ₹50,000
- [ ] Daily account loss: ₹1,00,000
- [ ] Account DD: 15% (₹2,25,000)
- [ ] Concurrent opens: 3 max

**Escalation Protocol** (Print & tape on monitor):
- [ ] 🟡 Yellow: DD 5–10%, reduce size 25%
- [ ] 🟠 Orange: DD 10–15%, reduce size 50%
- [ ] 🔴 Red: DD > 15%, STOP ALL

### Day 9–10: Simulate 3 Trades (2 hours)

**Simulation 1: Low VIX Entry**
- Scenario: VIX = 15, Nifty 25200, Sept expiry 5 DTE
- Backtest signal: 0.58 ML score, regime = LOW_VOL
- Action: Simulate entry at ₹85 credit (1 lot × 65)
  - Entry price: ₹85
  - Max profit: ₹85 × 65 = ₹5,525
  - Profit target (50%): ₹2,762
  - Stop loss (2×): ₹170 loss = ₹11,050 loss cap
- Simulate exit: Stock falls to ₹42 next day → Exit at 50% profit
- Log: Simulate entry in TRADES.csv
- Q: Would you have taken this? Why/why not?

**Simulation 2: High VIX Entry** (Cautious)
- Scenario: VIX = 26, Nifty 25100, Sept expiry 3 DTE
- Backtest signal: 0.51 ML score, regime = ELEVATED
- Action: Simulate entry at ₹55 credit (smaller, 1 lot × 65)
  - Entry price: ₹55
  - Max profit: ₹55 × 65 = ₹3,575
  - Profit target: ₹1,787
  - Stop loss: ₹110 loss = ₹7,150 loss cap
- Simulate exit: Stock rallies → Stop hit at day 2
- Log: Simulate exit in TRADES.csv
- Q: How would you adjust size for high VIX?

**Simulation 3: Tail Event** (Manage Max Loss)
- Scenario: Entered at ₹80, margin used ₹5L, mid-trade VIX spikes to 35+
- Backtest expected: Normal ₹25k profit
- Real scenario: Market gaps up, option worth ₹120
- Loss: ₹120 × 65 = ₹7,800 loss
- Action: Exit immediately, accept loss, log deviation
- Q: Should you have sized down for tail events?

**Checkpoint**: Can mentally execute entry/exit? Ready to trade live.

### Day 10–11: API Rehearsal (2 hours)

- [ ] Rehearse 10 mock order placements:
  - Open Nifty PE (1–2 contracts)
  - Wait 30 sec, exit
  - Time each order-to-fill
  - Log latency in RISK_DASHBOARD.md

- [ ] Practice trade logging:
  - Simulate 3 trades manually
  - Log each step to TRADES.csv
  - Calculate slippage, P&L, deviation
  - Take 5 min total per trade

- [ ] Test error handling:
  - Kill Fyers app mid-trade, recover via web platform
  - Test manual order cancellation
  - Test stop-loss failsafe

**Checkpoint**: Comfortable with API, logging fast & accurate.

### Day 12–14: Final Review & Launch Prep (3 hours)

- [ ] Reread QUICK_REFERENCE.md (laminated)
- [ ] Reread entry checklist (can do from memory?)
- [ ] Reread exit rules (profit target = 50%?, stop = 2×?)
- [ ] Reread hard stops (DD 15%?, single loss ₹50k?)
- [ ] Verify all files in place:
  ```bash
  ls paper_trading/{README.md, QUICK_REFERENCE.md, PAPER_TRADING_JOURNAL.md}
  ls paper_trading/tracker/{TRADES.csv, DAILY_LOG.csv, RISK_DASHBOARD.md}
  ls paper_trading/analysis/MONTHLY_ANALYSIS.md
  ```

- [ ] Final equipment check:
  - [ ] Monitor setup (QUICK_REFERENCE laminated visible)
  - [ ] Internet stable (test ping to NSE)
  - [ ] Phone charged (Fyers app + SMS alerts ready)
  - [ ] Notebook for manual notes (backup if no time to log)

- [ ] Pre-launch meeting (internal or with mentor):
  - [ ] Discuss backtest baseline
  - [ ] Discuss entry/exit rules
  - [ ] Discuss hard stops
  - [ ] Agree on check-in cadence (weekly call?)

**Checkpoint**: Ready for live trading. All systems GO.

---

## Launch Week: Live Trading Begins

### Day 15 (Monday)
- [ ] 9:00 AM: Final confidence check
- [ ] 10:55 AM: Enter entry checklist mindset
- [ ] 11:00 AM–1:00 PM: Trade!
- [ ] 4:30 PM: Log day (even if no trades)
- [ ] Evening: Reflect on first day

### Days 16–20 (Tue–Fri)
- [ ] 10:55 AM: Entry checklist (print it, follow it)
- [ ] 11:00 AM–1:00 PM: Execute if signal appears
- [ ] 4:30 PM: Log day
- [ ] Friday 4:00 PM: Weekly checkpoint

### After Week 1
- [ ] Review: How many signals? How many trades executed?
- [ ] Confidence: Are rules clear? Any tweaks needed?
- [ ] Continue for 6 months (or until Phase 2 decision)

---

## Go/No-Go Decision Points

### Day 30 (Month 1 end)
**Check**:
- [ ] Trades executed: 0–2 (expected)
- [ ] Win rate: >= 70% (early data)
- [ ] Account DD: < 5%
- [ ] Slippage: Within 0.75–1× of backtest

**Decision**:
- ✅ Continue Phase 1 → Week 5 starts
- ⏸️ Hold if poor data → Collect more trades
- ❌ Stop if DD > 15% → Investigate

### Day 90 (Month 3 end)
**Check**:
- [ ] Trades executed: 3–4 total
- [ ] Win rate: >= 75%
- [ ] P&L: ₹30–50k total (on track)
- [ ] Backtest variance: < 30%

**Decision**:
- ✅ Proceed to Month 4
- ⏸️ Extend Phase 1 if marginal
- ❌ Stop if criteria not met

### Day 180 (Month 6 end)
**Check**:
- [ ] Trades executed: 6–8 total
- [ ] Win rate: >= 75%
- [ ] P&L: ₹90–120k (within range)
- [ ] Account DD: < 12%
- [ ] Backtest variance: < 30%

**Decision**:
- ✅ **GO TO PHASE 2**: Add monthly trading (20/80 allocation)
- ⏸️ **HOLD**: Collect 3 more months data
- ❌ **STOP**: Investigate backtest vs live gap, pause trading

---

## Contacts & Resources

| Item | Details |
|------|---------|
| **Fyers Support** | https://support.fyers.in/ |
| **Fyers API Docs** | https://docs.fyers.in/api/ |
| **Backtest Report** | docs/BACKTEST_COMBINED_MODE.md |
| **ML Model** | data/.cache/entry_model_v4.pkl |
| **Emergency Broker** | [Backup broker, if any] |
| **Personal Contact** | [Your name, phone, email] |

---

## Final Checklist (Before Live)

- [ ] Account funded with ₹15L
- [ ] Fyers API tested (latency < 2 sec)
- [ ] All templates filled & ready
- [ ] QUICK_REFERENCE laminated & visible
- [ ] Alerts set (email, SMS)
- [ ] Rules memorized (entry, exit, stops)
- [ ] Calendar reminders active
- [ ] 3 trades simulated successfully
- [ ] Confidence level: 8+/10
- [ ] Ready to trade!

---

**Prepared By**: System  
**Date Prepared**: [Today]  
**Target Live Date**: [Today + 14 days]  
**Status**: [ ] Ready [ ] Not Yet [ ] Completed

---

