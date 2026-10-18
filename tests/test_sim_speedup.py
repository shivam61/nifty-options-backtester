"""
Regression tests for the layered-training simulation speedups.

Covers:
  - RollingWindowSimulator.simulate_all(entry_idx_range=...) chunking (exact equality)
  - models.layered_evolve._simulate_stage window path vs. simulate-all-then-filter
  - NIFTY_SIM_JOBS parallel path (order-preserving, equal to serial)
  - NIFTY_SIM_WINDOW=0 escape hatch and defaults
  - optional end-to-end run_layered_training comparison (see test_e2e_* below)

All data is synthetic; no network, no cache writes.
"""

import dataclasses
import datetime as dt
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from backtester.rolling_simulator import RollingWindowSimulator, SimConfig
from models import layered_evolve
from models.layered_evolve import (
    _filter_trades_in_window,
    _simulate_stage,
    _entry_index_lower_bound,
)
from training_config import TRAINING_FLOW


def _make_frame(n: int, seed: int = 7) -> pd.DataFrame:
    """Synthetic frame with the columns the rolling simulator reads (VIX 13-22 swing)."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2018-01-01", periods=n)
    spot = 18000.0 * (1 + rng.normal(0, 0.006, n)).cumprod()
    vix = 13.0 + 9.0 * (np.sin(np.linspace(0, 8 * np.pi, n)) + 1) / 2
    return pd.DataFrame({
        "nifty_close": spot,
        "nifty_open": spot * (1 + rng.normal(0, 0.001, n)),
        "nifty_high": spot * (1 + np.abs(rng.normal(0, 0.005, n))),
        "nifty_low": spot * (1 - np.abs(rng.normal(0, 0.005, n))),
        "vix": vix,
    }, index=idx)


def _sim_cfg() -> SimConfig:
    return SimConfig(entry_every_n_days=TRAINING_FLOW.layered_entry_every_n_days,
                     lots=2, lot_size=65)


# One config per strategy family.  A full simulate_all over 26 configs costs
# ~0.05 s per row, so the window/stage tests use this subset (the restriction
# logic does not depend on how many configs run).  Parallel tests keep the full
# list because loky workers re-import the module and would not see a patch.
_SUBSET_TYPES = ("vertical", "iron_condor", "iron_butterfly", "bwb",
                 "calendar", "ratio_put", "jade_lizard")


@pytest.fixture
def small_configs(monkeypatch):
    from backtester import rolling_simulator as rs
    picked, seen = [], set()
    for cfg in rs.STRATEGY_CONFIGS:
        if cfg["type"] in _SUBSET_TYPES and cfg["type"] not in seen:
            picked.append(cfg)
            seen.add(cfg["type"])
    monkeypatch.setattr(rs, "STRATEGY_CONFIGS", picked)
    return picked


def _as_dicts(trades) -> list:
    return [dataclasses.asdict(t) for t in trades]


def _stage_ends(n: int) -> list[int]:
    """Row positions of stage ends at roughly 0.6N, 0.73N, 0.87N and N."""
    return [int(n * 0.6), int(n * 0.73), int(n * 0.87), n - 1]


def _window_stages(data: pd.DataFrame):
    """Yield (stage_data, prev_end, stage_end) exactly as run_layered_training chains them."""
    prev_end = pd.Timestamp(data.index[0]) - pd.Timedelta(days=1)
    for end_pos in _stage_ends(len(data)):
        stage_end = pd.Timestamp(data.index[end_pos])
        yield data.loc[:stage_end].copy(), prev_end, stage_end
        prev_end = stage_end


# ---------------------------------------------------------------------------
# 1. simulate_all(entry_idx_range=...) chunking
# ---------------------------------------------------------------------------

class TestEntryIdxRangeChunking:

    @staticmethod
    def _chunk_and_compare(data, cuts):
        full = _as_dicts(RollingWindowSimulator(data, _sim_cfg()).simulate_all())
        assert full, "fixture should produce trades"
        chunked = []
        for a, b in zip(cuts[:-1], cuts[1:]):
            part = RollingWindowSimulator(data, _sim_cfg()).simulate_all(
                entry_idx_range=range(a, b)
            )
            chunked.extend(_as_dicts(part))
        assert chunked == full

    def test_chunked_equals_full_all_configs(self):
        """Full 26-config list on a 400-day frame, uneven split with a tiny leading chunk."""
        self._chunk_and_compare(_make_frame(400), [0, 3, 50, 51, 177, 301, 400])

    def test_chunked_equals_full_600_days_subset(self, small_configs):
        """600-day frame, many contiguous splits (incl. empty and single-bar chunks)."""
        self._chunk_and_compare(_make_frame(600), [0, 50, 51, 52, 100, 101, 250, 251, 399, 600, 600])

    def test_none_range_is_default(self, small_configs):
        data = _make_frame(400)
        a = _as_dicts(RollingWindowSimulator(data, _sim_cfg()).simulate_all())
        b = _as_dicts(RollingWindowSimulator(data, _sim_cfg()).simulate_all(entry_idx_range=None))
        assert a == b

    def test_range_below_warmup_is_clipped(self, small_configs):
        data = _make_frame(300)
        full = _as_dicts(RollingWindowSimulator(data, _sim_cfg()).simulate_all())
        part = _as_dicts(RollingWindowSimulator(data, _sim_cfg()).simulate_all(
            entry_idx_range=range(0, 300)
        ))
        assert part == full

    def test_range_must_be_unit_step(self):
        data = _make_frame(200)
        with pytest.raises(ValueError):
            RollingWindowSimulator(data, _sim_cfg()).simulate_all(entry_idx_range=range(50, 200, 2))


# ---------------------------------------------------------------------------
# 2. staged window restriction == simulate-all-then-filter
# ---------------------------------------------------------------------------

class TestStageWindowEquality:

    def test_window_path_equals_filter_for_every_stage(self, monkeypatch, small_configs):
        monkeypatch.delenv("NIFTY_SIM_WINDOW", raising=False)
        monkeypatch.delenv("NIFTY_SIM_JOBS", raising=False)
        data = _make_frame(500)
        n_stages_with_trades = 0
        for stage_data, prev_end, stage_end in _window_stages(data):
            full = RollingWindowSimulator(stage_data, _sim_cfg()).simulate_all()
            expected = _filter_trades_in_window(full, prev_end, stage_end)
            got = _simulate_stage(stage_data, _sim_cfg(), prev_end, stage_end)
            assert _as_dicts(got) == _as_dicts(expected), f"mismatch at stage end {stage_end.date()}"
            n_stages_with_trades += bool(expected)
        assert n_stages_with_trades == len(_stage_ends(500))

    def test_hidden_gap_before_stage_end_is_preserved(self, monkeypatch, small_configs):
        """Entries whose fill row falls in the last 21 rows of a stage never become samples."""
        monkeypatch.delenv("NIFTY_SIM_WINDOW", raising=False)
        monkeypatch.delenv("NIFTY_SIM_JOBS", raising=False)
        data = _make_frame(500)
        for stage_data, prev_end, stage_end in list(_window_stages(data))[:-1]:
            got = _simulate_stage(stage_data, _sim_cfg(), prev_end, stage_end)
            # remaining_days = n - entry_idx - 1 must be >= hold_days + 1, so the
            # latest fill row that can be simulated is index[n - 22].
            last_allowed = stage_data.index[len(stage_data) - 22]
            for t in got:
                assert pd.Timestamp(t.entry_date) <= last_allowed

    def test_lower_bound_is_conservative(self, small_configs):
        """No row below the bound may produce a trade inside the window."""
        data = _make_frame(500)
        for stage_data, prev_end, stage_end in _window_stages(data):
            lo = _entry_index_lower_bound(stage_data.index, prev_end)
            full = RollingWindowSimulator(stage_data, _sim_cfg()).simulate_all()
            below = [t for t in full
                     if stage_data.index.get_loc(pd.Timestamp(t.entry_date)) - 1 < lo]
            assert _filter_trades_in_window(below, prev_end, stage_end) == []


# ---------------------------------------------------------------------------
# 3. parallel == serial
# ---------------------------------------------------------------------------

class TestParallelEqualsSerial:

    def test_jobs2_equals_jobs1(self, monkeypatch):
        """Full config list (loky workers cannot see monkeypatched configs); last stage only."""
        monkeypatch.delenv("NIFTY_SIM_WINDOW", raising=False)
        data = _make_frame(300)
        stage_data, prev_end, stage_end = list(_window_stages(data))[-1]
        monkeypatch.setenv("NIFTY_SIM_JOBS", "1")
        serial = _simulate_stage(stage_data, _sim_cfg(), prev_end, stage_end)
        monkeypatch.setenv("NIFTY_SIM_JOBS", "2")
        parallel = _simulate_stage(stage_data, _sim_cfg(), prev_end, stage_end)
        assert serial, "fixture should produce trades"
        assert _as_dicts(parallel) == _as_dicts(serial)

    def test_jobs_env_parsing(self, monkeypatch):
        monkeypatch.setenv("NIFTY_SIM_JOBS", "3")
        assert layered_evolve._sim_jobs() == 3
        monkeypatch.setenv("NIFTY_SIM_JOBS", "100")
        assert layered_evolve._sim_jobs() == 8
        monkeypatch.setenv("NIFTY_SIM_JOBS", "0")
        assert 1 <= layered_evolve._sim_jobs() <= 8
        monkeypatch.delenv("NIFTY_SIM_JOBS")
        assert layered_evolve._sim_jobs() == 1


# ---------------------------------------------------------------------------
# 4. escape hatch and 5. defaults
# ---------------------------------------------------------------------------

class TestSwitches:

    def test_window_zero_uses_old_path_and_matches_window_path(self, monkeypatch, small_configs):
        monkeypatch.delenv("NIFTY_SIM_JOBS", raising=False)
        data = _make_frame(500)
        stage_data, prev_end, stage_end = list(_window_stages(data))[-1]

        monkeypatch.setenv("NIFTY_SIM_WINDOW", "0")
        with patch.object(RollingWindowSimulator, "simulate_all",
                          autospec=True, side_effect=RollingWindowSimulator.simulate_all) as spy:
            old = _simulate_stage(stage_data, _sim_cfg(), prev_end, stage_end)
        assert spy.call_count == 1
        assert spy.call_args.kwargs.get("entry_idx_range") is None
        assert len(spy.call_args.args) == 1  # only self

        monkeypatch.setenv("NIFTY_SIM_WINDOW", "1")
        with patch.object(RollingWindowSimulator, "simulate_all",
                          autospec=True, side_effect=RollingWindowSimulator.simulate_all) as spy:
            new = _simulate_stage(stage_data, _sim_cfg(), prev_end, stage_end)
        assert spy.call_args.kwargs.get("entry_idx_range") is not None

        assert _as_dicts(old) == _as_dicts(new)

    def test_defaults_are_window_serial(self, monkeypatch, small_configs):
        monkeypatch.delenv("NIFTY_SIM_WINDOW", raising=False)
        monkeypatch.delenv("NIFTY_SIM_JOBS", raising=False)
        data = _make_frame(500)
        stage_data, prev_end, stage_end = list(_window_stages(data))[1]
        with patch.object(RollingWindowSimulator, "simulate_all",
                          autospec=True, side_effect=RollingWindowSimulator.simulate_all) as spy:
            default = _simulate_stage(stage_data, _sim_cfg(), prev_end, stage_end)
        assert spy.call_count == 1  # serial: one call, not per-chunk
        assert spy.call_args.kwargs.get("entry_idx_range") is not None
        assert layered_evolve._sim_window_enabled() is True
        assert layered_evolve._sim_jobs() == 1
        expected = _filter_trades_in_window(
            RollingWindowSimulator(stage_data, _sim_cfg()).simulate_all(), prev_end, stage_end
        )
        assert _as_dicts(default) == _as_dicts(expected)


# ---------------------------------------------------------------------------
# 6. end-to-end run_layered_training comparison
# ---------------------------------------------------------------------------

def _e2e_frame(n: int = 420):
    """
    Full-column frame for run_layered_training.  Built from conftest's synthetic
    market generator, which carries the FeatureExtractor inputs.  Returns None
    if that generator cannot supply what the pipeline needs.
    """
    from tests.conftest import _make_market_data
    return _make_market_data(n_days=n, start_date="2018-01-01")


def _run_e2e(monkeypatch, tmp_path, window: str, jobs: str):
    from config import BacktestConfig
    from models.strategy_evolver import EvolvedStrategy

    monkeypatch.setenv("NIFTY_SIM_WINDOW", window)
    monkeypatch.setenv("NIFTY_SIM_JOBS", jobs)

    # Keep the walk-forward cache out of the repository's data/.cache.
    OrigWF = layered_evolve.WalkForwardManager

    class _WF(OrigWF):
        def __init__(self, *a, **kw):
            kw.setdefault("cache_dir", tmp_path / "wf")
            super().__init__(*a, **kw)

    monkeypatch.setattr(layered_evolve, "WalkForwardManager", _WF)
    monkeypatch.setattr(layered_evolve, "load_actual_training_trades", lambda: ([], 0))

    evolved = {
        "LOW_VOL": EvolvedStrategy(
            name="evolved_put_LOW_VOL", direction="put", sd=1.0, spread_width=500,
            profit_target_pct=50.0, stop_loss_pct=60.0, hold_days=21,
            min_vix=0, max_vix=14, sharpe=1.0, total_pnl=1000.0,
            win_rate=0.6, num_trades=50, max_drawdown=-0.05, avg_pnl=20.0,
        ),
    }
    return layered_evolve.run_layered_training(
        data=_e2e_frame(), config=BacktestConfig(), evolved_strategies=evolved, verbose=False,
    )


def _stage_signature(artifacts):
    return [
        (s.stage_index, str(s.stage_end), s.new_sim_trades, s.new_actual_trades,
         s.cumulative_trades, s.new_weekly_trades, s.cumulative_weekly_trades,
         s.exit_train_trades)
        for s in artifacts.stage_stats
    ]


def test_e2e_run_layered_training_equal_across_switches(monkeypatch, tmp_path):
    try:
        base = _run_e2e(monkeypatch, tmp_path, window="0", jobs="1")
    except (RuntimeError, KeyError, ValueError) as exc:
        pytest.skip(f"synthetic frame lacks full feature pipeline inputs: {exc!r}")

    variants = [("1", "1"), ("1", "2")]
    base_entry = _as_dicts(base.entry_training_trades)
    base_weekly = _as_dicts(base.weekly_training_trades)
    base_stats = _stage_signature(base)
    assert base_entry, "e2e fixture should produce entry training trades"
    for window, jobs in variants:
        other = _run_e2e(monkeypatch, tmp_path, window=window, jobs=jobs)
        assert _as_dicts(other.entry_training_trades) == base_entry, (window, jobs)
        assert _as_dicts(other.weekly_training_trades) == base_weekly, (window, jobs)
        assert _stage_signature(other) == base_stats, (window, jobs)
