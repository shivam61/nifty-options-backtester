"""Tests for the three opt-in weekly structural/exit arms of the real-price chain backtest.

  A  ChainConfig.pcs_put_sd / --pcs-put-sd     PCS short put at 1.2 SD (baseline 0.9)
  B  ChainConfig.exit_arms.breach_stop=False / --no-breach-stop
                                                close-based short-strike breach stop disabled (PCS, IC)
  C  ChainConfig.exit_arms.ic_hold_to_expiry=True / --ic-hold-to-expiry
                                                IC exits only on the credit-multiple stop and expiry settle

Defaults must reproduce the baseline exactly: tests/fixtures/chain_arms_baseline.json was generated
from the pre-arm code (git main 7a1b3ea) by _baseline_snapshot(). All data is synthetic.

  F1  ChainConfig.exit_arms.hold_to_expiry=True / --no-early-exits
                                                PCS and IC held to expiry settle; no other exit
  F2  ChainConfig.min_vix_floor=13 / --min-vix 13
                                                entry gate: skip signals with VIX below the floor
  T0  ChainConfig.capital_protection_per_lot    capital-protection equity scales with lots (default True)
"""

import json
import math
from datetime import date
from pathlib import Path

import pytest

from backtester.chain_engine import ChainBacktest, ChainConfig
from backtester.weekly_exit_policy import check_weekly_exit
from config import WeeklyBacktestConfig
from data.nse_fo_archive import NseFoArchive
from strategies.base import Leg, Trade, TradeAction
from strategies.weekly_strategies import WeeklyIronCondor, WeeklyPutCreditSpread
from tests.test_chain_engine import (
    E, F, S, SPOT, X, _expected_fees, _row, _write, _write_ic_world,
)
from tests.test_run_chain_backtest import _synthetic_market, _write_ic_archive, cli

FIXTURE = Path(__file__).parent / "fixtures" / "chain_arms_baseline.json"
D6, D7 = date(2025, 1, 6), date(2025, 1, 7)
VIX_PCS = 11.0
VIX_IC = 15.0


# ----------------------------------------------------------------- helpers
def _market(days, vix, spot_map=None):
    import pandas as pd
    spot_map = spot_map or {}
    idx = pd.DatetimeIndex([pd.Timestamp(d) for d in days])
    return pd.DataFrame({
        "nifty_close": [spot_map.get(d, SPOT) for d in days],
        "vix": [vix] * len(days),
        "nifty_return_5d": [0.0] * len(days),
        "vix_change_5d": [0.0] * len(days),
    }, index=idx)


def _run(root, days, market, mult=1.0, **cfg_extra):
    """One ChainBacktest run; cfg_extra are ChainConfig fields (e.g. exit_arms, pcs_put_sd)."""
    arch = NseFoArchive(archive_dir=str(root))
    # legacy settlement + legacy fees: these hand-computed arm cases pin the pre-fix model
    cfg_extra = {"cash_settlement": False, "legacy_costs": True, **cfg_extra}
    cfg = ChainConfig(slippage_multiplier=mult, start=S, end=S, **cfg_extra)
    bt = ChainBacktest(arch, market, cfg)
    return bt, bt.run()


def _arms(**kw):
    from strategies.weekly_strategies import WeeklyExitArms
    return WeeklyExitArms(**kw)


def _pcs_strikes(put_sd=None):
    strat = WeeklyPutCreditSpread(lots=1, lot_size=65)
    if put_sd is not None:
        strat.put_sd = put_sd
    legs = strat.generate_legs(SPOT, VIX_PCS, 6, 0.065)
    sp = next(l.strike for l in legs if l.is_short)
    lp = next(l.strike for l in legs if not l.is_short)
    return sp, lp


def _pcs_world(root, sp, lp, d6=(40.0, 15.0), exit_px=(10.0, 4.0), spot_map=None):
    """PCS cycle: signal S, fill F at (40, 15), marks D6/D7 at (fills unless d6), exit X (DTE 1)."""
    _write(root, S, [_row(S, S, 23000, "PE", 1.0)])
    _write(root, F, [_row(F, E, sp, "PE", 40.0), _row(F, E, lp, "PE", 15.0)])
    _write(root, D6, [_row(D6, E, sp, "PE", d6[0]), _row(D6, E, lp, "PE", d6[1])])
    _write(root, D7, [_row(D7, E, sp, "PE", 40.0), _row(D7, E, lp, "PE", 15.0)])
    _write(root, X, [_row(X, E, sp, "PE", exit_px[0]), _row(X, E, lp, "PE", exit_px[1])])
    days = [S, F, D6, D7, X]
    return days, _market(days, VIX_PCS, spot_map)


def _ic_world(root, d6_marks=(30.0, 10.0, 25.0, 8.0), spot_map=None):
    """Standard IC cycle from test_chain_engine (fills 30/10/25/8, exit at X), with D6 marks overridable."""
    days = _write_ic_world(root)                       # S, F, D6, D7, X
    strikes = [(23350, "CE"), (23600, "CE"), (22450, "PE"), (22200, "PE")]
    _write(root, D6, [_row(D6, E, k, o, v) for (k, o), v in zip(strikes, d6_marks)])
    return days, _market(days, VIX_IC, spot_map), None


def _expiry_rows(root, strikes_opts, index_settle=23000.0):
    """Expiry-day rows: settle holds the index settlement (2020+ archive convention)."""
    _write(root, E, [_row(E, E, k, o, index_settle, close=0.0) for k, o in strikes_opts])


def _snapshot_trade(t):
    return {
        "strategy": t["strategy"], "fill_date": t["fill_date"], "expiry": t["expiry"],
        "exit_date": t["exit_date"], "exit_reason": t["exit_reason"],
        "pnl": round(t["pnl"], 4), "entry_credit_fill": round(t["entry_credit_fill"], 4),
        "legs": [[l["type"], l["strike"], l["short"], round(l["entry_fill"], 4), round(l["exit_fill"], 4)]
                 for l in t["legs"]],
    }


# ----------------------------------------------------------------- baseline snapshot (fixture)
def _baseline_snapshot(tmp_root: Path) -> dict:
    """Trade lists of the default configuration on the synthetic scenarios (used to make the fixture)."""
    out = {}
    root = tmp_root / "ic"
    days = _write_ic_archive(root)
    out["ic_world"] = [_snapshot_trade(t) for t in _run(root, days, _market(days, VIX_IC), 1.0)[1]]
    root = tmp_root / "pcs"
    sp, lp = _pcs_strikes()
    days, mk = _pcs_world(root, sp, lp)
    out["pcs_world"] = [_snapshot_trade(t) for t in _run(root, days, mk, 1.0)[1]]
    root = tmp_root / "pcs_breach"
    days, mk = _pcs_world(root, sp, lp, spot_map={D6: 22400.0})
    out["pcs_breach_world"] = [_snapshot_trade(t) for t in _run(root, days, mk, 1.0)[1]]
    root = tmp_root / "ic_breach"
    days, mk, _ = _ic_world(root, spot_map={D6: 23400.0, D7: 23400.0})
    out["ic_call_breach_world"] = [_snapshot_trade(t) for t in _run(root, days, mk, 1.0)[1]]
    root = tmp_root / "ic_blow"
    days, mk, _ = _ic_world(root, d6_marks=(80.0, 10.0, 25.0, 8.0))
    out["ic_credit_blowup_world"] = [_snapshot_trade(t) for t in _run(root, days, mk, 1.0)[1]]
    return out


@pytest.fixture(scope="module")
def baseline_fixture():
    return json.load(open(FIXTURE))


def _assert_same_trades(got, want):
    assert len(got) == len(want), (got, want)
    for g, w in zip(got, want):
        for k in ("strategy", "fill_date", "expiry", "exit_date", "exit_reason", "legs"):
            assert g[k] == w[k], (k, g, w)
        assert g["pnl"] == pytest.approx(w["pnl"], abs=1e-3)
        assert g["entry_credit_fill"] == pytest.approx(w["entry_credit_fill"], abs=1e-4)


# ----------------------------------------------------------------- defaults == baseline
def test_defaults_reproduce_baseline_trades_on_synthetic_worlds(tmp_path, baseline_fixture):
    """Default ChainConfig (no arms) matches the pre-arm baseline trade lists exactly."""
    got = _baseline_snapshot(tmp_path)
    assert set(got) == set(baseline_fixture)
    for name in got:
        _assert_same_trades(got[name], baseline_fixture[name])


def test_defaults_match_explicit_default_arms(tmp_path):
    from strategies.weekly_strategies import WeeklyExitArms
    days, mk, _ = _ic_world(tmp_path / "a")
    _, t_default = _run(tmp_path / "a", days, mk, 1.0)
    _, t_explicit = _run(tmp_path / "a", days, mk, 1.0, pcs_put_sd=0.9, exit_arms=WeeklyExitArms())
    assert [_snapshot_trade(t) for t in t_default] == [_snapshot_trade(t) for t in t_explicit]


def test_cli_defaults_reproduce_baseline_on_test_run_chain_backtest_archive(tmp_path, monkeypatch, baseline_fixture):
    """The literal synthetic archive of tests/test_run_chain_backtest.py through the CLI (defaults)."""
    arch_dir = tmp_path / "archive"
    days = _write_ic_archive(arch_dir)
    monkeypatch.setattr(cli, "load_market", lambda end, market_start=None: _synthetic_market(days))
    out = tmp_path / "out"
    assert cli.main(["--start", str(S), "--end", str(X), "--slippage", "1.0", "--archive-dir", str(arch_dir),
                     "--out", str(out), "--legacy-settlement", "--legacy-costs", "--allow-holdout"]) == 0
    got = [_snapshot_trade(t) for t in json.load(open(out / "trades_x1.json"))["trades"]]
    _assert_same_trades(got, baseline_fixture["ic_world"])
    summ = json.load(open(out / "summary.json"))["arms"]
    assert summ == {"pcs_put_sd": 0.9, "breach_stop": True, "ic_hold_to_expiry": False, "hold_to_expiry": False}


def test_cli_arm_flags_are_recorded_and_do_not_touch_ic_world(tmp_path, monkeypatch, baseline_fixture):
    """A and B flags on the IC-only synthetic archive: IC legs are unchanged and there is no breach."""
    arch_dir = tmp_path / "archive"
    days = _write_ic_archive(arch_dir)
    monkeypatch.setattr(cli, "load_market", lambda end, market_start=None: _synthetic_market(days))
    out = tmp_path / "out"
    assert cli.main(["--start", str(S), "--end", str(X), "--slippage", "1.0", "--archive-dir", str(arch_dir),
                     "--out", str(out), "--pcs-put-sd", "1.2", "--no-breach-stop",
                     "--legacy-settlement", "--legacy-costs", "--allow-holdout"]) == 0
    got = [_snapshot_trade(t) for t in json.load(open(out / "trades_x1.json"))["trades"]]
    _assert_same_trades(got, baseline_fixture["ic_world"])
    summ = json.load(open(out / "summary.json"))["arms"]
    assert summ == {"pcs_put_sd": 1.2, "breach_stop": False, "ic_hold_to_expiry": False, "hold_to_expiry": False}
    assert json.load(open(out / "diag_x1.json"))["arms"]["pcs_put_sd"] == 1.2


# ----------------------------------------------------------------- arm A: PCS at 1.2 SD
def test_arm_a_strike_distance_in_sd_units():
    """1 SD = spot * (VIX/100/sqrt(252)) * sqrt(DTE_calendar), the strategy's own period_vol.

    VIX 11, DTE 6, spot 23000: period_vol = 0.11/sqrt(252)*sqrt(6) = 0.016974; 1 SD = 390.4 pts.
    Baseline 0.9 SD -> 351.4 pts -> 22648.6 -> snapped to 22650. Arm A 1.2 SD -> 468.5 pts
    -> 22531.5 -> snapped to 22550; the 200-pt width gives the long put at 22350.
    """
    one_sd = SPOT * (VIX_PCS / 100 / math.sqrt(252)) * math.sqrt(6)
    assert one_sd == pytest.approx(390.4, abs=0.1)
    assert _pcs_strikes() == (22650, 22450)
    assert _pcs_strikes(put_sd=1.2) == (22550, 22350)


def test_arm_a_chain_backtest_wires_put_sd(tmp_path):
    days = _write_ic_archive(tmp_path)
    arch = NseFoArchive(archive_dir=str(tmp_path))
    mk = _market(days, VIX_IC)
    base = ChainBacktest(arch, mk, ChainConfig(start=S, end=S))
    arm = ChainBacktest(arch, mk, ChainConfig(start=S, end=S, pcs_put_sd=1.2))
    assert base.strategies["weekly_pcs"].put_sd == 0.9
    assert arm.strategies["weekly_pcs"].put_sd == 1.2
    ic = lambda bt: [(l.option_type, l.strike, l.is_short) for l in
                     bt.strategies["weekly_ic"].generate_legs(SPOT, VIX_IC, 6, 0.065)]
    assert ic(arm) == ic(base)
    assert [(l.strike, l.is_short) for l in arm.strategies["weekly_pcs"].generate_legs(SPOT, VIX_PCS, 6, 0.065)] \
        == [(22550, True), (22350, False)]


def test_arm_a_round_trip_hand_computed(tmp_path):
    """Same fills/marks/exit as the baseline PCS round trip, strikes 22550/22350 under arm A.
    Net credit 24.10 and exit prices are unchanged, so P&L equals the baseline 1022.54."""
    sp, lp = _pcs_strikes(put_sd=1.2)
    days, mk = _pcs_world(tmp_path, sp, lp)
    bt, trades = _run(tmp_path, days, mk, 1.0, pcs_put_sd=1.2)
    assert len(trades) == 1, (trades, bt.skip_log)
    t = trades[0]
    assert (t["legs"][0]["strike"], t["legs"][1]["strike"]) == (22550, 22350)
    assert t["exit_reason"] == "dte_limit" and t["exit_date"] == str(X)
    credit = 39.55 - 15.45
    gross = (39.55 - 10.45) * 65 - (15.45 - 3.55) * 65
    assert t["pnl"] == pytest.approx(gross - _expected_fees(credit, 2), abs=0.01)
    assert t["pnl"] == pytest.approx(1022.54, abs=0.01)


# ----------------------------------------------------------------- arm B: no breach stop
def test_arm_b_pcs_breach_day_baseline_stops_arm_b_holds(tmp_path):
    """Spot closes 22400 on D6, below the 22650 short put (baseline breach stop fires on D6).
    Marks on D6 equal the fills, so no credit-multiple stop: arm B holds to the DTE-1 exit."""
    sp, lp = _pcs_strikes()
    days, mk = _pcs_world(tmp_path, sp, lp, spot_map={D6: 22400.0})
    _, base = _run(tmp_path, days, mk, 1.0)
    assert len(base) == 1
    assert base[0]["exit_date"] == str(D6) and base[0]["exit_reason"] == "stop_loss"
    # D6 marks 40/15: short 39.55 -> 40.45 (-58.5), long 15.45 -> 14.55 (-58.5), fees on 24.10 credit
    assert base[0]["pnl"] == pytest.approx(-117.0 - _expected_fees(24.10, 2), abs=0.01)

    days, mk = _pcs_world(tmp_path, sp, lp, spot_map={D6: 22400.0})
    _, armb = _run(tmp_path, days, mk, 1.0, exit_arms=_arms(breach_stop=False))
    assert len(armb) == 1
    assert armb[0]["exit_date"] == str(X) and armb[0]["exit_reason"] == "dte_limit"
    assert armb[0]["pnl"] == pytest.approx(1022.54, abs=0.01)


def test_arm_b_keeps_credit_multiple_stop(tmp_path):
    """D6 marks 80 / 5 with spot 22400: loss 51.8 per unit = 215% of credit. Arm B still stops on D6."""
    sp, lp = _pcs_strikes()
    days, mk = _pcs_world(tmp_path, sp, lp, d6=(80.0, 5.0), spot_map={D6: 22400.0})
    _, trades = _run(tmp_path, days, mk, 1.0, exit_arms=_arms(breach_stop=False))
    assert len(trades) == 1
    t = trades[0]
    assert t["exit_date"] == str(D6) and t["exit_reason"] == "stop_loss"
    # short 39.55 -> 80.45 = -40.9 ; long 15.45 -> 4.55 = -10.9 ; gross (-40.9 - 10.9) * 65
    assert t["pnl"] == pytest.approx((-40.9 - 10.9) * 65 - _expected_fees(24.10, 2), abs=0.01)


def test_arm_b_policy_and_strategy_level_pcs_and_ic(tmp_path):
    from backtester.weekly_exit_policy import build_tracker, check_weekly_exit
    cfg = WeeklyBacktestConfig()
    pcs = _pcs_trade(spot_entry=23000.0)
    ic = _ic_trade(marks=(30.0, 10.0, 25.0, 8.0))
    kw = dict(config=cfg, current_equity=500_000.0, entry_vix=15.0, vix=15.0, holding_days=1)
    # PCS below short strike 22650 with marks at fills (no credit stop)
    assert check_weekly_exit(trade=pcs, tracker=build_tracker(pcs), spot=22600.0, dte=5, **kw) == (True, _stop())
    assert check_weekly_exit(trade=pcs, tracker=build_tracker(pcs), spot=22600.0, dte=5,
                             arms=_arms(breach_stop=False), **kw) == (False, None)
    assert WeeklyPutCreditSpread(lots=1).should_exit(pcs, 22600.0, 15.0, 5)[1] == _stop()
    assert WeeklyPutCreditSpread(lots=1).should_exit(pcs, 22600.0, 15.0, 5, arms=_arms(breach_stop=False))[0] \
        == TradeAction.HOLD
    # IC call breach (spot 23400 > short call 23350), marks at fills
    assert check_weekly_exit(trade=ic, tracker=build_tracker(ic), spot=23400.0, dte=5, **kw) == (True, _stop())
    assert check_weekly_exit(trade=ic, tracker=build_tracker(ic), spot=23400.0, dte=5,
                             arms=_arms(breach_stop=False), **kw) == (False, None)
    assert WeeklyIronCondor(lots=1).should_exit(ic, 23400.0, 15.0, 5)[1] == _stop()
    assert WeeklyIronCondor(lots=1).should_exit(ic, 23400.0, 15.0, 5, arms=_arms(breach_stop=False))[0] \
        == TradeAction.HOLD


# ----------------------------------------------------------------- arm C: IC held to expiry
def test_arm_c_ic_held_to_expiry_hand_computed(tmp_path):
    """Standard IC world; no expiry-day rows exist for the baseline. Under arm C the IC is not
    closed at DTE 1 (X) and is closed on expiry day E at the index settle 23000 (all four legs
    OTM -> intrinsic 0, marked at the 0.05 tick floor).

    Entry fills 29.55 / 10.45 / 24.55 / 8.45 (credit 35.20). Exit: short legs buy at 0.05 + 0.45
    slippage = 0.50; long legs sell at max(0.05 - 0.45, 0.05) = 0.05.
    gross = (29.55-0.50)*65 + (0.05-10.45)*65 + (24.55-0.50)*65 + (0.05-8.45)*65 = 2229.5
    """
    days = _write_ic_world(tmp_path)
    _expiry_rows(tmp_path, [(23350, "CE"), (23600, "CE"), (22450, "PE"), (22200, "PE")])
    days = days + [E]
    base_bt, base = _run(tmp_path, days[:-1], _market(days[:-1], VIX_IC), 1.0)
    assert base[0]["exit_reason"] == "dte_limit" and base[0]["exit_date"] == str(X)
    bt, trades = _run(tmp_path, days, _market(days, VIX_IC), 1.0, exit_arms=_arms(ic_hold_to_expiry=True))
    assert len(trades) == 1, (trades, bt.skip_log, dict(bt.diag))
    t = trades[0]
    assert t["exit_date"] == str(E) and t["exit_reason"] == "expiry"
    assert t["pnl"] == pytest.approx(2229.5 - _expected_fees(35.20, 4), abs=0.01)


def test_arm_c_policy_and_strategy_level_ic(tmp_path):
    from backtester.weekly_exit_policy import build_tracker, check_weekly_exit
    cfg = WeeklyBacktestConfig()
    ic = _ic_trade(marks=(30.0, 10.0, 25.0, 8.0))
    c = _arms(ic_hold_to_expiry=True)
    kw = dict(config=cfg, current_equity=500_000.0, entry_vix=15.0, vix=15.0, holding_days=1)
    # short-strike breach (spot 23400 > 23350): baseline stop, arm C holds
    assert check_weekly_exit(trade=ic, tracker=build_tracker(ic), spot=23400.0, dte=3, **kw)[0] is True
    assert check_weekly_exit(trade=ic, tracker=build_tracker(ic), spot=23400.0, dte=3, arms=c, **kw) == (False, None)
    # DTE-1 exit (baseline DTE_LIMIT): arm C holds, expiry is handled by the chain engine
    assert check_weekly_exit(trade=ic, tracker=build_tracker(ic), spot=23000.0, dte=1, **kw) \
        == (True, _dte())
    assert check_weekly_exit(trade=ic, tracker=build_tracker(ic), spot=23000.0, dte=1, arms=c, **kw) == (False, None)
    assert check_weekly_exit(trade=ic, tracker=build_tracker(ic), spot=23000.0, dte=0, arms=c, **kw) == (False, None)
    # strategy-level: every IC early exit (DTE, width, breach) is disabled
    assert WeeklyIronCondor(lots=1).should_exit(ic, 23400.0, 15.0, 3)[0] == TradeAction.EXIT
    assert WeeklyIronCondor(lots=1).should_exit(ic, 23400.0, 15.0, 3, arms=c)[0] == TradeAction.HOLD
    assert WeeklyIronCondor(lots=1).should_exit(ic, 23000.0, 15.0, 1, arms=c)[0] == TradeAction.HOLD


def test_arm_c_keeps_credit_multiple_stop_for_ic(tmp_path):
    """D6 marks: short call 80 (loss 50.9 on that leg). Total 51.8 per unit = 147% of 35.20 credit."""
    from backtester.weekly_exit_policy import build_tracker, check_weekly_exit
    ic = _ic_trade(marks=(80.0, 10.0, 25.0, 8.0))
    got = check_weekly_exit(config=WeeklyBacktestConfig(), trade=ic, tracker=build_tracker(ic), spot=23000.0,
                            dte=3, current_equity=500_000.0, entry_vix=15.0, vix=15.0, holding_days=1,
                            arms=_arms(ic_hold_to_expiry=True))
    assert got == (True, _stop())
    days, mk, _ = _ic_world(tmp_path, d6_marks=(80.0, 10.0, 25.0, 8.0))
    _, trades = _run(tmp_path, days, mk, 1.0, exit_arms=_arms(ic_hold_to_expiry=True))
    assert len(trades) == 1 and trades[0]["exit_date"] == str(D6) and trades[0]["exit_reason"] == "stop_loss"


def test_arm_c_does_not_change_pcs(tmp_path):
    """PCS keeps every baseline exit under arm C: breach stop on D6 and the DTE-1 exit."""
    sp, lp = _pcs_strikes()
    days, mk = _pcs_world(tmp_path, sp, lp, spot_map={D6: 22400.0})
    _, base = _run(tmp_path, days, mk, 1.0)
    days, mk = _pcs_world(tmp_path, sp, lp, spot_map={D6: 22400.0})
    _, armc = _run(tmp_path, days, mk, 1.0, exit_arms=_arms(ic_hold_to_expiry=True))
    assert [_snapshot_trade(t) for t in armc] == [_snapshot_trade(t) for t in base]
    assert base[0]["exit_reason"] == "stop_loss" and base[0]["exit_date"] == str(D6)


# ----------------------------------------------------------------- trade builders for unit checks
def _stop():
    from strategies.base import ExitReason
    return ExitReason.STOP_LOSS


def _dte():
    from strategies.base import ExitReason
    return ExitReason.DTE_LIMIT


def _pcs_trade(spot_entry=23000.0):
    """PCS 22650/22450, entry fills 39.55 / 15.45, marks at fills (no P&L)."""
    legs = [Leg("PE", 22650, True, 39.55, 39.55, 1, 65), Leg("PE", 22450, False, 15.45, 15.45, 1, 65)]
    return Trade(strategy_name="weekly_pcs", entry_date=F, legs=legs, entry_spot=spot_entry,
                 entry_vix=VIX_PCS, lots=1, lot_size=65)


def _ic_trade(marks=(30.0, 10.0, 25.0, 8.0)):
    """IC 23350/23600 CE and 22450/22200 PE; entry fills 29.55 / 10.45 / 24.55 / 8.45 (credit 35.20)."""
    fills = [29.55, 10.45, 24.55, 8.45]
    spec = [("CE", 23350, True), ("CE", 23600, False), ("PE", 22450, True), ("PE", 22200, False)]
    legs = [Leg(o, k, s, f, m, 1, 65) for (o, k, s), f, m in zip(spec, fills, marks)]
    return Trade(strategy_name="weekly_ic", entry_date=F, legs=legs, entry_spot=23000.0,
                 entry_vix=VIX_IC, lots=1, lot_size=65)


# ----------------------------------------------------------------- T0: capital-protection scaling
def _loss_trade(lots, loss_per_unit, credit=400.0):
    """PCS 22650/22450 with net credit `credit`, short-leg mark up by `loss_per_unit` (long at entry).
    Spot 23000 is inside the short strike and the credit-multiple stop is not reached when loss < credit."""
    short = Leg("PE", 22650, True, credit + 100.0, credit + 100.0 + loss_per_unit, lots, 65)
    long_ = Leg("PE", 22450, False, 100.0, 100.0, lots, 65)
    return Trade(strategy_name="weekly_pcs", entry_date=F, legs=[short, long_], entry_spot=23000.0,
                 entry_vix=VIX_PCS, lots=lots, lot_size=65)


def test_capital_base_defaults_to_per_lot_scaling(tmp_path):
    days = _write_ic_archive(tmp_path)
    arch = NseFoArchive(archive_dir=str(tmp_path))
    mk = _market(days, VIX_IC)
    base = lambda **kw: ChainBacktest(arch, mk, ChainConfig(start=S, end=S, **kw))._capital_base()
    assert ChainConfig().capital_protection_per_lot is True
    assert base() == 500_000.0                                     # lots=1: unchanged
    assert base(lots=10) == 5_000_000.0                            # 500k per lot-unit of sizing
    assert base(lots=10, capital_protection_per_lot=False) == 500_000.0   # legacy fixed base
    for lots in (1, 10, 30):
        assert 0.04 * base(lots=lots) / lots == pytest.approx(20_000.0)   # Rs20,000 per lot at any lot count


@pytest.mark.parametrize("lots, loss_per_unit, scaled_fires, fixed_fires", [
    (1, 77.0, False, False),     # total -5,005: below Rs20,000 under both bases
    (1, 385.0, True, True),      # total -25,025: above Rs20,000 under both bases
    (10, 154.0, False, True),    # total -100,100: fixed Rs20,000 binds, per-lot Rs200,000 does not
    (10, 400.0, True, True),     # total -260,000 (per lot 26,000): binds under both bases
])
def test_capital_protection_threshold_scaling(lots, loss_per_unit, scaled_fires, fixed_fires):
    trade = _loss_trade(lots, loss_per_unit)
    kw = dict(config=WeeklyBacktestConfig(), tracker=None, spot=23000.0, vix=VIX_PCS, dte=5,
              entry_vix=VIX_PCS, holding_days=1)
    from backtester.weekly_exit_policy import build_tracker
    kw["tracker"] = build_tracker(trade)
    got_scaled = check_weekly_exit(trade=trade, current_equity=500_000.0 * lots, **kw)
    got_fixed = check_weekly_exit(trade=trade, current_equity=500_000.0, **kw)
    assert (got_scaled[0] is True) == scaled_fires
    assert (got_fixed[0] is True) == fixed_fires
    if scaled_fires:
        assert got_scaled == (True, _stop())


def test_capital_protection_scaling_at_chain_level_matches_lots1(tmp_path):
    """With per-lot scaling a 10-lot run has the same exit reasons and gross P&L per lot as a 1-lot run."""
    sp, lp = _pcs_strikes()
    days, mk = _pcs_world(tmp_path, sp, lp, d6=(80.0, 5.0), spot_map={D6: 22400.0})
    _, one = _run(tmp_path, days, mk, 1.0, lots=1)
    days, mk = _pcs_world(tmp_path, sp, lp, d6=(80.0, 5.0), spot_map={D6: 22400.0})
    _, ten = _run(tmp_path, days, mk, 1.0, lots=10)
    assert [t["exit_reason"] for t in one] == [t["exit_reason"] for t in ten]
    # gross P&L is linear in lots; only the flat per-order brokerage differs per lot (not tested here)
    assert one[0]["gross_fill_rs"] == pytest.approx(ten[0]["gross_fill_rs"] / 10, abs=1e-6)
    assert ten[0]["lots"] == 10 and one[0]["lots"] == 1


def test_lots1_legacy_capital_mode_is_identical(tmp_path):
    """At lots=1 the fixed and per-lot capital bases are the same number, so trades are identical."""
    days, mk, _ = _ic_world(tmp_path / "ic", d6_marks=(80.0, 10.0, 25.0, 8.0))
    _, a = _run(tmp_path / "ic", days, mk, 1.0)
    _, b = _run(tmp_path / "ic", days, mk, 1.0, capital_protection_per_lot=False)
    assert [_snapshot_trade(t) for t in a] == [_snapshot_trade(t) for t in b]


# ----------------------------------------------------------------- F1: hold to expiry
def test_f1_policy_and_strategy_disable_every_exit():
    from backtester.weekly_exit_policy import build_tracker
    cfg = WeeklyBacktestConfig()
    f1 = _arms(hold_to_expiry=True)
    pcs = _pcs_trade(spot_entry=23000.0)
    ic = _ic_trade(marks=(80.0, 10.0, 25.0, 8.0))          # credit-multiple stop would fire
    big = _loss_trade(10, 2000.0)                           # capital stop would fire at any base
    cases = [
        (pcs, 22600.0, 5), (pcs, 22600.0, 1),              # breach, and DTE-1 exit
        (ic, 23400.0, 3), (ic, 23000.0, 1),                 # breach / DTE exit, credit stop marks
        (big, 23000.0, 5),                                  # capital protection
    ]
    for trade, spot, dte in cases:
        kw = dict(config=cfg, trade=trade, tracker=build_tracker(trade), spot=spot, vix=15.0, dte=dte,
                  entry_vix=15.0, current_equity=500_000.0 * trade.lots, holding_days=1)
        assert check_weekly_exit(arms=f1, **kw) == (False, None)
    assert check_weekly_exit(config=cfg, trade=ic, tracker=build_tracker(ic), spot=23000.0, dte=3,
                             current_equity=500_000.0, entry_vix=15.0, vix=15.0, holding_days=1)[0] is True
    assert WeeklyPutCreditSpread(lots=1).should_exit(pcs, 22600.0, 15.0, 1, arms=f1)[0] == TradeAction.HOLD
    assert WeeklyPutCreditSpread(lots=1).should_exit(pcs, 22600.0, 15.0, 5, arms=f1)[0] == TradeAction.HOLD
    assert WeeklyIronCondor(lots=1).should_exit(ic, 23400.0, 15.0, 3, arms=f1)[0] == TradeAction.HOLD
    assert WeeklyIronCondor(lots=1).should_exit(ic, 23000.0, 15.0, 1, arms=f1)[0] == TradeAction.HOLD


def test_f1_pcs_credit_stop_holds_to_expiry_settle(tmp_path):
    """Baseline stops on D6 (marks 80/5 on a 24.10 credit). F1 holds, and the trade closes at the
    expiry settle E at intrinsic (both legs OTM -> 0.05 floor). Loss is capped by the 200-pt width."""
    sp, lp = _pcs_strikes()
    spot = {D6: 22400.0}
    days, mk = _pcs_world(tmp_path, sp, lp, d6=(80.0, 5.0), spot_map=spot)
    _, base = _run(tmp_path, days, mk, 1.0)
    assert base[0]["exit_reason"] == "stop_loss" and base[0]["exit_date"] == str(D6)
    _expiry_rows(tmp_path, [(sp, "PE"), (lp, "PE")])
    days, mk = _pcs_world(tmp_path, sp, lp, d6=(80.0, 5.0), spot_map=spot)
    days = days + [E]
    mk = _market(days, VIX_PCS, spot)
    bt, f1 = _run(tmp_path, days, mk, 1.0, exit_arms=_arms(hold_to_expiry=True))
    assert len(f1) == 1, (f1, bt.skip_log)
    t = f1[0]
    assert t["exit_reason"] == "expiry" and t["exit_date"] == str(E)
    assert all(l["exit_settle"] == pytest.approx(0.05) for l in t["legs"])
    fees = _expected_fees(t["entry_credit_fill"], 2)
    assert t["pnl"] == pytest.approx((39.55 - t["legs"][0]["exit_fill"]) * 65
                                     + (t["legs"][1]["exit_fill"] - 15.45) * 65 - fees, abs=0.01)
    assert t["pnl"] >= -(200 - t["entry_credit_fill"]) * 65 - fees - 0.01


def test_f1_ic_breach_and_credit_stop_hold_to_expiry(tmp_path):
    """IC breached on D6 (spot 23400 > short call 23350) with a credit blow-up. F1 holds to E."""
    spot = {D6: 23400.0, D7: 23400.0}
    days, mk, _ = _ic_world(tmp_path, d6_marks=(80.0, 10.0, 25.0, 8.0), spot_map=spot)
    _, base = _run(tmp_path, days, mk, 1.0)
    assert base[0]["exit_reason"] == "stop_loss" and base[0]["exit_date"] == str(D6)
    _expiry_rows(tmp_path, [(23350, "CE"), (23600, "CE"), (22450, "PE"), (22200, "PE")])
    days, mk, _ = _ic_world(tmp_path, d6_marks=(80.0, 10.0, 25.0, 8.0), spot_map=spot)
    days = days + [E]
    mk = _market(days, VIX_IC, spot)
    bt, f1 = _run(tmp_path, days, mk, 1.0, exit_arms=_arms(hold_to_expiry=True))
    assert len(f1) == 1, (f1, bt.skip_log)
    t = f1[0]
    assert t["exit_reason"] == "expiry" and t["exit_date"] == str(E)
    # one side can finish in the money, so the max loss is the 250-pt wing less the credit
    assert t["pnl"] >= -(250 - t["entry_credit_fill"]) * 65 - _expected_fees(t["entry_credit_fill"], 4) - 0.01


# ----------------------------------------------------------------- F2: VIX floor
def test_f2_min_vix_floor_skips_low_vix_signal(tmp_path):
    sp, lp = _pcs_strikes()
    days, mk = _pcs_world(tmp_path, sp, lp)                 # signal VIX 11
    _, base = _run(tmp_path, days, mk, 1.0)
    assert len(base) == 1
    days, mk = _pcs_world(tmp_path, sp, lp)
    bt, gated = _run(tmp_path, days, mk, 1.0, min_vix_floor=13.0)
    assert gated == []
    assert bt.skips["vix_floor"] == 1
    assert bt.skip_log[0]["reason"] == "vix_floor" and bt.skip_log[0]["vix"] == pytest.approx(11.0)


def test_f2_floor_is_strict_and_inactive_at_or_above(tmp_path):
    """Floor is 'skip when VIX < floor': VIX equal to the floor and above it trade exactly as baseline."""
    days = _write_ic_world(tmp_path)                        # signal VIX 15
    mk = _market(days, VIX_IC)
    _, base = _run(tmp_path, days, mk, 1.0)
    assert len(base) == 1
    for floor in (13.0, 15.0, None):
        bt, got = _run(tmp_path, days, mk, 1.0, min_vix_floor=floor)
        assert [_snapshot_trade(t) for t in got] == [_snapshot_trade(t) for t in base], floor
        assert bt.skips["vix_floor"] == 0
    bt, got = _run(tmp_path, days, mk, 1.0, min_vix_floor=15.01)
    assert got == [] and bt.skips["vix_floor"] == 1


# ----------------------------------------------------------------- CLI flags
def test_cli_new_flags_are_recorded_and_gate_entries(tmp_path, monkeypatch):
    arch_dir = tmp_path / "archive"
    days = _write_ic_archive(arch_dir)
    monkeypatch.setattr(cli, "load_market", lambda end, market_start=None: _synthetic_market(days))
    out = tmp_path / "out_f1"
    assert cli.main(["--start", str(S), "--end", str(X), "--slippage", "1.0", "--archive-dir", str(arch_dir),
                     "--out", str(out), "--no-early-exits", "--allow-holdout"]) == 0
    assert json.load(open(out / "summary.json"))["arms"]["hold_to_expiry"] is True
    out = tmp_path / "out_f2"
    assert cli.main(["--start", str(S), "--end", str(X), "--slippage", "1.0", "--archive-dir", str(arch_dir),
                     "--out", str(out), "--min-vix", "20", "--allow-holdout"]) == 0
    assert json.load(open(out / "trades_x1.json"))["n"] == 0
    assert json.load(open(out / "diag_x1.json"))["skips"]["vix_floor"] >= 1
    assert json.load(open(out / "summary.json"))["cfg"] == {
        "min_vix_floor": 20.0, "capital_protection_per_lot": True,
        "cash_settlement": True, "legacy_costs": False}
