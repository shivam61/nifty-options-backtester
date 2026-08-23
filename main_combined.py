#!/usr/bin/env python3
"""
Combined Monthly + Weekly Options Backtester

Runs both tracks concurrently on shared capital pool:
- Monthly: ML entry/exit, regime-adaptive (50% budget, v8 2026-08-23)
- Weekly: rule-based PCS/IC, 3-7 DTE (50% budget, v8 2026-08-23)

Usage:
    python main_combined.py                          # Full combined backtest
    python main_combined.py --monthly-pct 0.60       # Adjust budget split
    python main_combined.py --capital 1000000         # Custom capital
"""

import argparse
import os
import sys
import random
from datetime import date

os.environ["PYTHONHASHSEED"] = "42"
random.seed(42)

import numpy as np
import pandas as pd

np.random.seed(42)

from config import BacktestConfig, WeeklyBacktestConfig
from data.market_data import MarketDataFetcher
from strategies.multi_strategy import RegimeAdaptiveStrategy
from backtester.combined_engine import CombinedBacktestEngine, CombinedResult
from backtester.walk_forward import WalkForwardManager


def print_combined_result(r: CombinedResult) -> None:
    print(f"\n{'=' * 70}")
    print(f"  COMBINED MONTHLY + WEEKLY BACKTEST RESULTS")
    print(f"{'=' * 70}")

    print(f"\n  ── RETURN METRICS ──")
    print(f"  Total P&L:              Rs.{r.total_pnl:>12,.0f}")
    print(f"  CAGR:                   {r.cagr_pct:>11.2f}%")
    print(f"  Sharpe Ratio:           {r.sharpe_ratio:>11.2f}")
    print(f"  Sortino Ratio:          {r.sortino_ratio:>11.2f}")
    print(f"  Calmar Ratio:           {r.calmar_ratio:>11.2f}")

    print(f"\n  ── RISK METRICS ──")
    print(f"  Max Drawdown:           {r.max_drawdown_pct:>11.1f}%")
    print(f"  Cross-Track DD Blocks:  {r.cross_track_dd_blocks:>11}")
    print(f"  Best Trade:             Rs.{r.best_trade_pnl:>12,.0f}")
    print(f"  Worst Trade:            Rs.{r.worst_trade_pnl:>12,.0f}")

    print(f"\n  ── TRADE STATS ──")
    print(f"  Total Trades:           {r.total_trades:>11}  (monthly: {r.monthly_trades}, weekly: {r.weekly_trades})")
    print(f"  Combined Win Rate:      {r.win_rate:>10.1f}%")
    print(f"  Monthly Win Rate:       {r.monthly_win_rate:>10.1f}%")
    print(f"  Weekly Win Rate:        {r.weekly_win_rate:>10.1f}%")
    print(f"  Profit Factor:          {r.profit_factor:>11.2f}")
    print(f"  Capital Utilization:    {r.capital_utilization_pct:>10.1f}%")

    print(f"\n  ── P&L BY TRACK ──")
    print(f"  Monthly P&L:            Rs.{r.monthly_pnl:>12,.0f}")
    print(f"  Weekly P&L:             Rs.{r.weekly_pnl:>12,.0f}")
    pct_monthly = r.monthly_pnl / r.total_pnl * 100 if r.total_pnl != 0 else 0
    pct_weekly = r.weekly_pnl / r.total_pnl * 100 if r.total_pnl != 0 else 0
    print(f"  Monthly contribution:   {pct_monthly:>10.1f}%")
    print(f"  Weekly contribution:    {pct_weekly:>10.1f}%")

    print(f"\n  ── HOLDING PERIODS ──")
    print(f"  Avg Hold (monthly):     {r.avg_holding_days_monthly:>10.1f} days")
    print(f"  Avg Hold (weekly):      {r.avg_holding_days_weekly:>10.1f} days")
    print(f"{'=' * 70}")


def print_comparison(combined: CombinedResult, monthly_only_cagr: float, monthly_only_dd: float,
                     monthly_only_sharpe: float, monthly_only_trades: int) -> None:
    print(f"\n{'=' * 70}")
    print(f"  COMBINED vs MONTHLY-ONLY COMPARISON")
    print(f"{'=' * 70}")
    print(f"  {'Metric':<25s} {'Monthly Only':>14s} {'Combined':>14s} {'Delta':>10s}")
    print(f"  {'-' * 63}")

    cagr_delta = combined.cagr_pct - monthly_only_cagr
    dd_delta = combined.max_drawdown_pct - monthly_only_dd
    sharpe_delta = combined.sharpe_ratio - monthly_only_sharpe

    print(f"  {'CAGR':<25s} {monthly_only_cagr:>13.2f}% {combined.cagr_pct:>13.2f}% {cagr_delta:>+9.2f}%")
    print(f"  {'Max Drawdown':<25s} {monthly_only_dd:>13.1f}% {combined.max_drawdown_pct:>13.1f}% {dd_delta:>+9.1f}%")
    print(f"  {'Sharpe Ratio':<25s} {monthly_only_sharpe:>14.2f} {combined.sharpe_ratio:>14.2f} {sharpe_delta:>+10.2f}")
    print(f"  {'Total Trades':<25s} {monthly_only_trades:>14} {combined.total_trades:>14} {combined.total_trades - monthly_only_trades:>+10}")
    print(f"{'=' * 70}")


def main():
    parser = argparse.ArgumentParser(description="Combined Monthly+Weekly Options Backtester")
    parser.add_argument("--start", type=str, default="2009-01-01")
    parser.add_argument("--end", type=str, default=str(date.today()))
    parser.add_argument("--capital", type=float, default=500_000.0)
    parser.add_argument("--monthly-pct", type=float, default=0.60, help="Monthly budget allocation (0-1)")
    parser.add_argument("--weekly-lots", type=int, default=10)
    parser.add_argument("--cross-dd", type=float, default=0.15, help="Cross-track DD threshold to block weekly entries")
    parser.add_argument("--monthly-loss-block", type=float, default=0.02, help="Block weekly if monthly MTM loss exceeds this % of equity")
    parser.add_argument("--open-cap", type=float, default=0.04, help="Block entries if combined open loss exceeds this % of equity")
    parser.add_argument("--vix-cap", type=float, default=22.0, help="VIX ceiling for simultaneous monthly+weekly positions")
    parser.add_argument("--weekly-threshold", type=float, default=0.55, help="Weekly ML quality threshold")
    parser.add_argument("--emergency-exit", type=float, default=0.03, help="Emergency weekly exit if combined open loss > this % of equity")
    parser.add_argument("--diagnostics-dir", type=str, default="results/monthly_diagnostic_report",
                        help="Directory for monthly diagnostic artifacts")
    parser.add_argument("--sensitivity", action="store_true", help="Run budget split sensitivity experiments")
    args = parser.parse_args()

    monthly_config = BacktestConfig(
        start_date=date.fromisoformat(args.start),
        end_date=date.fromisoformat(args.end),
        initial_capital=args.capital,
    )
    weekly_config = WeeklyBacktestConfig(
        start_date=date.fromisoformat(args.start),
        end_date=date.fromisoformat(args.end),
        initial_capital=args.capital,
        max_lots=args.weekly_lots,
    )

    print("\n" + "=" * 70)
    print("  COMBINED MONTHLY + WEEKLY OPTIONS BACKTESTER (v2 — DD-fixed)")
    print(f"  Period: {monthly_config.start_date} to {monthly_config.end_date}")
    print(f"  Capital: Rs.{args.capital:,.0f}")
    print(f"  Budget: Monthly {args.monthly_pct:.0%} / Weekly {1 - args.monthly_pct:.0%}")
    print(f"  Cross-track DD threshold: {args.cross_dd:.0%}")
    print(f"  Monthly loss block: {args.monthly_loss_block:.0%}")
    print(f"  Open position cap: {args.open_cap:.0%}")
    print(f"  VIX simultaneous cap: {args.vix_cap:.0f}")
    print(f"  Weekly ML threshold: {args.weekly_threshold:.2f}")
    print(f"  Emergency exit threshold: {args.emergency_exit:.0%}")
    print("=" * 70)

    # ── Fetch data ──
    print("\n[1/6] Fetching market data...")
    fetcher = MarketDataFetcher(monthly_config.start_date, monthly_config.end_date)
    data = fetcher.build_combined_dataset()
    print(f"  Loaded {len(data)} trading days")

    print(f"\n[2/6] Building walk-forward model schedule (cache-only)...")
    wf_manager = WalkForwardManager(
        data,
        monthly_config=monthly_config,
        weekly_config=weekly_config,
        include_monthly=True,
        include_weekly_entry=True,
        train_on_cache_miss=False,
        retrain_interval_bars=21,
    )
    print(f"  Walk-forward windows: {len(wf_manager.windows)}")

    # ── Run combined backtest ──
    print(f"\n[3/6] Running combined backtest (cached ML when available, otherwise rule-based fallback)...")
    strategy = RegimeAdaptiveStrategy(
        lots=monthly_config.max_lots,
        lot_size=monthly_config.lot_size,
        allow_bwb=not monthly_config.monthly_disable_bwb,
    )

    engine = CombinedBacktestEngine(
        data=data,
        monthly_config=monthly_config,
        weekly_config=weekly_config,
        monthly_strategy=strategy,
        exit_engine=None,
        entry_model=None,
        weekly_entry_model=None,
        entry_threshold=monthly_config.monthly_entry_threshold,
        weekly_entry_threshold=args.weekly_threshold,
        monthly_budget_pct=args.monthly_pct,
        weekly_budget_pct=1.0 - args.monthly_pct,
        cross_track_dd_pct=args.cross_dd,
        monthly_loss_block_pct=args.monthly_loss_block,
        combined_open_loss_cap_pct=args.open_cap,
        vix_simultaneous_cap=args.vix_cap,
        emergency_weekly_exit_pct=args.emergency_exit,
        walk_forward_manager=wf_manager,
    )
    result = engine.run()

    diag_paths = engine.monthly_diagnostics.write_artifacts(args.diagnostics_dir)
    print(f"\n  Monthly diagnostics written to {args.diagnostics_dir}")
    print(f"  Files: {', '.join(sorted(str(p.name) for p in diag_paths.values()))}")

    # ── Report ──
    print(f"\n[4/6] Results")
    print_combined_result(result)

    print_comparison(
        result,
        monthly_only_cagr=13.78,
        monthly_only_dd=5.8,
        monthly_only_sharpe=1.23,
        monthly_only_trades=273,
    )

    print(f"\n  Engine Stats:")
    print(f"    Monthly ML entries:          {engine.monthly_ml_entries}")
    print(f"    Monthly ML skips:            {engine.monthly_ml_skips}")
    print(f"    Monthly smart exits:         {engine.monthly_smart_exits}")
    print(f"    Weekly entries:              {engine.weekly_entries}")
    print(f"    Weekly ML skips:             {engine.weekly_ml_skips}")
    print(f"    Emergency weekly exits:      {engine.emergency_weekly_exits}")
    print(f"    Cross-track DD blocks:       {engine.cross_track_dd_blocks}")
    print(f"    Monthly loss blocks:         {engine.weekly_monthly_loss_blocks}")
    print(f"    Open position cap blocks:    {engine.weekly_open_cap_blocks}")
    print(f"    VIX simultaneous blocks:     {engine.weekly_vix_gate_blocks}")
    print(f"    Weekly streak skips:         {engine.weekly_streak_skips}")
    print(f"    Weekly dynamic scale-downs:  {engine.weekly_dynamic_scale_downs}")
    monthly_diag = result.diagnostics or {}
    if monthly_diag:
        print(f"\n  Monthly Diagnostic Snapshot:")
        print(f"    Trades: {monthly_diag.get('trade_distribution', {}).get('total_trades', 0)}")
        print(f"    Avg P&L/trade: ₹{monthly_diag.get('trade_distribution', {}).get('avg_pnl', 0):,.0f}")
        print(f"    Payoff ratio: {monthly_diag.get('trade_distribution', {}).get('payoff_ratio', 0)}")
        print(f"    Winner cut early: {monthly_diag.get('exit_decomposition', {}).get('winner_cut_early_pct', 0)}%")
        print(f"    Avg final lots: {monthly_diag.get('sizing', {}).get('avg_final_lots', 0)}")

    # ── Sensitivity experiments (Step 7) ──
    if args.sensitivity:
        _run_sensitivity(
            data, monthly_config, weekly_config, strategy, wf_manager, args,
        )


def _run_sensitivity(data, monthly_config, weekly_config, strategy, wf_manager, args):
    """Run budget split sensitivity experiments."""
    print(f"\n{'=' * 70}")
    print(f"  BUDGET SPLIT SENSITIVITY EXPERIMENTS")
    print(f"{'=' * 70}")
    print(f"  {'Split':>10s}  {'CAGR':>8s}  {'Max DD':>8s}  {'Sharpe':>8s}  {'Calmar':>8s}  {'Trades':>8s}")
    print(f"  {'-' * 58}")

    splits = [(0.90, 0.10), (0.80, 0.20), (0.70, 0.30), (0.60, 0.40)]
    for m_pct, w_pct in splits:
        eng = CombinedBacktestEngine(
            data=data,
            monthly_config=monthly_config,
            weekly_config=weekly_config,
            monthly_strategy=strategy,
            exit_engine=None,
            entry_model=None,
            weekly_entry_model=None,
            entry_threshold=monthly_config.monthly_entry_threshold,
            weekly_entry_threshold=args.weekly_threshold,
            monthly_budget_pct=m_pct,
            weekly_budget_pct=w_pct,
            cross_track_dd_pct=args.cross_dd,
            monthly_loss_block_pct=args.monthly_loss_block,
            combined_open_loss_cap_pct=args.open_cap,
            vix_simultaneous_cap=args.vix_cap,
            emergency_weekly_exit_pct=args.emergency_exit,
            walk_forward_manager=wf_manager,
        )
        r = eng.run()
        label = f"{int(m_pct*100)}/{int(w_pct*100)}"
        print(f"  {label:>10s}  {r.cagr_pct:>7.2f}%  {r.max_drawdown_pct:>7.1f}%  {r.sharpe_ratio:>8.2f}  {r.calmar_ratio:>8.2f}  {r.total_trades:>8}")

    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
