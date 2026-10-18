"""
IST market clock helpers.

The host clock is UTC, so every market-hours or trading-day decision must go
through ``now_ist()`` instead of a naive ``datetime.now()``.
"""

from datetime import date, datetime, time
from typing import Optional
from zoneinfo import ZoneInfo

from data.expiry_calendar import get_holiday, is_trading_day

IST = ZoneInfo("Asia/Kolkata")
MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)


def now_ist() -> datetime:
    """Current time as a timezone-aware IST datetime."""
    return datetime.now(IST)


def is_market_hours(now: Optional[datetime] = None) -> bool:
    """
    True when ``now`` falls in the 09:15-15:30 IST cash/derivatives session on a
    trading day. Aware datetimes are converted to IST; naive datetimes are
    interpreted as IST wall-clock time.
    """
    if now is None:
        now = now_ist()
    elif now.tzinfo is None:
        now = now.replace(tzinfo=IST)
    else:
        now = now.astimezone(IST)
    return is_trading_day(now.date()) and MARKET_OPEN <= now.time() <= MARKET_CLOSE


def market_day_gate(day: date) -> Optional[str]:
    """
    None when ``day`` is a trading day. Otherwise a human-readable reason the
    market is closed, e.g. ``'market closed (holiday: Dussehra)'``.
    """
    if is_trading_day(day):
        return None
    holiday = get_holiday(day)
    if holiday is not None and holiday.get("segment_closed"):
        return f"market closed (holiday: {holiday['name']})"
    if day.weekday() >= 5:
        return "market closed (weekend)"
    return "market closed (holiday)"
