"""Gmail IMAP/SMTP connector authenticated by a local Google App Password.

The connector keeps the password only in memory. The onboarding route verifies
both transports before storing an encrypted local secret, then uses this adapter
for Sent-mail ingestion and outbound SMTP delivery.
"""

from __future__ import annotations

import imaplib
import smtplib
from email.message import EmailMessage
from email.utils import make_msgid

from backend.connectors.base import BaseEmailConnector, ConnectorError
from backend.connectors.imap_mbox import ImapConnector, email_message_to_raw
from backend.schemas import OutboundEmailRequest, RawSentEmail, SendReceipt


class GmailAppPasswordConnector(BaseEmailConnector):
    """Gmail Sent-mail access over IMAP/SMTP SSL using a 16-character App Password."""

    IMAP_HOST = "imap.gmail.com"
    IMAP_PORT = 993
    SMTP_HOST = "smtp.gmail.com"
    SMTP_PORT = 465

    def __init__(self, email: str, app_password: str) -> None:
        self.email = email.strip().lower()
        self.app_password = "".join(app_password.split())

    def _validate_inputs(self) -> None:
        if not self.email or "@" not in self.email:
            raise ConnectorError("A valid Gmail address is required.")
        if len(self.app_password) != 16:
            raise ConnectorError("Google App Passwords must contain exactly 16 characters.")

    def verify_connection(self) -> None:
        """Prove that the password can authenticate to both Gmail transports."""
        self._validate_inputs()
        try:
            with imaplib.IMAP4_SSL(self.IMAP_HOST, self.IMAP_PORT) as client:
                client.login(self.email, self.app_password)
        except (imaplib.IMAP4.error, OSError) as exc:
            raise ConnectorError("Gmail IMAP sign-in failed. Check the email and App Password.") from exc

        try:
            with smtplib.SMTP_SSL(self.SMTP_HOST, self.SMTP_PORT) as client:
                client.login(self.email, self.app_password)
        except (smtplib.SMTPException, OSError) as exc:
            raise ConnectorError("Gmail SMTP sign-in failed. Check the email and App Password.") from exc

    @staticmethod
    def _sent_folder(client: imaplib.IMAP4_SSL) -> str:
        """Locate Gmail's Sent folder, preferring the canonical Gmail mailbox."""
        status, _ = client.select('"[Gmail]/Sent Mail"', readonly=True)
        if status == "OK":
            return '"[Gmail]/Sent Mail"'

        status, folders = client.list()
        if status != "OK":
            raise ConnectorError("Unable to list Gmail folders while locating Sent mail.")
        for raw in folders or []:
            line = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
            if "\\Sent" not in line:
                continue
            delimiter = '"' if '"' in line else ""
            mailbox = line.rsplit(delimiter, 2)[-2] if delimiter else line.rsplit(" ", 1)[-1]
            status, _ = client.select(mailbox, readonly=True)
            if status == "OK":
                return mailbox
        raise ConnectorError("Unable to locate Gmail's Sent folder.")

    def fetch_sent_emails(self, limit: int) -> list[RawSentEmail]:
        """Fetch the most recent messages from Gmail's Sent folder over IMAP SSL."""
        self._validate_inputs()
        try:
            with imaplib.IMAP4_SSL(self.IMAP_HOST, self.IMAP_PORT) as client:
                client.login(self.email, self.app_password)
                self._sent_folder(client)
                status, data = client.search(None, "ALL")
                if status != "OK":
                    raise ConnectorError("Unable to search Gmail Sent mail.")
                numbers = (data[0] if data else b"").split()[-max(1, min(limit, 500)):]
                records: list[RawSentEmail] = []
                for number in reversed(numbers):
                    message_number = number.decode("ascii", errors="replace")
                    status, parts = client.fetch(message_number, "(RFC822)")
                    if status != "OK" or not parts or not isinstance(parts[0], tuple):
                        continue
                    import email
                    from email.policy import default

                    message = email.message_from_bytes(parts[0][1], policy=default)
                    records.append(email_message_to_raw(message, message_number))
                return records
        except ConnectorError:
            raise
        except (imaplib.IMAP4.error, OSError) as exc:
            raise ConnectorError("Unable to retrieve Gmail Sent mail with this App Password.") from exc

    def fetch_inbox_threads(self, limit: int = 25) -> list[dict]:
        """Read-only Gmail INBOX thread listing using IMAP BODY.PEEK[]."""
        self._validate_inputs()
        return ImapConnector(
            host=self.IMAP_HOST,
            username=self.email,
            password=self.app_password,
            folder="INBOX",
            port=self.IMAP_PORT,
            smtp_host=self.SMTP_HOST,
            smtp_port=self.SMTP_PORT,
        ).fetch_inbox_threads(limit=limit)

    def fetch_thread_messages(self, thread_id: str, limit: int = 100) -> dict | None:
        """Read-only Gmail INBOX thread detail using IMAP BODY.PEEK[]."""
        self._validate_inputs()
        return ImapConnector(
            host=self.IMAP_HOST,
            username=self.email,
            password=self.app_password,
            folder="INBOX",
            port=self.IMAP_PORT,
            smtp_host=self.SMTP_HOST,
            smtp_port=self.SMTP_PORT,
        ).fetch_thread_messages(thread_id=thread_id, limit=limit)

    def send_email(self, payload: OutboundEmailRequest) -> SendReceipt:
        """Send through Gmail SMTP SSL with the account's App Password."""
        self._validate_inputs()
        message = EmailMessage()
        message["From"] = self.email
        message["To"] = ", ".join(payload.to)
        if payload.cc:
            message["Cc"] = ", ".join(payload.cc)
        if payload.bcc:
            message["Bcc"] = ", ".join(payload.bcc)
        message["Subject"] = payload.subject
        message["Message-ID"] = make_msgid()
        if payload.in_reply_to:
            message["In-Reply-To"] = payload.in_reply_to
        elif payload.thread_id and str(payload.thread_id).startswith("<"):
            message["In-Reply-To"] = payload.thread_id
        if payload.references:
            message["References"] = " ".join(payload.references)
        elif payload.thread_id and str(payload.thread_id).startswith("<"):
            message["References"] = payload.thread_id
        elif payload.in_reply_to:
            message["References"] = payload.in_reply_to
        message.set_content(payload.body, subtype="plain")

        try:
            with smtplib.SMTP_SSL(self.SMTP_HOST, self.SMTP_PORT) as client:
                client.login(self.email, self.app_password)
                client.send_message(message, from_addr=self.email, to_addrs=payload.to + payload.cc + payload.bcc)
            return SendReceipt(
                message_id=message["Message-ID"],
                thread_id=payload.thread_id,
                status="sent",
            )
        except (smtplib.SMTPException, OSError) as exc:
            return SendReceipt(message_id="", status="failed", error=str(exc))
