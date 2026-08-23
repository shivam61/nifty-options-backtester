"""
Base strategy class and common data structures for all option strategies.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Optional


class TradeAction(Enum):
    ENTER = "enter"
    EXIT = "exit"
    ADJUST = "adjust"
    HOLD = "hold"
    NO_TRADE = "no_trade"


class ExitReason(Enum):
    PROFIT_TARGET = "profit_target"
    STOP_LOSS = "stop_loss"
    EXPIRY = "expiry"
    DTE_LIMIT = "dte_limit"
    MANUAL = "manual"
    ADJUSTMENT = "adjustment"
    MAX_DRAWDOWN = "max_drawdown"
    ROLL = "roll"
    TRAILING_DELTA = "trailing_delta"
    TREND_REVERSAL = "trend_reversal"
    MAX_HOLD_TIME = "max_hold_time"


@dataclass
class AdjustmentAction:
    """Describes a mid-trade adjustment (roll, add hedge, widen, etc.)."""
    action_type: str       # "roll_short", "roll_up", "roll_down", "add_hedge", "widen"
    legs_to_close: list    # indices into Trade.legs to close
    new_legs: list         # new Leg objects to add
    cost: float = 0.0      # net debit/credit of the adjustment
    reasoning: str = ""


@dataclass
class Leg:
    """Single option leg."""
    option_type: str  # "CE" or "PE"
    strike: float
    is_short: bool
    entry_premium: float = 0.0
    current_premium: float = 0.0
    lots: int = 1
    lot_size: int = 65
    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0

    @property
    def quantity(self) -> int:
        return self.lots * self.lot_size

    @property
    def entry_value(self) -> float:
        sign = -1 if self.is_short else 1
        return sign * self.entry_premium * self.quantity

    @property
    def current_value(self) -> float:
        sign = -1 if self.is_short else 1
        return sign * self.current_premium * self.quantity

    @property
    def pnl(self) -> float:
        if self.is_short:
            return (self.entry_premium - self.current_premium) * self.quantity
        else:
            return (self.current_premium - self.entry_premium) * self.quantity


@dataclass
class Trade:
    """Complete multi-leg trade."""
    strategy_name: str
    entry_date: date
    signal_date: Optional[date] = None
    exit_date: Optional[date] = None
    legs: list[Leg] = field(default_factory=list)
    entry_spot: float = 0.0
    entry_vix: float = 0.0
    exit_spot: float = 0.0
    exit_vix: float = 0.0
    exit_reason: Optional[ExitReason] = None
    lots: int = 1
    lot_size: int = 65
    roll_count: int = 0
    adjustment_history: list = field(default_factory=list)

    @property
    def net_credit(self) -> float:
        return sum(
            leg.entry_premium if leg.is_short else -leg.entry_premium for leg in self.legs
        )

    @property
    def current_debit(self) -> float:
        return sum(
            leg.current_premium if leg.is_short else -leg.current_premium for leg in self.legs
        )

    @property
    def pnl_per_contract(self) -> float:
        """PnL per single contract (unscaled by lots/lot_size). Use for % comparisons against net_credit."""
        return self.net_credit - self.current_debit

    @property
    def pnl_per_unit(self) -> float:
        """Alias for pnl_per_contract — kept for backward compatibility."""
        return self.pnl_per_contract

    @property
    def total_pnl(self) -> float:
        return sum(leg.pnl for leg in self.legs)

    @property
    def total_pnl_pct(self) -> float:
        max_loss = self.max_loss
        if max_loss == 0:
            return 0.0
        return (self.total_pnl / max_loss) * 100

    @property
    def portfolio_delta(self) -> float:
        """Net delta of the trade (sum of all legs, sign-adjusted for short)."""
        total = 0.0
        for leg in self.legs:
            sign = -1 if leg.is_short else 1
            total += sign * leg.delta * leg.lots * leg.lot_size
        return total

    @property
    def portfolio_vega(self) -> float:
        """Net vega of the trade."""
        total = 0.0
        for leg in self.legs:
            sign = -1 if leg.is_short else 1
            total += sign * leg.vega * leg.lots * leg.lot_size
        return total

    @property
    def portfolio_gamma(self) -> float:
        """Net gamma of the trade."""
        total = 0.0
        for leg in self.legs:
            sign = -1 if leg.is_short else 1
            total += sign * leg.gamma * leg.lots * leg.lot_size
        return total

    @property
    def portfolio_theta(self) -> float:
        """Net theta of the trade (positive = collecting theta)."""
        total = 0.0
        for leg in self.legs:
            sign = -1 if leg.is_short else 1
            total += sign * leg.theta * leg.lots * leg.lot_size
        return total

    @property
    def max_risk(self) -> float:
        """Max theoretical risk for the trade."""
        if not self.legs:
            return 0.0
        short_legs = [l for l in self.legs if l.is_short]
        long_legs = [l for l in self.legs if not l.is_short]
        if not short_legs or not long_legs:
            return abs(self.net_credit) * self.lots * self.lot_size * 5
        widths = []
        for sl in short_legs:
            closest_long = min(long_legs, key=lambda l: abs(l.strike - sl.strike))
            widths.append(abs(sl.strike - closest_long.strike))
        max_width = max(widths) if widths else 500
        return (max_width - abs(self.net_credit)) * self.lots * self.lot_size

    @property
    def max_loss(self) -> float:
        """Approximate max loss for any spread-based strategy.

        For spreads/Iron Condors: computes per-side max loss independently so that
        net_credit is not double-subtracted across both wings. For naked positions
        (no long hedge) uses credit * 5 as a conservative proxy.
        """
        short_legs = [l for l in self.legs if l.is_short]
        long_legs = [l for l in self.legs if not l.is_short]

        if not short_legs or not long_legs:
            return abs(self.net_credit) * self.lots * self.lot_size * 5

        # Group legs by option type (CE/CALL vs PE/PUT) and compute per-side max loss
        def _normalise(ot: str) -> str:
            return "CE" if ot.upper() in ("CE", "CALL") else "PE"

        sides: dict[str, dict] = {}
        for leg in self.legs:
            side = _normalise(leg.option_type)
            sides.setdefault(side, {"shorts": [], "longs": []})
            if leg.is_short:
                sides[side]["shorts"].append(leg)
            else:
                sides[side]["longs"].append(leg)

        worst = 0.0
        for side_data in sides.values():
            s_legs = side_data["shorts"]
            l_legs = side_data["longs"]
            if not s_legs or not l_legs:
                continue
            # Credit collected on this side only
            side_credit = sum(l.entry_premium for l in s_legs) - sum(l.entry_premium for l in l_legs)
            # Widest spread width on this side
            side_width = max(
                abs(sl.strike - ll.strike)
                for sl in s_legs
                for ll in l_legs
            )
            side_loss = max(0.0, (side_width - side_credit) * self.lots * self.lot_size)
            worst = max(worst, side_loss)

        # Fall back to 1000-point width if no matched same-side pairs found
        if worst == 0.0:
            worst = max(0, (1000 - self.net_credit) * self.lots * self.lot_size)

        return worst

    def apply_adjustment(self, adj: 'AdjustmentAction'):
        """
        Apply an adjustment: close specified legs, add new ones, track cost.
        """
        realized_pnl = 0.0
        for idx in sorted(adj.legs_to_close, reverse=True):
            if 0 <= idx < len(self.legs):
                closed_leg = self.legs.pop(idx)
                realized_pnl += closed_leg.pnl
        self.legs.extend(adj.new_legs)
        self.roll_count += 1
        self.adjustment_history.append({
            "type": adj.action_type,
            "cost": adj.cost,
            "realized_pnl": realized_pnl,
            "reasoning": adj.reasoning,
        })

    @property
    def is_open(self) -> bool:
        return self.exit_date is None

    @property
    def dte_at_entry(self) -> int:
        return 0

    @property
    def holding_days(self) -> int:
        if self.exit_date:
            return (self.exit_date - self.entry_date).days
        return 0


class BaseStrategy(ABC):
    """Abstract base class for option strategies."""

    def __init__(self, name: str, lots: int = 1, lot_size: int = 65):
        self.name = name
        self.lots = lots
        self.lot_size = lot_size

    @abstractmethod
    def generate_legs(
        self, spot: float, vix: float, dte: int, risk_free_rate: float = 0.065
    ) -> list[Leg]:
        pass

    @abstractmethod
    def should_enter(self, spot: float, vix: float, market_data: dict) -> TradeAction:
        pass

    @abstractmethod
    def should_exit(self, trade: Trade, spot: float, vix: float, dte_remaining: int) -> tuple[TradeAction, Optional[ExitReason]]:
        pass

    def should_adjust(
        self, trade: 'Trade', spot: float, vix: float, dte_remaining: int,
        market_data: dict = None,
    ) -> Optional['AdjustmentAction']:
        """
        Check if the trade should be adjusted instead of exited.
        Returns an AdjustmentAction if adjustment is beneficial, else None.
        Default: no adjustments. Override in strategies that support rolling.
        """
        return None

    def create_trade(
        self, entry_date: date, spot: float, vix: float, dte: int, risk_free_rate: float = 0.065
    ) -> Trade:
        legs = self.generate_legs(spot, vix, dte, risk_free_rate)
        return Trade(
            strategy_name=self.name,
            entry_date=entry_date,
            signal_date=entry_date,
            legs=legs,
            entry_spot=spot,
            entry_vix=vix,
            lots=self.lots,
            lot_size=self.lot_size,
        )
