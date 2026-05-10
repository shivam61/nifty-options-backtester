#!/usr/bin/env python3
"""
Compare legacy vs redesigned weekly exit logic.

Runs both versions of the weekly backtest side-by-side:
1. Before: legacy weekly exits
2. After: redesigned strategy-specific exits

Shows detailed comparison, including exit reason distribution.
"""

import argparse
import os
import sys
import random
from dataclasses import replace
from datetime import date
from pathlib import Path

os.environ["PYTHONHASHSEED"] = "42"
random.seed(42)

import numpy as np
import pandas as pd

np.random.seed(42)

from config import WeeklyBacktestConfig
from data.market_data import MarketDataFetcher
from backtester.weekly_engine import WeeklyBacktestEngine, WeeklyBacktestResult


def print_result(result: WeeklyBacktestResult, label: str) -> None:
    """Print formatted backtest results."""
    print(f"\n{'=' * 70}")
    print(f"  {label}")
    print(f"{'=' * 70}")
    print(f"  Total Trades:         {result.total_trades}")
    print(f"  Total P&L:            Rs.{result.total_pnl:,.0f}")
    print(f"  Total Return:         {result.total_return_pct:.2f}%")
    print(f"  CAGR:                 {result.cagr_pct:.2f}%")
    print(f"  Sharpe Ratio:         {result.sharpe_ratio:.2f}")
    print(f"  Sortino Ratio:        {result.sortino_ratio:.2f}")
    print(f"  Calmar Ratio:         {result.calmar_ratio:.2f}")
    print(f"  Max Drawdown:         {result.max_drawdown_pct:.1f}%")
    print(f"  Win Rate:             {result.win_rate:.1f}%")
    print(f"  Profit Factor:        {result.profit_factor:.2f}")
    print(f"  Avg P&L/Trade:        Rs.{result.avg_pnl_per_trade:,.0f}")
    print(f"  Avg Hold (days):      {result.avg_holding_days:.1f}")
    print(f"  Best Trade:           Rs.{result.best_trade_pnl:,.0f}")
    print(f"  Worst Trade:          Rs.{result.worst_trade_pnl:,.0f}")
    print(f"  Max Consec Wins:      {result.max_consecutive_wins}")
    print(f"  Max Consec Losses:    {result.max_consecutive_losses}")
    print(f"  Capital Utilization:  {result.capital_utilization_pct:.1f}%")

    if result.strategy_breakdown:
        print(f"\n  {'Strategy Breakdown':}")
        print(f"  {'Strategy':<30s} {'Trades':>7s} {'Win%':>7s} {'Total PnL':>12s}")
        print(f"  {'-' * 56}")
        for name, stats in sorted(result.strategy_breakdown.items(), key=lambda x: -x[1]["trades"]):
            wr = stats["wins"] / stats["trades"] * 100 if stats["trades"] > 0 else 0
            print(f"  {name:<30s} {stats['trades']:>7d} {wr:>6.1f}% Rs.{stats['total_pnl']:>10,.0f}")


def print_comparison(original: WeeklyBacktestResult, modified: WeeklyBacktestResult) -> None:
    """Print side-by-side comparison with difference analysis."""
    print(f"\n\n{'=' * 90}")
    print(f"  SIDE-BY-SIDE COMPARISON: Legacy vs Redesigned Weekly Exits")
    print(f"{'=' * 90}")
    print(f"  {'Metric':<30s} {'Before':>15s} {'After':>15s} {'Difference':>15s}")
    print(f"  {'-' * 75}")
    
    def fmt_diff(orig, mod, is_pct=False, inverse=False):
        """Format difference with color indicator."""
        diff = mod - orig
        if is_pct:
            diff_str = f"{diff:+.2f}pp"
        else:
            diff_str = f"{diff:+,.0f}" if abs(diff) > 100 else f"{diff:+.2f}"
        
        # For metrics where lower is better (inverse=True)
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
        
        ("Total Return", f"{original.total_return_pct:.2f}%", f"{modified.total_return_pct:.2f}%",
         fmt_diff(original.total_return_pct, modified.total_return_pct, is_pct=True)),
        
        ("CAGR", f"{original.cagr_pct:.2f}%", f"{modified.cagr_pct:.2f}%",
         fmt_diff(original.cagr_pct, modified.cagr_pct, is_pct=True)),
        
        ("Max Drawdown", f"{original.max_drawdown_pct:.1f}%", f"{modified.max_drawdown_pct:.1f}%",
         fmt_diff(original.max_drawdown_pct, modified.max_drawdown_pct, is_pct=True, inverse=True)),
        
        ("Sharpe Ratio", f"{original.sharpe_ratio:.2f}", f"{modified.sharpe_ratio:.2f}",
         fmt_diff(original.sharpe_ratio, modified.sharpe_ratio)),
        
        ("Sortino Ratio", f"{original.sortino_ratio:.2f}", f"{modified.sortino_ratio:.2f}",
         fmt_diff(original.sortino_ratio, modified.sortino_ratio)),
        
        ("Calmar Ratio", f"{original.calmar_ratio:.2f}", f"{modified.calmar_ratio:.2f}",
         fmt_diff(original.calmar_ratio, modified.calmar_ratio)),
        
        ("Win Rate", f"{original.win_rate:.1f}%", f"{modified.win_rate:.1f}%",
         fmt_diff(original.win_rate, modified.win_rate, is_pct=True)),
        
        ("Profit Factor", f"{original.profit_factor:.2f}", f"{modified.profit_factor:.2f}",
         fmt_diff(original.profit_factor, modified.profit_factor)),
        
        ("Avg P&L/Trade", f"Rs.{original.avg_pnl_per_trade:,.0f}", f"Rs.{modified.avg_pnl_per_trade:,.0f}",
         fmt_diff(original.avg_pnl_per_trade, modified.avg_pnl_per_trade)),
        
        ("Avg Hold (days)", f"{original.avg_holding_days:.1f}", f"{modified.avg_holding_days:.1f}",
         fmt_diff(original.avg_holding_days, modified.avg_holding_days, inverse=True)),
        
        ("Best Trade", f"Rs.{original.best_trade_pnl:,.0f}", f"Rs.{modified.best_trade_pnl:,.0f}",
         fmt_diff(original.best_trade_pnl, modified.best_trade_pnl)),
        
        ("Worst Trade", f"Rs.{original.worst_trade_pnl:,.0f}", f"Rs.{modified.worst_trade_pnl:,.0f}",
         fmt_diff(original.worst_trade_pnl, modified.worst_trade_pnl, inverse=True)),
        
        ("Max Consec Wins", f"{original.max_consecutive_wins}", f"{modified.max_consecutive_wins}",
         fmt_diff(original.max_consecutive_wins, modified.max_consecutive_wins)),
        
        ("Max Consec Losses", f"{original.max_consecutive_losses}", f"{modified.max_consecutive_losses}",
         fmt_diff(original.max_consecutive_losses, modified.max_consecutive_losses, inverse=True)),
        
        ("Capital Utilization", f"{original.capital_utilization_pct:.1f}%", f"{modified.capital_utilization_pct:.1f}%",
         fmt_diff(original.capital_utilization_pct, modified.capital_utilization_pct, is_pct=True)),
    ]
    
    for metric, orig, mod, diff in rows:
        print(f"  {metric:<30s} {orig:>15s} {mod:>15s} {diff:>15s}")
    
    print(f"{'=' * 90}")


def print_exit_distribution(original: WeeklyBacktestResult, modified: WeeklyBacktestResult) -> None:
    reasons = sorted(set(original.exit_reason_breakdown) | set(modified.exit_reason_breakdown))
    total_orig = max(1, original.total_trades)
    total_mod = max(1, modified.total_trades)

    print(f"\n{'=' * 90}")
    print("  EXIT DISTRIBUTION: Before vs After")
    print(f"{'=' * 90}")
    print(f"  {'Reason':<24s} {'Before':>18s} {'After':>18s} {'Delta':>10s}")
    print(f"  {'-' * 76}")
    for reason in reasons:
        before = original.exit_reason_breakdown.get(reason, 0)
        after = modified.exit_reason_breakdown.get(reason, 0)
        print(
            f"  {reason:<24s} "
            f"{before:>4d} ({before / total_orig * 100:>5.1f}%) "
            f"{after:>4d} ({after / total_mod * 100:>5.1f}%) "
            f"{after - before:>+10d}"
        )
    print(f"{'=' * 90}")


def analyze_verdict(original: WeeklyBacktestResult, modified: WeeklyBacktestResult) -> None:
    """Provide verdict on which approach is better."""
    print(f"\n{'=' * 90}")
    print(f"  VERDICT: Is the Redesigned Weekly Exit Better?")
    print(f"{'=' * 90}")
    
    # Key metrics to compare
    metrics_score = 0
    total_metrics = 0
    
    comparisons = [
        ("CAGR", modified.cagr_pct > original.cagr_pct, modified.cagr_pct, original.cagr_pct),
        ("Sharpe Ratio", modified.sharpe_ratio > original.sharpe_ratio, modified.sharpe_ratio, original.sharpe_ratio),
        ("Max Drawdown", modified.max_drawdown_pct < original.max_drawdown_pct, modified.max_drawdown_pct, original.max_drawdown_pct),
        ("Win Rate", modified.win_rate > original.win_rate, modified.win_rate, original.win_rate),
        ("Profit Factor", modified.profit_factor > original.profit_factor, modified.profit_factor, original.profit_factor),
        ("Sortino Ratio", modified.sortino_ratio > original.sortino_ratio, modified.sortino_ratio, original.sortino_ratio),
    ]
    
    for metric_name, is_better, mod_val, orig_val in comparisons:
        total_metrics += 1
        symbol = "✓" if is_better else "✗"
        status = "BETTER" if is_better else "WORSE"
        diff = mod_val - orig_val
        
        if metric_name == "Max Drawdown":
            diff_str = f"{diff:.2f}pp (lower is better)"
        else:
            diff_str = f"{diff:+.2f}"
        
        print(f"  [{symbol}] {metric_name:<20s}: {status:<10s} | Diff: {diff_str}")
        if is_better:
            metrics_score += 1
    
    print(f"\n  Score: {metrics_score}/{total_metrics} metrics improved")
    
    # Overall verdict
    if metrics_score >= 4:
        print(f"\n  >>> CONCLUSION: Redesigned weekly exits are SIGNIFICANTLY BETTER <<<")
        print(f"  Recommendation: Adopt the redesigned weekly exit logic.")
    elif metrics_score >= 3:
        print(f"\n  >>> CONCLUSION: Redesigned weekly exits are MODERATELY BETTER <<<")
        print(f"  Recommendation: Consider adopting with further validation.")
    elif metrics_score >= 2:
        print(f"\n  >>> CONCLUSION: Results are MIXED <<<")
        print(f"  Recommendation: More testing needed. Performance is similar.")
    else:
        print(f"\n  >>> CONCLUSION: Legacy weekly exits are BETTER <<<")
        print(f"  Recommendation: Keep the legacy exit logic for now.")
    
    print(f"{'=' * 90}\n")


def main():
    parser = argparse.ArgumentParser(description="Compare legacy vs redesigned weekly exit logic")
    parser.add_argument("--start", type=str, default="2009-01-01", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, default=str(date.today()), help="End date")
    parser.add_argument("--capital", type=float, default=500_000.0, help="Initial capital")
    parser.add_argument("--lots", type=int, default=10, help="Max lots per weekly trade")
    args = parser.parse_args()

    config = WeeklyBacktestConfig(
        start_date=date.fromisoformat(args.start),
        end_date=date.fromisoformat(args.end),
        initial_capital=args.capital,
        max_lots=args.lots,
    )

    print("\n" + "=" * 90)
    print("  EXIT STRATEGY COMPARISON: Legacy vs Redesigned Weekly Exits")
    print(f"  Period: {config.start_date} to {config.end_date}")
    print(f"  Capital: Rs.{config.initial_capital:,.0f} | Max Lots: {config.max_lots}")
    print("=" * 90)

    print("\n[1/5] Fetching market data...")
    fetcher = MarketDataFetcher(config.start_date, config.end_date)
    data = fetcher.build_combined_dataset()
    print(f"  Loaded {len(data)} trading days")
    print(f"  Nifty range: {data['nifty_close'].min():.0f} - {data['nifty_close'].max():.0f}")
    if "vix" in data.columns:
        print(f"  VIX range: {data['vix'].min():.1f} - {data['vix'].max():.1f}")

    before_config = replace(config, weekly_exit_policy="legacy")
    after_config = replace(config, weekly_exit_policy="redesigned")

    print(f"\n[2/5] Running BEFORE backtest (legacy exits)...")
    original_engine = WeeklyBacktestEngine(data, before_config)
    original_result = original_engine.run()
    print(f"  Completed: {original_result.total_trades} trades | P&L Rs.{original_result.total_pnl:,.0f} | "
          f"CAGR {original_result.cagr_pct:.2f}%")

    print(f"\n[3/5] Running AFTER backtest (redesigned exits)...")
    modified_engine = WeeklyBacktestEngine(data, after_config)
    modified_result = modified_engine.run()
    print(f"  Completed: {modified_result.total_trades} trades | P&L Rs.{modified_result.total_pnl:,.0f} | "
          f"CAGR {modified_result.cagr_pct:.2f}%")

    print(f"\n[4/5] Detailed Results")
    print_result(original_result, "BEFORE (LEGACY WEEKLY EXITS)")
    print_result(modified_result, "AFTER (REDESIGNED WEEKLY EXITS)")

    print(f"\n[5/5] Comparison & Verdict")
    print_comparison(original_result, modified_result)
    print_exit_distribution(original_result, modified_result)
    analyze_verdict(original_result, modified_result)


if __name__ == "__main__":
    main()
