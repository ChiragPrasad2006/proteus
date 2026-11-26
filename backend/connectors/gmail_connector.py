"""Google Gmail desktop-loopback Sent-mail & read-only Inbox connector with outbound send support."""

from __future__ import annotations

import base64
import json
import re
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import getaddresses, make_msgid
from pathlib import Path
from typing import Any

from backend.connectors.base import BaseEmailConnector, ConnectorError
from backend.connectors.imap_mbox import html_to_plain_text
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
    html_parts: list[str] = []

    def visit(part: dict[str, Any]) -> None:
        data = part.get("body", {}).get("data")
        mime_type = part.get("mimeType", "")
        if data:
            decoded = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode(
                "utf-8", errors="replace"
            )
            (plain if mime_type == "text/plain" else html_parts).append(decoded)
        for child in part.get("parts", []) or []:
            visit(child)

    visit(payload)
    if plain:
        return "\n".join(plain).strip()
    if html_parts:
        return html_to_plain_text("\n".join(html_parts))
    return ""


def _parse_addr_list(header_val: str) -> list[str]:
    return [addr.strip().lower() for _, addr in getaddresses([header_val or ""]) if addr and "@" in addr]


def _parse_references(header_val: str) -> list[str]:
    if not header_val:
        return []
    bracketed = re.findall(r"<[^>\s]+>", header_val)
    return bracketed if bracketed else [tok.strip() for tok in header_val.split() if tok.strip()]


class GmailConnector(BaseEmailConnector):
    """Reads Gmail ``in:sent`` / INBOX threads and sends mail via Google's OAuth2 desktop flow."""

    def __init__(self, client_secrets_file: Path, token_file: Path, scopes: list[str] | None = None) -> None:
        self.client_secrets_file = Path(client_secrets_file)
        self.token_file = Path(token_file)
        self.scopes = list(scopes) if scopes else list(GOOGLE_IDENTITY_SCOPES)

    def has_readonly_scope(self) -> bool:
        """Check whether stored token includes gmail.readonly."""
        if not self.token_file.exists():
            return False
        try:
            token_data = json.loads(self.token_file.read_text(encoding="utf-8"))
            stored = token_data.get("scopes") or token_data.get("granted_scopes") or self.scopes
            return GMAIL_READONLY_SCOPE in (stored or [])
        except (OSError, json.JSONDecodeError):
            return False

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
        flow = self.create_flow(redirect_uri=redirect_uri, scopes=scopes)
        url, returned_state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
            state=state,
        )
        return flow, url, returned_state

    def exchange_code(self, flow, code: str, redirect_uri: str | None = None):
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
        path = Path(token_file or self.token_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(credentials.to_json(), encoding="utf-8")
        return path

    def _get_credentials(self, require_send: bool = False):
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
        except ImportError as exc:
            raise ConnectorError("Gmail dependencies are missing; install google-auth-oauthlib and google-api-python-client.") from exc

        credentials = None
        if self.token_file.exists():
            stored_scopes: list[str] = []
            if require_send:
                try:
                    token_data = json.loads(self.token_file.read_text(encoding="utf-8"))
                    stored_scopes = token_data.get("scopes") or token_data.get("granted_scopes") or []
                except (OSError, json.JSONDecodeError) as exc:
                    raise ConnectorError("Stored Gmail OAuth token could not be read.") from exc
                if GMAIL_SEND_SCOPE not in stored_scopes:
                    raise ConnectorError(
                        "Stored Gmail OAuth token lacks gmail.send; unlock this Gmail account with its App Password to send."
                    )
                credentials = Credentials.from_authorized_user_file(str(self.token_file))
            else:
                credentials = Credentials.from_authorized_user_file(str(self.token_file), self.scopes)

        if require_send and credentials is None:
            raise ConnectorError(
                "No stored Gmail OAuth token grants gmail.send; unlock this Gmail account with its App Password to send."
            )
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        if not credentials or not credentials.valid:
            if require_send:
                raise ConnectorError("Stored Gmail OAuth credentials are not valid for sending.")
            if not self.client_secrets_file.exists():
                raise ConnectorError("Gmail client_secrets_file is required for the desktop OAuth flow.")
            flow = InstalledAppFlow.from_client_secrets_file(str(self.client_secrets_file), self.scopes)
            credentials = flow.run_local_server(port=0)
        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        self.token_file.write_text(credentials.to_json(), encoding="utf-8")
        return credentials

    def _build_service(self, require_send: bool = False):
        credentials = self._get_credentials(require_send=require_send)
        try:
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise ConnectorError("google-api-python-client is required for Gmail API access.") from exc
        return build("gmail", "v1", credentials=credentials, cache_discovery=False)

    def fetch_sent_emails(self, limit: int) -> list[RawSentEmail]:
        """Authorize locally, query ``in:sent``, and return normalized messages."""
        service = self._build_service(require_send=False)
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

    @staticmethod
    def _normalize_gmail_thread(thread_payload: dict[str, Any]) -> dict[str, Any]:
        """Normalize a Gmail API threads.get payload into summary + chronological messages."""
        raw_msgs = thread_payload.get("messages", []) or []
        raw_msgs_sorted = sorted(raw_msgs, key=lambda m: int(m.get("internalDate", "0")))
        messages: list[dict[str, Any]] = []
        participants: list[str] = []
        unread = False

        for m in raw_msgs_sorted:
            headers = m.get("payload", {}).get("headers", [])
            label_ids = m.get("labelIds") or []
            if "UNREAD" in label_ids:
                unread = True
            from_hdr = _header(headers, "From")
            from_pairs = getaddresses([from_hdr])
            from_name = (from_pairs[0][0] if from_pairs else "").strip()
            from_email = (from_pairs[0][1] if from_pairs else "").strip().lower()
            to_list = _parse_addr_list(_header(headers, "To"))
            cc_list = _parse_addr_list(_header(headers, "Cc"))
            for addr in [from_email, *to_list, *cc_list]:
                if addr and addr not in participants:
                    participants.append(addr)

            ts_ms = int(m.get("internalDate", "0") or 0)
            date_iso = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc).isoformat() if ts_ms else ""
            body_text = _body_from_payload(m.get("payload", {})) or (m.get("snippet") or "")
            messages.append(
                {
                    "message_id": _header(headers, "Message-ID") or m.get("id", ""),
                    "from_name": from_name or (from_email.split("@")[0] if from_email else ""),
                    "from_email": from_email,
                    "to": to_list,
                    "cc": cc_list,
                    "date": date_iso,
                    "subject": _header(headers, "Subject"),
                    "body_text": body_text,
                    "in_reply_to": _header(headers, "In-Reply-To").strip(),
                    "references": _parse_references(_header(headers, "References")),
                }
            )

        latest = messages[-1] if messages else {}
        subject = next((m["subject"] for m in messages if m.get("subject")), "") or "(no subject)"
        snippet = re.sub(r"\s+", " ", latest.get("body_text", "")).strip()[:160]
        return {
            "thread_id": str(thread_payload.get("id", "")),
            "subject": subject,
            "snippet": snippet,
            "last_message_at": latest.get("date", ""),
            "message_count": len(messages),
            "participants": participants,
            "unread": unread,
            "latest_sender_name": latest.get("from_name", ""),
            "latest_sender_email": latest.get("from_email", ""),
            "messages": messages,
        }

    def fetch_inbox_threads(self, limit: int = 25) -> list[dict[str, Any]]:
        """Read-only listing of INBOX threads via Gmail threads.list + threads.get."""
        if not self.has_readonly_scope():
            raise ConnectorError("Stored Gmail OAuth token lacks gmail.readonly scope.")
        service = self._build_service(require_send=False)
        listing = service.users().threads().list(
            userId="me", labelIds=["INBOX"], maxResults=max(1, min(limit, 100))
        ).execute()
        threads: list[dict[str, Any]] = []
        for item in listing.get("threads", []) or []:
            detail = service.users().threads().get(userId="me", id=item["id"], format="full").execute()
            normalized = self._normalize_gmail_thread(detail)
            threads.append({k: v for k, v in normalized.items() if k != "messages"})
        threads.sort(key=lambda t: t.get("last_message_at", ""), reverse=True)
        return threads

    def fetch_thread_messages(self, thread_id: str) -> dict[str, Any] | None:
        """Read-only fetch of one Gmail INBOX thread via threads.get."""
        if not self.has_readonly_scope():
            raise ConnectorError("Stored Gmail OAuth token lacks gmail.readonly scope.")
        service = self._build_service(require_send=False)
        try:
            detail = service.users().threads().get(userId="me", id=thread_id, format="full").execute()
        except Exception as exc:
            if "404" in str(exc):
                return None
            raise ConnectorError(f"Unable to fetch Gmail thread '{thread_id}': {exc}") from exc
        normalized = self._normalize_gmail_thread(detail)
        return {
            "thread_id": normalized["thread_id"],
            "subject": normalized["subject"],
            "participants": normalized["participants"],
            "messages": normalized["messages"],
        }

    def send_email(self, payload: OutboundEmailRequest) -> SendReceipt:
        """Send an email via Gmail API with proper MIME encoding and reply headers."""
        service = self._build_service(require_send=True)

        msg = EmailMessage()
        msg["To"] = ", ".join(payload.to)
        if payload.cc:
            msg["Cc"] = ", ".join(payload.cc)
        if payload.bcc:
            msg["Bcc"] = ", ".join(payload.bcc)
        msg["Subject"] = payload.subject
        msg["Message-ID"] = make_msgid()
        if payload.in_reply_to:
            msg["In-Reply-To"] = payload.in_reply_to
        elif payload.thread_id and str(payload.thread_id).startswith("<"):
            msg["In-Reply-To"] = payload.thread_id
        if payload.references:
            msg["References"] = " ".join(payload.references)
        elif payload.thread_id and str(payload.thread_id).startswith("<"):
            msg["References"] = payload.thread_id
        elif payload.in_reply_to:
            msg["References"] = payload.in_reply_to

        msg.set_content(payload.body, subtype="plain")

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

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
        body: dict[str, Any] = {"raw": raw}
        if payload.thread_id and not str(payload.thread_id).startswith("imap_"):
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
