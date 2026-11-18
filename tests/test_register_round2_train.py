"""Retroactive registration of the six round-2 train cells (audit fix 5). Throwaway registry paths only.

Synthetic trade files in tmp_path. The real logs/eval_registry.json is never opened by these tests.
"""

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

from strategy_eval import TestRegistry, load_trades
from strategy_eval.stats import nonoverlap_ttest
from strategy_eval.stress import per_lot

REPO = Path(__file__).resolve().parents[1]
CELLS = ("C1", "C2", "D1", "D2", "E1", "E2")


def _mod():
    spec = importlib.util.spec_from_file_location("register_round2_train", REPO / "scripts" / "register_round2_train.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _trade(i, pnl, lots=10):
    month = 1 + (i // 4) % 12
    day = 1 + (i % 4) * 7
    return {"strategy": "T", "entry_date": f"2020-{month:02d}-{day:02d}", "exit_date": f"2020-{month:02d}-{day + 4:02d}",
            "expiry": f"2020-{month:02d}-{day + 4:02d}", "lots": lots, "credit_rs": 1000.0, "max_loss_rs": 5000.0,
            "pnl_gross_rs": pnl + 10.0, "cost_rs": 10.0, "pnl_net_rs": pnl, "exit_reason": "expiry",
            "entry_vix": 15.0, "hedge_cost_rs": 0.0, "slippage_rs": 5.0, "base_haircut_pct": 0.0,
            "pricing_source": "chain"}


def _write_cells(d: Path, phase="train", start="2019-02-11", end="2021-12-31", lots=10, slip=1.0, cells=CELLS):
    d.mkdir(parents=True, exist_ok=True)
    for j, c in enumerate(cells):
        pnls = [200.0 + 30 * ((i * 7 + j) % 5) - 60 for i in range(40)]
        trades = [_trade(i, p, lots=lots) for i, p in enumerate(pnls)]
        obj = {"variant": f"round2_{c}_{phase}", "family": "X", "phase": phase, "start": start, "end": end,
               "lots": lots, "slippage_multiplier": slip, "n": len(trades), "trades": trades}
        (d / f"trades_{c}.json").write_text(json.dumps(obj), encoding="utf-8")
    return d


def _registry_rows(path: Path) -> dict:
    return {c["name"]: c for c in json.loads(path.read_text(encoding="utf-8"))}


def test_registers_six_train_cuts_with_names_kind_and_retroactive_note(tmp_path):
    mod = _mod()
    trades = _write_cells(tmp_path / "train")
    reg_path = tmp_path / "scratch_registry.json"
    rows = mod.register_round2_train(trades, reg_path)
    assert [r["name"] for r in rows] == [f"ROUND2_train|{c}" for c in CELLS]
    cuts = _registry_rows(reg_path)
    assert len(cuts) == 6
    for c in CELLS:
        rec = cuts[f"ROUND2_train|{c}"]
        assert rec["kind"] == "train"
        assert rec["p_value"] is not None and 0.0 < rec["p_value"] <= 1.0
        assert "RETROACTIVE REGISTRATION" in rec["detail"]
        assert "lots=10" in rec["detail"] and "1x" in rec["detail"]


def test_p_value_is_the_harness_nonoverlap_test_on_the_same_trades(tmp_path):
    mod = _mod()
    trades = _write_cells(tmp_path / "train")
    reg_path = tmp_path / "r.json"
    mod.register_round2_train(trades, reg_path)
    df = load_trades(trades / "trades_C2.json")
    expect = nonoverlap_ttest(per_lot(df, "pnl_net_rs"), df["entry_date"], df["exit_date"])["p_one_sided"]
    got = _registry_rows(reg_path)["ROUND2_train|C2"]["p_value"]
    assert np.isfinite(got)
    assert got == pytest.approx(expect)


def test_refuses_a_missing_cell_and_writes_nothing(tmp_path):
    mod = _mod()
    trades = _write_cells(tmp_path / "train", cells=("C1", "C2", "D1", "D2", "E1"))  # E2 missing
    reg_path = tmp_path / "r.json"
    with pytest.raises(ValueError, match="missing round-2 train file"):
        mod.register_round2_train(trades, reg_path)
    assert not reg_path.exists()


def test_refuses_a_non_train_file_and_wrong_lots_or_slippage(tmp_path):
    mod = _mod()
    t1 = _write_cells(tmp_path / "test_phase", phase="test", start="2022-01-01", end="2023-12-31")
    with pytest.raises(ValueError, match="not a train-window file"):
        mod.register_round2_train(t1, tmp_path / "a.json")
    t2 = _write_cells(tmp_path / "wrong_lots", lots=1)
    with pytest.raises(ValueError, match="expected lots=10"):
        mod.register_round2_train(t2, tmp_path / "b.json")
    t3 = _write_cells(tmp_path / "wrong_slip", slip=1.5)
    with pytest.raises(ValueError, match="expected lots=10"):
        mod.register_round2_train(t3, tmp_path / "c.json")
    for name in ("a.json", "b.json", "c.json"):
        assert not (tmp_path / name).exists()


def test_rerun_is_a_noop_and_a_changed_trade_file_is_refused_by_the_registry(tmp_path):
    mod = _mod()
    trades = _write_cells(tmp_path / "train")
    reg_path = tmp_path / "r.json"
    mod.register_round2_train(trades, reg_path)
    before = reg_path.read_text(encoding="utf-8")
    mod.register_round2_train(trades, reg_path)
    assert reg_path.read_text(encoding="utf-8") == before
    # the same cut name with different trades would move p: the registry refuses it
    other = _write_cells(tmp_path / "other")
    raw = json.loads((other / "trades_C1.json").read_text(encoding="utf-8"))
    raw["trades"] = [dict(t, pnl_net_rs=t["pnl_net_rs"] * 3.0) for t in raw["trades"]]
    (other / "trades_C1.json").write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError):
        mod.register_round2_train(other, reg_path)


def test_existing_round1_cuts_are_untouched(tmp_path):
    mod = _mod()
    reg_path = tmp_path / "r.json"
    reg = TestRegistry.open(reg_path)
    reg.add("PREG_20261117_train|PCS_A_k09_w200", 0.35, kind="train", detail="round 1")
    before = _registry_rows(reg_path)["PREG_20261117_train|PCS_A_k09_w200"]
    mod.register_round2_train(_write_cells(tmp_path / "train"), reg_path)
    after = _registry_rows(reg_path)
    assert after["PREG_20261117_train|PCS_A_k09_w200"] == before
    assert len(after) == 1 + len(CELLS)


def test_cli_writes_only_to_the_given_registry(tmp_path, capsys):
    mod = _mod()
    trades = _write_cells(tmp_path / "train")
    reg_path = tmp_path / "scratch.json"
    assert mod.main(["--trades-dir", str(trades), "--registry", str(reg_path)]) == 0
    assert len(_registry_rows(reg_path)) == 6
    assert "ROUND2_train|C1" in capsys.readouterr().out
