"""
Layered evolve-time retraining pipeline.

This module keeps model training out of backtest/signal flows.
It stages training over expanding walk-forward windows, trains entry/exit/risk
models incrementally, and saves only the final artifacts.

Speed switches (environment variables, read at call time; results are identical
across all settings):

- NIFTY_SIM_WINDOW (default "1"): each stage's entry simulation only visits the
  entry bars whose trade can land in that stage's (prev_end, stage_end] window.
  "0" restores the original simulate-everything-then-filter path.
- NIFTY_SIM_JOBS (default "1"): number of worker processes for the entry
  simulation of a stage. "0" or negative = os.cpu_count(); capped at 8.
  Chunk results are concatenated in chunk order, so output order is unchanged.
"""

from __future__ import annotations

import contextlib
import os
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Optional

import numpy as np
import pandas as pd
from joblib import Parallel, delayed

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


def _sim_window_enabled() -> bool:
    return os.environ.get("NIFTY_SIM_WINDOW", "1").strip() != "0"


def _sim_jobs() -> int:
    raw = os.environ.get("NIFTY_SIM_JOBS", "1").strip() or "1"
    jobs = int(raw)
    if jobs <= 0:
        jobs = os.cpu_count() or 1
    return max(1, min(jobs, 8))


def _entry_index_lower_bound(index: pd.Index, prev_end) -> int:
    """
    Smallest entry row that can produce a trade inside (prev_end, stage_end].

    Every simulator fills at row entry_idx + 1 and reports that row's date as
    entry_date (a date, i.e. at or before the row timestamp).  Rows whose fill
    row is <= prev_end therefore fail _filter_trades_in_window and are skipped.
    The bound is conservative (one row earlier than needed) and the existing
    window filter still runs afterwards, so the bound never changes the output.
    """
    if not index.is_monotonic_increasing:
        return 0
    first_fill = int(index.searchsorted(pd.Timestamp(prev_end), side="right"))
    return max(0, first_fill - 1)


def _log_progress(t0: float, msg: str) -> None:
    print(f"    [+{time.monotonic() - t0:8.1f}s] {msg}", flush=True)


def _simulate_entry_chunk(stage_data: pd.DataFrame, sim_cfg: SimConfig,
                          chunk_id: int, lo: int, hi: int) -> tuple[int, list]:
    """Worker entry point for parallel entry simulation (module-level for pickling)."""
    try:
        from threadpoolctl import threadpool_limits
        limiter = threadpool_limits(limits=1)
    except ImportError:  # pragma: no cover - threadpoolctl ships with scikit-learn
        limiter = contextlib.nullcontext()
    with limiter:
        trades = RollingWindowSimulator(stage_data, config=sim_cfg).simulate_all(
            entry_idx_range=range(lo, hi)
        )
    return chunk_id, trades


def _simulate_entry_chunks_parallel(
    stage_data: pd.DataFrame,
    sim_cfg: SimConfig,
    lo: int,
    hi: int,
    jobs: int,
    log: Optional[Callable[[str], None]],
) -> list:
    n_chunks = min(4 * jobs, hi - lo)
    if n_chunks <= 0:
        return []
    bounds = np.linspace(lo, hi, n_chunks + 1).astype(int)
    chunks = [
        (int(bounds[k]), int(bounds[k + 1]))
        for k in range(n_chunks)
        if bounds[k + 1] > bounds[k]
    ]
    slots: list[Optional[list]] = [None] * len(chunks)
    done = 0
    results = Parallel(n_jobs=jobs, backend="loky", return_as="generator_unordered")(
        delayed(_simulate_entry_chunk)(stage_data, sim_cfg, k, a, b)
        for k, (a, b) in enumerate(chunks)
    )
    for chunk_id, trades in results:
        slots[chunk_id] = trades
        done += 1
        if log is not None:
            a, b = chunks[chunk_id]
            log(f"entry sim chunk {done}/{len(chunks)} done: rows [{a}, {b}) -> {len(trades)} trades")
    # Concatenate in chunk order so the final list equals the serial list exactly.
    merged: list = []
    for trades in slots:
        merged.extend(trades or [])
    return merged


def _simulate_stage(
    stage_data: pd.DataFrame,
    sim_cfg: SimConfig,
    prev_end,
    stage_end,
    log: Optional[Callable[[str], None]] = None,
) -> list:
    """
    Entry-simulation trades for one stage whose entry falls in (prev_end, stage_end].

    Window mode (NIFTY_SIM_WINDOW != "0") only simulates entry bars from the
    window's lower bound onward; the skip rules still use len(stage_data), so the
    trades match simulate-everything-then-filter bit for bit.
    """
    window = _sim_window_enabled()
    jobs = _sim_jobs()
    n_rows = len(stage_data)
    lo = _entry_index_lower_bound(stage_data.index, prev_end) if window else 0

    if jobs > 1:
        raw = _simulate_entry_chunks_parallel(stage_data, sim_cfg, lo, n_rows, jobs, log)
    elif window:
        raw = RollingWindowSimulator(stage_data, config=sim_cfg).simulate_all(
            entry_idx_range=range(lo, n_rows)
        )
    else:
        raw = RollingWindowSimulator(stage_data, config=sim_cfg).simulate_all()
    return _filter_trades_in_window(raw, prev_end, stage_end)


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

    t0 = time.monotonic()
    prev_end = pd.Timestamp(data.index[0]) - pd.Timedelta(days=1)
    for i, window in enumerate(stage_windows, start=1):
        stage_end = pd.Timestamp(window.test_end)
        stage_data = data.loc[:stage_end].copy()
        if verbose:
            _log_progress(
                t0,
                f"Stage {i}/{len(stage_windows)} start: rows={len(stage_data)}, "
                f"window=({pd.Timestamp(prev_end).date()}, {stage_end.date()}]",
            )

        # Use RollingWindowSimulator so the full STRATEGY_CONFIGS (11 strategy types,
        # 26+ configs) are used for training data generation — not just evolved
        # put-credit-spread params.  Both return list[TradeResult]; fully compatible.
        # Run every eligible day (entry_every_n_days from TRAINING_FLOW) so the model
        # sees all strategy × market-condition combinations as feature rows.
        sim_t0 = time.monotonic()
        stage_new_sim = _simulate_stage(
            stage_data,
            SimConfig(
                entry_every_n_days=TRAINING_FLOW.layered_entry_every_n_days,
                lots=config.max_lots,
                lot_size=config.lot_size,
            ),
            prev_end,
            stage_end,
            log=(lambda msg: _log_progress(t0, msg)) if verbose else None,
        )
        if verbose:
            _log_progress(t0, f"entry sim: {len(stage_new_sim)} trades in "
                              f"{time.monotonic() - sim_t0:.1f}s")
        stage_new_actual = _filter_trades_in_window(actual_training_trades, prev_end, stage_end)
        cumulative_entry_trades.extend(stage_new_sim)
        cumulative_entry_trades.extend(stage_new_actual)

        entry_stats = {}
        if len(cumulative_entry_trades) >= TRAINING_FLOW.layered_min_trades:
            phase_t0 = time.monotonic()
            entry_model = RegimeAwareLearner(model_version=config.entry_model_version)
            entry_stats = entry_model.train(
                cumulative_entry_trades,
                stage_data,
                verbose=False,
            )
            if verbose:
                _log_progress(t0, f"entry train done in {time.monotonic() - phase_t0:.1f}s "
                                  f"({len(cumulative_entry_trades)} samples)")

        phase_t0 = time.monotonic()
        exit_model = ExitStrategyEngine(stage_data)
        exit_model.train_from_simulations(evolved_strategies, verbose=False)
        if verbose:
            _log_progress(t0, f"exit train done in {time.monotonic() - phase_t0:.1f}s")

        phase_t0 = time.monotonic()
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
        if verbose:
            _log_progress(t0, f"weekly sim: {len(stage_new_weekly)} trades in "
                              f"{time.monotonic() - phase_t0:.1f}s")

        weekly_risk_engine = WeeklyRiskEngine()
        weekly_stats = None
        if len(cumulative_weekly_trades) >= TRAINING_FLOW.weekly_training_min_samples:
            phase_t0 = time.monotonic()
            weekly_stats = weekly_risk_engine.fit(stage_data, cumulative_weekly_trades, verbose=False)
            if verbose:
                _log_progress(t0, f"weekly fit done in {time.monotonic() - phase_t0:.1f}s")

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
