"""
Fyers API Rate Limiter — Manage API call rates and adaptive caching

Handles:
- Rate limit tracking (calls/second, /minute, /day)
- Adaptive TTL caching (30s spot, 60s VIX, 5min chain, etc)
- Exponential backoff on rate limit
- Request queuing for burst traffic
- Fallback to cached/mock data when limits hit
"""

import time
import logging
from collections import deque
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from pathlib import Path
import json

from config import FyersAPIConfig

logger = logging.getLogger(__name__)


class RateLimiter:
    """Track API calls against Fyers rate limits"""

    def __init__(self, api_config: FyersAPIConfig = None):
        self.config = api_config or FyersAPIConfig()

        # Tracking windows
        self.second_calls = deque()      # Last 1 second of calls
        self.minute_calls = deque()      # Last 1 minute of calls
        self.daily_calls = deque()       # Last 24 hours of calls

        # Daily counter reset at midnight
        self.daily_call_count = 0
        self.last_reset_date = datetime.now().date()

    def _reset_daily_if_needed(self):
        """Reset daily counter at midnight"""
        today = datetime.now().date()
        if today > self.last_reset_date:
            self.daily_call_count = 0
            self.last_reset_date = today
            logger.info(f"Daily rate limit counter reset for {today}")

    def can_call(self) -> bool:
        """Check if API call is allowed"""
        now = time.time()

        # Clean old entries
        while self.second_calls and self.second_calls[0] < now - 1:
            self.second_calls.popleft()
        while self.minute_calls and self.minute_calls[0] < now - 60:
            self.minute_calls.popleft()
        while self.daily_calls and self.daily_calls[0] < now - 86400:
            self.daily_calls.popleft()

        self._reset_daily_if_needed()

        # Check all limits
        if len(self.second_calls) >= self.config.calls_per_second_limit:
            logger.warning(f"Rate limit hit: {len(self.second_calls)}/sec")
            return False

        if len(self.minute_calls) >= self.config.calls_per_minute_limit:
            logger.warning(f"Rate limit hit: {len(self.minute_calls)}/min")
            return False

        if self.daily_call_count >= self.config.calls_per_day_limit:
            logger.error(f"Daily limit hit: {self.daily_call_count}/{self.config.calls_per_day_limit}")
            return False

        return True

    def record_call(self):
        """Record an API call"""
        now = time.time()
        self.second_calls.append(now)
        self.minute_calls.append(now)
        self.daily_calls.append(now)
        self.daily_call_count += 1

        # Check usage thresholds
        daily_pct = (self.daily_call_count / self.config.calls_per_day_limit) * 100
        minute_pct = (len(self.minute_calls) / self.config.calls_per_minute_limit) * 100
        second_pct = (len(self.second_calls) / self.config.calls_per_second_limit) * 100

        if daily_pct >= self.config.daily_usage_alert_pct:
            logger.warning(f"Daily usage alert: {daily_pct:.1f}% of limit")
        if minute_pct >= self.config.minute_usage_alert_pct:
            logger.warning(f"Minute usage alert: {minute_pct:.1f}% of limit")
        if second_pct >= self.config.second_usage_alert_pct:
            logger.warning(f"Second usage alert: {second_pct:.1f}% of limit")

    def get_usage_stats(self) -> Dict[str, Any]:
        """Get current rate limit usage statistics"""
        self._reset_daily_if_needed()

        return {
            'second': {
                'used': len(self.second_calls),
                'limit': self.config.calls_per_second_limit,
                'pct': (len(self.second_calls) / self.config.calls_per_second_limit) * 100
            },
            'minute': {
                'used': len(self.minute_calls),
                'limit': self.config.calls_per_minute_limit,
                'pct': (len(self.minute_calls) / self.config.calls_per_minute_limit) * 100
            },
            'day': {
                'used': self.daily_call_count,
                'limit': self.config.calls_per_day_limit,
                'pct': (self.daily_call_count / self.config.calls_per_day_limit) * 100
            }
        }

    async def wait_if_needed(self):
        """Wait until rate limit allows next call"""
        import asyncio

        attempt = 0
        while not self.can_call() and attempt < self.config.retry_max_attempts:
            wait_time = self.config.retry_backoff_base_seconds ** (attempt + 1)
            logger.warning(f"Rate limited, waiting {wait_time:.1f}s (attempt {attempt + 1})")
            await asyncio.sleep(wait_time)
            attempt += 1

        if self.can_call():
            self.record_call()
            return True

        logger.error("Max retry attempts reached, giving up")
        return False


class AdaptiveTTLCache:
    """Cache market data with adaptive TTL based on data type"""

    def __init__(self, api_config: FyersAPIConfig = None):
        self.config = api_config or FyersAPIConfig()
        self.cache = {}

        # TTL settings from config
        self.ttl_config = {
            'spot_price': self.config.cache_ttl_spot_price_seconds,
            'vix_level': self.config.cache_ttl_vix_seconds,
            'option_chain': self.config.cache_ttl_option_chain_seconds,
            'market_status': self.config.cache_ttl_market_status_seconds,
            'account': self.config.cache_ttl_account_seconds,
            'holdings': self.config.cache_ttl_holdings_seconds,
            'orders': self.config.cache_ttl_orders_seconds,
        }

    def needs_refresh(self, key: str) -> bool:
        """Check if cached data needs refresh"""
        if key not in self.cache:
            return True

        timestamp, data = self.cache[key]
        ttl = self.ttl_config.get(key, 60)

        elapsed = (datetime.now() - timestamp).total_seconds()

        if elapsed > ttl:
            logger.debug(f"Cache expired for {key}: {elapsed:.0f}s > {ttl}s TTL")
            return True

        return False

    def get(self, key: str) -> Optional[Any]:
        """Get cached data if fresh"""
        if not self.needs_refresh(key):
            timestamp, data = self.cache[key]
            elapsed = (datetime.now() - timestamp).total_seconds()
            logger.debug(f"Cache hit for {key} ({elapsed:.0f}s old)")
            return data

        return None

    def set(self, key: str, data: Any):
        """Store data with timestamp"""
        self.cache[key] = (datetime.now(), data)
        logger.debug(f"Cached {key}")

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        stats = {}
        for key in self.ttl_config.keys():
            if key in self.cache:
                timestamp, data = self.cache[key]
                elapsed = (datetime.now() - timestamp).total_seconds()
                ttl = self.ttl_config[key]
                stats[key] = {
                    'cached': True,
                    'age_seconds': elapsed,
                    'ttl_seconds': ttl,
                    'fresh': elapsed < ttl
                }
            else:
                stats[key] = {'cached': False}

        return stats


class RequestQueue:
    """Queue API requests during rate limit periods"""

    def __init__(self, max_size: int = 1000):
        self.queue = deque(maxlen=max_size)
        self.max_size = max_size

    def enqueue(self, request_type: str, data: Dict[str, Any]):
        """Add request to queue"""
        self.queue.append({
            'type': request_type,
            'data': data,
            'timestamp': datetime.now(),
            'attempt': 0
        })
        logger.debug(f"Queued {request_type}, queue size: {len(self.queue)}")

    def is_full(self) -> bool:
        """Check if queue is at capacity"""
        return len(self.queue) >= self.max_size

    def get_next(self) -> Optional[Dict[str, Any]]:
        """Get next request from queue"""
        if self.queue:
            return self.queue.popleft()
        return None

    def size(self) -> int:
        """Get queue size"""
        return len(self.queue)

    def clear_old(self, max_age_seconds: int = 300):
        """Remove requests older than max age"""
        now = datetime.now()
        kept = deque()

        while self.queue:
            request = self.queue.popleft()
            age = (now - request['timestamp']).total_seconds()

            if age < max_age_seconds:
                kept.append(request)
            else:
                logger.warning(f"Dropping queued {request['type']} (age: {age:.0f}s)")

        self.queue = kept


class SmartFyersAPI:
    """Fyers API wrapper with automatic rate limit handling and caching"""

    def __init__(self, fyers_client, api_config: FyersAPIConfig = None):
        self.client = fyers_client
        self.config = api_config or FyersAPIConfig()
        self.rate_limiter = RateLimiter(self.config)
        self.cache = AdaptiveTTLCache(self.config)
        self.request_queue = RequestQueue(self.config.queue_max_size)

    def _call_with_rate_limit(self, method_name: str, *args, **kwargs) -> Optional[Any]:
        """Call API method with rate limit checking"""
        # Check cache first
        cache_key = f"{method_name}_{args}_{kwargs}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        # Check rate limit
        if not self.rate_limiter.can_call():
            logger.warning(f"Rate limited on {method_name}")

            if self.config.enable_request_queuing:
                logger.info(f"Queuing {method_name} for later")
                self.request_queue.enqueue(method_name, {'args': args, 'kwargs': kwargs})

            if self.config.use_cached_on_minute_limit:
                logger.info(f"Using cached data for {method_name}")
                return cached

            return None

        # Make the call
        try:
            method = getattr(self.client, method_name)
            result = method(*args, **kwargs)

            self.rate_limiter.record_call()

            # Cache result
            ttl_key = self._get_cache_key_for_method(method_name)
            if ttl_key:
                self.cache.set(ttl_key, result)

            return result

        except Exception as e:
            logger.error(f"API call failed: {method_name}: {e}")
            return cached

    def _get_cache_key_for_method(self, method_name: str) -> Optional[str]:
        """Map method name to cache key"""
        mapping = {
            'quotes': 'spot_price',
            'optionchain': 'option_chain',
            'market_status': 'market_status',
            'get_profile': 'account',
            'holdings': 'holdings',
            'orderbook': 'orders',
        }
        return mapping.get(method_name)

    def get_spot_price(self, symbol: str = "NIFTY50") -> Optional[float]:
        """Get cached spot price if fresh, fetch if needed"""
        cached = self.cache.get('spot_price')
        if cached is not None:
            return cached

        result = self._call_with_rate_limit('quotes', {"symbols": [symbol]})
        if result and result.get('s') == 'ok' and 'd' in result:
            try:
                data = result['d'][0] if isinstance(result['d'], list) else result['d']
                if data.get('v') and data['v'].get('ltp'):
                    price = float(data['v']['ltp'])
                    self.cache.set('spot_price', price)
                    return price
            except Exception as e:
                logger.error(f"Failed to parse spot price: {e}")

        return None

    def get_vix(self, symbol: str = "INDIAVIX") -> Optional[float]:
        """Get cached VIX if fresh, fetch if needed"""
        cached = self.cache.get('vix_level')
        if cached is not None:
            return cached

        result = self._call_with_rate_limit('quotes', {"symbols": [symbol]})
        if result and result.get('s') == 'ok' and 'd' in result:
            try:
                data = result['d'][0] if isinstance(result['d'], list) else result['d']
                if data.get('v') and data['v'].get('ltp'):
                    vix = float(data['v']['ltp'])
                    self.cache.set('vix_level', vix)
                    return vix
            except Exception as e:
                logger.error(f"Failed to parse VIX: {e}")

        return None

    def get_option_chain(self, symbol: str = "NIFTY50", **kwargs) -> Optional[Dict]:
        """Get cached option chain if fresh, fetch if needed"""
        cached = self.cache.get('option_chain')
        if cached is not None:
            return cached

        result = self._call_with_rate_limit('optionchain', {"mode": "LTP", "symbol": symbol})
        if result and result.get('s') == 'ok':
            self.cache.set('option_chain', result)
            return result

        return None

    def get_account(self) -> Optional[Dict]:
        """Get cached account info if fresh, fetch if needed"""
        cached = self.cache.get('account')
        if cached is not None:
            return cached

        result = self._call_with_rate_limit('get_profile')
        if result and result.get('s') == 'ok':
            self.cache.set('account', result)
            return result

        return None

    def get_rate_limit_stats(self) -> Dict[str, Any]:
        """Get rate limit usage statistics"""
        return {
            'rate_limit': self.rate_limiter.get_usage_stats(),
            'cache': self.cache.get_stats(),
            'queue_size': self.request_queue.size()
        }

    def process_queue(self):
        """Process queued requests if rate limit allows"""
        processed = 0

        while not self.request_queue.is_full():
            request = self.request_queue.get_next()
            if not request:
                break

            if self.rate_limiter.can_call():
                try:
                    method = getattr(self.client, request['type'])
                    result = method(*request['data'].get('args', []),
                                   **request['data'].get('kwargs', {}))
                    self.rate_limiter.record_call()
                    processed += 1
                except Exception as e:
                    logger.error(f"Failed to process queued {request['type']}: {e}")
                    # Re-queue failed request
                    request['attempt'] += 1
                    if request['attempt'] < 3:
                        self.request_queue.enqueue(request['type'], request['data'])
            else:
                # Rate limit reached, stop processing
                self.request_queue.enqueue(request['type'], request['data'])
                break

        if processed > 0:
            logger.info(f"Processed {processed} queued requests")

        return processed
