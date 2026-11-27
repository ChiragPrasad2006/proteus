"""Local-only connectors for Gmail, Outlook, Zoho Mail, IMAP, and mail archives."""

from .base import BaseEmailConnector, ConnectorError
from .factory import get_connector_for_account
from .gmail_app_password import GmailAppPasswordConnector
from .gmail_connector import GmailConnector
from .imap_mbox import ImapConnector, LocalMailFileConnector
from .outlook_connector import OutlookConnector, OutlookGraphConnector
from .zoho_connector import ZohoMailConnector, ZohoOAuthConnector

__all__ = [
    "BaseEmailConnector",
    "ConnectorError",
    "get_connector_for_account",
    "GmailAppPasswordConnector",
    "GmailConnector",
    "OutlookConnector",
    "OutlookGraphConnector",
    "ZohoMailConnector",
    "ZohoOAuthConnector",
    "ImapConnector",
    "LocalMailFileConnector",
]
