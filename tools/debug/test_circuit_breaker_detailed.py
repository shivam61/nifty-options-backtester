#!/usr/bin/env python3
"""
Test script to demonstrate the enhanced circuit breaker output.
Shows how multi-asset stress details are displayed.
"""

from datetime import date
from strategies.multi_strategy import RegimeAdaptiveStrategy

def test_circuit_breaker_output():
    """Simulate a circuit breaker trigger with multi-asset stress."""
    
    # Create a strategy instance
    strategy = RegimeAdaptiveStrategy(lots=2, lot_size=65)
    
    # Simulate market data during a stress event (e.g., March 2020 COVID crash)
    # VIX spiking, USD/INR surging, Crude collapsing, markets down
    market_data = {
        # Price levels
        "crude": 25.5,              # Crude collapsed (normal ~$70)
        "crude_sma_50": 62.3,       # 50-day average
        "crude_std_50": 8.5,        # 50-day std dev
        
        "usdinr": 76.8,             # INR weakened (normal ~74)
        "usdinr_sma_50": 74.2,
        "usdinr_std_50": 0.85,
        
        "vix": 35.2,                # India VIX spiking (normal ~15)
        "vix_sma_50": 16.5,
        "vix_std_50": 4.2,
        
        "gold": 1750.0,             # Gold rallying (safe haven)
        "gold_sma_50": 1625.0,
        "gold_std_50": 45.0,
        
        "us_vix": 58.3,             # US VIX extreme (normal ~15)
        "us_vix_sma_50": 18.2,
        "us_vix_std_50": 5.1,
        
        "sp500": 2480.0,            # S&P down
        "sp500_sma_50": 3150.0,
        "sp500_std_50": 120.0,
        
        "dxy": 102.5,               # Dollar strong (FII repatriation)
        "dxy_sma_50": 98.2,
        "dxy_std_50": 1.5,
        
        "nifty_bank": 18500.0,      # Bank Nifty crushed
        "nifty_bank_sma_50": 28500.0,
        "nifty_bank_std_50": 2100.0,
        
        # Composite stress indicators
        "multi_asset_stress": 1.13,  # 113% stress
        "crash_risk_score_v2": 0.72,
        "nifty_drawdown_from_50d_high_pct": -28.5,
        "vix_accel_3d_pct": 85.2,
        "crude_spike_10d_pct": -35.8,
    }
    
    spot = 9500.0  # Nifty spot (down from ~11,000)
    vix = 35.2
    
    # Test the circuit breaker
    print("="*80)
    print("CIRCUIT BREAKER TEST — Simulated March 2020 COVID Crash Conditions")
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
    
    # Calculate Z-scores manually to show breakdown
    print("Asset Stress Breakdown (Z-scores):")
    print("-" * 80)
    assets = [
        ("Crude Oil", market_data["crude"], market_data["crude_sma_50"], market_data["crude_std_50"]),
        ("USD/INR", market_data["usdinr"], market_data["usdinr_sma_50"], market_data["usdinr_std_50"]),
        ("India VIX", market_data["vix"], market_data["vix_sma_50"], market_data["vix_std_50"]),
        ("Gold", market_data["gold"], market_data["gold_sma_50"], market_data["gold_std_50"]),
        ("US VIX", market_data["us_vix"], market_data["us_vix_sma_50"], market_data["us_vix_std_50"]),
        ("S&P 500", market_data["sp500"], market_data["sp500_sma_50"], market_data["sp500_std_50"]),
        ("Dollar Index", market_data["dxy"], market_data["dxy_sma_50"], market_data["dxy_std_50"]),
        ("Bank Nifty", market_data["nifty_bank"], market_data["nifty_bank_sma_50"], market_data["nifty_bank_std_50"]),
    ]
    
    stressed_count = 0
    for name, current, mean_50, std_50 in assets:
        z_score = (current - mean_50) / std_50
        stressed = abs(z_score) > 2.0
        status = "🔴 STRESSED" if stressed else "🟢 Normal"
        if stressed:
            stressed_count += 1
        print(f"  {status:15} {name:15} Z={z_score:+.2f}σ  (current={current:.1f}, 50d avg={mean_50:.1f})")
    
    print("-" * 80)
    print(f"Total assets stressed (|Z| > 2.0σ): {stressed_count} / {len(assets)}")
    print(f"Composite multi-asset stress score: {market_data['multi_asset_stress']:.0%}")
    print()

if __name__ == "__main__":
    test_circuit_breaker_output()
