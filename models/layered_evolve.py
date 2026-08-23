"""
Layered evolve-time retraining pipeline.

This module keeps model training out of backtest/signal flows.
It stages training over expanding walk-forward windows, trains entry/exit/risk
models incrementally, and saves only the final artifacts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd

from backtester.rolling_simulator import RollingWindowSimulator, SimConfig
from backtester.walk_forward import WalkForwardManager
from backtester.weekly_simulator import WeeklyRollingSimulator, WeeklySimConfig
from config import BacktestConfig, WeeklyBacktestConfig
from models.regime_aware_learner import RegimeAwareLearner
from models.strategy_evolver import StrategyEvolver, EvolvedStrategy
from models.trade_monitor import ExitStrategyEngine, load_actual_training_trades
from models.weekly_risk_engine import WeeklyRiskEngine
from training_config import TRAINING_FLOW


@dataclass
class LayeredTrainStage:
    stage_index: int
    stage_end: date
    new_sim_trades: int
    new_actual_trades: int
    cumulative_trades: int
    new_weekly_trades: int
    cumulative_weekly_trades: int
    entry_cv_auc: float | None = None
    exit_train_trades: int = 0
    weekly_tail_auc: float | None = None


@dataclass
class LayeredEvolveArtifacts:
    evolved_strategies: dict[str, EvolvedStrategy]
    entry_model: RegimeAwareLearner
    exit_model: ExitStrategyEngine
    weekly_risk_engine: Optional[WeeklyRiskEngine]
    stage_stats: list[LayeredTrainStage] = field(default_factory=list)
    entry_training_trades: list = field(default_factory=list)
    weekly_training_trades: list = field(default_factory=list)


def _sample_stage_windows(windows, stage_count: int) -> list:
    if not windows:
        return []
    if stage_count <= 0 or stage_count >= len(windows):
        return list(windows)
    idxs = np.linspace(0, len(windows) - 1, num=stage_count, dtype=int)
    unique = []
    seen = set()
    for idx in idxs.tolist():
        if idx not in seen:
            unique.append(windows[idx])
            seen.add(idx)
    return unique


def _trade_entry_ts(trade) -> pd.Timestamp:
    raw = getattr(trade, "entry_date", None) or getattr(trade, "signal_date", None)
    return pd.Timestamp(raw)


def _filter_trades_in_window(trades: list, start_ts: pd.Timestamp, end_ts: pd.Timestamp) -> list:
    filtered = []
    for trade in trades:
        entry_ts = _trade_entry_ts(trade)
        if start_ts < entry_ts <= end_ts:
            filtered.append(trade)
    return filtered


def run_layered_training(
    *,
    data: pd.DataFrame,
    config: BacktestConfig,
    evolved_strategies: dict[str, EvolvedStrategy],
    verbose: bool = True,
) -> LayeredEvolveArtifacts:
    """
    Train monthly entry/exit models in staged walk-forward layers.

    The strategy universe is evolved once, then the model training loop is
    repeated on progressively larger data slices.
    """
    wf = WalkForwardManager(
        data,
        monthly_config=config,
        include_monthly=False,
        train_on_cache_miss=False,
        retrain_interval_bars=TRAINING_FLOW.layered_retrain_interval_bars,
    )
    stage_windows = _sample_stage_windows(wf.windows, TRAINING_FLOW.layered_stage_count)
    if not stage_windows:
        raise ValueError("No walk-forward windows available for layered training.")

    actual_training_trades, skipped_actual_trades = load_actual_training_trades()
    if verbose:
        print(f"\n  Layered training stages: {len(stage_windows)}")
        print(f"  Actual closed trades available: {len(actual_training_trades)}"
              f"{f' (skipped {skipped_actual_trades})' if skipped_actual_trades else ''}")

    cumulative_entry_trades: list = []
    cumulative_weekly_trades: list = []
    stage_stats: list[LayeredTrainStage] = []
    entry_model: RegimeAwareLearner | None = None
    exit_model: ExitStrategyEngine | None = None
    weekly_risk_engine: WeeklyRiskEngine | None = None

    prev_end = pd.Timestamp(data.index[0]) - pd.Timedelta(days=1)
    for i, window in enumerate(stage_windows, start=1):
        stage_end = pd.Timestamp(window.test_end)
        stage_data = data.loc[:stage_end].copy()

        # Use RollingWindowSimulator so the full STRATEGY_CONFIGS (11 strategy types,
        # 26+ configs) are used for training data generation — not just evolved
        # put-credit-spread params.  Both return list[TradeResult]; fully compatible.
        # Run every eligible day (entry_every_n_days from TRAINING_FLOW) so the model
        # sees all strategy × market-condition combinations as feature rows.
        stage_sim_trades = RollingWindowSimulator(
            stage_data,
            config=SimConfig(
                entry_every_n_days=TRAINING_FLOW.layered_entry_every_n_days,
                lots=config.max_lots,
                lot_size=config.lot_size,
            ),
        ).simulate_all()
        stage_new_sim = _filter_trades_in_window(stage_sim_trades, prev_end, stage_end)
        stage_new_actual = _filter_trades_in_window(actual_training_trades, prev_end, stage_end)
        cumulative_entry_trades.extend(stage_new_sim)
        cumulative_entry_trades.extend(stage_new_actual)

        entry_stats = {}
        if len(cumulative_entry_trades) >= TRAINING_FLOW.layered_min_trades:
            entry_model = RegimeAwareLearner(model_version=config.entry_model_version)
            entry_stats = entry_model.train(
                cumulative_entry_trades,
                stage_data,
                verbose=False,
            )

        exit_model = ExitStrategyEngine(stage_data)
        exit_model.train_from_simulations(evolved_strategies, verbose=False)

        weekly_sim = WeeklyRollingSimulator(
            stage_data,
            config=WeeklySimConfig(
                lots=WeeklyBacktestConfig().max_lots,
                lot_size=WeeklyBacktestConfig().lot_size,
            ),
        )
        stage_weekly_trades = weekly_sim.simulate_all()
        stage_new_weekly = _filter_trades_in_window(stage_weekly_trades, prev_end, stage_end)
        cumulative_weekly_trades.extend(stage_new_weekly)

        weekly_risk_engine = WeeklyRiskEngine()
        weekly_stats = None
        if len(cumulative_weekly_trades) >= TRAINING_FLOW.weekly_training_min_samples:
            weekly_stats = weekly_risk_engine.fit(stage_data, cumulative_weekly_trades, verbose=False)

        stage_stats.append(
            LayeredTrainStage(
                stage_index=i,
                stage_end=stage_end.date(),
                new_sim_trades=len(stage_new_sim),
                new_actual_trades=len(stage_new_actual),
                cumulative_trades=len(cumulative_entry_trades),
                new_weekly_trades=len(stage_new_weekly),
                cumulative_weekly_trades=len(cumulative_weekly_trades),
                entry_cv_auc=float(entry_stats.get("global", {}).get("cv_auc", 0.0) or 0.0),
                exit_train_trades=len(evolved_strategies),
                weekly_tail_auc=float(weekly_stats.get("tail_risk", {}).get("cv_auc", 0.0)) if weekly_stats else None,
            )
        )

        if verbose:
            print(
                f"    Stage {i}/{len(stage_windows)} @ {stage_end.date()}: "
                f"+{len(stage_new_sim)} sim trades, +{len(stage_new_actual)} actual trades, "
                f"cumulative entry samples {len(cumulative_entry_trades)}, "
                f"entry AUC {stage_stats[-1].entry_cv_auc:.3f}"
            )

        prev_end = stage_end

    if entry_model is None or exit_model is None:
        raise RuntimeError("Layered training did not produce final models.")

    return LayeredEvolveArtifacts(
        evolved_strategies=evolved_strategies,
        entry_model=entry_model,
        exit_model=exit_model,
        weekly_risk_engine=weekly_risk_engine,
        stage_stats=stage_stats,
        entry_training_trades=cumulative_entry_trades,
        weekly_training_trades=cumulative_weekly_trades,
    )
