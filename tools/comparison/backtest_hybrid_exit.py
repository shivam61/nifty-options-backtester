#!/usr/bin/env python3
"""
Backtest Hybrid Exit Strategy vs Fixed vs Original

Compares three approaches:
1. ORIGINAL: 50% profit target only (current)
2. FIXED_85: Hard-coded 85% max profit booking
3. HYBRID: 75% circuit breaker + ML-driven adaptive threshold

The hybrid approach simulates ML by using regime-based thresholds:
- Low VIX (< 15): Use 88% threshold (more room to run)
- Medium VIX (15-20): Use 85% threshold (balanced)
- High VIX (> 20): Use 82% threshold (protect faster)
"""

import argparse
import os
import sys
import random
from datetime import date
from typing import Dict, Tuple

os.environ["PYTHONHASHSEED"] = "42"
random.seed(42)

import numpy as np
import pandas as pd

np.random.seed(42)

from config import BacktestConfig
from data.market_data import MarketDataFetcher
from backtester.engine import BacktestEngine
from strategies.multi_strategy import PutCreditSpreadStrategy, IronCondorStrategy
from strategies.base import TradeAction, ExitReason


class ExitStrategy:
    """Base class for different exit approaches."""
    
    def should_exit(self, trade, spot, vix, dte, max_profit_per_unit):
        raise NotImplementedError


class OriginalExitStrategy(ExitStrategy):
    """Current approach: 50% profit target only."""
    
    def should_exit(self, trade, spot, vix, dte, max_profit_per_unit):
        # Just return False - let strategy's original logic handle it
        return False, None


class Fixed85ExitStrategy(ExitStrategy):
    """Fixed 85% max profit booking."""
    
    def should_exit(self, trade, spot, vix, dte, max_profit_per_unit):
        pnl_unit = trade.pnl_per_unit
        
        if max_profit_per_unit > 0 and pnl_unit > 0:
            if pnl_unit <= max_profit_per_unit * 0.85:
                return True, "85% max profit booking"
        
        return False, None


class HybridExitStrategy(ExitStrategy):
    """
    Hybrid approach:
    1. Circuit breaker at 75% (hard stop)
    2. ML-simulated adaptive threshold based on regime
    """
    
    def should_exit(self, trade, spot, vix, dte, max_profit_per_unit):
        pnl_unit = trade.pnl_per_unit
        
        if max_profit_per_unit <= 0 or pnl_unit <= 0:
            return False, None
        
        pct_of_max = pnl_unit / max_profit_per_unit
        
        # LAYER 1: Circuit breaker (hard stop at 75%)
        if pct_of_max <= 0.75:
            return True, "Circuit breaker 75%"
        
        # LAYER 2: ML-simulated adaptive threshold
        # In real ML, this would be: ml_model.predict_optimal_threshold(features)
        # For backtest, we simulate intelligent threshold selection based on regime
        
        optimal_threshold = self._get_ml_threshold(vix, dte, trade, spot)
        
        if pct_of_max <= optimal_threshold:
            return True, f"ML adaptive exit ({optimal_threshold:.0%})"
        
        return False, None
    
    def _get_ml_threshold(self, vix, dte, trade, spot):
        """
        Simulate ML model's threshold selection.
        
        In production, this would be:
            features = extract_features(vix, dte, greeks, profit_trajectory, ...)
            threshold = ml_model.predict(features)
        
        For backtest, we use rule-based logic that simulates what ML might learn:
        - Low VIX → Higher threshold (let it run)
        - High VIX → Lower threshold (protect faster)
        - Early DTE → Higher threshold (more time)
        - Late DTE → Lower threshold (less time to recover)
        """
        
        # Base threshold
        threshold = 0.85
        
        # Adjust for VIX regime
        if vix < 15:
            # Low VIX: calm market, let profit run more
            threshold = 0.88
        elif vix > 20:
            # High VIX: volatile, protect faster
            threshold = 0.82
        
        # Adjust for DTE
        if dte < 7:
            # Close to expiry: less time to recover, tighten
            threshold -= 0.02
        elif dte > 30:
            # Far from expiry: more time, loosen
            threshold += 0.02
        
        # Adjust for how fast we reached max profit
        if hasattr(trade, '_days_to_max_profit'):
            if trade._days_to_max_profit < 3:
                # Reached max very fast: likely to reverse, tighten
                threshold -= 0.02
        
        # Bound threshold between 80% and 90%
        threshold = max(0.80, min(0.90, threshold))
        
        return threshold


def test_exit_approach(data: pd.DataFrame, config: BacktestConfig,
                       strategy_class, exit_strategy: ExitStrategy,
                       approach_name: str):
    """Test a single exit approach."""
    
    strategy = strategy_class(lots=config.max_lots, lot_size=config.lot_size)
    
    # Wrap strategy's should_exit with our exit approach
    original_should_exit = strategy.should_exit
    
    def custom_should_exit(trade, spot, vix, dte_remaining):
        # Track max profit
        if not hasattr(trade, '_max_profit_per_unit'):
            trade._max_profit_per_unit = 0.0
            trade._days_to_max_profit = 0
        
        if trade.pnl_per_unit > trade._max_profit_per_unit:
            trade._max_profit_per_unit = trade.pnl_per_unit
            trade._days_to_max_profit = trade.holding_days if hasattr(trade, 'holding_days') else 0
        
        # Check exit strategy
        should_exit, reason = exit_strategy.should_exit(
            trade, spot, vix, dte_remaining, trade._max_profit_per_unit
        )
        
        if should_exit:
            return TradeAction.EXIT, ExitReason.PROFIT_TARGET
        
        # Fall back to original logic
        return original_should_exit(trade, spot, vix, dte_remaining)
    
    strategy.should_exit = custom_should_exit
    
    engine = BacktestEngine(strategy, data.copy(), config, target_dte=21)
    result = engine.run()
    
    return result


def print_comparison_table(results: Dict):
    """Print comprehensive comparison table."""
    print(f"\n{'=' * 140}")
    print(f"  EXIT STRATEGY COMPARISON")
    print(f"{'=' * 140}")
    
    headers = ['Approach', 'Trades', 'Total P&L', 'CAGR %', 'Max DD %', 'Sharpe', 'Sortino', 'Win %', 'Profit Factor', 'Avg Hold']
    col_widths = [20, 8, 15, 8, 9, 7, 8, 7, 13, 9]
    
    header_line = "  "
    for h, w in zip(headers, col_widths):
        header_line += f"{h:>{w}} "
    print(header_line)
    print(f"  {'-' * 138}")
    
    # Sort by CAGR descending
    sorted_results = sorted(results.items(), key=lambda x: x[1]['cagr_pct'], reverse=True)
    
    best_cagr = max(r['cagr_pct'] for r in results.values())
    best_sharpe = max(r['sharpe'] for r in results.values())
    best_dd = min(r['max_dd_pct'] for r in results.values())
    
    for approach, data in sorted_results:
        marker = ""
        if data['cagr_pct'] == best_cagr:
            marker = "← Best CAGR"
        elif data['sharpe'] == best_sharpe:
            marker = "← Best Sharpe"
        elif data['max_dd_pct'] == best_dd:
            marker = "← Best DD"
        
        line = f"  {approach:<20} {data['total_trades']:>8} "
        line += f"Rs.{data['total_pnl']:>12,.0f} {data['cagr_pct']:>7.2f} "
        line += f"{data['max_dd_pct']:>8.1f} {data['sharpe']:>7.2f} "
        line += f"{data['sortino']:>7.2f} {data['win_rate']:>6.1f} "
        line += f"{data['profit_factor']:>12.2f} {data['avg_hold']:>9.1f} {marker}"
        print(line)
    
    print(f"{'=' * 140}")


def analyze_improvements(original_result, fixed_result, hybrid_result):
    """Analyze improvements of each approach vs original."""
    print(f"\n{'=' * 140}")
    print(f"  IMPROVEMENT ANALYSIS (vs Original)")
    print(f"{'=' * 140}")
    
    def calc_improvement(new_val, orig_val, inverse=False):
        diff = new_val - orig_val
        pct = (diff / abs(orig_val) * 100) if orig_val != 0 else 0
        
        if inverse:  # For drawdown, lower is better
            indicator = "✓" if diff < 0 else "✗"
        else:
            indicator = "✓" if diff > 0 else "✗"
        
        return diff, pct, indicator
    
    approaches = [
        ("Fixed 85%", fixed_result),
        ("Hybrid", hybrid_result),
    ]
    
    metrics = [
        ('Total P&L', 'total_pnl', False, 'Rs.'),
        ('CAGR %', 'cagr_pct', False, 'pp'),
        ('Max DD %', 'max_dd_pct', True, 'pp'),
        ('Sharpe', 'sharpe', False, ''),
        ('Sortino', 'sortino', False, ''),
        ('Win Rate %', 'win_rate', False, 'pp'),
    ]
    
    for approach_name, result in approaches:
        print(f"\n  {approach_name}:")
        for metric_name, key, inverse, unit in metrics:
            diff, pct, indicator = calc_improvement(
                result[key], original_result[key], inverse
            )
            
            if unit == 'Rs.':
                print(f"    {indicator} {metric_name:<15}: {diff:+,.0f} Rs. ({pct:+.1f}%)")
            elif unit == 'pp':
                print(f"    {indicator} {metric_name:<15}: {diff:+.2f}pp")
            else:
                print(f"    {indicator} {metric_name:<15}: {diff:+.2f} ({pct:+.1f}%)")
    
    print(f"\n{'=' * 140}")


def determine_winner(results: Dict):
    """Determine which approach wins on different objectives."""
    print(f"\n{'=' * 140}")
    print(f"  WINNER BY OBJECTIVE")
    print(f"{'=' * 140}")
    
    objectives = [
        ('Maximum Profit (CAGR)', 'cagr_pct', False),
        ('Best Risk-Adjusted (Sharpe)', 'sharpe', False),
        ('Lowest Drawdown', 'max_dd_pct', True),
        ('Best Win Rate', 'win_rate', False),
        ('Best Profit Factor', 'profit_factor', False),
        ('Shortest Hold Time', 'avg_hold', True),
    ]
    
    for objective_name, key, inverse in objectives:
        if inverse:
            winner = min(results.items(), key=lambda x: x[1][key])
        else:
            winner = max(results.items(), key=lambda x: x[1][key])
        
        print(f"  {objective_name:<35}: {winner[0]:<20} ({winner[1][key]:.2f})")
    
    # Overall score (weighted)
    print(f"\n  Overall Score (Sharpe * (1 - DD%/100)):")
    for approach, data in sorted(results.items(), 
                                 key=lambda x: x[1]['sharpe'] * (1 - x[1]['max_dd_pct']/100),
                                 reverse=True):
        score = data['sharpe'] * (1 - data['max_dd_pct']/100)
        print(f"    {approach:<20}: {score:.3f}")
    
    print(f"{'=' * 140}")


def main():
    parser = argparse.ArgumentParser(description="Backtest Hybrid Exit Strategy")
    parser.add_argument("--start", type=str, default="2020-01-01", help="Start date")
    parser.add_argument("--end", type=str, default=str(date.today()), help="End date")
    parser.add_argument("--capital", type=float, default=500_000.0, help="Initial capital")
    parser.add_argument("--strategy", type=str, choices=["pcs", "ic", "both"], default="both")
    args = parser.parse_args()

    print("\n" + "=" * 140)
    print("  HYBRID EXIT STRATEGY BACKTEST")
    print("  Comparing: ORIGINAL vs FIXED_85% vs HYBRID (75% circuit breaker + ML-adaptive)")
    print(f"  Period: {args.start} to {args.end}")
    print("=" * 140)

    print("\n[1/2] Fetching market data...")
    start_date = date.fromisoformat(args.start)
    end_date = date.fromisoformat(args.end)
    fetcher = MarketDataFetcher(start_date, end_date)
    data = fetcher.build_combined_dataset()
    print(f"  Loaded {len(data)} trading days")

    config = BacktestConfig(
        start_date=start_date,
        end_date=end_date,
        initial_capital=args.capital,
    )

    strategies_to_test = []
    if args.strategy in ["pcs", "both"]:
        strategies_to_test.append(("Put Credit Spread", PutCreditSpreadStrategy))
    if args.strategy in ["ic", "both"]:
        strategies_to_test.append(("Iron Condor", IronCondorStrategy))

    for strategy_name, strategy_class in strategies_to_test:
        print(f"\n{'=' * 140}")
        print(f"  TESTING: {strategy_name}")
        print(f"{'=' * 140}")

        print(f"\n[2/2] Running backtests...")
        
        exit_strategies = [
            ("Original (50% only)", OriginalExitStrategy()),
            ("Fixed 85%", Fixed85ExitStrategy()),
            ("Hybrid (75% CB + ML)", HybridExitStrategy()),
        ]
        
        results = {}
        
        for approach_name, exit_strategy in exit_strategies:
            print(f"  Testing {approach_name}...", end=" ", flush=True)
            result = test_exit_approach(data, config, strategy_class, exit_strategy, approach_name)
            
            results[approach_name] = {
                'total_trades': result.total_trades,
                'total_pnl': result.total_pnl,
                'cagr_pct': result.cagr_pct,
                'max_dd_pct': result.max_drawdown_pct,
                'sharpe': result.sharpe_ratio,
                'sortino': result.sortino_ratio,
                'win_rate': result.win_rate,
                'profit_factor': result.profit_factor,
                'avg_hold': result.avg_holding_days,
            }
            print(f"✓ (P&L: Rs.{result.total_pnl:,.0f}, CAGR: {result.cagr_pct:.2f}%)")
        
        print_comparison_table(results)
        analyze_improvements(
            results["Original (50% only)"],
            results["Fixed 85%"],
            results["Hybrid (75% CB + ML)"]
        )
        determine_winner(results)


if __name__ == "__main__":
    main()
