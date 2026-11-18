"""Round 3 runner (scripts/run_round3.py): guards, fixed settings, EXTRA_LOOKS, train registration, end-to-end.

Synthetic archive and market only (tmp_path). Registry and EXTRA_LOOKS are always throwaway paths here; the real
logs/eval_registry.json is never named by a test. No 2024+ dates.
"""

import importlib.util
import json
from datetime import date
from pathlib import Path

import pytest

from backtester.candidates import PCS, CandidateSpec, get_round3_cell
from backtester.chain_engine import ChainBacktest
from data.nse_fo_archive import NseFoArchive
from strategy_eval import TestRegistry
from tests.test_candidates import E, F, LOT, S, SPOT, _market, _weekdays, _write_world

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def r3():
    spec = importlib.util.spec_from_file_location("run_round3", REPO_ROOT / "scripts" / "run_round3.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ----------------------------------------------------------------------------- argument guards

def test_defaults_are_tier1_at_one_pass_slippage(r3, tmp_path):
    a = r3.parse_args(["--phase", "train", "--out", str(tmp_path / "o")])
    assert a.lots is None and a.slippage == 1.0 and a.capital_mode is False   # main resolves None to 10 (Tier 1)
    assert a.registry == r3.DEFAULT_REGISTRY and a.extra_looks == r3.DEFAULT_EXTRA_LOOKS
    assert a.cell == "all"


def test_holdout_needs_allow_flag_and_allow_flag_needs_holdout(r3, tmp_path):
    with pytest.raises(SystemExit):
        r3.parse_args(["--phase", "holdout", "--out", str(tmp_path)])
    with pytest.raises(SystemExit):
        r3.parse_args(["--phase", "train", "--allow-holdout", "--out", str(tmp_path)])
    a = r3.parse_args(["--phase", "holdout", "--allow-holdout", "--out", str(tmp_path)])
    assert a.allow_holdout is True


def test_capital_mode_needs_one_lot(r3, tmp_path):
    with pytest.raises(SystemExit):
        r3.parse_args(["--phase", "train", "--capital-mode", "--lots", "10", "--out", str(tmp_path)])
    a = r3.parse_args(["--phase", "test", "--capital-mode", "--lots", "1", "--out", str(tmp_path)])
    assert a.capital_mode and a.lots == 1


@pytest.mark.parametrize("bad", ["C1", "D2", "F1", "M4", "PCS_A_k09_w200"])
def test_cell_choices_are_round3_only(r3, tmp_path, bad):
    with pytest.raises(SystemExit):
        r3.parse_args(["--phase", "train", "--cell", bad, "--out", str(tmp_path)])


@pytest.mark.parametrize("cell", ["M1", "M2", "M3", "S1", "T1", "R1", "W1", "all"])
def test_cell_choices_accept_declared_round3_cells(r3, tmp_path, cell):
    assert r3.parse_args(["--phase", "train", "--cell", cell, "--out", str(tmp_path)]).cell == cell


# ----------------------------------------------------------------------------- fixed settings

def test_build_config_fixed_round3_settings_tier1(r3):
    c = get_round3_cell("W1")
    cfg = r3.build_config(c, date(2019, 2, 11), date(2021, 12, 31), lots=None, slippage=1.0, capital_mode=False)
    assert cfg.lots == 10 and cfg.slippage_multiplier == 1.0 and cfg.capital_mode is False
    assert cfg.expiry_brokerage is True and cfg.skip_zero_contract_legs is True
    assert cfg.max_concurrent == 1 and cfg.signal_cadence == "expiry_day"
    assert cfg.cash_settlement is True and cfg.legacy_costs is False and cfg.equity_based_sizing is False
    assert cfg.candidate is c


def test_build_config_tier2_capital_settings(r3):
    c = get_round3_cell("M1")
    cfg = r3.build_config(c, date(2022, 1, 1), date(2023, 12, 31), lots=1, slippage=1.0, capital_mode=True)
    assert cfg.lots == 1 and cfg.capital_mode is True and cfg.capital_rs == 2_500_000.0
    assert cfg.risk_cap_pct == 0.05 and cfg.margin_cap_pct == 0.20 and cfg.kill_dd_pct == 0.20
    assert cfg.equity_based_sizing is True and cfg.expiry_brokerage is True
    assert cfg.candidate.monthly_signal is True


# ----------------------------------------------------------------------------- EXTRA_LOOKS rule

@pytest.mark.parametrize("phase, lots, slip, cap, exists, declared", [
    ("train", 10, 1.0, False, False, True),    # the single declared train run
    ("train", 10, 1.0, False, True, False),    # repeated train run
    ("train", 10, 1.5, False, False, False),   # sensitivity slippage
    ("train", 10, 0.5, False, False, False),
    ("train", 1, 1.0, True, False, False),     # capital mode is not the Tier-1 train run
    ("test", 10, 1.0, False, False, False),    # any test run is logged as an extra look
    ("holdout", 10, 1.0, False, False, False),
])
def test_declared_train_run_rule(r3, phase, lots, slip, cap, exists, declared):
    assert r3.is_declared_train_run(phase=phase, lots=lots, slippage=slip, capital_mode=cap,
                                    cut_exists=exists) is declared


def _patch_world(r3, monkeypatch, cell_fn=None):
    """Synthetic market and archive for the runner; the W1 world of tests/test_round2 (weekly expiries S..E)."""
    days = _weekdays(S, E)
    mk = _market(days, vix=20.0)
    monkeypatch.setattr(r3, "load_market", lambda end, market_start=None: mk)
    if cell_fn is not None:
        monkeypatch.setattr(r3, "get_round3_cell", cell_fn)


def test_extra_look_entry_is_written_before_any_run(r3, tmp_path, monkeypatch):
    extra = tmp_path / "EXTRA_LOOKS.md"
    seen = {}

    def fake_run(self):
        seen["text"] = extra.read_text(encoding="utf-8") if extra.exists() else ""
        return []

    _patch_world(r3, monkeypatch)
    _write_world(tmp_path / "arch", _weekdays(S, E), prices={(F, "PE", 22300.0): 40.0}, index=lambda d: SPOT)
    monkeypatch.setattr(ChainBacktest, "run", fake_run)
    monkeypatch.setitem(r3.PHASE_WINDOWS, "test", (S, E))
    rc = r3.main(["--phase", "test", "--cell", "W1", "--out", str(tmp_path / "o"),
                  "--extra-looks", str(extra), "--registry", str(tmp_path / "reg.json"),
                  "--archive-dir", str(tmp_path / "arch")])
    assert rc == 0
    assert "W1" in seen["text"] and "phase test" in seen["text"]    # entry existed when the run started


def test_declared_train_run_writes_no_extra_look(r3, tmp_path, monkeypatch):
    extra = tmp_path / "EXTRA_LOOKS.md"
    _patch_world(r3, monkeypatch)
    _write_world(tmp_path / "arch", _weekdays(S, E), prices={(F, "PE", 22300.0): 40.0}, index=lambda d: SPOT)
    monkeypatch.setattr(ChainBacktest, "run", lambda self: [])
    monkeypatch.setitem(r3.PHASE_WINDOWS, "train", (S, E))
    rc = r3.main(["--phase", "train", "--cell", "W1", "--out", str(tmp_path / "o"),
                  "--extra-looks", str(extra), "--registry", str(tmp_path / "reg.json"),
                  "--archive-dir", str(tmp_path / "arch")])
    assert rc == 0 and not extra.exists()


# ----------------------------------------------------------------------------- train registration

def _train_file(tmp_path, cell, pnls, lots=10, name="trades"):
    """A trades_<cell>.json with given per-trade net P&L (Rs for `lots`), dates spaced so none overlap."""
    trades = []
    for i, pnl in enumerate(pnls):
        ent = date.fromordinal(date(2019, 3, 1).toordinal() + 10 * i)
        ex = date.fromordinal(ent.toordinal() + 7)
        trades.append({"strategy": cell, "lots": lots, "entry_date": str(ent), "exit_date": str(ex),
                       "fill_date": str(ent), "expiry": str(ex), "signal_date": str(ent), "exit_reason": "expiry",
                       "pnl_net_rs": float(pnl), "pnl_gross_rs": float(pnl), "cost_rs": 0.0, "credit_rs": 1000.0,
                       "max_loss_rs": 25000.0, "entry_vix": 20.0, "hedge_cost_rs": 0.0, "slippage_rs": 0.0,
                       "base_haircut_pct": 0.0, "pricing_source": "chain", "family": "W", "cadence": "weekly"})
    d = tmp_path / name
    d.mkdir(exist_ok=True)
    p = d / f"trades_{cell}.json"
    p.write_text(json.dumps({"variant": f"round3_{cell}_train", "family": "W", "phase": "train",
                             "start": "2019-02-11", "end": "2021-12-31", "lots": lots,
                             "slippage_multiplier": 1.0, "n": len(trades), "trades": trades}), encoding="utf-8")
    return p


KW = dict(start=date(2019, 2, 11), end=date(2021, 12, 31), lots=10, slippage=1.0)


def test_register_train_cut_uses_one_sided_nonoverlap_p_and_no_retro_word(r3, tmp_path):
    f = _train_file(tmp_path, "W1", [5000, 4000, 6000, 3000, 7000, 2000])
    reg_path = tmp_path / "reg.json"
    row = r3.register_train_cut("W1", f, reg_path, **KW)
    assert row["name"] == "ROUND3_train|W1" and row["n"] == 6
    rec = [c for c in json.loads(reg_path.read_text(encoding="utf-8")) if c["name"] == "ROUND3_train|W1"][0]
    assert rec["kind"] == "train" and rec["p_value"] == pytest.approx(row["p_value"])
    assert 0.0 < rec["p_value"] < 1.0
    assert "RETRO" not in rec["detail"].upper()
    assert TestRegistry.load(reg_path).n_cuts == 1


def test_register_refuses_changed_p_for_same_cell_and_leaves_registry_unchanged(r3, tmp_path):
    reg_path = tmp_path / "reg.json"
    f = _train_file(tmp_path, "W1", [5000, 4000, 6000, 3000, 7000, 2000])
    r3.register_train_cut("W1", f, reg_path, **KW)
    before = reg_path.read_text(encoding="utf-8")
    g = _train_file(tmp_path, "W1", [-9000, 4000, -6000, 3000, -7000, 2000], name="other")
    with pytest.raises(ValueError):
        r3.register_train_cut("W1", g, reg_path, **KW)
    assert reg_path.read_text(encoding="utf-8") == before


def test_register_same_cut_twice_is_a_no_op(r3, tmp_path):
    reg_path = tmp_path / "reg.json"
    f = _train_file(tmp_path, "W1", [5000, 4000, 6000])
    r3.register_train_cut("W1", f, reg_path, **KW)
    r3.register_train_cut("W1", f, reg_path, **KW)
    assert TestRegistry.load(reg_path).n_cuts == 1


def test_register_refuses_wrong_lots_file_and_writes_nothing(r3, tmp_path):
    f = _train_file(tmp_path, "W1", [5000, 4000], lots=5)
    with pytest.raises(ValueError):
        r3.register_train_cut("W1", f, tmp_path / "reg.json", **KW)
    assert not (tmp_path / "reg.json").exists()


# ----------------------------------------------------------------------------- end-to-end, synthetic world

def _weekly_pcs_stand_in(cell_id):
    """Stand-in spec for the synthetic world only: a plain weekly PCS under a round-3 cell id (no extra rule)."""
    return CandidateSpec(cell_id, "T", PCS, 1.0, 300.0, "weekly", 13.0, 25.0,
                         strike_basis="signal_close", max_loss_basis="fill_plus_fees")


def test_end_to_end_train_registers_and_test_phase_logs_extra_look(r3, tmp_path, monkeypatch):
    arch_dir = tmp_path / "arch"
    days = _weekdays(S, E)
    prices = {(F, "PE", 22300.0): 40.0, (F, "PE", 22000.0): 15.0}
    _write_world(arch_dir, days, prices=prices, index=lambda d: 22300.0 if d == E else SPOT)
    mk = _market(days, vix=20.0)
    monkeypatch.setattr(r3, "load_market", lambda end, market_start=None: mk)
    monkeypatch.setattr(r3, "get_round3_cell", _weekly_pcs_stand_in)
    monkeypatch.setattr(r3, "ROUND3_CELL_IDS", ("T1",))
    monkeypatch.setitem(r3.PHASE_WINDOWS, "train", (S, E))
    monkeypatch.setitem(r3.PHASE_WINDOWS, "test", (S, E))
    reg = tmp_path / "reg.json"
    extra = tmp_path / "EXTRA_LOOKS.md"
    out = tmp_path / "out"
    common = ["--cell", "T1", "--archive-dir", str(arch_dir), "--out", str(out),
              "--registry", str(reg), "--extra-looks", str(extra)]

    assert r3.main(["--phase", "train", *common]) == 0
    names = [c["name"] for c in json.loads(reg.read_text(encoding="utf-8"))]
    assert names == ["ROUND3_train|T1"]
    assert not extra.exists()                                  # declared train run: no extra look
    assert (out / "trades_T1.json").exists() and (out / "skips_T1.csv").exists()
    payload = json.load(open(out / "trades_T1.json"))
    assert payload["lots"] == 10 and payload["n"] == 1
    # fill_plus_fees: W - credit at the fill (after slippage) + fees, so it is above the settle-basis (W - settle credit)
    assert payload["trades"][0]["max_loss_rs"] > (300.0 - 25.0) * LOT * 10
    assert payload["trades"][0]["cost_rs"] > 0                 # expiry brokerage and fees are charged

    before = reg.read_text(encoding="utf-8")
    assert r3.main(["--phase", "test", *common]) == 0
    assert reg.read_text(encoding="utf-8") == before           # test phase never writes the registry
    assert "T1" in extra.read_text(encoding="utf-8")           # extra look logged before the run
