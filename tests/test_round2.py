"""Round 2 (docs/preregistration_round2.md): RV20 entry gate, declared cells, round-2 runner.

Synthetic data only (no archive, no network, no dates after 2023-12-31 touched). The runner test monkeypatches
the market loader and writes a tmp archive. No registry or ledger is written.
"""

import importlib.util
import json
import math
from dataclasses import replace
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backtester.candidates import (
    CALL_CREDIT_SPREAD, IRON_CONDOR, PCS, CandidateSpec, rv20_annualised, rv20_gap_filter,
)
from backtester.chain_engine import ChainBacktest, ChainConfig
from data.nse_fo_archive import NseFoArchive
from tests.test_candidate_engine_ext import _cfg_spec, _spec
from tests.test_candidates import E, F, S, _a_world, _market, _run, _weekdays

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
