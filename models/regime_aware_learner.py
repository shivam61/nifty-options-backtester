"""
Regime-Aware Entry Model: trains separate TradeLearner per market regime.

Instead of one global model that averages across LOW_VOL/HIGH_VOL/CRASH/TRENDING,
this trains 3-4 specialized models, each learning the edge specific to its regime.

Architecture:
  1. RegimeClassifier labels each day → regime
  2. Training trades are split by regime at entry date
  3. Separate TradeLearner trained per regime
  4. At inference: classify regime → route to regime-specific model

Benefits:
  - LOW_VOL model learns thin-premium patterns (tight spreads, theta-heavy)
  - HIGH_VOL model learns fat-premium patterns (wider spreads, more aggressive)
  - CRASH model learns to skip/be very selective (or not trade at all)
  - TRENDING model learns directional overlays
"""

import datetime
import logging
from pathlib import Path

import joblib
import pandas as pd
import numpy as np
from models.cache_utils import ModelPeriodMetadata, metadata_from_state
from models.regime_classifier import RegimeClassifier, Regime, REGIME_NAMES
from models.trade_learner import TradeLearner, FeatureExtractor

logger = logging.getLogger(__name__)

_CACHE_DIR = Path(__file__).parent.parent / "data" / ".cache"
MODEL_CACHE_PATH = _CACHE_DIR / "entry_model_v4.pkl"


class RegimeAwareLearner:
    """
    Wraps multiple TradeLearners — one per regime.

    Replaces the single global TradeLearner with regime-specific models.
    Falls back to global model for regimes with insufficient training data.
    """

    MIN_TRADES_PER_REGIME = 30

    def __init__(self, model_version: str = "v4"):
        self.model_version = model_version
        self.regime_classifier = RegimeClassifier()
        self.regime_models: dict[Regime, TradeLearner] = {}
        self.global_model = self._make_learner()
        self.is_trained = False
        self.training_stats = {}
        self._regime_trade_counts = {}
        self.period_metadata: ModelPeriodMetadata | None = None

    def _make_learner(self):
        """Factory: create TradeLearner for the active version."""
        return TradeLearner(model_version=self.model_version)

    def train(self, trades, market_data: pd.DataFrame, verbose: bool = True) -> dict:
        """
        Train regime classifier + per-regime entry models.

        Args:
            trades: list of trade objects or BacktestResult with .trades
            market_data: full market dataframe (for feature extraction + regime labels)
        """
        if hasattr(trades, "trades"):
            trade_list = trades.trades
        elif isinstance(trades, list):
            trade_list = trades
        else:
            trade_list = list(trades)

        if verbose:
            print(f"\n  [Regime-Aware] Training on {len(trade_list)} trades...")

        if verbose:
            print(f"  [v4] Single model mode — regime used as feature, not separate models")
        rc_stats = self.regime_classifier.train(market_data, verbose=verbose)
        global_stats = self.global_model.train(trade_list, market_data)
        self.training_stats["global"] = global_stats
        for regime in Regime:
            self.regime_models[regime] = self.global_model
            self.training_stats[REGIME_NAMES[regime]] = {"status": "single_model"}
        self.is_trained = self.global_model.is_trained
        self._regime_trade_counts = {"ALL": len(trade_list)}
        return self.training_stats

    def predict(self, row: pd.Series, eligible_strategies: list[str] | None = None) -> dict:
        """Classify regime, then use global model (single-model architecture)."""
        regime = self.regime_classifier.predict(row)
        model = self.global_model

        prediction = model.predict(row, eligible_strategies=eligible_strategies)
        prediction["regime"] = REGIME_NAMES[regime]
        prediction["regime_probas"] = self.regime_classifier.predict_proba(row)
        prediction["used_global_fallback"] = (model is self.global_model and
                                               regime in self.regime_models and
                                               self.regime_models[regime] is not self.global_model)

        regime_name = REGIME_NAMES[regime]
        regime_threshold = TradeLearner.REGIME_QUALITY_THRESHOLDS.get(
            regime_name, TradeLearner.DEFAULT_QUALITY_THRESHOLD
        )
        quality_score = prediction.get("quality_score", 0)
        if quality_score < regime_threshold:
            prediction["should_enter"] = False
            prediction["signal"] = "AVOID"
        prediction["regime_quality_threshold"] = regime_threshold

        return prediction

    def predict_strategy(self, row: pd.Series,
                         eligible_strategies: list[str] | None = None) -> dict:
        """Regime-aware strategy selection."""
        regime = self.regime_classifier.predict(row)
        result = self.global_model.predict_strategy(row, eligible_strategies=eligible_strategies)
        result["regime"] = REGIME_NAMES[regime]
        return result

    def predict_optimal_params(self, row: pd.Series) -> dict:
        """Route to global model's parameter prediction."""
        regime = self.regime_classifier.predict(row)
        result = self.global_model.predict_optimal_params(row)
        result["regime"] = REGIME_NAMES[regime]
        return result

    def print_training_report(self):
        """Print detailed per-regime training report."""
        if not self.is_trained:
            print("  Model not trained yet.")
            return

        version_tag = f" [{self.model_version}]"
        print(f"\n  {'='*80}")
        print(f"  REGIME-AWARE ML MODEL TRAINING REPORT{version_tag}")
        print(f"  {'='*80}")

        # Regime distribution
        print(f"\n  Trade Distribution by Regime:")
        for regime_name, count in self._regime_trade_counts.items():
            bar = "#" * min(50, count // 10)
            print(f"    {regime_name:>10s}: {count:>5d} {bar}")

        # Per-regime model quality
        print(f"\n  Per-Regime Model Quality:")
        print(f"  {'Regime':<12s} {'Status':<15s} {'CV Accuracy':>12s} {'Trades':>8s} {'Winners':>8s} {'Losers':>8s}")
        print(f"  {'-'*70}")

        for regime in Regime:
            name = REGIME_NAMES[regime]
            stats = self.training_stats.get(name, {})
            status = stats.get("status", "trained")
            if status in ("global_fallback", "train_failed"):
                print(f"  {name:<12s} {'FALLBACK':<15s} {'(global)':>12s} {stats.get('trades', 0):>8d}")
            else:
                cv = stats.get("cv_auc", stats.get("cv_accuracy", 0))
                trades = stats.get("num_trades", 0)
                good = stats.get("num_quality_positive", stats.get("num_winners", 0))
                bad = stats.get("num_quality_negative", stats.get("num_losers", 0))
                print(f"  {name:<12s} {'SPECIALIZED':<15s} {cv:>11.3f} {trades:>8d} {good:>8d} {bad:>8d}")

        g = self.training_stats.get("global", {})
        if g:
            print(f"\n  Global baseline: CV AUC={g.get('cv_auc', g.get('cv_accuracy', 0)):.3f}, "
                  f"{g.get('num_trades', 0)} trades")

        # Feature importance per regime
        for regime in Regime:
            name = REGIME_NAMES[regime]
            stats = self.training_stats.get(name, {})
            fi = stats.get("feature_importance", {})
            if fi and stats.get("status") not in ("global_fallback", "train_failed"):
                print(f"\n  Top features for {name}:")
                for feat, imp in list(fi.items())[:5]:
                    bar = "#" * int(imp * 100)
                    print(f"    {feat:<35s} {imp:>6.1%} {bar}")

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(
        self,
        path: Path | str = MODEL_CACHE_PATH,
        *,
        period_metadata: ModelPeriodMetadata | None = None,
    ) -> None:
        """Persist fitted sklearn models and metadata to disk (no DataFrames)."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        gm = self.global_model
        self.period_metadata = period_metadata
        state = {
            "_saved_at": datetime.datetime.now().isoformat(),
            "model_version": self.model_version,
            "is_trained": self.is_trained,
            "training_stats": self.training_stats,
            "_regime_trade_counts": self._regime_trade_counts,
            "period_metadata": period_metadata.__dict__ if period_metadata else None,
            # RegimeClassifier
            "regime_clf_model": self.regime_classifier.model,
            "regime_clf_is_trained": self.regime_classifier.is_trained,
            "regime_clf_stats": self.regime_classifier.training_stats,
            # Global TradeLearner (sklearn objects only)
            "global_quality_clf": gm.quality_classifier,
            "global_return_reg": gm.return_regressor,
            "global_per_strategy_regs": gm.per_strategy_regressors,
            "global_selected_features": gm.selected_features,
            "global_feature_importance": gm.feature_importance,
            "global_label_threshold": gm.label_threshold,
            "global_training_stats": gm.training_stats,
            "global_strategy_stats": gm.strategy_stats,
            "global_learned_rules": gm.learned_rules,
            "global_macro_insights": gm.macro_insights,
            "global_model_version": gm.model_version,
            "global_regime_aucs": gm.regime_aucs,
        }
        joblib.dump(state, path)
        logger.info("Entry model saved to %s", path)

    @classmethod
    def load(cls, market_data: pd.DataFrame,
             path: Path | str = MODEL_CACHE_PATH,
             *,
             expected_metadata: ModelPeriodMetadata | None = None,
             signal_date: datetime.date | None = None,
             require_period_metadata: bool = False) -> "RegimeAwareLearner":
        """
        Load a previously saved entry model.  Raises FileNotFoundError if the
        cache is missing — caller should direct the user to run --mode evolve.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(
                f"Entry model cache not found at {path}.\n"
                "Run  python main.py --mode evolve  to train and save models first."
            )
        state = joblib.load(path)
        period_metadata = metadata_from_state(state)
        if require_period_metadata and period_metadata is None:
            raise ValueError(f"Entry model cache at {path} is missing period metadata.")
        if expected_metadata is not None:
            if period_metadata is None:
                raise ValueError(f"Entry model cache at {path} cannot be verified against expected metadata.")
            period_metadata.assert_matches(expected_metadata)
        if signal_date is not None:
            if period_metadata is None:
                raise ValueError(f"Entry model cache at {path} cannot be proven out-of-sample for {signal_date}.")
            period_metadata.assert_usable_for(signal_date)
        learner = cls(model_version=state["model_version"])

        # Restore RegimeClassifier
        learner.regime_classifier.model = state["regime_clf_model"]
        learner.regime_classifier.is_trained = state["regime_clf_is_trained"]
        learner.regime_classifier.training_stats = state["regime_clf_stats"]

        # Restore global TradeLearner
        gm = learner.global_model
        gm.quality_classifier = state["global_quality_clf"]
        gm.return_regressor = state["global_return_reg"]
        gm.per_strategy_regressors = state["global_per_strategy_regs"]
        gm.selected_features = state["global_selected_features"]
        gm.feature_importance = state["global_feature_importance"]
        gm.label_threshold = state["global_label_threshold"]
        gm.training_stats = state["global_training_stats"]
        gm.strategy_stats = state["global_strategy_stats"]
        gm.learned_rules = state["global_learned_rules"]
        gm.macro_insights = state["global_macro_insights"]
        gm.model_version = state["global_model_version"]
        gm.regime_aucs = state.get("global_regime_aucs", {})
        gm.feature_extractor = FeatureExtractor(market_data)
        gm.is_trained = True

        # All regime models point to global (single-model architecture)
        for regime in Regime:
            learner.regime_models[regime] = gm

        learner.is_trained = state["is_trained"]
        learner.training_stats = state["training_stats"]
        learner._regime_trade_counts = state.get("_regime_trade_counts", {})
        learner.period_metadata = period_metadata
        return learner

    @staticmethod
    def cache_age_days(path: Path | str = MODEL_CACHE_PATH) -> int | None:
        path = Path(path)
        if not path.exists():
            return None
        try:
            state = joblib.load(path)
            saved_at = datetime.datetime.fromisoformat(state["_saved_at"])
            return (datetime.datetime.now() - saved_at).days
        except Exception:
            return None
