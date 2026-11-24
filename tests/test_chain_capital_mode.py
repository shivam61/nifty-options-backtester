"""Tests for the opt-in capital-aware mode of the real-price chain backtest (ChainConfig.capital_mode).

  (a) default mode is unchanged: the per-lot trade fields of a capital-mode run equal the default run
  (b) lots = floor(min(risk_cap / max_loss_per_lot, margin_cap / margin_per_lot, max_lots)), hand-computed
  (c) the kill switch halts new entries after a drawdown breach, and force-closes an open trade
  (d) MaxDD, CAGR, Sharpe and utilisation of capital_summary on a known equity curve

All data is a tiny synthetic archive written to tmp_path (no real archive, no network).
PCS world: short 22650 PE filled at 40, long 22450 PE filled at 15 -> credit 25/unit, width 200.
Max loss per lot = (200 - 25) x 65 = 11,375 Rs.  Capital 5L: risk cap 50,000 -> floor(4.40) = 4 lots;
margin cap 100,000 -> floor(8.79) = 8 lots; max_lots 30. Sized lots = 4.
"""

import gzip
from datetime import date

import pandas as pd
import pytest

from backtester.chain_engine import ChainBacktest, ChainConfig
from data.nse_fo_archive import NseFoArchive
from strategies.base import Leg, Trade

COLS = ["date", "expiry", "strike", "opt", "open", "high", "low", "close", "settle",
        "contracts", "open_int", "underlying"]
S = date(2025, 1, 2)     # signal day (Thursday expiry day of cycle 1)
F = date(2025, 1, 3)     # fill day
D6 = date(2025, 1, 6)
D7 = date(2025, 1, 7)
X = date(2025, 1, 8)     # DTE 1 exit day
E = date(2025, 1, 9)     # cycle-1 expiry = cycle-2 signal day
F2 = date(2025, 1, 10)   # cycle-2 fill day
E2 = date(2025, 1, 16)   # cycle-2 expiry (DTE 6 at fill)
SPOT = 23000.0
VIX = 11.0
SP, LP = 22650, 22450    # PCS strikes at SPOT, VIX 11, DTE 6 (generate_legs)
LOT = 65
ML_LOT = (SP - LP - 25.0) * LOT       # 11,375
CAPITAL = 500_000.0


# ----------------------------------------------------------------- helpers
def _row(d, exp, k, opt, settle, contracts=100, oi=1000, close=None):
    close = settle if close is None else close
    return [d.isoformat(), exp.isoformat(), float(k), opt, 0.0, 0.0, 0.0, close, settle,
            contracts, oi, float("nan")]


def _write(root, d, rows):
    path = root / "daily" / (d.strftime("%Y%m%d") + ".csv.gz")
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt") as fh:
        pd.DataFrame(rows, columns=COLS).to_csv(fh, index=False)


def _market(days, vix=VIX):
    idx = pd.DatetimeIndex([pd.Timestamp(d) for d in days])
    return pd.DataFrame({
        "nifty_close": [SPOT] * len(days),
        "vix": [vix] * len(days),
        "nifty_return_5d": [0.0] * len(days),
        "vix_change_5d": [0.0] * len(days),
    }, index=idx)


def _pcs_cycle1(root, d6=(40.0, 15.0), exit_px=(10.0, 4.0)):
    """Signal S, fill F at (40, 15), marks D6 / D7, exit X. Same shape as test_chain_arms._pcs_world."""
    _write(root, S, [_row(S, S, 23000, "PE", 1.0)])
    _write(root, F, [_row(F, E, SP, "PE", 40.0), _row(F, E, LP, "PE", 15.0)])
    _write(root, D6, [_row(D6, E, SP, "PE", d6[0]), _row(D6, E, LP, "PE", d6[1])])
    _write(root, D7, [_row(D7, E, SP, "PE", 40.0), _row(D7, E, LP, "PE", 15.0)])
    _write(root, X, [_row(X, E, SP, "PE", exit_px[0]), _row(X, E, LP, "PE", exit_px[1])])
    return [S, F, D6, D7, X]


def _cycle2(root):
    """Cycle 2: signal on E (expiry day of cycle 1), fill F2 at (40, 15) for expiry E2."""
    _write(root, E, [_row(E, E, 23000, "PE", 1.0)])
    _write(root, F2, [_row(F2, E2, SP, "PE", 40.0), _row(F2, E2, LP, "PE", 15.0)])
    return [E, F2]


def _cfg(**kw):
    base = dict(start=S, end=F2, capital_mode=True, capital_rs=CAPITAL)
    base.update(kw)
    return ChainConfig(**base)


def _run(root, days, cfg):
    arch = NseFoArchive(archive_dir=str(root))
    bt = ChainBacktest(arch, _market(days), cfg)
    return bt, bt.run()


def _leg(opt, strike, short, premium):
    return Leg(opt, strike, short, premium, premium, 1, LOT)


def _bt_for_unit(**kw):
    """ChainBacktest with an unused archive: only the sizing helpers are exercised."""
    return ChainBacktest(None, _market([S]), ChainConfig(capital_mode=True, **kw))


def _pcs_trade(short_strike, long_strike, short_prem, long_prem):
    legs = [_leg("PE", short_strike, True, short_prem), _leg("PE", long_strike, False, long_prem)]
    return Trade(strategy_name="weekly_pcs", entry_date=F, legs=legs, lots=1, lot_size=LOT)


# ----------------------------------------------------------------- config guard
def test_capital_mode_requires_one_lot():
    with pytest.raises(ValueError):
        ChainBacktest(None, _market([S]), ChainConfig(capital_mode=True, lots=2))


def test_capital_mode_is_off_by_default():
    cfg = ChainConfig()
    assert cfg.capital_mode is False
    assert cfg.capital_rs == 500_000.0
    assert cfg.risk_cap_pct == 0.10 and cfg.margin_cap_pct == 0.20
    assert cfg.max_lots == 30 and cfg.kill_dd_pct == 0.20 and cfg.margin_proxy is None


# ----------------------------------------------------------------- (b) lots formula
def test_lots_formula_hand_computed_risk_binds(tmp_path):
    bt = _bt_for_unit()
    trade = _pcs_trade(SP, LP, 40.0, 15.0)
    credit = trade.net_credit
    assert credit == pytest.approx(25.0)
    lots, ml, margin, why = bt._capital_sizing(trade, credit)
    # max loss per lot = (200 - 25) x 65 = 11,375; risk 50,000 / 11,375 = 4.40 -> 4
    # margin 100,000 / 11,375 = 8.79 -> 8; max_lots 30 -> min(4, 8, 30) = 4
    assert ml == pytest.approx(ML_LOT) == pytest.approx(11_375.0)
    assert margin == pytest.approx(ML_LOT)              # default proxy: margin = max loss per lot
    assert why is None and lots == 4


def test_lots_formula_margin_proxy_binds():
    # margin proxy = 3 x max loss -> 34,125 per lot; 100,000 / 34,125 = 2.93 -> 2 < risk 4
    bt = _bt_for_unit(margin_proxy=lambda ml, trade: 3.0 * ml)
    trade = _pcs_trade(SP, LP, 40.0, 15.0)
    lots, ml, margin, why = bt._capital_sizing(trade, trade.net_credit)
    assert margin == pytest.approx(3.0 * ML_LOT)
    assert why is None and lots == 2


def test_lots_formula_max_lots_binds():
    bt = _bt_for_unit(max_lots=3)                       # min(4, 8, 3) = 3
    trade = _pcs_trade(SP, LP, 40.0, 15.0)
    lots, _, _, why = bt._capital_sizing(trade, trade.net_credit)
    assert why is None and lots == 3


def test_lots_zero_when_one_lot_exceeds_risk_cap():
    # width 1000 -> max loss per lot = (1000 - 25) x 65 = 63,375 > 50,000 risk cap -> 0 lots
    bt = _bt_for_unit()
    trade = _pcs_trade(23000, 22000, 40.0, 15.0)
    lots, ml, _, why = bt._capital_sizing(trade, trade.net_credit)
    assert ml == pytest.approx(63_375.0)
    assert why is None and lots == 0


def test_credit_at_or_above_width_is_invalid_max_loss():
    bt = _bt_for_unit()
    trade = _pcs_trade(SP, LP, 230.0, 15.0)            # credit 215 > width 200
    lots, ml, _, why = bt._capital_sizing(trade, trade.net_credit)
    assert lots == 0 and why == "invalid_max_loss" and not ml > 0


def test_end_to_end_sized_fields_and_per_lot_path_unchanged(tmp_path):
    days = _pcs_cycle1(tmp_path)
    bt, trades = _run(tmp_path, days, _cfg(end=X))
    assert len(trades) == 1, (trades, bt.skip_log)
    t = trades[0]
    assert t["sized_lots"] == 4
    # max loss uses the fill credit (slippage inside the fills), not the 25 mid-price credit
    assert t["max_loss_per_lot_rs"] == pytest.approx((SP - LP - t["entry_credit_fill"]) * LOT)
    assert t["margin_used_rs"] == pytest.approx(4 * t["max_loss_per_lot_rs"])
    assert t["pnl_sized_rs"] == pytest.approx(4 * t["pnl_per_lot"])
    assert t["lots"] == 1 and t["pnl"] == t["pnl_per_lot"]

    # (a) the per-lot record is the default-mode record, field for field
    arch = NseFoArchive(archive_dir=str(tmp_path))
    dflt = ChainBacktest(arch, _market(days), ChainConfig(start=S, end=X)).run()
    assert len(dflt) == 1
    base = dict(dflt[0])
    got = {k: v for k, v in t.items() if k in base}
    assert set(base) <= set(t)
    assert got == base
    assert "sized_lots" not in base            # default records carry no capital fields


# ----------------------------------------------------------------- (c) kill switch
def test_kill_switch_halts_new_entries_after_breach(tmp_path):
    # Cycle 1 exits on X at short 90 / long 15: loss 50 x 65 x 4 = 13,000 gross, below a 2% (10,000) line.
    days = _pcs_cycle1(tmp_path, exit_px=(90.0, 15.0)) + _cycle2(tmp_path)
    bt, trades = _run(tmp_path, days, _cfg(kill_dd_pct=0.02))
    assert len(trades) == 1, (trades, bt.skip_log)
    assert trades[0]["exit_date"] == str(X)
    assert bt.kill_active is True and bt.kill_date == X
    assert bt.skips["kill_switch"] == 1
    assert bt.skip_log[-1]["reason"] == "kill_switch" and bt.skip_log[-1]["date"] == str(E)


def test_same_world_without_breach_opens_cycle_two(tmp_path):
    days = _pcs_cycle1(tmp_path, exit_px=(90.0, 15.0)) + _cycle2(tmp_path)
    bt, trades = _run(tmp_path, days, _cfg(kill_dd_pct=0.5))   # control: a 50% line is never breached
    # run() returns closed trades only: cycle 2 is filled on F2 and still open at the window end
    assert len(trades) == 1 and bt.diag["open_at_end"] == 1, (trades, bt.skip_log)
    assert bt.kill_active is False and bt.skips.get("kill_switch", 0) == 0


def test_kill_switch_force_closes_open_trade_on_breach(tmp_path):
    # D6 short mark 60: loss ~21/unit x 65 x 4 lots = ~5,460 breaches the 1.0% (5,000) line while open.
    # Loss stays under the stop-loss rule (pnl < -100% of credit, i.e. -24 per unit), so the kill
    # switch is the only exit on D6.
    days = _pcs_cycle1(tmp_path, d6=(60.0, 15.0), exit_px=(40.0, 15.0))
    bt, trades = _run(tmp_path, days, _cfg(end=X, kill_dd_pct=0.01))
    assert len(trades) == 1, (trades, bt.skip_log)
    t = trades[0]
    assert t["exit_reason"] == "capital_kill"
    assert t["exit_date"] == str(D6)
    assert bt.kill_date == D6 and bt.kill_active is True
    assert t["sized_lots"] == 4 and t["pnl_sized_rs"] == pytest.approx(4 * t["pnl_per_lot"])


# ----------------------------------------------------------------- (d) equity-curve metrics
def _curve_bt(values, dates):
    bt = _bt_for_unit()
    bt.cfg.capital_rs = CAPITAL
    bt.capital_curve = [(d, v, 0.0) for d, v in zip(dates, values)]
    return bt


def test_maxdd_cagr_and_sharpe_on_known_curve():
    dates = [date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4), date(2025, 6, 30)]
    values = [500_000.0, 550_000.0, 440_000.0, 600_000.0, 450_000.0]
    bt = _curve_bt(values, dates)
    s = bt.capital_summary(echo=False)

    # MaxDD: 550k -> 440k is 20%; 600k -> 450k is 25% (the larger one)
    assert s["max_dd_pct"] == pytest.approx(25.0)
    # CAGR = (450k / 500k)^(365.25 / calendar days) - 1 over the curve span
    days = (dates[-1] - dates[0]).days
    assert s["curve_years"] == pytest.approx(days / 365.25, abs=1e-4)
    assert s["cagr_pct"] == pytest.approx(((450_000 / 500_000) ** (365.25 / days) - 1) * 100, abs=1e-3)
    assert s["final_equity"] == pytest.approx(450_000.0)
    assert s["total_return_pct"] == pytest.approx(-10.0)
    # daily Sharpe: mean / sample std of session returns x sqrt(252)
    rets = [b / a - 1 for a, b in zip(values, values[1:])]
    mu = sum(rets) / len(rets)
    sd = (sum((r - mu) ** 2 for r in rets) / (len(rets) - 1)) ** 0.5
    assert s["sharpe_daily_ann"] == pytest.approx(mu / sd * 252 ** 0.5, abs=1e-3)


def test_monotone_curve_has_zero_maxdd_and_positive_cagr():
    dates = [date(2024, 1, 1), date(2024, 12, 31), date(2025, 12, 31)]
    bt = _curve_bt([500_000.0, 550_000.0, 600_000.0], dates)
    s = bt.capital_summary(echo=False)
    assert s["max_dd_pct"] == 0.0
    assert s["cagr_pct"] > 0


def test_utilisation_is_margin_over_capital_averaged_over_sessions():
    dates = [date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)]
    bt = _bt_for_unit()
    bt.capital_curve = [(d, CAPITAL, m) for d, m in zip(dates, [0.0, 50_000.0, 50_000.0, 0.0])]
    s = bt.capital_summary(echo=False)
    assert s["capital_utilisation_avg_pct"] == pytest.approx(5.0)      # (0 + 0.1 + 0.1 + 0) / 4
    assert s["capital_utilisation_max_pct"] == pytest.approx(10.0)


def test_empty_run_summary_is_well_formed():
    bt = _bt_for_unit()
    s = bt.capital_summary(echo=False)
    assert s["trades"] == 0 and s["final_equity"] == CAPITAL
    assert s["cagr_pct"] is None and s["sharpe_daily_ann"] is None and s["max_dd_pct"] == 0.0


# ----------------------------------------------------------------- driver (CLI)
def test_cli_capital_mode_writes_capital_outputs_and_keeps_trade_table(tmp_path, monkeypatch):
    from tests.test_run_chain_backtest import cli

    days = _pcs_cycle1(tmp_path / "archive", exit_px=(40.0, 15.0))
    monkeypatch.setattr(cli, "load_market", lambda end, market_start=None: _market(days))
    base = ["--start", str(S), "--end", str(X), "--slippage", "1.0",
            "--archive-dir", str(tmp_path / "archive"), "--allow-holdout"]

    out_c = tmp_path / "cap"
    assert cli.main(base + ["--capital-mode", "--out", str(out_c)]) == 0
    cap = __import__("json").load(open(out_c / "capital_x1.json"))
    assert cap["trades"] == 1 and cap["avg_lots"] == 4.0
    trades_c = __import__("json").load(open(out_c / "trades_x1.json"))["trades"]

    out_d = tmp_path / "dflt"
    assert cli.main(base + ["--out", str(out_d)]) == 0
    assert not (out_d / "capital_x1.json").exists()
    trades_d = __import__("json").load(open(out_d / "trades_x1.json"))["trades"]
    assert [t["pnl_per_lot"] for t in trades_c] == [t["pnl_per_lot"] for t in trades_d]
    assert "sized_lots" not in trades_d[0] and "sized_lots" in trades_c[0]


def test_cli_rejects_capital_mode_with_multi_lot(tmp_path, monkeypatch):
    from tests.test_run_chain_backtest import cli

    with pytest.raises(SystemExit):
        cli.main(["--start", str(S), "--end", str(X), "--capital-mode", "--lots", "2",
                  "--archive-dir", str(tmp_path), "--out", str(tmp_path / "o")])
