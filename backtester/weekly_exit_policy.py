"""
Shared exit policy for weekly strategies.

The policy is deliberately runtime-safe:
- uses only entry-time values
- uses only state observed up to the current bar
- does not inspect future prices or greeks
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from config import WeeklyBacktestConfig
from strategies.base import ExitReason, Trade


@dataclass
class WeeklyExitTracker:
    peak_pnl_per_unit: float = 0.0
    entry_abs_delta: float = 0.0
    best_abs_delta: float = 0.0
    high_spot: float = 0.0
    low_spot: float = 0.0


def build_tracker(trade: Trade) -> WeeklyExitTracker:
    abs_delta = abs(trade.portfolio_delta)
    return WeeklyExitTracker(
        peak_pnl_per_unit=max(0.0, trade.pnl_per_unit),
        entry_abs_delta=abs_delta,
        best_abs_delta=abs_delta,
        high_spot=trade.entry_spot,
        low_spot=trade.entry_spot,
    )


def update_tracker(tracker: WeeklyExitTracker, trade: Trade, spot: float) -> None:
    tracker.peak_pnl_per_unit = max(tracker.peak_pnl_per_unit, trade.pnl_per_unit)
    tracker.best_abs_delta = min(tracker.best_abs_delta, abs(trade.portfolio_delta))
    tracker.high_spot = max(tracker.high_spot, spot)
    tracker.low_spot = min(tracker.low_spot, spot)


def check_weekly_exit(
    *,
    config: WeeklyBacktestConfig,
    trade: Trade,
    tracker: WeeklyExitTracker,
    spot: float,
    vix: float,
    dte: int,
    entry_vix: float,
    current_equity: float,
    holding_days: int,
) -> tuple[bool, Optional[ExitReason]]:
    if config.weekly_exit_policy == "legacy":
        return _legacy_exit_check(
            config=config,
            trade=trade,
            tracker=tracker,
            spot=spot,
            vix=vix,
            dte=dte,
            entry_vix=entry_vix,
            current_equity=current_equity,
        )
    return _redesigned_exit_check(
        config=config,
        trade=trade,
        tracker=tracker,
        spot=spot,
        vix=vix,
        dte=dte,
        entry_vix=entry_vix,
        current_equity=current_equity,
        holding_days=holding_days,
    )


def _legacy_exit_check(
    *,
    config: WeeklyBacktestConfig,
    trade: Trade,
    tracker: WeeklyExitTracker,
    spot: float,
    vix: float,
    dte: int,
    entry_vix: float,
    current_equity: float,
) -> tuple[bool, Optional[ExitReason]]:
    max_loss_abs = current_equity * config.capital_protection_pct
    if trade.total_pnl < -max_loss_abs:
        return True, ExitReason.STOP_LOSS

    net_credit = trade.net_credit
    if net_credit <= 0:
        return False, None

    pnl_pct = trade.pnl_per_unit / net_credit * 100

    if dte <= config.expiry_exit_dte:
        return True, ExitReason.DTE_LIMIT

    for short_leg in (leg for leg in trade.legs if leg.is_short):
        if short_leg.option_type in ("PUT", "PE") and spot < short_leg.strike:
            return True, ExitReason.STOP_LOSS
        if short_leg.option_type in ("CALL", "CE") and spot > short_leg.strike:
            return True, ExitReason.STOP_LOSS

    vix_change = (vix - entry_vix) / entry_vix if entry_vix > 0 else 0
    if vix_change > 0.20 and pnl_pct < -5:
        return True, ExitReason.STOP_LOSS

    if pnl_pct >= config.profit_target_pct:
        return True, ExitReason.PROFIT_TARGET

    if pnl_pct < -config.stop_loss_pct:
        return True, ExitReason.STOP_LOSS

    peak_pct = (tracker.peak_pnl_per_unit / net_credit * 100) if net_credit > 0 else 0
    drop_from_peak_pct = ((trade.pnl_per_unit - tracker.peak_pnl_per_unit) / net_credit * 100)
    if peak_pct >= config.trailing_peak_pct and drop_from_peak_pct < -config.trailing_drop_pct:
        return True, ExitReason.PROFIT_TARGET

    return False, None


def _redesigned_exit_check(
    *,
    config: WeeklyBacktestConfig,
    trade: Trade,
    tracker: WeeklyExitTracker,
    spot: float,
    vix: float,
    dte: int,
    entry_vix: float,
    current_equity: float,
    holding_days: int,
) -> tuple[bool, Optional[ExitReason]]:
    max_loss_abs = current_equity * config.capital_protection_pct
    if trade.total_pnl < -max_loss_abs:
        return True, ExitReason.STOP_LOSS

    net_credit = trade.net_credit
    if net_credit <= 0:
        return False, None

    pnl_pct = trade.pnl_per_unit / net_credit * 100

    if dte <= config.expiry_exit_dte:
        return True, ExitReason.DTE_LIMIT

    short_legs = [leg for leg in trade.legs if leg.is_short]
    for short_leg in short_legs:
        if short_leg.option_type in ("PUT", "PE") and spot < short_leg.strike:
            return True, ExitReason.STOP_LOSS
        if short_leg.option_type in ("CALL", "CE") and spot > short_leg.strike:
            return True, ExitReason.STOP_LOSS

    vix_change = (vix - entry_vix) / entry_vix if entry_vix > 0 else 0
    if vix_change > 0.20 and pnl_pct < -5:
        return True, ExitReason.STOP_LOSS

    if pnl_pct < -config.stop_loss_pct:
        return True, ExitReason.STOP_LOSS

    strategy_name = trade.strategy_name.lower()
    if "weekly_pcs" in strategy_name:
        if holding_days >= config.engine_a_min_hold_days and pnl_pct >= config.engine_a_profit_target_pct:
            return True, ExitReason.PROFIT_TARGET
        return False, None

    if "weekly_ic" in strategy_name:
        abs_delta = abs(trade.portfolio_delta)
        if (
            tracker.entry_abs_delta > 0
            and tracker.best_abs_delta <= tracker.entry_abs_delta * config.engine_b_delta_trail_arm_ratio
            and abs_delta >= tracker.best_abs_delta * config.engine_b_delta_trail_rebound_ratio
        ):
            return True, ExitReason.TRAILING_DELTA

        if (
            tracker.high_spot >= trade.entry_spot * (1 + config.engine_b_trend_trigger_pct)
            and spot <= tracker.high_spot * (1 - config.engine_b_trend_reversal_pct)
        ):
            return True, ExitReason.TREND_REVERSAL

        if (
            tracker.low_spot <= trade.entry_spot * (1 - config.engine_b_trend_trigger_pct)
            and spot >= tracker.low_spot * (1 + config.engine_b_trend_reversal_pct)
        ):
            return True, ExitReason.TREND_REVERSAL

        if holding_days >= config.engine_b_max_hold_days:
            return True, ExitReason.MAX_HOLD_TIME

        return False, None

    return False, None
