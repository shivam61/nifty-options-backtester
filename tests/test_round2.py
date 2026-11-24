"""Round 2 (docs/preregistration_round2.md): RV20 entry gate, declared cells, round-2 runner.

Synthetic data only (no archive, no network, no dates after 2023-12-31 touched). The runner test monkeypatches
the market loader and writes a tmp archive. No registry or ledger is written.
"""

import importlib.util
import json
import math
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backtester.candidates import IRON_CONDOR, PCS, CandidateSpec, rv20_annualised, rv20_gap_filter
from backtester.chain_engine import ChainBacktest, ChainConfig
from data.nse_fo_archive import NseFoArchive
from tests.test_candidate_engine_ext import _cfg_spec, _spec
from tests.test_candidates import E, F, LOT, S, SPOT, _a_world, _market, _run, _weekdays, _write_world

REPO = Path(__file__).resolve().parents[1]


def _alt_closes(n, step=0.01, start=date(2025, 1, 1)):
    """n closes whose daily log returns alternate +step, -step (sample stdev of 20 returns = step*sqrt(20/19))."""
    logs = [0.0]
    for i in range(1, n):
        logs.append(logs[-1] + (step if i % 2 == 1 else -step))
    idx = pd.bdate_range(start, periods=n)
    return pd.Series(100.0 * np.exp(logs), index=idx, name="nifty_close")


# ----------------------------------------------------------------------------- RV20 helper (Section 3)

def test_rv20_matches_hand_value_on_alternating_returns():
    # 20 returns of +/-0.01: sample variance 0.002 / 19, annualised x sqrt(252), in percent: 16.287
    closes = _alt_closes(21)
    sig = closes.index[-1].date()
    assert rv20_annualised(closes, sig) == pytest.approx(0.01 * math.sqrt(20 / 19) * math.sqrt(252) * 100, abs=1e-9)
    assert rv20_annualised(closes, sig) == pytest.approx(16.287, abs=0.001)


def test_rv20_needs_21_closes_else_nan():
    closes = _alt_closes(20)
    assert math.isnan(rv20_annualised(closes, closes.index[-1].date()))


def test_rv20_nan_inside_window_is_nan():
    closes = _alt_closes(30)
    closes.iloc[-5] = np.nan
    assert math.isnan(rv20_annualised(closes, closes.index[-1].date()))


def test_rv20_uses_only_closes_up_to_and_including_signal_day():
    closes = _alt_closes(40)
    sig = closes.index[25].date()
    base = rv20_annualised(closes, sig)
    assert math.isfinite(base)
    # the same value from the truncated series (up to S inclusive)
    assert base == pytest.approx(rv20_annualised(closes.iloc[:26], sig))
    # closes after S are irrelevant
    later = closes.copy()
    later.iloc[26:] = np.linspace(1.0, 50000.0, len(later) - 26)
    assert rv20_annualised(later, sig) == pytest.approx(base)


def test_rv20_gap_filter_thresholds_vix_minus_rv_and_returns_none_without_history():
    closes = _alt_closes(40)
    sig = closes.index[25]
    rv = rv20_annualised(closes, sig.date())
    f2 = rv20_gap_filter(closes, 2.0)
    assert f2(pd.Series({"vix": rv + 2.0}, name=sig)) is True      # gap exactly g is in
    assert f2(pd.Series({"vix": rv + 1.9}, name=sig)) is False
    assert rv20_gap_filter(closes, 4.0)(pd.Series({"vix": rv + 1.9}, name=sig)) is False
    short = _alt_closes(10)
    assert rv20_gap_filter(short, 2.0)(pd.Series({"vix": 20.0}, name=short.index[-1])) is None


# ----------------------------------------------------------------------------- spec field and engine wiring

def test_rv20_gap_field_defaults_off_and_must_be_finite():
    assert _spec().rv20_gap_min is None
    with pytest.raises(ValueError):
        _spec(rv20_gap_min=float("nan"))


def _with_history(tmp_path):
    """Archive from S (test world); market calendar starts 40 calendar days earlier so RV20 is defined on S."""
    days, _ = _a_world(tmp_path)
    hist = _weekdays(date(2024, 11, 20), E)
    return days, _market(hist)


def test_rv20_gate_on_spec_blocks_low_gap_and_passes_high_gap(tmp_path):
    days, mk = _with_history(tmp_path)      # nifty_close constant -> RV20 = 0, gap = VIX 20
    bt, trades = _run(tmp_path, days, mk, _cfg_spec(_spec(rv20_gap_min=2.0), S, E))
    assert len(trades) == 1 and "entry_filter" not in bt.skips
    bt, trades = _run(tmp_path, days, mk, _cfg_spec(_spec(rv20_gap_min=21.0), S, E))
    assert trades == [] and bt.skips["entry_filter"] >= 1


def test_rv20_gate_without_history_skips_as_missing_data(tmp_path):
    days, mk = _with_history(tmp_path)
    bt, trades = _run(tmp_path, days, mk.iloc[-8:], _cfg_spec(_spec(rv20_gap_min=2.0), S, E))
    assert trades == [] and bt.skips["missing_data"] >= 1 and "entry_filter" not in bt.skips


def test_rv20_gate_and_explicit_entry_filter_together_are_rejected(tmp_path):
    days, mk = _a_world(tmp_path)
    arch = NseFoArchive(archive_dir=str(tmp_path))
    with pytest.raises(ValueError):
        ChainBacktest(arch, mk, _cfg_spec(_spec(rv20_gap_min=2.0), S, E,
                                          candidate_entry_filter=lambda row: True))


# ----------------------------------------------------------------------------- declared cells (Section 3 table)

def test_round2_cells_are_exactly_the_declared_six_and_f_is_not_declared():
    from backtester.candidates import ROUND2_CELL_IDS, get_round2_cell
    assert ROUND2_CELL_IDS == ("C1", "C2", "D1", "D2", "E1", "E2")
    with pytest.raises(KeyError):
        get_round2_cell("F1")      # combiner: built only after train, never declared or run here
    with pytest.raises(KeyError):
        get_round2_cell("C3")


# (cell, family, structure, width, vix_lo, vix_hi, profit_target_pct, stop_loss_x, rv20_gap_min) per Section 3
_DOC_TABLE = {
    "C1": ("C", PCS, 300.0, 13.0, 25.0, 50.0, 2.0, None),
    "C2": ("C", PCS, 300.0, 13.0, 25.0, 75.0, 1.5, None),
    "D1": ("D", IRON_CONDOR, 300.0, 16.0, 25.0, 50.0, 2.0, None),
    "D2": ("D", IRON_CONDOR, 300.0, 16.0, 25.0, None, None, None),
    "E1": ("E", PCS, 300.0, 13.0, 25.0, None, None, 2.0),
    "E2": ("E", PCS, 300.0, 13.0, 25.0, None, None, 4.0),
}


@pytest.mark.parametrize("cell_id", sorted(_DOC_TABLE))
def test_each_round2_cell_matches_the_doc_table(cell_id):
    from backtester.candidates import get_round2_cell
    family, structure, width, vlo, vhi, pt, sl, rv = _DOC_TABLE[cell_id]
    c = get_round2_cell(cell_id)
    assert c.cell_id == cell_id and c.family == family and c.structure == structure
    assert c.k == 1.0 and c.width == width and c.cadence == "weekly"
    assert (c.vix_lo, c.vix_hi) == (vlo, vhi)
    assert c.profit_target_pct == pt and c.stop_loss_x == sl and c.rv20_gap_min == rv


def test_round2_cells_are_disjoint_from_round1_declared_grid():
    from backtester.candidates import CELLS, ROUND2_CELLS
    assert not set(ROUND2_CELLS) & set(CELLS)


# ----------------------------------------------------------------------------- runner (synthetic only)

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def r2(monkeypatch):
    spec = importlib.util.spec_from_file_location("run_round2", REPO_ROOT / "scripts" / "run_round2.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_runner_fixed_settings_for_tier1_and_tier2(r2):
    from backtester.candidates import get_round2_cell
    c = get_round2_cell("C1")
    t1 = r2.build_config(c, date(2019, 2, 11), date(2021, 12, 31), lots=None, slippage=1.0, capital_mode=False)
    assert t1.lots == 10 and t1.slippage_multiplier == 1.0 and t1.capital_mode is False
    assert t1.skip_zero_contract_legs is True and t1.max_concurrent == 1
    assert t1.signal_cadence == "expiry_day" and t1.equity_based_sizing is False
    assert t1.candidate is c and t1.cash_settlement is True and t1.legacy_costs is False
    t2 = r2.build_config(c, date(2022, 1, 1), date(2023, 12, 31), lots=None, slippage=1.0, capital_mode=True)
    assert t2.lots == 1 and t2.capital_mode is True and t2.capital_rs == 2_500_000.0
    assert t2.equity_based_sizing is True and t2.risk_cap_pct == 0.05 and t2.margin_cap_pct == 0.20
    assert t2.kill_dd_pct == 0.20 and t2.skip_zero_contract_legs is True and t2.max_concurrent == 1


def test_runner_slippage_default_is_one_and_capital_needs_one_lot(r2):
    args = r2.parse_args(["--phase", "train", "--out", "x"])
    assert args.slippage == 1.0 and args.lots is None and args.capital_mode is False
    with pytest.raises(SystemExit):
        r2.main(["--phase", "train", "--capital-mode", "--lots", "10", "--out", "x"])


def test_runner_holdout_refuses_without_allow_flag_and_flag_needs_holdout_phase(r2, tmp_path):
    with pytest.raises(SystemExit):
        r2.main(["--phase", "holdout", "--cell", "C1", "--out", str(tmp_path / "o")])
    with pytest.raises(SystemExit):
        r2.main(["--phase", "train", "--allow-holdout", "--cell", "C1", "--out", str(tmp_path / "o")])


def test_runner_rejects_f_and_round1_cells(r2, tmp_path):
    for bad in ("F1", "PCS_A_k09_w200"):
        with pytest.raises(SystemExit):
            r2.main(["--phase", "train", "--cell", bad, "--out", str(tmp_path / "o")])


def test_runner_end_to_end_on_synthetic_archive_writes_tables_only(r2, tmp_path, monkeypatch):
    from strategy_eval.schema import read_normalized
    arch_dir = tmp_path / "arch"
    days = _weekdays(S, E)
    prices = {(F, "PE", 22300.0): 40.0, (F, "PE", 22000.0): 15.0}
    _write_world(arch_dir, days, prices=prices, index=lambda d: 22300.0 if d == E else SPOT)
    mk = _market(days, vix=20.0)
    monkeypatch.setitem(r2.PHASE_WINDOWS, "train", (S, E))
    monkeypatch.setattr(r2, "load_market", lambda end, market_start=None: mk)
    out = tmp_path / "out"
    rc = r2.main(["--phase", "train", "--cell", "C1", "--archive-dir", str(arch_dir), "--out", str(out)])
    assert rc == 0
    payload = json.load(open(out / "trades_C1.json"))
    assert payload["n"] == 1 and payload["lots"] == 10 and payload["family"] == "C"
    t = payload["trades"][0]
    assert t["strategy"] == "C1" and t["lots"] == 10
    assert read_normalized(out / "trades_C1.json")["max_loss_rs"].iloc[0] == pytest.approx((300.0 - 25.0) * LOT * 10)
    # outputs: trade table and skip table only, no registry or ledger
    assert sorted(p.name for p in out.iterdir()) == ["skips_C1.csv", "trades_C1.json"]
