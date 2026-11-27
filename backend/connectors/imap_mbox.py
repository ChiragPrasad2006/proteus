"""IMAP and local .mbox/.eml Sent-mail & read-only Inbox connectors with SMTP send support."""

from __future__ import annotations

import email
import hashlib
import html as html_lib
import imaplib
import mailbox
import re
import smtplib
from datetime import datetime, timezone
from email.header import decode_header, make_header
from email.message import EmailMessage, Message
from email.policy import default
from email.utils import getaddresses, make_msgid, parsedate_to_datetime
from pathlib import Path
from typing import Any

from backend.connectors.base import BaseEmailConnector, ConnectorError
from backend.schemas import OutboundEmailRequest, RawSentEmail, SendReceipt

_HTML_BLOCK_BREAK_RE = re.compile(r"</?(?:p|div|br|li|tr|h[1-6]|blockquote)\b[^>]*>", re.IGNORECASE)
_HTML_IGNORE_RE = re.compile(r"<(?:style|script|head)\b[^>]*>.*?</(?:style|script|head)>", re.IGNORECASE | re.DOTALL)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_SUBJECT_PREFIX_RE = re.compile(r"^(?:(?:re|fwd?)\s*:\s*)+", re.IGNORECASE)


def _decoded(value: str | None) -> str:
    """Decode RFC 2047 header text safely."""
    return str(make_header(decode_header(value or ""))).strip()


def html_to_plain_text(raw_html: str) -> str:
    """Strip HTML tags/scripts cleanly into readable plain text."""
    text = _HTML_IGNORE_RE.sub(" ", raw_html or "")
    text = _HTML_BLOCK_BREAK_RE.sub("\n", text)
    text = _HTML_TAG_RE.sub(" ", text)
    text = html_lib.unescape(text)
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    collapsed = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", collapsed).strip()


def _body_from_message(message: Message) -> str:
    """Prefer a non-attachment text/plain part, then an HTML alternative."""
    plain: list[str] = []
    html_parts: list[str] = []
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
        (plain if content_type == "text/plain" else html_parts).append(content)
    if plain:
        return "\n".join(plain).strip()
    if html_parts:
        return html_to_plain_text("\n".join(html_parts))
    return ""


def _parse_addresses(header_val: str | None) -> list[tuple[str, str]]:
    """Return [(display_name, lowercase_email), ...] from an RFC 5322 address header."""
    results: list[tuple[str, str]] = []
    for name, addr in getaddresses([_decoded(header_val)]):
        clean_addr = (addr or "").strip().lower()
        if clean_addr and "@" in clean_addr:
            results.append((name.strip(), clean_addr))
    return results


def _parse_msg_id_tokens(header_val: str | None) -> list[str]:
    """Extract RFC 5322 message IDs from In-Reply-To / References headers."""
    text = _decoded(header_val)
    if not text:
        return []
    bracketed = re.findall(r"<[^>\s]+>", text)
    if bracketed:
        return bracketed
    return [tok.strip() for tok in text.split() if tok.strip()]


def _normalize_subject(subject: str) -> str:
    """Normalize subject by stripping Re:/Fwd: prefixes for fallback thread grouping."""
    return re.sub(r"\s+", " ", _SUBJECT_PREFIX_RE.sub("", (subject or "").strip())).strip().lower()


def _parse_date(date_header: str | None) -> tuple[str, float]:
    try:
        dt = parsedate_to_datetime(date_header or "")
        if dt is None:
            return "", 0.0
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt_utc = dt.astimezone(timezone.utc)
        return dt_utc.isoformat(), dt_utc.timestamp()
    except (TypeError, ValueError, IndexError):
        return "", 0.0


def parse_imap_inbox_message(
    raw_bytes: bytes,
    *,
    unread: bool = False,
    fallback_id: str = "",
) -> dict[str, Any]:
    """Parse raw RFC 822 bytes into a normalized inbox message dictionary."""
    message = email.message_from_bytes(raw_bytes, policy=default)
    message_id = _decoded(message.get("Message-ID")) or f"<imap-{fallback_id}@local>"
    from_pairs = _parse_addresses(message.get("From"))
    from_name, from_email = from_pairs[0] if from_pairs else ("", "")
    to_list = [addr for _, addr in _parse_addresses(message.get("To"))]
    cc_list = [addr for _, addr in _parse_addresses(message.get("Cc"))]
    subject = _decoded(message.get("Subject"))
    date_iso, sort_ts = _parse_date(message.get("Date"))
    in_reply_to_tokens = _parse_msg_id_tokens(message.get("In-Reply-To"))
    in_reply_to = in_reply_to_tokens[0] if in_reply_to_tokens else ""
    references = _parse_msg_id_tokens(message.get("References"))
    body_text = _body_from_message(message)

    return {
        "message_id": message_id,
        "from_name": from_name or (from_email.split("@")[0] if from_email else ""),
        "from_email": from_email,
        "to": to_list,
        "cc": cc_list,
        "date": date_iso,
        "subject": subject,
        "body_text": body_text,
        "in_reply_to": in_reply_to,
        "references": references,
        "unread": unread,
        "_sort_ts": sort_ts,
    }


def group_messages_into_threads(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group parsed inbox messages into chronological threads using References/In-Reply-To + subject fallback."""
    if not messages:
        return []

    n = len(messages)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    # Link by Message-ID / In-Reply-To / References chains.
    seen_msgid: dict[str, int] = {}
    for idx, msg in enumerate(messages):
        chain_ids = [msg.get("message_id", ""), msg.get("in_reply_to", ""), *(msg.get("references") or [])]
        for token in chain_ids:
            clean = str(token).strip()
            if not clean:
                continue
            if clean in seen_msgid:
                union(idx, seen_msgid[clean])
            else:
                seen_msgid[clean] = idx

    # Subject fallback for messages with empty References/In-Reply-To or unlinked replies.
    seen_subject: dict[str, int] = {}
    for idx, msg in enumerate(messages):
        norm_subj = _normalize_subject(msg.get("subject", ""))
        if not norm_subj:
            continue
        if norm_subj in seen_subject:
            union(idx, seen_subject[norm_subj])
        else:
            seen_subject[norm_subj] = idx

    buckets: dict[int, list[dict[str, Any]]] = {}
    for idx, msg in enumerate(messages):
        buckets.setdefault(find(idx), []).append(msg)

    threads: list[dict[str, Any]] = []
    for group in buckets.values():
        group.sort(key=lambda m: (m.get("_sort_ts", 0.0), m.get("date", ""), m.get("message_id", "")))
        earliest = group[0]
        latest = group[-1]

        # Deterministic URL-safe thread_id derived from the earliest root message ID or normalized subject.
        root_refs = earliest.get("references") or []
        root_key = (
            (root_refs[0] if root_refs else "")
            or earliest.get("in_reply_to")
            or earliest.get("message_id")
            or _normalize_subject(earliest.get("subject", ""))
        )
        thread_id = "imap_" + hashlib.sha256(root_key.encode("utf-8")).hexdigest()[:16]

        participants: list[str] = []
        for m in group:
            for addr in [m.get("from_email", ""), *(m.get("to") or []), *(m.get("cc") or [])]:
                clean_addr = str(addr).strip().lower()
                if clean_addr and clean_addr not in participants:
                    participants.append(clean_addr)

        # Clean subject (prefer earliest non-empty subject without redundant Re: when possible).
        raw_subj = next((m.get("subject", "").strip() for m in group if m.get("subject", "").strip()), "")
        snippet = re.sub(r"\s+", " ", latest.get("body_text", "")).strip()[:160]

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
                "thread_id": thread_id,
                "subject": raw_subj or "(no subject)",
                "snippet": snippet,
                "last_message_at": latest.get("date", ""),
                "message_count": len(clean_msgs),
                "participants": participants,
                "unread": any(bool(m.get("unread")) for m in group),
                "latest_sender_name": latest.get("from_name", ""),
                "latest_sender_email": latest.get("from_email", ""),
                "messages": clean_msgs,
                "_last_ts": latest.get("_sort_ts", 0.0),
            }
        )

    threads.sort(key=lambda t: (t["_last_ts"], t["last_message_at"]), reverse=True)
    for t in threads:
        t.pop("_last_ts", None)
    return threads


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
            "references": payload.references,
        }
        with outbox_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

        return SendReceipt(
            message_id=message_id,
            thread_id=payload.thread_id,
            status="sent",
        )


class ImapConnector(BaseEmailConnector):
    """Fetches Sent or read-only Inbox threads through IMAP and sends via SMTP."""

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

    def test_connection(self) -> dict[str, Any]:
        """Verify IMAP SSL authentication."""
        if not all((self.host, self.username, self.password)):
            raise ConnectorError("IMAP host, username, and password are required.")
        try:
            with imaplib.IMAP4_SSL(self.host, self.port) as client:
                client.login(self.username, self.password)
            return {"ok": True, "provider": "imap", "host": self.host}
        except (imaplib.IMAP4.error, OSError) as exc:
            raise ConnectorError(f"IMAP connection failed: {exc}") from exc

    def fetch_sent_emails(self, limit: int = 200) -> list[RawSentEmail]:
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
                message_numbers = (data[0] if data else b"").split()[-limit:]
                records: list[RawSentEmail] = []
                for number in reversed(message_numbers):
                    status, parts = client.fetch(number, "(BODY.PEEK[])")
                    if status != "OK" or not parts or not isinstance(parts[0], tuple):
                        continue
                    message = email.message_from_bytes(parts[0][1], policy=default)
                    records.append(email_message_to_raw(message, number.decode("ascii", errors="replace")))
                return records
        except imaplib.IMAP4.error as exc:
            raise ConnectorError(f"IMAP authentication or retrieval failed: {exc}") from exc

    def _fetch_raw_inbox_threads(self, limit: int = 25) -> list[dict[str, Any]]:
        """Read-only INBOX fetch using BODY.PEEK[] so unread state is never modified."""
        if not all((self.host, self.username, self.password)):
            raise ConnectorError("IMAP host, username, and password are required.")
        try:
            with imaplib.IMAP4_SSL(self.host, self.port) as client:
                client.login(self.username, self.password)
                status, _ = client.select("INBOX", readonly=True)
                if status != "OK":
                    raise ConnectorError("Unable to open IMAP INBOX.")
                unseen_set: set[bytes] = set()
                u_status, u_data = client.search(None, "UNSEEN")
                if u_status == "OK" and u_data and u_data[0]:
                    unseen_set = set(u_data[0].split())
                status, data = client.search(None, "ALL")
                if status != "OK":
                    raise ConnectorError("Unable to search IMAP INBOX.")
                all_nums = (data[0] if data and data[0] else b"").split()
                window = max(1, min(limit, 200))
                message_numbers = all_nums[-window:]
                parsed: list[dict[str, Any]] = []
                for number in message_numbers:
                    # Strictly use BODY.PEEK[] so reading never marks unread messages as \Seen.
                    f_status, parts = client.fetch(number, "(BODY.PEEK[])")
                    if f_status != "OK" or not parts or not isinstance(parts[0], tuple):
                        continue
                    msg_num_str = number.decode("ascii", errors="replace")
                    parsed.append(
                        parse_imap_inbox_message(
                            parts[0][1],
                            unread=(number in unseen_set),
                            fallback_id=msg_num_str,
                        )
                    )
                return group_messages_into_threads(parsed)
        except ConnectorError:
            raise
        except (imaplib.IMAP4.error, OSError) as exc:
            raise ConnectorError(f"IMAP INBOX retrieval failed: {exc}") from exc

    def fetch_inbox_threads(self, limit: int = 25) -> list[dict[str, Any]]:
        """Return thread summaries for the latest INBOX messages."""
        threads = self._fetch_raw_inbox_threads(limit=max(limit * 2, limit))
        return [
            {k: v for k, v in t.items() if k != "messages"}
            for t in threads[:limit]
        ]

    def fetch_thread_messages(self, thread_id: str, limit: int = 100) -> dict[str, Any] | None:
        """Return full chronological messages for one thread_id, or None if missing."""
        threads = self._fetch_raw_inbox_threads(limit=limit)
        for t in threads:
            if t["thread_id"] == thread_id:
                return {
                    "thread_id": t["thread_id"],
                    "subject": t["subject"],
                    "participants": t["participants"],
                    "messages": t["messages"],
                }
        return None

    def send_email(self, payload: OutboundEmailRequest) -> SendReceipt:
        """Send an email via SMTP with proper In-Reply-To and References headers."""
        msg = EmailMessage()
        msg["From"] = self.username
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

        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                server.login(self.username, self.password)
                all_recipients = payload.to + payload.cc + payload.bcc
                server.send_message(msg, from_addr=self.username, to_addrs=all_recipients)
            return SendReceipt(
                message_id=msg["Message-ID"],
                thread_id=payload.thread_id,
                status="sent",
            )
        except Exception as exc:
            return SendReceipt(
                message_id="",
                status="failed",
                error=str(exc),
            )
