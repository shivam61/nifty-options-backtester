from datetime import date

from config import WeeklyBacktestConfig
from backtester.weekly_exit_policy import WeeklyExitTracker, build_tracker, check_weekly_exit
from strategies.base import ExitReason, Leg, Trade


def _pcs_trade(current_short=40.0, current_long=5.0) -> Trade:
    return Trade(
        strategy_name="weekly_pcs",
        entry_date=date(2024, 6, 3),
        legs=[
            Leg("PE", 21000, True, 100.0, current_short, 1, 50, delta=-0.18),
            Leg("PE", 20600, False, 20.0, current_long, 1, 50, delta=-0.05),
        ],
        entry_spot=22000.0,
        entry_vix=16.0,
        lots=1,
        lot_size=50,
    )


def _ic_trade(
    current_sc=30.0,
    current_lc=8.0,
    current_sp=22.0,
    current_lp=6.0,
    deltas=(-0.22, 0.09, 0.20, -0.08),
) -> Trade:
    return Trade(
        strategy_name="weekly_ic",
        entry_date=date(2024, 6, 3),
        legs=[
            Leg("CE", 22500, True, 80.0, current_sc, 1, 50, delta=deltas[0]),
            Leg("CE", 22800, False, 25.0, current_lc, 1, 50, delta=deltas[1]),
            Leg("PE", 21500, True, 70.0, current_sp, 1, 50, delta=deltas[2]),
            Leg("PE", 21200, False, 20.0, current_lp, 1, 50, delta=deltas[3]),
        ],
        entry_spot=22000.0,
        entry_vix=16.0,
        lots=1,
        lot_size=50,
    )


def test_engine_a_profit_target_respects_min_hold_time():
    config = WeeklyBacktestConfig(weekly_exit_policy="redesigned", engine_a_profit_target_pct=75.0, engine_a_min_hold_days=2)
    trade = _pcs_trade(current_short=20.0, current_long=0.0)
    tracker = build_tracker(trade)

    should_exit, reason = check_weekly_exit(
        config=config,
        trade=trade,
        tracker=tracker,
        spot=22050.0,
        vix=15.0,
        dte=3,
        entry_vix=16.0,
        current_equity=500_000.0,
        holding_days=1,
    )
    assert (should_exit, reason) == (False, None)

    should_exit, reason = check_weekly_exit(
        config=config,
        trade=trade,
        tracker=tracker,
        spot=22050.0,
        vix=15.0,
        dte=3,
        entry_vix=16.0,
        current_equity=500_000.0,
        holding_days=2,
    )
    assert should_exit is True
    assert reason == ExitReason.PROFIT_TARGET


def test_engine_b_has_no_profit_target_exit():
    config = WeeklyBacktestConfig(weekly_exit_policy="redesigned")
    trade = _ic_trade(current_sc=10.0, current_lc=0.0, current_sp=5.0, current_lp=0.0)
    tracker = build_tracker(trade)

    should_exit, reason = check_weekly_exit(
        config=config,
        trade=trade,
        tracker=tracker,
        spot=22010.0,
        vix=15.0,
        dte=3,
        entry_vix=16.0,
        current_equity=500_000.0,
        holding_days=2,
    )
    assert (should_exit, reason) == (False, None)


def test_engine_b_trailing_delta_exit_uses_runtime_delta_state():
    config = WeeklyBacktestConfig(
        weekly_exit_policy="redesigned",
        engine_b_delta_trail_arm_ratio=0.80,
        engine_b_delta_trail_rebound_ratio=1.35,
    )
    trade = _ic_trade(deltas=(-0.45, 0.05, 0.05, -0.03))
    tracker = WeeklyExitTracker(
        peak_pnl_per_unit=80.0,
        entry_abs_delta=10.0,
        best_abs_delta=7.0,
        high_spot=22150.0,
        low_spot=21920.0,
    )

    should_exit, reason = check_weekly_exit(
        config=config,
        trade=trade,
        tracker=tracker,
        spot=22020.0,
        vix=15.5,
        dte=3,
        entry_vix=16.0,
        current_equity=500_000.0,
        holding_days=2,
    )
    assert should_exit is True
    assert reason == ExitReason.TRAILING_DELTA


def test_engine_b_trend_reversal_exit_uses_seen_price_extremes_only():
    config = WeeklyBacktestConfig(
        weekly_exit_policy="redesigned",
        engine_b_trend_trigger_pct=0.01,
        engine_b_trend_reversal_pct=0.005,
    )
    trade = _ic_trade()
    tracker = WeeklyExitTracker(
        peak_pnl_per_unit=60.0,
        entry_abs_delta=6.0,
        best_abs_delta=4.5,
        high_spot=22350.0,
        low_spot=22000.0,
    )

    should_exit, reason = check_weekly_exit(
        config=config,
        trade=trade,
        tracker=tracker,
        spot=22220.0,
        vix=15.0,
        dte=3,
        entry_vix=16.0,
        current_equity=500_000.0,
        holding_days=2,
    )
    assert should_exit is True
    assert reason == ExitReason.TREND_REVERSAL


def test_engine_b_max_hold_time_exit():
    config = WeeklyBacktestConfig(weekly_exit_policy="redesigned", engine_b_max_hold_days=4)
    trade = _ic_trade()
    tracker = build_tracker(trade)

    should_exit, reason = check_weekly_exit(
        config=config,
        trade=trade,
        tracker=tracker,
        spot=22000.0,
        vix=15.0,
        dte=2,
        entry_vix=16.0,
        current_equity=500_000.0,
        holding_days=4,
    )
    assert should_exit is True
    assert reason == ExitReason.MAX_HOLD_TIME
