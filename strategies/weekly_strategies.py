"""
Weekly options strategies for 3-8 DTE Nifty weekly expiry.

Only PCS and IC in Phase 1 (lean validation of the weekly edge).
Tighter parameters than monthly: narrower spreads, faster exits,
VIX gates to avoid gamma blowups.
"""

import math
from strategies.base import BaseStrategy, Leg, Trade, TradeAction, ExitReason
from pricing.black_scholes import price_option, iv_from_vix, OptionType


def _nan(val) -> bool:
    try:
        return math.isnan(val)
    except (TypeError, ValueError):
        return False


class WeeklyPutCreditSpread(BaseStrategy):
    """
    Weekly Put Credit Spread: 0.8-1.0 SD OTM put spread, 300-500 pt width.
    Enters early in the week targeting the first expiry inside the configured
    DTE window.
    Tighter stops than monthly — gamma punishes hesitation at short DTE.
    """

    def __init__(self, lots: int = 2, lot_size: int = 65):
        super().__init__("weekly_pcs", lots, lot_size)
        self.put_sd = 0.9
        self.spread_width = 400

    def generate_legs(self, spot, vix, dte, risk_free_rate=0.065):
        annual_vol = vix / 100.0
        period_vol = annual_vol / (252 ** 0.5) * (dte ** 0.5)
        put_dist = spot * period_vol * self.put_sd

        sp_strike = round((spot - put_dist) / 50) * 50

        expected_move = spot * period_vol
        dynamic_width = max(200, min(500, int(expected_move * 0.5 / 50) * 50))
        lp_strike = sp_strike - dynamic_width

        sp_iv = iv_from_vix(vix, sp_strike, spot, OptionType.PUT)
        lp_iv = iv_from_vix(vix, lp_strike, spot, OptionType.PUT)

        sp = price_option(spot, sp_strike, dte, sp_iv, risk_free_rate, OptionType.PUT)
        lp = price_option(spot, lp_strike, dte, lp_iv, risk_free_rate, OptionType.PUT)

        return [
            Leg("PE", sp_strike, True, sp.premium, sp.premium, self.lots, self.lot_size,
                sp.greeks.delta, sp.greeks.gamma, sp.greeks.theta, sp.greeks.vega),
            Leg("PE", lp_strike, False, lp.premium, lp.premium, self.lots, self.lot_size,
                lp.greeks.delta, lp.greeks.gamma, lp.greeks.theta, lp.greeks.vega),
        ]

    def should_enter(self, spot, vix, market_data):
        if vix < 10 or vix > 25:
            return TradeAction.NO_TRADE
        nifty_5d = market_data.get("nifty_return_5d", 0)
        if not _nan(nifty_5d) and nifty_5d < -0.03:
            return TradeAction.NO_TRADE
        vix_5d = market_data.get("vix_change_5d", 0)
        if not _nan(vix_5d) and vix_5d > 0.15:
            return TradeAction.NO_TRADE
        return TradeAction.ENTER

    def should_exit(self, trade, spot, vix, dte_remaining):
        if dte_remaining <= 1:
            return TradeAction.EXIT, ExitReason.DTE_LIMIT

        pnl_unit = trade.pnl_per_unit
        credit = trade.net_credit
        if credit <= 0:
            return TradeAction.HOLD, None

        short_leg = next((l for l in trade.legs if l.is_short), None)
        long_leg = next((l for l in trade.legs if not l.is_short), None)
        if short_leg and long_leg:
            width = abs(short_leg.strike - long_leg.strike)
            max_loss_unit = width - credit
            if pnl_unit < 0 and abs(pnl_unit) > max_loss_unit * 0.5:
                return TradeAction.EXIT, ExitReason.STOP_LOSS

        if short_leg and spot < short_leg.strike:
            return TradeAction.EXIT, ExitReason.STOP_LOSS

        return TradeAction.HOLD, None

    def update_premiums(self, trade, spot, vix, dte, risk_free_rate=0.065):
        for leg in trade.legs:
            iv = iv_from_vix(vix, leg.strike, spot, OptionType.PUT)
            result = price_option(spot, leg.strike, dte, iv, risk_free_rate, OptionType.PUT)
            leg.current_premium = result.premium
            leg.delta = result.greeks.delta
            leg.gamma = result.greeks.gamma
            leg.theta = result.greeks.theta
            leg.vega = result.greeks.vega


class WeeklyIronCondor(BaseStrategy):
    """
    Weekly Iron Condor: sell OTM call spread + OTM put spread, 3-8 DTE.
    Tighter wings than monthly (200-400 pts vs 500-800) since time to recover is short.
    """

    def __init__(self, lots: int = 2, lot_size: int = 65):
        super().__init__("weekly_ic", lots, lot_size)
        self.call_sd = 0.7
        self.put_sd = 1.0

    def _dynamic_width(self, spot, vix, dte):
        annual_vol = vix / 100.0
        period_vol = annual_vol / (252 ** 0.5) * (dte ** 0.5)
        expected_move = spot * period_vol
        return max(200, min(400, int(expected_move * 0.5 / 50) * 50))

    def generate_legs(self, spot, vix, dte, risk_free_rate=0.065):
        annual_vol = vix / 100.0
        period_vol = annual_vol / (252 ** 0.5) * (dte ** 0.5)

        sc_strike = round((spot + spot * period_vol * self.call_sd) / 50) * 50
        sp_strike = round((spot - spot * period_vol * self.put_sd) / 50) * 50

        width = self._dynamic_width(spot, vix, dte)
        lc_strike = sc_strike + width
        lp_strike = sp_strike - width

        sc_iv = iv_from_vix(vix, sc_strike, spot, OptionType.CALL)
        lc_iv = iv_from_vix(vix, lc_strike, spot, OptionType.CALL)
        sp_iv = iv_from_vix(vix, sp_strike, spot, OptionType.PUT)
        lp_iv = iv_from_vix(vix, lp_strike, spot, OptionType.PUT)

        sc = price_option(spot, sc_strike, dte, sc_iv, risk_free_rate, OptionType.CALL)
        lc = price_option(spot, lc_strike, dte, lc_iv, risk_free_rate, OptionType.CALL)
        sp = price_option(spot, sp_strike, dte, sp_iv, risk_free_rate, OptionType.PUT)
        lp = price_option(spot, lp_strike, dte, lp_iv, risk_free_rate, OptionType.PUT)

        return [
            Leg("CE", sc_strike, True, sc.premium, sc.premium, self.lots, self.lot_size,
                sc.greeks.delta, sc.greeks.gamma, sc.greeks.theta, sc.greeks.vega),
            Leg("CE", lc_strike, False, lc.premium, lc.premium, self.lots, self.lot_size,
                lc.greeks.delta, lc.greeks.gamma, lc.greeks.theta, lc.greeks.vega),
            Leg("PE", sp_strike, True, sp.premium, sp.premium, self.lots, self.lot_size,
                sp.greeks.delta, sp.greeks.gamma, sp.greeks.theta, sp.greeks.vega),
            Leg("PE", lp_strike, False, lp.premium, lp.premium, self.lots, self.lot_size,
                lp.greeks.delta, lp.greeks.gamma, lp.greeks.theta, lp.greeks.vega),
        ]

    def should_enter(self, spot, vix, market_data):
        if vix < 12 or vix > 22:
            return TradeAction.NO_TRADE
        nifty_5d = market_data.get("nifty_return_5d", 0)
        if not _nan(nifty_5d) and abs(nifty_5d) > 0.03:
            return TradeAction.NO_TRADE
        vix_5d = market_data.get("vix_change_5d", 0)
        if not _nan(vix_5d) and vix_5d > 0.12:
            return TradeAction.NO_TRADE
        return TradeAction.ENTER

    def should_exit(self, trade, spot, vix, dte_remaining):
        if dte_remaining <= 1:
            return TradeAction.EXIT, ExitReason.DTE_LIMIT

        pnl_unit = trade.pnl_per_unit
        credit = trade.net_credit
        if credit <= 0:
            return TradeAction.HOLD, None

        short_call = next((l for l in trade.legs if l.is_short and l.option_type == "CE"), None)
        short_put = next((l for l in trade.legs if l.is_short and l.option_type == "PE"), None)

        if short_call and spot > short_call.strike:
            return TradeAction.EXIT, ExitReason.STOP_LOSS
        if short_put and spot < short_put.strike:
            return TradeAction.EXIT, ExitReason.STOP_LOSS

        long_call = next((l for l in trade.legs if not l.is_short and l.option_type == "CE"), None)
        long_put = next((l for l in trade.legs if not l.is_short and l.option_type == "PE"), None)
        max_width = max(
            abs(long_call.strike - short_call.strike) if long_call and short_call else 300,
            abs(short_put.strike - long_put.strike) if long_put and short_put else 300,
        )
        max_loss_unit = max_width - credit
        if pnl_unit < 0 and abs(pnl_unit) > max_loss_unit * 0.5:
            return TradeAction.EXIT, ExitReason.STOP_LOSS

        return TradeAction.HOLD, None

    def update_premiums(self, trade, spot, vix, dte, risk_free_rate=0.065):
        for leg in trade.legs:
            ot = OptionType.CALL if leg.option_type == "CE" else OptionType.PUT
            iv = iv_from_vix(vix, leg.strike, spot, ot)
            result = price_option(spot, leg.strike, dte, iv, risk_free_rate, ot)
            leg.current_premium = result.premium
            leg.delta = result.greeks.delta
            leg.gamma = result.greeks.gamma
            leg.theta = result.greeks.theta
            leg.vega = result.greeks.vega


WEEKLY_STRATEGIES = {
    "weekly_pcs": WeeklyPutCreditSpread,
    "weekly_ic": WeeklyIronCondor,
}

WEEKLY_STRATEGY_DISPLAY = {
    "weekly_pcs": "Weekly Put Credit Spread",
    "weekly_ic": "Weekly Iron Condor",
}
