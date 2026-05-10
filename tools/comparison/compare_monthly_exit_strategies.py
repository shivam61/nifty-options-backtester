#!/usr/bin/env python3
"""
Compare Monthly Strategy Exit Logic: Original vs 80% Max Profit Booking

Tests the 80% max profit booking approach on monthly options (15-45 DTE)
using Put Credit Spread and Iron Condor strategies.

This tests if longer holding periods benefit from the 80% exit logic.
"""

import argparse
import os
import sys
import random
from datetime import date
from pathlib import Path

os.environ["PYTHONHASHSEED"] = "42"
random.seed(42)

import numpy as np
import pandas as pd

np.random.seed(42)

from config import BacktestConfig
from data.market_data import MarketDataFetcher
from strategies.multi_strategy import PutCreditSpreadStrategy, IronCondorStrategy
from backtester.engine import BacktestEngine, BacktestResult


def add_max_profit_tracking_to_strategy(strategy_class):
    """
    Dynamically add 80% max profit booking to should_exit method.
    """
    original_should_exit = strategy_class.should_exit
    
    def modified_should_exit(self, trade, spot, vix, dte_remaining, max_profit_per_unit=0.0):
        # Call original exit logic first
        action, reason = original_should_exit(self, trade, spot, vix, dte_remaining)
        if action.name == "EXIT":
            return action, reason
        
        # NEW: 80% max profit booking logic
        pnl_unit = trade.pnl_per_unit
        credit = trade.net_credit
        
        if max_profit_per_unit > 0 and pnl_unit > 0 and credit > 0:
            # If current profit drops to 80% of max profit seen, exit
            if pnl_unit <= max_profit_per_unit * 0.80:
                from strategies.base import TradeAction, ExitReason
                return TradeAction.EXIT, ExitReason.PROFIT_TARGET
        
        return action, reason
    
    strategy_class.should_exit = modified_should_exit
    return strategy_class


def add_max_profit_tracking_to_engine(engine_class):
    """
    Add max profit tracking to the backtest engine.
    """
    original_run = engine_class.run
    
    def modified_run(self):
        """Execute backtest with max profit tracking."""
        equity = self.config.initial_capital
        expiry_date = None
        trade_max_dd = 0.0
        trade_peak_pnl_per_unit = 0.0  # NEW: Track max profit per unit
        
        for idx, row in self.data.iterrows():
            current_date = idx.date() if hasattr(idx, "date") else idx
            spot = row.get("nifty_close", 0)
            vix = row.get("vix", 15)

            if pd.isna(spot) or spot == 0 or pd.isna(vix):
                continue

            market_data = row.to_dict()
            daily_trade_pnl = 0.0

            if self.open_trade is not None:
                dte = self._calculate_dte(current_date, expiry_date) if expiry_date else 0

                if hasattr(self.strategy, "update_premiums"):
                    self.strategy.update_premiums(
                        self.open_trade, spot, vix, dte, self.config.risk_free_rate
                    )

                # NEW: Track max profit per unit
                if self.open_trade.pnl_per_unit > trade_peak_pnl_per_unit:
                    trade_peak_pnl_per_unit = self.open_trade.pnl_per_unit

                # Pass max profit to should_exit if strategy supports it
                try:
                    action, reason = self.strategy.should_exit(
                        self.open_trade, spot, vix, dte, 
                        max_profit_per_unit=trade_peak_pnl_per_unit
                    )
                except TypeError:
                    # Fallback if strategy doesn't support max_profit_per_unit param
                    action, reason = self.strategy.should_exit(
                        self.open_trade, spot, vix, dte
                    )

                if action.name == "EXIT" or dte <= 0:
                    # Record trade and reset
                    pnl = self.open_trade.total_pnl
                    
                    from backtester.engine import TradeResult
                    result = TradeResult(
                        signal_date=self.open_trade.entry_date,
                        entry_date=self.open_trade.entry_date,
                        exit_date=current_date,
                        strategy=self.open_trade.strategy_name,
                        entry_spot=self.open_trade.entry_spot,
                        exit_spot=spot,
                        entry_vix=self.open_trade.entry_vix,
                        exit_vix=vix,
                        net_credit=self.open_trade.net_credit,
                        pnl_per_unit=self.open_trade.pnl_per_unit,
                        total_pnl=pnl,
                        pnl_pct=(pnl / abs(self.open_trade.net_credit * self.open_trade.lots * self.open_trade.lot_size) * 100) if self.open_trade.net_credit != 0 else 0,
                        exit_reason=reason.value if reason else "expiry",
                        holding_days=(current_date - self.open_trade.entry_date).days,
                        legs_detail=f"{len(self.open_trade.legs)} legs",
                        max_drawdown_during=trade_max_dd,
                    )
                    self.completed_trades.append(result)
                    daily_trade_pnl = pnl
                    self.open_trade = None
                    trade_max_dd = 0.0
                    trade_peak_pnl_per_unit = 0.0  # Reset for next trade
                else:
                    daily_trade_pnl = self.open_trade.total_pnl
                    if self.open_trade.total_pnl < trade_max_dd:
                        trade_max_dd = self.open_trade.total_pnl

            elif self.open_trade is None:
                action = self.strategy.should_enter(spot, vix, market_data)
                if action.name == "ENTER":
                    expiry_date = self._get_expiry_date(current_date)
                    dte = self._calculate_dte(current_date, expiry_date)
                    
                    if self.config.min_dte_entry <= dte <= self.config.max_dte_entry:
                        trade = self.strategy.create_trade(
                            current_date, spot, vix, dte, self.config.risk_free_rate
                        )
                        self.open_trade = trade
                        trade_max_dd = 0.0
                        trade_peak_pnl_per_unit = 0.0  # Initialize for new trade

            realized = sum(t.total_pnl for t in self.completed_trades)
            equity = self.config.initial_capital + realized
            if self.open_trade:
                equity += self.open_trade.total_pnl

            self.equity_curve.append(equity)
            self.daily_pnl.append(daily_trade_pnl)
            
            if equity > self.peak_equity:
                self.peak_equity = equity

        # Close any open trade at end
        if self.open_trade:
            last_row = self.data.iloc[-1]
            from backtester.engine import TradeResult
            result = TradeResult(
                signal_date=self.open_trade.entry_date,
                entry_date=self.open_trade.entry_date,
                exit_date=self.data.index[-1].date() if hasattr(self.data.index[-1], "date") else self.data.index[-1],
                strategy=self.open_trade.strategy_name,
                entry_spot=self.open_trade.entry_spot,
                exit_spot=last_row.get("nifty_close", 0),
                entry_vix=self.open_trade.entry_vix,
                exit_vix=last_row.get("vix", 15),
                net_credit=self.open_trade.net_credit,
                pnl_per_unit=self.open_trade.pnl_per_unit,
                total_pnl=self.open_trade.total_pnl,
                pnl_pct=0,
                exit_reason="expiry",
                holding_days=0,
                legs_detail=f"{len(self.open_trade.legs)} legs",
                max_drawdown_during=trade_max_dd,
            )
            self.completed_trades.append(result)

        return self._build_result()
    
    engine_class.run = modified_run
    return engine_class


def print_comparison(original: BacktestResult, modified: BacktestResult, strategy_name: str) -> None:
    """Print side-by-side comparison."""
    print(f"\n\n{'=' * 90}")
    print(f"  {strategy_name} COMPARISON: Original vs 80% Max Profit Booking")
    print(f"{'=' * 90}")
    print(f"  {'Metric':<30s} {'Original':>15s} {'80% Max Profit':>15s} {'Difference':>15s}")
    print(f"  {'-' * 75}")
    
    def fmt_diff(orig, mod, is_pct=False, inverse=False):
        """Format difference with indicator."""
        diff = mod - orig
        if is_pct:
            diff_str = f"{diff:+.2f}pp"
        else:
            diff_str = f"{diff:+,.0f}" if abs(diff) > 100 else f"{diff:+.2f}"
        
        if inverse:
            indicator = "+" if diff < 0 else ("-" if diff > 0 else "=")
        else:
            indicator = "+" if diff > 0 else ("-" if diff < 0 else "=")
        
        return f"{indicator} {diff_str}"
    
    rows = [
        ("Total Trades", f"{original.total_trades}", f"{modified.total_trades}", 
         fmt_diff(original.total_trades, modified.total_trades)),
        
        ("Total P&L", f"Rs.{original.total_pnl:,.0f}", f"Rs.{modified.total_pnl:,.0f}",
         fmt_diff(original.total_pnl, modified.total_pnl)),
        
        ("CAGR", f"{original.cagr_pct:.2f}%", f"{modified.cagr_pct:.2f}%",
         fmt_diff(original.cagr_pct, modified.cagr_pct, is_pct=True)),
        
        ("Max Drawdown", f"{original.max_drawdown_pct:.1f}%", f"{modified.max_drawdown_pct:.1f}%",
         fmt_diff(original.max_drawdown_pct, modified.max_drawdown_pct, is_pct=True, inverse=True)),
        
        ("Sharpe Ratio", f"{original.sharpe_ratio:.2f}", f"{modified.sharpe_ratio:.2f}",
         fmt_diff(original.sharpe_ratio, modified.sharpe_ratio)),
        
        ("Sortino Ratio", f"{original.sortino_ratio:.2f}", f"{modified.sortino_ratio:.2f}",
         fmt_diff(original.sortino_ratio, modified.sortino_ratio)),
        
        ("Win Rate", f"{original.win_rate:.1f}%", f"{modified.win_rate:.1f}%",
         fmt_diff(original.win_rate, modified.win_rate, is_pct=True)),
        
        ("Profit Factor", f"{original.profit_factor:.2f}", f"{modified.profit_factor:.2f}",
         fmt_diff(original.profit_factor, modified.profit_factor)),
        
        ("Avg P&L/Trade", f"Rs.{original.avg_pnl_per_trade:,.0f}", f"Rs.{modified.avg_pnl_per_trade:,.0f}",
         fmt_diff(original.avg_pnl_per_trade, modified.avg_pnl_per_trade)),
        
        ("Avg Hold (days)", f"{original.avg_holding_days:.1f}", f"{modified.avg_holding_days:.1f}",
         fmt_diff(original.avg_holding_days, modified.avg_holding_days, inverse=True)),
    ]
    
    for metric, orig, mod, diff in rows:
        print(f"  {metric:<30s} {orig:>15s} {mod:>15s} {diff:>15s}")
    
    print(f"{'=' * 90}")


def main():
    parser = argparse.ArgumentParser(description="Compare Monthly Strategy Exit Logic")
    parser.add_argument("--start", type=str, default="2009-01-01", help="Start date")
    parser.add_argument("--end", type=str, default=str(date.today()), help="End date")
    parser.add_argument("--capital", type=float, default=500_000.0, help="Initial capital")
    parser.add_argument("--strategy", type=str, default="both", choices=["pcs", "ic", "both"], 
                       help="Strategy to test")
    args = parser.parse_args()

    config = BacktestConfig(
        start_date=date.fromisoformat(args.start),
        end_date=date.fromisoformat(args.end),
        initial_capital=args.capital,
    )

    print("\n" + "=" * 90)
    print("  MONTHLY OPTIONS EXIT STRATEGY COMPARISON")
    print("  Testing: 80% Max Profit Booking on Monthly Trades (15-45 DTE)")
    print(f"  Period: {config.start_date} to {config.end_date}")
    print("=" * 90)

    print("\n[1/2] Fetching market data...")
    fetcher = MarketDataFetcher(config.start_date, config.end_date)
    data = fetcher.build_combined_dataset()
    print(f"  Loaded {len(data)} trading days")

    strategies_to_test = []
    if args.strategy in ["pcs", "both"]:
        strategies_to_test.append(("Put Credit Spread", PutCreditSpreadStrategy(lots=config.max_lots, lot_size=config.lot_size)))
    if args.strategy in ["ic", "both"]:
        strategies_to_test.append(("Iron Condor", IronCondorStrategy(lots=config.max_lots, lot_size=config.lot_size)))

    for strategy_name, strategy in strategies_to_test:
        print(f"\n{'=' * 90}")
        print(f"  TESTING: {strategy_name}")
        print(f"{'=' * 90}")

        print(f"\n[2/2] Running backtests...")
        
        # Original backtest
        print(f"  Running ORIGINAL {strategy_name}...")
        engine_original = BacktestEngine(strategy, data.copy(), config, target_dte=21)
        result_original = engine_original.run()
        print(f"    Completed: {result_original.total_trades} trades | "
              f"P&L Rs.{result_original.total_pnl:,.0f} | CAGR {result_original.cagr_pct:.2f}%")

        # Modified backtest with 80% max profit booking
        print(f"  Running MODIFIED {strategy_name} (80% max profit booking)...")
        strategy_modified_class = add_max_profit_tracking_to_strategy(type(strategy))
        strategy_modified = strategy_modified_class(lots=config.max_lots, lot_size=config.lot_size)
        engine_modified_class = add_max_profit_tracking_to_engine(BacktestEngine)
        engine_modified = engine_modified_class(strategy_modified, data.copy(), config, target_dte=21)
        result_modified = engine_modified.run()
        print(f"    Completed: {result_modified.total_trades} trades | "
              f"P&L Rs.{result_modified.total_pnl:,.0f} | CAGR {result_modified.cagr_pct:.2f}%")

        print_comparison(result_original, result_modified, strategy_name)


if __name__ == "__main__":
    main()
