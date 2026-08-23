"""
Weekly Entry Learner — lightweight ML quality gate for short-DTE weekly options.

Architecture:
  1. Reuses FeatureExtractor from trade_learner for 64 market features
  2. Adds weekly-specific features (day-of-week, VIX momentum, expiry proximity)
  3. Trains a single GBM classifier with walk-forward validation (3 folds, 5-day purge)
  4. Predicts quality_score per candidate entry; gate at threshold (QUALITY_THRESHOLD=0.55)

Differences from monthly RegimeAwareLearner:
  - No per-regime models (weekly trades are too short for regime to matter much)
  - Shorter purge window (5 days vs 21)
  - Fewer walk-forward folds (3 vs 5)
  - Weekly-specific features always included (pinned, never dropped by scout)
  - class_weight='balanced' used on scout and fold models to handle class imbalance
  - Positive label hurdle raised to COST_HURDLE_PCT=15% (reduces majority-class bias)
"""

import math
from pathlib import Path
from typing import Optional

import joblib
import numpy as np
import pandas as pd

from models.cache_utils import ModelPeriodMetadata, metadata_from_state
from models.trade_learner import FeatureExtractor


WEEKLY_EXTRA_FEATURES = [
    "entry_weekday",
    "vix_1d_momentum",
    "vix_3d_momentum",
    "nifty_1d_return",
    "nifty_3d_return",
    "vix_intraday_range_proxy",
    "distance_to_monthly_expiry",
]


class WeeklyEntryLearner:
    """
    ML quality gate for weekly option entries.

    Trained on simulated weekly trades via WeeklyRollingSimulator.
    Predicts whether a given market condition will produce a profitable
    short-DTE trade (binary: profitable after costs = 1, else = 0).
    """

    QUALITY_THRESHOLD = 0.55
    COST_HURDLE_PCT = 15.0   # raised from 5% — tighter hurdle reduces majority-class dominance
    MAX_FEATURES = 25
    N_FOLDS = 3
    PURGE_DAYS = 5

    def __init__(self):
        self.quality_classifier = None
        self.feature_extractor: Optional[FeatureExtractor] = None
        self.selected_features: list[str] = []
        self.is_trained = False
        self.training_stats: dict = {}
        self.period_metadata: ModelPeriodMetadata | None = None

    def train(self, weekly_trades, market_data: pd.DataFrame,
              verbose: bool = True) -> dict:
        """
        Train the weekly quality gate.

        Args:
            weekly_trades: list of WeeklySimTrade from WeeklyRollingSimulator
            market_data: full market DataFrame (for feature extraction)
        """
        if len(weekly_trades) < 20:
            self.is_trained = False
            return {"error": f"Need at least 20 trades, got {len(weekly_trades)}"}

        self.feature_extractor = FeatureExtractor(market_data)

        X_rows = []
        y_returns = []

        for trade in weekly_trades:
            entry_ts = pd.Timestamp(trade.entry_date)
            idx = market_data.index.get_indexer([entry_ts], method="nearest")[0]
            row = market_data.iloc[idx]

            base_features = self.feature_extractor.extract(row)
            if base_features is None:
                continue

            weekly_features = self._extract_weekly_features(row, market_data, idx)
            all_features = {**base_features, **weekly_features}
            X_rows.append(all_features)
            y_returns.append(trade.pnl_pct)

        if len(X_rows) < 20:
            self.is_trained = False
            return {"error": f"Only {len(X_rows)} valid samples after feature extraction"}

        X_all = pd.DataFrame(X_rows).fillna(0).replace([float("inf"), float("-inf")], 0)
        y_return = np.array(y_returns)
        y_quality = (y_return > self.COST_HURDLE_PCT).astype(int)

        if verbose:
            n_pos = int(y_quality.sum())
            n_neg = len(y_quality) - n_pos
            print(f"  [Weekly ML] Training on {len(X_all)} samples ({n_pos} positive, {n_neg} negative)")

        from lightgbm import LGBMClassifier
        from sklearn.calibration import CalibratedClassifierCV
        from sklearn.metrics import roc_auc_score
        from sklearn.utils.class_weight import compute_sample_weight

        n_est = min(150, max(50, len(weekly_trades)))
        max_d = 4
        min_leaf = max(5, len(weekly_trades) // 20)

        # Use sample weights to correct for class imbalance in the scout pass.
        sample_weights = compute_sample_weight("balanced", y_quality)

        scout = LGBMClassifier(
            n_estimators=n_est, max_depth=3, learning_rate=0.08,
            num_leaves=7,  # tight on small weekly datasets (~500-2000 trades)
            min_child_samples=min_leaf, subsample=0.8, colsample_bytree=0.8,
            random_state=42, n_jobs=-1, verbosity=-1,
        )
        if len(set(y_quality)) > 1:
            scout.fit(X_all, y_quality, sample_weight=sample_weights)
            raw_imp = dict(zip(X_all.columns, scout.feature_importances_))
        else:
            raw_imp = {c: 0.0 for c in X_all.columns}

        # Pin all weekly-specific features — always include them regardless of scout rank.
        # Without pinning, their importance is diluted by the 64 base features and they get
        # dropped, leaving the model blind to the short-DTE context it was designed to use.
        pinned = [f for f in WEEKLY_EXTRA_FEATURES if f in X_all.columns]
        remaining_budget = self.MAX_FEATURES - len(pinned)
        sorted_feats = sorted(
            [f for f in raw_imp if f not in pinned],
            key=raw_imp.get, reverse=True,
        )
        self.selected_features = pinned + sorted_feats[:remaining_budget]
        X = X_all[self.selected_features]

        cv_aucs = []
        if len(set(y_quality)) > 1:
            fold_size = len(X) // (self.N_FOLDS + 1)
            for fold_i in range(self.N_FOLDS):
                train_end = fold_size * (fold_i + 2)
                test_start = min(train_end + self.PURGE_DAYS, len(X) - 1)
                test_end = min(test_start + fold_size, len(X))
                if test_end - test_start < 10:
                    continue

                X_tr, y_tr = X.iloc[:train_end], y_quality[:train_end]
                X_te, y_te = X.iloc[test_start:test_end], y_quality[test_start:test_end]

                if len(set(y_tr)) < 2 or len(set(y_te)) < 2:
                    continue

                fold_model = LGBMClassifier(
                    n_estimators=n_est, max_depth=max_d, learning_rate=0.05,
                    num_leaves=10, min_child_samples=min_leaf,
                    subsample=0.8, colsample_bytree=0.8, random_state=42,
                    n_jobs=-1, verbosity=-1,
                )
                fold_sw = compute_sample_weight("balanced", y_tr)
                fold_model.fit(X_tr, y_tr, sample_weight=fold_sw)
                try:
                    fold_auc = roc_auc_score(y_te, fold_model.predict_proba(X_te)[:, 1])
                    cv_aucs.append(fold_auc)
                    if verbose:
                        print(f"    Fold {fold_i + 1}: AUC={fold_auc:.3f}")
                except Exception:
                    pass

        cv_scores = np.array(cv_aucs) if cv_aucs else np.array([0.5])

        base_params = dict(
            n_estimators=n_est, max_depth=max_d, learning_rate=0.05,
            num_leaves=10, min_child_samples=min_leaf,
            subsample=0.8, colsample_bytree=0.8, random_state=42,
            n_jobs=-1, verbosity=-1,
        )

        final_sw = compute_sample_weight("balanced", y_quality)

        if len(set(y_quality)) > 1:
            try:
                from sklearn.model_selection import TimeSeriesSplit
                tscv = TimeSeriesSplit(n_splits=min(3, max(2, len(X) // 50)))
                self.quality_classifier = CalibratedClassifierCV(
                    LGBMClassifier(**base_params),
                    method="sigmoid", cv=tscv,
                )
                self.quality_classifier.fit(X, y_quality, sample_weight=final_sw)
            except Exception:
                gbm = LGBMClassifier(**base_params)
                gbm.fit(X, y_quality, sample_weight=final_sw)
                self.quality_classifier = gbm
        else:
            gbm = LGBMClassifier(**base_params)
            gbm.fit(X, y_quality, sample_weight=final_sw)
            self.quality_classifier = gbm

        feature_importance = {f: round(raw_imp.get(f, 0), 4) for f in self.selected_features}

        self.training_stats = {
            "num_trades": len(weekly_trades),
            "num_samples": len(X),
            "num_positive": int(y_quality.sum()),
            "num_negative": int(len(y_quality) - y_quality.sum()),
            "cv_auc": float(cv_scores.mean()),
            "cv_std": float(cv_scores.std()),
            "num_features": len(self.selected_features),
            "top_features": dict(list(feature_importance.items())[:10]),
        }

        self.is_trained = True
        if verbose:
            print(f"  [Weekly ML] Trained: AUC={cv_scores.mean():.3f} +/- {cv_scores.std():.3f}")
            print(f"  [Weekly ML] Features: {len(self.selected_features)}, "
                  f"Positive: {int(y_quality.sum())}/{len(y_quality)}")

        return self.training_stats

    def predict(self, row: pd.Series, market_data_idx: int = -1) -> float:
        """
        Predict quality score for a weekly entry candidate.

        Returns quality_score in [0, 1]. Higher = more likely to be profitable.
        Gate at QUALITY_THRESHOLD (0.55).
        """
        if not self.is_trained or self.quality_classifier is None:
            return 0.60

        base_features = self.feature_extractor.extract(row)
        if base_features is None:
            return 0.40

        weekly_features = self._extract_weekly_features(
            row, self.feature_extractor.data, market_data_idx,
        )
        all_features = {**base_features, **weekly_features}

        X = pd.DataFrame([all_features]).reindex(
            columns=self.selected_features, fill_value=0,
        ).fillna(0).replace([float("inf"), float("-inf")], 0)

        try:
            probs = self.quality_classifier.predict_proba(X)[0]
            classes = list(self.quality_classifier.classes_)
            return float(probs[classes.index(1)] if 1 in classes else 0.5)
        except Exception:
            return 0.50

    def _extract_weekly_features(self, row, market_data, idx) -> dict:
        """Extract features specific to short-DTE weekly trades."""
        current_date = row.name if hasattr(row, "name") else None

        weekday = current_date.weekday() if hasattr(current_date, "weekday") else 0
        if hasattr(current_date, "date"):
            weekday = current_date.date().weekday()

        vix = _sf(row.get("vix", 15))
        vix_1d = _sf(row.get("vix_change_1d", 0))
        nifty_1d = _sf(row.get("nifty_return_1d", 0))

        vix_3d = 0.0
        nifty_3d = 0.0
        range_proxy = 0.0

        if isinstance(idx, int) and idx >= 3 and market_data is not None and idx < len(market_data):
            try:
                vix_now = market_data.iloc[idx].get("vix", vix)
                vix_3ago = market_data.iloc[idx - 3].get("vix", vix)
                vix_3d = (vix_now - vix_3ago) / vix_3ago if vix_3ago > 0 else 0

                spot_now = market_data.iloc[idx].get("nifty_close", 0)
                spot_3ago = market_data.iloc[idx - 3].get("nifty_close", 0)
                nifty_3d = (spot_now - spot_3ago) / spot_3ago if spot_3ago > 0 else 0

                highs = [market_data.iloc[idx - j].get("nifty_high", 0) for j in range(3)]
                lows = [market_data.iloc[idx - j].get("nifty_low", 0) for j in range(3)]
                closes = [market_data.iloc[idx - j].get("nifty_close", 1) for j in range(3)]
                ranges = [(h - l) / c * 100 for h, l, c in zip(highs, lows, closes) if c > 0]
                range_proxy = sum(ranges) / len(ranges) if ranges else 0
            except Exception:
                pass

        monthly_expiry_dist = 15
        if hasattr(current_date, "date"):
            d = current_date.date()
        elif hasattr(current_date, "day"):
            d = current_date
        else:
            d = None
        if d is not None:
            import calendar
            y, m = d.year, d.month
            cal = calendar.monthcalendar(y, m)
            thursdays = [w[calendar.THURSDAY] for w in cal if w[calendar.THURSDAY] != 0]
            if thursdays:
                from datetime import date as dt_date
                monthly_exp = dt_date(y, m, max(thursdays))
                monthly_expiry_dist = abs((monthly_exp - d).days)

        return {
            "entry_weekday": weekday,
            "vix_1d_momentum": vix_1d,
            "vix_3d_momentum": vix_3d,
            "nifty_1d_return": nifty_1d,
            "nifty_3d_return": nifty_3d,
            "vix_intraday_range_proxy": range_proxy,
            "distance_to_monthly_expiry": monthly_expiry_dist,
        }

    def save(
        self,
        path: Path | str,
        *,
        period_metadata: ModelPeriodMetadata | None = None,
    ) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.period_metadata = period_metadata
        state = {
            "quality_classifier": self.quality_classifier,
            "selected_features": self.selected_features,
            "is_trained": self.is_trained,
            "training_stats": self.training_stats,
            "period_metadata": period_metadata.__dict__ if period_metadata else None,
        }
        joblib.dump(state, path)

    @classmethod
    def load(
        cls,
        market_data: pd.DataFrame,
        path: Path | str,
        *,
        expected_metadata: ModelPeriodMetadata | None = None,
        signal_date=None,
        require_period_metadata: bool = False,
    ) -> "WeeklyEntryLearner":
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Weekly entry model cache not found at {path}")
        state = joblib.load(path)
        period_metadata = metadata_from_state(state)
        if require_period_metadata and period_metadata is None:
            raise ValueError(f"Weekly entry cache at {path} is missing period metadata.")
        if expected_metadata is not None:
            if period_metadata is None:
                raise ValueError(f"Weekly entry cache at {path} cannot be verified against expected metadata.")
            period_metadata.assert_matches(expected_metadata)
        if signal_date is not None:
            if period_metadata is None:
                raise ValueError(f"Weekly entry cache at {path} cannot be proven out-of-sample for {signal_date}.")
            period_metadata.assert_usable_for(signal_date)
        learner = cls()
        learner.quality_classifier = state["quality_classifier"]
        learner.selected_features = state.get("selected_features", [])
        learner.is_trained = state.get("is_trained", False)
        learner.training_stats = state.get("training_stats", {})
        learner.feature_extractor = FeatureExtractor(market_data)
        learner.period_metadata = period_metadata
        return learner


def _sf(val, default=0.0) -> float:
    try:
        v = float(val)
        return default if math.isnan(v) or math.isinf(v) else v
    except (TypeError, ValueError):
        return default
