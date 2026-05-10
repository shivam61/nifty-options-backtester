# Fyers Live Market Data Integration

This module provides real-time market data integration with Fyers API v3 for fetching live Nifty options prices.

## Setup

### 1. Install Dependencies

```bash
pip install fyers-apiv3
```

### 2. Configure Fyers Credentials

Add the following to your `.env` file:

```env
FYERS_CLIENT_ID="W4JMYLVR9Y-100"
FYERS_SECRET_KEY="4WAAVZ1UW0"
FYERS_REDIRECT_URI="http://127.0.0.1:8080"
FYERS_ACCESS_TOKEN="<your_access_token>"
```

### 3. Generate Access Token

Access tokens expire and need to be regenerated. Run:

```bash
python scripts/generate_fyers_token.py
```

This will:
1. Generate an authorization URL
2. Open it in your browser
3. After authorization, copy the redirected URL
4. Paste it back to the script
5. The script will generate and save the access token to `.env`

## Usage

### Basic Usage - Validation Test

```bash
python data/fyers_live_data.py
```

This runs a comprehensive validation test that:
- Validates API connection
- Fetches NIFTY spot price
- Fetches India VIX
- Calculates ATM strike
- Formats option symbols
- Fetches option chain quotes

### Python API Usage

```python
from data.fyers_live_data import FyersLiveDataClient
from datetime import date

# Initialize client (reads from .env automatically)
client = FyersLiveDataClient()

# Get NIFTY spot price
spot = client.get_nifty_spot_price()
print(f"NIFTY: {spot}")

# Get India VIX
vix = client.get_india_vix()
print(f"VIX: {vix}")

# Get ATM strike
atm = client.get_atm_strike()
print(f"ATM Strike: {atm}")

# Get strikes around ATM (±5 strikes, 50 point interval)
strikes = client.get_strikes_around_atm(num_strikes=5)
print(f"Strikes: {strikes}")

# Format option symbol
expiry = date(2026, 4, 24)
ce_symbol = client.format_nifty_option_symbol(24500, 'CE', expiry)
print(f"Symbol: {ce_symbol}")  # NSE:NIFTY26APR2424500CE-FO

# Get option chain quotes
option_chain = client.get_option_chain_quotes(
    strikes=[24400, 24450, 24500],
    expiry_date=expiry,
    include_both_sides=True
)
print(option_chain)

# Get single quote
quote = client.get_quotes(['NSE:NIFTY26APR2424500CE-FO'])
print(quote)

# Get market depth (order book)
depth = client.get_market_depth('NSE:NIFTY26APR2424500CE-FO')
print(depth)

# Get historical data
hist = client.get_historical_data(
    'NSE:NIFTY50-INDEX',
    resolution='5',  # 5-minute candles
    date_from=date(2026, 4, 1),
    date_to=date(2026, 4, 10)
)
print(hist)
```

## Features

### 1. Real-time Quotes
- Fetch up to 50 symbols per request
- Returns LTP, bid, ask, volume, OI, change%, OHLC

### 2. Option Symbol Formatting
- Automatic symbol formatting for NSE options
- Format: `NSE:NIFTY{YY}{MMM}{DD}{STRIKE}{CE/PE}-FO`
- Example: `NSE:NIFTY26APR2524500CE-FO`

### 3. ATM Strike Calculation
- Automatically calculates ATM based on current spot
- Rounds to nearest 50 (configurable)
- Generates strikes around ATM

### 4. Option Chain Data
- Fetch entire option chain for multiple strikes
- Returns structured DataFrame with all quote data
- Supports both CE and PE

### 5. Market Depth
- Get order book data (5 levels bid/ask)
- Returns best bid/ask with quantities

### 6. Historical Data
- Fetch historical candle data
- Supports multiple timeframes (1min, 5min, 15min, 1hour, 1day)
- Returns OHLCV DataFrame

## Symbol Format Reference

### Index Symbols
- NIFTY 50: `NSE:NIFTY50-INDEX`
- India VIX: `NSE:INDIAVIX-INDEX`
- Bank Nifty: `NSE:NIFTYBANK-INDEX`

### Option Symbols
Format: `NSE:NIFTY{YY}{MMM}{DD}{STRIKE}{CE/PE}-FO`

Examples:
- `NSE:NIFTY26APR2524500CE-FO` - NIFTY 24500 Call expiring 25-Apr-2026
- `NSE:NIFTY26MAY0124000PE-FO` - NIFTY 24000 Put expiring 01-May-2026

### Month Codes
JAN, FEB, MAR, APR, MAY, JUN, JUL, AUG, SEP, OCT, NOV, DEC

## API Limits

- **Quotes API**: Max 50 symbols per request
- **Depth API**: Single symbol per request
- **Historical Data**: Standard NSE rate limits apply
- **Access Token**: Expires after configured period (check token expiry)

## Error Handling

Common errors:

| Error Code | Message | Solution |
|------------|---------|----------|
| -15 | Please provide valid token | Regenerate access token |
| -50 | Invalid symbol | Check symbol format |
| Rate limit | Too many requests | Add delay between requests |

## Troubleshooting

### Token Invalid/Expired
```bash
python scripts/generate_fyers_token.py
```

### Symbol Not Found
- Verify expiry date is correct
- Check strike price exists
- Ensure format matches: `NSE:NIFTY{YY}{MMM}{DD}{STRIKE}{CE/PE}-FO`

### Market Closed
- Live quotes only available during market hours (9:15 AM - 3:30 PM IST)
- For testing outside market hours, use historical data API

### Connection Issues
- Check internet connectivity
- Verify Fyers API status
- Ensure firewall allows HTTPS connections

## Integration with Backtester

To integrate live data with the existing backtester:

```python
from data.fyers_live_data import FyersLiveDataClient
from strategies.iron_condor import IronCondorStrategy
from datetime import date

# Get live market data
client = FyersLiveDataClient()
spot = client.get_nifty_spot_price()
vix = client.get_india_vix()

# Use in strategy
expiry = date(2026, 4, 24)
strikes = client.get_strikes_around_atm(num_strikes=3)
option_chain = client.get_option_chain_quotes(strikes, expiry)

# Now you can use option_chain for live trading decisions
# The format matches the backtester's expected structure
```

## Security Best Practices

1. **Never commit `.env` file** - It contains sensitive credentials
2. **Rotate access tokens regularly** - They should expire
3. **Use environment variables** - Don't hardcode credentials
4. **Limit API permissions** - Only enable "Quotes & Market data"
5. **Monitor usage** - Watch for unusual API calls

## Resources

- [Fyers API Documentation](https://myapi.fyers.in/docsv3)
- [Fyers API Python SDK](https://pypi.org/project/fyers-apiv3/)
- [Sample Code Repository](https://github.com/FyersDev/fyers-api-sample-code)

## App Configuration

Your Fyers app configuration:
- **App ID**: W4JMYLVR9Y-100
- **App Name**: StockAnalysis
- **App Type**: User App
- **Permissions**: Quotes & Market data
- **Redirect URL**: http://127.0.0.1:8080

## Next Steps

1. Generate a valid access token
2. Run validation test: `python data/fyers_live_data.py`
3. Integrate with your backtester strategies
4. Build live monitoring dashboard
5. Add paper trading functionality
