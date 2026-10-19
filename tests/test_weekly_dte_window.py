"""
Tests for the weekly fill-time DTE window (WeeklyBacktestConfig.dte_check_at_signal).

Fill-time DTE drops are counted in weekly_fill_dte_drops and mirrored into the
legacy weekly_etl_skips total. The real ETL-gate skips are counted separately in
weekly_etl_gate_skips. With dte_check_at_signal=True the window re-check is skipped
and only an expiry already past on the fill date is dropped (weekly_expiry_past_drops).
"""

import logging
from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from config import BacktestConfig, WeeklyBacktestConfig
from backtester.combined_engine import CombinedBacktestEngine


SIGNAL_DATE = date(2026, 10, 19)   # Monday
FILL_DATE = date(2026, 10, 22)     # Thursday; expiry 2026-10-24 gives fill DTE = 2


def _make_engine(dte_check_at_signal: bool) -> CombinedBacktestEngine:
    dates = pd.bdate_range("2026-10-01", periods=10)
    df = pd.DataFrame({
        "nifty_close": [22000.0] * 10, "nifty_high": [22100.0] * 10,
        "nifty_low": [21900.0] * 10, "nifty_open": [22000.0] * 10,
        "nifty_mid_session": [22000.0] * 10,
        "vix": [16.0] * 10,
    }, index=dates)
    wcfg = WeeklyBacktestConfig(dte_check_at_signal=dte_check_at_signal)
    return CombinedBacktestEngine(
        data=df,
        monthly_config=BacktestConfig(initial_capital=500_000, lot_size=65, max_lots=15),
        weekly_config=wcfg,
        monthly_strategy=MagicMock(name="s"),
        exit_engine=None,
        entry_model=None,
        weekly_risk_engine=None,
    )


def _set_pending(engine, expiry):
    engine._pending_weekly_entry = {
        "signal_date": SIGNAL_DATE,
        "signal_spot": 22000.0,
        "signal_vix": 16.0,
        "expiry": expiry,
        "strategy": MagicMock(name="weekly_strategy"),
        "lots": 1,
    }


def _fill(engine, fill_date):
    row = pd.Series({"nifty_mid_session": 22000.0, "nifty_open": 22000.0, "nifty_close": 22000.0})
    with patch("backtester.combined_engine.build_tracker", MagicMock()), \
            patch.object(engine.weekly_fill_model, "apply_entry_fill", MagicMock()):
        engine._fill_pending_weekly_entry(fill_date, row)


def test_default_config_flag_is_false():
    assert WeeklyBacktestConfig().dte_check_at_signal is False


def test_default_drops_monday_signal_when_fill_dte_is_two():
    engine = _make_engine(dte_check_at_signal=False)
    _set_pending(engine, expiry=date(2026, 10, 24))  # fill DTE = 2, outside [3, 8]
    _fill(engine, FILL_DATE)

    assert engine.weekly_entries == 0
    assert engine.weekly_trade is None
    assert engine._pending_weekly_entry is None
    assert engine.weekly_fill_dte_drops == 1
    assert engine.weekly_etl_gate_skips == 0
    assert engine.weekly_expiry_past_drops == 0


def test_flag_true_keeps_fill_dte_two_and_counts_no_drop():
    engine = _make_engine(dte_check_at_signal=True)
    _set_pending(engine, expiry=date(2026, 10, 24))
    _fill(engine, FILL_DATE)

    assert engine.weekly_entries == 1
    assert engine.weekly_trade is not None
    assert engine.weekly_fill_dte_drops == 0
    assert engine.weekly_etl_skips == 0
    assert engine.weekly_expiry_past_drops == 0


def test_legacy_alias_tracks_fill_drops_and_etl_gate_separately():
    engine = _make_engine(dte_check_at_signal=False)
    _set_pending(engine, expiry=date(2026, 10, 24))
    _fill(engine, FILL_DATE)
    assert engine.weekly_etl_skips == engine.weekly_fill_dte_drops == 1

    # Simulate an ETL-gate skip from the run loop: it feeds the legacy total and its own counter.
    engine.weekly_etl_gate_skips += 1
    engine.weekly_etl_skips += 1
    assert engine.weekly_etl_skips == engine.weekly_fill_dte_drops + engine.weekly_etl_gate_skips
    assert engine.weekly_etl_gate_skips == 1


def test_flag_true_drops_expiry_already_passed_with_warning(caplog):
    engine = _make_engine(dte_check_at_signal=True)
    _set_pending(engine, expiry=date(2026, 10, 21))  # expiry before fill date
    with caplog.at_level(logging.WARNING, logger="backtester.combined_engine"):
        _fill(engine, FILL_DATE)

    assert engine.weekly_entries == 0
    assert engine.weekly_trade is None
    assert engine._pending_weekly_entry is None
    assert engine.weekly_expiry_past_drops == 1
    assert engine.weekly_fill_dte_drops == 0
    assert engine.weekly_etl_skips == 0
    assert any("already passed" in r.getMessage() for r in caplog.records)


def test_flag_true_expiry_on_fill_date_is_not_dropped():
    engine = _make_engine(dte_check_at_signal=True)
    _set_pending(engine, expiry=FILL_DATE)  # expiry == fill date: DTE 0, not "passed"
    _fill(engine, FILL_DATE)

    assert engine.weekly_entries == 1
    assert engine.weekly_expiry_past_drops == 0
