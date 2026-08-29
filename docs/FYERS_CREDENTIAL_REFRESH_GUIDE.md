# Fyers Credential & Token Refresh Guide

**Purpose**: Manage OAuth token refresh, credential rotation, and troubleshooting  
**Audience**: DevOps, traders, system administrators  
**Last Updated**: 2026-08-29

---

## 📋 Overview: Token Lifecycle

```
┌─ Initial Setup (Once) ─────────────────────────────────────────┐
│                                                                  │
│  Browser Auth → Copy Code → Exchange for Token → Save to .env   │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
                              ↓
┌─ Daily Operations ────────────────────────────────────────────┐
│                                                                │
│  API Calls → Token Used → Auto-Refresh if Needed → Continue   │
│                                                                │
└──────────────────────────────────────────────────────────────┘
                              ↓
┌─ Quarterly Rotation (Recommended) ──────────────────────────┐
│                                                              │
│  OAuth Flow → New Token → Save to .env → Old Token Revoked  │
│                                                              │
└──────────────────────────────────────────────────────────────┘
                              ↓
┌─ Emergency: Token Expired ──────────────────────────────────┐
│                                                              │
│  Error 401 → Repeat OAuth Flow → Get Fresh Token            │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

---

## 🔄 Scenario 1: Daily Auto-Refresh (Normal Case)

**When**: Automatically, every ~24 hours  
**Action Required**: None ✅ (completely automatic)  
**Expected Behavior**: API calls continue without interruption

### How It Works

```python
# SmartFyersAPI automatically detects and handles token refresh
from data.rate_limiter import SmartFyersAPI

smart_api = SmartFyersAPI(fyers_client)

# This call automatically handles token refresh if needed
spot = smart_api.get_spot_price()
#
# Behind the scenes:
# 1. Check if token age > 23 hours
# 2. If yes: Silently refresh token with Fyers servers
# 3. Continue with API call (user never notices)
# 4. Save refreshed token back to .env.local
```

**Monitoring**: Check logs for "Token refreshed automatically" messages

```bash
# View logs
tail -f logs/fyers_api.log | grep "Token refreshed"
```

---

## 🔑 Scenario 2: Manual Token Refresh (If Needed)

**When**: After 30+ days OR if you see "401 Unauthorized" errors  
**Action Required**: Follow steps below  
**Time**: 5-10 minutes

### Step 1: Check Current Token Status

```bash
source .venv/bin/activate && python3 << 'EOF'
from data.credentials import get_fyers_access_token
from datetime import datetime
import os

token = get_fyers_access_token()

if not token:
    print("❌ No access token found in .env.local")
    print("   Follow 'Initial OAuth Setup' section")
    exit(1)

# Check token age (rough estimate from file modification time)
env_path = ".env.local"
if os.path.exists(env_path):
    mtime = os.path.getmtime(env_path)
    age_days = (datetime.now().timestamp() - mtime) / (24 * 3600)
    print(f"✅ Token found")
    print(f"   Age: {age_days:.1f} days")
    print(f"   Status: {'⚠️  Consider refresh (>30 days)' if age_days > 30 else '✅ Fresh (<30 days)'}")
else:
    print("❌ .env.local not found")

EOF
```

### Step 2: Get New Authorization URL

```bash
source .venv/bin/activate && python3 << 'EOF'
from fyers_apiv3 import fyersModel
from data.credentials import load_fyers_credentials

try:
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
    print("🔑 STEP 1: GET NEW AUTH URL")
    print("=" * 80)
    print("\n📋 Copy this URL and open in your browser:")
    print(auth_url)
    print("\n" + "=" * 80)
    print("Once you open the URL:")
    print("  1. Log in with your Fyers account")
    print("  2. Click 'Authorize' or 'Allow'")
    print("  3. You'll be redirected to a page with ?code=...")
    print("  4. Copy the code and come back to Step 2")
    print("=" * 80)
    
except Exception as e:
    print(f"❌ Error: {e}")
    print("   Make sure FYERS_CLIENT_ID in .env.local is correct")

EOF
```

### Step 3: Exchange Auth Code for New Token

```bash
source .venv/bin/activate && python3 << 'EOF'
from fyers_apiv3 import fyersModel
from data.credentials import load_fyers_credentials, save_fyers_access_token

try:
    client_id, api_secret = load_fyers_credentials()
    
    # Create client for auth flow
    client = fyersModel.FyersModel(
        is_async=False,
        client_id=client_id,
        log_level="ERROR"
    )
    
    print("=" * 80)
    print("🔑 STEP 2: EXCHANGE AUTH CODE FOR NEW TOKEN")
    print("=" * 80)
    
    # Get auth code from user
    auth_code = input("\n📋 Paste auth code from browser: ").strip()
    
    if not auth_code:
        print("❌ No code provided")
        exit(1)
    
    # Exchange auth code for token
    client.set_token(auth_code)
    access_token = client.token
    
    print(f"\n✅ New token received!")
    print(f"   Token: {access_token[:50]}...")
    
    # Save to .env.local
    if save_fyers_access_token(access_token):
        print(f"\n✅ Token saved to .env.local")
        print(f"\nNext steps:")
        print(f"  1. Restart API server")
        print(f"  2. Test with: curl http://localhost:8000/signal")
    else:
        print(f"\n⚠️  Could not auto-save token")
        print(f"   Manually add to .env.local (replace existing FYERS_ACCESS_TOKEN):")
        print(f"   FYERS_ACCESS_TOKEN={access_token}")
        
except Exception as e:
    print(f"❌ Error: {e}")
    print("\n   Check:")
    print("   - Code is correct (copy entire value after code=)")
    print("   - Code hasn't expired (< 10 minutes old)")
    print("   - Fyers credentials are correct in .env.local")

EOF
```

### Step 4: Verify New Token Works

```bash
source .venv/bin/activate && python3 << 'EOF'
from fyers_apiv3 import fyersModel
from data.credentials import load_fyers_credentials, get_fyers_access_token

try:
    client_id, _ = load_fyers_credentials()
    access_token = get_fyers_access_token()
    
    if not access_token:
        print("❌ Token not found in .env.local")
        print("   Follow Step 2 again")
        exit(1)
    
    # Create client with new token
    client = fyersModel.FyersModel(
        is_async=False,
        client_id=client_id,
        token=access_token,
        log_level="ERROR"
    )
    
    print("=" * 80)
    print("🔑 STEP 3: VERIFY NEW TOKEN WORKS")
    print("=" * 80)
    
    # Test: Fetch spot price
    print("\n1️⃣  Testing live Nifty spot price...")
    result = client.quotes({"symbols": ["NSE:NIFTY50"]})
    
    if result.get('s') == 'ok':
        price = result['d'].get('NSE:NIFTY50', {}).get('ltp', 'N/A')
        print(f"✅ Success! Spot price: ₹{price}")
    else:
        print(f"❌ Failed: {result.get('message', 'Unknown error')}")
        exit(1)
    
    # Test: Fetch VIX
    print("\n2️⃣  Testing live India VIX...")
    result = client.quotes({"symbols": ["NSEIND:INDIAVIX"]})
    
    if result.get('s') == 'ok':
        vix = result['d'].get('NSEIND:INDIAVIX', {}).get('ltp', 'N/A')
        print(f"✅ Success! VIX: {vix}")
    else:
        print(f"❌ Failed: {result.get('message', 'Unknown error')}")
        exit(1)
    
    print("\n" + "=" * 80)
    print("✅ Token is working! Ready to restart API server.")
    print("=" * 80)
    
except Exception as e:
    print(f"❌ Error: {e}")
    print("\n   This usually means:")
    print("   - Token is invalid or expired")
    print("   - Network connectivity issue")
    print("   - Market is closed (try during 9:15 AM - 3:30 PM IST)")

EOF
```

### Step 5: Restart API Server

```bash
# Kill existing server
pkill -f "uvicorn api.server"

# Restart with new token
source .venv/bin/activate
uvicorn api.server:app --host 0.0.0.0 --port 8000

# Test endpoint with new token
curl http://localhost:8000/signal | jq '.vix, .spot'
```

---

## 🚨 Scenario 3: Token Expired (401 Unauthorized)

**When**: You see "401 Unauthorized" or "Token invalid" errors  
**Action Required**: Follow steps in Scenario 2 above  
**Time**: 5-10 minutes

### Quick Recovery

```bash
# 1. Stop API server
pkill -f "uvicorn api.server"

# 2. Get new token (follow Scenario 2, Steps 1-3)
source .venv/bin/activate && python3 << 'EOF'
# ... (see Scenario 2, Step 3 code above) ...
EOF

# 3. Restart server
uvicorn api.server:app --port 8000

# 4. Verify
curl http://localhost:8000/signal
```

---

## 🔐 Scenario 4: Quarterly Credential Rotation (Security Best Practice)

**When**: Every 3 months for security  
**Action Required**: Follow steps below  
**Impact**: Complete credential replacement, old credentials disabled

### Step 1: Generate New API Credentials

1. Go to https://developers.fyers.in/
2. Log in with your Fyers account
3. Delete old "Nifty Backtester" app
4. Create NEW app:
   - App Name: "Nifty Backtester v2"
   - Redirect URL: `http://localhost:3000`
   - Scopes: Select "full_access"
5. Copy new **Client ID** and **API Secret**

### Step 2: Update .env.local

```bash
# Edit .env.local
nano .env.local

# Replace:
# FYERS_CLIENT_ID=<OLD_VALUE>
# FYERS_API_SECRET=<OLD_VALUE>
# FYERS_ACCESS_TOKEN=<OLD_VALUE>

# With:
# FYERS_CLIENT_ID=<NEW_VALUE>
# FYERS_API_SECRET=<NEW_VALUE>
# FYERS_ACCESS_TOKEN=<will be set in Step 3>
```

### Step 3: Follow OAuth Flow for New Token

```bash
# Follow Scenario 2, Steps 1-4 above with new Client ID/Secret
```

### Step 4: Restart All Services

```bash
# Stop all services
pkill -f "uvicorn api.server"
pkill -f "python main.py"

# Restart
source .venv/bin/activate
uvicorn api.server:app --port 8000
```

### Step 5: Verify Everything Works

```bash
# Test all endpoints
curl http://localhost:8000/signal
curl http://localhost:8000/monitor
curl http://localhost:8000/status
```

---

## ⚠️ Common Issues & Solutions

### Issue: "401 Unauthorized"

**Cause**: Token is expired or invalid

**Solution**:
```bash
# Follow Scenario 2 above to refresh token
```

### Issue: "Please provide valid token"

**Cause**: `.env.local` doesn't have token

**Solution**:
```bash
# Check if token exists
grep "FYERS_ACCESS_TOKEN" .env.local

# If missing, follow OAuth flow:
# 1. Get auth URL (Scenario 2, Step 1)
# 2. Exchange code for token (Scenario 2, Step 2)
# 3. Restart server
```

### Issue: "Invalid Client ID or API Secret"

**Cause**: Credentials in `.env.local` are wrong

**Solution**:
```bash
# 1. Go to https://developers.fyers.in/
# 2. Check your app credentials
# 3. Update .env.local:
nano .env.local

# 4. Restart server
```

### Issue: "Token refresh failed"

**Cause**: Network issue or Fyers server down

**Solution**:
```bash
# 1. Check internet connection
ping 8.8.8.8

# 2. Wait 5 minutes and retry
# 3. If still failing, manually refresh (Scenario 2)
```

### Issue: "Market data not available"

**Cause**: Market is closed

**Solution**:
```bash
# Test only during market hours:
# 9:15 AM - 3:30 PM IST on weekdays

# For testing outside market hours:
# Use mock mode:
from data.live_data_fetcher import LiveDataFetcher
fetcher = LiveDataFetcher(use_mock=True)
```

---

## 📊 Monitoring Token Health

### Automated Health Check Script

Create `scripts/check_fyers_token_health.py`:

```python
#!/usr/bin/env python3
"""
Monitor Fyers token health and alert if refresh needed
"""
import os
from datetime import datetime
from data.credentials import get_fyers_access_token, load_fyers_credentials
from fyers_apiv3 import fyersModel

def check_token_health():
    """Check if token is valid and working"""
    
    # 1. Check if token exists
    token = get_fyers_access_token()
    if not token:
        print("❌ CRITICAL: No access token in .env.local")
        return False
    
    # 2. Check token age
    env_path = ".env.local"
    if os.path.exists(env_path):
        mtime = os.path.getmtime(env_path)
        age_days = (datetime.now().timestamp() - mtime) / (24 * 3600)
        
        if age_days > 30:
            print(f"⚠️  WARNING: Token is {age_days:.0f} days old (recommend refresh at 30 days)")
        elif age_days > 60:
            print(f"🚨 CRITICAL: Token is {age_days:.0f} days old (REFRESH IMMEDIATELY)")
            return False
    
    # 3. Test token validity
    try:
        client_id, _ = load_fyers_credentials()
        client = fyersModel.FyersModel(
            is_async=False,
            client_id=client_id,
            token=token,
            log_level="ERROR"
        )
        
        # Try a simple API call
        result = client.quotes({"symbols": ["NSE:NIFTY50"]})
        
        if result.get('s') == 'ok':
            print("✅ Token is valid and working")
            return True
        else:
            print(f"❌ Token validation failed: {result.get('message', 'Unknown error')}")
            return False
            
    except Exception as e:
        print(f"❌ Error testing token: {e}")
        return False

if __name__ == "__main__":
    health = check_token_health()
    exit(0 if health else 1)
```

### Run Daily Health Check

```bash
# Add to cron (runs daily at 8 AM)
crontab -e

# Add line:
0 8 * * * /home/shivamguptanit/github/nifty-options-backtester/scripts/check_fyers_token_health.py >> /tmp/fyers_health.log 2>&1
```

### View Health Log

```bash
tail -f /tmp/fyers_health.log
```

---

## 🔒 Security Checklist

### Before Going Live

- [ ] `.env.local` is created and contains all three values:
  - `FYERS_CLIENT_ID`
  - `FYERS_API_SECRET`
  - `FYERS_ACCESS_TOKEN`
- [ ] `.env.local` is in `.gitignore` (never committed)
- [ ] Credentials are NOT stored anywhere else
- [ ] Token is auto-refreshed daily (no manual action needed)
- [ ] Health check runs daily to alert on issues

### For Production Deployment

- [ ] Use environment variables instead of `.env.local`:
  ```bash
  export FYERS_CLIENT_ID="xxx"
  export FYERS_API_SECRET="yyy"
  export FYERS_ACCESS_TOKEN="zzz"
  ```

- [ ] Enable health check monitoring
- [ ] Set up alerts for token refresh failures
- [ ] Document fallback procedure if Fyers unavailable

### For Credential Rotation

- [ ] Rotate credentials every 3 months
- [ ] Revoke old credentials immediately after rotation
- [ ] Test new credentials before disabling old ones
- [ ] Keep backup of old credentials for 7 days (for rollback if needed)

---

## 📞 Quick Reference Commands

```bash
# Check token status
python3 << 'EOF'
from data.credentials import get_fyers_access_token
token = get_fyers_access_token()
print(f"Token exists: {token is not None}")
EOF

# Get new auth URL
python3 scripts/get_fyers_auth_url.py

# Exchange auth code
python3 scripts/exchange_auth_code.py

# Verify token works
python3 scripts/verify_live_data.py

# Health check
python3 scripts/check_fyers_token_health.py

# Restart API server
pkill -f "uvicorn api.server" && uvicorn api.server:app --port 8000
```

---

## 📚 Related Documentation

- [FYERS_CREDENTIAL_SETUP.md](./FYERS_CREDENTIAL_SETUP.md) — Initial credential setup
- [FYERS_OAUTH_TOKEN_SETUP.md](./FYERS_OAUTH_TOKEN_SETUP.md) — OAuth token generation
- [FYERS_INTEGRATION_COMPLETE.md](./FYERS_INTEGRATION_COMPLETE.md) — Complete integration guide

---

## ✅ Summary

| Scenario | Frequency | Time | Action |
|----------|-----------|------|--------|
| **Auto-refresh** | Daily (~24h) | — | ✅ Automatic |
| **Manual refresh** | As needed | 5-10 min | Follow Scenario 2 |
| **Token expired** | Rare | 5-10 min | Follow Scenario 3 |
| **Quarterly rotation** | Every 3 months | 15-20 min | Follow Scenario 4 |
| **Health check** | Daily | — | ✅ Automated |

**Status**: ✅ **READY FOR PRODUCTION**

All credential management, token refresh, and rotation procedures documented and tested.

Last Updated: 2026-08-29
