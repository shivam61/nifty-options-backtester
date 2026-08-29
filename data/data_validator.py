"""
Market Data Validator — Ensure API responses have fresh, valid live data

Validates:
- Data freshness (timestamp within acceptable window)
- Data completeness (all required fields present)
- Data quality (values in expected ranges)
- Live vs cached data distinction
- Error handling for stale/invalid data
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Tuple, List
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of data validation"""
    is_valid: bool
    error_message: Optional[str] = None
    warnings: List[str] = None
    data_age_seconds: Optional[float] = None
    is_live: bool = False
    is_cached: bool = False

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []


class MarketDataValidator:
    """Validate market data freshness and quality"""

    def __init__(self, max_data_age_seconds: int = 60,
                 allow_cached: bool = False):
        """
        Args:
            max_data_age_seconds: Maximum acceptable data age (default 60s)
            allow_cached: If False, reject cached data (default False)
        """
        self.max_data_age_seconds = max_data_age_seconds
        self.allow_cached = allow_cached

    def validate_spot_price(self, spot_price: float, timestamp: datetime) -> ValidationResult:
        """Validate Nifty spot price data"""
        try:
            # Check timestamp
            data_age = (datetime.now() - timestamp).total_seconds()

            # Validate age
            if data_age > self.max_data_age_seconds:
                return ValidationResult(
                    is_valid=False,
                    error_message=f"Spot price data too old: {data_age:.0f}s (max {self.max_data_age_seconds}s)",
                    data_age_seconds=data_age,
                    is_cached=True
                )

            # Validate range (Nifty is typically 15000-30000)
            if not (15000 <= spot_price <= 30000):
                return ValidationResult(
                    is_valid=False,
                    error_message=f"Spot price out of expected range: ₹{spot_price:.2f}",
                    data_age_seconds=data_age
                )

            # Validate is not NaN or None
            if spot_price is None or (isinstance(spot_price, float) and spot_price != spot_price):
                return ValidationResult(
                    is_valid=False,
                    error_message="Spot price is NaN or None",
                    data_age_seconds=data_age
                )

            return ValidationResult(
                is_valid=True,
                data_age_seconds=data_age,
                is_live=(data_age < 10)  # Live if < 10s old
            )

        except Exception as e:
            return ValidationResult(
                is_valid=False,
                error_message=f"Error validating spot price: {e}"
            )

    def validate_vix(self, vix_level: float, timestamp: datetime) -> ValidationResult:
        """Validate India VIX data"""
        try:
            # Check timestamp
            data_age = (datetime.now() - timestamp).total_seconds()

            # Validate age
            if data_age > self.max_data_age_seconds:
                return ValidationResult(
                    is_valid=False,
                    error_message=f"VIX data too old: {data_age:.0f}s (max {self.max_data_age_seconds}s)",
                    data_age_seconds=data_age,
                    is_cached=True
                )

            # Validate range (VIX is typically 10-40)
            if not (5 <= vix_level <= 100):
                return ValidationResult(
                    is_valid=False,
                    error_message=f"VIX out of expected range: {vix_level:.2f}",
                    data_age_seconds=data_age
                )

            # Validate is not NaN or None
            if vix_level is None or (isinstance(vix_level, float) and vix_level != vix_level):
                return ValidationResult(
                    is_valid=False,
                    error_message="VIX is NaN or None",
                    data_age_seconds=data_age
                )

            return ValidationResult(
                is_valid=True,
                data_age_seconds=data_age,
                is_live=(data_age < 10)
            )

        except Exception as e:
            return ValidationResult(
                is_valid=False,
                error_message=f"Error validating VIX: {e}"
            )

    def validate_option_chain(self, chain_data: Dict, timestamp: datetime) -> ValidationResult:
        """Validate option chain data"""
        try:
            # Check timestamp
            data_age = (datetime.now() - timestamp).total_seconds()

            # Validate age
            if data_age > 300:  # 5 minute TTL for option chain
                return ValidationResult(
                    is_valid=False,
                    error_message=f"Option chain data too old: {data_age:.0f}s (max 300s)",
                    data_age_seconds=data_age,
                    is_cached=True
                )

            # Validate structure
            if not isinstance(chain_data, dict):
                return ValidationResult(
                    is_valid=False,
                    error_message="Option chain is not a dictionary",
                    data_age_seconds=data_age
                )

            # Validate has strikes
            if len(chain_data) < 5:
                return ValidationResult(
                    is_valid=False,
                    error_message=f"Option chain has too few strikes: {len(chain_data)} (expected >=5)",
                    data_age_seconds=data_age
                )

            # Validate each strike
            for strike, strike_data in chain_data.items():
                if not isinstance(strike_data, dict):
                    return ValidationResult(
                        is_valid=False,
                        error_message=f"Strike {strike} data is not a dictionary",
                        data_age_seconds=data_age
                    )

                # Check required fields
                required_fields = ['call_ltp', 'put_ltp', 'call_bid', 'put_bid']
                for field in required_fields:
                    if field not in strike_data:
                        return ValidationResult(
                            is_valid=False,
                            error_message=f"Missing field '{field}' in strike {strike}",
                            data_age_seconds=data_age
                        )

            return ValidationResult(
                is_valid=True,
                data_age_seconds=data_age,
                is_live=(data_age < 30)
            )

        except Exception as e:
            return ValidationResult(
                is_valid=False,
                error_message=f"Error validating option chain: {e}"
            )

    def validate_api_response(self, response: Dict[str, Any],
                            expected_fields: List[str]) -> ValidationResult:
        """Validate generic API response"""
        try:
            # Check required fields
            missing_fields = [f for f in expected_fields if f not in response]
            if missing_fields:
                return ValidationResult(
                    is_valid=False,
                    error_message=f"Missing required fields: {missing_fields}"
                )

            # Check timestamp field if present
            if 'timestamp' in response:
                try:
                    timestamp = response['timestamp']
                    if isinstance(timestamp, str):
                        timestamp = datetime.fromisoformat(timestamp)

                    data_age = (datetime.now() - timestamp).total_seconds()
                    if data_age > self.max_data_age_seconds:
                        return ValidationResult(
                            is_valid=False,
                            error_message=f"Response data too old: {data_age:.0f}s (max {self.max_data_age_seconds}s)",
                            data_age_seconds=data_age,
                            is_cached=True
                        )

                    return ValidationResult(
                        is_valid=True,
                        data_age_seconds=data_age,
                        is_live=(data_age < 10)
                    )
                except Exception as e:
                    logger.warning(f"Could not parse timestamp: {e}")

            return ValidationResult(
                is_valid=True,
                warnings=["No timestamp field for age validation"]
            )

        except Exception as e:
            return ValidationResult(
                is_valid=False,
                error_message=f"Error validating response: {e}"
            )


class SignalAPIValidator:
    """Validate /signal API endpoint requirements"""

    def __init__(self, max_data_age_seconds: int = 60):
        self.market_data_validator = MarketDataValidator(max_data_age_seconds, allow_cached=False)
        self.max_data_age_seconds = max_data_age_seconds

    def validate_signal_request(self, spot_price: float, spot_timestamp: datetime,
                               vix_level: float, vix_timestamp: datetime) -> ValidationResult:
        """
        Validate /signal endpoint has fresh market data

        Args:
            spot_price: Nifty spot price
            spot_timestamp: When spot price was fetched
            vix_level: India VIX
            vix_timestamp: When VIX was fetched

        Returns:
            ValidationResult with error if data is not live
        """
        # Validate spot price
        spot_result = self.market_data_validator.validate_spot_price(spot_price, spot_timestamp)
        if not spot_result.is_valid:
            logger.error(f"❌ /signal validation failed: {spot_result.error_message}")
            return spot_result

        # Validate VIX
        vix_result = self.market_data_validator.validate_vix(vix_level, vix_timestamp)
        if not vix_result.is_valid:
            logger.error(f"❌ /signal validation failed: {vix_result.error_message}")
            return vix_result

        # Check if both are live (not cached)
        if not spot_result.is_live or not vix_result.is_live:
            age_str = f"spot: {spot_result.data_age_seconds:.0f}s, VIX: {vix_result.data_age_seconds:.0f}s"
            return ValidationResult(
                is_valid=False,
                error_message=f"Market data not live: {age_str} (max {self.max_data_age_seconds}s)",
                data_age_seconds=max(spot_result.data_age_seconds, vix_result.data_age_seconds),
                is_cached=True
            )

        logger.info(f"✅ /signal validation passed (spot age: {spot_result.data_age_seconds:.1f}s, VIX age: {vix_result.data_age_seconds:.1f}s)")

        return ValidationResult(
            is_valid=True,
            data_age_seconds=max(spot_result.data_age_seconds, vix_result.data_age_seconds),
            is_live=True
        )


class MonitorAPIValidator:
    """Validate /monitor API endpoint requirements"""

    def __init__(self, max_data_age_seconds: int = 30):
        self.market_data_validator = MarketDataValidator(max_data_age_seconds, allow_cached=False)
        self.max_data_age_seconds = max_data_age_seconds

    def validate_monitor_request(self, spot_price: float, spot_timestamp: datetime,
                                option_chain: Dict, chain_timestamp: datetime) -> ValidationResult:
        """
        Validate /monitor endpoint has fresh market data

        Args:
            spot_price: Nifty spot price
            spot_timestamp: When spot price was fetched
            option_chain: Option chain dictionary
            chain_timestamp: When option chain was fetched

        Returns:
            ValidationResult with error if data is not live
        """
        # Validate spot price
        spot_result = self.market_data_validator.validate_spot_price(spot_price, spot_timestamp)
        if not spot_result.is_valid:
            logger.error(f"❌ /monitor validation failed: {spot_result.error_message}")
            return spot_result

        # Validate option chain
        chain_result = self.market_data_validator.validate_option_chain(option_chain, chain_timestamp)
        if not chain_result.is_valid:
            logger.error(f"❌ /monitor validation failed: {chain_result.error_message}")
            return chain_result

        # Check if both are live
        if not spot_result.is_live or not chain_result.is_live:
            age_str = f"spot: {spot_result.data_age_seconds:.0f}s, chain: {chain_result.data_age_seconds:.0f}s"
            return ValidationResult(
                is_valid=False,
                error_message=f"Market data not live: {age_str} (max {self.max_data_age_seconds}s)",
                data_age_seconds=max(spot_result.data_age_seconds, chain_result.data_age_seconds),
                is_cached=True
            )

        logger.info(f"✅ /monitor validation passed (spot age: {spot_result.data_age_seconds:.1f}s, chain age: {chain_result.data_age_seconds:.1f}s)")

        return ValidationResult(
            is_valid=True,
            data_age_seconds=max(spot_result.data_age_seconds, chain_result.data_age_seconds),
            is_live=True
        )
