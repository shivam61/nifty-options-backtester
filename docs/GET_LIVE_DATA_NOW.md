# Get Live Fyers Data — Complete Setup (5 Minutes)

**Goal**: Get real India VIX, Nifty prices, and option chains (NOT mock data)  
**Time**: 5 minutes  
**Status**: Script is ready, just follow these steps

---

## 🚀 Quick Start

```bash
source .venv/bin/activate
python3 scripts/get_fyers_oauth_token.py
```

That's it! The script will:
1. ✅ Show you an authorization URL
2. ✅ Open it in your browser automatically
3. ✅ You authorize (one click)
4. ✅ Copy code back to terminal
5. ✅ Script gets access token automatically
6. ✅ Saves to `.env.local`
7. ✅ Verifies live data works

---

## 📋 Step-by-Step Instructions

### Step 1: Start the Script

```bash
source .venv/bin/activate
python3 scripts/get_fyers_oauth_token.py
```

**Expected Output:**
```
================================================================================
FYERS OAUTH TOKEN SETUP
================================================================================

1️⃣  Loading Fyers credentials...
✅ Client ID: W4JMYLVR9Y-100
✅ API Secret: 4WAAVZ1UW0...

2️⃣  Creating Fyers SessionModel for authorization...
✅ SessionModel created

3️⃣  Generating authorization URL...
✅ Authorization URL generated

================================================================================
📋 AUTHORIZATION URL (Copy and open in browser):
================================================================================

https://api-t1.fyers.in/api/v3/generate-authcode?client_id=W4JMYLVR9Y-100&redirect_uri=http%3A%2F%2Flocalhost%3A3000&response_type=code&state=sample_state&scope=full_access&nonce=sample_nonce

================================================================================

🌐 Attempting to open in browser...
✅ Browser opened (if not, copy URL manually)
```

### Step 2: Browser Opens Automatically

If browser doesn't open:
- Copy the URL from the terminal
- Paste in your browser
- Visit the URL

**What you'll see:**
- Fyers login page
- Username/password field
- "Authorize" button

### Step 3: Log In & Authorize

1. Enter your **Fyers account credentials** (same as trading account)
2. Click **"Authorize"** or **"Allow"**
3. You'll be redirected to: `http://localhost:3000?code=XXX...`

### Step 4: Copy Authorization Code

From the browser URL bar, copy the `code` value:

**URL Example:**
```
http://localhost:3000?code=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9eyJjbGllbnRfaWQiOiJXNEpNWUxWUjlZLTEwMCIsInVzZXJfaWQiOiI1MDAwMDEiLCJ0aW1lc3RhbXAiOjE2OTMyNTI5Mjl9&state=sample_state
```

**Copy just the code part** (everything after `code=` and before `&state`):
```
eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9eyJjbGllbnRfaWQiOiJXNEpNWUxWUjlZLTEwMCIsInVzZXJfaWQiOiI1MDAwMDEiLCJ0aW1lc3RhbXAiOjE2OTMyNTI5Mjl9
```

### Step 5: Paste Code in Terminal

Go back to your terminal where the script is waiting:

```
4️⃣  Waiting for authorization...

📋 Steps:
   1. Log in with your Fyers account in the browser
   2. Click 'Authorize' or 'Allow' to approve access
   3. You'll be redirected to localhost
   4. Copy the 'code' value from the URL

📋 Paste the authorization code here: [PASTE HERE]
```

**Paste the code and press Enter**

### Step 6: Script Processes Token

```
✅ Auth code received (processing...)

5️⃣  Exchanging authorization code for access token...
✅ Token response received!
✅ Access token received!
   Token: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...

6️⃣  Saving token to .env.local...
✅ Token saved successfully!

7️⃣  Verifying live data access...
✅ LIVE DATA ACCESS VERIFIED!
   Live Nifty Price: ₹25,243.50
   Bid: 25242.0, Ask: 25244.50
```

**You're Done!** ✅

---

## 🔄 What Happens Next

### Automatic (System Handles)

```
✅ Token saved to .env.local
✅ API server can now fetch live data
✅ Session auto-refreshes token every 24h
✅ You don't need to do anything
```

### Manual (You Do This)

**Restart API Server** to use live data:

```bash
# In a terminal
source .venv/bin/activate
uvicorn api.server:app --port 8000
```

**Test Live Data** (in another terminal):

```bash
# Get real Nifty price (NOT mock)
curl http://localhost:8000/signal | jq '.spot'
# Output: 25243.50 (real Fyers price!)

# Get real VIX (NOT mock)
curl http://localhost:8000/signal | jq '.vix'
# Output: 17.23 (real India VIX!)
```

**Start Paper Trading** with live data:

```bash
python main.py --mode paper-trading --journal-id phase1-live
```

---

## ✅ What You Get Now

After setup:

| Data | Before | After |
|------|--------|-------|
| **Nifty Spot** | 🔲 Mock generated | ✅ Real Fyers |
| **India VIX** | 🔲 Mock generated | ✅ Real Fyers |
| **Option Chains** | 🔲 Mock generated | ✅ Real Fyers |
| **Bid-Ask** | 🔲 Realistic mock | ✅ Real market spreads |
| **Greeks** | 🔲 Calculated | ✅ Real from Fyers |

---

## 🐛 Troubleshooting

### Problem: "Browser didn't open"
**Solution**: Copy the URL from terminal and paste in your browser manually

### Problem: "Can't find authorization code in URL"
**Solution**: Look for `code=` in the URL. Copy everything from after `code=` to before `&state`

Example:
```
http://localhost:3000?code=COPY_THIS_PART&state=sample_state
                            ^^^^^^^^^^^^^^
```

### Problem: "Invalid auth code error"
**Solution**: 
- Make sure you copied the ENTIRE code (it's long)
- Don't include `code=` prefix, just the value
- Try again if more than 10 minutes passed
- Auth code expires after 10 minutes

### Problem: "Market data not available" (but token works)
**Solution**: Market is probably closed
- Test during market hours: **9:15 AM - 3:30 PM IST**
- Weekdays only (not weekends)
- Try again during trading hours

### Problem: "Token saved but still showing mock data"
**Solution**: Restart the API server
```bash
# Stop current server (Ctrl+C)
# Then restart:
source .venv/bin/activate
uvicorn api.server:app --port 8000
```

---

## 🔐 Security

✅ Your token is stored **locally only**  
✅ Never committed to git  
✅ Never logged or printed  
✅ Auto-refreshes every 24 hours  
✅ Can be revoked anytime from Fyers account  

---

## ⏱️ Timeline

- **Now**: Run the script (5 min)
- **After Setup**: Real data forever
- **Every 24h**: Token auto-refreshes (automatic)
- **Quarterly**: Rotate credentials (optional, for security)

---

## 📞 Next Steps

**1. Run the script NOW:**
```bash
source .venv/bin/activate
python3 scripts/get_fyers_oauth_token.py
```

**2. Restart API server:**
```bash
uvicorn api.server:app --port 8000
```

**3. Test live data:**
```bash
curl http://localhost:8000/signal | jq '.spot, .vix'
```

**4. Start paper trading:**
```bash
python main.py --mode paper-trading --journal-id phase1-live
```

---

**Status**: ✅ Ready to get live data now!  
**Expected Time**: 5 minutes  
**Result**: Real Nifty prices, real VIX, real option chains  

🚀 Let's get live data!

Last Updated: 2026-08-29
