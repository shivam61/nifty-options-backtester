# Daily Trading Checklist — Quick Reference Card

**Print this page and keep it on your desk during trading hours.**

---

## ⏰ MORNING: 10:00–10:55 AM IST

### 1️⃣ Server Health (30 sec)
```bash
curl http://localhost:8000/health
# Expect: {"status":"healthy","market_data_loaded":true}
```
- ✅ = Ready
- ❌ = Restart server or call POST /market/refresh

### 2️⃣ Account Status (1 min)
```bash
curl "http://localhost:8000/status?journal_id=phase1-sep-2026"
```

**Check**:
- [ ] Account equity > initial capital? → Profit tracking ✓
- [ ] Account DD < 5%? → Risk OK ✓ (Yellow if 5–10%, Red stop if > 15%)
- [ ] Open trades = 0? → Ready for new entry ✓
- [ ] Note VIX + Regime for entry decision

### 3️⃣ Get Entry Signal (1 min)
```bash
curl http://localhost:8000/signal | jq '.weekly'
```

**Key Checks**:
| Field | OK If |
|-------|-------|
| `should_enter` | true |
| `quality_score` | ≥ 0.50 |
| `suggested_lots` | > 0 |
| `capital_to_deploy` | < available_capital |

### 4️⃣ Decision
```
should_enter=false?  → SKIP (wait for next signal)
quality_score<0.50?  → CAUTION (consider skipping)
capital issue?       → SKIP (wait for margin)
All OK?              → ✅ READY TO ENTER AT 11:30 AM
```

**Print Entry Checklist** (tape to monitor):
```
☐ VIX regime still OK?
☐ Signal still true (11:30 AM)?
☐ Capital available?
☐ No other open trades?
☐ Fyers API live?
☐ Time: 11:00–13:00 IST?
☐ DTE: 3–8 days?
→ ENTER?
```

---

## 🚀 MID-SESSION: 11:30 AM–1:00 PM IST

### 1️⃣ Re-Verify Signal (30 sec at 11:30 AM)
```bash
curl http://localhost:8000/signal | jq '.weekly'
```
- Signal changed? → **SKIP entry** (log reason in notes)
- Signal OK? → **PROCEED**

### 2️⃣ Place Order (3–5 min)
**Via Fyers app/web**:
1. Open Nifty options (NSE)
2. Select expiry (from DTE window)
3. Place IOC order
4. **Record**:
   - Entry time (HH:MM IST)
   - Entry price (₹)
   - Bid-ask spread

### 3️⃣ Log Trade to API (30 sec)
```bash
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
    "notes": "Entered at 11:42, quality 0.62"
  }'
```

**Verify**: Response says `"success":true`

---

## 📊 MID-AFTERNOON: 12:30 PM CHECKPOINT (Optional)

### Check Exit Recommendation
```bash
curl "http://localhost:8000/monitor?journal_id=phase1-sep-2026" | jq '.recommendations[0]'
```

**Decision**:
| `action` | Do What |
|----------|---------|
| HOLD | Keep holding, check at 1 PM |
| BOOK_PROFIT | **EXIT now** (hit 50% target) |
| EXIT_NOW | **EXIT now** (risk too high) |
| TRAIL_STOP | Adjust stop higher, keep open |

---

## 👁️ AFTERNOON: 3:00–4:30 PM IST (Check every 30 min)

### Get Exit Recommendation
```bash
curl "http://localhost:8000/monitor?journal_id=phase1-sep-2026" | jq '.recommendations[0]'
```

**Key metrics**:
| Metric | Action |
|--------|--------|
| `current_pnl_pct >= 50` | **EXIT** ← Golden rule |
| `risk_score >= 0.70` | **EXIT** ← Tail risk |
| `dte_remaining == 0` | **EXIT** ← Expiry day (by 3:15 PM) |

### Close Position (if needed)
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

**Exit Reasons**:
- `profit_target` ← 50% max profit hit (standard)
- `stop_loss` ← 2× credit stop triggered
- `dte_expired` ← Day 0 expiry (must close by 3:15 PM)
- `time_based` ← 3-day hold max
- `manual` ← Judgment call

---

## 📝 END-OF-DAY: 4:30 PM IST

### 1️⃣ Final Status (1 min)
```bash
curl "http://localhost:8000/status?journal_id=phase1-sep-2026" | jq '.'
```

**Copy**: Account equity, cumulative P&L, VIX, regime

### 2️⃣ Log Daily Snapshot (1 min)
```bash
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
    "avg_trade_pnl_ytd": 14300,
    "account_dd_pct": 0.0,
    "notes": "First trade: +14.3K"
  }'
```

### 3️⃣ Verify CSV (1 min)
```bash
# Check TRADES.csv
tail paper_trading/tracker/TRADES.csv

# Check DAILY_LOG.csv
tail paper_trading/tracker/DAILY_LOG.csv
```

### 4️⃣ End-of-Day Checklist
```
☐ All positions closed (open_trades = 0)?
☐ TRADES.csv has exit row (if trade closed)?
☐ DAILY_LOG.csv has daily row?
☐ Account DD < 15%? (STOP if > 15%)
☐ Notes logged?
☐ Tomorrow prep: Ready for new signal?
✓ DONE for the day
```

---

## 🔄 CATCH-UP (If You Missed Logging)

**Next morning (before new entry signal)**:

### Trade Close Not Logged?
```bash
# Get exit time from Fyers history
# Then log retroactively:
curl -X POST "http://localhost:8000/trades/PT-001/close?journal_id=phase1-sep-2026" \
  -d '{"exit_price_per_unit":42.5,"exit_time_ist":"14:05",...}'
```

### Daily Log Not Recorded?
```bash
# Get data from GET /status (yesterday's equity)
# Then log with yesterday's date:
curl -X POST http://localhost:8000/journal/daily-log \
  -d '{"journal_id":"phase1-sep-2026","date":"2026-09-01",...}'
```

**Always log oldest → newest if catching up 2+ days.**

---

## 🚨 HARD STOPS (IMMEDIATE ACTION)

| Trigger | Action |
|---------|--------|
| **Account DD > 15%** | CLOSE ALL POSITIONS. STOP TRADING. |
| **Single loss > ₹75k** | EXIT immediately. Reduce size 50% next trade. |
| **3 consecutive losses** | PAUSE. Review signal quality. |
| **API down > 1 hour** | CLOSE all positions via Fyers web. |
| **Win rate < 60% over 10 trades** | PAUSE. Investigate. |

---

## 📊 WEEKLY REVIEW (Friday 4:00 PM)

```bash
curl "http://localhost:8000/journals/phase1-sep-2026" | jq '.'
```

**Fill in RISK_DASHBOARD.md**:
- [ ] Trades this week: ___
- [ ] Win rate: ___%
- [ ] Total P&L: ₹_____
- [ ] Account DD: ___%
- [ ] Any API issues? Yes / No
- [ ] Next week decision: [ ] Continue [ ] Pause [ ] Adjust

---

## 📈 MONTHLY REVIEW (Month-End)

**30 days after start:**

```bash
curl "http://localhost:8000/journals/phase1-sep-2026"
```

**Fill MONTHLY_ANALYSIS.md**:
- Trades: ____ (target 6–8)
- Win rate: ___% (target ≥ 75%)
- Total P&L: ₹_____ (target ₹90–120k)
- Account DD: __% (target < 12%)

**Decision**:
- ✅ GO: Continue Phase 1 (6-month validation)
- ⚠️ HOLD: Collect more data
- ❌ STOP: Investigate backtest vs live gap

---

## 🎯 ENTRY RULES (GOLDEN)

✓ Must be 11:00–13:00 IST (mid-session window)  
✓ Quality score ≥ 0.50  
✓ Sufficient capital available  
✓ Max 1–2 concurrent trades (Phase 1)  
✓ Expiry 3–8 DTE away  

---

## 🎯 EXIT RULES (GOLDEN)

✓ **50% max profit** → EXIT immediately (MUST follow)  
✓ **2× credit stop loss** → EXIT immediately (MUST follow)  
✓ **DTE = 0 (expiry day)** → EXIT by 3:15 PM (MUST follow)  
✓ **Max 3 trading days** → EXIT by EOD day 3 (MUST follow)  
✓ **Risk score ≥ 0.70** → Manual judgment, consider EXIT  

---

## 📞 HELP

**Server won't start?**
```bash
# Restart
uvicorn api.server:app --port 8000
# Or check if port 8000 in use: lsof -i :8000
```

**Signal stale?**
```bash
# Refresh market data (wait 30s)
curl -X POST http://localhost:8000/market/refresh
```

**Trade not logging?**
```bash
# Re-call POST /trades/open (idempotent)
# Check response for "success":true
```

**TRADES.csv missing row?**
```bash
# Verify journal_id matches
curl "http://localhost:8000/trades?journal_id=phase1-sep-2026"
```

See [DAILY_OPERATIONS_GUIDE.md](./DAILY_OPERATIONS_GUIDE.md) for detailed troubleshooting.

---

## 🕐 TIME SUMMARY

| Time | Action | Duration |
|------|--------|----------|
| **10:00 AM** | Pre-market check + signal review | 5 min |
| **11:30 AM** | Entry decision + log trade | 5 min |
| **12:30 PM** | (Optional) Re-check exit recommendation | 2 min |
| **3:00–4:30 PM** | Monitor + exit (every 30 min) | 5 min |
| **4:30 PM** | End-of-day logging | 5 min |
| **TOTAL/DAY** | | ~15 min |

---

**Laminate this page. Keep on desk. Reference daily. Update routines as needed.**

**Ready to trade!** 🚀
