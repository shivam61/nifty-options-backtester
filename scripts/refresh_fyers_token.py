#!/usr/bin/env python3
"""
Quick script to refresh Fyers access token during market hours.
Run this before using the monitor to ensure fresh prices.
"""

import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv, set_key
load_dotenv()

def test_current_token():
    """Test if the current token works."""
    try:
        from data.fyers_live_data import FyersLiveDataClient
        print("Testing current Fyers token...")
        client = FyersLiveDataClient()
        spot = client.get_nifty_spot_price()
        vix = client.get_india_vix()
        print(f"✓ Token is VALID")
        print(f"  Nifty Spot: ₹{spot:,.2f}")
        print(f"  India VIX: {vix:.2f}")
        return True
    except Exception as e:
        print(f"✗ Token is INVALID or EXPIRED")
        print(f"  Error: {e}")
        return False

def generate_new_token():
    """Guide user to generate a new token."""
    print("\n" + "="*80)
    print("GENERATE NEW FYERS ACCESS TOKEN")
    print("="*80)
    print("\nYou need to generate a new access token. Follow these steps:")
    print("\n1. Run the token generation script:")
    print("   python scripts/generate_fyers_token.py")
    print("\n2. This will:")
    print("   - Open Fyers authorization in your browser")
    print("   - Start a local server on port 8080")
    print("   - Capture the auth code and generate access token")
    print("   - Update your .env file automatically")
    print("\n3. Once complete, run this script again to verify:")
    print("   python scripts/refresh_fyers_token.py")
    print("\n" + "="*80)
    
    # Check if generate_fyers_token.py exists
    token_script = Path(__file__).parent / "generate_fyers_token.py"
    if token_script.exists():
        print("\n✓ Token generation script found at:")
        print(f"  {token_script}")
        
        response = input("\nWould you like to run it now? (y/n): ").strip().lower()
        if response == 'y':
            import subprocess
            print("\nLaunching token generation...")
            subprocess.run([sys.executable, str(token_script)])
            print("\nToken generation complete. Testing new token...")
            return test_current_token()
    else:
        print(f"\n⚠ Token generation script not found at: {token_script}")
        print("You'll need to manually generate the token via Fyers API.")
    
    return False

def main():
    print("="*80)
    print("FYERS TOKEN CHECKER & REFRESHER")
    print("="*80)
    print()
    
    # Check .env file
    env_file = Path(__file__).parent.parent / ".env"
    if not env_file.exists():
        print(f"✗ .env file not found at: {env_file}")
        print("  Create a .env file with:")
        print("  FYERS_CLIENT_ID=your_app_id")
        print("  FYERS_SECRET_KEY=your_secret_key")
        print("  FYERS_REDIRECT_URI=http://127.0.0.1:8080")
        print("  FYERS_ACCESS_TOKEN=your_access_token")
        return
    
    print(f"✓ Found .env file at: {env_file}\n")
    
    # Test current token
    if test_current_token():
        print("\n✓ Your Fyers token is working fine!")
        print("  You can run monitor mode to get live prices:")
        print("  python main.py --mode monitor")
    else:
        print("\n✗ Your Fyers token needs to be refreshed.")
        generate_new_token()

if __name__ == "__main__":
    main()
