"""Microsoft Graph OAuth2 connector for Outlook.com and Microsoft 365."""

from __future__ import annotations

import hashlib
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from backend.auth.microsoft_oauth import (
    load_outlook_oauth_config,
    load_outlook_tokens,
    refresh_outlook_token,
    save_outlook_tokens,
)
from backend.config import Settings
from backend.connectors.base import BaseEmailConnector, ConnectorError
from backend.connectors.imap_mbox import html_to_plain_text
from backend.schemas import OutboundEmailRequest, RawSentEmail, SendReceipt

_GRAPH_BASE = "https://graph.microsoft.com/v1.0"


def _extract_graph_body(body_obj: dict[str, Any] | None) -> str:
    if not isinstance(body_obj, dict):
        return ""
    content = str(body_obj.get("content", "") or "")
    ctype = str(body_obj.get("contentType", "text") or "text").lower()
    if ctype == "html":
        return html_to_plain_text(content)
    return content.strip()


def _extract_graph_addresses(items: list[dict[str, Any]] | None) -> list[str]:
    out: list[str] = []
    for item in items or []:
        addr = str(((item or {}).get("emailAddress") or {}).get("address", "") or "").strip().lower()
        if addr and "@" in addr and addr not in out:
            out.append(addr)
    return out


class OutlookGraphConnector(BaseEmailConnector):
    """Read-only Inbox/Sent & outbound Mail.Send connector using Microsoft Graph OAuth2."""

    def __init__(
        self,
        access_token: str | None = None,
        *,
        acc_settings: Settings | None = None,
        root_settings: Settings | None = None,
        client_id: str = "",
        client_secret: str = "",
        tenant_id: str = "common",
        token_data: dict[str, Any] | None = None,
        token_cache_file: Path | None = None,
    ) -> None:
        self.acc_settings = acc_settings
        self.root_settings = root_settings or acc_settings
        self.client_id = client_id
        self.client_secret = client_secret
        self.tenant_id = tenant_id or "common"
        self.token_cache_file = token_cache_file
        self._token_data: dict[str, Any] = dict(token_data or {})
        if access_token:
            self._token_data.setdefault("access_token", access_token)
            self._token_data.setdefault("expires_at", time.time() + 3600)

    def _load_token_data(self) -> dict[str, Any]:
        if not self._token_data and self.acc_settings is not None:
            loaded = load_outlook_tokens(self.acc_settings)
            if loaded:
                self._token_data = loaded
        if not self._token_data or not self._token_data.get("access_token"):
            raise ConnectorError("Outlook OAuth token is missing. Sign in with Microsoft first.")
        return self._token_data

    def _get_oauth_config(self) -> dict[str, Any]:
        if self.client_id:
            return {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "tenant_id": self.tenant_id,
            }
        if self.root_settings is not None:
            cfg = load_outlook_oauth_config(self.root_settings)
            if cfg:
                return cfg
        raise ConnectorError("Outlook OAuth client_id is not configured.")

    def _access_token(self) -> str:
        data = self._load_token_data()
        expires_at = float(data.get("expires_at", 0) or 0)
        if expires_at and (expires_at - 60.0) <= time.time():
            refresh_tok = str(data.get("refresh_token", "") or "").strip()
            if not refresh_tok:
                raise ConnectorError("Outlook access token expired and no refresh_token is available. Re-authenticate.")
            config = self._get_oauth_config()
            refreshed = refresh_outlook_token(config, refresh_tok)
            self._token_data = refreshed
            if self.acc_settings is not None:
                save_outlook_tokens(self.acc_settings, refreshed)
        return str(self._token_data["access_token"])

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._access_token()}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def test_connection(self) -> dict[str, Any]:
        """Verify Graph API access by fetching /v1.0/me."""
        try:
            resp = httpx.get(f"{_GRAPH_BASE}/me", headers=self._headers(), timeout=15.0)
            resp.raise_for_status()
            me = resp.json()
        except ConnectorError:
            raise
        except Exception as exc:
            raise ConnectorError(f"Microsoft Graph connection failed: {exc}") from exc
        email = str(me.get("mail") or me.get("userPrincipalName") or "").strip().lower()
        return {
            "ok": True,
            "provider": "outlook",
            "email": email,
            "display_name": str(me.get("displayName") or ""),
        }

    def fetch_sent_emails(self, limit: int = 200) -> list[RawSentEmail]:
        """Fetch SentItems messages via Microsoft Graph without modifying mailbox state."""
        params = {
            "$top": max(1, min(limit, 500)),
            "$orderby": "sentDateTime desc",
            "$select": "id,conversationId,toRecipients,ccRecipients,bccRecipients,subject,body,sentDateTime,internetMessageId",
        }
        try:
            resp = httpx.get(
                f"{_GRAPH_BASE}/me/mailFolders/SentItems/messages",
                params=params,
                headers=self._headers(),
                timeout=30.0,
            )
            resp.raise_for_status()
            payload = resp.json()
        except ConnectorError:
            raise
        except Exception as exc:
            raise ConnectorError(f"Microsoft Graph SentItems request failed: {exc}") from exc

        records: list[RawSentEmail] = []
        for item in payload.get("value", []):
            to_addrs = _extract_graph_addresses(item.get("toRecipients"))
            recipient = to_addrs[0] if to_addrs else ""
            ts = item.get("sentDateTime")
            records.append(
                RawSentEmail(
                    message_id=str(item.get("internetMessageId") or item.get("id", "")),
                    recipient_email=recipient,
                    subject=str(item.get("subject", "") or ""),
                    raw_body=_extract_graph_body(item.get("body")),
                    timestamp=ts,
                    thread_id=str(item.get("conversationId", "") or ""),
                )
            )
        return records[:limit]

    def _fetch_inbox_messages(self, limit: int = 100) -> list[dict[str, Any]]:
        params = {
            "$top": max(1, min(limit, 200)),
            "$orderby": "receivedDateTime desc",
            "$select": (
                "id,conversationId,from,toRecipients,ccRecipients,subject,body,"
                "bodyPreview,receivedDateTime,isRead,internetMessageId"
            ),
        }
        try:
            resp = httpx.get(
                f"{_GRAPH_BASE}/me/mailFolders/Inbox/messages",
                params=params,
                headers=self._headers(),
                timeout=30.0,
            )
            resp.raise_for_status()
            payload = resp.json()
        except ConnectorError:
            raise
        except Exception as exc:
            raise ConnectorError(f"Microsoft Graph Inbox request failed: {exc}") from exc
        return list(payload.get("value", []))

    @staticmethod
    def _normalize_graph_message(item: dict[str, Any]) -> dict[str, Any]:
        sender = ((item.get("from") or {}).get("emailAddress") or {})
        from_email = str(sender.get("address", "") or "").strip().lower()
        from_name = str(sender.get("name", "") or "").strip() or (from_email.split("@")[0] if from_email else "")
        body_text = _extract_graph_body(item.get("body")) or str(item.get("bodyPreview", "") or "").strip()
        date_str = str(item.get("receivedDateTime", "") or "")
        try:
            sort_ts = datetime.fromisoformat(date_str.replace("Z", "+00:00")).timestamp() if date_str else 0.0
        except ValueError:
            sort_ts = 0.0
        return {
            "message_id": str(item.get("internetMessageId") or item.get("id", "")),
            "graph_id": str(item.get("id", "")),
            "from_name": from_name,
            "from_email": from_email,
            "to": _extract_graph_addresses(item.get("toRecipients")),
            "cc": _extract_graph_addresses(item.get("ccRecipients")),
            "date": date_str,
            "subject": str(item.get("subject", "") or ""),
            "body_text": body_text,
            "in_reply_to": "",
            "references": [],
            "unread": not bool(item.get("isRead", True)),
            "_sort_ts": sort_ts,
            "_conv_id": str(item.get("conversationId", "") or ""),
        }

    def _group_graph_threads(self, raw_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        buckets: dict[str, list[dict[str, Any]]] = {}
        for item in raw_items:
            norm = self._normalize_graph_message(item)
            conv_id = norm["_conv_id"] or (
                "outlook_" + hashlib.sha256((norm["message_id"] or norm["subject"]).encode("utf-8")).hexdigest()[:16]
            )
            buckets.setdefault(conv_id, []).append(norm)

        threads: list[dict[str, Any]] = []
        for conv_id, group in buckets.items():
            group.sort(key=lambda m: (m["_sort_ts"], m["date"], m["message_id"]))
            latest = group[-1]
            participants: list[str] = []
            for m in group:
                for addr in [m["from_email"], *m["to"], *m["cc"]]:
                    if addr and addr not in participants:
                        participants.append(addr)
            subj = next((m["subject"].strip() for m in group if m["subject"].strip()), "") or "(no subject)"
            snippet = " ".join(latest["body_text"].split())[:160]
            clean_msgs = [
                {
                    "message_id": m["message_id"],
                    "from_name": m["from_name"],
                    "from_email": m["from_email"],
                    "to": list(m["to"]),
                    "cc": list(m["cc"]),
                    "date": m["date"],
                    "subject": m["subject"],
                    "body_text": m["body_text"],
                    "in_reply_to": m["in_reply_to"],
                    "references": list(m["references"]),
                }
                for m in group
            ]
            threads.append(
                {
                    "thread_id": conv_id,
                    "subject": subj,
                    "snippet": snippet,
                    "last_message_at": latest["date"],
                    "message_count": len(clean_msgs),
                    "participants": participants,
                    "unread": any(m["unread"] for m in group),
                    "latest_sender_name": latest["from_name"],
                    "latest_sender_email": latest["from_email"],
                    "messages": clean_msgs,
                    "_last_ts": latest["_sort_ts"],
                }
            )
        threads.sort(key=lambda t: (t["_last_ts"], t["last_message_at"]), reverse=True)
        for t in threads:
            t.pop("_last_ts", None)
        return threads

    def fetch_inbox_threads(self, limit: int = 25) -> list[dict[str, Any]]:
        """Read-only Inbox threads grouped by Microsoft Graph conversationId."""
        raw_items = self._fetch_inbox_messages(limit=max(limit * 4, 50))
        threads = self._group_graph_threads(raw_items)
        return [{k: v for k, v in t.items() if k != "messages"} for t in threads[:limit]]

    def fetch_thread_messages(self, thread_id: str, limit: int = 100) -> dict[str, Any] | None:
        """Read-only chronological messages for one Graph conversationId."""
        escaped = thread_id.replace("'", "''")
        params = {
            "$filter": f"conversationId eq '{escaped}'",
            "$top": max(1, min(limit, 200)),
            "$select": (
                "id,conversationId,from,toRecipients,ccRecipients,subject,body,"
                "bodyPreview,receivedDateTime,isRead,internetMessageId"
            ),
        }
        try:
            resp = httpx.get(
                f"{_GRAPH_BASE}/me/messages",
                params=params,
                headers=self._headers(),
                timeout=30.0,
            )
            resp.raise_for_status()
            items = list(resp.json().get("value", []))
        except ConnectorError:
            raise
        except Exception:
            items = [i for i in self._fetch_inbox_messages(limit=limit) if i.get("conversationId") == thread_id]

        if not items:
            return None
        threads = self._group_graph_threads(items)
        if not threads:
            return None
        t = threads[0]
        return {
            "thread_id": t["thread_id"],
            "subject": t["subject"],
            "participants": t["participants"],
            "messages": t["messages"],
        }

    def send_email(
        self,
        payload: OutboundEmailRequest | None = None,
        *,
        to: list[str] | None = None,
        subject: str = "",
        body: str = "",
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        in_reply_to: str | None = None,
        references: list[str] | None = None,
        thread_id: str | None = None,
    ) -> SendReceipt:
        """Send an email via Microsoft Graph API, preserving threading headers when provided."""
        req = self._coerce_outbound_request(
            payload,
            to=to,
            subject=subject,
            body=body,
            cc=cc,
            bcc=bcc,
            in_reply_to=in_reply_to,
            references=references,
            thread_id=thread_id,
        )
        message: dict[str, Any] = {
            "subject": req.subject,
            "body": {"contentType": "Text", "content": req.body},
            "toRecipients": [{"emailAddress": {"address": addr}} for addr in req.to],
        }
        if req.cc:
            message["ccRecipients"] = [{"emailAddress": {"address": addr}} for addr in req.cc]
        if req.bcc:
            message["bccRecipients"] = [{"emailAddress": {"address": addr}} for addr in req.bcc]
        if req.thread_id:
            message["conversationId"] = req.thread_id

        extra_headers: list[dict[str, str]] = []
        if req.in_reply_to:
            extra_headers.append({"name": "In-Reply-To", "value": req.in_reply_to})
        if req.references:
            extra_headers.append({"name": "References", "value": " ".join(req.references)})
        if extra_headers:
            message["internetMessageHeaders"] = extra_headers

        try:
            resp = httpx.post(
                f"{_GRAPH_BASE}/me/sendMail",
                json={"message": message, "saveToSentItems": True},
                headers=self._headers(),
                timeout=30.0,
            )
            if resp.status_code in (200, 202):
                return SendReceipt(
                    message_id=resp.headers.get("request-id", ""),
                    thread_id=req.thread_id,
                    status="sent",
                )
            return SendReceipt(
                message_id="",
                thread_id=req.thread_id,
                status="failed",
                error=f"HTTP {resp.status_code}: {resp.text}",
            )
        except Exception as exc:
            return SendReceipt(
                message_id="",
                thread_id=req.thread_id,
                status="failed",
                error=str(exc),
            )


OutlookConnector = OutlookGraphConnector
