"""
data/expiry_calendar.py checked against the NSE F&O archive.

tests/fixtures/nifty_expiries_archive.json holds only derived facts: the NIFTY
weekly expiry dates observed in the archive (an expiry counts as observed when
the archive file dated on that expiry day carries rows for it), the monthly
expiry for each month, and the raw expiry days that were exchange holidays
(the expiry moved to the previous trading day). It contains no prices.

Observed schedule:
  Thursday weekly and monthly expiries through 2025-08-28 (first: 2019-02-14).
  Tuesday weekly and monthly expiries from 2025-09-02.
  No Monday-expiry era.
  Monthly expiry = last raw expiry weekday of the month (holiday-shifted).
  Note: 2025-04-30 is a weekly (shifted from Thu 2025-05-01), not April's monthly.
"""

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

import data.expiry_calendar as ec

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "nifty_expiries_archive.json"
HOLIDAYS = Path(__file__).resolve().parent.parent / "data" / "nse_holidays.json"

RANGE_START = date(2019, 2, 11)   # Monday of the first observed weekly week
RANGE_END = date(2026, 10, 31)


@pytest.fixture(scope="module")
def archive():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return {
        "weekly": [date.fromisoformat(x) for x in payload["weekly_expiries"]],
        "monthly": [date.fromisoformat(x) for x in payload["monthly_expiries"]],
        "closures": [(date.fromisoformat(c["raw"]), date.fromisoformat(c["expiry"]))
                     for c in payload["raw_day_closures"]],
        "listed_only": [date.fromisoformat(x) for x in payload["listed_only"]],
    }


def _weeks(start: date, end: date):
    """Monday-to-Sunday windows covering [start, end]."""
    cur = start - timedelta(days=start.weekday())
    while cur <= end:
        yield cur, cur + timedelta(days=6)
        cur += timedelta(days=7)


# ── Weekly expiries ─────────────────────────────────────────────────────────

def test_weekly_expiry_set_matches_archive(archive):
    got = ec.get_weekly_expiries(RANGE_START, RANGE_END)
    assert got == archive["weekly"]


def test_every_observed_week_has_the_archive_expiry(archive):
    """Week by week: the calendar's weekly expiries equal the archive's, including holiday shifts."""
    observed = set(archive["weekly"])
    for mon, sun in _weeks(RANGE_START, RANGE_END):
        expected = sorted(d for d in observed if mon <= d <= sun)
        got = ec.get_weekly_expiries(mon, sun)
        assert got == expected, f"week of {mon}: calendar {got} archive {expected}"
        assert len(got) == 1, f"week of {mon} should have exactly one weekly expiry, got {got}"


def _shifted_expiries(archive):
    """Expiries that moved off their raw weekday: archive closures plus the forward holiday 2026-10-19."""
    return {s for _, s in archive["closures"]} | {date(2026, 10, 19)}


def test_weekly_expiry_weekday_by_era(archive):
    shifted = _shifted_expiries(archive)
    for d in archive["weekly"]:
        expected = 3 if d < ec._TUESDAY_CUTOVER else 1
        assert d.weekday() == expected or d in shifted, d


def test_no_monday_expiries_except_holiday_shifts(archive):
    shifted = _shifted_expiries(archive)
    mondays = [d for d in archive["weekly"] if d.weekday() == 0]
    assert all(d in shifted for d in mondays), mondays


def test_thursday_era_last_expiry_and_tuesday_era_first_expiry(archive):
    weekly = archive["weekly"]
    last_thu = max(d for d in weekly if d < ec._TUESDAY_CUTOVER)
    first_tue = min(d for d in weekly if d >= ec._TUESDAY_CUTOVER)
    assert last_thu == date(2025, 8, 28)
    assert first_tue == date(2025, 9, 2)
    assert ec.is_thursday_expiry_era(last_thu) is True
    assert ec.is_thursday_expiry_era(first_tue) is False


def test_first_observed_weekly_is_2019_02_14(archive):
    assert min(archive["weekly"]) == date(2019, 2, 14)
    assert ec.get_weekly_expiries(date(2019, 2, 11), date(2019, 2, 17)) == [date(2019, 2, 14)]


def test_listed_only_dates_are_in_calendar(archive):
    """Expiries listed in the archive but after its last file (2026-10-16)."""
    got = ec.get_weekly_expiries(date(2026, 10, 17), date(2026, 10, 31))
    assert got == archive["listed_only"] == [date(2026, 10, 19), date(2026, 10, 27)]


# ── Monthly expiries ────────────────────────────────────────────────────────

def test_monthly_expiries_match_archive(archive):
    assert ec.get_monthly_expiries(date(2019, 2, 1), date(2026, 10, 31)) == archive["monthly"]


def test_monthly_expiries_are_weekly_expiries(archive):
    weekly = set(archive["weekly"])
    assert all(m in weekly for m in archive["monthly"])


def test_monthly_switches_with_weekly_in_same_week():
    assert ec.get_monthly_expiry(2025, 8) == date(2025, 8, 28)   # last Thursday, still Thursday era
    assert ec.get_monthly_expiry(2025, 9) == date(2025, 9, 30)   # last Tuesday, Tuesday era
    assert ec.get_monthly_expiry(2025, 9).weekday() == 1


def test_monthly_ignores_query_date_era():
    """A Thursday-era query date must not pick Thursdays for a Tuesday-era month."""
    assert ec.get_monthly_expiry(2025, 9, ref_date=date(2025, 8, 29)) == date(2025, 9, 30)


# ── Holiday shifts (archive-derived closures) ───────────────────────────────

def test_historical_closures_shift_to_previous_trading_day(archive):
    for raw, shifted in archive["closures"]:
        assert ec.is_trading_day(raw) is False, raw
        assert ec._expiry_shift(raw) == shifted, raw
        assert ec.is_trading_day(shifted) is True, shifted


def test_historical_closures_are_before_forward_cutoff_and_in_holiday_file():
    payload = json.loads(HOLIDAYS.read_text(encoding="utf-8"))
    closures = payload["historical_expiry_closures"]
    assert len(closures) == 19
    assert all(date.fromisoformat(c["date"]) < date(2026, 10, 19) for c in closures)
    # forward-looking list is untouched
    assert all(date.fromisoformat(h["date"]) >= date(2026, 10, 19) for h in payload["holidays"])


def test_holiday_shifted_weekly_expiry_example():
    # Thursday 2024-04-11 (Eid) -> Wednesday 2024-04-10
    assert ec.get_weekly_expiries(date(2024, 4, 8), date(2024, 4, 14)) == [date(2024, 4, 10)]


def test_holiday_shifted_tuesday_expiry_example():
    # Tuesday 2026-03-03 closed -> Monday 2026-03-02
    assert ec.get_weekly_expiries(date(2026, 3, 2), date(2026, 3, 8)) == [date(2026, 3, 2)]


# ── Entry-point helpers that were Monday-era aware ──────────────────────────

def test_next_weekly_expiry_across_cutover_uses_candidate_era():
    """From the last Thursday-era day, the next expiry is the first Tuesday, not a Thursday."""
    assert ec.get_next_weekly_expiry(date(2025, 8, 29)) == (date(2025, 9, 2), 4)
    assert ec.get_next_weekly_expiry(date(2025, 8, 28)) == (date(2025, 9, 2), 5)


def test_weekly_entry_window_pre_and_post_cutover():
    # Thursday era: Monday signal sees Thursday at 3 DTE
    assert ec.get_weekly_expiry_in_range(date(2025, 8, 25), 3, 8) == (date(2025, 8, 28), 3)
    # Tuesday era: Monday signal skips the 1-DTE Tuesday and takes the next one at 8 DTE
    assert ec.get_weekly_expiry_in_range(date(2025, 9, 1), 3, 8) == (date(2025, 9, 9), 8)


def test_no_monday_cutover_constant_remains():
    assert not hasattr(ec, "_MONDAY_CUTOVER")
    assert ec._TUESDAY_CUTOVER == date(2025, 9, 1)
