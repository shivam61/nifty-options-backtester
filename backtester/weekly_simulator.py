"""
Weekly Trade Simulator — generates training samples for the weekly ML entry model.

Simulates overlapping short-DTE (3-8 day) trades across the full dataset,
entering on Mon/Tue and pricing via Black-Scholes to track outcomes.
Produces TradeResult-compatible objects for WeeklyEntryLearner training.

v2: Gap-aware simulation — overnight gaps are modelled as discontinuities with
    IV shock repricing. Uses GapRiskModel to compute true worst-case loss.
"""

from dataclasses import dataclass
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd

from config import WeeklyBacktestConfig
from pricing.black_scholes import price_option, iv_from_vix, OptionType
from pricing.gap_risk import GapRiskModel
from data.expiry_calendar import get_weekly_expiry_in_range


@dataclass
class WeeklySimConfig:
    entry_every_n_days: int = 2
    lots: int = 2
    lot_size: int = 65
    profit_target_pct: float = WeeklyBacktestConfig().engine_a_profit_target_pct
    stop_loss_pct: float = WeeklyBacktestConfig().stop_loss_pct
    min_dte: int = 3
    max_dte: int = 8
    min_vix: float = 10.0
    max_vix: float = 25.0
    engine_a_min_hold_days: int = WeeklyBacktestConfig().engine_a_min_hold_days
    engine_b_max_hold_days: int = WeeklyBacktestConfig().engine_b_max_hold_days
    engine_b_delta_trail_arm_ratio: float = WeeklyBacktestConfig().engine_b_delta_trail_arm_ratio
    engine_b_delta_trail_rebound_ratio: float = WeeklyBacktestConfig().engine_b_delta_trail_rebound_ratio
    engine_b_trend_trigger_pct: float = WeeklyBacktestConfig().engine_b_trend_trigger_pct
    engine_b_trend_reversal_pct: float = WeeklyBacktestConfig().engine_b_trend_reversal_pct


@dataclass
class WeeklySimTrade:
    signal_date: date
    entry_date: date
    exit_date: date
    strategy: str
    entry_spot: float
    exit_spot: float
    entry_vix: float
    exit_vix: float
    net_credit: float
    pnl_per_unit: float
    total_pnl: float
    pnl_pct: float
    exit_reason: str
    holding_days: int
    dte_at_entry: int
    legs_detail: str
    max_gap_pct: float = 0.0            # largest overnight gap during the trade
    gap_triggered_exit: bool = False     # whether a gap caused the stop-loss
    worst_case_gap_loss: float = 0.0    # stress-tested worst-case gap loss/unit


WEEKLY_STRATEGY_CONFIGS = [
    {
        "name": "weekly_pcs",
        "direction": "put",
        "sd": 0.9,
        "spread_width": 400,
        "min_vix": 10,
        "max_vix": 25,
    },
    {
        "name": "weekly_pcs",
        "direction": "put",
        "sd": 1.0,
        "spread_width": 300,
        "min_vix": 12,
        "max_vix": 25,
    },
    {
        "name": "weekly_pcs",
        "direction": "put",
        "sd": 0.8,
        "spread_width": 500,
        "min_vix": 10,
        "max_vix": 20,
    },
    {
        "name": "weekly_ic",
        "direction": "iron_condor",
        "call_sd": 0.7,
        "put_sd": 1.0,
        "spread_width": 300,
        "min_vix": 12,
        "max_vix": 22,
    },
    {
        "name": "weekly_ic",
        "direction": "iron_condor",
        "call_sd": 0.6,
        "put_sd": 0.9,
        "spread_width": 200,
        "min_vix": 12,
        "max_vix": 20,
    },
]


class WeeklyRollingSimulator:
    """
    Simulates overlapping weekly option trades for ML training data.

    Entry on Mon/Tue only (weekday 0 or 1), targeting the first weekly expiry
    that fits the configured DTE range.
    Tighter exits than monthly: 50% profit target, spread-width stop.

    v2: Gap-aware. Overnight gaps reprice at the open using IV shock before
    checking exits. This means a gap through the stop-loss is properly
    reflected — you eat the full gap loss, not the stop price.
    """

    def __init__(self, data: pd.DataFrame, config: WeeklySimConfig = WeeklySimConfig()):
        self.data = data
        self.config = config
        self.gap_model = GapRiskModel()
        if {"nifty_open", "nifty_close"}.issubset(data.columns):
            self.gap_model.fit(data)

    def simulate_all(self) -> list[WeeklySimTrade]:
        all_trades = []
        n_rows = len(self.data)

        for entry_idx in range(30, n_rows):
            if (entry_idx - 30) % self.config.entry_every_n_days != 0:
                continue

            row = self.data.iloc[entry_idx]
            spot = row.get("nifty_close", 0)
            vix = row.get("vix", 15)

            if pd.isna(spot) or spot == 0 or pd.isna(vix):
                continue

            current_date = self.data.index[entry_idx]
            if hasattr(current_date, "date"):
                current_date = current_date.date()

            if current_date.weekday() not in (0, 1):
                continue

            if vix < self.config.min_vix or vix > self.config.max_vix:
                continue

            exp, dte = get_weekly_expiry_in_range(
                current_date, self.config.min_dte, self.config.max_dte,
            )
            if exp is None:
                continue

            remaining_days = n_rows - entry_idx - 1
            if remaining_days < dte + 2:
                continue

            for strat_cfg in WEEKLY_STRATEGY_CONFIGS:
                if vix < strat_cfg["min_vix"] or vix > strat_cfg["max_vix"]:
                    continue
                trade = self._simulate_trade(entry_idx, current_date, exp, strat_cfg, dte)
                if trade:
                    all_trades.append(trade)

        return all_trades

    def _simulate_trade(self, entry_idx: int, signal_date: date, expiry_date: date, strat_cfg: dict,
                        dte: int) -> Optional[WeeklySimTrade]:
        fill_idx = entry_idx + 1
        signal_row = self.data.iloc[entry_idx]
        row = self.data.iloc[fill_idx]
        spot = row.get("nifty_open", row["nifty_close"])
        vix = signal_row["vix"]
        entry_date = self.data.index[fill_idx]
        if hasattr(entry_date, "date"):
            entry_date = entry_date.date()
        dte = max((expiry_date - entry_date).days, 1)

        annual_vol = vix / 100.0
        period_vol = annual_vol / (252 ** 0.5) * (dte ** 0.5)
        direction = strat_cfg["direction"]

        if direction == "put":
            sd = strat_cfg["sd"]
            width = strat_cfg["spread_width"]
            short_strike = round((spot - spot * period_vol * sd) / 50) * 50
            long_strike = short_strike - width

            s_iv = iv_from_vix(vix, short_strike, spot, OptionType.PUT)
            l_iv = iv_from_vix(vix, long_strike, spot, OptionType.PUT)
            s_prem = price_option(spot, short_strike, dte, s_iv, 0.065, OptionType.PUT).premium
            l_prem = price_option(spot, long_strike, dte, l_iv, 0.065, OptionType.PUT).premium
            entry_credit = s_prem - l_prem

            if entry_credit <= 0:
                return None

            max_loss = width - entry_credit
            detail = f"weekly_pcs sd={sd} w={width} S={short_strike} L={long_strike}"

            return self._run_daily_loop(
                entry_idx, entry_date, spot, vix, dte, entry_credit, max_loss,
                signal_date,
                short_strike, long_strike, OptionType.PUT, OptionType.PUT,
                strat_cfg["name"], detail,
            )

        elif direction == "iron_condor":
            call_sd = strat_cfg["call_sd"]
            put_sd = strat_cfg["put_sd"]
            width = strat_cfg["spread_width"]

            sc_strike = round((spot + spot * period_vol * call_sd) / 50) * 50
            lc_strike = sc_strike + width
            sp_strike = round((spot - spot * period_vol * put_sd) / 50) * 50
            lp_strike = sp_strike - width

            sc_iv = iv_from_vix(vix, sc_strike, spot, OptionType.CALL)
            lc_iv = iv_from_vix(vix, lc_strike, spot, OptionType.CALL)
            sp_iv = iv_from_vix(vix, sp_strike, spot, OptionType.PUT)
            lp_iv = iv_from_vix(vix, lp_strike, spot, OptionType.PUT)

            sc_p = price_option(spot, sc_strike, dte, sc_iv, 0.065, OptionType.CALL).premium
            lc_p = price_option(spot, lc_strike, dte, lc_iv, 0.065, OptionType.CALL).premium
            sp_p = price_option(spot, sp_strike, dte, sp_iv, 0.065, OptionType.PUT).premium
            lp_p = price_option(spot, lp_strike, dte, lp_iv, 0.065, OptionType.PUT).premium

            call_credit = sc_p - lc_p
            put_credit = sp_p - lp_p
            entry_credit = call_credit + put_credit

            if entry_credit <= 0:
                return None

            max_loss = width - entry_credit
            detail = f"weekly_ic csd={call_sd} psd={put_sd} w={width}"

            return self._run_ic_daily_loop(
                entry_idx, entry_date, spot, vix, dte, entry_credit, max_loss,
                signal_date,
                sc_strike, lc_strike, sp_strike, lp_strike, width,
                strat_cfg["name"], detail,
            )

        return None

    def _run_daily_loop(self, entry_idx, entry_date, spot, vix, dte,
                        entry_credit, max_loss, signal_date, short_strike, long_strike,
                        short_type, long_type, strat_name, detail):
        exit_reason = "expiry"
        fill_idx = entry_idx + 1
        exit_idx = min(fill_idx + dte, len(self.data) - 1)
        pnl_per_unit = 0
        max_gap_pct = 0.0
        gap_triggered = False
        prev_close = spot

        for day_offset in range(1, dte + 1):
            idx = fill_idx + day_offset
            if idx >= len(self.data):
                break

            day_row = self.data.iloc[idx]
            day_open = day_row.get("nifty_open", prev_close)
            day_spot = day_row.get("nifty_close", spot)
            day_vix = day_row.get("vix", vix)
            dte_rem = max(dte - day_offset, 1)

            if pd.isna(day_spot) or pd.isna(day_vix):
                continue

            # ── Phase 1: Overnight gap repricing at the open ──
            # The gap happened while you were sleeping — no stop-loss can help.
            gap_pct, vix_at_open = self.gap_model.apply_overnight_gap(
                prev_close, day_open, day_vix,
            )
            max_gap_pct = max(max_gap_pct, abs(gap_pct))

            if abs(gap_pct) >= 0.3:
                s_iv_open = iv_from_vix(vix_at_open, short_strike, day_open, short_type)
                l_iv_open = iv_from_vix(vix_at_open, long_strike, day_open, long_type)
                s_open = price_option(day_open, short_strike, dte_rem, s_iv_open, 0.065, short_type).premium
                l_open = price_option(day_open, long_strike, dte_rem, l_iv_open, 0.065, long_type).premium
                pnl_at_open = entry_credit - (s_open - l_open)

                if pnl_at_open < 0 and abs(pnl_at_open) > max_loss * 0.5:
                    pnl_per_unit = pnl_at_open
                    exit_reason = "gap_stop_loss"
                    exit_idx = idx
                    gap_triggered = True
                    break

            # ── Phase 2: Close-to-close repricing (as before) ──
            s_iv = iv_from_vix(day_vix, short_strike, day_spot, short_type)
            l_iv = iv_from_vix(day_vix, long_strike, day_spot, long_type)
            s_now = price_option(day_spot, short_strike, dte_rem, s_iv, 0.065, short_type).premium
            l_now = price_option(day_spot, long_strike, dte_rem, l_iv, 0.065, long_type).premium

            pnl_per_unit = entry_credit - (s_now - l_now)
            pnl_pct = (pnl_per_unit / entry_credit * 100) if entry_credit > 0 else 0

            if (
                day_offset >= self.config.engine_a_min_hold_days
                and pnl_pct >= self.config.profit_target_pct
            ):
                exit_reason = "profit_target"
                exit_idx = idx
                break

            if pnl_per_unit < 0 and abs(pnl_per_unit) > max_loss * 0.5:
                exit_reason = "stop_loss"
                exit_idx = idx
                break

            if short_type == OptionType.PUT and day_spot < short_strike:
                exit_reason = "stop_loss"
                exit_idx = idx
                break
            if short_type == OptionType.CALL and day_spot > short_strike:
                exit_reason = "stop_loss"
                exit_idx = idx
                break

            if dte_rem <= 1:
                exit_reason = "dte_limit"
                exit_idx = idx
                break

            prev_close = day_spot

        # Entry-time stress test: what's the worst a gap could do to this position?
        stress = self.gap_model.stress_test_spread(
            spot, vix, short_strike, long_strike, dte, entry_credit, short_type,
            self.config.lots, self.config.lot_size,
        )

        total_pnl = pnl_per_unit * self.config.lots * self.config.lot_size
        exit_row = self.data.iloc[exit_idx]
        exit_date = self.data.index[exit_idx]
        if hasattr(exit_date, "date"):
            exit_date = exit_date.date()

        return WeeklySimTrade(
            signal_date=signal_date,
            entry_date=entry_date, exit_date=exit_date, strategy=strat_name,
            entry_spot=spot, exit_spot=exit_row.get("nifty_close", spot),
            entry_vix=vix, exit_vix=exit_row.get("vix", vix),
            net_credit=entry_credit, pnl_per_unit=pnl_per_unit,
            total_pnl=total_pnl,
            pnl_pct=(pnl_per_unit / entry_credit * 100) if entry_credit > 0 else 0,
            exit_reason=exit_reason,
            holding_days=(exit_date - entry_date).days if isinstance(exit_date, date) else 0,
            dte_at_entry=dte,
            legs_detail=detail,
            max_gap_pct=max_gap_pct,
            gap_triggered_exit=gap_triggered,
            worst_case_gap_loss=stress.worst_case_loss_per_unit,
        )

    def _run_ic_daily_loop(self, entry_idx, entry_date, spot, vix, dte,
                           entry_credit, max_loss, signal_date,
                           sc_strike, lc_strike, sp_strike, lp_strike, width,
                           strat_name, detail):
        exit_reason = "expiry"
        fill_idx = entry_idx + 1
        exit_idx = min(fill_idx + dte, len(self.data) - 1)
        pnl_per_unit = 0
        max_gap_pct = 0.0
        gap_triggered = False
        prev_close = spot
        high_spot = spot
        low_spot = spot
        sc_iv = iv_from_vix(vix, sc_strike, spot, OptionType.CALL)
        lc_iv = iv_from_vix(vix, lc_strike, spot, OptionType.CALL)
        sp_iv = iv_from_vix(vix, sp_strike, spot, OptionType.PUT)
        lp_iv = iv_from_vix(vix, lp_strike, spot, OptionType.PUT)
        entry_abs_delta = abs(
            (
                -price_option(spot, sc_strike, dte, sc_iv, 0.065, OptionType.CALL).greeks.delta
                + price_option(spot, lc_strike, dte, lc_iv, 0.065, OptionType.CALL).greeks.delta
                - price_option(spot, sp_strike, dte, sp_iv, 0.065, OptionType.PUT).greeks.delta
                + price_option(spot, lp_strike, dte, lp_iv, 0.065, OptionType.PUT).greeks.delta
            ) * self.config.lots * self.config.lot_size
        )
        best_abs_delta = entry_abs_delta

        for day_offset in range(1, dte + 1):
            idx = fill_idx + day_offset
            if idx >= len(self.data):
                break

            day_row = self.data.iloc[idx]
            day_open = day_row.get("nifty_open", prev_close)
            day_spot = day_row.get("nifty_close", spot)
            day_vix = day_row.get("vix", vix)
            dte_rem = max(dte - day_offset, 1)

            if pd.isna(day_spot) or pd.isna(day_vix):
                continue

            # ── Phase 1: Overnight gap repricing at the open ──
            gap_pct, vix_at_open = self.gap_model.apply_overnight_gap(
                prev_close, day_open, day_vix,
            )
            max_gap_pct = max(max_gap_pct, abs(gap_pct))

            if abs(gap_pct) >= 0.3:
                sc_iv_o = iv_from_vix(vix_at_open, sc_strike, day_open, OptionType.CALL)
                lc_iv_o = iv_from_vix(vix_at_open, lc_strike, day_open, OptionType.CALL)
                sp_iv_o = iv_from_vix(vix_at_open, sp_strike, day_open, OptionType.PUT)
                lp_iv_o = iv_from_vix(vix_at_open, lp_strike, day_open, OptionType.PUT)

                sc_o = price_option(day_open, sc_strike, dte_rem, sc_iv_o, 0.065, OptionType.CALL).premium
                lc_o = price_option(day_open, lc_strike, dte_rem, lc_iv_o, 0.065, OptionType.CALL).premium
                sp_o = price_option(day_open, sp_strike, dte_rem, sp_iv_o, 0.065, OptionType.PUT).premium
                lp_o = price_option(day_open, lp_strike, dte_rem, lp_iv_o, 0.065, OptionType.PUT).premium

                pnl_at_open = entry_credit - ((sc_o - lc_o) + (sp_o - lp_o))

                if pnl_at_open < 0 and abs(pnl_at_open) > max_loss * 0.5:
                    pnl_per_unit = pnl_at_open
                    exit_reason = "gap_stop_loss"
                    exit_idx = idx
                    gap_triggered = True
                    break

            # ── Phase 2: Close-to-close repricing ──
            sc_iv = iv_from_vix(day_vix, sc_strike, day_spot, OptionType.CALL)
            lc_iv = iv_from_vix(day_vix, lc_strike, day_spot, OptionType.CALL)
            sp_iv = iv_from_vix(day_vix, sp_strike, day_spot, OptionType.PUT)
            lp_iv = iv_from_vix(day_vix, lp_strike, day_spot, OptionType.PUT)

            sc_now = price_option(day_spot, sc_strike, dte_rem, sc_iv, 0.065, OptionType.CALL).premium
            lc_now = price_option(day_spot, lc_strike, dte_rem, lc_iv, 0.065, OptionType.CALL).premium
            sp_now = price_option(day_spot, sp_strike, dte_rem, sp_iv, 0.065, OptionType.PUT).premium
            lp_now = price_option(day_spot, lp_strike, dte_rem, lp_iv, 0.065, OptionType.PUT).premium
            current_abs_delta = abs(
                (
                    -price_option(day_spot, sc_strike, dte_rem, sc_iv, 0.065, OptionType.CALL).greeks.delta
                    + price_option(day_spot, lc_strike, dte_rem, lc_iv, 0.065, OptionType.CALL).greeks.delta
                    - price_option(day_spot, sp_strike, dte_rem, sp_iv, 0.065, OptionType.PUT).greeks.delta
                    + price_option(day_spot, lp_strike, dte_rem, lp_iv, 0.065, OptionType.PUT).greeks.delta
                ) * self.config.lots * self.config.lot_size
            )
            best_abs_delta = min(best_abs_delta, current_abs_delta)
            high_spot = max(high_spot, day_spot)
            low_spot = min(low_spot, day_spot)

            call_debit = sc_now - lc_now
            put_debit = sp_now - lp_now
            pnl_per_unit = entry_credit - (call_debit + put_debit)
            pnl_pct = (pnl_per_unit / entry_credit * 100) if entry_credit > 0 else 0

            if (
                entry_abs_delta > 0
                and best_abs_delta <= entry_abs_delta * self.config.engine_b_delta_trail_arm_ratio
                and current_abs_delta >= best_abs_delta * self.config.engine_b_delta_trail_rebound_ratio
            ):
                exit_reason = "trailing_delta"
                exit_idx = idx
                break

            if pnl_per_unit < 0 and abs(pnl_per_unit) > max_loss * 0.5:
                exit_reason = "stop_loss"
                exit_idx = idx
                break

            if day_spot > sc_strike or day_spot < sp_strike:
                exit_reason = "stop_loss"
                exit_idx = idx
                break

            if (
                high_spot >= spot * (1 + self.config.engine_b_trend_trigger_pct)
                and day_spot <= high_spot * (1 - self.config.engine_b_trend_reversal_pct)
            ):
                exit_reason = "trend_reversal"
                exit_idx = idx
                break

            if (
                low_spot <= spot * (1 - self.config.engine_b_trend_trigger_pct)
                and day_spot >= low_spot * (1 + self.config.engine_b_trend_reversal_pct)
            ):
                exit_reason = "trend_reversal"
                exit_idx = idx
                break

            if day_offset >= self.config.engine_b_max_hold_days:
                exit_reason = "max_hold_time"
                exit_idx = idx
                break

            if dte_rem <= 1:
                exit_reason = "dte_limit"
                exit_idx = idx
                break

            prev_close = day_spot

        stress = self.gap_model.stress_test_iron_condor(
            spot, vix, sc_strike, lc_strike, sp_strike, lp_strike,
            dte, entry_credit, self.config.lots, self.config.lot_size,
        )

        total_pnl = pnl_per_unit * self.config.lots * self.config.lot_size
        exit_row = self.data.iloc[exit_idx]
        exit_date = self.data.index[exit_idx]
        if hasattr(exit_date, "date"):
            exit_date = exit_date.date()

        return WeeklySimTrade(
            signal_date=signal_date,
            entry_date=entry_date, exit_date=exit_date, strategy=strat_name,
            entry_spot=spot, exit_spot=exit_row.get("nifty_close", spot),
            entry_vix=vix, exit_vix=exit_row.get("vix", vix),
            net_credit=entry_credit, pnl_per_unit=pnl_per_unit,
            total_pnl=total_pnl,
            pnl_pct=(pnl_per_unit / entry_credit * 100) if entry_credit > 0 else 0,
            exit_reason=exit_reason,
            holding_days=(exit_date - entry_date).days if isinstance(exit_date, date) else 0,
            dte_at_entry=dte,
            legs_detail=detail,
            max_gap_pct=max_gap_pct,
            gap_triggered_exit=gap_triggered,
            worst_case_gap_loss=stress.worst_case_loss_per_unit,
        )
