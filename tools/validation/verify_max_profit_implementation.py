#!/usr/bin/env python3
"""
Verification: Fixed 85% Max Profit Booking Implementation

Quick test to verify the 85% rule is working as expected in production code.
Runs a short backtest and confirms the feature is enabled and producing
the expected results.
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
from backtester.engine import BacktestEngine
from strategies.multi_strategy import PutCreditSpreadStrategy, IronCondorStrategy


def verify_implementation():
    """Verify the 85% max profit booking is working."""
    
    print("\n" + "=" * 80)
    print("  VERIFICATION: Fixed 85% Max Profit Booking")
    print("=" * 80)
    
    # Test configuration
    print("\n[1/4] Checking configuration...")
    
    pcs = PutCreditSpreadStrategy(lots=10, lot_size=65)
    ic = IronCondorStrategy(lots=10, lot_size=65)
    
    print(f"  PCS Max Profit Booking Enabled: {pcs.enable_max_profit_booking}")
    print(f"  PCS Threshold: {pcs.max_profit_threshold:.0%}")
    print(f"  IC Max Profit Booking Enabled: {ic.enable_max_profit_booking}")
    print(f"  IC Threshold: {ic.max_profit_threshold:.0%}")
    
    if not pcs.enable_max_profit_booking or not ic.enable_max_profit_booking:
        print("\n  ✗ ERROR: Max profit booking not enabled!")
        return False
    
    if pcs.max_profit_threshold != 0.85 or ic.max_profit_threshold != 0.85:
        print("\n  ✗ ERROR: Threshold not set to 85%!")
        return False
    
    print("  ✓ Configuration correct")
    
    # Run quick backtest
    print("\n[2/4] Running verification backtest (2023-2024)...")
    
    config = BacktestConfig(
        start_date=date(2023, 1, 1),
        end_date=date(2024, 12, 31),
        initial_capital=500_000.0,
    )
    
    fetcher = MarketDataFetcher(config.start_date, config.end_date)
    data = fetcher.build_combined_dataset()
    print(f"  Loaded {len(data)} trading days")
    
    # Test PCS
    print("\n[3/4] Testing PCS with 85% rule...")
    pcs_strategy = PutCreditSpreadStrategy(lots=config.max_lots, lot_size=config.lot_size)
    pcs_engine = BacktestEngine(pcs_strategy, data.copy(), config, target_dte=21)
    pcs_result = pcs_engine.run()
    
    print(f"  Trades: {pcs_result.total_trades}")
    print(f"  P&L: Rs.{pcs_result.total_pnl:,.0f}")
    print(f"  CAGR: {pcs_result.cagr_pct:.2f}%")
    print(f"  Max DD: {pcs_result.max_drawdown_pct:.1f}%")
    print(f"  Sharpe: {pcs_result.sharpe_ratio:.2f}")
    print(f"  Avg Hold: {pcs_result.avg_holding_days:.1f} days")
    
    # Test IC
    print("\n[4/4] Testing IC with 85% rule...")
    ic_strategy = IronCondorStrategy(lots=config.max_lots, lot_size=config.lot_size)
    ic_engine = BacktestEngine(ic_strategy, data.copy(), config, target_dte=21)
    ic_result = ic_engine.run()
    
    print(f"  Trades: {ic_result.total_trades}")
    print(f"  P&L: Rs.{ic_result.total_pnl:,.0f}")
    print(f"  CAGR: {ic_result.cagr_pct:.2f}%")
    print(f"  Max DD: {ic_result.max_drawdown_pct:.1f}%")
    print(f"  Sharpe: {ic_result.sharpe_ratio:.2f}")
    print(f"  Avg Hold: {ic_result.avg_holding_days:.1f} days")
    
    # Verification checks
    print("\n" + "=" * 80)
    print("  VERIFICATION RESULTS")
    print("=" * 80)
    
    checks = []
    
    # Check 1: Avg hold should be lower (85% exits earlier)
    if pcs_result.avg_holding_days < 12:
        print("  ✓ PCS avg hold is < 12 days (expected with 85% rule)")
        checks.append(True)
    else:
        print("  ✗ PCS avg hold is >= 12 days (85% rule may not be working)")
        checks.append(False)
    
    if ic_result.avg_holding_days < 15:
        print("  ✓ IC avg hold is < 15 days (expected with 85% rule)")
        checks.append(True)
    else:
        print("  ✗ IC avg hold is >= 15 days (85% rule may not be working)")
        checks.append(False)
    
    # Check 2: Drawdown should be reasonable
    if pcs_result.max_drawdown_pct < 50:
        print("  ✓ PCS max DD < 50% (expected with 85% rule)")
        checks.append(True)
    else:
        print("  ✗ PCS max DD >= 50% (85% rule may not be protecting)")
        checks.append(False)
    
    if ic_result.max_drawdown_pct < 30:
        print("  ✓ IC max DD < 30% (expected with 85% rule)")
        checks.append(True)
    else:
        print("  ✗ IC max DD >= 30% (85% rule may not be protecting)")
        checks.append(False)
    
    # Check 3: Sharpe should be positive/high
    if pcs_result.sharpe_ratio > 0:
        print("  ✓ PCS Sharpe > 0 (expected with 85% rule)")
        checks.append(True)
    else:
        print("  ⚠ PCS Sharpe <= 0 (may indicate issue)")
        checks.append(False)
    
    if ic_result.sharpe_ratio > 1.2:
        print("  ✓ IC Sharpe > 1.2 (expected with 85% rule)")
        checks.append(True)
    else:
        print("  ⚠ IC Sharpe <= 1.2 (may indicate issue)")
        checks.append(False)
    
    print("\n" + "=" * 80)
    
    if all(checks):
        print("  ✓✓✓ ALL CHECKS PASSED - Implementation is working correctly!")
        print("  85% max profit booking is active and producing expected results.")
        return True
    else:
        print("  ⚠⚠⚠ SOME CHECKS FAILED - Please review implementation")
        return False


def compare_with_without():
    """Compare results with and without max profit booking."""
    
    print("\n\n" + "=" * 80)
    print("  COMPARISON: With vs Without Max Profit Booking")
    print("=" * 80)
    
    config = BacktestConfig(
        start_date=date(2023, 1, 1),
        end_date=date(2024, 12, 31),
        initial_capital=500_000.0,
    )
    
    fetcher = MarketDataFetcher(config.start_date, config.end_date)
    data = fetcher.build_combined_dataset()
    
    # PCS with 85%
    pcs_with = PutCreditSpreadStrategy(
        lots=config.max_lots,
        lot_size=config.lot_size,
        enable_max_profit_booking=True,
        max_profit_threshold=0.85
    )
    engine_with = BacktestEngine(pcs_with, data.copy(), config, target_dte=21)
    result_with = engine_with.run()
    
    # PCS without
    pcs_without = PutCreditSpreadStrategy(
        lots=config.max_lots,
        lot_size=config.lot_size,
        enable_max_profit_booking=False
    )
    engine_without = BacktestEngine(pcs_without, data.copy(), config, target_dte=21)
    result_without = engine_without.run()
    
    print(f"\n  {'Metric':<20} {'With 85%':>15} {'Without':>15} {'Difference':>15}")
    print(f"  {'-' * 65}")
    print(f"  {'Total P&L':<20} Rs.{result_with.total_pnl:>12,.0f} Rs.{result_without.total_pnl:>12,.0f} "
          f"{result_with.total_pnl - result_without.total_pnl:>+12,.0f}")
    print(f"  {'CAGR':<20} {result_with.cagr_pct:>14.2f}% {result_without.cagr_pct:>14.2f}% "
          f"{result_with.cagr_pct - result_without.cagr_pct:>+13.2f}pp")
    print(f"  {'Max Drawdown':<20} {result_with.max_drawdown_pct:>14.1f}% {result_without.max_drawdown_pct:>14.1f}% "
          f"{result_with.max_drawdown_pct - result_without.max_drawdown_pct:>+13.1f}pp")
    print(f"  {'Sharpe':<20} {result_with.sharpe_ratio:>15.2f} {result_without.sharpe_ratio:>15.2f} "
          f"{result_with.sharpe_ratio - result_without.sharpe_ratio:>+15.2f}")
    print(f"  {'Avg Hold (days)':<20} {result_with.avg_holding_days:>15.1f} {result_without.avg_holding_days:>15.1f} "
          f"{result_with.avg_holding_days - result_without.avg_holding_days:>+15.1f}")
    
    print("\n" + "=" * 80)


if __name__ == "__main__":
    print("\nRunning implementation verification...")
    success = verify_implementation()
    
    if success:
        print("\nRunning with/without comparison...")
        compare_with_without()
        
        print("\n" + "=" * 80)
        print("  VERIFICATION COMPLETE")
        print("=" * 80)
        print("\n  ✓ Fixed 85% max profit booking is implemented correctly")
        print("  ✓ Ready for production deployment")
        print("\n  Next steps:")
        print("    1. Deploy to paper trading")
        print("    2. Monitor for 2 weeks")
        print("    3. Gradually roll out to production")
        print("=" * 80 + "\n")
    else:
        print("\n  ⚠ Verification failed - please review implementation")
        sys.exit(1)
