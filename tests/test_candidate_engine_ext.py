"""Step 0 engine extensions for candidate mode (opt-in; defaults must reproduce the current behaviour).

Covers: profit-target and stop-loss exits at EOD marks, overlapping positions (max_concurrent), equity-based
sizing, iron condor / call credit spread structures, the entry filter hook, and portfolio metrics
(scripts/portfolio_metrics.py, reported beside the per-lot verdict by scripts/eval_strategy.py).

Synthetic archive only (helpers from tests/test_candidates.py). No real data, no dates after 2023-12-31.
"""

import math
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from backtester.candidates import (
    CALL_CREDIT_SPREAD, IRON_CONDOR, PCS, CandidateSpec, get_cell, target_strikes,
)
from backtester.chain_engine import ChainBacktest, ChainConfig
from data.nse_fo_archive import NseFoArchive
from tests.test_candidates import (
    A_PRICES, E, E2, F, FEB27, JAN30, LOT, LONG_PE_200, S, SHORT_PE, SPOT, STRIKES,
    _a_world, _market, _run, _weekdays, _write_world,
)

REPO = Path(__file__).resolve().parents[1]
D6 = date(2025, 1, 6)
D10 = date(2025, 1, 10)
D31 = date(2025, 1, 31)
CE_SHORT, CE_LONG = 23650.0, 23850.0   # snapped call strikes for k=0.9 at VIX 20 from F spot 23000, DTE 6


def _spec(**kw):
    base = dict(cell_id="T_TEST", family="T", structure=PCS, k=0.9, width=200.0, cadence="weekly",
                vix_lo=16.0, vix_hi=25.0)
    base.update(kw)
    return CandidateSpec(**base)


def _cfg_spec(spec, start, end, **kw):
    kw.setdefault("slippage_multiplier", 0.0)
    kw.setdefault("lots", 1)
    return ChainConfig(start=start, end=end, candidate=spec, **kw)


# ----------------------------------------------------------------------------- defaults and validation

def test_new_fields_default_to_current_behaviour():
    a = get_cell("PCS_A_k09_w200")
    assert a.profit_target_pct is None and a.stop_loss_x is None
    cfg = ChainConfig()
    assert cfg.max_concurrent == 1
    assert cfg.equity_based_sizing is False
    assert cfg.candidate_entry_filter is None


def test_invalid_new_options_are_rejected(tmp_path):
    days, mk = _a_world(tmp_path)
    arch = NseFoArchive(archive_dir=str(tmp_path))
    with pytest.raises(ValueError):
        ChainBacktest(arch, mk, _cfg_spec(get_cell("PCS_A_k09_w200"), S, E, max_concurrent=0))
    with pytest.raises(ValueError):   # overlap only exists in candidate mode
        ChainBacktest(arch, mk, ChainConfig(start=S, end=E, max_concurrent=2))
    with pytest.raises(ValueError):   # equity sizing only exists in capital mode
        ChainBacktest(arch, mk, _cfg_spec(get_cell("PCS_A_k09_w200"), S, E, equity_based_sizing=True))
    with pytest.raises(ValueError):   # exit rules need a credit structure (family B is a debit)
        ChainBacktest(arch, mk, _cfg_spec(replace(get_cell("LS_B_k09_wk"), profit_target_pct=50.0), S, E))
    with pytest.raises(ValueError):
        ChainBacktest(arch, mk, _cfg_spec(_spec(profit_target_pct=0.0), S, E))
    with pytest.raises(ValueError):
        ChainBacktest(arch, mk, _cfg_spec(_spec(stop_loss_x=-1.0), S, E))
    with pytest.raises(ValueError):   # filter hook is candidate-only
        ChainBacktest(arch, mk, ChainConfig(start=S, end=E, candidate_entry_filter=lambda row: True))


# ----------------------------------------------------------------------------- exits at EOD marks

def _prices_marks(short_d6, long_d6, flat_after_fill=(40.0, 15.0)):
    """A_PRICES at F. Every later session keeps the fill prices (no move) unless D6 is set explicitly."""
    p = dict(A_PRICES)
    for d in _weekdays(D6, E):
        p[(d, "PE", SHORT_PE)] = flat_after_fill[0]
        p[(d, "PE", LONG_PE_200)] = flat_after_fill[1]
    p[(D6, "PE", SHORT_PE)] = short_d6
    p[(D6, "PE", LONG_PE_200)] = long_d6
    return p


def test_profit_target_closes_at_mark_and_pays_exit_costs(tmp_path):
    days = _weekdays(S, E)
    _write_world(tmp_path, days, prices=_prices_marks(10.0, 10.0))   # mark gain = full credit on D6
    mk = _market(days)
    cfg = _cfg_spec(_spec(profit_target_pct=50.0), S, E, slippage_multiplier=1.0)
    _, trades = _run(tmp_path, days, mk, cfg)
    assert len(trades) == 1
    t = trades[0]
    assert t["exit_reason"] == "profit_target"
    assert t["exit_date"] == str(D6) and t["dte_at_exit"] == 3
    assert t["close_slip_rs"] > 0          # exit slippage paid, as on the non-candidate exit path
    assert t["fee_rs"] > 0


def test_profit_target_not_reached_holds_to_expiry(tmp_path):
    days = _weekdays(S, E)
    _write_world(tmp_path, days, prices=_prices_marks(40.0, 15.0))   # no gain on D6
    _, trades = _run(tmp_path, days, _market(days), _cfg_spec(_spec(profit_target_pct=50.0), S, E))
    assert len(trades) == 1 and trades[0]["exit_reason"] == "expiry" and trades[0]["exit_date"] == str(E)


def test_stop_loss_closes_at_mark(tmp_path):
    days = _weekdays(S, E)
    _write_world(tmp_path, days, prices=_prices_marks(70.0, 15.0))   # short leg loses 30 on D6, credit 25
    cfg = _cfg_spec(_spec(stop_loss_x=1.0), S, E)
    _, trades = _run(tmp_path, days, _market(days), cfg)
    assert len(trades) == 1
    t = trades[0]
    assert t["exit_reason"] == "stop_loss" and t["exit_date"] == str(D6)
    assert t["gross_fill_rs"] == pytest.approx(-30.0 * LOT)


def test_stop_loss_not_reached_holds_and_default_none_holds(tmp_path):
    days = _weekdays(S, E)
    _write_world(tmp_path, days, prices=_prices_marks(70.0, 15.0))
    # 2x credit stop is not reached by a 30/unit loss on a 25/unit credit
    _, trades = _run(tmp_path, days, _market(days), _cfg_spec(_spec(stop_loss_x=2.0), S, E))
    assert trades[0]["exit_reason"] == "expiry"
    _, trades = _run(tmp_path, days, _market(days), _cfg_spec(_spec(), S, E))
    assert trades[0]["exit_reason"] == "expiry" and trades[0]["exit_date"] == str(E)


# ----------------------------------------------------------------------------- overlapping positions

def _overlap_world(root):
    days = _weekdays(S, FEB27)
    prices = {}
    for d in days:
        for k in STRIKES:
            prices[(d, "PE", k)] = 10.0 + (k - 21000) / 100.0   # PE credit: +2 per unit for a 200-wide spread
    _write_world(root, days, prices=prices)
    return days, _market(days)


def test_max_concurrent_one_skips_overlapping_signals(tmp_path):
    spec = _spec(cell_id="MO_T", cadence="monthly")
    days, mk = _overlap_world(tmp_path)
    bt, trades = _run(tmp_path, days, mk, _cfg_spec(spec, S, FEB27))
    assert [t["fill_date"] for t in trades] == [str(F), str(D31)]
    assert bt.skips["position_open"] >= 1


def test_max_concurrent_two_opens_second_position_while_first_open(tmp_path):
    spec = _spec(cell_id="MO_T", cadence="monthly")
    days, mk = _overlap_world(tmp_path)
    bt, trades = _run(tmp_path, days, mk, _cfg_spec(spec, S, FEB27, max_concurrent=2))
    # Jan 3 and Jan 10 expire (and close) Jan 30, before the Jan 30 signal. The Jan 31 fill then opens alone,
    # and the Feb 6 signal opens a second position beside it. Feb 13 finds two open: position_open.
    assert [t["fill_date"] for t in trades] == [str(F), str(D10), str(D31), str(date(2025, 2, 7))]
    assert trades[0]["exit_date"] == str(JAN30) and trades[1]["exit_date"] == str(JAN30)
    assert bt.skips["position_open"] >= 1


# ----------------------------------------------------------------------------- equity-based sizing

def test_equity_sizing_rescales_lots_from_current_equity(tmp_path):
    """Trade 1 loses 175/unit (at E = 22000 the short 22350 PE settles 350, the long 22150 PE settles 150).
    Trade 2 is sized from the lower equity; with equity sizing off it keeps trade 1's lots."""
    days = _weekdays(S, E2)
    prices = dict(A_PRICES)
    prices[(D10, "PE", SHORT_PE)] = 40.0
    prices[(D10, "PE", LONG_PE_200)] = 15.0
    _write_world(tmp_path, days, prices=prices, index=lambda d: 22000.0 if d == E else SPOT)
    mk = _market(days)
    base = dict(capital_mode=True, capital_rs=2_500_000.0, risk_cap_pct=0.10, margin_cap_pct=0.20,
                max_lots=30, kill_dd_pct=0.20)
    _, off = _run(tmp_path, days, mk, _cfg_spec(_spec(), S, E2, **base))
    assert [t["sized_lots"] for t in off] == [21, 21]
    _, on = _run(tmp_path, days, mk, _cfg_spec(_spec(), S, E2, equity_based_sizing=True, **base))
    assert len(on) == 2 and on[0]["sized_lots"] == 21
    eq = 2_500_000.0 + on[0]["pnl_sized_rs"]
    ml_lot = 175.0 * LOT
    expected = math.floor(min(0.10 * eq / ml_lot, 0.20 * eq / ml_lot, 30))
    assert on[1]["sized_lots"] == expected and expected < 21


def test_equity_sizing_default_uses_capital_rs(tmp_path):
    days, mk = _a_world(tmp_path)
    _, trades = _run(tmp_path, days, mk, _cfg_spec(get_cell("PCS_A_k09_w200"), S, E, capital_mode=True,
                                                  capital_rs=2_500_000.0))
    assert trades[0]["sized_lots"] == 21


# ----------------------------------------------------------------------------- structures

def _ic_prices():
    p = dict(A_PRICES)
    p[(F, "CE", CE_SHORT)] = 40.0
    p[(F, "CE", CE_LONG)] = 15.0
    return p


def test_iron_condor_defined_max_loss_and_pnl_bounds(tmp_path):
    spec = _spec(cell_id="IC_T", family="D", structure=IRON_CONDOR)
    days = _weekdays(S, E)
    _write_world(tmp_path, days, prices=_ic_prices())
    _, trades = _run(tmp_path, days, _market(days), _cfg_spec(spec, S, E))
    assert len(trades) == 1
    t = trades[0]
    assert [(l["type"], l["strike"], l["short"]) for l in t["legs"]] == [
        ("PE", 22350.0, True), ("PE", 22150.0, False), ("CE", CE_SHORT, True), ("CE", CE_LONG, False)]
    assert t["credit_rs"] == pytest.approx(50.0 * LOT)
    assert t["max_loss_rs"] == pytest.approx((200.0 - 50.0) * LOT)
    assert t["gross_fill_rs"] == pytest.approx(50.0 * LOT)        # expiry at spot 23000: all wings OTM


def test_iron_condor_loss_side_capped_at_wing_minus_credit(tmp_path):
    spec = _spec(cell_id="IC_T", family="D", structure=IRON_CONDOR)
    days = _weekdays(S, E)
    _write_world(tmp_path, days, prices=_ic_prices(), index=lambda d: 23900.0 if d == E else SPOT)
    _, trades = _run(tmp_path, days, _market(days), _cfg_spec(spec, S, E))
    assert trades[0]["gross_fill_rs"] == pytest.approx(-(200.0 - 50.0) * LOT)


def test_call_credit_spread_structure_and_max_loss(tmp_path):
    spec = _spec(cell_id="CCS_T", family="E", structure=CALL_CREDIT_SPREAD)
    days = _weekdays(S, E)
    p = {(F, "CE", CE_SHORT): 40.0, (F, "CE", CE_LONG): 15.0}
    _write_world(tmp_path, days, prices=p)
    _, trades = _run(tmp_path, days, _market(days), _cfg_spec(spec, S, E))
    assert len(trades) == 1
    t = trades[0]
    assert [(l["type"], l["strike"], l["short"]) for l in t["legs"]] == [("CE", CE_SHORT, True), ("CE", CE_LONG, False)]
    assert t["max_loss_rs"] == pytest.approx((200.0 - 25.0) * LOT)
    assert t["credit_rs"] == pytest.approx(25.0 * LOT)


def test_target_strikes_for_new_structures():
    tg = target_strikes(_spec(structure=IRON_CONDOR), 23000.0, 20.0, 6)
    assert set(tg) == {"CE", "PE"} and tg["CE"] > 23000 > tg["PE"]
    tg = target_strikes(_spec(structure=CALL_CREDIT_SPREAD), 23000.0, 20.0, 6)
    assert set(tg) == {"CE"} and tg["CE"] > 23000


# ----------------------------------------------------------------------------- entry filter hook

def test_entry_filter_false_blocks_every_signal_and_true_changes_nothing(tmp_path):
    days, mk = _a_world(tmp_path)
    _, base = _run(tmp_path, days, mk, _cfg_spec(get_cell("PCS_A_k09_w200"), S, E))
    bt, none = _run(tmp_path, days, mk, _cfg_spec(get_cell("PCS_A_k09_w200"), S, E,
                                                  candidate_entry_filter=lambda row: False))
    assert none == [] and bt.skips["entry_filter"] >= 1
    _, allowed = _run(tmp_path, days, mk, _cfg_spec(get_cell("PCS_A_k09_w200"), S, E,
                                                   candidate_entry_filter=lambda row: True))
    assert allowed == base


def test_entry_filter_receives_signal_day_market_row(tmp_path):
    days, mk = _a_world(tmp_path)
    seen = []

    def spy(row):
        seen.append((float(row["vix"]), float(row["nifty_close"])))
        return True

    _run(tmp_path, days, mk, _cfg_spec(get_cell("PCS_A_k09_w200"), S, E, candidate_entry_filter=spy))
    # called on the first signal day (Jan 2) with that day's market row; Jan 9 is a later listed expiry day
    assert seen[0] == (20.0, SPOT) and all(v == (20.0, SPOT) for v in seen)


# ----------------------------------------------------------------------------- signal cadence (GAP 1, opt-in)
# Thursday-expiry world (THURS). Signal weekday 1 (Tuesday) fills Wednesday, and the earliest expiry with DTE in
# [3, 8] from a Wednesday is the Thursday eight days on, so each position is held 8 days and a new one opens
# every 7 days while the previous one is still open.

MON6 = date(2025, 1, 6)   # Monday: the first Tuesday signal is 2025-01-07


def _cadence_world(root):
    """Thursday-expiry world from Monday 2025-01-06 (PE credit 2.0 per unit at every strike pair)."""
    days = _weekdays(MON6, FEB27)
    prices = {(d, "PE", k): 10.0 + (k - 21000) / 100.0 for d in days for k in STRIKES}
    _write_world(root, days, prices=prices)
    return days, _market(days)


TUE_JAN7 = date(2025, 1, 7)
WED_JAN8 = date(2025, 1, 8)
JAN16 = date(2025, 1, 16)
JAN15 = date(2025, 1, 15)
JAN22 = date(2025, 1, 22)
JAN23 = date(2025, 1, 23)


def test_signal_cadence_defaults_and_validation(tmp_path):
    cfg = ChainConfig()
    _, mk = _cadence_world(tmp_path)
    assert cfg.signal_cadence == "expiry_day" and cfg.signal_weekday == 0
    with pytest.raises(ValueError):   # candidate-only option
        ChainBacktest(NseFoArchive(archive_dir=str(tmp_path)), mk, ChainConfig(start=S, end=E, signal_cadence="daily"))
    with pytest.raises(ValueError):
        ChainBacktest(NseFoArchive(archive_dir=str(tmp_path)), mk,
                      _cfg_spec(_spec(), S, E, signal_cadence="hourly"))
    with pytest.raises(ValueError):
        ChainBacktest(NseFoArchive(archive_dir=str(tmp_path)), mk,
                      _cfg_spec(_spec(), S, E, signal_cadence="weekly_fixed_weekday", signal_weekday=7))


def test_weekly_fixed_weekday_signals_once_a_week_on_that_weekday(tmp_path):
    days, mk = _cadence_world(tmp_path)
    bt, trades = _run(tmp_path, days, mk, _cfg_spec(_spec(), MON6, FEB27, signal_cadence="weekly_fixed_weekday",
                                                   signal_weekday=1, max_concurrent=2))
    assert bt.signal_days == 8                       # Tuesdays 2025-01-07 .. 2025-02-25
    assert trades and all(date.fromisoformat(t["signal_date"]).weekday() == 1 for t in trades)


def test_weekly_fixed_weekday_opens_second_position_while_first_is_open(tmp_path):
    days, mk = _cadence_world(tmp_path)
    _, two = _run(tmp_path, days, mk, _cfg_spec(_spec(), MON6, FEB27, signal_cadence="weekly_fixed_weekday",
                                               signal_weekday=1, max_concurrent=2))
    assert [t["fill_date"] for t in two[:3]] == [str(WED_JAN8), str(JAN15), str(JAN22)]
    assert [t["exit_date"] for t in two[:2]] == [str(JAN16), str(JAN23)]
    assert two[1]["fill_date"] < two[0]["exit_date"]       # overlap: fill of #2 before expiry of #1

    bt1, one = _run(tmp_path, days, mk, _cfg_spec(_spec(), MON6, FEB27, signal_cadence="weekly_fixed_weekday",
                                                 signal_weekday=1, max_concurrent=1))
    assert [t["fill_date"] for t in one[:2]] == [str(WED_JAN8), str(date(2025, 1, 22))]
    assert bt1.skips["position_open"] >= 1                 # the Jan 14 signal finds one open


def test_weekly_fixed_weekday_reads_vix_at_signal_close(tmp_path):
    days, _ = _cadence_world(tmp_path)
    mk = _market(days, vix_map={TUE_JAN7: 30.0})          # out of band on the signal day only
    bt, trades = _run(tmp_path, days, mk, _cfg_spec(_spec(), MON6, FEB27, signal_cadence="weekly_fixed_weekday",
                                                   signal_weekday=1, max_concurrent=2))
    assert bt.skips["vix_out_of_band"] >= 1
    assert trades[0]["fill_date"] == str(JAN15)            # the Jan 7 signal is gone, Jan 14 is next
    assert trades[0]["entry_vix"] == 20.0


def test_daily_cadence_signals_every_session(tmp_path):
    days, mk = _cadence_world(tmp_path)
    bt, _ = _run(tmp_path, days, mk, _cfg_spec(_spec(), MON6, FEB27, signal_cadence="daily", max_concurrent=2))
    assert bt.signal_days == len(days)


# ----------------------------------------------------------------------------- margin netting (GAP 4)

def _netting_cfg(**kw):
    base = dict(capital_mode=True, capital_rs=2_500_000.0, risk_cap_pct=0.20, margin_cap_pct=0.20,
                max_lots=30, kill_dd_pct=0.20, max_concurrent=2)
    base.update(kw)
    return _cfg_spec(_spec(cell_id="MO_T", cadence="monthly"), S, FEB27, **base)


def test_margin_netting_sizes_second_entry_from_remaining_budget(tmp_path):
    """Two overlapping positions (Jan 3 and Jan 10 fills, both expire Jan 30). Max loss per lot is 198 x 65 = 12870.
    Entry 1: min(38, 38, max_lots 30) = 30 lots, committing 386100 of risk and of margin. Entry 2 may use only
    0.20 x 2.5M - 386100 = 113900, i.e. floor(113900 / 12870) = 8 lots. Equity-based sizing gives the same here
    (no mark-to-market move in this world)."""
    days, mk = _overlap_world(tmp_path)
    for eq_sizing in (False, True):
        _, trades = _run(tmp_path, days, mk, _netting_cfg(equity_based_sizing=eq_sizing))
        by_fill = sorted(trades, key=lambda t: t["fill_date"])
        assert [t["sized_lots"] for t in by_fill[:2]] == [30, 8]
        committed = sum(t["sized_lots"] * t["max_loss_per_lot_rs"] for t in by_fill[:2])
        assert committed <= 0.20 * 2_500_000.0 + 1e-6


def test_margin_netting_skips_sizing_zero_when_budget_is_used_up(tmp_path):
    days, mk = _overlap_world(tmp_path)
    bt, trades = _run(tmp_path, days, mk, _netting_cfg(risk_cap_pct=0.10, margin_cap_pct=0.20))
    by_fill = sorted(trades, key=lambda t: t["fill_date"])
    assert by_fill[0]["sized_lots"] == 19                  # floor(250000 / 12870)
    # budget left after entry 1: 250000 - 19 x 12870 = 5470 < one lot, so the Jan 10 entry is sizing_zero
    assert bt.skips["sizing_zero"] >= 1
    assert all(t["fill_date"] != str(D10) for t in trades)
