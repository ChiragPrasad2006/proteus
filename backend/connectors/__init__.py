"""Local-only connectors for Gmail, Outlook, IMAP, and mail archives."""

from .base import BaseEmailConnector, ConnectorError
from .gmail_app_password import GmailAppPasswordConnector
from .gmail_connector import GmailConnector
from .imap_mbox import ImapConnector, LocalMailFileConnector
from .outlook_connector import OutlookConnector

__all__ = [
    "BaseEmailConnector",
    "ConnectorError",
    "GmailAppPasswordConnector",
    "GmailConnector",
    "OutlookConnector",
    "ImapConnector",
    "LocalMailFileConnector",
]
