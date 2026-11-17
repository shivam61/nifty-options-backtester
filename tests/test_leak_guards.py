"""Leak guards: walk-forward selection (TRAIN chooses, TEST reports), the holdout guard and its ledger,
and chain-engine timing (signal on day D, fill at the next session's settle, entry gate on D's data).

Synthetic data only: no archive, no network. Chain tests reuse the synthetic-archive helpers of
tests/test_chain_engine.py.
"""

from datetime import date, timedelta

import json

import numpy as np
import pandas as pd
import pytest

from strategy_eval import holdout_ledger, stats
from strategy_eval.holdout_ledger import read_ledger
from strategy_eval.stats import TestRegistry
from strategy_eval.verdict import DEV_END
from strategy_eval.walkforward import (
    HOLDOUT_FROM, TEST_END, TEST_START, TRAIN_END, TRAIN_START, HoldoutAccessError, walk_forward_select,
)
from tests.test_chain_engine import (
    E, F, S, _market, _row, _run, _write, _write_ic_world,
)
from tests.test_strategy_eval import _frame


@pytest.fixture(autouse=True)
def _isolated_registry_and_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(stats, "DEFAULT_REGISTRY_PATH", tmp_path / "eval_registry.json")
    monkeypatch.setattr(holdout_ledger, "DEFAULT_LEDGER_PATH", tmp_path / "holdout_ledger.json")


# ----------------------------------------------------------------------------- walk-forward fixtures

# Weekly entries from 2019-02-18 to the end of the development window (exit = entry + 6 days).
WEEKLY = pd.date_range("2019-02-18", str(DEV_END), freq="7D")
TR_MASK = np.asarray((WEEKLY >= pd.Timestamp(TRAIN_START)) & (WEEKLY <= pd.Timestamp(TRAIN_END)))
TE_MASK = np.asarray((WEEKLY >= pd.Timestamp(TEST_START)) & (WEEKLY <= pd.Timestamp(TEST_END)))


def _cand(train_mean, train_seed, test_mean, test_seed, sd=1000.0, strategy="cand"):
    """Weekly trade table. TRAIN draws come only from train_seed/train_mean, TEST only from the test pair,
    so changing one window's arguments leaves the other window's trades bit-identical."""
    pnl = np.zeros(len(WEEKLY))
    pnl[TR_MASK] = np.random.default_rng(train_seed).normal(train_mean, sd, TR_MASK.sum())
    pnl[TE_MASK] = np.random.default_rng(test_seed).normal(test_mean, sd, TE_MASK.sum())
    return _frame(pnl, start=WEEKLY[0].date(), entry_offset_days=[(d - WEEKLY[0]).days for d in WEEKLY],
                  strategy=strategy)


def _window_expectancy(df, start, end):
    e = pd.to_datetime(df["entry_date"])
    m = (e >= pd.Timestamp(start)) & (e <= pd.Timestamp(end))
    return float(df.loc[m, "pnl_net_rs"].mean())


def _cands(good_train=300.0, good_test=-300.0, trap_train=-300.0, trap_test=600.0):
    return {
        "good": _cand(good_train, 1, good_test, 2, strategy="good"),
        "trap": _cand(trap_train, 3, trap_test, 4, strategy="trap"),
        "flat": _cand(0.0, 5, 0.0, 6, strategy="flat"),
    }


# ----------------------------------------------------------------------------- (a) walk-forward

def test_windows_are_the_documented_constants():
    assert str(TRAIN_START) == "2019-02-11" and str(TRAIN_END) == "2021-12-31"
    assert str(TEST_START) == "2022-01-01" and TEST_END == DEV_END == date(2023, 12, 31)
    assert HOLDOUT_FROM == date(2024, 1, 1)


def test_candidate_profitable_only_on_test_is_not_selected():
    cands = _cands()
    # The trap really is the better TEST performer, so a selector that peeked at TEST would pick it.
    assert _window_expectancy(cands["trap"], TEST_START, TEST_END) > _window_expectancy(cands["good"], TEST_START, TEST_END)
    res = walk_forward_select(cands, registry=TestRegistry())
    assert res["selected"] == "good"
    assert set(res["test_table"]["name"]) == {"good"}          # only the selected candidate is reported on TEST
    assert set(res["train_table"]["name"]) == {"good", "trap", "flat"}
    assert res["n_candidates"] == 3


def test_changing_test_data_never_changes_selection_or_train_table():
    base = walk_forward_select(_cands(), registry=TestRegistry())
    # Same TRAIN draws, very different TEST draws for every candidate.
    alt = {
        "good": _cand(300.0, 1, 5000.0, 99, strategy="good"),
        "trap": _cand(-300.0, 3, -4000.0, 98, strategy="trap"),
        "flat": _cand(0.0, 5, 700.0, 97, strategy="flat"),
    }
    res = walk_forward_select(alt, registry=TestRegistry())
    assert res["selected"] == base["selected"] == "good"
    pd.testing.assert_frame_equal(res["train_table"], base["train_table"])
    assert res["deflated_sharpe_ratio"] == base["deflated_sharpe_ratio"]
    # Non-vacuous: the TEST table did change.
    assert res["test_table"].loc[0, "expectancy_per_lot"] != pytest.approx(base["test_table"].loc[0, "expectancy_per_lot"])


def test_changing_train_data_changes_selection():
    before = walk_forward_select(_cands(), registry=TestRegistry())
    assert before["selected"] == "good"
    # Flip the TRAIN story: good loses on TRAIN, trap wins on TRAIN. TEST draws are unchanged.
    flipped = _cands(good_train=-300.0, trap_train=300.0)
    after = walk_forward_select(flipped, registry=TestRegistry())
    assert after["selected"] == "trap"
    assert after["train_table"].set_index("name").loc["trap", "expectancy_per_lot"] > \
        after["train_table"].set_index("name").loc["good", "expectancy_per_lot"]


def test_trades_straddling_train_end_are_purged_from_train():
    cands = _cands()
    tbl = cands["good"]
    e = pd.to_datetime(tbl["entry_date"])
    x = pd.to_datetime(tbl["exit_date"])
    straddle = (e >= pd.Timestamp(TRAIN_START)) & (e <= pd.Timestamp(TRAIN_END)) & (x > pd.Timestamp(TRAIN_END))
    assert straddle.sum() >= 1
    res = walk_forward_select(cands, registry=TestRegistry())
    assert res["train_table"].set_index("name").loc["good", "straddle_purged"] == int(straddle.sum())
    # The purged trades never reach the TRAIN score: rewriting their P&L leaves the score bit-identical.
    alt = tbl.copy()
    alt.loc[straddle, "pnl_gross_rs"] = -1e6
    alt.loc[straddle, "pnl_net_rs"] = -1e6
    alt.loc[straddle, "cost_rs"] = 0.0
    res2 = walk_forward_select({**cands, "good": alt}, registry=TestRegistry())
    assert res2["train_table"].set_index("name").loc["good", "expectancy_per_lot"] ==         res["train_table"].set_index("name").loc["good", "expectancy_per_lot"]


def test_selection_cut_is_registered_with_candidate_count():
    reg = TestRegistry()
    res = walk_forward_select(_cands(), registry=reg)
    cuts = {c["name"]: c for c in reg.to_dict()["cuts"]}
    sel = [c for c in cuts.values() if c["kind"] == "selection"]
    assert len(sel) == 1
    assert "chose=good" in sel[0]["name"] and "n_candidates=3" in sel[0]["detail"]
    assert sel[0]["p_value"] == pytest.approx(res["deflated_sharpe_ratio"]["p_value"])
    assert res["registry_cut"]["kind"] == "selection"
    # The selection is in the Holm family (it carries a p-value).
    assert reg.holm()[sel[0]["name"]] is not None


def test_selection_cut_persists_to_default_registry_file():
    walk_forward_select(_cands())                       # registry=None -> logs/eval_registry.json (redirected)
    cuts = json.loads(stats.DEFAULT_REGISTRY_PATH.read_text(encoding="utf-8"))
    assert sum(c["kind"] == "selection" for c in cuts) == 1


def test_dsr_uses_train_grid_and_candidate_count():
    res = walk_forward_select(_cands(), registry=TestRegistry())
    dsr = res["deflated_sharpe_ratio"]
    assert dsr["n_trials"] == 3 and dsr["n_obs"] == int(res["train_table"].set_index("name").loc["good", "n"])
    assert 0.0 <= dsr["dsr"] <= 1.0


def test_candidates_below_min_trades_on_train_are_not_selectable():
    cands = _cands()
    tiny = _frame(np.random.default_rng(9).normal(5000.0, 1000.0, 5), start=date(2019, 2, 18),
                  strategy="tiny")                                         # 5 trades, huge mean P&L
    res = walk_forward_select({**cands, "tiny": tiny}, registry=TestRegistry())
    assert res["selected"] == "good"
    assert not res["train_table"].set_index("name").loc["tiny", "eligible"]


def test_baseline_is_reported_but_never_selected():
    cands = _cands()
    base = _cand(10_000.0, 7, 10_000.0, 8, strategy="base")       # would win everything if selectable
    res = walk_forward_select(cands, base, registry=TestRegistry())
    assert res["selected"] == "good"
    assert set(res["test_table"]["role"]) == {"candidate", "baseline"}


def test_unknown_metric_is_rejected():
    with pytest.raises(ValueError, match="metric"):
        walk_forward_select(_cands(), metric="sharpe", registry=TestRegistry())


# ----------------------------------------------------------------------------- (b) holdout guard

def _with_holdout(cands, name="good"):
    late = _frame(np.full(12, -500.0), start=date(2024, 1, 8), strategy=name)
    out = dict(cands)
    out[name] = pd.concat([cands[name], late], ignore_index=True)
    return out


def test_holdout_trades_are_rejected_without_flag_and_nothing_is_written():
    reg = TestRegistry()
    with pytest.raises(HoldoutAccessError, match="holdout"):
        walk_forward_select(_with_holdout(_cands()), registry=reg)
    assert not holdout_ledger.DEFAULT_LEDGER_PATH.exists()
    assert reg.n_cuts == 0


def test_holdout_rejection_also_covers_the_baseline():
    base = _frame(np.full(12, 0.0), start=date(2024, 1, 8), strategy="base")
    with pytest.raises(HoldoutAccessError):
        walk_forward_select(_cands(), base, registry=TestRegistry())
    assert not holdout_ledger.DEFAULT_LEDGER_PATH.exists()


def test_allow_holdout_appends_ledger_row_and_counts_a_cut_then_second_look_chains():
    reg = TestRegistry()
    cands = _with_holdout(_cands())
    res1 = walk_forward_select(cands, registry=reg, allow_holdout=True)
    rows = read_ledger()
    assert len(rows) == 1
    assert rows[0]["candidate"] == "good" == res1["selected"]
    assert rows[0]["window"]["candidate_holdout_trades"] == 12
    assert rows[0]["window"]["walk_forward"] is True
    assert res1["holdout"]["n"] == 12
    assert any(c["kind"] == "holdout_look" for c in reg.to_dict()["cuts"])
    walk_forward_select(cands, registry=reg, allow_holdout=True)
    rows = read_ledger()
    assert [r["index"] for r in rows] == [0, 1] and rows[1]["prev_hash"] == rows[0]["hash"]


def test_allow_holdout_scores_holdout_only_for_selected_candidate():
    res = walk_forward_select(_with_holdout(_cands()), registry=TestRegistry(), allow_holdout=True)
    assert res["holdout"]["name"] == "good"
    assert set(res["test_table"]["name"]) == {"good"}
    assert res["holdout_trades_in_input"]["good"] == 12


# ----------------------------------------------------------------------------- (c) chain-engine timing

def _ic_world_with_bogus_signal_day(root):
    """IC world from test_chain_engine, plus bogus 999 settles for the same strikes on the signal day S.
    A fill that read S's chain instead of F's would show a credit near 999 - 999, not the F-based one."""
    days = _write_ic_world(root)
    legs_on_s = [(23350, "CE"), (23600, "CE"), (22450, "PE"), (22200, "PE")]
    _write(root, S, [_row(S, S, 23000, "PE", 1.0)] + [_row(S, E, k, opt, 999.0) for k, opt in legs_on_s])
    return days


def test_signal_on_day_d_fills_at_next_session_settle_not_on_d(tmp_path):
    days = _ic_world_with_bogus_signal_day(tmp_path)
    bt, trades = _run(tmp_path, days, _market(days, vix=15.0))
    assert len(trades) == 1, (trades, bt.skip_log)
    t = trades[0]
    assert t["signal_date"] == str(S)
    assert t["fill_date"] == str(F) == t["entry_date"]
    assert F > S and t["fill_date"] != t["signal_date"]
    # Fill prices come from F's settles (30, 10, 25, 8 less 0.45 adverse slippage), not S's 999.
    assert t["entry_credit_fill"] == pytest.approx((30.0 - 0.45) - (10.0 + 0.45) + (25.0 - 0.45) - (8.0 + 0.45))


def test_entry_gate_uses_signal_day_vix_not_fill_day_vix(tmp_path):
    days = _write_ic_world(tmp_path)
    vix = {d: 15.0 for d in days}
    vix[F] = 30.0                                  # outside the 10-25 entry band, but on the fill day only
    bt, trades = _run(tmp_path, days, _market_with_vix(days, vix))
    assert len(trades) == 1, (trades, bt.skip_log)
    assert trades[0]["signal_date"] == str(S) and trades[0]["entry_vix"] == pytest.approx(15.0)
    assert "vix_gate" not in bt.skips


def test_entry_gate_blocks_on_signal_day_vix(tmp_path):
    days = _write_ic_world(tmp_path)
    vix = {d: 15.0 for d in days}
    vix[S] = 30.0                                  # signal-day VIX outside the band blocks the entry
    bt, trades = _run(tmp_path, days, _market_with_vix(days, vix))
    assert trades == []
    assert bt.skips["vix_gate"] == 1
    assert bt.skip_log[0]["date"] == str(S)


def _market_with_vix(days, vix_by_day):
    m = _market(days, vix=15.0)
    m["vix"] = [vix_by_day[d] for d in days]
    return m
