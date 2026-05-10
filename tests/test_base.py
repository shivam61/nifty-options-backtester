"""
Tests for strategies/base.py

Covers:
- Leg P&L math (short vs long legs)
- Trade net credit, total P&L, max loss
- Edge cases (no legs, single leg, mixed option types)
"""

import pytest
from datetime import date

from strategies.base import Leg, Trade, TradeAction, ExitReason


# ---------------------------------------------------------------------------
# Leg
# ---------------------------------------------------------------------------

class TestLeg:

    def test_short_leg_pnl_positive_when_premium_decays(self):
        leg = Leg("PE", 21000, is_short=True, entry_premium=100.0, current_premium=60.0, lots=1, lot_size=65)
        assert leg.pnl == (100.0 - 60.0) * 65
        assert leg.pnl > 0

    def test_short_leg_pnl_negative_when_premium_rises(self):
        leg = Leg("PE", 21000, is_short=True, entry_premium=100.0, current_premium=200.0, lots=1, lot_size=65)
        assert leg.pnl == (100.0 - 200.0) * 65
        assert leg.pnl < 0

    def test_long_leg_pnl_positive_when_premium_rises(self):
        leg = Leg("PE", 20000, is_short=False, entry_premium=25.0, current_premium=80.0, lots=1, lot_size=65)
        assert leg.pnl == (80.0 - 25.0) * 65
        assert leg.pnl > 0

    def test_long_leg_pnl_negative_when_premium_decays(self):
        leg = Leg("PE", 20000, is_short=False, entry_premium=25.0, current_premium=5.0, lots=1, lot_size=65)
        assert leg.pnl < 0

    def test_quantity_is_lots_times_lot_size(self):
        leg = Leg("CE", 23000, True, 100.0, 100.0, lots=3, lot_size=65)
        assert leg.quantity == 195

    def test_entry_value_short_is_negative(self):
        """Short = sold premium, so entry_value (cash outflow from writer's perspective) is negative."""
        leg = Leg("CE", 23000, True, 100.0, 100.0, lots=1, lot_size=65)
        assert leg.entry_value < 0

    def test_entry_value_long_is_positive(self):
        leg = Leg("CE", 24000, False, 30.0, 30.0, lots=1, lot_size=65)
        assert leg.entry_value > 0


# ---------------------------------------------------------------------------
# Trade
# ---------------------------------------------------------------------------

class TestTrade:

    def _make_iron_condor(self, lots=2, lot_size=65):
        return Trade(
            strategy_name="test_ic",
            entry_date=date(2024, 6, 1),
            legs=[
                Leg("CE", 23000, True, 120.0, 120.0, lots, lot_size),
                Leg("CE", 24000, False, 30.0, 30.0, lots, lot_size),
                Leg("PE", 21000, True, 100.0, 100.0, lots, lot_size),
                Leg("PE", 20000, False, 25.0, 25.0, lots, lot_size),
            ],
            entry_spot=22000.0,
            entry_vix=15.0,
            lots=lots,
            lot_size=lot_size,
        )

    def test_net_credit_positive_for_iron_condor(self):
        trade = self._make_iron_condor()
        assert trade.net_credit > 0
        assert trade.net_credit == pytest.approx(120.0 + 100.0 - 30.0 - 25.0, abs=0.01)

    def test_total_pnl_zero_at_entry(self):
        """At entry, current_premium == entry_premium, so P&L should be zero."""
        trade = self._make_iron_condor()
        assert trade.total_pnl == pytest.approx(0.0, abs=0.01)

    def test_total_pnl_positive_when_premiums_decay(self):
        trade = self._make_iron_condor()
        for leg in trade.legs:
            if leg.is_short:
                leg.current_premium = leg.entry_premium * 0.5
            else:
                leg.current_premium = leg.entry_premium * 0.3
        assert trade.total_pnl > 0

    def test_max_loss_bounded_by_spread_width(self):
        trade = self._make_iron_condor()
        credit = trade.net_credit
        spread_width = 1000  # 23000-24000 or 21000-20000
        expected_max_loss = (spread_width - credit) * 2 * 65
        assert trade.max_loss == pytest.approx(expected_max_loss, rel=0.05)

    def test_is_open_before_exit(self):
        trade = self._make_iron_condor()
        assert trade.is_open is True

    def test_is_closed_after_exit(self):
        trade = self._make_iron_condor()
        trade.exit_date = date(2024, 6, 20)
        assert trade.is_open is False

    def test_holding_days_calculated(self):
        trade = self._make_iron_condor()
        trade.exit_date = date(2024, 6, 15)
        assert trade.holding_days == 14

    def test_pnl_per_unit_matches_credit_minus_debit(self):
        trade = self._make_iron_condor()
        assert trade.pnl_per_unit == pytest.approx(
            trade.net_credit - trade.current_debit, abs=0.01
        )

    def test_empty_trade_has_zero_credit(self):
        trade = Trade(strategy_name="empty", entry_date=date(2024, 1, 1))
        assert trade.net_credit == 0.0
        assert trade.total_pnl == 0.0

    def test_single_short_leg(self):
        """Naked short (no hedge) — max loss based on multiplier fallback."""
        trade = Trade(
            strategy_name="naked",
            entry_date=date(2024, 1, 1),
            legs=[Leg("PE", 22000, True, 200.0, 200.0, 1, 65)],
            lots=1, lot_size=65,
        )
        assert trade.net_credit == 200.0
        assert trade.total_pnl == pytest.approx(0.0, abs=0.01)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class TestEnums:

    def test_trade_action_values(self):
        assert TradeAction.ENTER.value == "enter"
        assert TradeAction.EXIT.value == "exit"
        assert TradeAction.HOLD.value == "hold"
        assert TradeAction.NO_TRADE.value == "no_trade"

    def test_exit_reason_values(self):
        assert ExitReason.PROFIT_TARGET.value == "profit_target"
        assert ExitReason.STOP_LOSS.value == "stop_loss"
        assert ExitReason.EXPIRY.value == "expiry"
        assert ExitReason.DTE_LIMIT.value == "dte_limit"
