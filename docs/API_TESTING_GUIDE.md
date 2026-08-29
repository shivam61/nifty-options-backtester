# API Testing Guide — Verify All Endpoints Work Correctly

**Purpose**: Ensure all 13 API endpoints work as expected before live trading  
**Time Required**: 15 minutes  
**Status**: Tests included in `tests/test_api_endpoints.py`

---

## 🚀 Quick Start: Run All Tests

### Option 1: Automated Testing (Recommended)

```bash
# Install pytest if not already installed
pip install pytest

# Run all API endpoint tests
cd /home/shivamguptanit/github/nifty-options-backtester
python -m pytest tests/test_api_endpoints.py -v -s
```

**Expected Output**:
```
tests/test_api_endpoints.py::TestJournalEndpoints::test_01_create_journal PASSED
tests/test_api_endpoints.py::TestJournalEndpoints::test_02_list_journals PASSED
tests/test_api_endpoints.py::TestJournalEndpoints::test_03_get_journal PASSED
tests/test_api_endpoints.py::TestJournalEndpoints::test_04_update_journal PASSED
tests/test_api_endpoints.py::TestAccountEndpoints::test_01_get_status_global PASSED
... (13 endpoints total)

✅ All API endpoints working as expected
```

### Option 2: Manual Testing (Using curl)

Start the API server first:
```bash
uvicorn api.server:app --port 8000
```

Then test each endpoint (see sections below).

---

## 📋 Endpoint Tests Breakdown

### A. Journal Management (4 endpoints)

#### Test 1: Create Journal Session
```bash
curl -X POST http://localhost:8000/journals \
  -H "Content-Type: application/json" \
  -d '{
    "journal_id": "test-journal-001",
    "label": "Test Journal",
    "initial_capital": 1500000,
    "strategy_track": "weekly"
  }'
```

**Expected**:
```json
{
  "success": true,
  "journal_id": "test-journal-001",
  "status": "active",
  "created_at": "2026-09-01T10:00:00"
}
```

✅ **PASS**: Returns 200 with success=true and journal_id

---

#### Test 2: List All Sessions
```bash
curl http://localhost:8000/journals
```

**Expected**:
```json
{
  "journals": [
    {
      "journal_id": "test-journal-001",
      "label": "Test Journal",
      "status": "active",
      "open_trades": 0,
      "closed_trades": 0,
      "total_pnl": 0,
      "win_rate_pct": null
    }
  ]
}
```

✅ **PASS**: Returns list of all sessions

---

#### Test 3: Get Session Details
```bash
curl http://localhost:8000/journals/test-journal-001
```

**Expected**:
```json
{
  "journal_id": "test-journal-001",
  "initial_capital": 1500000,
  "open_trades": 0,
  "closed_trades": 0,
  "total_pnl": 0,
  "trades": []
}
```

✅ **PASS**: Returns full session details

---

#### Test 4: Update Session
```bash
curl -X PATCH http://localhost:8000/journals/test-journal-001 \
  -H "Content-Type: application/json" \
  -d '{
    "label": "Updated Test Journal",
    "notes": "Updated notes"
  }'
```

**Expected**:
```json
{
  "success": true,
  "journal_id": "test-journal-001",
  "label": "Updated Test Journal",
  "status": "active"
}
```

✅ **PASS**: Returns success=true with updated label

---

### B. Account & Portfolio (2 endpoints)

#### Test 5: Get Account Status (Global)
```bash
curl http://localhost:8000/status
```

**Expected**:
```json
{
  "journal_id": "global",
  "account_equity": 1500000,
  "cumulative_pnl": 0,
  "account_dd_pct": 0.0,
  "open_trades": 0,
  "closed_trades": 0,
  "vix_now": 17.3,
  "spot_now": 25200.5,
  "regime": "LOW_VOL",
  "backtest_baseline_cagr": 12.07,
  "backtest_baseline_win_rate": 78.0
}
```

✅ **PASS**: Returns current account state with all fields

---

#### Test 6: Get Account Status (Journal-Scoped)
```bash
curl "http://localhost:8000/status?journal_id=test-journal-001"
```

**Expected**:
```json
{
  "journal_id": "test-journal-001",
  "account_equity": 1500000,
  "cumulative_pnl": 0,
  "open_trades": 0,
  "vix_now": 17.3,
  "regime": "LOW_VOL"
}
```

✅ **PASS**: Filters status to specific journal

---

#### Test 7: List Trades (Empty Initially)
```bash
curl "http://localhost:8000/trades?journal_id=test-journal-001&status=open"
```

**Expected**:
```json
{
  "count": 0,
  "trades": []
}
```

✅ **PASS**: Returns empty list (no trades yet)

---

### C. Signals & Entry (1 endpoint)

#### Test 8: Get Entry Signal
```bash
curl http://localhost:8000/signal | jq '.'
```

**Expected**:
```json
{
  "timestamp": "2026-09-01T11:15:00Z",
  "within_entry_window": true,
  "spot": 25200.5,
  "vix": 17.3,
  "regime": "LOW_VOL",
  "weekly": {
    "should_enter": true,
    "quality_score": 0.62,
    "signal": "STRONG_ENTRY",
    "recommended_strategy": "weekly_pcs",
    "suggested_lots": 8,
    "available_capital": 1200000,
    "capital_to_deploy": 520000,
    "dte_window": "3–8",
    "skip_reason": null
  },
  "monthly": {
    "should_enter": false,
    "quality_score": 0.44,
    "signal": "AVOID",
    "skip_reason": "monthly_paused_phase1"
  },
  "reasoning": ["Low VIX regime", "ML score 0.62 ≥ 0.50"]
}
```

**Check these fields**:
- ✅ `within_entry_window`: Is it 11:00–13:00 IST?
- ✅ `weekly.quality_score`: ≥ 0.50?
- ✅ `weekly.should_enter`: true or false?
- ✅ `monthly.skip_reason`: "monthly_paused_phase1" (Phase 1 monthly disabled)

---

### D. Trade Lifecycle (3 endpoints)

#### Test 9: Open Trade
```bash
curl -X POST http://localhost:8000/trades/open \
  -H "Content-Type: application/json" \
  -d '{
    "journal_id": "test-journal-001",
    "trade_id": "PT-TEST-001",
    "strategy": "weekly_pcs",
    "entry_date": "2026-09-01",
    "expiry_date": "2026-09-04",
    "legs_str": "SELL 24800 PE 85 @ 520; BUY 24600 PE 40 @ 520",
    "lots": 8,
    "capital_deployed": 520000,
    "ml_score": 0.62,
    "entry_time_ist": "11:42",
    "notes": "Test entry"
  }'
```

**Expected**:
```json
{
  "success": true,
  "trade_id": "PT-TEST-001",
  "journal_id": "test-journal-001",
  "message": "Trade PT-TEST-001 opened"
}
```

✅ **PASS**: Trade logged successfully

**Verify CSV**: Check `paper_trading/tracker/TRADES.csv` has new row

---

#### Test 10: List Open Trades
```bash
curl "http://localhost:8000/trades?journal_id=test-journal-001&status=open"
```

**Expected**:
```json
{
  "count": 1,
  "trades": [
    {
      "trade_id": "PT-TEST-001",
      "entry_date": "2026-09-01",
      "strategy_code": "weekly_pcs",
      "legs": [
        {
          "action": "SELL",
          "strike": 24800.0,
          "entry_price": 85.0,
          "current_ltp": 42.0
        }
      ],
      "estimated_pnl": 14300.0,
      "days_in_trade": 0,
      "dte_remaining": 5
    }
  ]
}
```

✅ **PASS**: Trade visible in list

---

#### Test 11: Close Trade
```bash
curl -X POST "http://localhost:8000/trades/PT-TEST-001/close?journal_id=test-journal-001" \
  -H "Content-Type: application/json" \
  -d '{
    "exit_price_per_unit": 42.5,
    "exit_reason": "profit_target",
    "exit_time_ist": "14:05",
    "brokerage": 320,
    "notes": "Test close"
  }'
```

**Expected**:
```json
{
  "success": true,
  "trade_id": "PT-TEST-001",
  "journal_id": "test-journal-001",
  "message": "Trade PT-TEST-001 closed"
}
```

✅ **PASS**: Trade closed successfully

**Verify CSV**: Check `TRADES.csv` has exit fields filled

---

### E. Monitoring (1 endpoint)

#### Test 12: Monitor Open Trades
```bash
curl "http://localhost:8000/monitor?journal_id=test-journal-001"
```

**Expected** (if open trades exist):
```json
{
  "count": 1,
  "timestamp": "2026-09-01T14:30:00Z",
  "recommendations": [
    {
      "trade_id": "PT-TEST-001",
      "action": "HOLD",
      "confidence": 0.72,
      "current_pnl_pct": 48.2,
      "pnl_rupees": 14300.0,
      "risk_score": 0.21,
      "reasoning": [
        "48% of max profit captured",
        "Risk score 0.21 — low risk",
        "DTE 5 — time to hold"
      ]
    }
  ]
}
```

**Check these fields**:
- ✅ `action`: HOLD, BOOK_PROFIT, EXIT_NOW, TRAIL_STOP, or PARTIAL_EXIT
- ✅ `current_pnl_pct`: Current profit percentage
- ✅ `risk_score`: 0–1 (0 = safe, 1 = risky)

---

### F. Logging (1 endpoint)

#### Test 13: Log Daily Snapshot
```bash
curl -X POST http://localhost:8000/journal/daily-log \
  -H "Content-Type: application/json" \
  -d '{
    "journal_id": "test-journal-001",
    "date": "2026-09-01",
    "account_equity": 1514300,
    "cumulative_pnl": 14300,
    "open_trades_count": 0,
    "vix_close": 17.3,
    "market_regime": "LOW_VOL",
    "win_rate_ytd_pct": 100.0,
    "account_dd_pct": 0.0,
    "notes": "First trade +14.3K"
  }'
```

**Expected**:
```json
{
  "success": true,
  "date": "2026-09-01",
  "journal_id": "test-journal-001",
  "message": "Daily snapshot logged"
}
```

✅ **PASS**: Daily snapshot recorded

**Verify CSV**: Check `DAILY_LOG.csv` has new row

---

### G. Maintenance (2 endpoints)

#### Test 14: Health Check
```bash
curl http://localhost:8000/health
```

**Expected**:
```json
{
  "status": "healthy",
  "market_data_loaded": true,
  "models_loaded": true,
  "timestamp": "2026-09-01T10:00:00Z"
}
```

✅ **PASS**: Server healthy + data/models loaded

---

#### Test 15: Market Refresh
```bash
curl -X POST http://localhost:8000/market/refresh
```

**Expected**:
```json
{
  "status": "refreshed",
  "latest_date": "2026-09-01",
  "rows": 4331
}
```

✅ **PASS**: Market data refreshed successfully

---

## ✅ Test Checklist

| # | Endpoint | Method | Status | Notes |
|----|----------|--------|--------|-------|
| 1 | /journals | POST | ✅ | Create journal |
| 2 | /journals | GET | ✅ | List journals |
| 3 | /journals/{id} | GET | ✅ | Get journal details |
| 4 | /journals/{id} | PATCH | ✅ | Update journal |
| 5 | /status | GET | ✅ | Global status |
| 6 | /status?journal_id | GET | ✅ | Scoped status |
| 7 | /trades | GET | ✅ | List trades |
| 8 | /signal | GET | ✅ | Entry signals |
| 9 | /trades/open | POST | ✅ | Open trade |
| 10 | /trades | GET | ✅ | List open trades |
| 11 | /trades/{id}/close | POST | ✅ | Close trade |
| 12 | /monitor | GET | ✅ | Exit recommendations |
| 13 | /journal/daily-log | POST | ✅ | Log daily snapshot |
| 14 | /health | GET | ✅ | Health check |
| 15 | /market/refresh | POST | ✅ | Refresh market data |

---

## 🔍 Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| `Connection refused` | API server not running | Start: `uvicorn api.server:app --port 8000` |
| `404 Not Found` | Wrong endpoint path | Check spelling (e.g., `/journals` not `/journal`) |
| `422 Validation Error` | Missing/invalid field | Check request JSON schema |
| `500 Server Error` | ML models not loaded | Wait 30s for startup; check `/health` |
| `{"status":"unhealthy"}` | Models loading | Restart server; run `POST /market/refresh` |

---

## 📊 Live Data Freshness Tests

### Test: Data Refresh Strategy

```bash
# Test live data fetcher (mock mode)
python -c "
from data.live_data_fetcher import LiveDataFetcher, DataRefreshStrategy
import logging

logging.basicConfig(level=logging.INFO)

# Mock fetcher (for testing without Fyers)
fetcher = LiveDataFetcher(use_mock=True)

# Test spot price
spot, ts = fetcher.fetch_nifty_spot_price()
print(f'Spot: ₹{spot:.2f}')

# Test VIX
vix, ts = fetcher.fetch_vix_level()
print(f'VIX: {vix:.2f}')

# Test option chain
chain = fetcher.fetch_option_chain('NIFTY50', '04-SEP-2026')
print(f'Chain: {len(chain)} strikes')

# Test refresh strategy
strategy = DataRefreshStrategy(fetcher)
s1 = strategy.get_spot_price()
print(f'Cached spot (no refresh): {s1:.2f}')
s2 = strategy.get_spot_price(force_refresh=True)
print(f'Forced refresh spot: {s2:.2f}')

print('✓ All data fetching tests passed')
"
```

---

## 🚀 Production Deployment Checklist

Before going live:

- [ ] Run full test suite: `pytest tests/test_api_endpoints.py -v`
- [ ] All 15 endpoints pass (✅)
- [ ] `/health` returns healthy status
- [ ] `/signal` returns valid entry recommendations
- [ ] `/monitor` works with test trade
- [ ] TRADES.csv and DAILY_LOG.csv update correctly
- [ ] Live data fetching configured (Fyers API keys loaded)
- [ ] Market open/entry window checks working
- [ ] Error handling tested (invalid journals, missing fields, etc.)
- [ ] Catch-up logging workflow tested (retroactive entries)

---

## 📞 Support

**All tests pass?** → Ready for live trading ✅

**Some tests failing?** → See troubleshooting section above

**Questions about endpoints?** → See `API_GUIDE.md`

---

**Last Updated**: 2026-08-29  
**Status**: All 13 endpoints tested and working ✅
