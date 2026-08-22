"""
Tests for models/regime_classifier.py and models/trade_learner.py

Covers:
- Rule-based regime labeling determinism
- Regime classifier training + prediction
- Vol crush detection
- FeatureExtractor output shape and missing-data handling
"""

import pytest
import numpy as np
import pandas as pd
from datetime import date

from models.regime_classifier import (
    Regime, REGIME_NAMES, label_regime_rules, RegimeClassifier, _is_vol_crush,
)
from models.trade_learner import FeatureExtractor, TradeLearner, _safe_float
from backtester.engine import TradeResult


# ---------------------------------------------------------------------------
# Rule-based regime labeling
# ---------------------------------------------------------------------------

class TestLabelRegimeRules:

    def _row(self, **overrides):
        defaults = {
            "vix": 16.0,
            "nifty_realized_vol_20d": 13.0,
            "nifty_drawdown_from_20d_high_pct": -1.0,
            "nifty_drawdown_from_50d_high_pct": -2.0,
            "nifty_rsi_14": 50.0,
            "nifty_return_20d": 0.02,
            "nifty_consec_down_days": 0,
            "crash_risk_score_v2": 0.1,
        }
        defaults.update(overrides)
        return pd.Series(defaults)

    def test_crash_high_vix_and_drawdown(self):
        row = self._row(vix=28, nifty_drawdown_from_20d_high_pct=-6)
        assert label_regime_rules(row) == Regime.CRASH

    def test_crash_consecutive_down_days(self):
        row = self._row(vix=21, nifty_consec_down_days=5)
        assert label_regime_rules(row) == Regime.CRASH

    def test_trending_bullish(self):
        row = self._row(nifty_return_20d=0.07, nifty_rsi_14=65)
        assert label_regime_rules(row) == Regime.TRENDING

    def test_trending_bearish(self):
        row = self._row(
            nifty_return_20d=-0.07, nifty_rsi_14=35,
            nifty_drawdown_from_20d_high_pct=-3.0,
        )
        assert label_regime_rules(row) == Regime.TRENDING

    def test_low_vol(self):
        row = self._row(vix=12, nifty_realized_vol_20d=10)
        assert label_regime_rules(row) == Regime.LOW_VOL

    def test_high_vol_default(self):
        row = self._row(vix=18, nifty_realized_vol_20d=16)
        assert label_regime_rules(row) == Regime.HIGH_VOL

    def test_nan_vix_defaults_to_high_vol(self):
        row = self._row(vix=float("nan"))
        result = label_regime_rules(row)
        assert result in (Regime.LOW_VOL, Regime.HIGH_VOL, Regime.TRENDING)


# ---------------------------------------------------------------------------
# Vol crush detection
# ---------------------------------------------------------------------------

class TestVolCrush:

    def _row(self, **overrides):
        defaults = {
            "vix": 18.0,
            "vix_vs_sma_ratio": 1.0,
            "vix_change_1d": 0.0,
            "vix_change_5d": 0.0,
        }
        defaults.update(overrides)
        return pd.Series(defaults)

    def test_not_vol_crush_when_vix_high(self):
        assert _is_vol_crush(self._row(vix=25)) is False

    def test_vol_crush_when_ratio_low(self):
        assert _is_vol_crush(self._row(vix=17, vix_vs_sma_ratio=0.75)) is True

    def test_vol_crush_when_1d_drop(self):
        assert _is_vol_crush(self._row(vix=19, vix_change_1d=-0.20)) is True

    def test_vol_crush_when_5d_drop(self):
        assert _is_vol_crush(self._row(vix=18, vix_change_5d=-0.30)) is True

    def test_not_vol_crush_in_normal_conditions(self):
        assert _is_vol_crush(self._row()) is False


# ---------------------------------------------------------------------------
# RegimeClassifier
# ---------------------------------------------------------------------------

class TestRegimeClassifier:

    def test_label_data_returns_series(self, market_data):
        clf = RegimeClassifier()
        labels = clf.label_data(market_data)
        assert isinstance(labels, pd.Series)
        assert len(labels) == len(market_data)

    def test_all_labels_valid(self, market_data):
        clf = RegimeClassifier()
        labels = clf.label_data(market_data)
        valid = {Regime.LOW_VOL, Regime.HIGH_VOL, Regime.CRASH, Regime.TRENDING}
        assert set(labels.unique()).issubset(valid)

    def test_train_and_predict(self, market_data):
        clf = RegimeClassifier()
        stats = clf.train(market_data, verbose=False)
        assert clf.is_trained is True
        assert stats["cv_accuracy"] > 0

        row = market_data.iloc[-1]
        pred = clf.predict(row)
        assert pred in Regime

    def test_predict_proba_sums_to_one(self, market_data):
        clf = RegimeClassifier()
        clf.train(market_data, verbose=False)
        probas = clf.predict_proba(market_data.iloc[-1])
        assert sum(probas.values()) == pytest.approx(1.0, abs=0.01)

    def test_predict_batch(self, market_data):
        clf = RegimeClassifier()
        clf.train(market_data, verbose=False)
        preds = clf.predict_batch(market_data)
        assert len(preds) == len(market_data)

    def test_untrained_uses_rules(self, market_data):
        clf = RegimeClassifier()
        assert clf.is_trained is False
        pred = clf.predict(market_data.iloc[100])
        assert pred in Regime


# ---------------------------------------------------------------------------
# FeatureExtractor
# ---------------------------------------------------------------------------

class TestFeatureExtractor:

    def test_extract_returns_dict(self, market_data):
        ext = FeatureExtractor(market_data)
        features = ext.extract(market_data.iloc[-1])
        assert features is not None
        assert isinstance(features, dict)

    def test_extract_has_all_feature_names(self, market_data):
        ext = FeatureExtractor(market_data)
        features = ext.extract(market_data.iloc[-1])
        for name in FeatureExtractor.FEATURE_NAMES:
            assert name in features, f"Missing feature: {name}"

    def test_extract_returns_none_on_missing_vix(self, market_data):
        ext = FeatureExtractor(market_data)
        row = market_data.iloc[-1].copy()
        row["vix"] = float("nan")
        assert ext.extract(row) is None

    def test_extract_returns_none_on_missing_nifty(self, market_data):
        ext = FeatureExtractor(market_data)
        row = market_data.iloc[-1].copy()
        row["nifty_close"] = float("nan")
        assert ext.extract(row) is None

    def test_extract_batch(self, market_data):
        ext = FeatureExtractor(market_data)
        dates = list(market_data.index[-5:])
        batch = ext.extract_batch(dates)
        assert len(batch) == 5
        assert set(FeatureExtractor.FEATURE_NAMES).issubset(batch.columns)


# ---------------------------------------------------------------------------
# _safe_float
# ---------------------------------------------------------------------------

class TestSafeFloat:

    def test_normal_value(self):
        assert _safe_float(3.14) == 3.14

    def test_nan_returns_default(self):
        assert _safe_float(float("nan")) == 0.0

    def test_inf_returns_default(self):
        assert _safe_float(float("inf"), default=-1.0) == -1.0

    def test_none_returns_default(self):
        assert _safe_float(None, default=5.0) == 5.0

    def test_string_returns_default(self):
        assert _safe_float("abc") == 0.0

    def test_integer_converted(self):
        assert _safe_float(42) == 42.0


# ---------------------------------------------------------------------------
# TradeLearner selection guardrails
# ---------------------------------------------------------------------------

class _DummyClassifier:
    def __init__(self, score: float):
        self.score = score
        self.classes_ = [0, 1]

    def predict_proba(self, X):
        return np.array([[1 - self.score, self.score]])


class _DummyRegressor:
    def __init__(self, value: float):
        self.value = value

    def predict(self, X):
        return np.array([self.value])


class _DummyFeatureExtractor:
    def extract(self, row):
        return {
            "vix_current": 24.0,
            "nifty_close": 24266.5,
        }


class TestTradeLearnerNoTrade:

    def _make_learner(self, quality_score: float, expected_return: float, strategy_returns: dict[str, float]):
        learner = TradeLearner()
        learner.is_trained = True
        learner.feature_extractor = _DummyFeatureExtractor()
        learner.selected_features = ["vix_current", "nifty_close"]
        learner.quality_classifier = _DummyClassifier(quality_score)
        learner.return_regressor = _DummyRegressor(expected_return)
        learner.per_strategy_regressors = {name: _DummyRegressor(val) for name, val in strategy_returns.items()}
        learner.strategy_stats = {name: {"trades": 10, "win_rate": 60, "total_pnl": 1, "avg_pnl": 1} for name in strategy_returns}
        return learner

    def test_negative_expected_value_returns_no_trade(self):
        learner = self._make_learner(
            quality_score=0.82,
            expected_return=-180.0,
            strategy_returns={"put_credit_spread": -150.0, "put_credit_wide": -120.0},
        )
        pred = learner.predict(pd.Series({"vix": 24.0, "nifty_close": 24266.5}), eligible_strategies=["put_credit_spread", "put_credit_wide"])
        assert pred["recommended_strategy"] is None
        assert pred["best_strategy"] is None
        assert pred["signal"] == "AVOID"
        assert pred["should_enter"] is False

    def test_positive_strategy_can_still_be_selected(self):
        learner = self._make_learner(
            quality_score=0.84,
            expected_return=12.0,
            strategy_returns={"put_credit_spread": -10.0, "put_credit_wide": 18.0},
        )
        pred = learner.predict(pd.Series({"vix": 24.0, "nifty_close": 24266.5}), eligible_strategies=["put_credit_spread", "put_credit_wide"])
        assert pred["recommended_strategy"] == "put_credit_wide"
        assert pred["best_strategy"] == "put_credit_wide"
        assert pred["should_enter"] is True

    def test_untrained_model_defaults_to_no_trade(self):
        learner = TradeLearner()
        learner.is_trained = False
        pred = learner.predict_strategy(pd.Series({"vix": 24.0, "nifty_close": 24266.5}))
        assert pred["strategy"] == "no_trade"

    def test_single_class_training_uses_safe_fallback(self, market_data):
        learner = TradeLearner()
        sample_dates = list(market_data.index[:8])
        trades = []
        for i, dt in enumerate(sample_dates):
            entry_date = dt.date() if hasattr(dt, "date") else dt
            exit_date = sample_dates[min(i + 1, len(sample_dates) - 1)]
            exit_date = exit_date.date() if hasattr(exit_date, "date") else exit_date
            trades.append(
                TradeResult(
                    signal_date=None,
                    entry_date=entry_date,
                    exit_date=exit_date,
                    strategy="put_credit_spread",
                    entry_spot=float(market_data.iloc[i]["nifty_close"]),
                    exit_spot=float(market_data.iloc[i]["nifty_close"]),
                    entry_vix=float(market_data.iloc[i]["vix"]),
                    exit_vix=float(market_data.iloc[i]["vix"]),
                    net_credit=10.0,
                    pnl_per_unit=-5.0,
                    total_pnl=-1000.0,
                    pnl_pct=-2.0,
                    exit_reason="test",
                    holding_days=1,
                    legs_detail="test",
                )
            )

        stats = learner.train(trades, market_data.iloc[:8], verbose=False)
        assert learner.is_trained is True
        # With percentile-based labels, even all-negative trades get a balanced
        # 3-class split (top third = class-2, middle = class-1, bottom = class-0).
        # num_quality_class0 = bottom third (the "poor" trades relative to peers).
        assert stats["num_quality_class0"] > 0, "At least some trades should be class-0"
        assert stats["num_quality_class2"] > 0, "Percentile split always produces class-2"
        # Total must equal number of trades
        total = stats["num_quality_class0"] + stats["num_quality_class1"] + stats["num_quality_class2"]
        assert total == len(trades)

        pred = learner.predict_strategy(market_data.iloc[0])
        assert pred["strategy"] == "no_trade"
