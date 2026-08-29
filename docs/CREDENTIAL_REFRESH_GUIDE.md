# Credential Refresh Guide — Do You Need to Update Daily?

**Quick Answer**: ❌ **NO** — You only update credentials when they expire or change.

---

## 🔄 Credential Lifecycle

### What Each Credential Type Does

| Credential | Purpose | Updates | Expires |
|-----------|---------|---------|---------|
| **Client ID** | Identifies your app | Never | Never |
| **API Secret** | Authenticates requests | Never | Never |
| **Access Token** | Session credentials | Auto-refreshed | 24 hours |

---

## 📅 When You Need to Update Credentials

### Case 1: First Time Setup
```bash
# Copy template
cp .env.local.template .env.local

# Edit and add your Client ID + API Secret (from https://developers.fyers.in/)
nano .env.local
```
**Frequency**: One time only

### Case 2: Access Token Expires (Auto-Handled)
The system automatically refreshes the access token:
- ✅ `data/credentials.py` handles token refresh
- ✅ New token auto-saved to `.env.local`
- ✅ No manual intervention needed
- ✅ Transparent to you

**Frequency**: Automatic (every 24 hours internally, but you don't notice)

### Case 3: Credentials Rotated (Security)
If you intentionally rotate Fyers API keys:
```bash
# Edit .env.local with NEW credentials
nano .env.local

# Update these lines only:
FYERS_CLIENT_ID=NEW_CLIENT_ID
FYERS_API_SECRET=NEW_API_SECRET

# Save and restart server
# New token will be fetched automatically
```
**Frequency**: When you rotate keys (quarterly recommended)

### Case 4: Credentials Compromised (Emergency)
If credentials leak:
```bash
# 1. Regenerate at https://developers.fyers.in/
# 2. Update .env.local with new credentials
nano .env.local

# 3. Delete old token
# 4. Restart server
uvicorn api.server:app --port 8000
```
**Frequency**: Only if compromised

---

## ✅ Do You Need to Refresh Every Day?

### Answer: ❌ **NO**

**Why?**
1. ✅ Client ID and API Secret don't expire
2. ✅ Access tokens are auto-refreshed by the system
3. ✅ `.env.local` is persistent across restarts
4. ✅ Data refresh is automatic (data, not credentials)

### What DOES refresh daily?

| Item | What | Frequency | Handled By |
|------|------|-----------|-----------|
| **Market Data** | Spot prices, VIX, option chains | Continuous (every 5s) | `LiveDataFetcher` TTL caching |
| **Access Token** | Session credentials | Auto (every 24h) | `credentials.py` |
| **Cached Data** | Market data cache | Every 5s–3600s | `DataRefreshStrategy` TTL |

**All automatic!** You don't need to do anything.

---

## 🔐 Security: Rotating Credentials (Best Practice)

### Recommended: Quarterly Rotation

**Why rotate?**
- Industry best practice
- Reduces risk if accidentally exposed
- Maintains security posture

**How to rotate:**

#### Step 1: Generate New Credentials
```
1. Go to https://developers.fyers.in/
2. Delete old app or regenerate credentials
3. Copy new Client ID and API Secret
```

#### Step 2: Update `.env.local`
```bash
nano .env.local
# Change these two lines:
FYERS_CLIENT_ID=NEW_ID_HERE
FYERS_API_SECRET=NEW_SECRET_HERE
# Save and exit
```

#### Step 3: Restart API Server
```bash
# Stop current server (Ctrl+C if running)
# Then restart:
uvicorn api.server:app --port 8000
```

#### Step 4: Verify
```bash
# Test with new credentials
python scripts/test_fyers_live.py
# Expected: ✅ ALL END-TO-END TESTS PASSED!
```

---

## 🤔 FAQ: Credential Updates

**Q: Do I need to update credentials every morning?**
> A: ❌ No. They persist across days. Only update if rotated or compromised.

**Q: Does the access token expire every day?**
> A: Yes, access tokens expire in 24 hours, but they're **auto-refreshed** by the system. You don't need to do anything.

**Q: What if the API returns "unauthorized" error?**
> A: Likely causes:
> - Client ID or API Secret is wrong → Check `nano .env.local`
> - Market is closed → Test during 9:15 AM–3:30 PM IST
> - Network issue → Check internet connection
> - Token refresh failed → Restart server

**Q: Can I share my `.env.local` with others?**
> A: ❌ **NEVER**. This contains sensitive credentials. Each person should have their own copy with their own Fyers credentials.

**Q: What if I lose my `.env.local` file?**
> A: Just recreate it:
> ```bash
> cp .env.local.template .env.local
> nano .env.local  # Add your credentials again
> ```

**Q: How often should I rotate Fyers credentials?**
> A: Best practice: **Quarterly (every 3 months)**
> - More frequent: More secure but more work
> - Less frequent: Less secure, easier to manage
> - Industry standard: 90 days

---

## 🚀 Deployment Best Practices

### Production Setup
```bash
# Option 1: Environment Variables (Recommended)
export FYERS_CLIENT_ID="your_client_id"
export FYERS_API_SECRET="your_api_secret"
python scripts/test_fyers_live.py

# Option 2: .env.local File
cp .env.local.template .env.local
nano .env.local  # Add credentials
python scripts/test_fyers_live.py
```

### Never Do This
```bash
# ❌ DON'T hardcode credentials in code
fyers_client_id = "XXXXXXX"  # BAD!

# ❌ DON'T commit .env.local to git
git add .env.local  # BAD! It's in .gitignore for a reason

# ❌ DON'T share credentials in messages
# "My Client ID is XXXXXXX"  # BAD!

# ❌ DON'T print credentials to logs
print(client_id)  # BAD!
```

### Always Do This
```bash
# ✅ Store in .env.local (local only)
# ✅ Load via credentials.py (safe)
# ✅ Never commit to git (it's in .gitignore)
# ✅ Rotate quarterly (security best practice)
# ✅ Check git before pushing (verify .env.local not included)
git status | grep ".env.local"  # Should show nothing
```

---

## 🔄 Data Refresh (Different from Credentials)

### Important: Data ≠ Credentials

**Data Refresh** (happens automatically):
- Spot price: Every 5 seconds
- VIX: Every 60 seconds  
- Option chain: Every 30 seconds
- Market DF: Every 3600 seconds

**Credential Refresh** (happens automatically):
- Access token: Every 24 hours
- Client ID + Secret: Never (until you rotate)

**You don't need to do anything for either!**

---

## ✅ Summary

| Action | When | How | Frequency |
|--------|------|-----|-----------|
| **Setup .env.local** | First time | `cp .env.local.template .env.local` + edit | Once |
| **Rotate Credentials** | Security practice | Regenerate at Fyers + update .env.local | Quarterly |
| **Refresh Access Token** | Auto | System does it automatically | 24h (auto) |
| **Refresh Market Data** | Auto | System does it automatically | 5s–3600s (auto) |
| **Restart Server** | After config changes | `Ctrl+C` + restart uvicorn | As needed |

**Bottom line**: You only manually update `.env.local` when you rotate credentials (quarterly recommended). Everything else is automatic!

---

## 📞 Support

**Question**: "Do I need to update credentials daily?"  
**Answer**: ❌ No. Only update when rotated (quarterly) or compromised (emergency).

**Question**: "How do I know if my token expired?"  
**Answer**: You don't! The system auto-refreshes it. If you see "unauthorized" errors:
1. Check `.env.local` has correct credentials
2. Restart the server
3. Try again

**Question**: "Can I see my credentials in logs?"  
**Answer**: ❌ No. They're never logged (see `data/credentials.py` — no print statements).

---

**Status**: Credentials are persistent and auto-managed. You only need to update them when rotating keys (quarterly). 🎉

Last Updated: 2026-08-29
