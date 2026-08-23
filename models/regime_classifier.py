"""
Regime Classifier: Labels each trading day into one of 4 regimes.

Regimes:
  LOW_VOL   — VIX < 15 OR post-vol-crush (VIX falling rapidly from highs)
  HIGH_VOL  — VIX 15-22, elevated AND stable/rising vol, choppy/range-bound
  CRASH     — VIX > 22 + drawdown + vol expansion (crisis mode)
  TRENDING  — Strong directional move (up or down), momentum-driven;
              also covers post-crash recovery with VIX mean reversion

Each regime has fundamentally different option premium dynamics:
  LOW_VOL:  Premiums thin → need wider spreads, theta-heavy strategies
  HIGH_VOL: Fat premiums → credit spreads thrive, but watch for blowups
  CRASH:    Premiums explode → only enter with extreme caution or skip
  TRENDING: Directional bias strong → trend-following overlays work

IMPORTANT: VIX *direction* matters as much as VIX *level*. A VIX of 19.6
falling from 25 is NOT the same as VIX of 19.6 rising from 14. The former
is a vol crush (premiums deflating, fear receding → TRENDING/LOW_VOL),
while the latter is genuine high-vol buildup.

The classifier uses a combination of rule-based labels (for ground truth)
and an ML model (for smoother transitions and forward prediction).
"""

import warnings

import numpy as np
import pandas as pd
from enum import IntEnum
from lightgbm import LGBMClassifier
from sklearn.model_selection import TimeSeriesSplit, cross_val_score


class Regime(IntEnum):
    LOW_VOL = 0
    HIGH_VOL = 1
    CRASH = 2
    TRENDING = 3


REGIME_NAMES = {
    Regime.LOW_VOL: "LOW_VOL",
    Regime.HIGH_VOL: "HIGH_VOL",
    Regime.CRASH: "CRASH",
    Regime.TRENDING: "TRENDING",
}

REGIME_FEATURES = [
    "vix",
    "vix_vs_sma_ratio",
    "vix_change_1d",
    "vix_change_5d",
    "nifty_realized_vol_10d",
    "nifty_realized_vol_20d",
    "nifty_bb_width",
    "nifty_drawdown_from_20d_high_pct",
    "nifty_drawdown_from_50d_high_pct",
    "nifty_rsi_14",
    "nifty_return_20d",
    "nifty_return_5d",
    "vol_expansion_ratio",
    "crash_risk_score",
    "crash_risk_score_v2",
    "multi_asset_stress",
    "nifty_consec_down_days",
    "vix_accel_3d_pct",
]


def _is_vol_crush(row: pd.Series) -> bool:
    """
    Detect post-volatility-crush / mean reversion phase.

    This is when VIX has dropped DRAMATICALLY from recent highs — premiums
    are deflating fast, fear is receding rapidly. Only triggers for clear,
    unambiguous vol crushes (not normal day-to-day VIX fluctuations).

    Key principle: we want HIGH precision here. Better to miss a borderline
    case than to reclassify a genuine high-vol day.

    Requires VIX to be below 23 (not in crisis territory) AND at least one:
      - VIX is 22%+ below its 10d SMA (vix_vs_sma_ratio < 0.78)
      - VIX dropped >18% in 1 day
      - VIX dropped >25% in 5 days
    """
    vix = row.get("vix", 15)
    if pd.isna(vix):
        return False
    if vix >= 23:
        return False

    vix_vs_sma = row.get("vix_vs_sma_ratio", 1.0)
    vix_chg_1d = row.get("vix_change_1d", 0)
    vix_chg_5d = row.get("vix_change_5d", 0)

    if pd.isna(vix_vs_sma):
        vix_vs_sma = 1.0
    if pd.isna(vix_chg_1d):
        vix_chg_1d = 0
    if pd.isna(vix_chg_5d):
        vix_chg_5d = 0

    if vix_vs_sma < 0.78:
        return True
    if vix_chg_1d < -0.18:
        return True
    if vix_chg_5d < -0.25:
        return True
    return False


def label_regime_rules(row: pd.Series) -> int:
    """
    Rule-based regime labeling — used as ground truth for ML training.

    NOTE: This does NOT include vol crush detection. Training labels use
    the classic VIX-level-based rules which have proven historical accuracy.
    Vol crush correction is applied only at prediction time (see
    _apply_vol_crush_override) to fix misclassifications on live data
    without disturbing the proven training distribution.
    """
    vix = row.get("vix", 15)
    rvol_20 = row.get("nifty_realized_vol_20d", 12)
    dd_20 = row.get("nifty_drawdown_from_20d_high_pct", 0)
    dd_50 = row.get("nifty_drawdown_from_50d_high_pct", 0)
    rsi = row.get("nifty_rsi_14", 50)
    ret_20d = row.get("nifty_return_20d", 0)
    consec_down = row.get("nifty_consec_down_days", 0)
    crash_v2 = row.get("crash_risk_score_v2", 0)

    if pd.isna(vix):
        vix = 15

    # CRASH: extreme fear + damage already happening
    if vix > 25 and dd_20 < -5:
        return Regime.CRASH
    if vix > 22 and rvol_20 > 20 and dd_20 < -3:
        return Regime.CRASH
    if crash_v2 > 0.5 and dd_20 < -3:
        return Regime.CRASH
    if consec_down >= 4 and vix > 20:
        return Regime.CRASH

    # TRENDING: strong sustained directional move
    if not pd.isna(ret_20d):
        if ret_20d > 0.05 and rsi > 60:
            return Regime.TRENDING
        if ret_20d < -0.05 and rsi < 40 and dd_20 > -5:
            return Regime.TRENDING

    # LOW_VOL: calm, low fear
    if vix < 15 and rvol_20 < 14:
        return Regime.LOW_VOL

    # HIGH_VOL: everything else (elevated but not crisis)
    return Regime.HIGH_VOL


class RegimeClassifier:
    """
    ML-backed regime classifier with rule-based fallback.

    Training: uses rule-based labels as ground truth, trains GBM for
    smoother boundaries and forward-looking regime prediction.
    """

    def __init__(self):
        self.model = None
        self.is_trained = False
        self.training_stats = {}
        self.feature_cols = REGIME_FEATURES

    def label_data(self, data: pd.DataFrame) -> pd.Series:
        """Apply rule-based labels to entire dataset."""
        return data.apply(label_regime_rules, axis=1)

    def train(self, data: pd.DataFrame, verbose: bool = True) -> dict:
        labels = self.label_data(data)

        X = data[self.feature_cols].copy()
        X = X.fillna(0).replace([np.inf, -np.inf], 0)
        y = labels.values

        n_classes = len(set(y))
        if n_classes < 2:
            if verbose:
                print(f"  [Regime] Only {n_classes} class found — using rule-based only")
            self.is_trained = False
            return {"status": "rules_only", "n_classes": n_classes}

        self.model = LGBMClassifier(
            n_estimators=150, max_depth=4, learning_rate=0.1,
            num_leaves=15,  # < 2^4=16; keeps regime boundaries clean
            subsample=0.8, colsample_bytree=0.8, random_state=42,
            n_jobs=-1, verbosity=-1,
        )

        n_cv = min(5, max(2, len(data) // 200))
        tscv = TimeSeriesSplit(n_splits=n_cv)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            cv_scores = cross_val_score(
                self.model, X, y, cv=tscv,
                scoring="accuracy", error_score=0.0,
            )
        self.model.fit(X, y)
        self.is_trained = True

        regime_counts = pd.Series(y).value_counts().to_dict()
        regime_pcts = {REGIME_NAMES.get(Regime(k), str(k)): f"{v/len(y):.0%}" for k, v in regime_counts.items()}

        self.training_stats = {
            "cv_accuracy": float(cv_scores.mean()),
            "cv_std": float(cv_scores.std()),
            "n_samples": len(y),
            "regime_distribution": regime_pcts,
            "feature_importance": dict(
                sorted(
                    zip(self.feature_cols, self.model.feature_importances_),
                    key=lambda x: x[1], reverse=True,
                )[:10]
            ),
        }

        if verbose:
            print(f"  [Regime] Classifier trained: CV accuracy={cv_scores.mean():.1%} +/- {cv_scores.std():.1%}")
            print(f"  [Regime] Distribution: {regime_pcts}")

        return self.training_stats

    def _apply_vol_crush_override(self, row: pd.Series, pred: Regime) -> Regime:
        """
        Hard override: if VIX is in vol crush, never classify as HIGH_VOL or CRASH.

        The ML model can lag on regime transitions because backward-looking
        features (realized vol, BB width) still reflect the old high-vol period.
        This override uses forward-looking VIX direction to correct that.

        Always reclassifies to TRENDING: vol crush means premiums are still
        decent but deflating — this is a transitional state, not calm (LOW_VOL)
        and not sustained high vol (HIGH_VOL).
        """
        if pred not in (Regime.HIGH_VOL, Regime.CRASH):
            return pred

        if not _is_vol_crush(row):
            return pred

        return Regime.TRENDING

    def predict(self, row: pd.Series) -> Regime:
        """Predict regime for a single row. Falls back to rules if ML unavailable."""
        if not self.is_trained:
            return Regime(label_regime_rules(row))

        features = {}
        for col in self.feature_cols:
            v = row.get(col, 0)
            features[col] = float(v) if pd.notna(v) else 0.0

        X = pd.DataFrame([features])
        X = X.fillna(0).replace([np.inf, -np.inf], 0)
        pred = Regime(self.model.predict(X)[0])
        return self._apply_vol_crush_override(row, pred)

    def predict_proba(self, row: pd.Series) -> dict:
        """Return probability distribution over regimes."""
        if not self.is_trained:
            r = label_regime_rules(row)
            return {Regime(r): 1.0}

        features = {}
        for col in self.feature_cols:
            v = row.get(col, 0)
            features[col] = float(v) if pd.notna(v) else 0.0

        X = pd.DataFrame([features])
        X = X.fillna(0).replace([np.inf, -np.inf], 0)
        probas = self.model.predict_proba(X)[0]
        classes = self.model.classes_
        result = {Regime(c): float(p) for c, p in zip(classes, probas)}

        ml_pred = Regime(classes[np.argmax(probas)])
        corrected = self._apply_vol_crush_override(row, ml_pred)
        if corrected != ml_pred:
            result = {r: 0.0 for r in result}
            result[corrected] = 1.0
        return result

    def predict_batch(self, data: pd.DataFrame) -> pd.Series:
        """Predict regimes for entire dataframe."""
        if not self.is_trained:
            return self.label_data(data)

        X = data[self.feature_cols].copy()
        X = X.fillna(0).replace([np.inf, -np.inf], 0)
        preds = self.model.predict(X)
        return pd.Series(preds, index=data.index)
