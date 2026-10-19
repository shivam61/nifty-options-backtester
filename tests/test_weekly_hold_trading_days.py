"""
Weekly hold-time limits are TRADING sessions, not calendar days.

config.engine_a_min_hold_days (PCS) and config.engine_b_max_hold_days (IC) are
trading-day limits. Callers used to pass calendar days, so a weekend counted as two
days of hold. trading_sessions_held() counts sessions from the engine's own index.

Example: Tuesday entry -> Monday of the following week is 4 trading sessions
(Wed, Thu, Fri, Mon), so an IC with engine_b_max_hold_days=4 exits on that Monday
(6 calendar days, but only 4 sessions).
"""

from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd

from config import BacktestConfig, WeeklyBacktestConfig
from backtester.combined_engine import CombinedBacktestEngine
from backtester.weekly_exit_policy import build_tracker, check_weekly_exit, trading_sessions_held
from strategies.base import ExitReason, Leg, Trade, TradeAction


# ── helper ────────────────────────────────────────────────────────────────

def test_helper_weekend_gap_counts_sessions_not_calendar_days():
    index = pd.bdate_range("2026-10-05", periods=10)  # Mon 5 Oct onward, weekdays only
    # Tuesday 6 Oct -> Monday 12 Oct: Wed, Thu, Fri, Mon = 4 sessions (6 calendar days)
    assert trading_sessions_held(index, date(2026, 10, 6), date(2026, 10, 12)) == 4


def test_helper_friday_entry_to_monday_is_one_session():
    index = pd.bdate_range("2026-10-05", periods=10)
    # Fri 9 Oct -> Mon 12 Oct: one session (3 calendar days)
    assert trading_sessions_held(index, date(2026, 10, 9), date(2026, 10, 12)) == 1


def test_helper_holiday_gap_is_not_counted():
    # Thursday 8 Oct is a market holiday, so it is absent from the session index.
    index = pd.bdate_range("2026-10-05", periods=10).drop(pd.Timestamp("2026-10-08"))
    # Tue 6 Oct -> Mon 12 Oct: Wed 7, Fri 9, Mon 12 = 3 sessions
    assert trading_sessions_held(index, date(2026, 10, 6), date(2026, 10, 12)) == 3


def test_helper_same_day_and_backwards_are_zero():
    index = pd.bdate_range("2026-10-05", periods=10)
    assert trading_sessions_held(index, date(2026, 10, 6), date(2026, 10, 6)) == 0
    assert trading_sessions_held(index, date(2026, 10, 6), date(2026, 10, 5)) == 0


def test_helper_weekday_only_window_matches_calendar_days():
    index = pd.bdate_range("2026-10-05", periods=10)
    # Mon 5 -> Thu 8 Oct: no weekend, so sessions == calendar days
    assert trading_sessions_held(index, date(2026, 10, 5), date(2026, 10, 8)) == 3


def test_helper_accepts_tz_aware_index():
    index = pd.bdate_range("2026-10-05", periods=10, tz="Asia/Kolkata")
    assert trading_sessions_held(index, date(2026, 10, 6), date(2026, 10, 12)) == 4


# ── exit policy ───────────────────────────────────────────────────────────

def _ic_trade(entry_date=date(2026, 10, 8)) -> Trade:
    """Thursday IC with credit 105 and current premiums 38 -> profitable, no stop."""
    return Trade(
        strategy_name="weekly_ic",
        entry_date=entry_date,
        legs=[
            Leg("CE", 22500, True, 80.0, 30.0, 1, 50, delta=-0.22),
            Leg("CE", 22800, False, 25.0, 8.0, 1, 50, delta=0.09),
            Leg("PE", 21500, True, 70.0, 22.0, 1, 50, delta=0.20),
            Leg("PE", 21200, False, 20.0, 6.0, 1, 50, delta=-0.08),
        ],
        entry_spot=22000.0,
        entry_vix=16.0,
        lots=1,
        lot_size=50,
    )


def test_ic_max_hold_exits_at_fourth_trading_session():
    index = pd.bdate_range("2026-10-05", periods=12)
    entry = date(2026, 10, 8)  # Thursday
    config = WeeklyBacktestConfig(weekly_exit_policy="redesigned", engine_b_max_hold_days=4)
    trade = _ic_trade(entry)
    tracker = build_tracker(trade)

    def exit_on(day):
        held = trading_sessions_held(index, entry, day)
        return check_weekly_exit(
            config=config, trade=trade, tracker=tracker, spot=22000.0, vix=16.0,
            dte=5, entry_vix=16.0, current_equity=500_000.0, holding_days=held,
        )

    # Mon 12 Oct is 4 calendar days after entry but only session 2: no exit.
    assert exit_on(date(2026, 10, 12)) == (False, None)
    # Tue 13 Oct: session 3.
    assert exit_on(date(2026, 10, 13)) == (False, None)
    # Wed 14 Oct: session 4 -> MAX_HOLD_TIME.
    assert exit_on(date(2026, 10, 14)) == (True, ExitReason.MAX_HOLD_TIME)


def test_pcs_min_hold_counts_sessions_across_weekend():
    index = pd.bdate_range("2026-10-05", periods=12)
    config = WeeklyBacktestConfig(weekly_exit_policy="redesigned",
                                  engine_a_profit_target_pct=75.0, engine_a_min_hold_days=2)
    pcs = Trade(
        strategy_name="weekly_pcs",
        entry_date=date(2026, 10, 9),  # Friday
        legs=[
            Leg("PE", 21000, True, 100.0, 20.0, 1, 50, delta=-0.18),
            Leg("PE", 20600, False, 20.0, 0.0, 1, 50, delta=-0.05),
        ],
        entry_spot=22000.0, entry_vix=16.0, lots=1, lot_size=50,
    )
    tracker = build_tracker(pcs)

    def exit_on(day):
        held = trading_sessions_held(index, pcs.entry_date, day)
        return check_weekly_exit(
            config=config, trade=pcs, tracker=tracker, spot=22050.0, vix=15.0,
            dte=3, entry_vix=16.0, current_equity=500_000.0, holding_days=held,
        )

    # Mon 12 Oct: calendar 3 days but only 1 session -> min hold (2) not met.
    assert exit_on(date(2026, 10, 12)) == (False, None)
    # Tue 13 Oct: 2 sessions -> profit target eligible.
    assert exit_on(date(2026, 10, 13)) == (True, ExitReason.PROFIT_TARGET)


def test_pcs_min_hold_unchanged_on_weekend_free_window():
    index = pd.bdate_range("2026-10-05", periods=12)
    # Mon 5 -> Wed 7 Oct: no weekend, sessions == calendar days, so 2 either way.
    assert trading_sessions_held(index, date(2026, 10, 5), date(2026, 10, 7)) == (date(2026, 10, 7) - date(2026, 10, 5)).days


# ── engine level ──────────────────────────────────────────────────────────

def _make_engine() -> CombinedBacktestEngine:
    dates = pd.bdate_range("2026-10-05", periods=12)
    df = pd.DataFrame({
        "nifty_close": [22000.0] * 12, "nifty_high": [22100.0] * 12,
        "nifty_low": [21900.0] * 12, "nifty_open": [22000.0] * 12,
        "nifty_mid_session": [22000.0] * 12,
        "vix": [16.0] * 12,
    }, index=dates)
    return CombinedBacktestEngine(
        data=df,
        monthly_config=BacktestConfig(initial_capital=500_000, lot_size=65, max_lots=15),
        weekly_config=WeeklyBacktestConfig(weekly_exit_policy="redesigned", engine_b_max_hold_days=4),
        monthly_strategy=MagicMock(name="s"),
        exit_engine=None,
        entry_model=None,
        weekly_risk_engine=None,
    )


def test_engine_ic_max_hold_uses_trading_sessions():
    engine = _make_engine()
    trade = _ic_trade(entry_date=date(2026, 10, 8))  # Thursday entry
    engine.weekly_trade = trade
    engine._w_expiry = date(2026, 10, 16)
    engine._w_entry_vix = 16.0
    engine._w_exit_tracker = None
    engine._combined_equity = 500_000.0
    strategy = MagicMock(name="ic")
    strategy.should_exit.return_value = (TradeAction.HOLD, None)

    closed_on = None
    with patch.object(engine, "_weekly_strategy_for_trade", return_value=strategy):
        for idx, row in engine.data.iterrows():
            day = idx.date()
            if day <= date(2026, 10, 8):
                continue
            engine._process_weekly_exit(row, day, 22000.0, 16.0, row.to_dict())
            if engine.weekly_trade is None:
                closed_on = day
                break

    # Sessions after Thu 8 Oct: Fri 9 (1), Mon 12 (2), Tue 13 (3), Wed 14 (4).
    assert closed_on == date(2026, 10, 14)
    assert engine.weekly_completed[-1]["exit_reason"] == ExitReason.MAX_HOLD_TIME.value
