#!/usr/bin/env python3
"""
Production Model Validation Suite

Runs comprehensive validation for ALL ML models used in the combined backtester:
  1. Monthly Entry Model (RegimeAwareLearner → TradeLearner v4)
  2. Monthly Exit Model (ExitStrategyEngine)
  3. Weekly Entry Model (WeeklyEntryLearner)
  4. Regime Classifier

Validation methods:
  - Walk-forward (expanding yearly window, true OOS)
  - Permutation test (label shuffling, statistical significance)
  - In-training CV metrics (rolling folds with purge gap)

Usage:
    python main_validate.py                     # Full validation (7 checks)
    python main_validate.py --quick             # Fewer permutations (faster)
    python main_validate.py --n-perms 50        # More permutations (rigorous)
"""

import argparse
import os
import sys
import random
import time
from datetime import date

random.seed(42)

import numpy as np
np.random.seed(42)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import BacktestConfig, WeeklyBacktestConfig
from data.market_data import MarketDataFetcher
from models.strategy_evolver import StrategyEvolver


def main():
    parser = argparse.ArgumentParser(description="Production Model Validation Suite")
    parser.add_argument("--start", type=str, default="2009-01-01")
    parser.add_argument("--end", type=str, default=str(date.today()))
    parser.add_argument("--n-perms", type=int, default=20, help="Number of permutations for label-shuffle test")
    parser.add_argument("--quick", action="store_true", help="Quick mode: 10 permutations")
    args = parser.parse_args()

    n_perms = 10 if args.quick else args.n_perms

    mc = BacktestConfig(
        start_date=date.fromisoformat(args.start),
        end_date=date.fromisoformat(args.end),
    )
    wc = WeeklyBacktestConfig()

    print("\n" + "=" * 80)
    print("  PRODUCTION MODEL VALIDATION")
    print(f"  Period: {mc.start_date} to {mc.end_date}")
    print(f"  Permutations: {n_perms}")
    print("=" * 80)

    # Fetch data
    print("\n[1/3] Fetching market data...")
    fetcher = MarketDataFetcher(mc.start_date, mc.end_date)
    data = fetcher.build_combined_dataset()
    print(f"  Loaded {len(data)} trading days ({data.index[0].date()} to {data.index[-1].date()})")

    # Load evolved strategies (needed for exit model validation)
    print("\n[2/3] Loading evolved strategy configs...")
    evolved = StrategyEvolver.load_from_cache()
    if evolved is None:
        print("  No cached evolved strategies — training fresh...")
        train_cutoff = int(len(data) * 0.6)
        train_data = data.iloc[:train_cutoff]
        se = StrategyEvolver(train_data, lots=mc.max_lots, lot_size=mc.lot_size)
        evolved = se.evolve(target="sharpe", entry_every_n_days=10, verbose=False)
    print(f"  Loaded {len(evolved)} evolved strategies")

    # Run full validation
    print("\n[3/3] Running validation suite...")
    t0 = time.time()

    from models.model_validator import run_full_validation
    results = run_full_validation(
        data=data,
        evolved_strategies=evolved,
        lots=mc.max_lots,
        lot_size=mc.lot_size,
        weekly_lots=wc.max_lots,
        weekly_lot_size=wc.lot_size,
        n_permutations=n_perms,
        verbose=True,
    )

    elapsed = time.time() - t0
    print(f"\n  Validation completed in {elapsed / 60:.1f} minutes")

    # In-training CV recap
    print("\n" + "=" * 80)
    print("  IN-TRAINING CV METRICS (from model.train() internals)")
    print("=" * 80)

    # Train each model once to get internal CV stats
    train_cutoff = int(len(data) * 0.6)
    train_data = data.iloc[:train_cutoff]

    print("\n  Monthly Entry (TradeLearner v4):")
    from backtester.rolling_simulator import RollingWindowSimulator, SimConfig
    from models.regime_aware_learner import RegimeAwareLearner
    sim = RollingWindowSimulator(train_data, config=SimConfig(lots=mc.max_lots, lot_size=mc.lot_size, entry_every_n_days=3))
    entry_model = RegimeAwareLearner(model_version="v4")
    entry_stats = entry_model.train(sim.simulate_all(), train_data, verbose=False)
    regime_stats = entry_stats.get("regime_stats", {})
    global_stats = entry_stats.get("global_model_stats", {})
    print(f"    Regime Classifier CV Acc: {regime_stats.get('cv_accuracy', 0):.1%} ± {regime_stats.get('cv_std', 0):.1%}")
    print(f"    Entry Model CV AUC:      {global_stats.get('cv_auc', 0):.3f} ± {global_stats.get('cv_std', 0):.3f}")
    print(f"    Trained on {global_stats.get('num_trades', 0)} simulated trades")

    print("\n  Monthly Exit (ExitStrategyEngine):")
    from models.trade_monitor import ExitStrategyEngine
    exit_engine = ExitStrategyEngine(train_data)
    exit_engine.train_from_simulations(evolved, verbose=False)
    print(f"    Trained: {exit_engine.is_trained}")

    print("\n  Weekly Entry (WeeklyEntryLearner):")
    from backtester.weekly_simulator import WeeklyRollingSimulator, WeeklySimConfig
    from models.weekly_entry_learner import WeeklyEntryLearner
    wsim = WeeklyRollingSimulator(train_data, config=WeeklySimConfig(lots=wc.max_lots, lot_size=wc.lot_size))
    weekly_model = WeeklyEntryLearner()
    weekly_stats = weekly_model.train(wsim.simulate_all(), train_data, verbose=False)
    print(f"    Weekly Entry CV AUC:     {weekly_stats.get('cv_auc', 0):.3f} ± {weekly_stats.get('cv_std', 0):.3f}")
    print(f"    Trained on {weekly_stats.get('num_trades', 0)} simulated trades")
    print(f"    Positive rate:           {weekly_stats.get('positive_pct', 0):.1f}%")

    # Final verdict
    print("\n" + "=" * 80)
    rate = results["overall_pass_rate"]
    tp = results["total_passed"]
    tc = results["total_checks"]
    if rate >= 0.85:
        emoji = "STRONG"
    elif rate >= 0.57:
        emoji = "ACCEPTABLE"
    elif rate >= 0.28:
        emoji = "WEAK"
    else:
        emoji = "POOR"

    print(f"  FINAL PRODUCTION READINESS: {emoji} ({tp}/{tc} checks passed, {rate:.0%})")
    print("=" * 80)


if __name__ == "__main__":
    main()
