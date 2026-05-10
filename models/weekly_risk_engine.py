"""
Weekly Risk Engine — replaces the prediction-based WeeklyEntryLearner.

Philosophy: "Don't predict winners. Manage the losers."

Four integrated components:
  1. TailRiskScorer    — ML predicts P(disaster), scales position size down
  2. ConditionalGapModel — ETL = P(gap > strike) * loss_given_gap; skip if ETL > credit
  3. WeeklyRegimeClassifier — 4 market regimes, each with different params
  4. DynamicWeeklyExit — kill hold-to-expiry; exit on delta/IV/distance triggers

Usage:
  engine = WeeklyRiskEngine()
  engine.fit(market_data, simulated_trades)

  # At entry time:
  sizing = engine.compute_entry(row, spot, vix, short_strike, long_strike,
                                 entry_credit, dte, base_lots)
  if sizing.skip:
      return  # ETL > credit, or regime says skip
  lots = sizing.lots

  # During the trade (each day):
  should_exit, reason = engine.check_exit(trade, spot, vix, dte_rem, entry_data)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd

from pricing.black_scholes import price_option, iv_from_vix, OptionType
from models.cache_utils import ModelPeriodMetadata, metadata_from_state


# ═══════════════════════════════════════════════════════════════════════════════
#  Data classes
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class WeeklyEntrySizing:
    """Output of the risk engine at entry time."""
    skip: bool = False
    skip_reason: str = ""
    lots: int = 1
    regime: str = "unknown"
    risk_score: float = 0.0       # P(tail event) from ML
    risk_scale: float = 1.0       # 1 - risk_score
    etl: float = 0.0              # Expected Tail Loss
    credit_collected: float = 0.0
    regime_scale: float = 1.0
    spread_width_adj: int = 0     # regime-recommended spread width override


@dataclass
class WeeklyExitSignal:
    should_exit: bool = False
    reason: str = ""
    urgency: float = 0.0   # 0-1, higher = more urgent


# ═══════════════════════════════════════════════════════════════════════════════
#  1. Tail Risk Scorer — predict P(disaster), not P(winner)
# ═══════════════════════════════════════════════════════════════════════════════

class TailRiskScorer:
    """
    Predicts probability of a tail loss event (pnl < -100% of credit).
    Even a weak model (AUC 0.55-0.58) is valuable for sizing because:
      position_size = base_size * (1 - risk_score)
    A 0.3 risk score → 70% size. You don't need to be right, just directional.
    """

    TAIL_THRESHOLD_PCT = -100.0  # y=1 if pnl < -100% of credit (full loss)
    MAX_FEATURES = 20
    N_FOLDS = 3
    PURGE_DAYS = 5

    def __init__(self):
        self.classifier = None
        self.feature_names: list[str] = []
        self.is_trained = False
        self.training_stats: dict = {}

    def train(self, X: pd.DataFrame, y_pnl_pct: np.ndarray,
              verbose: bool = True) -> dict:
        """
        Train on feature matrix X and raw pnl_pct array.
        Target: y = 1 if pnl_pct < TAIL_THRESHOLD_PCT (a disaster).
        """
        from sklearn.ensemble import GradientBoostingClassifier
        from sklearn.metrics import roc_auc_score
        from sklearn.utils.class_weight import compute_sample_weight

        y = (y_pnl_pct < self.TAIL_THRESHOLD_PCT).astype(int)
        n_pos = int(y.sum())
        n_neg = len(y) - n_pos

        if n_pos < 10 or n_neg < 10:
            self.is_trained = False
            return {"error": f"Need >=10 of each class, got {n_pos} tail/{n_neg} normal"}

        if verbose:
            print(f"  [TailRisk] {len(X)} samples: {n_pos} tail events "
                  f"({n_pos/len(y)*100:.1f}%), {n_neg} normal")

        sw = compute_sample_weight("balanced", y)

        # Scout pass for feature selection
        scout = GradientBoostingClassifier(
            n_estimators=100, max_depth=3, learning_rate=0.08,
            min_samples_leaf=max(5, n_pos // 5), subsample=0.8, random_state=42,
        )
        scout.fit(X, y, sample_weight=sw)
        imp = dict(zip(X.columns, scout.feature_importances_))
        self.feature_names = sorted(imp, key=imp.get, reverse=True)[:self.MAX_FEATURES]
        X_sel = X[self.feature_names]

        # Walk-forward CV
        cv_aucs = []
        fold_size = len(X_sel) // (self.N_FOLDS + 1)
        for fold_i in range(self.N_FOLDS):
            tr_end = fold_size * (fold_i + 2)
            te_start = min(tr_end + self.PURGE_DAYS, len(X_sel) - 1)
            te_end = min(te_start + fold_size, len(X_sel))
            if te_end - te_start < 10:
                continue
            y_tr, y_te = y[:tr_end], y[te_start:te_end]
            if len(set(y_tr)) < 2 or len(set(y_te)) < 2:
                continue
            X_tr, X_te = X_sel.iloc[:tr_end], X_sel.iloc[te_start:te_end]
            sw_tr = compute_sample_weight("balanced", y_tr)
            m = GradientBoostingClassifier(
                n_estimators=120, max_depth=4, learning_rate=0.05,
                min_samples_leaf=max(5, n_pos // 5), subsample=0.8, random_state=42,
            )
            m.fit(X_tr, y_tr, sample_weight=sw_tr)
            try:
                auc = roc_auc_score(y_te, m.predict_proba(X_te)[:, 1])
                cv_aucs.append(auc)
                if verbose:
                    print(f"    Fold {fold_i+1}: AUC={auc:.3f}")
            except Exception:
                pass

        cv_scores = np.array(cv_aucs) if cv_aucs else np.array([0.5])

        # Final model
        from sklearn.calibration import CalibratedClassifierCV
        from sklearn.model_selection import TimeSeriesSplit
        sw_all = compute_sample_weight("balanced", y)
        try:
            tscv = TimeSeriesSplit(n_splits=min(3, max(2, len(X_sel) // 50)))
            self.classifier = CalibratedClassifierCV(
                GradientBoostingClassifier(
                    n_estimators=120, max_depth=4, learning_rate=0.05,
                    min_samples_leaf=max(5, n_pos // 5), subsample=0.8, random_state=42,
                ),
                method="sigmoid", cv=tscv,
            )
            self.classifier.fit(X_sel, y, sample_weight=sw_all)
        except Exception:
            gbm = GradientBoostingClassifier(
                n_estimators=120, max_depth=4, learning_rate=0.05,
                min_samples_leaf=max(5, n_pos // 5), subsample=0.8, random_state=42,
            )
            gbm.fit(X_sel, y, sample_weight=sw_all)
            self.classifier = gbm

        self.is_trained = True
        self.training_stats = {
            "n_samples": len(X), "n_tail": n_pos, "n_normal": n_neg,
            "tail_rate": round(n_pos / len(y) * 100, 1),
            "cv_auc": round(float(cv_scores.mean()), 4),
            "cv_std": round(float(cv_scores.std()), 4),
            "n_features": len(self.feature_names),
            "top_features": {f: round(imp.get(f, 0), 4) for f in self.feature_names[:10]},
        }
        if verbose:
            print(f"  [TailRisk] AUC={cv_scores.mean():.3f} ± {cv_scores.std():.3f}")
        return self.training_stats

    def predict_risk(self, features: dict) -> float:
        """Returns P(tail event) in [0, 1]. Higher = more dangerous."""
        if not self.is_trained or self.classifier is None:
            return 0.15  # conservative default
        X = pd.DataFrame([features]).reindex(
            columns=self.feature_names, fill_value=0,
        ).fillna(0).replace([float("inf"), float("-inf")], 0)
        try:
            probs = self.classifier.predict_proba(X)[0]
            classes = list(self.classifier.classes_)
            return float(probs[classes.index(1)] if 1 in classes else 0.15)
        except Exception:
            return 0.15


# ═══════════════════════════════════════════════════════════════════════════════
#  2. Conditional Gap Model — ETL = P(gap > strike) * loss_given_gap
# ═══════════════════════════════════════════════════════════════════════════════

class ConditionalGapModel:
    """
    Computes Expected Tail Loss conditioned on current market state.
    Not a raw historical average — conditioned on:
      - VIX percentile (not absolute VIX)
      - Day of week (Monday gaps > Wednesday gaps)
      - Event proximity (from production_rules.EventCalendar)

    Decision rule: skip trade if ETL > credit_collected.
    """

    def __init__(self):
        self._gap_series: Optional[pd.Series] = None
        self._vix_series: Optional[pd.Series] = None
        self._vix_percentiles: Optional[pd.Series] = None
        self._weekday_series: Optional[pd.Series] = None
        self._gap_by_vix_bucket: dict[str, np.ndarray] = {}
        self._gap_by_weekday: dict[int, np.ndarray] = {}

    def fit(self, data: pd.DataFrame) -> None:
        """Fit conditional gap distributions from historical OHLCV data."""
        close_prev = data["nifty_close"].shift(1)
        gaps = ((data["nifty_open"] / close_prev) - 1.0) * 100.0
        gaps = gaps.dropna().replace([np.inf, -np.inf], np.nan).dropna()
        self._gap_series = gaps

        if "vix" in data.columns:
            vix = data["vix"].reindex(gaps.index)
            vix_50 = vix.rolling(252, min_periods=50).median()
            self._vix_percentiles = vix.rank(pct=True)

            # Bucket by VIX percentile
            for label, lo, hi in [("low", 0, 0.33), ("mid", 0.33, 0.66), ("high", 0.66, 1.01)]:
                mask = (self._vix_percentiles >= lo) & (self._vix_percentiles < hi)
                bucket_gaps = gaps[mask].values
                if len(bucket_gaps) > 20:
                    self._gap_by_vix_bucket[label] = bucket_gaps

        # By weekday
        weekdays = gaps.index.weekday if hasattr(gaps.index, "weekday") else pd.Series(
            [d.weekday() for d in gaps.index], index=gaps.index,
        )
        for wd in range(5):
            wd_gaps = gaps[weekdays == wd].values
            if len(wd_gaps) > 20:
                self._gap_by_weekday[wd] = wd_gaps

    def expected_tail_loss(
        self,
        spot: float,
        short_strike: float,
        entry_credit: float,
        spread_width: float,
        vix: float,
        vix_percentile: Optional[float] = None,
        weekday: int = 0,
    ) -> float:
        """
        ETL = P(gap breaches short strike) * E[loss | breach]

        For a put credit spread: breach when spot gaps below short_strike.
        The loss given breach ≈ spread_width (capped at max loss).
        """
        distance_pct = abs(spot - short_strike) / spot * 100.0 if spot > 0 else 5.0

        # Select conditional gap distribution
        if vix_percentile is not None and self._gap_by_vix_bucket:
            if vix_percentile < 0.33:
                gap_dist = self._gap_by_vix_bucket.get("low", self._gap_series.values)
            elif vix_percentile < 0.66:
                gap_dist = self._gap_by_vix_bucket.get("mid", self._gap_series.values)
            else:
                gap_dist = self._gap_by_vix_bucket.get("high", self._gap_series.values)
        elif self._gap_series is not None:
            gap_dist = self._gap_series.values
        else:
            return 0.0

        # Blend with weekday distribution if available
        if weekday in self._gap_by_weekday:
            wd_gaps = self._gap_by_weekday[weekday]
            gap_dist = np.concatenate([gap_dist, wd_gaps])

        # P(gap exceeds distance to short strike)
        # For PCS: dangerous = gap down > distance_pct
        breach_gaps = gap_dist[gap_dist < -distance_pct]
        p_breach = len(breach_gaps) / len(gap_dist) if len(gap_dist) > 0 else 0.0

        if p_breach == 0:
            return 0.0

        # E[loss | breach] — the average overshoot beyond the strike, capped at spread width
        avg_overshoot_pct = abs(np.mean(breach_gaps)) - distance_pct
        loss_given_breach = min(avg_overshoot_pct / 100.0 * spot, spread_width)
        loss_given_breach = max(loss_given_breach, spread_width * 0.5)

        return p_breach * loss_given_breach

    def current_vix_percentile(self, vix: float) -> float:
        """Where does current VIX sit in the historical distribution?"""
        if self._vix_percentiles is not None and len(self._vix_percentiles) > 0:
            return float((self._vix_percentiles < vix / 100).mean())
        if vix < 13:
            return 0.2
        elif vix < 16:
            return 0.4
        elif vix < 20:
            return 0.6
        elif vix < 25:
            return 0.8
        return 0.95


# ═══════════════════════════════════════════════════════════════════════════════
#  3. Weekly Regime Classifier — not ML, just clustering
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class RegimeParams:
    """Per-regime trading parameters."""
    name: str
    lot_scale: float        # multiplier on base lots
    spread_width: int       # recommended spread width (points)
    profit_target_pct: float
    skip: bool = False      # skip entry entirely in this regime
    description: str = ""


REGIME_CONFIGS = {
    "low_vol_grind": RegimeParams(
        name="low_vol_grind", lot_scale=1.0, spread_width=400,
        profit_target_pct=50.0,
        description="VIX < P33, low RV, positive drift — theta farm",
    ),
    "pre_event_compression": RegimeParams(
        name="pre_event_compression", lot_scale=0.5, spread_width=300,
        profit_target_pct=40.0,
        description="Low RV but VIX elevated — vol is coiled, skip or reduce",
    ),
    "post_event_expansion": RegimeParams(
        name="post_event_expansion", lot_scale=0.6, spread_width=500,
        profit_target_pct=60.0,
        description="RV spiked, VIX elevated — wider spreads, smaller size",
    ),
    "trend_week": RegimeParams(
        name="trend_week", lot_scale=0.3, spread_width=500,
        profit_target_pct=30.0,
        description="Strong directional drift (|ADX| high, slope steep) — "
                    "minimum size, early exit bias",
    ),
}


class WeeklyRegimeClassifier:
    """
    Classifies current week into one of 4 regimes using simple indicators.
    No ML — just VIX percentile, realized vol, and trend strength.
    """

    def __init__(self):
        self._vix_median_252: float = 15.0
        self._rv_median_252: float = 12.0

    def fit(self, data: pd.DataFrame) -> None:
        if "vix" in data.columns:
            self._vix_median_252 = float(data["vix"].median())
        if "nifty_realized_vol_10d" in data.columns:
            self._rv_median_252 = float(data["nifty_realized_vol_10d"].median())

    def classify(self, row: pd.Series) -> RegimeParams:
        vix = _sf(row.get("vix", 15))
        rv_10d = _sf(row.get("nifty_realized_vol_10d", 12))
        rv_20d = _sf(row.get("nifty_realized_vol_20d", 12))
        ret_5d = _sf(row.get("nifty_return_5d", 0))
        rsi = _sf(row.get("nifty_rsi_14", 50))

        vix_ratio = vix / self._vix_median_252 if self._vix_median_252 > 0 else 1.0
        rv_ratio = rv_10d / self._rv_median_252 if self._rv_median_252 > 0 else 1.0

        # Trend detection: strong 5d move + RSI at extremes
        trend_strength = abs(ret_5d) * 100
        is_trending = trend_strength > 3.0 or rsi < 30 or rsi > 70

        # Pre-event compression: VIX elevated but RV is low (vol is coiled)
        if vix_ratio > 1.2 and rv_ratio < 0.9:
            return REGIME_CONFIGS["pre_event_compression"]

        # Post-event expansion: RV spiked
        if rv_ratio > 1.4:
            return REGIME_CONFIGS["post_event_expansion"]

        # Trend week
        if is_trending:
            return REGIME_CONFIGS["trend_week"]

        # Default: low vol grind
        return REGIME_CONFIGS["low_vol_grind"]


# ═══════════════════════════════════════════════════════════════════════════════
#  4. Dynamic Weekly Exit — kill hold-to-expiry
# ═══════════════════════════════════════════════════════════════════════════════

class DynamicWeeklyExit:
    """
    Converts bimodal P&L distribution into a more continuous one by exiting
    BEFORE the catastrophe happens. Rules:

    1. Take profit at 50-70% of max credit (regime-dependent)
    2. Exit if net delta doubles from entry
    3. Exit if VIX expands > 25% intraday (IV spike)
    4. Exit if underlying breaches 50% of distance to short strike
    """

    def check(
        self,
        spot: float,
        vix: float,
        entry_spot: float,
        entry_vix: float,
        entry_credit: float,
        short_strike: float,
        long_strike: float,
        option_type: OptionType,
        dte_remaining: int,
        current_pnl_per_unit: float,
        entry_delta: float,
        current_delta: float,
        profit_target_pct: float = 50.0,
    ) -> WeeklyExitSignal:
        """
        Check all dynamic exit conditions. Returns first trigger hit.
        """
        pnl_pct = (current_pnl_per_unit / entry_credit * 100) if entry_credit > 0 else 0

        # 1. Profit target (regime-adaptive, default 50%)
        if pnl_pct >= profit_target_pct:
            return WeeklyExitSignal(
                should_exit=True, reason="profit_target",
                urgency=0.8,
            )

        # 2. Delta doubling — position risk has grown materially
        if entry_delta != 0 and abs(current_delta) > abs(entry_delta) * 2.0:
            return WeeklyExitSignal(
                should_exit=True, reason="delta_doubled",
                urgency=0.9,
            )

        # 3. IV expansion spike — VIX jumped > 25% from entry
        if entry_vix > 0:
            vix_expansion = (vix - entry_vix) / entry_vix
            if vix_expansion > 0.25 and pnl_pct < 10:
                return WeeklyExitSignal(
                    should_exit=True, reason="iv_spike",
                    urgency=0.85,
                )

        # 4. Underlying breaches 50-60% of distance to short strike
        if option_type in (OptionType.PUT, "PE", "PUT"):
            distance = entry_spot - short_strike
            if distance > 0:
                breach_pct = (entry_spot - spot) / distance
                if breach_pct >= 0.50:
                    return WeeklyExitSignal(
                        should_exit=True, reason="distance_breach_50pct",
                        urgency=0.7 + breach_pct * 0.3,
                    )
        elif option_type in (OptionType.CALL, "CE", "CALL"):
            distance = short_strike - entry_spot
            if distance > 0:
                breach_pct = (spot - entry_spot) / distance
                if breach_pct >= 0.50:
                    return WeeklyExitSignal(
                        should_exit=True, reason="distance_breach_50pct",
                        urgency=0.7 + breach_pct * 0.3,
                    )

        # 5. Time decay acceleration: if DTE <= 1 and losing, don't gamble on expiry
        if dte_remaining <= 1 and pnl_pct < -10:
            return WeeklyExitSignal(
                should_exit=True, reason="dte_losing_exit",
                urgency=0.6,
            )

        return WeeklyExitSignal(should_exit=False)


# ═══════════════════════════════════════════════════════════════════════════════
#  Orchestrator — brings all 4 components together
# ═══════════════════════════════════════════════════════════════════════════════

class WeeklyRiskEngine:
    """
    Single entry point for the weekly risk system.

    Replaces WeeklyEntryLearner. Instead of predicting winners:
      - Predicts disaster probability → scales size
      - Computes ETL → rejects unprofitable risk
      - Classifies regime → adjusts params
      - Checks dynamic exits → kills hold-to-expiry
    """

    def __init__(self):
        self.tail_scorer = TailRiskScorer()
        self.gap_model = ConditionalGapModel()
        self.regime_classifier = WeeklyRegimeClassifier()
        self.exit_engine = DynamicWeeklyExit()
        self.is_fitted = False
        self.feature_extractor = None
        self.period_metadata: ModelPeriodMetadata | None = None

    def fit(self, data: pd.DataFrame, trades, verbose: bool = True) -> dict:
        """
        Fit all components from market data + simulated trades.
        """
        from models.trade_learner import FeatureExtractor

        self.feature_extractor = FeatureExtractor(data)
        self.gap_model.fit(data)
        self.regime_classifier.fit(data)

        # Build feature matrix for tail risk scorer
        X_rows, y_pnl = [], []
        for trade in trades:
            entry_ts = pd.Timestamp(trade.entry_date)
            idx = data.index.get_indexer([entry_ts], method="nearest")[0]
            row = data.iloc[idx]
            base = self.feature_extractor.extract(row)
            if base is None:
                continue
            extra = {
                "entry_weekday": row.name.weekday() if hasattr(row.name, "weekday") else 0,
                "overnight_gap_abs": _sf(row.get("overnight_gap_abs", 0)),
                "gap_3d_max_abs": _sf(row.get("gap_3d_max_abs", 0)),
                "gap_5d_max_abs": _sf(row.get("gap_5d_max_abs", 0)),
            }
            X_rows.append({**base, **extra})
            y_pnl.append(trade.pnl_pct)

        if len(X_rows) < 50:
            if verbose:
                print(f"  [WeeklyRiskEngine] Insufficient data ({len(X_rows)} samples)")
            return {"error": "insufficient data"}

        X = pd.DataFrame(X_rows).fillna(0).replace([float("inf"), float("-inf")], 0)
        y = np.array(y_pnl)

        if verbose:
            print(f"\n  [WeeklyRiskEngine] Fitting on {len(X)} trades...")
        tail_stats = self.tail_scorer.train(X, y, verbose=verbose)

        self.is_fitted = True
        stats = {
            "tail_risk": tail_stats,
            "gap_model": {"fitted": True, "n_gaps": len(self.gap_model._gap_series) if self.gap_model._gap_series is not None else 0},
            "regime_classifier": {"vix_median": self.regime_classifier._vix_median_252},
        }
        if verbose:
            regime_names = list(REGIME_CONFIGS.keys())
            print(f"  [WeeklyRiskEngine] Regimes: {regime_names}")
        return stats

    def compute_entry(
        self,
        row: pd.Series,
        spot: float,
        vix: float,
        short_strike: float,
        long_strike: float,
        entry_credit: float,
        dte: int,
        base_lots: int,
        option_type: OptionType = OptionType.PUT,
    ) -> WeeklyEntrySizing:
        """
        Compute risk-adjusted entry sizing. Called before creating the trade.
        """
        spread_width = abs(short_strike - long_strike)

        # ── Regime classification ──
        regime = self.regime_classifier.classify(row)
        if regime.skip:
            return WeeklyEntrySizing(skip=True, skip_reason=f"regime:{regime.name}",
                                     regime=regime.name)

        # ── Expected Tail Loss ──
        vix_pctile = self.gap_model.current_vix_percentile(vix)
        weekday = row.name.weekday() if hasattr(row.name, "weekday") else 0
        etl = self.gap_model.expected_tail_loss(
            spot, short_strike, entry_credit, spread_width,
            vix, vix_pctile, weekday,
        )

        if entry_credit > 0 and etl > entry_credit:
            return WeeklyEntrySizing(
                skip=True, skip_reason=f"etl:{etl:.1f} > credit:{entry_credit:.1f}",
                regime=regime.name, etl=etl, credit_collected=entry_credit,
            )

        # ── ML tail risk score ──
        risk_score = 0.15
        if self.is_fitted and self.feature_extractor is not None:
            base = self.feature_extractor.extract(row)
            if base is not None:
                extra = {
                    "entry_weekday": weekday,
                    "overnight_gap_abs": _sf(row.get("overnight_gap_abs", 0)),
                    "gap_3d_max_abs": _sf(row.get("gap_3d_max_abs", 0)),
                    "gap_5d_max_abs": _sf(row.get("gap_5d_max_abs", 0)),
                }
                risk_score = self.tail_scorer.predict_risk({**base, **extra})

        risk_scale = max(0.2, 1.0 - risk_score)
        regime_scale = regime.lot_scale

        lots = max(1, int(base_lots * risk_scale * regime_scale))

        return WeeklyEntrySizing(
            skip=False, lots=lots, regime=regime.name,
            risk_score=risk_score, risk_scale=risk_scale,
            etl=etl, credit_collected=entry_credit,
            regime_scale=regime_scale,
            spread_width_adj=regime.spread_width,
        )

    def check_exit(
        self,
        spot: float,
        vix: float,
        entry_spot: float,
        entry_vix: float,
        entry_credit: float,
        short_strike: float,
        long_strike: float,
        option_type: OptionType,
        dte_remaining: int,
        current_pnl_per_unit: float,
        entry_delta: float,
        current_delta: float,
        regime_name: str = "low_vol_grind",
    ) -> WeeklyExitSignal:
        """Check dynamic exit rules. Called each day during the trade."""
        regime = REGIME_CONFIGS.get(regime_name, REGIME_CONFIGS["low_vol_grind"])
        return self.exit_engine.check(
            spot, vix, entry_spot, entry_vix, entry_credit,
            short_strike, long_strike, option_type,
            dte_remaining, current_pnl_per_unit,
            entry_delta, current_delta,
            profit_target_pct=regime.profit_target_pct,
        )


# ═══════════════════════════════════════════════════════════════════════════════
#  Persistence (mirrors WeeklyEntryLearner.save/load)
# ═══════════════════════════════════════════════════════════════════════════════

_CACHE_DIR = None

def _get_cache_dir():
    global _CACHE_DIR
    if _CACHE_DIR is None:
        from pathlib import Path
        _CACHE_DIR = Path(__file__).parent.parent / "data" / ".cache"
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _CACHE_DIR

RISK_ENGINE_CACHE = "weekly_risk_engine_v2.pkl"


def save_risk_engine(
    engine: WeeklyRiskEngine,
    *,
    path=None,
    period_metadata: ModelPeriodMetadata | None = None,
) -> None:
    import joblib, datetime
    path = path or (_get_cache_dir() / RISK_ENGINE_CACHE)
    state = {
        "_saved_at": datetime.datetime.now().isoformat(),
        "tail_classifier": engine.tail_scorer.classifier,
        "tail_feature_names": engine.tail_scorer.feature_names,
        "tail_training_stats": engine.tail_scorer.training_stats,
        "tail_is_trained": engine.tail_scorer.is_trained,
        "regime_vix_median": engine.regime_classifier._vix_median_252,
        "regime_rv_median": engine.regime_classifier._rv_median_252,
        "period_metadata": period_metadata.__dict__ if period_metadata else None,
    }
    joblib.dump(state, path)


def load_risk_engine(
    market_data: pd.DataFrame,
    *,
    path=None,
    expected_metadata: ModelPeriodMetadata | None = None,
    signal_date: date | None = None,
    require_period_metadata: bool = False,
) -> WeeklyRiskEngine:
    import joblib
    from models.trade_learner import FeatureExtractor
    path = path or (_get_cache_dir() / RISK_ENGINE_CACHE)
    if not path.exists():
        raise FileNotFoundError(f"No risk engine cache at {path}")
    state = joblib.load(path)
    period_metadata = metadata_from_state(state)
    if require_period_metadata and period_metadata is None:
        raise ValueError(f"Weekly risk engine cache at {path} is missing period metadata.")
    if expected_metadata is not None:
        if period_metadata is None:
            raise ValueError(f"Weekly risk engine cache at {path} cannot be verified against expected metadata.")
        period_metadata.assert_matches(expected_metadata)
    if signal_date is not None:
        if period_metadata is None:
            raise ValueError(f"Weekly risk engine cache at {path} cannot be proven out-of-sample for {signal_date}.")
        period_metadata.assert_usable_for(signal_date)
    engine = WeeklyRiskEngine()
    engine.tail_scorer.classifier = state["tail_classifier"]
    engine.tail_scorer.feature_names = state["tail_feature_names"]
    engine.tail_scorer.training_stats = state["tail_training_stats"]
    engine.tail_scorer.is_trained = state["tail_is_trained"]
    engine.regime_classifier._vix_median_252 = state["regime_vix_median"]
    engine.regime_classifier._rv_median_252 = state["regime_rv_median"]
    engine.feature_extractor = FeatureExtractor(market_data)
    engine.gap_model.fit(market_data)
    engine.is_fitted = True
    engine.period_metadata = period_metadata
    return engine


def risk_engine_cache_age_days() -> Optional[int]:
    import joblib, datetime
    path = _get_cache_dir() / RISK_ENGINE_CACHE
    if not path.exists():
        return None
    try:
        state = joblib.load(path)
        saved = datetime.datetime.fromisoformat(state["_saved_at"])
        return (datetime.datetime.now() - saved).days
    except Exception:
        return None


def _sf(val, default=0.0) -> float:
    try:
        v = float(val)
        return default if math.isnan(v) or math.isinf(v) else v
    except (TypeError, ValueError):
        return default
