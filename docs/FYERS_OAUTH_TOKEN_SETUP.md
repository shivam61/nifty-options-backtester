# Fyers OAuth Token Setup — Get Live Data Access

**Status**: ⏳ REQUIRED for live data  
**Time**: 5-10 minutes  
**Benefit**: Access to real Nifty spot prices, VIX, option chains

---

## Why You Need OAuth Token

Your Fyers credentials (Client ID + API Secret) authenticate your APP, but the **OAuth token** authenticates YOUR ACCOUNT for data access.

Think of it as:
- **Client ID + Secret** = "App is legitimate"
- **OAuth Token** = "User authorized this app to access my account"

---

## Step-by-Step OAuth Setup

### Step 1: Get Authorization URL

```bash
source .venv/bin/activate && python3 << 'EOF'
from fyers_apiv3 import fyersModel
from data.credentials import load_fyers_credentials

client_id, api_secret = load_fyers_credentials()

# Create client for auth flow
client = fyersModel.FyersModel(
    is_async=False,
    client_id=client_id,
    log_level="ERROR"
)

# Get authorization URL
auth_url = client.get_auth_url()

print("=" * 80)
print("STEP 1: AUTHORIZATION URL")
print("=" * 80)
print("\n📋 Copy this URL and open in your browser:\n")
print(auth_url)
print("\n" + "=" * 80)
EOF
```

**Expected Output:**
```
https://api-t2.fyers.in/api/oauth/authorize?client_id=W4JMYLVR9Y-100&response_type=code&state=sample_state&scope=full_access&redirect_uri=http://localhost:3000&nonce=...
```

### Step 2: Authorize in Browser

1. Copy the URL from above
2. Open in your browser
3. Log in with your **Fyers account** credentials
4. Click "Authorize" or "Allow"
5. You'll be redirected to: `http://localhost:3000?code=XXXXX&state=...`
6. **Copy the `code=` value** (the part after `code=` and before `&state`)

Example:
```
URL after auth: http://localhost:3000?code=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...&state=sample_state

Your auth code: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

### Step 3: Exchange Auth Code for Token

```bash
source .venv/bin/activate && python3 << 'EOF'
from fyers_apiv3 import fyersModel
from data.credentials import load_fyers_credentials, save_fyers_access_token

client_id, api_secret = load_fyers_credentials()

# Create client for auth flow
client = fyersModel.FyersModel(
    is_async=False,
    client_id=client_id,
    log_level="ERROR"
)

print("=" * 80)
print("STEP 2: EXCHANGE AUTH CODE FOR TOKEN")
print("=" * 80)

# Get auth code from user
auth_code = input("\n📋 Paste your auth code from browser: ").strip()

if not auth_code:
    print("❌ No auth code provided")
    exit(1)

try:
    # Set token with auth code (this exchanges it for actual token)
    client.set_token(auth_code)
    
    # Get the actual access token
    access_token = client.token
    
    print(f"\n✅ Success! Access token received:")
    print(f"   Token: {access_token[:50]}...")
    
    # Save token to .env.local
    if save_fyers_access_token(access_token):
        print(f"\n✅ Token saved to .env.local")
        print(f"\nYou can now use live Fyers data!")
    else:
        print(f"\n⚠️  Failed to save token automatically")
        print(f"   Manually add to .env.local:")
        print(f"   FYERS_ACCESS_TOKEN={access_token}")
        
except Exception as e:
    print(f"❌ Error exchanging auth code: {e}")
    print(f"\nMake sure:")
    print(f"  - Auth code is correct (copy the entire code after code=)")
    print(f"  - Auth code hasn't expired (try again if > 10 min)")
    print(f"  - Fyers credentials are valid in .env.local")

EOF
```

### Step 4: Verify Token Works

```bash
source .venv/bin/activate && python3 << 'EOF'
from fyers_apiv3 import fyersModel
from data.credentials import load_fyers_credentials, get_fyers_access_token
import json

client_id, api_secret = load_fyers_credentials()
access_token = get_fyers_access_token()

if not access_token:
    print("❌ No access token found in .env.local")
    print("   Follow steps 1-3 above to get token")
    exit(1)

# Create client with token
client = fyersModel.FyersModel(
    is_async=False,
    client_id=client_id,
    token=access_token,
    log_level="ERROR"
)

print("=" * 80)
print("STEP 3: VERIFY LIVE DATA ACCESS")
print("=" * 80)

# Test 1: Fetch live Nifty spot price
print("\n1️⃣  Fetching live NIFTY50 spot price...")
try:
    result = client.quotes({"symbols": ["NSE:NIFTY50"]})
    
    if result.get('s') == 'ok' and 'd' in result:
        data = result['d']['NSE:NIFTY50']
        print(f"✅ Live Nifty Price: ₹{data.get('ltp', 'N/A')}")
        print(f"   Bid: {data.get('bid', 'N/A')}, Ask: {data.get('ask', 'N/A')}")
    else:
        print(f"❌ Error: {result.get('message', 'Unknown error')}")
except Exception as e:
    print(f"❌ Error: {e}")

# Test 2: Fetch live India VIX
print("\n2️⃣  Fetching live India VIX...")
try:
    result = client.quotes({"symbols": ["NSEIND:INDIAVIX"]})
    
    if result.get('s') == 'ok' and 'd' in result:
        data = result['d']['NSEIND:INDIAVIX']
        print(f"✅ Live VIX: {data.get('ltp', 'N/A')}")
        print(f"   Bid: {data.get('bid', 'N/A')}, Ask: {data.get('ask', 'N/A')}")
    else:
        print(f"❌ Error: {result.get('message', 'Unknown error')}")
except Exception as e:
    print(f"❌ Error: {e}")

# Test 3: Fetch live option chain
print("\n3️⃣  Fetching live option chain...")
try:
    # Get option chain for current expiry
    result = client.optionchain({"mode": "LTP", "symbol": "NSE:NIFTY50"})
    
    if result.get('s') == 'ok':
        data = result.get('d', {})
        if 'options' in data:
            options = data['options']
            print(f"✅ Live option chain: {len(options)} strikes")
            
            # Show first 3 strikes
            for i, option in enumerate(options[:3]):
                print(f"\n   Strike {i+1}: {option.get('strikePrice', 'N/A')}")
                print(f"   - Call LTP: ₹{option.get('call', {}).get('ltp', 'N/A')}")
                print(f"   - Put LTP: ₹{option.get('put', {}).get('ltp', 'N/A')}")
        else:
            print(f"⚠️  No options in response")
    else:
        print(f"❌ Error: {result.get('message', 'Unknown error')}")
except Exception as e:
    print(f"❌ Error: {e}")

print("\n" + "=" * 80)
print("✅ LIVE DATA VERIFICATION COMPLETE")
print("=" * 80)
print("""
If all tests passed:
  ✅ You have live data access!
  ✅ Restart your API server
  ✅ All endpoints will use real Fyers data
  
Next: Restart API server
  uvicorn api.server:app --port 8000
""")

EOF
```

---

## Complete OAuth Flow (Quick Reference)

```bash
# 1. Get auth URL
python3 scripts/get_fyers_auth_url.py

# 2. Open URL in browser, authorize, copy auth code

# 3. Exchange for token
python3 scripts/exchange_auth_code.py

# 4. Verify live data works
python3 scripts/verify_live_data.py

# 5. Restart API server
uvicorn api.server:app --port 8000

# 6. Check live data
curl http://localhost:8000/signal | jq '.spot, .vix'
```

---

## Troubleshooting

### Issue: "Invalid auth code"
- Make sure you copied the ENTIRE code value
- Don't include `code=` prefix, just the value after it
- Try again if more than 10 minutes have passed

### Issue: "Please provide valid token" still appears
- Make sure token was saved to `.env.local`
- Restart API server after saving token
- Check `.env.local` has the token on line 3

### Issue: "Market data not available"
- Verify auth happened during market hours (9:15 AM - 3:30 PM IST)
- Market may be closed, try again during trading hours
- Check Fyers account is active and funded

### Issue: Can't open auth URL
- URL might be very long, try copying to text editor first
- Or manually construct: `https://api-t2.fyers.in/api/oauth/authorize?client_id=YOUR_CLIENT_ID&response_type=code&state=sample_state&scope=full_access&redirect_uri=http://localhost:3000`

---

## Token Lifecycle

| Event | Action | Frequency |
|-------|--------|-----------|
| **Initial Setup** | Get auth URL → Authorize → Exchange code for token | Once |
| **Token Refresh** | System auto-refreshes token | Every 24 hours (automatic) |
| **Token Rotation** | Regenerate new token via OAuth flow | Quarterly (security) |
| **Token Expiration** | Very rare; regenerate if needed | Seldom |

---

## What Works After Token Setup

✅ **Live Nifty Spot Prices** — Real-time quotes  
✅ **Live VIX Levels** — Real India VIX data  
✅ **Live Option Chains** — Full option data with Greeks  
✅ **Live Bid-Ask Spreads** — Real market spreads  
✅ **All API Endpoints** — Full data without mocking  

---

## Security

✅ Token is stored **locally only** (`.env.local`)  
✅ Token is **never committed** to git  
✅ Token is **never logged** or printed  
✅ Token is **encrypted** by Fyers API  
✅ Token can be **revoked anytime** from Fyers settings  

---

**Status**: ⏳ Ready for OAuth setup  
**Next Action**: Follow Step 1 above to get auth URL

Last Updated: 2026-08-29
