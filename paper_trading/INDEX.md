# Paper Trading Documentation Index

**Status**: Restarting forward-only on Mon 2026-10-19. Weekly-track model acceptance recorded (risk engine OFF); the Mon 10-19 pre-flight is still to run.
**Last Updated**: 2026-10-18
**API Server**: ⚠️ **API status: NOT USABLE until fixed** (`api/server.py` cannot start at HEAD). Use the CLI and the CSVs. Known issues: [RESTART_2026-10-19.md](./RESTART_2026-10-19.md) section (f). The API docs are kept for reference but are not operational.

---

## 📚 Available Guides (Read in Order)

### 1. **START HERE** → [RESTART_2026-10-19.md](./RESTART_2026-10-19.md)
- One-page runbook for the Mon 10-19 restart
- Status snapshot, pre-flight checklist, SKIP and ENTRY logging, exit rules, known gaps
- **Use this** before the first session

### 2. **LAMINATE & PRINT** → [DAILY_CHECKLIST.md](./DAILY_CHECKLIST.md)
- Tape to your monitor
- CLI commands only; hard stops highlighted
- **Use this** during trading hours (keep on desk)

### 3. **DETAILED GUIDE** → [DAILY_OPERATIONS_GUIDE.md](./DAILY_OPERATIONS_GUIDE.md)
- Step-by-step procedure for each phase (CLI + manual CSV)
- Catch-up workflow (missed logging)
- **Use this** for detailed questions

### 4. **QUICK REFERENCE** → [QUICK_REFERENCE.md](./QUICK_REFERENCE.md)
- Entry checklist, exit rules, risk limits
- Escalation protocol
- **Use this** when you need trading rules

### 5. **API DOCUMENTATION** → [../API_GUIDE.md](../API_GUIDE.md)
- Endpoint reference (13 endpoints). **Not operational** at HEAD.
- **Use this** for reference only until the API is fixed

### 6. **RISK MANAGEMENT** → [tracker/RISK_DASHBOARD.md](./tracker/RISK_DASHBOARD.md)
- Risk monitoring template
- Pause rule (DD ≥ 15% of peak)
- Weekly checkpoint
- **Use this** for Friday reviews

### 7. **MONTHLY REVIEW** → [analysis/MONTHLY_ANALYSIS.md](./analysis/MONTHLY_ANALYSIS.md)
- Trade-by-trade breakdown template
- Backtest vs live comparison
- **Use this** at month-end checkpoints

### 8. **SETUP GUIDE** → [SETUP_CHECKLIST.md](./SETUP_CHECKLIST.md)
- Pre-launch preparation
- Fyers account setup
- Equipment checklist
- **Use this** before first trade

### 9. **MAIN JOURNAL** → [PAPER_TRADING_JOURNAL.md](./PAPER_TRADING_JOURNAL.md)
- Checkpoints (rebased to 2026-10-19)
- Rule changes vs original template
- Trading rules reference
- Deviation log
- **Use this** for milestone tracking

### 10. **OVERVIEW** → [README.md](./README.md)
- System overview
- Capital allocation
- Daily/weekly/monthly routine
- Phase transition criteria
- **Use this** for big-picture context

---

## 📊 CSV Templates (Filled by Hand)

### [tracker/TRADES.csv](./tracker/TRADES.csv)
- Master trade log (27 columns)
- Entry → Exit complete record
- P&L, slippage, backtest deviation
- **Updated by**: hand, from the CLI signal output and broker fills (RESTART section d)

### [tracker/DAILY_LOG.csv](./tracker/DAILY_LOG.csv)
- Daily snapshot, one row per trading day, including skips (15 columns)
- Equity, P&L, VIX, regime, reason codes in Notes
- **Updated by**: hand at 4:30 PM (RESTART section c)

---

## 🕐 Which Guide When?

| Situation | Guide |
|-----------|-------|
| **First time reading / restart** | RESTART_2026-10-19.md |
| **During trading (10 AM)** | DAILY_CHECKLIST.md (keep visible) |
| **"How do I..."** | DAILY_OPERATIONS_GUIDE.md (detailed) |
| **"What's the rule for..."** | QUICK_REFERENCE.md (rules only) |
| **"Signal said SKIP"** | RESTART_2026-10-19.md section (c) (reason codes) |
| **"How do I handle risk?"** | RISK_DASHBOARD.md (Friday review) |
| **"End of month, what's next?"** | MONTHLY_ANALYSIS.md (month-end) |
| **"I need full context"** | README.md (overview) |

---

## 🚀 Quick Start (CLI, 3 Steps)

### Step 1: Pre-flight
Work through the pre-flight checklist in [RESTART_2026-10-19.md](./RESTART_2026-10-19.md) section (b) (calendar, cache, models, Fyers credentials).

### Step 2: Run the signal (inside 11:00–13:00 IST)
```bash
python main.py --mode signal-combined --capital 2500000 --lots 30
```
Read the weekly track only. Ignore the monthly track.

### Step 3: Log by hand
- ENTER: add a row to `tracker/TRADES.csv` after taking real broker prices
- SKIP: add a row to `tracker/DAILY_LOG.csv` with a reason code

---

## 📈 Phase 1 Timeline (6 Months from Restart)

| Period | Checkpoint | Docs to Read |
|--------|-----------|--------------|
| **Before 10-19** | Pre-launch | SETUP_CHECKLIST.md, RESTART_2026-10-19.md |
| **Mon 10-19** | Restart day | RESTART_2026-10-19.md (pre-flight) |
| **Days 1–30** | First month | DAILY_CHECKLIST.md |
| **Day 30 (2026-11-18)** | Checkpoint 1 | PAPER_TRADING_JOURNAL.md, MONTHLY_ANALYSIS.md |
| **Day 60 (2026-12-18)** | Checkpoint 2 (go/no-go) | PAPER_TRADING_JOURNAL.md |
| **Day 180** | Phase 1 complete | PAPER_TRADING_JOURNAL.md (Decision: Go to Phase 2?) |

---

## 🎯 Daily Workflow Duration

| Phase | Time | Docs |
|-------|------|------|
| Pre-flight (10 AM) | 5 min | DAILY_CHECKLIST.md, RESTART section (b) |
| Signal and entry (11:00–13:00) | 5–10 min | DAILY_OPERATIONS_GUIDE.md |
| Monitoring (3–4:30 PM) | 5 min | DAILY_CHECKLIST.md |
| EOD logging (4:30 PM) | 5 min | DAILY_OPERATIONS_GUIDE.md |
| **DAILY TOTAL** | **~15 min** | **All of above** |
| **Weekly Review** (Fri) | +5 min | RISK_DASHBOARD.md |
| **Monthly Review** | +20 min | MONTHLY_ANALYSIS.md |

---

## 🔗 External Resources

| Resource | Link | Use For |
|----------|------|---------|
| Fyers API Docs | https://docs.fyers.in/api/ | Reference (API not operational) |
| NSE Holidays | https://www.nseindia.com/market-data/holiday-calendar | Trading days (verified against NSE's holiday master API, 2026-10-18) |
| VIX Levels | https://www.nseindia.com/products/indices-vix.htm | Market regime assessment |
| Backtest Results | [docs/BACKTEST_COMBINED_MODE.md](../docs/BACKTEST_COMBINED_MODE.md) | Baseline expectations |

---

## ✅ Pre-Trading Checklist

- [ ] Pre-flight passed (RESTART section b)
- [x] Models accepted: weekly track only, risk engine OFF (owner decision 2026-10-19); monthly track not accepted
- [ ] Broker account funded (₹25L) and Fyers credentials present in `.env` or `.env.local`
- [ ] DAILY_CHECKLIST.md printed & on desk
- [ ] Understand entry window (11:00–13:00 IST) and exit rules (100% credit / short strike stop; PCS 75% target)
- [ ] Know the single pause rule (DD ≥ 15% of peak)

---

## 🆘 Help

**"Where do I start?"**
→ RESTART_2026-10-19.md

**"How do I log trades?"**
→ DAILY_OPERATIONS_GUIDE.md (entry and exit steps) and RESTART section (d)

**"Signal said SKIP. What do I log?"**
→ RESTART_2026-10-19.md section (c)

**"API call failed!"**
→ Expected: the API is not usable. Use the CLI (see RESTART section f).

**"End of month, what now?"**
→ Fill MONTHLY_ANALYSIS.md (month-end review template)

---

**Next step**: Read [RESTART_2026-10-19.md](./RESTART_2026-10-19.md), then print [DAILY_CHECKLIST.md](./DAILY_CHECKLIST.md).
