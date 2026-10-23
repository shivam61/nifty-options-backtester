"""Tests for scripts/evaluate_prereg_arms.py (pre-registered pass rule, Holm, cost gate, window guard)."""

import importlib.util
import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("evaluate_prereg_arms", ROOT / "scripts" / "evaluate_prereg_arms.py")
EV = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(EV)

YEARS = [2019, 2020, 2021, 2022, 2023]


def _series(mean, n, rng, noise=200.0):
    x = rng.normal(0.0, noise, n)
    return x - x.mean() + mean


def make_arm(path, means_by_mult, year_shift=None, years=YEARS, n_per_year=45, seed=1, extra_2024=0):
    """Write trades_x<mult>.json with an exact per-year mean = overall target + year_shift[year]."""
    path.mkdir(parents=True, exist_ok=True)
    for mult, target in means_by_mult.items():
        rng = np.random.default_rng(seed + int(mult * 10))
        trades = []
        for y in years:
            shift = (year_shift or {}).get(y, 0.0)
            pnl = _series(target + shift, n_per_year, rng)
            d0 = date(y, 1, 7)
            for k, v in enumerate(pnl):
                d = d0 + timedelta(days=7 * k)
                trades.append({"entry_date": d.isoformat(), "exit_date": (d + timedelta(days=4)).isoformat(),
                               "pnl_per_lot": float(v), "strategy": "weekly_ic", "entry_vix": 15.0})
        for k in range(extra_2024):
            d = date(2024, 1, 9) + timedelta(days=7 * k)
            trades.append({"entry_date": d.isoformat(), "exit_date": (d + timedelta(days=4)).isoformat(),
                           "pnl_per_lot": 1000.0, "strategy": "weekly_ic", "entry_vix": 15.0})
        json.dump({"trades": trades}, open(path / f"trades_x{mult:g}.json", "w"))
    return path


def _load(path, window_end=EV.DEV_END):
    return EV.load_arm(path, window_end)[0]


def test_consistently_positive_arm_passes_everything(tmp_path):
    base = make_arm(tmp_path / "base", {1.0: -200, 1.5: -300, 2.0: -400})
    good = make_arm(tmp_path / "good", {1.0: 450, 1.5: 400, 2.0: 350}, seed=7)
    res = EV.evaluate(_load(base), {"H1": _load(good)})
    r = res["arms"]["H1"]
    assert all(r["checks"].values()) and r["rule_pass"]
    assert r["holm_ok"] and r["confirmatory_pass"]
    assert r["break_even_status"] == "above_range"
    assert r["positive_years"] == 5 and r["years_needed"] == 4


def test_overlay_that_beats_baseline_but_stays_negative_fails(tmp_path):
    base = make_arm(tmp_path / "base", {1.5: -300})
    trim = make_arm(tmp_path / "trim", {1.5: -50}, seed=3)
    r = EV.evaluate(_load(base), {"H2": _load(trim)})["arms"]["H2"]
    assert r["checks"]["beats_baseline"] is True
    assert r["checks"]["positive"] is False
    assert not r["rule_pass"] and not r["confirmatory_pass"]


def test_positive_overall_but_two_negative_years_fails_consistency(tmp_path):
    base = make_arm(tmp_path / "base", {1.5: -300})
    shift = {2019: 900, 2020: 900, 2021: 900, 2022: -900, 2023: -900}
    uneven = make_arm(tmp_path / "uneven", {1.5: 260}, year_shift=shift, seed=5)
    r = EV.evaluate(_load(base), {"H3": _load(uneven)})["arms"]["H3"]
    assert r["exp_per_lot"] > 0
    assert r["positive_years"] == 3 and r["years_needed"] == 4
    assert r["checks"]["year_consistency"] is False
    assert not r["rule_pass"]


def test_break_even_interpolation_and_statuses():
    be, st = EV.break_even({1.0: 100.0, 1.5: -100.0, 2.0: -300.0})
    assert st == "interpolated" and be == pytest.approx(1.25)
    assert EV.break_even({1.0: 50.0, 2.0: 10.0}) == (None, "above_range")
    assert EV.break_even({1.0: -50.0, 2.0: -10.0}) == (None, "below_range")
    assert EV.break_even({1.5: 10.0}) == (None, "needs_two_multipliers")


def test_holm_adjustment_is_monotone_and_correct():
    adj = EV.holm({"a": 0.01, "b": 0.02, "c": 0.04})
    assert adj["a"] == pytest.approx(0.03)
    assert adj["b"] == pytest.approx(0.04)
    assert adj["c"] == pytest.approx(0.04)
    assert EV.holm({"x": 0.9})["x"] == pytest.approx(0.9)
    assert EV.holm({"a": 0.5, "b": 0.6})["a"] <= 1.0


def test_window_guard_drops_holdout_trades_unless_allowed(tmp_path):
    arm = make_arm(tmp_path / "arm", {1.5: 100}, extra_2024=10)
    runs, dropped = EV.load_arm(arm, EV.DEV_END)
    assert dropped == 10
    assert runs[1.5]["entry_date"].max() <= EV.DEV_END
    runs_all, dropped_all = EV.load_arm(arm, None)
    assert dropped_all == 0
    assert (runs_all[1.5]["entry_date"] > EV.DEV_END).sum() == 10


def test_cost_gate_uses_break_even_multiplier(tmp_path):
    base = make_arm(tmp_path / "base", {1.0: -200, 1.5: -300, 2.0: -400})
    arm = make_arm(tmp_path / "arm", {1.0: 500, 1.5: 300, 2.0: -100}, seed=9)
    ok = EV.evaluate(_load(base), {"H4": _load(arm)}, measured_multiplier=1.0)["arms"]["H4"]
    bad = EV.evaluate(_load(base), {"H4": _load(arm)}, measured_multiplier=2.0)["arms"]["H4"]
    none = EV.evaluate(_load(base), {"H4": _load(arm)})["arms"]["H4"]
    assert ok["break_even_multiplier"] == pytest.approx(1.875, abs=0.01)
    assert ok["cost_gate"] == "pass" and ok["confirmatory_pass"]
    assert bad["cost_gate"] == "fail" and bad["rule_pass"] and not bad["confirmatory_pass"]
    assert none["cost_gate"] == "not_evaluated"


def test_missing_pass_slippage_is_an_error(tmp_path):
    base = make_arm(tmp_path / "base", {1.0: -200})
    arm = make_arm(tmp_path / "arm", {1.0: 100}, seed=2)
    with pytest.raises(SystemExit):
        EV.evaluate(_load(base), {"H": _load(arm)})


def test_cli_end_to_end_writes_json(tmp_path, capsys):
    base = make_arm(tmp_path / "base", {1.0: -200, 1.5: -300})
    a1 = make_arm(tmp_path / "a1", {1.0: 450, 1.5: 400}, seed=7, extra_2024=5)
    a2 = make_arm(tmp_path / "a2", {1.0: -10, 1.5: -60}, seed=8)
    out = tmp_path / "eval.json"
    rc = EV.main(["--baseline", str(base), "--arm", f"H1={a1}", "--arm", f"H2={a2}", "--out", str(out)])
    assert rc == 0
    res = json.loads(out.read_text())
    assert res["family_size"] == 2 and res["window_end"] == EV.DEV_END
    assert res["dropped_after_window"]["H1"] == 5
    assert res["arms"]["H1"]["confirmatory_pass"] is True
    assert res["arms"]["H2"]["confirmatory_pass"] is False
    text = capsys.readouterr().out
    assert "CONFIRMATORY PASS: YES" in text and "CONFIRMATORY PASS: NO" in text


def test_cli_requires_an_arm(tmp_path):
    base = make_arm(tmp_path / "base", {1.5: -300})
    with pytest.raises(SystemExit):
        EV.main(["--baseline", str(base)])
