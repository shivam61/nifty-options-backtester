"""Leak guards for the round-3 entry filters (docs/strategy_candidates_round3.md, Section 5 and Section 4 item 6).

Filters 2 (post-spike), 3 (term-structure) and 4 (trend-selected structure) may read only data dated on or before
the signal day S. Mutating any input dated after S must leave their outputs unchanged. Each test also checks that
the same mutation on S itself does change the output, so the guard is not vacuous.

Synthetic data only (tmp_path archives, in-memory market frames).
"""

from datetime import date

import numpy as np
import pandas as pd

from backtester.candidates import (
    CALL_CREDIT_SPREAD, PCS, post_spike_decision, post_spike_filter, term_structure_filter, trend_structure,
)
from data.nse_fo_archive import NseFoArchive
from tests.test_candidates import S, _market, _weekdays
from tests.test_round3_engine import JAN9, _term_price, _write_priced_world


# ----------------------------------------------------------------------------- filter 2: post-spike

def _vix_path():
    idx = pd.bdate_range("2024-11-01", "2025-02-28")
    rng = np.random.default_rng(11)
    vals = np.clip(18.0 + np.cumsum(rng.normal(0.0, 0.8, len(idx))), 9.0, 60.0)
    return pd.Series(vals, index=idx)


def test_post_spike_filter_ignores_vix_after_signal_day():
    vix = _vix_path()
    sig = pd.Timestamp(date(2025, 1, 15))
    base = post_spike_decision(vix, sig.date(), 25.0, 0.2)
    poisoned = vix.copy()
    poisoned.loc[poisoned.index > sig] = np.linspace(1.0, 90.0, int((poisoned.index > sig).sum()))
    assert post_spike_decision(poisoned, sig.date(), 25.0, 0.2) == base
    row = pd.Series({"vix": float(vix.loc[sig])}, name=sig)
    assert post_spike_filter(poisoned, 25.0, 0.2)(row) == post_spike_filter(vix, 25.0, 0.2)(row)


def test_post_spike_guard_is_not_vacuous():
    vix = _vix_path()
    sig = pd.Timestamp(date(2025, 1, 15))
    # Build a case that flips on the signal-day value: spike 30 well inside the window, VIX_S just above or below
    # the drop threshold.
    s = vix.copy()
    s.loc[:sig] = 15.0
    s.loc[sig - pd.offsets.BDay(3)] = 30.0
    s.loc[sig] = 22.0
    assert post_spike_decision(s, sig.date(), 25.0, 0.2) is True
    s.loc[sig] = 26.0
    assert post_spike_decision(s, sig.date(), 25.0, 0.2) is False


# ----------------------------------------------------------------------------- filter 3: term structure

def _world(root_name, tmp_path, after_price):
    """Archive identical to the others on S (weekly 30 vs monthly 75: contango). Days after S use after_price."""
    days = _weekdays(S, date(2025, 1, 10))
    root = tmp_path / root_name
    base = _term_price(30.0, 75.0)

    def price(d, e, opt, k):
        return base(d, e, opt, k) if d <= S else after_price(d, e, opt, k)

    _write_priced_world(root, days, price)
    return NseFoArchive(archive_dir=str(root))


def _signal_row(s_close=23000.0):
    days = _weekdays(S, date(2025, 1, 10))
    mk = _market(days, vix=20.0)
    mk["nifty_close"] = s_close
    return mk.loc[pd.Timestamp(S)]


def test_term_filter_ignores_archive_rows_dated_after_signal_day(tmp_path):
    calm = _world("calm", tmp_path, lambda d, e, opt, k: 10.0)
    wild = _world("wild", tmp_path, lambda d, e, opt, k: 999.0 if e == JAN9 else 1.0)
    row = _signal_row()
    assert term_structure_filter(calm)(row) is True
    assert term_structure_filter(wild)(row) == term_structure_filter(calm)(row)


def test_term_filter_guard_is_not_vacuous_when_signal_day_prices_change(tmp_path):
    contango = _world("c2", tmp_path, lambda d, e, opt, k: 10.0)
    days = _weekdays(S, date(2025, 1, 10))
    root = tmp_path / "flipped"
    _write_priced_world(root, days, _term_price(75.0, 30.0))      # S itself now backwardated
    flipped = NseFoArchive(archive_dir=str(root))
    row = _signal_row()
    assert term_structure_filter(contango)(row) is True
    assert term_structure_filter(flipped)(row) is False


# ----------------------------------------------------------------------------- filter 4: trend-selected structure

def test_trend_structure_ignores_closes_after_signal_day():
    idx = pd.bdate_range("2024-10-01", "2025-02-28")
    rng = np.random.default_rng(5)
    closes = pd.Series(21000.0 + np.cumsum(rng.normal(0.0, 60.0, len(idx))), index=idx)
    sig = pd.Timestamp(date(2025, 1, 2))
    base = trend_structure(closes, sig.date(), 50)
    assert base in (PCS, CALL_CREDIT_SPREAD)
    poisoned = closes.copy()
    poisoned.loc[poisoned.index > sig] = np.linspace(1.0, 1.0e6, int((poisoned.index > sig).sum()))
    assert trend_structure(poisoned, sig.date(), 50) == base


def test_trend_structure_guard_is_not_vacuous_on_the_signal_close():
    idx = pd.bdate_range("2024-10-01", "2025-02-28")
    closes = pd.Series(np.linspace(20000.0, 23000.0, len(idx)), index=idx)
    sig = pd.Timestamp(date(2025, 1, 2))
    assert trend_structure(closes, sig.date(), 50) == PCS
    on_s = closes.copy()
    on_s.loc[sig] = 15000.0                               # the signal-day close itself is inside the window
    assert trend_structure(on_s, sig.date(), 50) == CALL_CREDIT_SPREAD
