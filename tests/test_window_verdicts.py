"""Window verdicts (docs/preregistration_candidates.md Section 10): default 'dev' unchanged; 'test' and
'holdout' use C3' (monthly-block CI lower bound > 0) and C4' (every window year positive). Synthetic data only.
"""

import numpy as np
import pandas as pd
import pytest

from strategy_eval import holdout_ledger, stats
from strategy_eval.holdout_ledger import read_ledger
from strategy_eval.stats import TestRegistry
from strategy_eval.verdict import evaluate_pass_rule
from strategy_eval.evaluate import run_evaluation
from tests.test_strategy_eval import _frame


@pytest.fixture(autouse=True)
def _isolated_registry_and_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(stats, "DEFAULT_REGISTRY_PATH", tmp_path / "eval_registry.json")
    monkeypatch.setattr(holdout_ledger, "DEFAULT_LEDGER_PATH", tmp_path / "holdout_ledger.json")


TEST_DATES = pd.date_range("2022-01-03", "2023-12-31", freq="7D")       # Mondays, exit +6 days stays in window
HOLD_DATES = pd.date_range("2024-01-08", "2025-12-31", freq="7D")


def _by_year(dates, means, seed=3, sd=1000.0):
    """Per-lot P&L for the given dates; means maps calendar year -> mean."""
    rng = np.random.default_rng(seed)
    pnl = np.array([rng.normal(means[d.year], sd) for d in dates])
    return _frame(pnl, start=dates[0].date(), entry_offset_days=[(d - dates[0]).days for d in dates],
                  strategy="cand")


def _pair(cand, shift=100.0):
    base = cand.copy()
    base["strategy"] = "base"
    base["pnl_net_rs"] = base["pnl_net_rs"] - shift
    base["pnl_gross_rs"] = base["pnl_gross_rs"] - shift
    return base


def _statuses(res):
    return {c["id"]: c["status"] for c in res["criteria"]}


# ----------------------------------------------------------------------------- default window

def test_default_window_is_dev_and_unchanged_ids():
    cand = _by_year(TEST_DATES, {2022: 400.0, 2023: 400.0})
    res_default = evaluate_pass_rule(cand, _pair(cand), registry=TestRegistry(), n_boot=500)
    res_dev = evaluate_pass_rule(cand, _pair(cand), registry=TestRegistry(), n_boot=500, window="dev")
    assert "window" not in res_default
    assert set(_statuses(res_default)) == {"C1", "C2", "C3", "C4", "C5"}
    assert _statuses(res_default) == _statuses(res_dev)
    assert res_default["bootstrap"] is not None


def test_dev_cut_name_has_no_window_suffix_and_test_cut_is_distinct():
    cand = _by_year(TEST_DATES, {2022: 400.0, 2023: 400.0})
    reg = TestRegistry()
    evaluate_pass_rule(cand, _pair(cand), registry=reg, name="same", n_boot=300, window="dev")
    evaluate_pass_rule(cand, _pair(cand), registry=reg, name="same", n_boot=300, window="test")
    names = [c["name"] for c in reg.to_dict()["cuts"] if c["kind"] == "verdict"]
    assert len(names) == 2 and len(set(names)) == 2
    assert any(n.endswith("|dev") for n in names) and any(n.endswith("|test-window") for n in names)


# ----------------------------------------------------------------------------- test window

def test_test_window_passes_when_both_years_positive_and_block_ci_above_zero():
    cand = _by_year(TEST_DATES, {2022: 400.0, 2023: 400.0})
    res = evaluate_pass_rule(cand, _pair(cand), registry=TestRegistry(), name="t", window="test", n_boot=2000)
    st = _statuses(res)
    assert st["C3'"] == "PASS" and st["C4'"] == "PASS"
    assert set(st) == {"C1", "C2", "C3'", "C4'", "C5"}
    assert res["verdict"] == "PASS" and res["window"] == "test"
    assert res["bootstrap"] is None and res["block_bootstrap"]["n_boot"] == 2000
    assert res["guards"]["candidate_window"]["window"] == "test"


def test_test_window_one_negative_year_fails_c4_prime():
    cand = _by_year(TEST_DATES, {2022: 900.0, 2023: -300.0})
    res = evaluate_pass_rule(cand, _pair(cand), registry=TestRegistry(), name="neg", window="test", n_boot=1000)
    assert _statuses(res)["C4'"] == "FAIL"
    assert res["verdict"] == "FAIL"


def test_test_window_block_ci_crossing_zero_fails_c3_prime():
    cand = _by_year(TEST_DATES, {2022: 60.0, 2023: 60.0}, sd=3000.0)
    res = evaluate_pass_rule(cand, _pair(cand), registry=TestRegistry(), name="noisy", window="test", n_boot=2000)
    assert _statuses(res)["C3'"] == "FAIL"
    assert res["verdict"] == "FAIL"


def test_test_window_under_30_trades_is_insufficient_not_fail():
    dates = pd.date_range("2022-01-03", periods=20, freq="7D")
    cand = _by_year(dates, {2022: 400.0, 2023: 400.0})
    res = evaluate_pass_rule(cand, _pair(cand), registry=TestRegistry(), name="small", window="test", n_boot=300)
    assert res["verdict"] == "INSUFFICIENT_DATA"
    assert _statuses(res)["C3'"] == "INSUFFICIENT_DATA" and _statuses(res)["C4'"] == "INSUFFICIENT_DATA"


def test_test_window_missing_year_is_insufficient():
    cand = _by_year(TEST_DATES[TEST_DATES.year == 2022], {2022: 400.0})
    res = evaluate_pass_rule(cand, _pair(cand), registry=TestRegistry(), name="one-year", window="test", n_boot=300)
    assert _statuses(res)["C4'"] == "INSUFFICIENT_DATA"
    assert res["verdict"] == "INSUFFICIENT_DATA"


def test_test_window_purges_trade_exiting_after_window_end():
    cand = _by_year(TEST_DATES, {2022: 400.0, 2023: 400.0})
    straddler = _frame([123.0], start=pd.Timestamp("2023-12-29").date(), strategy="cand")   # exit 2024-01-04
    cand = pd.concat([cand, straddler], ignore_index=True)
    res = evaluate_pass_rule(cand, None, registry=TestRegistry(), name="s", window="test", n_boot=200)
    assert res["guards"]["candidate_window"]["straddle_purged"] == 1
    assert res["n_trades"] == len(TEST_DATES)


def test_test_window_refuses_allow_holdout_and_writes_no_ledger():
    cand = _by_year(TEST_DATES, {2022: 400.0, 2023: 400.0})
    with pytest.raises(ValueError, match="allow_holdout"):
        evaluate_pass_rule(cand, None, registry=TestRegistry(), window="test", allow_holdout=True, n_boot=200)
    assert not holdout_ledger.DEFAULT_LEDGER_PATH.exists()


def test_run_evaluation_passes_window_through():
    cand = _by_year(TEST_DATES, {2022: 400.0, 2023: 400.0})
    res = run_evaluation(cand, _pair(cand), name="re", registry=TestRegistry(), n_boot=300, window="test")
    assert res["window"] == "test" and res["verdict"]["window"] == "test"
    assert res["metrics"]["at_verdict_cost"]["n"] == len(TEST_DATES)


# ----------------------------------------------------------------------------- holdout window

def test_holdout_window_refuses_without_allow_holdout():
    cand = _by_year(HOLD_DATES, {2024: 400.0, 2025: 400.0})
    with pytest.raises(ValueError, match="allow_holdout"):
        evaluate_pass_rule(cand, _pair(cand), registry=TestRegistry(), window="holdout", n_boot=200)
    assert not holdout_ledger.DEFAULT_LEDGER_PATH.exists()


def test_holdout_window_writes_exactly_one_ledger_row_and_uses_c3_prime_c4_prime():
    cand = _by_year(HOLD_DATES, {2024: 400.0, 2025: 400.0})
    res = evaluate_pass_rule(cand, _pair(cand), registry=TestRegistry(), name="h", window="holdout",
                             allow_holdout=True, n_boot=2000)
    rows = read_ledger()
    assert len(rows) == 1
    assert rows[0]["candidate"] == "h" and rows[0]["window"]["window"] == "holdout"
    assert res["holdout_look"]["index"] == 0
    st = _statuses(res)
    assert st["C3'"] == "PASS" and st["C4'"] == "PASS" and res["verdict"] == "PASS"


def test_holdout_window_negative_year_fails_c4_prime():
    cand = _by_year(HOLD_DATES, {2024: 900.0, 2025: -300.0})
    res = evaluate_pass_rule(cand, _pair(cand), registry=TestRegistry(), name="hn", window="holdout",
                             allow_holdout=True, n_boot=1000)
    assert _statuses(res)["C4'"] == "FAIL" and res["verdict"] == "FAIL"
    assert len(read_ledger()) == 1


# ----------------------------------------------------------------------------- verdict slippage (round 2 pass bar)

def test_run_evaluation_verdict_slippage_defaults_to_1_5_and_accepts_1_0():
    """docs/preregistration_round2.md Section 5/7: the pass bar is 1.0x. The default stays 1.5x (round 1)."""
    from strategy_eval.stress import per_lot
    cand = _by_year(TEST_DATES, {2022: 400.0, 2023: 400.0})
    res_default = run_evaluation(cand, _pair(cand), name="vs-d", registry=TestRegistry(), n_boot=300, window="test")
    assert res_default["verdict"]["cost_level"]["slippage_mult"] == 1.5
    res_1x = run_evaluation(cand, _pair(cand), name="vs-1", registry=TestRegistry(), n_boot=300, window="test",
                            verdict_slippage=1.0)
    assert res_1x["verdict"]["cost_level"]["slippage_mult"] == 1.0
    assert res_1x["metrics"]["at_verdict_cost"]["expectancy_per_lot"] == pytest.approx(float(per_lot(cand).mean()))
    assert "|slip1|" in res_1x["verdict"]["cut_key"] and "|slip1.5|" in res_default["verdict"]["cut_key"]
