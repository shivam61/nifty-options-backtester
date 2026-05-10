#!/usr/bin/env python3
"""
Test script showing various circuit breaker scenarios with different stress levels.
"""

from datetime import date
from strategies.multi_strategy import RegimeAdaptiveStrategy

def test_moderate_stress():
    """Test with moderate stress (only 2-3 assets stressed)."""
    
    strategy = RegimeAdaptiveStrategy(lots=2, lot_size=65)
    
    # Moderate stress: only Crude and VIX elevated, rest normal
    market_data = {
        "crude": 92.5,              # Crude elevated
        "crude_sma_50": 75.2,
        "crude_std_50": 6.8,
        
        "usdinr": 74.5,             # Normal
        "usdinr_sma_50": 74.2,
        "usdinr_std_50": 0.85,
        
        "vix": 26.8,                # Elevated but not extreme
        "vix_sma_50": 16.5,
        "vix_std_50": 4.2,
        
        "gold": 1650.0,             # Normal
        "gold_sma_50": 1625.0,
        "gold_std_50": 45.0,
        
        "us_vix": 19.5,             # Slightly elevated
        "us_vix_sma_50": 18.2,
        "us_vix_std_50": 5.1,
        
        "sp500": 3120.0,            # Normal
        "sp500_sma_50": 3150.0,
        "sp500_std_50": 120.0,
        
        "dxy": 98.8,                # Normal
        "dxy_sma_50": 98.2,
        "dxy_std_50": 1.5,
        
        "nifty_bank": 28200.0,      # Normal
        "nifty_bank_sma_50": 28500.0,
        "nifty_bank_std_50": 2100.0,
        
        "multi_asset_stress": 0.85,  # 85% stress (above 80% threshold)
        "crash_risk_score_v2": 0.45,
        "nifty_drawdown_from_50d_high_pct": -8.5,
        "vix_accel_3d_pct": 25.2,
        "crude_spike_10d_pct": 15.8,
    }
    
    spot = 10800.0
    vix = 26.8
    
    print("="*80)
    print("SCENARIO 1: MODERATE STRESS (Crude + VIX elevated)")
    print("="*80)
    print()
    
    eligible = strategy.get_eligible_strategies(spot, vix, market_data)
    
    if not eligible:
        print("CIRCUIT BREAKER ACTIVE — NO MONTHLY TRADE TODAY\n")
        reasons = getattr(strategy, "_circuit_breaker_reasons", [])
        for reason in reasons:
            print(f"  X  {reason}\n")
    else:
        print(f"✓ Circuit breaker NOT triggered")
        print(f"  Eligible strategies: {eligible}")
    
    print("="*80)
    print()

def test_low_stress():
    """Test with low stress (all assets normal)."""
    
    strategy = RegimeAdaptiveStrategy(lots=2, lot_size=65)
    
    # All normal
    market_data = {
        "crude": 76.2,
        "crude_sma_50": 75.2,
        "crude_std_50": 6.8,
        
        "usdinr": 74.3,
        "usdinr_sma_50": 74.2,
        "usdinr_std_50": 0.85,
        
        "vix": 14.5,
        "vix_sma_50": 16.5,
        "vix_std_50": 4.2,
        
        "gold": 1630.0,
        "gold_sma_50": 1625.0,
        "gold_std_50": 45.0,
        
        "us_vix": 17.8,
        "us_vix_sma_50": 18.2,
        "us_vix_std_50": 5.1,
        
        "sp500": 3180.0,
        "sp500_sma_50": 3150.0,
        "sp500_std_50": 120.0,
        
        "dxy": 98.5,
        "dxy_sma_50": 98.2,
        "dxy_std_50": 1.5,
        
        "nifty_bank": 29100.0,
        "nifty_bank_sma_50": 28500.0,
        "nifty_bank_std_50": 2100.0,
        
        "multi_asset_stress": 0.15,  # 15% stress (low)
        "crash_risk_score_v2": 0.12,
        "nifty_drawdown_from_50d_high_pct": -2.1,
        "vix_accel_3d_pct": 5.2,
        "crude_spike_10d_pct": 2.8,
    }
    
    spot = 11200.0
    vix = 14.5
    
    print("="*80)
    print("SCENARIO 2: LOW STRESS (All assets normal)")
    print("="*80)
    print()
    
    eligible = strategy.get_eligible_strategies(spot, vix, market_data)
    
    if not eligible:
        print("CIRCUIT BREAKER ACTIVE — NO MONTHLY TRADE TODAY\n")
        reasons = getattr(strategy, "_circuit_breaker_reasons", [])
        for reason in reasons:
            print(f"  X  {reason}\n")
    else:
        print(f"✓ Circuit breaker NOT triggered")
        print(f"  Eligible strategies: {eligible}")
        print(f"  Multi-asset stress: {market_data['multi_asset_stress']:.0%}")
        print(f"  V2 crash risk: {market_data['crash_risk_score_v2']:.0%}")
    
    print("="*80)
    print()

def test_single_factor_extreme():
    """Test with only one extreme factor (deep correction only)."""
    
    strategy = RegimeAdaptiveStrategy(lots=2, lot_size=65)
    
    # Deep correction but other factors normal
    market_data = {
        "crude": 76.2,
        "crude_sma_50": 75.2,
        "crude_std_50": 6.8,
        
        "usdinr": 74.3,
        "usdinr_sma_50": 74.2,
        "usdinr_std_50": 0.85,
        
        "vix": 18.5,
        "vix_sma_50": 16.5,
        "vix_std_50": 4.2,
        
        "gold": 1630.0,
        "gold_sma_50": 1625.0,
        "gold_std_50": 45.0,
        
        "us_vix": 17.8,
        "us_vix_sma_50": 18.2,
        "us_vix_std_50": 5.1,
        
        "sp500": 3180.0,
        "sp500_sma_50": 3150.0,
        "sp500_std_50": 120.0,
        
        "dxy": 98.5,
        "dxy_sma_50": 98.2,
        "dxy_std_50": 1.5,
        
        "nifty_bank": 29100.0,
        "nifty_bank_sma_50": 28500.0,
        "nifty_bank_std_50": 2100.0,
        
        "multi_asset_stress": 0.25,
        "crash_risk_score_v2": 0.35,
        "nifty_drawdown_from_50d_high_pct": -16.8,  # Deep correction!
        "vix_accel_3d_pct": 12.2,
        "crude_spike_10d_pct": 2.8,
    }
    
    spot = 9800.0
    vix = 18.5
    
    print("="*80)
    print("SCENARIO 3: SINGLE EXTREME FACTOR (Deep correction only)")
    print("="*80)
    print()
    
    eligible = strategy.get_eligible_strategies(spot, vix, market_data)
    
    if not eligible:
        print("CIRCUIT BREAKER ACTIVE — NO MONTHLY TRADE TODAY\n")
        reasons = getattr(strategy, "_circuit_breaker_reasons", [])
        for reason in reasons:
            print(f"  X  {reason}\n")
    else:
        print(f"✓ Circuit breaker NOT triggered")
        print(f"  Eligible strategies: {eligible}")
    
    print("="*80)
    print()

if __name__ == "__main__":
    test_moderate_stress()
    test_low_stress()
    test_single_factor_extreme()
