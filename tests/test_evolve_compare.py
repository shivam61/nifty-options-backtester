"""
Tests for the evolve-step baseline comparison (regression for KeyError: 'direction').

Covers:
- StrategyEvolver.compare_with_baseline on the mixed-type STRATEGY_CONFIGS list
- Non-vertical baseline configs are skipped instead of raising
- Vertical-only baseline metrics are unchanged (checked against the private helpers)
- main._safe_baseline_comparison never aborts the evolve pipeline

All data is synthetic and seeded; no network and no market cache.
"""

import numpy as np
import pandas as pd
import pytest

import main as main_module
from models.strategy_evolver import (
    StrategyEvolver, EvolvedStrategy, VIX_REGIMES, _is_vertical_baseline,
)
from backtester.rolling_simulator import STRATEGY_CONFIGS


def _make_regime_frame(n_rows: int = 400, seed: int = 7) -> pd.DataFrame:
    """Synthetic frame whose VIX cycles through all four regimes.

    Entries fall on every 5th row from row 50, so the VIX sequence below
    gives each regime roughly a quarter of the ~70 entries.
    """
    rng = np.random.RandomState(seed)
    dates = pd.bdate_range(start="2019-01-01", periods=n_rows)
    base_vix = np.tile([13.0, 17.0, 25.0, 35.0], n_rows // 4 + 1)[:n_rows]
    vix = base_vix + rng.normal(0, 0.5, n_rows)
    nifty = 22000.0 * np.cumprod(1 + rng.normal(0.0002, 0.01, n_rows))
    return pd.DataFrame({"nifty_close": nifty, "vix": vix}, index=dates)


def _make_evolver() -> StrategyEvolver:
    evolver = StrategyEvolver(_make_regime_frame(), lots=2, lot_size=65)
    evolver.evolved_strategies = {
        "low_vix_12_15": EvolvedStrategy(
            name="put_credit_spread", direction="put", sd=1.0, spread_width=500,
            profit_target_pct=50.0, stop_loss_pct=60.0, hold_days=21,
            min_vix=12, max_vix=15,
        ),
        "high_vix_20_30": EvolvedStrategy(
            name="put_credit_wide", direction="call", sd=0.8, spread_width=400,
            profit_target_pct=30.0, stop_loss_pct=50.0, hold_days=14,
            min_vix=20, max_vix=30,
        ),
    }
    return evolver


VERTICAL_ONLY = [c for c in STRATEGY_CONFIGS if c.get("type") == "vertical"]


class TestCompareWithBaseline:

    def test_real_mixed_config_list_does_not_raise(self):
        """Regression: STRATEGY_CONFIGS mixes types; used to raise KeyError: 'direction'."""
        evolver = _make_evolver()
        result = evolver.compare_with_baseline(STRATEGY_CONFIGS)
        assert set(result.keys()) == {"baseline", "evolved"}
        assert "low_vix_12_15" in result["evolved"]
        assert "high_vix_20_30" in result["evolved"]
        assert result["baseline"], "vertical baseline configs should produce metrics"

    def test_non_vertical_configs_are_skipped(self):
        """Adding non-vertical configs must not change the baseline result."""
        evolver = _make_evolver()
        mixed = evolver.compare_with_baseline(STRATEGY_CONFIGS)
        vertical = evolver.compare_with_baseline(VERTICAL_ONLY)
        assert mixed["baseline"] == vertical["baseline"]
        assert mixed["evolved"] == vertical["evolved"]

    def test_config_without_direction_is_skipped(self):
        evolver = _make_evolver()
        ic_only = [{"name": "iron_condor", "type": "iron_condor",
                    "put_sd": 1.0, "call_sd": 1.0, "spread_width": 500,
                    "min_vix": 0, "max_vix": 100}]
        result = evolver.compare_with_baseline(ic_only)
        assert result["baseline"] == {}
        assert set(result["evolved"]) == {"low_vix_12_15", "high_vix_20_30"}

    def test_config_missing_spread_width_is_skipped(self):
        evolver = _make_evolver()
        no_width = [{"name": "x", "type": "vertical", "direction": "put",
                     "sd": 1.0, "min_vix": 0, "max_vix": 100}]
        assert evolver.compare_with_baseline(no_width)["baseline"] == {}

    def test_vertical_baseline_metrics_match_private_helpers(self):
        """Baseline metrics for one regime equal a direct call to the private helpers."""
        evolver = _make_evolver()
        regime = "mid_vix_15_20"
        vix_lo, vix_hi = VIX_REGIMES[regime]
        entries = evolver._compute_regime_entries(5)[regime]
        assert len(entries) >= 5

        expected_trades = []
        for cfg in VERTICAL_ONLY:
            if cfg["min_vix"] <= vix_lo and cfg["max_vix"] >= vix_hi:
                params = {
                    "direction": cfg["direction"], "sd": cfg["sd"],
                    "spread_width": cfg["spread_width"],
                    "profit_target_pct": 50.0, "stop_loss_pct": 60.0, "hold_days": 21,
                }
                expected_trades.extend(evolver._simulate_param_set(entries, params))
        assert expected_trades, "fixture should cover the mid regime with vertical configs"
        expected = evolver._compute_metrics(expected_trades)

        result = evolver.compare_with_baseline(VERTICAL_ONLY)
        assert result["baseline"][regime] == expected

    def test_is_vertical_baseline_predicate(self):
        assert _is_vertical_baseline({"direction": "put", "sd": 1.0, "spread_width": 500})
        assert _is_vertical_baseline({"direction": "call", "sd": 1.0, "spread_width": 500})
        assert not _is_vertical_baseline({"type": "iron_condor", "put_sd": 1.0})
        assert not _is_vertical_baseline({"direction": "put", "sd": 1.0})
        assert not _is_vertical_baseline({"direction": "long", "sd": 1.0, "spread_width": 500})


class _ExplodingEvolver:
    def compare_with_baseline(self, baseline_configs):
        raise KeyError("direction")


class TestSafeBaselineComparison:

    def test_success_returns_comparison(self):
        evolver = _make_evolver()
        result = main_module._safe_baseline_comparison(evolver, VERTICAL_ONLY)
        assert result == evolver.compare_with_baseline(VERTICAL_ONLY)

    def test_failure_returns_empty_structure_and_warns(self, capsys):
        result = main_module._safe_baseline_comparison(_ExplodingEvolver(), STRATEGY_CONFIGS)
        assert result == {"baseline": {}, "evolved": {}}
        out = capsys.readouterr().out
        assert "baseline comparison skipped" in out
        assert "KeyError" in out
