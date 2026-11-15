"""Microsoft Graph desktop-flow Sent Items connector with outbound send support."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from backend.connectors.base import BaseEmailConnector, ConnectorError
from backend.schemas import OutboundEmailRequest, RawSentEmail, SendReceipt

_GRAPH_SENT_ENDPOINT = "https://graph.microsoft.com/v1.0/me/mailFolders/SentItems/messages"
_GRAPH_SEND_ENDPOINT = "https://graph.microsoft.com/v1.0/me/sendMail"


class OutlookConnector(BaseEmailConnector):
    """Uses MSAL public-client desktop auth and Microsoft Graph Mail.Read / Mail.Send."""

    def __init__(self, client_id: str, token_cache_file: Path, tenant_id: str = "common") -> None:
        self.client_id = client_id
        self.token_cache_file = token_cache_file
        self.tenant_id = tenant_id

    def _token(self, require_send: bool = False) -> str:
        try:
            import msal
        except ImportError as exc:
            raise ConnectorError("Outlook support requires the msal package.") from exc
        if not self.client_id:
            raise ConnectorError("Outlook client_id is required for the MSAL desktop flow.")
        cache = msal.SerializableTokenCache()
        if self.token_cache_file.exists():
            cache.deserialize(self.token_cache_file.read_text(encoding="utf-8"))
        scopes = ["Mail.Send", "Mail.Read"] if require_send else ["Mail.Read"]
        app = msal.PublicClientApplication(
            self.client_id,
            authority=f"https://login.microsoftonline.com/{self.tenant_id}",
            token_cache=cache,
        )
        accounts = app.get_accounts()
        result = app.acquire_token_silent(scopes, account=accounts[0]) if accounts else None
        if not result:
            result = app.acquire_token_interactive(scopes=scopes)
        if cache.has_state_changed:
            self.token_cache_file.parent.mkdir(parents=True, exist_ok=True)
            self.token_cache_file.write_text(cache.serialize(), encoding="utf-8")
        if "access_token" not in result:
            raise ConnectorError(f"Microsoft authorization failed: {result.get('error_description', result)}")
        return str(result["access_token"])

    def fetch_sent_emails(self, limit: int) -> list[RawSentEmail]:
        """Request Sent Items and normalize the Graph message page locally."""
        token = self._token(require_send=False)
        query = urlencode(
            {
                "$top": min(limit, 500),
                "$orderby": "sentDateTime desc",
                "$select": "id,conversationId,toRecipients,subject,body,sentDateTime,internetMessageId",
            }
        )
        request = Request(
            f"{_GRAPH_SENT_ENDPOINT}?{query}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        try:
            with urlopen(request, timeout=30) as response:
                payload: dict[str, Any] = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise ConnectorError(f"Microsoft Graph Sent Items request failed: {exc}") from exc
        records: list[RawSentEmail] = []
        for item in payload.get("value", []):
            recipients = item.get("toRecipients", [])
            recipient = recipients[0].get("emailAddress", {}).get("address", "") if recipients else ""
            records.append(
                RawSentEmail(
                    message_id=item.get("internetMessageId") or item["id"],
                    recipient_email=recipient,
                    subject=item.get("subject", ""),
                    raw_body=item.get("body", {}).get("content", ""),
                    timestamp=item.get("sentDateTime"),
                    thread_id=item.get("conversationId", ""),
                )
            )
        return records

    def send_email(self, payload: OutboundEmailRequest) -> SendReceipt:
        """Send an email via Microsoft Graph API."""
        token = self._token(require_send=True)

        # Build message object for Graph API
        message = {
            "subject": payload.subject,
            "body": {"contentType": "Text", "content": payload.body},
            "toRecipients": [{"emailAddress": {"address": addr}} for addr in payload.to],
        }
        if payload.cc:
            message["ccRecipients"] = [{"emailAddress": {"address": addr}} for addr in payload.cc]
        if payload.bcc:
            message["bccRecipients"] = [{"emailAddress": {"address": addr}} for addr in payload.bcc]

        # Attachments would need special handling (upload to OneDrive first for large files)
        # For now, skip attachments in Outlook connector

        body = {"message": message, "saveToSentItems": "true"}

        request = Request(
            _GRAPH_SEND_ENDPOINT,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=30) as response:
                if response.status == 202:
                    return SendReceipt(
                        message_id="",
                        status="sent",
                    )
                else:
                    return SendReceipt(
                        message_id="",
                        status="failed",
                        error=f"HTTP {response.status}: {response.read().decode('utf-8')}",
                    )
        except Exception as exc:
            return SendReceipt(
                message_id="",
                status="failed",
                error=str(exc),
            )