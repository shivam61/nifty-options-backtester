"""Round 3 engine capabilities (docs/strategy_candidates_round3.md, Section 4). All opt-in; defaults unchanged.

  1. monthly cadence for PCS / IC (signal on monthly expiry day, monthly target, DTE window [15, 28])
  2. post-spike entry filter (max VIX over 20 sessions up to S >= spike_level and VIX_S <= (1 - drop) * max)
  3. term-structure filter (ATM straddle implied-move proxy: nearest weekly <= nearest monthly)
  4. trend-selected spread (TREND_SPREAD: PCS if close_S > SMA(close up to S), else CCS)
  5. wide weekly IC (k up to 1.5, arbitrary width) expressible through CandidateSpec alone

Synthetic archive and market only (tmp_path). No network, no real archive, no 2024+ dates.
"""

import gzip
import math
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from backtester.candidates import (
    CALL_CREDIT_SPREAD, IRON_CONDOR, PCS, TREND_SPREAD, CandidateSpec, all_of, is_monthly_signal_day,
    post_spike_decision, post_spike_filter, sigma_T, straddle_implied_move, term_structure_pass,
    trend_structure,
)
from backtester.chain_engine import ChainBacktest
from data.nse_fo_archive import NseFoArchive
from tests.test_candidate_engine_ext import _cfg_spec, _spec
from tests.test_candidates import (
    COLS, E, F, S, SPOT, THURS, _a_world, _market, _row, _run, _weekdays, _write_world,
)

MAR20 = date(2025, 3, 20)
JAN9 = date(2025, 1, 9)      # weekly, DTE 7 from S (Thu 2025-01-02)
JAN30 = date(2025, 1, 30)    # monthly (last Thursday of January), DTE 28 from S
FEB27 = date(2025, 2, 27)    # monthly
JAN31 = date(2025, 1, 31)    # session after the 2025-01-30 monthly signal
STRIKES_WIDE = list(range(20000, 26001, 50))


def _nearest50(x):
    return int(round(x / 50.0)) * 50


# ----------------------------------------------------------------------------- spec fields and validation

def test_round3_fields_default_off_and_existing_specs_are_unchanged():
    c = CandidateSpec("X", "X", PCS, 0.9, 200.0, "weekly", 16.0, 25.0)
    assert c.spike_level is None and c.spike_drop_pct is None
    assert c.term_structure_gate is False and c.trend_sma_days is None


def test_cadence_must_be_weekly_or_monthly():
    with pytest.raises(ValueError):
        _spec(cadence="daily")
    assert _spec(cadence="monthly").cadence == "monthly"


def test_monthly_signal_flag_defaults_off_and_needs_monthly_cadence():
    assert _spec(cadence="monthly").monthly_signal is False     # round-1 family B meaning is the default
    with pytest.raises(ValueError):
        _spec(cadence="weekly", monthly_signal=True)


def test_round1_monthly_b_cells_still_signal_every_weekly_expiry(tmp_path):
    days, mk = _monthly_world(tmp_path)
    spec = _spec(cell_id="B_T", structure=PCS, cadence="monthly", k=0.9, width=200.0)   # monthly_signal False
    bt, _ = _run(tmp_path, days, mk, _cfg_spec(spec, S, MAR20))
    assert bt.signal_days == len(THURS)


def test_monthly_cadence_is_allowed_for_credit_structures_and_ic():
    assert _spec(structure=PCS, cadence="monthly").cadence == "monthly"
    assert _spec(structure=IRON_CONDOR, cadence="monthly", k=1.0, width=300.0).structure == IRON_CONDOR


def test_spike_level_and_drop_must_be_set_together_and_in_range():
    with pytest.raises(ValueError):
        _spec(spike_level=25.0)
    with pytest.raises(ValueError):
        _spec(spike_drop_pct=0.2)
    with pytest.raises(ValueError):
        _spec(spike_level=25.0, spike_drop_pct=1.0)
    with pytest.raises(ValueError):
        _spec(spike_level=-1.0, spike_drop_pct=0.2)
    ok = _spec(spike_level=25.0, spike_drop_pct=0.2)
    assert (ok.spike_level, ok.spike_drop_pct) == (25.0, 0.2)


def test_trend_spread_requires_sma_days_and_sma_days_only_for_trend_spread():
    with pytest.raises(ValueError):
        CandidateSpec("T", "T", TREND_SPREAD, 1.0, 300.0, "weekly", 13.0, 25.0)
    with pytest.raises(ValueError):
        CandidateSpec("T", "T", TREND_SPREAD, 1.0, 300.0, "weekly", 13.0, 25.0, trend_sma_days=1)
    with pytest.raises(ValueError):
        _spec(trend_sma_days=50)                       # PCS: a trend window would be a silent no-op
    t = CandidateSpec("T", "T", TREND_SPREAD, 1.0, 300.0, "weekly", 13.0, 25.0, trend_sma_days=50)
    assert t.trend_sma_days == 50


def test_credit_width_and_k_must_be_positive_finite_but_k_has_no_upper_cap():
    with pytest.raises(ValueError):
        _spec(width=0.0)
    with pytest.raises(ValueError):
        _spec(k=0.0)
    with pytest.raises(ValueError):
        _spec(k=float("nan"))
    assert _spec(k=2.5, width=775.0).k == 2.5


def test_all_of_is_false_if_any_false_none_if_any_undefined_else_true():
    t, f, n = (lambda r: True), (lambda r: False), (lambda r: None)
    assert all_of([t, t])(None) is True
    assert all_of([t, f, n])(None) is False          # a definite False wins over an undefined
    assert all_of([t, n])(None) is None
    assert all_of([])(None) is True


# ----------------------------------------------------------------------------- 2. post-spike decision (pure)

def _vix(vals, start=date(2024, 12, 2)):
    """Weekday VIX series. The last value is the signal day S."""
    idx = pd.bdate_range(start, periods=len(vals))
    return pd.Series(np.asarray(vals, dtype=float), index=idx)


def test_post_spike_passes_when_spike_in_window_and_vix_fell_enough():
    s = _vix([15.0] * 9 + [30.0] + [15.0] * 9 + [22.0])      # 20 values, max 30, VIX_S 22 <= 0.8 * 30
    assert post_spike_decision(s, s.index[-1].date(), 25.0, 0.2) is True


def test_post_spike_fails_when_vix_has_not_fallen_enough():
    s = _vix([15.0] * 9 + [30.0] + [15.0] * 9 + [25.0])      # 25 > 0.8 * 30 = 24
    assert post_spike_decision(s, s.index[-1].date(), 25.0, 0.2) is False


def test_post_spike_fails_without_a_spike_level_in_window():
    s = _vix([15.0] * 10 + [24.0] * 9 + [10.0])              # max 24 < 25 even though VIX fell a lot
    assert post_spike_decision(s, s.index[-1].date(), 25.0, 0.2) is False


def test_post_spike_window_is_exactly_twenty_sessions():
    s = _vix([30.0] + [15.0] * 20)                           # spike is 20 sessions before S: outside the window
    assert post_spike_decision(s, s.index[-1].date(), 25.0, 0.2) is False
    s = _vix([30.0] + [15.0] * 19)                           # spike is the first of the 20 window values
    assert post_spike_decision(s, s.index[-1].date(), 25.0, 0.2) is True


def test_post_spike_boundaries_are_inclusive():
    s = _vix([25.0] + [15.0] * 18 + [20.0])                  # max 25 == spike_level (inclusive)
    assert post_spike_decision(s, s.index[-1].date(), 25.0, 0.2) is True
    s = _vix([40.0] + [15.0] * 18 + [30.0])                  # VIX_S 30 == (1 - 0.25) * 40 (inclusive)
    assert post_spike_decision(s, s.index[-1].date(), 40.0, 0.25) is True
    s = _vix([40.0] + [15.0] * 18 + [30.5])
    assert post_spike_decision(s, s.index[-1].date(), 40.0, 0.25) is False


def test_post_spike_undefined_with_short_history_or_nan_in_window_is_none():
    short = _vix([15.0] * 19)
    assert post_spike_decision(short, short.index[-1].date(), 25.0, 0.2) is None
    s = _vix([15.0] * 8 + [np.nan] + [15.0] * 10 + [22.0])
    assert post_spike_decision(s, s.index[-1].date(), 25.0, 0.2) is None


def test_post_spike_ignores_vix_after_signal_day():
    s = _vix([15.0] * 9 + [30.0] + [15.0] * 9 + [22.0])
    sig = s.index[-1].date()
    base = post_spike_decision(s, sig, 25.0, 0.2)
    later = pd.concat([s, _vix([99.0, 0.5, 60.0], start=s.index[-1] + pd.offsets.BDay(1))])
    assert post_spike_decision(later, sig, 25.0, 0.2) == base


def test_post_spike_filter_reads_the_signal_row_date():
    s = _vix([15.0] * 9 + [30.0] + [15.0] * 9 + [22.0])
    f = post_spike_filter(s, 25.0, 0.2)
    assert f(pd.Series({"vix": 22.0}, name=s.index[-1])) is True
    assert f(pd.Series({"vix": 22.0}, name=s.index[-2])) is None   # 19 sessions up to that day: undefined


# ----------------------------------------------------------------------------- 3. straddle proxy and term gate (pure)

def _chain(rows):
    """rows: (strike, opt, settle, contracts)."""
    return pd.DataFrame([{"strike": float(k), "opt": o, "settle": float(p), "contracts": float(c)}
                         for k, o, p, c in rows])


def test_straddle_proxy_uses_atm_pair_and_sqrt_dte_365():
    ch = _chain([(23000, "CE", 300.0, 100), (23000, "PE", 280.0, 100),     # |CE-PE| = 20
                 (23050, "CE", 250.0, 100), (23050, "PE", 250.0, 100),     # |CE-PE| = 0: ATM
                 (23100, "CE", 200.0, 100), (23100, "PE", 330.0, 100)])
    got = straddle_implied_move(ch, 23000.0, 7)
    assert got == pytest.approx(500.0 / (23000.0 * math.sqrt(7 / 365)))


def test_straddle_proxy_excludes_zero_contract_settles():
    ch = _chain([(23050, "CE", 250.0, 0), (23050, "PE", 250.0, 100),       # 0-contract CE: strike unusable
                 (23000, "CE", 300.0, 100), (23000, "PE", 320.0, 100)])
    got = straddle_implied_move(ch, 23000.0, 7)
    assert got == pytest.approx(620.0 / (23000.0 * math.sqrt(7 / 365)))


def test_straddle_proxy_undefined_without_a_pair_or_bad_inputs():
    assert straddle_implied_move(_chain([(23000, "CE", 300.0, 100)]), 23000.0, 7) is None
    ch = _chain([(23000, "CE", 300.0, 100), (23000, "PE", 300.0, 100)])
    assert straddle_implied_move(ch, 23000.0, 0) is None
    assert straddle_implied_move(ch, float("nan"), 7) is None


class FakeArch:
    """Minimal archive for the pure helpers: per-day expiry index and chain frames."""

    def __init__(self, listed_by_day, chains):
        self._expiries_by_day = listed_by_day
        self._chains = chains

    def chain(self, day, expiry):
        return self._chains.get((day, expiry), pd.DataFrame(columns=COLS))


def _pair(px_leg):
    return [(23000, "CE", px_leg, 100), (23000, "PE", px_leg, 100)]


def _fake(weekly_leg, monthly_leg, extra=None):
    """On S: weekly JAN9 (DTE 7) with straddle 2*weekly_leg; monthly JAN30 (DTE 28) with straddle 2*monthly_leg."""
    listed = {S: [S, JAN9, JAN30, FEB27]}
    chains = {(S, JAN9): _chain(_pair(weekly_leg)), (S, JAN30): _chain(_pair(monthly_leg))}
    chains.update(extra or {})
    return FakeArch(listed, chains)


def test_term_structure_passes_on_contango_and_fails_on_backwardation():
    spot = 23000.0
    assert term_structure_pass(_fake(30.0, 75.0), S, spot) is True      # 60 at DTE 7 vs 150 at DTE 28
    assert term_structure_pass(_fake(75.0, 30.0), S, spot) is False


def test_term_structure_never_reads_the_signal_day_expiry_rows():
    junk = {(S, S): _chain([(23000, "CE", 1e6, 100), (23000, "PE", 1e6, 100)])}
    assert term_structure_pass(_fake(30.0, 75.0, extra=junk), S, 23000.0) is True


def test_term_structure_undefined_without_monthly_or_weekly_or_atm():
    spot = 23000.0
    # S, JAN9 only: JAN9 is the last listed expiry of January, so it is the monthly; no weekly exists
    no_weekly = FakeArch({S: [S, JAN9]}, {(S, JAN9): _chain(_pair(30.0))})
    assert term_structure_pass(no_weekly, S, spot) is None
    # JAN30 is the monthly, nothing non-monthly after S
    empty_weekly = FakeArch({S: [S, JAN30]}, {(S, JAN30): _chain(_pair(75.0))})
    assert term_structure_pass(empty_weekly, S, spot) is None
    # weekly exists but has no ATM pair (CE only)
    no_atm = _fake(30.0, 75.0, extra={(S, JAN9): _chain([(23000, "CE", 30.0, 100)])})
    assert term_structure_pass(no_atm, S, spot) is None


def test_is_monthly_signal_day_is_true_only_on_the_last_listed_expiry_of_the_month():
    arch = FakeArch({JAN30: [JAN30, FEB27], S: [S, JAN9, JAN30, FEB27]}, {})
    assert is_monthly_signal_day(arch, JAN30) is True
    assert is_monthly_signal_day(arch, S) is False


# ----------------------------------------------------------------------------- trend-selected spread (pure)

def test_trend_structure_is_pcs_above_sma_ccs_otherwise():
    idx = pd.bdate_range("2024-10-01", periods=60)
    sig = idx[-1].date()
    rising = pd.Series(np.linspace(20000.0, 23000.0, 60), index=idx)
    assert trend_structure(rising, sig, 50) == PCS
    falling = pd.Series(np.linspace(23000.0, 20000.0, 60), index=idx)
    assert trend_structure(falling, sig, 50) == CALL_CREDIT_SPREAD
    flat = pd.Series(np.full(60, 23000.0), index=idx)
    assert trend_structure(flat, sig, 50) == CALL_CREDIT_SPREAD   # close == SMA is not above


def test_trend_structure_needs_sma_days_closes_up_to_signal_else_none():
    idx = pd.bdate_range("2024-10-01", periods=60)
    s = pd.Series(np.linspace(20000.0, 23000.0, 60), index=idx)
    assert trend_structure(s.iloc[:49], idx[48].date(), 50) is None   # 49 closes up to S
    holed = s.copy()
    holed.iloc[-10] = np.nan
    assert trend_structure(holed, idx[-1].date(), 50) is None


def test_trend_structure_ignores_closes_after_signal_day():
    idx = pd.bdate_range("2024-10-01", periods=80)
    s = pd.Series(np.linspace(20000.0, 23000.0, 80), index=idx)
    sig = idx[60].date()                                  # 61 closes up to S: the SMA50 is defined
    assert trend_structure(s, sig, 50) == PCS
    later = s.copy()
    later.iloc[61:] = 1.0
    assert trend_structure(later, sig, 50) == PCS
    on_s = s.copy()
    on_s.iloc[60] = 1.0                                   # not vacuous: the close on S itself decides
    assert trend_structure(on_s, sig, 50) == CALL_CREDIT_SPREAD


# ----------------------------------------------------------------------------- engine: monthly cadence

def _monthly_world(root):
    days = _weekdays(S, MAR20)
    _write_world(root, days)
    return days, _market(days, vix=20.0)


def test_monthly_cadence_signals_only_on_monthly_expiry_days(tmp_path):
    days, mk = _monthly_world(tmp_path)
    spec = _spec(cell_id="M_T", structure=PCS, cadence="monthly", monthly_signal=True, k=0.9, width=200.0)
    bt, _ = _run(tmp_path, days, mk, _cfg_spec(spec, S, MAR20))
    assert bt.signal_days == 3          # Jan 30, Feb 27, Mar 20 (last listed expiry of each month)


def test_weekly_cadence_still_signals_every_listed_expiry_day(tmp_path):
    days, mk = _monthly_world(tmp_path)
    bt, _ = _run(tmp_path, days, mk, _cfg_spec(_spec(cell_id="W_T", cadence="weekly"), S, MAR20))
    assert bt.signal_days == len(THURS)


def test_monthly_signal_on_jan30_targets_feb27_with_dte_27_and_holds_to_it(tmp_path):
    root = tmp_path / "m2"
    days = _weekdays(S, MAR20)
    sg = sigma_T(SPOT, 20.0, 27)
    ks = _nearest50(SPOT - 0.9 * sg)
    _write_world(root, days, prices={(JAN31, "PE", ks): 40.0, (JAN31, "PE", ks - 200): 15.0})
    mk = _market(days, vix=20.0)
    spec = _spec(cell_id="M_T", structure=PCS, cadence="monthly", monthly_signal=True, k=0.9, width=200.0)
    bt, trades = _run(root, days, mk, _cfg_spec(spec, S, MAR20))
    jan = [t for t in trades if t["signal_date"] == str(JAN30)]
    assert len(jan) == 1, bt.skip_log
    t = jan[0]
    assert t["fill_date"] == str(JAN31) and t["expiry"] == str(FEB27)
    assert t["dte_at_fill"] == 27 and t["exit_date"] == str(FEB27)
    assert sorted((l["strike"], l["short"]) for l in t["legs"]) == [(ks - 200, False), (ks, True)]


def test_monthly_cadence_requires_expiry_day_signal_cadence(tmp_path):
    days, mk = _monthly_world(tmp_path)
    with pytest.raises(ValueError):
        ChainBacktest(NseFoArchive(archive_dir=str(tmp_path)), mk,
                      _cfg_spec(_spec(cadence="monthly", monthly_signal=True), S, MAR20, signal_cadence="weekly_fixed_weekday"))


# ----------------------------------------------------------------------------- engine: post-spike filter

SPIKE_DAY = date(2024, 12, 20)     # inside the 20 sessions before S


def _hist_market(vix_map, vix=20.0):
    hist = _weekdays(date(2024, 11, 20), E)
    return hist, _market(hist, vix=vix, vix_map=vix_map)


def _spike_spec(**kw):
    base = dict(cell_id="SP_T", structure=PCS, k=0.9, width=200.0, vix_lo=0.0, vix_hi=100.0,
                spike_level=25.0, spike_drop_pct=0.2)
    base.update(kw)
    return _spec(**base)


def test_engine_post_spike_passes_and_skips_as_the_rule_says(tmp_path):
    days = _a_world(tmp_path)[0]
    hist, mk = _hist_market({SPIKE_DAY: 30.0, S: 22.0})
    bt, _ = _run(tmp_path, days, mk, _cfg_spec(_spike_spec(), S, E))
    assert "entry_filter" not in bt.skips                        # 22 <= 0.8 * 30 with a spike in window

    mk2 = _market(hist, vix=20.0, vix_map={SPIKE_DAY: 30.0, S: 26.0})
    bt2, trades2 = _run(tmp_path, days, mk2, _cfg_spec(_spike_spec(), S, E))
    assert bt2.skips["entry_filter"] == 1 and trades2 == []      # 26 > 0.8 * 30
    assert [e["date"] for e in bt2.skip_log if e["reason"] == "entry_filter"] == [str(S)]


def test_engine_post_spike_undefined_history_is_missing_data(tmp_path):
    days = _a_world(tmp_path)[0]
    _, mk = _hist_market({})
    bt, trades = _run(tmp_path, days, mk.iloc[-8:], _cfg_spec(_spike_spec(), S, E))
    assert trades == [] and bt.skips["missing_data"] >= 1 and "entry_filter" not in bt.skips


def test_post_spike_and_explicit_entry_filter_together_are_rejected(tmp_path):
    days = _a_world(tmp_path)[0]
    _, mk = _hist_market({SPIKE_DAY: 30.0})
    with pytest.raises(ValueError):
        ChainBacktest(NseFoArchive(archive_dir=str(tmp_path)), mk,
                      _cfg_spec(_spike_spec(), S, E, candidate_entry_filter=lambda r: True))


# ----------------------------------------------------------------------------- engine: term-structure gate

def _write_priced_world(root, days, price):
    """price(day, expiry, opt, strike) -> settle for non-expiry-day groups; expiry-day groups settle at the index."""
    for d in days:
        rows = []
        for e in THURS:
            if e < d or (e - d).days > 60:
                continue
            for opt in ("PE", "CE"):
                for k in range(21000, 24001, 50):
                    settle = SPOT if e == d else price(d, e, opt, k)
                    rows.append(_row(d, e, k, opt, settle))
        path = root / "daily" / (d.strftime("%Y%m%d") + ".csv.gz")
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(path, "wt") as fh:
            pd.DataFrame(rows, columns=COLS).to_csv(fh, index=False)


def _term_price(weekly_leg, monthly_leg):
    def price(d, e, opt, k):
        if e == JAN9:
            return weekly_leg
        if e == JAN30:
            return monthly_leg
        return 10.0
    return price


def test_engine_term_gate_blocks_backwardation_and_passes_contango(tmp_path):
    days = _weekdays(S, JAN30)
    mk = _market(days, vix=20.0)
    spec = _spec(cell_id="TS_T", structure=PCS, term_structure_gate=True)
    # Only the decision on S is asserted: later Thursdays in this synthetic world carry flat prices and may be
    # backwardated for reasons unrelated to the test.
    def _filter_days(bt):
        return [e["date"] for e in bt.skip_log if e["reason"] == "entry_filter"]

    _write_priced_world(tmp_path / "back", days, _term_price(75.0, 30.0))      # weekly straddle > monthly
    bt, _ = _run(tmp_path / "back", days, mk, _cfg_spec(spec, S, JAN30))
    assert str(S) in _filter_days(bt)
    _write_priced_world(tmp_path / "contango", days, _term_price(30.0, 75.0))  # weekly straddle < monthly
    bt2, _ = _run(tmp_path / "contango", days, mk, _cfg_spec(spec, S, JAN30))
    assert str(S) not in _filter_days(bt2)


def test_term_gate_off_by_default_is_unchanged(tmp_path):
    days = _weekdays(S, JAN30)
    _write_priced_world(tmp_path, days, _term_price(75.0, 30.0))
    bt, _ = _run(tmp_path, days, _market(days, vix=20.0), _cfg_spec(_spec(cell_id="TS0"), S, JAN30))
    assert "entry_filter" not in bt.skips


# ----------------------------------------------------------------------------- engine: trend-selected spread

def _trend_market(pre_closes):
    """History (2024-11-20 .. S-1) with the given closes, then a flat 23000 from S (so the F spot is 23000)."""
    hist = _weekdays(date(2024, 9, 2), S - timedelta(days=1))     # ~85 sessions: SMA50 defined on S
    days = _weekdays(S, E)
    closes = list(pre_closes(len(hist))) + [SPOT] * len(days)
    m = _market(hist + days, vix=20.0)
    m["nifty_close"] = closes
    return days, m


def _trend_spec(**kw):
    base = dict(cell_id="TR_T", family="T", structure=TREND_SPREAD, k=0.9, width=200.0, cadence="weekly",
                vix_lo=16.0, vix_hi=25.0, trend_sma_days=50)
    base.update(kw)
    return CandidateSpec(**base)


def _tr_prices():
    sg = sigma_T(SPOT, 20.0, 6)
    kp, kc = _nearest50(SPOT - 0.9 * sg), _nearest50(SPOT + 0.9 * sg)
    return {(F, "PE", kp): 40.0, (F, "PE", kp - 200): 15.0, (F, "CE", kc): 40.0, (F, "CE", kc + 200): 15.0}


def test_trend_spread_selects_pcs_on_uptrend_and_ccs_on_downtrend(tmp_path):
    days = _a_world(tmp_path, prices=_tr_prices())[0]
    _, up = _trend_market(lambda n: np.linspace(21000.0, 22990.0, n))
    bt, trades = _run(tmp_path, days, up, _cfg_spec(_trend_spec(), S, E))
    assert len(trades) == 1, (trades, bt.skip_log)
    assert trades[0]["resolved_structure"] == PCS
    assert {l["type"] for l in trades[0]["legs"]} == {"PE"}

    _, down = _trend_market(lambda n: np.linspace(24000.0, 23010.0, n))
    bt2, trades2 = _run(tmp_path, days, down, _cfg_spec(_trend_spec(), S, E))
    assert len(trades2) == 1, (trades2, bt2.skip_log)
    assert trades2[0]["resolved_structure"] == CALL_CREDIT_SPREAD
    assert {l["type"] for l in trades2[0]["legs"]} == {"CE"}


def test_trend_spread_without_enough_history_skips_as_missing_data(tmp_path):
    days = _a_world(tmp_path, prices=_tr_prices())[0]
    _, up = _trend_market(lambda n: np.linspace(21000.0, 22990.0, n))
    bt, trades = _run(tmp_path, days, up.iloc[-16:], _cfg_spec(_trend_spec(), S, E))   # 10 closes before S
    assert trades == [] and bt.skips["missing_data"] >= 1


# ----------------------------------------------------------------------------- 5. wide weekly IC is expressible

def _wide_world(root):
    days = _weekdays(S, E)
    sg = sigma_T(SPOT, 20.0, 6)
    kc, kp = _nearest50(SPOT + 1.5 * sg), _nearest50(SPOT - 1.5 * sg)
    prices = {(F, "PE", kp): 40.0, (F, "PE", kp - 450): 15.0, (F, "CE", kc): 40.0, (F, "CE", kc + 450): 15.0}
    _write_world(root, days, prices=prices, strikes=STRIKES_WIDE)
    return days, _market(days, vix=20.0), kc, kp


def test_wide_weekly_ic_with_k_1_5_and_width_450_opens_with_expected_legs(tmp_path):
    days, mk, kc, kp = _wide_world(tmp_path)
    spec = CandidateSpec("IC_WIDE", "W", IRON_CONDOR, 1.5, 450.0, "weekly", 16.0, 25.0)
    bt, trades = _run(tmp_path, days, mk, _cfg_spec(spec, S, E))
    assert len(trades) == 1, (trades, bt.skip_log)
    t = trades[0]
    assert t["k"] == 1.5 and t["width"] == 450.0
    assert sorted((l["type"], l["strike"], l["short"]) for l in t["legs"]) == sorted([
        ("PE", kp, True), ("PE", kp - 450, False), ("CE", kc, True), ("CE", kc + 450, False)])


def test_arbitrary_width_is_expressible_and_unlisted_wing_is_a_skip_not_a_crash(tmp_path):
    days, mk, _, _ = _wide_world(tmp_path)
    spec = CandidateSpec("IC_W275", "W", IRON_CONDOR, 1.5, 275.0, "weekly", 16.0, 25.0)
    bt, trades = _run(tmp_path, days, mk, _cfg_spec(spec, S, E))
    assert trades == [] and bt.skips["no_listed_strike"] >= 1
