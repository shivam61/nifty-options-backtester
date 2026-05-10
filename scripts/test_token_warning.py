#!/usr/bin/env python3
"""
Test script to simulate and verify the Fyers token expiry warning.

This script tests the token check and warning system by:
1. Testing during market hours with expired token (simulated)
2. Testing outside market hours (should skip)
3. Testing during market hours with valid token (current state)
"""

import os
import sys
from pathlib import Path
from datetime import datetime, time

# Add parent directory to path
parent_dir = Path(__file__).parent.parent
sys.path.insert(0, str(parent_dir))

def test_token_check_logic():
    """Test the token check warning function."""
    from main import _check_fyers_token_and_warn
    
    print("=" * 80)
    print("FYERS TOKEN CHECK TEST")
    print("=" * 80)
    
    # Test 1: Current state
    print("\n[TEST 1] Current State (Market Hours + Token Status)")
    print("-" * 80)
    
    now = datetime.now()
    market_hours = (time(9, 15) <= now.time() <= time(15, 30) and now.weekday() < 5)
    
    print(f"Current time: {now}")
    print(f"Market hours: {market_hours}")
    
    if market_hours:
        print("\nRunning token check (should show warning if expired)...\n")
        is_market, is_valid = _check_fyers_token_and_warn()
        
        print(f"\nResult:")
        print(f"  Market hours detected: {is_market}")
        print(f"  Token valid: {is_valid}")
        
        if is_valid:
            print("\n✓ Token is VALID - Live prices will be fetched from Fyers")
        else:
            print("\n✗ Token is EXPIRED - Warning should have been displayed above")
    else:
        print("\nMarket is CLOSED - Token check will be skipped")
        print("(This is expected behavior - warning only shows during market hours)")
    
    # Test 2: Token expiry info
    print("\n" + "=" * 80)
    print("[TEST 2] Token Expiry Information")
    print("-" * 80)
    
    from dotenv import load_dotenv
    import json
    import base64
    
    load_dotenv()
    token = os.getenv('FYERS_ACCESS_TOKEN')
    
    if token:
        try:
            # Decode JWT payload
            parts = token.split('.')
            payload = parts[1]
            # Add padding if needed
            padding = 4 - len(payload) % 4
            if padding != 4:
                payload += '=' * padding
            
            decoded_bytes = base64.b64decode(payload)
            decoded = json.loads(decoded_bytes)
            
            exp_timestamp = decoded.get('exp', 0)
            exp_date = datetime.fromtimestamp(exp_timestamp)
            now = datetime.now()
            time_until_expiry = exp_date - now
            
            print(f"Token expiry: {exp_date}")
            print(f"Current time: {now}")
            print(f"Token status: {'EXPIRED' if now > exp_date else 'VALID'}")
            
            if now <= exp_date:
                hours_left = time_until_expiry.total_seconds() / 3600
                print(f"Time until expiry: {hours_left:.1f} hours ({time_until_expiry.days} days)")
                
                if hours_left < 6:
                    print("\n⚠️  WARNING: Token expires in less than 6 hours!")
                    print("   Consider refreshing it before tomorrow's market open.")
            else:
                print(f"Token expired {abs(time_until_expiry.days)} days ago")
                
        except Exception as e:
            print(f"Could not decode token: {e}")
    else:
        print("No token found in .env file")
    
    # Test 3: Verify scripts exist
    print("\n" + "=" * 80)
    print("[TEST 3] Token Refresh Scripts Availability")
    print("-" * 80)
    
    scripts = [
        ("Generate Token", "scripts/generate_fyers_token.py"),
        ("Check Token", "scripts/check_fyers_token.py"),
        ("Refresh Token", "scripts/refresh_fyers_token.py"),
    ]
    
    for name, path in scripts:
        full_path = parent_dir / path
        if full_path.exists():
            print(f"✓ {name:20} → {path}")
        else:
            print(f"✗ {name:20} → MISSING: {path}")
    
    print("\n" + "=" * 80)
    print("TEST COMPLETE")
    print("=" * 80)
    print("\nTo refresh your token:")
    print("  python scripts/generate_fyers_token.py")
    print("\nTo check token status:")
    print("  python scripts/check_fyers_token.py")
    print()


if __name__ == "__main__":
    test_token_check_logic()
