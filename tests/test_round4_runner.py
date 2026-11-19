"""Round 4 runner (scripts/run_round4.py): guards, model refusals, declared-run rule, EXTRA_LOOKS ordering.

Synthetic archive and market only (tmp_path), stub pickles. The real registry and archive are never touched.
"""

import importlib.util
import json
from pathlib import Path

import joblib
import pytest

from backtester.chain_engine import ChainBacktest
from tests.test_candidates import E, F, S, SPOT, _market, _weekdays, _write_world

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def r4():
    spec = importlib.util.spec_from_file_location("run_round4", REPO_ROOT / "scripts" / "run_round4.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _stub(tmp_path, train_end, name="m.pkl"):
    p = tmp_path / name
    md = None if train_end is None else {"train_end": train_end}
    joblib.dump({"period_metadata": md}, p)
    return p


# ----------------------------------------------------------------------------- arg guards

def test_defaults_are_tier1_at_03_slippage_gate_on(r4, tmp_path):
    a = r4.parse_args(["--phase", "train", "--out", str(tmp_path)])
    assert a.slippage == 0.3 and r4.PASS_SLIPPAGE == 0.3 and a.lots is None
    assert a.no_gate is False and a.cell == "all"
    assert a.registry == r4.DEFAULT_REGISTRY and a.extra_looks == r4.DEFAULT_EXTRA_LOOKS


def test_fixed_exit_model_path(r4):
    assert r4.EXIT_MODEL_PATH == REPO_ROOT / "logs" / "ml_cutoff_2021" / "exit_model.pkl"


def test_holdout_guard(r4, tmp_path):
    with pytest.raises(SystemExit):
        r4.parse_args(["--phase", "holdout", "--out", str(tmp_path)])
    with pytest.raises(SystemExit):
        r4.parse_args(["--phase", "train", "--allow-holdout", "--out", str(tmp_path)])
    assert r4.parse_args(["--phase", "holdout", "--allow-holdout", "--out", str(tmp_path)]).allow_holdout


def test_capital_mode_needs_one_lot(r4, tmp_path):
    with pytest.raises(SystemExit):
        r4.parse_args(["--phase", "train", "--capital-mode", "--lots", "10", "--out", str(tmp_path)])


@pytest.mark.parametrize("bad", ["M1", "G_M4", "C1"])
def test_cell_choices_are_round4_only(r4, tmp_path, bad):
    with pytest.raises(SystemExit):
        r4.parse_args(["--phase", "train", "--cell", bad, "--out", str(tmp_path)])


def test_exit_model_override_only_with_no_gate(r4, tmp_path):
    other = tmp_path / "x.pkl"
    with pytest.raises(SystemExit):
        r4.parse_args(["--phase", "train", "--exit-model", str(other), "--out", str(tmp_path)])
    assert r4.parse_args(["--phase", "train", "--no-gate", "--exit-model", str(other), "--out", str(tmp_path)]).no_gate
    assert r4.parse_args(["--phase", "train", "--exit-model", str(r4.EXIT_MODEL_PATH), "--out", str(tmp_path)])


@pytest.mark.parametrize("sub", ["data/.cache/exit_model.pkl", "data/.cache_seed/exit_model.pkl"])
def test_leaky_path_refused_even_with_no_gate(r4, tmp_path, sub):
    p = REPO_ROOT / sub
    with pytest.raises(SystemExit):
        r4.parse_args(["--phase", "train", "--no-gate", "--exit-model", str(p), "--out", str(tmp_path)])
    with pytest.raises(ValueError, match="refused"):
        r4.validate_exit_model(p)


# ----------------------------------------------------------------------------- model validation

def test_validate_accepts_train_end_2021(r4, tmp_path):
    p = _stub(tmp_path, "2021-12-31")
    assert r4.validate_exit_model(p) == p


@pytest.mark.parametrize("te", ["2022-01-01", "2026-10-12"])
def test_validate_refuses_late_train_end(r4, tmp_path, te):
    with pytest.raises(ValueError, match="after"):
        r4.validate_exit_model(_stub(tmp_path, te))


def test_validate_refuses_missing_metadata_or_file(r4, tmp_path):
    with pytest.raises(ValueError, match="train_end"):
        r4.validate_exit_model(_stub(tmp_path, None))
    with pytest.raises(ValueError, match="not found"):
        r4.validate_exit_model(tmp_path / "nope.pkl")


def test_main_refuses_leaky_model_before_writing_anything(r4, tmp_path, monkeypatch):
    monkeypatch.setattr(r4, "EXIT_MODEL_PATH", _stub(tmp_path, "2026-01-01"))
    extra = tmp_path / "EXTRA_LOOKS.md"
    rc = r4.main(["--phase", "test", "--cell", "G_W1", "--out", str(tmp_path / "o"), "--extra-looks", str(extra),
                  "--registry", str(tmp_path / "reg.json")])
    assert rc == 2 and not extra.exists() and not (tmp_path / "reg.json").exists()


# ----------------------------------------------------------------------------- declared-run rule

@pytest.mark.parametrize("phase, lots, slip, cap, exists, gate, declared", [
    ("train", 10, 0.3, False, False, True, True),
    ("train", 10, 0.3, False, True, True, False),     # repeated
    ("train", 10, 1.0, False, False, True, False),    # sensitivity
    ("train", 1, 0.3, True, False, True, False),      # capital mode
    ("train", 10, 0.3, False, False, False, False),   # --no-gate
    ("test", 10, 0.3, False, False, True, False),
    ("holdout", 10, 0.3, False, False, True, False),
])
def test_declared_train_run_rule(r4, phase, lots, slip, cap, exists, gate, declared):
    assert r4.is_declared_train_run(phase=phase, lots=lots, slippage=slip, capital_mode=cap,
                                    cut_exists=exists, gate_on=gate) is declared


# ----------------------------------------------------------------------------- EXTRA_LOOKS ordering, registration

def _setup(r4, monkeypatch, tmp_path, train_end="2021-12-31"):
    days = _weekdays(S, E)
    mk = _market(days, vix=20.0)
    monkeypatch.setattr(r4, "load_market", lambda end, market_start=None: mk)
    monkeypatch.setattr(r4, "EXIT_MODEL_PATH", _stub(tmp_path, train_end))
    monkeypatch.setattr(r4, "build_gate", lambda path, end: (lambda ctx: (False, 0.0)))
    _write_world(tmp_path / "arch", days, prices={(F, "PE", 22300.0): 40.0}, index=lambda d: SPOT)
    monkeypatch.setitem(r4.PHASE_WINDOWS, "test", (S, E))
    monkeypatch.setitem(r4.PHASE_WINDOWS, "train", (S, E))


def _argv(tmp_path, phase, *more):
    return ["--phase", phase, "--cell", "G_W1", "--out", str(tmp_path / "o"),
            "--extra-looks", str(tmp_path / "EXTRA_LOOKS.md"), "--registry", str(tmp_path / "reg.json"),
            "--archive-dir", str(tmp_path / "arch"), *more]


@pytest.mark.parametrize("phase, more", [("test", []), ("train", ["--no-gate"]), ("train", ["--slippage", "1.0"])])
def test_extra_look_written_before_run(r4, tmp_path, monkeypatch, phase, more):
    extra = tmp_path / "EXTRA_LOOKS.md"
    seen = {}

    def fake_run(self):
        seen["text"] = extra.read_text(encoding="utf-8") if extra.exists() else ""
        return []

    _setup(r4, monkeypatch, tmp_path)
    monkeypatch.setattr(ChainBacktest, "run", fake_run)
    assert r4.main(_argv(tmp_path, phase, *more)) == 0
    assert "G_W1" in seen["text"] and f"phase={phase}" in seen["text"]


def test_declared_train_run_no_extra_look_registers_with_gate_header(r4, tmp_path, monkeypatch):
    _setup(r4, monkeypatch, tmp_path)
    monkeypatch.setattr(ChainBacktest, "run", lambda self: [])
    assert r4.main(_argv(tmp_path, "train")) == 0
    assert not (tmp_path / "EXTRA_LOOKS.md").exists()
    hdr = json.load(open(tmp_path / "o" / "trades_G_W1.json"))
    assert hdr["gate"] is True and hdr["slippage_multiplier"] == 0.3 and hdr["n_ml_exits"] == 0
    names = [c["name"] for c in json.loads((tmp_path / "reg.json").read_text(encoding="utf-8"))]
    assert names == ["ROUND4_train|G_W1"]


def test_gate_passed_to_config_only_when_on(r4, tmp_path, monkeypatch):
    _setup(r4, monkeypatch, tmp_path)
    seen = []
    orig = ChainBacktest.__init__

    def init(self, arch, market, cfg):
        seen.append(cfg.exit_gate)
        orig(self, arch, market, cfg)

    monkeypatch.setattr(ChainBacktest, "__init__", init)
    monkeypatch.setattr(ChainBacktest, "run", lambda self: [])
    assert r4.main(_argv(tmp_path, "test")) == 0
    assert r4.main(_argv(tmp_path, "test", "--no-gate")) == 0
    assert seen[0] is not None and seen[1] is None
