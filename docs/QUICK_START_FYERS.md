# Quick Start: Fyers API Testing (3 Minutes)

## 🚀 TL;DR - 4 Commands to Test

```bash
# 1. Copy credentials template
cp .env.local.template .env.local

# 2. Edit with your Fyers credentials (see https://developers.fyers.in/)
nano .env.local

# 3. Install dependencies
pip install fyers-apiv3 python-dotenv fastapi uvicorn

# 4. Run end-to-end test
python scripts/test_fyers_live.py
```

**Expected output**: ✅ ALL END-TO-END TESTS PASSED!

---

## 📍 Where to Get Your Credentials

1. Visit: https://developers.fyers.in/
2. Log in with your Fyers account
3. Copy your **Client ID** and **API Secret**
4. Paste into `.env.local`

---

## 📋 What Gets Tested

✅ Credentials loading  
✅ Fyers client initialization  
✅ Real Nifty spot price  
✅ Real VIX level  
✅ Real option chain  
✅ Data refresh strategy  
✅ API endpoints with real data  

---

## ✅ Success Indicators

When test passes, you'll see:
```
✅ ALL END-TO-END TESTS PASSED!
✅ Credentials loaded successfully
✅ Fyers client initialized
✅ Real spot price fetched: ₹25,243.50
✅ Real VIX fetched: 17.23
✅ Real option chain fetched: 12 strikes
```

---

## 🔐 Security

- Credentials stored in `.env.local` (LOCAL ONLY)
- `.env.local` is in `.gitignore` (never committed)
- Never share `.env.local` file
- Safe to delete after testing

---

## 🐛 Troubleshooting

| Error | Fix |
|-------|-----|
| `No credentials found` | Make sure `.env.local` exists and has your credentials |
| `fyers-apiv3 not installed` | Run: `pip install fyers-apiv3` |
| `Market closed error` | Test only during 9:15 AM - 3:30 PM IST (market hours) |
| `Invalid credentials` | Double-check Client ID and API Secret at https://developers.fyers.in/ |

---

## 🎯 Next Steps

After test passes:

```bash
# Start live API server
uvicorn api.server:app --port 8000

# In another terminal, test live signal
curl http://localhost:8000/signal

# Then: Begin Phase 1 paper trading! 🎉
```

---

**Full guide**: See `docs/FYERS_CREDENTIAL_SETUP.md` for detailed setup instructions.

---

*Last updated: 2026-08-29*
