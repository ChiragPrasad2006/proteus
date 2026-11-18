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

import os
import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from backend.automation import Contact, ContactResolver, Dispatcher
from backend.config import Settings
from backend.main import create_app
from backend.schemas import DispatchRequest
from backend.storage import ProfileStore

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
        self.assertTrue(card["body"].strip(), "draft body must not be empty")
        self.assertEqual(card["to"], ["manu@expano.in"])
        self.assertEqual(sorted(card["cc"]), ["chiranth@expano.in", "jatin@expano.in"])
        self.assertIn(card["status"], ("DRAFT", "PENDING_REVIEW", "SENT"))

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


if __name__ == "__main__":
    unittest.main()
