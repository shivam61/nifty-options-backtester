"""
Quick test to verify what data we can fetch from Fyers API
"""

from data.fyers_live_data import FyersLiveDataClient
from datetime import date, timedelta

def test_market_data():
    print("=" * 70)
    print("Fyers API - Market Data Test")
    print("=" * 70)
    
    client = FyersLiveDataClient()
    
    # Test 1: Index quotes (should work anytime)
    print("\n1. Testing index quotes...")
    try:
        spot = client.get_nifty_spot_price()
        print(f"   ✓ NIFTY Spot: ₹{spot:,.2f}")
    except Exception as e:
        print(f"   ✗ Error: {e}")
    
    try:
        vix = client.get_india_vix()
        print(f"   ✓ India VIX: {vix:.2f}")
    except Exception as e:
        print(f"   ✗ Error: {e}")
    
    # Test 2: Try to get multiple index quotes
    print("\n2. Testing multiple index quotes...")
    try:
        symbols = ['NSE:NIFTY50-INDEX', 'NSE:INDIAVIX-INDEX', 'NSE:NIFTYBANK-INDEX']
        response = client.get_quotes(symbols)
        print(f"   ✓ Response status: {response.get('s')}")
        if response.get('d'):
            for item in response['d']:
                symbol = item['n']
                ltp = item['v'].get('lp', 0)
                print(f"   {symbol}: ₹{ltp:,.2f}")
    except Exception as e:
        print(f"   ✗ Error: {e}")
    
    # Test 3: Try different option expiry dates
    print("\n3. Testing option symbols with different expiries...")
    
    # Try nearest weekly expiry (Thursday)
    today = date.today()
    days_until_thursday = (3 - today.weekday()) % 7
    if days_until_thursday == 0:
        days_until_thursday = 7
    next_expiry = today + timedelta(days=days_until_thursday)
    
    print(f"   Next weekly expiry: {next_expiry}")
    
    atm = 24050
    test_strikes = [24000, 24050, 24100]
    
    for expiry_date in [next_expiry, date(2026, 4, 17), date(2026, 4, 30)]:
        print(f"\n   Testing expiry: {expiry_date}")
        
        # Try a few strikes
        for strike in test_strikes[:1]:  # Just test one strike
            ce_symbol = client.format_nifty_option_symbol(strike, 'CE', expiry_date)
            pe_symbol = client.format_nifty_option_symbol(strike, 'PE', expiry_date)
            
            print(f"      Trying: {ce_symbol}")
            try:
                response = client.get_quotes([ce_symbol])
                if response.get('s') == 'ok' and response.get('d'):
                    data = response['d'][0]
                    if 'v' in data and isinstance(data['v'], dict):
                        ltp = data['v'].get('lp', 0)
                        print(f"         ✓ LTP: ₹{ltp:.2f}")
                        break  # Found valid expiry
                    else:
                        print(f"         ✗ Error: {data.get('v', {}).get('errmsg', 'Unknown')}")
                else:
                    print(f"         ✗ Response: {response}")
            except Exception as e:
                print(f"         ✗ Error: {e}")
    
    # Test 4: Historical data (should work anytime)
    print("\n4. Testing historical data...")
    try:
        hist = client.get_historical_data(
            'NSE:NIFTY50-INDEX',
            resolution='D',
            date_from=date.today() - timedelta(days=5),
            date_to=date.today()
        )
        print(f"   ✓ Fetched {len(hist)} candles")
        if len(hist) > 0:
            print(f"   Latest close: ₹{hist['close'].iloc[-1]:,.2f}")
    except Exception as e:
        print(f"   ✗ Error: {e}")
    
    print("\n" + "=" * 70)
    print("Test completed!")
    print("=" * 70)


if __name__ == "__main__":
    test_market_data()
