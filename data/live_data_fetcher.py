"""
Live Market Data Fetcher — Fetch latest data from Fyers & NSE for live signals
Ensures trade recommendations are based on current market data
"""

import pandas as pd
import numpy as np
from datetime import datetime, time as dt_time
import logging
from typing import Dict, Tuple, Optional
import json
from pathlib import Path

logger = logging.getLogger(__name__)

# ============================================================================
# NSE / Fyers Live Data Integration
# ============================================================================

class LiveDataFetcher:
    """Fetch latest market data from Fyers (primary) or NSE fallback"""

    def __init__(self, fyers_client=None, use_mock=True):
        """
        Args:
            fyers_client: Fyers API client object (optional)
            use_mock: If True, use mock data for testing; False for production
        """
        self.fyers_client = fyers_client
        self.use_mock = use_mock
        self.last_refresh_time = None
        self.cache_ttl_seconds = 30  # Cache data for 30 seconds
        self._data_cache = {}

    def fetch_nifty_spot_price(self) -> Tuple[float, datetime]:
        """
        Fetch live Nifty 50 spot price and timestamp

        Returns:
            (spot_price, timestamp)
        """
        if self.use_mock:
            return self._get_mock_spot_price()

        # Try Fyers first
        if self.fyers_client:
            try:
                spot, ts = self._fetch_from_fyers("NIFTY50")
                logger.info(f"Fetched Nifty spot from Fyers: ₹{spot:.2f}")
                return spot, ts
            except Exception as e:
                logger.warning(f"Fyers spot fetch failed: {e}. Trying NSE fallback.")

        # Fallback to NSE
        try:
            spot, ts = self._fetch_from_nse()
            logger.info(f"Fetched Nifty spot from NSE: ₹{spot:.2f}")
            return spot, ts
        except Exception as e:
            logger.error(f"NSE spot fetch also failed: {e}")
            raise

    def fetch_vix_level(self) -> Tuple[float, datetime]:
        """
        Fetch live India VIX level

        Returns:
            (vix_level, timestamp)
        """
        if self.use_mock:
            return self._get_mock_vix()

        # Try Fyers
        if self.fyers_client:
            try:
                vix, ts = self._fetch_from_fyers("INDIAVIX")
                logger.info(f"Fetched VIX from Fyers: {vix:.2f}")
                return vix, ts
            except Exception as e:
                logger.warning(f"Fyers VIX fetch failed: {e}. Trying NSE fallback.")

        # Fallback to NSE
        try:
            vix, ts = self._fetch_from_nse_vix()
            logger.info(f"Fetched VIX from NSE: {vix:.2f}")
            return vix, ts
        except Exception as e:
            logger.error(f"NSE VIX fetch failed: {e}")
            raise

    def fetch_option_chain(self, symbol: str, expiry_date: str) -> Dict:
        """
        Fetch live option chain for a given symbol and expiry

        Args:
            symbol: "NIFTY50" or "BANKNIFTY"
            expiry_date: "04-SEP-2026" (NSE format)

        Returns:
            Dict with strike → {call_bid, call_ask, put_bid, put_ask, ...}
        """
        if self.use_mock:
            return self._get_mock_option_chain(symbol, expiry_date)

        # Try Fyers first
        if self.fyers_client:
            try:
                chain = self._fetch_option_chain_from_fyers(symbol, expiry_date)
                logger.info(f"Fetched option chain from Fyers: {len(chain)} strikes")
                return chain
            except Exception as e:
                logger.warning(f"Fyers option chain failed: {e}. Trying NSE fallback.")

        # Fallback to NSE
        try:
            chain = self._fetch_option_chain_from_nse(symbol, expiry_date)
            logger.info(f"Fetched option chain from NSE: {len(chain)} strikes")
            return chain
        except Exception as e:
            logger.error(f"NSE option chain fetch failed: {e}")
            raise

    def is_market_open(self) -> bool:
        """Check if market is currently open (9:15 AM - 3:30 PM IST)"""
        now_ist = datetime.now()  # Assuming IST
        market_open = dt_time(9, 15)
        market_close = dt_time(15, 30)

        is_weekday = now_ist.weekday() < 5  # Mon-Fri
        is_open_time = market_open <= now_ist.time() <= market_close

        return is_weekday and is_open_time

    def is_in_entry_window(self) -> bool:
        """Check if current time is in 11:00-13:00 IST entry window"""
        now_ist = datetime.now()
        entry_open = dt_time(11, 0)
        entry_close = dt_time(13, 0)

        return entry_open <= now_ist.time() <= entry_close

    # ========================================================================
    # Fyers API Methods
    # ========================================================================

    def _fetch_from_fyers(self, symbol: str) -> Tuple[float, datetime]:
        """Fetch live price from Fyers API"""
        if not self.fyers_client:
            raise ValueError("Fyers client not initialized")

        try:
            # Use Fyers quote API
            quote = self.fyers_client.get_quotes(
                symbols=[symbol],
                mode="LTP"  # Last Traded Price
            )

            if quote and "data" in quote:
                data = quote["data"].get(symbol, {})
                price = float(data.get("ltp", 0))
                timestamp = datetime.now()

                if price > 0:
                    return price, timestamp
                else:
                    raise ValueError(f"Invalid LTP received: {price}")
            else:
                raise ValueError("Invalid quote response from Fyers")
        except Exception as e:
            logger.error(f"Fyers fetch error for {symbol}: {e}")
            raise

    def _fetch_option_chain_from_fyers(self, symbol: str, expiry_date: str) -> Dict:
        """Fetch option chain from Fyers API"""
        if not self.fyers_client:
            raise ValueError("Fyers client not initialized")

        try:
            # Use Fyers option chain API
            chain_data = self.fyers_client.get_option_chain(
                symbol=symbol,
                expiry_date=expiry_date
            )

            # Parse into standardized format
            chain = {}
            for strike_data in chain_data.get("data", []):
                strike = float(strike_data["strike"])
                chain[strike] = {
                    "call_bid": float(strike_data.get("call_bid", 0)),
                    "call_ask": float(strike_data.get("call_ask", 0)),
                    "call_ltp": float(strike_data.get("call_ltp", 0)),
                    "call_iv": float(strike_data.get("call_iv", 0)),
                    "put_bid": float(strike_data.get("put_bid", 0)),
                    "put_ask": float(strike_data.get("put_ask", 0)),
                    "put_ltp": float(strike_data.get("put_ltp", 0)),
                    "put_iv": float(strike_data.get("put_iv", 0)),
                }

            return chain
        except Exception as e:
            logger.error(f"Fyers option chain error: {e}")
            raise

    # ========================================================================
    # NSE Fallback Methods
    # ========================================================================

    def _fetch_from_nse(self) -> Tuple[float, datetime]:
        """Fetch Nifty 50 spot price from NSE website fallback"""
        try:
            # NSE live data endpoint (may require headers)
            import requests

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "Accept": "application/json"
            }

            # NSE official Nifty 50 index page
            url = "https://www.nseindia.com/api/equity-indices?index=NIFTY%2050"
            response = requests.get(url, headers=headers, timeout=5)

            if response.status_code == 200:
                data = response.json()
                # Parse NSE response (structure: data[0]["lastPrice"])
                spot = float(data.get("data", [{}])[0].get("lastPrice", 0))
                timestamp = datetime.now()

                if spot > 0:
                    return spot, timestamp
                else:
                    raise ValueError(f"Invalid spot price from NSE: {spot}")
            else:
                raise ValueError(f"NSE returned {response.status_code}")
        except Exception as e:
            logger.error(f"NSE spot fetch error: {e}")
            raise

    def _fetch_from_nse_vix(self) -> Tuple[float, datetime]:
        """Fetch India VIX from NSE website"""
        try:
            import requests

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "Accept": "application/json"
            }

            # NSE VIX endpoint
            url = "https://www.nseindia.com/api/equity-indices?index=INDIA%20VIX"
            response = requests.get(url, headers=headers, timeout=5)

            if response.status_code == 200:
                data = response.json()
                vix = float(data.get("data", [{}])[0].get("lastPrice", 0))
                timestamp = datetime.now()

                if vix > 0:
                    return vix, timestamp
                else:
                    raise ValueError(f"Invalid VIX from NSE: {vix}")
            else:
                raise ValueError(f"NSE returned {response.status_code}")
        except Exception as e:
            logger.error(f"NSE VIX fetch error: {e}")
            raise

    def _fetch_option_chain_from_nse(self, symbol: str, expiry_date: str) -> Dict:
        """Fetch option chain from NSE website"""
        try:
            import requests

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "Accept": "application/json"
            }

            # NSE option chain endpoint
            url = f"https://www.nseindia.com/api/option-chain-indices?index={symbol}"
            response = requests.get(url, headers=headers, timeout=5)

            if response.status_code == 200:
                data = response.json()
                records = data.get("records", {}).get("data", [])

                # Parse into standardized format
                chain = {}
                for record in records:
                    # Filter by expiry_date
                    if record.get("expiryDate") != expiry_date:
                        continue

                    strike = float(record.get("strikePrice", 0))
                    ce = record.get("CE", {})
                    pe = record.get("PE", {})

                    chain[strike] = {
                        "call_bid": float(ce.get("bidprice", 0)),
                        "call_ask": float(ce.get("askprice", 0)),
                        "call_ltp": float(ce.get("lastPrice", 0)),
                        "call_iv": float(ce.get("impliedVolatility", 0)),
                        "put_bid": float(pe.get("bidprice", 0)),
                        "put_ask": float(pe.get("askprice", 0)),
                        "put_ltp": float(pe.get("lastPrice", 0)),
                        "put_iv": float(pe.get("impliedVolatility", 0)),
                    }

                return chain
            else:
                raise ValueError(f"NSE returned {response.status_code}")
        except Exception as e:
            logger.error(f"NSE option chain error: {e}")
            raise

    # ========================================================================
    # Mock Data (for testing without live APIs)
    # ========================================================================

    def _get_mock_spot_price(self) -> Tuple[float, datetime]:
        """Return mock Nifty 50 spot price"""
        # Simulate realistic spot prices
        base_spot = 25200
        noise = np.random.normal(0, 50)
        spot = base_spot + noise
        return spot, datetime.now()

    def _get_mock_vix(self) -> Tuple[float, datetime]:
        """Return mock VIX level"""
        base_vix = 17.5
        noise = np.random.normal(0, 1)
        vix = max(10, base_vix + noise)
        return vix, datetime.now()

    def _get_mock_option_chain(self, symbol: str, expiry_date: str) -> Dict:
        """Return mock option chain"""
        spot, _ = self._get_mock_spot_price()
        vix, _ = self._get_mock_vix()

        chain = {}
        strikes = [int(spot) - 400 + (100 * i) for i in range(9)]  # 9 strikes around spot

        for strike in strikes:
            distance = abs(strike - spot)
            # Realistic Greeks-based pricing
            call_price = max(1, spot - strike + 100)
            put_price = max(1, strike - spot + 100)

            chain[float(strike)] = {
                "call_bid": call_price * 0.98,
                "call_ask": call_price * 1.02,
                "call_ltp": call_price,
                "call_iv": vix / 100,
                "put_bid": put_price * 0.98,
                "put_ask": put_price * 1.02,
                "put_ltp": put_price,
                "put_iv": vix / 100,
            }

        return chain


class DataRefreshStrategy:
    """Strategy for ensuring data freshness in live trading"""

    # Data freshness requirements
    DATA_FRESHNESS_RULES = {
        "spot_price": 5,          # Refresh spot every 5 sec (entry decisions)
        "vix_level": 60,          # Refresh VIX every 60 sec (regime decisions)
        "option_chain": 30,       # Refresh chain every 30 sec (Greeks, pricing)
        "market_data_df": 3600,   # Refresh full DF every 1 hour (features)
    }

    def __init__(self, live_fetcher: LiveDataFetcher):
        self.fetcher = live_fetcher
        self.last_update_times = {}
        self.data_cache = {}

    def needs_refresh(self, data_type: str) -> bool:
        """Check if a data type needs refresh based on TTL"""
        last_update = self.last_update_times.get(data_type, 0)
        ttl = self.DATA_FRESHNESS_RULES.get(data_type, 60)

        time_since_update = (datetime.now().timestamp() - last_update)
        return time_since_update >= ttl

    def get_spot_price(self, force_refresh=False) -> float:
        """Get spot price, refreshing if needed"""
        if force_refresh or self.needs_refresh("spot_price"):
            spot, ts = self.fetcher.fetch_nifty_spot_price()
            self.data_cache["spot_price"] = spot
            self.last_update_times["spot_price"] = datetime.now().timestamp()
            logger.info(f"Refreshed spot: ₹{spot:.2f}")

        return self.data_cache.get("spot_price", 25200)

    def get_vix_level(self, force_refresh=False) -> float:
        """Get VIX, refreshing if needed"""
        if force_refresh or self.needs_refresh("vix_level"):
            vix, ts = self.fetcher.fetch_vix_level()
            self.data_cache["vix_level"] = vix
            self.last_update_times["vix_level"] = datetime.now().timestamp()
            logger.info(f"Refreshed VIX: {vix:.2f}")

        return self.data_cache.get("vix_level", 17.5)

    def get_option_chain(self, symbol: str, expiry: str, force_refresh=False) -> Dict:
        """Get option chain, refreshing if needed"""
        cache_key = f"chain_{symbol}_{expiry}"

        if force_refresh or self.needs_refresh("option_chain"):
            chain = self.fetcher.fetch_option_chain(symbol, expiry)
            self.data_cache[cache_key] = chain
            self.last_update_times["option_chain"] = datetime.now().timestamp()
            logger.info(f"Refreshed {symbol} chain: {len(chain)} strikes")

        return self.data_cache.get(cache_key, {})


# ============================================================================
# Usage Example
# ============================================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Create fetcher with mock data (for testing)
    fetcher = LiveDataFetcher(use_mock=True)

    print("Testing Live Data Fetcher")
    print("=" * 60)

    # Test spot price
    try:
        spot, ts = fetcher.fetch_nifty_spot_price()
        print(f"✓ Nifty Spot: ₹{spot:.2f} (as of {ts.strftime('%H:%M:%S')})")
    except Exception as e:
        print(f"✗ Spot fetch failed: {e}")

    # Test VIX
    try:
        vix, ts = fetcher.fetch_vix_level()
        print(f"✓ India VIX: {vix:.2f} (as of {ts.strftime('%H:%M:%S')})")
    except Exception as e:
        print(f"✗ VIX fetch failed: {e}")

    # Test option chain
    try:
        chain = fetcher.fetch_option_chain("NIFTY50", "04-SEP-2026")
        print(f"✓ Option Chain: {len(chain)} strikes")
        # Print sample strikes
        strikes = sorted(chain.keys())[:3]
        for strike in strikes:
            c = chain[strike]
            print(f"  Strike {strike}: CE {c['call_ltp']:.1f}, PE {c['put_ltp']:.1f}")
    except Exception as e:
        print(f"✗ Option chain fetch failed: {e}")

    # Test market open check
    is_open = fetcher.is_market_open()
    in_window = fetcher.is_in_entry_window()
    print(f"✓ Market open: {is_open}, In entry window (11-1 PM): {in_window}")

    # Test refresh strategy
    print("\nTesting Data Refresh Strategy")
    print("-" * 60)
    strategy = DataRefreshStrategy(fetcher)

    spot1 = strategy.get_spot_price()
    vix1 = strategy.get_vix_level()
    print(f"Initial fetch: Spot ₹{spot1:.2f}, VIX {vix1:.2f}")

    # Get cached (should not refresh)
    spot2 = strategy.get_spot_price()
    print(f"Cached fetch: Spot ₹{spot2:.2f} (same={spot1 == spot2})")

    # Force refresh
    spot3 = strategy.get_spot_price(force_refresh=True)
    print(f"Forced refresh: Spot ₹{spot3:.2f}")
