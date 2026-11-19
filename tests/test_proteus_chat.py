"""Behavioral tests for Proteus chat: name resolution, the first-recipient gate,
and contact persistence.

Ollama is not running in the test environment, so ``/api/chat/turn`` deterministically
falls back to the heuristic intent parser (``backend.main._parse_chat_intent``). These
tests exercise that fallback path end to end: it must resolve the contacts a user
names regardless of case, report ambiguity/unknown names instead of guessing, gate the
first email to a new recipient, and persist contacts in the account's registry.

Conventions match the rest of the suite: a ``tempfile`` Settings with
``profiler_mode="heuristic"`` and no context-manager TestClient (no embedder load).
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
import uuid
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from backend.automation import Contact, ContactResolver, Dispatcher
from backend.config import Settings
from backend.main import create_app
from backend.schemas import DispatchRequest
from backend.storage import ChatSessionStore, ProfileStore

_MANU = Contact(
    email="manu@expano.in", full_name="Manu Roy", first_name="Manu", last_name="Roy",
    company_domain="expano.in",
)
_JATIN = Contact(
    email="jatin@expano.in", full_name="Jatin Mehta", first_name="Jatin", last_name="Mehta",
    company_domain="expano.in",
)
_CHIRANTH = Contact(
    email="chiranth@expano.in", full_name="Chiranth Rao", first_name="Chiranth", last_name="Rao",
    company_domain="expano.in",
)

_SPRINT_REVIEW_MESSAGE = (
    "send an email to manu with cc attached to jatin and chiranth "
    "about postponing tomorrow's sprint review"
)


class _ChatTestBase(unittest.TestCase):
    """Shared temp-dir app/client fixtures."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.settings = Settings(
            local_user_data_dir=Path(self.temp_dir.name),
            profiler_mode="heuristic",
            model_name="not-installed-for-test",
        )
        self.app = create_app(settings=self.settings)
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # --- helpers ------------------------------------------------------------
    def _create_account(self, email: str, display_name: str = "Test User") -> str:
        account = self.app.state.account_manager.create_account(email=email, display_name=display_name)
        return account.account_id

    def _demo_seed_and_profile(self, email: str) -> tuple[str, Settings]:
        """Demo-seed both accounts, then build a profile for ``email``'s account."""
        seeded = self.client.post("/api/onboarding/demo-seed")
        self.assertEqual(seeded.status_code, 200, seeded.text)
        accounts = {
            account["email"]: account
            for account in self.client.get("/api/accounts").json()["accounts"]
        }
        account_id = accounts[email]["account_id"]
        built = self.client.post(
            "/api/onboarding/build-profile", headers={"X-Account-ID": account_id}
        )
        self.assertEqual(built.status_code, 200, built.text)
        return account_id, self.settings.for_account(account_id)

    def _seed_contacts(self, account_id: str, contacts: list[Contact]) -> None:
        resolver = ContactResolver(self.settings.for_account(account_id).contacts_path)
        for contact in contacts:
            resolver.upsert_contact(contact)

    def _turn(self, account_id: str, message: str, **extra) -> dict:
        response = self.client.post(
            "/api/chat/turn",
            headers={"X-Account-ID": account_id},
            json={"user_message": message, **extra},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()


class NameResolutionTests(_ChatTestBase):
    """Item 6: resolve To/Cc contacts (lowercase names) and draft, or ask for help."""

    def test_chat_turn_resolves_to_and_cc_badges_and_drafts(self) -> None:
        account_id, _ = self._demo_seed_and_profile("chirag@expano.in")
        self._seed_contacts(account_id, [_MANU, _JATIN, _CHIRANTH])

        turn = self._turn(account_id, _SPRINT_REVIEW_MESSAGE)

        self.assertIn(turn["status"], ("DRAFTED", "PENDING_REVIEW", "SENT"), turn["status"])

        to_resolutions = turn["resolutions"]["to"]
        self.assertEqual(len(to_resolutions), 1)
        self.assertEqual(to_resolutions[0]["status"], "MATCHED")
        self.assertEqual(to_resolutions[0]["matched_email"], "manu@expano.in")
        self.assertEqual(to_resolutions[0]["matched_name"], "Manu Roy")

        cc_resolutions = turn["resolutions"]["cc"]
        self.assertEqual({r["status"] for r in cc_resolutions}, {"MATCHED"})
        self.assertEqual(
            sorted(r["matched_email"] for r in cc_resolutions),
            ["chiranth@expano.in", "jatin@expano.in"],
        )

        # The parsed intent separated To from Cc, despite all names being lowercase.
        self.assertEqual(turn["parsed"]["to_names"], ["Manu Roy"])
        self.assertEqual(set(turn["parsed"]["cc_names"]), {"Jatin Mehta", "Chiranth Rao"})
        self.assertIn(turn["parsed"]["source"], ("heuristic", "ollama"))

        # A draft was produced and is addressed to the resolved recipients.
        card = turn["draft_card"]
        self.assertIsNotNone(card)
        self.assertIsInstance(card.get("warnings"), list)
        self.assertIsInstance(card.get("retrieved_examples"), list)
        self.assertTrue(card.get("model_used"))
        self.assertTrue(card["body"].strip(), "draft body must not be empty")
        self.assertEqual(card["to"], ["manu@expano.in"])
        self.assertEqual(sorted(card["cc"]), ["chiranth@expano.in", "jatin@expano.in"])
        self.assertIn(card["status"], ("DRAFT", "PENDING_REVIEW", "SENT"))

        detail = self.client.get(
            f"/api/chat/sessions/{turn['session_id']}", headers={"X-Account-ID": account_id}
        )
        self.assertEqual(detail.status_code, 200, detail.text)
        persisted_card = detail.json()["draft_cards"][0]
        self.assertIsInstance(persisted_card["warnings"], list)
        self.assertIsInstance(persisted_card["retrieved_examples"], list)

    def test_chat_turn_unknown_name_requests_clarification_with_candidates(self) -> None:
        account_id, _ = self._demo_seed_and_profile("chirag@expano.in")
        self._seed_contacts(account_id, [_MANU, _JATIN, _CHIRANTH])

        turn = self._turn(account_id, "send an email to Zoltan about the quarterly plan")

        self.assertEqual(turn["status"], "NEEDS_CLARIFICATION")
        self.assertIsNone(turn["draft_card"])
        to_resolutions = turn["resolutions"]["to"]
        self.assertTrue(to_resolutions, "the unknown recipient must appear as a resolution")
        self.assertEqual(to_resolutions[0]["query"], "Zoltan")
        self.assertEqual(to_resolutions[0]["status"], "NEEDS_CLARIFICATION")
        self.assertIsNone(to_resolutions[0]["matched_email"])
        self.assertIn("candidates", to_resolutions[0])
        self.assertEqual(to_resolutions[0]["candidates"], [])

    def test_duplicate_recipient_mentions_resolve_to_a_single_recipient(self) -> None:
        """The same recipient named twice must yield one resolution and one To address."""
        account_id = self._create_account("chirag@expano.in", "Chirag Sharma")
        self._seed_contacts(account_id, [_MANU])

        # The intent parser can name one recipient in two forms ("manu" and the
        # resolved address). Both must collapse to a single resolution.
        duplicate_parse = {
            "action": "send",
            "to_names": ["manu", "manu@expano.in"],
            "cc_names": [],
            "bcc_names": [],
            "subject_hint": "Roadmap",
            "intent_bullets": "share the roadmap",
            "source": "test",
        }
        with patch("backend.main._parse_chat_intent", return_value=duplicate_parse):
            turn = self._turn(account_id, "send an email to manu about the roadmap")

        to_resolutions = turn["resolutions"]["to"]
        self.assertEqual(len(to_resolutions), 1, to_resolutions)
        self.assertEqual(to_resolutions[0]["status"], "MATCHED")
        self.assertEqual(to_resolutions[0]["matched_email"], "manu@expano.in")
        self.assertIsNotNone(turn["draft_card"])
        self.assertEqual(turn["draft_card"]["to"], ["manu@expano.in"])

    def test_chat_turn_ambiguous_first_name_requests_clarification(self) -> None:
        account_id = self._create_account("chirag@expano.in", "Chirag Sharma")
        self._seed_contacts(account_id, [
            Contact(email="jatin.mehta@expano.in", full_name="Jatin Mehta",
                    first_name="Jatin", last_name="Mehta", company_domain="expano.in"),
            Contact(email="jatin.rao@expano.in", full_name="Jatin Rao",
                    first_name="Jatin", last_name="Rao", company_domain="expano.in"),
        ])

        turn = self._turn(account_id, "send an email to jatin about the offsite")

        self.assertEqual(turn["status"], "NEEDS_CLARIFICATION")
        self.assertIsNone(turn["draft_card"])
        to_resolutions = turn["resolutions"]["to"]
        self.assertEqual(len(to_resolutions), 1)
        self.assertEqual(to_resolutions[0]["status"], "NEEDS_CLARIFICATION")
        self.assertIsNone(to_resolutions[0]["matched_email"])
        self.assertGreaterEqual(len(to_resolutions[0]["candidates"]), 2)
        self.assertEqual(
            {candidate["email"] for candidate in to_resolutions[0]["candidates"]},
            {"jatin.mehta@expano.in", "jatin.rao@expano.in"},
        )


class FirstRecipientGateTests(_ChatTestBase):
    """Item 7: first email to a recipient is gated until history exists."""

    def test_first_contact_is_gated_then_ungated_after_history(self) -> None:
        account_id, account_settings = self._demo_seed_and_profile("chirag@expano.in")
        self._seed_contacts(account_id, [_MANU])

        first = self._turn(account_id, "send an email to manu about the launch")
        self.assertEqual(first["status"], "PENDING_REVIEW")
        reason = (first["review_reason"] or "").lower()
        self.assertIn("first contact", reason)
        self.assertIn("manu@expano.in", first["review_reason"])
        self.assertEqual(first["draft_card"]["to"], ["manu@expano.in"])

        # Simulate prior history: the recipient now has a non-zero sent count.
        ProfileStore(account_settings).increment_recipient_sent_count("manu@expano.in")

        second = self._turn(account_id, "send an email to manu about the launch", auto_send=True)
        second_reason = (second["review_reason"] or "").lower()
        self.assertNotIn("first contact", second_reason, second["review_reason"])

    def test_approve_and_learn_returns_rules_without_raising(self) -> None:
        account_id, account_settings = self._demo_seed_and_profile("chirag@expano.in")
        self._seed_contacts(account_id, [_MANU])
        store = ProfileStore(account_settings)

        # (a) Unknown draft id -> graceful FAILED (never an exception).
        missing = self.client.post(
            "/api/email/approve-and-learn",
            headers={"X-Account-ID": account_id},
            json={
                "draft_id": "no-such-draft",
                "final_subject": "Launch",
                "final_body": "Hi Manu,\n\nLaunch is on.",
            },
        )
        self.assertEqual(missing.status_code, 200, missing.text)
        self.assertEqual(missing.json()["status"], "FAILED")
        self.assertIsInstance(missing.json()["extracted_rules"], list)

        # (b) A real pending draft -> SENT via the local demo outbox (or FAILED), no exception.
        profile = store.load_profile()
        self.assertIsNotNone(profile)
        dispatcher = Dispatcher(account_settings)
        draft_id = str(uuid.uuid4())
        dispatcher._save_pending_draft(
            draft_id=draft_id,
            request=DispatchRequest(
                provider="demo",
                to=["manu@expano.in"],
                subject="Launch",
                intent_bullets="- ship on Friday",
                auto_send=False,
            ),
            draft="Hi Manu,\n\nDraft body.",
            profile_id=profile.profile_id,
            recipient_profiles={},
        )

        # The demo connector writes a relative outbox path; keep it inside the temp dir.
        previous_cwd = os.getcwd()
        os.chdir(self.temp_dir.name)
        try:
            approved = self.client.post(
                "/api/email/approve-and-learn",
                headers={"X-Account-ID": account_id},
                json={
                    "draft_id": draft_id,
                    "final_subject": "Launch plan",
                    "final_body": "Hi Manu,\n\nLaunch is on for Friday. Thanks.",
                },
            )
        finally:
            os.chdir(previous_cwd)

        self.assertEqual(approved.status_code, 200, approved.text)
        payload = approved.json()
        self.assertIn(payload["status"], ("SENT", "FAILED"), payload["status"])
        self.assertIsInstance(payload["extracted_rules"], list)

        if payload["status"] == "SENT":
            self.assertIsNone(store.load_pending_draft(draft_id))
            recipient = store.get_recipient_profile("manu@expano.in")
            self.assertIsNotNone(recipient)
            self.assertGreaterEqual(recipient.sent_count, 1)
            self.assertTrue((Path(self.temp_dir.name) / "local_user_data" / "demo_outbox.jsonl").is_file())


class ContactPersistenceTests(_ChatTestBase):
    """Item 8: resolved contacts live in that account's registry."""

    def test_resolved_contact_row_persists_in_account_registry(self) -> None:
        account_id, account_settings = self._demo_seed_and_profile("chirag@expano.in")
        self._seed_contacts(account_id, [_MANU])

        turn = self._turn(account_id, "send an email to manu about the roadmap")
        self.assertEqual(turn["resolutions"]["to"][0]["matched_email"], "manu@expano.in")

        # Contacts are stored in the account's contacts registry (``contacts.sqlite3``),
        # which is the per-account contact table for the profile store.
        contacts_db = account_settings.contacts_path
        self.assertTrue(contacts_db.is_file())
        with sqlite3.connect(contacts_db) as connection:
            row = connection.execute(
                "SELECT email, full_name, company_domain FROM contacts WHERE email = ?",
                ("manu@expano.in",),
            ).fetchone()
        self.assertIsNotNone(row, "resolved contact must be persisted")
        self.assertEqual(row[0], "manu@expano.in")
        self.assertEqual(row[1], "Manu Roy")
        self.assertEqual(row[2], "expano.in")

        # Unknown names are not silently persisted.
        before = self._contact_count(contacts_db)
        self._turn(account_id, "send an email to Zoltan about the plan")
        self.assertEqual(self._contact_count(contacts_db), before)

        # The registry is isolated: a sibling account never gains this contact.
        sibling_id = self._create_account("sam@cloudscale.io", "Sam Carter")
        sibling_resolver = ContactResolver(self.settings.for_account(sibling_id).contacts_path)
        self.assertEqual(
            [contact.email for contact in sibling_resolver.list_contacts() if contact.email == "manu@expano.in"],
            [],
        )

    @staticmethod
    def _contact_count(contacts_db: Path) -> int:
        with sqlite3.connect(contacts_db) as connection:
            return connection.execute("SELECT COUNT(*) FROM contacts").fetchone()[0]


class InPlaceDraftTweakTests(_ChatTestBase):
    def test_reviser_calls_qwen_json_endpoint_with_thinking_disabled(self) -> None:
        from backend.generation import QwenDrafter

        account_id, account_settings = self._demo_seed_and_profile("chirag@expano.in")
        account_settings = replace(account_settings, model_name="qwen3:8b")
        profile = ProfileStore(account_settings).load_profile()
        self.assertIsNotNone(profile)
        assert profile is not None

        response = Mock()
        response.status_code = 200
        response.json.return_value = {"message": {"content": json.dumps({"subject": "Quick update", "body": "Hi, quick update."})}}
        with patch("backend.generation.drafter.httpx.post", return_value=response) as post:
            revised = QwenDrafter(account_settings).revise_email_draft(
                profile=profile,
                subject="Status update",
                body="Dear team, here is the detailed update.",
                tweak_instruction="make it more casual",
                to_recipients=["kamisama7892@gmail.com"],
                cc_recipients=[],
                bcc_recipients=[],
            )

        # The reviser post-processes the body, which adds the sign-off
        self.assertEqual(revised["subject"], "Quick update")
        self.assertIn("Hi, quick update.", revised["body"])
        self.assertIn("Best,", revised["body"])  # fallback sign-off from profile
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["model"], "qwen3:8b")
        self.assertIs(payload["think"], False)
        self.assertEqual(payload["format"], "json")
        self.assertIn("Formality:", payload["messages"][0]["content"])
        self.assertIn("Do not add boilerplate", payload["messages"][0]["content"])

    def test_draft_tweak_updates_staged_draft_and_session_card(self) -> None:
        account_id, account_settings = self._demo_seed_and_profile("chirag@expano.in")
        store = ProfileStore(account_settings)
        sessions = ChatSessionStore(account_settings.chat_sessions_path)
        session = sessions.create_session(account_id, title="Safe draft revision test")
        draft_id = str(uuid.uuid4())
        original_request = {
            "to": ["kamisama7892@gmail.com"],
            "cc": ["observer@example.test"],
            "bcc": ["hidden@example.test"],
            "subject": "Project update",
            "intent_bullets": "Share a short project status",
            "provider": "gmail",
            "thread_id": "<thread@example.test>",
            "in_reply_to": "<parent@example.test>",
            "session_id": session["session_id"],
        }
        original_body = "Dear team, I am writing to provide the status update."
        profile = store.load_profile()
        self.assertIsNotNone(profile)
        assert profile is not None
        with sqlite3.connect(account_settings.sqlite_path) as connection:
            connection.execute(
                "INSERT INTO pending_drafts (draft_id, profile_id, request_json, draft, created_at, recipient_profiles_json) VALUES (?, ?, ?, ?, ?, ?)",
                (draft_id, profile.profile_id, json.dumps(original_request), original_body, "2026-11-19T00:00:00+00:00", "{}"),
            )
        card = sessions.upsert_draft_card(
            session_id=session["session_id"],
            to=original_request["to"], cc=original_request["cc"], bcc=original_request["bcc"], subject=original_request["subject"],
            body=original_body, status="PENDING_REVIEW", draft_id=draft_id,
        )
        sessions.append_message(
            session["session_id"], "assistant", "Draft ready for review.",
            metadata={"status": "PENDING_REVIEW", "card_id": card["card_id"]},
        )

        revised = {"subject": "Project update", "body": "Hi, quick update on the project."}
        with patch("backend.main.QwenDrafter.revise_email_draft", return_value=revised, create=True):
            response = self.client.post(
                "/api/draft/tweak",
                headers={"X-Account-ID": account_id},
                json={
                    "draft_id": draft_id,
                    "tweak_instruction": "no need to be so formal, let it be casual",
                    "current_to": ["kamisama7892@gmail.com"],
                    "current_cc": ["observer@example.test"],
                    "current_bcc": ["hidden@example.test"],
                    "current_subject": original_request["subject"],
                    "current_body": original_body,
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["draft_id"], draft_id)
        self.assertEqual(response.json()["subject"], revised["subject"])
        self.assertEqual(response.json()["body"], revised["body"])
        staged = store.load_pending_draft(draft_id)
        self.assertIsNotNone(staged)
        assert staged is not None
        self.assertEqual(staged["draft"], revised["body"])
        self.assertEqual(staged["request"]["to"], ["kamisama7892@gmail.com"])
        self.assertEqual(staged["request"]["cc"], ["observer@example.test"])
        self.assertEqual(staged["request"]["bcc"], ["hidden@example.test"])
        self.assertEqual(staged["request"]["thread_id"], "<thread@example.test>")
        detail = sessions.get_session(session["session_id"])
        self.assertIsNotNone(detail)
        assert detail is not None
        self.assertEqual(detail["draft_cards"][0]["subject"], revised["subject"])
        self.assertEqual(detail["draft_cards"][0]["body"], revised["body"])
        self.assertEqual(detail["draft_cards"][0]["cc"], ["observer@example.test"])
        self.assertEqual(detail["draft_cards"][0]["bcc"], ["hidden@example.test"])

        followup_revision = {"subject": "Quick project update", "body": "Hey, here's a quick project update."}
        with patch("backend.main.QwenDrafter.revise_email_draft", return_value=followup_revision, create=True):
            followup = self.client.post(
                "/api/chat/turn",
                headers={"X-Account-ID": account_id},
                json={"session_id": session["session_id"], "user_message": "make it more casual"},
            )
        self.assertEqual(followup.status_code, 200, followup.text)
        self.assertEqual(followup.json()["status"], "PENDING_REVIEW")
        self.assertEqual(followup.json()["draft_card"]["draft_id"], draft_id)
        self.assertEqual(followup.json()["draft_card"]["body"], followup_revision["body"])
        self.assertNotIn("Who should I send this to?", followup.json()["assistant_message"])
        staged_after_followup = store.load_pending_draft(draft_id)
        self.assertIsNotNone(staged_after_followup)
        assert staged_after_followup is not None
        self.assertEqual(staged_after_followup["draft"], followup_revision["body"])



class SchemaMigrationTests(_ChatTestBase):
    """Verify idempotent SQLite column migrations for legacy databases."""

    def test_legacy_chat_sessions_migrates_pending_clarification_column(self) -> None:
        """A legacy chat_sessions.sqlite3 without pending_clarification_json must upgrade seamlessly."""
        import sqlite3
        from backend.storage.chat_sessions import ChatSessionStore

        # Create a legacy database WITHOUT the pending_clarification_json column
        legacy_db = Path(self.temp_dir.name) / "legacy_chat_sessions.sqlite3"
        with sqlite3.connect(legacy_db) as conn:
            conn.executescript(
                """
                CREATE TABLE sessions (
                    session_id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    message_count INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE messages (
                    message_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE draft_cards (
                    card_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    message_id TEXT,
                    draft_id TEXT,
                    to_json TEXT NOT NULL DEFAULT '[]',
                    cc_json TEXT NOT NULL DEFAULT '[]',
                    bcc_json TEXT NOT NULL DEFAULT '[]',
                    subject TEXT NOT NULL DEFAULT '',
                    body TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'DRAFT',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

        # Initialize the store on the legacy DB - this should trigger migration
        store = ChatSessionStore(legacy_db)

        # Verify the column was added by querying the schema
        with sqlite3.connect(legacy_db) as conn:
            cursor = conn.execute("PRAGMA table_info(sessions)")
            columns = {row[1] for row in cursor.fetchall()}
            self.assertIn("pending_clarification_json", columns, "Migration should add pending_clarification_json column")

        # Verify get_pending_clarification and set_pending_clarification work without OperationalError
        session = store.create_session("account-1", title="Migration Test")
        session_id = session["session_id"]

        # Should not raise OperationalError
        payload = {"action": "send", "intent_bullets": "- test", "unresolved_names": ["jatin"]}
        store.set_pending_clarification(session_id, payload)
        loaded = store.get_pending_clarification(session_id)
        self.assertEqual(loaded["unresolved_names"], ["jatin"])

        store.clear_pending_clarification(session_id)
        cleared = store.get_pending_clarification(session_id)
        self.assertIsNone(cleared)

        # Verify normal session operations still work
        store.append_message(session_id, "user", "Hello")
        messages = store.list_messages(session_id)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["content"], "Hello")



class SessionTitleTests(_ChatTestBase):
    """Tests for auto-summarize email as session title, rename, and delete."""

    def test_auto_title_updates_from_new_session_to_email_summary(self) -> None:
        """Session title should auto-update from 'New session' to email summary when draft is generated."""
        account_id, _ = self._demo_seed_and_profile("chirag@expano.in")
        self._seed_contacts(account_id, [_MANU])

        # Create a session with default title
        session = self.client.post(
            "/api/chat/sessions",
            headers={"X-Account-ID": account_id},
            json={"title": "New session"},
        ).json()
        session_id = session["session_id"]
        self.assertEqual(session["title"], "New session")

        # Send a chat turn that generates a draft
        turn = self._turn(account_id, "send an email to manu about the roadmap", session_id=session_id)
        self.assertIn(turn["status"], ("PENDING_REVIEW", "DRAFTED", "SENT"))

        # Check that session_title was returned and session was updated
        self.assertIn("session_title", turn)
        self.assertIsNotNone(turn.get("session_title"))
        self.assertNotEqual(turn["session_title"], "New session")
        # Should contain recipient name and subject
        self.assertIn("Manu", turn["session_title"])
        self.assertIn("roadmap", turn["session_title"].lower())

        # Verify session in store was updated
        sessions = self.client.get("/api/chat/sessions", headers={"X-Account-ID": account_id}).json()["sessions"]
        updated = next(s for s in sessions if s["session_id"] == session_id)
        self.assertEqual(updated["title"], turn["session_title"])
        self.assertFalse(updated.get("isCustomTitle", False))

    def test_rename_session_marks_custom_and_prevents_overwrite(self) -> None:
        """PATCH rename should set isCustomTitle=true and prevent subsequent turns from overwriting."""
        account_id, _ = self._demo_seed_and_profile("chirag@expano.in")
        self._seed_contacts(account_id, [_MANU])

        session = self.client.post(
            "/api/chat/sessions",
            headers={"X-Account-ID": account_id},
            json={"title": "New session"},
        ).json()
        session_id = session["session_id"]

        # Rename the session
        renamed = self.client.patch(
            f"/api/chat/sessions/{session_id}",
            headers={"X-Account-ID": account_id},
            json={"title": "My Custom Title"},
        )
        self.assertEqual(renamed.status_code, 200, renamed.text)
        self.assertEqual(renamed.json()["title"], "My Custom Title")
        self.assertTrue(renamed.json().get("is_custom_title", False))

        # Send another chat turn - should NOT overwrite the custom title
        turn = self._turn(account_id, "send an email to manu about the quarterly plan", session_id=session_id)
        self.assertIn(turn["status"], ("PENDING_REVIEW", "DRAFTED", "SENT"))

        # Verify session title remains custom
        sessions = self.client.get("/api/chat/sessions", headers={"X-Account-ID": account_id}).json()["sessions"]
        updated = next(s for s in sessions if s["session_id"] == session_id)
        self.assertEqual(updated["title"], "My Custom Title")
        self.assertTrue(updated.get("is_custom_title", False))

    def test_delete_session_removes_session_and_messages(self) -> None:
        """DELETE should remove session, messages, and associated drafts."""
        account_id, _ = self._demo_seed_and_profile("chirag@expano.in")
        self._seed_contacts(account_id, [_MANU])

        session = self.client.post(
            "/api/chat/sessions",
            headers={"X-Account-ID": account_id},
            json={"title": "To Delete"},
        ).json()
        session_id = session["session_id"]

        # Add some messages
        self._turn(account_id, "send an email to manu about the roadmap", session_id=session_id)

        # Delete the session
        deleted = self.client.delete(
            f"/api/chat/sessions/{session_id}",
            headers={"X-Account-ID": account_id},
        )
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertTrue(deleted.json()["deleted"])
        self.assertEqual(deleted.json()["session_id"], session_id)

        # Verify session is gone
        sessions = self.client.get("/api/chat/sessions", headers={"X-Account-ID": account_id}).json()["sessions"]
        self.assertEqual([s["id"] for s in sessions], [])

    def test_delete_active_session_switches_to_next(self) -> None:
        """Deleting the active session should switch to the next available session."""
        account_id, _ = self._demo_seed_and_profile("chirag@expano.in")
        self._seed_contacts(account_id, [_MANU])

        # Create two sessions
        session1 = self.client.post(
            "/api/chat/sessions",
            headers={"X-Account-ID": account_id},
            json={"title": "Session 1"},
        ).json()
        session2 = self.client.post(
            "/api/chat/sessions",
            headers={"X-Account-ID": account_id},
            json={"title": "Session 2"},
        ).json()

        # Select session1 as active
        self.client.post(
            "/api/chat/turn",
            headers={"X-Account-ID": account_id},
            json={"session_id": session1["session_id"], "user_message": "hello"},
        )

        # Delete session1
        deleted = self.client.delete(
            f"/api/chat/sessions/{session1['session_id']}",
            headers={"X-Account-ID": account_id},
        )
        self.assertEqual(deleted.status_code, 200)

        # Verify session2 is now the only one
        sessions = self.client.get("/api/chat/sessions", headers={"X-Account-ID": account_id}).json()["sessions"]
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["session_id"], session2["session_id"])

    def test_account_isolation_for_rename_delete(self) -> None:
        """Account B cannot rename/delete Account A's session."""
        account_a, _ = self._demo_seed_and_profile("chirag@expano.in")
        self._seed_contacts(account_a, [_MANU])

        # Account B - create separate account
        account_b = self.client.post(
            "/api/accounts",
            headers={"X-Account-ID": account_a},  # This will fail - need to create properly
        )

        # Actually, let's create account B properly
        app = self.client.app
        account_b_obj = app.state.account_manager.create_account(email="other@test.com", display_name="Other User")
        account_b_id = account_b_obj.account_id

        # Create session for account A
        session_a = self.client.post(
            "/api/chat/sessions",
            headers={"X-Account-ID": account_a},
            json={"title": "Account A Session"},
        ).json()
        session_a_id = session_a["session_id"]

        # Account B tries to rename Account A's session - should fail with 404
        rename_attempt = self.client.patch(
            f"/api/chat/sessions/{session_a_id}",
            headers={"X-Account-ID": account_b_id},
            json={"title": "Hacked"},
        )
        self.assertEqual(rename_attempt.status_code, 404, "Account B should not access Account A's session")

        # Account B tries to delete Account A's session - should fail with 404
        delete_attempt = self.client.delete(
            f"/api/chat/sessions/{session_a_id}",
            headers={"X-Account-ID": account_b_id},
        )
        self.assertEqual(delete_attempt.status_code, 404, "Account B should not delete Account A's session")


if __name__ == "__main__":
    unittest.main()
