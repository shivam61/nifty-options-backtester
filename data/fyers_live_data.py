"""
Fyers Live Market Data Integration
Fetches real-time quotes for Nifty options using Fyers API v3.

Symbol Format for NSE Options:
NSE:NIFTY{YY}{M}{DD}{STRIKE}{CE/PE}-FO

Example: NSE:NIFTY26APR2524500CE-FO
- 26 = Year (2026)
- APR = Month (3-letter abbreviation)
- 25 = Day
- 24500 = Strike Price
- CE = Call Option (PE for Put)
"""

import os
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple
from pathlib import Path

from fyers_apiv3 import fyersModel
from dotenv import load_dotenv
import pandas as pd
import numpy as np

# Load environment variables
load_dotenv()


class FyersLiveDataClient:
    """
    Client for fetching live market data from Fyers API.
    Handles authentication, quote fetching, and symbol formatting.
    """
    
    # Month codes for symbol formatting
    MONTH_CODES = {
        1: 'JAN', 2: 'FEB', 3: 'MAR', 4: 'APR', 5: 'MAY', 6: 'JUN',
        7: 'JUL', 8: 'AUG', 9: 'SEP', 10: 'OCT', 11: 'NOV', 12: 'DEC'
    }
    
    def __init__(self, client_id: Optional[str] = None, access_token: Optional[str] = None):
        """
        Initialize Fyers client.
        
        Args:
            client_id: Fyers App ID (default: from FYERS_CLIENT_ID env var)
            access_token: Fyers access token (default: from FYERS_ACCESS_TOKEN env var)
        """
        self.client_id = client_id or os.getenv('FYERS_CLIENT_ID')
        self.access_token = access_token or os.getenv('FYERS_ACCESS_TOKEN')
        
        if not self.client_id or not self.access_token:
            raise ValueError(
                "Fyers credentials not found. Set FYERS_CLIENT_ID and FYERS_ACCESS_TOKEN "
                "in .env file or pass them as arguments."
            )
        
        # Initialize Fyers model
        self.fyers = fyersModel.FyersModel(
            client_id=self.client_id,
            token=self.access_token,
            log_path=""
        )
        
        self._validate_connection()
    
    def _validate_connection(self) -> bool:
        """
        Validate that the connection and authentication are working.
        
        Returns:
            True if connection is valid, raises exception otherwise
        """
        try:
            # Try to get NIFTY index quote as a simple test
            test_data = {"symbols": "NSE:NIFTY50-INDEX"}
            response = self.fyers.quotes(data=test_data)
            
            if response.get('s') == 'ok':
                print("✓ Fyers API connection validated successfully")
                return True
            else:
                raise ConnectionError(f"Fyers API validation failed: {response}")
        except Exception as e:
            raise ConnectionError(f"Failed to connect to Fyers API: {str(e)}")
    
    # Cached valid expiries fetched from Fyers option chain API
    _valid_expiries: Dict = {}   # {month_key: {'monthly_sym_ts': ..., 'dates': [...]}}

    def format_nifty_option_symbol(
        self,
        strike: float,
        option_type: str,
        expiry_date: date,
        is_monthly: bool = False,
    ) -> str:
        """
        Format NIFTY option symbol using Fyers' actual convention.

        Fyers uses TWO formats depending on contract type:
          Monthly: NSE:NIFTY{YY}{MMM}{STRIKE}{CE/PE}         (no day, no -FO)
          Weekly:  NSE:NIFTY{YY}{MMM}{DD}{STRIKE}{CE/PE}     (with day, no -FO)

        The function auto-detects monthly vs weekly based on the expiry date.
        It queries the Fyers option chain once per month and caches the result.
        """
        year_2digit = str(expiry_date.year)[-2:]
        month_code = self.MONTH_CODES[expiry_date.month]
        day = str(expiry_date.day).zfill(2)
        strike_str = str(int(strike))
        opt = option_type.upper()

        # Detect monthly by querying the Fyers option chain (cached per month)
        if not is_monthly:
            is_monthly = self._is_monthly_expiry(expiry_date)

        if is_monthly:
            # Monthly format: no day, no -FO
            return f"NSE:NIFTY{year_2digit}{month_code}{strike_str}{opt}"
        else:
            # Weekly format: with day, no -FO
            return f"NSE:NIFTY{year_2digit}{month_code}{day}{strike_str}{opt}"

    def _is_monthly_expiry(self, expiry_date: date) -> bool:
        """
        Check if expiry_date is a monthly contract by querying Fyers option chain.
        Results are cached for the lifetime of the client.
        """
        cache_key = f"{expiry_date.year}-{expiry_date.month}"
        if cache_key not in self._valid_expiries:
            try:
                from fyers_apiv3 import fyersModel as _fm
                _fyers = _fm.FyersModel(
                    client_id=self.client_id, token=self.access_token, log_path=""
                )
                r = _fyers.optionchain(
                    data={"symbol": "NSE:NIFTY50-INDEX", "strikecount": 1, "timestamp": ""}
                )
                expiry_map = {}
                for e in r.get("data", {}).get("expiryData", []):
                    # date is like "28-04-2026"
                    d_parts = e["date"].split("-")
                    d = date(int(d_parts[2]), int(d_parts[1]), int(d_parts[0]))
                    expiry_map[d] = e.get("expiry_flag", "W")
                self._valid_expiries[cache_key] = expiry_map
            except Exception:
                return False

        expiry_map = self._valid_expiries.get(cache_key, {})
        return expiry_map.get(expiry_date, "W") == "M"

    def resolve_nearest_valid_expiry(self, target_date: date) -> date:
        """
        Given a target date, return the nearest valid Nifty expiry.
        Useful when the active trade's expiry_date doesn't exactly match an NSE expiry.
        """
        try:
            from fyers_apiv3 import fyersModel as _fm
            _fyers = _fm.FyersModel(
                client_id=self.client_id, token=self.access_token, log_path=""
            )
            r = _fyers.optionchain(
                data={"symbol": "NSE:NIFTY50-INDEX", "strikecount": 1, "timestamp": ""}
            )
            valid_dates = []
            for e in r.get("data", {}).get("expiryData", []):
                d_parts = e["date"].split("-")
                d = date(int(d_parts[2]), int(d_parts[1]), int(d_parts[0]))
                valid_dates.append((d, e.get("expiry_flag", "W")))
            # Find nearest date to target
            nearest = min(valid_dates, key=lambda x: abs((x[0] - target_date).days))
            return nearest[0]
        except Exception:
            return target_date
    
    def get_quotes(self, symbols: List[str]) -> Dict:
        """
        Get quotes for one or more symbols.
        
        Args:
            symbols: List of symbol strings (max 50)
        
        Returns:
            Dictionary containing quote data
        
        Example:
            >>> client = FyersLiveDataClient()
            >>> symbols = ['NSE:NIFTY26APR2524500CE-FO', 'NSE:NIFTY26APR2524500PE-FO']
            >>> quotes = client.get_quotes(symbols)
        """
        if len(symbols) > 50:
            raise ValueError("Fyers API supports maximum 50 symbols per request")
        
        # Format as comma-separated string
        symbols_str = ",".join(symbols)
        data = {"symbols": symbols_str}
        
        response = self.fyers.quotes(data=data)
        
        if response.get('s') != 'ok':
            raise ValueError(f"Fyers API error: {response}")
        
        return response
    
    def get_nifty_spot_price(self) -> float:
        """
        Get current Nifty 50 spot price.
        
        Returns:
            Current Nifty spot price
        """
        data = {"symbols": "NSE:NIFTY50-INDEX"}
        response = self.fyers.quotes(data=data)
        
        if response.get('s') == 'ok' and 'd' in response:
            quote_data = response['d'][0]['v']
            return quote_data['lp']  # Last price
        
        raise ValueError(f"Failed to get NIFTY spot price: {response}")
    
    def get_india_vix(self) -> float:
        """
        Get current India VIX value.
        
        Returns:
            Current India VIX value
        """
        data = {"symbols": "NSE:INDIAVIX-INDEX"}
        response = self.fyers.quotes(data=data)
        
        if response.get('s') == 'ok' and 'd' in response:
            quote_data = response['d'][0]['v']
            return quote_data['lp']
        
        raise ValueError(f"Failed to get India VIX: {response}")
    
    def get_option_chain_quotes(
        self,
        strikes: List[float],
        expiry_date: date,
        include_both_sides: bool = True
    ) -> pd.DataFrame:
        """
        Get quotes for an option chain (multiple strikes).
        
        Args:
            strikes: List of strike prices
            expiry_date: Option expiry date
            include_both_sides: If True, fetch both CE and PE for each strike
        
        Returns:
            DataFrame with columns: symbol, strike, option_type, ltp, bid, ask, 
                                   oi, volume, timestamp
        """
        symbols = []
        strike_map = {}
        
        for strike in strikes:
            if include_both_sides:
                ce_symbol = self.format_nifty_option_symbol(strike, 'CE', expiry_date)
                pe_symbol = self.format_nifty_option_symbol(strike, 'PE', expiry_date)
                symbols.extend([ce_symbol, pe_symbol])
                strike_map[ce_symbol] = (strike, 'CE')
                strike_map[pe_symbol] = (strike, 'PE')
            else:
                # For custom usage, can be extended
                pass
        
        # Fyers API limits to 50 symbols per request
        if len(symbols) > 50:
            # Split into multiple requests
            all_data = []
            for i in range(0, len(symbols), 50):
                batch = symbols[i:i+50]
                response = self.get_quotes(batch)
                all_data.extend(response.get('d', []))
        else:
            response = self.get_quotes(symbols)
            all_data = response.get('d', [])
        
        # Parse response into DataFrame
        rows = []
        for item in all_data:
            symbol = item['n']
            quote = item['v']
            
            strike, opt_type = strike_map.get(symbol, (None, None))
            
            rows.append({
                'symbol': symbol,
                'strike': strike,
                'option_type': opt_type,
                'ltp': quote.get('lp', 0),  # Last traded price
                'bid': quote.get('bid', 0),
                'ask': quote.get('ask', 0),
                'open_interest': quote.get('oi', 0),
                'volume': quote.get('volume', 0),
                'timestamp': datetime.now(),
                'change_pct': quote.get('ch', 0),  # Change %
                'high': quote.get('high_price', 0),
                'low': quote.get('low_price', 0),
                'open': quote.get('open_price', 0),
                'prev_close': quote.get('prev_close_price', 0),
            })
        
        return pd.DataFrame(rows)
    
    def get_atm_strike(self, spot_price: Optional[float] = None, round_to: int = 50) -> float:
        """
        Calculate ATM (At The Money) strike based on current spot price.
        
        Args:
            spot_price: Spot price (fetches current if None)
            round_to: Round strike to nearest value (default: 50)
        
        Returns:
            ATM strike price
        """
        if spot_price is None:
            spot_price = self.get_nifty_spot_price()
        
        atm_strike = round(spot_price / round_to) * round_to
        return atm_strike
    
    def get_strikes_around_atm(
        self,
        num_strikes: int = 5,
        spot_price: Optional[float] = None,
        strike_interval: int = 50
    ) -> List[float]:
        """
        Generate list of strikes around ATM.
        
        Args:
            num_strikes: Number of strikes on each side of ATM
            spot_price: Current spot price (fetches if None)
            strike_interval: Gap between strikes (default: 50)
        
        Returns:
            List of strike prices centered around ATM
        
        Example:
            >>> client = FyersLiveDataClient()
            >>> strikes = client.get_strikes_around_atm(num_strikes=3)
            >>> # Returns: [24350, 24400, 24450, 24500, 24550, 24600, 24650]
        """
        atm = self.get_atm_strike(spot_price, round_to=strike_interval)
        
        strikes = []
        for i in range(-num_strikes, num_strikes + 1):
            strikes.append(atm + (i * strike_interval))
        
        return sorted(strikes)
    
    def get_market_depth(self, symbol: str) -> Dict:
        """
        Get market depth (order book) for a single symbol.
        
        Args:
            symbol: Fyers symbol string
        
        Returns:
            Dictionary containing bid/ask depth data
        """
        data = {"symbol": symbol}
        response = self.fyers.depth(data=data)
        
        if response.get('s') != 'ok':
            raise ValueError(f"Fyers API error: {response}")
        
        return response
    
    def get_historical_data(
        self,
        symbol: str,
        resolution: str = "1",
        date_from: Optional[date] = None,
        date_to: Optional[date] = None
    ) -> pd.DataFrame:
        """
        Get historical candle data for a symbol.
        
        Args:
            symbol: Fyers symbol string
            resolution: Timeframe ('1'=1min, '5'=5min, '15'=15min, '60'=1hour, 'D'=1day)
            date_from: Start date (default: 30 days ago)
            date_to: End date (default: today)
        
        Returns:
            DataFrame with OHLCV data
        """
        if date_from is None:
            date_from = date.today() - timedelta(days=30)
        if date_to is None:
            date_to = date.today()
        
        # Convert to Unix timestamps
        date_from_unix = int(datetime.combine(date_from, datetime.min.time()).timestamp())
        date_to_unix = int(datetime.combine(date_to, datetime.max.time()).timestamp())
        
        data = {
            "symbol": symbol,
            "resolution": resolution,
            "date_format": "1",  # Unix timestamp
            "range_from": str(date_from_unix),
            "range_to": str(date_to_unix),
            "cont_flag": "1"
        }
        
        response = self.fyers.history(data=data)
        
        if response.get('s') != 'ok':
            raise ValueError(f"Fyers API error: {response}")
        
        candles = response.get('candles', [])
        
        df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')
        df.set_index('timestamp', inplace=True)
        
        return df


def main():
    """
    Test and validate Fyers API connection and data fetching.
    """
    print("=" * 70)
    print("Fyers Live Market Data - Validation Test")
    print("=" * 70)
    
    try:
        # Initialize client
        print("\n1. Initializing Fyers client...")
        client = FyersLiveDataClient()
        
        # Test 1: Get NIFTY spot price
        print("\n2. Fetching NIFTY 50 spot price...")
        spot_price = client.get_nifty_spot_price()
        print(f"   NIFTY Spot: ₹{spot_price:,.2f}")
        
        # Test 2: Get India VIX
        print("\n3. Fetching India VIX...")
        vix = client.get_india_vix()
        print(f"   India VIX: {vix:.2f}")
        
        # Test 3: Calculate ATM and surrounding strikes
        print("\n4. Calculating ATM and strikes...")
        atm_strike = client.get_atm_strike(spot_price)
        print(f"   ATM Strike: ₹{atm_strike:,.0f}")
        
        strikes = client.get_strikes_around_atm(num_strikes=2, spot_price=spot_price)
        print(f"   Strikes: {strikes}")
        
        # Test 4: Format option symbols
        print("\n5. Formatting option symbols...")
        expiry = date(2026, 4, 24)  # Example expiry
        sample_ce = client.format_nifty_option_symbol(atm_strike, 'CE', expiry)
        sample_pe = client.format_nifty_option_symbol(atm_strike, 'PE', expiry)
        print(f"   ATM Call: {sample_ce}")
        print(f"   ATM Put:  {sample_pe}")
        
        # Test 5: Get option quotes
        print("\n6. Fetching option quotes...")
        test_strikes = strikes[:3]  # Test with 3 strikes
        option_chain = client.get_option_chain_quotes(test_strikes, expiry)
        
        print("\n   Option Chain Data:")
        print(option_chain[['strike', 'option_type', 'ltp', 'bid', 'ask', 'volume', 'open_interest']].to_string(index=False))
        
        # Test 6: Get single quote
        print("\n7. Testing single symbol quote...")
        single_quote = client.get_quotes([sample_ce])
        print(f"   Quote response keys: {single_quote.keys()}")
        if single_quote.get('d'):
            print(f"   Data: {single_quote['d'][0]['v']}")
        
        print("\n" + "=" * 70)
        print("✓ All tests completed successfully!")
        print("=" * 70)
        
    except Exception as e:
        print(f"\n✗ Error: {str(e)}")
        print("\nPlease check:")
        print("1. FYERS_CLIENT_ID and FYERS_ACCESS_TOKEN are set in .env file")
        print("2. Access token is valid and not expired")
        print("3. Internet connection is active")
        print("4. Market is open (for live quotes)")
        raise


if __name__ == "__main__":
    main()
