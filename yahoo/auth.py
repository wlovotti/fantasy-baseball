"""Yahoo Fantasy API OAuth 2.0 authentication."""

import json
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

TOKEN_FILE = Path("oauth2.json")


def get_yahoo_auth():
    """Get an authenticated Yahoo OAuth2 session.

    On first run, opens a browser for the user to authorize the app and
    writes the token to oauth2.json. On subsequent runs, loads the saved
    token and refreshes it automatically.

    Returns:
        An OAuth2 object from yahoo_fantasy_api suitable for API calls.

    Raises:
        ValueError: If Yahoo credentials are not configured in .env.
    """
    try:
        from yahoo_oauth import OAuth2
    except ImportError:
        raise ImportError(
            "yahoo-oauth is required. Install it with: pip install yahoo-oauth"
        )

    client_id = os.getenv("YAHOO_CLIENT_ID")
    client_secret = os.getenv("YAHOO_CLIENT_SECRET")

    if not client_id or not client_secret:
        raise ValueError(
            "YAHOO_CLIENT_ID and YAHOO_CLIENT_SECRET must be set in .env. "
            "See .env.example for details."
        )

    # yahoo_oauth expects a JSON file with consumer_key/consumer_secret
    # to persist tokens across runs via from_file
    if not TOKEN_FILE.exists():
        TOKEN_FILE.write_text(json.dumps({
            "consumer_key": client_id,
            "consumer_secret": client_secret,
        }))

    oauth = OAuth2(None, None, from_file=str(TOKEN_FILE))

    if not oauth.token_is_valid():
        oauth.refresh_access_token()

    return oauth
