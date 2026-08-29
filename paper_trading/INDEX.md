# Paper Trading Documentation Index

**Status**: ✅ Ready for Daily Use  
**Last Updated**: 2026-08-29  
**API Server**: `http://localhost:8000`

---

## 📚 Available Guides (Read in Order)

### 1. **START HERE** → [DAILY_WORKFLOW_SUMMARY.md](./DAILY_WORKFLOW_SUMMARY.md)
- One-page quick start (5 min read)
- 4 daily touchpoints with curl commands
- Setup checklist
- **Use this** if you want to start immediately

### 2. **LAMINATE & PRINT** → [DAILY_CHECKLIST.md](./DAILY_CHECKLIST.md)
- Tape to your monitor
- Pre-formatted for printing
- Copy-paste API commands
- Hard stops highlighted
- **Use this** during trading hours (keep on desk)

### 3. **DETAILED GUIDE** → [DAILY_OPERATIONS_GUIDE.md](./DAILY_OPERATIONS_GUIDE.md)
- Step-by-step instructions for each phase
- Decision trees for every API response
- Troubleshooting section
- Catch-up workflow (missed logging)
- **Use this** for detailed questions

### 4. **QUICK REFERENCE** → [QUICK_REFERENCE.md](./QUICK_REFERENCE.md)
- Entry rules (7-item checklist)
- Exit rules (profit target, stop loss, DTE, time)
- VIX regime guide
- Escalation protocol (yellow/orange/red alerts)
- **Use this** when you need trading rules

### 5. **API DOCUMENTATION** → [../API_GUIDE.md](../API_GUIDE.md)
- Complete endpoint reference (13 endpoints)
- Request/response schemas
- Curl examples
- Error handling
- **Use this** for API technical details

### 6. **RISK MANAGEMENT** → [tracker/RISK_DASHBOARD.md](./tracker/RISK_DASHBOARD.md)
- Real-time risk monitoring template
- Hard stops (DD, losses, streaks)
- Weekly checkpoint
- Monthly thresholds
- **Use this** for Friday reviews + risk alerts

### 7. **MONTHLY REVIEW** → [analysis/MONTHLY_ANALYSIS.md](./analysis/MONTHLY_ANALYSIS.md)
- Trade-by-trade breakdown template
- Backtest vs live comparison
- 7 risk management checks
- Go/no-go decision criteria
- **Use this** at month-end (30-day checkpoint)

### 8. **SETUP GUIDE** → [SETUP_CHECKLIST.md](./SETUP_CHECKLIST.md)
- 2-week pre-launch preparation
- Fyers account setup
- API testing steps
- Equipment checklist
- **Use this** before first trade

### 9. **MAIN JOURNAL** → [PAPER_TRADING_JOURNAL.md](./PAPER_TRADING_JOURNAL.md)
- 6 monthly checkpoints (for 6-month Phase 1)
- Account allocation rules
- Trading rules reference
- Deviation log
- **Use this** for milestone tracking

### 10. **OVERVIEW** → [README.md](./README.md)
- Complete system overview (15 min read)
- Capital allocation breakdown
- Daily/weekly/monthly routine
- Phase transition criteria
- **Use this** for big-picture context

---

## 📊 CSV Templates (Auto-Updated by API)

### [tracker/TRADES.csv](./tracker/TRADES.csv)
- Master trade log (25 columns)
- Entry → Exit complete record
- P&L, slippage, backtest deviation
- **Updated by**: `POST /trades/open` and `POST /trades/{id}/close`

### [tracker/DAILY_LOG.csv](./tracker/DAILY_LOG.csv)
- Daily account snapshot (11 columns)
- Equity, P&L, VIX, regime, win rate
- **Updated by**: `POST /journal/daily-log` (4:30 PM daily)

---

## 🕐 Which Guide When?

| Situation | Guide |
|-----------|-------|
| **First time reading** | DAILY_WORKFLOW_SUMMARY.md (5 min) |
| **During trading (10 AM)** | DAILY_CHECKLIST.md (keep visible) |
| **"How do I..."** | DAILY_OPERATIONS_GUIDE.md (detailed) |
| **"What's the rule for..."** | QUICK_REFERENCE.md (rules only) |
| **"My API call failed"** | API_GUIDE.md (troubleshooting) |
| **"How do I handle risk?"** | RISK_DASHBOARD.md (Friday review) |
| **"End of month, what's next?"** | MONTHLY_ANALYSIS.md (month-end) |
| **"I need full context"** | README.md (15-min overview) |

---

## 🚀 Quick Start (3 Steps)

### Step 1: Start API Server
```bash
uvicorn api.server:app --port 8000
```

### Step 2: Create Journal Session
```bash
curl -X POST http://localhost:8000/journals \
  -H "Content-Type: application/json" \
  -d '{
    "journal_id": "phase1-sep-2026",
    "label": "Phase 1 Weekly Sep 2026",
    "initial_capital": 1500000,
    "strategy_track": "weekly"
  }'
```

### Step 3: Follow Daily Workflow
Read [DAILY_WORKFLOW_SUMMARY.md](./DAILY_WORKFLOW_SUMMARY.md) and execute at:
- **10:00 AM** ← Pre-market check
- **11:30 AM** ← Entry decision
- **3:00 PM** ← Monitoring (every 30 min)
- **4:30 PM** ← End-of-day logging

---

## 📈 Phase 1 Timeline (6 Months)

| Period | Checkpoint | Docs to Read |
|--------|-----------|--------------|
| **Days 1–14** | Pre-launch | SETUP_CHECKLIST.md |
| **Day 15** | First trade | DAILY_OPERATIONS_GUIDE.md |
| **Days 16–30** | First month | DAILY_CHECKLIST.md + monitoring |
| **Day 30** | Month 1 review | MONTHLY_ANALYSIS.md |
| **Days 31–60** | Month 2 | Continue routine |
| **Day 60** | Month 2 review | MONTHLY_ANALYSIS.md |
| **Days 61–180** | Months 3–6 | Repeat daily + monthly review |
| **Day 180** | Phase 1 complete | PAPER_TRADING_JOURNAL.md (Decision: Go to Phase 2?) |

---

## 🎯 Daily Workflow Duration

| Phase | Time | Docs |
|-------|------|------|
| Pre-market (10 AM) | 5 min | DAILY_CHECKLIST.md |
| Entry (11:30 AM) | 5 min | DAILY_OPERATIONS_GUIDE.md |
| Monitoring (3–4:30 PM) | 5 min | DAILY_CHECKLIST.md |
| EOD logging (4:30 PM) | 5 min | DAILY_OPERATIONS_GUIDE.md |
| **DAILY TOTAL** | **~15 min** | **All of above** |
| **Weekly Review** (Fri) | +5 min | RISK_DASHBOARD.md |
| **Monthly Review** | +20 min | MONTHLY_ANALYSIS.md |

---

## 🔗 External Resources

| Resource | Link | Use For |
|----------|------|---------|
| Fyers API Docs | https://docs.fyers.in/api/ | Live order placement (Phase 2) |
| NSE Holidays | https://www.nseindia.com/market-data/holiday-calendar | Trading days |
| VIX Levels | https://www.nseindia.com/products/indices-vix.htm | Market regime assessment |
| Backtest Results | [docs/BACKTEST_COMBINED_MODE.md](../docs/BACKTEST_COMBINED_MODE.md) | Baseline expectations |

---

## ✅ Pre-Trading Checklist

- [ ] API server running (`http://localhost:8000/health` returns healthy)
- [ ] Journal session created
- [ ] Fyers account funded with ₹15L
- [ ] Fyers API credentials tested
- [ ] DAILY_CHECKLIST.md printed & on desk
- [ ] All 4 daily reminders set (10 AM, 11:30 AM, 3 PM, 4:30 PM)
- [ ] Understand entry window (11:00–13:00 IST mandatory)
- [ ] Understand exit rules (50% target, 2× stop loss)
- [ ] Know hard stops (DD > 15%, losses, streaks)
- [ ] Ready to trade tomorrow! 🚀

---

## 🆘 Help

**"Where do I start?"**
→ Read DAILY_WORKFLOW_SUMMARY.md (this page → that page = 5 min)

**"How do I log trades?"**
→ Follow DAILY_OPERATIONS_GUIDE.md (Phase 2: Entry Decision)

**"What if I miss logging?"**
→ See DAILY_OPERATIONS_GUIDE.md (Catch-up section)

**"API call failed!"**
→ Check API_GUIDE.md (error handling)

**"I need to know the rules"**
→ Print QUICK_REFERENCE.md (1 page, laminated)

**"End of month, what now?"**
→ Fill MONTHLY_ANALYSIS.md (month-end review template)

---

**You're ready!** 📋 Pick a guide above and start. Questions? See "Help" section.

**Next step**: Read [DAILY_WORKFLOW_SUMMARY.md](./DAILY_WORKFLOW_SUMMARY.md) right now (5 min). Then print [DAILY_CHECKLIST.md](./DAILY_CHECKLIST.md) and tape to your monitor.

Good luck! 🚀
