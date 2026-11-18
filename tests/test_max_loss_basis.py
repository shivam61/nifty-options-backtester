"""Opt-in max-loss basis (audit fix 2): CandidateSpec.max_loss_basis in {'settle' (default), 'fill_plus_fees'}.

'settle' is the historical W - net credit on the F settle basis (the pre-registered figure).
'fill_plus_fees' is W - net credit at the fill price (after entry slippage) plus round-trip fees. Round-trip fees
are a conservative bound: entry order fees, the mirrored exit order fees at the fill premiums, and STT on exercise
of each long leg with its intrinsic capped at the wing width W. The cap is an assumption: a realised expiry that
puts a long leg more than W in the money pays more exercise STT than the bound allows for.

Regression case: the audited round-2 train trade D2 2021-01-29 (net -156,569.77 Rs at 10 lots against a recorded
max loss of 153,237.5 Rs) must not breach under the new basis. The D2 numbers below are copied from the audit record.
Synthetic archive only (tmp_path).
"""

import math
from datetime import date

import pytest

from backtester.candidates import LS, PCS, CandidateSpec, fill_basis_max_loss_unit, get_cell, pcs_max_loss_per_unit
from backtester.chain_engine import ChainBacktest
from backtester.nse_option_rates import STT_EXERCISE_PCT, rate_on
from data.nse_fo_archive import NseFoArchive
from tests.test_candidate_engine_ext import _cfg_spec, _spec
from tests.test_candidates import E, F, S, SPOT, STRIKES, _market, _run, _weekdays, _write_world

LOT = 65
D2_DAY = date(2021, 1, 29)
D2_QTY = 10 * LOT
D2_LEGS = [  # (type, strike, short, fill per unit), audited 2021-01-29 trade
    ("PE", 13100.0, True, 46.44259994506836),
    ("PE", 12800.0, False, 20.97982383462241),
    ("CE", 14150.0, True, 61.242599945068356),
    ("CE", 14450.0, False, 26.727007584890107),
]
D2_CREDIT_RS = 38985.93950590573
D2_MAX_LOSS_SETTLE_RS = 153237.5
D2_NET_PNL_RS = -156569.76669260694
D2_AUDITED_COST_RS = 555.7061985126746
D2_WIDTH = 300.0


def _bound(root, sold, bought, n_orders, n_long, width, qty, day=D2_DAY):
    _write_world(root, [S, F])   # one minimal archive: the fee helper reads no rows, the archive needs some
    bt = ChainBacktest(NseFoArchive(archive_dir=str(root)), _market([S, F], vix=15.0), _cfg_spec(_spec(), S, F))
    return bt, bt._max_loss_round_trip_fee_rs(day, sold, bought, n_orders=n_orders, n_long=n_long,
                                              width=width, qty=qty)


def _d2_bound(root):
    sold = sum(f for _, _, short, f in D2_LEGS if short) * D2_QTY
    bought = sum(f for _, _, short, f in D2_LEGS if not short) * D2_QTY
    return _bound(root, sold, bought, n_orders=4, n_long=2, width=D2_WIDTH, qty=D2_QTY)


# ----------------------------------------------------------------------------- spec defaults and validation

def test_max_loss_basis_defaults_to_settle_and_rejects_unknown_values():
    assert get_cell("PCS_A_k09_w200").max_loss_basis == "settle"
    with pytest.raises(ValueError):
        _spec(max_loss_basis="expiry")


def test_max_loss_basis_is_for_credit_structures_only():
    with pytest.raises(ValueError):
        CandidateSpec("LS_T", "T", LS, 0.9, None, "weekly", -math.inf, 13.0, max_loss_basis="fill_plus_fees")


# ----------------------------------------------------------------------------- pure helpers

def test_fill_basis_unit_is_width_minus_fill_credit_plus_fee_share_per_unit():
    assert fill_basis_max_loss_unit(200.0, 25.0, 650.0, 650) == pytest.approx(175.0 + 1.0)
    assert pcs_max_loss_per_unit(200.0, 25.0) == pytest.approx(175.0)


def test_round_trip_fee_bound_decomposes_and_covers_the_audited_d2_costs(tmp_path):
    bt, bound = _d2_bound(tmp_path / "bound")
    sold = sum(f for _, _, short, f in D2_LEGS if short) * D2_QTY
    bought = sum(f for _, _, short, f in D2_LEGS if not short) * D2_QTY
    entry = bt._order_fees(D2_DAY, sold, bought, 4)["total"]
    mirror = bt._order_fees(D2_DAY, bought, sold, 4)["total"]
    exercise = 2 * D2_WIDTH * D2_QTY * rate_on(STT_EXERCISE_PCT, D2_DAY) / 100
    assert bound == pytest.approx(entry + mirror + exercise)
    assert bound >= D2_AUDITED_COST_RS


def test_audited_d2_trade_does_not_breach_under_fill_plus_fees(tmp_path):
    _, bound = _d2_bound(tmp_path / "d2")
    credit_fill_unit = D2_CREDIT_RS / D2_QTY
    ml_rs_new = fill_basis_max_loss_unit(D2_WIDTH, credit_fill_unit, bound, D2_QTY) * D2_QTY
    assert -D2_NET_PNL_RS > D2_MAX_LOSS_SETTLE_RS          # the audited record breached its settle-basis max loss
    assert -D2_NET_PNL_RS <= ml_rs_new                     # the fill-plus-fees max loss covers it
    assert ml_rs_new > D2_MAX_LOSS_SETTLE_RS


# ----------------------------------------------------------------------------- engine

def _pcs_world(root, index_settle):
    """Weekly PCS world, PE settles rising with strike so the fill credit is positive (short 22350 / long 22150 = 10).
    The expiry day settles at index_settle; with 0 slippage the fills equal the F settles."""
    days = _weekdays(S, E)
    prices = {(F, "PE", k): 5.0 + (k - 21000) / 20.0 for k in STRIKES}
    _write_world(root, days, prices=prices, index=lambda d: index_settle if d == E else SPOT)
    return days


SHORT_PX, LONG_PX = 5.0 + (22350 - 21000) / 20.0, 5.0 + (22150 - 21000) / 20.0   # 72.5, 62.5
CREDIT = SHORT_PX - LONG_PX                                                       # 10.0 per unit
# index 22100: long 22150 is 50 in the money (within one wing width W = 200), short 22350 is 250 in the money
INDEX_IN_WING = 22100.0


def test_engine_fill_plus_fees_adds_a_round_trip_bound_and_settle_default_is_unchanged(tmp_path):
    days = _pcs_world(tmp_path, INDEX_IN_WING)
    mk = _market(days, vix=20.0)
    _, ta = _run(tmp_path, days, mk, _cfg_spec(_spec(cell_id="ML_T", structure=PCS, k=0.9, width=200.0), S, E))
    _, tb = _run(tmp_path, days, mk, _cfg_spec(_spec(cell_id="ML_T", structure=PCS, k=0.9, width=200.0,
                                                    max_loss_basis="fill_plus_fees"), S, E))
    a, b = ta[0], tb[0]
    assert a["max_loss_rs"] == pytest.approx((200.0 - CREDIT) * LOT)            # settle basis, unchanged
    assert b["max_loss_rs"] > a["max_loss_rs"]
    assert b["max_loss_rs"] - a["max_loss_rs"] > 0                              # the increment is the fee bound
    assert a["pnl"] == pytest.approx(b["pnl"])                                  # the basis moves only the max loss
    assert -b["pnl"] <= b["max_loss_rs"]                                        # realised loss inside the new max
    assert -a["pnl"] > a["max_loss_rs"]                                         # and the settle basis misses the fees


def test_engine_fill_plus_fees_is_what_sizing_uses_in_capital_mode(tmp_path):
    days = _pcs_world(tmp_path, INDEX_IN_WING)
    mk = _market(days, vix=20.0)
    spec = _spec(cell_id="ML_S", structure=PCS, k=0.9, width=200.0, max_loss_basis="fill_plus_fees")
    _, trades = _run(tmp_path, days, mk, _cfg_spec(spec, S, E, capital_mode=True, capital_rs=500_000.0))
    t = trades[0]
    assert t["max_loss_per_lot_rs"] == pytest.approx(t["max_loss_rs"])          # lots == 1
    assert t["max_loss_per_lot_rs"] > (200.0 - CREDIT) * LOT
    expect = math.floor(min(0.10 * 500_000 / t["max_loss_per_lot_rs"], 30, 0.20 * 500_000 / t["margin_per_lot_rs"]))
    assert t["sized_lots"] == expect
