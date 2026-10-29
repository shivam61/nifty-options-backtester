"""Unit tests for scripts/ml_gate_adapters.py (no models, no network)."""

import json
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import ml_gate_adapters as g  # noqa: E402


def _frame(n=6):
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    data = {c: np.arange(n, dtype=float) + i for i, c in enumerate(g.LAG_COLUMNS + g.INDIA_COLUMNS)}
    return pd.DataFrame(data, index=idx)


def test_lag_columns_disjoint_and_complete():
    assert not set(g.LAG_COLUMNS) & set(g.INDIA_COLUMNS)
    assert len(g.LAG_COLUMNS) + len(g.INDIA_COLUMNS) == 103


def test_lag_shifts_exactly_one_row_and_leaves_india_untouched():
    df = _frame()
    out = g.lag_non_india_columns(df)
    for c in g.LAG_COLUMNS:
        assert np.isnan(out[c].iloc[0])
        np.testing.assert_array_equal(out[c].iloc[1:].values, df[c].iloc[:-1].values)
    for c in g.INDIA_COLUMNS:
        np.testing.assert_array_equal(out[c].values, df[c].values)
    assert out is not df


def test_unclassified_column_raises():
    df = _frame()
    df["brand_new_series"] = 1.0
    with pytest.raises(ValueError, match="brand_new_series"):
        g.lag_non_india_columns(df)


def test_finite_or_raise_allowlist_and_missing():
    ok = g._finite_or_raise({"a": 1.0, "b": 2.0}, ["a", "b"], "t")
    assert ok.shape == (1, 2)
    with pytest.raises(ValueError):
        g._finite_or_raise({"a": float("nan")}, ["a"], "t")
    with pytest.raises(ValueError):
        g._finite_or_raise({"a": float("inf")}, ["a"], "t")
    with pytest.raises(KeyError):
        g._finite_or_raise({}, ["a"], "t")
    z = g._finite_or_raise({"a": float("nan")}, ["a", "b"], "t", frozenset({"a", "b"}))
    assert z.tolist() == [[0.0, 0.0]]


def test_fold_models_select_by_year_and_reject_leaky_fold(tmp_path):
    for y, train_end, max_row in ((2023, "2022-12-31", "2022-12-30"), (2024, "2024-06-30", "2024-06-30")):
        (tmp_path / str(y)).mkdir()
        (tmp_path / str(y) / "meta.json").write_text(json.dumps(
            {"train_end": train_end, "max_row_date": max_row}))
    seen = []
    fm = g._FoldModels(tmp_path, "m.pkl", lambda mdf, p: seen.append(p) or p.parent.name, pd.DataFrame())
    assert fm.get(date(2023, 5, 1)) == "2023"
    assert fm.get(date(2023, 11, 1)) == "2023"
    assert len(seen) == 1
    with pytest.raises(AssertionError, match="not out of sample"):
        fm.get(date(2024, 2, 1))
    with pytest.raises(FileNotFoundError):
        fm.get(date(2030, 1, 1))


def _leg(opt, strike, short):
    return SimpleNamespace(option_type=opt, strike=strike, is_short=short)


def _ctx(pnl_rs, holding, dte=3, spot=24000.0, legs=None):
    legs = legs or [_leg("PE", 23600, True), _leg("PE", 23500, False)]
    trade = SimpleNamespace(lots=10, lot_size=65, legs=legs)
    shorts = [(l.option_type, l.strike) for l in legs if l.is_short]
    return {"date": date(2024, 3, 1), "trade": trade, "fill_date": date(2024, 2, 26), "dte": dte,
            "holding_sessions": holding, "holding_days": holding, "entry_spot": 24000.0, "spot": spot,
            "entry_vix": 14.0, "vix": 16.8, "entry_credit_rs": 20.0 * 650, "mark_pnl_rs": pnl_rs * 650,
            "short_strikes": shorts}


def test_trade_exit_features_units_and_signs():
    hist = {}
    f = g.trade_exit_features(_ctx(-5.0, 1, spot=23900.0), hist)
    assert f["pnl_pct"] == pytest.approx(-25.0)
    assert f["credit_captured_pct"] == f["pnl_pct"]
    assert f["dist_to_short_strike_pct"] == pytest.approx((23900 - 23600) / 23900 * 100)
    assert f["vix_change_since_entry"] == pytest.approx(0.2)
    assert f["spot_change_since_entry"] == pytest.approx(-100 / 24000 * 100)
    assert f["max_loss_proximity"] == pytest.approx(5.0 / (100 - 20.0))
    assert f["pnl_velocity"] == pytest.approx(-5.0)
    assert f["pnl_velocity_3d"] == pytest.approx(-5.0)
    assert f["pnl_from_peak"] == pytest.approx(-5.0)
    assert f["days_since_peak"] == 0


def test_trade_exit_features_peak_and_3d_velocity_use_history():
    hist = {}
    for d, p in ((1, 4.0), (2, 8.0), (3, 6.0), (4, 2.0)):
        f = g.trade_exit_features(_ctx(p, d), hist)
    assert f["pnl_from_peak"] == pytest.approx(2.0 - 8.0)
    assert f["days_since_peak"] == 2
    assert f["pnl_velocity_3d"] == pytest.approx((2.0 - 4.0) / 3)


def test_trade_exit_features_condor_uses_nearest_side_and_wider_wing():
    legs = [_leg("PE", 23600, True), _leg("PE", 23500, False), _leg("CE", 24400, True), _leg("CE", 24600, False)]
    f = g.trade_exit_features(_ctx(-1.0, 1, spot=24300.0, legs=legs), {})
    assert f["dist_to_short_strike_pct"] == pytest.approx((24400 - 24300) / 24300 * 100)
    assert f["max_loss_proximity"] == pytest.approx(1.0 / (200 - 20.0))


def test_trade_exit_features_history_gap_raises():
    with pytest.raises(ValueError, match="gap"):
        g.trade_exit_features(_ctx(1.0, 5), {1: 0.5})


class _StubClf:
    classes_ = [0, 1]
    feature_name_ = ["pnl_pct", "vix_now"]

    def __init__(self, p):
        self.p = p

    def predict_proba(self, X):
        return np.array([[1 - self.p, self.p]])


def _stub_exit_gate(monkeypatch, tmp_path, prob):
    (tmp_path / "2024").mkdir()
    (tmp_path / "2024" / "meta.json").write_text(json.dumps(
        {"train_end": "2023-12-31", "max_row_date": "2023-12-31"}))
    idx = pd.to_datetime([date(2024, 3, 1)])
    frame = pd.DataFrame({"vix_vs_sma_ratio": [1.1], "vix_change_1d": [0.02]}, index=idx)

    class _Eng:
        exit_classifier = _StubClf(prob)
        feature_extractor = SimpleNamespace(data=frame, extract=lambda row: {"vix_now_market": 1.0})

    import models.trade_monitor as tm
    monkeypatch.setattr(tm.ExitStrategyEngine, "load", classmethod(lambda cls, mdf, path: _Eng()))
    monkeypatch.setattr(g, "_assert_all_nan", lambda *a, **k: None)
    return g.make_exit_gate(tmp_path, frame)


@pytest.mark.parametrize("pnl,prob,fires", [(-5.0, 0.9, True), (-1.0, 0.99, False), (-5.0, 0.7, False),
                                            (-5.0, 0.75, True)])
def test_exit_gate_needs_both_prob_and_loss(monkeypatch, tmp_path, pnl, prob, fires):
    gate = _stub_exit_gate(monkeypatch, tmp_path, prob)
    exit_now, score = gate(_ctx(pnl, 1))
    assert score == pytest.approx(prob)
    assert exit_now is fires


FOLDS = Path.home() / "edge_explore" / "ml_wf"


@pytest.mark.skipif(not (FOLDS / "2024" / "weekly_entry.pkl").exists(), reason="walk-forward folds not present")
def test_entry_gate_matches_learner_predict_on_lagged_frame():
    m = g.load_gate_market(date(2024, 12, 31))
    gate = g.make_entry_gate(FOLDS, m, 0.55)
    d = pd.Timestamp("2024-06-13")
    allow, score = gate(d.date(), "weekly_ic", float(m.loc[d, "vix"]), {})
    lr = gate.models.get(d)
    idx = lr.feature_extractor.data.index.get_loc(d)
    assert score == pytest.approx(lr.predict(lr.feature_extractor.data.iloc[idx], idx))
    assert allow == (score >= 0.55)
