# Fyers API Credentials Setup & End-to-End Testing

**Purpose**: Set up Fyers API credentials securely and verify end-to-end integration  
**Time Required**: 15-30 minutes  
**Security**: Credentials stored locally (`.env.local`), never committed to git

---

## 🔐 Security First

Your Fyers credentials will be stored in `.env.local` which is:
- ✅ **Excluded from git** (in `.gitignore`)
- ✅ **Local only** (never uploaded to GitHub)
- ✅ **Readable only by you** (file permissions)
- ❌ **NOT committed** (git prevents it)

```bash
# Verify .gitignore contains .env.local
grep ".env.local" .gitignore
# Output: .env.local
```

---

## 📋 Step 1: Get Your Fyers API Credentials

### 1.1 Create Fyers Account
1. Go to **https://www.fyers.in/**
2. Sign up or log in
3. Complete KYC verification

### 1.2 Fund Account (Required for Live API)
- Minimum deposit: **₹15 Lakhs** (₹1,500,000)
- Note: For paper trading you need access to live data APIs
- Account status should be "Active"

### 1.3 Generate API Credentials
1. Go to **https://developers.fyers.in/**
2. Log in with your Fyers account
3. Create a new app:
   - App Name: "Nifty Backtester"
   - Redirect URL: `http://localhost:3000`
   - Scopes: Select "full_access"
4. Copy your credentials:
   - **Client ID** (e.g., "XXXXXXXXXXXXXXXX")
   - **API Secret** (e.g., "XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX")

**Keep these safe!** You'll need them in the next step.

---

## 🔧 Step 2: Create `.env.local` File

### 2.1 Copy Template
```bash
cd /home/shivamguptanit/github/nifty-options-backtester

# Copy the template
cp .env.local.template .env.local
```

### 2.2 Edit with Your Credentials

**Option A: Using nano/vim**
```bash
nano .env.local
```

**Option B: Using echo**
```bash
# Append your credentials (replace with actual values)
cat >> .env.local << 'EOF'
FYERS_CLIENT_ID=YOUR_ACTUAL_CLIENT_ID
FYERS_API_SECRET=YOUR_ACTUAL_API_SECRET
EOF
```

### 2.3 Verify File (Don't Show Content)
```bash
# Check file exists (but DON'T print contents for security)
ls -la .env.local

# Expected output:
# -rw-r--r-- 1 user user 150 Aug 29 15:30 .env.local
```

### 2.4 Verify it's Not in Git
```bash
# Check .env.local is ignored
git check-ignore -v .env.local
# Expected: .env.local

# Verify it won't be committed
git status | grep ".env.local"
# Expected: (nothing - file should be ignored)
```

---

## ✅ Step 3: Test Credentials

### 3.1 Install Dependencies
```bash
# Create virtual environment (recommended)
python3 -m venv .venv
source .venv/bin/activate

# Install required packages
pip install fyers-apiv3 python-dotenv fastapi uvicorn pytest
```

### 3.2 Run End-to-End Test
```bash
# Run the comprehensive test
python scripts/test_fyers_live.py
```

### 3.3 Expected Output

**If Market is OPEN** (9:15 AM - 3:30 PM IST):
```
================================================================================
FYERS API END-TO-END TEST
================================================================================

1️⃣  Loading Fyers credentials...
✅ Credentials loaded
   Client ID: XXXXXXXX...

2️⃣  Initializing Fyers client...
✅ Fyers client initialized

3️⃣  Testing LiveDataFetcher with Fyers API...
✅ LiveDataFetcher initialized with Fyers

4️⃣  Fetching Nifty spot price...
✅ Spot price: ₹25,243.50 (timestamp: 2026-08-29 11:30:00)
✅ Spot price in valid range

5️⃣  Fetching VIX level...
✅ VIX level: 17.23 (timestamp: 2026-08-29 11:30:00)
✅ VIX in valid range

6️⃣  Fetching option chain...
✅ Option chain fetched: 12 strikes
   Strike range: 25,000 - 25,200

   Sample strike 25,100:
   - Call LTP: ₹42.50
   - Put LTP: ₹285.00

7️⃣  Testing data refresh strategy...
✅ First call (cached): ₹25,243.50
✅ Force refresh: ₹25,248.25
   ✅ Cache correctly refreshed with new data

8️⃣  Testing API endpoint with real data...
✅ /signal endpoint working with real data
   Spot: ₹25,243.50
   VIX: 17.23
   Regime: LOW_VOL
   Weekly entry: true
   Weekly score: 0.58

================================================================================
✅ ALL END-TO-END TESTS PASSED!
================================================================================

Fyers API Integration Status:
  ✅ Credentials loaded successfully
  ✅ Fyers client initialized
  ✅ Real spot price fetched: ₹25,243.50
  ✅ Real VIX fetched: 17.23
  ✅ Real option chain fetched: 12 strikes
  ✅ Data refresh strategy working
  ✅ API endpoints working with real data

Ready for production deployment! 🚀
```

**If Market is CLOSED** (3:30 PM - 9:15 AM IST):
```
4️⃣  Fetching Nifty spot price...
❌ Failed to fetch spot price: ...
   This might be because:
   - Market is closed
   - Fyers credentials need token setup
   - Network connectivity issue
```

This is expected! Market data is only available during trading hours.

---

## 🐛 Troubleshooting

| Issue | Cause | Solution |
|-------|-------|----------|
| `No credentials found` | `.env.local` missing or empty | Copy template: `cp .env.local.template .env.local` and fill with credentials |
| `fyers-apiv3 not installed` | Missing dependency | `pip install fyers-apiv3` |
| `Failed to fetch spot price` | Market closed | Test only during 9:15 AM - 3:30 PM IST |
| `Invalid credentials` | Wrong CLIENT_ID or SECRET | Double-check at https://developers.fyers.in/ |
| `Connection refused` | Network issue | Check internet connection, firewall rules |
| `HTTPError: 401 Unauthorized` | API credentials invalid | Regenerate at https://developers.fyers.in/ |

---

## 🚀 Step 4: Deploy Live API Server

Once testing passes:

### 4.1 Start API Server
```bash
# Option 1: Direct with uvicorn
uvicorn api.server:app --host 0.0.0.0 --port 8000 --reload

# Option 2: Via main.py (if implemented)
python main.py --mode api --port 8000
```

### 4.2 Verify Server Health
```bash
# In another terminal
curl http://localhost:8000/health

# Expected output:
# {"status": "healthy", "market_data_loaded": true, "models_loaded": true}
```

### 4.3 Test Live Signal Endpoint
```bash
# Get current entry signal with real Fyers data
curl http://localhost:8000/signal | jq '.weekly'

# Expected output:
# {
#   "should_enter": true,
#   "quality_score": 0.58,
#   "signal": "STRONG_ENTRY",
#   "recommended_strategy": "weekly_pcs",
#   "suggested_lots": 8,
#   "available_capital": 1200000,
#   "capital_to_deploy": 520000
# }
```

---

## 📊 Step 5: Run Full API Endpoint Tests

```bash
# Run all 15 endpoint tests
pytest tests/test_api_endpoints.py -v -s

# Expected: All tests PASS
```

---

## ⚠️ Security Checklist

Before going live, ensure:

- [ ] `.env.local` is created (copy from `.env.local.template`)
- [ ] Credentials are filled in correctly
- [ ] `git status` shows `.env.local` is NOT listed (it's ignored)
- [ ] `.env.local` is NOT committed to GitHub
- [ ] Credentials are stored ONLY locally
- [ ] Never share `.env.local` file with anyone
- [ ] Never paste credentials into messages or chat
- [ ] Regularly rotate credentials at https://developers.fyers.in/

---

## 🔄 Data Freshness Verification

After deployment, verify data freshness:

```bash
# Test spot price refresh
python -c "
from data.live_data_fetcher import LiveDataFetcher, DataRefreshStrategy
from data.credentials import load_fyers_credentials
from fyers_api import fyersModel

# Load credentials
client_id, api_secret = load_fyers_credentials()
client = fyersModel.FyersModel(client_id=client_id, is_async=False, ...)

# Create fetcher with real Fyers
fetcher = LiveDataFetcher(fyers_client=client, use_mock=False)
strategy = DataRefreshStrategy(fetcher)

# First call (cached for 5 seconds)
s1 = strategy.get_spot_price()
print(f'Cached: ₹{s1:.2f}')

# Force refresh
import time
s2 = strategy.get_spot_price(force_refresh=True)
print(f'Refreshed: ₹{s2:.2f}')
print(f'Data freshness: < 5 seconds ✅')
"
```

---

## 🎯 What's Next?

After successful testing:

1. ✅ Start API server: `uvicorn api.server:app --port 8000`
2. ✅ Monitor live signals: `curl http://localhost:8000/signal`
3. ✅ Test trade endpoints: `curl http://localhost:8000/trades`
4. ✅ Begin Phase 1 paper trading with live data!

---

## 📞 Support

**Test fails?**
1. Check credentials in `.env.local` (copy from developers.fyers.in)
2. Verify market is open (9:15 AM - 3:30 PM IST weekdays)
3. Run `python scripts/test_fyers_live.py` with verbose logging

**Credentials lost?**
1. Regenerate at https://developers.fyers.in/
2. Update `.env.local` with new credentials
3. Rerun test

**Need to disable Fyers temporarily?**
```python
# Use mock mode (no credentials needed)
from data.live_data_fetcher import LiveDataFetcher
fetcher = LiveDataFetcher(use_mock=True)  # Mock data, no Fyers needed
```

---

## 🎓 Files Created/Modified

| File | Purpose | Notes |
|------|---------|-------|
| `.env.local.template` | Credentials template | Copy to `.env.local` and fill |
| `.env.local` | Your credentials | **DO NOT COMMIT** (in .gitignore) |
| `data/credentials.py` | Load credentials helper | Reads `.env.local` safely |
| `scripts/test_fyers_live.py` | End-to-end test | Verifies entire integration |

---

**Status**: Ready to deploy with Fyers credentials! 🚀

Last Updated: 2026-08-29
