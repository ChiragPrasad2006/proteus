"""Central connector factory for Gmail, Outlook, and Zoho Mail accounts."""

from __future__ import annotations

import json
from typing import Literal

from backend.auth.microsoft_oauth import load_outlook_tokens
from backend.auth.zoho_oauth import load_zoho_tokens
from backend.config import Settings
from backend.connectors.base import BaseEmailConnector, ConnectorError
from backend.connectors.gmail_app_password import GmailAppPasswordConnector
from backend.connectors.gmail_connector import GMAIL_READONLY_SCOPE, GMAIL_SEND_SCOPE, GmailConnector
from backend.connectors.outlook_connector import OutlookGraphConnector
from backend.connectors.zoho_connector import ZohoMailConnector, ZohoOAuthConnector
from backend.storage.account_manager import AccountManager
from backend.storage.secret_vault import reveal_secret


def get_connector_for_account(
    account_id: str,
    settings: Settings,
    account_manager: AccountManager | None = None,
    *,
    purpose: Literal["send", "inbox", "sent"] = "send",
) -> BaseEmailConnector:
    """Resolve the appropriate provider connector for ``account_id``.

    All credentials and tokens are decrypted strictly from ``accounts/<account_id>/``.
    """
    mgr = account_manager or AccountManager(settings.local_user_data_dir)
    account = mgr.get_account(account_id)
    if account is None:
        raise ConnectorError(f"Unknown account '{account_id}'.")

    acc_settings = settings.for_account(account.account_id)
    provider = (account.provider or "gmail").lower()

    if provider == "outlook":
        tokens = load_outlook_tokens(acc_settings)
        if not tokens:
            raise ConnectorError("Outlook OAuth token is missing. Sign in with Microsoft first.")
        return OutlookGraphConnector(
            acc_settings=acc_settings,
            root_settings=settings,
            token_data=tokens,
        )

    if provider == "zoho":
        zoho_cred_file = acc_settings.local_user_data_dir / "zoho_credentials.bin"
        if zoho_cred_file.is_file():
            try:
                raw = reveal_secret(zoho_cred_file.read_text(encoding="utf-8").strip(), acc_settings.local_user_data_dir)
                creds = json.loads(raw)
                return ZohoMailConnector(
                    email_address=str(creds.get("email", account.email)),
                    app_password=str(creds["app_password"]),
                    region=str(creds.get("region", "in")),
                    imap_host=creds.get("imap_host"),
                    smtp_host=creds.get("smtp_host"),
                )
            except Exception as exc:
                raise ConnectorError("Saved Zoho Mail credentials could not be opened; reconnect Zoho Mail.") from exc
        zoho_tokens = load_zoho_tokens(acc_settings)
        if zoho_tokens:
            return ZohoOAuthConnector(
                region=str(zoho_tokens.get("region", "in")),
                zoho_account_id=str(zoho_tokens.get("zoho_account_id", "")),
                email_address=account.email,
                acc_settings=acc_settings,
                root_settings=settings,
                token_data=zoho_tokens,
            )
        raise ConnectorError("Zoho Mail is not connected yet. Enter your Zoho App Password or sign in with Zoho OAuth.")

    # Default: Gmail (App Password preferred for send, OAuth with readonly preferred for inbox)
    app_password_file = acc_settings.local_user_data_dir / "app_password.bin"
    token_candidates = (
        acc_settings.oauth_token_dir / "google_identity.json",
        acc_settings.oauth_token_dir / "gmail_token.json",
    )

    def _gmail_oauth_with_scope(required_scope: str) -> GmailConnector | None:
        for token_file in token_candidates:
            if not token_file.is_file():
                continue
            try:
                token_data = json.loads(token_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            scopes = token_data.get("scopes") or token_data.get("granted_scopes") or []
            if isinstance(scopes, list) and required_scope in scopes:
                return GmailConnector(
                    acc_settings.google_client_secrets_file,
                    token_file,
                    scopes=[s for s in scopes if isinstance(s, str)],
                )
        return None

    def _gmail_app_password() -> GmailAppPasswordConnector | None:
        if not app_password_file.is_file():
            return None
        try:
            app_password = reveal_secret(
                app_password_file.read_text(encoding="utf-8"),
                acc_settings.local_user_data_dir,
            )
            if len(app_password) == 16:
                return GmailAppPasswordConnector(account.email, app_password)
        except Exception as exc:
            raise ConnectorError("The saved Gmail App Password could not be opened; reconnect the mailbox.") from exc
        return None

    if purpose in ("inbox", "sent"):
        oauth_conn = _gmail_oauth_with_scope(GMAIL_READONLY_SCOPE)
        if oauth_conn is not None:
            return oauth_conn
        app_conn = _gmail_app_password()
        if app_conn is not None:
            return app_conn
        raise ConnectorError("Inbox access requires gmail.readonly OAuth scope or an unlocked Gmail App Password.")

    app_conn = _gmail_app_password()
    if app_conn is not None:
        return app_conn
    oauth_conn = _gmail_oauth_with_scope(GMAIL_SEND_SCOPE)
    if oauth_conn is not None:
        return oauth_conn
    raise ConnectorError(
        "This OAuth token lacks gmail.send and no App Password is saved. Unlock the mailbox with a Gmail App Password before sending."
    )
