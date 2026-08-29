# Daily Workflow Summary — Quick Start Guide

**Ready to Use**: Yes ✅  
**Time Commitment**: 15 minutes/day  
**Start Date**: [Your trading date]

---

## 📋 Your Daily Trading Routine

### ⏰ 10:00 AM — PRE-MARKET CHECK (5 min)

```bash
# 1. Check server health
curl http://localhost:8000/health

# 2. Check account status
curl "http://localhost:8000/status?journal_id=phase1-sep-2026"

# 3. Get entry signal
curl http://localhost:8000/signal | jq '.weekly'
```

**Decision**: Should I enter today?
- ✅ `should_enter=true` AND `quality_score ≥ 0.50` AND capital available → **READY**
- ❌ Otherwise → **SKIP for today**

---

### 🚀 11:30 AM — ENTRY DECISION (5 min)

**If signal was YES**:

```bash
# 1. Verify signal still good at 11:30 AM
curl http://localhost:8000/signal | jq '.weekly'

# 2. Place order via Fyers app/web
#    (Manual broker action — log the fill time & price)

# 3. Log trade to API
curl -X POST http://localhost:8000/trades/open \
  -H "Content-Type: application/json" \
  -d '{
    "journal_id": "phase1-sep-2026",
    "trade_id": "PT-001",
    "strategy": "weekly_pcs",
    "entry_date": "2026-09-01",
    "expiry_date": "2026-09-04",
    "lots": 8,
    "capital_deployed": 520000,
    "ml_score": 0.62,
    "entry_time_ist": "11:42",
    "notes": "Entered, low VIX regime"
  }'
```

---

### 📊 12:30 PM — MID-SESSION CHECK (Optional, 2 min)

```bash
# Check if trade should be closed yet
curl "http://localhost:8000/monitor?journal_id=phase1-sep-2026" | jq '.recommendations[0].action'
```

**Decision**:
- `HOLD` → Keep position, check again at 1 PM
- `BOOK_PROFIT` → Close now (50% target hit)
- `EXIT_NOW` → Close now (risk high)

---

### 👁️ 3:00–4:30 PM — MONITORING (Check every 30 min)

```bash
# Get exit recommendation
curl "http://localhost:8000/monitor?journal_id=phase1-sep-2026" | jq '.recommendations[0]'
```

**Key Check**:
- Is `current_pnl_pct ≥ 50`? → **EXIT** (profit target hit)
- Is `risk_score ≥ 0.70`? → **EXIT** (risk too high)

**Close trade if needed**:

```bash
curl -X POST "http://localhost:8000/trades/PT-001/close?journal_id=phase1-sep-2026" \
  -H "Content-Type: application/json" \
  -d '{
    "exit_price_per_unit": 42.5,
    "exit_reason": "profit_target",
    "exit_time_ist": "14:05",
    "brokerage": 320,
    "notes": "Closed at 50% profit"
  }'
```

---

### 🏁 4:30 PM — END-OF-DAY LOGGING (5 min)

```bash
# 1. Get final account state
curl "http://localhost:8000/status?journal_id=phase1-sep-2026"

# 2. Log daily snapshot
curl -X POST http://localhost:8000/journal/daily-log \
  -H "Content-Type: application/json" \
  -d '{
    "journal_id": "phase1-sep-2026",
    "date": "2026-09-01",
    "account_equity": 1514300,
    "cumulative_pnl": 14300,
    "open_trades_count": 0,
    "vix_close": 17.3,
    "market_regime": "LOW_VOL",
    "win_rate_ytd_pct": 100.0,
    "account_dd_pct": 0.0,
    "notes": "First trade: +14.3K"
  }'

# 3. Verify CSVs updated
tail paper_trading/tracker/TRADES.csv
tail paper_trading/tracker/DAILY_LOG.csv
```

---

## 🎯 Key Rules (MUST FOLLOW)

✅ **Entry Window**: 11:00–13:00 IST (mid-session only)  
✅ **Quality Score**: ≥ 0.50 (no exceptions)  
✅ **Profit Target**: 50% max profit → **EXIT immediately**  
✅ **Stop Loss**: 2× credit amount → **EXIT immediately**  
✅ **Max Hold**: 3 trading days (exit by EOD day 3)  
✅ **Expiry Day**: Close by 3:15 PM (0 DTE)  
✅ **Account DD**: > 15% → **STOP ALL TRADING**  

---

## 🔄 Missed Logging? (Catch-up Next Morning)

**Before opening new position**, catch up:

```bash
# If trade closed but not logged:
curl -X POST "http://localhost:8000/trades/PT-001/close?journal_id=phase1-sep-2026" \
  -d '{"exit_time_ist":"14:05","exit_price_per_unit":42.5,...}'

# If daily log not recorded:
curl -X POST http://localhost:8000/journal/daily-log \
  -d '{"date":"2026-09-01","account_equity":1514300,...}'
```

Always log **oldest → newest** if multiple days behind.

---

## 📂 Files You'll Use Daily

| File | Purpose | Update When |
|------|---------|-------------|
| `DAILY_CHECKLIST.md` | Print & tape to monitor | Daily reference |
| `DAILY_OPERATIONS_GUIDE.md` | Step-by-step detailed guide | Detailed questions |
| `TRADES.csv` | Master trade log | After opening/closing |
| `DAILY_LOG.csv` | Daily account snapshot | 4:30 PM daily |
| `RISK_DASHBOARD.md` | Real-time risk status | Weekly (Friday) |
| `MONTHLY_ANALYSIS.md` | Month-end review | Month-end |

---

## 🚀 Getting Started

### Day 1: Setup

1. Start API server:
   ```bash
   uvicorn api.server:app --port 8000
   ```

2. Create journal session:
   ```bash
   curl -X POST http://localhost:8000/journals \
     -H "Content-Type: application/json" \
     -d '{
       "journal_id": "phase1-sep-2026",
       "label": "Phase 1 Weekly Validation Sep 2026",
       "initial_capital": 1500000,
       "strategy_track": "weekly"
     }'
   ```

3. Verify setup:
   ```bash
   curl http://localhost:8000/health
   curl "http://localhost:8000/status?journal_id=phase1-sep-2026"
   ```

### Day 2+: Normal Routine

Follow the 4-phase workflow above (10 AM → 11:30 AM → 3 PM → 4:30 PM).

---

## ✅ Checklist: Ready to Trade?

- [ ] API server running on port 8000
- [ ] `GET /health` returns healthy status
- [ ] Journal session created
- [ ] `GET /status` shows correct initial capital
- [ ] `GET /signal` returns valid entry signal
- [ ] `DAILY_CHECKLIST.md` printed & on desk
- [ ] Fyers account funded & API working
- [ ] Mobile/browser ready for manual order placement
- [ ] 4 daily reminders set (10 AM, 11:30 AM, 3 PM, 4:30 PM)
- [ ] Ready to trade! 🚀

---

## 📞 Support

**Server won't start?**
```bash
# Check if port 8000 in use
lsof -i :8000
# Kill existing: kill -9 <PID>
# Restart: uvicorn api.server:app --port 8000
```

**Signal stale?**
```bash
# Refresh market data (wait 30s)
curl -X POST http://localhost:8000/market/refresh
```

**Detailed questions?**
- See `DAILY_OPERATIONS_GUIDE.md` for full step-by-step
- See `API_GUIDE.md` for endpoint details
- See `QUICK_REFERENCE.md` for trading rules

---

## 🎓 Expected Outcomes (Phase 1, 6 months)

- 6–8 total trades
- ≥ 75% win rate
- ₹90–120k total P&L
- < 12% account DD
- Backtest vs live variance < 30%

If achieved → **Phase 2 approved** (add monthly trading)

---

**You're ready! Start with the morning checklist tomorrow at 10:00 AM IST.** ✅
