"""Connector contract for normalized local Sent-mail extraction, read-only Inbox reading, and outbound dispatch."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from backend.schemas import OutboundEmailRequest, RawSentEmail, SendReceipt


class ConnectorError(RuntimeError):
    """Raised when a provider cannot safely or successfully complete a mailbox operation."""


class BaseEmailConnector(ABC):
    """Unified provider adapter for Sent ingestion, read-only Inbox threads, and outbound send."""

    @staticmethod
    def _coerce_outbound_request(
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
    ) -> OutboundEmailRequest:
        if payload is not None:
            return payload
        return OutboundEmailRequest(
            to=list(to or []),
            cc=list(cc or []),
            bcc=list(bcc or []),
            subject=subject,
            body=body,
            thread_id=thread_id,
            in_reply_to=in_reply_to,
            references=list(references or []),
        )

    def test_connection(self) -> dict[str, Any]:
        """Verify that credentials/tokens can reach the provider."""
        return {"ok": True}

    @abstractmethod
    def fetch_sent_emails(self, limit: int = 200) -> list[RawSentEmail]:
        """Fetch no more than ``limit`` Sent messages into the normalized schema."""

    def fetch_inbox_threads(self, limit: int = 25) -> list[dict[str, Any]]:
        """Read-only fetch of recent Inbox threads (must never mark unread messages as read)."""
        raise ConnectorError("Inbox thread reading is not supported by this connector.")

    def fetch_thread_messages(self, thread_id: str, limit: int = 100) -> dict[str, Any] | None:
        """Read-only fetch of chronological messages for ``thread_id``."""
        raise ConnectorError("Inbox thread detail is not supported by this connector.")

    @abstractmethod
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
        """Send an email via the provider and return a receipt."""
