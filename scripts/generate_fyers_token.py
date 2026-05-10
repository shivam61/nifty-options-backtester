"""
Fyers Access Token Generator
Generates a new access token for Fyers API v3 using OAuth flow.

Usage:
    python scripts/generate_fyers_token.py
    
This will:
1. Generate an authorization URL
2. Open it in your browser
3. After you authorize, it will redirect to the redirect_uri with an auth_code
4. You need to copy the auth_code from the URL and paste it back
5. Script will generate access_token and save it to .env
"""

import os
import sys
from pathlib import Path
import webbrowser
from fyers_apiv3 import fyersModel
from dotenv import load_dotenv, set_key

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

# Load environment variables
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)


def generate_access_token():
    """Generate Fyers access token using OAuth flow."""
    
    print("=" * 70)
    print("Fyers API - Access Token Generator")
    print("=" * 70)
    
    # Get credentials from .env
    client_id = os.getenv('FYERS_CLIENT_ID')
    secret_key = os.getenv('FYERS_SECRET_KEY')
    redirect_uri = os.getenv('FYERS_REDIRECT_URI', 'http://127.0.0.1:8080')
    
    if not client_id:
        print("\n✗ FYERS_CLIENT_ID not found in .env file")
        print("\nPlease add the following to your .env file:")
        print("FYERS_CLIENT_ID=W4JMYLVR9Y-100")
        print("FYERS_SECRET_KEY=4WAAVZ1UW0")
        print("FYERS_REDIRECT_URI=http://127.0.0.1:8080")
        return
    
    if not secret_key:
        print("\n✗ FYERS_SECRET_KEY not found in .env file")
        print("\nPlease add FYERS_SECRET_KEY to your .env file")
        return
    
    print(f"\n✓ Client ID: {client_id}")
    print(f"✓ Redirect URI: {redirect_uri}")
    
    # Step 1: Create session and generate auth code URL
    print("\nStep 1: Generating authorization URL...")
    
    session = fyersModel.SessionModel(
        client_id=client_id,
        secret_key=secret_key,
        redirect_uri=redirect_uri,
        response_type="code",
        grant_type="authorization_code"
    )
    
    auth_url = session.generate_authcode()
    
    print("\n" + "=" * 70)
    print("AUTHORIZATION URL:")
    print("=" * 70)
    print(auth_url)
    print("=" * 70)
    
    # Open in browser
    print("\nOpening authorization URL in browser...")
    try:
        webbrowser.open(auth_url)
    except:
        print("Could not open browser automatically. Please copy the URL above.")
    
    # Step 2: Get auth code from user
    print("\n" + "=" * 70)
    print("INSTRUCTIONS:")
    print("=" * 70)
    print("1. Login to Fyers in the browser window that opened")
    print("2. Authorize the application")
    print("3. You will be redirected to: http://127.0.0.1:8080/?auth_code=...")
    print("4. Copy the FULL URL from the browser address bar")
    print("   OR just copy the 'auth_code' parameter value")
    print("=" * 70)
    
    redirected_url = input("\nPaste the redirected URL or auth_code here: ").strip()
    
    # Extract auth_code from URL if full URL was pasted
    if 'auth_code=' in redirected_url:
        auth_code = redirected_url.split('auth_code=')[1].split('&')[0]
    else:
        auth_code = redirected_url
    
    print(f"\n✓ Auth code extracted: {auth_code[:20]}...")
    
    # Step 3: Generate access token
    print("\nStep 3: Generating access token...")
    
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
                print(f"\n⚠ Token expires in: {response['expires_in']} seconds")
                print("   You may need to regenerate it before expiry.")
            
            print("\n" + "=" * 70)
            print("SUCCESS! You can now use the Fyers API.")
            print("=" * 70)
            print("\nNext steps:")
            print("1. Run: python data/fyers_live_data.py")
            print("2. This will validate your connection and fetch live data")
            
        else:
            print("\n✗ Failed to generate access token")
            print(f"Response: {response}")
            
    except Exception as e:
        print(f"\n✗ Error generating access token: {str(e)}")
        print("\nPlease check:")
        print("1. The auth_code is correct")
        print("2. The auth_code hasn't expired (they're valid for a short time)")
        print("3. Your Client ID and Secret Key are correct")


if __name__ == "__main__":
    generate_access_token()
