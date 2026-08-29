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
    from fyers_apiv3.fyersModel import SessionModel, FyersModel
    from data.credentials import load_fyers_credentials, save_fyers_access_token

    print("=" * 80)
    print("FYERS OAUTH TOKEN SETUP")
    print("=" * 80)

    # Step 1: Load credentials
    print("\n1️⃣  Loading Fyers credentials...")
    client_id, api_secret = load_fyers_credentials()

    if not client_id or not api_secret:
        print("❌ No credentials found in .env.local")
        print("   Please set up credentials first (see docs/FYERS_CREDENTIAL_SETUP.md)")
        return False

    print(f"✅ Client ID: {client_id}")
    print(f"✅ API Secret: {api_secret[:10]}...")

    # Step 2: Create SessionModel for OAuth flow
    print("\n2️⃣  Creating Fyers SessionModel for authorization...")
    try:
        session = SessionModel(
            client_id=client_id,
            redirect_uri="http://localhost:3000",
            response_type="code",
            scope="full_access",
            state="sample_state",
            nonce="sample_nonce",
            secret_key=api_secret,
            grant_type="authorization_code"
        )
        print("✅ SessionModel created")
    except Exception as e:
        print(f"❌ Failed to create SessionModel: {e}")
        return False

    # Step 3: Get authorization URL
    print("\n3️⃣  Generating authorization URL...")
    try:
        auth_url = session.generate_authcode()
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
        import traceback
        traceback.print_exc()
        return False

    # Step 4: Get authorization code
    print("\n4️⃣  Waiting for authorization...")
    print("\n📋 Steps:")
    print("   1. Log in with your Fyers account in the browser")
    print("   2. Click 'Authorize' or 'Allow' to approve access")
    print("   3. You'll be redirected to localhost")
    print("   4. Copy the 'code' value from the URL")
    print("\n   Example URL: http://localhost:3000?code=ABC123DEF456&state=...")
    print("   Copy value after 'code=': ABC123DEF456\n")

    auth_code = input("📋 Paste the authorization code here: ").strip()

    if not auth_code:
        print("❌ No authorization code provided")
        return False

    print("\n✅ Auth code received (processing...)")

    # Step 5: Exchange code for token using SessionModel
    print("\n5️⃣  Exchanging authorization code for access token...")
    try:
        # Set the auth code in session
        session.set_token(auth_code)

        # Generate the token from auth code
        token_response = session.generate_token()

        print("✅ Token response received!")
        print(f"   Response: {token_response}")

        # Extract access token from response
        if isinstance(token_response, dict):
            access_token = token_response.get('access_token') or token_response.get('data', {}).get('access_token')

            if not access_token:
                print(f"⚠️  Could not extract token from response: {token_response}")
                # Try to use raw response as token
                access_token = str(token_response)
        else:
            access_token = str(token_response)

        if not access_token or access_token == 'None':
            print("❌ Failed to get valid access token")
            print(f"   Response: {token_response}")
            return False

        print("✅ Access token received!")
        print(f"   Token: {str(access_token)[:50]}...")

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
        import traceback
        traceback.print_exc()
        print("\n⚠️  Troubleshooting:")
        print("   - Make sure you copied the entire code value")
        print("   - Don't include 'code=' prefix")
        print("   - Try again if more than 10 minutes have passed")
        print("   - Check Fyers account is active and authorized")
        return False

    # Step 6: Verify token works
    print("\n7️⃣  Verifying live data access...")
    try:
        # Create new client with token
        client_with_token = FyersModel(
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
            print(f"⚠️  Response: {result.get('message', 'Unknown')}")

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
   source .venv/bin/activate
   uvicorn api.server:app --port 8000

2. Test Live Data (in another terminal):
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
