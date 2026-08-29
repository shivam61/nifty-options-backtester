#!/usr/bin/env python3
"""
Interactive Fyers OAuth Token Setup

This script guides you through getting an OAuth token for live Fyers data access.

Steps:
  1. Generate authorization URL
  2. Authorize in browser
  3. Copy authorization code
  4. Exchange for access token
  5. Verify live data access

Usage:
    python3 scripts/get_fyers_oauth_token.py
"""

import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

def main():
    from fyers_apiv3 import fyersModel
    from data.credentials import load_fyers_credentials, save_fyers_access_token

    print("=" * 80)
    print("FYERS OAUTH TOKEN SETUP")
    print("=" * 80)

    # Step 1: Load credentials
    print("\n1️⃣  Loading Fyers credentials...")
    client_id, api_secret = load_fyers_credentials()

    if not client_id:
        print("❌ No credentials found in .env.local")
        print("   Please set up credentials first (see docs/FYERS_CREDENTIAL_SETUP.md)")
        return False

    print(f"✅ Client ID: {client_id}")

    # Step 2: Create client for auth flow
    print("\n2️⃣  Creating Fyers client for authorization...")
    try:
        client = fyersModel.FyersModel(
            is_async=False,
            client_id=client_id,
            log_level="ERROR"
        )
        print("✅ Client ready for OAuth flow")
    except Exception as e:
        print(f"❌ Failed to create client: {e}")
        return False

    # Step 3: Get authorization URL
    print("\n3️⃣  Generating authorization URL...")
    try:
        auth_url = client.get_auth_url()
        print("✅ Authorization URL generated")
        print("\n" + "=" * 80)
        print("📋 AUTHORIZATION URL (Copy and open in browser):")
        print("=" * 80)
        print(f"\n{auth_url}\n")
        print("=" * 80)

        # Try to open in browser
        print("\n🌐 Attempting to open in browser...")
        try:
            webbrowser.open(auth_url)
            print("✅ Browser opened (if not, copy URL manually)")
        except:
            print("⚠️  Could not open browser - copy URL above manually")

    except Exception as e:
        print(f"❌ Failed to generate auth URL: {e}")
        return False

    # Step 4: Get authorization code
    print("\n4️⃣  Waiting for authorization...")
    print("\n📋 Steps:")
    print("   1. Log in with your Fyers account")
    print("   2. Click 'Authorize' or 'Allow'")
    print("   3. You'll be redirected to localhost")
    print("   4. Copy the 'code' value from the URL")
    print("\n   Example URL: http://localhost:3000?code=ABC123DEF456...")
    print("   Copy: ABC123DEF456...\n")

    auth_code = input("📋 Paste the authorization code here: ").strip()

    if not auth_code:
        print("❌ No authorization code provided")
        return False

    print("\n✅ Auth code received (processing...)")

    # Step 5: Exchange code for token
    print("\n5️⃣  Exchanging authorization code for access token...")
    try:
        # Set token with auth code (exchanges it for actual token)
        client.set_token(auth_code)
        access_token = client.token

        print("✅ Access token received!")
        print(f"   Token: {access_token[:50]}...")

        # Save token
        print("\n6️⃣  Saving token to .env.local...")
        if save_fyers_access_token(access_token):
            print("✅ Token saved successfully!")
        else:
            print("⚠️  Failed to save automatically")
            print(f"   Manually add to .env.local:")
            print(f"   FYERS_ACCESS_TOKEN={access_token}")

    except Exception as e:
        print(f"❌ Failed to exchange code for token: {e}")
        print("\n⚠️  Troubleshooting:")
        print("   - Make sure you copied the entire code value")
        print("   - Don't include 'code=' prefix")
        print("   - Try again if more than 10 minutes have passed")
        print("   - Check Fyers account is active")
        return False

    # Step 6: Verify token works
    print("\n7️⃣  Verifying live data access...")
    try:
        # Create new client with token
        client_with_token = fyersModel.FyersModel(
            is_async=False,
            client_id=client_id,
            token=access_token,
            log_level="ERROR"
        )

        # Test spot price
        result = client_with_token.quotes({"symbols": ["NSE:NIFTY50"]})

        if result.get('s') == 'ok':
            data = result['d']['NSE:NIFTY50']
            print("✅ LIVE DATA ACCESS VERIFIED!")
            print(f"   Live Nifty Price: ₹{data.get('ltp', 'N/A')}")
            print(f"   Bid: {data.get('bid', 'N/A')}, Ask: {data.get('ask', 'N/A')}")
        elif result.get('code') == -15:
            print("⚠️  Token works but market data not available")
            print("   Possible reasons:")
            print("   - Market is closed (try during 9:15 AM - 3:30 PM IST)")
            print("   - Fyers account not fully set up")
        else:
            print(f"⚠️  Unexpected response: {result.get('message', 'Unknown')}")

    except Exception as e:
        print(f"⚠️  Could not verify live data: {e}")
        print("   But token should still work (try restarting API server)")

    # Summary
    print("\n" + "=" * 80)
    print("✅ OAUTH SETUP COMPLETE!")
    print("=" * 80)
    print("""
Next Steps:

1. Restart API Server:
   uvicorn api.server:app --port 8000

2. Test Live Data:
   curl http://localhost:8000/signal | jq '.spot, .vix'

3. Start Paper Trading:
   python main.py --mode paper-trading --journal-id phase1-live

Your API now has access to:
   ✅ Live Nifty spot prices
   ✅ Live India VIX
   ✅ Live option chains
   ✅ Real bid-ask spreads
   ✅ All market data

Questions? See docs/FYERS_OAUTH_TOKEN_SETUP.md
""")

    return True


if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n❌ Setup cancelled by user")
        sys.exit(1)
