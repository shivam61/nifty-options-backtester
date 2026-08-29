# Daily Operations Guide — Paper Trading Journal

**Purpose**: Step-by-step checklist for managing trades every trading day  
**Frequency**: Daily (Mon–Fri, 10:00 AM–4:30 PM IST)  
**Time commitment**: ~15 min/day (5 min entry, 5 min mid-session, 5 min close)  
**Journal ID**: `phase1-sep-2026` (example; replace with your session)

---

## Overview: Three Daily Touchpoints

| Time | Task | Duration | API Calls |
|------|------|----------|-----------|
| **10:00–10:55 AM IST** | Pre-market checklist | 5 min | `GET /health`, `GET /status`, `GET /signal` |
| **11:30 AM–1:00 PM IST** | Mid-session entry decision | 5 min | `POST /trades/open` (if signal + capital + entry window OK) |
| **3:00–4:30 PM IST** | Monitoring & exit decisions | 5 min | `GET /monitor`, `POST /trades/{id}/close` (if target/stop hit) |
| **4:30 PM IST** | End-of-day logging | 5 min | `POST /journal/daily-log`, review TRADES.csv |

---

# MORNING: PRE-MARKET CHECKLIST (10:00–10:55 AM)

**Goal**: Verify systems are ready + get entry signal for today  
**Output**: Decision: YES (open position if signal ≥ 0.50) or NO (wait)

## Step 1: Server Health Check (1 min)

```bash
# Check API is running
curl http://localhost:8000/health
```

**Expected**: 
```json
{"status":"healthy","market_data_loaded":true,"models_loaded":true}
```

**If not healthy**:
- Server crashed overnight → Restart: `uvicorn api.server:app --port 8000`
- Market data stale → Call: `curl -X POST http://localhost:8000/market/refresh`
- Wait 30 sec, retry

## Step 2: Account Status Snapshot (2 min)

```bash
# Get current account state
curl "http://localhost:8000/status?journal_id=phase1-sep-2026"
```

**Check these fields**:
| Field | Check | Action If Issue |
|-------|-------|-----------------|
| `account_equity` | > initial capital? | Good, profit growing |
| `cumulative_pnl` | Positive trend? | Assess 5-day win rate |
| `account_dd_pct` | < 5%? | Yellow if 5–10%; Red stop if > 15% |
| `open_trades` | = 0 (before entry)? | Close lingering trades first |
| `vix_now` | Note regime | Impacts position sizing below |
| `regime` | LOW_VOL / NORMAL / ELEVATED? | Entry aggressiveness |

**Copy to DAILY_LOG.csv row** (via API later):
- Account equity
- VIX close (from status)
- Current regime

## Step 3: Get Today's Entry Signal (2 min)

```bash
# Fetch ML signal + entry recommendation
curl http://localhost:8000/signal | jq '.weekly'
```

**Review in detail**:
```json
{
  "should_enter": true/false,
  "quality_score": 0.XX,        ← Is it ≥ 0.50?
  "signal": "STRONG_ENTRY",     ← Not "AVOID"?
  "suggested_lots": 8,          ← Enough capital for margin?
  "capital_to_deploy": 520000,  ← Available capital > this?
  "dte_window": "3–8",          ← Expiry range (check NSE calendar)
  "within_entry_window": true   ← Is it 11:00–13:00 IST? (mandatory)
}
```

**Decision Tree**:

```
┌─ should_enter == false?
│  └─ STOP. Wait for next signal (next day or later today if reopens)
│
├─ should_enter == true?
│  ├─ quality_score < 0.50?
│  │  └─ CAUTION. ML confidence low. May skip or 25% smaller size.
│  │
│  ├─ quality_score >= 0.50?
│  │  ├─ suggested_lots > 0?
│  │  │  ├─ capital_to_deploy < available_capital?
│  │  │  │  └─ ✓ READY TO OPEN TRADE (enter during 11:00–13:00 IST window)
│  │  │  │
│  │  │  └─ capital_to_deploy >= available_capital?
│  │  │     └─ ✗ SKIP. Insufficient margin. Wait for capital to free up.
│  │  │
│  │  └─ suggested_lots == 0?
│  │     └─ ✗ SKIP. Position sizing blocked (DD too high or VIX extreme).
│  │
│  └─ within_entry_window == false?
│     └─ Reminder: Entry window opens at 11:00 AM IST.
│        Call this endpoint again at 11:30 AM to confirm window is open.
```

## Step 4: Prepare Entry Checklist (2 min)

If `should_enter=true` and capital is sufficient:

**Print this checklist to your monitor or phone**:

```
=== ENTRY CHECKLIST (11:00–13:00 IST) ===
Before placing order:

☐ VIX check — Is regime still LOW_VOL/NORMAL? (re-check at 11:30)
☐ ML signal — Is quality_score still ≥ 0.50?
☐ Capital check — Is available_capital > suggested_capital_to_deploy?
☐ Open positions — Are we at 0 other trades? (max 1–2 concurrent for Phase 1)
☐ Fyers API — Is connection live? (dummy test order if unsure)
☐ Entry time — Is it 11:00–13:00 IST window?
☐ DTE filter — Is expiry 3–8 days away?
☐ READY? ✓ → Proceed to entry at 11:30 AM.
```

---

# MID-SESSION: ENTRY DECISION & EXECUTION (11:30 AM–1:00 PM IST)

**Goal**: Verify signal still valid, enter position if all checks pass, log trade  
**Duration**: 5–10 min (or SKIP if conditions changed)

## Step 1: Re-Verify Entry Signal (1 min)

**At 11:30 AM**, re-check signal to confirm it hasn't changed:

```bash
curl http://localhost:8000/signal | jq '.weekly'
```

**Check**:
- `should_enter` still true?
- `quality_score` still ≥ 0.50?
- `within_entry_window` now true (11:30 is in window)?

**If signal changed to AVOID or score < 0.50**:
- Skip entry for today
- Log in TRADES.csv notes: "Signal changed 11:30 AM, did not enter"
- Try again next trading day

---

## Step 2: Place Order via Fyers Broker (3–5 min)

This is **manual** (API doesn't place orders yet; Phase 2 will add this).

**Via Fyers app or web**:
1. Open Nifty options chain (NSE)
2. Select expiry from `dte_window` (e.g., 5 DTE)
3. Enter legs based on strategy (`PUT_CREDIT_SPREAD` suggested by API)
4. Place IOC order (Immediate Or Cancel)
5. Note fill prices

**Record these**:
- Entry time (HH:MM IST)
- Entry price per unit (rupees)
- Bid-ask spread (for slippage measurement)

---

## Step 3: Log Trade to API (1 min)

Immediately after order fills:

```bash
curl -X POST http://localhost:8000/trades/open \
  -H "Content-Type: application/json" \
  -d '{
    "journal_id": "phase1-sep-2026",
    "trade_id": "PT-001",
    "strategy": "weekly_pcs",
    "entry_date": "2026-09-01",
    "expiry_date": "2026-09-04",
    "legs_str": "SELL 24800 PE 85 @ 520; BUY 24600 PE 40 @ 520",
    "lots": 8,
    "capital_deployed": 520000,
    "ml_score": 0.62,
    "entry_time_ist": "11:42",
    "vix": 17.3,
    "regime": "LOW_VOL",
    "strike": 24800,
    "notes": "Entered during low VIX, quality score 0.62"
  }'
```

**Key fields to extract from Fyers**:
- `entry_time_ist`: When order filled (HH:MM IST)
- `entry_date`: Today (YYYY-MM-DD)
- `expiry_date`: Option expiry date (YYYY-MM-DD)
- `lots`: Number of 65-lot units deployed
- `capital_deployed`: Margin posted (₹)
- `strike`: Strike price of primary leg
- `legs_str`: Human-readable leg description

**Expected response**:
```json
{"success":true,"trade_id":"PT-001","message":"Trade PT-001 opened"}
```

---

## Step 4: Verify TRADES.csv was Updated (1 min)

Open `paper_trading/tracker/TRADES.csv` (in Excel or terminal):

```bash
tail -2 paper_trading/tracker/TRADES.csv
```

**Should see your new row** with:
- Trade_ID: PT-001
- Journal_ID: phase1-sep-2026
- Date_Entry: 2026-09-01
- Entry_Price_Fill: 85.0
- Lots_Size: 8
- Exit fields empty (will fill at close)

---

# AFTERNOON: MONITORING & EXIT DECISIONS (3:00–4:30 PM IST)

**Goal**: Monitor open position + decide when to exit (profit target or stop loss)  
**Check frequency**: Every 30 min during market hours

## Step 1: Get Exit Recommendation (2 min)

Every 30 min during 3:00–4:30 PM (or more frequently if nervous):

```bash
curl "http://localhost:8000/monitor?journal_id=phase1-sep-2026"
```

**Expected response**:
```json
{
  "count": 1,
  "recommendations": [
    {
      "trade_id": "PT-001",
      "action": "HOLD",           ← Action to take
      "confidence": 0.72,         ← Certainty (60–95%)
      "current_pnl_pct": 48.2,    ← % of max profit captured
      "pnl_rupees": 14300,        ← Unrealized P&L (₹)
      "days_in_trade": 0,
      "dte_remaining": 5,
      "risk_score": 0.21,         ← Tail loss risk (0–1)
      "reasoning": [
        "48% of max profit captured",
        "Risk score 0.21 — low risk",
        "DTE 5 — time to hold"
      ]
    }
  ]
}
```

## Step 2: Exit Decision Tree

**Based on `action` recommendation**:

### If `action == "HOLD"`:
- Continue monitoring every 30 min
- Do NOT exit yet
- Log in notes: "Holding, 48% captured, risk low"

### If `action == "BOOK_PROFIT"` OR `current_pnl_pct >= 50`:
- **EXIT IMMEDIATELY**
- This is your 50% profit target (key rule)
- Close all legs in Fyers

### If `action == "EXIT_NOW"` OR `risk_score >= 0.70`:
- **EXIT IMMEDIATELY**
- Risk is too high; don't wait
- Close all legs in Fyers

### If `action == "TRAIL_STOP"`:
- Adjust stop-loss **higher** (follow profit up)
- Don't close yet; lock in gains while staying long

### If `action == "PARTIAL_EXIT"`:
- Close 50% of position to lock profits
- Let remaining 50% run for larger upside
- Update TRADES.csv with partial exit fields

---

## Step 3: Close Trade (if action = EXIT)

**Via Fyers**:
1. Close all legs of the trade
2. Note exit price + exit time

**Log to API**:

```bash
curl -X POST "http://localhost:8000/trades/PT-001/close?journal_id=phase1-sep-2026" \
  -H "Content-Type: application/json" \
  -d '{
    "exit_price_per_unit": 42.5,
    "exit_reason": "profit_target",
    "exit_time_ist": "14:05",
    "brokerage": 320,
    "notes": "Closed at 50% profit target, P&L +14.3K"
  }'
```

**Exit reasons**:
- `profit_target` — Hit 50% max profit ✓ (standard)
- `stop_loss` — Hit 2× credit stop loss (loss limit)
- `dte_expired` — Expiry day reached (0 DTE)
- `time_based` — Held 3 trading days max
- `manual` — Tail event or judgment call

**Expected response**:
```json
{"success":true,"trade_id":"PT-001","message":"Trade PT-001 closed"}
```

---

## Step 4: Verify TRADES.csv Exit Fields (1 min)

```bash
tail -2 paper_trading/tracker/TRADES.csv
```

**Should now have**:
- Date_Exit: 2026-09-02
- Exit_Time_IST: 14:05
- Exit_Price_Fill: 42.5
- Exit_Reason: profit_target
- Gross_P&L_₹: 14300
- Net_P&L_₹: 13980 (after brokerage)
- Win_Loss: W (or L if loss)

---

# END-OF-DAY: LOGGING & WRAP-UP (4:30 PM IST)

**Goal**: Record daily account state + prepare for next day  
**Duration**: 5 min

## Step 1: Final Account Snapshot (2 min)

```bash
curl "http://localhost:8000/status?journal_id=phase1-sep-2026"
```

**Record**:
- `account_equity`: Updated value
- `cumulative_pnl`: Total profit to date
- `open_trades`: Should be 0 at close
- `win_rate_pct`: Updated if trade closed
- `vix_now`: Final VIX of day
- `account_dd_pct`: Current drawdown

## Step 2: Log Daily Snapshot (2 min)

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
    "notes": "First trade: +14.3K profit on weekly PCS. Quality entry, hit 50% target."
  }'
```

## Step 3: Review DAILY_LOG.csv (1 min)

```bash
tail -2 paper_trading/tracker/DAILY_LOG.csv
```

**Should show**:
- Date: 2026-09-01
- Journal_ID: phase1-sep-2026
- Account_Equity_₹: 1514300
- Cumulative_P&L_₹: 14300
- Open_Trades_Count: 0
- VIX_Close: 17.3
- Market_Regime: LOW_VOL

## Step 4: End-of-Day Checklist (1 min)

```
=== END-OF-DAY CHECKLIST ===
☐ All open positions closed? (None = 0)
☐ TRADES.csv updated with exit? (if trade closed)
☐ DAILY_LOG.csv updated with snapshot? (via API)
☐ Account DD checked? (< 15% = OK)
☐ Next day prep: Review morning checklist for tomorrow
☐ Notes logged: Any market observations? (log in DAILY_LOG notes)
☐ Ready for tomorrow ✓
```

---

# HANDLING MISSED LOGGING (CATCH-UP)

**If you don't log at 4:30 PM IST**, you can catch up the **next morning before 11:00 AM**.

## Scenario 1: Trade Closed Overnight But Not Logged

**Morning (before entry for new trade)**:

```bash
# Check if trade still in active_trades.json
curl "http://localhost:8000/trades?journal_id=phase1-sep-2026&status=open"

# If PT-001 still shows as open but it's actually closed:
# Get exit details from Fyers history
```

**Then log the close retroactively**:

```bash
curl -X POST "http://localhost:8000/trades/PT-001/close?journal_id=phase1-sep-2026" \
  -H "Content-Type: application/json" \
  -d '{
    "exit_price_per_unit": 42.5,
    "exit_reason": "profit_target",
    "exit_time_ist": "14:05",      ← Actual exit time from yesterday
    "brokerage": 320,
    "notes": "Logged retroactively on 2026-09-02 morning"
  }'
```

## Scenario 2: Missed Yesterday's Daily Log

**Tomorrow morning** (before new entry decision):

```bash
# Check yesterday's status
curl "http://localhost:8000/status?journal_id=phase1-sep-2026"

# Reconstruct yesterday's snapshot:
# - Equity = initial + cumulative P&L
# - VIX = from NSE website or previous day close
# - Regime = infer from VIX

# Log retroactively with yesterday's date:
curl -X POST http://localhost:8000/journal/daily-log \
  -H "Content-Type: application/json" \
  -d '{
    "journal_id": "phase1-sep-2026",
    "date": "2026-09-01",          ← Yesterday
    "account_equity": 1514300,
    "cumulative_pnl": 14300,
    "open_trades_count": 0,
    "vix_close": 17.3,
    "market_regime": "LOW_VOL",
    "notes": "Logged retroactively on 2026-09-02 morning"
  }'
```

## Scenario 3: Multiple Days Missed

**Approach**: Log from oldest to newest, once per day:

```bash
# Day 1 (Sept 1)
curl -X POST http://localhost:8000/journal/daily-log -d '{"date":"2026-09-01",...}'

# Day 2 (Sept 2)
curl -X POST http://localhost:8000/journal/daily-log -d '{"date":"2026-09-02",...}'

# Day 3 (Sept 3) — today
curl -X POST http://localhost:8000/journal/daily-log -d '{"date":"2026-09-03",...}'
```

**To get missing data**:
- Account equity: `GET /status` (shows cumulative_pnl, compute equity = initial + pnl)
- VIX close: Check NSE website or financial data provider
- Trade count: Check TRADES.csv (count rows with Date_Exit = null for that day)
- Win rate: Calculate from TRADES.csv closed trades

---

# MANAGING PREVIOUS DAY'S SUGGESTION AT 12:30 PM

**Key Insight**: The 11:30 AM exit recommendation is for **active positions only**. At 12:30 PM, you **re-evaluate the suggestion** to decide if it still applies.

## Workflow: 12:30 PM Checkpoint

**If trade still open** (from 11:30 AM entry):

```bash
# Re-check exit recommendation at 12:30 PM
curl "http://localhost:8000/monitor?journal_id=phase1-sep-2026" | jq '.recommendations[0].action'
```

**Decision table**:

| 11:30 AM Suggestion | Current State (12:30 PM) | Action |
|---------------------|--------------------------|--------|
| HOLD | Still HOLD (P&L < 50%) | Continue holding, re-check at 1:00 PM |
| HOLD | Now BOOK_PROFIT (P&L ≥ 50%) | EXIT immediately |
| BOOK_PROFIT | Already exited | ✓ Completed (log if not done) |
| EXIT_NOW | Already exited | ✓ Completed (log if not done) |
| HOLD | Now EXIT_NOW (risk spike) | EXIT immediately |

---

## Example Timeline

### Scenario: Low VIX Morning, Enter at 11:42 AM

```
10:00 AM: Check status + signal → should_enter=true, quality=0.62 ✓

11:30 AM: Re-verify signal → Still true, within_entry_window=true ✓
          Place order via Fyers → Filled at ₹85 credit
          Log: POST /trades/open

11:45 AM: Position now open, unrealized P&L = +₹5,000

12:30 PM: CHECK EXIT RECOMMENDATION
          curl /monitor → action="HOLD", pnl_pct=35%, risk_score=0.15 ✓
          Decision: KEEP HOLDING. Not at 50% yet. Risk is low.
          Log notes: "12:30 check: holding, 35% profit, risk low"

1:30 PM: RE-CHECK (optional, if anxious)
          curl /monitor → action="BOOK_PROFIT", pnl_pct=51%, risk_score=0.25 ✓
          Decision: EXIT. Hit 50% target.
          Close order via Fyers → Filled at ₹42.50
          Log: POST /trades/{id}/close

4:30 PM: End-of-day logging
          Log daily snapshot → cumulative_pnl updated
          Verify TRADES.csv + DAILY_LOG.csv
```

---

# QUICK REFERENCE: DAILY COMMAND CHEAT SHEET

## Pre-Market (10:00–10:55 AM)

```bash
# Health check
curl http://localhost:8000/health

# Status
curl "http://localhost:8000/status?journal_id=phase1-sep-2026" | jq '.'

# Signal
curl http://localhost:8000/signal | jq '.weekly'
```

## Entry (11:30–1:00 PM)

```bash
# Log new trade
curl -X POST http://localhost:8000/trades/open \
  -H "Content-Type: application/json" \
  -d '{"journal_id":"phase1-sep-2026",...}'
```

## Monitoring (3:00–4:30 PM, every 30 min)

```bash
# Exit recommendation
curl "http://localhost:8000/monitor?journal_id=phase1-sep-2026" | jq '.recommendations[0]'

# Close trade
curl -X POST "http://localhost:8000/trades/PT-001/close?journal_id=phase1-sep-2026" \
  -H "Content-Type: application/json" \
  -d '{"exit_price_per_unit":42.5,...}'
```

## End-of-Day (4:30 PM)

```bash
# Status
curl "http://localhost:8000/status?journal_id=phase1-sep-2026" | jq '.'

# Daily log
curl -X POST http://localhost:8000/journal/daily-log \
  -H "Content-Type: application/json" \
  -d '{"journal_id":"phase1-sep-2026",...}'
```

---

# TROUBLESHOOTING: COMMON ISSUES

| Issue | Symptom | Fix |
|-------|---------|-----|
| **Server down** | "Connection refused" on curl | Restart: `uvicorn api.server:app --port 8000` |
| **Signal stale** | Yesterday's VIX in signal response | Call: `POST /market/refresh` (wait 30s) |
| **Trade not logged** | TRADES.csv still has empty row | Re-call: `POST /trades/open` with same trade_id |
| **Exit stuck as HOLD** | Position at 48% profit, want to exit | Manual override: Call `POST /trades/{id}/close` anyway |
| **Missed yesterday's log** | No DAILY_LOG row for yesterday | Log retroactively: Call with `"date": "2026-09-01"` |
| **Multiple open trades** | Opened 2 trades, only 1 showing | Check: `GET /trades?status=open` filters by journal_id |

---

# WEEKLY SUMMARY (Every Friday 4:00 PM)

After logging final trade Friday:

```bash
# Get week summary
curl "http://localhost:8000/journals/phase1-sep-2026" | jq '.'
```

**Record in RISK_DASHBOARD.md**:
- Trades taken this week: N
- Win rate: X%
- Total P&L: ₹Y
- Account DD: Z%
- Any API/Fyers issues?
- Decision: Continue? Adjust size? Pause?

---

# 30-DAY MONTHLY REVIEW (Month-End)

At end of month (or every 30 days):

```bash
# Get full session summary
curl "http://localhost:8000/journals/phase1-sep-2026"
```

**Copy all trades to MONTHLY_ANALYSIS.md**:
- Trade-by-trade review
- Win rate vs backtest (78% target)
- P&L vs backtest (₹29.5k avg target)
- Largest win/loss
- Missed signals
- Backtest vs live deviation

**Decision**:
- ✅ GO: Continue Phase 1 (6-month validation)
- ⚠️ HOLD: Collect more data (margin, win rate)
- ❌ STOP: Investigate backtest vs live gap

---

# BEST PRACTICES

✓ **Log immediately** — Don't delay trade logs; memory fades  
✓ **Check signal every 5 min** around 11:30 AM (entry window)  
✓ **Monitor every 30 min** from 3:00 PM onward (profit building)  
✓ **Never hold past 3:15 PM** on expiry day (0 DTE)  
✓ **Always exit at 50% profit target** — Lock gains, move on  
✓ **Never hold through stop loss** — 2× credit is hard cap  
✓ **Catch up next morning** if you miss EOD logging (do it before new signal)  
✓ **Review weekly** (Fridays) — Spot trends early  

---

**Ready to trade!** Use this guide daily. Once familiar, most days take 10–12 minutes.

---

**Questions?** See [API_GUIDE.md](../API_GUIDE.md) for endpoint details or [QUICK_REFERENCE.md](./QUICK_REFERENCE.md) for trading rules.
