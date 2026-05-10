"""
V1 Entry Model — GBM + RF Ensemble with binary win/loss labels.

This is the ORIGINAL entry model that produced Run #7 (Sharpe 3.69, CAGR 16.33%).
Preserved as a stable baseline while v2/v2_tuned are iterated upon.

Architecture:
- Binary label: pnl > 0 → 1 (win), else 0 (loss)
- Win probability: 0.6 * GBM + 0.4 * RandomForest ensemble
- Strategy classifier: GBM predicting best strategy index
- Per-strategy mini-models: GBM win probability per strategy
- P&L regressor: GBM predicting expected trade P&L
- Strategy ranking: blended_score = 0.7 * ml_win_prob + 0.3 * historical_wr

Uses all available features (no pruning) — overfitting risk is mitigated by
the ensemble and the regime-aware wrapper which splits by market regime.
"""

import math
import pickle
import warnings
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from backtester.engine import BacktestResult, TradeResult
from models.trade_learner import (
    FeatureExtractor,
    MODEL_DIR,
    STRATEGY_DISPLAY,
    _safe_float,
)


class TradeLearnerV1:
    """
    V1 multi-strategy ML model (GBM + RF ensemble).

    Learns:
    - WHEN to trade (win probability via GBM + RF ensemble)
    - WHICH strategy to use (strategy classifier)
    - HOW MUCH to expect (P&L regressor)
    - Per-strategy performance patterns
    """

    STRATEGY_LABELS = {
        "put_credit_spread": 0,
        "broken_wing_butterfly": 1,
        "put_credit_wide": 2,
        "calendar_spread": 3,
        "ratio_put_spread": 4,
    }
    STRATEGY_NAMES = {v: k for k, v in STRATEGY_LABELS.items()}

    def __init__(self, model_version: str = "v1"):
        self.model_version = model_version
        self.classifier = None
        self.rf_classifier = None
        self.regressor = None
        self.strategy_classifier = None
        self.per_strategy_models: dict = {}
        self.feature_extractor: Optional[FeatureExtractor] = None
        self.feature_importance: dict = {}
        self.training_stats: dict = {}
        self.strategy_stats: dict = {}
        self.learned_rules: list = []
        self.macro_insights: list = []
        self.is_trained = False

    def train(
        self,
        backtest_result_or_trades,
        market_data: pd.DataFrame,
        min_trades: int = 8,
    ) -> dict:
        """
        Train v1 ensemble on backtest results.

        Binary label: pnl > 0 → 1 (win), else 0 (loss).
        Trains GBM + RF for win probability, GBM for strategy classification,
        GBM regressor for expected P&L, and per-strategy win-probability models.
        """
        if isinstance(backtest_result_or_trades, BacktestResult):
            trades = backtest_result_or_trades.trades
        else:
            trades = backtest_result_or_trades

        if len(trades) < min_trades:
            return {"error": f"Need at least {min_trades} trades, got {len(trades)}"}

        self.feature_extractor = FeatureExtractor(market_data)

        X_rows, y_pnl, y_strategy = [], [], []
        strategy_trades = {}

        for trade in trades:
            entry_date = pd.Timestamp(trade.entry_date)
            idx = market_data.index.get_indexer([entry_date], method="nearest")[0]
            features = self.feature_extractor.extract(market_data.iloc[idx])
            if features is None:
                continue
            X_rows.append(features)
            y_pnl.append(trade.total_pnl)

            strat_name = trade.strategy.replace("adaptive:", "")
            y_strategy.append(self.STRATEGY_LABELS.get(strat_name, 0))

            if strat_name not in strategy_trades:
                strategy_trades[strat_name] = {"wins": 0, "losses": 0, "pnl": 0, "trades": []}
            strategy_trades[strat_name]["trades"].append(trade)
            strategy_trades[strat_name]["pnl"] += trade.total_pnl
            if trade.total_pnl > 0:
                strategy_trades[strat_name]["wins"] += 1
            else:
                strategy_trades[strat_name]["losses"] += 1

        X = pd.DataFrame(X_rows).fillna(0).replace([float("inf"), float("-inf")], 0)
        y_class = (np.array(y_pnl) > 0).astype(int)
        y_pnl_arr = np.array(y_pnl)
        y_strat = np.array(y_strategy)

        from sklearn.ensemble import (
            GradientBoostingClassifier,
            GradientBoostingRegressor,
            RandomForestClassifier,
        )
        from sklearn.model_selection import cross_val_score, TimeSeriesSplit

        n_est = min(100, max(30, len(trades) * 2))
        max_d = 4 if len(trades) > 20 else 3
        min_leaf = max(2, len(trades) // 10)

        # ── GBM classifier (win/loss) ──
        self.classifier = GradientBoostingClassifier(
            n_estimators=n_est, max_depth=max_d, learning_rate=0.08,
            min_samples_leaf=min_leaf, subsample=0.8, random_state=42,
        )
        self.classifier.fit(X, y_class)

        # ── RF classifier (win/loss) ──
        self.rf_classifier = RandomForestClassifier(
            n_estimators=n_est, max_depth=max_d + 2,
            min_samples_leaf=min_leaf, random_state=42, n_jobs=-1,
        )
        self.rf_classifier.fit(X, y_class)

        # ── P&L regressor ──
        self.regressor = GradientBoostingRegressor(
            n_estimators=n_est, max_depth=max_d, learning_rate=0.08,
            min_samples_leaf=min_leaf, subsample=0.8, random_state=42,
        )
        self.regressor.fit(X, y_pnl_arr)

        # ── Strategy classifier ──
        if len(set(y_strat)) > 1:
            self.strategy_classifier = GradientBoostingClassifier(
                n_estimators=min(80, n_est), max_depth=3, learning_rate=0.1,
                min_samples_leaf=min_leaf, random_state=42,
            )
            self.strategy_classifier.fit(X, y_strat)

        # ── Per-strategy win probability models ──
        self.per_strategy_models = {}
        for strat_name, strat_label in self.STRATEGY_LABELS.items():
            mask = y_strat == strat_label
            if mask.sum() >= 5 and len(set(y_class[mask])) > 1:
                model = GradientBoostingClassifier(
                    n_estimators=min(50, max(20, int(mask.sum()) * 2)),
                    max_depth=3, learning_rate=0.1,
                    min_samples_leaf=max(2, int(mask.sum()) // 5),
                    random_state=42,
                )
                model.fit(X[mask], y_class[mask])
                self.per_strategy_models[strat_name] = model

        # ── Cross-validation ──
        n_cv = min(3, max(2, len(trades) // 10))
        tscv = TimeSeriesSplit(n_splits=n_cv)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            cv_scores = cross_val_score(
                GradientBoostingClassifier(
                    n_estimators=n_est, max_depth=max_d, learning_rate=0.08,
                    min_samples_leaf=min_leaf, subsample=0.8, random_state=42,
                ),
                X, y_class, cv=tscv, scoring="accuracy", error_score=0.5,
            )
            strategy_cv = np.array([0.5])
            if self.strategy_classifier is not None:
                strategy_cv = cross_val_score(
                    GradientBoostingClassifier(
                        n_estimators=min(80, n_est), max_depth=3,
                        learning_rate=0.1, min_samples_leaf=min_leaf,
                        random_state=42,
                    ),
                    X, y_strat, cv=tscv, scoring="accuracy", error_score=0.5,
                )

        # Feature importance from GBM
        self.feature_importance = dict(
            zip(X.columns, self.classifier.feature_importances_)
        )
        self.feature_importance = dict(
            sorted(self.feature_importance.items(), key=lambda x: x[1], reverse=True)
        )

        self._learn_optimal_params(trades, X, y_pnl_arr)
        self._learn_macro_patterns(trades, X, y_class)
        self._learn_strategy_patterns(strategy_trades, X, y_class, y_strat)

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

        self.training_stats = {
            "num_trades": len(trades),
            "num_winners": int(y_class.sum()),
            "num_losers": int(len(y_class) - y_class.sum()),
            "cv_accuracy": float(cv_scores.mean()),
            "cv_std": float(cv_scores.std()),
            "cv_auc": float(cv_scores.mean()),
            "strategy_cv_accuracy": float(strategy_cv.mean()),
            "total_pnl": float(sum(t.total_pnl for t in trades)),
            "feature_importance": {k: round(v, 4) for k, v in list(self.feature_importance.items())[:25]},
            "feature_group_importance": group_importance,
            "num_features": len(X.columns),
            "num_strategies": len(set(y_strat)),
            "training_period_days": (
                pd.Timestamp(trades[-1].exit_date) - pd.Timestamp(trades[0].entry_date)
            ).days if len(trades) > 1 else 0,
            "strategy_stats": self.strategy_stats,
        }

        self.is_trained = True
        return self.training_stats

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
            key_features = [
                "vix_10d_avg", "nifty_weekly_return_pct", "nifty_monthly_return_pct",
                "vix_pct_chg_5d", "price_action_sentiment", "crude_x_inr_stress",
                "nifty_dist_above_sma50_pct", "global_contagion_score",
                "em_etf_monthly_return_pct", "dxy_strengthening_5d_pct",
            ]
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

    def predict(self, row: pd.Series, eligible_strategies: list[str] | None = None) -> dict:
        """
        V1 predict: GBM + RF ensemble for win probability, regressor for
        expected P&L, strategy classifier for selection.
        """
        if not self.is_trained or self.feature_extractor is None:
            return {"error": "Model not trained. Run train() first."}

        features = self.feature_extractor.extract(row)
        if features is None:
            return {"error": "Critical market data missing (vix or nifty_close) — cannot predict."}

        X = pd.DataFrame([features]).fillna(0).replace([float("inf"), float("-inf")], 0)

        # ── Win probability: 60% GBM + 40% RF ──
        try:
            gbm_probs = self.classifier.predict_proba(X)[0]
            gbm_classes = list(self.classifier.classes_)
            gbm_win = float(gbm_probs[gbm_classes.index(1)] if 1 in gbm_classes else gbm_probs[-1])
        except Exception:
            gbm_win = 0.5

        try:
            rf_probs = self.rf_classifier.predict_proba(X)[0]
            rf_classes = list(self.rf_classifier.classes_)
            rf_win = float(rf_probs[rf_classes.index(1)] if 1 in rf_classes else rf_probs[-1])
        except Exception:
            rf_win = 0.5

        prob_profitable = 0.6 * gbm_win + 0.4 * rf_win

        # ── Expected P&L ──
        try:
            expected_pnl = float(self.regressor.predict(X)[0])
        except Exception:
            expected_pnl = 0.0

        # ── Strategy classification + scoring ──
        strategy_probs = {}
        if self.strategy_classifier is not None:
            try:
                strat_pred = self.strategy_classifier.predict_proba(X)[0]
                for i, prob in enumerate(strat_pred):
                    sname = self.STRATEGY_NAMES.get(i)
                    if sname:
                        strategy_probs[sname] = float(prob)
            except Exception:
                pass

        strategy_scores = {}
        for sname, model in self.per_strategy_models.items():
            try:
                strat_probs = model.predict_proba(X)[0]
                strat_classes = list(model.classes_)
                ml_win = float(strat_probs[strat_classes.index(1)] if 1 in strat_classes else strat_probs[-1])
                stats = self.strategy_stats.get(sname, {})
                historical_wr = stats.get("win_rate", 50) / 100.0
                blended = 0.7 * ml_win + 0.3 * historical_wr
                strategy_scores[sname] = {
                    "expected_return": round(ml_win * 100, 2),
                    "composite_score": round(blended, 4),
                    "ml_win_prob": round(ml_win, 3),
                    "historical_wr": round(historical_wr, 3),
                    "blended_score": round(blended, 4),
                    "historical_trades": stats.get("trades", 0),
                    "avg_pnl": stats.get("avg_pnl", 0),
                }
            except Exception:
                pass

        # ── Strategy recommendation ──
        recommended_strategy = None
        if eligible_strategies:
            eligible_set = set(eligible_strategies)
            eligible_scores = {k: v for k, v in strategy_scores.items() if k in eligible_set}
            if eligible_scores:
                recommended_strategy = max(
                    eligible_scores, key=lambda s: eligible_scores[s]["blended_score"],
                )
            else:
                recommended_strategy = eligible_strategies[0]
        elif strategy_scores:
            recommended_strategy = max(
                strategy_scores, key=lambda s: strategy_scores[s]["blended_score"],
            )

        # ── Signal classification ──
        crash_risk = features.get("crash_risk_score_v2", features.get("crash_risk_score", 0))
        multi_stress = features.get("multi_asset_stress", 0)

        if crash_risk >= 0.80 or multi_stress >= 0.80:
            signal = "AVOID"
            should_enter = False
        elif prob_profitable < 0.45:
            signal = "AVOID"
            should_enter = False
        elif prob_profitable > 0.60:
            signal = "STRONG_ENTRY"
            should_enter = True
        elif prob_profitable > 0.45:
            sentiment = features.get("price_action_sentiment", 0)
            crude_stress = features.get("crude_x_inr_stress", 0)
            if sentiment < -0.3 or crude_stress > 2.5:
                signal = "CAUTION_ENTRY"
            else:
                signal = "MODERATE_ENTRY"
            should_enter = True
        else:
            signal = "AVOID"
            should_enter = False

        # ── Macro context ──
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

        contagion = features.get("global_contagion_score", 0)
        if contagion > 0.3:
            macro_context.append(f"HIGH GLOBAL CONTAGION SCORE ({contagion:.2f})")
        if crash_risk >= 0.80:
            macro_context.append(f"EXTREME CRASH RISK ({crash_risk:.0%})")
        elif crash_risk >= 0.50:
            macro_context.append(f"CRASH RISK ELEVATED ({crash_risk:.0%})")

        # ── Reasoning ──
        reasoning = [
            f"Win probability: {prob_profitable:.1%} (GBM {gbm_win:.1%} + RF {rf_win:.1%})",
            f"Expected P&L: ₹{expected_pnl:+,.0f}",
        ]
        top_features = list(self.feature_importance.items())[:8]
        for feat, importance in top_features:
            val = features.get(feat, 0)
            if importance > 0.03:
                reasoning.append(f"{feat}={val:.3f} (importance: {importance:.1%})")
        for ctx in macro_context:
            reasoning.append(f"[MACRO] {ctx}")
        for rule in self.learned_rules:
            reasoning.append(f"[Learned] {rule}")

        return {
            "signal": signal,
            "quality_score": round(prob_profitable, 3),
            "expected_return": round(expected_pnl / 1000, 2),
            "composite_score": round(prob_profitable * max(expected_pnl, 0) / 10000, 4),
            "should_enter": should_enter,
            "probability_profitable": round(prob_profitable, 3),
            "expected_pnl": round(expected_pnl, 0),
            "confidence": round(abs(prob_profitable - 0.5) * 2, 3),
            "recommended_strategy": recommended_strategy,
            "strategy_scores": strategy_scores,
            "strategy_selection_probs": strategy_probs,
            "macro_context": macro_context,
            "reasoning": reasoning,
            "features": {k: round(v, 4) for k, v in features.items()},
        }

    def predict_strategy(self, row: pd.Series, eligible_strategies: list[str] | None = None) -> dict:
        if not self.is_trained:
            return {"strategy": "put_credit_spread", "reasoning": "Model not trained, defaulting"}

        prediction = self.predict(row, eligible_strategies=eligible_strategies)
        features = prediction["features"]
        vix = _safe_float(row.get("vix"), default=features.get("vix_10d_avg", 15))
        scores = prediction.get("strategy_scores", {})
        recommended = prediction.get("recommended_strategy", "put_credit_spread")

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

        if recommended == "put_credit_spread":
            put_sd = 1.3 if vix < 15 else 1.0 if vix < 20 else 0.8
            result["params"] = {"put_sd": put_sd, "spread_width": 500, "profit_target_pct": 50, "lots": 2, "target_dte": 21}
        elif recommended == "broken_wing_butterfly":
            result["params"] = {"inner_wing": 300, "outer_wing": 800, "profit_target_pct": 50, "lots": 2, "target_dte": 28}
        elif recommended == "calendar_spread":
            result["params"] = {"profit_target_pct": 40, "lots": 2, "target_dte": 28, "dte_gap": 30, "max_rolls": 2}
        elif recommended == "ratio_put_spread":
            result["params"] = {"put_sd": 1.0, "spread_width": 500, "profit_target_pct": 50, "lots": 2, "target_dte": 28}
        else:
            result["params"] = {"put_sd": 1.0, "spread_width": 500, "profit_target_pct": 50, "lots": 2, "target_dte": 21}

        insights = getattr(self, "strategy_insights", {}).get(recommended, [])
        for ins in insights[:3]:
            result["reasoning"].append(f"[Pattern] {ins}")

        return result

    def predict_optimal_params(self, row: pd.Series) -> dict:
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
        return params

    def save(self, path: Optional[str] = None):
        path = path or str(MODEL_DIR / "trade_learner_v1.pkl")
        with open(path, "wb") as f:
            pickle.dump({
                "version": 1,
                "model_version": "v1",
                "classifier": self.classifier,
                "rf_classifier": self.rf_classifier,
                "regressor": self.regressor,
                "strategy_classifier": self.strategy_classifier,
                "per_strategy_models": self.per_strategy_models,
                "feature_importance": self.feature_importance,
                "training_stats": self.training_stats,
                "strategy_stats": self.strategy_stats,
                "strategy_insights": getattr(self, "strategy_insights", {}),
                "learned_rules": self.learned_rules,
                "macro_insights": self.macro_insights,
                "vix_mean": self.feature_extractor.vix_mean if self.feature_extractor else 15,
                "vix_std": self.feature_extractor.vix_std if self.feature_extractor else 5,
            }, f)
        print(f"  Model saved to {path}")

    def load(self, path: Optional[str] = None) -> bool:
        path = path or str(MODEL_DIR / "trade_learner_v1.pkl")
        try:
            with open(path, "rb") as f:
                data = pickle.load(f)
            self.classifier = data["classifier"]
            self.rf_classifier = data["rf_classifier"]
            self.regressor = data["regressor"]
            self.strategy_classifier = data.get("strategy_classifier")
            self.per_strategy_models = data.get("per_strategy_models", {})
            self.feature_importance = data["feature_importance"]
            self.training_stats = data["training_stats"]
            self.strategy_stats = data.get("strategy_stats", {})
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
        print(f"\n  {'='*75}")
        print(f"  ML ENTRY MODEL REPORT (v1 — GBM + RF Ensemble)")
        print(f"  {'='*75}")
        print(f"  Training Data: {s['num_trades']} trades "
              f"({s.get('num_winners', '?')} wins, {s.get('num_losers', '?')} losses)")
        print(f"  Training Period: {s.get('training_period_days', 'N/A')} days")
        print(f"  Features: {s.get('num_features', '?')} (all groups, no pruning)")
        print(f"  Strategies Learned: {s.get('num_strategies', 'N/A')}")
        print(f"  GBM CV Accuracy: {s.get('cv_accuracy', 0):.3f} ± {s.get('cv_std', 0):.3f}")
        print(f"  Strategy CV Accuracy: {s.get('strategy_cv_accuracy', 0):.3f}")
        print(f"  Total P&L in training set: ₹{s['total_pnl']:,.0f}")

        strat_stats = s.get("strategy_stats", {})
        if strat_stats:
            print(f"\n  PER-STRATEGY PERFORMANCE:")
            for sname, ss in sorted(strat_stats.items(), key=lambda x: x[1]["total_pnl"], reverse=True):
                display = STRATEGY_DISPLAY.get(sname, sname)
                has_model = "Y" if sname in self.per_strategy_models else "N"
                print(f"    [{has_model}] {display:<33} {ss['wins']}/{ss['trades']} ({ss['win_rate']:.0f}%) "
                      f"| P&L: ₹{ss['total_pnl']:>+10,.0f} | VIX: {ss['avg_entry_vix']:.1f}")

        print(f"\n  TOP FEATURES:")
        for feat, imp in list(s["feature_importance"].items())[:15]:
            bar = "█" * int(imp * 100)
            print(f"    {feat:<35} {imp:>6.1%} {bar}")

        if self.learned_rules:
            print(f"\n  LEARNED RULES:")
            for rule in self.learned_rules:
                print(f"    • {rule}")
