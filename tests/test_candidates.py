"""Tests for the pre-registered candidate families A and B (backtester/candidates.py, chain engine candidate path,
scripts/run_candidates.py). Pre-registration: docs/preregistration_candidates.md.

All data is a synthetic archive written to tmp_path (no real archive, no network). Weekday calendar from
Thu 2025-01-02; Thursdays are weekly expiries. Default settle is 10.0 unless a (day, opt, strike) price is set.
Slippage multiplier 0 in most tests so fills equal the F settle exactly.
"""

import gzip
import importlib.util
import json
import math
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

from backtester.candidates import (
    CELLS, FAMILY_CELLS, PHASE_WINDOWS, CandidateSpec, get_cell, harness_record, listed_expiries,
    monthly_expiries, pick_expiry, sigma_T, target_strikes,
)
from backtester.chain_engine import ChainBacktest, ChainConfig
from data.nse_fo_archive import NseFoArchive
from strategies.base import Trade

COLS = ["date", "expiry", "strike", "opt", "open", "high", "low", "close", "settle",
        "contracts", "open_int", "underlying"]
S = date(2025, 1, 2)     # signal: weekly expiry day (Thursday)
F = date(2025, 1, 3)     # fill: next session
D6 = date(2025, 1, 6)
D7 = date(2025, 1, 7)
E = date(2025, 1, 9)     # weekly expiry, DTE 6 from F
E2 = date(2025, 1, 16)
JAN23 = date(2025, 1, 23)
JAN30 = date(2025, 1, 30)  # last Thursday of January: monthly expiry
FEB27 = date(2025, 2, 27)  # monthly expiry, DTE 55 from F
SPOT = 23000.0
LOT = 65
THURS = [S + timedelta(days=7 * i) for i in range(12)]
STRIKES = list(range(21000, 24001, 50))
SHORT_PE, LONG_PE_200, LONG_PE_300 = 22350, 22150, 22050   # A k=0.9 at VIX 20 from F spot 23000, DTE 6


# ----------------------------------------------------------------- synthetic archive helpers
def _row(d, exp, k, opt, settle, contracts=100, oi=1000, close=None):
    close = settle if close is None else close
    return [d.isoformat(), exp.isoformat(), float(k), opt, 0.0, 0.0, 0.0, close, settle,
            contracts, oi, float("nan")]


def _weekdays(a, b):
    out, d = [], a
    while d <= b:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _write_world(root, days, prices=None, index=None, strikes=None):
    """Write one daily file per weekday in `days`. Each file lists every Thursday expiry from that day
    within 60 days. On an expiry day the expiry-day group settles at index(day) (the archive convention)."""
    prices = prices or {}
    index = index or (lambda d: SPOT)
    strikes = STRIKES if strikes is None else strikes
    for d in days:
        rows = []
        for e in THURS:
            if e < d or (e - d).days > 60:
                continue
            for opt in ("PE", "CE"):
                for k in strikes:
                    settle = index(d) if e == d else prices.get((d, opt, k), 10.0)
                    rows.append(_row(d, e, k, opt, settle))
        path = root / "daily" / (d.strftime("%Y%m%d") + ".csv.gz")
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(path, "wt") as fh:
            pd.DataFrame(rows, columns=COLS).to_csv(fh, index=False)


def _market(days, vix=20.0, vix_map=None):
    idx = pd.DatetimeIndex([pd.Timestamp(d) for d in days])
    vix_map = vix_map or {}
    return pd.DataFrame({
        "nifty_close": [SPOT] * len(days),
        "vix": [vix_map.get(d, vix) for d in days],
        "nifty_return_5d": [0.0] * len(days),
        "vix_change_5d": [0.0] * len(days),
    }, index=idx)


def _cfg(cell_id, start, end, **kw):
    kw.setdefault("slippage_multiplier", 0.0)
    kw.setdefault("lots", 1)
    return ChainConfig(start=start, end=end, candidate=get_cell(cell_id), **kw)


def _run(root, days, market, cfg):
    arch = NseFoArchive(archive_dir=str(root))
    bt = ChainBacktest(arch, market, cfg)
    trades = bt.run()
    return bt, trades


A_PRICES = {(F, "PE", SHORT_PE): 40.0, (F, "PE", LONG_PE_200): 15.0, (F, "PE", LONG_PE_300): 15.0}


def _a_world(root, days_end=E, vix=20.0, prices=None, index=None, vix_map=None, strikes=None):
    days = _weekdays(S, days_end)
    _write_world(root, days, prices=prices if prices is not None else dict(A_PRICES), index=index,
                 strikes=strikes)
    return days, _market(days, vix=vix, vix_map=vix_map)


# ----------------------------------------------------------------- spec, cells, pure helpers
def test_declared_grid_is_exactly_the_ten_preregistered_cells():
    assert sorted(CELLS) == sorted([
        "PCS_A_k09_w200", "PCS_A_k09_w300", "PCS_A_k11_w200", "PCS_A_k11_w300",
        "PCS_A_k13_w200", "PCS_A_k13_w300",
        "LS_B_k09_wk", "LS_B_k09_mo", "LS_B_k13_wk", "LS_B_k13_mo",
    ])
    assert len(FAMILY_CELLS["A"]) == 6 and len(FAMILY_CELLS["B"]) == 4
    a = get_cell("PCS_A_k11_w300")
    assert (a.k, a.width, a.vix_lo, a.vix_hi, a.cadence) == (1.1, 300.0, 16.0, 25.0, "weekly")
    b = get_cell("LS_B_k13_mo")
    assert (b.k, b.width, b.vix_hi, b.cadence) == (1.3, None, 13.0, "monthly")


def test_sigma_t_and_strike_targets_match_formula():
    # sigma_T = spot_F * (VIX_S/100) * sqrt(DTE/252)
    assert sigma_T(23000.0, 20.0, 6) == pytest.approx(23000.0 * 0.20 * math.sqrt(6 / 252))
    spec_a = get_cell("PCS_A_k09_w200")
    tg = target_strikes(spec_a, 23000.0, 20.0, 6)
    assert tg == {"PE": pytest.approx(23000.0 - 0.9 * 709.7954, abs=1e-3)}
    spec_b = get_cell("LS_B_k13_wk")
    tb = target_strikes(spec_b, 23000.0, 11.0, 6)
    s = sigma_T(23000.0, 11.0, 6)
    assert tb["CE"] == pytest.approx(23000.0 + 1.3 * s) and tb["PE"] == pytest.approx(23000.0 - 1.3 * s)


def test_strike_snaps_to_nearest_listed_and_long_wing_is_exact(tmp_path):
    days, mk = _a_world(tmp_path, days_end=E)
    arch = NseFoArchive(archive_dir=str(tmp_path))
    bt = ChainBacktest(arch, mk, _cfg("PCS_A_k09_w200", S, E))
    # target 22361.8 snaps to 22350 (distance 11.8) rather than 22400 (38.2)
    assert bt._snap(F, E, 22361.8, "PE") == 22350.0
    _, trades = _run(tmp_path, days, mk, _cfg("PCS_A_k09_w200", S, E))
    t = trades[0]
    assert [(l["type"], l["strike"], l["short"]) for l in t["legs"]] == [
        ("PE", 22350.0, True), ("PE", 22150.0, False)]


def test_vix_gate_is_half_open_for_a_and_b():
    a = get_cell("PCS_A_k09_w200")
    assert a.vix_in_band(16.0) is True          # lower bound included
    assert a.vix_in_band(25.0) is False         # upper bound excluded
    assert a.vix_in_band(15.99) is False
    assert a.vix_in_band(24.99) is True
    assert a.vix_in_band(float("nan")) is False
    b = get_cell("LS_B_k09_wk")
    assert b.vix_in_band(12.99) is True
    assert b.vix_in_band(13.0) is False
    assert b.vix_in_band(0.5) is True           # no floor for B


def test_weekly_and_monthly_expiry_selection():
    spec_w = get_cell("LS_B_k09_wk")
    spec_m = get_cell("LS_B_k09_mo")
    listed = [E, E2, JAN23, JAN30, date(2025, 2, 6), date(2025, 2, 13), date(2025, 2, 20), FEB27]
    # weekly: earliest expiry with DTE in [3, 8] from F
    assert pick_expiry(spec_w, listed, F) == (E, 6)
    # monthly from F=Jan 3: Jan 23 (DTE 20) is weekly, not monthly; Jan 30 (DTE 27) is the monthly in [15, 28]
    assert monthly_expiries(listed, F) == [JAN30, FEB27]
    assert pick_expiry(spec_m, listed, F) == (JAN30, 27)
    # from Jan 10 the monthly is at DTE 20; the closest-to-21 rule picks it
    assert pick_expiry(spec_m, listed, date(2025, 1, 10)) == (JAN30, 20)
    # from Jan 1 the monthly is at DTE 29 (outside [15, 28]); nothing else qualifies
    assert pick_expiry(spec_m, listed, date(2025, 1, 1)) == (None, None)


def test_monthly_rule_treats_last_listed_expiry_of_month_as_monthly():
    spec_m = get_cell("LS_B_k09_mo")
    # March's last listed expiry is Mar 6 (monthly by the rule); from Feb 18 it is at DTE 16, in window;
    # the April monthly (Apr 3) is at DTE 44, outside the window
    listed = [date(2025, 3, 6), date(2025, 4, 3)]
    assert pick_expiry(spec_m, listed, date(2025, 2, 18)) == (date(2025, 3, 6), 16)
    # with Mar 6 and Mar 13 both listed, only Mar 13 (the last of March) is monthly, at DTE 23
    assert pick_expiry(spec_m, [date(2025, 3, 6), date(2025, 3, 13)], date(2025, 2, 18)) == (date(2025, 3, 13), 23)


def test_max_loss_helpers_b_is_debit_not_five_times_credit():
    from backtester.candidates import ls_debit_per_unit, pcs_max_loss_per_unit
    assert pcs_max_loss_per_unit(200.0, 25.0) == 175.0
    assert ls_debit_per_unit(50.0, 65.0, 65) == pytest.approx(50.0 + 1.0)


# ----------------------------------------------------------------- fill, exit and P&L
def test_fill_uses_f_settle_not_s_settle(tmp_path):
    prices = dict(A_PRICES)
    prices[(S, "PE", SHORT_PE)] = 99.0       # same contract on the signal day: must not be used
    days, mk = _a_world(tmp_path, prices=prices)
    _, trades = _run(tmp_path, days, mk, _cfg("PCS_A_k09_w200", S, E))
    t = trades[0]
    assert t["fill_date"] == str(F)
    short, long_ = t["legs"]
    assert short["entry_settle"] == 40.0 and short["entry_fill"] == 40.0
    assert long_["entry_settle"] == 15.0 and long_["entry_fill"] == 15.0
    assert t["entry_credit_settle"] == pytest.approx(25.0)


def test_hold_to_expiry_exits_at_intrinsic_of_index_settle(tmp_path):
    # index settles at 22300 on E: short 22350 PE intrinsic 50, long 22150 PE intrinsic 0
    days, mk = _a_world(tmp_path, index=lambda d: 22300.0 if d == E else SPOT)
    bt, trades = _run(tmp_path, days, mk, _cfg("PCS_A_k09_w200", S, E))
    assert len(trades) == 1
    t = trades[0]
    assert t["exit_date"] == str(E) and t["exit_reason"] == "expiry" and t["settled_at_expiry"] is True
    short, long_ = t["legs"]
    assert short["exit_fill"] == pytest.approx(50.0) and long_["exit_fill"] == pytest.approx(0.0)
    assert t["gross_fill_rs"] == pytest.approx((40 - 50) * LOT + (0 - 15) * LOT)
    entry_fee = bt._order_fees(F, 40 * LOT, 15 * LOT, 2)["total"]
    assert t["fee_rs"] == pytest.approx(entry_fee)          # OTM long: no exercise STT, no exit order
    assert t["exercise_stt_rs"] == 0.0
    assert t["pnl"] == pytest.approx(t["gross_fill_rs"] - entry_fee)


def test_no_early_exit_even_when_a_stop_would_have_fired(tmp_path):
    # short PE marked at 300 on D6 (> 2x the 25 credit): a stop would fire; hold-to-expiry must not
    prices = dict(A_PRICES)
    prices[(D6, "PE", SHORT_PE)] = 300.0
    days, mk = _a_world(tmp_path, prices=prices)
    _, trades = _run(tmp_path, days, mk, _cfg("PCS_A_k09_w200", S, E))
    t = trades[0]
    assert t["exit_date"] == str(E) and t["exit_reason"] == "expiry"
    assert t["dte_at_exit"] == 0 and t["stale_marks"] == 0


def test_b_long_leg_itm_pays_exercise_stt(tmp_path):
    # VIX 11, weekly k 0.9: CE 23350 and PE 22650. Index settles 23500 on E: CE intrinsic 150 is exercised.
    days = _weekdays(S, E)
    _write_world(tmp_path, days, index=lambda d: 23500.0 if d == E else SPOT)
    mk = _market(days, vix=11.0)
    bt, trades = _run(tmp_path, days, mk, _cfg("LS_B_k09_wk", S, E, legacy_costs=False))
    assert len(trades) == 1
    t = trades[0]
    ce, pe = t["legs"]
    assert ce["strike"] == 23350.0 and ce["short"] is False
    assert pe["strike"] == 22650.0 and pe["short"] is False
    ex_stt = 150.0 * 0.125 / 100 * LOT          # 0.125% of intrinsic on exercised ITM long: 121.875
    assert t["exercise_stt_rs"] == pytest.approx(ex_stt)
    assert t["exit_fee_rs"] == pytest.approx(ex_stt)
    assert t["fee_rs"] == pytest.approx(t["entry_fee_rs"] + ex_stt)


# ----------------------------------------------------------------- gates, positions, skip counts
def test_vix_gate_end_to_end_a(tmp_path):
    # window S..E has two signal days (S and E); both are out of band at VIX 25.0
    days, mk_hi = _a_world(tmp_path, vix=25.0)           # 25.0 is excluded
    bt, trades = _run(tmp_path, days, mk_hi, _cfg("PCS_A_k09_w200", S, E))
    assert trades == [] and bt.skips["vix_out_of_band"] == 2 and bt.signal_days == 2
    # 16.0 is included. At VIX 16 the k=0.9 target is 23000 - 0.9 x 567.8 = 22489 -> short strike 22500
    # (not 22350 as at VIX 20), long 22300. Prices are set on those strikes.
    prices16 = {(F, "PE", 22500): 40.0, (F, "PE", 22300): 15.0}
    days, mk_lo = _a_world(tmp_path, vix=16.0, prices=prices16)
    bt, trades = _run(tmp_path, days, mk_lo, _cfg("PCS_A_k09_w200", S, E))
    assert len(trades) == 1 and trades[0]["entry_vix"] == 16.0
    assert trades[0]["legs"][0]["strike"] == 22500.0 and "vix_out_of_band" not in bt.skips


def test_b_vix_gate_end_to_end(tmp_path):
    days = _weekdays(S, E)
    _write_world(tmp_path, days)
    bt, trades = _run(tmp_path, days, _market(days, vix=13.0), _cfg("LS_B_k09_wk", S, E))
    assert trades == [] and bt.skips["vix_out_of_band"] == 2     # signal days S and E
    bt, trades = _run(tmp_path, days, _market(days, vix=12.99), _cfg("LS_B_k09_wk", S, E))
    assert len(trades) == 1


def test_missing_vix_is_counted_as_missing_data(tmp_path):
    days, mk = _a_world(tmp_path)
    mk.loc[pd.Timestamp(S), "vix"] = float("nan")
    bt, trades = _run(tmp_path, days, mk, _cfg("PCS_A_k09_w200", S, E))
    # S: VIX missing. E: signal with no session after it in the window (no fill day), also missing_data.
    assert trades == [] and bt.skips["missing_data"] == 2


def test_one_position_at_a_time_and_skip_counters(tmp_path):
    """Monthly B: the Jan 3 fill targets Jan 30 (monthly). Signals on Jan 9, 16, 23 are skipped as
    position_open. Jan 30 closes the trade and re-signals; the Jan 31 fill targets Feb 27, which is
    beyond the window end, so it is skipped as expiry_after_end."""
    end = date(2025, 1, 31)
    days = _weekdays(S, end)
    _write_world(tmp_path, days)
    mk = _market(days, vix=11.0)
    bt, trades = _run(tmp_path, days, mk, _cfg("LS_B_k09_mo", S, end))
    assert len(trades) == 1
    assert trades[0]["expiry"] == str(JAN30) and trades[0]["exit_date"] == str(JAN30)
    assert bt.signal_days == 5                       # Jan 2, 9, 16, 23, 30
    assert bt.skips["position_open"] == 3
    assert bt.skips["expiry_after_end"] == 1
    assert bt.signals_while_open == 3


def test_unlisted_long_wing_is_skipped_and_counted(tmp_path):
    # the 22150 put (K_s - W for W=200) is not listed on the chain: no_listed_strike, not a trade
    strikes = [k for k in STRIKES if k != LONG_PE_200]
    days, mk = _a_world(tmp_path, strikes=strikes)
    bt, trades = _run(tmp_path, days, mk, _cfg("PCS_A_k09_w200", S, E))
    # S: no_listed_strike. E: signal with no fill session inside the window -> missing_data.
    assert trades == [] and bt.skips == {"no_listed_strike": 1, "missing_data": 1}


def test_expiry_after_window_end_is_not_opened(tmp_path):
    # window ends on the fill day F: the E expiry settles after the window, so the trade is not opened
    days, mk = _a_world(tmp_path, days_end=F)
    bt, trades = _run(tmp_path, days, mk, _cfg("PCS_A_k09_w200", S, F))
    assert trades == [] and bt.skips == {"expiry_after_end": 1}


# ----------------------------------------------------------------- sizing and debit max loss
def test_a_capital_sizing_uses_width_minus_settle_credit(tmp_path):
    days, mk = _a_world(tmp_path)
    cfg = _cfg("PCS_A_k09_w200", S, E, capital_mode=True, capital_rs=500_000.0)
    bt, trades = _run(tmp_path, days, mk, cfg)
    t = trades[0]
    assert t["max_loss_per_lot_rs"] == pytest.approx((200 - 25) * LOT)      # 11,375
    assert t["max_loss_rs"] == pytest.approx((200 - 25) * LOT)
    assert t["margin_per_lot_rs"] == pytest.approx((200 - 25) * LOT)
    assert t["sized_lots"] == 4                                             # floor(min(4.39, 8.79, 30))


def test_b_debit_max_loss_and_sizing_no_five_times_fallback(tmp_path, monkeypatch):
    """Trade.max_loss falls back to 5x |credit| for trades without a short leg. The B path must never reach
    it: the property below raises if anything calls it."""
    def _forbidden(self):
        raise AssertionError("Trade.max_loss (5x fallback) must not be used for candidate family B")
    monkeypatch.setattr(Trade, "max_loss", property(_forbidden))

    days = _weekdays(S, E)
    _write_world(tmp_path, days)
    mk = _market(days, vix=11.0)
    cfg = _cfg("LS_B_k09_wk", S, E, capital_mode=True, capital_rs=500_000.0)
    bt, trades = _run(tmp_path, days, mk, cfg)
    assert len(trades) == 1
    t = trades[0]
    debit_fill = (10.0 + 10.0)                         # CE and PE at F settle, slippage 0
    fee = bt._order_fees(F, 0.0, debit_fill * LOT, 2)["total"]
    debit_unit = debit_fill + fee / LOT
    assert t["max_loss_rs"] == pytest.approx(debit_unit * LOT)
    assert t["max_loss_per_lot_rs"] == pytest.approx(debit_unit * LOT)
    assert t["margin_per_lot_rs"] == pytest.approx(debit_unit * LOT)
    assert t["credit_rs"] == pytest.approx(-debit_fill * LOT)
    assert t["max_loss_rs"] != pytest.approx(5 * debit_fill * LOT)
    lots = math.floor(min(0.10 * 500_000 / (debit_unit * LOT), 0.20 * 500_000 / (debit_unit * LOT), 30))
    assert t["sized_lots"] == lots


def test_capital_sizing_debit_formula_direct(tmp_path):
    """_capital_sizing with a debit: max loss per lot = debit x 65, margin = same; lots formula holds."""
    bt = ChainBacktest(NseFoArchive(archive_dir=str(_empty_archive(tmp_path))), _market([S]),
                       ChainConfig(capital_mode=True, lots=1, candidate=get_cell("LS_B_k09_wk")))
    trade = Trade(strategy_name="LS_B_k09_wk", entry_date=F, legs=[], lots=1, lot_size=LOT)
    lots, ml, margin, why = bt._capital_sizing(trade, 0.0, debit_unit=100.0)
    assert why is None and ml == pytest.approx(6500.0) and margin == pytest.approx(6500.0)
    assert lots == math.floor(min(50_000 / 6500, 100_000 / 6500, 30))         # 7
    lots, ml, margin, why = bt._capital_sizing(trade, 0.0, debit_unit=0.0)
    assert why == "invalid_max_loss" and lots == 0


def _empty_archive(root):
    root.mkdir(parents=True, exist_ok=True)
    _write_world(root, [S], prices={})
    return root


# ----------------------------------------------------------------- default path, harness, CLI
def test_default_config_has_no_candidate_and_no_candidate_fields(tmp_path):
    assert ChainConfig().candidate is None
    days, mk = _a_world(tmp_path)
    cfg = ChainConfig(start=S, end=E, slippage_multiplier=0.0, lots=1, cash_settlement=True,
                      legacy_costs=False)
    arch = NseFoArchive(archive_dir=str(tmp_path))
    bt = ChainBacktest(arch, mk, cfg)
    trades = bt.run()
    assert all("candidate" not in t and "pnl_per_lot" in t for t in trades)


def test_candidate_config_rejects_gates_legacy_costs_and_legacy_settlement(tmp_path):
    arch = NseFoArchive(archive_dir=str(_empty_archive(tmp_path / "x")))
    m = _market([S])
    with pytest.raises(ValueError):
        ChainBacktest(arch, m, ChainConfig(candidate=get_cell("LS_B_k09_wk"), legacy_costs=True))
    with pytest.raises(ValueError):
        ChainBacktest(arch, m, ChainConfig(candidate=get_cell("LS_B_k09_wk"), cash_settlement=False))
    with pytest.raises(ValueError):
        ChainBacktest(arch, m, ChainConfig(candidate=get_cell("LS_B_k09_wk"), min_vix_floor=12.0))


def test_harness_projection_reads_as_normalised_schema(tmp_path):
    from strategy_eval.schema import normalize
    days, mk = _a_world(tmp_path, index=lambda d: 22300.0 if d == E else SPOT)
    _, trades = _run(tmp_path, days, mk, _cfg("PCS_A_k09_w200", S, E))
    recs = [harness_record(t) for t in trades]
    assert "pnl_per_lot" not in recs[0]
    df = normalize(pd.DataFrame(recs))
    assert df["pricing_source"].iloc[0] == "chain" and df["entry_vix"].iloc[0] == 20.0
    assert df["max_loss_rs"].iloc[0] == pytest.approx(175 * LOT)


@pytest.fixture
def cli(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "run_candidates", Path(__file__).resolve().parents[1] / "scripts" / "run_candidates.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_cli_writes_trade_and_skip_tables_readable_by_harness(tmp_path, cli, monkeypatch):
    from strategy_eval.schema import read_normalized
    days, mk = _a_world(tmp_path / "arch", index=lambda d: 22300.0 if d == E else SPOT)
    monkeypatch.setitem(cli.PHASE_WINDOWS, "train", (S, E))
    monkeypatch.setattr(cli, "load_market", lambda end, market_start=None: mk)
    out = tmp_path / "out"
    rc = cli.main(["--family", "A", "--cell", "PCS_A_k09_w200", "--phase", "train", "--lots", "10",
                   "--slippage", "0.0", "--archive-dir", str(tmp_path / "arch"), "--out", str(out)])
    assert rc == 0
    payload = json.load(open(out / "trades_PCS_A_k09_w200.json"))
    assert payload["n"] == 1 and payload["lots"] == 10
    assert payload["trades"][0]["lots"] == 10
    df = read_normalized(out / "trades_PCS_A_k09_w200.json")
    assert len(df) == 1 and df["max_loss_rs"].iloc[0] == pytest.approx(175 * 650)
    skips = pd.read_csv(out / "skips_PCS_A_k09_w200.csv")
    assert list(skips.columns) == ["reason", "count"]


def test_cli_holdout_refuses_without_allow_flag(tmp_path, cli):
    with pytest.raises(SystemExit):
        cli.main(["--family", "A", "--phase", "holdout", "--out", str(tmp_path / "o")])


def test_cli_rejects_cell_from_other_family(tmp_path, cli):
    with pytest.raises(SystemExit):
        cli.main(["--family", "B", "--cell", "PCS_A_k09_w200", "--phase", "train",
                  "--out", str(tmp_path / "o")])


def test_cli_holdout_end_is_last_archive_day_and_does_not_write_registry(tmp_path, cli, monkeypatch, capsys):
    days, mk = _a_world(tmp_path / "arch", index=lambda d: 22300.0 if d == E else SPOT)
    seen = {}

    def fake_market(end, market_start=None):
        seen["end"] = end
        return mk

    monkeypatch.setattr(cli, "load_market", fake_market)
    out = tmp_path / "out"
    rc = cli.main(["--family", "A", "--cell", "PCS_A_k09_w200", "--phase", "holdout", "--allow-holdout",
                   "--slippage", "0.0", "--archive-dir", str(tmp_path / "arch"), "--out", str(out)])
    assert rc == 0
    assert seen["end"] == days[-1]
    text = capsys.readouterr().out
    assert "written by strategy_eval" in text
    # the script writes only trade and skip tables; no registry or ledger file appears in the output dir
    assert sorted(p.name for p in out.iterdir()) == ["skips_PCS_A_k09_w200.csv", "trades_PCS_A_k09_w200.json"]


def test_phase_windows_match_preregistration():
    assert PHASE_WINDOWS["train"] == (date(2019, 2, 11), date(2021, 12, 31))
    assert PHASE_WINDOWS["test"] == (date(2022, 1, 1), date(2023, 12, 31))
    assert PHASE_WINDOWS["holdout"] == (date(2024, 1, 1), None)
