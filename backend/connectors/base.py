"""Connector contract for normalized local Sent-mail extraction and outbound dispatch."""

from __future__ import annotations

from abc import ABC, abstractmethod

from backend.schemas import OutboundEmailRequest, RawSentEmail, SendReceipt


class ConnectorError(RuntimeError):
    """Raised when a provider cannot safely or successfully return sent mail."""


class BaseEmailConnector(ABC):
    """Provider adapter that returns normalized Sent messages without cloud persistence."""

    @abstractmethod
    def fetch_sent_emails(self, limit: int) -> list[RawSentEmail]:
        """Fetch no more than ``limit`` Sent messages into the normalized schema."""

    @abstractmethod
    def send_email(self, payload: OutboundEmailRequest) -> SendReceipt:
        """Send an email via the provider and return a receipt."""