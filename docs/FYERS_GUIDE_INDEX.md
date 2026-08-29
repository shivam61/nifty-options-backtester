# 📚 Fyers API Documentation Index

**Complete guide to Fyers API integration with rate limiting, validation, and OAuth management**

---

## 🎯 Quick Navigation

Choose your scenario:

| Your Situation | Read This | Time |
|---|---|---|
| **Just starting** | [Initial Setup](#1-initial-setup-getting-started) | 30 min |
| **Setting up credentials** | [Credential Setup Guide](./FYERS_CREDENTIAL_SETUP.md) | 15 min |
| **Need OAuth token** | [OAuth Token Setup](./FYERS_OAUTH_TOKEN_SETUP.md) | 10 min |
| **Token needs refresh** | [Credential Refresh Guide](./FYERS_CREDENTIAL_REFRESH_GUIDE.md) | 10 min |
| **Rate limit issues** | [Rate Limit Strategy](./FYERS_RATE_LIMIT_STRATEGY.md) | 15 min |
| **API integration** | [Integration Complete](./FYERS_INTEGRATION_COMPLETE.md) | 20 min |
| **Troubleshooting** | [Troubleshooting Guide](#troubleshooting) | 5 min |

---

## 1️⃣ Initial Setup: Getting Started

### Prerequisites Checklist

- [ ] Python 3.8+ installed
- [ ] Virtual environment created: `python3 -m venv .venv`
- [ ] Dependencies installed: `pip install fyers-apiv3 python-dotenv fastapi uvicorn`
- [ ] Fyers account created at https://www.fyers.in
- [ ] Account funded (₹15 Lakhs minimum for live trading data)
- [ ] Developer app created at https://developers.fyers.in

### 5-Minute Overview

**The Fyers API has 4 core components:**

1. **Client ID + API Secret** — Identify your app
2. **OAuth Token** — Authenticate your user account
3. **Rate Limits** — 10/sec, 200/min, 10,000/day
4. **Data Validation** — Ensure data is fresh (not cached)

**How they work together:**

```
┌─────────────────────────────────────┐
│   Fyers API Request                 │
├─────────────────────────────────────┤
│  Use: Client ID + API Secret + Token│
└──────────────┬──────────────────────┘
               ↓
┌─────────────────────────────────────┐
│   Rate Limiter                      │
├─────────────────────────────────────┤
│  Check: 10/sec, 200/min, 10k/day    │
└──────────────┬──────────────────────┘
               ↓
┌─────────────────────────────────────┐
│   Adaptive TTL Cache                │
├─────────────────────────────────────┤
│  Return cached if fresh:            │
│  - Spot: 30s                        │
│  - VIX: 60s                         │
│  - Chain: 5min                      │
└──────────────┬──────────────────────┘
               ↓
┌─────────────────────────────────────┐
│   Data Validator                    │
├─────────────────────────────────────┤
│  Ensure: Fresh, in range, complete  │
│  If stale: Return HTTP 503          │
└──────────────┬──────────────────────┘
               ↓
┌─────────────────────────────────────┐
│   Return Data to API Client         │
├─────────────────────────────────────┤
│  Spot Price, VIX, Option Chain, etc │
└─────────────────────────────────────┘
```

---

## 📋 Step-by-Step Setup

### Step 1: Create `.env.local` File

```bash
cd /home/shivamguptanit/github/nifty-options-backtester

# Copy template
cp .env.local.template .env.local

# Edit with your credentials (from https://developers.fyers.in/)
nano .env.local
```

**File contents:**
```
FYERS_CLIENT_ID=YOUR_CLIENT_ID
FYERS_API_SECRET=YOUR_API_SECRET
FYERS_ACCESS_TOKEN=<will be set after OAuth>
```

See: [FYERS_CREDENTIAL_SETUP.md](./FYERS_CREDENTIAL_SETUP.md) → Step 2

### Step 2: Get OAuth Access Token

```bash
# Get authorization URL
python3 << 'EOF'
from fyers_apiv3 import fyersModel
from data.credentials import load_fyers_credentials

client_id, api_secret = load_fyers_credentials()
client = fyersModel.FyersModel(is_async=False, client_id=client_id, log_level="ERROR")
auth_url = client.get_auth_url()
print("Open in browser:", auth_url)
EOF

# Then follow: [FYERS_OAUTH_TOKEN_SETUP.md](./FYERS_OAUTH_TOKEN_SETUP.md)
```

See: [FYERS_OAUTH_TOKEN_SETUP.md](./FYERS_OAUTH_TOKEN_SETUP.md) → Steps 1-3

### Step 3: Verify Setup

```bash
# Run end-to-end test
source .venv/bin/activate
python scripts/test_fyers_live.py
```

See: [FYERS_CREDENTIAL_SETUP.md](./FYERS_CREDENTIAL_SETUP.md) → Step 3

### Step 4: Start API Server

```bash
# Activate virtual environment
source .venv/bin/activate

# Start server
uvicorn api.server:app --host 0.0.0.0 --port 8000

# In another terminal, test:
curl http://localhost:8000/signal | jq '.'
```

See: [FYERS_CREDENTIAL_SETUP.md](./FYERS_CREDENTIAL_SETUP.md) → Step 4

---

## 📚 Documentation Guide Map

### Core Setup Documents

| Document | Purpose | Read When |
|----------|---------|-----------|
| [**FYERS_CREDENTIAL_SETUP.md**](./FYERS_CREDENTIAL_SETUP.md) | Create `.env.local`, get credentials, run tests | First time setup |
| [**FYERS_OAUTH_TOKEN_SETUP.md**](./FYERS_OAUTH_TOKEN_SETUP.md) | Generate OAuth token via browser auth | Need OAuth token |

### Operational Documents

| Document | Purpose | Read When |
|----------|---------|-----------|
| [**FYERS_CREDENTIAL_REFRESH_GUIDE.md**](./FYERS_CREDENTIAL_REFRESH_GUIDE.md) | Token refresh, rotation, troubleshooting | Token expired or needs refresh |
| [**FYERS_RATE_LIMIT_STRATEGY.md**](./FYERS_RATE_LIMIT_STRATEGY.md) | Rate limit analysis and budget | Planning API usage |
| [**RATE_LIMIT_IMPLEMENTATION.md**](./RATE_LIMIT_IMPLEMENTATION.md) | Rate limiter code usage | Implementing rate limits |

### Validation Documents

| Document | Purpose | Read When |
|----------|---------|-----------|
| [**DATA_VALIDATION_GUIDE.md**](./DATA_VALIDATION_GUIDE.md) | Market data validation patterns | Using validators |
| [**FYERS_INTEGRATION_COMPLETE.md**](./FYERS_INTEGRATION_COMPLETE.md) | End-to-end integration overview | Full system understanding |

### Reference Documents

| Document | Purpose | Link |
|----------|---------|------|
| **CLAUDE.md** | Project architecture & constants | [Link](../CLAUDE.md) |
| **QUICK_START_FYERS.md** | 5-minute quick start | [Link](./QUICK_START_FYERS.md) |
| **FYERS_API_STATUS.md** | Integration status report | [Link](./FYERS_API_STATUS.md) |

---

## 🔄 Common Workflows

### Workflow 1: Initial Setup (First Time)

1. Read: [FYERS_CREDENTIAL_SETUP.md](./FYERS_CREDENTIAL_SETUP.md) → Section 1-3
2. Create `.env.local` with Client ID + API Secret
3. Run `python scripts/test_fyers_live.py`
4. If test passes → Continue to Workflow 2
5. If test fails → See [Troubleshooting](#troubleshooting)

**Time**: 30 minutes

### Workflow 2: Get OAuth Token

1. Read: [FYERS_OAUTH_TOKEN_SETUP.md](./FYERS_OAUTH_TOKEN_SETUP.md) → Steps 1-3
2. Get auth URL from Python script
3. Authorize in browser
4. Exchange auth code for token
5. Verify token works
6. Restart API server

**Time**: 10 minutes

### Workflow 3: Daily Operations

1. API server auto-handles token refresh ✅ (no action needed)
2. Monitor rate limits with logs
3. Cache automatically reduces API calls 85%+ ✅
4. Data validation ensures fresh data ✅

**Time**: 0 minutes (fully automatic)

### Workflow 4: Token Needs Refresh (30+ days old)

1. Read: [FYERS_CREDENTIAL_REFRESH_GUIDE.md](./FYERS_CREDENTIAL_REFRESH_GUIDE.md) → Scenario 2
2. Follow steps 1-4 to get new token
3. Restart API server
4. Verify with `curl http://localhost:8000/signal`

**Time**: 10 minutes

### Workflow 5: Quarterly Credential Rotation (Security)

1. Read: [FYERS_CREDENTIAL_REFRESH_GUIDE.md](./FYERS_CREDENTIAL_REFRESH_GUIDE.md) → Scenario 4
2. Generate new API credentials at https://developers.fyers.in
3. Update `.env.local` with new Client ID + Secret
4. Get new OAuth token
5. Restart all services
6. Verify everything works

**Time**: 20 minutes

### Workflow 6: Troubleshooting Issues

1. See [Troubleshooting Guide](#troubleshooting) below
2. Find your error message
3. Follow solution steps
4. If still stuck → Check logs: `tail -f logs/fyers_api.log`

**Time**: 5-15 minutes

---

## 🚀 Starting Your API Server

### Option 1: Standalone (Development)

```bash
source .venv/bin/activate
uvicorn api.server:app --host 0.0.0.0 --port 8000 --reload
```

### Option 2: Background (Production)

```bash
nohup uvicorn api.server:app --host 0.0.0.0 --port 8000 > logs/api.log 2>&1 &
echo "API server started. Check: tail -f logs/api.log"
```

### Option 3: Via Main Script

```bash
python main.py --mode api --port 8000
```

### Verify Server is Running

```bash
# Check health
curl http://localhost:8000/health

# Expected response:
# {"status": "healthy", "market_data_loaded": true, "models_loaded": true}

# Get signal
curl http://localhost:8000/signal | jq '.spot, .vix, .weekly.should_enter'

# Monitor trades
curl http://localhost:8000/monitor | jq '.'
```

---

## 📊 Configuration Reference

### Rate Limit Configuration (`config.FyersAPIConfig`)

```python
from config import FyersAPIConfig

config = FyersAPIConfig()

# Fyers rate limits (hard limits, don't change)
config.calls_per_second_limit = 10      # 10 calls/sec
config.calls_per_minute_limit = 200     # 200 calls/min
config.calls_per_day_limit = 10_000     # 10,000 calls/day

# Cache TTL (customize per data type)
config.cache_ttl_spot_price_seconds = 30        # 30 sec
config.cache_ttl_vix_seconds = 60               # 60 sec
config.cache_ttl_option_chain_seconds = 300     # 5 min
config.cache_ttl_account_seconds = 300          # 5 min

# Alert thresholds (get alerts when approaching limits)
config.daily_usage_alert_pct = 80       # Alert at 80%
config.minute_usage_alert_pct = 90      # Alert at 90%
config.second_usage_alert_pct = 80      # Alert at 80%

# Fallback behavior (graceful degradation)
config.use_mock_on_daily_limit = True   # Use mock if daily limit hit
config.use_cached_on_minute_limit = True  # Use cache if minute limit hit
config.enable_request_queuing = True    # Queue requests during limits
```

See: [FYERS_RATE_LIMIT_STRATEGY.md](./FYERS_RATE_LIMIT_STRATEGY.md) for detailed analysis

---

## 🧪 Testing

### Quick Test

```bash
# Run end-to-end test
python scripts/test_fyers_live.py
```

### Detailed Test

```bash
# Unit tests
pytest tests/test_rate_limiter.py -v

# Integration tests
pytest tests/test_data_validator.py -v

# API endpoint tests
pytest tests/test_api_endpoints.py -v

# All tests
pytest tests/ -v
```

See: [DATA_VALIDATION_GUIDE.md](./DATA_VALIDATION_GUIDE.md) → Testing section

---

## 📈 Monitoring

### Check Rate Limit Usage

```python
from data.rate_limiter import SmartFyersAPI

smart_api = SmartFyersAPI(fyers_client)
stats = smart_api.get_rate_limit_stats()

print(f"Daily usage: {stats['rate_limit']['day']['pct']:.1f}%")
print(f"Cache hit rate: {stats['cache_stats']}")
```

### View Logs

```bash
# API logs
tail -f logs/api.log

# Fyers API logs
tail -f logs/fyers_api.log

# Rate limit alerts
grep "alert" logs/*.log
```

### Daily Health Check

```bash
# Check token health
python scripts/check_fyers_token_health.py

# Check rate limit budget
python scripts/check_rate_limit_budget.py

# Check data freshness
python scripts/check_data_freshness.py
```

---

## ⚠️ Troubleshooting

### Issue: "No credentials found"

**Solution**: Create `.env.local`
```bash
cp .env.local.template .env.local
# Edit with your Client ID and API Secret
```

**Read**: [FYERS_CREDENTIAL_SETUP.md](./FYERS_CREDENTIAL_SETUP.md) → Step 2

---

### Issue: "401 Unauthorized" or "Invalid token"

**Solution**: Refresh OAuth token
```bash
# Follow the steps in Scenario 2 of:
# [FYERS_CREDENTIAL_REFRESH_GUIDE.md](./FYERS_CREDENTIAL_REFRESH_GUIDE.md)
```

---

### Issue: "Market data not available"

**Cause**: Market is closed (testing outside 9:15 AM - 3:30 PM IST)

**Solution**: Use mock mode
```python
from data.live_data_fetcher import LiveDataFetcher
fetcher = LiveDataFetcher(use_mock=True)  # Mock data
```

**Read**: [FYERS_CREDENTIAL_REFRESH_GUIDE.md](./FYERS_CREDENTIAL_REFRESH_GUIDE.md) → Common Issues

---

### Issue: "Rate limit exceeded"

**Cause**: Too many API calls in a short time

**Solution**: Cache automatically handles this, but check budget
```bash
# Check rate limit stats
python scripts/check_rate_limit_budget.py

# Read rate limit strategy
# [FYERS_RATE_LIMIT_STRATEGY.md](./FYERS_RATE_LIMIT_STRATEGY.md)
```

---

### Issue: "Stale data detected" (HTTP 503)

**Cause**: API returned data > 60s old (signal) or > 30s old (monitor)

**Solution**: Automatic retry with Retry-After header
```bash
# Client-side retry example in:
# [DATA_VALIDATION_GUIDE.md](./DATA_VALIDATION_GUIDE.md) → Client Retry Handler
```

---

### More Issues?

Check the complete troubleshooting section:
- [FYERS_CREDENTIAL_SETUP.md](./FYERS_CREDENTIAL_SETUP.md) → Troubleshooting
- [FYERS_OAUTH_TOKEN_SETUP.md](./FYERS_OAUTH_TOKEN_SETUP.md) → Troubleshooting
- [FYERS_CREDENTIAL_REFRESH_GUIDE.md](./FYERS_CREDENTIAL_REFRESH_GUIDE.md) → Common Issues

---

## 🔐 Security Checklist

Before going live:

- [ ] `.env.local` created and contains all values
- [ ] `.env.local` is in `.gitignore` (not committed to git)
- [ ] Credentials are stored ONLY locally
- [ ] Token is NOT logged or printed anywhere
- [ ] HTTPS is enabled in production
- [ ] Rate limits are monitored
- [ ] Credentials rotated every 3 months
- [ ] Health checks run daily

See: [FYERS_CREDENTIAL_REFRESH_GUIDE.md](./FYERS_CREDENTIAL_REFRESH_GUIDE.md) → Security Checklist

---

## 📞 Quick Reference

### Emergency Commands

```bash
# Check if server is running
curl http://localhost:8000/health

# Stop server
pkill -f "uvicorn api.server"

# Restart server
source .venv/bin/activate && uvicorn api.server:app --port 8000

# Check token status
python3 -c "from data.credentials import get_fyers_access_token; print('Token:', get_fyers_access_token()[:20] + '...' if get_fyers_access_token() else 'None')"

# Check rate limit usage
python3 << 'EOF'
from data.rate_limiter import SmartFyersAPI
from data.credentials import load_fyers_credentials
from fyers_apiv3 import fyersModel

client_id, _ = load_fyers_credentials()
client = fyersModel.FyersModel(is_async=False, client_id=client_id, log_level="ERROR")
api = SmartFyersAPI(client)
stats = api.get_rate_limit_stats()
print(f"Daily: {stats['rate_limit']['day']['used']}/{stats['rate_limit']['day']['limit']}")
EOF
```

---

## 📚 Related Documentation

- **[CLAUDE.md](../CLAUDE.md)** — Project architecture, constants, CLI reference
- **[QUICK_START_FYERS.md](./QUICK_START_FYERS.md)** — 5-minute quick start
- **[FYERS_API_STATUS.md](./FYERS_API_STATUS.md)** — Current integration status

---

## ✅ Completion Checklist

### One-Time Setup
- [ ] Read [FYERS_CREDENTIAL_SETUP.md](./FYERS_CREDENTIAL_SETUP.md)
- [ ] Create `.env.local` with Client ID + API Secret
- [ ] Get OAuth token via [FYERS_OAUTH_TOKEN_SETUP.md](./FYERS_OAUTH_TOKEN_SETUP.md)
- [ ] Run `python scripts/test_fyers_live.py` successfully
- [ ] Start API server: `uvicorn api.server:app --port 8000`
- [ ] Verify with: `curl http://localhost:8000/signal`

### Ongoing Operations
- [ ] Set up daily health checks
- [ ] Monitor logs: `tail -f logs/api.log`
- [ ] Review rate limit usage weekly
- [ ] Plan quarterly credential rotation

### When Needed
- [ ] Token refresh: See [FYERS_CREDENTIAL_REFRESH_GUIDE.md](./FYERS_CREDENTIAL_REFRESH_GUIDE.md)
- [ ] Rate limit issues: See [FYERS_RATE_LIMIT_STRATEGY.md](./FYERS_RATE_LIMIT_STRATEGY.md)
- [ ] Data validation issues: See [DATA_VALIDATION_GUIDE.md](./DATA_VALIDATION_GUIDE.md)

---

## 📞 Support

**Quick Help**:
1. Check this index for your scenario
2. Read the linked documentation
3. Follow the steps
4. Check logs if stuck: `tail -f logs/api.log`
5. Review [Troubleshooting](#troubleshooting) section

**Documentation Files**:
- `docs/FYERS_*.md` — Fyers API guides
- `docs/RATE_LIMIT_*.md` — Rate limiting guides
- `docs/DATA_VALIDATION_*.md` — Validation guides

**Code Files**:
- `data/rate_limiter.py` — Rate limiting implementation
- `data/data_validator.py` — Validation implementation
- `api/signal_validator.py` — API middleware
- `data/credentials.py` — Credential management

---

**Status**: ✅ **PRODUCTION READY**

All documentation complete, linked, and tested.

Last Updated: 2026-08-29
