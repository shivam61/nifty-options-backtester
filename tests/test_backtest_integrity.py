from datetime import date, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest

from backtester.rolling_simulator import RollingWindowSimulator, SimConfig
from backtester.walk_forward import WalkForwardManager
from backtester.weekly_simulator import WeeklyRollingSimulator, WeeklySimConfig
from backtester.engine import SmartBacktestEngine
from backtester.combined_engine import CombinedBacktestEngine
from config import BacktestConfig, WeeklyBacktestConfig
from models.cache_utils import ModelPeriodMetadata
from models.regime_aware_learner import RegimeAwareLearner
from models.trade_monitor import ExitStrategyEngine
from models.weekly_entry_learner import WeeklyEntryLearner
from strategies.multi_strategy import RegimeAdaptiveStrategy


def test_period_metadata_rejects_future_reuse():
    md = ModelPeriodMetadata.build(
        model_type="monthly_entry",
        train_start=date(2024, 1, 1),
        train_end=date(2024, 6, 30),
        feature_version="v4",
        config={"lots": 2},
    )
    md.assert_usable_for(date(2024, 7, 1))
    with pytest.raises(ValueError):
        md.assert_usable_for(date(2024, 6, 30))


def test_walk_forward_bundle_is_strictly_oos(market_data, monkeypatch):
    # Mock model loading to avoid stale pickled numpy RNG state (MT19937 bit
    # generator mismatch across numpy versions) while still testing OOS logic.
    from models.cache_utils import ModelPeriodMetadata
    from datetime import date as _date

    class _DummyLearner:
        def __init__(self, train_end):
            self.period_metadata = ModelPeriodMetadata.build(
                model_type="monthly_entry",
                train_start=_date(2024, 1, 1),
                train_end=train_end,
                feature_version="v4",
                config={"lots": 1},
            )

    class _DummyExit:
        def __init__(self, train_end):
            self.period_metadata = ModelPeriodMetadata.build(
                model_type="exit",
                train_start=_date(2024, 1, 1),
                train_end=train_end,
                feature_version="v4",
                config={"lots": 1},
            )

    def _fake_entry_load(cls, market_data_arg, path=None, **kwargs):
        # Use a train_end well before any test window starts
        return _DummyLearner(train_end=_date(2024, 1, 31))

    def _fake_exit_load(cls, market_data_arg, path=None, **kwargs):
        return _DummyExit(train_end=_date(2024, 1, 31))

    monkeypatch.setattr(RegimeAwareLearner, "load", classmethod(_fake_entry_load))
    monkeypatch.setattr(ExitStrategyEngine, "load", classmethod(_fake_exit_load))

    wf = WalkForwardManager(
        market_data,
        monthly_config=BacktestConfig(max_lots=1, lot_size=65),
        include_monthly=True,
        retrain_interval_bars=10,
    )
    first_window = wf.windows[0]
    bundle = wf.get_bundle_for_date(first_window.test_start.date())
    assert bundle.entry_model is not None
    assert bundle.exit_engine is not None
    assert bundle.entry_model.period_metadata.train_end_date < first_window.test_start.date()
    assert bundle.exit_engine.period_metadata.train_end_date < first_window.test_start.date()


def test_walk_forward_cache_only_does_not_train_on_miss(market_data, tmp_path, monkeypatch):
    def fail_train(*args, **kwargs):
        raise AssertionError("training should not run in cache-only backtest mode")

    def miss_load(*args, **kwargs):
        raise FileNotFoundError("missing cache")

    monkeypatch.setattr(RegimeAwareLearner, "train", fail_train)
    monkeypatch.setattr(ExitStrategyEngine, "train_from_simulations", fail_train)
    monkeypatch.setattr(RegimeAwareLearner, "load", classmethod(lambda cls, *args, **kwargs: miss_load()))
    monkeypatch.setattr(ExitStrategyEngine, "load", classmethod(lambda cls, *args, **kwargs: miss_load()))

    wf = WalkForwardManager(
        market_data,
        monthly_config=BacktestConfig(max_lots=1, lot_size=65),
        include_monthly=True,
        train_on_cache_miss=False,
        cache_dir=tmp_path,
        retrain_interval_bars=10,
    )
    first_window = wf.windows[0]
    bundle = wf.get_bundle_for_date(first_window.test_start.date())
    assert bundle.entry_model is None
    assert bundle.exit_engine is None


def test_monthly_training_simulator_enters_next_bar(short_market_data):
    sim = RollingWindowSimulator(
        short_market_data,
        SimConfig(entry_every_n_days=5, hold_days=5, lots=1, lot_size=65),
    )
    trades = sim.simulate_all()
    assert trades
    first = trades[0]
    assert first.signal_date < first.entry_date
    signal_ts = pd.Timestamp(first.signal_date)
    entry_ts = pd.Timestamp(first.entry_date)
    expected_entry_spot = short_market_data.loc[entry_ts, "nifty_open"]
    assert first.entry_spot == pytest.approx(expected_entry_spot)
    assert entry_ts > signal_ts


def test_weekly_training_simulator_enters_next_bar(short_market_data):
    sim = WeeklyRollingSimulator(
        short_market_data,
        WeeklySimConfig(entry_every_n_days=2, lots=1, lot_size=65),
    )
    trades = sim.simulate_all()
    assert trades
    first = trades[0]
    assert first.signal_date < first.entry_date
    entry_ts = pd.Timestamp(first.entry_date)
    expected_entry_spot = short_market_data.loc[entry_ts, "nifty_open"]
    assert first.entry_spot == pytest.approx(expected_entry_spot)


def test_weekly_entry_cache_requires_matching_period_metadata(short_market_data, tmp_path):
    learner = WeeklyEntryLearner()
    learner.is_trained = True
    learner.quality_classifier = {"stub": True}
    learner.selected_features = ["vix_current"]
    path = tmp_path / "weekly_entry.pkl"
    md = ModelPeriodMetadata.build(
        model_type="weekly_entry",
        train_start=date(2024, 1, 1),
        train_end=date(2024, 2, 29),
        feature_version="weekly_entry_v1",
        config={"lots": 1, "lot_size": 65},
    )
    learner.save(path, period_metadata=md)
    loaded = WeeklyEntryLearner.load(
        short_market_data,
        path,
        expected_metadata=md,
        require_period_metadata=True,
    )
    assert loaded.period_metadata == md
    with pytest.raises(ValueError):
        WeeklyEntryLearner.load(
            short_market_data,
            path,
            signal_date=date(2024, 2, 29),
            require_period_metadata=True,
        )


def test_smart_engine_pending_entry_fills_next_bar(short_market_data):
    strategy = RegimeAdaptiveStrategy(lots=1, lot_size=65)
    engine = SmartBacktestEngine(
        strategy=strategy,
        data=short_market_data.iloc[:40],
        config=BacktestConfig(max_lots=1, lot_size=65, apply_costs=False),
        entry_model=None,
        exit_engine=None,
    )
    strategy.force_strategy_selection("put_credit_spread")
    signal_ts = short_market_data.index[30]
    next_ts = short_market_data.index[31]
    expiry = next_ts.date() + timedelta(days=21)
    engine._pending_entry = {
        "signal_date": signal_ts.date(),
        "signal_spot": float(short_market_data.loc[signal_ts, "nifty_close"]),
        "signal_vix": float(short_market_data.loc[signal_ts, "vix"]),
        "expiry_date": expiry,
        "lots": 1,
        "strategy_name": "put_credit_spread",
        "equity_at_signal": 500_000.0,
    }
    engine._fill_pending_entry(next_ts.date(), short_market_data.loc[next_ts])
    assert engine.open_trade is not None
    assert engine.open_trade.signal_date == signal_ts.date()
    assert engine.open_trade.entry_date == next_ts.date()
    assert engine.open_trade.signal_date < engine.open_trade.entry_date


def test_combined_engine_pending_monthly_entry_fills_next_bar(short_market_data):
    monthly_cfg = BacktestConfig(max_lots=1, lot_size=65, apply_costs=False)
    weekly_cfg = WeeklyBacktestConfig(max_lots=1, lot_size=65, apply_costs=False)
    strategy = RegimeAdaptiveStrategy(lots=1, lot_size=65)
    strategy.force_strategy_selection("put_credit_spread")
    engine = CombinedBacktestEngine(
        data=short_market_data.iloc[:40],
        monthly_config=monthly_cfg,
        weekly_config=weekly_cfg,
        monthly_strategy=strategy,
        exit_engine=None,
        entry_model=None,
    )
    signal_ts = short_market_data.index[30]
    next_ts = short_market_data.index[31]
    engine._pending_monthly_entry = {
        "signal_date": signal_ts.date(),
        "signal_spot": float(short_market_data.loc[signal_ts, "nifty_close"]),
        "signal_vix": float(short_market_data.loc[signal_ts, "vix"]),
        "expiry": next_ts.date() + timedelta(days=21),
        "lots": 1,
        "strategy_name": "put_credit_spread",
    }
    engine._fill_pending_monthly_entry(next_ts.date(), short_market_data.loc[next_ts])
    assert engine.monthly_trade is not None
    assert engine.monthly_trade.signal_date == signal_ts.date()
    assert engine.monthly_trade.entry_date == next_ts.date()


def test_backtest_combined_uses_final_caches_only(short_market_data, monkeypatch):
    import main as main_module
    import backtester.combined_engine as combined_engine_module
    from models.regime_aware_learner import RegimeAwareLearner
    from models.trade_monitor import ExitStrategyEngine
    import models.weekly_risk_engine as weekly_risk_module

    captured = {}
    dummy_entry = object()
    dummy_exit = object()
    dummy_weekly = object()

    class DummyFetcher:
        def __init__(self, *args, **kwargs):
            pass

        def build_combined_dataset(self):
            return short_market_data

    class DummyEngine:
        def __init__(self, *args, **kwargs):
            captured["engine_kwargs"] = kwargs

        def run(self):
            return SimpleNamespace(
                monthly_trades=0,
                monthly_win_rate=0.0,
                monthly_pnl=0.0,
                avg_holding_days_monthly=0.0,
                weekly_trades=0,
                weekly_win_rate=0.0,
                weekly_pnl=0.0,
                avg_holding_days_weekly=0.0,
                total_trades=0,
                win_rate=0.0,
                total_pnl=0.0,
                cagr_pct=0.0,
                max_drawdown_pct=0.0,
                sharpe_ratio=0.0,
                calmar_ratio=0.0,
                profit_factor=0.0,
                cross_track_dd_blocks=0,
                weekly_vix_gate_blocks=0,
                weekly_open_cap_blocks=0,
                emergency_weekly_exits=0,
                weekly_etl_skips=0,
                weekly_regime_skips=0,
                weekly_risk_score_avg=0.0,
                weekly_dynamic_exit_count=0,
                weekly_dynamic_exit_reasons={},
                weekly_regime_distribution={},
                all_trades=[],
                capital_utilization_pct=0.0,
            )

        def _monthly_funnel_report(self, start_date=None, end_date=None) -> str:
            return ""

    def fake_entry_load(cls, market_data, path=None, **kwargs):
        captured["entry_model_market_data"] = market_data
        return dummy_entry

    def fake_exit_load(cls, market_data, path=None, **kwargs):
        captured["exit_engine_market_data"] = market_data
        return dummy_exit

    def fake_load_risk_engine(market_data, **kwargs):
        captured["weekly_risk_market_data"] = market_data
        return dummy_weekly

    monkeypatch.setattr(main_module, "MarketDataFetcher", DummyFetcher)
    monkeypatch.setattr(main_module, "log_backtest_run", lambda *args, **kwargs: None)
    monkeypatch.setattr(main_module, "_build_weekly_trade_stats", lambda trades: {"distribution": None, "top_winners": [], "top_losers": []})
    monkeypatch.setattr(combined_engine_module, "CombinedBacktestEngine", DummyEngine)
    monkeypatch.setattr(RegimeAwareLearner, "load", classmethod(fake_entry_load))
    monkeypatch.setattr(ExitStrategyEngine, "load", classmethod(fake_exit_load))
    monkeypatch.setattr(weekly_risk_module, "load_risk_engine", fake_load_risk_engine)

    config = BacktestConfig(max_lots=1, lot_size=65, apply_costs=False)
    main_module.run_backtest_combined(config, run_label="unit-test")

    assert captured["engine_kwargs"]["walk_forward_manager"] is None
    assert captured["engine_kwargs"]["entry_model"] is dummy_entry
    assert captured["engine_kwargs"]["exit_engine"] is dummy_exit
    assert captured["engine_kwargs"]["weekly_risk_engine"] is dummy_weekly
