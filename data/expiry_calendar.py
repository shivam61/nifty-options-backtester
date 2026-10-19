"""
Nifty option expiry calendar.

NSE moved NIFTY expiries twice in recent years:
  Pre  2024-04-04: weekly = every Thursday, monthly = last Thursday of month
  2024-04-04 .. 2025-08-31: weekly = every Monday, monthly = last Monday of month
  Post 2025-09-01: weekly = every Tuesday, monthly = last Tuesday of month

Trading holidays (data/nse_holidays.json): when a raw expiry day is a
segment-closed exchange holiday, the expiry moves to the previous trading day.
The holiday file only lists forward-looking dates, so historical expiries are
unchanged. Muhurat sessions are informational and do not shift expiries.

All public functions accept an optional ``ref_date`` to select the correct
weekday automatically. When omitted they default to today, so code that only
ever runs in the present (signal mode, monitor) just works.
"""

import calendar
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

# NSE expiry schedule cutovers.
_MONDAY_CUTOVER = date(2024, 4, 4)
_TUESDAY_CUTOVER = date(2025, 9, 1)

# Holiday shifts can chain over several closed days; bound the lookahead used
# when scanning raw expiry days so a shifted expiry is never missed.
_MAX_SHIFT_DAYS = 14

_HOLIDAYS_PATH = Path(__file__).resolve().parent / "nse_holidays.json"
_holiday_cache: Optional[dict[date, dict]] = None


# ── Holiday calendar ────────────────────────────────────────────────────────

def _load_holidays() -> dict[date, dict]:
    """Load data/nse_holidays.json once, keyed by date."""
    global _holiday_cache
    if _holiday_cache is None:
        payload = json.loads(_HOLIDAYS_PATH.read_text(encoding="utf-8"))
        _holiday_cache = {
            date.fromisoformat(entry["date"]): entry
            for entry in payload.get("holidays", [])
        }
    return _holiday_cache


def _closed_holiday_dates() -> frozenset[date]:
    """Dates on which the equity and derivatives segments are closed."""
    return frozenset(d for d, h in _load_holidays().items() if h.get("segment_closed"))


def get_holiday(d: date) -> Optional[dict]:
    """Holiday record for ``d`` (any kind, including Muhurat), or None."""
    return _load_holidays().get(d)


def is_trading_day(d: date) -> bool:
    """True when ``d`` is a weekday and not a segment-closed NSE holiday."""
    return d.weekday() < 5 and d not in _closed_holiday_dates()


def is_market_open_day(d: date) -> bool:
    """Alias of :func:`is_trading_day` for call sites that gate live modes."""
    return is_trading_day(d)


def previous_trading_day(d: date) -> date:
    """Latest trading day strictly before ``d``."""
    cur = d - timedelta(days=1)
    for _ in range(_MAX_SHIFT_DAYS * 4):
        if is_trading_day(cur):
            return cur
        cur -= timedelta(days=1)
    raise RuntimeError(f"No trading day found within {_MAX_SHIFT_DAYS * 4} days before {d}")


def _expiry_shift(d: date) -> date:
    """Expiry actually traded for raw expiry day ``d`` (previous trading day if closed)."""
    return d if is_trading_day(d) else previous_trading_day(d)


# ── Backward-compat; callers in legacy code path ───────────────────────────

def _expiry_weekday(ref_date: date) -> int:
    """Return calendar weekday constant for NSE expiry on the given date."""
    if ref_date >= _TUESDAY_CUTOVER:
        return calendar.TUESDAY
    if ref_date >= _MONDAY_CUTOVER:
        return calendar.MONDAY
    return calendar.THURSDAY


def _all_weekday_in_month(year: int, month: int, weekday: int) -> list[date]:
    """All dates in (year, month) that fall on ``weekday`` (calendar.MONDAY etc.)."""
    cal = calendar.monthcalendar(year, month)
    return [
        date(year, month, week[weekday])
        for week in cal
        if week[weekday] != 0
    ]


def get_all_thursdays(year: int, month: int) -> list[date]:
    """Get all Thursdays in a given month (legacy — pre-2024 use only)."""
    return _all_weekday_in_month(year, month, calendar.THURSDAY)


# ── Core helpers ────────────────────────────────────────────────────────────

def is_thursday_expiry_era(ref_date: date) -> bool:
    """True for the pre-2024-04-04 era in which NIFTY weekly expiries fall on Thursday."""
    return ref_date < _MONDAY_CUTOVER


def get_monthly_expiry(year: int, month: int, ref_date: Optional[date] = None) -> date:
    """
    Last expiry day of the month (raw last Tuesday/Monday/Thursday, shifted to
    the previous trading day if that day is an NSE holiday).
    ``ref_date`` defaults to mid-month of the requested year/month.
    """
    if ref_date is None:
        ref_date = date(year, month, 15)
    weekday = _expiry_weekday(ref_date)
    days = _all_weekday_in_month(year, month, weekday)
    return _expiry_shift(max(days))


def get_weekly_expiries(start_date: date, end_date: date) -> list[date]:
    """All weekly expiry dates (Tuesdays, Mondays or Thursdays by era) in [start, end]."""
    expiries: set[date] = set()
    current = start_date
    scan_end = end_date + timedelta(days=_MAX_SHIFT_DAYS)
    while current <= scan_end:
        if current.weekday() == _expiry_weekday(current):
            shifted = _expiry_shift(current)
            if start_date <= shifted <= end_date:
                expiries.add(shifted)
        current += timedelta(days=1)
    return sorted(expiries)


def get_monthly_expiries(start_date: date, end_date: date) -> list[date]:
    """All monthly expiry dates in [start, end]."""
    expiries: list[date] = []
    y, m = start_date.year, start_date.month
    while True:
        exp = get_monthly_expiry(y, m)
        if exp > end_date:
            break
        if exp >= start_date:
            expiries.append(exp)
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return expiries


def get_next_monthly_expiry(from_date: date) -> date:
    """Next monthly expiry on or after ``from_date``."""
    y, m = from_date.year, from_date.month
    for _ in range(3):
        exp = get_monthly_expiry(y, m)
        if exp >= from_date:
            return exp
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return get_monthly_expiry(y, m)


def get_best_expiry_for_dte(from_date: date, target_dte: int) -> tuple[date, int]:
    """Monthly expiry closest to ``target_dte`` days out. Returns (expiry, actual_dte)."""
    candidates: list[tuple[date, int, int]] = []
    y, m = from_date.year, from_date.month
    for _ in range(4):
        exp = get_monthly_expiry(y, m)
        if exp > from_date:
            actual_dte = (exp - from_date).days
            candidates.append((exp, actual_dte, abs(actual_dte - target_dte)))
        m += 1
        if m > 12:
            m, y = 1, y + 1
    if not candidates:
        exp = get_next_monthly_expiry(from_date)
        return exp, (exp - from_date).days
    best = min(candidates, key=lambda x: x[2])
    return best[0], best[1]


def format_expiry_label(expiry: date) -> str:
    """Human-readable expiry label, e.g. '28 Apr 2026'."""
    return expiry.strftime("%-d %b %Y")


# ── Weekly helpers ──────────────────────────────────────────────────────────

def get_next_weekly_expiry(from_date: date) -> tuple[date, int]:
    """
    Next weekly expiry *after* ``from_date`` (Tue, Mon or Thu depending on era),
    holiday-shifted. Returns (expiry_date, dte) with DTE measured to the shifted
    expiry.
    """
    weekday = _expiry_weekday(from_date)
    current = from_date + timedelta(days=1)
    while True:
        if current.weekday() == weekday:
            shifted = _expiry_shift(current)
            if shifted > from_date:
                return shifted, (shifted - from_date).days
        current += timedelta(days=1)


def get_weekly_expiry_in_range(
    from_date: date,
    min_dte: int,
    max_dte: int,
    lookahead_cycles: int = 3,
) -> tuple[Optional[date], int]:
    """
    Return the first weekly expiry whose DTE falls inside ``[min_dte, max_dte]``.

    This is more robust than taking the immediate next expiry because after an
    exchange weekday shift the nearest expiry may be too close (for example,
    Monday entry with Tuesday expiry). In that case we intentionally skip to the
    following weekly cycle if it lands inside the desired DTE window.

    DTE is measured to the holiday-shifted expiry (e.g. a Tuesday expiry moved
    to Monday by a holiday is one day closer).
    """
    if min_dte > max_dte:
        return None, 0

    anchor = from_date
    current = from_date
    for _ in range(max(1, lookahead_cycles)):
        expiry, _ = get_next_weekly_expiry(current)
        dte = (expiry - anchor).days
        if min_dte <= dte <= max_dte:
            return expiry, dte
        current = expiry
    return None, 0


def get_upcoming_weekly_expiries(from_date: date, count: int = 4) -> list[dict]:
    """Next ``count`` weekly expiries (Tue, Mon or Thu) with DTE info."""
    results: list[dict] = []
    seen: set[date] = set()
    current = from_date + timedelta(days=1)
    while len(results) < count:
        if current.weekday() == _expiry_weekday(current):
            exp = _expiry_shift(current)
            if exp > from_date and exp not in seen:
                seen.add(exp)
                dte = (exp - from_date).days
                results.append({
                    "expiry": exp,
                    "label": format_expiry_label(exp),
                    "dte": dte,
                    "is_monthly": exp == get_monthly_expiry(exp.year, exp.month),
                })
        current += timedelta(days=1)
    return results


# ── Monthly-only listing (used by existing backtest / signal paths) ─────────

def get_upcoming_expiries(from_date: date, count: int = 5) -> list[dict]:
    """
    Next ``count`` *monthly* expiries with DTE info.
    Weekday is Tuesday, Monday or Thursday depending on ``from_date``.
    """
    results: list[dict] = []
    y, m = from_date.year, from_date.month
    for _ in range(24):
        exp = get_monthly_expiry(y, m)
        if exp > from_date:
            dte = (exp - from_date).days
            results.append({
                "expiry": exp,
                "label": format_expiry_label(exp),
                "dte": dte,
                "is_monthly": True,
                "is_weekly": False,
                "is_current_month": exp.month == from_date.month,
            })
            if len(results) >= count:
                break
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return results


# ── Combined weekly+monthly listing (used by signal-combined & ExpirySelector) ─

def get_all_expiries(from_date: date, count: int = 8) -> list[dict]:
    """
    Next ``count`` expiries mixing both weekly AND monthly dates.

    In the Monday/Tuesday eras every weekly expiry day is a potential expiry;
    the last such day of each month is additionally tagged as monthly.
    Pre-2024 the same logic applies to Thursdays. Holiday-shifted expiries are
    reported on the trading day they actually settle.

    Useful for ExpirySelector (backtest + signal) so it can compare
    short-DTE weekly trades against longer-DTE monthly ones.
    """
    weekday = _expiry_weekday(from_date)
    results: list[dict] = []
    seen: set[date] = set()
    current = from_date + timedelta(days=1)
    while len(results) < count:
        if current.weekday() == weekday:
            exp = _expiry_shift(current)
            if exp > from_date and exp not in seen:
                seen.add(exp)
                dte = (exp - from_date).days
                is_monthly = exp == get_monthly_expiry(exp.year, exp.month, ref_date=exp)
                results.append({
                    "expiry": exp,
                    "label": format_expiry_label(exp),
                    "dte": dte,
                    "is_monthly": is_monthly,
                    "is_weekly": not is_monthly,
                })
        current += timedelta(days=1)
    return results
