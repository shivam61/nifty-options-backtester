"""
Unified Exit Decision Engine.

Single source of truth for exit logic used by BOTH:
  - Backtester engine (_smart_exit_check + strategy.should_exit)
  - Monitor mode (live trades with real-time prices)

Design:
  1. Live price fetching stays in monitor (Fyers API) — this module doesn't touch prices.
  2. Exit DECISION logic lives here — called by both backtest and monitor.
  3. strategy.should_exit() remains the core exit check (includes 85% max profit booking).
  4. _smart_exit_check() wraps strategy with engine-level guards (capital protection, crash detection).

Usage in monitor:
    from exits.unified import evaluate_exit

    decision = evaluate_exit(
        strategy=strategy,
        trade_adapter=trade_adapter,   # wraps ActiveTrade to look like backtest Trade
        spot=live_spot,
        vix=live_vix,
        dte=dte_remaining,
        market_data=latest_row,        # for VIX-adaptive and crash signals
        equity=current_equity,         # for capital protection
        exit_engine=exit_engine,       # optional ML exit model
    )
"""

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from strategies.base import TradeAction, ExitReason


@dataclass
class ExitDecision:
    """Result of the unified exit evaluation."""
    should_exit: bool
    action: str          # HOLD, BOOK_PROFIT, EXIT_NOW, TRAIL_STOP
    reason: Optional[str]
    exit_reason: Optional[ExitReason]
    confidence: float    # 0.0 to 1.0
    reasoning: list[str]
    risk_score: float    # 0.0 (safe) to 1.0 (danger)
    source: str          # "strategy", "engine_smart", "ml_override"


class TradeAdapter:
    """
    Adapter that makes an ActiveTrade (monitor) look like a backtest Trade
    so strategy.should_exit() can work on it.

    The key fields strategy.should_exit() needs:
      - pnl_per_unit
      - net_credit
      - legs (with is_short, option_type, strike)
      - entry_date
      - entry_vix
      - total_pnl
      - max_risk
    """

    def __init__(self, active_trade, live_pnl_total: float, live_pnl_per_unit: float,
                 entry_vix: float = 15.0, peak_pnl_per_unit: float = 0.0):
        self._trade = active_trade
        self._live_pnl_total = live_pnl_total
        self._live_pnl_per_unit = live_pnl_per_unit
        self._entry_vix = entry_vix

        # Pre-seed the max profit tracker so strategy's 85% rule works
        # in a single call (monitor calls should_exit once per run, not in a loop)
        self._max_profit_per_unit = max(peak_pnl_per_unit, live_pnl_per_unit)

        self._legs = []
        for leg in active_trade.get_legs():
            self._legs.append(_LegAdapter(leg))

    @property
    def pnl_per_unit(self):
        return self._live_pnl_per_unit

    @property
    def net_credit(self):
        return self._trade.net_entry_credit_per_unit

    @property
    def total_pnl(self):
        return self._live_pnl_total

    @property
    def legs(self):
        return self._legs

    @property
    def entry_date(self):
        from datetime import date as _date
        return _date.fromisoformat(self._trade.entry_date)

    @property
    def entry_vix(self):
        return self._entry_vix

    @property
    def max_risk(self):
        return self._trade.max_loss_total

    @property
    def strategy_name(self):
        return self._trade.strategy_name


class _LegAdapter:
    """Makes a monitor TradeLeg look like a backtest Leg."""

    def __init__(self, trade_leg):
        self._leg = trade_leg
        self.strike = trade_leg.strike
        self.option_type = trade_leg.option_type
        self.is_short = trade_leg.is_short


def evaluate_exit(
    strategy,
    trade_adapter: TradeAdapter,
    spot: float,
    vix: float,
    dte: int,
    market_data: Optional[pd.Series] = None,
    equity: float = 500_000.0,
    exit_engine=None,
    entry_spot: float = 0.0,
    entry_vix: float = 0.0,
    peak_pnl_per_unit: float = 0.0,
    pnl_history: Optional[list] = None,
) -> ExitDecision:
    """
    Unified exit evaluation — same logic as backtester.

    Calls the SAME exit checks in the SAME order as the backtest engine:
    1. Capital protection (6% max loss)
    2. VIX-adaptive profit/stop targets
    3. Trailing stop (35% drop from peak)
    4. ML override (if model available)
    5. strategy.should_exit() (includes 85% max profit booking)

    Args:
        strategy: The strategy instance (PCS/IC/RegimeAdaptive) — same as backtest
        trade_adapter: TradeAdapter wrapping the ActiveTrade
        spot: Current Nifty spot (live from Fyers or latest close)
        vix: Current India VIX
        dte: Days to expiry
        market_data: Latest market data row (for crash signals, VIX SMA, etc.)
        equity: Current portfolio equity (for capital protection)
        exit_engine: Optional trained ExitStrategyEngine (ML model)
        entry_spot: Spot at trade entry (for VIX change calc)
        entry_vix: VIX at trade entry
        peak_pnl_per_unit: Max P&L per unit seen during trade lifetime
        pnl_history: List of historical pnl_per_unit values (for velocity calc)

    Returns:
        ExitDecision with should_exit, action, reasoning, etc.
    """
    trade = trade_adapter
    reasoning = []
    risk_score = 0.0

    net_credit = trade.net_credit
    pnl_per_unit = trade.pnl_per_unit
    if pnl_history is None:
        pnl_history = []

    if net_credit <= 0:
        return ExitDecision(
            should_exit=False, action="HOLD", reason=None,
            exit_reason=None, confidence=0.3, reasoning=["Net credit <= 0, skipping checks"],
            risk_score=0.0, source="engine_smart",
        )

    pnl_pct = (pnl_per_unit / net_credit * 100)

    # Track peak for this evaluation
    if pnl_per_unit > peak_pnl_per_unit:
        peak_pnl_per_unit = pnl_per_unit
    pnl_from_peak = pnl_per_unit - peak_pnl_per_unit

    # ── 1. CAPITAL PROTECTION (6% max loss) ──
    max_loss_pct_of_capital = 0.06
    max_loss_abs = equity * max_loss_pct_of_capital
    if trade.total_pnl < -max_loss_abs:
        reasoning.insert(0, f"Loss ₹{abs(trade.total_pnl):,.0f} exceeds 6% of equity (₹{max_loss_abs:,.0f}) — capital protection")
        return ExitDecision(
            should_exit=True, action="EXIT_NOW", reason="capital_protection",
            exit_reason=ExitReason.STOP_LOSS, confidence=0.95,
            reasoning=reasoning, risk_score=1.0, source="engine_smart",
        )

    # ── Gather market signals ──
    vix_change = (vix - entry_vix) / entry_vix if entry_vix > 0 else 0
    days_in = trade_adapter._trade.days_in_trade

    short_legs = [l for l in trade.legs if l.is_short]
    min_dist = 999
    for sl in short_legs:
        if sl.option_type in ("PUT", "PE"):
            dist = (spot - sl.strike) / spot * 100
        else:
            dist = (sl.strike - spot) / spot * 100
        min_dist = min(min_dist, dist)

    crash_risk_v2 = 0
    vix_vs_sma = 1.0
    correction_depth = 0
    if market_data is not None:
        crash_risk_v2 = market_data.get("crash_risk_score_v2", 0) if hasattr(market_data, "get") else 0
        vix_vs_sma = market_data.get("vix_vs_sma_ratio", 1.0) if hasattr(market_data, "get") else 1.0
        correction_depth = market_data.get("nifty_drawdown_from_20d_high_pct", 0) if hasattr(market_data, "get") else 0

    # ── 2. VIX-ADAPTIVE PROFIT/STOP TARGETS ──
    if vix < 15:
        profit_target, stop_loss = 60, 80
    elif vix < 20:
        profit_target, stop_loss = 50, 65
    elif vix < 30:
        profit_target, stop_loss = 40, 55
    else:
        profit_target, stop_loss = 30, 45

    if vix_vs_sma and vix_vs_sma < 0.85:
        profit_target = int(profit_target * 1.15)
        stop_loss = int(stop_loss * 1.10)
    elif vix_vs_sma and vix_vs_sma > 1.15:
        stop_loss = int(stop_loss * 0.85)
        profit_target = int(profit_target * 0.90)

    if crash_risk_v2 >= 0.80 or correction_depth < -15:
        stop_loss = int(stop_loss * 0.7)
        profit_target = min(profit_target, 30)

    if dte <= 5:
        profit_target = min(profit_target, 30)

    # ── Build reasoning (informational) ──
    if dte <= 3:
        risk_score += 0.3
        reasoning.append(f"DTE={dte} — expiry imminent, gamma risk high")
    elif dte <= 7:
        risk_score += 0.15
        reasoning.append(f"DTE={dte} — approaching expiry")

    if pnl_pct >= 50:
        reasoning.append(f"P&L at +{pnl_pct:.0f}% of credit — strong profit")
    elif pnl_pct >= 0:
        reasoning.append(f"P&L at +{pnl_pct:.0f}% of credit")
    elif pnl_pct > -30:
        risk_score += 0.15
        reasoning.append(f"P&L at {pnl_pct:.0f}% — underwater but recoverable")
    else:
        risk_score += 0.3
        reasoning.append(f"P&L at {pnl_pct:.0f}% — significant loss")

    if min_dist < 2:
        risk_score += 0.15 if min_dist >= 1 else 0.3
        reasoning.append(f"Closest short strike {min_dist:.1f}% away — {'DANGER' if min_dist < 1 else 'getting close'}")
    elif min_dist > 5:
        reasoning.append(f"Closest short strike {min_dist:.1f}% away — comfortable")

    if vix > 25:
        risk_score += 0.1
        reasoning.append(f"VIX at {vix:.1f} — elevated")
    if vix_vs_sma and vix_vs_sma > 1.15:
        risk_score += 0.15
        reasoning.append(f"VIX surging ({vix_vs_sma:.2f}x 10d avg)")

    # ── 3. HARD RULES (same as _smart_exit_check) ──

    # Strike proximity danger
    if min_dist < 1.5 and pnl_pct < -5:
        reasoning.insert(0, f"Strike within {min_dist:.1f}% while losing — exit to limit damage")
        return ExitDecision(
            should_exit=True, action="EXIT_NOW", reason="strike_proximity",
            exit_reason=ExitReason.STOP_LOSS, confidence=0.9,
            reasoning=reasoning, risk_score=min(risk_score + 0.3, 1.0), source="engine_smart",
        )

    # VIX spike
    if vix_change > 0.25 and pnl_pct < -10:
        reasoning.insert(0, f"VIX jumped {vix_change:.0%} since entry while losing — exit")
        return ExitDecision(
            should_exit=True, action="EXIT_NOW", reason="vix_spike",
            exit_reason=ExitReason.STOP_LOSS, confidence=0.85,
            reasoning=reasoning, risk_score=min(risk_score + 0.2, 1.0), source="engine_smart",
        )

    # VIX trend surge
    if vix_vs_sma and vix_vs_sma > 1.20 and pnl_pct < -15:
        reasoning.insert(0, f"VIX surging above SMA while deep in loss — exit")
        return ExitDecision(
            should_exit=True, action="EXIT_NOW", reason="vix_trend",
            exit_reason=ExitReason.STOP_LOSS, confidence=0.85,
            reasoning=reasoning, risk_score=min(risk_score + 0.2, 1.0), source="engine_smart",
        )

    # Crash in progress
    if crash_risk_v2 >= 0.80 and pnl_pct < 0:
        reasoning.insert(0, f"Crash risk {crash_risk_v2:.2f} while losing — exit immediately")
        return ExitDecision(
            should_exit=True, action="EXIT_NOW", reason="crash_detection",
            exit_reason=ExitReason.STOP_LOSS, confidence=0.95,
            reasoning=reasoning, risk_score=1.0, source="engine_smart",
        )

    # VIX-adaptive profit target
    if pnl_pct >= profit_target:
        reasoning.insert(0, f"Profit {pnl_pct:.0f}% hit VIX-adaptive target ({profit_target}%) — book profit")
        return ExitDecision(
            should_exit=True, action="BOOK_PROFIT", reason="vix_adaptive_target",
            exit_reason=ExitReason.PROFIT_TARGET, confidence=0.8,
            reasoning=reasoning, risk_score=risk_score, source="engine_smart",
        )

    # VIX-adaptive stop loss
    if pnl_pct < -stop_loss:
        reasoning.insert(0, f"Loss {pnl_pct:.0f}% exceeds VIX-adaptive stop ({stop_loss}%) — cut losses")
        return ExitDecision(
            should_exit=True, action="EXIT_NOW", reason="vix_adaptive_stop",
            exit_reason=ExitReason.STOP_LOSS, confidence=0.8,
            reasoning=reasoning, risk_score=min(risk_score + 0.3, 1.0), source="engine_smart",
        )

    # ── 4. TRAILING STOP ──
    peak_pct = (peak_pnl_per_unit / net_credit * 100) if net_credit > 0 else 0
    drop_from_peak_pct = (pnl_from_peak / net_credit * 100) if net_credit > 0 else 0

    if peak_pct >= 25 and drop_from_peak_pct < -35:
        reasoning.insert(0, f"Profit dropped {drop_from_peak_pct:.0f}% from peak ({peak_pct:.0f}%) — trailing stop")
        return ExitDecision(
            should_exit=True, action="BOOK_PROFIT", reason="trailing_stop",
            exit_reason=ExitReason.PROFIT_TARGET, confidence=0.75,
            reasoning=reasoning, risk_score=risk_score, source="engine_smart",
        )

    if peak_pct >= 40 and drop_from_peak_pct < -20:
        reasoning.insert(0, f"Profit dropped {drop_from_peak_pct:.0f}% from peak ({peak_pct:.0f}%) — tight trailing stop")
        return ExitDecision(
            should_exit=True, action="BOOK_PROFIT", reason="trailing_stop_tight",
            exit_reason=ExitReason.PROFIT_TARGET, confidence=0.75,
            reasoning=reasoning, risk_score=risk_score, source="engine_smart",
        )

    # ── 5. ML OVERRIDE (only when model is confident and losing) ──
    ml_exit_prob = 0.5
    if exit_engine and exit_engine.is_trained and market_data is not None:
        try:
            from models.trade_learner import FeatureExtractor
            market_features = exit_engine.feature_extractor.extract(market_data)
            pnl_3d_ago = pnl_history[-3] if len(pnl_history) >= 3 else 0
            vix_1d_chg = market_data.get("vix_1d_change_pct", 0) if hasattr(market_data, "get") else 0
            trade_features = {
                "pnl_pct": pnl_pct, "dte_remaining": dte, "days_in_trade": days_in,
                "dist_to_short_strike_pct": min_dist, "vix_now": vix,
                "vix_change_since_entry": vix_change,
                "vix_vs_sma_ratio_now": vix_vs_sma if not pd.isna(vix_vs_sma) else 1.0,
                "vix_1d_change_now": vix_1d_chg if not pd.isna(vix_1d_chg) else 0.0,
                "spot_change_since_entry": (spot - entry_spot) / entry_spot * 100 if entry_spot > 0 else 0,
                "pnl_velocity": pnl_per_unit / max(days_in, 1),
                "credit_captured_pct": pnl_pct,
                "max_loss_proximity": abs(pnl_per_unit) / (net_credit * 3) if pnl_per_unit < 0 else 0,
                "theta_estimate": net_credit / max(dte + days_in, 1),
                "pnl_from_peak": pnl_from_peak,
                "pnl_velocity_3d": (pnl_per_unit - pnl_3d_ago) / 3 if days_in >= 3 else pnl_per_unit / max(days_in, 1),
                "days_since_peak": 0,
            }
            all_features = {**market_features, **trade_features}
            X = pd.DataFrame([all_features]).reindex(
                columns=exit_engine.exit_feature_cols, fill_value=0
            ).fillna(0).replace([float("inf"), float("-inf")], 0)
            probs = exit_engine.exit_classifier.predict_proba(X)[0]
            classes = list(exit_engine.exit_classifier.classes_)
            ml_exit_prob = probs[classes.index(1)] if 1 in classes else 0.0
            reasoning.append(f"ML exit probability: {ml_exit_prob:.0%}")

            if ml_exit_prob >= 0.75 and pnl_pct < -15:
                reasoning.insert(0, f"ML exit {ml_exit_prob:.0%} + deep loss — exit")
                return ExitDecision(
                    should_exit=True, action="EXIT_NOW", reason="ml_override",
                    exit_reason=ExitReason.STOP_LOSS, confidence=ml_exit_prob,
                    reasoning=reasoning, risk_score=min(risk_score + 0.3, 1.0), source="ml_override",
                )
        except Exception:
            pass

    # ── 6. STRATEGY EXIT (includes 85% max profit booking) ──
    # For RegimeAdaptiveStrategy: auto-select sub-strategy based on trade type
    _strategy_to_call = strategy
    if hasattr(strategy, '_active_strategy') and strategy._active_strategy is None:
        _name = trade_adapter.strategy_name
        _name_lower = _name.lower().replace(" ", "_")
        _mapping = {
            "put_credit_spread": "put_credit_spread",
            "iron_condor": "iron_condor",
            "broken_wing_butterfly": "broken_wing_butterfly",
            "bear_call_spread": "put_credit_wide",
            "calendar_spread": "calendar_spread",
        }
        for key, strat_key in _mapping.items():
            if key in _name_lower:
                if hasattr(strategy, 'force_strategy_selection'):
                    strategy.force_strategy_selection(strat_key)
                break
    try:
        action, reason = strategy.should_exit(trade_adapter, spot, vix, dte)
        if action == TradeAction.EXIT:
            reason_name = reason.name if hasattr(reason, "name") else str(reason)
            if reason == ExitReason.PROFIT_TARGET:
                action_str = "BOOK_PROFIT"
                reasoning.insert(0, f"Strategy exit: {reason_name} (includes 85% max profit booking)")
            elif reason == ExitReason.DTE_LIMIT:
                action_str = "EXIT_NOW"
                reasoning.insert(0, f"Strategy exit: DTE limit reached — expiry imminent")
            else:
                action_str = "EXIT_NOW"
                reasoning.insert(0, f"Strategy exit: {reason_name}")

            return ExitDecision(
                should_exit=True, action=action_str, reason=reason_name,
                exit_reason=reason, confidence=0.8,
                reasoning=reasoning, risk_score=risk_score, source="strategy",
            )
    except Exception:
        pass

    # ── 7. HOLD — no exit triggered ──
    reasoning.insert(0, "Trade on track — theta working, no immediate risk")
    confidence = abs(ml_exit_prob - 0.5) * 2 if ml_exit_prob != 0.5 else max(0.3, 1 - risk_score)

    return ExitDecision(
        should_exit=False, action="HOLD", reason=None,
        exit_reason=None, confidence=confidence,
        reasoning=reasoning, risk_score=risk_score, source="strategy",
    )
