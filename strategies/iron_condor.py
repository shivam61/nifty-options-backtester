"""
Iron Condor strategy with configurable parameters.
Adapts strike selection based on VIX regime and market conditions.
"""

from typing import Optional
from datetime import date

from strategies.base import BaseStrategy, Leg, Trade, TradeAction, ExitReason
from pricing.black_scholes import (
    price_option, iv_from_vix, OptionType,
)


class IronCondorStrategy(BaseStrategy):
    """
    Iron Condor: Sell OTM Call + Sell OTM Put, Buy further OTM Call + Put as hedges.
    Profits from range-bound markets and Vega decay.

    Strike selection adapts to VIX:
    - Low VIX (<14): Tighter strikes (0.7 SD), smaller premium
    - Medium VIX (14-22): Standard strikes (1.0 SD)
    - High VIX (22-28): Wider strikes (1.3 SD), more premium
    - Extreme VIX (>28): Very wide (1.5 SD) or skip trade
    """

    def __init__(
        self,
        lots: int = 2,
        lot_size: int = 65,
        call_sd: float = 1.0,
        put_sd: float = 1.0,
        hedge_width: int = 1000,
        profit_target_pct: float = 50.0,
        stop_loss_multiplier: float = 2.0,
        min_credit: float = 300.0,
        min_dte_exit: int = 3,
        adaptive_strikes: bool = True,
    ):
        super().__init__("iron_condor", lots, lot_size)
        self.call_sd = call_sd
        self.put_sd = put_sd
        self.hedge_width = hedge_width
        self.profit_target_pct = profit_target_pct
        self.stop_loss_multiplier = stop_loss_multiplier
        self.min_credit = min_credit
        self.min_dte_exit = min_dte_exit
        self.adaptive_strikes = adaptive_strikes

    def _get_strike_distance(self, spot: float, vix: float, dte: int) -> tuple[float, float]:
        """Calculate strike distance from spot based on VIX and DTE."""
        annual_vol = vix / 100.0
        daily_vol = annual_vol / (252 ** 0.5)
        period_vol = daily_vol * (dte ** 0.5)
        one_sd_move = spot * period_vol

        if self.adaptive_strikes:
            if vix < 14:
                call_mult, put_mult = 0.4, 0.4
            elif vix < 18:
                call_mult, put_mult = 0.35, 0.35
            elif vix < 22:
                call_mult, put_mult = 0.30, 0.30
            elif vix < 28:
                call_mult, put_mult = 0.25, 0.35
            else:
                call_mult, put_mult = 0.20, 0.30
        else:
            call_mult, put_mult = self.call_sd, self.put_sd

        call_distance = one_sd_move * call_mult
        put_distance = one_sd_move * put_mult

        return call_distance, put_distance

    def _round_strike(self, strike: float, step: int = 100) -> float:
        """Round to nearest Nifty strike (multiples of 50 or 100)."""
        if strike > 20000:
            step = 100
        return round(strike / step) * step

    def generate_legs(
        self, spot: float, vix: float, dte: int, risk_free_rate: float = 0.065
    ) -> list[Leg]:
        call_dist, put_dist = self._get_strike_distance(spot, vix, dte)

        short_call_strike = self._round_strike(spot + call_dist)
        short_put_strike = self._round_strike(spot - put_dist)
        long_call_strike = short_call_strike + self.hedge_width
        long_put_strike = short_put_strike - self.hedge_width

        short_call_iv = iv_from_vix(vix, short_call_strike, spot, OptionType.CALL)
        long_call_iv = iv_from_vix(vix, long_call_strike, spot, OptionType.CALL)
        short_put_iv = iv_from_vix(vix, short_put_strike, spot, OptionType.PUT)
        long_put_iv = iv_from_vix(vix, long_put_strike, spot, OptionType.PUT)

        sc = price_option(spot, short_call_strike, dte, short_call_iv, risk_free_rate, OptionType.CALL)
        lc = price_option(spot, long_call_strike, dte, long_call_iv, risk_free_rate, OptionType.CALL)
        sp = price_option(spot, short_put_strike, dte, short_put_iv, risk_free_rate, OptionType.PUT)
        lp = price_option(spot, long_put_strike, dte, long_put_iv, risk_free_rate, OptionType.PUT)

        return [
            Leg("CE", short_call_strike, True, sc.premium, sc.premium, self.lots, self.lot_size),
            Leg("CE", long_call_strike, False, lc.premium, lc.premium, self.lots, self.lot_size),
            Leg("PE", short_put_strike, True, sp.premium, sp.premium, self.lots, self.lot_size),
            Leg("PE", long_put_strike, False, lp.premium, lp.premium, self.lots, self.lot_size),
        ]

    def should_enter(self, spot: float, vix: float, market_data: dict) -> TradeAction:
        """
        Entry rules:
        1. VIX must be above 14 (enough premium to collect)
        2. VIX should be declining or stable (not spiking up)
        3. Nifty should not be in free-fall (check 5-day return)
        4. No existing open trade
        """
        if vix < 12:
            return TradeAction.NO_TRADE

        if vix > 35:
            return TradeAction.NO_TRADE

        vix_change_5d = market_data.get("vix_change_5d", 0)
        if vix_change_5d > 0.30:
            return TradeAction.NO_TRADE

        nifty_return_5d = market_data.get("nifty_return_5d", 0)
        if abs(nifty_return_5d) > 0.08:
            return TradeAction.NO_TRADE

        daily_range_pct = market_data.get("nifty_daily_range_pct", 0)
        if daily_range_pct > 4.0:
            return TradeAction.NO_TRADE

        return TradeAction.ENTER

    def should_exit(
        self, trade: Trade, spot: float, vix: float, dte_remaining: int
    ) -> tuple[TradeAction, Optional[ExitReason]]:
        """
        Exit rules:
        1. Profit target reached (default 50% of max credit)
        2. Stop loss hit (default 2x max credit loss)
        3. DTE < min threshold (default 3 days)
        4. Spot breaches short strikes
        """
        if dte_remaining <= self.min_dte_exit:
            return TradeAction.EXIT, ExitReason.DTE_LIMIT

        pnl_per_unit = trade.pnl_per_unit
        net_credit = trade.net_credit

        if net_credit > 0:
            profit_pct = (pnl_per_unit / net_credit) * 100
            if profit_pct >= self.profit_target_pct:
                return TradeAction.EXIT, ExitReason.PROFIT_TARGET

        max_loss_per_unit = self.hedge_width - net_credit
        if pnl_per_unit < 0 and abs(pnl_per_unit) > max_loss_per_unit * 0.7:
            return TradeAction.EXIT, ExitReason.STOP_LOSS

        short_call = next((l for l in trade.legs if l.option_type == "CE" and l.is_short), None)
        short_put = next((l for l in trade.legs if l.option_type == "PE" and l.is_short), None)

        if short_call and spot > short_call.strike:
            return TradeAction.EXIT, ExitReason.STOP_LOSS
        if short_put and spot < short_put.strike:
            return TradeAction.EXIT, ExitReason.STOP_LOSS

        return TradeAction.HOLD, None

    def update_premiums(
        self, trade: Trade, spot: float, vix: float, dte: int, risk_free_rate: float = 0.065
    ):
        """Reprice all legs at current market conditions."""
        for leg in trade.legs:
            opt_type = OptionType.CALL if leg.option_type == "CE" else OptionType.PUT
            iv = iv_from_vix(vix, leg.strike, spot, opt_type)
            option = price_option(spot, leg.strike, dte, iv, risk_free_rate, opt_type)
            leg.current_premium = option.premium


class WidePutSpreadStrategy(BaseStrategy):
    """
    Standalone put credit spread — used when call side is too risky
    (e.g., strong upward momentum or binary event risk on the upside).
    """

    def __init__(
        self,
        lots: int = 2,
        lot_size: int = 65,
        put_sd: float = 1.2,
        hedge_width: int = 1000,
        profit_target_pct: float = 60.0,
    ):
        super().__init__("put_spread", lots, lot_size)
        self.put_sd = put_sd
        self.hedge_width = hedge_width
        self.profit_target_pct = profit_target_pct

    def generate_legs(
        self, spot: float, vix: float, dte: int, risk_free_rate: float = 0.065
    ) -> list[Leg]:
        annual_vol = vix / 100.0
        period_vol = annual_vol / (252 ** 0.5) * (dte ** 0.5)
        put_distance = spot * period_vol * self.put_sd

        short_put = round((spot - put_distance) / 100) * 100
        long_put = short_put - self.hedge_width

        sp_iv = iv_from_vix(vix, short_put, spot, OptionType.PUT)
        lp_iv = iv_from_vix(vix, long_put, spot, OptionType.PUT)

        sp_price = price_option(spot, short_put, dte, sp_iv, risk_free_rate, OptionType.PUT)
        lp_price = price_option(spot, long_put, dte, lp_iv, risk_free_rate, OptionType.PUT)

        return [
            Leg("PE", short_put, True, sp_price.premium, sp_price.premium, self.lots, self.lot_size),
            Leg("PE", long_put, False, lp_price.premium, lp_price.premium, self.lots, self.lot_size),
        ]

    def should_enter(self, spot: float, vix: float, market_data: dict) -> TradeAction:
        if vix < 14:
            return TradeAction.NO_TRADE
        if vix > 35:
            return TradeAction.NO_TRADE
        return TradeAction.ENTER

    def should_exit(
        self, trade: Trade, spot: float, vix: float, dte_remaining: int
    ) -> tuple[TradeAction, Optional[ExitReason]]:
        if dte_remaining <= 3:
            return TradeAction.EXIT, ExitReason.DTE_LIMIT

        pnl = trade.pnl_per_unit
        credit = trade.net_credit
        if credit > 0 and (pnl / credit) * 100 >= self.profit_target_pct:
            return TradeAction.EXIT, ExitReason.PROFIT_TARGET

        short_put = next((l for l in trade.legs if l.is_short), None)
        if short_put and spot < short_put.strike:
            return TradeAction.EXIT, ExitReason.STOP_LOSS

        return TradeAction.HOLD, None
