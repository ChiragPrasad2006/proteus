"""Microsoft Graph OAuth2 (PKCE + optional confidential client) for Outlook / M365."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

from backend.config import Settings
from backend.connectors.base import ConnectorError
from backend.storage.secret_vault import protect_secret, reveal_secret

MICROSOFT_SCOPES: list[str] = [
    "openid",
    "profile",
    "email",
    "offline_access",
    "Mail.Read",
    "Mail.Send",
    "User.Read",
]

_CONFIG_FILENAME = "outlook_oauth_config.bin"
_TOKEN_FILENAME = "outlook_token.bin"


def generate_pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) using S256."""
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def save_outlook_oauth_config(
    settings: Settings,
    client_id: str,
    client_secret: str = "",
    tenant_id: str = "common",
) -> dict[str, Any]:
    """Encrypt and persist the Microsoft Entra / Azure App registration config."""
    clean_client_id = (client_id or "").strip()
    if not clean_client_id:
        raise ConnectorError("Outlook Application (client) ID is required.")
    clean_tenant = (tenant_id or "common").strip() or "common"
    payload = {
        "client_id": clean_client_id,
        "client_secret": (client_secret or "").strip(),
        "tenant_id": clean_tenant,
    }
    config_path = settings.local_user_data_dir / _CONFIG_FILENAME
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        protect_secret(json.dumps(payload), settings.local_user_data_dir),
        encoding="utf-8",
    )
    return payload


def load_outlook_oauth_config(settings: Settings) -> dict[str, Any] | None:
    """Load and decrypt the stored Microsoft OAuth app config if present."""
    config_path = settings.local_user_data_dir / _CONFIG_FILENAME
    if not config_path.is_file():
        return None
    try:
        raw = reveal_secret(config_path.read_text(encoding="utf-8").strip(), settings.local_user_data_dir)
        data = json.loads(raw)
        if isinstance(data, dict) and data.get("client_id"):
            return {
                "client_id": str(data["client_id"]).strip(),
                "client_secret": str(data.get("client_secret", "")).strip(),
                "tenant_id": str(data.get("tenant_id", "common")).strip() or "common",
            }
    except Exception:
        return None
    return None


def save_outlook_tokens(acc_settings: Settings, token_data: dict[str, Any]) -> Path:
    """Encrypt and persist Outlook OAuth access/refresh tokens under the account dir."""
    acc_settings.oauth_token_dir.mkdir(parents=True, exist_ok=True)
    token_path = acc_settings.oauth_token_dir / _TOKEN_FILENAME
    payload = dict(token_data)
    if "expires_at" not in payload and "expires_in" in payload:
        try:
            payload["expires_at"] = time.time() + int(payload["expires_in"])
        except (TypeError, ValueError):
            payload["expires_at"] = time.time() + 3600
    token_path.write_text(
        protect_secret(json.dumps(payload), acc_settings.local_user_data_dir),
        encoding="utf-8",
    )
    return token_path


def load_outlook_tokens(acc_settings: Settings) -> dict[str, Any] | None:
    """Load and decrypt Outlook OAuth tokens for a specific account."""
    token_path = acc_settings.oauth_token_dir / _TOKEN_FILENAME
    if not token_path.is_file():
        return None
    try:
        raw = reveal_secret(token_path.read_text(encoding="utf-8").strip(), acc_settings.local_user_data_dir)
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def build_outlook_auth_url(
    config: dict[str, Any],
    redirect_uri: str,
    state: str,
    code_challenge: str,
) -> str:
    tenant_id = config.get("tenant_id") or "common"
    params = {
        "client_id": config["client_id"],
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "response_mode": "query",
        "scope": " ".join(MICROSOFT_SCOPES),
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "prompt": "select_account",
    }
    return f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/authorize?{urlencode(params)}"


def exchange_outlook_code(
    config: dict[str, Any],
    code: str,
    redirect_uri: str,
    code_verifier: str,
) -> dict[str, Any]:
    tenant_id = config.get("tenant_id") or "common"
    token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    form: dict[str, str] = {
        "client_id": config["client_id"],
        "scope": " ".join(MICROSOFT_SCOPES),
        "code": code,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
        "code_verifier": code_verifier,
    }
    if config.get("client_secret"):
        form["client_secret"] = str(config["client_secret"])
    try:
        resp = httpx.post(token_url, data=form, timeout=20.0)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        raise ConnectorError(f"Microsoft OAuth token exchange failed: {exc}") from exc
    if "access_token" not in data:
        raise ConnectorError(f"Microsoft OAuth response missing access_token: {data.get('error_description', data)}")
    data["expires_at"] = time.time() + int(data.get("expires_in", 3600))
    return data


def refresh_outlook_token(config: dict[str, Any], refresh_token: str) -> dict[str, Any]:
    tenant_id = config.get("tenant_id") or "common"
    token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    form: dict[str, str] = {
        "client_id": config["client_id"],
        "scope": " ".join(MICROSOFT_SCOPES),
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    if config.get("client_secret"):
        form["client_secret"] = str(config["client_secret"])
    try:
        resp = httpx.post(token_url, data=form, timeout=20.0)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        raise ConnectorError(f"Microsoft OAuth token refresh failed: {exc}") from exc
    if "access_token" not in data:
        raise ConnectorError(f"Microsoft OAuth refresh missing access_token: {data.get('error_description', data)}")
    if "refresh_token" not in data:
        data["refresh_token"] = refresh_token
    data["expires_at"] = time.time() + int(data.get("expires_in", 3600))
    return data


def fetch_microsoft_user_info(access_token: str) -> dict[str, Any]:
    try:
        resp = httpx.get(
            "https://graph.microsoft.com/v1.0/me",
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
            timeout=15.0,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        raise ConnectorError(f"Failed to fetch Microsoft Graph profile (/v1.0/me): {exc}") from exc
