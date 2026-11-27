"""Zoho Mail connector supporting regional App-Specific Password IMAP/SMTP and optional OAuth2."""

from __future__ import annotations

import email
import imaplib
import smtplib
import time
from email.message import EmailMessage
from email.policy import default
from email.utils import make_msgid
from typing import Any

import httpx

from backend.auth.zoho_oauth import (
    get_zoho_region_config,
    load_zoho_oauth_config,
    load_zoho_tokens,
    refresh_zoho_token,
    save_zoho_tokens,
)
from backend.config import Settings
from backend.connectors.base import BaseEmailConnector, ConnectorError
from backend.connectors.imap_mbox import ImapConnector, email_message_to_raw, html_to_plain_text
from backend.schemas import OutboundEmailRequest, RawSentEmail, SendReceipt


class ZohoMailConnector(BaseEmailConnector):
    """Zoho Mail App-Specific Password IMAP/SMTP connector with regional DC + pro/free fallback."""

    def __init__(
        self,
        email_address: str,
        app_password: str,
        region: str = "in",
        *,
        imap_host: str | None = None,
        smtp_host: str | None = None,
        imap_port: int | None = None,
        smtp_port: int | None = None,
    ) -> None:
        self.email = email_address.strip().lower()
        self.app_password = app_password.strip()
        self.region = (region or "in").strip().lower()
        cfg = get_zoho_region_config(self.region)
        self.imap_host = imap_host or str(cfg["imap_pro"])
        self.smtp_host = smtp_host or str(cfg["smtp_pro"])
        self.imap_free_host = str(cfg["imap_free"])
        self.smtp_free_host = str(cfg["smtp_free"])
        self.imap_port = imap_port or int(cfg["imap_port"])
        self.smtp_port = smtp_port or int(cfg["smtp_port"])

    def _validate_inputs(self) -> None:
        if not self.email or "@" not in self.email:
            raise ConnectorError("A valid Zoho Mail address is required.")
        if not self.app_password:
            raise ConnectorError("A Zoho App-Specific Password is required.")

    def _try_imap_login(self, host: str) -> None:
        with imaplib.IMAP4_SSL(host, self.imap_port) as client:
            client.login(self.email, self.app_password)

    def _try_smtp_login(self, host: str) -> None:
        if self.smtp_port == 465:
            with smtplib.SMTP_SSL(host, self.smtp_port) as client:
                client.login(self.email, self.app_password)
        else:
            with smtplib.SMTP(host, self.smtp_port) as client:
                client.starttls()
                client.login(self.email, self.app_password)

    def test_connection(self) -> dict[str, Any]:
        """Verify IMAP + SMTP login, falling back from imappro/smtppro to imap/smtp for free accounts."""
        self._validate_inputs()
        imap_candidates = [self.imap_host]
        if self.imap_free_host not in imap_candidates:
            imap_candidates.append(self.imap_free_host)

        working_imap: str | None = None
        last_imap_exc: Exception | None = None
        for candidate in imap_candidates:
            try:
                self._try_imap_login(candidate)
                working_imap = candidate
                break
            except (imaplib.IMAP4.error, OSError) as exc:
                last_imap_exc = exc
        if working_imap is None:
            raise ConnectorError("Zoho IMAP sign-in failed. Check your email, region, and App Password.") from last_imap_exc
        self.imap_host = working_imap

        smtp_candidates = [self.smtp_host]
        if working_imap == self.imap_free_host and self.smtp_free_host in smtp_candidates:
            smtp_candidates = [self.smtp_free_host]
        elif self.smtp_free_host not in smtp_candidates:
            smtp_candidates.append(self.smtp_free_host)
        if working_imap == self.imap_free_host and self.smtp_free_host != self.smtp_host:
            # Prefer matching free SMTP host when free IMAP host succeeded
            smtp_candidates = [self.smtp_free_host, self.smtp_host]

        working_smtp: str | None = None
        last_smtp_exc: Exception | None = None
        for candidate in smtp_candidates:
            try:
                self._try_smtp_login(candidate)
                working_smtp = candidate
                break
            except (smtplib.SMTPException, OSError) as exc:
                last_smtp_exc = exc
        if working_smtp is None:
            raise ConnectorError("Zoho SMTP sign-in failed. Check your email, region, and App Password.") from last_smtp_exc
        self.smtp_host = working_smtp

        return {
            "ok": True,
            "provider": "zoho",
            "region": self.region,
            "imap_host": self.imap_host,
            "smtp_host": self.smtp_host,
        }

    @staticmethod
    def _sent_folder(client: imaplib.IMAP4_SSL) -> str:
        for candidate in ("Sent", '"Sent"', "Sent Mail", '"Sent Mail"', "Sent Items"):
            status, _ = client.select(candidate, readonly=True)
            if status == "OK":
                return candidate
        status, folders = client.list()
        if status == "OK":
            for raw in folders or []:
                line = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
                if "\\Sent" not in line:
                    continue
                delimiter = '"' if '"' in line else ""
                mailbox = line.rsplit(delimiter, 2)[-2] if delimiter else line.rsplit(" ", 1)[-1]
                st, _ = client.select(mailbox, readonly=True)
                if st == "OK":
                    return mailbox
        raise ConnectorError("Unable to locate Zoho Sent folder.")

    def fetch_sent_emails(self, limit: int = 200) -> list[RawSentEmail]:
        self._validate_inputs()
        try:
            with imaplib.IMAP4_SSL(self.imap_host, self.imap_port) as client:
                client.login(self.email, self.app_password)
                self._sent_folder(client)
                status, data = client.search(None, "ALL")
                if status != "OK":
                    raise ConnectorError("Unable to search Zoho Sent folder.")
                numbers = (data[0] if data and data[0] else b"").split()[-max(1, min(limit, 500)):]
                records: list[RawSentEmail] = []
                for number in reversed(numbers):
                    msg_num = number.decode("ascii", errors="replace")
                    f_status, parts = client.fetch(msg_num, "(BODY.PEEK[])")
                    if f_status != "OK" or not parts or not isinstance(parts[0], tuple):
                        continue
                    msg = email.message_from_bytes(parts[0][1], policy=default)
                    records.append(email_message_to_raw(msg, msg_num))
                return records
        except ConnectorError:
            raise
        except (imaplib.IMAP4.error, OSError) as exc:
            raise ConnectorError(f"Unable to retrieve Zoho Sent mail: {exc}") from exc

    def _imap_delegate(self) -> ImapConnector:
        return ImapConnector(
            host=self.imap_host,
            username=self.email,
            password=self.app_password,
            folder="INBOX",
            port=self.imap_port,
            smtp_host=self.smtp_host,
            smtp_port=self.smtp_port,
        )

    def fetch_inbox_threads(self, limit: int = 25) -> list[dict[str, Any]]:
        self._validate_inputs()
        return self._imap_delegate().fetch_inbox_threads(limit=limit)

    def fetch_thread_messages(self, thread_id: str, limit: int = 100) -> dict[str, Any] | None:
        self._validate_inputs()
        return self._imap_delegate().fetch_thread_messages(thread_id=thread_id, limit=limit)

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
        self._validate_inputs()
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
        msg = EmailMessage()
        msg["From"] = self.email
        msg["To"] = ", ".join(req.to)
        if req.cc:
            msg["Cc"] = ", ".join(req.cc)
        if req.bcc:
            msg["Bcc"] = ", ".join(req.bcc)
        msg["Subject"] = req.subject
        msg["Message-ID"] = make_msgid()
        if req.in_reply_to:
            msg["In-Reply-To"] = req.in_reply_to
        elif req.thread_id and str(req.thread_id).startswith("<"):
            msg["In-Reply-To"] = req.thread_id
        if req.references:
            msg["References"] = " ".join(req.references)
        elif req.thread_id and str(req.thread_id).startswith("<"):
            msg["References"] = req.thread_id
        elif req.in_reply_to:
            msg["References"] = req.in_reply_to
        msg.set_content(req.body, subtype="plain")

        try:
            all_recipients = req.to + req.cc + req.bcc
            if self.smtp_port == 465:
                with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port) as client:
                    client.login(self.email, self.app_password)
                    client.send_message(msg, from_addr=self.email, to_addrs=all_recipients)
            else:
                with smtplib.SMTP(self.smtp_host, self.smtp_port) as client:
                    client.starttls()
                    client.login(self.email, self.app_password)
                    client.send_message(msg, from_addr=self.email, to_addrs=all_recipients)
            return SendReceipt(message_id=msg["Message-ID"], thread_id=req.thread_id, status="sent")
        except (smtplib.SMTPException, OSError) as exc:
            return SendReceipt(message_id="", thread_id=req.thread_id, status="failed", error=str(exc))


class ZohoOAuthConnector(BaseEmailConnector):
    """Optional Zoho Mail REST API connector authenticated with Zoho OAuth2."""

    def __init__(
        self,
        access_token: str | None = None,
        *,
        region: str = "in",
        zoho_account_id: str = "",
        email_address: str = "",
        acc_settings: Settings | None = None,
        root_settings: Settings | None = None,
        token_data: dict[str, Any] | None = None,
    ) -> None:
        self.region = (region or "in").strip().lower()
        self.zoho_account_id = zoho_account_id
        self.email = email_address.strip().lower()
        self.acc_settings = acc_settings
        self.root_settings = root_settings or acc_settings
        self._token_data: dict[str, Any] = dict(token_data or {})
        if access_token:
            self._token_data.setdefault("access_token", access_token)
            self._token_data.setdefault("expires_at", time.time() + 3600)

    def _load_token_data(self) -> dict[str, Any]:
        if not self._token_data and self.acc_settings is not None:
            loaded = load_zoho_tokens(self.acc_settings)
            if loaded:
                self._token_data = loaded
        if not self._token_data or not self._token_data.get("access_token"):
            raise ConnectorError("Zoho OAuth token is missing.")
        return self._token_data

    def _access_token(self) -> str:
        data = self._load_token_data()
        expires_at = float(data.get("expires_at", 0) or 0)
        if expires_at and (expires_at - 60.0) <= time.time():
            refresh_tok = str(data.get("refresh_token", "") or "").strip()
            if not refresh_tok or self.root_settings is None:
                raise ConnectorError("Zoho OAuth token expired and cannot be refreshed.")
            cfg = load_zoho_oauth_config(self.root_settings)
            if not cfg:
                raise ConnectorError("Zoho OAuth client config is missing.")
            refreshed = refresh_zoho_token(cfg, refresh_tok)
            self._token_data = refreshed
            if self.acc_settings is not None:
                save_zoho_tokens(self.acc_settings, refreshed)
        return str(self._token_data["access_token"])

    def _api_base(self) -> str:
        return str(get_zoho_region_config(self.region)["mail_api_base"])

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Zoho-oauthtoken {self._access_token()}", "Accept": "application/json"}

    def _resolve_zoho_account_id(self) -> str:
        if self.zoho_account_id:
            return self.zoho_account_id
        data = self._load_token_data()
        if data.get("zoho_account_id"):
            self.zoho_account_id = str(data["zoho_account_id"])
            return self.zoho_account_id
        resp = httpx.get(f"{self._api_base()}/api/accounts", headers=self._headers(), timeout=15.0)
        resp.raise_for_status()
        accts = resp.json().get("data") or []
        if not accts:
            raise ConnectorError("No Zoho Mail account found for this OAuth token.")
        self.zoho_account_id = str(accts[0].get("accountId", ""))
        if not self.email:
            self.email = str(accts[0].get("primaryEmailAddress", "")).strip().lower()
        return self.zoho_account_id

    def test_connection(self) -> dict[str, Any]:
        acct_id = self._resolve_zoho_account_id()
        return {"ok": True, "provider": "zoho", "region": self.region, "zoho_account_id": acct_id}

    def fetch_sent_emails(self, limit: int = 200) -> list[RawSentEmail]:
        acct_id = self._resolve_zoho_account_id()
        resp = httpx.get(
            f"{self._api_base()}/api/accounts/{acct_id}/messages/view",
            params={"limit": max(1, min(limit, 200)), "status": "sent"},
            headers=self._headers(),
            timeout=30.0,
        )
        resp.raise_for_status()
        items = resp.json().get("data") or []
        records: list[RawSentEmail] = []
        for item in items:
            to_raw = str(item.get("toAddress", "") or "")
            recipient = to_raw.split(",")[0].strip().lower()
            content = str(item.get("content", "") or item.get("summary", "") or "")
            records.append(
                RawSentEmail(
                    message_id=str(item.get("messageId", "")),
                    recipient_email=recipient,
                    subject=str(item.get("subject", "") or ""),
                    raw_body=html_to_plain_text(content) if "<" in content else content,
                    thread_id=str(item.get("threadId", "") or ""),
                )
            )
        return records[:limit]

    def fetch_inbox_threads(self, limit: int = 25) -> list[dict[str, Any]]:
        acct_id = self._resolve_zoho_account_id()
        resp = httpx.get(
            f"{self._api_base()}/api/accounts/{acct_id}/messages/view",
            params={"limit": max(1, min(limit * 2, 100))},
            headers=self._headers(),
            timeout=30.0,
        )
        resp.raise_for_status()
        items = resp.json().get("data") or []
        threads: dict[str, dict[str, Any]] = {}
        for item in items:
            tid = str(item.get("threadId") or item.get("messageId", ""))
            sender = str(item.get("sender", "") or "").strip()
            from_addr = str(item.get("fromAddress", "") or "").strip().lower()
            entry = threads.setdefault(
                tid,
                {
                    "thread_id": tid,
                    "subject": str(item.get("subject", "") or "(no subject)"),
                    "snippet": str(item.get("summary", "") or "")[:160],
                    "last_message_at": str(item.get("receivedTime", "") or ""),
                    "message_count": 0,
                    "participants": [],
                    "unread": str(item.get("status", "")).lower() == "unread",
                    "latest_sender_name": sender or from_addr,
                    "latest_sender_email": from_addr,
                },
            )
            entry["message_count"] += 1
            if from_addr and from_addr not in entry["participants"]:
                entry["participants"].append(from_addr)
        return list(threads.values())[:limit]

    def fetch_thread_messages(self, thread_id: str, limit: int = 100) -> dict[str, Any] | None:
        acct_id = self._resolve_zoho_account_id()
        resp = httpx.get(
            f"{self._api_base()}/api/accounts/{acct_id}/threads/{thread_id}",
            headers=self._headers(),
            timeout=30.0,
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        items = resp.json().get("data") or []
        if not items:
            return None
        messages = []
        participants: list[str] = []
        for item in items[:limit]:
            from_addr = str(item.get("fromAddress", "") or "").strip().lower()
            if from_addr and from_addr not in participants:
                participants.append(from_addr)
            messages.append(
                {
                    "message_id": str(item.get("messageId", "")),
                    "from_name": str(item.get("sender", "") or from_addr),
                    "from_email": from_addr,
                    "to": [a.strip().lower() for a in str(item.get("toAddress", "")).split(",") if "@" in a],
                    "cc": [],
                    "date": str(item.get("receivedTime", "") or ""),
                    "subject": str(item.get("subject", "") or ""),
                    "body_text": str(item.get("summary", "") or ""),
                    "in_reply_to": "",
                    "references": [],
                }
            )
        return {
            "thread_id": thread_id,
            "subject": messages[0]["subject"] or "(no subject)",
            "participants": participants,
            "messages": messages,
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
        req = self._coerce_outbound_request(
            payload, to=to, subject=subject, body=body, cc=cc, bcc=bcc,
            in_reply_to=in_reply_to, references=references, thread_id=thread_id,
        )
        acct_id = self._resolve_zoho_account_id()
        body_json: dict[str, Any] = {
            "fromAddress": self.email,
            "toAddress": ",".join(req.to),
            "subject": req.subject,
            "content": req.body,
            "mailFormat": "plaintext",
        }
        if req.cc:
            body_json["ccAddress"] = ",".join(req.cc)
        if req.bcc:
            body_json["bccAddress"] = ",".join(req.bcc)
        try:
            resp = httpx.post(
                f"{self._api_base()}/api/accounts/{acct_id}/messages",
                json=body_json,
                headers=self._headers(),
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json().get("data", {})
            return SendReceipt(message_id=str(data.get("messageId", "")), thread_id=req.thread_id, status="sent")
        except Exception as exc:
            return SendReceipt(message_id="", thread_id=req.thread_id, status="failed", error=str(exc))
