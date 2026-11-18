"""Google Gmail desktop-loopback Sent-mail connector with outbound send support."""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from backend.connectors.base import BaseEmailConnector, ConnectorError
from backend.schemas import OutboundEmailRequest, RawSentEmail, SendReceipt

# --- OAuth2 scope sets -----------------------------------------------------
# Identity scopes let us read the connecting user's email, name, and avatar.
GOOGLE_IDENTITY_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]
GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"

# Combined scope set requested by the desktop-loopback connect flow.
GMAIL_ALL_SCOPES = GOOGLE_IDENTITY_SCOPES + [GMAIL_READONLY_SCOPE, GMAIL_SEND_SCOPE]

# Back-compat aliases retained for older call sites.
_GMAIL_READONLY_SCOPE = [GMAIL_READONLY_SCOPE]
_GMAIL_SEND_SCOPE = [GMAIL_SEND_SCOPE, GMAIL_READONLY_SCOPE]

# OpenID Connect userinfo endpoint used to resolve the connecting account identity.
USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"


def _header(headers: list[dict[str, str]], name: str) -> str:
    """Read a case-insensitive Gmail message header."""
    return next((item.get("value", "") for item in headers if item.get("name", "").lower() == name.lower()), "")


def _body_from_payload(payload: dict[str, Any]) -> str:
    """Recursively prefer text/plain MIME parts, falling back to HTML."""
    plain: list[str] = []
    html: list[str] = []

    def visit(part: dict[str, Any]) -> None:
        data = part.get("body", {}).get("data")
        mime_type = part.get("mimeType", "")
        if data:
            decoded = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode(
                "utf-8", errors="replace"
            )
            (plain if mime_type == "text/plain" else html).append(decoded)
        for child in part.get("parts", []) or []:
            visit(child)

    visit(payload)
    return "\n".join(plain or html)


class GmailConnector(BaseEmailConnector):
    """Reads Gmail ``in:sent`` mail and sends mail via Google's OAuth2 desktop flow.

    The landing-page identity flow passes only standard OpenID/userinfo scopes.
    Gmail mailbox access is intentionally handled separately through the local
    IMAP/SMTP App Password connector.
    """

    def __init__(self, client_secrets_file: Path, token_file: Path, scopes: list[str] | None = None) -> None:
        self.client_secrets_file = Path(client_secrets_file)
        self.token_file = Path(token_file)
        self.scopes = list(scopes) if scopes else list(GOOGLE_IDENTITY_SCOPES)

    # --- OAuth2 desktop flow -------------------------------------------------
    def create_flow(self, redirect_uri: str | None = None, scopes: list[str] | None = None):
        """Build a google_auth_oauthlib Flow bound to the desktop client secrets file."""
        try:
            from google_auth_oauthlib.flow import Flow
        except ImportError as exc:
            raise ConnectorError(
                "Gmail dependencies are missing; install google-auth-oauthlib and google-api-python-client."
            ) from exc
        if not self.client_secrets_file.exists():
            raise ConnectorError(f"Gmail client secrets file not found at {self.client_secrets_file}.")
        flow = Flow.from_client_secrets_file(
            str(self.client_secrets_file),
            scopes=scopes or self.scopes,
            redirect_uri=redirect_uri,
        )
        # Enable PKCE when the installed google-auth-oauthlib supports it (required by
        # Google for the "Desktop app" client type). Safe no-op on older versions.
        try:
            flow.autogenerate_code_verifier = True  # type: ignore[attr-defined]
        except Exception:
            pass
        return flow

    def authorization_url(
        self,
        redirect_uri: str | None = None,
        state: str | None = None,
        scopes: list[str] | None = None,
    ) -> tuple[Any, str, str]:
        """Return ``(flow, authorization_url, state)`` for the consent redirect.

        The caller must persist ``flow`` (or its PKCE verifier) until the callback
        arrives so the authorization code can be exchanged with the matching verifier.
        """
        flow = self.create_flow(redirect_uri=redirect_uri, scopes=scopes)
        url, returned_state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
            state=state,
        )
        return flow, url, returned_state

    def exchange_code(self, flow, code: str, redirect_uri: str | None = None):
        """Exchange an authorization code for credentials using the original flow object."""
        if redirect_uri:
            try:
                flow.redirect_uri = redirect_uri
            except Exception:
                pass
        try:
            flow.fetch_token(code=code)
        except Exception as exc:
            raise ConnectorError(f"Failed to exchange Google authorization code: {exc}") from exc
        return flow.credentials

    def fetch_user_info(self, credentials) -> dict[str, Any]:
        """Fetch the OpenID Connect userinfo payload for the connected account."""
        import httpx

        token = getattr(credentials, "token", None)
        if not token:
            raise ConnectorError("Credentials do not carry an access token; cannot fetch user info.")
        try:
            response = httpx.get(
                USERINFO_ENDPOINT,
                headers={"Authorization": f"Bearer {token}"},
                timeout=15.0,
            )
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            raise ConnectorError(f"Failed to fetch Google user info: {exc}") from exc

    def save_credentials(self, credentials, token_file: Path | None = None) -> Path:
        """Persist credentials to the token file for later refresh-based reuse."""
        path = Path(token_file or self.token_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(credentials.to_json(), encoding="utf-8")
        return path

    def _get_credentials(self, require_send: bool = False):
        """Get OAuth credentials, optionally requesting send scope."""
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
        except ImportError as exc:
            raise ConnectorError("Gmail dependencies are missing; install google-auth-oauthlib and google-api-python-client.") from exc

        # Always request the full scope set so a single cached token can read and send.
        scopes = self.scopes
        credentials = None
        if self.token_file.exists():
            credentials = Credentials.from_authorized_user_file(str(self.token_file), scopes)
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        if not credentials or not credentials.valid:
            if not self.client_secrets_file.exists():
                raise ConnectorError("Gmail client_secrets_file is required for the desktop OAuth flow.")
            flow = InstalledAppFlow.from_client_secrets_file(str(self.client_secrets_file), scopes)
            credentials = flow.run_local_server(port=0)
        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        self.token_file.write_text(credentials.to_json(), encoding="utf-8")
        return credentials

    def fetch_sent_emails(self, limit: int) -> list[RawSentEmail]:
        """Authorize locally, query ``in:sent``, and return normalized messages."""
        credentials = self._get_credentials(require_send=False)
        try:
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise ConnectorError("google-api-python-client is required for Gmail fetch.") from exc

        service = build("gmail", "v1", credentials=credentials, cache_discovery=False)
        listing = service.users().messages().list(
            userId="me", q="in:sent", maxResults=min(limit, 500)
        ).execute()
        records: list[RawSentEmail] = []
        for item in listing.get("messages", []):
            message = service.users().messages().get(userId="me", id=item["id"], format="full").execute()
            headers = message.get("payload", {}).get("headers", [])
            recipient = _header(headers, "To").split(",", 1)[0].strip()
            timestamp = datetime.fromtimestamp(int(message.get("internalDate", "0")) / 1000, tz=timezone.utc)
            records.append(
                RawSentEmail(
                    message_id=_header(headers, "Message-ID") or message["id"],
                    recipient_email=recipient,
                    subject=_header(headers, "Subject"),
                    raw_body=_body_from_payload(message.get("payload", {})),
                    timestamp=timestamp,
                    thread_id=message.get("threadId", ""),
                )
            )
        return records

    def send_email(self, payload: OutboundEmailRequest) -> SendReceipt:
        """Send an email via Gmail API with proper MIME encoding."""
        credentials = self._get_credentials(require_send=True)
        try:
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise ConnectorError("google-api-python-client is required for Gmail send.") from exc

        service = build("gmail", "v1", credentials=credentials, cache_discovery=False)

        # Build MIME message
        msg = EmailMessage()
        msg["To"] = ", ".join(payload.to)
        if payload.cc:
            msg["Cc"] = ", ".join(payload.cc)
        if payload.bcc:
            msg["Bcc"] = ", ".join(payload.bcc)
        msg["Subject"] = payload.subject
        if payload.thread_id:
            msg["In-Reply-To"] = payload.thread_id
            msg["References"] = payload.thread_id
        if payload.in_reply_to:
            msg["In-Reply-To"] = payload.in_reply_to

        msg.set_content(payload.body, subtype="plain")

        # Handle attachments if any
        for attachment_path in payload.attachments:
            try:
                with open(attachment_path, "rb") as f:
                    data = f.read()
                import mimetypes
                mimetype, _ = mimetypes.guess_type(attachment_path)
                if mimetype is None:
                    mimetype = "application/octet-stream"
                maintype, subtype = mimetype.split("/", 1)
                msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=Path(attachment_path).name)
            except Exception as exc:
                raise ConnectorError(f"Failed to attach {attachment_path}: {exc}") from exc

        # Encode and send
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
        body = {"raw": raw}
        if payload.thread_id:
            body["threadId"] = payload.thread_id

        try:
            sent = service.users().messages().send(userId="me", body=body).execute()
            return SendReceipt(
                message_id=sent.get("id", ""),
                thread_id=sent.get("threadId"),
                status="sent",
            )
        except Exception as exc:
            return SendReceipt(
                message_id="",
                status="failed",
                error=str(exc),
            )


def _header(headers: list[dict[str, str]], name: str) -> str:
    """Read a case-insensitive Gmail message header."""
    return next((item.get("value", "") for item in headers if item.get("name", "").lower() == name.lower()), "")


def _body_from_payload(payload: dict[str, Any]) -> str:
    """Recursively prefer text/plain MIME parts, falling back to HTML."""
    plain: list[str] = []
    html: list[str] = []

    def visit(part: dict[str, Any]) -> None:
        data = part.get("body", {}).get("data")
        mime_type = part.get("mimeType", "")
        if data:
            decoded = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode(
                "utf-8", errors="replace"
            )
            (plain if mime_type == "text/plain" else html).append(decoded)
        for child in part.get("parts", []) or []:
            visit(child)

    visit(payload)
    return "\n".join(plain or html)