"""Autonomous email dispatch with first-recipient gate."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from backend.connectors import (
    BaseEmailConnector,
    ConnectorError,
    GmailConnector,
    ImapConnector,
    LocalMailFileConnector,
    OutlookConnector,
)
from backend.config import Settings
from backend.generation import QwenDrafter
from backend.retrieval import LanceDBVectorStore, LocalEmbedder
from backend.schemas import (
    DispatchRequest,
    DispatchResponse,
    OutboundEmailRequest,
    RecipientProfile,
    SendReceipt,
    UserStyleProfile,
)
from backend.storage import ProfileStore


class Dispatcher:
    """Orchestrates autonomous email dispatch with first-recipient gate."""

    def __init__(self, settings: Settings, connector_factory: Callable[[], BaseEmailConnector] | None = None) -> None:
        self.settings = settings
        self.store = ProfileStore(settings)
        self.drafter = QwenDrafter(settings)
        self.embedder = LocalEmbedder()
        self.vector_store = LanceDBVectorStore(settings)
        self.connector_factory = connector_factory

    def _connector_from_provider(
        self, provider: str, credentials: dict[str, Any] | None = None, file_path: str | None = None
    ) -> BaseEmailConnector:
        """Construct a connector for the given provider."""
        credentials = credentials or {}
        if provider == "gmail":
            client_path = credentials.get("client_secrets_file")
            if not client_path:
                raise ConnectorError("gmail credentials.client_secrets_file is required.")
            return GmailConnector(
                Path(client_path).expanduser(),
                self.store.settings.oauth_token_dir / "gmail_token.json",
            )
        if provider == "outlook":
            return OutlookConnector(
                client_id=str(credentials.get("client_id", "")),
                token_cache_file=self.store.settings.oauth_token_dir / "outlook_token_cache.json",
                tenant_id=str(credentials.get("tenant_id", "common")),
            )
        if provider == "imap":
            return ImapConnector(
                host=str(credentials.get("host", "")),
                username=str(credentials.get("username", "")),
                password=str(credentials.get("password", "")),
                folder=str(credentials.get("folder", "Sent")),
                port=int(credentials.get("port", 993)),
            )
        if provider == "demo":
            return LocalMailFileConnector(Path("local_user_data/demo_outbox.jsonl"))
        path = file_path or credentials.get("file_path")
        if not path:
            raise ConnectorError("mbox requires file_path or credentials.file_path.")
        return LocalMailFileConnector(Path(path).expanduser())

    def connector_for_provider(self, provider: str) -> BaseEmailConnector:
        """Return an injected account-aware connector when supplied, otherwise provider defaults."""
        if provider == "gmail" and self.connector_factory is not None:
            return self.connector_factory()
        return self._connector_from_provider(provider)

    def dispatch(self, request: DispatchRequest) -> DispatchResponse:
        """
        Dispatch an email with first-recipient gate logic.

        Returns PENDING_REVIEW if:
        - Any To recipient has sent_count == 0 (first contact)
        - Any To/Cc recipient has an unseen external domain (when auto_send=False)
        - auto_send is False

        Returns SENT if all recipients are established and auto_send is True.
        """
        draft_id = str(uuid.uuid4())

        # Load user profile
        profile = self.store.load_profile()
        if profile is None:
            return DispatchResponse(
                draft_id=draft_id,
                status="PENDING_REVIEW",
                review_reason="No user profile found. Complete onboarding first.",
                draft=None,
            )

        # Prepare recipient lists
        to_recipients = request.to
        cc_recipients = request.cc
        bcc_recipients = request.bcc
        all_to_cc = to_recipients + cc_recipients

        # Check first-recipient gate
        pending_reasons = []

        # Load recipient profiles for all To/Cc recipients
        recipient_profiles: dict[str, RecipientProfile] = {}
        for email in all_to_cc:
            profile_rec = self.store.get_recipient_profile(email)
            recipient_profiles[email.lower()] = profile_rec

            if profile_rec is None or profile_rec.sent_count == 0:
                pending_reasons.append(f"First contact with {email}")

            # Check for unseen external domain (only block if auto_send=False, since auto-send will upsert)
            domain = email.split("@")[-1].lower() if "@" in email else ""
            if domain and not self._is_known_domain(domain) and not request.auto_send:
                pending_reasons.append(f"Unseen external domain: {domain}")

        if not request.auto_send:
            pending_reasons.append("auto_send is False")

        # Generate draft with audience topology
        try:
            self.embedder.load()
        except Exception as exc:
            return DispatchResponse(
                draft_id=draft_id,
                status="PENDING_REVIEW",
                review_reason=f"Embedder unavailable: {exc}",
                draft=None,
            )

        # Build intent bullets
        intent_bullets = request.intent_bullets

        # Generate draft using the drafter with audience topology
        try:
            draft = self.drafter.generate_draft(
                profile=profile,
                cleaned_emails=self.store.load_cleaned_emails(),
                intent_bullets=intent_bullets,
                recipient_email=to_recipients[0] if to_recipients else None,
                incoming_context=request.incoming_email_context,
                model_name=None,
                cc_recipients=cc_recipients,
                bcc_recipients=bcc_recipients,
                recipient_profiles=recipient_profiles,
            )
        except Exception as exc:
            return DispatchResponse(
                draft_id=draft_id,
                status="PENDING_REVIEW",
                review_reason=f"Draft generation failed: {exc}",
                draft=None,
            )

        # If pending review, save draft to pending queue and return
        if pending_reasons or not request.auto_send:
            from backend.generation.context_resolver import classify_audience

            aud_mode = classify_audience(to_recipients, cc_recipients, bcc_recipients)
            self._save_pending_draft(
                draft_id=draft_id,
                request=request,
                draft=draft,
                profile_id=profile.profile_id,
                recipient_profiles=recipient_profiles,
            )
            self.store.record_pilot_event("draft_generated", audience_type=aud_mode, draft_id=draft_id)
            return DispatchResponse(
                draft_id=draft_id,
                status="PENDING_REVIEW",
                review_reason="; ".join(pending_reasons) if pending_reasons else "auto_send is False",
                draft=draft,
            )

        # Auto-send: dispatch via the account-aware connector when configured.
        outbound = OutboundEmailRequest(
            to=to_recipients,
            cc=cc_recipients,
            bcc=bcc_recipients,
            subject=request.subject,
            body=draft,
            thread_id=request.thread_id,
            in_reply_to=request.in_reply_to,
            references=list(request.references or []),
        )
        try:
            receipt = self.connector_for_provider(request.provider).send_email(outbound)
        except Exception as exc:
            receipt = SendReceipt(message_id="", status="failed", error=str(exc))

        if receipt.status == "sent":
            # Update sent counts and upsert into LanceDB
            for email in all_to_cc:
                self.store.increment_recipient_sent_count(email)

            # Upsert sent email into LanceDB for immediate availability
            from backend.schemas import CleanedSentEmail
            from email.utils import make_msgid

            sent_email = CleanedSentEmail(
                message_id=receipt.message_id or make_msgid(),
                recipient_email=to_recipients[0] if to_recipients else "",
                recipient_domain=to_recipients[0].split("@")[-1] if to_recipients and "@" in to_recipients[0] else "",
                subject=request.subject,
                raw_body=draft,
                clean_body=draft,
                signature="",
                word_count=len(draft.split()),
                timestamp=datetime.now(timezone.utc),
                thread_id=request.thread_id or "",
            )

            # Determine audience mode
            audience_mode = "1on1_private"
            if cc_recipients:
                audience_mode = "group_cc"
            elif bcc_recipients and len(bcc_recipients) >= 2:
                audience_mode = "broadcast_bcc"

            self.vector_store.upsert_sent_email(
                sent_email,
                self.embedder,
                audience_mode=audience_mode,
                cc_count=len(cc_recipients),
                bcc_count=len(bcc_recipients),
            )
            self.store.record_pilot_event("draft_generated", audience_type=audience_mode, draft_id=draft_id)
            self.store.record_pilot_event("draft_sent", audience_type=audience_mode, draft_id=draft_id)

            return DispatchResponse(
                draft_id=draft_id,
                status="SENT",
                receipt=receipt,
                draft=draft,
            )
        else:
            # Send failed - fall back to pending
            self._save_pending_draft(
                draft_id=draft_id,
                request=request,
                draft=draft,
                profile_id=profile.profile_id,
                recipient_profiles=recipient_profiles,
            )
            return DispatchResponse(
                draft_id=draft_id,
                status="PENDING_REVIEW",
                review_reason=f"Send failed: {receipt.error}",
                draft=draft,
            )

    def _is_known_domain(self, domain: str) -> bool:
        """Check if domain has been seen before in sent emails."""
        cleaned = self.store.load_cleaned_emails()
        for email in cleaned:
            if email.recipient_domain == domain:
                return True
        return False

    def _save_pending_draft(
        self,
        draft_id: str,
        request: DispatchRequest,
        draft: str,
        profile_id: str,
        recipient_profiles: dict[str, RecipientProfile],
    ) -> None:
        """Save a pending draft to SQLite for later approval."""
        import json
        with sqlite3.connect(self.store.settings.sqlite_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS pending_drafts (
                    draft_id TEXT PRIMARY KEY,
                    profile_id TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    draft TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    recipient_profiles_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                INSERT INTO pending_drafts (draft_id, profile_id, request_json, draft, created_at, recipient_profiles_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    draft_id,
                    profile_id,
                    json.dumps(request.model_dump(mode="json")),
                    draft,
                    datetime.now(timezone.utc).isoformat(),
                    json.dumps({k: v.model_dump(mode="json") for k, v in recipient_profiles.items() if v is not None}),
                ),
            )

    def load_pending_draft(self, draft_id: str) -> dict[str, Any] | None:
        """Load a pending draft from SQLite."""
        with sqlite3.connect(self.store.settings.sqlite_path) as connection:
            cursor = connection.execute(
                "SELECT draft_id, profile_id, request_json, draft, created_at, recipient_profiles_json FROM pending_drafts WHERE draft_id = ?",
                (draft_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            import json
            return {
                "draft_id": row[0],
                "profile_id": row[1],
                "request": json.loads(row[2]),
                "draft": row[3],
                "created_at": row[4],
                "recipient_profiles": json.loads(row[5]),
            }

    def delete_pending_draft(self, draft_id: str) -> bool:
        """Delete a pending draft after approval."""
        with sqlite3.connect(self.store.settings.sqlite_path) as connection:
            cursor = connection.execute("DELETE FROM pending_drafts WHERE draft_id = ?", (draft_id,))
            return cursor.rowcount > 0


# Import needed modules
import sqlite3
from datetime import datetime, timezone
from email.utils import make_msgid
from backend.schemas import CleanedSentEmail