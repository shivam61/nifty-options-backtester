"""
Thursday-era weekly signal day (WeeklyBacktestConfig.era_aware_signal_day).

NIFTY weekly expiries were Thursdays until 2025-08-28 (no Monday era) and Tuesdays from
2025-09-02. The default Monday/Tuesday signal selects the Thursday expiry at 3 DTE on Monday,
then the Tuesday fill sits at 2 DTE and is dropped by the fill-time window. With the flag on,
the Thursday-era signal fires on Thursday (expiry day) and targets the next weekly expiry, so
the Friday fill lands at about 6 DTE. Tuesday-era behaviour must be identical with the flag on or off.
"""

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

import data.expiry_calendar as ec
from config import BacktestConfig, WeeklyBacktestConfig
from backtester.combined_engine import CombinedBacktestEngine
from strategies.base import TradeAction

THURSDAY_ERA_END = date(2025, 8, 28)     # last Thursday expiry
TUESDAY_CUTOVER = date(2025, 9, 1)       # ec._TUESDAY_CUTOVER


def _engine(era_aware: bool) -> CombinedBacktestEngine:
    dates = pd.bdate_range("2023-09-01", "2024-12-31")
    df = pd.DataFrame({
        "nifty_close": [22000.0] * len(dates), "nifty_high": [22100.0] * len(dates),
        "nifty_low": [21900.0] * len(dates), "nifty_open": [22000.0] * len(dates),
        "nifty_mid_session": [22000.0] * len(dates), "vix": [16.0] * len(dates),
    }, index=dates)
    eng = CombinedBacktestEngine(
        data=df,
        monthly_config=BacktestConfig(initial_capital=500_000, lot_size=65, max_lots=15),
        weekly_config=WeeklyBacktestConfig(era_aware_signal_day=era_aware),
        monthly_strategy=MagicMock(name="s"),
        exit_engine=None,
        entry_model=None,
        weekly_risk_engine=None,
    )
    eng.prod_gate.should_block_weekly_entry = MagicMock(return_value=(False, ""))
    eng._effective_allocation = MagicMock(return_value=(0.5, 0.5))
    eng._compute_weekly_dynamic_scale = MagicMock(return_value=1.0)
    eng._estimate_weekly_delta = MagicMock(return_value=0.2)
    strategy = MagicMock(name="weekly_strategy")
    strategy.should_enter.return_value = TradeAction.ENTER
    strategy.create_trade.return_value = MagicMock(net_credit=10.0, legs=[])
    eng._select_weekly_strategy = MagicMock(return_value=strategy)
    return eng


def _signal(eng, signal_date: date) -> None:
    row = pd.Series({"nifty_close": 22000.0, "nifty_mid_session": 22000.0, "vix": 16.0})
    eng._process_weekly_entry(row, signal_date, 22000.0, 16.0, {}, 500_000.0, 0, 0.0)


def _fill(eng, fill_date: date) -> None:
    row = pd.Series({"nifty_mid_session": 22000.0, "nifty_open": 22000.0, "nifty_close": 22000.0})
    with patch("backtester.combined_engine.build_tracker", MagicMock()), \
            patch.object(eng.weekly_fill_model, "apply_entry_fill", MagicMock()):
        eng._fill_pending_weekly_entry(fill_date, row)


def _next_trading_day(d: date) -> date:
    d = d + timedelta(days=1)
    while not ec.is_trading_day(d):
        d += timedelta(days=1)
    return d


def _thursdays(start: date, end: date):
    d = start
    while d <= end:
        if d.weekday() == 3:
            yield d
        d += timedelta(days=1)


# ── Config and calendar helper ─────────────────────────────────────────────

def test_default_flag_is_false():
    assert WeeklyBacktestConfig().era_aware_signal_day is False


def test_is_thursday_expiry_era_boundary():
    assert ec.is_thursday_expiry_era(date(2023, 10, 2)) is True
    assert ec.is_thursday_expiry_era(date(2024, 4, 4)) is True      # no Monday era: still Thursday
    assert ec.is_thursday_expiry_era(THURSDAY_ERA_END) is True
    assert ec.is_thursday_expiry_era(TUESDAY_CUTOVER) is False


# ── Flag off: legacy behaviour pinned ──────────────────────────────────────

def test_flag_off_monday_signal_fill_tuesday_is_dropped_at_two_dte():
    eng = _engine(era_aware=False)
    _signal(eng, date(2023, 10, 2))                # Monday -> Thu 2023-10-05 at 3 DTE
    assert eng._pending_weekly_entry is not None
    assert eng._pending_weekly_entry["expiry"] == date(2023, 10, 5)
    _fill(eng, date(2023, 10, 3))                  # Tuesday fill -> 2 DTE, outside [3, 8]
    assert eng.weekly_entries == 0
    assert eng.weekly_fill_dte_drops == 1
    assert eng.weekly_era_signal_entries == 0


@pytest.mark.parametrize("signal_date", [date(2023, 10, 5), date(2023, 10, 6)])  # Thu, Fri
def test_flag_off_thursday_and_friday_do_not_signal(signal_date):
    eng = _engine(era_aware=False)
    _signal(eng, signal_date)
    assert eng._pending_weekly_entry is None


# ── Flag on: Thursday-era entries land inside the window ───────────────────

def test_flag_on_thursday_signal_fills_friday_at_six_dte():
    eng = _engine(era_aware=True)
    _signal(eng, date(2023, 10, 5))                # Thursday -> next Thu 2023-10-12 at 7 DTE
    assert eng._pending_weekly_entry["expiry"] == date(2023, 10, 12)
    _fill(eng, date(2023, 10, 6))                  # Friday fill -> 6 DTE
    assert eng.weekly_entries == 1
    assert eng.weekly_fill_dte_drops == 0
    assert eng.weekly_era_signal_entries == 1


@pytest.mark.parametrize("signal_date", [date(2023, 10, 2), date(2023, 10, 3), date(2023, 10, 6)])
def test_flag_on_non_thursday_signal_days_do_not_signal_in_thursday_era(signal_date):
    eng = _engine(era_aware=True)
    _signal(eng, signal_date)
    assert eng._pending_weekly_entry is None
    assert eng.weekly_era_signal_entries == 0


def test_flag_on_sweep_every_thursday_era_week_fills_inside_window():
    eng = _engine(era_aware=True)
    thursdays = list(_thursdays(date(2012, 1, 1), date(2024, 3, 28)))
    assert len(thursdays) > 600
    # Only the 2023-09..2024-04 synthetic frame has rows; widen the frame for the sweep.
    idx = pd.bdate_range("2012-01-01", "2024-12-31")
    eng.data = pd.DataFrame({c: [22000.0] * len(idx) for c in
                             ("nifty_close", "nifty_high", "nifty_low", "nifty_open",
                              "nifty_mid_session", "vix")}, index=idx)
    for thu in thursdays:
        _signal(eng, thu)
        assert eng._pending_weekly_entry is not None, thu
        fill = _next_trading_day(thu)
        _fill(eng, fill)
        assert eng._pending_weekly_entry is None
        eng.weekly_trade = None    # previous week's trade closes before the next signal
    assert eng.weekly_entries == len(thursdays)
    assert eng.weekly_fill_dte_drops == 0
    assert eng.weekly_era_signal_entries == len(thursdays)


# ── Cutover boundary ───────────────────────────────────────────────────────

def test_thursday_era_week_across_cutover_with_flag_on_is_thursday_only():
    eng = _engine(era_aware=True)
    _signal(eng, date(2024, 3, 28))                # Thu: expiry 2024-04-04, 7 DTE
    _fill(eng, date(2024, 3, 29))                  # Fri fill -> 6 DTE
    assert eng.weekly_entries == 1
    # Monday 2024-04-01 is in the Thursday era: no Monday signal under the flag (no drop either).
    _signal(eng, date(2024, 4, 1))
    assert eng._pending_weekly_entry is None
    assert eng.weekly_fill_dte_drops == 0


def test_last_thursday_era_signal_targets_first_tuesday_expiry():
    eng = _engine(era_aware=True)
    _signal(eng, THURSDAY_ERA_END)                 # Thu 2025-08-28 (expiry day) -> Tue 2025-09-02, 5 DTE
    assert eng._pending_weekly_entry["expiry"] == date(2025, 9, 2)
    _fill(eng, date(2025, 8, 29))                  # Fri fill -> 4 DTE, inside window
    assert eng.weekly_entries == 1
    assert eng.weekly_fill_dte_drops == 0


def test_tuesday_era_pending_entries_identical_flag_on_and_off():
    off, on = _engine(era_aware=False), _engine(era_aware=True)
    compared = 0
    d = TUESDAY_CUTOVER
    while d <= date(2026, 3, 31):
        for eng in (off, on):
            eng._pending_weekly_entry = None
            _signal(eng, d)
        p_off, p_on = off._pending_weekly_entry, on._pending_weekly_entry
        if p_off is None or p_on is None:
            assert p_off is None and p_on is None, d
        else:
            for key in ("signal_date", "signal_spot", "signal_vix", "expiry", "lots"):
                assert p_off[key] == p_on[key], (d, key)
            compared += 1
        d += timedelta(days=1)
    assert compared > 30           # Tuesday-era cadence present
    assert on.weekly_era_signal_entries == 0


def test_tuesday_era_monday_signal_still_fills_tuesday_at_seven_dte_with_flag_on():
    eng = _engine(era_aware=True)
    _signal(eng, date(2025, 9, 8))                 # Mon -> Tue 09-09 (1 DTE, skipped) -> Tue 09-16, 8 DTE
    assert eng._pending_weekly_entry["expiry"] == date(2025, 9, 16)
    _fill(eng, date(2025, 9, 9))                   # Tue fill -> 7 DTE
    assert eng.weekly_entries == 1
    assert eng.weekly_fill_dte_drops == 0
    assert eng.weekly_era_signal_entries == 0


# ── Holiday cases (synthetic holiday list, historical file has none pre-2024) ──

@pytest.fixture
def holidays(monkeypatch):
    def _set(dates):
        cache = {d: {"date": d.isoformat(), "segment_closed": True} for d in dates}
        monkeypatch.setattr(ec, "_holiday_cache", cache)
    return _set


def test_holiday_on_expiry_thursday_shifts_expiry_to_wednesday_and_still_in_window(holidays):
    holidays([date(2023, 10, 12)])                 # next Thursday expiry closed
    eng = _engine(era_aware=True)
    _signal(eng, date(2023, 10, 5))
    assert eng._pending_weekly_entry["expiry"] == date(2023, 10, 11)   # shifted to Wed
    _fill(eng, date(2023, 10, 6))                  # Friday fill -> 5 DTE, inside window
    assert eng.weekly_entries == 1
    assert eng.weekly_fill_dte_drops == 0


def test_holiday_on_fill_friday_moves_fill_to_monday_still_in_window(holidays):
    holidays([date(2023, 10, 6)])                  # Friday closed; fill rolls to Monday
    eng = _engine(era_aware=True)
    _signal(eng, date(2023, 10, 5))
    _fill(eng, date(2023, 10, 9))                  # Monday fill -> 3 DTE, inside window
    assert eng.weekly_entries == 1
    assert eng.weekly_fill_dte_drops == 0


def test_holiday_on_signal_thursday_has_no_row_so_no_signal_and_no_drop(holidays):
    holidays([date(2023, 10, 5)])                  # Thursday closed: no data row, no signal
    eng = _engine(era_aware=True)
    assert ec.is_trading_day(date(2023, 10, 5)) is False
    assert eng._pending_weekly_entry is None
    assert eng.weekly_entries == 0
    assert eng.weekly_fill_dte_drops == 0
