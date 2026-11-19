"""Style learning from user edits via diff-based delta extraction."""

from __future__ import annotations

import difflib
import json
import re
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import httpx

from backend.config import Settings
from backend.schemas import ApproveAndLearnRequest, ApproveAndLearnResponse, RecipientProfile, SendReceipt, UserStyleProfile
from backend.storage import ProfileStore


class StyleLearner:
    """Extracts atomic style rules from user edits using qwen3:8b deep reasoning (think=True)."""

    LEARN_SYSTEM_PROMPT = """You are a style rule extractor for a personalized email writer.
Given a diff between an AI-generated draft and a user-edited final version, extract 1-2 concise, atomic style rules.
Rules must be specific, actionable, and generalizable (not about specific facts/numbers/dates).
Ignore factual corrections, number/date changes, or content additions - focus ONLY on style, tone, formatting, and phrasing patterns.
Each rule should be a single sentence describing a writing habit.
Retire any conflicting older rule when adding a new one."""

    def __init__(self, settings: Settings, connector_factory: Callable[[], Any] | None = None) -> None:
        self.settings = settings
        self.store = ProfileStore(settings)
        self.connector_factory = connector_factory

    def approve_and_learn(self, request: ApproveAndLearnRequest) -> ApproveAndLearnResponse:
        """
        Process user-approved draft, extract style rules from diff, and dispatch the final email.
        """
        # Load pending draft
        pending = self.store.load_pending_draft(request.draft_id)
        if not pending:
            return ApproveAndLearnResponse(
                status="FAILED",
                extracted_rules=[],
                rule_scope="global",
            )

        original_draft = pending["draft"]
        request_data = pending["request"]
        profile_id = pending["profile_id"]
        recipient_profiles_data = pending.get("recipient_profiles", {})

        # Load user profile
        profile = self.store.load_profile()
        if not profile:
            return ApproveAndLearnResponse(
                status="FAILED",
                extracted_rules=[],
                rule_scope="global",
            )

        # Compute unified diff
        diff = self._compute_diff(original_draft, request.final_body)

        # Extract style rules using qwen3:8b deep reasoning
        rules = []
        if diff.strip():
            rules = self._extract_rules_from_diff(diff, request)

        # Apply rules to recipient profiles or global profile
        rule_scope = "global"
        for rule in rules:
            # Determine if rule is recipient-specific or global
            # Heuristic: if rule mentions a specific person/domain, it's recipient-specific
            is_recipient_specific = any(
                word in rule.lower() for word in ["recipient", "client", "executive", "to ", "for "]
            )

            if is_recipient_specific and request_data.get("to"):
                primary_to = request_data["to"][0]
                self.store.add_learned_rule(primary_to, rule)
                rule_scope = "recipient"
            else:
                self.store.add_global_learned_rule(rule)
                rule_scope = "global"

        # Update relationship tier if provided
        if request.relationship_tier_override and request_data.get("to"):
            primary_to = request_data["to"][0]
            recip_profile = self.store.get_recipient_profile(primary_to)
            if recip_profile:
                recip_profile.relationship_tier = request.relationship_tier_override
                self.store.upsert_recipient_profile(recip_profile)

        # Dispatch the final email
        from backend.automation.dispatcher import Dispatcher
        from backend.connectors import (
            BaseEmailConnector,
            ConnectorError,
            GmailConnector,
            ImapConnector,
            LocalMailFileConnector,
            OutlookConnector,
        )
        from backend.schemas import OutboundEmailRequest, DispatchRequest

        dispatcher = Dispatcher(self.settings, connector_factory=self.connector_factory)
        connector = dispatcher.connector_for_provider(request_data["provider"])

        outbound = OutboundEmailRequest(
            to=request_data["to"],
            cc=request_data.get("cc", []),
            bcc=request_data.get("bcc", []),
            subject=request.final_subject,
            body=request.final_body,
            thread_id=request_data.get("thread_id"),
            in_reply_to=request_data.get("in_reply_to"),
        )

        try:
            receipt = connector.send_email(outbound)
        except Exception as exc:
            receipt = SendReceipt(message_id="", status="failed", error=str(exc))

        if receipt.status == "sent":
            # Update sent counts and upsert into LanceDB
            all_to_cc = request_data["to"] + request_data.get("cc", [])
            for email in all_to_cc:
                self.store.increment_recipient_sent_count(email)

            # Upsert sent email into LanceDB
            from backend.schemas import CleanedSentEmail
            from email.utils import make_msgid
            from backend.retrieval import LanceDBVectorStore
            from backend.retrieval.embedder import LocalEmbedder

            sent_email = CleanedSentEmail(
                message_id=receipt.message_id or make_msgid(),
                recipient_email=request_data["to"][0] if request_data["to"] else "",
                recipient_domain=request_data["to"][0].split("@")[-1] if request_data["to"] and "@" in request_data["to"][0] else "",
                subject=request.final_subject,
                raw_body=request.final_body,
                clean_body=request.final_body,
                signature="",
                word_count=len(request.final_body.split()),
                timestamp=datetime.now(timezone.utc),
                thread_id=request_data.get("thread_id") or "",
            )

            # Determine audience mode
            audience_mode = "1on1_private"
            if request_data.get("cc"):
                audience_mode = "group_cc"
            elif request_data.get("bcc") and len(request_data["bcc"]) >= 2:
                audience_mode = "broadcast_bcc"

            embedder = LocalEmbedder()
            try:
                embedder.load()
            except Exception:
                pass  # Embedder might already be loaded

            vector_store = LanceDBVectorStore(self.settings)
            vector_store.upsert_sent_email(
                sent_email,
                embedder,
                audience_mode=audience_mode,
                cc_count=len(request_data.get("cc", [])),
                bcc_count=len(request_data.get("bcc", [])),
            )

            # Mark the persisted review card as sent so reopening the session stays consistent.
            from backend.storage.chat_sessions import ChatSessionStore

            ChatSessionStore(self.settings.chat_sessions_path).update_draft_card_by_draft_id(
                request.draft_id,
                subject=request.final_subject,
                body=request.final_body,
                status="SENT",
            )

            # Clean up pending draft
            self.store.delete_pending_draft(request.draft_id)

            return ApproveAndLearnResponse(
                status="SENT",
                receipt=receipt,
                extracted_rules=rules,
                rule_scope=rule_scope,
            )
        else:
            return ApproveAndLearnResponse(
                status="FAILED",
                receipt=receipt,
                extracted_rules=rules,
                rule_scope=rule_scope,
            )

    def _compute_diff(self, original: str, final: str) -> str:
        """Compute unified diff between original and final text."""
        original_lines = original.splitlines(keepends=True)
        final_lines = final.splitlines(keepends=True)
        diff = difflib.unified_diff(original_lines, final_lines, lineterm="")
        return "\n".join(diff)

    def _extract_rules_from_diff(self, diff: str, request: ApproveAndLearnRequest) -> list[str]:
        """Extract 1-2 atomic style rules from the diff using qwen3:8b with think=True."""
        endpoint = f"{self.settings.ollama_url.rstrip('/')}/api/chat"

        # Build prompt with diff and context
        prompt = (
            f"Original AI Draft vs User-Edited Final Version:\n\n"
            f"--- DIFF ---\n{diff}\n\n"
            f"User's relationship tier override: {request.relationship_tier_override or 'none'}\n\n"
            f"Extract 1-2 atomic style rules from this diff. Rules must:\n"
            f"1. Be specific, actionable, and generalizable\n"
            f"2. Focus ONLY on style/tone/formatting/phrasing (ignore factual/number/date changes)\n"
            f"3. Each rule = one sentence describing a writing habit\n"
            f"4. Retire any conflicting older rule\n\n"
            f"Return ONLY a JSON array of strings, e.g.:\n"
            f'["Use concise bullet points for action items", "Address executives with formal titles"]'
        )

        messages = [
            {"role": "system", "content": self.LEARN_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

        try:
            response = httpx.post(
                endpoint,
                json={
                    "model": self.settings.ollama_fallback_model,  # Use qwen3:8b
                    "messages": messages,
                    "stream": False,
                    "options": {
                        "temperature": 0.6,
                        "top_p": 0.95,
                        "top_k": 20,
                        "num_ctx": self.settings.ollama_num_ctx,
                        "think": True,  # Deep reasoning for rule extraction
                    },
                },
                timeout=180,
            )

            if response.status_code == 404:
                return []

            response.raise_for_status()
            content = response.json().get("message", {}).get("content", "")

            # Strip thinking blocks
            if "question" in content and "answer" in content:
                content = re.sub(r"question.*?answer", "", content, flags=re.DOTALL).strip()

            # Parse JSON array
            try:
                rules = json.loads(content)
                if isinstance(rules, list):
                    return [str(r).strip() for r in rules if str(r).strip()][:2]
            except json.JSONDecodeError:
                pass

        except Exception:
            pass

        return []


import re
import sqlite3
from datetime import datetime, timezone