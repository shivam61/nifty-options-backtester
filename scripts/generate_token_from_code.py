"""
Generate Fyers Access Token from Auth Code
Use this script when you already have an auth code.
"""

import os
import sys
from pathlib import Path
from fyers_apiv3 import fyersModel
from dotenv import load_dotenv, set_key

# Load environment variables
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)


def generate_token_from_auth_code(auth_code: str):
    """Generate access token from auth code."""
    
    print("=" * 70)
    print("Fyers API - Generate Token from Auth Code")
    print("=" * 70)
    
    client_id = os.getenv('FYERS_CLIENT_ID')
    secret_key = os.getenv('FYERS_SECRET_KEY')
    redirect_uri = os.getenv('FYERS_REDIRECT_URI', 'http://127.0.0.1:8080')
    
    if not client_id or not secret_key:
        print("\n✗ Missing credentials in .env file")
        return False
    
    print(f"\n✓ Client ID: {client_id}")
    print(f"✓ Secret Key: {secret_key[:4]}...{secret_key[-4:]}")
    print(f"✓ Auth Code: {auth_code[:20]}...")
    
    try:
        # Create session
        session = fyersModel.SessionModel(
            client_id=client_id,
            secret_key=secret_key,
            redirect_uri=redirect_uri,
            response_type="code",
            grant_type="authorization_code"
        )
        
        # Set auth code and generate token
        print("\n🔄 Generating access token...")
        session.set_token(auth_code)
        response = session.generate_token()
        
        if 'access_token' in response:
            access_token = response['access_token']
            
            print("\n✅ Access token generated successfully!")
            print(f"\nAccess Token: {access_token[:50]}...")
            
            # Save to .env
            set_key(env_path, 'FYERS_ACCESS_TOKEN', access_token)
            print(f"\n✓ Token saved to: {env_path}")
            
            # Show expiry info
            if 'expires_in' in response:
                expires_in_days = response['expires_in'] / (24 * 3600)
                print(f"\n⏰ Token expires in: {response['expires_in']} seconds (~{expires_in_days:.1f} days)")
            
            print("\n" + "=" * 70)
            print("SUCCESS! You can now use the Fyers API.")
            print("=" * 70)
            print("\nNext steps:")
            print("1. Run: python scripts/check_fyers_token.py")
            print("2. Run: python data/fyers_live_data.py")
            
            return True
        else:
            print("\n✗ Failed to generate token")
            print(f"Response: {response}")
            return False
            
    except Exception as e:
        print(f"\n✗ Error: {str(e)}")
        return False


if __name__ == "__main__":
    # Auth code from the redirect URL
    auth_code = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJhcHBfaWQiOiJXNEpNWUxWUjlZIiwidXVpZCI6ImE3OGQwNzI4OWMwODQzNWM4ZmJhZTIwY2I5NWQwYjA1IiwiaXBBZGRyIjoiIiwibm9uY2UiOiIiLCJzY29wZSI6IiIsImRpc3BsYXlfbmFtZSI6IlhTODMwMjQiLCJvbXMiOiJLMSIsImhzbV9rZXkiOiI5Y2M2OWMyN2ZiNmNjOWE0NWNkZjkwMGQ1N2RkNTBlZTlmNzI5MzdmMjE1YzA2MDdhMzk4OTVhZiIsImlzRGRwaUVuYWJsZWQiOiJOIiwiaXNNdGZFbmFibGVkIjoiTiIsImF1ZCI6IltcImQ6MVwiXSIsImV4cCI6MTc3NTg2MzA2OCwiaWF0IjoxNzc1ODMzMDY4LCJpc3MiOiJhcGkubG9naW4uZnllcnMuaW4iLCJuYmYiOjE3NzU4MzMwNjgsInN1YiI6ImF1dGhfY29kZSJ9.6WWmvYaDC2_29ZVirA98fai0yUtwRIWlyHR0LqjZ95w"
    
    success = generate_token_from_auth_code(auth_code)
    exit(0 if success else 1)
