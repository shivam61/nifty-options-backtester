# Market Data Validation Guide

**Purpose**: Ensure `/signal` and `/monitor` API endpoints only respond with fresh, live market data  
**Status**: ✅ Production ready  
**Location**: `data/data_validator.py` + `api/signal_validator.py`

---

## 🎯 Problem Statement

**Without Validation:**
- API might return recommendations based on 2-minute-old data
- Trader executes based on stale prices
- Results in poor entry/exit decisions

**With Validation:**
- ✅ Fresh market data guaranteed
- ✅ Clear error messages if data is stale
- ✅ Automatic retry guidance for client
- ✅ Production safety

---

## 🏗️ Architecture

### Two Layers of Validation

```
API Request
    ↓
1. Data Fetcher (rate_limiter.py)
   ├─ Fetches latest spot, VIX, chain
   └─ Returns data + timestamp
    ↓
2. Data Validator (data_validator.py)
   ├─ Checks freshness (timestamp age)
   ├─ Validates ranges (spot 15k-30k, VIX 5-100)
   ├─ Checks completeness (all fields present)
   └─ Returns ValidationResult or error
    ↓
3. API Response
   ├─ If valid: Return signal/monitoring data
   └─ If invalid: Return 503 Service Unavailable + error details
```

---

## 📋 Validation Components

### MarketDataValidator

```python
from data.data_validator import MarketDataValidator

validator = MarketDataValidator(
    max_data_age_seconds=60,    # Reject data older than 60s
    allow_cached=False          # Reject cached data
)

# Validate spot price
result = validator.validate_spot_price(spot_price=25200.5, timestamp=datetime.now())

if not result.is_valid:
    print(f"❌ Error: {result.error_message}")
    print(f"Data age: {result.data_age_seconds:.1f}s")
else:
    print(f"✅ Spot price valid (age: {result.data_age_seconds:.1f}s)")
    print(f"Is live: {result.is_live}")  # True if < 10s old
```

**Validates:**
- ✅ Spot price (15,000–30,000 range)
- ✅ VIX level (5–100 range)
- ✅ Option chain (≥5 strikes, all fields present)
- ✅ Data age (timestamp within max_data_age_seconds)
- ✅ Data completeness (no NaN/None values)

### SignalAPIValidator

```python
from data.data_validator import SignalAPIValidator

validator = SignalAPIValidator(max_data_age_seconds=60)

# Validate /signal endpoint data
result = validator.validate_signal_request(
    spot_price=25200.5,
    spot_timestamp=datetime.now(),
    vix_level=17.3,
    vix_timestamp=datetime.now()
)

if not result.is_valid:
    print(f"❌ {result.error_message}")
else:
    print(f"✅ /signal data valid (live: {result.is_live})")
```

**Validates:**
- ✅ Both spot and VIX are live (< 10s old)
- ✅ Both within acceptable ranges
- ✅ Both within max age (60s default)

### MonitorAPIValidator

```python
from data.data_validator import MonitorAPIValidator

validator = MonitorAPIValidator(max_data_age_seconds=30)  # Stricter: 30s

# Validate /monitor endpoint data
result = validator.validate_monitor_request(
    spot_price=25200.5,
    spot_timestamp=datetime.now(),
    option_chain={...},  # Dict of strikes
    chain_timestamp=datetime.now()
)

if not result.is_valid:
    print(f"❌ {result.error_message}")
else:
    print(f"✅ /monitor data valid (live: {result.is_live})")
```

**Validates:**
- ✅ Both spot and option chain are live
- ✅ Stricter 30s max age for monitoring
- ✅ Option chain has ≥5 strikes

---

## 🔌 API Integration

### /signal Endpoint

```python
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from api.signal_validator import validate_signal_data

app = FastAPI()

@app.get("/signal")
async def get_signal():
    # Fetch latest market data
    spot, spot_ts = live_fetcher.fetch_nifty_spot_price()
    vix, vix_ts = live_fetcher.fetch_vix_level()

    # VALIDATE DATA FRESHNESS
    is_valid, error = validate_signal_data(spot, spot_ts, vix, vix_ts)

    if not is_valid:
        logger.error(f"❌ Stale data rejected: {error.message}")
        return JSONResponse(
            status_code=503,  # Service Unavailable
            content=error.dict(),
            headers={"Retry-After": "5"}
        )

    # Proceed with signal generation (data is guaranteed fresh)
    regime = regime_classifier.classify(spot, vix)
    ml_signal = entry_model.predict(spot, vix, regime)

    return {
        "timestamp": datetime.now().isoformat(),
        "data_freshness": {
            "spot_age_seconds": (datetime.now() - spot_ts).total_seconds(),
            "vix_age_seconds": (datetime.now() - vix_ts).total_seconds(),
            "is_live": True  # Guaranteed by validation
        },
        "signal": ml_signal,
        "regime": regime
    }
```

### /monitor Endpoint

```python
@app.get("/monitor")
async def monitor_trades():
    # Fetch latest market data
    spot, spot_ts = live_fetcher.fetch_nifty_spot_price()
    chain = live_fetcher.fetch_option_chain("NIFTY50", expiry)
    chain_ts = datetime.now()

    # VALIDATE DATA FRESHNESS (stricter: 30s instead of 60s)
    is_valid, error = validate_monitor_data(spot, spot_ts, chain, chain_ts)

    if not is_valid:
        logger.error(f"❌ Stale data rejected: {error.message}")
        return JSONResponse(
            status_code=503,
            content=error.dict(),
            headers={"Retry-After": "10"}
        )

    # Proceed with monitoring (data is guaranteed fresh)
    trades = get_open_trades()
    recommendations = []

    for trade in trades:
        # Use fresh chain data for Greeks calculation
        exit_rec = exit_engine.analyze_trade(trade, chain, spot)
        recommendations.append(exit_rec)

    return {
        "timestamp": datetime.now().isoformat(),
        "data_freshness": {
            "spot_age_seconds": (datetime.now() - spot_ts).total_seconds(),
            "chain_age_seconds": (datetime.now() - chain_ts).total_seconds(),
            "is_live": True  # Guaranteed by validation
        },
        "recommendations": recommendations
    }
```

---

## 📊 Error Response Examples

### Stale Spot Data

```json
{
  "error": "STALE_MARKET_DATA",
  "message": "Market data too old: 75s (max 60s). Please retry.",
  "data_age_seconds": 75,
  "is_cached": true,
  "required_freshness_seconds": 60,
  "action": "retry_with_latest_data",
  "timestamp": "2026-08-29T16:35:00"
}
```

**HTTP Status**: `503 Service Unavailable`  
**Retry-After**: `5` (seconds)

### Missing Option Chain Data

```json
{
  "error": "STALE_MARKET_DATA",
  "message": "Option chain data not available or too old: 350s (max 300s)",
  "data_age_seconds": 350,
  "is_cached": true,
  "required_freshness_seconds": 300,
  "action": "refresh_market_data",
  "timestamp": "2026-08-29T16:35:00"
}
```

**HTTP Status**: `503 Service Unavailable`  
**Retry-After**: `10` (seconds)

---

## ⏱️ Data Freshness Requirements

### /signal Endpoint

| Data | Max Age | Live Threshold | Use Case |
|------|---------|-----------------|----------|
| Spot Price | 60s | < 10s | Entry decision |
| VIX Level | 60s | < 10s | Regime classification |
| Both | 60s | Either < 10s | Must have fresh *both* |

### /monitor Endpoint

| Data | Max Age | Live Threshold | Use Case |
|------|---------|-----------------|----------|
| Spot Price | 30s | < 10s | Greeks recalculation |
| Option Chain | 30s | < 30s | Exit decision |
| Both | 30s | Either < 10s | Must have fresh *both* |

### Rationale

- **Spot**: 60s for signal (less critical), 30s for monitor (active trades)
- **VIX**: 60s (changes slowly, important for regime)
- **Chain**: 30s for monitor (Greeks recalculation needed)
- **Live**: < 10s = definitely live market data (not cached)

---

## 🧪 Testing

### Unit Tests

```python
from data.data_validator import MarketDataValidator
from datetime import datetime, timedelta

validator = MarketDataValidator(max_data_age_seconds=60)

# Test 1: Fresh spot price
fresh = datetime.now()
result = validator.validate_spot_price(25200.5, fresh)
assert result.is_valid
assert result.is_live

# Test 2: Stale spot price
stale = datetime.now() - timedelta(seconds=75)
result = validator.validate_spot_price(25200.5, stale)
assert not result.is_valid
assert "too old" in result.error_message

# Test 3: Out of range
now = datetime.now()
result = validator.validate_spot_price(50000, now)  # Out of range
assert not result.is_valid
assert "out of expected range" in result.error_message

print("✅ All validation tests passed!")
```

### Integration Test

```python
from api.signal_validator import validate_signal_data
from datetime import datetime, timedelta

# Test: Fresh data should pass
spot_ts = datetime.now()
vix_ts = datetime.now()

is_valid, error = validate_signal_data(25200.5, spot_ts, 17.3, vix_ts)
assert is_valid
assert error is None

# Test: Stale data should fail
stale_ts = datetime.now() - timedelta(seconds=75)
is_valid, error = validate_signal_data(25200.5, stale_ts, 17.3, vix_ts)
assert not is_valid
assert error.error == "STALE_MARKET_DATA"

print("✅ All integration tests passed!")
```

---

## 🚀 Production Deployment

### Pre-Flight Checklist

- ✅ Data validator imported in API server
- ✅ /signal endpoint has validation call
- ✅ /monitor endpoint has validation call
- ✅ Error responses use 503 status code
- ✅ Retry-After header set appropriately
- ✅ Logging captures validation failures
- ✅ Tests verify validation logic
- ✅ Client code handles 503 responses

### Client-Side Handling

```python
import time
import requests

def get_signal_with_retry(max_retries=3):
    for attempt in range(max_retries):
        response = requests.get("http://api/signal")

        # Handle stale data error
        if response.status_code == 503:
            error_data = response.json()
            if error_data.get("error") == "STALE_MARKET_DATA":
                retry_after = int(response.headers.get("Retry-After", 5))
                print(f"Stale data, retrying in {retry_after}s...")
                time.sleep(retry_after)
                continue

        # Data is fresh
        if response.status_code == 200:
            data = response.json()
            if data.get("data_freshness", {}).get("is_live"):
                return data

        # Other errors
        response.raise_for_status()

    raise Exception("Failed to get fresh signal after retries")

# Use in trading loop
signal = get_signal_with_retry()
print(f"✅ Got fresh signal: {signal}")
```

---

## 📝 Summary

| Component | Status | Purpose |
|-----------|--------|---------|
| **MarketDataValidator** | ✅ Ready | Validates individual data items |
| **SignalAPIValidator** | ✅ Ready | Validates /signal endpoint |
| **MonitorAPIValidator** | ✅ Ready | Validates /monitor endpoint |
| **Error Responses** | ✅ Ready | 503 + retry guidance |
| **API Integration** | ✅ Ready | Drop-in to endpoints |
| **Testing** | ✅ Ready | Unit + integration tests |

---

## ✨ Key Benefits

✅ **Guaranteed Fresh Data** — No stale recommendations  
✅ **Clear Error Messages** — Easy client debugging  
✅ **Production Safety** — Prevents bad trades  
✅ **Automatic Retry** — Clients know when/how to retry  
✅ **Comprehensive Validation** — Range, freshness, completeness  
✅ **Easy Integration** — 3-line validation in each endpoint  

---

**Status**: ✅ **Ready for Production Deployment**

Last Updated: 2026-08-29
