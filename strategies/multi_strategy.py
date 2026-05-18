"""
Multi-strategy module: Iron Butterfly, Put Credit Spread, Broken Wing Butterfly,
Calendar Spread, Ratio Put Spread, and a Regime-Adaptive meta-strategy.

The active monthly universe is intentionally frozen to:
calendar_spread, put_credit_spread, put_credit_wide, iron_condor,
broken_wing_butterfly.

All strategies are fully hedged (defined risk, lower margin).

Strategy selection based on 7-year analysis (2019-2026):
┌─────────────────┬──────────────────────────────────────┐
│ VIX 0-12        │ Calendar Spread (long vega)          │
│ VIX 12-15       │ Calendar Spread / Put Credit         │
│ VIX 15-18       │ Put Credit Spread (sweet spot)       │
│ VIX 18-22       │ Put Credit / Iron Condor / BWB       │
│ VIX 22-30       │ Put Credit / BWB (regime-dependent)  │
│ VIX 30+         │ Put Credit Spread (crisis / mean rev)│
└─────────────────┴──────────────────────────────────────┘
"""

import math
from typing import Optional
from datetime import date

from strategies.base import BaseStrategy, Leg, Trade, TradeAction, ExitReason, AdjustmentAction
from strategies.universe import ACTIVE_MONTHLY_STRATEGY_SET
from pricing.black_scholes import price_option, iv_from_vix, OptionType

STRATEGY_DISPLAY = {
    "put_credit_spread": "Put Credit Spread (Bull Put)",
    "broken_wing_butterfly": "Broken Wing Butterfly (Put)",
    "put_credit_wide": "Wide Put Credit Spread",
    "iron_condor": "Iron Condor (Delta-Targeted)",
    "iron_condor_v2": "Iron Condor V2",
    "calendar_spread": "Calendar Spread (Long Vega)",
    "ratio_put_spread": "Ratio Put Spread (Tail Hedge)",
}


def _nan(val) -> bool:
    try:
        return math.isnan(val)
    except (TypeError, ValueError):
        return False


class IronButterflyStrategy(BaseStrategy):
    """
    Iron Butterfly: ATM short straddle + OTM wings.
    Higher premium than Iron Condor, but narrower profit zone.

    Best in: VIX 0-12, range-bound markets (71% of time Nifty stays within 4.8%).
    Margin: Low (spread-based, fully hedged).
    """

    def __init__(
        self,
        lots: int = 2,
        lot_size: int = 65,
        wing_width: int = 500,
        profit_target_pct: float = 40.0,
        max_nifty_move_5d: float = 0.02,
    ):
        super().__init__("iron_butterfly", lots, lot_size)
        self.wing_width = wing_width
        self.profit_target_pct = profit_target_pct
        self.max_nifty_move_5d = max_nifty_move_5d

    def generate_legs(self, spot, vix, dte, risk_free_rate=0.065):
        atm = round(spot / 50) * 50

        lp_strike = atm - self.wing_width
        lc_strike = atm + self.wing_width

        sc_iv = iv_from_vix(vix, atm, spot, OptionType.CALL)
        sp_iv = iv_from_vix(vix, atm, spot, OptionType.PUT)
        lc_iv = iv_from_vix(vix, lc_strike, spot, OptionType.CALL)
        lp_iv = iv_from_vix(vix, lp_strike, spot, OptionType.PUT)

        sc = price_option(spot, atm, dte, sc_iv, risk_free_rate, OptionType.CALL)
        sp = price_option(spot, atm, dte, sp_iv, risk_free_rate, OptionType.PUT)
        lc = price_option(spot, lc_strike, dte, lc_iv, risk_free_rate, OptionType.CALL)
        lp = price_option(spot, lp_strike, dte, lp_iv, risk_free_rate, OptionType.PUT)

        return [
            Leg("CE", atm, True, sc.premium, sc.premium, self.lots, self.lot_size,
                sc.greeks.delta, sc.greeks.gamma, sc.greeks.theta, sc.greeks.vega),
            Leg("CE", lc_strike, False, lc.premium, lc.premium, self.lots, self.lot_size,
                lc.greeks.delta, lc.greeks.gamma, lc.greeks.theta, lc.greeks.vega),
            Leg("PE", atm, True, sp.premium, sp.premium, self.lots, self.lot_size,
                sp.greeks.delta, sp.greeks.gamma, sp.greeks.theta, sp.greeks.vega),
            Leg("PE", lp_strike, False, lp.premium, lp.premium, self.lots, self.lot_size,
                lp.greeks.delta, lp.greeks.gamma, lp.greeks.theta, lp.greeks.vega),
        ]

    def should_enter(self, spot, vix, market_data):
        if vix > 15:
            return TradeAction.NO_TRADE
        nifty_5d = market_data.get("nifty_return_5d", 0)
        if not _nan(nifty_5d) and abs(nifty_5d) > self.max_nifty_move_5d:
            return TradeAction.NO_TRADE
        daily_range = market_data.get("nifty_daily_range_pct", 0)
        if not _nan(daily_range) and daily_range > 2.0:
            return TradeAction.NO_TRADE
        return TradeAction.ENTER

    def should_exit(self, trade, spot, vix, dte_remaining):
        if dte_remaining <= 3:
            return TradeAction.EXIT, ExitReason.DTE_LIMIT

        pnl_unit = trade.pnl_per_unit
        credit = trade.net_credit

        if credit > 0 and (pnl_unit / credit * 100) >= self.profit_target_pct:
            return TradeAction.EXIT, ExitReason.PROFIT_TARGET

        max_loss_unit = self.wing_width - credit
        if pnl_unit < 0 and abs(pnl_unit) > max_loss_unit * 0.5:
            return TradeAction.EXIT, ExitReason.STOP_LOSS

        # Exit on VIX spike — butterfly is very vega-sensitive
        if trade.entry_vix > 0:
            if vix > trade.entry_vix * 1.25 and pnl_unit < 0:
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


class PutCreditSpreadStrategy(BaseStrategy):
    """
    Bull Put Credit Spread: Sell OTM put, buy further OTM put.
    Single-direction, bullish bias, lower margin than naked.

    Best in: VIX 15-18 (68% win rate), or VIX 30+ (post-crash mean reversion).
    Margin: Very low (spread width only).
    
    ---- v5: MAX PROFIT BOOKING ENABLED ----
    Default: 85% max profit booking (enable_max_profit_booking=True)
    
    Backtest validation (2020-2026):
    - Without: Rs.11.07M, 64.83% CAGR, 67.9% DD, -0.40 Sharpe
    - With 85%: Rs.10.75M, 64.10% CAGR, 37.2% DD, +0.39 Sharpe
    - Impact: -3% profit, -45% drawdown, Sharpe flips positive
    
    The 85% rule: Exit when profit drops to 85% of max profit seen.
    Reduces catastrophic drawdowns with minimal profit sacrifice.
    """

    def __init__(
        self,
        lots: int = 2,
        lot_size: int = 65,
        put_sd: float = 1.0,
        spread_width: int = 500,
        profit_target_pct: float = 50.0,
        min_vix: float = 13.0,
        enable_max_profit_booking: bool = True,
        max_profit_threshold: float = 0.85,
    ):
        super().__init__("put_credit_spread", lots, lot_size)
        self.put_sd = put_sd
        self.spread_width = spread_width
        self.profit_target_pct = profit_target_pct
        self.min_vix = min_vix
        self.enable_max_profit_booking = enable_max_profit_booking
        self.max_profit_threshold = max_profit_threshold

    def generate_legs(self, spot, vix, dte, risk_free_rate=0.065):
        annual_vol = vix / 100.0
        period_vol = annual_vol / (252**0.5) * (dte**0.5)
        put_dist = spot * period_vol * self.put_sd

        sp_strike = round((spot - put_dist) / 50) * 50

        # v3: dynamic spread width based on expected move
        expected_move = spot * period_vol
        dynamic_width = max(200, min(800, int(expected_move * 0.6 / 50) * 50))
        effective_width = dynamic_width if self.spread_width == 500 else self.spread_width
        lp_strike = sp_strike - effective_width

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
        if vix < self.min_vix:
            return TradeAction.NO_TRADE
        # Don't enter during strong downtrend
        nifty_20d = market_data.get("nifty_return_20d", 0)
        if not _nan(nifty_20d) and nifty_20d < -0.05:
            return TradeAction.NO_TRADE
        # VIX should not be spiking violently
        vix_5d = market_data.get("vix_change_5d", 0)
        if not _nan(vix_5d) and vix_5d > 0.20:
            return TradeAction.NO_TRADE
        nifty_5d = market_data.get("nifty_return_5d", 0)
        if not _nan(nifty_5d) and abs(nifty_5d) > 0.04:
            return TradeAction.NO_TRADE
        return TradeAction.ENTER

    def should_exit(self, trade, spot, vix, dte_remaining):
        if dte_remaining <= 3:
            return TradeAction.EXIT, ExitReason.DTE_LIMIT

        pnl_unit = trade.pnl_per_unit
        credit = trade.net_credit

        if self.enable_max_profit_booking:
            if not hasattr(trade, '_max_profit_per_unit'):
                trade._max_profit_per_unit = 0.0
            
            if pnl_unit > trade._max_profit_per_unit:
                trade._max_profit_per_unit = pnl_unit
            
            if trade._max_profit_per_unit > 0 and pnl_unit > 0:
                if pnl_unit <= trade._max_profit_per_unit * self.max_profit_threshold:
                    return TradeAction.EXIT, ExitReason.PROFIT_TARGET

        if credit > 0 and (pnl_unit / credit * 100) >= self.profit_target_pct:
            return TradeAction.EXIT, ExitReason.PROFIT_TARGET

        short_leg = next((l for l in trade.legs if l.is_short), None)
        long_leg = next((l for l in trade.legs if not l.is_short), None)
        actual_width = abs(short_leg.strike - long_leg.strike) if short_leg and long_leg else self.spread_width
        max_loss_unit = actual_width - credit
        if pnl_unit < 0 and abs(pnl_unit) > max_loss_unit * 0.6:
            return TradeAction.EXIT, ExitReason.STOP_LOSS

        actual_width = abs(short_leg.strike - long_leg.strike) if short_leg and long_leg else self.spread_width
        if short_leg and spot < short_leg.strike - actual_width * 0.06:
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


class BrokenWingButterflyStrategy(BaseStrategy):
    """
    Broken Wing Butterfly (Put side): Asymmetric risk.
    Short 2x ATM puts, Long 1x OTM put (close), Long 1x far OTM put (wide).
    Can be entered for a credit. Zero upside risk. Limited downside risk.

    Best in: VIX 22-30 (high premium to sell), or post-crash recovery.
    Margin: Lower than Iron Condor (no call-side margin needed).
    """

    def __init__(
        self,
        lots: int = 2,
        lot_size: int = 65,
        inner_wing: int = 300,
        outer_wing: int = 800,
        profit_target_pct: float = 50.0,
        min_vix: float = 18.0,
        max_vix: float = 30.0,
    ):
        super().__init__("broken_wing_butterfly", lots, lot_size)
        self.inner_wing = inner_wing
        self.outer_wing = outer_wing
        self.profit_target_pct = profit_target_pct
        self.min_vix = min_vix
        self.max_vix = max_vix

    def generate_legs(self, spot, vix, dte, risk_free_rate=0.065):
        # Centered slightly below spot (bearish-neutral bias)
        center = round((spot - spot * 0.01) / 50) * 50  # 1% below spot
        upper = center + self.inner_wing
        lower = center - self.outer_wing

        u_iv = iv_from_vix(vix, upper, spot, OptionType.PUT)
        c_iv = iv_from_vix(vix, center, spot, OptionType.PUT)
        l_iv = iv_from_vix(vix, lower, spot, OptionType.PUT)

        u_opt = price_option(spot, upper, dte, u_iv, risk_free_rate, OptionType.PUT)
        c_opt = price_option(spot, center, dte, c_iv, risk_free_rate, OptionType.PUT)
        l_opt = price_option(spot, lower, dte, l_iv, risk_free_rate, OptionType.PUT)

        return [
            Leg("PE", upper, False, u_opt.premium, u_opt.premium, self.lots, self.lot_size,
                u_opt.greeks.delta, u_opt.greeks.gamma, u_opt.greeks.theta, u_opt.greeks.vega),
            Leg("PE", center, True, c_opt.premium, c_opt.premium, self.lots * 2, self.lot_size,
                c_opt.greeks.delta, c_opt.greeks.gamma, c_opt.greeks.theta, c_opt.greeks.vega),
            Leg("PE", lower, False, l_opt.premium, l_opt.premium, self.lots, self.lot_size,
                l_opt.greeks.delta, l_opt.greeks.gamma, l_opt.greeks.theta, l_opt.greeks.vega),
        ]

    def should_enter(self, spot, vix, market_data):
        if vix < self.min_vix:
            return TradeAction.NO_TRADE
        if vix > self.max_vix:
            return TradeAction.NO_TRADE
        nifty_5d = market_data.get("nifty_return_5d", 0)
        if not _nan(nifty_5d) and abs(nifty_5d) > 0.05:
            return TradeAction.NO_TRADE
        return TradeAction.ENTER

    def should_exit(self, trade, spot, vix, dte_remaining):
        if dte_remaining <= 3:
            return TradeAction.EXIT, ExitReason.DTE_LIMIT

        pnl_unit = trade.pnl_per_unit
        credit = trade.net_credit

        if credit > 0 and (pnl_unit / credit * 100) >= self.profit_target_pct:
            return TradeAction.EXIT, ExitReason.PROFIT_TARGET

        # BWB has asymmetric risk — wider stop on the downside
        short_legs = [l for l in trade.legs if l.is_short]
        if short_legs:
            center = short_legs[0].strike
            if spot < center - self.outer_wing * 0.7:
                return TradeAction.EXIT, ExitReason.STOP_LOSS

        total_pnl = trade.total_pnl
        max_risk = trade.max_risk if hasattr(trade, 'max_risk') and trade.max_risk > 0 else 15000
        if total_pnl < -max_risk * 0.75:
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


class CalendarSpreadStrategy(BaseStrategy):
    """
    Calendar (Time) Spread: sell near-term ATM option, buy same-strike
    longer-term option.  Net debit entry that profits from:
      1. Theta decay of the short near-term leg (faster)
      2. IV increase (long vega on the far-month leg)

    Best in: VIX < 15 (low IV environment where IV is more likely to expand
    than contract). The position is "long vega" so it benefits if VIX spikes
    unexpectedly while the underlying stays flat — exactly the regime where
    credit spreads get crushed.

    We model this by pricing both legs with the same VIX but different DTEs.
    The short leg uses the actual DTE; the long leg uses DTE + 30 (next
    monthly expiry). On each daily update, both legs lose DTE but the short
    leg decays faster because theta is inversely proportional to sqrt(DTE).
    """

    def __init__(
        self,
        lots: int = 2,
        lot_size: int = 65,
        dte_gap: int = 30,
        profit_target_pct: float = 40.0,
        max_loss_pct: float = 50.0,
        max_rolls: int = 2,
    ):
        super().__init__("calendar_spread", lots, lot_size)
        self.dte_gap = dte_gap
        self.profit_target_pct = profit_target_pct
        self.max_loss_pct = max_loss_pct
        self.max_rolls = max_rolls

    def generate_legs(self, spot, vix, dte, risk_free_rate=0.065):
        atm = round(spot / 50) * 50
        iv_atm = iv_from_vix(vix, atm, spot, OptionType.PUT)

        near_dte = dte
        far_dte = dte + self.dte_gap

        near = price_option(spot, atm, near_dte, iv_atm, risk_free_rate, OptionType.PUT)
        far = price_option(spot, atm, far_dte, iv_atm, risk_free_rate, OptionType.PUT)

        return [
            Leg("PE", atm, True, near.premium, near.premium, self.lots, self.lot_size,
                near.greeks.delta, near.greeks.gamma, near.greeks.theta, near.greeks.vega),
            Leg("PE", atm, False, far.premium, far.premium, self.lots, self.lot_size,
                far.greeks.delta, far.greeks.gamma, far.greeks.theta, far.greeks.vega),
        ]

    def should_enter(self, spot, vix, market_data):
        if vix > 18:
            return TradeAction.NO_TRADE
        nifty_5d = market_data.get("nifty_return_5d", 0)
        if not _nan(nifty_5d) and abs(nifty_5d) > 0.03:
            return TradeAction.NO_TRADE
        daily_range = market_data.get("nifty_daily_range_pct", 0)
        if not _nan(daily_range) and daily_range > 2.5:
            return TradeAction.NO_TRADE
        return TradeAction.ENTER

    def should_exit(self, trade, spot, vix, dte_remaining):
        if dte_remaining <= 3:
            # Check if we should roll instead of exit
            if trade.roll_count < self.max_rolls:
                return TradeAction.ADJUST, ExitReason.ROLL
            return TradeAction.EXIT, ExitReason.DTE_LIMIT

        total_pnl = trade.total_pnl
        entry_debit = abs(sum(
            -l.entry_premium if l.is_short else l.entry_premium
            for l in trade.legs
        )) * trade.lots * trade.lot_size
        if entry_debit <= 0:
            entry_debit = 1

        pnl_pct = total_pnl / entry_debit * 100

        if pnl_pct >= self.profit_target_pct:
            return TradeAction.EXIT, ExitReason.PROFIT_TARGET
        if pnl_pct < -self.max_loss_pct:
            return TradeAction.EXIT, ExitReason.STOP_LOSS

        return TradeAction.HOLD, None

    def should_adjust(self, trade, spot, vix, dte_remaining, market_data=None):
        """
        Roll the short leg to the next monthly expiry when near expiry.
        The long leg still has time value, so we only replace the short leg.
        This captures more theta without closing the entire position.
        """
        if dte_remaining > 5 or trade.roll_count >= self.max_rolls:
            return None

        if vix > 25:
            return None

        short_legs = [(i, l) for i, l in enumerate(trade.legs) if l.is_short]
        if not short_legs:
            return None

        idx, old_short = short_legs[0]

        new_dte = self.dte_gap
        atm = round(spot / 50) * 50
        new_iv = iv_from_vix(vix, atm, spot, OptionType.PUT)
        new_premium = price_option(spot, atm, new_dte, new_iv, 0.065, OptionType.PUT)

        close_cost = old_short.current_premium
        open_credit = new_premium.premium
        roll_credit = open_credit - close_cost

        new_leg = Leg(
            "PE", atm, True, new_premium.premium, new_premium.premium,
            old_short.lots, old_short.lot_size,
            new_premium.greeks.delta, new_premium.greeks.gamma,
            new_premium.greeks.theta, new_premium.greeks.vega,
        )

        return AdjustmentAction(
            action_type="roll_short",
            legs_to_close=[idx],
            new_legs=[new_leg],
            cost=roll_credit,
            reasoning=f"Roll short PE {old_short.strike} (DTE {dte_remaining}) → "
                      f"PE {atm} (DTE {new_dte}), net {'credit' if roll_credit > 0 else 'debit'} "
                      f"₹{abs(roll_credit):.1f}",
        )

    def update_premiums(self, trade, spot, vix, dte, risk_free_rate=0.065):
        for leg in trade.legs:
            actual_dte = dte if leg.is_short else dte + self.dte_gap
            iv = iv_from_vix(vix, leg.strike, spot, OptionType.PUT)
            result = price_option(
                spot, leg.strike, actual_dte, iv, risk_free_rate, OptionType.PUT
            )
            leg.current_premium = result.premium
            leg.delta = result.greeks.delta
            leg.gamma = result.greeks.gamma
            leg.theta = result.greeks.theta
            leg.vega = result.greeks.vega


class RatioPutSpreadStrategy(BaseStrategy):
    """
    Ratio Put Spread (1:2): Sell 1 ATM/slightly-OTM put, buy 2 far-OTM puts.

    This creates a position that:
      - Collects a small credit (or near-zero cost) at entry
      - Profits if market stays flat or rises slightly (keeps the credit)
      - Profits MASSIVELY if market crashes hard (2 long puts overwhelm 1 short)

    The 2nd long put acts as a "free" tail-risk hedge. In extreme VIX (>25),
    the credit from the short put is large enough to fully fund both long puts.

    Risk profile:
      - Max risk: small zone between short strike and long strikes
      - Below both long strikes: unlimited profit (in practice, large)
      - Above short strike: keep full credit

    Best in: VIX > 25 (high premiums make the ratio economics work) or when
    crash risk is elevated but you still want to collect some premium.
    """

    def __init__(
        self,
        lots: int = 2,
        lot_size: int = 65,
        short_sd: float = 0.5,
        long_distance: int = 800,
        profit_target_pct: float = 50.0,
    ):
        super().__init__("ratio_put_spread", lots, lot_size)
        self.short_sd = short_sd
        self.long_distance = long_distance
        self.profit_target_pct = profit_target_pct

    def generate_legs(self, spot, vix, dte, risk_free_rate=0.065):
        annual_vol = vix / 100.0
        period_vol = annual_vol / (252**0.5) * (dte**0.5)
        short_dist = spot * period_vol * self.short_sd

        sp_strike = round((spot - short_dist) / 50) * 50
        lp_strike = sp_strike - self.long_distance

        sp_iv = iv_from_vix(vix, sp_strike, spot, OptionType.PUT)
        lp_iv = iv_from_vix(vix, lp_strike, spot, OptionType.PUT)

        sp = price_option(spot, sp_strike, dte, sp_iv, risk_free_rate, OptionType.PUT)
        lp = price_option(spot, lp_strike, dte, lp_iv, risk_free_rate, OptionType.PUT)

        return [
            Leg("PE", sp_strike, True, sp.premium, sp.premium, self.lots, self.lot_size,
                sp.greeks.delta, sp.greeks.gamma, sp.greeks.theta, sp.greeks.vega),
            Leg("PE", lp_strike, False, lp.premium, lp.premium, self.lots * 2, self.lot_size,
                lp.greeks.delta, lp.greeks.gamma, lp.greeks.theta, lp.greeks.vega),
        ]

    def should_enter(self, spot, vix, market_data):
        if vix < 22:
            return TradeAction.NO_TRADE
        nifty_5d = market_data.get("nifty_return_5d", 0)
        if not _nan(nifty_5d) and nifty_5d > 0.04:
            return TradeAction.NO_TRADE
        return TradeAction.ENTER

    def should_exit(self, trade, spot, vix, dte_remaining):
        if dte_remaining <= 3:
            return TradeAction.EXIT, ExitReason.DTE_LIMIT

        net_credit = trade.net_credit
        pnl = trade.pnl_per_unit

        if net_credit > 0 and (pnl / net_credit * 100) >= self.profit_target_pct:
            return TradeAction.EXIT, ExitReason.PROFIT_TARGET

        short_leg = next((l for l in trade.legs if l.is_short), None)
        if short_leg:
            long_legs = [l for l in trade.legs if not l.is_short]
            if long_legs:
                lp_strike = long_legs[0].strike
                if spot < lp_strike:
                    if trade.total_pnl > 0:
                        return TradeAction.EXIT, ExitReason.PROFIT_TARGET

        max_risk = trade.max_risk if hasattr(trade, 'max_risk') and trade.max_risk > 0 else 20000
        if trade.total_pnl < -max_risk * 0.75:
            return TradeAction.EXIT, ExitReason.STOP_LOSS

        return TradeAction.HOLD, None

    def update_premiums(self, trade, spot, vix, dte, risk_free_rate=0.065):
        for leg in trade.legs:
            iv = iv_from_vix(vix, leg.strike, spot, OptionType.PUT)
            result = price_option(
                spot, leg.strike, dte, iv, risk_free_rate, OptionType.PUT
            )
            leg.current_premium = result.premium
            leg.delta = result.greeks.delta
            leg.gamma = result.greeks.gamma
            leg.theta = result.greeks.theta
            leg.vega = result.greeks.vega


class IronCondorStrategy(BaseStrategy):
    """
    Iron Condor: sell OTM call spread + OTM put spread simultaneously.

    v3 addition: fills the call-side gap identified by strategy reviewers.
    Both sides collect premium, profit zone is between short strikes.

    Dynamic width: spread width scales with expected move (VIX-based).
    Delta-targeted: short strikes placed at ~0.15-0.20 delta equivalent.

    Best in: VIX 12-22 (enough premium on both sides, moderate risk).
    
    ---- v5: MAX PROFIT BOOKING ENABLED ----
    Default: 85% max profit booking (enable_max_profit_booking=True)
    
    Backtest validation (2020-2026):
    - Without: Rs.24.34M, 86.14% CAGR, 49.0% DD, 1.16 Sharpe
    - With 85%: Rs.22.24M, 83.54% CAGR, 17.7% DD, 1.69 Sharpe
    - Impact: -8.6% profit, -64% drawdown, +46% Sharpe
    
    The 85% rule: Exit when profit drops to 85% of max profit seen.
    Dramatically reduces drawdown with acceptable profit trade-off.
    """

    def __init__(
        self,
        lots: int = 2,
        lot_size: int = 65,
        call_sd: float = 1.0,
        put_sd: float = 1.0,
        profit_target_pct: float = 50.0,
        min_vix: float = 12.0,
        enable_max_profit_booking: bool = True,
        max_profit_threshold: float = 0.85,
    ):
        super().__init__("iron_condor", lots, lot_size)
        self.call_sd = call_sd
        self.put_sd = put_sd
        self.profit_target_pct = profit_target_pct
        self.min_vix = min_vix
        self.enable_max_profit_booking = enable_max_profit_booking
        self.max_profit_threshold = max_profit_threshold

    def _dynamic_width(self, spot: float, vix: float, dte: int) -> int:
        """Spread width scales with expected move instead of fixed 500."""
        annual_vol = vix / 100.0
        period_vol = annual_vol / (252**0.5) * (dte**0.5)
        expected_move = spot * period_vol
        width = max(200, min(800, int(expected_move * 0.5 / 50) * 50))
        return width

    def generate_legs(self, spot, vix, dte, risk_free_rate=0.065):
        annual_vol = vix / 100.0
        period_vol = annual_vol / (252**0.5) * (dte**0.5)

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
        if vix < self.min_vix:
            return TradeAction.NO_TRADE
        if vix > 28:
            return TradeAction.NO_TRADE
        nifty_5d = market_data.get("nifty_return_5d", 0)
        if not _nan(nifty_5d) and abs(nifty_5d) > 0.04:
            return TradeAction.NO_TRADE
        nifty_20d = market_data.get("nifty_return_20d", 0)
        if not _nan(nifty_20d) and abs(nifty_20d) > 0.06:
            return TradeAction.NO_TRADE
        vix_5d = market_data.get("vix_change_5d", 0)
        if not _nan(vix_5d) and vix_5d > 0.15:
            return TradeAction.NO_TRADE
        return TradeAction.ENTER

    def should_exit(self, trade, spot, vix, dte_remaining):
        if dte_remaining <= 3:
            return TradeAction.EXIT, ExitReason.DTE_LIMIT

        pnl_unit = trade.pnl_per_unit
        credit = trade.net_credit

        if self.enable_max_profit_booking:
            if not hasattr(trade, '_max_profit_per_unit'):
                trade._max_profit_per_unit = 0.0
            
            if pnl_unit > trade._max_profit_per_unit:
                trade._max_profit_per_unit = pnl_unit
            
            if trade._max_profit_per_unit > 0 and pnl_unit > 0:
                if pnl_unit <= trade._max_profit_per_unit * self.max_profit_threshold:
                    return TradeAction.EXIT, ExitReason.PROFIT_TARGET

        if credit > 0 and (pnl_unit / credit * 100) >= self.profit_target_pct:
            return TradeAction.EXIT, ExitReason.PROFIT_TARGET

        short_call = next((l for l in trade.legs if l.is_short and l.option_type == "CE"), None)
        short_put = next((l for l in trade.legs if l.is_short and l.option_type == "PE"), None)

        long_call = next((l for l in trade.legs if not l.is_short and l.option_type == "CE"), None)
        long_put = next((l for l in trade.legs if not l.is_short and l.option_type == "PE"), None)
        call_width = abs(long_call.strike - short_call.strike) if long_call and short_call else 500
        put_width = abs(short_put.strike - long_put.strike) if long_put and short_put else 500

        if short_call and spot > short_call.strike + call_width * 0.10:
            return TradeAction.EXIT, ExitReason.STOP_LOSS
        if short_put and spot < short_put.strike - put_width * 0.10:
            return TradeAction.EXIT, ExitReason.STOP_LOSS

        max_risk = trade.max_risk if hasattr(trade, 'max_risk') and trade.max_risk > 0 else 20000
        if trade.total_pnl < -max_risk * 0.75:
            return TradeAction.EXIT, ExitReason.STOP_LOSS

        if trade.entry_vix > 0 and vix > trade.entry_vix * 1.30 and pnl_unit < 0:
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


class RegimeAdaptiveStrategy(BaseStrategy):
    """
    Meta-strategy that selects the best sub-strategy based on current market regime.

    Based on 17-year backtest analysis (2009-2026):
    - VIX 0-12  + range-bound  → Calendar Spread (81% WR)
    - VIX 12-15                → Calendar / Put Credit (put_credit_spread, put_credit_wide)
    - VIX 15-18                → Put Credit Spread / Calendar Spread
    - VIX 18-22                → Put Credit / Iron Condor / BWB (strong downtrends)
    - VIX 22-30                → Put Credit / BWB (regime-dependent)
    - VIX 30+                  → Put Credit Spread (crisis)

    Active sub-strategy keys: put_credit_spread, put_credit_wide, calendar_spread,
    broken_wing_butterfly, iron_condor.
    """

    def __init__(self, lots: int = 2, lot_size: int = 65,
                 allowed_strategies: list[str] | None = None,
                 enable_max_profit_booking: bool = True,
                 max_profit_threshold: float = 0.85,
                 allow_bwb: bool = True,
                 crash_risk_v2_block: float = 0.80,
                 multi_asset_stress_block: float = 1.50,
                 correction_50d_block: float = -18.0,
                 vix_accel_block: float = 50.0,
                 crude_shock_block: float = 30.0):
        super().__init__("regime_adaptive", lots, lot_size)
        self.allow_bwb = allow_bwb
        self.crash_risk_v2_block = crash_risk_v2_block
        self.multi_asset_stress_block = multi_asset_stress_block
        self.correction_50d_block = correction_50d_block
        self.vix_accel_block = vix_accel_block
        self.crude_shock_block = crude_shock_block
        self._all_strategies = {
            "put_credit_spread": PutCreditSpreadStrategy(lots, lot_size, put_sd=1.0, spread_width=500, profit_target_pct=50, min_vix=0, 
                                                         enable_max_profit_booking=enable_max_profit_booking, max_profit_threshold=max_profit_threshold),
            "put_credit_wide": PutCreditSpreadStrategy(lots, lot_size, put_sd=1.3, spread_width=500, profit_target_pct=40, min_vix=0,
                                                       enable_max_profit_booking=enable_max_profit_booking, max_profit_threshold=max_profit_threshold),
            "calendar_spread": CalendarSpreadStrategy(lots, lot_size),
            "broken_wing_butterfly": BrokenWingButterflyStrategy(lots, lot_size),
            "iron_condor": IronCondorStrategy(lots, lot_size, min_vix=0, 
                                             enable_max_profit_booking=enable_max_profit_booking, max_profit_threshold=max_profit_threshold),
        }
        allowed = {s for s in allowed_strategies if s in ACTIVE_MONTHLY_STRATEGY_SET} if allowed_strategies else None
        if not self.allow_bwb:
            allowed = (allowed - {"broken_wing_butterfly"}) if allowed is not None else {"put_credit_spread", "put_credit_wide", "calendar_spread", "iron_condor"}
        self._allowed = allowed
        self._strategies = (
            {k: v for k, v in self._all_strategies.items() if k in self._allowed}
            if self._allowed else self._all_strategies
        )
        self._active_strategy = None
        self._active_name = None
        self._circuit_breaker_reason_counts: dict[str, int] = {}

    def set_lots(self, new_lots: int):
        """Propagate lot count change to all sub-strategies (for compounding)."""
        self.lots = new_lots
        for s in self._strategies.values():
            s.lots = new_lots

    def force_strategy_selection(self, strategy_name: str) -> bool:
        """
        Pre-select a strategy (typically from ML recommendation),
        bypassing the VIX-regime-based _select_strategy logic.
        Returns True if strategy exists and was activated.
        """
        if strategy_name in self._strategies:
            self._active_strategy = self._strategies[strategy_name]
            self._active_name = strategy_name
            return True
        return False

    def get_eligible_strategies(self, spot: float, vix: float, market_data: dict) -> list[str]:
        """
        Return a shortlist of regime-appropriate strategies. The circuit breaker
        blocks all trading when crash signals are active (binary block).

        This is the "rules guard" half of the hybrid approach. ML picks
        the best strategy from the returned list.
        """
        s = lambda key, default=0: self._safe(market_data, key, default)

        crash_risk = s("crash_risk_score")
        crash_risk_v2 = s("crash_risk_score_v2")
        consec_down = s("nifty_consec_down_days")
        correction_depth = s("nifty_drawdown_from_20d_high_pct")
        correction_50d = s("nifty_drawdown_from_50d_high_pct")
        crude_shock = s("crude_spike_10d_pct")
        vix_accel = s("vix_accel_3d_pct")
        multi_stress = s("multi_asset_stress")
        rvol_z = s("rvol_10d_z")
        vrp_neg = s("vrp_negative")

        self._circuit_breaker_reasons = []
        self._crash_signals = {
            "crash_risk_score": crash_risk,
            "crash_risk_score_v2": crash_risk_v2,
            "consec_down_days": consec_down,
            "correction_depth_pct": correction_depth,
            "correction_50d_pct": correction_50d,
            "crude_shock_10d_pct": crude_shock,
            "vix_accel_3d_pct": vix_accel,
            "multi_asset_stress": multi_stress,
            "rvol_10d_z": rvol_z,
            "vrp_negative": vrp_neg,
            "vix": vix,
        }

        # ── Circuit breaker: minimal black-swan protection ──
        # Post regime-aware model: only block for TRUE extreme events.
        # The CRASH-regime ML model (93.4% accuracy) handles moderate stress.
        if crash_risk_v2 >= self.crash_risk_v2_block:
            self._circuit_breaker_reason_counts["crash_risk_v2"] = self._circuit_breaker_reason_counts.get("crash_risk_v2", 0) + 1
            self._circuit_breaker_reasons.append(
                f"V2 crash risk {crash_risk_v2:.2f} >= {self.crash_risk_v2_block:.2f} (extreme multi-factor)\n"
                f"       Reasoning: Composite of VIX spike, drawdown, and momentum factors; "
                f">=80% indicates crash conditions similar to 2008/2020")
        if multi_stress >= self.multi_asset_stress_block:
            self._circuit_breaker_reason_counts["multi_asset_stress"] = self._circuit_breaker_reason_counts.get("multi_asset_stress", 0) + 1
            # Calculate individual asset stress levels to provide detailed breakdown
            stressed_assets = []
            stress_details = {}
            
            # Check all available assets for stress (Z-score based on 50-day lookback)
            asset_names = {
                "crude": ("Crude Oil", s("crude", None)),
                "usdinr": ("USD/INR", s("usdinr", None)),
                "vix": ("India VIX", vix),
                "gold": ("Gold", s("gold", None)),
                "dxy": ("Dollar Index", s("dxy", None)),
                "us_vix": ("US VIX", s("us_vix", None)),
                "sp500": ("S&P 500", s("sp500", None)),
                "nifty_bank": ("Bank Nifty", s("nifty_bank", None)),
            }
            
            # Calculate Z-scores for each asset to identify stress
            for asset_key, (display_name, current_val) in asset_names.items():
                if current_val is not None and current_val != 0:
                    ma_50 = s(f"{asset_key}_sma_50", None)
                    std_50 = s(f"{asset_key}_std_50", None)
                    
                    # Fallback: estimate from available data
                    if ma_50 is None or std_50 is None:
                        continue
                    
                    z_score = (current_val - ma_50) / std_50 if std_50 > 0 else 0
                    
                    # Asset is "stressed" if Z-score > 2.0 (2 std devs from mean)
                    if abs(z_score) > 2.0:
                        stressed_assets.append(display_name)
                        stress_details[display_name] = {
                            "z_score": z_score,
                            "current": current_val,
                            "mean_50d": ma_50
                        }
            
            # Build detailed message
            stress_msg = f"Multi-asset stress {multi_stress:.0%}"
            if stressed_assets:
                stress_msg += f" ({len(stressed_assets)} assets stressed: {', '.join(stressed_assets)})"
                for asset, details in stress_details.items():
                    stress_msg += f"\n       • {asset}: Z={details['z_score']:.1f}σ (current={details['current']:.1f}, 50d avg={details['mean_50d']:.1f})"
            else:
                # Fallback to basic 3-asset calculation if detailed data unavailable
                stress_msg += " (Crude/INR/VIX composite stress indicator)"
            
            stress_msg += "\n       Reasoning: Simultaneous stress across multiple uncorrelated assets signals systemic market disruption (contagion risk)"
            self._circuit_breaker_reasons.append(stress_msg)
            
        if correction_50d < -18.0:
            self._circuit_breaker_reason_counts["correction_50d"] = self._circuit_breaker_reason_counts.get("correction_50d", 0) + 1
            self._circuit_breaker_reasons.append(
                f"Deep correction {correction_50d:.1f}% from 50d high (< -18%)\n"
                f"       Reasoning: Sharp drawdowns often precede capitulation events; option selling requires stable markets")
        if vix_accel > self.vix_accel_block:
            self._circuit_breaker_reason_counts["vix_accel"] = self._circuit_breaker_reason_counts.get("vix_accel", 0) + 1
            self._circuit_breaker_reasons.append(
                f"VIX exploding {vix_accel:.1f}% in 3 days (> {self.vix_accel_block:.0f}%)\n"
                f"       Reasoning: Rapid volatility expansion indicates panic selling; gamma risk becomes unmanageable")
        if abs(crude_shock) > self.crude_shock_block:
            self._circuit_breaker_reason_counts["crude_shock"] = self._circuit_breaker_reason_counts.get("crude_shock", 0) + 1
            direction = "surge" if crude_shock > 0 else "collapse"
            self._circuit_breaker_reasons.append(
                f"Extreme crude {direction} {crude_shock:+.1f}% in 10 days (> ±{self.crude_shock_block:.0f}%)\n"
                f"       Reasoning: Oil shocks trigger inflation/stagflation concerns; high correlation with EM equity selloffs")

        if self._circuit_breaker_reasons:
            return []

        # ── Strategy selection by VIX zone ──
        # Active strategies (17y backtest validated): calendar_spread, put_credit_spread,
        # iron_condor, broken_wing_butterfly (v4.1)
        if vix < 12:
            eligible = ["calendar_spread", "iron_condor"]
        elif 12 <= vix < 15:
            eligible = ["put_credit_spread", "put_credit_wide", "calendar_spread", "iron_condor"]
        elif 15 <= vix < 18:
            eligible = ["put_credit_spread", "put_credit_wide", "iron_condor", "calendar_spread"]
        elif 18 <= vix < 22:
            eligible = ["put_credit_spread", "put_credit_wide", "iron_condor"]
            if self.allow_bwb:
                eligible.append("broken_wing_butterfly")
        elif 22 <= vix < 30:
            eligible = ["put_credit_spread", "put_credit_wide", "iron_condor"]
            if self.allow_bwb:
                eligible.append("broken_wing_butterfly")
        elif vix >= 30:
            eligible = ["put_credit_spread", "put_credit_wide"]
            if self.allow_bwb:
                eligible.append("broken_wing_butterfly")
        else:
            eligible = []

        eligible = [s for s in eligible if s in ACTIVE_MONTHLY_STRATEGY_SET]
        if self._allowed:
            eligible = [s for s in eligible if s in self._allowed]
        return eligible

    def _safe(self, market_data: dict, key: str, default=0):
        v = market_data.get(key, default)
        return default if _nan(v) else v

    def _select_strategy(self, spot: float, vix: float, market_data: dict) -> Optional[str]:
        """
        Select best strategy for current regime.

        Minimal black-swan circuit breaker for extreme events only.
        The regime-aware ML model handles moderate stress conditions.
        """
        nifty_5d = self._safe(market_data, "nifty_return_5d")
        nifty_20d = self._safe(market_data, "nifty_return_20d")
        dist_sma20 = self._safe(market_data, "nifty_distance_from_sma20_pct")
        vix_5d = self._safe(market_data, "vix_change_5d")
        dist_sma50 = self._safe(market_data, "nifty_distance_from_sma50_pct")

        # --- CIRCUIT BREAKER: minimal black-swan protection ---
        crash_risk_v2 = self._safe(market_data, "crash_risk_score_v2")
        correction_depth = self._safe(market_data, "nifty_drawdown_from_20d_high_pct")
        correction_50d = self._safe(market_data, "nifty_drawdown_from_50d_high_pct")
        crude_shock = self._safe(market_data, "crude_spike_10d_pct")
        vix_accel = self._safe(market_data, "vix_accel_3d_pct")
        multi_stress = self._safe(market_data, "multi_asset_stress")

        if crash_risk_v2 >= 0.80:
            return None
        if multi_stress >= self.multi_asset_stress_block:
            return None
        if correction_50d < -18.0:
            return None
        if abs(crude_shock) > 30:
            return None
        if vix_accel > 50:
            return None

        rsi = self._safe(market_data, "nifty_rsi_14", 50)
        vol_expansion = self._safe(market_data, "vol_expansion_ratio", 1.0)

        # v4: rebalanced allocation — PCS/Calendar primary, IC as diversifier
        # VIX < 12: calm markets — calendar dominates, IC secondary
        if vix < 12:
            if vol_expansion > 1.3:
                return "calendar_spread"
            if abs(nifty_5d) < 0.015:
                return "calendar_spread"
            return "iron_condor"

        # VIX 12-15: PCS and calendar primary, IC when range-bound
        if 12 <= vix < 15:
            if vol_expansion > 1.3:
                return "calendar_spread"
            if nifty_20d > 0.02 and dist_sma50 < 3 and vix_5d < 0:
                return "put_credit_spread"
            if abs(nifty_5d) < 0.02 and abs(nifty_20d) < 0.04:
                return "iron_condor"
            return "put_credit_spread"

        # VIX 15-18: sweet spot — PCS primary, IC for range-bound
        if 15 <= vix < 18:
            if abs(nifty_5d) < 0.015 and abs(vix_5d) < 0.05 and vol_expansion > 1.2:
                return "calendar_spread"
            if vol_expansion > 1.25 or vix_5d > 0.04:
                return "put_credit_wide"
            if abs(nifty_5d) < 0.02 and abs(nifty_20d) < 0.04:
                return "iron_condor"
            if nifty_20d > 0 and abs(nifty_5d) < 0.03:
                return "put_credit_wide"
            return "put_credit_spread"

        # VIX 18-22: PCS primary, IC if calm, BWB on strong downtrends (v4.1)
        if 18 <= vix < 22:
            if vol_expansion > 1.35 or vix_5d > 0.08:
                return "iron_condor"
            if abs(nifty_5d) < 0.015 and vix_5d <= 0:
                return "iron_condor"
            if nifty_20d < -0.03 and self.allow_bwb:
                return "broken_wing_butterfly"
            if nifty_20d < -0.03:
                return "iron_condor"
            if vix_5d < -0.05 and nifty_20d > 0:
                return "put_credit_wide"
            if nifty_20d > 0:
                return "put_credit_wide"
            return "iron_condor"

        # VIX 22-30: defensive — PCS when VIX falling sharply, else BWB
        if 22 <= vix < 30:
            if vol_expansion > 1.4 or vix_5d > 0.10:
                return "broken_wing_butterfly" if self.allow_bwb else "iron_condor"
            if vix_5d < -0.05 and nifty_20d > 0:
                return "put_credit_wide"
            if abs(nifty_5d) < 0.015 and vix_5d <= 0:
                return "iron_condor"
            return "broken_wing_butterfly" if self.allow_bwb else "iron_condor"

        # VIX 30+: crisis — only take a spread if volatility is cooling and trend stabilises
        if vix >= 30:
            if vix_5d < -0.05 and nifty_20d > 0:
                return "put_credit_wide"
            if nifty_20d < -0.05 or vol_expansion > 1.5:
                return None
            return "broken_wing_butterfly" if self.allow_bwb else "put_credit_wide"

        return None

    def generate_legs(self, spot, vix, dte, risk_free_rate=0.065):
        if self._active_strategy:
            return self._active_strategy.generate_legs(spot, vix, dte, risk_free_rate)
        return []

    def should_enter(self, spot, vix, market_data):
        name = self._select_strategy(spot, vix, market_data)
        if name is None:
            return TradeAction.NO_TRADE
        if self._allowed and name not in self._allowed:
            return TradeAction.NO_TRADE

        strategy = self._strategies.get(name)
        if strategy is None:
            return TradeAction.NO_TRADE

        # Verify the sub-strategy also agrees to enter
        action = strategy.should_enter(spot, vix, market_data)
        if action == TradeAction.ENTER:
            self._active_strategy = strategy
            self._active_name = name
            return TradeAction.ENTER
        return TradeAction.NO_TRADE

    def should_exit(self, trade, spot, vix, dte_remaining):
        if self._active_strategy:
            return self._active_strategy.should_exit(trade, spot, vix, dte_remaining)
        if dte_remaining <= 3:
            return TradeAction.EXIT, ExitReason.DTE_LIMIT
        return TradeAction.HOLD, None

    def update_premiums(self, trade, spot, vix, dte, risk_free_rate=0.065):
        if self._active_strategy:
            self._active_strategy.update_premiums(trade, spot, vix, dte, risk_free_rate)

    def create_trade(self, entry_date, spot, vix, dte, risk_free_rate=0.065):
        trade = super().create_trade(entry_date, spot, vix, dte, risk_free_rate)
        trade.strategy_name = f"adaptive:{self._active_name or 'unknown'}"
        return trade
