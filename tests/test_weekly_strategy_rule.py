"""Unified weekly strategy-selection rule: backtest engines and live CLI must agree."""

import ast
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from backtester import combined_engine, weekly_engine
from backtester.weekly_exit_policy import (
    WEEKLY_IC,
    WEEKLY_PCS,
    select_weekly_strategy_name,
)

REPO = Path(__file__).resolve().parents[1]


# ── Rule table (boundaries of VIX band and |5d return| threshold) ─────────────

@pytest.mark.parametrize(
    "vix, ret, expected",
    [
        # VIX band [12, 22] inclusive, ret 0 so only VIX matters
        (11.99, 0.0, WEEKLY_PCS),
        (12.0, 0.0, WEEKLY_IC),
        (22.0, 0.0, WEEKLY_IC),
        (22.01, 0.0, WEEKLY_PCS),
        # |5d return| strictly < 2%, inside the VIX band
        (17.0, 0.0199, WEEKLY_IC),
        (17.0, -0.0199, WEEKLY_IC),
        (17.0, 0.02, WEEKLY_PCS),
        (17.0, -0.02, WEEKLY_PCS),
        (17.0, float("nan"), WEEKLY_PCS),
        (17.0, np.nan, WEEKLY_PCS),
        (17.0, None, WEEKLY_PCS),
        # Old live CLI cut-off (VIX 16) is no longer a boundary
        (15.0, 0.0, WEEKLY_IC),
        (16.5, 0.01, WEEKLY_IC),
        # VIX outside the band is PCS regardless of return
        (11.0, 0.0, WEEKLY_PCS),
        (25.0, 0.0, WEEKLY_PCS),
        (float("nan"), 0.0, WEEKLY_PCS),
    ],
)
def test_rule_table(vix, ret, expected):
    assert select_weekly_strategy_name(vix, ret) == expected


def _old_engine_rule(vix, nifty_5d):
    """Verbatim copy of the pre-unification inline rule, used as an oracle."""
    if 12 <= vix <= 22:
        if not (isinstance(nifty_5d, float) and np.isnan(nifty_5d)) and abs(nifty_5d) < 0.02:
            return WEEKLY_IC
    return WEEKLY_PCS


def test_rule_matches_old_engine_formula_on_numeric_grid():
    vixs = np.round(np.arange(9.0, 26.0, 0.25), 2)
    rets = [-0.05, -0.02, -0.0199, -0.01, 0.0, 0.005, 0.0199, 0.02, 0.05, float("nan")]
    for v in vixs:
        for r in rets:
            assert select_weekly_strategy_name(float(v), r) == _old_engine_rule(float(v), r), (v, r)


# ── Both engines delegate to the shared function ─────────────────────────────

@pytest.fixture
def spy(monkeypatch):
    calls = []

    def _make(module, forced):
        real_name = "select_weekly_strategy_name"

        def fake(vix, ret):
            calls.append((vix, ret))
            return forced

        monkeypatch.setattr(module, real_name, fake)
        return calls

    return _make


@pytest.mark.parametrize("forced, expected_attr", [(WEEKLY_IC, "IC"), (WEEKLY_PCS, "PCS")])
def test_combined_engine_delegates(spy, forced, expected_attr):
    calls = spy(combined_engine, forced)
    eng = SimpleNamespace(weekly_ic="IC", weekly_pcs="PCS")
    out = combined_engine.CombinedBacktestEngine._select_weekly_strategy(
        eng, 18.0, {"nifty_return_5d": 0.003}
    )
    assert out == expected_attr
    assert calls == [(18.0, 0.003)]


@pytest.mark.parametrize("forced, expected_attr", [(WEEKLY_IC, "IC"), (WEEKLY_PCS, "PCS")])
def test_weekly_engine_delegates(spy, forced, expected_attr):
    calls = spy(weekly_engine, forced)
    eng = SimpleNamespace(ic="IC", pcs="PCS")
    out = weekly_engine.WeeklyBacktestEngine._select_strategy(
        eng, 18.0, {"nifty_return_5d": 0.003}
    )
    assert out == expected_attr
    assert calls == [(18.0, 0.003)]


def test_engine_methods_return_expected_objects_without_spy():
    ic_eng = SimpleNamespace(weekly_ic="IC", weekly_pcs="PCS")
    assert combined_engine.CombinedBacktestEngine._select_weekly_strategy(
        ic_eng, 18.0, {"nifty_return_5d": 0.001}) == "IC"
    assert combined_engine.CombinedBacktestEngine._select_weekly_strategy(
        ic_eng, 18.0, {"nifty_return_5d": 0.05}) == "PCS"
    # Missing key defaults to 0 (as before) -> IC inside band
    assert combined_engine.CombinedBacktestEngine._select_weekly_strategy(
        ic_eng, 18.0, {}) == "IC"

    w_eng = SimpleNamespace(ic="IC", pcs="PCS")
    assert weekly_engine.WeeklyBacktestEngine._select_strategy(
        w_eng, 18.0, {"nifty_return_5d": float("nan")}) == "PCS"


# ── Live CLI uses the shared function ────────────────────────────────────────

def _signal_combined_source():
    tree = ast.parse((REPO / "main.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "run_signal_combined":
            return node
    raise AssertionError("run_signal_combined not found in main.py")


def test_cli_calls_shared_rule():
    fn = _signal_combined_source()
    called = {
        n.func.id for n in ast.walk(fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    assert "select_weekly_strategy_name" in called


def test_cli_has_no_legacy_vix16_rule():
    fn = _signal_combined_source()
    src = ast.get_source_segment((REPO / "main.py").read_text(encoding="utf-8"), fn)
    assert "vix <= 16" not in src
    assert "vix <=16" not in src
