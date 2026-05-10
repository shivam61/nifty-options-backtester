"""
Execution/fill abstractions for separating theoretical marking from executable fills.
"""

from __future__ import annotations

from dataclasses import dataclass

from config import CostModel
from pricing.black_scholes import OptionType, iv_from_vix, price_option
from strategies.base import Leg, Trade


@dataclass(frozen=True)
class FillSnapshot:
    spot: float
    vix: float
    risk_free_rate: float
    gap_pct: float = 0.0


class ConservativeFillModel:
    """
    Keeps Black-Scholes as the theoretical mark, but worsens actual fills
    through spread/slippage and gap-sensitive widening.
    """

    def __init__(self, cost_model: CostModel):
        self.cost_model = cost_model

    def mark_leg(self, leg: Leg, snap: FillSnapshot) -> float:
        option_type = OptionType.CALL if leg.option_type in ("CE", "CALL") else OptionType.PUT
        iv = iv_from_vix(snap.vix, leg.strike, snap.spot, option_type)
        return price_option(
            snap.spot, leg.strike, 0, iv, snap.risk_free_rate, option_type,
        ).premium

    def executable_leg_premium(
        self,
        leg: Leg,
        *,
        theoretical_premium: float,
        trade_spot: float,
        vix: float,
        is_entry: bool,
        gap_pct: float = 0.0,
    ) -> float:
        moneyness = leg.strike / trade_spot if trade_spot > 0 else 1.0
        half_spread = self.cost_model.slippage_per_unit(vix=vix, moneyness=moneyness)
        gap_widen = max(0.0, abs(gap_pct) - 0.25) * 0.75
        penalty = half_spread + gap_widen

        if is_entry:
            return max(0.01, theoretical_premium - penalty) if leg.is_short else theoretical_premium + penalty
        return theoretical_premium + penalty if leg.is_short else max(0.01, theoretical_premium - penalty)

    def apply_entry_fill(
        self,
        trade: Trade,
        *,
        spot: float,
        vix: float,
        dte: int,
        risk_free_rate: float,
        gap_pct: float = 0.0,
    ) -> None:
        for leg in trade.legs:
            option_type = OptionType.CALL if leg.option_type in ("CE", "CALL") else OptionType.PUT
            iv = iv_from_vix(vix, leg.strike, spot, option_type)
            theo = price_option(spot, leg.strike, dte, iv, risk_free_rate, option_type).premium
            filled = self.executable_leg_premium(
                leg,
                theoretical_premium=theo,
                trade_spot=spot,
                vix=vix,
                is_entry=True,
                gap_pct=gap_pct,
            )
            leg.entry_premium = filled
            leg.current_premium = filled

    def close_trade_pnl(
        self,
        trade: Trade,
        *,
        spot: float,
        vix: float,
        dte: int,
        risk_free_rate: float,
        gap_pct: float = 0.0,
    ) -> tuple[float, float]:
        raw_total = 0.0
        theoretical_total = 0.0
        for leg in trade.legs:
            option_type = OptionType.CALL if leg.option_type in ("CE", "CALL") else OptionType.PUT
            iv = iv_from_vix(vix, leg.strike, spot, option_type)
            theo = price_option(
                spot, leg.strike, max(dte, 0), iv, risk_free_rate, option_type,
            ).premium
            filled = self.executable_leg_premium(
                leg,
                theoretical_premium=theo,
                trade_spot=spot,
                vix=vix,
                is_entry=False,
                gap_pct=gap_pct,
            )
            if leg.is_short:
                theoretical_total += (leg.entry_premium - theo) * leg.quantity
                raw_total += (leg.entry_premium - filled) * leg.quantity
            else:
                theoretical_total += (theo - leg.entry_premium) * leg.quantity
                raw_total += (filled - leg.entry_premium) * leg.quantity
        return raw_total, raw_total - theoretical_total

