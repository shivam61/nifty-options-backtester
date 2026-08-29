# Paper Trading REST API — Complete Usage Guide

**Status**: Ready for deployment  
**Version**: 1.0.0  
**Framework**: FastAPI + Uvicorn  
**Last Updated**: 2026-08-29

---

## Quick Start

### 1. Install Dependencies
```bash
# Using pip (in virtual environment)
pip install fastapi uvicorn pydantic

# Or manually via requirements.txt
pip install -r requirements-api.txt
```

### 2. Start Server
```bash
# Option 1: Direct Uvicorn
uvicorn api.server:app --host 0.0.0.0 --port 8000 --reload

# Option 2: Python script
python api/server.py

# Option 3: Background (nohup)
nohup python -m uvicorn api.server:app --host 0.0.0.0 --port 8000 \
  > logs/api_$(date +%Y%m%d_%H%M).log 2>&1 &
echo "Server started. PID=$!"
```

### 3. Verify Server
```bash
# Health check
curl http://localhost:8000/health

# Expected response:
# {"status":"healthy","market_data_loaded":true,"models_loaded":true,"timestamp":"..."}
```

---

## API Endpoints — Complete Reference

### A. Journal Session Management

#### 1. `POST /journals` — Create a Journal Session

**Purpose**: Initialize a new named trading session (e.g., "Phase1-Aug-2026", "Weekly-Run-1")

**Request**:
```bash
curl -X POST http://localhost:8000/journals \
  -H "Content-Type: application/json" \
  -d '{
    "journal_id": "phase1-sep-2026",
    "label": "Phase 1 Weekly Validation Sep 2026",
    "initial_capital": 1500000,
    "strategy_track": "weekly",
    "notes": "Phase 1 paper trading, weekly PCS/IC only"
  }'
```

**Response**:
```json
{
  "success": true,
  "journal_id": "phase1-sep-2026",
  "label": "Phase 1 Weekly Validation Sep 2026",
  "status": "active",
  "created_at": "2026-09-01T09:00:00"
}
```

**Parameters**:
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `journal_id` | string | Yes | Unique identifier (kebab-case recommended) |
| `label` | string | Yes | Human-readable title |
| `initial_capital` | number | Yes | Starting account balance (₹) |
| `strategy_track` | string | Yes | "weekly", "monthly", or "combined" |
| `notes` | string | No | Optional free-form notes |

---

#### 2. `GET /journals` — List All Sessions

**Purpose**: Get summary of all active journal sessions

**Request**:
```bash
curl http://localhost:8000/journals
```

**Response**:
```json
{
  "journals": [
    {
      "journal_id": "phase1-sep-2026",
      "label": "Phase 1 Weekly Validation Sep 2026",
      "status": "active",
      "created_at": "2026-09-01T09:00:00",
      "strategy_track": "weekly",
      "open_trades": 2,
      "closed_trades": 5,
      "total_pnl": 87500,
      "win_rate_pct": 80.0,
      "account_dd_pct": 3.2
    }
  ]
}
```

---

#### 3. `GET /journals/{journal_id}` — Get Session Details

**Purpose**: Full summary for one journal, including all trades and metrics

**Request**:
```bash
curl http://localhost:8000/journals/phase1-sep-2026
```

**Response**:
```json
{
  "journal_id": "phase1-sep-2026",
  "label": "Phase 1 Weekly Validation Sep 2026",
  "status": "active",
  "created_at": "2026-09-01T09:00:00",
  "initial_capital": 1500000,
  "strategy_track": "weekly",
  "open_trades": 2,
  "closed_trades": 5,
  "total_pnl": 87500,
  "win_rate_pct": 80.0,
  "account_dd_pct": 3.2,
  "trades": [
    {
      "Trade_ID": "PT-001",
      "Journal_ID": "phase1-sep-2026",
      "Date_Entry": "2026-09-01",
      "Entry_Price_Fill": "85",
      "Lots_Size": "8",
      "Net_P&L_₹": "14300",
      "Win_Loss": "W"
      // ... 20+ more columns from TRADES.csv
    }
  ]
}
```

---

#### 4. `PATCH /journals/{journal_id}` — Update Session

**Purpose**: Modify session metadata (label, notes, or close session)

**Request**:
```bash
curl -X PATCH http://localhost:8000/journals/phase1-sep-2026 \
  -H "Content-Type: application/json" \
  -d '{
    "label": "Phase 1 Weekly Sep 2026 (Updated)",
    "notes": "Added monthly support after validation",
    "status": "closed"
  }'
```

**Response**:
```json
{
  "success": true,
  "journal_id": "phase1-sep-2026",
  "label": "Phase 1 Weekly Sep 2026 (Updated)",
  "status": "closed"
}
```

---

### B. Account & Portfolio Endpoints

#### 5. `GET /status?journal_id=<id>` — Account Snapshot

**Purpose**: Real-time account equity, P&L, DD%, and trade count

**Request**:
```bash
# Global status (all journals)
curl http://localhost:8000/status

# Scoped to journal
curl "http://localhost:8000/status?journal_id=phase1-sep-2026"
```

**Response**:
```json
{
  "journal_id": "phase1-sep-2026",
  "label": "Phase 1 Weekly Validation Sep 2026",
  "account_equity": 1587500,
  "initial_capital": 1500000,
  "cumulative_pnl": 87500,
  "account_dd_pct": 3.2,
  "open_trades": 2,
  "closed_trades": 5,
  "win_rate_pct": 80.0,
  "available_capital": 1270000,
  "reserve_capital": 317500,
  "vix_now": 17.3,
  "spot_now": 25200,
  "regime": "LOW_VOL",
  "market_date": "2026-09-01",
  "backtest_baseline_cagr": 12.07,
  "backtest_baseline_win_rate": 78.0
}
```

| Field | Description |
|-------|-------------|
| `account_equity` | Current account value (initial + P&L) |
| `cumulative_pnl` | Total realized profit/loss across all trades |
| `account_dd_pct` | Peak-to-trough drawdown percentage |
| `available_capital` | 80% of equity available for new trades |
| `reserve_capital` | 20% safety cushion |
| `regime` | VIX-inferred regime: VERY_LOW_VOL, LOW_VOL, NORMAL, ELEVATED, HIGH, CRISIS |

---

#### 6. `GET /trades?journal_id=<id>&status=open|closed|all` — List Trades

**Purpose**: Get all trades (open/closed/both) with current P&L estimates

**Request**:
```bash
# All open trades (default)
curl http://localhost:8000/trades

# Scoped to journal + status
curl "http://localhost:8000/trades?journal_id=phase1-sep-2026&status=open"

# Get closed trades only
curl "http://localhost:8000/trades?journal_id=phase1-sep-2026&status=closed"
```

**Response**:
```json
{
  "count": 2,
  "trades": [
    {
      "trade_id": "PT-001",
      "journal_id": "phase1-sep-2026",
      "entry_date": "2026-08-15",
      "expiry_date": "2026-08-28",
      "strategy_code": "weekly_pcs",
      "legs": [
        {
          "action": "SELL",
          "strike": 24800.0,
          "option_type": "PE",
          "qty": 520,
          "entry_price": 85.0,
          "current_ltp": 42.0
        },
        {
          "action": "BUY",
          "strike": 24600.0,
          "option_type": "PE",
          "qty": 520,
          "entry_price": 40.0,
          "current_ltp": 18.0
        }
      ],
      "entry_credit_per_unit": 45.0,
      "days_in_trade": 3,
      "dte_remaining": 7,
      "estimated_pnl": 14300.0,
      "notes": "Low VIX entry, ML score 0.61"
    }
  ]
}
```

---

### C. Signal & Entry Guidance

#### 7. `GET /signal` — Entry Signals (Weekly + Monthly)

**Purpose**: Get ML-driven entry recommendations for both strategy tracks

**Request**:
```bash
curl http://localhost:8000/signal
```

**Response**:
```json
{
  "timestamp": "2026-09-01T11:30:00Z",
  "within_entry_window": true,
  "spot": 25200.0,
  "vix": 17.3,
  "regime": "LOW_VOL",
  "weekly": {
    "should_enter": true,
    "quality_score": 0.62,
    "signal": "STRONG_ENTRY",
    "recommended_strategy": "weekly_pcs",
    "suggested_lots": 8,
    "available_capital": 1200000,
    "capital_to_deploy": 500000,
    "dte_window": "3–8",
    "skip_reason": null,
    "eligible_strategies": ["put_credit_spread", "iron_condor"]
  },
  "monthly": {
    "should_enter": false,
    "quality_score": 0.44,
    "signal": "AVOID",
    "recommended_strategy": null,
    "suggested_lots": 0,
    "available_capital": 0,
    "capital_to_deploy": 0.0,
    "dte_window": null,
    "skip_reason": "monthly_paused_phase1",
    "eligible_strategies": []
  },
  "macro_context": ["VIX below 20-day SMA", "Crude stable", "FII flows neutral"],
  "reasoning": ["Low VIX regime activates", "ML score 0.62 exceeds 0.50 threshold", "Entry window 11:00–13:00 IST is OPEN"]
}
```

**Key Fields**:
| Field | Description |
|-------|-------------|
| `within_entry_window` | Is it 11:00–13:00 IST? (Required for order placement) |
| `quality_score` | ML prediction confidence (0–1) |
| `signal` | STRONG_ENTRY, MODERATE_ENTRY, CAUTION_ENTRY, AVOID |
| `suggested_lots` | Recommended position size (nifty lot units) |
| `capital_to_deploy` | Margin required (₹) |
| `skip_reason` | If `should_enter=false`, why (e.g., "quality_threshold", "monthly_paused_phase1") |

---

### D. Trade Lifecycle (Open, Monitor, Close)

#### 8. `POST /trades/open` — Record New Trade

**Purpose**: Log a newly entered trade into active_trades.json and TRADES.csv

**Request**:
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
    "notes": "Entered at 11:42 IST, low VIX setup"
  }'
```

**Response**:
```json
{
  "success": true,
  "trade_id": "PT-001",
  "journal_id": "phase1-sep-2026",
  "message": "Trade PT-001 opened"
}
```

**Parameters**:
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `journal_id` | string | Yes | Session to log this trade to |
| `trade_id` | string | Yes | Unique ID (e.g., "PT-001") |
| `strategy` | string | Yes | "weekly_pcs", "weekly_ic", "monthly_*" |
| `entry_date` | string | Yes | ISO date (YYYY-MM-DD) |
| `expiry_date` | string | Yes | Option expiry date (YYYY-MM-DD) |
| `legs_str` | string | Yes | Leg description for record |
| `lots` | integer | Yes | Nifty lot units (typically 1–10) |
| `capital_deployed` | number | Yes | Margin posted (₹) |
| `ml_score` | number | Yes | Model quality score (0–1) |
| `entry_time_ist` | string | Yes | Time entered (HH:MM IST) |
| `vix`, `regime`, `strike`, `notes` | various | No | Optional metadata |

---

#### 9. `GET /monitor?journal_id=<id>` — Exit Recommendations

**Purpose**: Real-time exit guidance for all open trades (HOLD/BOOK_PROFIT/EXIT_NOW/TRAIL_STOP)

**Request**:
```bash
# Monitor all open trades
curl http://localhost:8000/monitor

# Monitor trades in specific journal
curl "http://localhost:8000/monitor?journal_id=phase1-sep-2026"
```

**Response**:
```json
{
  "count": 2,
  "timestamp": "2026-09-01T14:30:00Z",
  "recommendations": [
    {
      "trade_id": "PT-001",
      "action": "HOLD",
      "confidence": 0.72,
      "current_pnl_pct": 48.2,
      "pnl_rupees": 14300.0,
      "days_in_trade": 3,
      "dte_remaining": 7,
      "risk_score": 0.21,
      "theta_per_day": 1820.0,
      "reasoning": [
        "48% of max profit captured",
        "Risk score 0.21 — low risk",
        "DTE 7 — time to hold",
        "Exit at 50% target or 2× stop"
      ],
      "per_leg_pnl": [
        {
          "leg": "SELL 24800 PE",
          "entry": 85.0,
          "current_bs": 42.0,
          "pnl": 22360.0,
          "qty": 520
        },
        {
          "leg": "BUY 24600 PE",
          "entry": 40.0,
          "current_bs": 18.0,
          "pnl": -11440.0,
          "qty": 520
        }
      ],
      "partial_exit_legs": null
    }
  ]
}
```

**Action Meanings**:
| Action | When | Typical Confidence |
|--------|------|-------------------|
| `HOLD` | P&L < 50% max profit; risk score low | 60–80% |
| `BOOK_PROFIT` | P&L >= 50% max profit or high risk | 80%+ |
| `EXIT_NOW` | Stop loss triggered or tail risk | 95%+ |
| `TRAIL_STOP` | Volatility spike; adjust stop higher | 70%+ |
| `PARTIAL_EXIT` | Cover half the position; reduce risk | 65%+ |

---

#### 10. `POST /trades/{trade_id}/close?journal_id=<id>` — Close Trade

**Purpose**: Mark trade as closed with exit details; updates TRADES.csv and closed_trades.json

**Request**:
```bash
curl -X POST "http://localhost:8000/trades/PT-001/close?journal_id=phase1-sep-2026" \
  -H "Content-Type: application/json" \
  -d '{
    "exit_price_per_unit": 42.5,
    "exit_reason": "profit_target",
    "exit_time_ist": "12:05",
    "brokerage": 320,
    "notes": "Closed at 50% profit target"
  }'
```

**Response**:
```json
{
  "success": true,
  "trade_id": "PT-001",
  "journal_id": "phase1-sep-2026",
  "message": "Trade PT-001 closed"
}
```

**Exit Reasons**:
- `profit_target` — Hit 50% max profit
- `stop_loss` — Hit 2× credit stop loss
- `dte_expired` — Expiry day reached (0 DTE)
- `time_based` — 3-day max holding period reached
- `manual` — Manual exit (tail event, slippage, etc.)

---

### E. Daily Logging

#### 11. `POST /journal/daily-log` — Log Daily Snapshot

**Purpose**: Record end-of-day account status for trend analysis and monthly review

**Request**:
```bash
curl -X POST http://localhost:8000/journal/daily-log \
  -H "Content-Type: application/json" \
  -d '{
    "journal_id": "phase1-sep-2026",
    "date": "2026-09-01",
    "account_equity": 1587500,
    "cumulative_pnl": 87500,
    "open_trades_count": 2,
    "vix_close": 17.3,
    "market_regime": "LOW_VOL",
    "win_rate_ytd_pct": 80.0,
    "avg_trade_pnl_ytd": 14583.33,
    "account_dd_pct": 3.2,
    "notes": "Strong week, all trades profitable"
  }'
```

**Response**:
```json
{
  "success": true,
  "date": "2026-09-01",
  "journal_id": "phase1-sep-2026",
  "message": "Daily snapshot logged"
}
```

**Fields**:
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `journal_id` | string | Yes | Journal session ID |
| `date` | string | No | ISO date (defaults to today) |
| `account_equity` | number | Yes | Current account value |
| `cumulative_pnl` | number | Yes | Total P&L (realized only) |
| `open_trades_count` | integer | Yes | # of active positions |
| `vix_close` | number | Yes | VIX close value |
| `market_regime` | string | Yes | VIX-based regime label |
| `win_rate_ytd_pct` | number | No | YTD win rate (%) |
| `avg_trade_pnl_ytd` | number | No | YTD avg profit per trade |
| `account_dd_pct` | number | Yes | Current drawdown % |
| `notes` | string | No | Free-form observations |

---

### F. Market Data Management

#### 12. `POST /market/refresh` — Reload Market Data

**Purpose**: Force refresh of cached market data after 3:30 PM IST when OHLC is finalized

**Request**:
```bash
curl -X POST http://localhost:8000/market/refresh
```

**Response**:
```json
{
  "status": "refreshed",
  "latest_date": "2026-09-01",
  "rows": 4331
}
```

---

#### 13. `GET /health` — Health Check

**Purpose**: Verify server is running and models are loaded

**Request**:
```bash
curl http://localhost:8000/health
```

**Response**:
```json
{
  "status": "healthy",
  "market_data_loaded": true,
  "models_loaded": true,
  "timestamp": "2026-09-01T15:00:00Z"
}
```

---

## Workflow Example: Full Day Trade

### Morning (Before 11:00 AM IST)

```bash
# 1. Create journal session (first time only)
curl -X POST http://localhost:8000/journals \
  -H "Content-Type: application/json" \
  -d '{
    "journal_id": "phase1-sep-2026",
    "label": "Phase 1 Weekly Sep 2026",
    "initial_capital": 1500000,
    "strategy_track": "weekly"
  }'

# 2. Check account status
curl "http://localhost:8000/status?journal_id=phase1-sep-2026"

# 3. Check for signals
curl http://localhost:8000/signal
```

### Mid-Session (11:00–13:00 IST)

```bash
# 4. If signal is positive, open trade
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
    "notes": "Entered during low VIX"
  }'
```

### Afternoon (During Trade)

```bash
# 5. Monitor open trades for exit signals
curl "http://localhost:8000/monitor?journal_id=phase1-sep-2026"

# Response will suggest: HOLD, BOOK_PROFIT, EXIT_NOW, TRAIL_STOP
```

### Market Close (4:30 PM IST)

```bash
# 6. If profit target hit, close trade
curl -X POST "http://localhost:8000/trades/PT-001/close?journal_id=phase1-sep-2026" \
  -H "Content-Type: application/json" \
  -d '{
    "exit_price_per_unit": 42.5,
    "exit_reason": "profit_target",
    "exit_time_ist": "14:05",
    "brokerage": 320,
    "notes": "Closed at 50% profit"
  }'

# 7. Log daily snapshot
curl -X POST http://localhost:8000/journal/daily-log \
  -H "Content-Type: application/json" \
  -d '{
    "journal_id": "phase1-sep-2026",
    "account_equity": 1514300,
    "cumulative_pnl": 14300,
    "open_trades_count": 0,
    "vix_close": 17.3,
    "market_regime": "LOW_VOL",
    "win_rate_ytd_pct": 100.0,
    "account_dd_pct": 0.0,
    "notes": "First trade: +14.3K profit"
  }'
```

---

## Error Handling

### HTTP Status Codes

| Code | Meaning | Example |
|------|---------|---------|
| `200` | Success | Trade opened successfully |
| `400` | Bad request | Missing required field |
| `404` | Not found | Journal session doesn't exist |
| `500` | Server error | Market data fetch failed |

### Sample Error Response

```json
{
  "detail": "Journal session 'invalid-id' not found"
}
```

### Recovery Strategy

1. **Market data not loaded** → Call `POST /market/refresh`
2. **Models not loaded** → Restart server, wait 30s for startup
3. **Missing journal** → Create with `POST /journals` first
4. **API timeout** → Increase market data cache or skip refresh

---

## File Structure

```
api/
├── server.py              ← FastAPI app (all 13 endpoints)
├── journal.py             ← Journal session CRUD + CSV helpers
├── signal_wrapper.py      ← JSON serialization for ML outputs
└── __init__.py

data/.cache/
├── journal_sessions.json  ← Registry of all paper trading sessions
├── active_trades.json     ← Currently open trades (with journal_id field)
└── closed_trades.json     ← Archived closed trades (with journal_id)

paper_trading/tracker/
├── TRADES.csv             ← Master trade log (25 columns)
└── DAILY_LOG.csv          ← Daily account snapshots (11 columns)
```

---

## Performance Tips

1. **Cache refresh**: Call `/market/refresh` once per day (after 3:30 PM IST) to update cached data
2. **Monitor frequency**: Call `/monitor` every 30 min during market hours
3. **Signal polling**: Call `/signal` every 5 min around entry window (11:00–13:00 IST)
4. **Batch logging**: Log all daily data in one call at 4:30 PM (not continuous)

---

## Next Steps

1. **Deploy**: Start server with `uvicorn api.server:app --port 8000`
2. **Test**: Use curl or Postman to verify endpoints
3. **Integrate**: Wire up Fyers API for live order placement (not in Phase 1)
4. **Monitor**: Keep logs in `logs/api_*.log` for troubleshooting
5. **Document**: Add custom headers/auth as security requirements evolve

---

## Support & Troubleshooting

| Issue | Solution |
|-------|----------|
| "Market data not loaded" | Wait 30s after startup or call `POST /market/refresh` |
| "Journal not found" | Create journal with `POST /journals` first |
| "No active trades" | `/monitor` returns empty list if no open positions |
| "Signal always AVOID" | Check ML model is loaded; check `GET /health` |
| "Port 8000 in use" | Change with `--port 8001` or kill existing process |

---

**Ready to paper trade!** 🚀

