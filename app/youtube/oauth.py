"""Google OAuth 2.0 PKCE desktop flow for YouTube channel authorization."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import google.oauth2.credentials
import google_auth_oauthlib.flow
import googleapiclient.discovery

from app.database.session import db_session
from app.database.repository import Repository
from app.paths import DATA_DIR
from app.youtube.crypto import encrypt_token, decrypt_token
from app.youtube.quota import record_quota_usage, READ_COST

logger = logging.getLogger(__name__)

YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]

CLIENT_SECRETS_FILE = DATA_DIR / "client_secrets.json"

# In-memory storage for PKCE code_verifier keyed by OAuth state token
_STATE_VERIFIERS: Dict[str, str] = {}
_LATEST_VERIFIER: Optional[str] = None
VERIFIERS_FILE = DATA_DIR / "oauth_state.json"


def _save_verifier(state: str, verifier: str) -> None:
    _STATE_VERIFIERS[state] = verifier
    global _LATEST_VERIFIER
    _LATEST_VERIFIER = verifier
    try:
        # Overwrite entire file with only current state + latest to avoid stale data
        data = {state: verifier, "__latest__": verifier}
        VERIFIERS_FILE.write_text(json.dumps(data), encoding="utf-8")
        logger.info("Saved PKCE verifier for state %s to %s", state, VERIFIERS_FILE)
    except Exception as e:
        logger.warning("Could not persist oauth verifier: %s", e)


def _get_verifier(state: Optional[str]) -> Optional[str]:
    # 1. Check in-memory first
    if state and state in _STATE_VERIFIERS:
        val = _STATE_VERIFIERS.pop(state)
        logger.info("Found PKCE verifier in memory for state %s", state)
        return val

    # 2. Check file
    if VERIFIERS_FILE.exists():
        try:
            data = json.loads(VERIFIERS_FILE.read_text(encoding="utf-8"))
            if state and state in data:
                val = data.pop(state)
                logger.info("Found PKCE verifier in file for state %s", state)
                VERIFIERS_FILE.write_text(json.dumps(data), encoding="utf-8")
                return val
            if "__latest__" in data:
                logger.info("Using __latest__ PKCE verifier as fallback (state=%s not found in file keys: %s)",
                           state, [k for k in data.keys() if k != "__latest__"])
                return data["__latest__"]
        except Exception as e:
            logger.warning("Error reading verifier file: %s", e)

    if _LATEST_VERIFIER:
        logger.info("Using in-memory _LATEST_VERIFIER as final fallback")
    return _LATEST_VERIFIER


def _get_client_config() -> Optional[Dict[str, Any]]:
    """Load OAuth client config from environment variables or client_secrets.json."""
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")

    if client_id and client_secret:
        return {
            "web": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        }

    if CLIENT_SECRETS_FILE.exists():
        try:
            return json.loads(CLIENT_SECRETS_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("Could not read client_secrets.json: %s", e)

    return None


def get_authorization_url(redirect_uri: str = "http://localhost:8000/api/v2/oauth/callback") -> Tuple[str, str]:
    """Generate Google OAuth 2.0 authorization URL and state token."""
    config = _get_client_config()
    if not config:
        raise ValueError(
            "Google OAuth client credentials not found. Configure GOOGLE_CLIENT_ID and "
            "GOOGLE_CLIENT_SECRET environment variables or place client_secrets.json in data/ directory."
        )

    flow = google_auth_oauthlib.flow.Flow.from_client_config(
        client_config=config,
        scopes=YOUTUBE_SCOPES,
        redirect_uri=redirect_uri,
    )

    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )

    if hasattr(flow, "code_verifier") and flow.code_verifier:
        _save_verifier(state, flow.code_verifier)

    return auth_url, state


def exchange_code_for_tokens(
    code: str,
    redirect_uri: str = "http://localhost:8000/api/v2/oauth/callback",
    state: Optional[str] = None,
) -> Dict[str, Any]:
    """Exchange authorization code for tokens, fetch channel profile, and save encrypted credential."""
    config = _get_client_config()
    if not config:
        raise ValueError("OAuth credentials config missing.")

    # Restore matching PKCE code_verifier
    verifier = _get_verifier(state)
    logger.info("Retrieved PKCE verifier for state %s: %s", state, bool(verifier))

    flow = google_auth_oauthlib.flow.Flow.from_client_config(
        client_config=config,
        scopes=YOUTUBE_SCOPES,
        redirect_uri=redirect_uri,
        state=state,
    )
    # Set code_verifier as an attribute — the constructor may not accept it as kwarg
    if verifier:
        flow.code_verifier = verifier

    flow.fetch_token(code=code)
    creds = flow.credentials

    if not creds.refresh_token:
        raise ValueError("No refresh token returned by Google. Re-authorize with prompt=consent.")

    # Fetch channel metadata
    youtube = googleapiclient.discovery.build("youtube", "v3", credentials=creds)
    ch_req = youtube.channels().list(part="snippet,contentDetails", mine=True)
    ch_resp = ch_req.execute()
    record_quota_usage(READ_COST)

    items = ch_resp.get("items", [])
    if not items:
        raise ValueError("No YouTube channel found for authenticated Google account.")

    channel_item = items[0]
    channel_id = channel_item["id"]
    channel_title = channel_item["snippet"]["title"]

    # Encrypt refresh token
    encrypted_refresh = encrypt_token(creds.refresh_token)

    metadata = {
        "client_id": creds.client_id,
        "token_uri": creds.token_uri,
        "scopes": creds.scopes,
        "channel_id": channel_id,
        "channel_title": channel_title,
    }

    with db_session() as session:
        repo = Repository(session)
        cred_obj = repo.save_credential("google", encrypted_refresh, metadata)
        channel_obj = repo.get_or_create_channel(channel_id, channel_title, cred_obj.id)

        return {
            "channel_id": channel_obj.youtube_channel_id,
            "title": channel_obj.title,
            "credential_id": cred_obj.id,
            "status": "connected",
        }


def _get_client_secret() -> Optional[str]:
    """Resolve the OAuth client_secret from env var or client_secrets.json."""
    secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    if secret:
        return secret
    config = _get_client_config()
    if config:
        for key in ("web", "installed"):
            if key in config and "client_secret" in config[key]:
                return config[key]["client_secret"]
    return None


def get_authenticated_service(credential_id: int) -> Any:
    """Build authenticated YouTube API v3 service from stored encrypted credential."""
    with db_session() as session:
        repo = Repository(session)
        cred = repo.get_credential(credential_id)
        if not cred:
            raise ValueError(f"Credential {credential_id} not found.")

        meta = json.loads(cred.token_metadata_json or "{}")
        plain_refresh_token = decrypt_token(cred.encrypted_refresh_token)

        client_secret = _get_client_secret()
        if not client_secret:
            raise ValueError(
                "Cannot find client_secret. Set GOOGLE_CLIENT_SECRET env var "
                "or ensure data/client_secrets.json is present."
            )

        google_creds = google.oauth2.credentials.Credentials(
            token=None,
            refresh_token=plain_refresh_token,
            token_uri=meta.get("token_uri", "https://oauth2.googleapis.com/token"),
            client_id=meta.get("client_id", os.environ.get("GOOGLE_CLIENT_ID")),
            client_secret=client_secret,
            scopes=meta.get("scopes", YOUTUBE_SCOPES),
        )

        return googleapiclient.discovery.build("youtube", "v3", credentials=google_creds)
