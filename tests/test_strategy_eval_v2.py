"""Tests for the strategy_eval v2 additions: auto-registration, holdout ledger, block bootstrap,
VIX-bucket table, deflated Sharpe and White's reality check. Synthetic data only, no network.
"""

import importlib.util
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy import stats as sps

from strategy_eval import (
    LedgerError, TestRegistry, append_holdout_look, deflated_sharpe_grid, deflated_sharpe_ratio, normalize,
    expected_max_sharpe, monthly_block_bootstrap, read_ledger, run_evaluation, vix_bucket_table,
    white_reality_check, year_cluster_bootstrap,
)
from strategy_eval import holdout_ledger, stats
from strategy_eval.report import render_markdown
from tests.test_strategy_eval import _chain_pair, _frame, _pass_pnl

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _isolated_registry_and_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(stats, "DEFAULT_REGISTRY_PATH", tmp_path / "eval_registry.json")
    monkeypatch.setattr(holdout_ledger, "DEFAULT_LEDGER_PATH", tmp_path / "holdout_ledger.json")


def _late_holdout_frame(n=10, pnl=-10_000.0):
    offs = [(pd.Timestamp("2024-01-08") - pd.Timestamp("2019-02-18")).days + 7 * i for i in range(n)]
    return _frame(np.full(n, pnl), start=pd.Timestamp("2019-02-18").date(), entry_offset_days=offs,
                  strategy="late")


# ----------------------------------------------------------------------------- auto-registration

def test_auto_registration_writes_registry_file():
    reg_path = stats.DEFAULT_REGISTRY_PATH
    assert not reg_path.exists()
    cand, base = _chain_pair()
    run_evaluation(cand, base, name="auto-a", n_boot=500)
    assert reg_path.exists()
    cuts = json.loads(reg_path.read_text(encoding="utf-8"))
    assert len(cuts) == 1 and cuts[0]["name"].startswith("auto-a|verdict|") and cuts[0]["p_value"] is not None


def test_auto_registration_appends_each_new_cut_and_is_not_double_counted():
    cand, base = _chain_pair()
    run_evaluation(cand, base, name="auto-b", n_boot=500)
    run_evaluation(cand, base, name="auto-c", n_boot=500)
    run_evaluation(cand, base, name="auto-c", n_boot=500)      # same cut again: no new row
    cuts = json.loads(stats.DEFAULT_REGISTRY_PATH.read_text(encoding="utf-8"))
    names = [c["name"] for c in cuts]
    assert len(names) == 2 and any(n.startswith("auto-b|") for n in names) and any(n.startswith("auto-c|") for n in names)


def test_evaluate_pass_rule_records_insufficient_cut_without_p_value():
    cand = _frame(_pass_pnl(n=20))
    base = _frame(_pass_pnl(n=20) - 100, strategy="base")
    from strategy_eval import evaluate_pass_rule
    res = evaluate_pass_rule(cand, base, name="tiny", n_boot=200)
    assert res["verdict"] == "INSUFFICIENT_DATA"
    cuts = json.loads(stats.DEFAULT_REGISTRY_PATH.read_text(encoding="utf-8"))
    assert len(cuts) == 1 and cuts[0]["p_value"] is None and cuts[0]["kind"] == "verdict"


def test_registry_reloads_across_runs_and_refuses_changed_p_for_same_name(tmp_path):
    path = tmp_path / "shared.json"
    reg = TestRegistry.open(path)
    reg.add("x|verdict", 0.01, kind="verdict")
    assert path.exists()
    again = TestRegistry.open(path)
    assert again.n_cuts == 1 and again.holm()["x|verdict"] == pytest.approx(0.01)
    with pytest.raises(ValueError, match="already registered"):
        again.add("x|verdict", 0.2)
    again.add("y|verdict", None, kind="verdict")                  # recorded without p
    again.add("y|verdict", 0.03, kind="verdict")                  # first real p fills it in
    assert TestRegistry.open(path).holm()["y|verdict"] == pytest.approx(0.03)


def test_cli_default_registry_is_the_logs_file_and_is_written(tmp_path):
    spec = importlib.util.spec_from_file_location("eval_strategy_v2", REPO / "scripts" / "eval_strategy.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert stats.REPO_ROOT / "logs" / "eval_registry.json" == REPO / "logs" / "eval_registry.json"
    cand, base = _chain_pair()
    cpath, bpath = tmp_path / "c.csv", tmp_path / "b.csv"
    cand.to_csv(cpath, index=False)
    base.to_csv(bpath, index=False)
    rc = mod.main(["--trades", str(cpath), "--baseline", str(bpath), "--out", str(tmp_path / "o.md"),
                   "--name", "cli-default"])
    assert rc == 0
    cuts = json.loads(stats.DEFAULT_REGISTRY_PATH.read_text(encoding="utf-8"))
    assert any(c["name"].startswith("cli-default|") for c in cuts)


# ----------------------------------------------------------------------------- holdout ledger

def test_holdout_look_appends_ledger_row_and_second_look_appends_second_row():
    from strategy_eval import evaluate_pass_rule
    cand, base = _chain_pair()
    cand_h = normalize(pd.concat([cand, _late_holdout_frame()], ignore_index=True))
    base_h = normalize(pd.concat([base, _late_holdout_frame().assign(strategy="base")], ignore_index=True))

    evaluate_pass_rule(cand, base, name="hold", n_boot=200)               # dev-only: no ledger row
    assert not holdout_ledger.DEFAULT_LEDGER_PATH.exists()

    res1 = evaluate_pass_rule(cand_h, base_h, name="hold", allow_holdout=True, n_boot=200)
    assert len(read_ledger()) == 1
    res2 = evaluate_pass_rule(cand_h, base_h, name="hold", allow_holdout=True, n_boot=200)
    rows = read_ledger()
    assert len(rows) == 2
    assert [r["index"] for r in rows] == [0, 1]
    assert rows[0]["candidate"] == "hold" and set(rows[0]) >= {"timestamp", "candidate", "window"}
    assert rows[0]["window"]["candidate_holdout_trades"] == 10
    assert rows[1]["prev_hash"] == rows[0]["hash"]
    assert res1["holdout_look"]["index"] == 0 and res2["holdout_look"]["index"] == 1

    cuts = json.loads(stats.DEFAULT_REGISTRY_PATH.read_text(encoding="utf-8"))
    looks = [c["name"] for c in cuts if c["kind"] == "holdout_look"]
    assert looks == ["hold|holdout-look#0", "hold|holdout-look#1"]


def test_ledger_append_keeps_earlier_bytes_and_detects_tampering(tmp_path):
    path = tmp_path / "ledger.json"
    append_holdout_look("a", {"k": 1}, path)
    first = path.read_bytes()
    append_holdout_look("b", {"k": 2}, path)
    second = path.read_bytes()
    assert second.startswith(first.rstrip()[:-1])            # every earlier byte is kept
    assert [r["candidate"] for r in read_ledger(path)] == ["a", "b"]

    edited = second.replace(b'"candidate": "a"', b'"candidate": "z"')
    path.write_bytes(edited)
    with pytest.raises(LedgerError):
        read_ledger(path)

    path.write_bytes(second)
    lines = second.decode("utf-8").splitlines(keepends=True)
    path.write_text("".join(lines[:2] + lines[3:]), encoding="utf-8")   # delete the first row
    with pytest.raises(LedgerError):
        read_ledger(path)


def test_ledger_row_records_timestamp_and_window_fields(tmp_path):
    rec = append_holdout_look("cand", {"dev_end": "2023-12-31", "holdout_from": "2024-01-01"}, tmp_path / "l.json")
    assert rec["timestamp"].endswith("+00:00") and rec["window"]["holdout_from"] == "2024-01-01"
    assert rec["prev_hash"] == "0" * 64 and len(rec["hash"]) == 64


# ----------------------------------------------------------------------------- block bootstrap

def test_monthly_block_bootstrap_deterministic_with_seed():
    pl = _pass_pnl(250)
    dates = pd.Series(pd.Timestamp("2019-02-18") + pd.to_timedelta(7 * np.arange(250), unit="D"))
    a = monthly_block_bootstrap(pl, dates, n_boot=2000, seed=11)
    b = monthly_block_bootstrap(pl, dates, n_boot=2000, seed=11)
    c = monthly_block_bootstrap(pl, dates, n_boot=2000, seed=12)
    assert a == b
    assert (a["lo"], a["hi"]) != (c["lo"], c["hi"])
    assert a["lo"] <= a["mean"] <= a["hi"]
    assert a["cluster"] == "month" and a["n_clusters"] == dates.dt.strftime("%Y-%m").nunique()
    yr = year_cluster_bootstrap(pl, dates.dt.year.to_numpy(), n_boot=2000, seed=11)
    assert yr["lo"] != a["lo"]                                  # a different cluster unit gives a different CI


def test_block_ci_reported_and_pass_criterion_still_year_cluster():
    cand, base = _chain_pair()
    from strategy_eval import evaluate_pass_rule
    res = evaluate_pass_rule(cand, base, n_boot=2000, seed=5)
    blk = res["block_bootstrap"]
    assert blk is not None and blk["seed"] == 5 and blk["cluster"] == "month"
    c3 = [c for c in res["criteria"] if c["id"] == "C3"][0]
    assert c3["value"] == pytest.approx(res["bootstrap"]["lo"])     # C3 still uses the year-cluster lower bound
    md = render_markdown(run_evaluation(cand, base, n_boot=2000, seed=5))
    assert "Monthly-block bootstrap 95% CI" in md


# ----------------------------------------------------------------------------- VIX buckets

def test_vix_table_renders_buckets_when_column_present():
    cand, base = _chain_pair()
    vix = np.array([12.0, 14.0, 18.0, 22.0, 27.0] * (len(cand) // 5 + 1))[:len(cand)]
    cand = cand.assign(entry_vix=vix)
    vt = vix_bucket_table(cand)
    assert vt["available"] is True and vt["unknown_vix_n"] == 0
    assert [r["bucket"] for r in vt["rows"]] == ["<13", "13-16", "16-20", "20-25", "25+"]
    assert sum(r["n"] for r in vt["rows"]) == len(cand)
    res = run_evaluation(cand, base, n_boot=500)
    md = render_markdown(res)
    assert "## VIX bucket breakdown" in md and "| 25+ |" in md and "n/a: the trade table has no entry_vix" not in md


def test_vix_table_reports_na_without_column_or_values():
    cand, base = _chain_pair()
    no_col = cand.drop(columns=["entry_vix"])
    assert vix_bucket_table(no_col) == {"available": False, "rows": [], "unknown_vix_n": len(no_col)}
    all_nan = cand.assign(entry_vix=np.nan)
    assert vix_bucket_table(all_nan)["available"] is False
    md = render_markdown(run_evaluation(no_col, base, n_boot=500))
    assert "## VIX bucket breakdown" in md and "n/a: the trade table has no entry_vix values" in md


# ----------------------------------------------------------------------------- deflated Sharpe

def test_expected_max_sharpe_known_values():
    assert expected_max_sharpe(1, 1.0) == 0.0 and expected_max_sharpe(10, 0.0) == 0.0
    g = 0.5772156649015329
    ref = (1 - g) * sps.norm.ppf(0.9) + g * sps.norm.ppf(1 - 1 / (10 * math.e))
    assert expected_max_sharpe(10, 1.0) == pytest.approx(ref, rel=1e-12)
    assert expected_max_sharpe(10, 1.0) == pytest.approx(1.5746, abs=2e-3)   # hand value, N=10, V=1
    assert expected_max_sharpe(10, 4.0) == pytest.approx(2 * expected_max_sharpe(10, 1.0))


def test_dsr_single_trial_matches_hand_value():
    # N=1 so SR0=0; skew 0, kurt 3 gives denominator sqrt(1 + 0.5*sr^2)
    d = deflated_sharpe_ratio(sr_hat=0.1, n_obs=101, n_trials=1, var_sharpe=0.0)
    assert d["sr0"] == 0.0
    assert d["dsr"] == pytest.approx(sps.norm.cdf(0.1 * 10 / math.sqrt(1 + 0.5 * 0.01)), rel=1e-12)
    assert d["dsr"] == pytest.approx(0.8407, abs=5e-4)


def test_dsr_is_one_half_when_sharpe_equals_sr0_and_falls_with_more_trials():
    sr0 = expected_max_sharpe(10, 0.01)
    assert deflated_sharpe_ratio(sr0, 500, 10, 0.01)["dsr"] == pytest.approx(0.5, abs=1e-12)
    few = deflated_sharpe_ratio(0.15, 500, 2, 0.01)["dsr"]
    many = deflated_sharpe_ratio(0.15, 500, 200, 0.01)["dsr"]
    assert many < few


def test_deflated_sharpe_grid_separates_edge_from_noise():
    rng = np.random.default_rng(3)
    grid = {f"noise{i}": rng.normal(0.0, 1.0, 500) for i in range(30)}
    grid["edge"] = rng.normal(0.5, 1.0, 500)
    out = deflated_sharpe_grid(grid)
    assert out["n_trials"] == 31 and out["best"] == "edge"
    by = {r["name"]: r for r in out["rows"]}
    assert by["edge"]["dsr"] > 0.99
    assert all(0.0 <= by[k]["dsr"] <= 1.0 for k in grid)
    assert out["sr0"] == pytest.approx(expected_max_sharpe(31, out["var_sharpe"]))
    # pure-noise grid: best Sharpe is not deflated to significance
    noise_only = deflated_sharpe_grid({k: v for k, v in grid.items() if k != "edge"})
    assert noise_only["rows"] and max(r["dsr"] for r in noise_only["rows"]) < 0.99


# ----------------------------------------------------------------------------- White reality check

def test_white_reality_check_deterministic_and_null_not_rejected():
    rng = np.random.default_rng(21)
    r = rng.normal(0.0, 1.0, size=(300, 40))
    a = white_reality_check(r, n_boot=2000, seed=4)
    b = white_reality_check(r, n_boot=2000, seed=4)
    assert a == b
    assert a["p_value"] > 0.10 and a["n_candidates"] == 40 and a["n_dates"] == 300


def test_white_reality_check_rejects_a_real_edge_in_a_noisy_grid():
    rng = np.random.default_rng(22)
    r = rng.normal(0.0, 1.0, size=(300, 40))
    r[:, 7] += 0.5                       # sqrt(300) * 0.5 is about 8.7, far above the null max of about 2.5
    out = white_reality_check(r, n_boot=2000, seed=4)
    assert out["p_value"] < 0.01 and out["best"] == 7
    blocked = white_reality_check(r, n_boot=2000, seed=4, block_len=5)
    assert blocked["p_value"] < 0.01 and blocked["block_len"] == 5


def test_white_reality_check_validates_input():
    with pytest.raises(ValueError):
        white_reality_check(np.ones(10))
    with pytest.raises(ValueError):
        white_reality_check(np.array([[1.0, np.nan], [0.0, 1.0]]))
