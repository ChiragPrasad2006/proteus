"""Unit tests for multi-turn clarification, literal email resolution, and drafter post-processing."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.automation.contact_resolver import Contact, ContactResolver
from backend.config import Settings
from backend.generation.drafter import QwenDrafter
from backend.schemas import UserStyleProfile, StylometryMetrics, GlobalStyleCard, CorpusStatistics
from backend.storage.chat_sessions import ChatSessionStore


class LiteralEmailResolutionTests(unittest.TestCase):
    """Test that literal email addresses are resolved immediately without clarification."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.contacts_path = Path(self.temp_dir.name) / "contacts.sqlite3"
        self.resolver = ContactResolver(self.contacts_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_literal_email_address_returns_matched_immediately(self) -> None:
        """A valid email address string should return MATCHED even if not in registry."""
        resolution = self.resolver.resolve("jatingourav111@gmail.com")
        self.assertEqual(resolution.status, "MATCHED")
        self.assertIsNotNone(resolution.matched)
        self.assertEqual(resolution.matched.email, "jatingourav111@gmail.com")
        self.assertNotEqual(resolution.reason, "")

    def test_literal_email_address_with_display_name(self) -> None:
        """An email with display name should still resolve to MATCHED."""
        resolution = self.resolver.resolve("Jatin G <jatingourav111@gmail.com>")
        self.assertEqual(resolution.status, "MATCHED")
        self.assertIsNotNone(resolution.matched)
        self.assertEqual(resolution.matched.email, "jatingourav111@gmail.com")

    def test_literal_email_in_resolve_many(self) -> None:
        """resolve_many should handle literal emails alongside names."""
        resolutions = self.resolver.resolve_many(["jatin", "jatingourav111@gmail.com"])
        # Both should be present (name needs clarification, email should match)
        statuses = [r.status for r in resolutions]
        self.assertIn("MATCHED", statuses)
        matched_emails = [r.matched.email for r in resolutions if r.status == "MATCHED" and r.matched]
        self.assertIn("jatingourav111@gmail.com", matched_emails)

    def test_invalid_email_still_needs_clarification(self) -> None:
        """Invalid email-like strings should still need clarification."""
        resolution = self.resolver.resolve("not-an-email")
        self.assertEqual(resolution.status, "NEEDS_CLARIFICATION")


class MultiTurnClarificationTests(unittest.TestCase):
    """Test multi-turn clarification flow: unknown name -> user provides email -> contact saved -> draft generated."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.settings = Settings(
            local_user_data_dir=Path(self.temp_dir.name),
            profiler_mode="heuristic",
            model_name="not-installed-for-test",
        )
        self.chat_sessions_path = self.settings.chat_sessions_path
        self.contacts_path = self.settings.contacts_path
        self.sessions = ChatSessionStore(self.chat_sessions_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_pending_clarification_persisted_and_cleared(self) -> None:
        """Pending clarification payload should be saved and cleared."""
        session = self.sessions.create_session("account-1", title="Test")
        session_id = session["session_id"]

        payload = {
            "action": "send",
            "intent_bullets": "- discuss project",
            "subject_hint": "Project update",
            "unresolved_names": ["jatin"],
            "target_field": "to",
            "to": [],
            "cc": [],
            "bcc": [],
        }
        self.sessions.set_pending_clarification(session_id, payload)
        loaded = self.sessions.get_pending_clarification(session_id)
        self.assertEqual(loaded["unresolved_names"], ["jatin"])
        self.assertEqual(loaded["intent_bullets"], "- discuss project")

        self.sessions.clear_pending_clarification(session_id)
        cleared = self.sessions.get_pending_clarification(session_id)
        self.assertIsNone(cleared)

    def test_recent_messages_loaded_for_context(self) -> None:
        """get_recent_messages should return last N messages in chronological order."""
        session = self.sessions.create_session("account-1", title="Test")
        session_id = session["session_id"]

        for i in range(10):
            self.sessions.append_message(session_id, "user" if i % 2 == 0 else "assistant", f"Message {i}")

        recent = self.sessions.get_recent_messages(session_id, limit=8)
        self.assertEqual(len(recent), 8)
        # Should be in chronological order (oldest first)
        self.assertEqual(recent[0]["content"], "Message 2")
        self.assertEqual(recent[-1]["content"], "Message 9")


class DrafterPostProcessingTests(unittest.TestCase):
    """Test drafter post-processing: no markdown, no placeholders, no leading Subject:, single sign-off."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.settings = Settings(
            local_user_data_dir=Path(self.temp_dir.name),
            profiler_mode="heuristic",
            model_name="not-installed-for-test",
        )
        self.drafter = QwenDrafter(self.settings)

        # Create a minimal profile for testing
        self.profile = UserStyleProfile(
            profile_id="test-profile",
            created_at="2026-01-01T00:00:00+00:00",
            deterministic_stylometry=StylometryMetrics(
                top_greetings=[],
                exact_signoff="Regards,\nChirag Prasad",
                avg_sentence_length_words=10.0,
                avg_email_length_words=50.0,
                avg_paragraph_count=2.0,
                exclamation_rate=0.0,
                emoji_rate=0.0,
                uses_bullet_lists_pct=0.0,
            ),
            global_style_card=GlobalStyleCard(
                formality="semi-formal",
                tone="professional",
                directness="balanced",
                vocabulary_level="standard-professional",
                sentence_structure="detailed & analytical",
                formatting_preferences=[],
                characteristic_phrases=[],
                source="heuristic",
                model="test",
                sampled_email_count=10,
            ),
            corpus_statistics=CorpusStatistics(
                total_sent_emails=10,
                clean_emails_retained=10,
                top_recipients=[],
            ),
            global_learned_rules=[],
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_strips_markdown_bold(self) -> None:
        draft = "Hello **Jatin**, this is **important**."
        result = self.drafter._post_process_draft(draft, self.profile)
        self.assertNotIn("**", result)
        self.assertIn("Hello Jatin, this is important.", result)

    def test_strips_markdown_headings(self) -> None:
        draft = "### Subject\n\nBody text."
        result = self.drafter._post_process_draft(draft, self.profile)
        self.assertNotIn("###", result)
        self.assertIn("Subject", result)

    def test_strips_placeholders(self) -> None:
        draft = "Hello {first_name},\n\n[Name] please see [Recipient] details (date if known)."
        result = self.drafter._post_process_draft(draft, self.profile)
        self.assertNotIn("{first_name}", result)
        self.assertNotIn("[Name]", result)
        self.assertNotIn("[Recipient]", result)
        self.assertNotIn("(date if known)", result)

    def test_strips_leading_subject_line(self) -> None:
        draft = "Subject: Project Update\n\nHello,\n\nBody here."
        result = self.drafter._post_process_draft(draft, self.profile)
        self.assertNotIn("Subject:", result)
        self.assertTrue(result.startswith("Hello"))

    def test_deduplicates_signoff(self) -> None:
        # Draft already ends with the exact signoff
        draft = "Hello,\n\nBody here.\n\nRegards,\nChirag Prasad"
        result = self.drafter._post_process_draft(draft, self.profile)
        # Should appear exactly once
        self.assertEqual(result.count("Regards,\nChirag Prasad"), 1)

    def test_deduplicates_similar_signoff(self) -> None:
        # Draft ends with a similar closing phrase
        draft = "Hello,\n\nBody here.\n\nBest regards,\nChirag Prasad"
        result = self.drafter._post_process_draft(draft, self.profile)
        # Should replace with exact signoff
        self.assertEqual(result.count("Regards,\nChirag Prasad"), 1)
        self.assertNotIn("Best regards", result)

    def test_resolves_first_name_in_greeting(self) -> None:
        # This tests the _resolve_first_name method
        first_name = self.drafter._resolve_first_name("jatin.mehta@expano.in", {})
        self.assertEqual(first_name, "Jatin")

    def test_resolves_first_name_from_profile(self) -> None:
        from backend.schemas import RecipientProfile
        profile = RecipientProfile(
            recipient_email="jatin@expano.in",
            recipient_domain="expano.in",
            relationship_tier="peer",
            preferred_greeting="Hi Jatin,",
            sent_count=5,
            learned_rules_json=[],
        )
        first_name = self.drafter._resolve_first_name("jatin@expano.in", {"jatin@expano.in": profile})
        self.assertEqual(first_name, "Jatin")

    def test_unknown_email_returns_empty_first_name(self) -> None:
        # kamisama7892@gmail.com should not yield a guessed name
        first_name = self.drafter._resolve_first_name("kamisama7892@gmail.com", {})
        self.assertEqual(first_name, "")


if __name__ == "__main__":
    unittest.main()
