"""
ML model that learns from multi-strategy backtests to predict:
1. WHEN to trade (entry timing)
2. WHICH strategy to use (regime-adaptive selection)
3. HOW MUCH to expect (P&L prediction)
4. WHAT parameters work best (strike distances, DTE)

Architecture:
- FeatureExtractor: 22 features (pruned from 39) across volatility, momentum, macro, composite
- Strategy Classifier: predicts best strategy for current regime
- Win Probability Model: ensemble of GradientBoosting + RandomForest
- P&L Regressor: predicts expected trade P&L
- Macro Pattern Analyzer: learns which macro conditions drive wins/losses per strategy

Trained on 7-year multi-strategy backtest data (2019-2026).
"""

import json
import math
import pickle
import warnings
from datetime import date
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from backtester.engine import BacktestResult, TradeResult
from backtester.position_sizer import _regime_from_vix
from strategies.universe import ACTIVE_MONTHLY_STRATEGY_SET

MODEL_DIR = Path(__file__).parent / ".trained"
MODEL_DIR.mkdir(exist_ok=True)

STRATEGY_DISPLAY = {
    "no_trade": "No Trade",
    "put_credit_spread": "Put Credit Spread (Bull Put)",
    "broken_wing_butterfly": "Broken Wing Butterfly (Put)",
    "put_credit_wide": "Wide Put Credit Spread",
    "iron_condor": "Iron Condor (Delta-Targeted)",
    "iron_condor_v2": "Iron Condor V2",
    "calendar_spread": "Calendar Spread (Long Vega)",
    "ratio_put_spread": "Ratio Put Spread (Tail Hedge)",
}


class FeatureExtractor:
    """
    Extracts ML features including cross-geo disruption and macro indicators.

    Missing-data policy:
    - Critical fields (vix, nifty_close): if missing, extract() returns None
      so callers can skip the row entirely.
    - Derived/secondary fields: use NaN so the downstream .fillna(0) in
      training pipelines replaces them with 0 (a neutral value), which the
      model learns to treat as "no signal". This is far safer than fabricated
      defaults like vix=15 or spot=22000 which silently corrupt predictions.
    """

    FEATURE_GROUPS = {
        "volatility": [
            "vix_current", "vix_10d_avg", "vix_1d_change_pct",
            "vix_pct_chg_5d", "vix_vs_sma_ratio",
            "iv_minus_rv_premium", "nifty_bollinger_width_pct",
        ],
        "momentum": [
            "nifty_weekly_return_pct", "nifty_monthly_return_pct",
            "nifty_dist_above_sma50_pct", "nifty_rsi_14", "nifty_overnight_gap_pct",
        ],
        "macro_global": [
            "us_10y_yield_chg_5d",
            "sp500_weekly_return_pct", "sp500_monthly_return_pct",
        ],
        "macro_india": [
            "crude_oil_monthly_chg_pct",
            "usdinr_weakening_5d_pct", "usdinr_weakening_20d_pct",
            "banknifty_weekly_return_pct", "banknifty_nifty_ratio",
            "crude_x_inr_stress",
        ],
        "cross_geo": [
            "em_etf_monthly_return_pct",
            "china_hsi_weekly_return_pct", "china_hsi_monthly_return_pct",
            "europe_weekly_return_pct",
            "dxy_strengthening_5d_pct", "dxy_strengthening_20d_pct",
            "gold_safe_haven_5d_pct", "gold_safe_haven_20d_pct",
            "india_vix_premium_over_us",
        ],
        "composite": [
            "price_action_sentiment", "india_us_return_divergence",
            "global_contagion_score", "dxy_x_crude_pressure",
            "fii_outflow_proxy",
        ],
        "crash_detection": [
            "vix_acceleration_3d_pct", "crude_shock_10d_pct",
            "nifty_consec_down_days", "nifty_correction_depth_pct",
            "vol_expansion_ratio", "crash_risk_score",
        ],
        "crash_v2": [
            "vrp_change_5d", "vrp_negative",
            "rvol_10d_z", "range_expansion_ratio",
            "bn_ratio_change_5d", "correlation_spike_5d",
            "multi_asset_stress", "nifty_drawdown_from_50d_high_pct",
            "gap_magnitude_avg_5d", "intraday_dd_expanding_3d",
            "crash_risk_score_v2",
        ],
        "strategy_selection": [
            "iv_rv_term_spread",
            "iv_rv_term_spread_5d_chg",
            "iv_rv_term_spread_z",
            "iv_skew_proxy",
            "iv_skew_proxy_z",
            "theta_quality",
            "vega_regime",
            "vega_regime_5d_chg",
            "institutional_hedge_proxy",
            "nifty_dist_from_sma20_pct",
            "vix_volatility_10d",
            "regime_stability_10d",
        ],
    }

    FEATURE_NAMES = []
    for features in FEATURE_GROUPS.values():
        FEATURE_NAMES.extend(features)

    CRITICAL_FIELDS = {"vix", "nifty_close"}

    def __init__(self, full_data: pd.DataFrame):
        self.data = full_data
        self._precompute()

    def _precompute(self):
        if "vix" in self.data.columns:
            vix = self.data["vix"].dropna()
            self.vix_mean = vix.mean()
            self.vix_std = vix.std() if vix.std() > 0 else 1.0
            self.vix_values = vix.values
        else:
            self.vix_mean = 15.0
            self.vix_std = 5.0
            self.vix_values = np.array([15.0])

        from data.news_sentiment import (
            compute_price_action_sentiment,
            compute_geopolitical_risk_index,
        )
        self.data["sentiment_proxy"] = compute_price_action_sentiment(self.data)
        self.data["geopolitical_risk"] = compute_geopolitical_risk_index(self.data)

    def extract(self, row: pd.Series) -> dict | None:
        """
        Extract features from a market data row.

        Returns None if critical fields (vix, nifty_close) are missing or NaN,
        so callers can skip that row cleanly.
        """
        raw_vix = row.get("vix")
        raw_spot = row.get("nifty_close")
        if raw_vix is None or raw_spot is None or pd.isna(raw_vix) or pd.isna(raw_spot):
            return None
        vix = _safe_float(raw_vix)
        spot = _safe_float(raw_spot)
        if vix <= 0 or spot <= 0:
            return None

        sma50 = _safe_float(row.get("nifty_sma_50"), default=float("nan"))
        dist_sma50 = ((spot - sma50) / sma50 * 100) if not math.isnan(sma50) and sma50 > 0 else float("nan")

        sp_ret = _safe_float(row.get("sp500_return_5d"), default=float("nan"))
        nifty_ret = _safe_float(row.get("nifty_return_5d"), default=float("nan"))

        def _get(field: str) -> float:
            """Get field value; returns NaN if missing so .fillna(0) handles it downstream."""
            return _safe_float(row.get(field), default=float("nan"))

        return {
            # Volatility (7): current fear level + trend direction
            "vix_current": vix,
            "vix_10d_avg": _safe_float(row.get("vix_sma_10"), default=vix),
            "vix_1d_change_pct": _get("vix_change_1d"),
            "vix_pct_chg_5d": _get("vix_change_5d"),
            "vix_vs_sma_ratio": _get("vix_vs_sma_ratio"),
            "iv_minus_rv_premium": _get("vol_risk_premium"),
            "nifty_bollinger_width_pct": _get("nifty_bb_width"),

            # Momentum (5): where is Nifty heading?
            "nifty_weekly_return_pct": nifty_ret,
            "nifty_monthly_return_pct": _get("nifty_return_20d"),
            "nifty_dist_above_sma50_pct": dist_sma50,
            "nifty_rsi_14": _get("nifty_rsi_14"),
            "nifty_overnight_gap_pct": _get("overnight_gap_pct"),

            # Global macro (3): US rates and equity
            "us_10y_yield_chg_5d": _get("us_10y_change_5d"),
            "sp500_weekly_return_pct": sp_ret,
            "sp500_monthly_return_pct": _get("sp500_return_20d"),

            # India macro (6): oil, currency, banking
            "crude_oil_monthly_chg_pct": _get("crude_change_20d"),
            "usdinr_weakening_5d_pct": _get("usdinr_change_5d"),
            "usdinr_weakening_20d_pct": _get("usdinr_change_20d"),
            "banknifty_weekly_return_pct": _get("bank_nifty_return_5d"),
            "banknifty_nifty_ratio": _get("bank_nifty_ratio"),
            "crude_x_inr_stress": _get("crude_inr_composite"),

            # Cross-geo disruption (9): global contagion channels
            "em_etf_monthly_return_pct": _get("em_return_20d"),
            "china_hsi_weekly_return_pct": _get("china_return_5d"),
            "china_hsi_monthly_return_pct": _get("china_return_20d"),
            "europe_weekly_return_pct": _get("europe_return_5d"),
            "dxy_strengthening_5d_pct": _get("dxy_change_5d"),
            "dxy_strengthening_20d_pct": _get("dxy_change_20d"),
            "gold_safe_haven_5d_pct": _get("gold_change_5d"),
            "gold_safe_haven_20d_pct": _get("gold_change_20d"),
            "india_vix_premium_over_us": _get("vix_premium_over_us"),

            # Composite (5): derived risk signals
            "price_action_sentiment": _get("sentiment_proxy"),
            "india_us_return_divergence": (nifty_ret - sp_ret) if not (math.isnan(nifty_ret) or math.isnan(sp_ret)) else float("nan"),
            "global_contagion_score": _get("global_contagion_score"),
            "dxy_x_crude_pressure": _get("dxy_crude_composite"),
            "fii_outflow_proxy": _get("fii_flow_proxy"),

            # Crash detection (6): regime-shift early warnings
            "vix_acceleration_3d_pct": _get("vix_accel_3d_pct"),
            "crude_shock_10d_pct": _get("crude_spike_10d_pct"),
            "nifty_consec_down_days": _get("nifty_consec_down_days"),
            "nifty_correction_depth_pct": _get("nifty_drawdown_from_20d_high_pct"),
            "vol_expansion_ratio": _get("vol_expansion_ratio"),
            "crash_risk_score": _get("crash_risk_score"),

            # Crash V2 (11): forensics-driven features from 17yr analysis
            "vrp_change_5d": _get("vrp_change_5d"),
            "vrp_negative": _get("vrp_negative"),
            "rvol_10d_z": _get("rvol_10d_z"),
            "range_expansion_ratio": _get("range_expansion_ratio"),
            "bn_ratio_change_5d": _get("bn_ratio_change_5d"),
            "correlation_spike_5d": _get("correlation_spike_5d"),
            "multi_asset_stress": _get("multi_asset_stress"),
            "nifty_drawdown_from_50d_high_pct": _get("nifty_drawdown_from_50d_high_pct"),
            "gap_magnitude_avg_5d": _get("gap_magnitude_avg_5d"),
            "intraday_dd_expanding_3d": _get("intraday_dd_expanding_3d"),
            "crash_risk_score_v2": _get("crash_risk_score_v2"),

            # Strategy selection (12): features that differentiate which strategy to use
            "iv_rv_term_spread": _get("iv_rv_term_spread"),
            "iv_rv_term_spread_5d_chg": _get("iv_rv_term_spread_5d_chg"),
            "iv_rv_term_spread_z": _get("iv_rv_term_spread_z"),
            "iv_skew_proxy": _get("iv_skew_proxy"),
            "iv_skew_proxy_z": _get("iv_skew_proxy_z"),
            "theta_quality": _get("theta_quality"),
            "vega_regime": _get("vega_regime"),
            "vega_regime_5d_chg": _get("vega_regime_5d_chg"),
            "institutional_hedge_proxy": _get("institutional_hedge_proxy"),
            "nifty_dist_from_sma20_pct": _get("nifty_distance_from_sma20_pct"),
            "vix_volatility_10d": _get("vix_volatility_10d"),
            "regime_stability_10d": _get("regime_stability_10d"),
        }

    def extract_batch(self, dates: list) -> pd.DataFrame:
        rows = []
        for d in dates:
            if d in self.data.index:
                feats = self.extract(self.data.loc[d])
            else:
                closest = self.data.index[self.data.index.get_indexer([d], method="nearest")[0]]
                feats = self.extract(self.data.loc[closest])
            if feats is not None:
                rows.append(feats)
            else:
                rows.append({f: float("nan") for f in self.FEATURE_NAMES})
        return pd.DataFrame(rows, index=dates)


class TradeLearner:
    """
    Multi-strategy ML model that learns from regime-adaptive backtests.

    Learns:
    - WHEN to trade (win probability per strategy)
    - WHICH strategy to use (strategy classifier)
    - HOW MUCH to expect (P&L per strategy)
    - Per-strategy performance patterns
    """

    STRATEGY_LABELS = {
        "put_credit_spread":     0,
        "broken_wing_butterfly": 1,
        "put_credit_wide":       2,
        "calendar_spread":       3,
        "ratio_put_spread":      4,
        "iron_condor":           5,
        # Phase 2 v3: multi-strategy sim diversity additions
        "iron_butterfly":        6,
        "diagonal_spread":       7,
        "jade_lizard":           8,
        "put_backspread":        9,
    }
    STRATEGY_NAMES = {v: k for k, v in STRATEGY_LABELS.items()}

    MAX_FEATURES = 30
    LABEL_PERCENTILE = 45
    COST_HURDLE_PCT = 30.0   # 30% of credit captured = "good" trade (was 0.5 — trivially low)
    PCS_PENALTY = 0.85
    NEGATIVE_PNL_PENALTY = 0.75
    MIN_REGIME_AUC = 0.45   # OvR macro-AUC floor for 3-class (was 0.52)
    REGIME_RERANK_STRENGTH = 0.18
    REGIME_SCORE_CAP = 0.20

    DEFAULT_QUALITY_THRESHOLD = 0.48
    REGIME_QUALITY_THRESHOLDS = {
        "CRASH": 0.52,
        "HIGH_VOL": 0.50,
        "LOW_VOL": 0.48,
        "TRENDING": 0.46,
    }
    N_WALK_FORWARD_FOLDS = 5
    PURGE_DAYS = 60   # 60 days — covers 4-8 week options regime cycles (was 21)

    def __init__(self, model_version: str = "v4"):
        self.model_version = model_version
        self.quality_classifier = None
        self.return_regressor = None
        self.per_strategy_regressors: dict = {}
        self.feature_extractor: Optional[FeatureExtractor] = None
        self.selected_features: list = []
        self.label_threshold: float = 0.0
        self.regime_aucs: dict = {}
        self.feature_importance: dict = {}
        self.training_stats: dict = {}
        self.strategy_stats: dict = {}
        self.regime_strategy_stats: dict = {}
        self.strategy_insights: dict = {}
        self.learned_rules: list = []
        self.macro_insights: list = []
        self.is_trained = False

    def _quality_label(self, pnl_pct: float) -> int:
        """
        Absolute 3-class trade quality label (used in tests and as fallback).

          0 = poor   (pnl_pct <   0) — loss
          1 = ok     (0 <= pnl_pct < 30) — marginal win
          2 = good   (pnl_pct >= 30) — strong win

        NOTE: train() uses _quality_label_percentile() instead, which guarantees
        a balanced 33/33/33 split. This method is kept for unit-test validation
        of boundary semantics and for any caller that needs absolute labels.
        """
        if pnl_pct < 0:
            return 0
        elif pnl_pct < 30.0:
            return 1
        else:
            return 2

    def _quality_label_percentile(self, pnl_pct: float, p33: float, p67: float) -> int:
        """
        Percentile-based 3-class label for Gate 8 training.

          pnl_pct < p33  → class 0 (poor   — bottom third of entries)
          p33 <= pnl_pct < p67 → class 1 (ok — middle third)
          pnl_pct >= p67 → class 2 (good  — top third; Gate 8 allows entry)

        p33 and p67 are computed from the full training set's pnl_pct distribution,
        guaranteeing ~33% per class regardless of how sim trades are generated.
        This avoids the bimodal problem where absolute thresholds (e.g. 30%) produce
        94:0:6 class imbalance on sim trades, making AUC < 0.50.
        """
        if pnl_pct < p33:
            return 0
        elif pnl_pct < p67:
            return 1
        else:
            return 2

    def train(
        self,
        backtest_result_or_trades,
        market_data: pd.DataFrame,
        min_trades: int = 8,
        verbose: bool = False,
    ) -> dict:
        """
        Train trade-quality filter on backtest results.

        Key design changes from the original win/loss classifier:
        1. Label = risk-adjusted percentile (top 60% = 1) not binary P&L sign.
           Options selling has ~70% structural win rate, so "will it win?" is
           trivially solvable.  "Is it a *good* trade?" is the real question.
        2. Two-pass feature pruning: train scout GBM on all 64 features, keep
           top-25 by importance, retrain calibrated model on pruned set.
        3. Single calibrated GBM (Platt scaling) instead of 0.6 GBM + 0.4 RF.
           RF adds noise on small datasets; calibration is critical because
           quality_score feeds directly into position sizing.
        4. Per-strategy return regressors for composite ranking instead of a
           strategy classifier (ranking > classification).
        """
        if isinstance(backtest_result_or_trades, BacktestResult):
            trades = backtest_result_or_trades.trades
        else:
            trades = backtest_result_or_trades

        if len(trades) < min_trades:
            return {"error": f"Need at least {min_trades} trades, got {len(trades)}"}

        self.feature_extractor = FeatureExtractor(market_data)

        X_rows, risk_adj_returns, y_strategy = [], [], []
        strategy_trades = {}
        regime_strategy_trades = {}

        for trade in trades:
            entry_date = pd.Timestamp(trade.entry_date)
            idx = market_data.index.get_indexer([entry_date], method="nearest")[0]
            features = self.feature_extractor.extract(market_data.iloc[idx])
            if features is None:
                continue
            X_rows.append(features)
            risk_adj_returns.append(trade.pnl_pct)

            strat_name = trade.strategy.replace("adaptive:", "")
            y_strategy.append(self.STRATEGY_LABELS.get(strat_name, 0))
            regime = _regime_from_vix(trade.entry_vix)
            regime_strategy_trades.setdefault(regime, {})
            regime_strategy_trades[regime].setdefault(strat_name, {"wins": 0, "losses": 0, "pnl": 0, "trades": []})
            regime_strategy_trades[regime][strat_name]["trades"].append(trade)
            regime_strategy_trades[regime][strat_name]["pnl"] += trade.total_pnl
            if trade.total_pnl > 0:
                regime_strategy_trades[regime][strat_name]["wins"] += 1
            else:
                regime_strategy_trades[regime][strat_name]["losses"] += 1

            if strat_name not in strategy_trades:
                strategy_trades[strat_name] = {"wins": 0, "losses": 0, "pnl": 0, "trades": []}
            strategy_trades[strat_name]["trades"].append(trade)
            strategy_trades[strat_name]["pnl"] += trade.total_pnl
            if trade.total_pnl > 0:
                strategy_trades[strat_name]["wins"] += 1
            else:
                strategy_trades[strat_name]["losses"] += 1

        X_all = pd.DataFrame(X_rows).fillna(0).replace([float("inf"), float("-inf")], 0)
        y_return = np.array(risk_adj_returns)
        y_strat = np.array(y_strategy)

        # ── Percentile-based 3-class labels (Phase 2 v2) ──────────────────
        # Absolute thresholds (e.g. 30%) fail with sim-trade data because the
        # 50%-profit-target exit mechanic produces a bimodal distribution:
        # ~94% land above 30% (class-2) and ~6% are losses (class-0), leaving
        # class-1 nearly empty → AUC < 0.50 (model just predicts "good" always).
        #
        # Percentile labels guarantee a balanced 33/33/33 split regardless of
        # the absolute pnl_pct values, forcing the model to learn *relative*
        # entry quality: "is this entry in the top third of its historical peers?"
        #
        # p33 = 33rd percentile of pnl_pct → boundary between poor and ok
        # p67 = 67th percentile of pnl_pct → boundary between ok and good
        self.label_threshold = self.COST_HURDLE_PCT   # kept for display/compat
        p33 = float(np.percentile(y_return, 33))
        p67 = float(np.percentile(y_return, 67))
        if p33 >= p67:
            # Degenerate distribution (e.g. 94% of values identical — bimodal sim trades).
            # Fall back to rank-based tertile splitting via pd.qcut which handles ties.
            try:
                rank_labels = pd.qcut(y_return, q=3, labels=[0, 1, 2], duplicates="drop")
                y_quality = rank_labels.astype(int).values
                # Recompute p33/p67 from rank boundaries for stats
                cuts = pd.qcut(y_return, q=3, duplicates="drop", retbins=True)[1]
                p33 = float(cuts[1]) if len(cuts) > 1 else p33
                p67 = float(cuts[2]) if len(cuts) > 2 else p67
            except Exception:
                # Last resort: sort and split by index
                order = np.argsort(y_return)
                y_quality = np.zeros(len(y_return), dtype=int)
                n = len(y_return)
                y_quality[order[n//3:2*n//3]] = 1
                y_quality[order[2*n//3:]] = 2
        else:
            y_quality = np.array([self._quality_label_percentile(p, p33, p67) for p in y_return])
        self._label_p33 = p33   # stored for inspection / tests
        self._label_p67 = p67
        quality_classes = np.unique(y_quality)

        from sklearn.dummy import DummyClassifier
        from sklearn.ensemble import GradientBoostingClassifier, GradientBoostingRegressor
        from sklearn.calibration import CalibratedClassifierCV
        from sklearn.metrics import roc_auc_score
        from sklearn.model_selection import cross_val_score, TimeSeriesSplit

        n_est = min(100, max(30, len(trades) * 2))
        max_d = 4 if len(trades) > 20 else 3
        min_leaf = max(2, len(trades) // 10)

        # ── Pass 1: scout GBM on ALL features → importance for pruning ──
        scout = GradientBoostingClassifier(
            n_estimators=n_est, max_depth=max_d, learning_rate=0.08,
            min_samples_leaf=min_leaf, subsample=0.8, random_state=42,
        )
        if len(quality_classes) > 1:
            scout.fit(X_all, y_quality)
            raw_imp = dict(zip(X_all.columns, scout.feature_importances_))
        else:
            raw_imp = {c: 0.0 for c in X_all.columns}

        sorted_feats = sorted(raw_imp, key=raw_imp.get, reverse=True)
        max_feats = self.MAX_FEATURES
        self.selected_features = sorted_feats[:max_feats]
        self.feature_importance = {f: round(raw_imp[f], 4) for f in self.selected_features}
        X = X_all[self.selected_features]

        # ── Pass 2: calibrated quality classifier (Platt scaling) ──
        n_cv = min(3, max(2, len(trades) // 10))
        tscv = TimeSeriesSplit(n_splits=n_cv)
        base_gbm_params = dict(
            n_estimators=n_est, max_depth=max_d, learning_rate=0.08,
            min_samples_leaf=min_leaf, subsample=0.8, random_state=42,
        )

        if len(quality_classes) > 1:
            # Rolling walk-forward with purge/embargo for rigorous OOS validation
            n_folds = self.N_WALK_FORWARD_FOLDS
            fold_size = len(X) // (n_folds + 1)
            purge = self.PURGE_DAYS
            cv_aucs = []
            oof_scores = []
            oof_returns = []
            oof_labels = []
            for fold_i in range(n_folds):
                train_end = fold_size * (fold_i + 2)
                test_start = min(train_end + purge, len(X) - 1)
                test_end = min(test_start + fold_size, len(X))
                if test_end - test_start < 20:
                    continue
                X_tr, y_tr = X.iloc[:train_end], y_quality[:train_end]
                X_te, y_te = X.iloc[test_start:test_end], y_quality[test_start:test_end]
                if len(np.unique(y_te)) < 2:
                    continue

                fold_scout = GradientBoostingClassifier(
                    n_estimators=100, max_depth=3, learning_rate=0.05, subsample=0.8,
                    random_state=42,
                )
                fold_scout.fit(X_tr, y_tr)
                fold_imp = dict(zip(X_tr.columns, fold_scout.feature_importances_))
                fold_top = sorted(fold_imp, key=fold_imp.get, reverse=True)[:self.MAX_FEATURES]

                fold_model = GradientBoostingClassifier(
                    n_estimators=200, max_depth=4, learning_rate=0.05, subsample=0.8,
                    min_samples_leaf=20, random_state=42,
                )
                fold_model.fit(X_tr[fold_top], y_tr)
                try:
                    fold_probs_all = fold_model.predict_proba(X_te[fold_top])  # shape (n, 3)
                    # For 3-class OvR AUC; falls back to binary if only 2 classes survived
                    n_classes = fold_probs_all.shape[1] if fold_probs_all.ndim == 2 else 1
                    if n_classes >= 3:
                        fold_auc = roc_auc_score(
                            y_te, fold_probs_all, multi_class='ovr', average='macro'
                        )
                        # quality_score = P(class==2 — "good" trade)
                        fold_probs = fold_probs_all[:, 2]
                    else:
                        fold_probs = fold_probs_all[:, -1]
                        fold_auc = roc_auc_score(y_te, fold_probs)
                    cv_aucs.append(fold_auc)
                    oof_scores.extend(list(fold_probs))
                    oof_returns.extend(list(y_return[test_start:test_end]))
                    oof_labels.extend(list(y_te))
                except Exception:
                    pass

            cv_scores = np.array(cv_aucs) if cv_aucs else np.array([0.5])
            if verbose:
                for i, auc in enumerate(cv_aucs):
                    print(f"    Fold {i+1}: AUC={auc:.3f}")
            threshold_stats = self._sweep_thresholds(
                np.array(oof_scores) if oof_scores else np.array([]),
                np.array(oof_returns) if oof_returns else np.array([]),
                np.array(oof_labels) if oof_labels else np.array([]),
            )
            try:
                self.quality_classifier = CalibratedClassifierCV(
                    GradientBoostingClassifier(**base_gbm_params),
                    method="sigmoid", cv=tscv,
                )
                self.quality_classifier.fit(X, y_quality)
            except Exception:
                _gbm = GradientBoostingClassifier(**base_gbm_params)
                _gbm.fit(X, y_quality)
                self.quality_classifier = _gbm
        else:
            cv_scores = np.array([float(quality_classes[0]) if len(quality_classes) else 0.0])
            threshold_stats = {"recommended_threshold": self.DEFAULT_QUALITY_THRESHOLD, "threshold_table": []}
            fallback = DummyClassifier(strategy="constant", constant=int(quality_classes[0]) if len(quality_classes) else 0)
            fallback.fit(X, y_quality)
            self.quality_classifier = fallback

        # ── Expected risk-adjusted return regressor ──
        self.return_regressor = GradientBoostingRegressor(
            n_estimators=n_est, max_depth=max_d, learning_rate=0.08,
            min_samples_leaf=min_leaf, subsample=0.8, random_state=42,
        )
        self.return_regressor.fit(X, y_return)

        # ── Per-strategy return regressors (ranking > classification) ──
        self.per_strategy_regressors = {}
        for strat_name, strat_label in self.STRATEGY_LABELS.items():
            mask = y_strat == strat_label
            if mask.sum() >= 5:
                model = GradientBoostingRegressor(
                    n_estimators=min(50, max(20, int(mask.sum()) * 2)),
                    max_depth=3, learning_rate=0.1,
                    min_samples_leaf=max(2, int(mask.sum()) // 5),
                    random_state=42,
                )
                model.fit(X[mask], y_return[mask])
                self.per_strategy_regressors[strat_name] = model

        self._learn_optimal_params(trades, X, y_return)
        self._learn_macro_patterns(trades, X, y_quality)
        self._learn_strategy_patterns(strategy_trades, X, y_quality, y_strat)
        self._learn_regime_strategy_patterns(regime_strategy_trades)

        group_importance = {}
        for group, feats in FeatureExtractor.FEATURE_GROUPS.items():
            grp_imp = sum(self.feature_importance.get(f, 0) for f in feats)
            group_importance[group] = round(grp_imp, 4)

        self.strategy_stats = {}
        for sname, info in strategy_trades.items():
            total = info["wins"] + info["losses"]
            self.strategy_stats[sname] = {
                "trades": total,
                "wins": info["wins"],
                "win_rate": info["wins"] / total * 100 if total > 0 else 0,
                "total_pnl": info["pnl"],
                "avg_pnl": info["pnl"] / total if total > 0 else 0,
                "avg_entry_vix": np.mean([t.entry_vix for t in info["trades"]]),
            }

        self.regime_strategy_stats = {}
        for regime, s_map in regime_strategy_trades.items():
            self.regime_strategy_stats[regime] = {}
            for sname, info in s_map.items():
                total = info["wins"] + info["losses"]
                self.regime_strategy_stats[regime][sname] = {
                    "trades": total,
                    "wins": info["wins"],
                    "win_rate": info["wins"] / total * 100 if total > 0 else 0,
                    "total_pnl": info["pnl"],
                    "avg_pnl": info["pnl"] / total if total > 0 else 0,
                }

        self.training_stats = {
            "num_trades": len(trades),
            "num_quality_class2": int((y_quality == 2).sum()),   # class 2 = good
            "num_quality_class1": int((y_quality == 1).sum()),   # class 1 = ok
            "num_quality_class0": int((y_quality == 0).sum()),   # class 0 = poor
            # Legacy aliases (kept for compatibility; num_quality_positive previously
            # summed label values which was wrong with 3-class labels)
            "num_quality_positive": int((y_quality == 2).sum()),
            "num_quality_negative": int((y_quality == 0).sum()),
            "label_p33": round(getattr(self, "_label_p33", self.label_threshold), 2),
            "label_p67": round(getattr(self, "_label_p67", self.label_threshold), 2),
            "label_threshold_pct": round(self.label_threshold, 1),
            "cv_auc": float(cv_scores.mean()),
            "cv_std": float(cv_scores.std()),
            "total_pnl": float(sum(t.total_pnl for t in trades)),
            "avg_risk_adj_return": float(y_return.mean()),
            "feature_importance": {k: round(v, 4) for k, v in self.feature_importance.items()},
            "feature_group_importance": group_importance,
            "num_features_selected": len(self.selected_features),
            "num_features_total": len(X_all.columns),
            "num_strategies": len(set(y_strat)),
            "training_period_days": (
                pd.Timestamp(trades[-1].exit_date) - pd.Timestamp(trades[0].entry_date)
            ).days if len(trades) > 1 else 0,
            "strategy_stats": self.strategy_stats,
            "regime_strategy_stats": self.regime_strategy_stats,
            "recommended_threshold": round(float(threshold_stats.get("recommended_threshold", self.DEFAULT_QUALITY_THRESHOLD)), 3),
            "threshold_sweep": threshold_stats.get("threshold_table", []),
        }

        self.is_trained = True
        return self.training_stats

    def _sweep_thresholds(self, scores: np.ndarray, returns: np.ndarray, labels: np.ndarray) -> dict:
        """Leakage-safe threshold sweep using out-of-fold scores only."""
        if scores.size == 0 or returns.size == 0:
            return {
                "recommended_threshold": self.DEFAULT_QUALITY_THRESHOLD,
                "threshold_table": [],
            }

        thresholds = np.round(np.arange(0.40, 0.71, 0.01), 2)
        table = []
        best = None
        min_selected = max(8, int(len(scores) * 0.20))
        for thr in thresholds:
            mask = scores >= thr
            selected = int(mask.sum())
            if selected == 0:
                continue
            selected_returns = returns[mask]
            selected_labels = labels[mask] if labels.size == scores.size else (selected_returns > self.label_threshold).astype(int)
            precision = float(selected_labels.mean()) if selected_labels.size else 0.0
            recall = float(selected_labels.sum() / max(labels.sum(), 1)) if labels.size else 0.0
            total_return = float(selected_returns.sum())
            avg_return = float(selected_returns.mean())
            wins = selected_returns[selected_returns > 0]
            losses = selected_returns[selected_returns <= 0]
            pf = float(wins.sum() / abs(losses.sum())) if len(losses) and abs(losses.sum()) > 0 else float("inf")
            utilization = selected / len(scores)
            score = total_return
            if selected >= min_selected and total_return > 0:
                score *= max(0.5, min(pf, 5.0))
                score *= max(0.5, utilization)
            table.append({
                "threshold": round(float(thr), 2),
                "selected": selected,
                "precision": round(precision, 3),
                "recall": round(recall, 3),
                "avg_return": round(avg_return, 3),
                "total_return": round(total_return, 3),
                "profit_factor": round(pf, 3) if np.isfinite(pf) else float("inf"),
                "utilization": round(utilization, 3),
                "objective": round(float(score), 3),
            })
            if best is None or score > best["objective"]:
                best = table[-1]

        if best is None:
            best = {"threshold": self.DEFAULT_QUALITY_THRESHOLD, "objective": 0.0}

        return {
            "recommended_threshold": float(best["threshold"]),
            "threshold_table": table,
        }

    def _learn_optimal_params(self, trades, X, y_pnl):
        self.learned_rules = []

        winners = [t for t in trades if t.total_pnl > 0]
        losers = [t for t in trades if t.total_pnl <= 0]

        if winners:
            avg_win_vix = np.mean([t.entry_vix for t in winners])
            avg_win_holding = np.mean([t.holding_days for t in winners])
            self.learned_rules.append(
                f"Winning trades: avg entry VIX {avg_win_vix:.1f}, avg hold {avg_win_holding:.0f} days"
            )

        if losers:
            avg_loss_vix = np.mean([t.entry_vix for t in losers])
            vix_spike_losers = [t for t in losers if t.exit_vix > t.entry_vix * 1.15]
            self.learned_rules.append(f"Losing trades: avg entry VIX {avg_loss_vix:.1f}")
            if vix_spike_losers:
                self.learned_rules.append(
                    f"{len(vix_spike_losers)}/{len(losers)} losses had VIX spike >15%"
                )

        # Per-strategy learned rules
        strat_perf = {}
        for t in trades:
            s = t.strategy.replace("adaptive:", "")
            if s not in strat_perf:
                strat_perf[s] = []
            strat_perf[s].append(t)

        for s, s_trades in strat_perf.items():
            wins = [t for t in s_trades if t.total_pnl > 0]
            wr = len(wins) / len(s_trades) * 100
            avg_vix = np.mean([t.entry_vix for t in s_trades])
            display = STRATEGY_DISPLAY.get(s, s)
            self.learned_rules.append(
                f"{display}: {len(wins)}/{len(s_trades)} wins ({wr:.0f}%), avg VIX {avg_vix:.1f}"
            )

    def _learn_macro_patterns(self, trades, X, y_cls):
        self.macro_insights = []
        if len(X) == 0:
            return

        win_mask = y_cls == 1
        lose_mask = y_cls == 0

        macro_features = [
            "crude_oil_monthly_chg_pct", "usdinr_weakening_5d_pct",
            "gold_safe_haven_5d_pct", "sp500_weekly_return_pct",
            "price_action_sentiment", "us_10y_yield_chg_5d",
            "crude_x_inr_stress", "global_contagion_score",
        ]

        for feat in macro_features:
            if feat not in X.columns:
                continue
            win_mean = X.loc[win_mask, feat].mean() if win_mask.any() else 0
            lose_mean = X.loc[lose_mask, feat].mean() if lose_mask.any() else 0
            diff = abs(win_mean - lose_mean)
            feat_std = X[feat].std()
            if feat_std > 0 and diff / feat_std > 0.3:
                direction = "higher" if win_mean > lose_mean else "lower"
                self.macro_insights.append(
                    f"{feat}: wins have {direction} values "
                    f"(win={win_mean:.3f}, loss={lose_mean:.3f})"
                )

        if "global_contagion_score" in X.columns:
            high_contagion = X["global_contagion_score"] > X["global_contagion_score"].quantile(0.75)
            if high_contagion.any():
                contagion_wr = y_cls[high_contagion].mean() * 100
                norm_wr = y_cls[~high_contagion].mean() * 100 if (~high_contagion).any() else 0
                self.macro_insights.append(
                    f"High global contagion: {contagion_wr:.0f}% win rate vs {norm_wr:.0f}% normal"
                )

    def _learn_strategy_patterns(self, strategy_trades, X, y_cls, y_strat):
        """Learn which features drive success for each strategy."""
        self.strategy_insights = {}

        for strat_name, strat_label in self.STRATEGY_LABELS.items():
            mask = y_strat == strat_label
            if mask.sum() < 5:
                continue

            X_strat = X[mask]
            y_strat_cls = y_cls[mask]

            if len(set(y_strat_cls)) < 2:
                continue

            win_mask = y_strat_cls == 1
            lose_mask = y_strat_cls == 0
            insights = []

            key_features = ["vix_10d_avg", "nifty_weekly_return_pct", "nifty_monthly_return_pct",
                           "vix_pct_chg_5d", "price_action_sentiment", "crude_x_inr_stress",
                           "nifty_dist_above_sma50_pct", "global_contagion_score",
                           "em_etf_monthly_return_pct", "dxy_strengthening_5d_pct"]

            for feat in key_features:
                if feat not in X_strat.columns:
                    continue
                win_mean = X_strat.loc[win_mask, feat].mean() if win_mask.any() else 0
                lose_mean = X_strat.loc[lose_mask, feat].mean() if lose_mask.any() else 0
                std = X_strat[feat].std()
                if std > 0 and abs(win_mean - lose_mean) / std > 0.4:
                    better = "higher" if win_mean > lose_mean else "lower"
                    insights.append(f"{feat}: wins when {better} ({win_mean:.3f} vs {lose_mean:.3f})")

            self.strategy_insights[strat_name] = insights

    def _learn_regime_strategy_patterns(self, regime_strategy_trades: dict) -> None:
        """
        Build a regime x strategy performance matrix for ranking priors.

        The matrix stays descriptive rather than predictive: it is used as a
        small, bounded adjustment to the learned composite score so the ML
        layer can prefer sleeves that have actually worked in the current
        regime.
        """
        matrix = {}
        for regime, s_map in regime_strategy_trades.items():
            matrix[regime] = {}
            for sname, info in s_map.items():
                total = info["wins"] + info["losses"]
                if total <= 0:
                    continue
                matrix[regime][sname] = {
                    "trades": total,
                    "wins": info["wins"],
                    "win_rate": info["wins"] / total * 100 if total > 0 else 0,
                    "total_pnl": info["pnl"],
                    "avg_pnl": info["pnl"] / total if total > 0 else 0,
                }
        self.regime_strategy_stats = matrix

    def _regime_multiplier(
        self,
        regime: str,
        strategy_name: str,
        strength: float | None = None,
    ) -> tuple[float, dict]:
        """
        Compute a bounded multiplicative prior from historical regime stats.

        The multiplier is intentionally modest and support-weighted so it can
        improve ranking without overpowering the calibrated quality score.
        """
        regime_stats = self.regime_strategy_stats.get(regime, {})
        stats = regime_stats.get(strategy_name)
        if not stats:
            return 1.0, {}

        overall = self.strategy_stats.get(strategy_name, {})
        regime_wr = stats.get("win_rate", 0.0) / 100.0
        overall_wr = overall.get("win_rate", 50.0) / 100.0
        regime_avg_pnl = stats.get("avg_pnl", 0.0)
        support = min(1.0, stats.get("trades", 0) / 20.0)

        wr_edge = regime_wr - overall_wr
        pnl_edge = math.tanh(regime_avg_pnl / 15_000.0)
        score = 0.7 * wr_edge + 0.3 * pnl_edge
        base_strength = self.REGIME_RERANK_STRENGTH if strength is None else strength
        multiplier = 1.0 + (base_strength * support * score)

        if regime == "HIGH_VOL":
            if strategy_name in {"iron_condor", "calendar_spread"}:
                multiplier += 0.05 * support
            elif strategy_name == "put_credit_spread":
                multiplier -= 0.05 * support
            elif strategy_name == "broken_wing_butterfly":
                multiplier -= 0.03 * support

        multiplier = max(1.0 - self.REGIME_SCORE_CAP, min(1.0 + self.REGIME_SCORE_CAP, multiplier))
        return multiplier, {
            "regime_win_rate": round(regime_wr, 3),
            "overall_win_rate": round(overall_wr, 3),
            "regime_avg_pnl": round(regime_avg_pnl, 2),
            "support": round(support, 3),
            "multiplier": round(multiplier, 3),
        }

    def predict(self, row: pd.Series, eligible_strategies: list[str] | None = None) -> dict:
        """
        Score current market conditions as a trade-quality filter.

        The model answers "is this a good trade relative to alternatives?"
        rather than "will this trade win?".  Crash/circuit-breaker logic
        is intentionally left to the rules layer (RegimeAdaptiveStrategy)
        so that ML focuses purely on quality scoring and ranking.

        Returns quality_score (calibrated), expected_return (risk-adjusted),
        composite_score for each eligible strategy, and a filter decision.
        """
        if not self.is_trained or self.feature_extractor is None:
            return {"error": "Model not trained. Run train() first."}

        features = self.feature_extractor.extract(row)
        if features is None:
            return {"error": "Critical market data missing (vix or nifty_close) — cannot predict."}
        X = pd.DataFrame([features]).reindex(
            columns=self.selected_features, fill_value=0,
        ).fillna(0).replace([float("inf"), float("-inf")], 0)

        # ── Quality score = P(class==2 — "good" trade, captured >30% of credit) ──
        # With 3-class labels (poor=0, ok=1, good=2), Gate 8 allows entry only
        # when the model is confident this is a class-2 outcome.
        try:
            probs = self.quality_classifier.predict_proba(X)[0]
            classes = list(self.quality_classifier.classes_)
            if len(classes) == 1:
                quality_score = float(classes[0] == 2)
            elif 2 in classes:
                # 3-class model: P(good)
                quality_score = float(probs[classes.index(2)])
            elif 1 in classes:
                # Fallback: binary model still in cache — P(win)
                quality_score = float(probs[classes.index(1)])
            else:
                quality_score = 0.0
        except Exception:
            quality_score = 0.5

        # ── Expected risk-adjusted return ──
        expected_return = float(self.return_regressor.predict(X)[0])

        composite_score = quality_score * expected_return
        current_regime = _regime_from_vix(features.get("vix_current", 15.0))
        rerank_enabled = getattr(self, "regime_rerank_enabled", True)
        rerank_strength = getattr(self, "regime_rerank_strength", self.REGIME_RERANK_STRENGTH)

        # ── Per-strategy composite scoring (ranking, not classification) ──
        strategy_scores = {}
        for sname, model in self.per_strategy_regressors.items():
            try:
                strat_return = float(model.predict(X)[0])
                stats = self.strategy_stats.get(sname, {})
                strat_composite = quality_score * strat_return
                regime_multiplier = 1.0
                regime_context = {}
                if rerank_enabled:
                    regime_multiplier, regime_context = self._regime_multiplier(
                        current_regime, sname, strength=rerank_strength,
                    )
                strat_composite *= regime_multiplier

                if sname == "put_credit_spread":
                    penalty = self.PCS_PENALTY
                    strat_composite *= penalty
                elif stats.get("total_pnl", 0) < 0:
                    penalty = self.NEGATIVE_PNL_PENALTY
                    strat_composite *= penalty

                strategy_scores[sname] = {
                    "expected_return": round(strat_return, 2),
                    "composite_score": round(strat_composite, 4),
                    "historical_trades": stats.get("trades", 0),
                    "historical_wr": round(stats.get("win_rate", 50) / 100, 3),
                    "avg_pnl": stats.get("avg_pnl", 0),
                    "is_viable": strat_return > 0 and strat_composite > 0,
                    "regime_multiplier": round(regime_multiplier, 3),
                    "regime_context": regime_context,
                }
            except Exception:
                pass

        viable_scores = {k: v for k, v in strategy_scores.items() if v["composite_score"] > 0}
        candidate_scores = viable_scores if viable_scores else {}

        recommended_strategy = None
        if eligible_strategies and candidate_scores:
            eligible_set = set(eligible_strategies) & ACTIVE_MONTHLY_STRATEGY_SET
            eligible_scores = {k: v for k, v in candidate_scores.items() if k in eligible_set}
            if eligible_scores:
                recommended_strategy = max(
                    eligible_scores, key=lambda s: eligible_scores[s]["composite_score"],
                )
        elif candidate_scores:
            recommended_strategy = max(
                candidate_scores, key=lambda s: candidate_scores[s]["composite_score"],
            )
        else:
            recommended_strategy = None

        # ── Filter decision (regime-aware quality gate) ──
        quality_gate = self.DEFAULT_QUALITY_THRESHOLD
        should_enter = quality_score >= quality_gate and recommended_strategy is not None

        if not should_enter:
            signal = "AVOID"
        elif quality_score > 0.70:
            signal = "STRONG_ENTRY"
        elif quality_score > 0.58:
            signal = "MODERATE_ENTRY"
        else:
            signal = "CAUTION_ENTRY"

        # ── Reasoning ──
        reasoning = []
        reasoning.append(
            f"Quality score: {quality_score:.1%} "
            f"({'above' if should_enter else 'below'} {quality_gate:.0%} filter)"
        )
        reasoning.append(f"Expected risk-adj return: {expected_return:+.1f}%")

        top_features = list(self.feature_importance.items())[:8]
        for feat, importance in top_features:
            val = features.get(feat, 0)
            if importance > 0.03:
                reasoning.append(f"{feat}={val:.3f} (importance: {importance:.1%})")

        # ── Macro context (unchanged — pure feature reads, no model dependency) ──
        macro_context = []
        sentiment = features.get("price_action_sentiment", 0)
        if sentiment < -0.2:
            macro_context.append(f"NEGATIVE MARKET SENTIMENT ({sentiment:.2f})")
        elif sentiment > 0.2:
            macro_context.append(f"POSITIVE MARKET SENTIMENT ({sentiment:.2f})")
        crude_chg = features.get("crude_oil_monthly_chg_pct", 0)
        if abs(crude_chg) > 0.05:
            macro_context.append(f"Crude oil {'surging' if crude_chg > 0 else 'falling'} ({crude_chg:.1%} in 20d)")
        inr_chg = features.get("usdinr_weakening_5d_pct", 0)
        if inr_chg > 0.005:
            macro_context.append(f"Rupee weakening ({inr_chg:.2%} in 5d)")
        crude_inr = features.get("crude_x_inr_stress", 0)
        if crude_inr > 1.5:
            macro_context.append(f"CRUDE + INR DOUBLE STRESS ({crude_inr:.2f})")
        bb_width = features.get("nifty_bollinger_width_pct", 3)
        if bb_width < 2.0:
            macro_context.append(f"BOLLINGER SQUEEZE ({bb_width:.1f}%) — breakout imminent")
        rsi = features.get("nifty_rsi_14", 50)
        if rsi > 75:
            macro_context.append(f"RSI OVERBOUGHT ({rsi:.0f})")
        elif rsi < 25:
            macro_context.append(f"RSI OVERSOLD ({rsi:.0f})")
        gap = features.get("nifty_overnight_gap_pct", 0)
        if abs(gap) > 0.5:
            macro_context.append(f"Significant overnight gap ({gap:+.2f}%)")

        em_ret = features.get("em_etf_monthly_return_pct", 0)
        if em_ret < -0.03:
            macro_context.append(f"EM SELLOFF (EEM {em_ret:.1%} in 20d) — contagion risk")
        china_ret = features.get("china_hsi_weekly_return_pct", 0)
        if china_ret < -0.04:
            macro_context.append(f"CHINA WEAKNESS (HSI {china_ret:.1%} in 5d)")
        dxy_chg = features.get("dxy_strengthening_5d_pct", 0)
        if dxy_chg > 0.015:
            macro_context.append(f"DOLLAR STRENGTHENING (DXY +{dxy_chg:.1%}) — FII outflow risk")
        dxy_crude = features.get("dxy_x_crude_pressure", 0)
        if dxy_crude > 2.0:
            macro_context.append(f"DXY + CRUDE DOUBLE PRESSURE ({dxy_crude:.1f})")
        contagion = features.get("global_contagion_score", 0)
        if contagion > 0.3:
            macro_context.append(f"HIGH GLOBAL CONTAGION SCORE ({contagion:.2f})")
        vix_prem = features.get("india_vix_premium_over_us", 0)
        if vix_prem > 0.3:
            macro_context.append(f"INDIA FEAR PREMIUM over US ({vix_prem:.0%})")
        fii_flow = features.get("fii_outflow_proxy", 0)
        if fii_flow < -0.04:
            macro_context.append(f"FII OUTFLOW SIGNAL ({fii_flow:.1%})")

        crash_risk = features.get("crash_risk_score", 0)
        vix_accel = features.get("vix_acceleration_3d_pct", 0)
        crude_shock = features.get("crude_shock_10d_pct", 0)
        consec_down = features.get("nifty_consec_down_days", 0)
        correction = features.get("nifty_correction_depth_pct", 0)
        vol_expansion = features.get("vol_expansion_ratio", 1)
        crash_risk_v2 = features.get("crash_risk_score_v2", 0)
        multi_stress = features.get("multi_asset_stress", 0)

        if crash_risk_v2 >= 0.80:
            macro_context.append(f"EXTREME CRASH RISK ({crash_risk_v2:.0%}) — circuit breaker active")
        elif crash_risk >= 0.50:
            macro_context.append(f"CRASH RISK ELEVATED ({crash_risk:.0%})")
        if vix_accel > 30:
            macro_context.append(f"VIX ACCELERATING FAST (+{vix_accel:.0f}% in 3d)")
        if abs(crude_shock) > 20:
            macro_context.append(f"CRUDE OIL SHOCK ({crude_shock:+.0f}% in 10d)")
        if consec_down >= 4:
            macro_context.append(f"SUSTAINED SELLING ({consec_down:.0f} consecutive down days)")
        if correction < -10:
            macro_context.append(f"DEEP CORRECTION ({correction:.1f}% from 20d high)")
        if multi_stress >= 0.80:
            macro_context.append(f"MULTI-ASSET STRESS ({multi_stress:.0%})")
        if vol_expansion > 1.5:
            macro_context.append(f"VOLATILITY EXPANSION ({vol_expansion:.1f}x short vs long-term)")

        for ctx in macro_context:
            reasoning.append(f"[MACRO] {ctx}")
        for rule in self.learned_rules:
            reasoning.append(f"[Learned] {rule}")
        for insight in self.macro_insights:
            reasoning.append(f"[Macro] {insight}")

        return {
            "signal": signal,
            "quality_score": round(quality_score, 3),
            "expected_return": round(expected_return, 2),
            "composite_score": round(composite_score, 4),
            "should_enter": should_enter,
            "probability_profitable": round(quality_score, 3),
            "expected_pnl": round(expected_return, 0),
            "confidence": round(abs(quality_score - 0.5) * 2, 3),
            "recommended_strategy": recommended_strategy,
            "best_strategy": recommended_strategy,
            "strategy_scores": strategy_scores,
            "strategy_selection_probs": {},
            "current_regime": current_regime,
            "macro_context": macro_context,
            "reasoning": reasoning,
            "features": {k: round(v, 4) for k, v in features.items()},
        }

    def predict_strategy(self, row: pd.Series, eligible_strategies: list[str] | None = None) -> dict:
        """
        Recommend the best strategy for current conditions.
        In hybrid mode, eligible_strategies constrains ML's choice.
        Returns strategy name, parameters, and reasoning.
        """
        if not self.is_trained:
            return {"strategy": "no_trade", "reasoning": "Model not trained, defaulting to no trade"}

        prediction = self.predict(row, eligible_strategies=eligible_strategies)
        features = prediction["features"]
        vix = _safe_float(row.get("vix"), default=features.get("vix_10d_avg", 15))
        scores = prediction.get("strategy_scores", {})
        recommended = prediction.get("recommended_strategy") or "no_trade"

        result = {
            "strategy": recommended,
            "display_name": STRATEGY_DISPLAY.get(recommended, recommended),
            "strategy_scores": scores,
            "signal": prediction["signal"],
            "quality_score": prediction.get("quality_score", 0.5),
            "expected_return": prediction.get("expected_return", 0),
            "win_probability": prediction["probability_profitable"],
            "reasoning": [],
        }

        # Strategy-specific parameters
        if recommended == "put_credit_spread":
            put_sd = 1.3 if vix < 15 else 1.0 if vix < 20 else 0.8
            result["params"] = {
                "put_sd": put_sd, "spread_width": 500,
                "profit_target_pct": 50, "lots": 2, "target_dte": 21,
            }
            result["reasoning"].append(f"Put Credit Spread selected (VIX {vix:.1f})")
            result["reasoning"].append(f"Put distance: {put_sd:.1f} SD from spot")
        elif recommended == "no_trade":
            result["params"] = {}
            result["reasoning"].append("No strategy clears the risk-adjusted quality bar")

        elif recommended == "broken_wing_butterfly":
            result["params"] = {
                "inner_wing": 300, "outer_wing": 800,
                "profit_target_pct": 50, "lots": 2, "target_dte": 28,
            }
            result["reasoning"].append(f"Broken Wing Butterfly selected (VIX {vix:.1f})")

        elif recommended == "put_credit_wide":
            result["params"] = {
                "put_sd": 1.3, "spread_width": 500,
                "profit_target_pct": 40, "lots": 2, "target_dte": 21,
            }
            result["reasoning"].append(f"Wide Put Credit Spread selected (low VIX {vix:.1f})")

        elif recommended == "calendar_spread":
            result["params"] = {
                "profit_target_pct": 40, "lots": 2, "target_dte": 28,
                "dte_gap": 30, "max_rolls": 2,
            }
            result["reasoning"].append(f"Calendar Spread selected — long vega play (VIX {vix:.1f})")
            result["reasoning"].append("Supports rolling: up to 2 short-leg rolls for 40-60d total hold")

        elif recommended == "ratio_put_spread":
            result["params"] = {
                "put_sd": 1.0, "spread_width": 500,
                "profit_target_pct": 50, "lots": 2, "target_dte": 28,
            }
            result["reasoning"].append(f"Ratio Put Spread selected — tail-risk hedge (VIX {vix:.1f})")

        else:
            result["params"] = {
                "put_sd": 1.0, "spread_width": 500,
                "profit_target_pct": 50, "lots": 2, "target_dte": 21,
            }

        # Macro adjustments using active features
        crude_inr = features.get("crude_inr_composite", 0)
        crude_20d = features.get("crude_change_20d", 0)

        if crude_inr > 1.5:
            result["params"]["spread_width"] = max(result["params"].get("spread_width", 500), 500)
            result["reasoning"].append(f"Crude+INR stress elevated ({crude_inr:.2f}) — wider spread")
        if crude_20d > 0.10:
            result["params"]["profit_target_pct"] = min(result["params"].get("profit_target_pct", 50), 40)
            result["reasoning"].append(f"Crude surged {crude_20d:.0%} in 20d — lower profit target")

        # Strategy-specific insights
        insights = self.strategy_insights.get(recommended, [])
        for ins in insights[:3]:
            result["reasoning"].append(f"[Pattern] {ins}")

        return result

    def predict_optimal_params(self, row: pd.Series) -> dict:
        """Suggest optimal parameters based on conditions + macro."""
        if not self.is_trained:
            return {}

        strat_rec = self.predict_strategy(row)
        features = self.feature_extractor.extract(row)
        vix_sma = _safe_float(row.get("vix"), default=features.get("vix_sma_10", 15))
        crude_inr = features.get("crude_inr_composite", 0)
        sentiment = features.get("sentiment_proxy", 0)
        vix_chg = features.get("vix_change_5d", 0)
        us_vix_chg = features.get("us_vix_change_5d", 0)

        if crude_inr > 3.0 and vix_chg > 0.15:
            return {"recommendation": "AVOID - Crude + INR + VIX all stressed simultaneously"}
        if vix_sma > 28 and vix_chg > 0 and us_vix_chg > 0.15:
            return {"recommendation": "AVOID - Global + India volatility spiking"}
        if vix_sma < 12:
            return {"recommendation": "SKIP - VIX too low, premiums paper-thin"}

        params = strat_rec.get("params", {})
        params["strategy"] = strat_rec["strategy"]
        params["display_name"] = strat_rec["display_name"]
        params["reasoning"] = " | ".join(strat_rec.get("reasoning", []))
        params["crude_inr_stress"] = round(crude_inr, 3)
        params["sentiment"] = round(sentiment, 3)
        params["vix_trend"] = round(vix_chg, 3)

        return params

    def save(self, path: Optional[str] = None):
        path = path or str(MODEL_DIR / "trade_learner.pkl")
        with open(path, "wb") as f:
            pickle.dump({
                "version": 2,
                "model_version": self.model_version,
                "quality_classifier": self.quality_classifier,
                "return_regressor": self.return_regressor,
                "per_strategy_regressors": self.per_strategy_regressors,
                "selected_features": self.selected_features,
                "label_threshold": self.label_threshold,
                "regime_aucs": self.regime_aucs,
                "feature_importance": self.feature_importance,
                "training_stats": self.training_stats,
                "strategy_stats": self.strategy_stats,
                "regime_strategy_stats": self.regime_strategy_stats,
                "strategy_insights": getattr(self, "strategy_insights", {}),
                "learned_rules": self.learned_rules,
                "macro_insights": self.macro_insights,
                "vix_mean": self.feature_extractor.vix_mean if self.feature_extractor else 15,
                "vix_std": self.feature_extractor.vix_std if self.feature_extractor else 5,
            }, f)
        print(f"  Model saved to {path}")

    def load(self, path: Optional[str] = None) -> bool:
        path = path or str(MODEL_DIR / "trade_learner.pkl")
        try:
            with open(path, "rb") as f:
                data = pickle.load(f)
            if data.get("version", 1) < 2:
                print("  Stale v1 model detected — retrain required.")
                return False
            self.quality_classifier = data["quality_classifier"]
            self.return_regressor = data["return_regressor"]
            self.per_strategy_regressors = data.get("per_strategy_regressors", {})
            self.selected_features = data.get("selected_features", [])
            self.label_threshold = data.get("label_threshold", 0.0)
            self.regime_aucs = data.get("regime_aucs", {})
            self.model_version = data.get("model_version", "v4")
            self.feature_importance = data["feature_importance"]
            self.training_stats = data["training_stats"]
            self.strategy_stats = data.get("strategy_stats", {})
            self.regime_strategy_stats = data.get("regime_strategy_stats", {})
            self.strategy_insights = data.get("strategy_insights", {})
            self.learned_rules = data.get("learned_rules", [])
            self.macro_insights = data.get("macro_insights", [])
            self.is_trained = True
            return True 
        except (FileNotFoundError, Exception):
            return False

    def print_training_report(self):
        if not self.training_stats:
            print("  Model not trained yet.")
            return

        s = self.training_stats
        version_label = "v4 — Walk-Forward Validated + Greeks Caps + Normalized Exits"
        print(f"\n  {'='*75}")
        print(f"  ML TRADE-QUALITY FILTER REPORT ({version_label})")
        print(f"  {'='*75}")
        print(f"  Training Data: {s['num_trades']} trades "
              f"({s.get('num_quality_positive', '?')} good, "
              f"{s.get('num_quality_negative', '?')} mediocre/bad)")
        print(f"  Label: risk-adj return > {s.get('label_threshold_pct', '?')}% "
              f"= 'good trade' (top 60th pctl)")
        print(f"  Training Period: {s.get('training_period_days', 'N/A')} days")
        print(f"  Features: {s.get('num_features_selected', '?')}/{s.get('num_features_total', '?')} "
              f"selected (importance-pruned)")
        print(f"  Strategies Learned: {s.get('num_strategies', 'N/A')}")
        print(f"  Quality Classifier CV AUC: {s.get('cv_auc', 0):.3f} ± {s.get('cv_std', 0):.3f}")
        print(f"  Avg Risk-Adjusted Return: {s.get('avg_risk_adj_return', 0):+.1f}%")
        print(f"  Total P&L in training set: ₹{s['total_pnl']:,.0f}")

        strat_stats = s.get("strategy_stats", {})
        if strat_stats:
            print(f"\n  PER-STRATEGY PERFORMANCE (from training data):")
            for sname, ss in sorted(strat_stats.items(), key=lambda x: x[1]["total_pnl"], reverse=True):
                display = STRATEGY_DISPLAY.get(sname, sname)
                has_model = "✓" if sname in self.per_strategy_regressors else "–"
                print(f"    [{has_model}] {display:<33} {ss['wins']}/{ss['trades']} ({ss['win_rate']:.0f}%) "
                      f"| P&L: ₹{ss['total_pnl']:>+10,.0f} | Avg: ₹{ss['avg_pnl']:>+6,.0f} "
                      f"| Avg VIX: {ss['avg_entry_vix']:.1f}")

        print(f"\n  SELECTED FEATURES (top {len(self.selected_features)}):")
        for feat, imp in list(s["feature_importance"].items())[:15]:
            bar = "█" * int(imp * 100)
            print(f"    {feat:<35} {imp:>6.1%} {bar}")

        grp_imp = s.get("feature_group_importance", {})
        if grp_imp:
            print(f"\n  FEATURE GROUP IMPORTANCE:")
            for group, imp in sorted(grp_imp.items(), key=lambda x: x[1], reverse=True):
                bar = "█" * int(imp * 100)
                print(f"    {group:<20} {imp:>6.1%} {bar}")

        if self.learned_rules:
            print(f"\n  LEARNED RULES:")
            for rule in self.learned_rules:
                print(f"    • {rule}")

        if self.macro_insights:
            print(f"\n  MACRO INSIGHTS:")
            for insight in self.macro_insights:
                print(f"    • {insight}")

        if hasattr(self, "strategy_insights") and self.strategy_insights:
            print(f"\n  PER-STRATEGY PATTERNS:")
            for sname, insights in self.strategy_insights.items():
                if insights:
                    display = STRATEGY_DISPLAY.get(sname, sname)
                    print(f"    {display}:")
                    for ins in insights[:3]:
                        print(f"      • {ins}")


def _safe_float(val, default=0.0) -> float:
    try:
        v = float(val)
        if math.isnan(v) or math.isinf(v):
            return default
        return v
    except (TypeError, ValueError):
        return default
