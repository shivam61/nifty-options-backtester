"""Tests for the real-price chain backtest: archive loader, snapping, liquidity, expiry-day
settle, slippage multiplier, and hand-computed IC / PCS round trips.

All data is a tiny synthetic archive written to tmp_path (no real archive, no network).
Expected P&L values are hand-computed in the comments from the price inputs and the CostModel
formulas; strikes are asserted against the repo's own generate_legs output.
"""

import gzip
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from backtester.chain_engine import ChainBacktest, ChainConfig
from data.nse_fo_archive import NseFoArchive
from strategies.weekly_strategies import WeeklyIronCondor, WeeklyPutCreditSpread

COLS = ["date", "expiry", "strike", "opt", "open", "high", "low", "close", "settle",
        "contracts", "open_int", "underlying"]
S = date(2025, 1, 2)          # Thursday expiry day = signal day
F = date(2025, 1, 3)          # fill day (next session)
E = date(2025, 1, 9)          # expiry used by the trade (DTE 6 at fill)
X = date(2025, 1, 8)          # DTE 1: dte_limit exit day
SPOT = 23000.0


def _row(d, exp, k, opt, settle, contracts=100, oi=1000, close=None):
    close = settle if close is None else close
    return [d.isoformat(), exp.isoformat(), float(k), opt, 0.0, 0.0, 0.0, close, settle,
            contracts, oi, float("nan")]


def _write(root, d, rows):
    path = root / "daily" / (d.strftime("%Y%m%d") + ".csv.gz")
    path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows, columns=COLS)
    with gzip.open(path, "wt") as fh:
        df.to_csv(fh, index=False)


def _market(days, spot=SPOT, vix=15.0, spot_map=None):
    spot_map = spot_map or {}
    idx = pd.DatetimeIndex([pd.Timestamp(d) for d in days])
    return pd.DataFrame({
        "nifty_close": [spot_map.get(d, spot) for d in days],
        "vix": [vix] * len(days),
        "nifty_return_5d": [0.0] * len(days),
        "vix_change_5d": [0.0] * len(days),
    }, index=idx)


def _cfg(mult=1.0):
    return ChainConfig(slippage_multiplier=mult, start=S, end=S)


def _run(root, days, market, mult=1.0, index_fallback=None):  # market gives the calendar
    arch = NseFoArchive(archive_dir=str(root), index_fallback=index_fallback)
    bt = ChainBacktest(arch, market, _cfg(mult))
    trades = bt.run()
    return bt, trades


def _expected_fees(credit_per_unit, n_legs):
    notional = credit_per_unit * 65
    stt = notional * 0.0625 / 100
    exch = notional * 0.0019 / 100
    sebi = notional * 0.0001 / 100
    stamp = notional * 0.003 / 100
    brok = 20.0 * n_legs * 2
    return stt + exch + sebi + stamp + brok + brok * 0.18


# ----------------------------------------------------------------- loader
def test_loader_days_weekly_expiries_and_price_fallback(tmp_path):
    _write(tmp_path, S, [
        _row(S, S, 23000, "PE", 10.0),
        _row(S, E, 23000, "PE", 0.0, contracts=0, oi=5, close=7.5),   # settle 0 -> close fallback
        _row(S, date(2025, 3, 27), 23000, "PE", 99.0),                 # far-future: not weekly
        _row(S, E, 23000, "CE", 50.0),
    ])
    _write(tmp_path, F, [_row(F, E, 23000, "PE", 12.0)])
    arch = NseFoArchive(archive_dir=str(tmp_path))
    assert arch.trading_days() == [S, F]
    assert arch.expires_on(S) and not arch.expires_on(F)
    assert arch.weekly_expiries(S) == [S, E]        # 2025-03-27 is 84 days out: excluded
    assert arch.weekly_expiries(F) == [E]
    assert arch.price(S, E, 23000, "PE", field="settle") == 0.0
    assert arch.row(S, E, 23000, "PE")["px"] == pytest.approx(7.5)
    assert arch.row(S, E, 23000, "PE")["px_src"] == 1
    assert arch.row(F, E, 23000, "PE")["px_src"] == 0
    assert arch.row(F, E, 23100, "PE") is None
    assert arch.next_day(S) == F and arch.next_day(F) is None


def test_snap_to_nearest_listed_strike_with_tie_to_lower(tmp_path):
    rows = [_row(F, E, k, "PE", 5.0) for k in (22450, 22500, 22550)]
    _write(tmp_path, F, rows)
    _write(tmp_path, S, [_row(S, S, 23000, "PE", 1.0)])
    arch = NseFoArchive(archive_dir=str(tmp_path))
    bt = ChainBacktest(arch, _market([S, F]), _cfg())
    assert bt._snap(F, E, 22510, "PE") == 22500.0
    assert bt._snap(F, E, 22525, "PE") == 22500.0        # equidistant: lower strike
    assert bt._snap(F, E, 22600, "PE") == 22550.0
    assert bt._snap(F, E, 22600, "CE") is None           # no CE listed


# ----------------------------------------------------------------- round trips
def _write_ic_world(root, zero_liq_short=False):
    """Archive for one IC cycle: signal S (expiry day), fill F, marks D6/D7, exit X (DTE 1)."""
    legs = WeeklyIronCondor(lots=1, lot_size=65).generate_legs(SPOT, 15.0, 6, 0.065)
    got = {(l.option_type, l.is_short): l.strike for l in legs}
    assert got == {("CE", True): 23350, ("CE", False): 23600, ("PE", True): 22450, ("PE", False): 22200}
    fill = {(23350, "CE"): 30.0, (23600, "CE"): 10.0, (22450, "PE"): 25.0, (22200, "PE"): 8.0}
    exit_px = {(23350, "CE"): 5.0, (23600, "CE"): 2.0, (22450, "PE"): 6.0, (22200, "PE"): 3.0}
    d6, d7 = date(2025, 1, 6), date(2025, 1, 7)
    _write(root, S, [_row(S, S, 23000, "PE", 1.0)])
    for d in (F, d6, d7):
        rows = []
        for (k, opt), v in fill.items():
            liq = (0, 0) if (zero_liq_short and d == F and k == 23350) else (100, 1000)
            rows.append(_row(d, E, k, opt, v, contracts=liq[0], oi=liq[1]))
        _write(root, d, rows)
    _write(root, X, [_row(X, E, k, opt, v) for (k, opt), v in exit_px.items()])
    return [S, F, d6, d7, X]


def test_ic_round_trip_hand_computed(tmp_path):
    days = _write_ic_world(tmp_path)
    bt, trades = _run(tmp_path, days, _market(days, vix=15.0))
    assert len(trades) == 1, (trades, bt.skips, bt.skip_log)
    t = trades[0]
    assert t["strategy"] == "weekly_ic"
    assert t["fill_date"] == str(F) and t["expiry"] == str(E)
    assert t["exit_date"] == str(X) and t["exit_reason"] == "dte_limit"
    # fills: short 30 -> 29.55, long 10 -> 10.45, short 25 -> 24.55, long 8 -> 8.45
    credit = 29.55 - 10.45 + 24.55 - 8.45
    assert t["entry_credit_fill"] == pytest.approx(credit)
    # exit: short CE 5 -> buy 5.45, long CE 2 -> sell 1.55, short PE 6 -> 6.45, long PE 3 -> 2.55
    gross = (29.55 - 5.45) * 65 - (10.45 - 1.55) * 65 + (24.55 - 6.45) * 65 - (8.45 - 2.55) * 65
    fees = _expected_fees(credit, 4)
    assert t["pnl"] == pytest.approx(gross - fees, abs=0.01)
    # hand: gross 1566.5 - 578.5 + 1176.5 - 383.5 = 1781.0; fees: notional 2288 (fees 1.5444)
    # + brokerage 20 x 4 legs x 2 = 160 + GST 28.8 = 190.3444 -> 1590.6556
    assert t["pnl"] == pytest.approx(1590.6556, abs=0.01)
    assert t["expiry"] == str(E) and t["holding_days"] == (X - F).days
    assert t["entry_pen_rs"] == pytest.approx(4 * 0.45 * 65)
    assert t["close_slip_rs"] == pytest.approx(4 * 0.45 * 65)
    assert t["stale_marks"] == 0


def test_pcs_round_trip_hand_computed(tmp_path):
    legs = WeeklyPutCreditSpread(lots=1, lot_size=65).generate_legs(SPOT, 11.0, 6, 0.065)
    sp = [l.strike for l in legs if l.is_short][0]
    lp = [l.strike for l in legs if not l.is_short][0]
    assert (sp, lp) == (22650, 22450)
    _write(tmp_path, S, [_row(S, S, 23000, "PE", 1.0)])
    fill = {sp: 40.0, lp: 15.0}
    _write(tmp_path, F, [_row(F, E, k, "PE", v) for k, v in fill.items()])
    _write(tmp_path, date(2025, 1, 6), [_row(date(2025, 1, 6), E, k, "PE", v) for k, v in fill.items()])
    _write(tmp_path, date(2025, 1, 7), [_row(date(2025, 1, 7), E, k, "PE", v) for k, v in fill.items()])
    _write(tmp_path, X, [_row(X, E, sp, "PE", 10.0), _row(X, E, lp, "PE", 4.0)])
    days = [S, F, date(2025, 1, 6), date(2025, 1, 7), X]
    bt, trades = _run(tmp_path, days, _market(days, vix=11.0))
    assert len(trades) == 1, (trades, bt.skip_log)
    t = trades[0]
    assert t["strategy"] == "weekly_pcs" and t["exit_reason"] == "dte_limit"
    credit = 39.55 - 15.45                                    # 24.10
    gross = (39.55 - 10.45) * 65 - (15.45 - 3.55) * 65        # 1891.5 - 773.5
    assert t["pnl"] == pytest.approx(gross - _expected_fees(credit, 2), abs=0.01)
    assert t["pnl"] == pytest.approx(1022.54, abs=0.01)


def test_expiry_day_exit_uses_expiry_settle(tmp_path):
    """The day before expiry is absent from the calendar, so the trade is held to expiry day
    and closes at that day's settle (intrinsic at a 22400 expiry close)."""
    legs = WeeklyPutCreditSpread(lots=1, lot_size=65).generate_legs(SPOT, 11.0, 6, 0.065)
    sp = [l.strike for l in legs if l.is_short][0]
    lp = [l.strike for l in legs if not l.is_short][0]
    fill = {sp: 40.0, lp: 15.0}
    _write(tmp_path, S, [_row(S, S, 23000, "PE", 1.0)])
    _write(tmp_path, F, [_row(F, E, k, "PE", v) for k, v in fill.items()])
    _write(tmp_path, date(2025, 1, 6), [_row(date(2025, 1, 6), E, k, "PE", v) for k, v in fill.items()])
    _write(tmp_path, date(2025, 1, 7), [_row(date(2025, 1, 7), E, k, "PE", v) for k, v in fill.items()])
    # 2020+ archive convention: expiry-day 'settle' holds the INDEX settlement (22400) on every row
    _write(tmp_path, E, [_row(E, E, sp, "PE", 22400.0, close=250.0), _row(E, E, lp, "PE", 22400.0, close=50.0)])
    days = [S, F, date(2025, 1, 6), date(2025, 1, 7), E]
    market = _market(days, vix=11.0, spot_map={E: 22400.0})
    bt, trades = _run(tmp_path, days, market)
    assert len(trades) == 1, (trades, bt.skip_log)
    t = trades[0]
    assert t["exit_date"] == str(E)
    assert t["exit_spot"] == pytest.approx(22400.0)
    assert [l["exit_settle"] for l in t["legs"] if l["short"]] == [pytest.approx(250.0)]
    assert t["expiry_intrinsic_dev"] == pytest.approx(0.0, abs=1e-9)  # close 250 = intrinsic
    # exit fills at intrinsic (index settle 22400): short buy 250.45, long sell 49.55
    gross = (39.55 - 250.45) * 65 + (49.55 - 15.45) * 65
    assert t["pnl"] == pytest.approx(gross - _expected_fees(24.10, 2), abs=0.01)


def test_illiquid_short_leg_is_skipped_and_counted(tmp_path):
    days = _write_ic_world(tmp_path, zero_liq_short=True)
    bt, trades = _run(tmp_path, days, _market(days, vix=15.0))
    assert trades == []
    assert bt.skips["illiquid_leg"] == 1
    assert bt.skip_log[0]["strike"] == 23350


def test_slippage_multiplier_scales_penalties(tmp_path):
    days = _write_ic_world(tmp_path)
    _, t1 = _run(tmp_path, days, _market(days, vix=15.0), mult=1.0)
    _, t2 = _run(tmp_path, days, _market(days, vix=15.0), mult=2.0)
    assert t1[0]["entry_pen_rs"] == pytest.approx(4 * 0.45 * 65)
    assert t2[0]["entry_pen_rs"] == pytest.approx(2 * t1[0]["entry_pen_rs"])
    assert t2[0]["close_slip_rs"] == pytest.approx(2 * t1[0]["close_slip_rs"])
    # each of the 4 legs moves 0.45 per unit more at 2x than at 1x: credit falls by 4*0.45
    assert t1[0]["entry_credit_fill"] - t2[0]["entry_credit_fill"] == pytest.approx(4 * 0.45)
    assert t2[0]["pnl"] < t1[0]["pnl"]
