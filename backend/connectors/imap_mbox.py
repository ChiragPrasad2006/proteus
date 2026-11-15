"""IMAP and local .mbox/.eml Sent-mail connectors with SMTP send support."""

from __future__ import annotations

import email
import imaplib
import mailbox
import smtplib
from datetime import timezone
from email.header import decode_header, make_header
from email.message import EmailMessage, Message
from email.policy import default
from email.utils import getaddresses, make_msgid, parsedate_to_datetime
from pathlib import Path
from typing import Iterable

from backend.connectors.base import BaseEmailConnector, ConnectorError
from backend.schemas import OutboundEmailRequest, RawSentEmail, SendReceipt


def _decoded(value: str | None) -> str:
    """Decode RFC 2047 header text safely."""
    return str(make_header(decode_header(value or ""))).strip()


def _body_from_message(message: Message) -> str:
    """Prefer a non-attachment text/plain part, then an HTML alternative."""
    plain: list[str] = []
    html: list[str] = []
    for part in message.walk() if message.is_multipart() else [message]:
        if part.get_content_disposition() == "attachment":
            continue
        content_type = part.get_content_type()
        if content_type not in {"text/plain", "text/html"}:
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        content = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        (plain if content_type == "text/plain" else html).append(content)
    return "\n".join(plain or html)


def email_message_to_raw(message: Message, fallback_id: str) -> RawSentEmail:
    """Normalize a Python email Message to the project Sent-mail schema."""
    addresses = getaddresses([message.get("To", "")])
    recipient = addresses[0][1] if addresses else ""
    try:
        timestamp = parsedate_to_datetime(message.get("Date", ""))
        if timestamp and timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError, IndexError):
        timestamp = None
    return RawSentEmail(
        message_id=_decoded(message.get("Message-ID")) or fallback_id,
        recipient_email=recipient,
        subject=_decoded(message.get("Subject")),
        raw_body=_body_from_message(message),
        timestamp=timestamp,
        thread_id=_decoded(message.get("In-Reply-To")) or _decoded(message.get("References")),
    )


class LocalMailFileConnector(BaseEmailConnector):
    """Extracts local Apple Mail, Thunderbird, or standard RFC 822 archives."""

    def __init__(self, file_path: Path) -> None:
        self.file_path = file_path

    def fetch_sent_emails(self, limit: int) -> list[RawSentEmail]:
        """Read a .mbox or .eml file without transmitting any contents."""
        if not self.file_path.is_file():
            raise ConnectorError(f"Local mail file does not exist: {self.file_path}")
        suffix = self.file_path.suffix.lower()
        if suffix == ".eml":
            with self.file_path.open("rb") as handle:
                return [email_message_to_raw(email.message_from_binary_file(handle, policy=default), self.file_path.name)]
        if suffix != ".mbox":
            raise ConnectorError("Local file must be an .mbox or .eml export.")
        archive = mailbox.mbox(str(self.file_path), factory=lambda handle: email.message_from_binary_file(handle, policy=default))
        messages = list(archive)[-limit:]
        messages.reverse()
        return [email_message_to_raw(message, str(index)) for index, message in enumerate(messages)]

    def send_email(self, payload: OutboundEmailRequest) -> SendReceipt:
        """Simulated local outbox sink for demo mode - writes to demo_outbox.jsonl."""
        import json
        from datetime import datetime, timezone

        outbox_path = Path("local_user_data/demo_outbox.jsonl")
        outbox_path.parent.mkdir(parents=True, exist_ok=True)

        message_id = make_msgid()
        record = {
            "message_id": message_id,
            "to": payload.to,
            "cc": payload.cc,
            "bcc": payload.bcc,
            "subject": payload.subject,
            "body": payload.body,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "thread_id": payload.thread_id,
            "in_reply_to": payload.in_reply_to,
        }
        with outbox_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

        return SendReceipt(
            message_id=message_id,
            thread_id=payload.thread_id,
            status="sent",
        )


class ImapConnector(BaseEmailConnector):
    """Fetches a configured Sent mailbox through IMAP using in-memory credentials.
    Sends via SMTP using the same credentials.
    """

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        folder: str = "Sent",
        port: int = 993,
        smtp_host: str | None = None,
        smtp_port: int = 587,
    ) -> None:
        self.host = host
        self.username = username
        self.password = password
        self.folder = folder
        self.port = port
        self.smtp_host = smtp_host or host.replace("imap.", "smtp.")
        self.smtp_port = smtp_port

    def fetch_sent_emails(self, limit: int) -> list[RawSentEmail]:
        """Download only the requested recent Sent messages and immediately normalize them."""
        if not all((self.host, self.username, self.password)):
            raise ConnectorError("IMAP host, username, and password are required.")
        try:
            with imaplib.IMAP4_SSL(self.host, self.port) as client:
                client.login(self.username, self.password)
                status, _ = client.select(self.folder, readonly=True)
                if status != "OK":
                    raise ConnectorError(f"Unable to open IMAP Sent folder '{self.folder}'.")
                status, data = client.search(None, "ALL")
                if status != "OK":
                    raise ConnectorError("Unable to search IMAP Sent folder.")
                message_numbers = data[0].split()[-limit:]
                records: list[RawSentEmail] = []
                for number in reversed(message_numbers):
                    status, parts = client.fetch(number, "(RFC822)")
                    if status != "OK" or not parts or not isinstance(parts[0], tuple):
                        continue
                    message = email.message_from_bytes(parts[0][1], policy=default)
                    records.append(email_message_to_raw(message, number.decode("ascii", errors="replace")))
                return records
        except imaplib.IMAP4.error as exc:
            raise ConnectorError(f"IMAP authentication or retrieval failed: {exc}") from exc

    def send_email(self, payload: OutboundEmailRequest) -> SendReceipt:
        """Send an email via SMTP."""
        msg = EmailMessage()
        msg["From"] = self.username
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

        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                server.login(self.username, self.password)
                # BCC recipients are not in headers, so include them in sendmail
                all_recipients = payload.to + payload.cc + payload.bcc
                server.send_message(msg, from_addr=self.username, to_addrs=all_recipients)
            return SendReceipt(
                message_id=msg["Message-ID"],
                status="sent",
            )
        except Exception as exc:
            return SendReceipt(
                message_id="",
                status="failed",
                error=str(exc),
            )


def _decoded(value: str | None) -> str:
    """Decode RFC 2047 header text safely."""
    return str(make_header(decode_header(value or ""))).strip()


def _body_from_message(message: Message) -> str:
    """Prefer a non-attachment text/plain part, then an HTML alternative."""
    plain: list[str] = []
    html: list[str] = []
    for part in message.walk() if message.is_multipart() else [message]:
        if part.get_content_disposition() == "attachment":
            continue
        content_type = part.get_content_type()
        if content_type not in {"text/plain", "text/html"}:
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        content = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        (plain if content_type == "text/plain" else html).append(content)
    return "\n".join(plain or html)


def email_message_to_raw(message: Message, fallback_id: str) -> RawSentEmail:
    """Normalize a Python email Message to the project Sent-mail schema."""
    addresses = getaddresses([message.get("To", "")])
    recipient = addresses[0][1] if addresses else ""
    try:
        timestamp = parsedate_to_datetime(message.get("Date", ""))
        if timestamp and timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError, IndexError):
        timestamp = None
    return RawSentEmail(
        message_id=_decoded(message.get("Message-ID")) or fallback_id,
        recipient_email=recipient,
        subject=_decoded(message.get("Subject")),
        raw_body=_body_from_message(message),
        timestamp=timestamp,
        thread_id=_decoded(message.get("In-Reply-To")) or _decoded(message.get("References")),
    )