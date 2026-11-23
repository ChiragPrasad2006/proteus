"""Tests for the backend persistence endpoints.

Covers the seven endpoints that replaced the frontend's localStorage adapter:

* ``PATCH  /api/chat/sessions/{session_id}/pin``
* ``GET    /api/profile/recipient-rules``
* ``PATCH  /api/profile/rules/{rule_id}``
* ``DELETE /api/profile/rules/{rule_id}``
* ``POST   /api/profile/reset``
* ``PATCH  /api/draft/{draft_id}``
* ``DELETE /api/draft/{draft_id}``

plus the idempotent ``pinned`` SQLite migration, strict ``X-Account-ID``
isolation, and the drafter's plain-email (no report headings) output.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from backend.config import Settings  # noqa: E402
from backend.generation.drafter import QwenDrafter  # noqa: E402
from backend.main import create_app  # noqa: E402
from backend.schemas import (  # noqa: E402
    CorpusStatistics,
    GreetingFrequency,
    GlobalStyleCard,
    RecipientProfile,
    StylometryMetrics,
    UserStyleProfile,
)
from backend.storage import ChatSessionStore, ProfileStore  # noqa: E402


def _profile(rules: list[str] | None = None, signoff: str = "Regards, Chirag") -> UserStyleProfile:
    return UserStyleProfile(
        profile_id="profile-under-test",
        created_at=datetime.now(timezone.utc),
        deterministic_stylometry=StylometryMetrics(
            top_greetings=[GreetingFrequency(pattern="Hello {first_name},", pct=100)],
            exact_signoff=signoff,
            avg_sentence_length_words=16.0,
            avg_email_length_words=42.0,
            avg_paragraph_count=3.0,
        ),
        global_style_card=GlobalStyleCard(
            formality="semi-formal",
            tone="blunt-technical",
            directness="balanced",
            vocabulary_level="standard-professional",
            sentence_structure="short & punchy",
            formatting_preferences=[],
            characteristic_phrases=[],
            source="heuristic",
            model="heuristic",
            sampled_email_count=0,
        ),
        corpus_statistics=CorpusStatistics(
            total_sent_emails=12, clean_emails_retained=8, top_recipients=[]
        ),
        global_learned_rules=list(rules or []),
    )


def _loaded_profile(store: ProfileStore) -> UserStyleProfile:
    """Return the persisted profile (asserting it exists)."""
    profile = store.load_profile()
    assert profile is not None, "expected a persisted style profile"
    return profile


def _recipient_profile(store: ProfileStore, email: str) -> RecipientProfile:
    profile = store.get_recipient_profile(email)
    assert profile is not None, "expected a persisted recipient profile"
    return profile


class _PersistenceTestBase(unittest.TestCase):
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

    @staticmethod
    def _headers(account_id: str) -> dict[str, str]:
        return {"X-Account-ID": account_id}

    def _write_profile(self, account_id: str, rules: list[str] | None = None) -> ProfileStore:
        store = ProfileStore(self.settings.for_account(account_id))
        store.save_profile(_profile(rules))
        return store

    def _stage_draft(self, account_id: str, draft_id: str = "draft-under-test"):
        """Create a staged draft (pending_drafts + chat draft card) for the account."""
        account_settings = self.settings.for_account(account_id)
        store = ProfileStore(account_settings)
        sessions = ChatSessionStore(account_settings.chat_sessions_path)
        session = sessions.create_session(account_id, title="Draft session")
        card = sessions.upsert_draft_card(
            session_id=session["session_id"],
            to=["k@example.com"],
            cc=[],
            bcc=[],
            subject="Original subject",
            body="Original body",
            status="PENDING_REVIEW",
            draft_id=draft_id,
        )
        with sqlite3.connect(account_settings.sqlite_path) as connection:
            connection.execute(
                """
                INSERT INTO pending_drafts
                (draft_id, profile_id, request_json, draft, created_at, recipient_profiles_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    draft_id,
                    "profile-under-test",
                    json.dumps(
                        {
                            "to": ["k@example.com"],
                            "cc": [],
                            "bcc": [],
                            "subject": "Original subject",
                            "session_id": session["session_id"],
                            "card_id": card["card_id"],
                        }
                    ),
                    "Original body",
                    datetime.now(timezone.utc).isoformat(),
                    "{}",
                ),
            )
        return session, draft_id

    @staticmethod
    def _columns(path: Path, table: str) -> list[str]:
        with sqlite3.connect(path) as connection:
            return [row[1] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()]


class PinnedMigrationTests(_PersistenceTestBase):
    """The ``pinned`` column is added idempotently to existing databases."""

    def test_pinned_column_is_added_and_migration_is_idempotent(self) -> None:
        path = Path(self.temp_dir.name) / "chat_sessions.sqlite3"
        ChatSessionStore(path)
        self.assertIn("pinned", self._columns(path, "sessions"))

        # Re-opening an existing database re-runs the migration: no error, no duplicates.
        ChatSessionStore(path)
        self.assertEqual(self._columns(path, "sessions").count("pinned"), 1)

    def test_existing_rows_default_to_unpinned(self) -> None:
        path = Path(self.temp_dir.name) / "chat_sessions.sqlite3"
        store = ChatSessionStore(path)
        store.create_session("account-1", title="Older")
        summary = store.get_session_summary(
            store.list_sessions("account-1")[0]["session_id"]
        )
        assert summary is not None
        self.assertFalse(summary["pinned"])


class PinEndpointTests(_PersistenceTestBase):
    """``PATCH /api/chat/sessions/{session_id}/pin``."""

    def test_pin_sets_flag_and_orders_pinned_sessions_first(self) -> None:
        account_id = self._create_account("one@example.com")
        headers = self._headers(account_id)
        first = self.client.post("/api/chat/sessions", json={"title": "First"}, headers=headers).json()
        second = self.client.post("/api/chat/sessions", json={"title": "Second"}, headers=headers).json()

        response = self.client.patch(
            f"/api/chat/sessions/{first['session_id']}/pin", json={"pinned": True}, headers=headers
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["pinned"])
        self.assertEqual(response.json()["session_id"], first["session_id"])

        listing = self.client.get("/api/chat/sessions", headers=headers).json()["sessions"]
        self.assertEqual(listing[0]["session_id"], first["session_id"])
        self.assertEqual(sum(1 for item in listing if item.get("pinned")), 1)
        self.assertIn(second["session_id"], [item["session_id"] for item in listing])

        # Idempotent: pinning twice keeps exactly one pinned session.
        again = self.client.patch(
            f"/api/chat/sessions/{first['session_id']}/pin", json={"pinned": True}, headers=headers
        )
        self.assertTrue(again.json()["pinned"])
        listing = self.client.get("/api/chat/sessions", headers=headers).json()["sessions"]
        self.assertEqual(sum(1 for item in listing if item.get("pinned")), 1)

        # Unpinning restores the plain ordering.
        unpinned = self.client.patch(
            f"/api/chat/sessions/{first['session_id']}/pin", json={"pinned": False}, headers=headers
        )
        self.assertFalse(unpinned.json()["pinned"])
        listing = self.client.get("/api/chat/sessions", headers=headers).json()["sessions"]
        self.assertTrue(all(not item.get("pinned") for item in listing))

    def test_pin_enforces_account_isolation(self) -> None:
        owner = self._create_account("owner@example.com")
        intruder = self._create_account("intruder@example.com")
        session = self.client.post(
            "/api/chat/sessions", json={"title": "Owner only"}, headers=self._headers(owner)
        ).json()

        response = self.client.patch(
            f"/api/chat/sessions/{session['session_id']}/pin",
            json={"pinned": True},
            headers=self._headers(intruder),
        )
        self.assertEqual(response.status_code, 404)

        # The owner's session is untouched and the intruder sees nothing pinned.
        owner_listing = self.client.get("/api/chat/sessions", headers=self._headers(owner)).json()["sessions"]
        self.assertTrue(all(not item.get("pinned") for item in owner_listing))
        intruder_listing = self.client.get("/api/chat/sessions", headers=self._headers(intruder)).json()["sessions"]
        self.assertEqual(intruder_listing, [])


class LearnedRuleEndpointTests(_PersistenceTestBase):
    """``GET /api/profile/recipient-rules`` + rule edit/forget/reset."""

    def test_recipient_rules_are_listed_with_deterministic_ids(self) -> None:
        account_id = self._create_account("rules@example.com")
        store = ProfileStore(self.settings.for_account(account_id))
        store.upsert_recipient_profile(
            RecipientProfile(
                recipient_email="Kamisama@Example.com",
                recipient_domain="example.com",
                learned_rules_json=["prefers short sign-offs", "uses dashes not bullets"],
            )
        )
        response = self.client.get("/api/profile/recipient-rules", headers=self._headers(account_id))
        self.assertEqual(response.status_code, 200, response.text)
        rules = response.json()["rules"]
        self.assertEqual(len(rules), 2)
        self.assertEqual(rules[0]["recipient_email"], "kamisama@example.com")
        self.assertEqual(rules[0]["rule_id"], "recipient:kamisama@example.com:0")
        self.assertEqual(rules[1]["rule_id"], "recipient:kamisama@example.com:1")
        self.assertEqual(rules[0]["text"], "prefers short sign-offs")

    def test_update_and_forget_global_rule(self) -> None:
        account_id = self._create_account("edit@example.com")
        store = self._write_profile(account_id, rules=["You prefer concise sign-offs"])
        headers = self._headers(account_id)

        updated = self.client.patch(
            "/api/profile/rules/global:0", json={"text": "You prefer short sign-offs"}, headers=headers
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["rule_id"], "global:0")
        self.assertEqual(_loaded_profile(store).global_learned_rules, ["You prefer short sign-offs"])

        missing = self.client.patch(
            "/api/profile/rules/global:9", json={"text": "nope"}, headers=headers
        )
        self.assertEqual(missing.status_code, 404)

        forgotten = self.client.delete("/api/profile/rules/global:0", headers=headers)
        self.assertEqual(forgotten.status_code, 200, forgotten.text)
        self.assertTrue(forgotten.json()["forgotten"])
        self.assertEqual(forgotten.json()["rule_id"], "global:0")
        self.assertEqual(_loaded_profile(store).global_learned_rules, [])

    def test_update_and_forget_recipient_rule(self) -> None:
        account_id = self._create_account("recipient@example.com")
        store = ProfileStore(self.settings.for_account(account_id))
        store.upsert_recipient_profile(
            RecipientProfile(
                recipient_email="k@example.com",
                recipient_domain="example.com",
                learned_rules_json=["prefers short sign-offs"],
            )
        )
        headers = self._headers(account_id)

        updated = self.client.patch(
            "/api/profile/rules/recipient:k@example.com:0",
            json={"text": "prefers one-line sign-offs"},
            headers=headers,
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(
            _recipient_profile(store, "k@example.com").learned_rules_json, ["prefers one-line sign-offs"]
        )

        forgotten = self.client.delete(
            "/api/profile/rules/recipient:k@example.com:0", headers=headers
        )
        self.assertEqual(forgotten.status_code, 200, forgotten.text)
        self.assertEqual(_recipient_profile(store, "k@example.com").learned_rules_json, [])

    def test_rules_are_isolated_per_account(self) -> None:
        owner = self._create_account("rules-owner@example.com")
        intruder = self._create_account("rules-intruder@example.com")
        store = self._write_profile(owner, rules=["Owner only rule"])

        response = self.client.patch(
            "/api/profile/rules/global:0",
            json={"text": "Hijacked"},
            headers=self._headers(intruder),
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(_loaded_profile(store).global_learned_rules, ["Owner only rule"])

    def test_profile_reset_clears_rules_but_keeps_the_profile(self) -> None:
        account_id = self._create_account("reset@example.com")
        store = self._write_profile(account_id, rules=["rule one", "rule two"])
        store.upsert_recipient_profile(
            RecipientProfile(
                recipient_email="k@example.com",
                recipient_domain="example.com",
                learned_rules_json=["per recipient rule"],
            )
        )
        response = self.client.post("/api/profile/reset", headers=self._headers(account_id))
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["global_learned_rules"], [])
        self.assertEqual(body["corpus_statistics"]["total_sent_emails"], 12)
        self.assertEqual(_loaded_profile(store).global_learned_rules, [])
        self.assertEqual(_recipient_profile(store, "k@example.com").learned_rules_json, [])
        # The profile file itself survives the reset.
        self.assertTrue(self.settings.for_account(account_id).profile_path.is_file())


class StagedDraftEndpointTests(_PersistenceTestBase):
    """``PATCH`` / ``DELETE`` ``/api/draft/{draft_id}``."""

    def test_update_persists_across_a_reload(self) -> None:
        account_id = self._create_account("draft@example.com")
        headers = self._headers(account_id)
        session, draft_id = self._stage_draft(account_id)

        response = self.client.patch(
            f"/api/draft/{draft_id}",
            json={
                "to": ["new@example.com"],
                "cc": ["cc@example.com"],
                "bcc": [],
                "subject": "Updated subject",
                "body": "Updated body",
            },
            headers=headers,
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["draft_id"], draft_id)
        self.assertTrue(response.json()["updated_at"])

        account_settings = self.settings.for_account(account_id)
        pending = ProfileStore(account_settings).load_pending_draft(draft_id)
        assert pending is not None
        self.assertEqual(pending["draft"], "Updated body")
        self.assertEqual(pending["request"]["subject"], "Updated subject")
        self.assertEqual(pending["request"]["to"], ["new@example.com"])
        self.assertEqual(pending["request"]["cc"], ["cc@example.com"])

        # The session snapshot (what a reload re-hydrates from) matches the saved draft.
        detail = self.client.get(
            f"/api/chat/sessions/{session['session_id']}", headers=headers
        ).json()
        card = detail["draft_cards"][0]
        assert card is not None
        self.assertEqual(card["body"], "Updated body")
        self.assertEqual(card["subject"], "Updated subject")
        self.assertEqual(card["to"], ["new@example.com"])
        self.assertEqual(card["status"], "DRAFT")

    def test_delete_removes_the_staged_draft_and_its_card(self) -> None:
        account_id = self._create_account("discard@example.com")
        headers = self._headers(account_id)
        session, draft_id = self._stage_draft(account_id)

        response = self.client.delete(f"/api/draft/{draft_id}", headers=headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["deleted"])
        self.assertEqual(response.json()["draft_id"], draft_id)

        account_settings = self.settings.for_account(account_id)
        self.assertIsNone(ProfileStore(account_settings).load_pending_draft(draft_id))
        detail = self.client.get(
            f"/api/chat/sessions/{session['session_id']}", headers=headers
        ).json()
        self.assertEqual(detail["draft_cards"], [])

        # Deleting twice is a 404, not a silent success.
        self.assertEqual(
            self.client.delete(f"/api/draft/{draft_id}", headers=headers).status_code, 404
        )

    def test_draft_endpoints_are_isolated_per_account(self) -> None:
        owner = self._create_account("draft-owner@example.com")
        intruder = self._create_account("draft-intruder@example.com")
        _session, draft_id = self._stage_draft(owner)

        response = self.client.patch(
            f"/api/draft/{draft_id}", json={"body": "Hijacked"}, headers=self._headers(intruder)
        )
        self.assertEqual(response.status_code, 404)
        pending = ProfileStore(self.settings.for_account(owner)).load_pending_draft(draft_id)
        self.assertEqual(pending["draft"], "Original body")


class DrafterPlainEmailTests(unittest.TestCase):
    """The drafter must not emit report/ticket headings."""

    def setUp(self) -> None:
        # Skip the heavy embedder/vector-store initialisation.
        self.drafter = QwenDrafter.__new__(QwenDrafter)
        self.profile = _profile()

    def test_post_process_rewrites_report_headings_as_sentences(self) -> None:
        raw = (
            "Hello,\n\n"
            "Project Deadline: Monday\n"
            "Severity Score: 7/10\n"
            "Request: Please review the draft.\n"
            "Outstanding Issues\n\n"
            "Can you take a look before Friday?\n\n"
            "Regards,\n"
            "Chirag"
        )
        cleaned = self.drafter._post_process_draft(raw, self.profile)
        self.assertNotIn("Project Deadline", cleaned)
        self.assertNotIn("Severity Score", cleaned)
        self.assertNotIn("Outstanding Issues", cleaned)
        self.assertIn("The project deadline is Monday.", cleaned)
        self.assertIn("The severity score is 7/10.", cleaned)
        self.assertIn("Please review the draft.", cleaned)
        self.assertIn("Can you take a look before Friday?", cleaned)
        self.assertTrue(cleaned.endswith("Regards, Chirag"))

    def test_ambiguous_label_is_dropped_only_when_it_introduces_a_list(self) -> None:
        raw = "Hello,\n\nRequest\n- Fast-track the sessions.\n- Keep it short.\n\nThanks!"
        cleaned = self.drafter._post_process_draft(raw, self.profile)
        self.assertNotIn("Request", cleaned)
        self.assertIn("Fast-track the sessions.", cleaned)

    def test_plain_subject_heading_over_prose_is_preserved(self) -> None:
        # Regression guard: markdown headings keep their text (see the existing suite).
        cleaned = self.drafter._post_process_draft("### Subject\n\nBody text.", self.profile)
        self.assertIn("Subject", cleaned)
        self.assertIn("Body text.", cleaned)

    def test_system_prompt_forbids_report_headings(self) -> None:
        prompt = QwenDrafter.SYSTEM_PROMPT_TEMPLATE
        self.assertIn("Project Deadline", prompt)
        self.assertIn("Severity Score", prompt)
        self.assertIn("NEVER write report, ticket, or memo headings", prompt)


class LauncherOllamaDefaultsTests(unittest.TestCase):
    """The launcher must cap Ollama's VRAM usage for 8GB GPUs."""

    def test_setup_environment_sets_ollama_defaults(self) -> None:
        import launcher

        keys = (
            "OLLAMA_NUM_PARALLEL",
            "OLLAMA_MAX_LOADED_MODELS",
            "OLLAMA_CONTEXT_LENGTH",
            "OLLAMA_FLASH_ATTENTION",
        )
        saved = {key: os.environ.get(key) for key in keys}
        for key in keys:
            os.environ.pop(key, None)
        try:
            launcher.setup_environment()
            self.assertEqual(os.environ["OLLAMA_NUM_PARALLEL"], "1")
            self.assertEqual(os.environ["OLLAMA_MAX_LOADED_MODELS"], "1")
            self.assertEqual(os.environ["OLLAMA_CONTEXT_LENGTH"], "4096")
            self.assertEqual(os.environ["OLLAMA_FLASH_ATTENTION"], "1")
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
