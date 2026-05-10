"""
Iron Condor V2 — Optimized strategy based on 12-month backtest learnings.

KEY LEARNINGS INCORPORATED:
1. Asymmetric strikes: Tight calls (0.7 SD), Wide puts (1.2 SD)
   - Nifty rallies are capped (call side safer closer)
   - Crashes are violent (put side needs more buffer)
2. VIX direction filter: Only enter when VIX is stable or declining
   - VIX rising during trade → avg P&L -₹4,335
   - VIX declining during trade → avg P&L +₹7,716
3. Higher profit target: 60% (not 50%)
   - Profit target exits averaged +₹22,473 vs stop losses -₹3,771
4. Nifty range filter: Skip when Nifty moved >3% in 5 days (0% win rate)
5. Volatility Risk Premium filter: Only enter when IV > Realized Vol
6. Trailing profit lock: Once 30% profit reached, tighten stop to breakeven
"""

from typing import Optional
from datetime import date

from strategies.base import BaseStrategy, Leg, Trade, TradeAction, ExitReason
from pricing.black_scholes import price_option, iv_from_vix, OptionType


class IronCondorV2Strategy(BaseStrategy):
    """
    Optimized Iron Condor with asymmetric strikes and multi-filter entry.
    """

    def __init__(
        self,
        lots: int = 2,
        lot_size: int = 65,
        call_sd: float = 0.7,
        put_sd: float = 1.2,
        hedge_width: int = 1000,
        profit_target_pct: float = 60.0,
        trailing_lock_pct: float = 30.0,
        min_dte_exit: int = 3,
        min_credit: float = 250.0,
        max_vix_spike_5d: float = 0.15,
        max_nifty_move_5d: float = 0.03,
        min_vrp: float = 0.0,
    ):
        super().__init__("iron_condor_v2", lots, lot_size)
        self.call_sd = call_sd
        self.put_sd = put_sd
        self.hedge_width = hedge_width
        self.profit_target_pct = profit_target_pct
        self.trailing_lock_pct = trailing_lock_pct
        self.min_dte_exit = min_dte_exit
        self.min_credit = min_credit
        self.max_vix_spike_5d = max_vix_spike_5d
        self.max_nifty_move_5d = max_nifty_move_5d
        self.min_vrp = min_vrp
        self._peak_profit_pct = 0.0

    def _get_strike_distance(self, spot: float, vix: float, dte: int) -> tuple[float, float]:
        annual_vol = vix / 100.0
        daily_vol = annual_vol / (252 ** 0.5)
        period_vol = daily_vol * (dte ** 0.5)
        one_sd_move = spot * period_vol

        if vix < 14:
            call_mult = self.call_sd * 0.6
            put_mult = self.put_sd * 0.5
        elif vix < 18:
            call_mult = self.call_sd * 0.5
            put_mult = self.put_sd * 0.45
        elif vix < 22:
            call_mult = self.call_sd * 0.4
            put_mult = self.put_sd * 0.38
        elif vix < 28:
            call_mult = self.call_sd * 0.30
            put_mult = self.put_sd * 0.35
        else:
            call_mult = self.call_sd * 0.25
            put_mult = self.put_sd * 0.30

        return one_sd_move * call_mult, one_sd_move * put_mult

    def _round_strike(self, strike: float, step: int = 100) -> float:
        return round(strike / step) * step

    def generate_legs(
        self, spot: float, vix: float, dte: int, risk_free_rate: float = 0.065
    ) -> list[Leg]:
        call_dist, put_dist = self._get_strike_distance(spot, vix, dte)

        short_call_strike = self._round_strike(spot + call_dist)
        short_put_strike = self._round_strike(spot - put_dist)
        long_call_strike = short_call_strike + self.hedge_width
        long_put_strike = short_put_strike - self.hedge_width

        sc_iv = iv_from_vix(vix, short_call_strike, spot, OptionType.CALL)
        lc_iv = iv_from_vix(vix, long_call_strike, spot, OptionType.CALL)
        sp_iv = iv_from_vix(vix, short_put_strike, spot, OptionType.PUT)
        lp_iv = iv_from_vix(vix, long_put_strike, spot, OptionType.PUT)

        sc = price_option(spot, short_call_strike, dte, sc_iv, risk_free_rate, OptionType.CALL)
        lc = price_option(spot, long_call_strike, dte, lc_iv, risk_free_rate, OptionType.CALL)
        sp = price_option(spot, short_put_strike, dte, sp_iv, risk_free_rate, OptionType.PUT)
        lp = price_option(spot, long_put_strike, dte, lp_iv, risk_free_rate, OptionType.PUT)

        return [
            Leg("CE", short_call_strike, True, sc.premium, sc.premium, self.lots, self.lot_size),
            Leg("CE", long_call_strike, False, lc.premium, lc.premium, self.lots, self.lot_size),
            Leg("PE", short_put_strike, True, sp.premium, sp.premium, self.lots, self.lot_size),
            Leg("PE", long_put_strike, False, lp.premium, lp.premium, self.lots, self.lot_size),
        ]

    def should_enter(self, spot: float, vix: float, market_data: dict) -> TradeAction:
        """
        Multi-filter entry with learnings from 12-month analysis.
        """
        # Filter 1: VIX must be in tradeable range
        if vix < 10 or vix > 35:
            return TradeAction.NO_TRADE

        # Filter 2: VIX must NOT be spiking (most critical filter)
        # Learning: VIX rising during trade → -₹4,335 avg
        vix_change_5d = market_data.get("vix_change_5d", 0)
        if not _is_nan(vix_change_5d) and vix_change_5d > self.max_vix_spike_5d:
            return TradeAction.NO_TRADE

        # Filter 3: Nifty must not have moved >3% in 5 days
        # Learning: >3% move → 0% win rate
        nifty_return_5d = market_data.get("nifty_return_5d", 0)
        if not _is_nan(nifty_return_5d) and abs(nifty_return_5d) > self.max_nifty_move_5d:
            return TradeAction.NO_TRADE

        # Filter 4: Daily range should not be extreme
        daily_range_pct = market_data.get("nifty_daily_range_pct", 0)
        if not _is_nan(daily_range_pct) and daily_range_pct > 3.5:
            return TradeAction.NO_TRADE

        # Filter 5: Volatility Risk Premium should be positive (IV > RV)
        vrp = market_data.get("vol_risk_premium", 0)
        if not _is_nan(vrp) and vrp < self.min_vrp:
            return TradeAction.NO_TRADE

        # Filter 6: If VIX is in "medium" transitional zone (18-22),
        # require VIX to be declining (Learning: 33% win rate in this zone)
        if 18 <= vix <= 22:
            vix_change_1d = market_data.get("vix_change_1d", 0)
            if not _is_nan(vix_change_1d) and vix_change_1d > 0:
                return TradeAction.NO_TRADE

        self._peak_profit_pct = 0.0
        return TradeAction.ENTER

    def should_exit(
        self, trade: Trade, spot: float, vix: float, dte_remaining: int
    ) -> tuple[TradeAction, Optional[ExitReason]]:
        """
        Enhanced exit logic with trailing profit lock.
        """
        # Exit 1: DTE limit
        if dte_remaining <= self.min_dte_exit:
            return TradeAction.EXIT, ExitReason.DTE_LIMIT

        pnl_per_unit = trade.pnl_per_unit
        net_credit = trade.net_credit

        if net_credit > 0:
            profit_pct = (pnl_per_unit / net_credit) * 100

            # Exit 2: Profit target reached
            if profit_pct >= self.profit_target_pct:
                return TradeAction.EXIT, ExitReason.PROFIT_TARGET

            # Track peak profit for trailing stop
            if profit_pct > self._peak_profit_pct:
                self._peak_profit_pct = profit_pct

            # Exit 3: Trailing profit lock
            # Once 30% profit was reached, don't let it go below 10%
            if self._peak_profit_pct >= self.trailing_lock_pct and profit_pct < 10:
                return TradeAction.EXIT, ExitReason.PROFIT_TARGET

        # Exit 4: Max loss (70% of hedge width)
        max_loss_per_unit = self.hedge_width - net_credit
        if pnl_per_unit < 0 and abs(pnl_per_unit) > max_loss_per_unit * 0.6:
            return TradeAction.EXIT, ExitReason.STOP_LOSS

        # Exit 5: Spot breaches short strikes
        short_call = next((l for l in trade.legs if l.option_type == "CE" and l.is_short), None)
        short_put = next((l for l in trade.legs if l.option_type == "PE" and l.is_short), None)

        if short_call and spot > short_call.strike + 50:
            return TradeAction.EXIT, ExitReason.STOP_LOSS
        if short_put and spot < short_put.strike - 50:
            return TradeAction.EXIT, ExitReason.STOP_LOSS

        # Exit 6: VIX spike during trade (cut losses early)
        if trade.entry_vix > 0:
            vix_increase = (vix - trade.entry_vix) / trade.entry_vix
            if vix_increase > 0.30 and pnl_per_unit < 0:
                return TradeAction.EXIT, ExitReason.STOP_LOSS

        return TradeAction.HOLD, None

    def update_premiums(
        self, trade: Trade, spot: float, vix: float, dte: int, risk_free_rate: float = 0.065
    ):
        for leg in trade.legs:
            opt_type = OptionType.CALL if leg.option_type == "CE" else OptionType.PUT
            iv = iv_from_vix(vix, leg.strike, spot, opt_type)
            option = price_option(spot, leg.strike, dte, iv, risk_free_rate, opt_type)
            leg.current_premium = option.premium


def _is_nan(val) -> bool:
    try:
        import math
        return math.isnan(val)
    except (TypeError, ValueError):
        return False
