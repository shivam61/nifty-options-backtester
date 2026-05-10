"""
Fyers Token Status Checker
Quickly check if your Fyers access token is valid and working.
"""

import os
from pathlib import Path
from dotenv import load_dotenv
from fyers_apiv3 import fyersModel
from datetime import datetime

# Load environment variables
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)


def check_token_status():
    """Check if the Fyers access token is valid."""
    
    print("=" * 70)
    print("Fyers Token Status Checker")
    print("=" * 70)
    
    # Check if credentials exist
    client_id = os.getenv('FYERS_CLIENT_ID')
    access_token = os.getenv('FYERS_ACCESS_TOKEN')
    
    if not client_id:
        print("\n❌ FYERS_CLIENT_ID not found in .env file")
        return False
    
    if not access_token:
        print("\n❌ FYERS_ACCESS_TOKEN not found in .env file")
        print("\n💡 Run: python scripts/generate_fyers_token.py")
        return False
    
    print(f"\n✓ Client ID found: {client_id}")
    print(f"✓ Access token found: {access_token[:20]}...{access_token[-10:]}")
    
    # Try to connect
    print("\n🔄 Testing API connection...")
    
    try:
        fyers = fyersModel.FyersModel(
            client_id=client_id,
            token=access_token,
            log_path=""
        )
        
        # Test with a simple quote request
        test_data = {"symbols": "NSE:NIFTY50-INDEX"}
        response = fyers.quotes(data=test_data)
        
        if response.get('s') == 'ok':
            print("✅ Token is VALID and working!")
            
            # Get some data to confirm
            if 'd' in response and len(response['d']) > 0:
                quote = response['d'][0]['v']
                ltp = quote.get('lp', 'N/A')
                print(f"\n📊 Sample Data Retrieved:")
                print(f"   NIFTY LTP: ₹{ltp:,.2f}")
                print(f"   Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            
            print("\n✅ You're ready to use the Fyers API!")
            print("\n💡 Try running: python data/fyers_live_data.py")
            return True
        else:
            error_code = response.get('code', 'unknown')
            error_msg = response.get('message', 'Unknown error')
            
            print(f"\n❌ Token is INVALID")
            print(f"   Error Code: {error_code}")
            print(f"   Error Message: {error_msg}")
            
            if error_code == -15:
                print("\n💡 Your token has expired or is invalid.")
                print("   Run: python scripts/generate_fyers_token.py")
            
            return False
            
    except Exception as e:
        print(f"\n❌ Connection failed: {str(e)}")
        print("\n💡 Possible issues:")
        print("   1. Internet connection")
        print("   2. Invalid token")
        print("   3. Fyers API downtime")
        return False


if __name__ == "__main__":
    success = check_token_status()
    exit(0 if success else 1)
