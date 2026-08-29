"""
API Signal Validator — Middleware for /signal and /monitor endpoints

Ensures:
- Latest market data is fetched before responding
- Data freshness validation
- Error responses for stale/invalid data
- Detailed error messages for debugging
"""

import logging
from typing import Dict, Any, Optional
from datetime import datetime
from pydantic import BaseModel, Field

from data.data_validator import SignalAPIValidator, MonitorAPIValidator, ValidationResult

logger = logging.getLogger(__name__)


# ============================================================================
# Response Models with Validation
# ============================================================================

class DataFreshnessError(BaseModel):
    """Error response for stale/invalid market data"""
    error: str = Field(..., description="Error type")
    message: str = Field(..., description="Detailed error message")
    data_age_seconds: Optional[float] = Field(None, description="Age of the stale data")
    is_cached: bool = Field(False, description="Whether data was from cache")
    required_freshness_seconds: int = Field(60, description="Required data freshness")
    action: str = Field("retry", description="Recommended action")
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())

    class Config:
        schema_extra = {
            "example": {
                "error": "STALE_MARKET_DATA",
                "message": "Market data too old: 65s (max 60s). Please retry.",
                "data_age_seconds": 65,
                "is_cached": True,
                "required_freshness_seconds": 60,
                "action": "retry",
                "timestamp": "2026-08-29T16:35:00"
            }
        }


class SignalValidatorMiddleware:
    """Validate /signal endpoint before responding"""

    def __init__(self, max_data_age_seconds: int = 60):
        self.validator = SignalAPIValidator(max_data_age_seconds)
        self.max_data_age_seconds = max_data_age_seconds

    def validate_before_signal(self, spot_price: float, spot_timestamp: datetime,
                              vix_level: float, vix_timestamp: datetime,
                              endpoint_name: str = "/signal") -> Dict[str, Any]:
        """
        Validate market data before /signal response

        Returns:
            {
                "valid": bool,
                "error": Optional[DataFreshnessError],
                "data_quality": ValidationResult
            }
        """
        # Validate both spot and VIX
        result = self.validator.validate_signal_request(
            spot_price, spot_timestamp,
            vix_level, vix_timestamp
        )

        if not result.is_valid:
            error_response = DataFreshnessError(
                error="STALE_MARKET_DATA",
                message=result.error_message,
                data_age_seconds=result.data_age_seconds,
                is_cached=result.is_cached,
                required_freshness_seconds=self.max_data_age_seconds,
                action="retry_with_latest_data"
            )

            logger.error(f"❌ {endpoint_name} validation failed: {result.error_message}")

            return {
                "valid": False,
                "error": error_response,
                "data_quality": result
            }

        logger.info(f"✅ {endpoint_name} validation passed")

        return {
            "valid": True,
            "error": None,
            "data_quality": result
        }


class MonitorValidatorMiddleware:
    """Validate /monitor endpoint before responding"""

    def __init__(self, max_data_age_seconds: int = 30):
        self.validator = MonitorAPIValidator(max_data_age_seconds)
        self.max_data_age_seconds = max_data_age_seconds

    def validate_before_monitor(self, spot_price: float, spot_timestamp: datetime,
                               option_chain: Dict, chain_timestamp: datetime,
                               endpoint_name: str = "/monitor") -> Dict[str, Any]:
        """
        Validate market data before /monitor response

        Returns:
            {
                "valid": bool,
                "error": Optional[DataFreshnessError],
                "data_quality": ValidationResult
            }
        """
        # Validate spot and option chain
        result = self.validator.validate_monitor_request(
            spot_price, spot_timestamp,
            option_chain, chain_timestamp
        )

        if not result.is_valid:
            error_response = DataFreshnessError(
                error="STALE_MARKET_DATA",
                message=result.error_message,
                data_age_seconds=result.data_age_seconds,
                is_cached=result.is_cached,
                required_freshness_seconds=self.max_data_age_seconds,
                action="refresh_market_data"
            )

            logger.error(f"❌ {endpoint_name} validation failed: {result.error_message}")

            return {
                "valid": False,
                "error": error_response,
                "data_quality": result
            }

        logger.info(f"✅ {endpoint_name} validation passed")

        return {
            "valid": True,
            "error": None,
            "data_quality": result
        }


# ============================================================================
# Helper Functions for API Endpoints
# ============================================================================

def validate_signal_data(spot_price: float, spot_timestamp: datetime,
                        vix_level: float, vix_timestamp: datetime) -> tuple[bool, Optional[DataFreshnessError]]:
    """
    Validate data before returning /signal response

    Returns:
        (is_valid, error_response)
    """
    validator = SignalValidatorMiddleware()
    result = validator.validate_before_signal(spot_price, spot_timestamp, vix_level, vix_timestamp)

    return result["valid"], result["error"]


def validate_monitor_data(spot_price: float, spot_timestamp: datetime,
                         option_chain: Dict, chain_timestamp: datetime) -> tuple[bool, Optional[DataFreshnessError]]:
    """
    Validate data before returning /monitor response

    Returns:
        (is_valid, error_response)
    """
    validator = MonitorValidatorMiddleware()
    result = validator.validate_before_monitor(spot_price, spot_timestamp, option_chain, chain_timestamp)

    return result["valid"], result["error"]


# ============================================================================
# FastAPI Integration Examples
# ============================================================================

"""
Example usage in FastAPI endpoints:

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from data.data_validator import SignalAPIValidator

app = FastAPI()

@app.get("/signal")
async def get_signal():
    # Fetch latest market data
    spot, spot_ts = live_fetcher.fetch_nifty_spot_price()
    vix, vix_ts = live_fetcher.fetch_vix_level()

    # Validate data freshness
    is_valid, error = validate_signal_data(spot, spot_ts, vix, vix_ts)

    if not is_valid:
        logger.error(f"❌ Stale data rejected: {error.message}")
        return JSONResponse(
            status_code=503,  # Service Unavailable
            content=error.dict(),
            headers={"Retry-After": "5"}  # Suggest retry after 5 seconds
        )

    # Proceed with signal generation
    # ... generate signal ...

    return {
        "timestamp": datetime.now().isoformat(),
        "data_freshness": {
            "spot_age_seconds": (datetime.now() - spot_ts).total_seconds(),
            "vix_age_seconds": (datetime.now() - vix_ts).total_seconds(),
            "is_live": True
        },
        # ... signal data ...
    }


@app.get("/monitor")
async def monitor_trades():
    # Fetch latest market data
    spot, spot_ts = live_fetcher.fetch_nifty_spot_price()
    chain = live_fetcher.fetch_option_chain("NIFTY50", expiry)
    chain_ts = datetime.now()

    # Validate data freshness (stricter: 30s instead of 60s)
    is_valid, error = validate_monitor_data(spot, spot_ts, chain, chain_ts)

    if not is_valid:
        logger.error(f"❌ Stale data rejected: {error.message}")
        return JSONResponse(
            status_code=503,
            content=error.dict(),
            headers={"Retry-After": "10"}
        )

    # Proceed with monitoring
    # ... analyze trades ...

    return {
        "timestamp": datetime.now().isoformat(),
        "data_freshness": {
            "spot_age_seconds": (datetime.now() - spot_ts).total_seconds(),
            "chain_age_seconds": (datetime.now() - chain_ts).total_seconds(),
            "is_live": True
        },
        # ... monitoring data ...
    }
"""
