"""Opt-in ML exit gate in candidate mode (default off must be byte-identical; entry gate stays forbidden).

Synthetic archive only (helpers from tests/test_candidates.py).
"""

from datetime import date

import pytest

from backtester.candidates import get_cell
from backtester.chain_engine import ML_EXIT_REASON, ChainBacktest
from data.nse_fo_archive import NseFoArchive
from tests.test_candidate_engine_ext import D6, _cfg_spec, _prices_marks, _spec
from tests.test_candidates import E, S, _market, _run, _weekdays, _write_world

D7 = date(2025, 1, 7)


def _world(tmp_path):
    days = _weekdays(S, E)
    _write_world(tmp_path, days, prices=_prices_marks(40.0, 15.0))
    return days, _market(days)


def test_gate_none_runs_identical(tmp_path):
    days, mk = _world(tmp_path)
    cfg = _cfg_spec(_spec(), S, E, slippage_multiplier=1.0)
    _, t1 = _run(tmp_path, days, mk, cfg)
    _, t2 = _run(tmp_path, days, mk, cfg)
    assert t1 == t2 and len(t1) == 1 and t1[0]["exit_reason"] == "expiry"


def test_stub_gate_exits_on_day_two_at_that_days_mark(tmp_path):
    days, mk = _world(tmp_path)
    seen = []

    def gate(ctx):
        seen.append(ctx)
        return ctx["holding_sessions"] == 2, 0.9

    cfg = _cfg_spec(_spec(), S, E, exit_gate=gate)
    _, trades = _run(tmp_path, days, mk, cfg)
    assert len(trades) == 1
    t = trades[0]
    assert t["exit_reason"] == ML_EXIT_REASON
    assert t["exit_date"] == str(D7) and t["dte_at_exit"] == 2
    assert [c["holding_sessions"] for c in seen] == [1, 2]
    for k in ("peak_pnl_rs", "short_dist_pct", "mark_pnl_rs", "entry_credit_rs", "rule_exit"):
        assert k in seen[0]
    assert seen[0]["rule_exit"] is False


def test_gate_not_called_on_expiry_day(tmp_path):
    days, mk = _world(tmp_path)
    dtes = []

    def gate(ctx):
        dtes.append(ctx["dte"])
        return False, 0.0

    _, trades = _run(tmp_path, days, mk, _cfg_spec(_spec(), S, E, exit_gate=gate))
    assert trades[0]["exit_reason"] == "expiry" and 0 not in dtes and dtes


def test_entry_gate_still_forbidden_in_candidate_mode(tmp_path):
    days, mk = _world(tmp_path)
    arch = NseFoArchive(archive_dir=str(tmp_path))
    with pytest.raises(ValueError):
        ChainBacktest(arch, mk, _cfg_spec(get_cell("PCS_A_k09_w200"), S, E, entry_gate=lambda c: (True, 1.0)))
