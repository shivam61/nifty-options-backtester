# Paper Trading Journal REST API

**Provides**: Real-time entry signals, exit recommendations, and trade journal management for Phase 1 live validation  
**Status**: Production-ready  
**Framework**: FastAPI + Uvicorn  
**Architecture**: Multi-session journal support with ML integration

---

## Overview

This REST API wraps the backtester's signal generation, exit monitoring, and position sizing logic into a deployable web service. It enables:

1. **Multi-session journal tracking** — Run parallel experiments (weekly, monthly, combined)
2. **Real-time entry signals** — ML-driven recommendations via RegimeAwareLearner
3. **Live exit guidance** — ExitStrategyEngine analysis for each open trade
4. **Automated logging** — TRADES.csv and DAILY_LOG.csv via API endpoints
5. **Account monitoring** — Equity, DD, win rate, and trade statistics

---

## Architecture

### Components

| Module | Purpose |
|--------|---------|
| **api/server.py** | FastAPI application (13 endpoints, startup/shutdown) |
| **api/journal.py** | Journal session CRUD + CSV read/write helpers |
| **api/signal_wrapper.py** | JSON serialization for ML/sizing outputs |

### Dependencies

```
fastapi>=0.100.0
uvicorn>=0.23.0
pydantic>=2.0.0
```

### Integration with Existing Code

| Endpoint | Reuses | No Changes To |
|----------|--------|----------------|
| `GET /signal` | RegimeAwareLearner, PositionSizer, RegimeAdaptiveStrategy | ✓ |
| `GET /monitor` | ExitStrategyEngine, load_active_trades | ✓ |
| `POST /trades/open` | Trade/Leg dataclasses | ✓ |
| `GET /journals/{id}` | TRADES.csv, DAILY_LOG.csv (new CSV columns for journal_id) | ✓ |
| `POST /market/refresh` | MarketDataFetcher | ✓ |

**Key**: No changes to backtester core logic. CSV columns `Journal_ID` added for filtering.

---

## Quick Start

### 1. Install Dependencies

```bash
# In virtual environment
pip install fastapi uvicorn

# Or bulk
pip install -r api/requirements.txt
```

### 2. Start Server

```bash
# Development (auto-reload)
uvicorn api.server:app --reload

# Production (nohup, background)
nohup python -m uvicorn api.server:app --host 0.0.0.0 --port 8000 \
  > logs/api_$(date +%Y%m%d_%H%M).log 2>&1 &
echo "PID=$!"

# Or directly
python api/server.py
```

### 3. Verify

```bash
curl http://localhost:8000/health
# Expected: {"status":"healthy","market_data_loaded":true,...}
```

---

## Endpoint Summary

### Journal Management (4 endpoints)
- `POST /journals` — Create session
- `GET /journals` — List all sessions  
- `GET /journals/{journal_id}` — Get summary
- `PATCH /journals/{journal_id}` — Update metadata

### Account & Portfolio (2 endpoints)
- `GET /status?journal_id=<id>` — Account snapshot (equity, DD, win rate)
- `GET /trades?journal_id=<id>&status=open|closed|all` — Trade list

### Signals & Execution (4 endpoints)
- `GET /signal` — ML entry recommendations (weekly + monthly)
- `POST /trades/open` — Record new trade
- `GET /monitor?journal_id=<id>` — Exit recommendations (HOLD/BOOK_PROFIT/EXIT_NOW)
- `POST /trades/{trade_id}/close?journal_id=<id>` — Close trade

### Logging & Maintenance (3 endpoints)
- `POST /journal/daily-log` — Log daily snapshot
- `POST /market/refresh` — Reload cached data
- `GET /health` — Server status

**Full details**: See [API_GUIDE.md](../API_GUIDE.md)

---

## Key Features

### Multi-Session Journal Support

Each journal session has:
- **journal_id**: Unique identifier (e.g., "phase1-sep-2026")
- **label**: Human-readable name
- **initial_capital**: Starting account balance
- **strategy_track**: "weekly", "monthly", or "combined"
- **trade_ids**: List of associated trades
- **status**: "active" or "closed"

Enables:
- Running weekly and monthly experiments in parallel
- Easy filtering of trades by experiment
- Per-session P&L, win rate, DD tracking

### Smart Trade Filtering

All endpoints supporting journal scoping:
```bash
# Get status for specific journal
curl "http://localhost:8000/status?journal_id=phase1-sep-2026"

# List trades in journal
curl "http://localhost:8000/trades?journal_id=phase1-sep-2026&status=open"

# Monitor only this journal's trades
curl "http://localhost:8000/monitor?journal_id=phase1-sep-2026"
```

### ML-Driven Entry Signals

`GET /signal` integrates:
1. **RegimeAdaptiveStrategy.get_eligible_strategies()** — Circuit breaker checks (crash risk, VIX zones)
2. **RegimeAwareLearner.predict()** — ML quality score + signal classification
3. **PositionSizer.compute_lots()** — VIX/regime-adjusted lot sizing
4. **Entry window gate** — Enforces 11:00–13:00 IST mid-session window

Response includes:
- `weekly.should_enter` → Boolean entry decision
- `weekly.quality_score` → ML confidence (0–1)
- `weekly.suggested_lots` → Position size (nifty units)
- `weekly.dte_window` → Valid expiry range
- `within_entry_window` → Is it 11:00–13:00 IST?

### Real-Time Exit Guidance

`GET /monitor` for each open trade:
- **action**: HOLD, BOOK_PROFIT, EXIT_NOW, TRAIL_STOP, PARTIAL_EXIT
- **confidence**: Decision certainty (60–95%)
- **current_pnl_pct**: % of max profit captured
- **risk_score**: Tail loss probability (0–1)
- **reasoning**: English explanation (["48% max profit", "Low risk", ...])
- **per_leg_pnl**: Individual leg P&Ls for transparency

---

## Data Flow

### Entry Workflow

```
User calls GET /signal
    ↓
Server loads MarketDataFetcher.build_combined_dataset() → latest row
    ↓
RegimeAdaptiveStrategy.get_eligible_strategies(spot, vix, features)
    ↓
RegimeAwareLearner.predict(row, eligible_strats) → quality_score, signal
    ↓
PositionSizer.compute_lots(equity, vix, regime, quality_score, dd)
    ↓
JSON response with weekly/monthly signals
    ↓
User places trade via broker (not API)
    ↓
User logs trade: POST /trades/open (records to active_trades.json + TRADES.csv)
```

### Exit Workflow

```
User calls GET /monitor?journal_id=phase1
    ↓
Load active_trades.json, filter by journal_id
    ↓
For each trade:
  - Fetch live LTP from Fyers (or compute Black-Scholes)
  - Call ExitStrategyEngine.analyze_trade(trade, latest_row)
  - Return: {action, confidence, pnl_pct, reasoning}
    ↓
User decides: HOLD, BOOK, or EXIT
    ↓
User closes trade via broker
    ↓
User logs close: POST /trades/{id}/close (updates TRADES.csv)
```

---

## CSV Schema

### TRADES.csv (25 columns)

| Column | Type | Example |
|--------|------|---------|
| Trade_ID | String | PT-001 |
| Journal_ID | String | phase1-sep-2026 |
| Date_Entry | Date | 2026-09-01 |
| Entry_Time_IST | String | 11:42 |
| Strategy | String | weekly_pcs |
| Signal_VIX | Float | 17.3 |
| Signal_Regime | String | LOW_VOL |
| ML_Score | Float | 0.62 |
| Entry_Price_Fill | Float | 85.0 |
| Lots_Size | Integer | 8 |
| Capital_Deployed_₹ | Integer | 520000 |
| Strike_Entry | Float | 24800 |
| Expiry_DTE | Integer | 5 |
| Date_Exit | Date | 2026-09-02 |
| Exit_Time_IST | String | 12:05 |
| Exit_Price_Fill | Float | 42.5 |
| Exit_Reason | String | profit_target |
| Days_Held | Integer | 1 |
| Gross_P&L_₹ | Integer | 14300 |
| Brokerage_₹ | Integer | 320 |
| Slippage_vs_Backtest_bp | Integer | 50 |
| Net_P&L_₹ | Integer | 13980 |
| Win_Loss | String | W |
| P&L_vs_Max_Profit_% | Float | 100.0 |
| Backtest_Expected_P&L_₹ | Integer | 29528 |
| Backtest_Deviation_% | Float | -53.0 |
| Notes | String | Closed at 50% profit |

### DAILY_LOG.csv (11 columns)

| Column | Type | Example |
|--------|------|---------|
| Date | Date | 2026-09-01 |
| Journal_ID | String | phase1-sep-2026 |
| Account_Equity_₹ | Integer | 1514300 |
| Cumulative_P&L_₹ | Integer | 14300 |
| Open_Trades_Count | Integer | 0 |
| VIX_Close | Float | 17.3 |
| Market_Regime | String | LOW_VOL |
| Open_Trades_Count_Weekly | Integer | 0 |
| Win_Rate_%_YTD | Float | 100.0 |
| Avg_Trade_P&L_₹_YTD | Float | 14300 |
| Account_DD_% | Float | 0.0 |
| Notes | String | First trade: +14.3K |

---

## Error Handling

### Common Errors

| Error | Status | Cause | Fix |
|-------|--------|-------|-----|
| Market data not loaded | 500 | Startup incomplete | Wait 30s or call `POST /market/refresh` |
| Journal not found | 404 | Journal ID doesn't exist | Create with `POST /journals` |
| Model not loaded | 500 | Startup failed or models deleted | Restart server |
| Missing required field | 400 | Incomplete request body | Check API_GUIDE.md for schema |
| Port already in use | — | Another process on port 8000 | Kill existing or use `--port 8001` |

### Example Error Response

```json
{
  "detail": "Journal session 'invalid-id' not found"
}
```

---

## Performance Characteristics

| Operation | Time | Notes |
|-----------|------|-------|
| Server startup | ~30s | Loads 17 years of data, trains/loads 2 ML models |
| `/signal` (first call) | 2–5s | Computes features, ML prediction, position sizing |
| `/signal` (cached) | <500ms | Uses cached market data |
| `/monitor` (N trades) | 1–3s | ExitStrategyEngine per trade × N |
| `/trades` | <100ms | JSON serialization of active_trades.json |
| `/market/refresh` | 15–30s | Re-fetches + re-caches all market data |

**Recommendation**: Call `/market/refresh` once daily (after 3:30 PM IST).

---

## Deployment Options

### Development
```bash
uvicorn api.server:app --reload --port 8000
```

### Production (nohup, background)
```bash
nohup python -m uvicorn api.server:app --host 0.0.0.0 --port 8000 \
  > logs/api_$(date +%Y%m%d_%H%M).log 2>&1 &
echo "Server PID: $!"
```

### Docker (future)
```dockerfile
FROM python:3.11-slim
RUN pip install fastapi uvicorn
COPY . /app
WORKDIR /app
CMD ["uvicorn", "api.server:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

## Testing Checklist

- [ ] Server starts without errors
- [ ] `GET /health` returns healthy status
- [ ] `POST /journals` creates session successfully
- [ ] `GET /signal` returns weekly signal with quality_score > 0.5
- [ ] `POST /trades/open` logs trade to TRADES.csv
- [ ] `GET /monitor` returns recommendations for open trades
- [ ] `GET /status` shows correct cumulative P&L
- [ ] `POST /trades/{id}/close` closes trade and updates CSV
- [ ] `POST /journal/daily-log` appends to DAILY_LOG.csv
- [ ] `POST /market/refresh` reloads data without error

---

## Future Enhancements (Phase 2+)

1. **Fyers API Integration** — Place orders directly via `/orders/place` endpoint
2. **WebSocket Streaming** — Live quote updates instead of REST polling
3. **Authentication** — JWT tokens for production security
4. **Database** — PostgreSQL instead of JSON files for scale
5. **Analytics** — BI dashboards (Grafana/Metabase)
6. **Monthly Track** — Activate endpoints when ML threshold improves (Phase 5)

---

## Support

**For detailed endpoint documentation**: See [API_GUIDE.md](../API_GUIDE.md)  
**For paper trading setup**: See [paper_trading/README.md](../paper_trading/README.md)  
**For backtest logic**: See [CLAUDE.md](../CLAUDE.md)

---

**Ready to trade!** 🚀

