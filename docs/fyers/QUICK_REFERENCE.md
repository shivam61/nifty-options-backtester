# Fyers Integration - Quick Reference

## 🚀 Quick Start (3 Steps)

```bash
# 1. Generate token
python scripts/generate_fyers_token.py

# 2. Check if token works
python scripts/check_fyers_token.py

# 3. Validate full integration
python data/fyers_live_data.py
```

## 📖 Common Code Snippets

### Initialize Client
```python
from data.fyers_live_data import FyersLiveDataClient
client = FyersLiveDataClient()
```

### Get Market Levels
```python
spot = client.get_nifty_spot_price()    # ₹24,487.50
vix = client.get_india_vix()             # 14.23
atm = client.get_atm_strike()            # ₹24,500
```

### Get Option Chain
```python
from datetime import date

strikes = [24400, 24450, 24500, 24550, 24600]
expiry = date(2026, 4, 24)

chain = client.get_option_chain_quotes(strikes, expiry)
# Returns DataFrame with: strike, option_type, ltp, bid, ask, oi, volume
```

### Format Single Symbol
```python
symbol = client.format_nifty_option_symbol(
    strike=24500, 
    option_type='CE',
    expiry_date=date(2026, 4, 24)
)
# Returns: 'NSE:NIFTY26APR2424500CE-FO'
```

### Get Single Quote
```python
quote = client.get_quotes(['NSE:NIFTY26APR2424500CE-FO'])
# Returns full quote data
```

### Auto-Generate Strikes
```python
# Get 5 strikes on each side of ATM (11 total)
strikes = client.get_strikes_around_atm(num_strikes=5)
# Returns: [24250, 24300, ..., 24500, ..., 24700, 24750]
```

### Get Historical Data
```python
hist = client.get_historical_data(
    symbol='NSE:NIFTY50-INDEX',
    resolution='5',  # 5-minute candles
    date_from=date(2026, 4, 1),
    date_to=date(2026, 4, 10)
)
# Returns DataFrame with: timestamp, open, high, low, close, volume
```

### Get Market Depth
```python
depth = client.get_market_depth('NSE:NIFTY26APR2424500CE-FO')
# Returns order book with bid/ask levels
```

## 🔧 Utility Scripts

| Script | Purpose |
|--------|---------|
| `scripts/generate_fyers_token.py` | Generate new access token |
| `scripts/check_fyers_token.py` | Check if token is valid |
| `data/fyers_live_data.py` | Full validation test |
| `examples/fyers_usage_examples.py` | Usage examples |

## 📊 Symbol Format

| Type | Format | Example |
|------|--------|---------|
| **Index** | `NSE:{INDEX}-INDEX` | `NSE:NIFTY50-INDEX` |
| **VIX** | `NSE:INDIAVIX-INDEX` | `NSE:INDIAVIX-INDEX` |
| **Options** | `NSE:NIFTY{YY}{MMM}{DD}{STRIKE}{CE/PE}-FO` | `NSE:NIFTY26APR2524500CE-FO` |

### Month Codes
JAN, FEB, MAR, APR, MAY, JUN, JUL, AUG, SEP, OCT, NOV, DEC

## ⚡ API Limits

- **Max symbols per quote request**: 50
- **Depth API**: 1 symbol only
- **Token validity**: Check expiry in token payload
- **Rate limits**: Respect Fyers limits (no documented number)

## 🐛 Common Errors

| Error | Fix |
|-------|-----|
| `code: -15` (Invalid token) | Run `python scripts/generate_fyers_token.py` |
| `code: -50` (Invalid symbol) | Check symbol format |
| Market closed | No live quotes outside 9:15-3:30 IST |
| Connection error | Check internet / Fyers status |

## 📦 DataFrame Columns

### Option Chain
```
symbol, strike, option_type, ltp, bid, ask, open_interest, 
volume, timestamp, change_pct, high, low, open, prev_close
```

### Historical Data
```
timestamp (index), open, high, low, close, volume
```

## 🎯 Strategy Integration Example

```python
from data.fyers_live_data import FyersLiveDataClient
from datetime import date

# Initialize
client = FyersLiveDataClient()

# Get market state
spot = client.get_nifty_spot_price()
vix = client.get_india_vix()
atm = client.get_atm_strike(spot)

# Decide strategy based on VIX
if vix < 13:
    distance = 150  # Sell closer
elif vix < 18:
    distance = 200
else:
    distance = 300  # Sell further

# Calculate strikes
call_strike = atm + distance
put_strike = atm - distance

# Get quotes
expiry = date(2026, 4, 24)
chain = client.get_option_chain_quotes(
    [call_strike, put_strike], 
    expiry
)

# Use chain data for entry decision
call_premium = chain[
    (chain['strike'] == call_strike) & 
    (chain['option_type'] == 'CE')
]['ltp'].iloc[0]

put_premium = chain[
    (chain['strike'] == put_strike) & 
    (chain['option_type'] == 'PE')
]['ltp'].iloc[0]

print(f"Sell {call_strike} CE @ ₹{call_premium}")
print(f"Sell {put_strike} PE @ ₹{put_premium}")
```

## 🔐 Environment Variables

```env
FYERS_CLIENT_ID="W4JMYLVR9Y-100"
FYERS_SECRET_KEY="4WAAVZ1UW0"
FYERS_REDIRECT_URI="http://127.0.0.1:8080"
FYERS_ACCESS_TOKEN="<generated_token>"
```

## 📚 Full Documentation

- **Complete Guide**: [INTEGRATION.md](./INTEGRATION.md)
- **Summary**: [INTEGRATION_SUMMARY.md](./INTEGRATION_SUMMARY.md)
- **Examples**: `examples/fyers_usage_examples.py`
- **Fyers API Docs**: https://myapi.fyers.in/docsv3

## 🎓 Learning Path

1. ✅ Generate token → `scripts/generate_fyers_token.py`
2. ✅ Check status → `scripts/check_fyers_token.py`
3. ✅ Run validation → `data/fyers_live_data.py`
4. ✅ Study examples → `examples/fyers_usage_examples.py`
5. ✅ Build your strategy using the client

## 💡 Pro Tips

1. **Cache calculations**: ATM, strikes don't change frequently
2. **Batch requests**: Fetch 50 symbols at once
3. **Handle market hours**: Check if market is open
4. **Monitor token expiry**: Refresh before expiry
5. **Error handling**: Wrap all API calls in try-except
6. **Rate limiting**: Add small delays between requests
7. **Test outside market**: Use historical data API

## 🚨 Security Checklist

- [ ] `.env` in `.gitignore`
- [ ] No hardcoded credentials
- [ ] Minimal API permissions
- [ ] Regular token rotation
- [ ] Monitor API usage
