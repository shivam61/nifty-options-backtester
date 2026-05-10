#!/usr/bin/env python3
"""
Weekly Options Backtester — Phase 1 Edge Validation

Standalone entry point for weekly (3-7 DTE) Nifty options backtesting.
Uses PCS + IC strategies only, pure rule-based (no ML).

Usage:
    python main_weekly.py                           # Full backtest
    python main_weekly.py --start 2019-01-01        # From weekly expiry launch
    python main_weekly.py --capital 1000000          # Custom capital
    python main_weekly.py --compare                  # Side-by-side with monthly
"""

import argparse
import os
import sys
import random
from datetime import date, datetime
from pathlib import Path

os.environ["PYTHONHASHSEED"] = "42"
random.seed(42)

import numpy as np
import pandas as pd

np.random.seed(42)

from config import WeeklyBacktestConfig
from data.market_data import MarketDataFetcher
from backtester.weekly_engine import WeeklyBacktestEngine, WeeklyBacktestResult


DECISION_GATE = {
    "cagr_pct": 8.0,
    "max_drawdown_pct": 12.0,
    "sharpe_ratio": 0.8,
    "win_rate": 55.0,
}


def print_result(result: WeeklyBacktestResult, label: str = "Weekly") -> None:
    """Print formatted backtest results."""
    print(f"\n{'=' * 70}")
    print(f"  {label} OPTIONS BACKTEST RESULTS")
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
        print(f"  {'Strategy':<20s} {'Trades':>7s} {'Win%':>7s} {'Total PnL':>12s}")
        print(f"  {'-' * 46}")
        for name, stats in sorted(result.strategy_breakdown.items(), key=lambda x: -x[1]["trades"]):
            wr = stats["wins"] / stats["trades"] * 100 if stats["trades"] > 0 else 0
            print(f"  {name:<20s} {stats['trades']:>7d} {wr:>6.1f}% Rs.{stats['total_pnl']:>10,.0f}")


def evaluate_decision_gate(result: WeeklyBacktestResult) -> dict:
    """Check if weekly results pass Phase 1 decision gate."""
    checks = {
        "CAGR > 8%": (result.cagr_pct >= DECISION_GATE["cagr_pct"], result.cagr_pct, DECISION_GATE["cagr_pct"]),
        "Max DD < 12%": (result.max_drawdown_pct <= DECISION_GATE["max_drawdown_pct"], result.max_drawdown_pct, DECISION_GATE["max_drawdown_pct"]),
        "Sharpe > 0.8": (result.sharpe_ratio >= DECISION_GATE["sharpe_ratio"], result.sharpe_ratio, DECISION_GATE["sharpe_ratio"]),
        "Win Rate > 55%": (result.win_rate >= DECISION_GATE["win_rate"], result.win_rate, DECISION_GATE["win_rate"]),
    }

    print(f"\n{'=' * 70}")
    print(f"  PHASE 1 DECISION GATE")
    print(f"{'=' * 70}")

    all_pass = True
    for check_name, (passed, actual, threshold) in checks.items():
        status = "PASS" if passed else "FAIL"
        symbol = "+" if passed else "X"
        print(f"  [{symbol}] {check_name:.<30s} actual={actual:.2f}  threshold={threshold:.1f}  {status}")
        if not passed:
            all_pass = False

    print(f"\n  {'>>> PROCEED TO PHASE 2 <<<' if all_pass else '>>> WEEKLY EDGE NOT VALIDATED — DO NOT PROCEED <<<'}")
    print(f"{'=' * 70}")

    return {"passed": all_pass, "checks": checks}


def compute_correlation(weekly_daily_pnl: list, monthly_daily_pnl: list) -> float:
    """Compute correlation between weekly and monthly daily P&L series."""
    min_len = min(len(weekly_daily_pnl), len(monthly_daily_pnl))
    if min_len < 30:
        return 0.0
    w = np.array(weekly_daily_pnl[:min_len])
    m = np.array(monthly_daily_pnl[:min_len])
    mask = (w != 0) | (m != 0)
    if mask.sum() < 30:
        return 0.0
    corr = np.corrcoef(w[mask], m[mask])[0, 1]
    return round(corr, 3) if not np.isnan(corr) else 0.0


def load_weekly_market_data(config: WeeklyBacktestConfig) -> pd.DataFrame:
    """Fetch market data once so baseline and realism runs share the same input."""
    fetcher = MarketDataFetcher(config.start_date, config.end_date)
    return fetcher.build_combined_dataset()


def run_weekly_backtest(
    config: WeeklyBacktestConfig,
    data: pd.DataFrame | None = None,
    *,
    print_summary: bool = True,
    label: str = "Weekly",
) -> WeeklyBacktestResult:
    """Run the weekly options backtest."""
    if print_summary:
        print("\n" + "=" * 70)
        print("  WEEKLY OPTIONS BACKTESTER — PHASE 1 EDGE VALIDATION")
        print(f"  Period: {config.start_date} to {config.end_date}")
        print(f"  Capital: Rs.{config.initial_capital:,.0f} | Max Lots: {config.max_lots}")
        print(f"  Entry DTE: {config.min_dte_entry}-{config.max_dte_entry} | VIX Band: {config.min_vix_entry}-{config.max_vix_entry}")
        print(f"  Profit Target: {config.profit_target_pct}% | Stop Loss: {config.stop_loss_pct}%")
        print(f"  Stop-Loss Fill: {config.stop_loss_fill_policy} | Extra Penalty/Unit: {config.stop_loss_slippage_penalty_per_unit:.2f}")
        print("=" * 70)
        print("\n[1/3] Fetching market data...")

    if data is None:
        data = load_weekly_market_data(config)

    if print_summary:
        print(f"  Loaded {len(data)} trading days")
        print(f"  Nifty range: {data['nifty_close'].min():.0f} - {data['nifty_close'].max():.0f}")
        if "vix" in data.columns:
            print(f"  VIX range: {data['vix'].min():.1f} - {data['vix'].max():.1f}")
        print(f"\n[2/3] Running weekly backtest (PCS + IC, rule-based exits)...")

    engine = WeeklyBacktestEngine(data, config)
    result = engine.run()

    if print_summary:
        print(f"  Trades: {result.total_trades} | Win Rate: {result.win_rate:.0f}% | "
              f"P&L Rs.{result.total_pnl:,.0f} | CAGR {result.cagr_pct:.2f}%")
        print(f"  Sharpe: {result.sharpe_ratio:.2f} | Max DD: {result.max_drawdown_pct:.1f}% | "
              f"Calmar: {result.calmar_ratio:.2f}")
        print(f"\n[3/3] Results & Decision Gate")
        print_result(result, label=label)
        evaluate_decision_gate(result)

    return result


def average_weekly_pnl(result: WeeklyBacktestResult) -> float:
    """Average realized P&L per exit week."""
    if not result.trades:
        return 0.0
    weekly = {}
    for trade in result.trades:
        week_end = pd.Timestamp(trade.exit_date).to_period("W-FRI").end_time.date()
        weekly[week_end] = weekly.get(week_end, 0.0) + trade.total_pnl
    return sum(weekly.values()) / len(weekly) if weekly else 0.0


def _fmt_currency(val: float) -> str:
    return f"Rs.{val:,.0f}"


def _fmt_diff(base: float, new: float, *, pct: bool = False, currency: bool = False) -> str:
    if currency:
        return f"{_fmt_currency(base)} -> {_fmt_currency(new)} ({new - base:+,.0f})"
    suffix = "%" if pct else ""
    return f"{base:.2f}{suffix} -> {new:.2f}{suffix} ({new - base:+.2f}{suffix})"


def print_stop_loss_realism_diff(
    baseline: WeeklyBacktestResult,
    realism: WeeklyBacktestResult,
    realism_config: WeeklyBacktestConfig,
) -> None:
    """Print the requested concise baseline vs realism diff."""
    print("\n" + "=" * 70)
    print("  STOP-LOSS REALISM DIFF")
    print("=" * 70)
    print(f"  Policy: {realism_config.stop_loss_fill_policy}")
    print(f"  Extra Stop-Loss Penalty/Unit: {realism_config.stop_loss_slippage_penalty_per_unit:.2f}")
    print(f"  Total P&L:                   {_fmt_diff(baseline.total_pnl, realism.total_pnl, currency=True)}")
    print(f"  Weekly P&L:                  {_fmt_diff(average_weekly_pnl(baseline), average_weekly_pnl(realism), currency=True)}")
    print(f"  CAGR:                        {_fmt_diff(baseline.cagr_pct, realism.cagr_pct, pct=True)}")
    print(f"  Max Drawdown:                {_fmt_diff(baseline.max_drawdown_pct, realism.max_drawdown_pct, pct=True)}")
    print(f"  Sharpe:                      {_fmt_diff(baseline.sharpe_ratio, realism.sharpe_ratio)}")
    print(f"  PF:                          {_fmt_diff(baseline.profit_factor, realism.profit_factor)}")
    print(f"  Worst Trade:                 {_fmt_diff(baseline.worst_trade_pnl, realism.worst_trade_pnl, currency=True)}")
    print(
        f"  Stop-Loss Exits Affected:    "
        f"{baseline.stop_loss_exits_affected} -> {realism.stop_loss_exits_affected} "
        f"({realism.stop_loss_exits_affected - baseline.stop_loss_exits_affected:+d})"
    )
    print("=" * 70)


def run_comparison(weekly_config: WeeklyBacktestConfig) -> None:
    """Run both weekly and monthly backtests side-by-side."""
    from config import BacktestConfig
    from strategies.multi_strategy import RegimeAdaptiveStrategy
    from backtester.engine import SmartBacktestEngine
    from models.strategy_evolver import StrategyEvolver
    from backtester.rolling_simulator import RollingWindowSimulator, SimConfig
    from models.regime_aware_learner import RegimeAwareLearner
    from models.trade_monitor import ExitStrategyEngine

    print("\n" + "=" * 70)
    print("  WEEKLY vs MONTHLY — SIDE-BY-SIDE COMPARISON")
    print("=" * 70)

    print("\n--- WEEKLY BACKTEST ---")
    weekly_result = run_weekly_backtest(weekly_config)

    monthly_config = BacktestConfig(
        start_date=weekly_config.start_date,
        end_date=weekly_config.end_date,
        initial_capital=weekly_config.initial_capital,
    )

    print("\n\n--- MONTHLY BACKTEST ---")
    print(f"\n[1/4] Fetching market data...")
    fetcher = MarketDataFetcher(monthly_config.start_date, monthly_config.end_date)
    data = fetcher.build_combined_dataset()
    print(f"  Loaded {len(data)} trading days")

    train_cutoff = int(len(data) * 0.6)
    train_data = data.iloc[:train_cutoff]

    print(f"\n[2/4] Training exit model...")
    exit_engine = ExitStrategyEngine(train_data)
    cached_evolved = StrategyEvolver.load_from_cache()
    if cached_evolved:
        exit_engine.train_from_simulations(cached_evolved, verbose=False)
    else:
        from models.strategy_evolver import StrategyEvolver as SE
        se = SE(train_data, lots=monthly_config.max_lots, lot_size=monthly_config.lot_size)
        evolved = se.evolve(target="sharpe", entry_every_n_days=10, verbose=False)
        exit_engine.train_from_simulations(evolved, verbose=False)

    print(f"\n[3/4] Training entry model...")
    sim_cfg = SimConfig(lots=monthly_config.max_lots, lot_size=monthly_config.lot_size, entry_every_n_days=3)
    sim = RollingWindowSimulator(train_data, config=sim_cfg)
    sim_trades = sim.simulate_all()
    entry_model = RegimeAwareLearner(model_version="v4")
    entry_model.train(sim_trades, train_data, verbose=False)

    print(f"\n[4/4] Running monthly backtest...")
    strategy = RegimeAdaptiveStrategy(lots=monthly_config.max_lots, lot_size=monthly_config.lot_size)
    engine = SmartBacktestEngine(
        strategy, data, monthly_config, 21,
        exit_engine=exit_engine,
        entry_model=entry_model,
        entry_threshold=0.48,
        compound=True,
    )
    monthly_result = engine.run()

    corr = compute_correlation(weekly_result.daily_pnl, monthly_result.daily_pnl)

    print(f"\n\n{'=' * 70}")
    print(f"  SIDE-BY-SIDE COMPARISON")
    print(f"{'=' * 70}")
    print(f"  {'Metric':<25s} {'Weekly':>12s} {'Monthly':>12s}")
    print(f"  {'-' * 49}")
    rows = [
        ("Total Trades", f"{weekly_result.total_trades}", f"{monthly_result.total_trades}"),
        ("CAGR", f"{weekly_result.cagr_pct:.2f}%", f"{monthly_result.cagr_pct:.2f}%"),
        ("Max Drawdown", f"{weekly_result.max_drawdown_pct:.1f}%", f"{monthly_result.max_drawdown_pct:.1f}%"),
        ("Sharpe Ratio", f"{weekly_result.sharpe_ratio:.2f}", f"{monthly_result.sharpe_ratio:.2f}"),
        ("Sortino Ratio", f"{weekly_result.sortino_ratio:.2f}", f"{monthly_result.sortino_ratio:.2f}"),
        ("Calmar Ratio", f"{weekly_result.calmar_ratio:.2f}", f"{monthly_result.calmar_ratio:.2f}"),
        ("Win Rate", f"{weekly_result.win_rate:.1f}%", f"{monthly_result.win_rate:.1f}%"),
        ("Profit Factor", f"{weekly_result.profit_factor:.2f}", f"{monthly_result.profit_factor:.2f}"),
        ("Avg Hold (days)", f"{weekly_result.avg_holding_days:.1f}", f"{monthly_result.avg_holding_days:.1f}" if hasattr(monthly_result, "avg_holding_days") else "N/A"),
        ("Capital Utilization", f"{weekly_result.capital_utilization_pct:.1f}%", "N/A"),
        ("Total P&L", f"Rs.{weekly_result.total_pnl:,.0f}", f"Rs.{monthly_result.total_pnl:,.0f}"),
    ]
    for metric, w, m in rows:
        print(f"  {metric:<25s} {w:>12s} {m:>12s}")

    print(f"\n  Daily P&L Correlation:   {corr:.3f}  {'(< 0.5 = diversifying)' if corr < 0.5 else '(>= 0.5 = amplifying!)'}")

    combined_pnl = weekly_result.total_pnl + monthly_result.total_pnl
    combined_return = combined_pnl / weekly_config.initial_capital * 100
    n_days = len(weekly_result.equity_curve)
    years = n_days / 252 if n_days > 0 else 1
    combined_final = weekly_config.initial_capital + combined_pnl
    combined_cagr = ((combined_final / weekly_config.initial_capital) ** (1 / years) - 1) * 100 if years > 0 else 0

    print(f"\n  --- Combined Estimate (concurrent, shared capital) ---")
    print(f"  Combined P&L:           Rs.{combined_pnl:,.0f}")
    print(f"  Combined Return:        {combined_return:.2f}%")
    print(f"  Combined CAGR (est):    {combined_cagr:.2f}%")
    print(f"{'=' * 70}")


def main():
    parser = argparse.ArgumentParser(description="Weekly Options Backtester — Phase 1")
    parser.add_argument("--start", type=str, default="2009-01-01", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, default=str(date.today()), help="End date")
    parser.add_argument("--capital", type=float, default=500_000.0, help="Initial capital")
    parser.add_argument("--lots", type=int, default=10, help="Max lots per weekly trade")
    parser.add_argument("--compare", action="store_true", help="Run side-by-side comparison with monthly")
    parser.add_argument(
        "--stop-loss-fill-policy",
        choices=["mark_to_market", "worst_of_trigger_and_next_open"],
        default="mark_to_market",
        help="How stop-loss exits are filled",
    )
    parser.add_argument(
        "--stop-loss-slippage-penalty-per-unit",
        type=float,
        default=0.0,
        help="Extra per-unit penalty applied only to stop-loss exits",
    )
    parser.add_argument(
        "--compare-stop-loss-realism",
        action="store_true",
        help="Run baseline vs realism mode on the same weekly backtest",
    )
    args = parser.parse_args()

    config = WeeklyBacktestConfig(
        start_date=date.fromisoformat(args.start),
        end_date=date.fromisoformat(args.end),
        initial_capital=args.capital,
        max_lots=args.lots,
        stop_loss_fill_policy=args.stop_loss_fill_policy,
        stop_loss_slippage_penalty_per_unit=args.stop_loss_slippage_penalty_per_unit,
    )

    if args.compare:
        run_comparison(config)
    elif args.compare_stop_loss_realism:
        data = load_weekly_market_data(config)
        baseline_config = WeeklyBacktestConfig(
            start_date=config.start_date,
            end_date=config.end_date,
            initial_capital=config.initial_capital,
            lot_size=config.lot_size,
            max_lots=config.max_lots,
            risk_free_rate=config.risk_free_rate,
            min_dte_entry=config.min_dte_entry,
            max_dte_entry=config.max_dte_entry,
            profit_target_pct=config.profit_target_pct,
            stop_loss_pct=config.stop_loss_pct,
            max_vix_entry=config.max_vix_entry,
            min_vix_entry=config.min_vix_entry,
            capital_protection_pct=config.capital_protection_pct,
            trailing_peak_pct=config.trailing_peak_pct,
            trailing_drop_pct=config.trailing_drop_pct,
            expiry_exit_dte=config.expiry_exit_dte,
            weekly_exit_policy=config.weekly_exit_policy,
            stop_loss_fill_policy="mark_to_market",
            stop_loss_slippage_penalty_per_unit=0.0,
            engine_a_profit_target_pct=config.engine_a_profit_target_pct,
            engine_a_min_hold_days=config.engine_a_min_hold_days,
            engine_b_max_hold_days=config.engine_b_max_hold_days,
            engine_b_delta_trail_arm_ratio=config.engine_b_delta_trail_arm_ratio,
            engine_b_delta_trail_rebound_ratio=config.engine_b_delta_trail_rebound_ratio,
            engine_b_trend_trigger_pct=config.engine_b_trend_trigger_pct,
            engine_b_trend_reversal_pct=config.engine_b_trend_reversal_pct,
            cost_model=config.cost_model,
            apply_costs=config.apply_costs,
        )
        realism_config = WeeklyBacktestConfig(
            start_date=config.start_date,
            end_date=config.end_date,
            initial_capital=config.initial_capital,
            lot_size=config.lot_size,
            max_lots=config.max_lots,
            risk_free_rate=config.risk_free_rate,
            min_dte_entry=config.min_dte_entry,
            max_dte_entry=config.max_dte_entry,
            profit_target_pct=config.profit_target_pct,
            stop_loss_pct=config.stop_loss_pct,
            max_vix_entry=config.max_vix_entry,
            min_vix_entry=config.min_vix_entry,
            capital_protection_pct=config.capital_protection_pct,
            trailing_peak_pct=config.trailing_peak_pct,
            trailing_drop_pct=config.trailing_drop_pct,
            expiry_exit_dte=config.expiry_exit_dte,
            weekly_exit_policy=config.weekly_exit_policy,
            stop_loss_fill_policy="worst_of_trigger_and_next_open",
            stop_loss_slippage_penalty_per_unit=args.stop_loss_slippage_penalty_per_unit,
            engine_a_profit_target_pct=config.engine_a_profit_target_pct,
            engine_a_min_hold_days=config.engine_a_min_hold_days,
            engine_b_max_hold_days=config.engine_b_max_hold_days,
            engine_b_delta_trail_arm_ratio=config.engine_b_delta_trail_arm_ratio,
            engine_b_delta_trail_rebound_ratio=config.engine_b_delta_trail_rebound_ratio,
            engine_b_trend_trigger_pct=config.engine_b_trend_trigger_pct,
            engine_b_trend_reversal_pct=config.engine_b_trend_reversal_pct,
            cost_model=config.cost_model,
            apply_costs=config.apply_costs,
        )
        baseline = run_weekly_backtest(baseline_config, data=data, print_summary=False, label="Baseline Weekly")
        realism = run_weekly_backtest(realism_config, data=data, print_summary=False, label="Realism Weekly")
        print_stop_loss_realism_diff(baseline, realism, realism_config)
    else:
        run_weekly_backtest(config)


if __name__ == "__main__":
    main()
