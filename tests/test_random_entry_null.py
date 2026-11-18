"""Mean-zero bootstrap null (audit fix 6). Synthetic trades only; no archive, no registry, no 2024+ dates.

These tests pin what the null does: a one-sided test of mean > 0 on centred resamples, with a fixed seed. They
also pin what it does NOT do: it is not an entry-timing test, and it refuses windows past 2023-12-31.
"""

import importlib.util
import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]


def _mod():
    spec = importlib.util.spec_from_file_location("random_entry_null", REPO / "scripts" / "random_entry_null.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _trade_file(path: Path, pnls, start=date(2020, 1, 6), lots=10, step_days=7):
    recs = []
    for i, p in enumerate(pnls):
        d = start + timedelta(days=i * step_days)
        out = d + timedelta(days=4)
        recs.append({"strategy": "T", "entry_date": str(d), "exit_date": str(out), "expiry": str(out),
                     "lots": lots, "credit_rs": 1000.0,
                     "max_loss_rs": 5000.0, "pnl_gross_rs": p * lots + 10.0, "cost_rs": 10.0,
                     "pnl_net_rs": p * lots,
                     "exit_reason": "expiry", "entry_vix": 15.0, "hedge_cost_rs": 0.0, "slippage_rs": 5.0,
                     "base_haircut_pct": 0.0, "pricing_source": "chain"})
    path.write_text(json.dumps({"trades": recs}), encoding="utf-8")
    return path


def test_zero_mean_sample_gives_a_middling_p_and_symmetric_null(tmp_path):
    mod = _mod()
    rng = np.random.default_rng(1)
    x = rng.normal(0.0, 100.0, size=200)
    x = x - x.mean()                     # exactly zero mean
    res = mod.mean_zero_bootstrap(x, n_boot=10_000, seed=20261111)
    assert res["observed_mean_per_lot"] == pytest.approx(0.0, abs=1e-9)
    assert 0.3 < res["p_one_sided"] < 0.7
    assert res["null_p5"] < 0.0 < res["null_p95"]
    assert res["null_p5"] == pytest.approx(-res["null_p95"], rel=0.15)


def test_strong_positive_mean_gives_a_tiny_p(tmp_path):
    mod = _mod()
    rng = np.random.default_rng(2)
    x = 300.0 + rng.normal(0.0, 50.0, size=120)
    res = mod.mean_zero_bootstrap(x, n_boot=10_000, seed=20261111)
    assert res["observed_mean_per_lot"] > 290
    assert res["p_one_sided"] <= 1.0 / 10_001 + 1e-12    # never 0: the +1 correction
    assert res["n"] == 120 and res["n_boot"] == 10_000 and res["seed"] == 20261111


def test_negative_mean_gives_p_near_one(tmp_path):
    mod = _mod()
    x = np.array([-100.0, -120.0, -80.0, -90.0, -110.0, -95.0, -105.0, -100.0])
    res = mod.mean_zero_bootstrap(x, n_boot=2000, seed=7)
    assert res["p_one_sided"] > 0.99


def test_same_seed_same_answer_and_default_seed_is_the_pre_registered_one(tmp_path):
    mod = _mod()
    x = np.linspace(-50.0, 150.0, 40)
    a = mod.mean_zero_bootstrap(x, n_boot=3000, seed=20261111)
    b = mod.mean_zero_bootstrap(x, n_boot=3000, seed=20261111)
    c = mod.mean_zero_bootstrap(x, n_boot=3000, seed=99)
    assert a == b
    assert a["p_one_sided"] != c["p_one_sided"] or a["null_p5"] != c["null_p5"]
    assert mod.DEFAULT_SEED == 20261111 and mod.DEFAULT_N_BOOT == 10_000


def test_too_few_or_non_finite_trades_are_refused():
    mod = _mod()
    with pytest.raises(ValueError):
        mod.mean_zero_bootstrap([1.0])
    with pytest.raises(ValueError):
        mod.mean_zero_bootstrap([1.0, float("nan"), 2.0])


def test_window_keeps_only_entries_in_range(tmp_path):
    mod = _mod()
    # 6 trades from 2020-01-06 weekly; window covers only the first three
    f = _trade_file(tmp_path / "t.json", [10.0, 20.0, 30.0, -500.0, -500.0, -500.0])
    from strategy_eval import load_trades
    df = load_trades(f)
    pl = mod.window_per_lot(df, date(2020, 1, 1), date(2020, 1, 20))
    assert list(np.round(pl, 6)) == [10.0, 20.0, 30.0]


def test_run_null_refuses_any_window_past_the_development_end(tmp_path):
    mod = _mod()
    f = _trade_file(tmp_path / "t.json", [10.0, 20.0, 30.0])
    with pytest.raises(ValueError, match="2024|2023-12-31"):
        mod.run_null(f, date(2020, 1, 1), date(2024, 1, 2))
    with pytest.raises(ValueError):
        mod.run_null(f, date(2021, 1, 2), date(2020, 1, 1))


def test_run_null_end_to_end_on_a_chain_style_file(tmp_path):
    mod = _mod()
    f = _trade_file(tmp_path / "t.json", [50.0 + (i % 5) * 10.0 for i in range(60)])
    res = mod.run_null(f, date(2020, 1, 1), date(2021, 12, 31), n_boot=2000)
    assert res["n"] == 60
    assert res["observed_mean_per_lot"] == pytest.approx(70.0)   # mean of 50,60,70,80,90
    assert res["p_one_sided"] < 0.01
    assert "NOT an entry-timing test" in mod.__doc__


def test_cli_refuses_holdout_window_and_has_no_allow_holdout_flag(tmp_path, capsys):
    mod = _mod()
    f = _trade_file(tmp_path / "t.json", [10.0, 20.0, 30.0])
    assert mod.main(["--trades", str(f), "--start", "2020-01-01", "--end", "2024-06-30"]) == 2
    with pytest.raises(SystemExit):
        mod.main(["--trades", str(f), "--allow-holdout"])
