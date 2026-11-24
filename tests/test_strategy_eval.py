"""Tests for strategy_eval/: schema, metrics, stress, statistics, pass rule, guards, hedge scorecard,
adapters, CLI. Synthetic data only (no network); real research files are smoke-tested if present.
"""

import importlib.util
import json
import math
import os
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from strategy_eval import (
    DEV_END, DEV_START, SchemaError, TestRegistry, core_metrics, defined_max_loss_per_unit,
    evaluate_pass_rule, from_chain_trades, from_h9_frame, from_run69_trades, hedge_scorecard,
    holm_adjust, load_trades, normalize, per_year_table, run_evaluation, sizing, stress_trades,
    year_cluster_bootstrap, year_consistency,
)
from strategy_eval.metrics import max_drawdown_per_lot
from strategy_eval.stats import nonoverlapping_subsample
from strategy_eval.verdict import apply_windows

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _isolated_registry_and_ledger(tmp_path, monkeypatch):
    """Auto-registration writes to logs/ by default. Tests get their own files so that real cuts from
    earlier runs never change a test's Holm family or holdout count."""
    from strategy_eval import holdout_ledger, stats
    monkeypatch.setattr(stats, "DEFAULT_REGISTRY_PATH", tmp_path / "isolated_registry.json")
    monkeypatch.setattr(holdout_ledger, "DEFAULT_LEDGER_PATH", tmp_path / "isolated_ledger.json")


SCRATCH = Path(os.environ.get(
    "STRATEGY_EVAL_SCRATCH",
    "C:/Users/user/AppData/Local/Temp/claude/ab792cd6a65eab7a/bbf3a506-204c-4d5c-917d-3affd979f39a/scratchpad"))


def _frame(pnl_per_lot, *, start=date(2019, 2, 18), step=7, hold=6, lots=1, credit=1000.0,
           cost=100.0, slip=100.0, source="chain", strategy="cand", max_loss=float("nan"),
           exit_reason="expiry", hedge=0.0, haircut_pct=0.0, entry_offset_days=None):
    """Normalised frame from per-lot net P&L values. cost and slip are per lot."""
    pnl = np.asarray(pnl_per_lot, dtype=float)
    n = len(pnl)
    if entry_offset_days is None:
        entries = [pd.Timestamp(start) + pd.Timedelta(days=step * i) for i in range(n)]
    else:
        entries = [pd.Timestamp(start) + pd.Timedelta(days=int(d)) for d in entry_offset_days]
    df = pd.DataFrame({
        "strategy": strategy,
        "entry_date": entries,
        "exit_date": [e + pd.Timedelta(days=hold) for e in entries],
        "expiry": [e + pd.Timedelta(days=hold) for e in entries],
        "lots": lots,
        "credit_rs": credit * lots,
        "max_loss_rs": max_loss * lots,
        "pnl_net_rs": pnl * lots,
        "cost_rs": cost * lots,
        "pnl_gross_rs": pnl * lots + cost * lots,
        "exit_reason": exit_reason,
        "entry_vix": 15.0,
        "hedge_cost_rs": hedge * lots,
        "slippage_rs": slip * lots if slip is not None else np.nan,
        "base_haircut_pct": haircut_pct,
        "pricing_source": source,
    })
    return normalize(df)


def _pass_pnl(n=250, seed=8, mean=215.0, sd=1000.0):
    """Per-lot net P&L that passes all five criteria at 1.5x (seed chosen by search; raw p about 0.006)."""
    return np.random.default_rng(seed).normal(mean, sd, n)


# ----------------------------------------------------------------------------- schema

def test_schema_accepts_valid_frame_and_fills_optional_defaults():
    df = _frame([100.0, -50.0])
    assert {"expiry", "max_loss_rs", "exit_reason", "entry_vix", "hedge_cost_rs",
            "slippage_rs", "base_haircut_pct"} <= set(df.columns)
    assert df["hedge_cost_rs"].tolist() == [0.0, 0.0]
    assert df["base_haircut_pct"].tolist() == [0.0, 0.0]


def test_schema_missing_required_column_raises():
    df = _frame([100.0]).drop(columns=["cost_rs"])
    with pytest.raises(SchemaError, match="cost_rs"):
        normalize(df)


def test_schema_rejects_bad_pricing_source_and_lots():
    raw = _frame([100.0]).copy()
    raw["pricing_source"] = "guess"
    with pytest.raises(SchemaError, match="pricing_source"):
        normalize(raw)
    raw = _frame([100.0]).copy()
    raw["lots"] = 0
    with pytest.raises(SchemaError, match="lots"):
        normalize(raw)


def test_schema_rejects_broken_identity_and_bad_dates_and_hedge_cost():
    raw = _frame([100.0]).copy()
    raw["pnl_net_rs"] = raw["pnl_net_rs"] + 50.0
    with pytest.raises(SchemaError, match="pnl_net_rs"):
        normalize(raw)
    raw = _frame([100.0]).copy()
    raw["exit_date"] = raw["entry_date"] - pd.Timedelta(days=1)
    with pytest.raises(SchemaError, match="exit_date"):
        normalize(raw)
    raw = _frame([100.0]).copy()
    raw["hedge_cost_rs"] = raw["cost_rs"] + 10.0
    with pytest.raises(SchemaError, match="hedge_cost_rs"):
        normalize(raw)


def test_loader_round_trip_csv_and_pickle(tmp_path):
    df = _frame(_pass_pnl(20))
    csv = tmp_path / "t.csv"
    df.to_csv(csv, index=False)
    back = load_trades(csv, adapter="normal")
    assert len(back) == 20 and np.allclose(back["pnl_net_rs"], df["pnl_net_rs"])
    pkl = tmp_path / "t.pkl"
    df.to_pickle(pkl)
    back2 = load_trades(pkl, adapter="normal")
    assert np.allclose(back2["pnl_net_rs"], df["pnl_net_rs"])


# ----------------------------------------------------------------------------- metrics

def test_expectancy_payoff_breakeven_hand_computed():
    df = _frame([100.0, -50.0, 200.0, -150.0, 50.0], cost=0.0, slip=None)
    m = core_metrics(df)
    assert m["expectancy_per_lot"] == pytest.approx(30.0)
    assert m["avg_win_per_lot"] == pytest.approx(350.0 / 3)
    assert m["payoff_ratio"] == pytest.approx((350.0 / 3) / 100.0)
    assert m["win_rate_actual"] == pytest.approx(0.6)
    assert m["breakeven_win_rate"] == pytest.approx(100.0 / (350.0 / 3 + 100.0))
    assert m["worst_per_lot"] == pytest.approx(-150.0)
    assert m["p5_per_lot"] == pytest.approx(np.percentile([100, -50, 200, -150, 50], 5))


def test_per_lot_scaling_is_invariant_to_lots():
    one = core_metrics(_frame([100.0, -50.0, 200.0, -150.0, 50.0], cost=0.0, slip=None))
    two = core_metrics(_frame([100.0, -50.0, 200.0, -150.0, 50.0], cost=0.0, slip=None, lots=2))
    assert two["expectancy_per_lot"] == pytest.approx(one["expectancy_per_lot"])
    assert two["worst_per_lot"] == pytest.approx(one["worst_per_lot"])


def test_max_drawdown_hand_computed():
    df = _frame([100.0, -50.0, 200.0, -150.0, 50.0], cost=0.0, slip=None)
    # cum 100, 50, 250, 100, 150; peak 100, 100, 250, 250, 250; drawdowns 0, 50, 0, 150, 100
    assert max_drawdown_per_lot(df) == pytest.approx(150.0)


def test_per_year_table_and_exit_mix():
    df = _frame(_pass_pnl(120), exit_reason=["expiry"] * 60 + ["stop_loss"] * 60)
    yt = per_year_table(df)
    assert yt["n"].sum() == 120 and set(yt["year"]) <= {2019, 2020, 2021, 2022, 2023, 2024}
    from strategy_eval.metrics import exit_reason_mix
    mix = exit_reason_mix(df)
    assert set(mix["exit_reason"]) == {"expiry", "stop_loss"}
    assert mix["n"].sum() == 120


def test_sizing_caps_lots_to_risk_cap_and_implied_cagr():
    df = _frame([100.0, -200.0, 300.0, 50.0], cost=0.0, slip=None, max_loss=13000.0)
    s = sizing(df, capital=2_500_000, risk_cap=50_000)
    assert s["lots_cap"] == 3                       # floor(50000 / 13000)
    assert s["worst_loss_at_lots_rs"] <= 50_000
    total = float(df["pnl_net_rs"].sum() / df["lots"].iloc[0] * 3)   # per-lot sum at 3 lots (lots=1 here)
    assert s["total_pnl_at_lots_cap"] == pytest.approx(total)
    years = s["span_years"]
    assert s["implied_cagr"] == pytest.approx(((2_500_000 + total) / 2_500_000) ** (1 / years) - 1)


def test_sizing_reports_when_risk_cap_below_one_lot():
    df = _frame([100.0, -200.0], cost=0.0, slip=None, max_loss=80_000.0)
    assert sizing(df, 2_500_000, 50_000)["lots_cap"] == 0


# ----------------------------------------------------------------------------- stress

def test_haircut_scales_pnl_by_credit_and_identity_holds():
    df = _frame([500.0], credit=1000.0, cost=100.0, slip=None)
    s = stress_trades(df, haircut=0.30)
    assert s["pnl_net_rs"].iloc[0] == pytest.approx(500.0 - 0.30 * 1000.0)
    assert s["pnl_gross_rs"].iloc[0] - s["cost_rs"].iloc[0] == pytest.approx(s["pnl_net_rs"].iloc[0])
    assert df["pnl_net_rs"].iloc[0] == pytest.approx(500.0)   # input untouched


def test_slippage_multiplier_adds_slippage_share_only():
    df = _frame([500.0], credit=1000.0, cost=100.0, slip=60.0)
    s = stress_trades(df, slippage_mult=1.5)
    assert s["pnl_net_rs"].iloc[0] == pytest.approx(500.0 - 0.5 * 60.0)


def test_slippage_unknown_scales_whole_cost():
    df = _frame([500.0], credit=1000.0, cost=100.0, slip=None)
    s = stress_trades(df, slippage_mult=2.0)
    assert s["pnl_net_rs"].iloc[0] == pytest.approx(500.0 - 100.0)


def test_base_haircut_only_applies_increment():
    df = _frame([500.0], credit=1000.0, cost=0.0, slip=None, haircut_pct=30.0)
    # stress at the base haircut changes nothing
    assert stress_trades(df, haircut=0.30)["pnl_net_rs"].iloc[0] == pytest.approx(500.0)
    # stress to 65% total: remaining credit 700, incremental x = (0.65-0.30)/0.70 = 0.5 of 1000 credit
    s = stress_trades(df, haircut=0.65)
    assert s["pnl_net_rs"].iloc[0] == pytest.approx(500.0 - 0.5 * 1000.0)


# ----------------------------------------------------------------------------- statistics

def test_bootstrap_is_deterministic_and_seed_sensitive():
    pl = _pass_pnl(120)
    years = np.repeat([2019, 2020, 2021, 2022, 2023], 24)
    a = year_cluster_bootstrap(pl, years, n_boot=500, seed=1)
    b = year_cluster_bootstrap(pl, years, n_boot=500, seed=1)
    c = year_cluster_bootstrap(pl, years, n_boot=500, seed=2)
    assert a == b
    assert (a["lo"], a["hi"]) != (c["lo"], c["hi"])
    assert a["lo"] < a["mean"] < a["hi"]


def test_holm_matches_hand_computed_example():
    adj = holm_adjust([0.01, 0.04, 0.03, 0.005])
    # sorted: 0.005*4=0.02, 0.01*3=0.03, 0.03*2=0.06, 0.04*1=0.04 -> running max 0.02, 0.03, 0.06, 0.06
    assert adj == pytest.approx([0.03, 0.06, 0.06, 0.02])


def test_holm_ignores_nan_in_family():
    adj = holm_adjust([0.01, float("nan"), 0.04])
    assert adj[0] == pytest.approx(0.02) and math.isnan(adj[1]) and adj[2] == pytest.approx(0.04)


def test_registry_counts_each_cut_once_and_refuses_changed_p(tmp_path):
    reg = TestRegistry()
    reg.add("a", 0.01)
    reg.add("a", 0.01)                       # same cut again: not counted twice
    reg.add("b", 0.04)
    assert reg.n_cuts == 2
    with pytest.raises(ValueError):
        reg.add("a", 0.2)
    assert reg.holm()["a"] == pytest.approx(0.02)
    path = tmp_path / "reg.json"
    reg.save(path)
    again = TestRegistry.load(path)
    assert again.n_cuts == 2 and again.holm()["b"] == pytest.approx(0.04)


def test_nonoverlapping_subsample_keeps_trades_that_do_not_overlap():
    entry = pd.Series(pd.to_datetime(["2020-01-01", "2020-01-04", "2020-01-08"]))
    exit_ = entry + pd.Timedelta(days=5)
    assert nonoverlapping_subsample(entry, exit_).tolist() == [0, 2]


def test_year_consistency_counts_positive_years():
    years = np.repeat([2019, 2020, 2021, 2022, 2023], 10)
    pl = np.repeat([10.0, -5.0, 10.0, -5.0, 10.0], 10)
    yc = year_consistency(pl, years, (2019, 2020, 2021, 2022, 2023), min_positive=4)
    assert yc["positive"] == 3 and yc["status"] == "FAIL"


# ----------------------------------------------------------------------------- pass rule

def _chain_pair(base_shift=100.0, **kw):
    cand = _frame(_pass_pnl(**kw), source="chain")
    base = _frame(_pass_pnl(**kw) - base_shift, source="chain", strategy="base")
    return cand, base


def _statuses(res):
    return {c["id"]: c["status"] for c in res["criteria"]}


def test_pass_rule_all_criteria_pass_on_clean_chain_data():
    cand, base = _chain_pair()
    res = evaluate_pass_rule(cand, base, n_boot=2000)
    assert _statuses(res) == {"C1": "PASS", "C2": "PASS", "C3": "PASS", "C4": "PASS", "C5": "PASS"}
    assert res["verdict"] == "PASS"


def test_pass_rule_c1_fails_when_baseline_is_better():
    cand = _frame(_pass_pnl())
    base = _frame(_pass_pnl() + 200.0, strategy="base")
    res = evaluate_pass_rule(cand, base, n_boot=2000)
    assert _statuses(res)["C1"] == "FAIL" and res["verdict"] == "FAIL"


def test_pass_rule_c2_fails_on_negative_expectancy():
    cand = _frame(_pass_pnl(mean=-300.0))
    base = _frame(_pass_pnl(mean=-400.0), strategy="base")
    res = evaluate_pass_rule(cand, base, n_boot=2000)
    assert _statuses(res)["C2"] == "FAIL" and res["verdict"] == "FAIL"


def test_pass_rule_c3_fails_when_year_cluster_ci_crosses_zero():
    # year means 1000, 1000, 1000, 1000, -3000: mean positive, 4 of 5 years positive, but the
    # year-cluster CI lower bound is below zero.
    per_year = [1000.0] * 4 + [-3000.0]
    pnl = np.repeat(per_year, 50)
    cand = _frame(pnl)
    base = _frame(pnl - 100.0, strategy="base")
    res = evaluate_pass_rule(cand, base, n_boot=5000)
    st = _statuses(res)
    assert st["C2"] == "PASS" and st["C4"] == "PASS" and st["C3"] == "FAIL"
    assert res["verdict"] == "FAIL"


def test_pass_rule_c4_fails_with_three_positive_years():
    per_year = [1000.0, 1000.0, 1000.0, -1000.0, -1000.0]
    pnl = np.repeat(per_year, 50)
    cand = _frame(pnl)
    base = _frame(pnl - 100.0, strategy="base")
    res = evaluate_pass_rule(cand, base, n_boot=2000)
    assert _statuses(res)["C4"] == "FAIL" and res["verdict"] == "FAIL"


def test_pass_rule_c5_fails_when_holm_family_is_large():
    cand, base = _chain_pair()
    first = evaluate_pass_rule(cand, base, n_boot=2000)
    p_raw = first["nonoverlap_ttest"]["p_one_sided"]
    assert first["criteria"][4]["status"] == "PASS" and p_raw < 0.05
    # add enough cuts with large p-values that Holm multiplies the verdict cut past 0.05
    reg = TestRegistry()
    n_pad = int(math.ceil(0.05 / p_raw)) + 1
    for i in range(n_pad):
        reg.add(f"pad{i}", 0.9)
    res = evaluate_pass_rule(cand, base, n_boot=2000, registry=reg)
    assert _statuses(res)["C5"] == "FAIL" and res["verdict"] == "FAIL"


def test_pass_rule_insufficient_without_baseline():
    cand, _ = _chain_pair()
    res = evaluate_pass_rule(cand, None, n_boot=2000)
    assert _statuses(res)["C1"] == "INSUFFICIENT_DATA"
    assert res["verdict"] == "INSUFFICIENT_DATA"


def test_pass_rule_insufficient_with_too_few_trades():
    cand = _frame(_pass_pnl(n=20))
    base = _frame(_pass_pnl(n=20) - 100, strategy="base")
    res = evaluate_pass_rule(cand, base, n_boot=500)
    assert _statuses(res)["C2"] == "INSUFFICIENT_DATA"
    assert res["verdict"] == "INSUFFICIENT_DATA"


def test_bs_priced_result_is_capped_at_indicative_only_even_when_all_criteria_pass():
    cand = _frame(_pass_pnl(), source="bs")
    base = _frame(_pass_pnl() - 100.0, source="bs", strategy="base")
    res = evaluate_pass_rule(cand, base, n_boot=2000)
    assert res["criteria_verdict"] == "PASS"
    assert res["verdict"] == "INDICATIVE_ONLY"
    assert res["guards"]["bs_capped"] is True


def test_bs_baseline_alone_also_caps_the_verdict():
    cand = _frame(_pass_pnl(), source="chain")
    base = _frame(_pass_pnl() - 100.0, source="bs", strategy="base")
    assert evaluate_pass_rule(cand, base, n_boot=2000)["verdict"] == "INDICATIVE_ONLY"


# ----------------------------------------------------------------------------- holdout / dev window

def test_window_excludes_pre_dev_and_holdout_by_default():
    df = _frame([1.0, 2.0, 3.0, 4.0], entry_offset_days=[
        (pd.Timestamp("2019-02-10") - pd.Timestamp("2019-02-18")).days,       # before DEV_START
        (pd.Timestamp("2019-02-11") - pd.Timestamp("2019-02-18")).days,       # DEV_START, kept
        (pd.Timestamp("2023-12-31") - pd.Timestamp("2019-02-18")).days,       # DEV_END, kept
        (pd.Timestamp("2024-01-01") - pd.Timestamp("2019-02-18")).days,       # holdout
    ])
    kept, info = apply_windows(df, allow_holdout=False)
    assert len(kept) == 2 and info["pre_dev_excluded"] == 1 and info["holdout_excluded"] == 1
    assert DEV_START == date(2019, 2, 11) and DEV_END == date(2023, 12, 31)
    kept2, info2 = apply_windows(df, allow_holdout=True)
    assert len(kept2) == 3 and info2["holdout_excluded"] == 0


def test_holdout_trades_do_not_affect_verdict_unless_allowed():
    cand, base = _chain_pair()
    # 2024+ trades with a large loss: would flip the verdict if they were used
    holdout_off = [(pd.Timestamp("2024-01-08") - pd.Timestamp("2019-02-18")).days + 7 * i for i in range(10)]
    bad = _frame(np.full(10, -10_000.0), start=date(2019, 2, 18), entry_offset_days=holdout_off, strategy="cand")
    cand_h = normalize(pd.concat([cand, bad], ignore_index=True))
    base_h = normalize(pd.concat([base, _frame(np.full(10, -10_000.0), entry_offset_days=holdout_off,
                                                strategy="base")], ignore_index=True))
    res = evaluate_pass_rule(cand_h, base_h, n_boot=2000)
    assert res["verdict"] == "PASS"
    assert res["guards"]["candidate_window"]["holdout_excluded"] == 10
    assert res["n_trades"] == len(cand)
    res2 = evaluate_pass_rule(cand_h, base_h, n_boot=2000, allow_holdout=True)
    assert res2["n_trades"] == len(cand) + 10
    assert res2["verdict"] != "PASS"


# ----------------------------------------------------------------------------- hedge scorecard

def _hedge_pair(hedge_cost, tail_gain):
    n = 260
    pnl = np.full(n, 200.0)
    pnl[::20] = -5000.0                       # ~5% tail of the baseline
    base = _frame(pnl, strategy="unhedged", cost=0.0, slip=None, credit=1000.0)
    hpl = pnl.copy()
    hpl[pnl < 0] = pnl[pnl < 0] + tail_gain
    hpl = hpl - hedge_cost
    hedged = _frame(hpl, strategy="hedged", cost=hedge_cost, slip=None, hedge=hedge_cost, credit=1000.0)
    return hedged, base


def test_hedge_scorecard_keeps_hedge_when_tail_removed_exceeds_cost():
    hedged, base = _hedge_pair(hedge_cost=100.0, tail_gain=4000.0)
    sc = hedge_scorecard(hedged, base, n_boot=500)
    assert sc["decision"].startswith("KEEP")
    assert sc["hedge_cost_per_lot"] == pytest.approx(100.0)
    assert sc["hedge_cost_pct_of_credit"] == pytest.approx(10.0)
    assert sc["tail_removed_per_lot"] > 0
    assert sc["p5_change"] > 0 and sc["worst_change"] > 0


def test_hedge_scorecard_drops_hedge_whose_cost_exceeds_tail_removed():
    hedged, base = _hedge_pair(hedge_cost=500.0, tail_gain=0.0)
    sc = hedge_scorecard(hedged, base, n_boot=500)
    assert sc["decision"].startswith("DROP")


def test_hedge_scorecard_paired_diff_ci_is_reported():
    hedged, base = _hedge_pair(hedge_cost=100.0, tail_gain=4000.0)
    sc = hedge_scorecard(hedged, base, n_boot=500)
    ci = sc["paired_diff_per_lot"]
    assert ci["lo"] <= ci["mean"] <= ci["hi"] and sc["n_pairs"] == 260


# ----------------------------------------------------------------------------- adapters

def test_defined_max_loss_iron_condor_and_naked_and_spread():
    ic = [{"type": "CE", "strike": 5550, "short": True}, {"type": "CE", "strike": 5750, "short": False},
          {"type": "PE", "strike": 4600, "short": True}, {"type": "PE", "strike": 4400, "short": False}]
    assert defined_max_loss_per_unit(ic, 30.0) == pytest.approx(200.0 - 30.0)
    naked = [{"type": "CE", "strike": 5550, "short": True}, {"type": "PE", "strike": 4600, "short": True}]
    assert math.isnan(defined_max_loss_per_unit(naked, 30.0))
    pcs = [{"type": "PE", "strike": 4600, "short": True}, {"type": "PE", "strike": 4500, "short": False}]
    assert defined_max_loss_per_unit(pcs, 20.0) == pytest.approx(80.0)


def _chain_record(**over):
    rec = {
        "strategy": "weekly_ic", "fill_date": "2025-01-03", "exit_date": "2025-01-08",
        "expiry": "2025-01-09", "lots": 2, "entry_credit_fill": 30.0,
        "gross_fill_rs": 1000.0, "fee_rs": 200.0, "pnl": 800.0,
        "entry_pen_rs": 50.0, "close_slip_rs": 25.0, "exit_reason": "dte_limit", "entry_vix": 16.0,
        "legs": [{"type": "CE", "strike": 23000, "short": True}, {"type": "CE", "strike": 23200, "short": False},
                 {"type": "PE", "strike": 22000, "short": True}, {"type": "PE", "strike": 21800, "short": False}],
    }
    rec.update(over)
    return rec


def test_chain_adapter_maps_fields_and_identity():
    df = from_chain_trades([_chain_record()], lot_size=65)
    r = df.iloc[0]
    assert r["credit_rs"] == pytest.approx(30.0 * 65 * 2)
    assert r["max_loss_rs"] == pytest.approx((200.0 - 30.0) * 65 * 2)
    assert r["pnl_net_rs"] == pytest.approx(800.0)
    assert r["cost_rs"] == pytest.approx(200.0)
    assert r["slippage_rs"] == pytest.approx(75.0)
    assert r["pricing_source"] == "chain" and r["exit_reason"] == "dte_limit"


def test_run69_adapter_treats_max_loss_as_total_and_cost_as_gross_minus_net():
    rec = {"track": "weekly", "strategy": "iron_condor", "entry_date": "2019-03-01", "exit_date": "2019-03-06",
           "lots": 4, "lot_size": 65, "net_credit_per_unit": 30.0, "max_loss_per_unit": 40000.0,
           "gross_pnl_pre_cost": 2000.0, "total_pnl": 1500.0, "exit_reason": "profit_target", "entry_vix": 14.0}
    df = from_run69_trades([rec])
    r = df.iloc[0]
    assert r["cost_rs"] == pytest.approx(500.0) and r["pnl_net_rs"] == pytest.approx(1500.0)
    assert r["credit_rs"] == pytest.approx(30.0 * 65 * 4) and r["max_loss_rs"] == pytest.approx(40000.0)
    assert r["strategy"] == "weekly:iron_condor" and r["pricing_source"] == "bs"


def test_h9_adapter_maps_hedge_cost_and_tags_bs():
    raw = pd.DataFrame({
        "entry": ["2019-02-15"], "expiry": ["2019-02-21"], "V0": [16.0], "credit": [2500.0],
        "opt_pnl": [2400.0], "fut_pnl": [-300.0], "opt_cost": [90.0], "fut_cost": [60.0],
        "net": [1950.0],   # opt_pnl - opt_cost + fut_pnl - fut_cost, as h9_sim writes it
    })
    df = from_h9_frame(raw, input_haircut_pct=30)
    r = df.iloc[0]
    assert r["pnl_gross_rs"] == pytest.approx(2100.0) and r["cost_rs"] == pytest.approx(150.0)
    assert r["hedge_cost_rs"] == pytest.approx(60.0) and r["base_haircut_pct"] == 30.0
    assert r["pricing_source"] == "bs"


def test_auto_detection_on_json_records(tmp_path):
    rec = {"track": "monthly", "strategy": "ic", "entry_date": "2019-03-01", "exit_date": "2019-03-29",
           "lots": 1, "lot_size": 65, "net_credit_per_unit": 10.0, "max_loss_per_unit": 1000.0,
           "gross_pnl_pre_cost": 100.0, "total_pnl": 90.0, "exit_reason": "x", "entry_vix": 12.0}
    p = tmp_path / "run.json"
    p.write_text(json.dumps({"summary": {}, "trades": [rec]}), encoding="utf-8")
    df = load_trades(p)
    assert df.iloc[0]["pricing_source"] == "bs" and len(df) == 1


# ----------------------------------------------------------------------------- run + report + CLI

def test_run_evaluation_and_report_json_is_clean(tmp_path):
    from strategy_eval.report import write_report
    cand, base = _chain_pair()
    res = run_evaluation(cand, base, name="synthetic", n_boot=1000)
    assert res["verdict"]["verdict"] == "PASS"
    assert res["scorecard"] is not None
    md, js = tmp_path / "r.md", tmp_path / "r.json"
    write_report(res, md, js)
    text = md.read_text(encoding="utf-8")
    assert "## Verdict: **PASS**" in text and "Cut registry" in text
    raw = js.read_text(encoding="utf-8")
    assert "NaN" not in raw and "Infinity" not in raw
    json.loads(raw)


def test_cli_writes_report_and_registry(tmp_path):
    spec = importlib.util.spec_from_file_location("eval_strategy", REPO / "scripts" / "eval_strategy.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    cand, base = _chain_pair()
    cpath, bpath = tmp_path / "cand.csv", tmp_path / "base.csv"
    cand.to_csv(cpath, index=False)
    base.to_csv(bpath, index=False)
    out = tmp_path / "eval.md"
    reg = tmp_path / "reg.json"
    rc = mod.main(["--trades", str(cpath), "--baseline", str(bpath), "--out", str(out),
                   "--registry", str(reg), "--name", "cli-test"])
    assert rc == 0
    assert "Verdict: **PASS**" in out.read_text(encoding="utf-8")
    assert json.loads(reg.read_text(encoding="utf-8"))[0]["kind"] == "verdict"
    assert out.with_suffix(".json").exists()


def test_cli_holdout_refusal_is_default_and_flag_opens_it(tmp_path):
    spec = importlib.util.spec_from_file_location("eval_strategy2", REPO / "scripts" / "eval_strategy.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    cand = _frame(_pass_pnl())
    late = _frame(np.full(5, -9000.0), entry_offset_days=[
        (pd.Timestamp("2024-02-01") - pd.Timestamp("2019-02-18")).days + 7 * i for i in range(5)])
    cpath = tmp_path / "c.csv"
    normalize(pd.concat([cand, late], ignore_index=True)).to_csv(cpath, index=False)
    out1 = tmp_path / "a.md"
    mod.main(["--trades", str(cpath), "--out", str(out1), "--name", "h"])
    assert "holdout (entries after 2023-12-31) excluded" in out1.read_text(encoding="utf-8")
    out2 = tmp_path / "b.md"
    mod.main(["--trades", str(cpath), "--out", str(out2), "--name", "h", "--allow-holdout"])
    assert "INCLUDED" in out2.read_text(encoding="utf-8")


def test_dev_window_constants_match_run_chain_backtest():
    spec = importlib.util.spec_from_file_location("rcb", REPO / "scripts" / "run_chain_backtest.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert DEV_END == mod.DEV_END and DEV_START == mod.DEFAULT_START


# ----------------------------------------------------------------------------- real research files (skipped if absent)

RUN69 = SCRATCH / "run69_trades.json"
H9_HEDGED = SCRATCH / "carry_run" / "h9_trades_H9spec_regA.csv"
H9_UNHEDGED = SCRATCH / "carry_run" / "h9_trades_unhedged_regA.csv"


@pytest.mark.skipif(not RUN69.exists(), reason="run69 scratch trade file not present")
def test_smoke_run69_trades_are_indicative_only():
    cand = load_trades(RUN69)
    res = run_evaluation(cand, None, name="run69", n_boot=1000)
    assert res["verdict"]["verdict"] == "INDICATIVE_ONLY"
    assert res["verdict"]["guards"]["candidate_window"]["holdout_excluded"] > 0


@pytest.mark.skipif(not (H9_HEDGED.exists() and H9_UNHEDGED.exists()), reason="H9 scratch CSVs not present")
def test_smoke_h9_hedge_pair_is_indicative_only():
    hedged = load_trades(H9_HEDGED, input_haircut_pct=30)
    base = load_trades(H9_UNHEDGED, input_haircut_pct=30)
    res = run_evaluation(hedged, base, name="h9", n_boot=1000)
    assert res["verdict"]["verdict"] == "INDICATIVE_ONLY"
    assert res["scorecard"] is not None and res["scorecard"]["decision"]
