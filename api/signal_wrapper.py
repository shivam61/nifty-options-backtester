"""
Wraps model predictions and position sizing into JSON-safe dicts.
Provides helper functions to serialize ML outputs from:
  - RegimeAwareLearner.predict() → entry signal
  - PositionSizer.compute_lots() → position sizing
  - RegimeAdaptiveStrategy.get_eligible_strategies() → strategy shortlist
"""

from typing import Dict, List, Any, Optional
from datetime import datetime, time as datetime_time
import pandas as pd


def wrap_regime_aware_signal(
    prediction_dict: Dict[str, Any],
    spot: float,
    vix: float,
    regime: str,
    eligible_strategies: List[str]
) -> Dict[str, Any]:
    """
    Wrap RegimeAwareLearner.predict() output into JSON-safe signal format.

    prediction_dict should have keys like:
      - 'quality_score': float (0-1)
      - 'signal': str (STRONG_ENTRY, MODERATE_ENTRY, CAUTION_ENTRY, AVOID)
      - 'strategy': str or None
      - 'macro_context': list[str]
      - 'reasoning': str or list[str]
    """
    quality_score = float(prediction_dict.get("quality_score", 0.0))
    signal_str = prediction_dict.get("signal", "AVOID")
    recommended_strategy = prediction_dict.get("strategy")
    macro_context = prediction_dict.get("macro_context", [])
    reasoning = prediction_dict.get("reasoning", [])

    # Flatten reasoning if string
    if isinstance(reasoning, str):
        reasoning = [reasoning]

    return {
        "quality_score": quality_score,
        "signal": signal_str,
        "recommended_strategy": recommended_strategy,
        "eligible_strategies": eligible_strategies,
        "regime": regime,
        "spot": spot,
        "vix": vix,
        "macro_context": macro_context if isinstance(macro_context, list) else [macro_context],
        "reasoning": reasoning if isinstance(reasoning, list) else [reasoning]
    }


def wrap_position_sizing(
    sizing_decision: Any,  # PositionSizer.SizingDecision dataclass
    available_capital: float,
    initial_capital: float
) -> Dict[str, Any]:
    """
    Wrap PositionSizer.compute_lots() output into JSON-safe format.

    sizing_decision should be a SizingDecision with attributes:
      - lots: int
      - base_lots: int
      - confidence_scale: float
      - regime_scale: float
      - dd_scale: float
      - reason: str
    """
    lots = getattr(sizing_decision, "lots", 0)
    base_lots = getattr(sizing_decision, "base_lots", 0)
    confidence_scale = float(getattr(sizing_decision, "confidence_scale", 1.0))
    regime_scale = float(getattr(sizing_decision, "regime_scale", 1.0))
    dd_scale = float(getattr(sizing_decision, "dd_scale", 1.0))
    reason = getattr(sizing_decision, "reason", "")

    # Assume 65 nifty spot as 1 lot
    margin_per_lot = 500_000 / 65  # approx ₹7692 per lot
    capital_to_deploy = lots * margin_per_lot

    return {
        "suggested_lots": int(lots),
        "base_lots": int(base_lots),
        "confidence_scale": confidence_scale,
        "regime_scale": regime_scale,
        "dd_scale": dd_scale,
        "available_capital": available_capital,
        "capital_to_deploy": capital_to_deploy,
        "capital_to_deploy_pct": (capital_to_deploy / initial_capital * 100) if initial_capital > 0 else 0.0,
        "reason": reason
    }


def wrap_entry_signal_for_track(
    track_name: str,  # "weekly" or "monthly"
    prediction: Dict[str, Any],
    sizing: Dict[str, Any],
    available_capital: float,
    entry_threshold: float,
    dte_window: str = "3–8",
    skip_reason: Optional[str] = None
) -> Dict[str, Any]:
    """
    Wrap entry decision for a single track (weekly or monthly).

    Returns:
      {
        "should_enter": bool,
        "quality_score": float,
        "signal": str,
        "recommended_strategy": str or None,
        "suggested_lots": int,
        "available_capital": float,
        "capital_to_deploy": float,
        "dte_window": str,
        "skip_reason": str or None
      }
    """
    quality_score = prediction.get("quality_score", 0.0)
    should_enter = (
        quality_score >= entry_threshold
        and prediction.get("signal") != "AVOID"
        and skip_reason is None
    )

    return {
        "should_enter": should_enter,
        "quality_score": quality_score,
        "signal": prediction.get("signal", "AVOID"),
        "recommended_strategy": prediction.get("recommended_strategy"),
        "suggested_lots": sizing.get("suggested_lots", 0),
        "available_capital": available_capital,
        "capital_to_deploy": sizing.get("capital_to_deploy", 0.0),
        "dte_window": dte_window,
        "skip_reason": skip_reason,
        "eligible_strategies": prediction.get("eligible_strategies", [])
    }


def wrap_full_signal_response(
    spot: float,
    vix: float,
    regime: str,
    weekly_signal: Dict[str, Any],
    monthly_signal: Dict[str, Any],
    macro_context: List[str],
    reasoning: List[str],
    within_entry_window: bool
) -> Dict[str, Any]:
    """
    Wrap complete signal response for /signal endpoint.

    Returns full JSON with both weekly and monthly tracks.
    """
    return {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "within_entry_window": within_entry_window,
        "spot": float(spot),
        "vix": float(vix),
        "regime": regime,
        "weekly": weekly_signal,
        "monthly": monthly_signal,
        "macro_context": macro_context if isinstance(macro_context, list) else [macro_context],
        "reasoning": reasoning if isinstance(reasoning, list) else [reasoning]
    }


def wrap_active_trade(
    trade: Any,  # ActiveTrade dataclass from models/trade_monitor.py
    current_ltp_dict: Dict[str, float],  # {"strike_type": ltp, ...}
    entry_credit_per_unit: float = 0.0
) -> Dict[str, Any]:
    """
    Wrap ActiveTrade dataclass into JSON-safe dict.

    Assumes trade has:
      - trade_id: str
      - entry_date: date
      - expiry_date: date
      - strategy_code: str
      - legs: list[TradeLeg]
      - current_pnl: float (optional, computed here if not provided)

    current_ltp_dict maps leg keys to live LTP values.
    """
    from datetime import date as date_class

    legs_data = []
    for leg in getattr(trade, "legs", []):
        leg_key = f"{leg.option_type}_{leg.strike}"
        current_ltp = current_ltp_dict.get(leg_key, leg.entry_price)

        leg_dict = {
            "action": leg.action,
            "strike": float(leg.strike),
            "option_type": leg.option_type,
            "qty": int(leg.qty),
            "entry_price": float(leg.entry_price),
            "current_ltp": float(current_ltp)
        }
        legs_data.append(leg_dict)

    # Compute days in trade
    today = date_class.today()
    entry_date = getattr(trade, "entry_date", today)
    if isinstance(entry_date, str):
        from datetime import datetime as dt
        entry_date = dt.strptime(entry_date, "%Y-%m-%d").date()
    days_in_trade = (today - entry_date).days

    # Compute DTE remaining
    expiry_date = getattr(trade, "expiry_date", today)
    if isinstance(expiry_date, str):
        from datetime import datetime as dt
        expiry_date = dt.strptime(expiry_date, "%Y-%m-%d").date()
    dte_remaining = (expiry_date - today).days

    # Compute estimated P&L (simple sum of leg P&Ls)
    estimated_pnl = 0.0
    for leg, leg_data in zip(getattr(trade, "legs", []), legs_data):
        if leg.action == "SELL":
            leg_pnl = (leg_data["entry_price"] - leg_data["current_ltp"]) * leg_data["qty"]
        else:  # BUY
            leg_pnl = (leg_data["current_ltp"] - leg_data["entry_price"]) * leg_data["qty"]
        estimated_pnl += leg_pnl

    return {
        "trade_id": str(getattr(trade, "trade_id", "UNKNOWN")),
        "journal_id": str(getattr(trade, "journal_id", "default")),
        "entry_date": str(entry_date),
        "expiry_date": str(expiry_date),
        "strategy_code": str(getattr(trade, "strategy_code", "")),
        "legs": legs_data,
        "entry_credit_per_unit": float(entry_credit_per_unit),
        "days_in_trade": int(days_in_trade),
        "dte_remaining": int(dte_remaining),
        "estimated_pnl": float(estimated_pnl),
        "notes": str(getattr(trade, "notes", ""))
    }


def wrap_exit_recommendation(
    recommendation: Any,  # ExitRecommendation dataclass from models/trade_monitor.py
    trade_id: str
) -> Dict[str, Any]:
    """
    Wrap ExitStrategyEngine.analyze_trade() output into JSON-safe dict.

    Assumes recommendation has:
      - action: str (HOLD, BOOK_PROFIT, EXIT_NOW, TRAIL_STOP, PARTIAL_EXIT)
      - confidence: float (0-1)
      - current_pnl_pct: float
      - pnl_rupees: float
      - risk_score: float (0-1)
      - reasoning: list[str] or str
      - per_leg_pnl: list[dict] (optional)
      - partial_exit_legs: list[str] (optional)
    """
    reasoning = getattr(recommendation, "reasoning", [])
    if isinstance(reasoning, str):
        reasoning = [reasoning]

    per_leg_pnl = getattr(recommendation, "per_leg_pnl", [])
    if per_leg_pnl is None:
        per_leg_pnl = []

    return {
        "trade_id": trade_id,
        "action": str(getattr(recommendation, "action", "HOLD")),
        "confidence": float(getattr(recommendation, "confidence", 0.5)),
        "current_pnl_pct": float(getattr(recommendation, "current_pnl_pct", 0.0)),
        "pnl_rupees": float(getattr(recommendation, "pnl_rupees", 0.0)),
        "days_in_trade": int(getattr(recommendation, "days_in_trade", 0)),
        "dte_remaining": int(getattr(recommendation, "dte_remaining", 0)),
        "risk_score": float(getattr(recommendation, "risk_score", 0.0)),
        "theta_per_day": float(getattr(recommendation, "theta_per_day", 0.0)),
        "reasoning": reasoning if isinstance(reasoning, list) else [reasoning],
        "per_leg_pnl": per_leg_pnl if isinstance(per_leg_pnl, list) else [],
        "partial_exit_legs": getattr(recommendation, "partial_exit_legs", None)
    }
