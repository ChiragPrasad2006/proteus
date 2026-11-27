"""Zoho Mail regional data center mapping and optional OAuth2 helpers."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

from backend.config import Settings
from backend.connectors.base import ConnectorError
from backend.storage.secret_vault import protect_secret, reveal_secret

ZOHO_OAUTH_SCOPES: list[str] = [
    "ZohoMail.accounts.READ",
    "ZohoMail.messages.READ",
    "ZohoMail.messages.CREATE",
]

ZOHO_REGIONS: dict[str, dict[str, Any]] = {
    "in": {
        "label": "India (.in)",
        "domain": "zoho.in",
        "imap_pro": "imappro.zoho.in",
        "imap_free": "imap.zoho.in",
        "imap_port": 993,
        "smtp_pro": "smtppro.zoho.in",
        "smtp_free": "smtp.zoho.in",
        "smtp_port": 465,
        "auth_base": "https://accounts.zoho.in",
        "mail_api_base": "https://mail.zoho.in",
    },
    "com": {
        "label": "US (.com)",
        "domain": "zoho.com",
        "imap_pro": "imappro.zoho.com",
        "imap_free": "imap.zoho.com",
        "imap_port": 993,
        "smtp_pro": "smtppro.zoho.com",
        "smtp_free": "smtp.zoho.com",
        "smtp_port": 465,
        "auth_base": "https://accounts.zoho.com",
        "mail_api_base": "https://mail.zoho.com",
    },
    "eu": {
        "label": "EU (.eu)",
        "domain": "zoho.eu",
        "imap_pro": "imappro.zoho.eu",
        "imap_free": "imap.zoho.eu",
        "imap_port": 993,
        "smtp_pro": "smtppro.zoho.eu",
        "smtp_free": "smtp.zoho.eu",
        "smtp_port": 465,
        "auth_base": "https://accounts.zoho.eu",
        "mail_api_base": "https://mail.zoho.eu",
    },
    "com.au": {
        "label": "Australia (.com.au)",
        "domain": "zoho.com.au",
        "imap_pro": "imappro.zoho.com.au",
        "imap_free": "imap.zoho.com.au",
        "imap_port": 993,
        "smtp_pro": "smtppro.zoho.com.au",
        "smtp_free": "smtp.zoho.com.au",
        "smtp_port": 465,
        "auth_base": "https://accounts.zoho.com.au",
        "mail_api_base": "https://mail.zoho.com.au",
    },
    "jp": {
        "label": "Japan (.jp)",
        "domain": "zoho.jp",
        "imap_pro": "imappro.zoho.jp",
        "imap_free": "imap.zoho.jp",
        "imap_port": 993,
        "smtp_pro": "smtppro.zoho.jp",
        "smtp_free": "smtp.zoho.jp",
        "smtp_port": 465,
        "auth_base": "https://accounts.zoho.jp",
        "mail_api_base": "https://mail.zoho.jp",
    },
}

_CONFIG_FILENAME = "zoho_oauth_config.bin"
_TOKEN_FILENAME = "zoho_token.bin"


def get_zoho_region_config(region: str = "in") -> dict[str, Any]:
    key = (region or "in").strip().lower()
    if key not in ZOHO_REGIONS:
        raise ConnectorError(f"Unsupported Zoho region '{region}'. Choose one of: {', '.join(ZOHO_REGIONS)}.")
    return dict(ZOHO_REGIONS[key])


def save_zoho_oauth_config(
    settings: Settings,
    client_id: str,
    client_secret: str,
    region: str = "in",
) -> dict[str, Any]:
    clean_id = (client_id or "").strip()
    clean_secret = (client_secret or "").strip()
    if not clean_id or not clean_secret:
        raise ConnectorError("Zoho OAuth client_id and client_secret are required.")
    get_zoho_region_config(region)
    payload = {
        "client_id": clean_id,
        "client_secret": clean_secret,
        "region": region.strip().lower(),
    }
    path = settings.local_user_data_dir / _CONFIG_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(protect_secret(json.dumps(payload), settings.local_user_data_dir), encoding="utf-8")
    return payload


def load_zoho_oauth_config(settings: Settings) -> dict[str, Any] | None:
    path = settings.local_user_data_dir / _CONFIG_FILENAME
    if not path.is_file():
        return None
    try:
        raw = reveal_secret(path.read_text(encoding="utf-8").strip(), settings.local_user_data_dir)
        data = json.loads(raw)
        if isinstance(data, dict) and data.get("client_id") and data.get("client_secret"):
            return {
                "client_id": str(data["client_id"]).strip(),
                "client_secret": str(data["client_secret"]).strip(),
                "region": str(data.get("region", "in")).strip().lower() or "in",
            }
    except Exception:
        return None
    return None


def save_zoho_tokens(acc_settings: Settings, token_data: dict[str, Any]) -> Path:
    acc_settings.oauth_token_dir.mkdir(parents=True, exist_ok=True)
    path = acc_settings.oauth_token_dir / _TOKEN_FILENAME
    payload = dict(token_data)
    if "expires_at" not in payload and "expires_in" in payload:
        try:
            payload["expires_at"] = time.time() + int(payload["expires_in"])
        except (TypeError, ValueError):
            payload["expires_at"] = time.time() + 3600
    path.write_text(protect_secret(json.dumps(payload), acc_settings.local_user_data_dir), encoding="utf-8")
    return path


def load_zoho_tokens(acc_settings: Settings) -> dict[str, Any] | None:
    path = acc_settings.oauth_token_dir / _TOKEN_FILENAME
    if not path.is_file():
        return None
    try:
        raw = reveal_secret(path.read_text(encoding="utf-8").strip(), acc_settings.local_user_data_dir)
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def build_zoho_auth_url(config: dict[str, Any], redirect_uri: str, state: str) -> str:
    reg = get_zoho_region_config(config.get("region", "in"))
    params = {
        "scope": ",".join(ZOHO_OAUTH_SCOPES),
        "client_id": config["client_id"],
        "response_type": "code",
        "access_type": "offline",
        "redirect_uri": redirect_uri,
        "state": state,
        "prompt": "consent",
    }
    return f"{reg['auth_base']}/oauth/v2/auth?{urlencode(params)}"


def exchange_zoho_code(config: dict[str, Any], code: str, redirect_uri: str) -> dict[str, Any]:
    reg = get_zoho_region_config(config.get("region", "in"))
    token_url = f"{reg['auth_base']}/oauth/v2/token"
    form = {
        "code": code,
        "client_id": config["client_id"],
        "client_secret": config["client_secret"],
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    try:
        resp = httpx.post(token_url, data=form, timeout=20.0)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        raise ConnectorError(f"Zoho OAuth token exchange failed: {exc}") from exc
    if "access_token" not in data:
        raise ConnectorError(f"Zoho OAuth response missing access_token: {data}")
    data["region"] = config.get("region", "in")
    data["expires_at"] = time.time() + int(data.get("expires_in", 3600))
    return data


def refresh_zoho_token(config: dict[str, Any], refresh_token: str) -> dict[str, Any]:
    reg = get_zoho_region_config(config.get("region", "in"))
    token_url = f"{reg['auth_base']}/oauth/v2/token"
    form = {
        "refresh_token": refresh_token,
        "client_id": config["client_id"],
        "client_secret": config["client_secret"],
        "grant_type": "refresh_token",
    }
    try:
        resp = httpx.post(token_url, data=form, timeout=20.0)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        raise ConnectorError(f"Zoho OAuth token refresh failed: {exc}") from exc
    if "access_token" not in data:
        raise ConnectorError(f"Zoho OAuth refresh missing access_token: {data}")
    data["refresh_token"] = data.get("refresh_token") or refresh_token
    data["region"] = config.get("region", "in")
    data["expires_at"] = time.time() + int(data.get("expires_in", 3600))
    return data


def fetch_zoho_user_info(access_token: str, region: str = "in") -> dict[str, Any]:
    reg = get_zoho_region_config(region)
    try:
        resp = httpx.get(
            f"{reg['mail_api_base']}/api/accounts",
            headers={"Authorization": f"Zoho-oauthtoken {access_token}"},
            timeout=15.0,
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:
        raise ConnectorError(f"Failed to fetch Zoho Mail account info: {exc}") from exc
    accounts = payload.get("data") or []
    first = accounts[0] if accounts else {}
    email = (first.get("primaryEmailAddress") or first.get("mailboxAddress") or "").strip().lower()
    display_name = (first.get("displayName") or first.get("accountName") or email.split("@")[0]).strip()
    account_key = str(first.get("accountId") or "")
    return {
        "email": email,
        "display_name": display_name,
        "zoho_account_id": account_key,
    }
