"""Gmail OAuth plumbing for the email tools (delphi/tools/email_tools.py) and
the daily summary (delphi/daily_summary.py) - kept separate from the tool
definitions so the two responsibilities (authing to Gmail vs. what Delphi can
do with it) don't tangle.

Disabled by default: enable with DELPHI_ENABLE_EMAIL=1 plus
GOOGLE_GMAIL_CREDENTIALS pointing at a Google Cloud "Desktop app" OAuth
client's downloaded credentials.json, the optional dependency
(`pip install -e .[gmail]`), and a one-time `delphi auth gmail` to grant
access. See README.md "Email (Gmail)" for details.

Scope is gmail.modify (read + label + archive) rather than a broader scope -
this build never calls the trash/send endpoints gmail.modify technically also
permits, by design (see README.md).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from delphi import secrets

_ENABLE_ENV_VAR = "DELPHI_ENABLE_EMAIL"
_CREDENTIALS_ENV_VAR = "GOOGLE_GMAIL_CREDENTIALS"
_TOKEN_SECRET_NAME = "GMAIL_OAUTH_TOKEN"
SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


class GmailUnavailable(Exception):
    """Raised when Gmail can't be used right now (disabled, not installed, no
    client credentials configured, no stored token, or auth/refresh failed) -
    always carries a human-readable reason."""


def is_enabled() -> bool:
    return os.environ.get(_ENABLE_ENV_VAR) == "1"


def _credentials_path() -> Path | None:
    raw = os.environ.get(_CREDENTIALS_ENV_VAR)
    return Path(raw) if raw else None


def get_client():
    """Return an authorized Gmail API client, refreshing the stored token if
    it's expired (no browser involved - only run_interactive_auth_flow ever
    opens one). Raises GmailUnavailable at the first unmet precondition."""
    if not is_enabled():
        raise GmailUnavailable(f"Set {_ENABLE_ENV_VAR}=1 to enable Gmail.")

    creds_path = _credentials_path()
    if not creds_path or not creds_path.is_file():
        raise GmailUnavailable(
            f"{_CREDENTIALS_ENV_VAR} must point at a Google OAuth client "
            "credentials.json file - see README.md 'Email (Gmail)'."
        )

    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError as e:
        raise GmailUnavailable(
            f"Missing optional dependency ({e}). Run `pip install -e .[gmail]`."
        ) from e

    token_json = secrets.get_secret(_TOKEN_SECRET_NAME)
    if not token_json:
        raise GmailUnavailable("No Gmail access granted yet - run `delphi auth gmail` first.")

    try:
        creds = Credentials.from_authorized_user_info(json.loads(token_json), SCOPES)
    except (ValueError, KeyError, json.JSONDecodeError) as e:
        raise GmailUnavailable(
            f"Stored Gmail token is invalid ({e}) - run `delphi auth gmail` to re-authorize."
        ) from e

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception as e:
            raise GmailUnavailable(
                f"Gmail token refresh failed: {e}. Run `delphi auth gmail` to re-authorize."
            ) from e
        secrets.set_secret(_TOKEN_SECRET_NAME, creds.to_json())

    return build("gmail", "v1", credentials=creds)


def ensure_ready() -> None:
    """Raise GmailUnavailable with a clear reason if Gmail can't be used right
    now. Call this before doing any real work so a broken setup degrades
    cleanly instead of failing mid-operation."""
    get_client()


def run_interactive_auth_flow() -> None:
    """One-time interactive consent flow: opens a browser for the user to
    grant access, then stores the resulting token in the OS keychain. The
    only place in this module that does browser-based auth - never call this
    from a background thread. Invoked by `delphi auth gmail`."""
    if not is_enabled():
        raise GmailUnavailable(f"Set {_ENABLE_ENV_VAR}=1 to enable Gmail.")

    creds_path = _credentials_path()
    if not creds_path or not creds_path.is_file():
        raise GmailUnavailable(
            f"{_CREDENTIALS_ENV_VAR} must point at a Google OAuth client "
            "credentials.json file - see README.md 'Email (Gmail)'."
        )

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as e:
        raise GmailUnavailable(
            f"Missing optional dependency ({e}). Run `pip install -e .[gmail]`."
        ) from e

    flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
    creds = flow.run_local_server(port=0)
    secrets.set_secret(_TOKEN_SECRET_NAME, creds.to_json())
