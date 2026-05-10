"""
Tests for:
- strategies/expiry_selector.py (multi-expiry evaluation)
- CalendarSpread roll adjustment
- AdjustmentAction / Trade.apply_adjustment
"""

import pytest
from datetime import date

from strategies.base import Leg, Trade, TradeAction, ExitReason, AdjustmentAction
from strategies.multi_strategy import (
    CalendarSpreadStrategy,
    PutCreditSpreadStrategy,
    RegimeAdaptiveStrategy,
)
from strategies.expiry_selector import (
    ExpirySelector,
    ExpiryCandidate,
    _estimate_win_prob,
    _score_candidate,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _calm(vix=16.0, **kw):
    defaults = {
        "vix": vix,
        "nifty_return_5d": 0.005,
        "nifty_return_20d": 0.02,
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
    defaults.update(kw)
    return defaults


# ---------------------------------------------------------------------------
# CalendarSpread rolling
# ---------------------------------------------------------------------------

class TestCalendarSpreadRolling:

    def test_signals_roll_near_expiry(self):
        s = CalendarSpreadStrategy(lots=2, max_rolls=2)
        trade = Trade(
            strategy_name="calendar_spread",
            entry_date=date(2024, 6, 1),
            legs=[
                Leg("PE", 22000, True, 80.0, 10.0, 2, 65),
                Leg("PE", 22000, False, 200.0, 170.0, 2, 65),
            ],
            entry_spot=22000, entry_vix=14, roll_count=0,
        )
        action, reason = s.should_exit(trade, 22050, 13, 2)
        assert action == TradeAction.ADJUST
        assert reason == ExitReason.ROLL

    def test_roll_produces_new_short_leg(self):
        s = CalendarSpreadStrategy(lots=2, max_rolls=2)
        trade = Trade(
            strategy_name="calendar_spread",
            entry_date=date(2024, 6, 1),
            legs=[
                Leg("PE", 22000, True, 80.0, 5.0, 2, 65),
                Leg("PE", 22000, False, 200.0, 170.0, 2, 65),
            ],
            entry_spot=22000, entry_vix=14, roll_count=0,
        )
        adj = s.should_adjust(trade, 22050, 13, 2)
        assert adj is not None
        assert adj.action_type == "roll_short"

    def test_no_roll_when_vix_extreme(self):
        s = CalendarSpreadStrategy(lots=2, max_rolls=2)
        trade = Trade(
            strategy_name="calendar_spread",
            entry_date=date(2024, 6, 1),
            legs=[Leg("PE", 22000, True, 80.0, 5.0, 2, 65),
                  Leg("PE", 22000, False, 200.0, 170.0, 2, 65)],
            entry_spot=22000, entry_vix=14, roll_count=0,
        )
        adj = s.should_adjust(trade, 20000, 30, 2)
        assert adj is None


# ---------------------------------------------------------------------------
# AdjustmentAction + Trade.apply_adjustment
# ---------------------------------------------------------------------------

class TestAdjustmentMechanics:

    def test_apply_adjustment_replaces_leg(self):
        trade = Trade(
            strategy_name="test",
            entry_date=date(2024, 6, 1),
            legs=[
                Leg("PE", 21000, True, 100.0, 30.0, 2, 65),
                Leg("PE", 20000, False, 50.0, 40.0, 2, 65),
            ],
        )
        new_leg = Leg("PE", 21500, True, 110.0, 110.0, 2, 65)
        adj = AdjustmentAction(
            action_type="roll_short",
            legs_to_close=[0],
            new_legs=[new_leg],
            cost=5.0,
            reasoning="test roll",
        )
        trade.apply_adjustment(adj)
        assert trade.roll_count == 1
        assert len(trade.legs) == 2
        short_legs = [l for l in trade.legs if l.is_short]
        assert short_legs[0].strike == 21500
        assert len(trade.adjustment_history) == 1
        assert trade.adjustment_history[0]["type"] == "roll_short"

    def test_multiple_rolls_tracked(self):
        trade = Trade(strategy_name="test", entry_date=date(2024, 6, 1),
                      legs=[Leg("PE", 21000, True, 100, 30, 2, 65)])
        for i in range(3):
            adj = AdjustmentAction("roll_short", [0],
                                   [Leg("PE", 21000 + (i+1)*100, True, 90, 90, 2, 65)])
            trade.apply_adjustment(adj)
        assert trade.roll_count == 3
        assert len(trade.adjustment_history) == 3


# ---------------------------------------------------------------------------
# ExpirySelector
# ---------------------------------------------------------------------------

class TestExpirySelector:

    def _strategies(self):
        return {
            "put_credit_spread": PutCreditSpreadStrategy(lots=2, min_vix=0),
            "calendar_spread": CalendarSpreadStrategy(lots=2),
        }

    def test_evaluate_all_returns_candidates(self):
        sel = ExpirySelector(
            spot=22000, vix=16,
            eligible_strategies=["put_credit_spread", "calendar_spread"],
        )
        candidates = sel.evaluate_all(date(2026, 4, 1), self._strategies())
        assert len(candidates) > 0
        assert all(isinstance(c, ExpiryCandidate) for c in candidates)

    def test_candidates_sorted_by_score_descending(self):
        sel = ExpirySelector(
            spot=22000, vix=16,
            eligible_strategies=["put_credit_spread", "calendar_spread"],
        )
        candidates = sel.evaluate_all(date(2026, 4, 1), self._strategies())
        scores = [c.score for c in candidates]
        assert scores == sorted(scores, reverse=True)

    def test_select_best_returns_single(self):
        sel = ExpirySelector(
            spot=22000, vix=16,
            eligible_strategies=["put_credit_spread", "calendar_spread"],
        )
        best = sel.select_best(date(2026, 4, 1), self._strategies())
        assert best is not None
        assert best.strategy_name in ("put_credit_spread", "calendar_spread")
        assert best.dte > 0
        assert best.score > -999

    def test_empty_eligible_returns_none(self):
        sel = ExpirySelector(spot=22000, vix=16, eligible_strategies=[])
        best = sel.select_best(date(2026, 4, 1), self._strategies())
        assert best is None

    def test_multiple_expiries_evaluated(self):
        sel = ExpirySelector(
            spot=22000, vix=16,
            eligible_strategies=["put_credit_spread"],
            num_expiries=3,
        )
        candidates = sel.evaluate_all(date(2026, 4, 1), self._strategies())
        dtes = set(c.dte for c in candidates)
        assert len(dtes) >= 2

    def test_longer_dte_gets_bonus(self):
        sel = ExpirySelector(
            spot=22000, vix=16,
            eligible_strategies=["put_credit_spread"],
            num_expiries=3,
        )
        candidates = sel.evaluate_all(date(2026, 4, 1), self._strategies())
        if len(candidates) >= 2:
            longer = [c for c in candidates if c.dte >= 30]
            shorter = [c for c in candidates if c.dte < 25]
            if longer and shorter:
                for lc in longer:
                    assert any("Longer DTE" in r for r in lc.reasoning)


# ---------------------------------------------------------------------------
# Win probability estimate
# ---------------------------------------------------------------------------

class TestWinProbEstimate:

    def test_further_otm_higher_prob(self):
        near = _estimate_win_prob(15.0, 21, 50, 450, 3.0)
        far = _estimate_win_prob(15.0, 21, 50, 450, 6.0)
        assert far > near

    def test_bounded_0_to_1(self):
        for vix in [10, 15, 25, 40]:
            for dist in [0.5, 2, 5, 10]:
                p = _estimate_win_prob(vix, 21, 50, 500, dist)
                assert 0 <= p <= 1.0

    def test_higher_vix_lower_prob_same_distance(self):
        low_vix = _estimate_win_prob(12.0, 21, 50, 450, 4.0)
        high_vix = _estimate_win_prob(25.0, 21, 50, 450, 4.0)
        assert low_vix > high_vix


