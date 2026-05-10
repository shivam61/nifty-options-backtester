#!/usr/bin/env python3
"""
Compare Exit Logic Priority: Current (ML first → 85%) vs Proposed (85% first → ML)

Current Setup:
  1. _smart_exit_check() (VIX-adaptive + ML)
  2. strategy.should_exit() (85% rule)

Proposed Setup:
  1. 85% max profit booking (FIRST)
  2. _smart_exit_check() (VIX-adaptive + ML)
  3. strategy.should_exit() (remaining rules)

Test both approaches and see which produces better risk-adjusted returns.
"""

import os
import sys
import random
from datetime import date
from copy import deepcopy

os.environ["PYTHONHASHSEED"] = "42"
random.seed(42)

import numpy as np
np.random.seed(42)

from config import BacktestConfig
from data.market_data import MarketDataFetcher
from backtester.engine import SmartBacktestEngine
from strategies.multi_strategy import PutCreditSpreadStrategy, IronCondorStrategy
from strategies.base import TradeAction, ExitReason


def run_backtest_current_priority(config, data, strategy_class, strategy_name):
    """
    Current priority: ML first, then 85% rule.
    This is what's already in the code - no modification needed.
    """
    print(f"\n  Running {strategy_name} with CURRENT priority (ML → 85%)...")
    
    strategy = strategy_class(
        lots=config.max_lots,
        lot_size=config.lot_size,
        enable_max_profit_booking=True,  # 85% rule in strategy
        max_profit_threshold=0.85,
    )
    
    engine = SmartBacktestEngine(strategy, data.copy(), config, target_dte=21)
    result = engine.run()
    
    return result


def run_backtest_proposed_priority(config, data, strategy_class, strategy_name):
    """
    Proposed priority: 85% rule first, then ML.
    
    To implement this, we'll:
    1. Disable 85% in strategy (to avoid duplication)
    2. Monkey-patch _smart_exit_check to add 85% check at the top
    """
    print(f"\n  Running {strategy_name} with PROPOSED priority (85% → ML)...")
    
    # Disable 85% in strategy since it'll be in _smart_exit_check
    strategy = strategy_class(
        lots=config.max_lots,
        lot_size=config.lot_size,
        enable_max_profit_booking=False,  # Disabled in strategy
        max_profit_threshold=0.85,
    )
    
    engine = SmartBacktestEngine(strategy, data.copy(), config, target_dte=21)
    
    # Monkey-patch _smart_exit_check to add 85% rule at the top
    original_smart_exit = engine._smart_exit_check
    
    def smart_exit_with_85_first(row, spot, vix, dte, entry_spot, entry_vix):
        trade = engine.open_trade
        if trade is None:
            return False, None
        
        net_credit = trade.net_credit
        if net_credit <= 0:
            return original_smart_exit(row, spot, vix, dte, entry_spot, entry_vix)
        
        pnl_per_unit = trade.pnl_per_unit
        pnl_pct = (pnl_per_unit / net_credit * 100)
        
        # === 85% MAX PROFIT BOOKING (PRIORITY #1) ===
        if not hasattr(trade, '_max_profit_pct_engine'):
            trade._max_profit_pct_engine = 0.0
        
        if pnl_pct > trade._max_profit_pct_engine:
            trade._max_profit_pct_engine = pnl_pct
        
        # Exit when profit drops to 85% of max seen
        if trade._max_profit_pct_engine > 0 and pnl_pct > 0:
            if pnl_pct <= trade._max_profit_pct_engine * 0.85:
                engine.ml_exit_count += 1  # Count it
                return True, ExitReason.PROFIT_TARGET
        
        # === THEN run original ML + VIX-adaptive logic ===
        return original_smart_exit(row, spot, vix, dte, entry_spot, entry_vix)
    
    engine._smart_exit_check = smart_exit_with_85_first
    
    result = engine.run()
    
    return result


def compare_strategies():
    """Compare both exit priority approaches for PCS and IC."""
    
    print("\n" + "=" * 80)
    print("  EXIT LOGIC PRIORITY COMPARISON")
    print("  Testing: Current (ML→85%) vs Proposed (85%→ML)")
    print("  Period: 2020-2026")
    print("=" * 80)
    
    config = BacktestConfig(
        start_date=date(2020, 1, 1),
        end_date=date(2026, 4, 16),
        initial_capital=500_000.0,
    )
    
    print("\n[1/2] Fetching market data...")
    fetcher = MarketDataFetcher(config.start_date, config.end_date)
    data = fetcher.build_combined_dataset()
    print(f"  Loaded {len(data)} trading days")
    
    strategies = [
        (PutCreditSpreadStrategy, "Put Credit Spread"),
        (IronCondorStrategy, "Iron Condor"),
    ]
    
    results = {}
    
    for strategy_class, strategy_name in strategies:
        print("\n" + "=" * 80)
        print(f"  TESTING: {strategy_name}")
        print("=" * 80)
        
        # Run current priority
        current_result = run_backtest_current_priority(
            config, data, strategy_class, strategy_name
        )
        
        # Run proposed priority
        proposed_result = run_backtest_proposed_priority(
            config, data, strategy_class, strategy_name
        )
        
        results[strategy_name] = {
            'current': current_result,
            'proposed': proposed_result,
        }
        
        # Print comparison
        print_comparison(strategy_name, current_result, proposed_result)
    
    # Print final summary
    print_final_summary(results)


def print_comparison(strategy_name, current, proposed):
    """Print detailed comparison table."""
    
    print(f"\n" + "=" * 80)
    print(f"  {strategy_name} COMPARISON: Current vs Proposed Priority")
    print("=" * 80)
    
    metrics = [
        ("Total Trades", "total_trades", ""),
        ("Total P&L", "total_pnl", "Rs."),
        ("CAGR", "cagr_pct", "%"),
        ("Max Drawdown", "max_drawdown_pct", "%"),
        ("Sharpe Ratio", "sharpe_ratio", ""),
        ("Sortino Ratio", "sortino_ratio", ""),
        ("Win Rate", "win_rate", "%"),
        ("Profit Factor", "profit_factor", ""),
        ("Avg P&L/Trade", "avg_pnl_per_trade", "Rs."),
        ("Avg Hold (days)", "avg_holding_days", ""),
    ]
    
    print(f"  {'Metric':<20} {'Current (ML→85%)':<20} {'Proposed (85%→ML)':<20} {'Difference':<15}")
    print(f"  {'-' * 75}")
    
    for metric_name, metric_key, prefix in metrics:
        current_val = getattr(current, metric_key)
        proposed_val = getattr(proposed, metric_key)
        diff = proposed_val - current_val
        
        if prefix == "Rs.":
            current_str = f"{prefix}{current_val:>12,.0f}"
            proposed_str = f"{prefix}{proposed_val:>12,.0f}"
            diff_str = f"{diff:>+12,.0f}"
        elif prefix == "%":
            current_str = f"{current_val:>14.2f}{prefix}"
            proposed_str = f"{proposed_val:>14.2f}{prefix}"
            diff_str = f"{diff:>+13.2f}pp"
        else:
            current_str = f"{current_val:>15.2f}"
            proposed_str = f"{proposed_val:>15.2f}"
            diff_str = f"{diff:>+15.2f}"
        
        # Add indicator
        if abs(diff) < 0.01 and prefix != "Rs.":
            indicator = "  ="
        elif diff > 0:
            indicator = "  +"
        else:
            indicator = "  -"
        
        print(f"  {metric_name:<20} {current_str:<20} {proposed_str:<20} {diff_str}{indicator}")
    
    print("=" * 80)


def print_final_summary(results):
    """Print final verdict."""
    
    print("\n" + "=" * 80)
    print("  FINAL ANALYSIS")
    print("=" * 80)
    
    for strategy_name, res in results.items():
        current = res['current']
        proposed = res['proposed']
        
        print(f"\n  {strategy_name}:")
        print(f"  {'-' * 40}")
        
        # Calculate composite scores
        current_score = (
            current.cagr_pct * 0.3 +
            (100 - current.max_drawdown_pct) * 0.3 +
            current.sharpe_ratio * 20 * 0.4
        )
        
        proposed_score = (
            proposed.cagr_pct * 0.3 +
            (100 - proposed.max_drawdown_pct) * 0.3 +
            proposed.sharpe_ratio * 20 * 0.4
        )
        
        print(f"  Current Priority (ML→85%):")
        print(f"    CAGR: {current.cagr_pct:.2f}% | DD: {current.max_drawdown_pct:.1f}% | Sharpe: {current.sharpe_ratio:.2f}")
        print(f"    Composite Score: {current_score:.2f}")
        
        print(f"\n  Proposed Priority (85%→ML):")
        print(f"    CAGR: {proposed.cagr_pct:.2f}% | DD: {proposed.max_drawdown_pct:.1f}% | Sharpe: {proposed.sharpe_ratio:.2f}")
        print(f"    Composite Score: {proposed_score:.2f}")
        
        # Verdict
        print(f"\n  Impact:")
        cagr_diff = proposed.cagr_pct - current.cagr_pct
        dd_diff = proposed.max_drawdown_pct - current.max_drawdown_pct
        sharpe_diff = proposed.sharpe_ratio - current.sharpe_ratio
        
        print(f"    CAGR:   {cagr_diff:>+6.2f}pp  {'↑ Better' if cagr_diff > 0 else '↓ Worse' if cagr_diff < 0 else '→ Same'}")
        print(f"    DD:     {dd_diff:>+6.2f}pp  {'↓ Better' if dd_diff < 0 else '↑ Worse' if dd_diff > 0 else '→ Same'}")
        print(f"    Sharpe: {sharpe_diff:>+6.2f}   {'↑ Better' if sharpe_diff > 0 else '↓ Worse' if sharpe_diff < 0 else '→ Same'}")
        
        if proposed_score > current_score * 1.02:
            verdict = "✓ PROPOSED PRIORITY WINS (85% first)"
            reason = "Significantly better risk-adjusted returns"
        elif proposed_score < current_score * 0.98:
            verdict = "✗ CURRENT PRIORITY WINS (ML first)"
            reason = "Better performance with ML taking precedence"
        else:
            verdict = "≈ NEGLIGIBLE DIFFERENCE"
            reason = "Both approaches produce similar results"
        
        print(f"\n  Verdict: {verdict}")
        print(f"  Reason:  {reason}")
    
    print("\n" + "=" * 80)
    print("  RECOMMENDATION")
    print("=" * 80)
    
    # Overall recommendation
    all_proposed_better = all(
        res['proposed'].sharpe_ratio > res['current'].sharpe_ratio
        for res in results.values()
    )
    
    if all_proposed_better:
        print("\n  ✓ RECOMMEND: Move 85% rule to TOP of exit logic (before ML)")
        print("\n  Benefits:")
        print("    - More consistent profit protection across all trades")
        print("    - Simpler logic (85% always evaluated first)")
        print("    - Better risk-adjusted returns")
        print("\n  Implementation: Add 85% check at top of _smart_exit_check()")
    else:
        print("\n  ✓ RECOMMEND: Keep CURRENT priority (ML first, then 85%)")
        print("\n  Benefits:")
        print("    - ML can identify danger signals before 85% rule")
        print("    - VIX-adaptive targets provide regime-specific exits")
        print("    - Better overall performance")
        print("\n  Implementation: No changes needed - current setup is optimal")
    
    print("=" * 80 + "\n")


if __name__ == "__main__":
    print("\nStarting exit logic priority comparison...")
    compare_strategies()
