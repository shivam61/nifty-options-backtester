"""
Period-aware walk-forward model training and cache management.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd

from backtester.rolling_simulator import RollingWindowSimulator, SimConfig
from backtester.weekly_simulator import WeeklyRollingSimulator, WeeklySimConfig
from config import BacktestConfig, WeeklyBacktestConfig
from models.cache_utils import ModelPeriodMetadata
from models.regime_aware_learner import RegimeAwareLearner
from models.strategy_evolver import StrategyEvolver
from models.trade_monitor import ExitStrategyEngine
from models.weekly_entry_learner import WeeklyEntryLearner
from models.weekly_risk_engine import WeeklyRiskEngine, load_risk_engine, save_risk_engine
from training_config import TRAINING_FLOW


WALK_FORWARD_CACHE_DIR = Path(__file__).parent.parent / "data" / ".cache" / "walk_forward"


@dataclass(frozen=True)
class WalkForwardWindow:
    period_index: int
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp


@dataclass
class WalkForwardBundle:
    window: WalkForwardWindow
    entry_model: Optional[RegimeAwareLearner] = None
    exit_engine: Optional[ExitStrategyEngine] = None
    weekly_entry_model: Optional[WeeklyEntryLearner] = None
    weekly_risk_engine: Optional[WeeklyRiskEngine] = None

    def assert_usable_for(self, signal_date) -> None:
        for model in (self.entry_model, self.exit_engine, self.weekly_entry_model):
            md = getattr(model, "period_metadata", None)
            if md is not None:
                md.assert_usable_for(signal_date)


class WalkForwardManager:
    """
    Expanding-window retraining with period-aware caches.

    Every OOS period uses models trained only on data strictly before that period.
    When ``train_on_cache_miss`` is False, the manager becomes inference-only:
    it will load cached models if present and otherwise return ``None``.
    """

    def __init__(
        self,
        data: pd.DataFrame,
        *,
        monthly_config: Optional[BacktestConfig] = None,
        weekly_config: Optional[WeeklyBacktestConfig] = None,
        initial_train_frac: float = 0.60,
        retrain_interval_bars: int = 21,
        include_monthly: bool = True,
        include_weekly_entry: bool = False,
        include_weekly_risk: bool = False,
        train_on_cache_miss: bool = True,
        cache_dir: Path = WALK_FORWARD_CACHE_DIR,
    ):
        self.data = data
        self.monthly_config = monthly_config or BacktestConfig()
        self.weekly_config = weekly_config or WeeklyBacktestConfig()
        self.initial_train_frac = initial_train_frac
        self.retrain_interval_bars = max(1, retrain_interval_bars)
        self.include_monthly = include_monthly
        self.include_weekly_entry = include_weekly_entry
        self.include_weekly_risk = include_weekly_risk
        self.train_on_cache_miss = train_on_cache_miss
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self.train_cutoff = int(len(self.data) * self.initial_train_frac)
        if self.train_cutoff < 30:
            raise ValueError("Walk-forward training window is too short.")
        self.windows = self._build_windows()
        self._bundles: dict[int, WalkForwardBundle] = {}

    def _build_windows(self) -> list[WalkForwardWindow]:
        windows = []
        start_idx = self.train_cutoff
        period_index = 0
        while start_idx < len(self.data):
            end_idx = min(start_idx + self.retrain_interval_bars - 1, len(self.data) - 1)
            train_end_idx = start_idx - 1
            windows.append(WalkForwardWindow(
                period_index=period_index,
                train_start=self.data.index[0],
                train_end=self.data.index[train_end_idx],
                test_start=self.data.index[start_idx],
                test_end=self.data.index[end_idx],
            ))
            start_idx = end_idx + 1
            period_index += 1
        return windows

    def get_bundle_for_date(self, signal_date) -> WalkForwardBundle:
        ts = pd.Timestamp(signal_date)
        for window in self.windows:
            if window.test_start <= ts <= window.test_end:
                bundle = self._ensure_bundle(window)
                bundle.assert_usable_for(ts.date() if hasattr(ts, "date") else ts)
                return bundle
        raise ValueError(f"No walk-forward bundle covers signal date {ts}.")

    def _window_train_data(self, window: WalkForwardWindow) -> pd.DataFrame:
        return self.data.loc[:window.train_end].copy()

    def _metadata(self, *, model_type: str, feature_version: str, window: WalkForwardWindow, config: dict) -> ModelPeriodMetadata:
        return ModelPeriodMetadata.build(
            model_type=model_type,
            train_start=window.train_start.date(),
            train_end=window.train_end.date(),
            feature_version=feature_version,
            config=config,
        )

    def _cache_path(self, metadata: ModelPeriodMetadata, suffix: str = ".pkl") -> Path:
        filename = (
            f"{metadata.model_type}_{metadata.train_start}_{metadata.train_end}_"
            f"{metadata.feature_version}_{metadata.config_hash}_{metadata.cache_key}{suffix}"
        )
        return self.cache_dir / filename

    def _ensure_bundle(self, window: WalkForwardWindow) -> WalkForwardBundle:
        existing = self._bundles.get(window.period_index)
        if existing is not None:
            return existing

        train_data = self._window_train_data(window)
        bundle = WalkForwardBundle(window=window)

        if self.include_monthly:
            entry_md = self._metadata(
                model_type="monthly_entry",
                feature_version=self.monthly_config.entry_model_version,
                window=window,
                config={
                    "lots": self.monthly_config.max_lots,
                    "lot_size": self.monthly_config.lot_size,
                    "entry_every_n_days": TRAINING_FLOW.monthly_entry_every_n_days,
                },
            )
            bundle.entry_model = self._load_or_train_monthly_entry(train_data, entry_md)

            exit_md = self._metadata(
                model_type="monthly_exit",
                feature_version="exit_v1",
                window=window,
                config={
                    "lots": self.monthly_config.max_lots,
                    "lot_size": self.monthly_config.lot_size,
                    "entry_every_n_days": TRAINING_FLOW.monthly_exit_entry_every_n_days,
                },
            )
            bundle.exit_engine = self._load_or_train_monthly_exit(train_data, exit_md)

        if self.include_weekly_entry:
            weekly_md = self._metadata(
                model_type="weekly_entry",
                feature_version="weekly_entry_v1",
                window=window,
                config={
                    "lots": self.weekly_config.max_lots,
                    "lot_size": self.weekly_config.lot_size,
                    "entry_every_n_days": TRAINING_FLOW.weekly_entry_every_n_days,
                    "min_dte": self.weekly_config.min_dte_entry,
                    "max_dte": self.weekly_config.max_dte_entry,
                },
            )
            bundle.weekly_entry_model = self._load_or_train_weekly_entry(train_data, weekly_md)

        if self.include_weekly_risk:
            risk_md = self._metadata(
                model_type="weekly_risk",
                feature_version="weekly_risk_v2",
                window=window,
                config={
                    "lots": self.weekly_config.max_lots,
                    "lot_size": self.weekly_config.lot_size,
                    "entry_every_n_days": TRAINING_FLOW.weekly_entry_every_n_days,
                },
            )
            bundle.weekly_risk_engine = self._load_or_train_weekly_risk(train_data, risk_md)

        self._bundles[window.period_index] = bundle
        return bundle

    def _load_or_train_monthly_entry(self, train_data: pd.DataFrame, metadata: ModelPeriodMetadata) -> Optional[RegimeAwareLearner]:
        path = self._cache_path(metadata)
        if path.exists():
            return RegimeAwareLearner.load(
                train_data,
                path,
                expected_metadata=metadata,
                require_period_metadata=True,
            )
        if not self.train_on_cache_miss:
            try:
                return RegimeAwareLearner.load(train_data)
            except FileNotFoundError:
                return None
        sim = RollingWindowSimulator(
            train_data,
            SimConfig(
                lots=self.monthly_config.max_lots,
                lot_size=self.monthly_config.lot_size,
                entry_every_n_days=TRAINING_FLOW.monthly_entry_every_n_days,
            ),
        )
        trades = sim.simulate_all()
        learner = RegimeAwareLearner(model_version=self.monthly_config.entry_model_version)
        learner.train(trades, train_data, verbose=False)
        learner.save(path, period_metadata=metadata)
        return learner

    def _load_or_train_monthly_exit(self, train_data: pd.DataFrame, metadata: ModelPeriodMetadata) -> Optional[ExitStrategyEngine]:
        path = self._cache_path(metadata)
        if path.exists():
            return ExitStrategyEngine.load(
                train_data,
                path,
                expected_metadata=metadata,
                require_period_metadata=True,
            )
        if not self.train_on_cache_miss:
            try:
                return ExitStrategyEngine.load(train_data)
            except FileNotFoundError:
                return None
        evolver = StrategyEvolver(
            train_data,
            lots=self.monthly_config.max_lots,
            lot_size=self.monthly_config.lot_size,
        )
        evolved = evolver.evolve(
            target=TRAINING_FLOW.evolve_target,
            entry_every_n_days=TRAINING_FLOW.monthly_exit_entry_every_n_days,
            verbose=False,
            save_cache=False,
        )
        engine = ExitStrategyEngine(train_data)
        engine.train_from_simulations(evolved, verbose=False)
        engine.save(path, period_metadata=metadata)
        return engine

    def _load_or_train_weekly_entry(self, train_data: pd.DataFrame, metadata: ModelPeriodMetadata) -> Optional[WeeklyEntryLearner]:
        path = self._cache_path(metadata)
        if path.exists():
            return WeeklyEntryLearner.load(
                train_data,
                path,
                expected_metadata=metadata,
                require_period_metadata=True,
            )
        if not self.train_on_cache_miss:
            try:
                return WeeklyEntryLearner.load(train_data)
            except FileNotFoundError:
                return None
        sim = WeeklyRollingSimulator(
            train_data,
            WeeklySimConfig(
                lots=self.weekly_config.max_lots,
                lot_size=self.weekly_config.lot_size,
                entry_every_n_days=TRAINING_FLOW.weekly_entry_every_n_days,
                min_dte=self.weekly_config.min_dte_entry,
                max_dte=self.weekly_config.max_dte_entry,
            ),
        )
        trades = sim.simulate_all()
        learner = WeeklyEntryLearner()
        learner.train(trades, train_data, verbose=False)
        learner.save(path, period_metadata=metadata)
        return learner

    def _load_or_train_weekly_risk(self, train_data: pd.DataFrame, metadata: ModelPeriodMetadata) -> Optional[WeeklyRiskEngine]:
        path = self._cache_path(metadata)
        if path.exists():
            return load_risk_engine(train_data, path=path, expected_metadata=metadata, require_period_metadata=True)
        if not self.train_on_cache_miss:
            try:
                return load_risk_engine(train_data)
            except FileNotFoundError:
                return None
        sim = WeeklyRollingSimulator(
            train_data,
            WeeklySimConfig(
                lots=self.weekly_config.max_lots,
                lot_size=self.weekly_config.lot_size,
                entry_every_n_days=TRAINING_FLOW.weekly_entry_every_n_days,
            ),
        )
        trades = sim.simulate_all()
        engine = WeeklyRiskEngine()
        engine.fit(train_data, trades, verbose=False)
        save_risk_engine(engine, path=path, period_metadata=metadata)
        return engine
