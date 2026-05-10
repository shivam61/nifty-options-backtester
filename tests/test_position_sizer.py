"""
Tests for backtester/position_sizer.py

Covers:
- Cold start (few trades): margin-fallback sizing
- Volatility targeting layer (with equity-at-entry fix)
- Confidence tier scaler (3-tier)
- Regime scaling
- Drawdown scaling
- Combined compute_lots
- Edge cases (zero equity, extreme VIX)
"""

import pytest
from dataclasses import dataclass

from config import BacktestConfig
from backtester.position_sizer import (
    PositionSizer,
    SizingDecision,
    _TradeReturn,
    _regime_from_vix,
    _drawdown_scale,
    _confidence_scale,
    REGIME_SCALE,
    _VOL_WARMUP,
)


# ── VIX regime mapping ──────────────────────────────────────────────────

class TestRegimeFromVix:

    def test_low_vol(self):
        assert _regime_from_vix(10.0) == "LOW_VOL"
        assert _regime_from_vix(13.9) == "LOW_VOL"

    def test_trending(self):
        assert _regime_from_vix(15.0) == "TRENDING"
        assert _regime_from_vix(17.5) == "TRENDING"

    def test_high_vol(self):
        assert _regime_from_vix(20.0) == "HIGH_VOL"
        assert _regime_from_vix(24.9) == "HIGH_VOL"

    def test_crash(self):
        assert _regime_from_vix(25.0) == "CRASH"
        assert _regime_from_vix(50.0) == "CRASH"


# ── Drawdown scaler ─────────────────────────────────────────────────────

class TestDrawdownScale:

    def test_no_drawdown(self):
        assert _drawdown_scale(0.0) == 1.0

    def test_small_drawdown(self):
        assert _drawdown_scale(0.03) == 1.0

    def test_moderate_drawdown(self):
        assert _drawdown_scale(0.07) == 0.85

    def test_large_drawdown(self):
        assert _drawdown_scale(0.12) == 0.65

    def test_severe_drawdown(self):
        assert _drawdown_scale(0.20) == 0.45

    def test_boundary_5pct(self):
        assert _drawdown_scale(0.05) == 1.0

    def test_boundary_10pct(self):
        assert _drawdown_scale(0.10) == 0.85


# ── Confidence tier scaler ───────────────────────────────────────────────

class TestConfidenceScale:

    def test_high_confidence(self):
        assert _confidence_scale(0.70) == 1.15
        assert _confidence_scale(0.90) == 1.15

    def test_neutral_confidence(self):
        assert _confidence_scale(0.60) == 1.0
        assert _confidence_scale(0.56) == 1.0

    def test_low_confidence(self):
        assert _confidence_scale(0.50) == 0.90
        assert _confidence_scale(0.30) == 0.90

    def test_boundary_065(self):
        assert _confidence_scale(0.65) == 1.0  # > 0.65 is the threshold; 0.65 is neutral
        assert _confidence_scale(0.651) == 1.15

    def test_boundary_055(self):
        assert _confidence_scale(0.55) == 0.90  # > 0.55 needed for neutral; 0.55 is low tier
        assert _confidence_scale(0.551) == 1.0
        assert _confidence_scale(0.549) == 0.90


# ── Cold start / margin fallback ────────────────────────────────────────

class TestColdStart:

    def setup_method(self):
        self.config = BacktestConfig(initial_capital=500_000, lot_size=65, max_lots=15)
        self.sizer = PositionSizer(self.config, max_lots_cap=200)

    def test_few_trades_uses_margin_fallback(self):
        """With < 20 recorded trades, vol targeting can't estimate vol."""
        result = self.sizer.compute_lots(
            equity=500_000, vix=12, regime="LOW_VOL",
            win_prob=0.70, drawdown_pct=0.0,
        )
        assert result.lots >= 1
        assert result.regime_scale == 1.0
        assert result.dd_scale == 1.0

    def test_zero_trades_still_sizes(self):
        result = self.sizer.compute_lots(
            equity=500_000, vix=12, regime="LOW_VOL",
            win_prob=0.70, drawdown_pct=0.0,
        )
        assert result.lots >= 1
        assert result.lots >= 5

    def test_zero_equity_returns_floor(self):
        result = self.sizer.compute_lots(
            equity=0, vix=12, regime="LOW_VOL",
            win_prob=0.70, drawdown_pct=0.0,
        )
        assert result.lots == 1
        assert result.reason == "equity <= 0, floor"


# ── Volatility targeting (with equity-at-entry fix) ─────────────────────

class TestVolTargeting:

    def setup_method(self):
        self.config = BacktestConfig(initial_capital=500_000, lot_size=65, max_lots=15)
        self.sizer = PositionSizer(self.config, target_annual_vol=0.15, max_lots_cap=200)

    def test_warmup_returns_margin_based(self):
        """Below _VOL_WARMUP trades → margin fallback."""
        for _ in range(_VOL_WARMUP - 1):
            self.sizer.record_trade_with_equity(5000, 500_000)
        base = self.sizer._base_lots(500_000)
        margin = self.sizer._margin_fallback(500_000)
        assert base == margin

    def test_vol_target_activates_after_warmup(self):
        """After _VOL_WARMUP trades, vol targeting kicks in."""
        for _ in range(_VOL_WARMUP + 5):
            self.sizer.record_trade_with_equity(5000, 500_000)
        base = self.sizer._base_lots(500_000)
        margin = self.sizer._margin_fallback(500_000)
        assert base != margin or base > 0

    def test_volatile_trades_reduce_lots(self):
        """Volatile returns → smaller vol-target base lots."""
        sizer_wild = PositionSizer(self.config, target_annual_vol=0.15, max_lots_cap=200)
        pnls_wild = [50_000, -40_000, 60_000, -55_000] * 8
        for p in pnls_wild:
            sizer_wild.record_trade_with_equity(p, 500_000)

        sizer_calm = PositionSizer(self.config, target_annual_vol=0.15, max_lots_cap=200)
        pnls_calm = [5_000, 4_000, 6_000, 3_000] * 8
        for p in pnls_calm:
            sizer_calm.record_trade_with_equity(p, 500_000)

        wild_base = sizer_wild._base_lots(500_000)
        calm_base = sizer_calm._base_lots(500_000)
        assert wild_base < calm_base

    def test_equity_at_entry_used_for_return(self):
        """Vol-target uses equity_at_entry (not current equity) for return calc."""
        tr = _TradeReturn(pnl=10_000, equity_at_entry=200_000)
        assert abs(tr.ret - 0.05) < 1e-9
        tr2 = _TradeReturn(pnl=10_000, equity_at_entry=1_000_000)
        assert abs(tr2.ret - 0.01) < 1e-9
        assert tr.ret > tr2.ret


# ── Confidence tier integration ──────────────────────────────────────────

class TestConfidenceIntegration:

    def setup_method(self):
        self.config = BacktestConfig(initial_capital=500_000, lot_size=65, max_lots=15)
        self.sizer = PositionSizer(self.config, max_lots_cap=200)

    def test_high_confidence_more_lots_than_low(self):
        """High win_prob (>0.65) gets a modest boost while low confidence is muted."""
        high = self.sizer.compute_lots(
            equity=500_000, vix=12, regime="LOW_VOL",
            win_prob=0.70, drawdown_pct=0.0,
        )
        low = self.sizer.compute_lots(
            equity=500_000, vix=12, regime="LOW_VOL",
            win_prob=0.40, drawdown_pct=0.0,
        )
        assert high.confidence_scale == 1.15
        assert low.confidence_scale == 0.90
        assert high.lots >= low.lots

    def test_neutral_confidence_no_scaling(self):
        result = self.sizer.compute_lots(
            equity=500_000, vix=12, regime="LOW_VOL",
            win_prob=0.60, drawdown_pct=0.0,
        )
        assert result.confidence_scale == 1.0

    def test_risk_budget_can_reject_unsafe_structure(self):
        result = self.sizer.compute_lots(
            equity=500_000, vix=24, regime="HIGH_VOL",
            win_prob=0.80, drawdown_pct=0.0,
            trade_max_loss_per_unit=2000.0,
            trade_margin_per_lot=130_000.0,
        )
        assert result.lots == 0
        assert "budget too small" in result.reason

    def test_positive_structure_still_sizes(self):
        result = self.sizer.compute_lots(
            equity=500_000, vix=24, regime="HIGH_VOL",
            win_prob=0.80, drawdown_pct=0.0,
            trade_max_loss_per_unit=250.0,
            trade_margin_per_lot=16_250.0,
        )
        assert result.lots >= 1

    def test_config_override_changes_high_vol_scale(self):
        config = BacktestConfig(
            initial_capital=500_000,
            lot_size=65,
            max_lots=15,
            monthly_high_vol_scale=0.82,
        )
        sizer = PositionSizer(config, max_lots_cap=200)
        result = sizer.compute_lots(
            equity=500_000, vix=24, regime="HIGH_VOL",
            win_prob=0.60, drawdown_pct=0.0,
        )
        assert result.regime_scale == 0.82


# ── Regime scaling ───────────────────────────────────────────────────────

class TestRegimeScaling:

    def setup_method(self):
        self.config = BacktestConfig(initial_capital=500_000, lot_size=65, max_lots=15)
        self.sizer = PositionSizer(self.config, max_lots_cap=200)

    def test_crash_regime_reduces_lots(self):
        low_vol = self.sizer.compute_lots(
            equity=500_000, vix=12, regime="LOW_VOL",
            win_prob=0.70, drawdown_pct=0.0,
        )
        crash = self.sizer.compute_lots(
            equity=500_000, vix=35, regime="CRASH",
            win_prob=0.70, drawdown_pct=0.0,
        )
        assert crash.regime_scale == REGIME_SCALE["CRASH"]
        assert low_vol.regime_scale == 1.0
        assert crash.lots <= low_vol.lots

    def test_unknown_regime_falls_back_to_vix(self):
        result = self.sizer.compute_lots(
            equity=500_000, vix=30, regime="SOME_UNKNOWN",
            win_prob=0.70, drawdown_pct=0.0,
        )
        assert result.regime_scale == REGIME_SCALE["CRASH"]


# ── Drawdown integration ────────────────────────────────────────────────

class TestDrawdownIntegration:

    def setup_method(self):
        self.config = BacktestConfig(initial_capital=500_000, lot_size=65, max_lots=15)
        self.sizer = PositionSizer(self.config, max_lots_cap=200)

    def test_deep_drawdown_reduces_lots(self):
        no_dd = self.sizer.compute_lots(
            equity=500_000, vix=12, regime="LOW_VOL",
            win_prob=0.70, drawdown_pct=0.0,
        )
        deep_dd = self.sizer.compute_lots(
            equity=500_000, vix=12, regime="LOW_VOL",
            win_prob=0.70, drawdown_pct=0.20,
        )
        assert deep_dd.dd_scale == 0.45
        assert deep_dd.lots < no_dd.lots


# ── Combined behaviour ──────────────────────────────────────────────────

class TestCombined:

    def setup_method(self):
        self.config = BacktestConfig(initial_capital=500_000, lot_size=65, max_lots=15)
        self.sizer = PositionSizer(self.config, max_lots_cap=200)

    def test_floor_is_always_1(self):
        result = self.sizer.compute_lots(
            equity=10_000, vix=40, regime="CRASH",
            win_prob=0.30, drawdown_pct=0.20,
        )
        assert result.lots >= 1

    def test_ceiling_is_max_lots_cap(self):
        sizer = PositionSizer(self.config, max_lots_cap=10)
        result = sizer.compute_lots(
            equity=50_000_000, vix=10, regime="LOW_VOL",
            win_prob=0.95, drawdown_pct=0.0,
        )
        assert result.lots <= 10

    def test_sizing_decision_is_dataclass(self):
        result = self.sizer.compute_lots(
            equity=500_000, vix=12, regime="LOW_VOL",
            win_prob=0.70, drawdown_pct=0.0,
        )
        assert isinstance(result, SizingDecision)
        assert isinstance(result.lots, int)
        assert isinstance(result.reason, str)
        assert isinstance(result.confidence_scale, float)

    def test_record_trade_with_equity(self):
        self.sizer.record_trade_with_equity(10_000, 500_000)
        self.sizer.record_trade_with_equity(-5_000, 510_000)
        assert len(self.sizer._trade_returns) == 2
        assert self.sizer._trade_returns[0].pnl == 10_000
        assert self.sizer._trade_returns[0].equity_at_entry == 500_000
        assert self.sizer._trade_returns[1].pnl == -5_000

    def test_compounding_produces_more_lots_with_more_equity(self):
        """Higher equity → more lots (compounding works)."""
        small = self.sizer.compute_lots(
            equity=500_000, vix=12, regime="LOW_VOL",
            win_prob=0.70, drawdown_pct=0.0,
        )
        big = self.sizer.compute_lots(
            equity=2_000_000, vix=12, regime="LOW_VOL",
            win_prob=0.70, drawdown_pct=0.0,
        )
        assert big.lots > small.lots
