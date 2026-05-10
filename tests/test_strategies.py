"""
Tests for strategies/multi_strategy.py

Covers:
- Each sub-strategy's entry/exit logic
- Leg generation produces valid spreads
- RegimeAdaptiveStrategy selects correct strategy per VIX zone
- Circuit breaker blocks during extreme conditions
- force_strategy_selection mechanism
"""

import pytest
from datetime import date

from strategies.base import TradeAction, ExitReason, Leg, Trade
from strategies.multi_strategy import (
    PutCreditSpreadStrategy,
    BrokenWingButterflyStrategy,
    CalendarSpreadStrategy,
    RatioPutSpreadStrategy,
    RegimeAdaptiveStrategy,
)
from strategies.universe import ACTIVE_MONTHLY_STRATEGY_SET


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _calm_market(vix=16.0, nifty_return_5d=0.005, nifty_return_20d=0.02):
    """Market data dict representing a calm, range-bound market."""
    return {
        "vix": vix,
        "nifty_return_5d": nifty_return_5d,
        "nifty_return_20d": nifty_return_20d,
        "nifty_daily_range_pct": 1.2,
        "vix_change_5d": -0.02,
        "nifty_distance_from_sma20_pct": 0.5,
        "nifty_distance_from_sma50_pct": 1.0,
        "crash_risk_score": 0.0,
        "crash_risk_score_v2": 0.05,
        "nifty_drawdown_from_20d_high_pct": -0.5,
        "nifty_drawdown_from_50d_high_pct": -1.0,
        "crude_spike_10d_pct": 2.0,
        "vix_accel_3d_pct": 3.0,
        "multi_asset_stress": 0.1,
        "vol_expansion_ratio": 1.0,
        "nifty_rsi_14": 55,
        "nifty_consec_down_days": 0,
    }


def _crash_market():
    """Market data dict representing a crash / extreme stress scenario."""
    return {
        "vix": 35.0,
        "nifty_return_5d": -0.08,
        "nifty_return_20d": -0.12,
        "nifty_daily_range_pct": 4.5,
        "vix_change_5d": 0.40,
        "nifty_distance_from_sma20_pct": -6.0,
        "nifty_distance_from_sma50_pct": -8.0,
        "crash_risk_score": 0.9,
        "crash_risk_score_v2": 0.85,
        "nifty_drawdown_from_20d_high_pct": -12.0,
        "nifty_drawdown_from_50d_high_pct": -18.0,
        "crude_spike_10d_pct": 25.0,
        "vix_accel_3d_pct": 55.0,
        "multi_asset_stress": 0.85,
        "vol_expansion_ratio": 2.0,
        "nifty_rsi_14": 22,
        "nifty_consec_down_days": 6,
    }


# ---------------------------------------------------------------------------
# PutCreditSpreadStrategy
# ---------------------------------------------------------------------------

class TestPutCreditSpread:

    def test_enters_in_calm_market(self):
        s = PutCreditSpreadStrategy(lots=2, min_vix=13)
        action = s.should_enter(22000, 16.0, _calm_market())
        assert action == TradeAction.ENTER

    def test_skips_when_vix_too_low(self):
        s = PutCreditSpreadStrategy(lots=2, min_vix=15)
        action = s.should_enter(22000, 12.0, _calm_market(vix=12))
        assert action == TradeAction.NO_TRADE

    def test_skips_during_strong_downtrend(self):
        s = PutCreditSpreadStrategy(lots=2, min_vix=13)
        action = s.should_enter(22000, 16.0, _calm_market(nifty_return_20d=-0.06))
        assert action == TradeAction.NO_TRADE

    def test_legs_are_two_puts(self):
        s = PutCreditSpreadStrategy(lots=2, spread_width=500)
        legs = s.generate_legs(22000, 16.0, 21)
        assert len(legs) == 2
        assert all(l.option_type == "PE" for l in legs)

    def test_short_put_strike_below_spot(self):
        s = PutCreditSpreadStrategy(lots=2, put_sd=1.0, spread_width=500)
        legs = s.generate_legs(22000, 16.0, 21)
        short_leg = next(l for l in legs if l.is_short)
        assert short_leg.strike < 22000

    def test_long_put_below_short_put(self):
        """Long put must always be below the short put regardless of dynamic_width."""
        s = PutCreditSpreadStrategy(lots=2, spread_width=500)
        legs = s.generate_legs(22000, 16.0, 21)
        short = next(l for l in legs if l.is_short)
        long = next(l for l in legs if not l.is_short)
        assert long.strike < short.strike

    def test_fixed_spread_width_honored(self):
        """When spread_width != 500 the strategy skips dynamic_width and uses the fixed value."""
        s = PutCreditSpreadStrategy(lots=2, spread_width=600)
        legs = s.generate_legs(22000, 16.0, 21)
        short = next(l for l in legs if l.is_short)
        long = next(l for l in legs if not l.is_short)
        assert short.strike - long.strike == 600

    def test_exit_on_profit_target(self):
        s = PutCreditSpreadStrategy(lots=2, profit_target_pct=50)
        trade = Trade(
            strategy_name="put_credit_spread",
            entry_date=date(2024, 6, 1),
            legs=[
                Leg("PE", 21000, True, 100.0, 40.0, 2, 65),
                Leg("PE", 20500, False, 25.0, 5.0, 2, 65),
            ],
            entry_spot=22000, entry_vix=16,
        )
        action, reason = s.should_exit(trade, 22200, 14, 10)
        assert action == TradeAction.EXIT
        assert reason == ExitReason.PROFIT_TARGET

    def test_exit_near_expiry(self):
        s = PutCreditSpreadStrategy(lots=2)
        trade = Trade(
            strategy_name="put_credit_spread",
            entry_date=date(2024, 6, 1),
            legs=[Leg("PE", 21000, True, 100.0, 80.0, 2, 65),
                  Leg("PE", 20500, False, 25.0, 20.0, 2, 65)],
            entry_spot=22000, entry_vix=16,
        )
        action, reason = s.should_exit(trade, 22000, 15, 2)
        assert action == TradeAction.EXIT
        assert reason == ExitReason.DTE_LIMIT


# ---------------------------------------------------------------------------
# BrokenWingButterfly
# ---------------------------------------------------------------------------

class TestBrokenWingButterfly:

    def test_enters_in_high_vix(self):
        """BWB accepts VIX between min_vix (18) and 20 — vix > 20 is blocked by should_enter."""
        s = BrokenWingButterflyStrategy(lots=2, min_vix=18)
        action = s.should_enter(22000, 19.0, _calm_market(vix=19))
        assert action == TradeAction.ENTER

    def test_skips_above_max_vix(self):
        """BWB blocks entry above max_vix (default 30)."""
        s = BrokenWingButterflyStrategy(lots=2, min_vix=18, max_vix=30)
        action = s.should_enter(22000, 32.0, _calm_market(vix=32))
        assert action == TradeAction.NO_TRADE

    def test_enters_in_high_vix_22_30_range(self):
        """BWB enters in the 22–30 VIX zone that the router routes to it."""
        s = BrokenWingButterflyStrategy(lots=2, min_vix=18, max_vix=30)
        action = s.should_enter(22000, 25.0, _calm_market(vix=25))
        assert action == TradeAction.ENTER

    def test_skips_in_low_vix(self):
        s = BrokenWingButterflyStrategy(lots=2, min_vix=18)
        action = s.should_enter(22000, 14.0, _calm_market(vix=14))
        assert action == TradeAction.NO_TRADE

    def test_has_three_legs(self):
        s = BrokenWingButterflyStrategy(lots=2)
        legs = s.generate_legs(22000, 22.0, 21)
        assert len(legs) == 3
        short_legs = [l for l in legs if l.is_short]
        long_legs = [l for l in legs if not l.is_short]
        assert len(short_legs) == 1
        assert len(long_legs) == 2

    def test_center_is_short_with_double_quantity(self):
        s = BrokenWingButterflyStrategy(lots=2)
        legs = s.generate_legs(22000, 22.0, 21)
        short_leg = next(l for l in legs if l.is_short)
        long_legs = [l for l in legs if not l.is_short]
        assert short_leg.lots == 4  # 2 lots × 2
        assert all(l.lots == 2 for l in long_legs)


# ---------------------------------------------------------------------------
# CalendarSpreadStrategy
# ---------------------------------------------------------------------------

class TestCalendarSpread:

    def test_enters_in_low_vix(self):
        s = CalendarSpreadStrategy(lots=2)
        data = _calm_market(vix=12)
        data["nifty_return_5d"] = 0.005
        action = s.should_enter(22000, 12.0, data)
        assert action == TradeAction.ENTER

    def test_skips_in_high_vix(self):
        s = CalendarSpreadStrategy(lots=2)
        action = s.should_enter(22000, 22.0, _calm_market(vix=22))
        assert action == TradeAction.NO_TRADE

    def test_legs_have_same_strike(self):
        s = CalendarSpreadStrategy(lots=2)
        legs = s.generate_legs(22000, 12.0, 21)
        assert len(legs) == 2
        assert legs[0].strike == legs[1].strike


# ---------------------------------------------------------------------------
# RegimeAdaptiveStrategy — strategy selection
# ---------------------------------------------------------------------------

class TestRegimeAdaptiveStrategy:

    def test_monthly_universe_is_frozen(self):
        s = RegimeAdaptiveStrategy(lots=2)
        assert set(s._strategies.keys()) == ACTIVE_MONTHLY_STRATEGY_SET
        eligible = s.get_eligible_strategies(22000, 16.0, _calm_market(vix=16))
        assert set(eligible) <= ACTIVE_MONTHLY_STRATEGY_SET

    def test_selects_calendar_in_very_low_vix(self):
        s = RegimeAdaptiveStrategy(lots=2)
        eligible = s.get_eligible_strategies(22000, 10.0, _calm_market(vix=10))
        assert "calendar_spread" in eligible

    def test_selects_put_credit_in_sweet_spot(self):
        s = RegimeAdaptiveStrategy(lots=2)
        eligible = s.get_eligible_strategies(22000, 16.0, _calm_market(vix=16))
        assert "put_credit_spread" in eligible

    def test_selects_put_credit_and_bwb_in_extreme_vix(self):
        """At VIX >= 30 the eligible set is put_credit_spread and broken_wing_butterfly."""
        s = RegimeAdaptiveStrategy(lots=2)
        data = _calm_market(vix=32)
        data["crash_risk_score_v2"] = 0.2
        data["multi_asset_stress"] = 0.2
        data["nifty_drawdown_from_50d_high_pct"] = -3.0
        data["vix_accel_3d_pct"] = 10
        data["crude_spike_10d_pct"] = 5
        eligible = s.get_eligible_strategies(22000, 32.0, data)
        assert "put_credit_spread" in eligible
        assert "broken_wing_butterfly" in eligible

    def test_high_vol_includes_alternatives_to_plain_pcs(self):
        s = RegimeAdaptiveStrategy(lots=2)
        data = _calm_market(vix=24)
        data["vix_change_5d"] = 0.01
        eligible = s.get_eligible_strategies(22000, 24.0, data)
        assert "put_credit_wide" in eligible
        assert "iron_condor" in eligible

    def test_circuit_breaker_blocks_during_crash(self):
        s = RegimeAdaptiveStrategy(lots=2)
        eligible = s.get_eligible_strategies(20000, 35.0, _crash_market())
        assert eligible == []
        assert len(s._circuit_breaker_reasons) > 0

    def test_circuit_breaker_reasons_populated(self):
        s = RegimeAdaptiveStrategy(lots=2)
        s.get_eligible_strategies(20000, 35.0, _crash_market())
        reasons = s._circuit_breaker_reasons
        assert any("crash risk" in r.lower() or "stress" in r.lower() for r in reasons)

    def test_force_strategy_selection_activates(self):
        s = RegimeAdaptiveStrategy(lots=2)
        assert s.force_strategy_selection("put_credit_spread") is True
        assert s._active_name == "put_credit_spread"

    def test_force_strategy_selection_rejects_unknown(self):
        s = RegimeAdaptiveStrategy(lots=2)
        assert s.force_strategy_selection("nonexistent_strategy") is False

    def test_set_lots_propagates(self):
        s = RegimeAdaptiveStrategy(lots=2)
        s.set_lots(5)
        assert s.lots == 5
        for sub in s._strategies.values():
            assert sub.lots == 5

    def test_create_trade_uses_active_strategy_name(self):
        s = RegimeAdaptiveStrategy(lots=2)
        s.force_strategy_selection("put_credit_wide")
        trade = s.create_trade(date(2024, 6, 1), 22000, 14.0, 21, 0.065)
        assert "put_credit_wide" in trade.strategy_name

    def test_should_enter_returns_no_trade_when_circuit_breaker_active(self):
        s = RegimeAdaptiveStrategy(lots=2)
        action = s.should_enter(20000, 35.0, _crash_market())
        assert action == TradeAction.NO_TRADE
