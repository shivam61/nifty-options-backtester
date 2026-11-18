"""Opt-in strike basis (audit fix 1): CandidateSpec.strike_basis in {'fill_close', 'signal_close'}.

'fill_close' (default) sizes sigma_T and the strike targets on the F-day NIFTY close, the historical behaviour.
'signal_close' sizes them on the NIFTY close of the signal day S, which is known at entry. Legs are still
priced at F settle and DTE / expiry selection is still taken from F. Synthetic archive only (tmp_path).
"""

from datetime import date

import pytest

from backtester.candidates import CandidateSpec, get_cell, sigma_T, PCS
from backtester.chain_engine import ChainBacktest
from data.nse_fo_archive import NseFoArchive
from tests.test_candidate_engine_ext import _cfg_spec, _spec
from tests.test_candidates import E, F, S, SPOT, STRIKES, _run, _weekdays, _write_world

import pandas as pd


def _market_with_closes(days, closes, vix=20.0):
    idx = pd.DatetimeIndex([pd.Timestamp(d) for d in days])
    return pd.DataFrame({
        "nifty_close": [closes.get(d, SPOT) for d in days],
        "vix": [vix] * len(days),
        "nifty_return_5d": [0.0] * len(days),
        "vix_change_5d": [0.0] * len(days),
    }, index=idx)


def _nearest50(x):
    """Nearest listed strike on the 50-point grid (no exact ties occur in these tests)."""
    return int(round(x / 50.0)) * 50


def _pcs_world(root):
    """Weekly world with strike-monotone PE settles on the fill day, so a put credit spread has a positive credit."""
    days = _weekdays(S, E)
    prices = {(F, "PE", k): 5.0 + (k - 21000) / 20.0 for k in STRIKES}
    _write_world(root, days, prices=prices)
    return days


def _short_strike(trade):
    return [l["strike"] for l in trade["legs"] if l["short"]][0]


# ----------------------------------------------------------------------------- spec defaults and validation

def test_strike_basis_defaults_to_fill_close_and_rejects_unknown_values():
    assert get_cell("PCS_A_k09_w200").strike_basis == "fill_close"
    assert _spec().strike_basis == "fill_close"
    with pytest.raises(ValueError):
        _spec(strike_basis="open")


def test_default_cells_are_unchanged_by_the_new_field():
    spec = get_cell("PCS_A_k09_w200")
    assert CandidateSpec(**{**spec.__dict__, "strike_basis": "fill_close"}) == spec


# ----------------------------------------------------------------------------- engine behaviour

def test_fill_close_default_sizes_strikes_on_the_fill_day_close(tmp_path):
    days = _pcs_world(tmp_path)
    closes = {F: 23500.0}                        # S close stays at SPOT 23000
    mk = _market_with_closes(days, closes)
    spec = _spec(cell_id="BASIS_FC", structure=PCS, k=0.9, width=200.0)
    _, trades = _run(tmp_path, days, mk, _cfg_spec(spec, S, E))
    expect = _nearest50(23500.0 - 0.9 * sigma_T(23500.0, 20.0, 6))
    assert _short_strike(trades[0]) == expect


def test_signal_close_sizes_strikes_on_the_signal_day_close(tmp_path):
    days = _pcs_world(tmp_path)
    closes = {S: 22600.0, F: 23500.0}            # S close differs from F close
    mk = _market_with_closes(days, closes)
    spec = _spec(cell_id="BASIS_SC", structure=PCS, k=0.9, width=200.0, strike_basis="signal_close")
    _, trades = _run(tmp_path, days, mk, _cfg_spec(spec, S, E))
    t = trades[0]
    expect = _nearest50(22600.0 - 0.9 * sigma_T(22600.0, 20.0, 6))
    assert _short_strike(t) == expect
    # the legs are still priced at the F-day settle, and DTE is still taken from F
    assert t["fill_date"] == str(F) and t["expiry"] == str(E) and t["dte_at_fill"] == 6
    assert all(l["entry_settle"] == 5.0 + (l["strike"] - 21000) / 20.0 for l in t["legs"])


def test_signal_close_strikes_differ_from_fill_close_when_the_closes_differ(tmp_path):
    days = _pcs_world(tmp_path)
    closes = {S: 22600.0, F: 23500.0}
    mk = _market_with_closes(days, closes)
    fc = _spec(cell_id="BASIS_FC2", structure=PCS, k=0.9, width=200.0)
    sc = _spec(cell_id="BASIS_SC2", structure=PCS, k=0.9, width=200.0, strike_basis="signal_close")
    _, t_fc = _run(tmp_path, days, mk, _cfg_spec(fc, S, E))
    _, t_sc = _run(tmp_path, days, mk, _cfg_spec(sc, S, E))
    assert _short_strike(t_fc[0]) != _short_strike(t_sc[0])


def test_leak_guard_fill_day_close_cannot_move_strikes_under_signal_close(tmp_path):
    """Changing the F-day NIFTY close must not change any strike under signal_close."""
    root_a, root_b = tmp_path / "a", tmp_path / "b"
    days_a = _pcs_world(root_a)
    days_b = _pcs_world(root_b)
    mk_a = _market_with_closes(days_a, {S: 22600.0, F: 23000.0})
    mk_b = _market_with_closes(days_b, {S: 22600.0, F: 24200.0})
    spec = _spec(cell_id="BASIS_LEAK", structure=PCS, k=0.9, width=200.0, strike_basis="signal_close")
    _, ta = _run(root_a, days_a, mk_a, _cfg_spec(spec, S, E))
    _, tb = _run(root_b, days_b, mk_b, _cfg_spec(spec, S, E))
    assert [(l["type"], l["strike"], l["short"]) for l in ta[0]["legs"]] == \
           [(l["type"], l["strike"], l["short"]) for l in tb[0]["legs"]]
    # sanity: under the default basis the same change DOES move the strikes (the guard tests something real)
    fc = _spec(cell_id="BASIS_LEAK_FC", structure=PCS, k=0.9, width=200.0)
    _, fa = _run(root_a, days_a, mk_a, _cfg_spec(fc, S, E))
    _, fb = _run(root_b, days_b, mk_b, _cfg_spec(fc, S, E))
    assert _short_strike(fa[0]) != _short_strike(fb[0])


def test_signal_close_skips_as_missing_data_when_the_signal_close_is_absent(tmp_path):
    days = _pcs_world(tmp_path)
    mk = _market_with_closes(days, {})
    mk.loc[pd.Timestamp(S), "nifty_close"] = float("nan")
    spec = _spec(cell_id="BASIS_NAN", structure=PCS, k=0.9, width=200.0, strike_basis="signal_close")
    bt, trades = _run(tmp_path, days, mk, _cfg_spec(spec, S, E))
    assert trades == []
    assert any(r.get("note") == "signal_close_missing" for r in bt.skip_log)
