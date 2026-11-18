"""Opt-in expiry brokerage (audit fix 3): ChainConfig.expiry_brokerage (default False).

docs/COSTS_NSE_OPTIONS.md: Zerodha's charges page says brokerage is charged on expired, exercised and assigned
contracts (Rs20 flat). The default model does not charge it. With the flag on, every leg still open at expiry
(cash-settled) is charged Rs20 plus 18% GST on that brokerage. This is a conservative assumption: it charges every
expiring leg, in the money or not, and it is not verified against a contract note.

Synthetic archive only (tmp_path).
"""

from datetime import date

import pytest

from backtester.chain_engine import ChainBacktest, ChainConfig
from backtester.nse_option_rates import BROKERAGE_PER_ORDER, GST_PCT
from data.nse_fo_archive import NseFoArchive
from tests.test_candidate_engine_ext import _cfg_spec, _spec
from tests.test_candidates import E, F, S, SPOT, STRIKES, _market, _run, _weekdays, _write_world

from tests.test_max_loss_basis import INDEX_IN_WING, _pcs_world  # PCS world, expiry settles inside the wing

PER_LEG = BROKERAGE_PER_ORDER * (1 + GST_PCT / 100.0)   # Rs 23.6 per expiring leg, brokerage plus GST


def _cfg(spec, **kw):
    return _cfg_spec(spec, S, E, **kw)


def test_expiry_brokerage_defaults_off_and_leaves_the_record_unchanged(tmp_path):
    days = _pcs_world(tmp_path, INDEX_IN_WING)
    mk = _market(days, vix=20.0)
    spec = _spec(cell_id="EB_OFF", structure="put_credit_spread", k=0.9, width=200.0)
    _, off = _run(tmp_path, days, mk, _cfg(spec))
    _, explicit = _run(tmp_path, days, mk, _cfg(spec, expiry_brokerage=False))
    assert off[0] == explicit[0]
    assert "expiry_brokerage_rs" not in off[0]
    assert ChainConfig().expiry_brokerage is False


def test_expiry_brokerage_charges_each_expiring_leg_brokerage_plus_gst(tmp_path):
    days = _pcs_world(tmp_path, INDEX_IN_WING)
    mk = _market(days, vix=20.0)
    spec = _spec(cell_id="EB_ON", structure="put_credit_spread", k=0.9, width=200.0)
    _, base = _run(tmp_path, days, mk, _cfg(spec))
    _, on = _run(tmp_path, days, mk, _cfg(spec, expiry_brokerage=True))
    a, b = base[0], on[0]
    assert b["expiry_brokerage_rs"] == pytest.approx(2 * PER_LEG)          # two legs expire
    assert b["fee_rs"] == pytest.approx(a["fee_rs"] + 2 * PER_LEG)
    assert b["pnl"] == pytest.approx(a["pnl"] - 2 * PER_LEG)
    assert b["exit_reason"] == a["exit_reason"] == "expiry"


def test_early_exit_is_not_charged_expiry_brokerage(tmp_path):
    """A profit-target exit on the session before expiry is an ordinary exit order, not an expiring leg."""
    days = _weekdays(S, E)
    prices = {(F, "PE", k): 5.0 + (k - 21000) / 20.0 for k in STRIKES}
    d6 = date(2025, 1, 6)
    prices.update({(d6, "PE", 22350): 30.0, (d6, "PE", 22150): 35.0})  # short gained, long lost: target fires
    _write_world(tmp_path, days, prices=prices, index=lambda d: SPOT)
    mk = _market(days, vix=20.0)
    spec = _spec(cell_id="EB_EARLY", structure="put_credit_spread", k=0.9, width=200.0, profit_target_pct=50.0)
    _, trades = _run(tmp_path, days, mk, _cfg(spec, expiry_brokerage=True))
    t = trades[0]
    assert t["exit_reason"] == "profit_target"
    assert t.get("expiry_brokerage_rs", 0.0) == 0.0


def test_expiry_brokerage_needs_the_date_aware_cost_model_and_cash_settlement(tmp_path):
    days = _pcs_world(tmp_path, INDEX_IN_WING)
    arch = NseFoArchive(archive_dir=str(tmp_path))
    mk = _market(days, vix=20.0)
    spec = _spec(cell_id="EB_REJ", structure="put_credit_spread", k=0.9, width=200.0)
    with pytest.raises(ValueError):
        ChainBacktest(arch, mk, _cfg(spec, expiry_brokerage=True, legacy_costs=True))
    with pytest.raises(ValueError):
        ChainBacktest(arch, mk, _cfg(spec, expiry_brokerage=True, cash_settlement=False))
