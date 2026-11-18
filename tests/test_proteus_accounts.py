"""Behavioral tests for Proteus multi-account isolation, accounts, and chat sessions.

Covers the multi-account surface added on top of the Tier 1-4 backend:

* the demo seed creating BOTH demo accounts with per-account isolated storage,
* strict profile / contact / vector-store isolation between accounts,
* ``X-Account-ID`` enforcement on ``/api/chat/turn``,
* account switch + delete,
* chat session CRUD with SQLite persistence.

All tests follow the existing suite convention: a ``tempfile`` Settings with
``profiler_mode="heuristic"`` (no Ollama, no fine-tuned model, no network) passed
to ``create_app``. The TestClient is intentionally NOT used as a context manager
so the app lifespan does not eagerly load the sentence-transformer embedder.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.automation import Contact, ContactResolver
from backend.config import Settings
from backend.main import create_app
from backend.storage import ProfileStore


class _StubEmbedder:
    """Deterministic 384-dim embedder so vector-store isolation can be tested without a model."""

    DIM = 384

    @staticmethod
    def prepare_text(subject: str, clean_body: str, max_chars: int = 1000) -> str:
        body = (clean_body or "")[:max_chars].strip()
        return f"Subject: {subject}\n{body}" if subject else body

    def encode(self, texts: list[str], normalize: bool = True) -> np.ndarray:
        return np.zeros((len(texts), self.DIM), dtype=np.float32)

    def encode_single(self, text: str, normalize: bool = True) -> np.ndarray:
        return np.zeros(self.DIM, dtype=np.float32)


class _AccountTestBase(unittest.TestCase):
    """Shared temp-dir app/client fixtures."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.settings = Settings(
            local_user_data_dir=Path(self.temp_dir.name),
            profiler_mode="heuristic",
            model_name="not-installed-for-test",
        )
        self.app = create_app(settings=self.settings)
        # No context manager: skip the lifespan embedder load (no model needed here).
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # --- helpers ------------------------------------------------------------
    def _accounts_by_email(self) -> dict[str, dict]:
        payload = self.client.get("/api/accounts").json()
        return {account["email"]: account for account in payload["accounts"]}

    def _demo_seed(self) -> dict[str, dict]:
        response = self.client.post("/api/onboarding/demo-seed")
        self.assertEqual(response.status_code, 200, response.text)
        return self._accounts_by_email()

    def _build_profile(self, account_id: str) -> None:
        response = self.client.post(
            "/api/onboarding/build-profile", headers={"X-Account-ID": account_id}
        )
        self.assertEqual(response.status_code, 200, response.text)

    def _seed_contacts(self, account_id: str, contacts: list[Contact]) -> None:
        resolver = ContactResolver(self.settings.for_account(account_id).contacts_path)
        for contact in contacts:
            resolver.upsert_contact(contact)


class DemoSeedIsolationTests(_AccountTestBase):
    """Item 1: the demo seed creates both accounts with isolated directory trees."""

    def test_demo_seed_creates_both_accounts_with_isolated_storage(self) -> None:
        accounts = self._demo_seed()

        self.assertEqual(set(accounts), {"sam@cloudscale.io", "chirag@expano.in"})

        index_path = self.settings.local_user_data_dir / "accounts_index.json"
        index = json.loads(index_path.read_text(encoding="utf-8"))
        self.assertEqual(len(index), 2)
        self.assertEqual(
            {entry["email"] for entry in index.values()},
            {"sam@cloudscale.io", "chirag@expano.in"},
        )

        # Exactly one account is active, and it is the first demo account.
        listing = self.client.get("/api/accounts").json()
        active = [account for account in listing["accounts"] if account["is_active"]]
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["email"], "sam@cloudscale.io")
        self.assertEqual(listing["active_account_id"], active[0]["account_id"])

        # Build a profile and open a chat session for each account so every
        # long-lived per-account artifact is materialised.
        for account in listing["accounts"]:
            account_id = account["account_id"]
            self._build_profile(account_id)
            session = self.client.post(
                "/api/chat/sessions",
                headers={"X-Account-ID": account_id},
                json={"title": f"session for {account['email']}"},
            )
            self.assertEqual(session.status_code, 200, session.text)

        account_roots = []
        for account in listing["accounts"]:
            base = self.settings.local_user_data_dir / "accounts" / account["account_id"]
            account_roots.append(base)
            self.assertTrue(base.is_dir(), f"missing account root {base}")
            for file_name in (
                "profile_metadata.sqlite3",
                "cleaned_sent_emails.jsonl",
                "chat_sessions.sqlite3",
            ):
                artifact = base / file_name
                self.assertTrue(artifact.is_file(), f"{artifact} must be a file")
            for dir_name in ("oauth_tokens", "lancedb"):
                self.assertTrue((base / dir_name).is_dir(), f"{base / dir_name} must be a dir")

        # The two account trees are physically distinct locations.
        self.assertEqual(len(set(account_roots)), 2)


class StrictIsolationTests(_AccountTestBase):
    """Item 2: profiles, contacts, and vector records never leak across accounts."""

    def test_profile_is_isolation_scoped(self) -> None:
        accounts = self._demo_seed()
        a_id = accounts["sam@cloudscale.io"]["account_id"]
        b_id = accounts["chirag@expano.in"]["account_id"]

        # Only account A builds a profile; account B must still report none.
        self._build_profile(a_id)
        a_profile = self.client.get("/api/profile", headers={"X-Account-ID": a_id})
        self.assertEqual(a_profile.status_code, 200, a_profile.text)
        b_profile = self.client.get("/api/profile", headers={"X-Account-ID": b_id})
        self.assertEqual(b_profile.status_code, 404, b_profile.text)

        # Once B has its own profile the two must be different documents.
        self._build_profile(b_id)
        a_payload = self.client.get("/api/profile", headers={"X-Account-ID": a_id}).json()
        b_payload = self.client.get("/api/profile", headers={"X-Account-ID": b_id}).json()
        self.assertNotEqual(a_payload["profile_id"], b_payload["profile_id"])

    def test_contacts_are_isolation_scoped(self) -> None:
        accounts = self._demo_seed()
        a_id = accounts["sam@cloudscale.io"]["account_id"]
        b_id = accounts["chirag@expano.in"]["account_id"]

        self._seed_contacts(
            a_id,
            [Contact(email="vivek@cloudscale.io", full_name="Vivek Nair",
                     first_name="Vivek", last_name="Nair", company_domain="cloudscale.io")],
        )
        self._seed_contacts(
            b_id,
            [Contact(email="manu@expano.in", full_name="Manu Roy",
                     first_name="Manu", last_name="Roy", company_domain="expano.in")],
        )

        # B resolves its own B-only contact to an @expano.in address.
        response = self.client.post(
            "/api/chat/turn",
            headers={"X-Account-ID": b_id},
            json={"user_message": "send an email to manu about the roadmap"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        turn = response.json()
        to_resolutions = turn["resolutions"]["to"]
        self.assertEqual(len(to_resolutions), 1)
        self.assertEqual(to_resolutions[0]["status"], "MATCHED")
        self.assertEqual(to_resolutions[0]["matched_email"], "manu@expano.in")
        self.assertTrue(to_resolutions[0]["matched_email"].endswith("@expano.in"))

        # B must NOT be able to reach account A's contact.
        response = self.client.post(
            "/api/chat/turn",
            headers={"X-Account-ID": b_id},
            json={"user_message": "send an email to Vivek about the roadmap"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        turn = response.json()
        self.assertEqual(turn["status"], "NEEDS_CLARIFICATION")
        vivek = turn["resolutions"]["to"][0]
        self.assertEqual(vivek["status"], "NEEDS_CLARIFICATION")
        self.assertIsNone(vivek["matched_email"])
        leaked = [
            candidate["email"]
            for resolutions in turn["resolutions"].values()
            for resolution in resolutions
            for candidate in resolution["candidates"]
            if candidate["email"].endswith("@cloudscale.io")
        ]
        self.assertEqual(leaked, [], "account A contact leaked into account B resolution")

        # A resolves its own contact, confirming the seed landed in A.
        response = self.client.post(
            "/api/chat/turn",
            headers={"X-Account-ID": a_id},
            json={"user_message": "send an email to Vivek about the roadmap"},
        )
        self.assertEqual(response.json()["resolutions"]["to"][0]["matched_email"], "vivek@cloudscale.io")

    def test_lancedb_records_are_isolation_scoped(self) -> None:
        pytest.importorskip("lancedb")
        from backend.retrieval import LanceDBVectorStore

        accounts = self._demo_seed()
        a_id = accounts["sam@cloudscale.io"]["account_id"]
        b_id = accounts["chirag@expano.in"]["account_id"]
        a_settings = self.settings.for_account(a_id)
        b_settings = self.settings.for_account(b_id)

        cleaned = ProfileStore(a_settings).load_cleaned_emails()
        self.assertTrue(cleaned, "demo seed must populate account A's cleaned corpus")

        indexed = LanceDBVectorStore(a_settings).index_emails(cleaned, _StubEmbedder(), force_recreate=True)
        self.assertEqual(indexed, len(cleaned))

        self.assertGreater(LanceDBVectorStore(a_settings).count(), 0)
        self.assertEqual(
            LanceDBVectorStore(b_settings).count(),
            0,
            "account B's vector store must not contain account A's records",
        )


class AccountIdEnforcementTests(_AccountTestBase):
    """Item 3: X-Account-ID is strict."""

    def test_chat_turn_without_any_account_is_rejected(self) -> None:
        # Fresh install: no header, no body account_id, and no active account.
        response = self.client.post(
            "/api/chat/turn", json={"user_message": "send an email to someone"}
        )
        self.assertIn(response.status_code, (400, 422), response.text)

    def test_chat_turn_rejects_unknown_header_account(self) -> None:
        response = self.client.post(
            "/api/chat/turn",
            headers={"X-Account-ID": "does-not-exist"},
            json={"user_message": "send an email to someone"},
        )
        self.assertEqual(response.status_code, 404, response.text)

    def test_chat_turn_rejects_unknown_body_account(self) -> None:
        response = self.client.post(
            "/api/chat/turn",
            json={"user_message": "send an email to someone", "account_id": "nope"},
        )
        self.assertEqual(response.status_code, 404, response.text)

    def test_chat_turn_accepts_header_and_body_agreeing(self) -> None:
        accounts = self._demo_seed()
        b_id = accounts["chirag@expano.in"]["account_id"]
        response = self.client.post(
            "/api/chat/turn",
            headers={"X-Account-ID": b_id},
            json={"user_message": "send an email to someone", "account_id": b_id},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["session_id"])


class AccountSwitchDeleteTests(_AccountTestBase):
    """Item 4: switch flips the active flag; delete removes dir + index entry."""

    def test_switch_and_delete_account(self) -> None:
        accounts = self._demo_seed()
        a_id = accounts["sam@cloudscale.io"]["account_id"]
        b_id = accounts["chirag@expano.in"]["account_id"]
        self.assertTrue(accounts["sam@cloudscale.io"]["is_active"])
        self.assertFalse(accounts["chirag@expano.in"]["is_active"])

        switched = self.client.post("/api/accounts/switch", json={"account_id": b_id})
        self.assertEqual(switched.status_code, 200, switched.text)
        self.assertEqual(switched.json()["account_id"], b_id)
        self.assertTrue(switched.json()["is_active"])

        listing = self.client.get("/api/accounts").json()
        self.assertEqual(listing["active_account_id"], b_id)
        self.assertEqual(sum(1 for account in listing["accounts"] if account["is_active"]), 1)

        unknown = self.client.post("/api/accounts/switch", json={"account_id": "nope"})
        self.assertEqual(unknown.status_code, 404, unknown.text)

        account_dir = self.settings.local_user_data_dir / "accounts" / b_id
        self.assertTrue(account_dir.exists())
        deleted = self.client.delete(f"/api/accounts/{b_id}")
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertTrue(deleted.json()["deleted"])
        self.assertFalse(account_dir.exists(), "account directory must be removed")

        index = json.loads(
            (self.settings.local_user_data_dir / "accounts_index.json").read_text(encoding="utf-8")
        )
        self.assertNotIn(b_id, index)
        self.assertEqual(len(index), 1)
        self.assertIn(a_id, index)

        self.assertEqual(self.client.delete(f"/api/accounts/{b_id}").status_code, 404)


class ChatSessionCrudTests(_AccountTestBase):
    """Item 5: chat session CRUD with SQLite persistence."""

    def test_chat_session_crud_and_persistence(self) -> None:
        accounts = self._demo_seed()
        a_id = accounts["sam@cloudscale.io"]["account_id"]
        b_id = accounts["chirag@expano.in"]["account_id"]

        created = self.client.post(
            "/api/chat/sessions", headers={"X-Account-ID": a_id}, json={"title": "Kickoff"}
        )
        self.assertEqual(created.status_code, 200, created.text)
        session = created.json()
        session_id = session["session_id"]
        self.assertEqual(session["account_id"], a_id)
        self.assertEqual(session["title"], "Kickoff")
        self.assertEqual(session["message_count"], 0)

        listed = self.client.get("/api/chat/sessions", headers={"X-Account-ID": a_id})
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual([item["session_id"] for item in listed.json()["sessions"]], [session_id])

        # A chat turn appends both a user and an assistant message to the session.
        turn = self.client.post(
            "/api/chat/turn",
            headers={"X-Account-ID": a_id},
            json={"session_id": session_id, "user_message": "send an email to manu"},
        )
        self.assertEqual(turn.status_code, 200, turn.text)
        self.assertEqual(turn.json()["session_id"], session_id)

        detail = self.client.get(f"/api/chat/sessions/{session_id}", headers={"X-Account-ID": a_id})
        self.assertEqual(detail.status_code, 200, detail.text)
        payload = detail.json()
        self.assertEqual(payload["session"]["session_id"], session_id)
        self.assertEqual(payload["session"]["message_count"], 2)
        roles = [message["role"] for message in payload["messages"]]
        self.assertEqual(roles, ["user", "assistant"])
        self.assertEqual(payload["messages"][0]["content"], "send an email to manu")

        # Messages are persisted in the account's own chat_sessions.sqlite3.
        db_path = self.settings.for_account(a_id).chat_sessions_path
        self.assertTrue(db_path.is_file())
        with sqlite3.connect(db_path) as connection:
            rows = connection.execute(
                "SELECT role, content FROM messages WHERE session_id = ? ORDER BY rowid", (session_id,)
            ).fetchall()
        self.assertEqual([row[0] for row in rows], ["user", "assistant"])

        # Sessions are account-scoped: account B sees none of A's sessions.
        other = self.client.get("/api/chat/sessions", headers={"X-Account-ID": b_id})
        self.assertEqual(other.json()["sessions"], [])

        # Unknown session id -> 404.
        missing = self.client.get("/api/chat/sessions/does-not-exist", headers={"X-Account-ID": a_id})
        self.assertEqual(missing.status_code, 404, missing.text)


class GoogleIdentityAndMailboxGateTests(_AccountTestBase):
    """Identity login creates a locked account; verified app passwords unlock it."""

    def test_google_identity_scopes_are_non_sensitive(self) -> None:
        self.assertEqual(
            self.settings.google_oauth_scopes,
            (
                "openid",
                "https://www.googleapis.com/auth/userinfo.email",
                "https://www.googleapis.com/auth/userinfo.profile",
            ),
        )

    def test_manual_identity_creates_locked_account(self) -> None:
        response = self.client.post(
            "/api/auth/identity",
            json={"email": "person@gmail.com", "display_name": "Person Example"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        account = response.json()["account"]
        self.assertFalse(account["mailbox_connected"])

        index = json.loads(
            (self.settings.local_user_data_dir / "accounts_index.json").read_text(encoding="utf-8")
        )
        self.assertFalse(index[account["account_id"]]["mailbox_connected"])

    def test_verified_app_password_unlocks_and_is_not_stored_as_plaintext(self) -> None:
        from datetime import datetime, timezone
        from unittest.mock import patch

        identity = self.client.post(
            "/api/auth/identity",
            json={"email": "person@gmail.com", "display_name": "Person Example"},
        )
        self.assertEqual(identity.status_code, 200, identity.text)
        account_id = identity.json()["account"]["account_id"]

        class FakeGmailAppPasswordConnector:
            verified: tuple[str, str]

            def __init__(self, email: str, app_password: str) -> None:
                self.email = email
                self.app_password = app_password

            def verify_connection(self) -> None:
                self.__class__.verified = (self.email, self.app_password)

            def fetch_sent_emails(self, limit: int):
                return [
                    __import__("backend.schemas", fromlist=["RawSentEmail"]).RawSentEmail(
                        message_id="sent-1",
                        recipient_email="friend@example.com",
                        subject="Hello",
                        raw_body="Hello friend, this is a sufficiently long sent message for testing.",
                        timestamp=datetime.now(timezone.utc),
                    )
                ]

            def send_email(self, payload):  # pragma: no cover - endpoint does not send
                raise AssertionError("send_email must not run during onboarding")

        password = "abcdefghijklmnop"
        with patch("backend.main.GmailAppPasswordConnector", FakeGmailAppPasswordConnector):
            response = self.client.post(
                "/api/onboarding/connect-app-password",
                headers={"X-Account-ID": account_id},
                json={"app_password": "abcd efgh ijkl mnop", "limit": 5},
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(FakeGmailAppPasswordConnector.verified, ("person@gmail.com", password))
        self.assertTrue(response.json()["account"]["mailbox_connected"])

        account_root = self.settings.for_account(account_id).local_user_data_dir
        blob = (account_root / "app_password.bin").read_text(encoding="utf-8")
        self.assertNotIn(password, blob)
        self.assertTrue(blob.startswith(("dpapi:", "fernet:")))


if __name__ == "__main__":
    unittest.main()
