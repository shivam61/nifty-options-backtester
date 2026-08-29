"""Load and manage Fyers API credentials from local environment."""

import os
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


def load_fyers_credentials():
    """
    Load Fyers API credentials from .env.local or environment variables.

    Returns:
        tuple: (client_id, api_secret) or (None, None) if not found
    """

    # Check .env.local first (development)
    env_file = Path(__file__).parent.parent / ".env.local"

    if env_file.exists():
        try:
            # Try to load from .env.local using python-dotenv
            from dotenv import load_dotenv
            load_dotenv(env_file)

            client_id = os.getenv("FYERS_CLIENT_ID")
            api_secret = os.getenv("FYERS_API_SECRET")

            if client_id and api_secret:
                logger.info("✅ Loaded Fyers credentials from .env.local")
                return client_id, api_secret
            else:
                logger.warning("❌ .env.local found but credentials incomplete")
        except ImportError:
            # python-dotenv not installed, fall back to manual parsing
            logger.debug("python-dotenv not installed, parsing .env.local manually")
            creds = _parse_env_file(env_file)
            if creds.get("FYERS_CLIENT_ID") and creds.get("FYERS_API_SECRET"):
                logger.info("✅ Loaded Fyers credentials from .env.local")
                return creds["FYERS_CLIENT_ID"], creds["FYERS_API_SECRET"]

    # Check environment variables
    client_id = os.getenv("FYERS_CLIENT_ID")
    api_secret = os.getenv("FYERS_API_SECRET")

    if client_id and api_secret:
        logger.info("✅ Loaded Fyers credentials from environment variables")
        return client_id, api_secret

    logger.warning("❌ No Fyers credentials found in .env.local or environment")
    return None, None


def _parse_env_file(env_file):
    """Manually parse .env file (fallback if python-dotenv not installed)."""
    creds = {}
    try:
        with open(env_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    creds[key.strip()] = value.strip()
    except Exception as e:
        logger.error(f"Failed to parse .env file: {e}")
    return creds


def get_fyers_access_token():
    """Get stored Fyers access token (if available)."""
    token = os.getenv("FYERS_ACCESS_TOKEN")
    if token:
        logger.info("✅ Using stored Fyers access token")
        return token
    return None


def save_fyers_access_token(token):
    """Save Fyers access token to .env.local (for next session)."""
    env_file = Path(__file__).parent.parent / ".env.local"

    try:
        # Read existing content
        content = {}
        if env_file.exists():
            content = _parse_env_file(env_file)

        # Update token
        content["FYERS_ACCESS_TOKEN"] = token

        # Write back
        with open(env_file, 'w') as f:
            for key, value in content.items():
                f.write(f"{key}={value}\n")

        logger.info("✅ Saved Fyers access token to .env.local")
        return True
    except Exception as e:
        logger.error(f"Failed to save access token: {e}")
        return False
