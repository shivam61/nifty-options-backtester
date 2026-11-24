"""Tests for main.py mode wiring: eval-chain is an accepted mode, and validate prints the
NON-EVIDENTIAL banner. Heavy dependencies (model validator, strategy evolver, market data) are
replaced with fakes so nothing expensive runs.
"""

import sys
import types
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import main  # noqa: E402


def test_eval_chain_is_accepted_mode(monkeypatch):
    calls = []

    def fake_run_eval_chain(args):
        calls.append(args)
        return 0

    monkeypatch.setattr(main, "run_eval_chain", fake_run_eval_chain)
    monkeypatch.setattr(sys, "argv", [
        "main.py", "--mode", "eval-chain", "--trades", "cand.csv",
        "--baseline", "base.csv", "--name", "candX",
    ])
    with pytest.raises(SystemExit) as exc:
        main.main()
    assert exc.value.code == 0
    assert len(calls) == 1
    assert calls[0].trades == Path("cand.csv")
    assert calls[0].baseline == Path("base.csv")
    assert calls[0].name == "candX"


def test_eval_chain_requires_trades(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["main.py", "--mode", "eval-chain"])
    with pytest.raises(SystemExit) as exc:
        main.main()
    assert exc.value.code == 2


def test_validate_prints_non_evidential_banner(monkeypatch, capsys):
    class _FakeFetcher:
        def __init__(self, start, end):
            pass

        def build_combined_dataset(self):
            idx = pd.date_range("2024-01-01", periods=5, freq="B")
            return pd.DataFrame({"x": range(5)}, index=idx)

    class _FakeEvolver:
        @staticmethod
        def load_from_cache():
            return {"dummy": True}

    validated = {}

    def fake_run_full_validation(data, **kwargs):
        validated["n_permutations"] = kwargs.get("n_permutations")

    fake_validator_mod = types.ModuleType("models.model_validator")
    fake_validator_mod.run_full_validation = fake_run_full_validation
    fake_evolver_mod = types.ModuleType("models.strategy_evolver")
    fake_evolver_mod.StrategyEvolver = _FakeEvolver
    monkeypatch.setitem(sys.modules, "models.model_validator", fake_validator_mod)
    monkeypatch.setitem(sys.modules, "models.strategy_evolver", fake_evolver_mod)
    monkeypatch.setattr(main, "MarketDataFetcher", _FakeFetcher)

    from config import BacktestConfig
    main.run_validate(BacktestConfig())

    out = capsys.readouterr().out
    assert validated["n_permutations"] == 20
    assert out.count(main.VALIDATE_NON_EVIDENTIAL_NOTE) == 2  # start banner + final summary
    assert "NON-EVIDENTIAL" in out
    assert "--mode eval-chain" in out
