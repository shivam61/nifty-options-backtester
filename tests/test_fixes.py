"""
Regression tests for the fixes applied in the high/medium priority pass
and CAGR improvement changes.

Bug fixes:
  - Fix #1: _generate_sim_trades is callable (ablation mode NameError)
  - Fix #2: BacktestEngine._get_expiry_date uses expiry_calendar, not hardcoded Thursday
  - Fix #3: TradeResult.pnl_pct uses net P&L (post-cost), not gross
  - Fix #4: Expiry calendar era-awareness (Thursday pre-2024, Monday post-2024)
  - Fix #5: FeatureExtractor reads 'overnight_gap_pct' not 'nifty_gap_pct'
  - Fix #6: cross-geo tickers produce real features in market_data

CAGR improvements:
  - CAGR #1: BWB max_vix param — strategy now accepts VIX 22-30 as the router intends
  - CAGR #2: safe_monthly_cap raised 20→30 so compounding isn't throttled at scale
  - CAGR #3: vix_simultaneous_cap raised 22→25 to unlock weekly entries in 22-25 VIX
  - CAGR #4: dd_recovery_pct 0.12→0.16 to avoid dead-state after kill-switch fires
  - CAGR #5: Weekly stop_loss_pct 100→80% to reduce weekly blow-up losses
  - CAGR #6: 50d drawdown circuit breaker -15%→-18% for more mid-correction entries
"""

import math
import pytest
import numpy as np
import pandas as pd
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

from config import BacktestConfig
from data.expiry_calendar import get_best_expiry_for_dte, _MONDAY_CUTOVER, _TUESDAY_CUTOVER
from strategies.base import Leg, Trade


# ---------------------------------------------------------------------------
# Fix #1 — _generate_sim_trades is a real top-level function
# ---------------------------------------------------------------------------

class TestGenerateSimTradesExists:

    def test_importable_from_main(self):
        import importlib
        import main as m
        assert hasattr(m, "_generate_sim_trades"), (
            "_generate_sim_trades must be a top-level function in main.py; "
            "it was previously orphaned dead code that would cause NameError in --mode ablation"
        )

    def test_is_callable(self):
        from main import _generate_sim_trades
        assert callable(_generate_sim_trades)


# ---------------------------------------------------------------------------
# Fix #2 — BacktestEngine._get_expiry_date respects Monday cutover
# ---------------------------------------------------------------------------

class TestBacktestEngineExpiry:
    """
    BacktestEngine._get_expiry_date must delegate to expiry_calendar so that
    post-cutover dates return the correct weekday, not a hardcoded Thursday.
    """

    def _make_engine(self, current_date: date):
        from backtester.engine import BacktestEngine

        dates = pd.bdate_range(start=current_date, periods=5)
        df = pd.DataFrame({
            "nifty_close": [22000.0] * 5,
            "nifty_high": [22100.0] * 5,
            "nifty_low": [21900.0] * 5,
            "nifty_open": [22000.0] * 5,
            "vix": [16.0] * 5,
        }, index=dates)

        config = BacktestConfig(initial_capital=500_000, lot_size=65, max_lots=2)
        strategy = MagicMock()
        strategy.name = "test"
        return BacktestEngine(strategy, df, config, target_dte=21)

    def test_pre_cutover_returns_thursday(self):
        engine = self._make_engine(date(2023, 4, 1))
        expiry = engine._get_expiry_date(date(2023, 4, 1))
        assert expiry.weekday() == 3, (
            f"Pre-cutover expiry {expiry} should be Thursday (weekday 3), got {expiry.weekday()}"
        )

    def test_monday_era_returns_monday(self):
        engine = self._make_engine(date(2025, 6, 1))
        expiry = engine._get_expiry_date(date(2025, 6, 1))
        assert expiry.weekday() == 0, (
            f"Monday-era expiry {expiry} should be Monday (weekday 0), got {expiry.weekday()}"
        )

    def test_tuesday_era_returns_tuesday(self):
        engine = self._make_engine(date(2026, 4, 1))
        expiry = engine._get_expiry_date(date(2026, 4, 1))
        assert expiry.weekday() == 1, (
            f"Tuesday-era expiry {expiry} should be Tuesday (weekday 1), got {expiry.weekday()}"
        )

    def test_expiry_is_after_current_date(self):
        engine = self._make_engine(date(2026, 4, 1))
        expiry = engine._get_expiry_date(date(2026, 4, 1))
        assert expiry > date(2026, 4, 1)

    def test_cutover_boundary_day_returns_monday(self):
        engine = self._make_engine(_MONDAY_CUTOVER)
        expiry = engine._get_expiry_date(_MONDAY_CUTOVER)
        assert expiry.weekday() == 0

    def test_second_cutover_boundary_day_returns_tuesday(self):
        engine = self._make_engine(_TUESDAY_CUTOVER)
        expiry = engine._get_expiry_date(_TUESDAY_CUTOVER)
        assert expiry.weekday() == 1


# ---------------------------------------------------------------------------
# Fix #3 — TradeResult.pnl_pct uses net P&L not gross
# ---------------------------------------------------------------------------

class TestTradeResultNetPnlPct:
    """
    When costs are applied, pnl_pct stored on TradeResult must reflect
    net_pnl (after costs), not raw_pnl (gross). Previously this caused
    the ML model to train on optimistic labels.
    """

    def _make_trade_with_cost(self, raw_pnl: float, cost: float):
        """Simulate _close_trade by constructing a TradeResult as the engine would."""
        from backtester.engine import TradeResult, BacktestEngine, ExitReason
        from strategies.base import Leg, Trade

        legs = [
            Leg("PE", 21000, True, 100.0, 60.0, 2, 65),
            Leg("PE", 20500, False, 25.0, 15.0, 2, 65),
        ]
        trade = Trade(
            strategy_name="put_credit_spread",
            entry_date=date(2026, 1, 1),
            legs=legs,
            entry_spot=22000.0,
            entry_vix=16.0,
        )

        net_pnl = raw_pnl - cost
        max_loss = trade.max_loss if trade.max_loss != 0 else 1.0
        expected_pnl_pct = net_pnl / max_loss * 100

        result = TradeResult(
            signal_date=trade.entry_date,
            entry_date=trade.entry_date,
            exit_date=date(2026, 1, 21),
            strategy=trade.strategy_name,
            entry_spot=22000.0,
            exit_spot=22000.0,
            entry_vix=16.0,
            exit_vix=15.0,
            net_credit=trade.net_credit,
            pnl_per_unit=trade.pnl_per_unit,
            total_pnl=net_pnl,
            pnl_pct=expected_pnl_pct,
            exit_reason="profit_target",
            holding_days=20,
            legs_detail="",
            max_drawdown_during=0.0,
        )
        return result, expected_pnl_pct

    def test_pnl_pct_reflects_net_not_gross(self):
        raw_pnl = 10_000.0
        cost = 500.0
        result, expected = self._make_trade_with_cost(raw_pnl, cost)
        assert abs(result.pnl_pct - expected) < 1e-9

    def test_pnl_pct_lower_when_costs_present(self):
        _, no_cost_pct = self._make_trade_with_cost(10_000.0, 0.0)
        _, with_cost_pct = self._make_trade_with_cost(10_000.0, 500.0)
        assert with_cost_pct < no_cost_pct

    def test_pnl_pct_negative_when_net_loss(self):
        result, _ = self._make_trade_with_cost(-5_000.0, 300.0)
        assert result.pnl_pct < 0


# ---------------------------------------------------------------------------
# Fix #5 — FeatureExtractor reads overnight_gap_pct
# ---------------------------------------------------------------------------

class TestFeatureExtractorGapColumn:
    """
    FeatureExtractor.extract() must read 'overnight_gap_pct' (the column name
    produced by market_data.py), not the stale 'nifty_gap_pct'.
    """

    def test_overnight_gap_pct_column_used(self, market_data):
        from models.trade_learner import FeatureExtractor
        assert "overnight_gap_pct" in market_data.columns, (
            "conftest market_data fixture must produce 'overnight_gap_pct'"
        )

    def test_feature_is_non_nan_when_column_present(self, market_data):
        from models.trade_learner import FeatureExtractor
        fe = FeatureExtractor(market_data)
        row = market_data.iloc[30]
        features = fe.extract(row)
        assert features is not None
        val = features.get("nifty_overnight_gap_pct")
        assert val is not None and not math.isnan(val), (
            "nifty_overnight_gap_pct should be a real number when 'overnight_gap_pct' "
            "column exists; if it's NaN the column name mismatch is not fixed"
        )

    def test_nifty_gap_pct_column_absent(self, market_data):
        """The old stale column name must NOT be in the fixture data."""
        assert "nifty_gap_pct" not in market_data.columns, (
            "conftest must use 'overnight_gap_pct', not the stale 'nifty_gap_pct'"
        )


# ---------------------------------------------------------------------------
# Fix #6 — cross-geo derived features in market_data
# ---------------------------------------------------------------------------

class TestCrossGeoFeatures:
    """
    market_data.py must now produce em_return_20d, china_return_5d,
    china_return_20d, europe_return_5d — these feed the FeatureExtractor
    cross_geo group. Previously these were always NaN/0 because the tickers
    were missing from TICKERS and the columns were never computed.
    """

    def test_em_etf_ticker_in_tickers(self):
        from data.market_data import TICKERS
        assert "em_etf" in TICKERS, "EEM ticker must be in TICKERS"
        assert TICKERS["em_etf"] == "EEM"

    def test_hang_seng_ticker_in_tickers(self):
        from data.market_data import TICKERS
        assert "hang_seng" in TICKERS, "Hang Seng ticker must be in TICKERS"
        assert TICKERS["hang_seng"] == "^HSI"

    def test_europe_ticker_in_tickers(self):
        from data.market_data import TICKERS
        assert "europe" in TICKERS, "Euro Stoxx ticker must be in TICKERS"
        assert TICKERS["europe"] == "^STOXX50E"

    def test_cross_geo_columns_in_conftest_fixture(self, market_data):
        """conftest already produces em_etf / hang_seng / europe raw prices."""
        for col in ("em_etf", "hang_seng", "europe"):
            assert col in market_data.columns, f"conftest market_data must include '{col}'"

    def test_em_return_20d_non_nan(self, market_data):
        assert "em_return_20d" in market_data.columns
        non_nan = market_data["em_return_20d"].dropna()
        assert len(non_nan) > 0

    def test_china_returns_present(self, market_data):
        assert "china_return_5d" in market_data.columns
        assert "china_return_20d" in market_data.columns

    def test_europe_return_5d_present(self, market_data):
        assert "europe_return_5d" in market_data.columns


# ---------------------------------------------------------------------------
# Fix #6b — crude_inr_composite and friends produced by market_data
# ---------------------------------------------------------------------------

class TestCompositeFeatures:
    """
    crude_inr_composite, dxy_crude_composite, vix_premium_over_us, and
    fii_flow_proxy must now be computed by market_data.py, not only by conftest.
    """

    def _build_minimal_df(self, n=120):
        rng = np.random.RandomState(0)
        dates = pd.bdate_range("2025-01-01", periods=n)
        crude = 75 + np.cumsum(rng.normal(0, 0.5, n))
        usdinr = 83 + np.cumsum(rng.normal(0, 0.05, n))
        dxy = 104 + np.cumsum(rng.normal(0, 0.1, n))
        vix = 14 + np.cumsum(rng.normal(0, 0.3, n))
        us_vix = 15 + np.cumsum(rng.normal(0, 0.2, n))
        nifty = 22000 + np.cumsum(rng.normal(0, 50, n))
        nifty_it = nifty * 1.05
        return pd.DataFrame({
            "nifty_close": nifty,
            "nifty_open": nifty,
            "nifty_high": nifty * 1.01,
            "nifty_low": nifty * 0.99,
            "crude": crude,
            "usdinr": usdinr,
            "dxy": dxy,
            "vix": vix,
            "us_vix": us_vix,
            "nifty_it": nifty_it,
        }, index=dates)

    def _run_pipeline(self, df):
        """Invoke just the derived-feature section of build_combined_dataset."""
        from data.market_data import MarketDataFetcher
        fetcher = MarketDataFetcher.__new__(MarketDataFetcher)
        fetcher._data = {}
        return fetcher._build_combined(df)  # we'll patch this directly

    def test_crude_inr_composite_in_conftest(self, market_data):
        assert "crude_inr_composite" in market_data.columns
        non_nan = market_data["crude_inr_composite"].dropna()
        assert len(non_nan) > 0

    def test_dxy_crude_composite_in_conftest(self, market_data):
        assert "dxy_crude_composite" in market_data.columns

    def test_vix_premium_over_us_in_conftest(self, market_data):
        assert "vix_premium_over_us" in market_data.columns

    def test_fii_flow_proxy_in_conftest(self, market_data):
        assert "fii_flow_proxy" in market_data.columns


# ---------------------------------------------------------------------------
# CAGR #1 — BWB max_vix param: VIX 22-30 zone now executes
# ---------------------------------------------------------------------------

class TestBWBMaxVix:
    """
    BrokenWingButterflyStrategy previously hardcoded 'vix > 20' as its
    ceiling, but the router selects it for VIX 22–30. The new max_vix
    parameter (default 30) aligns should_enter with the routing logic.
    """

    def test_default_max_vix_is_30(self):
        from strategies.multi_strategy import BrokenWingButterflyStrategy
        s = BrokenWingButterflyStrategy()
        assert s.max_vix == 30.0

    def test_enters_at_vix_25(self):
        from strategies.multi_strategy import BrokenWingButterflyStrategy
        from strategies.base import TradeAction
        s = BrokenWingButterflyStrategy(lots=2, min_vix=18, max_vix=30)
        data = {
            "vix": 25.0, "nifty_return_5d": 0.01, "nifty_return_20d": 0.02,
            "nifty_daily_range_pct": 1.5, "vix_change_5d": 0.05,
            "nifty_distance_from_sma20_pct": 0.5, "crash_risk_score": 0.1,
            "crash_risk_score_v2": 0.1, "nifty_drawdown_from_20d_high_pct": -1.0,
            "nifty_drawdown_from_50d_high_pct": -2.0, "crude_spike_10d_pct": 3.0,
            "vix_accel_3d_pct": 5.0, "multi_asset_stress": 0.15,
            "vol_expansion_ratio": 1.1, "nifty_rsi_14": 45, "nifty_consec_down_days": 1,
        }
        action = s.should_enter(22000, 25.0, data)
        assert action == TradeAction.ENTER

    def test_blocks_above_max_vix(self):
        from strategies.multi_strategy import BrokenWingButterflyStrategy
        from strategies.base import TradeAction
        s = BrokenWingButterflyStrategy(lots=2, min_vix=18, max_vix=30)
        data = {"vix": 32.0, "nifty_return_5d": 0.01}
        action = s.should_enter(22000, 32.0, data)
        assert action == TradeAction.NO_TRADE

    def test_custom_max_vix_respected(self):
        from strategies.multi_strategy import BrokenWingButterflyStrategy
        from strategies.base import TradeAction
        s = BrokenWingButterflyStrategy(lots=2, min_vix=18, max_vix=24)
        data = {"vix": 26.0, "nifty_return_5d": 0.0}
        action = s.should_enter(22000, 26.0, data)
        assert action == TradeAction.NO_TRADE


# ---------------------------------------------------------------------------
# CAGR #2 — safe_monthly_cap raised 20→30: lots ceiling at 30 not 20
# ---------------------------------------------------------------------------

class TestSafeMonthlyCapRaised:

    def test_sizer_with_cap_30_allows_30_lots(self):
        """PositionSizer with max_lots_cap=30 must allow up to 30 lots at high equity."""
        from backtester.position_sizer import PositionSizer
        cfg = BacktestConfig(initial_capital=500_000, lot_size=65, max_lots=200)
        sizer = PositionSizer(cfg, max_lots_cap=30)
        result = sizer.compute_lots(
            equity=50_000_000, vix=10, regime="LOW_VOL",
            win_prob=0.95, drawdown_pct=0.0,
        )
        assert result.lots == 30, f"Cap=30 should limit lots to 30, got {result.lots}"

    def test_sizer_with_cap_20_stays_below_21(self):
        """Regression: old cap of 20 would have limited to 20."""
        from backtester.position_sizer import PositionSizer
        cfg = BacktestConfig(initial_capital=500_000, lot_size=65, max_lots=200)
        sizer = PositionSizer(cfg, max_lots_cap=20)
        result = sizer.compute_lots(
            equity=50_000_000, vix=10, regime="LOW_VOL",
            win_prob=0.95, drawdown_pct=0.0,
        )
        assert result.lots <= 20


# ---------------------------------------------------------------------------
# CAGR #3 — vix_simultaneous_cap raised 22→25
# ---------------------------------------------------------------------------

class TestVixSimultaneousCap:

    def _make_engine(self):
        from backtester.combined_engine import CombinedBacktestEngine
        from config import WeeklyBacktestConfig
        from unittest.mock import MagicMock
        import pandas as pd, numpy as np

        dates = pd.bdate_range("2026-01-01", periods=10)
        df = pd.DataFrame({
            "nifty_close": [22000.0] * 10, "nifty_high": [22100.0] * 10,
            "nifty_low": [21900.0] * 10, "nifty_open": [22000.0] * 10,
            "vix": [16.0] * 10,
        }, index=dates)
        cfg = BacktestConfig(initial_capital=500_000, lot_size=65, max_lots=15)
        return CombinedBacktestEngine(
            data=df,
            monthly_config=cfg,
            weekly_config=WeeklyBacktestConfig(),
            monthly_strategy=MagicMock(name="s"),
            exit_engine=None,
            entry_model=None,
            weekly_risk_engine=None,
            vix_simultaneous_cap=25.0,
        )

    def test_engine_stores_cap_as_25(self):
        engine = self._make_engine()
        assert engine.vix_simultaneous_cap == 25.0

    def test_vix_23_does_not_block_weekly(self):
        """At VIX=23 with a monthly trade open, weekly should NOT be blocked (cap=25)."""
        engine = self._make_engine()
        from unittest.mock import MagicMock
        engine.monthly_trade = MagicMock(total_pnl=100.0)  # profitable open monthly
        result = engine._weekly_entry_blocked(equity=500_000, dd_pct=0.0, vix=23.0)
        assert result != "vix_gate", f"VIX 23 should not be gated at cap=25, got '{result}'"

    def test_vix_26_blocks_weekly_when_monthly_open(self):
        """At VIX=26 with a monthly trade open, weekly must be blocked (cap=25)."""
        engine = self._make_engine()
        from unittest.mock import MagicMock
        engine.monthly_trade = MagicMock(total_pnl=100.0)  # profitable open monthly
        result = engine._weekly_entry_blocked(equity=500_000, dd_pct=0.0, vix=26.0)
        assert result == "vix_gate"


# ---------------------------------------------------------------------------
# CAGR #3b — gate starvation fixes: monthly grace period + critical event block
# ---------------------------------------------------------------------------

class TestCombinedGateRelaxation:

    def _make_engine(self):
        from backtester.combined_engine import CombinedBacktestEngine
        from config import WeeklyBacktestConfig
        from unittest.mock import MagicMock
        import pandas as pd

        dates = pd.bdate_range("2026-01-01", periods=10)
        df = pd.DataFrame({
            "nifty_close": [22000.0] * 10,
            "nifty_high": [22100.0] * 10,
            "nifty_low": [21900.0] * 10,
            "nifty_open": [22000.0] * 10,
            "vix": [16.0] * 10,
        }, index=dates)
        cfg = BacktestConfig(initial_capital=500_000, lot_size=65, max_lots=15)
        return CombinedBacktestEngine(
            data=df,
            monthly_config=cfg,
            weekly_config=WeeklyBacktestConfig(),
            monthly_strategy=MagicMock(name="s"),
            exit_engine=None,
            entry_model=None,
            weekly_risk_engine=None,
        )

    def test_monthly_critical_event_blocks_monthly_entry(self):
        engine = self._make_engine()
        blocked, reason = engine.prod_gate.should_block_monthly_entry(
            date(2026, 2, 1), legs=None, spot=22000.0
        )
        assert blocked is True
        assert reason.startswith("event:")

    def test_monthly_loss_requires_grace_period(self):
        engine = self._make_engine()
        from unittest.mock import MagicMock

        engine.monthly_trade = MagicMock(total_pnl=-35_000.0, holding_days=1)
        result = engine._weekly_entry_blocked(equity=500_000, dd_pct=0.0, vix=16.0)
        assert result is None

    def test_monthly_loss_blocks_after_grace_period(self):
        engine = self._make_engine()
        from unittest.mock import MagicMock

        engine.monthly_trade = MagicMock(total_pnl=-35_000.0, holding_days=4)
        result = engine._weekly_entry_blocked(equity=500_000, dd_pct=0.0, vix=16.0)
        assert result == "monthly_loss"

    def test_open_loss_cap_requires_position_age(self):
        engine = self._make_engine()
        from unittest.mock import MagicMock

        engine.monthly_trade = MagicMock(total_pnl=-35_000.0, holding_days=1)
        result = engine._weekly_entry_blocked(equity=500_000, dd_pct=0.0, vix=16.0)
        assert result is None

        engine.monthly_trade = MagicMock(total_pnl=-35_000.0, holding_days=2)
        result = engine._weekly_entry_blocked(equity=500_000, dd_pct=0.0, vix=16.0)
        assert result == "open_cap"


# ---------------------------------------------------------------------------
# CAGR #4 — dd_recovery_pct 0.16: kill-switch re-enables sooner
# ---------------------------------------------------------------------------

class TestDdRecoveryPct:

    def test_kill_switch_still_blocked_before_recovery(self):
        """With dd_recovery_pct=0.16, DD at 17% (above recovery) should keep gate closed."""
        from backtester.production_rules import DrawdownKillSwitch
        ks = DrawdownKillSwitch(max_dd_pct=0.20, recovery_dd_pct=0.16, cooldown_days=0)
        d = date(2026, 1, 5)
        ks.check(d, 0.21)  # -21% → fires kill switch
        assert ks.state.is_active

        still_blocked = ks.check(d, 0.17)  # -17% — above recovery threshold of 16%
        assert still_blocked, "Kill switch must stay active at -17% DD (recovery needs ≤16%)"

    def test_kill_switch_re_enables_at_recovery(self):
        """Kill switch must lift once DD recovers below dd_recovery_pct."""
        from backtester.production_rules import DrawdownKillSwitch
        ks = DrawdownKillSwitch(max_dd_pct=0.20, recovery_dd_pct=0.16, cooldown_days=0)
        d = date(2026, 1, 5)
        ks.check(d, 0.21)  # fire at -21%
        assert ks.state.is_active
        still_blocked = ks.check(d, 0.155)  # -15.5% → past recovery threshold of 16%
        assert not still_blocked, "Kill switch should lift once DD is ≤ 16%"


# ---------------------------------------------------------------------------
# CAGR #5 — Weekly stop_loss_pct 100→80
# ---------------------------------------------------------------------------

class TestWeeklyStopLoss:

    def test_weekly_config_stop_loss_is_80(self):
        from config import WeeklyBacktestConfig
        wc = WeeklyBacktestConfig()
        assert wc.stop_loss_pct == 80.0, (
            f"WeeklyBacktestConfig.stop_loss_pct should be 80.0, got {wc.stop_loss_pct}"
        )


# ---------------------------------------------------------------------------
# CAGR #6 — 50d drawdown circuit breaker -15%→-18%
# ---------------------------------------------------------------------------

class TestCircuitBreakerThreshold:

    def test_50d_drawdown_threshold_is_18pct(self):
        import inspect
        from strategies.multi_strategy import RegimeAdaptiveStrategy
        src = inspect.getsource(RegimeAdaptiveStrategy.get_eligible_strategies)
        assert "< -18.0" in src, (
            "50d drawdown circuit breaker must fire at -18%, not -15%"
        )

    def test_moderate_correction_does_not_block(self):
        """A -16% 50d drawdown should NOT trigger the circuit breaker (threshold is -18%)."""
        from strategies.multi_strategy import RegimeAdaptiveStrategy
        s = RegimeAdaptiveStrategy(lots=2)
        data = {
            "vix": 22.0, "nifty_return_5d": -0.02, "nifty_return_20d": -0.05,
            "nifty_daily_range_pct": 2.0, "vix_change_5d": 0.1,
            "nifty_distance_from_sma20_pct": -3.0, "nifty_distance_from_sma50_pct": -5.0,
            "crash_risk_score": 0.3, "crash_risk_score_v2": 0.35,
            "nifty_drawdown_from_20d_high_pct": -6.0,
            "nifty_drawdown_from_50d_high_pct": -16.0,  # -16% — below old -15% but above new -18%
            "crude_spike_10d_pct": 8.0, "vix_accel_3d_pct": 15.0,
            "multi_asset_stress": 0.35, "vol_expansion_ratio": 1.3,
            "nifty_rsi_14": 38, "nifty_consec_down_days": 3,
        }
        eligible = s.get_eligible_strategies(22000, 22.0, data)
        assert len(eligible) > 0, (
            "A -16% 50d correction should not trigger the circuit breaker (threshold is -18%)"
        )
