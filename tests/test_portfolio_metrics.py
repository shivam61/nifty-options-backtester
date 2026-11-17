"""Tier 2 portfolio metrics: scripts/portfolio_metrics.py and the eval_strategy.py --equity-curve block.

Hand-computed curve, the single-point case, agreement with ChainBacktest.capital_summary on one synthetic
capital-mode run, and the CLI check that the per-lot verdict is unchanged by the Tier 2 block.
"""

import importlib.util
import json
import math
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from backtester.candidates import get_cell
from tests.test_candidates import E, S, _a_world, _run
from tests.test_candidate_engine_ext import _cfg_spec

REPO = Path(__file__).resolve().parents[1]


# ----------------------------------------------------------------------------- portfolio metrics

def _pm():
    spec = importlib.util.spec_from_file_location("portfolio_metrics", REPO / "scripts" / "portfolio_metrics.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_portfolio_metrics_hand_computed_curve():
    pm = _pm()
    dates = [date(2020, 1, 1), date(2020, 6, 30), date(2021, 6, 30), date(2022, 6, 30)]
    eq = [100.0, 110.0, 99.0, 121.0]
    m = pm.portfolio_metrics(dates, eq, capital_rs=100.0)
    years = (dates[-1] - dates[0]).days / 365.25
    assert m["cagr_pct"] == pytest.approx(((121 / 100) ** (1 / years) - 1) * 100, abs=1e-3)   # rounded to 3 dp
    assert m["max_dd_pct"] == pytest.approx(10.0)
    r = [b / a - 1 for a, b in zip(eq, eq[1:])]
    mu = sum(r) / len(r)
    sd = math.sqrt(sum((x - mu) ** 2 for x in r) / (len(r) - 1))
    assert m["sharpe_daily_ann"] == pytest.approx(mu / sd * math.sqrt(252), abs=1e-3)
    assert m["final_equity"] == 121.0 and m["n_sessions"] == 4
    assert m["years"] == pytest.approx(years, abs=1e-4)


def test_portfolio_metrics_single_point_is_none():
    m = _pm().portfolio_metrics([date(2020, 1, 1)], [100.0], capital_rs=100.0)
    assert m["cagr_pct"] is None and m["sharpe_daily_ann"] is None


def test_portfolio_metrics_agree_with_capital_summary(tmp_path):
    days, mk = _a_world(tmp_path)
    bt, _ = _run(tmp_path, days, mk, _cfg_spec(get_cell("PCS_A_k09_w200"), S, E, capital_mode=True,
                                              capital_rs=2_500_000.0))
    summ = bt.capital_summary(echo=False)
    curve = bt.capital_curve
    m = _pm().portfolio_metrics([c[0] for c in curve], [c[1] for c in curve], capital_rs=2_500_000.0)
    assert m["max_dd_pct"] == pytest.approx(summ["max_dd_pct"], abs=1e-3)
    assert m["final_equity"] == pytest.approx(summ["final_equity"], abs=1e-2)
    if summ["cagr_pct"] is not None:
        assert m["cagr_pct"] == pytest.approx(summ["cagr_pct"], abs=1e-3)
    if summ["sharpe_daily_ann"] is not None:
        assert m["sharpe_daily_ann"] == pytest.approx(summ["sharpe_daily_ann"], abs=1e-3)


def _eval_mod(name):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / "eval_strategy.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_eval_cli_reports_tier2_beside_unchanged_verdict(tmp_path):
    from tests.test_strategy_eval import _chain_pair

    cand, base = _chain_pair()
    cpath, bpath = tmp_path / "cand.csv", tmp_path / "base.csv"
    cand.to_csv(cpath, index=False)
    base.to_csv(bpath, index=False)
    curve = tmp_path / "curve.csv"
    dates = pd.bdate_range("2019-02-11", periods=400)
    pd.DataFrame({"date": dates, "equity": 2_500_000.0 * (1 + 0.0005) ** pd.Series(range(400))}).to_csv(
        curve, index=False)

    out0, out1 = tmp_path / "a.md", tmp_path / "b.md"
    _eval_mod("eval_a").main(["--trades", str(cpath), "--baseline", str(bpath), "--out", str(out0),
                              "--registry", str(tmp_path / "r0.json"), "--name", "t2a"])
    _eval_mod("eval_b").main(["--trades", str(cpath), "--baseline", str(bpath), "--out", str(out1),
                              "--registry", str(tmp_path / "r1.json"), "--name", "t2b",
                              "--equity-curve", str(curve), "--capital", "2500000"])
    j0 = json.loads(out0.with_suffix(".json").read_text(encoding="utf-8"))
    j1 = json.loads(out1.with_suffix(".json").read_text(encoding="utf-8"))
    assert j0["verdict"]["verdict"] == j1["verdict"]["verdict"]
    assert j0["verdict"]["criteria"] == j1["verdict"]["criteria"]
    assert "tier2_portfolio" not in j0 and "tier2_portfolio" in j1
    t2 = j1["tier2_portfolio"]
    assert t2["cagr_pct"] is not None and t2["max_dd_pct"] is not None and t2["sharpe_daily_ann"] is not None
    assert "Tier 2" in out1.read_text(encoding="utf-8") and "Tier 2" not in out0.read_text(encoding="utf-8")
