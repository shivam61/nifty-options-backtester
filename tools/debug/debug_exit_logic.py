#!/usr/bin/env python3
"""
Debug: Why is 85% rule not making any difference?

Let's track:
1. How many times does 85% rule get evaluated?
2. How many times does it trigger vs ML triggering first?
3. What are the exit reason distributions?
"""

import os
import sys
import random
from datetime import date

os.environ["PYTHONHASHSEED"] = "42"
random.seed(42)

import numpy as np
np.random.seed(42)

from config import BacktestConfig
from data.market_data import MarketDataFetcher
from backtester.engine import SmartBacktestEngine
from strategies.multi_strategy import PutCreditSpreadStrategy
from strategies.base import ExitReason


def analyze_exit_logic():
    """Track which exit logic triggers in practice."""
    
    print("\n" + "=" * 80)
    print("  EXIT LOGIC DEBUG ANALYSIS")
    print("  Tracking: Which exit logic actually triggers?")
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
    
    print("\n[2/2] Running instrumented backtest...")
    
    # Create strategy with 85% enabled
    strategy = PutCreditSpreadStrategy(
        lots=config.max_lots,
        lot_size=config.lot_size,
        enable_max_profit_booking=True,
        max_profit_threshold=0.85,
    )
    
    engine = SmartBacktestEngine(strategy, data.copy(), config, target_dte=21)
    
    # Track exits
    exit_tracking = {
        'ml_exits': 0,
        'strategy_85_exits': 0,
        'strategy_other_exits': 0,
        'total_checks': 0,
        'ml_said_hold_count': 0,
        'trades_with_85_trigger': [],
    }
    
    # Instrument _smart_exit_check
    original_smart_exit = engine._smart_exit_check
    
    def instrumented_smart_exit(row, spot, vix, dte, entry_spot, entry_vix):
        exit_tracking['total_checks'] += 1
        should_exit, reason = original_smart_exit(row, spot, vix, dte, entry_spot, entry_vix)
        if should_exit:
            exit_tracking['ml_exits'] += 1
        else:
            exit_tracking['ml_said_hold_count'] += 1
        return should_exit, reason
    
    engine._smart_exit_check = instrumented_smart_exit
    
    # Instrument strategy.should_exit
    original_strategy_exit = strategy.should_exit
    
    def instrumented_strategy_exit(trade, spot, vix, dte_remaining):
        from strategies.base import TradeAction
        
        # Check if 85% rule would trigger
        pnl_unit = trade.pnl_per_unit
        credit = trade.net_credit
        
        if hasattr(trade, '_max_profit_per_unit'):
            max_profit = trade._max_profit_per_unit
            if max_profit > 0 and pnl_unit > 0:
                if pnl_unit <= max_profit * 0.85:
                    # 85% rule is about to trigger!
                    exit_tracking['trades_with_85_trigger'].append({
                        'date': trade.entry_date,
                        'max_profit': max_profit,
                        'current_profit': pnl_unit,
                        'pct_of_max': (pnl_unit / max_profit * 100) if max_profit > 0 else 0,
                        'credit': credit,
                    })
        
        action, reason = original_strategy_exit(trade, spot, vix, dte_remaining)
        
        if action == TradeAction.EXIT:
            if reason == ExitReason.PROFIT_TARGET and hasattr(trade, '_max_profit_per_unit'):
                # This might be 85% rule
                exit_tracking['strategy_85_exits'] += 1
            else:
                exit_tracking['strategy_other_exits'] += 1
        
        return action, reason
    
    strategy.should_exit = instrumented_strategy_exit
    
    # Run backtest
    result = engine.run()
    
    # Print analysis
    print("\n" + "=" * 80)
    print("  EXIT LOGIC FLOW ANALYSIS")
    print("=" * 80)
    
    print(f"\n  Total Trades: {result.total_trades}")
    print(f"  Total Exit Checks: {exit_tracking['total_checks']:,}")
    print(f"  Avg Checks per Trade: {exit_tracking['total_checks'] / max(result.total_trades, 1):.1f}")
    
    print(f"\n  EXIT DECISION FLOW:")
    print(f"  ─────────────────────")
    print(f"  ML said 'EXIT':       {exit_tracking['ml_exits']:>6} checks  (ML exits first)")
    print(f"  ML said 'HOLD':       {exit_tracking['ml_said_hold_count']:>6} checks  (Strategy gets a chance)")
    
    print(f"\n  WHEN STRATEGY GETS TO DECIDE:")
    print(f"  ─────────────────────────────")
    print(f"  85% rule triggered:   {exit_tracking['strategy_85_exits']:>6} times")
    print(f"  Other rules triggered:{exit_tracking['strategy_other_exits']:>6} times")
    
    print(f"\n  OVERALL EXIT ATTRIBUTION:")
    print(f"  ─────────────────────────────")
    total_exits = result.total_trades
    ml_pct = (exit_tracking['ml_exits'] / max(total_exits, 1) * 100)
    strat_85_pct = (exit_tracking['strategy_85_exits'] / max(total_exits, 1) * 100)
    strat_other_pct = (exit_tracking['strategy_other_exits'] / max(total_exits, 1) * 100)
    
    print(f"  ML exits:             {exit_tracking['ml_exits']:>6} / {total_exits} ({ml_pct:.1f}%)")
    print(f"  Strategy 85% exits:   {exit_tracking['strategy_85_exits']:>6} / {total_exits} ({strat_85_pct:.1f}%)")
    print(f"  Strategy other exits: {exit_tracking['strategy_other_exits']:>6} / {total_exits} ({strat_other_pct:.1f}%)")
    
    # Analyze trades where 85% triggered
    if exit_tracking['trades_with_85_trigger']:
        print(f"\n  TRADES WHERE 85% RULE TRIGGERED:")
        print(f"  ─────────────────────────────────")
        print(f"  Total: {len(exit_tracking['trades_with_85_trigger'])} times")
        print(f"\n  Sample trades:")
        for i, trade_info in enumerate(exit_tracking['trades_with_85_trigger'][:5], 1):
            print(f"    {i}. Date: {trade_info['date']}")
            print(f"       Max Profit: Rs.{trade_info['max_profit']:.2f} | Current: Rs.{trade_info['current_profit']:.2f}")
            print(f"       Current = {trade_info['pct_of_max']:.1f}% of max (< 85% threshold)")
            print(f"       Credit: Rs.{trade_info['credit']:.2f}")
    else:
        print(f"\n  ⚠ 85% RULE NEVER TRIGGERED!")
        print(f"  Possible reasons:")
        print(f"    1. ML exits trades before profit drops to 85% of max")
        print(f"    2. Trades are exiting on other criteria first")
        print(f"    3. Not enough profitable trades to build up max profit")
    
    # Exit reason distribution
    print(f"\n  EXIT REASON DISTRIBUTION:")
    print(f"  ─────────────────────────")
    reason_counts = {}
    for trade in result.trades:
        reason = trade.exit_reason
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
    
    for reason, count in sorted(reason_counts.items(), key=lambda x: x[1], reverse=True):
        pct = (count / max(len(result.trades), 1) * 100)
        print(f"    {reason:<20} {count:>3} ({pct:>5.1f}%)")
    
    print(f"\n  BACKTEST RESULTS:")
    print(f"  ─────────────────")
    print(f"  Total P&L:    Rs.{result.total_pnl:>12,.0f}")
    print(f"  CAGR:         {result.cagr_pct:>11.2f}%")
    print(f"  Max DD:       {result.max_drawdown_pct:>11.1f}%")
    print(f"  Sharpe:       {result.sharpe_ratio:>11.2f}")
    print(f"  Win Rate:     {result.win_rate:>11.1f}%")
    print(f"  Avg Hold:     {result.avg_holding_days:>11.1f} days")
    
    print("\n" + "=" * 80)
    print("  CONCLUSION")
    print("=" * 80)
    
    if exit_tracking['strategy_85_exits'] == 0:
        print("\n  ✗ The 85% rule is NEVER triggering!")
        print("\n  Root Cause:")
        print("    - ML's VIX-adaptive exits (30-60% targets) fire first")
        print("    - ML exits trades before profit has a chance to drop to 85%")
        print("    - The 85% rule only works if profit BUILDS UP then DROPS")
        print("\n  Implication:")
        print("    - Moving 85% to the top won't help (nothing to protect yet)")
        print("    - The 85% rule is only useful for trades that:")
        print("      1. Build significant profit (>85% of credit)")
        print("      2. THEN start losing that profit")
        print("      3. Don't hit ML's profit targets first (30-60%)")
    else:
        print(f"\n  ✓ The 85% rule IS triggering ({exit_tracking['strategy_85_exits']} times)")
        print(f"  {strat_85_pct:.1f}% of trades exit via 85% rule")
        if strat_85_pct > 10:
            print("\n  Recommendation: 85% rule is working as intended.")
        else:
            print("\n  Recommendation: 85% rule has minimal impact.")
    
    print("=" * 80 + "\n")


if __name__ == "__main__":
    print("\nStarting exit logic debug analysis...")
    analyze_exit_logic()
