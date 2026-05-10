"""
EntryDecisionEngine — single authoritative entry gate shared by backtest,
signal, and any future execution mode.

All four steps of the entry decision live here:
  1. Cooldown (inter-trade gap enforcement)
  2. Circuit breaker (regime-adaptive eligibility filter)
  3. ML quality filter + loss-streak threshold bump
  4. PCS quality floor + strategy force-activation

Both SmartBacktestEngine and run_signal() instantiate this class and call
check(), so the logic is guaranteed to be identical across modes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class EntryDecision:
    """Result returned by EntryDecisionEngine.check()."""

    should_enter: bool
    recommended_strategy: Optional[str] = None
    quality_score: float = 0.0
    win_prob: float = 0.0
    eligible_strategies: list = field(default_factory=list)
    strategy_scores: dict = field(default_factory=dict)
    # Raw dict from entry_model.predict() — used by signal mode for display
    ml_prediction: dict = field(default_factory=dict)
    # Dict from entry_model.predict_strategy() — richer display info
    strat_rec: dict = field(default_factory=dict)
    # Why entry was blocked (None if allowed)
    skip_reason: Optional[str] = None


class EntryDecisionEngine:
    """
    Single authoritative entry gate used by backtest, signal, and monitor.

    Instantiate once per run (backtest) or once per signal call (signal mode)
    and call check() for each candidate entry date.  After each trade closes,
    call record_outcome() to keep the loss-streak counter accurate.
    """

    PCS_QUALITY_FLOOR = 0.60

    def __init__(
        self,
        entry_model,
        strategy,
        entry_threshold: float = 0.48,
        cooldown_days: int = 2,
        max_loss_streak: int = 3,
        loss_streak_bump: float = 0.03,
    ):
        self.entry_model = entry_model
        self.strategy = strategy
        self.entry_threshold = entry_threshold
        self.cooldown_days = cooldown_days
        self.max_loss_streak = max_loss_streak
        self.loss_streak_bump = loss_streak_bump

        # Mutable state — updated across check() calls
        self._last_entry_date = None
        self._consecutive_losses: int = 0

        # Cumulative counters (read by SmartBacktestEngine for reporting)
        self.ml_skip_count: int = 0
        self.ml_entry_count: int = 0
        self.cooldown_skips: int = 0
        self.loss_streak_skips: int = 0
        self.skip_reasons: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check(self, row, spot: float, vix: float, market_data: dict) -> EntryDecision:
        """
        Run the full entry gate and return an EntryDecision.

        Flow:
          1. Cooldown: skip if last entry was < cooldown_days ago
          2. Circuit breaker: eligible_strategies empty → skip
          3. ML quality filter (+ loss-streak threshold bump)
          4. PCS quality floor → swap to next-best strategy if needed
          5. Force-activate the chosen strategy on the regime-adaptive engine
        """
        try:
            return self._check(row, spot, vix, market_data)
        except Exception:
            logger.exception("EntryDecisionEngine.check() failed; falling back to rule-based entry")
            return self._rule_based_fallback(spot, vix, market_data)

    def record_outcome(self, was_win: bool) -> None:
        """Update the loss-streak counter after a trade closes."""
        if was_win:
            self._consecutive_losses = 0
        else:
            self._consecutive_losses += 1

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check(self, row, spot: float, vix: float, market_data: dict) -> EntryDecision:
        current_date = row.name if hasattr(row, "name") else None

        # Step 1 — Cooldown
        if current_date and self._last_entry_date and self.cooldown_days > 0:
            days_since = (current_date - self._last_entry_date).days
            if days_since < self.cooldown_days:
                return self._skip("cooldown")

        # Step 2 — Circuit breaker
        eligible: list[str] = []
        if hasattr(self.strategy, "get_eligible_strategies"):
            eligible = self.strategy.get_eligible_strategies(spot, vix, market_data)
            if not eligible:
                return self._skip("circuit_breaker", eligible_strategies=[])

        # Step 3 — ML prediction + quality threshold
        prediction = self.entry_model.predict(row, eligible_strategies=eligible or None)
        quality_score = prediction.get("quality_score", 0.0)
        win_prob = prediction.get("probability_profitable", quality_score)
        strategy_scores = prediction.get("strategy_scores", {})
        ml_strat = prediction.get("recommended_strategy")

        model_threshold = self._model_recommended_threshold()
        effective_threshold = model_threshold if model_threshold is not None else self.entry_threshold
        if self._consecutive_losses >= self.max_loss_streak:
            effective_threshold += self.loss_streak_bump
        regime_threshold = prediction.get("regime_quality_threshold", effective_threshold)
        effective_threshold = max(effective_threshold, regime_threshold)

        if quality_score < effective_threshold:
            if self._consecutive_losses >= self.max_loss_streak:
                self.loss_streak_skips += 1
            return self._skip(
                "quality_threshold",
                quality_score=quality_score,
                win_prob=win_prob,
                eligible_strategies=eligible,
                strategy_scores=strategy_scores,
                ml_prediction=prediction,
            )

        if not ml_strat or ml_strat == "no_trade":
            return self._skip(
                "no_viable_strategy",
                quality_score=quality_score,
                win_prob=win_prob,
                eligible_strategies=eligible,
                strategy_scores=strategy_scores,
                ml_prediction=prediction,
            )

        # Step 4 — PCS quality floor
        if ml_strat == "put_credit_spread" and quality_score < self.PCS_QUALITY_FLOOR:
            non_pcs = [s for s in eligible if s != "put_credit_spread"]
            if not non_pcs:
                return self._skip(
                    "pcs_floor_no_alternative",
                    quality_score=quality_score,
                    win_prob=win_prob,
                    eligible_strategies=eligible,
                    strategy_scores=strategy_scores,
                    ml_prediction=prediction,
                )
            ml_strat = max(
                non_pcs,
                key=lambda s: strategy_scores.get(s, {}).get("composite_score", 0.0),
            )

        # Enrich with predict_strategy() for richer display in signal mode
        strat_rec: dict = {}
        if hasattr(self.entry_model, "predict_strategy"):
            try:
                strat_rec = self.entry_model.predict_strategy(
                    row, eligible_strategies=eligible or None
                )
                # Ensure recommended_strategy from floor-check overrides strat_rec
                if ml_strat and ml_strat != strat_rec.get("strategy"):
                    strat_rec["strategy"] = ml_strat
            except Exception:
                logger.debug("predict_strategy() failed; strat_rec will be empty")

        # Step 5 — Force-activate strategy on the regime-adaptive engine
        chosen_strat = ml_strat
        if chosen_strat and hasattr(self.strategy, "force_strategy_selection"):
            if self.strategy.force_strategy_selection(chosen_strat):
                self.ml_entry_count += 1
                if current_date:
                    self._last_entry_date = current_date
                return EntryDecision(
                    should_enter=True,
                    recommended_strategy=chosen_strat,
                    quality_score=quality_score,
                    win_prob=win_prob,
                    eligible_strategies=eligible,
                    strategy_scores=strategy_scores,
                    ml_prediction=prediction,
                    strat_rec=strat_rec,
                )

        # Fallback — try eligible strategies ranked by composite score
        if eligible:
            ranked = sorted(
                eligible,
                key=lambda s: strategy_scores.get(s, {}).get("composite_score", float("-inf")),
                reverse=True,
            )
            for fallback_strat in ranked:
                if strategy_scores.get(fallback_strat, {}).get("composite_score", float("-inf")) <= 0:
                    continue
                if fallback_strat == "put_credit_spread" and quality_score < self.PCS_QUALITY_FLOOR:
                    continue
                if hasattr(self.strategy, "force_strategy_selection"):
                    if self.strategy.force_strategy_selection(fallback_strat):
                        self.ml_entry_count += 1
                        if current_date:
                            self._last_entry_date = current_date
                        return EntryDecision(
                            should_enter=True,
                            recommended_strategy=fallback_strat,
                            quality_score=quality_score,
                            win_prob=win_prob,
                            eligible_strategies=eligible,
                            strategy_scores=strategy_scores,
                            ml_prediction=prediction,
                            strat_rec=strat_rec,
                        )

        return self._skip(
            "no_strategy_activated",
            quality_score=quality_score,
            win_prob=win_prob,
            eligible_strategies=eligible,
            strategy_scores=strategy_scores,
            ml_prediction=prediction,
            strat_rec=strat_rec,
        )

    def _rule_based_fallback(self, spot: float, vix: float, market_data: dict) -> EntryDecision:
        """Used only if check() itself raises an unexpected exception."""
        from strategies.base import TradeAction

        if hasattr(self.strategy, "get_eligible_strategies"):
            eligible = self.strategy.get_eligible_strategies(spot, vix, market_data)
            if not eligible:
                return EntryDecision(should_enter=False, skip_reason="circuit_breaker")
        action = self.strategy.should_enter(spot, vix, market_data)
        return EntryDecision(should_enter=(action == TradeAction.ENTER))

    def _skip(self, reason: str, **kwargs) -> EntryDecision:
        self.ml_skip_count += 1
        self.skip_reasons[reason] = self.skip_reasons.get(reason, 0) + 1
        if reason == "cooldown":
            self.cooldown_skips += 1
        return EntryDecision(should_enter=False, skip_reason=reason, **kwargs)

    def _model_recommended_threshold(self) -> float | None:
        stats = getattr(self.entry_model, "training_stats", None)
        if not isinstance(stats, dict):
            return None
        if "recommended_threshold" in stats:
            try:
                return float(stats["recommended_threshold"])
            except Exception:
                return None
        global_stats = stats.get("global", {})
        if isinstance(global_stats, dict) and "recommended_threshold" in global_stats:
            try:
                return float(global_stats["recommended_threshold"])
            except Exception:
                return None
        return None
