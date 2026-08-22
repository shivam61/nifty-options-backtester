"""
Rolling Window Trade Simulator — generates 1000+ training samples from 7 years of data.

Instead of running one-at-a-time sequential backtests (which yield ~135 trades),
this simulator asks "what if we entered a trade on EVERY Nth day?" and tracks
the outcome over the next hold_days using Black-Scholes repricing.

Multiple parameter variations per strategy maximize training diversity.
"""

from dataclasses import dataclass
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd

from pricing.black_scholes import price_option, iv_from_vix, OptionType
from backtester.engine import TradeResult


@dataclass
class SimConfig:
    entry_every_n_days: int = 3
    hold_days: int = 21
    lots: int = 2
    lot_size: int = 75
    profit_target_pct: float = 50.0
    stop_loss_pct: float = 60.0


STRATEGY_CONFIGS = [
    # ── Put Credit Spreads — put-side verticals, bullish bias ────────────
    {"name": "put_credit_spread", "type": "vertical", "direction": "put",
     "sd": 1.0, "spread_width": 500, "min_vix": 12, "max_vix": 100},
    {"name": "put_credit_spread", "type": "vertical", "direction": "put",
     "sd": 1.2, "spread_width": 500, "min_vix": 15, "max_vix": 100},
    {"name": "put_credit_spread", "type": "vertical", "direction": "put",
     "sd": 0.8, "spread_width": 400, "min_vix": 13, "max_vix": 25},

    # ── Put Credit Wide — call-side verticals ────────────────────────────
    {"name": "put_credit_wide", "type": "vertical", "direction": "call",
     "sd": 0.8, "spread_width": 500, "min_vix": 10, "max_vix": 22},
    {"name": "put_credit_wide", "type": "vertical", "direction": "call",
     "sd": 1.0, "spread_width": 500, "min_vix": 12, "max_vix": 25},
    {"name": "put_credit_wide", "type": "vertical", "direction": "call",
     "sd": 0.6, "spread_width": 300, "min_vix": 10, "max_vix": 18},

    # ── Iron Condor — 4-leg symmetric range, VIX 12–28 ───────────────────
    # Teaches: both-skew pricing, symmetric theta decay, range-bound features
    {"name": "iron_condor", "type": "iron_condor",
     "put_sd": 1.0, "call_sd": 1.0, "spread_width": 500, "min_vix": 12, "max_vix": 28},
    {"name": "iron_condor", "type": "iron_condor",
     "put_sd": 1.2, "call_sd": 1.2, "spread_width": 500, "min_vix": 15, "max_vix": 28},
    {"name": "iron_condor", "type": "iron_condor",
     "put_sd": 0.9, "call_sd": 1.1, "spread_width": 400, "min_vix": 12, "max_vix": 22},

    # ── Iron Butterfly — ATM short straddle + wings, ultra-low VIX ───────
    # Teaches: highest theta/gamma, pinning regime at VIX < 15
    {"name": "iron_butterfly", "type": "iron_butterfly",
     "wing_width": 500, "min_vix": 10, "max_vix": 15},
    {"name": "iron_butterfly", "type": "iron_butterfly",
     "wing_width": 400, "min_vix": 10, "max_vix": 13},

    # ── Broken Wing Butterfly — 3-leg asymmetric, VIX 18–30 ──────────────
    # Teaches: asymmetric convexity, downside skew, directional bias
    # Structure: 2 short puts at body_sd (moderate OTM) + 1 long put at long_sd (closer OTM)
    # Net credit positive when body_sd > long_sd (body puts are cheaper, 2x funds the closer long)
    {"name": "broken_wing_butterfly", "type": "bwb",
     "body_sd": 0.8, "long_sd": 0.5, "min_vix": 18, "max_vix": 30},
    {"name": "broken_wing_butterfly", "type": "bwb",
     "body_sd": 0.8, "long_sd": 0.6, "min_vix": 20, "max_vix": 30},

    # ── Ratio Put Spread — 1:2, tail-hedge flavor, VIX > 22 ──────────────
    # Teaches: long gamma tails, positive skew at high VIX
    {"name": "ratio_put_spread", "type": "ratio_put",
     "short_sd": 0.5, "long_sd": 1.2, "min_vix": 22, "max_vix": 100},
    {"name": "ratio_put_spread", "type": "ratio_put",
     "short_sd": 0.7, "long_sd": 1.5, "min_vix": 25, "max_vix": 100},

    # ── Calendar Spread — near-term short + far-term long ATM ────────────
    # Teaches: IV term structure (iv_rv_term_spread), vega-theta tradeoff
    {"name": "calendar_spread", "type": "calendar",
     "near_dte": 21, "far_dte": 42, "min_vix": 10, "max_vix": 18},
    {"name": "calendar_spread", "type": "calendar",
     "near_dte": 14, "far_dte": 35, "min_vix": 10, "max_vix": 16},
    {"name": "calendar_spread", "type": "calendar",
     "near_dte": 21, "far_dte": 49, "min_vix": 12, "max_vix": 20},

    # ── Diagonal Spread — near OTM short + far deeper long ───────────────
    # Teaches: term structure + directional skew combined (iv_skew_proxy)
    {"name": "diagonal_spread", "type": "diagonal",
     "short_sd": 0.5, "long_sd": 1.0, "near_dte": 21, "far_dte": 42, "min_vix": 12, "max_vix": 22},
    {"name": "diagonal_spread", "type": "diagonal",
     "short_sd": 0.7, "long_sd": 1.3, "near_dte": 14, "far_dte": 35, "min_vix": 14, "max_vix": 22},

    # ── Jade Lizard — short OTM put + bear call spread ────────────────────
    # Teaches: asymmetric upside removal, skew-skew pricing, theta quality
    {"name": "jade_lizard", "type": "jade_lizard",
     "put_sd": 0.8, "call_sd": 0.8, "call_width": 400, "min_vix": 15, "max_vix": 28},
    {"name": "jade_lizard", "type": "jade_lizard",
     "put_sd": 1.0, "call_sd": 1.0, "call_width": 300, "min_vix": 18, "max_vix": 28},

    # ── Put Backspread — sell 1 ATM put, buy 2 far-OTM puts ──────────────
    # Teaches: long vega / long gamma, BREAKS uniform short-option negative skew
    {"name": "put_backspread", "type": "put_backspread",
     "short_sd": 0.3, "long_sd": 1.2, "min_vix": 22, "max_vix": 100},
    {"name": "put_backspread", "type": "put_backspread",
     "short_sd": 0.5, "long_sd": 1.5, "min_vix": 25, "max_vix": 100},
]


class RollingWindowSimulator:
    """
    Simulates overlapping trades across the full dataset.

    For each entry date (every N days), simulates all applicable strategy
    configurations and tracks day-by-day P&L until exit.
    """

    def __init__(self, data: pd.DataFrame, config: SimConfig = SimConfig()):
        self.data = data
        self.config = config

    def simulate_all(self) -> list[TradeResult]:
        """Run rolling simulations for all strategies and parameter variations."""
        all_trades = []
        n_rows = len(self.data)

        for entry_idx in range(50, n_rows):
            if (entry_idx - 50) % self.config.entry_every_n_days != 0:
                continue

            remaining_days = n_rows - entry_idx - 1
            if remaining_days < self.config.hold_days + 1:
                continue

            row = self.data.iloc[entry_idx]
            spot = row.get("nifty_close", 0)
            vix = row.get("vix", 15)

            if pd.isna(spot) or spot == 0 or pd.isna(vix):
                continue

            for strat_cfg in STRATEGY_CONFIGS:
                if vix < strat_cfg["min_vix"] or vix > strat_cfg["max_vix"]:
                    continue

                type_ = strat_cfg.get("type", "vertical")
                dispatch = {
                    "vertical":       self._simulate_trade,
                    "iron_condor":    self._simulate_iron_condor,
                    "iron_butterfly": self._simulate_iron_butterfly,
                    "bwb":            self._simulate_bwb,
                    "ratio_put":      self._simulate_ratio_put,
                    "calendar":       self._simulate_calendar,
                    "diagonal":       self._simulate_diagonal,
                    "jade_lizard":    self._simulate_jade_lizard,
                    "put_backspread": self._simulate_put_backspread,
                }
                sim_fn = dispatch.get(type_)
                if sim_fn is None:
                    continue
                trade = sim_fn(entry_idx, strat_cfg)
                if trade:
                    all_trades.append(trade)

        return all_trades

    def _simulate_trade(
        self, entry_idx: int, strat_cfg: dict
    ) -> Optional[TradeResult]:
        """Simulate a single trade from entry to exit."""
        signal_row = self.data.iloc[entry_idx]
        signal_spot = signal_row["nifty_close"]
        signal_vix = signal_row["vix"]
        signal_date = self.data.index[entry_idx]
        if hasattr(signal_date, "date"):
            signal_date = signal_date.date()

        fill_idx = entry_idx + 1
        row = self.data.iloc[fill_idx]
        spot = row.get("nifty_open", row["nifty_close"])
        vix = signal_vix
        entry_date = self.data.index[fill_idx]
        if hasattr(entry_date, "date"):
            entry_date = entry_date.date()

        dte = self.config.hold_days
        annual_vol = vix / 100.0
        period_vol = annual_vol / (252**0.5) * (dte**0.5)

        direction = strat_cfg["direction"]
        sd = strat_cfg["sd"]
        spread_width = strat_cfg["spread_width"]
        strat_name = strat_cfg["name"]

        if direction == "put":
            short_strike = round((spot - spot * period_vol * sd) / 50) * 50
            long_strike = short_strike - spread_width

            s_iv = iv_from_vix(vix, short_strike, spot, OptionType.PUT)
            l_iv = iv_from_vix(vix, long_strike, spot, OptionType.PUT)
            s_prem = price_option(spot, short_strike, dte, s_iv, 0.065, OptionType.PUT).premium
            l_prem = price_option(spot, long_strike, dte, l_iv, 0.065, OptionType.PUT).premium
            entry_credit = s_prem - l_prem
            opt_type = OptionType.PUT

        elif direction == "call":
            short_strike = round((spot + spot * period_vol * sd) / 50) * 50
            long_strike = short_strike + spread_width

            s_iv = iv_from_vix(vix, short_strike, spot, OptionType.CALL)
            l_iv = iv_from_vix(vix, long_strike, spot, OptionType.CALL)
            s_prem = price_option(spot, short_strike, dte, s_iv, 0.065, OptionType.CALL).premium
            l_prem = price_option(spot, long_strike, dte, l_iv, 0.065, OptionType.CALL).premium
            entry_credit = s_prem - l_prem
            opt_type = OptionType.CALL

        else:
            return None

        if entry_credit <= 0:
            return None

        max_loss_unit = spread_width - entry_credit

        exit_reason = "expiry"
        exit_idx = min(fill_idx + self.config.hold_days, len(self.data) - 1)
        pnl_per_unit = 0

        for day_offset in range(1, self.config.hold_days + 1):
            idx = fill_idx + day_offset
            if idx >= len(self.data):
                break

            day_row = self.data.iloc[idx]
            day_spot = day_row.get("nifty_close", spot)
            day_vix = day_row.get("vix", vix)
            dte_remaining = max(self.config.hold_days - day_offset, 1)

            if pd.isna(day_spot) or pd.isna(day_vix):
                continue

            s_iv2 = iv_from_vix(day_vix, short_strike, day_spot, opt_type)
            l_iv2 = iv_from_vix(day_vix, long_strike, day_spot, opt_type)
            s_now = price_option(day_spot, short_strike, dte_remaining, s_iv2, 0.065, opt_type).premium
            l_now = price_option(day_spot, long_strike, dte_remaining, l_iv2, 0.065, opt_type).premium
            current_debit = s_now - l_now

            pnl_per_unit = entry_credit - current_debit

            if pnl_per_unit >= entry_credit * self.config.profit_target_pct / 100:
                exit_reason = "profit_target"
                exit_idx = idx
                break

            if pnl_per_unit < 0 and abs(pnl_per_unit) > max_loss_unit * self.config.stop_loss_pct / 100:
                exit_reason = "stop_loss"
                exit_idx = idx
                break

            if dte_remaining <= 3:
                exit_reason = "dte_limit"
                exit_idx = idx
                break

        total_pnl = pnl_per_unit * self.config.lots * self.config.lot_size

        exit_row = self.data.iloc[exit_idx]
        exit_date = self.data.index[exit_idx]
        if hasattr(exit_date, "date"):
            exit_date = exit_date.date()

        return TradeResult(
            signal_date=signal_date,
            entry_date=entry_date,
            exit_date=exit_date,
            strategy=strat_name,
            entry_spot=spot,
            exit_spot=exit_row.get("nifty_close", spot),
            entry_vix=vix,
            exit_vix=exit_row.get("vix", vix),
            net_credit=entry_credit,
            pnl_per_unit=pnl_per_unit,
            total_pnl=total_pnl,
            pnl_pct=(pnl_per_unit / entry_credit * 100) if entry_credit > 0 else 0,
            exit_reason=exit_reason,
            holding_days=(exit_date - entry_date).days if isinstance(exit_date, date) else 0,
            legs_detail=f"{strat_name} sd={sd} w={spread_width} short={short_strike} long={long_strike}",
        )

    # ─────────────────────────────────────────────────────────────────────
    # Helper: resolve fill row and common entry scalars
    # ─────────────────────────────────────────────────────────────────────

    def _entry_context(self, entry_idx: int):
        """Return (signal_date, fill_idx, spot, vix, entry_date) for a given entry index."""
        signal_row = self.data.iloc[entry_idx]
        signal_vix  = signal_row["vix"]
        signal_date = self.data.index[entry_idx]
        if hasattr(signal_date, "date"):
            signal_date = signal_date.date()

        fill_idx   = entry_idx + 1
        row        = self.data.iloc[fill_idx]
        spot       = row.get("nifty_open", row["nifty_close"])
        vix        = signal_vix
        entry_date = self.data.index[fill_idx]
        if hasattr(entry_date, "date"):
            entry_date = entry_date.date()
        return signal_date, fill_idx, spot, vix, entry_date

    def _make_result(
        self,
        signal_date, entry_date, fill_idx: int,
        strat_name: str,
        spot: float, vix: float,
        net_credit: float,
        pnl_per_unit: float,
        exit_idx: int,
        exit_reason: str,
        legs_detail: str,
        reference_for_pct: float | None = None,
    ) -> TradeResult:
        """Assemble a TradeResult from common scalars."""
        exit_row  = self.data.iloc[exit_idx]
        exit_date = self.data.index[exit_idx]
        if hasattr(exit_date, "date"):
            exit_date = exit_date.date()
        ref = reference_for_pct if reference_for_pct is not None else net_credit
        pnl_pct = (pnl_per_unit / ref * 100) if ref != 0 else 0.0
        return TradeResult(
            signal_date=signal_date,
            entry_date=entry_date,
            exit_date=exit_date,
            strategy=strat_name,
            entry_spot=spot,
            exit_spot=exit_row.get("nifty_close", spot),
            entry_vix=vix,
            exit_vix=exit_row.get("vix", vix),
            net_credit=net_credit,
            pnl_per_unit=pnl_per_unit,
            total_pnl=pnl_per_unit * self.config.lots * self.config.lot_size,
            pnl_pct=pnl_pct,
            exit_reason=exit_reason,
            holding_days=(exit_date - entry_date).days if isinstance(exit_date, date) else 0,
            legs_detail=legs_detail,
        )

    # ─────────────────────────────────────────────────────────────────────
    # Iron Condor — 4 legs: short put + long put + short call + long call
    # Teaches: symmetric range-bound theta, both-skew pricing
    # ─────────────────────────────────────────────────────────────────────

    def _simulate_iron_condor(self, entry_idx: int, strat_cfg: dict) -> Optional[TradeResult]:
        signal_date, fill_idx, spot, vix, entry_date = self._entry_context(entry_idx)
        dte      = self.config.hold_days
        psd      = strat_cfg["put_sd"]
        csd      = strat_cfg["call_sd"]
        width    = strat_cfg["spread_width"]
        period_v = (vix / 100.0) / (252 ** 0.5) * (dte ** 0.5)

        sp_strike = round((spot - spot * period_v * psd) / 50) * 50
        lp_strike = sp_strike - width
        sc_strike = round((spot + spot * period_v * csd) / 50) * 50
        lc_strike = sc_strike + width

        sp_iv = iv_from_vix(vix, sp_strike, spot, OptionType.PUT)
        lp_iv = iv_from_vix(vix, lp_strike, spot, OptionType.PUT)
        sc_iv = iv_from_vix(vix, sc_strike, spot, OptionType.CALL)
        lc_iv = iv_from_vix(vix, lc_strike, spot, OptionType.CALL)

        sp_prem = price_option(spot, sp_strike, dte, sp_iv, 0.065, OptionType.PUT).premium
        lp_prem = price_option(spot, lp_strike, dte, lp_iv, 0.065, OptionType.PUT).premium
        sc_prem = price_option(spot, sc_strike, dte, sc_iv, 0.065, OptionType.CALL).premium
        lc_prem = price_option(spot, lc_strike, dte, lc_iv, 0.065, OptionType.CALL).premium

        net_credit = (sp_prem - lp_prem) + (sc_prem - lc_prem)
        if net_credit <= 0:
            return None
        max_loss = width - net_credit

        exit_reason = "expiry"
        exit_idx    = min(fill_idx + dte, len(self.data) - 1)
        pnl_per_unit = 0.0

        for day_offset in range(1, dte + 1):
            idx = fill_idx + day_offset
            if idx >= len(self.data):
                break
            day_row  = self.data.iloc[idx]
            ds       = day_row.get("nifty_close", spot)
            dv       = day_row.get("vix", vix)
            dte_rem  = max(dte - day_offset, 1)
            if pd.isna(ds) or pd.isna(dv):
                continue

            sp_n = price_option(ds, sp_strike, dte_rem, iv_from_vix(dv, sp_strike, ds, OptionType.PUT),  0.065, OptionType.PUT).premium
            lp_n = price_option(ds, lp_strike, dte_rem, iv_from_vix(dv, lp_strike, ds, OptionType.PUT),  0.065, OptionType.PUT).premium
            sc_n = price_option(ds, sc_strike, dte_rem, iv_from_vix(dv, sc_strike, ds, OptionType.CALL), 0.065, OptionType.CALL).premium
            lc_n = price_option(ds, lc_strike, dte_rem, iv_from_vix(dv, lc_strike, ds, OptionType.CALL), 0.065, OptionType.CALL).premium
            current_cost = (sp_n - lp_n) + (sc_n - lc_n)
            pnl_per_unit = net_credit - current_cost

            if pnl_per_unit >= net_credit * self.config.profit_target_pct / 100:
                exit_reason, exit_idx = "profit_target", idx; break
            if pnl_per_unit < 0 and abs(pnl_per_unit) > max_loss * self.config.stop_loss_pct / 100:
                exit_reason, exit_idx = "stop_loss", idx; break
            if dte_rem <= 3:
                exit_reason, exit_idx = "dte_limit", idx; break

        return self._make_result(
            signal_date, entry_date, fill_idx, "iron_condor", spot, vix,
            net_credit, pnl_per_unit, exit_idx, exit_reason,
            f"iron_condor psd={psd} csd={csd} w={width}",
        )

    # ─────────────────────────────────────────────────────────────────────
    # Iron Butterfly — ATM short straddle + OTM wings
    # Teaches: highest theta/gamma, pinning regime, ultra-low VIX
    # ─────────────────────────────────────────────────────────────────────

    def _simulate_iron_butterfly(self, entry_idx: int, strat_cfg: dict) -> Optional[TradeResult]:
        signal_date, fill_idx, spot, vix, entry_date = self._entry_context(entry_idx)
        dte   = self.config.hold_days
        width = strat_cfg["wing_width"]

        atm       = round(spot / 50) * 50
        lp_strike = atm - width
        lc_strike = atm + width

        sc_iv = iv_from_vix(vix, atm,       spot, OptionType.CALL)
        sp_iv = iv_from_vix(vix, atm,       spot, OptionType.PUT)
        lc_iv = iv_from_vix(vix, lc_strike, spot, OptionType.CALL)
        lp_iv = iv_from_vix(vix, lp_strike, spot, OptionType.PUT)

        sc_prem = price_option(spot, atm,       dte, sc_iv, 0.065, OptionType.CALL).premium
        sp_prem = price_option(spot, atm,       dte, sp_iv, 0.065, OptionType.PUT).premium
        lc_prem = price_option(spot, lc_strike, dte, lc_iv, 0.065, OptionType.CALL).premium
        lp_prem = price_option(spot, lp_strike, dte, lp_iv, 0.065, OptionType.PUT).premium

        net_credit = sc_prem + sp_prem - lc_prem - lp_prem
        if net_credit <= 0:
            return None
        max_loss = width - net_credit

        exit_reason  = "expiry"
        exit_idx     = min(fill_idx + dte, len(self.data) - 1)
        pnl_per_unit = 0.0

        for day_offset in range(1, dte + 1):
            idx = fill_idx + day_offset
            if idx >= len(self.data):
                break
            day_row = self.data.iloc[idx]
            ds      = day_row.get("nifty_close", spot)
            dv      = day_row.get("vix", vix)
            dte_rem = max(dte - day_offset, 1)
            if pd.isna(ds) or pd.isna(dv):
                continue

            sc_n = price_option(ds, atm,       dte_rem, iv_from_vix(dv, atm,       ds, OptionType.CALL), 0.065, OptionType.CALL).premium
            sp_n = price_option(ds, atm,       dte_rem, iv_from_vix(dv, atm,       ds, OptionType.PUT),  0.065, OptionType.PUT).premium
            lc_n = price_option(ds, lc_strike, dte_rem, iv_from_vix(dv, lc_strike, ds, OptionType.CALL), 0.065, OptionType.CALL).premium
            lp_n = price_option(ds, lp_strike, dte_rem, iv_from_vix(dv, lp_strike, ds, OptionType.PUT),  0.065, OptionType.PUT).premium
            pnl_per_unit = net_credit - (sc_n + sp_n - lc_n - lp_n)

            if pnl_per_unit >= net_credit * self.config.profit_target_pct / 100:
                exit_reason, exit_idx = "profit_target", idx; break
            if pnl_per_unit < 0 and abs(pnl_per_unit) > max_loss * self.config.stop_loss_pct / 100:
                exit_reason, exit_idx = "stop_loss", idx; break
            if dte_rem <= 3:
                exit_reason, exit_idx = "dte_limit", idx; break

        return self._make_result(
            signal_date, entry_date, fill_idx, "iron_butterfly", spot, vix,
            net_credit, pnl_per_unit, exit_idx, exit_reason,
            f"iron_butterfly atm={atm} w={width}",
        )

    # ─────────────────────────────────────────────────────────────────────
    # Broken Wing Butterfly — asymmetric 3-leg put structure
    # Teaches: directional skew, asymmetric convexity, high-VIX entries
    # ─────────────────────────────────────────────────────────────────────

    def _simulate_bwb(self, entry_idx: int, strat_cfg: dict) -> Optional[TradeResult]:
        """Broken Wing Butterfly — asymmetric structure for net credit.

        Structure: 2 short puts at body_sd (moderate OTM) + 1 long put at long_sd (closer to ATM).
        Since long_sd < body_sd, the long put is more expensive per unit but we sell 2 body puts,
        so net_credit = 2*body_prem - long_prem is positive when body is sufficiently OTM.
        No upper wing hedge — the asymmetry creates directional downside exposure.
        """
        signal_date, fill_idx, spot, vix, entry_date = self._entry_context(entry_idx)
        dte      = self.config.hold_days
        body_sd  = strat_cfg["body_sd"]   # moderate OTM (further from spot) — sell 2
        long_sd  = strat_cfg["long_sd"]   # closer OTM (nearer spot) — buy 1
        period_v = (vix / 100.0) / (252 ** 0.5) * (dte ** 0.5)

        body_strike = round((spot - spot * period_v * body_sd) / 50) * 50  # 2× short
        long_strike = round((spot - spot * period_v * long_sd) / 50) * 50  # 1× long

        body_iv = iv_from_vix(vix, body_strike, spot, OptionType.PUT)
        long_iv = iv_from_vix(vix, long_strike, spot, OptionType.PUT)

        body_prem = price_option(spot, body_strike, dte, body_iv, 0.065, OptionType.PUT).premium
        long_prem = price_option(spot, long_strike, dte, long_iv, 0.065, OptionType.PUT).premium

        # net_credit = 2*body_prem - long_prem (positive when body is deep enough OTM)
        net_credit = 2 * body_prem - long_prem
        if net_credit <= 0:
            return None

        exit_reason  = "expiry"
        exit_idx     = min(fill_idx + dte, len(self.data) - 1)
        pnl_per_unit = 0.0

        for day_offset in range(1, dte + 1):
            idx = fill_idx + day_offset
            if idx >= len(self.data):
                break
            day_row = self.data.iloc[idx]
            ds      = day_row.get("nifty_close", spot)
            dv      = day_row.get("vix", vix)
            dte_rem = max(dte - day_offset, 1)
            if pd.isna(ds) or pd.isna(dv):
                continue

            body_n = price_option(ds, body_strike, dte_rem, iv_from_vix(dv, body_strike, ds, OptionType.PUT), 0.065, OptionType.PUT).premium
            long_n = price_option(ds, long_strike, dte_rem, iv_from_vix(dv, long_strike, ds, OptionType.PUT), 0.065, OptionType.PUT).premium
            pnl_per_unit = net_credit - (2 * body_n - long_n)

            if pnl_per_unit >= net_credit * self.config.profit_target_pct / 100:
                exit_reason, exit_idx = "profit_target", idx; break
            if pnl_per_unit < 0 and abs(pnl_per_unit) > net_credit * self.config.stop_loss_pct / 100:
                exit_reason, exit_idx = "stop_loss", idx; break
            if dte_rem <= 3:
                exit_reason, exit_idx = "dte_limit", idx; break

        return self._make_result(
            signal_date, entry_date, fill_idx, "broken_wing_butterfly", spot, vix,
            net_credit, pnl_per_unit, exit_idx, exit_reason,
            f"bwb body_sd={body_sd} long_sd={long_sd} body={body_strike} long={long_strike}",
        )

    # ─────────────────────────────────────────────────────────────────────
    # Ratio Put Spread — sell 1 put, buy 2 far-OTM puts (1:2)
    # Teaches: long gamma tail, crash upside, high-VIX entries
    # ─────────────────────────────────────────────────────────────────────

    def _simulate_ratio_put(self, entry_idx: int, strat_cfg: dict) -> Optional[TradeResult]:
        signal_date, fill_idx, spot, vix, entry_date = self._entry_context(entry_idx)
        dte      = self.config.hold_days
        short_sd = strat_cfg["short_sd"]
        long_sd  = strat_cfg["long_sd"]
        period_v = (vix / 100.0) / (252 ** 0.5) * (dte ** 0.5)

        sp_strike = round((spot - spot * period_v * short_sd) / 50) * 50
        lp_strike = round((spot - spot * period_v * long_sd)  / 50) * 50

        sp_iv = iv_from_vix(vix, sp_strike, spot, OptionType.PUT)
        lp_iv = iv_from_vix(vix, lp_strike, spot, OptionType.PUT)

        sp_prem = price_option(spot, sp_strike, dte, sp_iv, 0.065, OptionType.PUT).premium
        lp_prem = price_option(spot, lp_strike, dte, lp_iv, 0.065, OptionType.PUT).premium

        net_credit = sp_prem - 2 * lp_prem
        if net_credit <= 0:
            return None

        exit_reason  = "expiry"
        exit_idx     = min(fill_idx + dte, len(self.data) - 1)
        pnl_per_unit = 0.0

        for day_offset in range(1, dte + 1):
            idx = fill_idx + day_offset
            if idx >= len(self.data):
                break
            day_row = self.data.iloc[idx]
            ds      = day_row.get("nifty_close", spot)
            dv      = day_row.get("vix", vix)
            dte_rem = max(dte - day_offset, 1)
            if pd.isna(ds) or pd.isna(dv):
                continue

            sp_n = price_option(ds, sp_strike, dte_rem, iv_from_vix(dv, sp_strike, ds, OptionType.PUT), 0.065, OptionType.PUT).premium
            lp_n = price_option(ds, lp_strike, dte_rem, iv_from_vix(dv, lp_strike, ds, OptionType.PUT), 0.065, OptionType.PUT).premium
            pnl_per_unit = net_credit - (sp_n - 2 * lp_n)

            if pnl_per_unit >= net_credit * self.config.profit_target_pct / 100:
                exit_reason, exit_idx = "profit_target", idx; break
            if pnl_per_unit < 0 and abs(pnl_per_unit) > net_credit * self.config.stop_loss_pct / 100:
                exit_reason, exit_idx = "stop_loss", idx; break
            if dte_rem <= 3:
                exit_reason, exit_idx = "dte_limit", idx; break

        return self._make_result(
            signal_date, entry_date, fill_idx, "ratio_put_spread", spot, vix,
            net_credit, pnl_per_unit, exit_idx, exit_reason,
            f"ratio_put short_sd={short_sd} long_sd={long_sd} sp={sp_strike} lp={lp_strike}",
        )

    # ─────────────────────────────────────────────────────────────────────
    # Calendar Spread — near-term short + far-term long ATM put (dual DTE)
    # Teaches: IV term structure, vega-theta tradeoff, low-VIX regimes
    # ─────────────────────────────────────────────────────────────────────

    def _simulate_calendar(self, entry_idx: int, strat_cfg: dict) -> Optional[TradeResult]:
        """Calendar Spread — short near-term put + long far-term put at ATM.

        Calendars are net-debit structures (far_prem > near_prem). Profit comes from
        the near-term short decaying faster than the long. P&L is tracked as change in
        the spread value (long_value - short_value) vs initial net debit paid.
        pnl_pct is referenced against the initial net_debit (positive = profit).
        """
        signal_date, fill_idx, spot, vix, entry_date = self._entry_context(entry_idx)
        near_dte = strat_cfg["near_dte"]
        far_dte  = strat_cfg["far_dte"]

        atm      = round(spot / 50) * 50
        near_iv  = iv_from_vix(vix, atm, spot, OptionType.PUT, dte=near_dte)
        far_iv   = iv_from_vix(vix, atm, spot, OptionType.PUT, dte=far_dte)
        near_prem = price_option(spot, atm, near_dte, near_iv, 0.065, OptionType.PUT).premium
        far_prem  = price_option(spot, atm, far_dte,  far_iv,  0.065, OptionType.PUT).premium

        # Net debit = what we pay upfront (far - near); must be positive
        net_debit = far_prem - near_prem
        if net_debit <= 0:
            return None

        exit_reason  = "expiry"
        exit_idx     = min(fill_idx + near_dte, len(self.data) - 1)
        pnl_per_unit = 0.0

        for day_offset in range(1, near_dte + 1):
            idx = fill_idx + day_offset
            if idx >= len(self.data):
                break
            day_row  = self.data.iloc[idx]
            ds       = day_row.get("nifty_close", spot)
            dv       = day_row.get("vix", vix)
            near_rem = max(near_dte - day_offset, 1)
            far_rem  = max(far_dte  - day_offset, 1)
            if pd.isna(ds) or pd.isna(dv):
                continue

            n_iv   = iv_from_vix(dv, atm, ds, OptionType.PUT, dte=near_rem)
            f_iv   = iv_from_vix(dv, atm, ds, OptionType.PUT, dte=far_rem)
            near_n = price_option(ds, atm, near_rem, n_iv, 0.065, OptionType.PUT).premium
            far_n  = price_option(ds, atm, far_rem,  f_iv, 0.065, OptionType.PUT).premium
            # Spread value now = far_n - near_n; P&L vs what we paid
            spread_now   = far_n - near_n
            pnl_per_unit = spread_now - net_debit

            if pnl_per_unit >= net_debit * self.config.profit_target_pct / 100:
                exit_reason, exit_idx = "profit_target", idx; break
            if pnl_per_unit < 0 and abs(pnl_per_unit) > net_debit * self.config.stop_loss_pct / 100:
                exit_reason, exit_idx = "stop_loss", idx; break
            if near_rem <= 3:
                exit_reason, exit_idx = "dte_limit", idx; break

        # For ML training, store net_credit as -net_debit (negative = paid premium)
        # but pnl_pct is referenced against net_debit so positive pnl = profit
        return self._make_result(
            signal_date, entry_date, fill_idx, "calendar_spread", spot, vix,
            net_credit=-net_debit,   # negative signals net debit structure
            pnl_per_unit=pnl_per_unit,
            exit_idx=exit_idx,
            exit_reason=exit_reason,
            legs_detail=f"calendar atm={atm} near_dte={near_dte} far_dte={far_dte}",
            reference_for_pct=net_debit,   # pnl_pct relative to cost paid
        )

    # ─────────────────────────────────────────────────────────────────────
    # Diagonal Spread — near OTM short put + far deeper long put (dual DTE+strike)
    # Teaches: term structure + directional skew combined
    # ─────────────────────────────────────────────────────────────────────

    def _simulate_diagonal(self, entry_idx: int, strat_cfg: dict) -> Optional[TradeResult]:
        signal_date, fill_idx, spot, vix, entry_date = self._entry_context(entry_idx)
        near_dte  = strat_cfg["near_dte"]
        far_dte   = strat_cfg["far_dte"]
        short_sd  = strat_cfg["short_sd"]
        long_sd   = strat_cfg["long_sd"]
        period_v  = (vix / 100.0) / (252 ** 0.5) * (near_dte ** 0.5)

        sp_strike = round((spot - spot * period_v * short_sd) / 50) * 50
        lp_strike = round((spot - spot * period_v * long_sd)  / 50) * 50

        sp_iv = iv_from_vix(vix, sp_strike, spot, OptionType.PUT, dte=near_dte)
        lp_iv = iv_from_vix(vix, lp_strike, spot, OptionType.PUT, dte=far_dte)
        sp_prem = price_option(spot, sp_strike, near_dte, sp_iv, 0.065, OptionType.PUT).premium
        lp_prem = price_option(spot, lp_strike, far_dte,  lp_iv, 0.065, OptionType.PUT).premium

        # Diagonal can be net credit (short near OTM > long far deep OTM) or net debit
        # Use abs value as reference; track P&L as position change
        net_value    = sp_prem - lp_prem   # positive = net credit, negative = net debit
        ref_value    = abs(net_value) if net_value != 0 else sp_prem
        if ref_value <= 0:
            return None

        exit_reason  = "expiry"
        exit_idx     = min(fill_idx + near_dte, len(self.data) - 1)
        pnl_per_unit = 0.0

        for day_offset in range(1, near_dte + 1):
            idx = fill_idx + day_offset
            if idx >= len(self.data):
                break
            day_row  = self.data.iloc[idx]
            ds       = day_row.get("nifty_close", spot)
            dv       = day_row.get("vix", vix)
            near_rem = max(near_dte - day_offset, 1)
            far_rem  = max(far_dte  - day_offset, 1)
            if pd.isna(ds) or pd.isna(dv):
                continue

            sp_n = price_option(ds, sp_strike, near_rem, iv_from_vix(dv, sp_strike, ds, OptionType.PUT, dte=near_rem), 0.065, OptionType.PUT).premium
            lp_n = price_option(ds, lp_strike, far_rem,  iv_from_vix(dv, lp_strike, ds, OptionType.PUT, dte=far_rem),  0.065, OptionType.PUT).premium
            # P&L: gain on short (sp decays) + loss on long (lp decays)
            pnl_per_unit = (sp_prem - sp_n) - (lp_prem - lp_n)

            if pnl_per_unit >= ref_value * self.config.profit_target_pct / 100:
                exit_reason, exit_idx = "profit_target", idx; break
            if pnl_per_unit < 0 and abs(pnl_per_unit) > ref_value * self.config.stop_loss_pct / 100:
                exit_reason, exit_idx = "stop_loss", idx; break
            if near_rem <= 3:
                exit_reason, exit_idx = "dte_limit", idx; break

        return self._make_result(
            signal_date, entry_date, fill_idx, "diagonal_spread", spot, vix,
            net_credit=net_value, pnl_per_unit=pnl_per_unit,
            exit_idx=exit_idx, exit_reason=exit_reason,
            legs_detail=f"diagonal sp={sp_strike}/{near_dte}d lp={lp_strike}/{far_dte}d",
            reference_for_pct=ref_value,
        )

    # ─────────────────────────────────────────────────────────────────────
    # Jade Lizard — short OTM put + bear call spread (credit > call width)
    # Teaches: asymmetric upside removal, skew-skew pricing, theta quality
    # ─────────────────────────────────────────────────────────────────────

    def _simulate_jade_lizard(self, entry_idx: int, strat_cfg: dict) -> Optional[TradeResult]:
        signal_date, fill_idx, spot, vix, entry_date = self._entry_context(entry_idx)
        dte      = self.config.hold_days
        put_sd   = strat_cfg["put_sd"]
        call_sd  = strat_cfg["call_sd"]
        c_width  = strat_cfg["call_width"]
        period_v = (vix / 100.0) / (252 ** 0.5) * (dte ** 0.5)

        sp_strike = round((spot - spot * period_v * put_sd)  / 50) * 50   # short OTM put
        sc_strike = round((spot + spot * period_v * call_sd) / 50) * 50   # short OTM call
        lc_strike = sc_strike + c_width                                    # long OTM call (hedge)

        sp_iv = iv_from_vix(vix, sp_strike, spot, OptionType.PUT)
        sc_iv = iv_from_vix(vix, sc_strike, spot, OptionType.CALL)
        lc_iv = iv_from_vix(vix, lc_strike, spot, OptionType.CALL)

        sp_prem = price_option(spot, sp_strike, dte, sp_iv, 0.065, OptionType.PUT).premium
        sc_prem = price_option(spot, sc_strike, dte, sc_iv, 0.065, OptionType.CALL).premium
        lc_prem = price_option(spot, lc_strike, dte, lc_iv, 0.065, OptionType.CALL).premium

        call_spread_credit = sc_prem - lc_prem
        net_credit = sp_prem + call_spread_credit
        # Jade Lizard condition: total credit must exceed call spread width (no upside risk)
        if net_credit <= 0 or call_spread_credit <= 0:
            return None

        exit_reason  = "expiry"
        exit_idx     = min(fill_idx + dte, len(self.data) - 1)
        pnl_per_unit = 0.0

        for day_offset in range(1, dte + 1):
            idx = fill_idx + day_offset
            if idx >= len(self.data):
                break
            day_row = self.data.iloc[idx]
            ds      = day_row.get("nifty_close", spot)
            dv      = day_row.get("vix", vix)
            dte_rem = max(dte - day_offset, 1)
            if pd.isna(ds) or pd.isna(dv):
                continue

            sp_n = price_option(ds, sp_strike, dte_rem, iv_from_vix(dv, sp_strike, ds, OptionType.PUT),  0.065, OptionType.PUT).premium
            sc_n = price_option(ds, sc_strike, dte_rem, iv_from_vix(dv, sc_strike, ds, OptionType.CALL), 0.065, OptionType.CALL).premium
            lc_n = price_option(ds, lc_strike, dte_rem, iv_from_vix(dv, lc_strike, ds, OptionType.CALL), 0.065, OptionType.CALL).premium
            pnl_per_unit = net_credit - (sp_n + sc_n - lc_n)

            if pnl_per_unit >= net_credit * self.config.profit_target_pct / 100:
                exit_reason, exit_idx = "profit_target", idx; break
            if pnl_per_unit < 0 and abs(pnl_per_unit) > net_credit * self.config.stop_loss_pct / 100:
                exit_reason, exit_idx = "stop_loss", idx; break
            if dte_rem <= 3:
                exit_reason, exit_idx = "dte_limit", idx; break

        return self._make_result(
            signal_date, entry_date, fill_idx, "jade_lizard", spot, vix,
            net_credit, pnl_per_unit, exit_idx, exit_reason,
            f"jade_lizard sp={sp_strike} sc={sc_strike} lc={lc_strike}",
        )

    # ─────────────────────────────────────────────────────────────────────
    # Put Backspread — sell 1 ATM put, buy 2 far-OTM puts (reversed ratio)
    # Teaches: long vega/gamma, BREAKS uniform short-option negative skew
    # Can be net debit; pnl_pct referenced against abs(net_cost)
    # ─────────────────────────────────────────────────────────────────────

    def _simulate_put_backspread(self, entry_idx: int, strat_cfg: dict) -> Optional[TradeResult]:
        signal_date, fill_idx, spot, vix, entry_date = self._entry_context(entry_idx)
        dte      = self.config.hold_days
        short_sd = strat_cfg["short_sd"]
        long_sd  = strat_cfg["long_sd"]
        period_v = (vix / 100.0) / (252 ** 0.5) * (dte ** 0.5)

        sp_strike = round((spot - spot * period_v * short_sd) / 50) * 50  # sell 1 (closer to ATM)
        lp_strike = round((spot - spot * period_v * long_sd)  / 50) * 50  # buy 2 (far OTM)

        sp_iv = iv_from_vix(vix, sp_strike, spot, OptionType.PUT)
        lp_iv = iv_from_vix(vix, lp_strike, spot, OptionType.PUT)
        sp_prem = price_option(spot, sp_strike, dte, sp_iv, 0.065, OptionType.PUT).premium
        lp_prem = price_option(spot, lp_strike, dte, lp_iv, 0.065, OptionType.PUT).premium

        # net = short_prem - 2*long_prem (often negative → net debit)
        net_credit = sp_prem - 2 * lp_prem
        net_cost   = -net_credit  # positive when net debit
        # Reference for pnl_pct: use abs value of the position cost (debit or credit)
        ref_value  = abs(net_credit) if net_credit != 0 else sp_prem

        # Skip if both strikes are the same (degenerate)
        if sp_strike <= lp_strike:
            return None

        exit_reason  = "expiry"
        exit_idx     = min(fill_idx + dte, len(self.data) - 1)
        pnl_per_unit = 0.0

        for day_offset in range(1, dte + 1):
            idx = fill_idx + day_offset
            if idx >= len(self.data):
                break
            day_row = self.data.iloc[idx]
            ds      = day_row.get("nifty_close", spot)
            dv      = day_row.get("vix", vix)
            dte_rem = max(dte - day_offset, 1)
            if pd.isna(ds) or pd.isna(dv):
                continue

            sp_n = price_option(ds, sp_strike, dte_rem, iv_from_vix(dv, sp_strike, ds, OptionType.PUT), 0.065, OptionType.PUT).premium
            lp_n = price_option(ds, lp_strike, dte_rem, iv_from_vix(dv, lp_strike, ds, OptionType.PUT), 0.065, OptionType.PUT).premium
            # P&L = change in position value: (sp_n - sp_prem) is a loss (short), (2*lp_n - 2*lp_prem) is a gain
            pnl_per_unit = (sp_prem - sp_n) + 2 * (lp_n - lp_prem)

            profit_threshold = ref_value * self.config.profit_target_pct / 100
            loss_threshold   = ref_value * self.config.stop_loss_pct    / 100
            if pnl_per_unit >= profit_threshold:
                exit_reason, exit_idx = "profit_target", idx; break
            if pnl_per_unit < -loss_threshold:
                exit_reason, exit_idx = "stop_loss", idx; break
            if dte_rem <= 3:
                exit_reason, exit_idx = "dte_limit", idx; break

        return self._make_result(
            signal_date, entry_date, fill_idx, "put_backspread", spot, vix,
            net_credit, pnl_per_unit, exit_idx, exit_reason,
            f"put_backspread short_sd={short_sd} long_sd={long_sd} sp={sp_strike} lp={lp_strike}",
            reference_for_pct=ref_value,
        )
