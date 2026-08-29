# Paper Trading Journal & Tracking System

**Status**: Ready for launch  
**Initial Capital**: ₹15,00,000  
**Strategy**: Weekly PCS/IC (3-day holds)  
**Baseline Model**: Run #60 (12.07% CAGR, 78% win rate)  
**Phase**: 1 — Validation (6 months)

---

## Overview

This is a complete paper trading tracking system for validating the Phase 4 baseline backtest (Run #60) against live market conditions. The system is designed to capture every trade, measure slippage, validate ML signals, and provide clear go/no-go decision criteria for advancing to Phase 2 (adding monthly trading).

### What's Inside

```
paper_trading/
├── README.md                        ← You are here
├── PAPER_TRADING_JOURNAL.md        ← Main journal with checkpoints
├── QUICK_REFERENCE.md              ← Laminated cheat sheet (print this)
├── tracker/
│   ├── TRADES.csv                  ← Every trade logged here
│   ├── DAILY_LOG.csv               ← End-of-day account snapshot
│   └── RISK_DASHBOARD.md           ← Real-time risk monitoring
├── analysis/
│   └── MONTHLY_ANALYSIS.md         ← Month-end detailed review
├── journal/
│   └── [TRADE_NOTES_YYYY_MM.txt]  ← Free-form daily notes
└── logs/
    └── [API_LOGS_YYYY_MM_DD.log]  ← Technical execution logs
```

---

## Quick Start (5 Minutes)

### 1. Account Setup
- [ ] Open Fyers account with ₹15L capital
- [ ] Get Fyers API credentials
- [ ] Test API connection (place dummy order)
- [ ] Set up 2FA & withdraw-disable mode

### 2. System Initialization
- [ ] Fill "Account Setup Date" in PAPER_TRADING_JOURNAL.md
- [ ] Verify baseline models exist (`data/.cache/entry_model_v4.pkl`, `exit_model.pkl`)
- [ ] Print QUICK_REFERENCE.md (keep on desk during trading)
- [ ] Set calendar reminders for weekly checkpoints (Fridays 4 PM)

### 3. Pre-Trading Checklist
- [ ] Read PAPER_TRADING_JOURNAL.md (full document, 10 min)
- [ ] Read QUICK_REFERENCE.md (trading rules, 5 min)
- [ ] Simulate 3 trades mentally using the trade log template
- [ ] Verify Fyers API latency < 2 seconds
- [ ] Set up email/Slack alerts for P&L milestones

### 4. Go Live
- [ ] Enable live trading mode in Fyers (first 2 weeks: paper mode)
- [ ] Trade weekly PCS/IC exclusively (monthly paused)
- [ ] Log every entry/exit in TRADES.csv within 5 min of execution
- [ ] Update DAILY_LOG.csv at 4:30 PM (after market close)

---

## File-by-File Guide

### PAPER_TRADING_JOURNAL.md
**Purpose**: Central journal with 6 monthly checkpoints and decision criteria  
**Update Frequency**: Monthly (every 30 days)  
**Key Sections**:
- Account overview (₹15L allocation)
- Trading rules (STRICT)
- 6 monthly checkpoints (fill in trade count, win rate, P&L)
- Deviation log (trades outside backtest logic)
- Go/no-go decision criteria for Phase 2

**How to Use**:
1. Fill dates for each checkpoint now (months 1–6)
2. Every 30 days: Fill in trades, P&L, win rate
3. At month 6: Make Phase 2 go/no-go decision
4. Keep this as the source of truth

### QUICK_REFERENCE.md
**Purpose**: Laminated trading cheat sheet (one-pager equivalent)  
**Update Frequency**: Read before every trading session  
**Key Sections**:
- Entry checklist (7 items, must all be ✓)
- Exit rules (profit target, stop loss, DTE, time)
- Risk limits (hard stops)
- VIX regime guide
- Trade log example (template)
- Escalation protocol (yellow/orange/red alerts)
- Common mistakes

**How to Use**:
- Print this. Pin to monitor.
- Read entry checklist 10 min before 11 AM IST
- Reference exit rules every day

### TRADES.csv
**Purpose**: Master log of every trade (entry → exit)  
**Update Frequency**: After every trade exit (same day)  
**Columns**: 25 fields (entry, exit, P&L, backtest deviation, notes)

**How to Use**:
1. After entering a trade, log: Trade_ID, Date, Time, Strike, Entry Price, Lots, VIX, ML Score, Expiry DTE
2. After exiting, complete: Date_Exit, Exit_Time, Exit Price, Exit_Reason, Days_Held, P&L, Slippage
3. Calculate: Win_Loss (W/L), P&L_vs_Max_Profit, Backtest_Deviation
4. Every Friday: Paste this into MONTHLY_ANALYSIS.md

### DAILY_LOG.csv
**Purpose**: Daily account snapshot (equity, DD%, open trades, VIX)  
**Update Frequency**: Every trading day at 4:30 PM  
**Key Columns**: Date, Account_Equity, P&L, VIX_Close, Regime, Trades_Executed, Win_Rate_YTD, Notes

**How to Use**:
1. At market close (4:30 PM), fill in the day's row
2. Use this to spot trends (e.g., "losing streak week 3")
3. This becomes the data source for MONTHLY_ANALYSIS.md

### RISK_DASHBOARD.md
**Purpose**: Real-time risk monitoring (updated daily)  
**Update Frequency**: Before market open + end of day  
**Key Sections**:
- Account status (equity, P&L, DD%)
- Open positions (unrealized P&L)
- Risk alerts (🔴 critical, 🟡 warning, 🟢 normal)
- Daily checklist (8 items)
- Weekly checkpoint (Fridays)
- Hard stops (7 triggers for pausing)

**How to Use**:
- Every morning (10 AM IST): Check 🟢/🟡/🔴 status
- If any critical alert: STOP all new entries
- Every Friday 4 PM: Fill weekly checkpoint
- This is your early warning system

### MONTHLY_ANALYSIS.md
**Purpose**: Detailed month-end review (backtest vs live)  
**Update Frequency**: Once per month (end of month, take 1 hour)  
**Key Sections**:
- Summary metrics (wins, losses, P&L, max DD)
- Trade-by-trade review (analysis of each 1–2 trades)
- Missed signals & deviations
- Market conditions & VIX regime analysis
- Backtest vs live comparison table
- Fyers API performance
- Risk management checks (7 checks)
- Key observations & learnings
- Decision: Continue / Pause / Escalate

**How to Use**:
1. Copy template to new file: `ANALYSIS_2024_09.md` (date-named)
2. Pull data from TRADES.csv and DAILY_LOG.csv
3. Analyze each trade individually (why did it win/lose?)
4. Compare actual results to backtest expectations
5. Make go/no-go decision for next month

---

## Capital Allocation Breakdown

| Allocation | Amount | Purpose |
|----------|--------|---------|
| **Weekly Trading Capital** | ₹12,00,000 (80%) | Primary strategy |
| **Monthly Trading Capital** | ₹0 (paused, 0%) | Disabled Phase 1 |
| **Reserve/Cushion** | ₹3,00,000 (20%) | Drawdown absorption |
| **Margin per Trade** | ~₹5,00,000 | 65-lot position (approx) |

**Capital Usage**:
- Open 1 weekly trade: Uses ~₹5,00,000 margin, leaving ₹7,00,000 available
- Can open 2–3 concurrent weekly trades if signals align
- Never deploy entire ₹12L in one position

---

## Key Metrics & Targets

### Phase 1 Success Criteria (6 months)

| Metric | Backtest | Live Target | Status |
|--------|----------|-------------|--------|
| **Trades** | 6/year | 6–8 trades | [ ] |
| **Win Rate** | 78% | >= 75% | [ ] |
| **Avg P&L/Trade** | ₹29,528 | >= ₹25,000 | [ ] |
| **Total P&L** | ₹177k/year | ₹90–120k (6 mo) | [ ] |
| **Max Single Loss** | ₹-53k | <= ₹-50k | [ ] |
| **Max Account DD** | 6.2% | < 15% (hard cap) | [ ] |
| **Slippage vs Backtest** | 0.75× | ±50 bp acceptable | [ ] |

**Decision Criteria**:
- ✅ GO to Phase 2 if: 10+ trades, >= 75% win rate, < 12% DD
- ⚠️ HOLD if: 5–10 trades, 70–75% win rate, < 12% DD
- ❌ STOP if: Win rate < 60%, DD > 15%, API failures

---

## Daily Routine (Sample Day)

### 10:00 AM IST
- Check RISK_DASHBOARD.md
- Read entry checklist in QUICK_REFERENCE.md
- Check Fyers API (dummy order test)
- Review last trade's outcome

### 11:00 AM–1:00 PM IST (Entry Window)
- Monitor ML signals from model
- Check VIX current reading
- If signal triggers: Place IOC order
- Log entry immediately in TRADES.csv

### Throughout Day
- Monitor open position (unrealized P&L)
- Be ready to exit at profit target or stop loss
- No "hope trading" — follow the rules

### 3:00 PM IST
- Start monitoring for exit opportunity
- Prepare to close if target/stop hit
- No holding into close (risk overnight gap)

### 4:00 PM IST (Market Close)
- Exit any remaining open positions
- Update TRADES.csv with exit price
- Log daily data in DAILY_LOG.csv

### 4:30 PM IST
- Update RISK_DASHBOARD.md (red/yellow/green status)
- Review the day's trade(s)
- Update journal notes: What went well? What was hard?

---

## Monthly Review Cadence

| Frequency | Task | Output |
|-----------|------|--------|
| **Daily** | Log entry/exit in TRADES.csv | Trade record |
| **Daily EOD** | Update DAILY_LOG.csv | Account snapshot |
| **Weekly (Fri 4 PM)** | Fill RISK_DASHBOARD checkpoint | Weekly status |
| **Monthly (End)** | Complete MONTHLY_ANALYSIS.md | Detailed review |
| **Monthly (Day 1)** | Make go/no-go decision for next month | Continue/Pause/Phase 2 |

---

## Escalation Protocol (Critical)

### 🟡 Yellow Alert (Caution)
**Trigger**: DD 5–10%, or win rate < 75% over 5 trades, or single loss > ₹40k  
**Action**: Reduce position size 25%, continue monitoring

### 🟠 Orange Alert (Reduce Risk)
**Trigger**: DD 10–15%, or win rate < 60% over 5 trades, or single loss > ₹75k  
**Action**: Reduce position size 50%, pause aggressive entries

### 🔴 Red Alert (STOP)
**Trigger**: DD > 15%, or 3 consecutive losses, or API failure > 1 hour  
**Action**: CLOSE ALL POSITIONS, PAUSE ALL TRADING  
**Recovery**: Investigate root cause, contact support, plan restart

---

## Phase Transition Decision (Month 6)

### Go to Phase 2 (Add Monthly)? ✅
**Conditions**:
- ✅ 10+ weekly trades with >= 75% win rate
- ✅ Avg P&L >= ₹25k/trade
- ✅ Account DD < 12%
- ✅ Backtest vs live deviation < 30%
- ✅ Fyers API stable (zero outages)
- ✅ Phase 5 monthly improvements deployed (ML threshold 0.55–0.60)

**Action**: Unlock ₹3,00,000 for monthly trading, update allocation to 20/80 monthly/weekly

### Hold (Collect More Data)? ⏸️
**Conditions**:
- 5–10 trades, 70–75% win rate, DD < 12%

**Action**: Continue Phase 1 for another 3 months, no allocation change

### Stop (Investigate Issue)? ❌
**Conditions**:
- Win rate < 60%, OR DD > 15%, OR API consistent failures

**Action**: Pause live trading, investigate backtest vs live gap, plan corrections

---

## Files Checklist

- [ ] PAPER_TRADING_JOURNAL.md (main journal with checkpoints)
- [ ] QUICK_REFERENCE.md (trading cheat sheet, print this)
- [ ] TRADES.csv (every trade logged)
- [ ] DAILY_LOG.csv (daily account snapshot)
- [ ] RISK_DASHBOARD.md (real-time risk status)
- [ ] MONTHLY_ANALYSIS.md (template for month-end review)
- [ ] journal/ (free-form daily notes folder, optional but recommended)
- [ ] logs/ (Fyers API execution logs, technical reference)

---

## Support & Resources

**If Something Goes Wrong**:

1. **API Connection Lost**: Switch to Fyers web platform, close all positions manually
2. **Fill Quality Terrible**: Skip that trade, wait for next opportunity, log deviation
3. **Profit Target Not Filling**: Exit manually at nearest bid, accept slippage
4. **Account DD Spike**: Don't panic, follow hard stop rules (15% DD = pause)
5. **Model Signal Wrong**: Log it, continue Phase 1, use for Phase 5 improvements

**Contacts**:
- Fyers API Support: https://support.fyers.in/
- Emergency: Close manually via Fyers web + call broker
- Questions on backtest: Review docs/BACKTEST_COMBINED_MODE.md

---

## Last Notes

**This is validation work, not profit-chasing.**

- Goal: Confirm backtest holds in live market
- Acceptable variance: ±30% from backtest
- Acceptable win rate: >= 75% (vs 78% backtest)
- Unacceptable: Win rate < 60%, DD > 15%, API issues

**If live results don't match backtest within 6 months, there's work to do.** This is diagnostic, not business as usual.

**Expected Outcome After 6 Months**:
- 6–8 weekly trades executed
- ~₹90–120k profit captured
- Confirmation that 78% win rate is realistic
- Green light to add monthly trading (Phase 2)
- OR root cause analysis if things went wrong

---

**Start Date**: [Fill this]  
**Target End Date (Month 6)**: [Fill this]  
**Status**: Ready to launch ✅

Good luck!

