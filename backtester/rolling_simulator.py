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
    # Put Credit Spreads — vary distance and width
    {
        "name": "put_credit_spread",
        "direction": "put",
        "sd": 1.0,
        "spread_width": 500,
        "min_vix": 12,
        "max_vix": 100,
    },
    {
        "name": "put_credit_spread",
        "direction": "put",
        "sd": 1.2,
        "spread_width": 500,
        "min_vix": 15,
        "max_vix": 100,
    },
    {
        "name": "put_credit_spread",
        "direction": "put",
        "sd": 0.8,
        "spread_width": 400,
        "min_vix": 13,
        "max_vix": 25,
    },
    # Call-side verticals (labeled put_credit_wide for ML / regime keys)
    {
        "name": "put_credit_wide",
        "direction": "call",
        "sd": 0.8,
        "spread_width": 500,
        "min_vix": 10,
        "max_vix": 22,
    },
    {
        "name": "put_credit_wide",
        "direction": "call",
        "sd": 1.0,
        "spread_width": 500,
        "min_vix": 12,
        "max_vix": 25,
    },
    {
        "name": "put_credit_wide",
        "direction": "call",
        "sd": 0.6,
        "spread_width": 300,
        "min_vix": 10,
        "max_vix": 18,
    },
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

                trade = self._simulate_trade(entry_idx, strat_cfg)
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
