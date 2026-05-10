#!/usr/bin/env python3
"""
Complete the Fyers token generation using the provided auth code.
"""

import os
import sys
from pathlib import Path
from fyers_apiv3 import fyersModel
from dotenv import load_dotenv, set_key

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

# Load environment variables
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

# Auth code from the redirect
auth_code = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJhcHBfaWQiOiJXNEpNWUxWUjlZIiwidXVpZCI6IjA3ODE3NjkwMzk4NDQ5Nzg5NmFlOGVmZGVmZjZjZWFhIiwiaXBBZGRyIjoiIiwibm9uY2UiOiIiLCJzY29wZSI6IiIsImRpc3BsYXlfbmFtZSI6IlhTODMwMjQiLCJvbXMiOiJLMSIsImhzbV9rZXkiOiI5Y2M2OWMyN2ZiNmNjOWE0NWNkZjkwMGQ1N2RkNTBlZTlmNzI5MzdmMjE1YzA2MDdhMzk4OTVhZiIsImlzRGRwaUVuYWJsZWQiOiJOIiwiaXNNdGZFbmFibGVkIjoiTiIsImF1ZCI6IltcImQ6MVwiXSIsImV4cCI6MTc3NjA5OTQ5MCwiaWF0IjoxNzc2MDY5NDkwLCJpc3MiOiJhcGkubG9naW4uZnllcnMuaW4iLCJuYmYiOjE3NzYwNjk0OTAsInN1YiI6ImF1dGhfY29kZSJ9.WXcZJF37_N6A9Y9TxLxm1D_z-Z19a18TlrYOidqqU1w"

def generate_token():
    print("=" * 70)
    print("Generating Fyers Access Token from Auth Code")
    print("=" * 70)
    
    # Get credentials from .env
    client_id = os.getenv('FYERS_CLIENT_ID')
    secret_key = os.getenv('FYERS_SECRET_KEY')
    redirect_uri = os.getenv('FYERS_REDIRECT_URI', 'http://127.0.0.1:8080')
    
    if not client_id or not secret_key:
        print("\n✗ Missing credentials in .env file")
        return False
    
    print(f"\n✓ Client ID: {client_id}")
    print(f"✓ Auth code: {auth_code[:30]}...")
    
    # Create session
    session = fyersModel.SessionModel(
        client_id=client_id,
        secret_key=secret_key,
        redirect_uri=redirect_uri,
        response_type="code",
        grant_type="authorization_code"
    )
    
    print("\nGenerating access token...")
    
    try:
        session.set_token(auth_code)
        response = session.generate_token()
        
        if 'access_token' in response:
            access_token = response['access_token']
            
            print("\n✓ Access token generated successfully!")
            print(f"\nAccess Token: {access_token[:50]}...")
            
            # Save to .env file
            set_key(env_path, 'FYERS_ACCESS_TOKEN', access_token)
            
            print(f"\n✓ Access token saved to .env file: {env_path}")
            
            # Show expiry if available
            if 'expires_in' in response:
                expires_in = response['expires_in']
                hours = expires_in / 3600
                print(f"\n⚠ Token expires in: {expires_in} seconds ({hours:.1f} hours)")
            
            print("\n" + "=" * 70)
            print("SUCCESS! Token is now active.")
            print("=" * 70)
            
            # Verify the token works
            print("\nVerifying token...")
            from data.fyers_live_data import FyersLiveDataClient
            try:
                client = FyersLiveDataClient()
                spot = client.get_nifty_spot_price()
                vix = client.get_india_vix()
                print(f"✓ Token verified successfully!")
                print(f"  Nifty Spot: ₹{spot:,.2f}")
                print(f"  India VIX: {vix:.2f}")
                
                print("\n" + "=" * 70)
                print("You can now run: python main.py --mode monitor")
                print("=" * 70)
                return True
            except Exception as e:
                print(f"⚠ Token saved but verification failed: {e}")
                print("  This may be normal if market is closed.")
                return True
        else:
            print("\n✗ Failed to generate access token")
            print(f"Response: {response}")
            return False
            
    except Exception as e:
        print(f"\n✗ Error generating access token: {str(e)}")
        print("\nPossible issues:")
        print("1. Auth code expired (they're valid for ~5 minutes)")
        print("2. Auth code already used")
        print("3. Client ID or Secret Key incorrect")
        return False

if __name__ == "__main__":
    success = generate_token()
    sys.exit(0 if success else 1)
