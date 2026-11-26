"""Unit and integration tests for the deterministic personalization resolver.

Every test here is fully offline: the resolver itself is pure Python, and the
API tests mock the drafter and LanceDB retrieval. No Ollama server, no SMTP and
no real recipient addresses are involved.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from backend.config import Settings  # noqa: E402
from backend.generation.context_resolver import classify_audience, resolve_draft_context  # noqa: E402
from backend.main import create_app  # noqa: E402
from backend.schemas import (  # noqa: E402
    CorpusStatistics,
    GlobalStyleCard,
    GreetingFrequency,
    RecipientProfile,
    StylometryMetrics,
    UserStyleProfile,
)
from backend.storage import ChatSessionStore, ProfileStore  # noqa: E402

CASUAL_RULE = "Use a casual Hey greeting and slang like bro with this recipient"


def _example(mode: str, message_id: str = "m-1") -> dict[str, Any]:
    return {
        "message_id": message_id,
        "recipient_email": "kamisama7892@gmail.com",
        "recipient_domain": "gmail.com",
        "subject": "Status update",
        "clean_body": "Hi,\n\nEverything is on track for Thursday.\n\nBest",
        "greeting": "Hi," if mode == "1on1_private" else "Hi everyone,",
        "signoff": "Best",
        "word_count": 120,
        "timestamp": "2026-01-01T00:00:00+00:00",
        "timestamp_epoch": 1767225600.0,
        "audience_mode": mode,
        "cc_count": 0 if mode == "1on1_private" else 2,
        "bcc_count": 0 if mode != "broadcast_bcc" else 3,
    }


def _global_profile(rules: list[str] | None = None) -> dict[str, Any]:
    return {
        "profile_id": "profile-under-test",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "deterministic_stylometry": {
            "top_greetings": [{"pattern": "Hello {first_name},", "pct": 100}],
            "exact_signoff": "Regards, Chirag",
            "avg_sentence_length_words": 16.0,
            "avg_email_length_words": 42.0,
            "avg_paragraph_count": 3.0,
            "exclamation_rate": 0.0,
            "emoji_rate": 0.0,
            "uses_bullet_lists_pct": 0.0,
        },
        "global_style_card": {
            "formality": "semi-formal",
            "tone": "blunt-technical",
            "directness": "balanced",
            "vocabulary_level": "standard-professional",
            "sentence_structure": "short & punchy",
            "formatting_preferences": [],
            "characteristic_phrases": [],
            "source": "heuristic",
            "model": "heuristic",
            "sampled_email_count": 0,
        },
        "corpus_statistics": {
            "total_sent_emails": 12,
            "clean_emails_retained": 8,
            "top_recipients": [],
        },
        "global_learned_rules": list(rules or []),
    }


def _recipient_profile() -> dict[str, Any]:
    return {
        "recipient_email": "kamisama7892@gmail.com",
        "recipient_domain": "gmail.com",
        "relationship_tier": "peer",
        "preferred_greeting": "Hey Jatin,",
        "sent_count": 7,
        "learned_rules_json": [CASUAL_RULE],
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }


class ResolverUnitTests(unittest.TestCase):
    """Pure policy layer: no app, no database, no model."""

    def _resolve(self, *, to=None, cc=None, bcc=None, examples=None, instructions="", rules=None):
        return resolve_draft_context(
            to=to if to is not None else ["kamisama7892@gmail.com"],
            cc=cc or [],
            bcc=bcc or [],
            account_id="account-A",
            retrieved_emails=examples or [],
            recipient_profiles={"kamisama7892@gmail.com": _recipient_profile()},
            global_profile=_global_profile(rules),
            current_instructions=instructions,
        )

    def test_classify_audience_precedence(self) -> None:
        self.assertEqual(classify_audience(["a@example.com"], [], ["hidden@example.com"]), "broadcast_bcc")
        self.assertEqual(classify_audience(["a@example.com"], ["cc@example.com"], []), "group_cc")
        self.assertEqual(classify_audience(["a@example.com", "b@example.com"], [], []), "group_cc")
        self.assertEqual(classify_audience(["a@example.com"], [], []), "1on1_private")
        self.assertEqual(classify_audience([], [], ["hidden@example.com"]), "broadcast_bcc")

    def test_cc_added_suppresses_casual_greeting_and_rule(self) -> None:
        result = self._resolve(
            cc=["watcher@example.com"],
            examples=[_example("1on1_private"), _example("group_cc", "m-2")],
        )
        self.assertEqual(result["audience_type"], "group_cc")
        self.assertNotIn("Hey", result["greeting"])
        self.assertIn("Hi", result["greeting"])
        self.assertTrue(any(CASUAL_RULE in rule for rule in result["suppressed_rules"]))
        self.assertFalse(any(CASUAL_RULE in rule for rule in result["applied_rules"]))
        self.assertTrue(any("context sharing" in d.lower() or "self-contained" in d.lower()
                            for d in result["policy_directives"]))

    def test_cc_removed_restores_1on1_greeting_and_rule(self) -> None:
        result = self._resolve(examples=[_example("1on1_private")])
        self.assertEqual(result["audience_type"], "1on1_private")
        self.assertEqual(result["greeting"], "Hey Jatin,")
        self.assertTrue(any(CASUAL_RULE in rule for rule in result["applied_rules"]))
        self.assertEqual(result["suppressed_rules"], [])

    def test_bcc_switches_to_broadcast_and_suppresses_1on1(self) -> None:
        result = self._resolve(
            bcc=["hidden-1@example.com"],
            examples=[_example("broadcast_bcc")],
        )
        self.assertEqual(result["audience_type"], "broadcast_bcc")
        self.assertEqual(result["greeting"], "Hello everyone,")
        self.assertTrue(any(CASUAL_RULE in rule for rule in result["suppressed_rules"]))
        self.assertFalse(any(CASUAL_RULE in rule for rule in result["applied_rules"]))
        self.assertTrue(any("BCC" in d for d in result["policy_directives"]))

    def test_cold_start_group_fallback_excludes_1on1_examples(self) -> None:
        result = self._resolve(cc=["watcher@example.com"], examples=[_example("1on1_private")])
        self.assertTrue(result["cold_start_fallback"])
        self.assertEqual(result["examples"], [])
        probe = " ".join(result["policy_directives"] + result["applied_rules"]).lower()
        self.assertIn("evidence for this recipient/audience is low", probe)
        self.assertIn("professional baseline", probe)

    def test_group_examples_are_used_when_present(self) -> None:
        result = self._resolve(
            cc=["watcher@example.com"],
            examples=[_example("1on1_private"), _example("group_cc", "m-2")],
        )
        self.assertFalse(result["cold_start_fallback"])
        self.assertEqual([ex["message_id"] for ex in result["examples"]], ["m-2"])

    def test_tier1_formal_override_suppresses_casual_rules(self) -> None:
        result = self._resolve(
            instructions="/formal",
            rules=["Use casual slang and emojis in every email"],
            examples=[_example("1on1_private")],
        )
        self.assertEqual(result["audience_type"], "1on1_private")
        self.assertEqual(result["greeting"], "Hello Jatin,")
        self.assertTrue(any("casual" in rule.lower() for rule in result["suppressed_rules"]))

    def test_global_rules_apply_across_audiences(self) -> None:
        global_rule = "Always include a clear next step"
        private = self._resolve(rules=[global_rule])
        group = self._resolve(cc=["watcher@example.com"], rules=[global_rule])
        self.assertIn(f"Global rule: {global_rule}", private["applied_rules"])
        self.assertIn(f"Global rule: {global_rule}", group["applied_rules"])

    def test_account_isolation_never_leaks_other_account_rules(self) -> None:
        account_a = self._resolve(rules=["Account A only rule"])
        self.assertEqual(account_a["resolution_meta"]["account_id"], "account-A")
        self.assertIn("Account A only rule", " ".join(account_a["applied_rules"]))
        self.assertNotIn("Account B only rule", " ".join(account_a["applied_rules"]))

        # Records explicitly tagged for another account are ignored even if
        # a caller accidentally hands them to this resolution.
        foreign = resolve_draft_context(
            to=["kamisama7892@gmail.com"], cc=[], bcc=[], account_id="account-A",
            retrieved_emails=[{**_example("group_cc"), "account_id": "account-B"}],
            recipient_profiles={
                "kamisama7892@gmail.com": {**_recipient_profile(), "account_id": "account-B"}
            },
            global_profile={**_global_profile(["Account B only rule"]), "account_id": "account-B"},
        )
        self.assertNotIn("Account B only rule", " ".join(foreign["applied_rules"]))
        self.assertEqual(foreign["suppressed_rules"], [])
        # Neither B's greeting nor B's rules survive; a clean default is used.
        self.assertEqual(foreign["greeting"], "Hello,")


class _APITestBase(unittest.TestCase):
    """Temp-dir app/client fixtures with all model/embedder I/O mocked out."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.settings = Settings(
            local_user_data_dir=Path(self.temp_dir.name),
            profiler_mode="heuristic",
            model_name="not-installed-for-test",
        )
        # Never load sentence-transformers; retrieval is mocked in each test.
        self.load_patcher = patch("backend.main.LocalEmbedder.load", return_value=None)
        self.load_patcher.start()
        self.addCleanup(self.load_patcher.stop)

        self.app = create_app(settings=self.settings)
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _create_account(self, email: str) -> str:
        return self.app.state.account_manager.create_account(email=email, display_name="Test User").account_id

    @staticmethod
    def _headers(account_id: str) -> dict[str, str]:
        return {"X-Account-ID": account_id}

    def _write_profile(self, account_id: str, rules: list[str] | None = None) -> ProfileStore:
        account_settings = self.settings.for_account(account_id)
        store = ProfileStore(account_settings)
        model = UserStyleProfile(
            profile_id="profile-under-test",
            created_at=datetime.now(timezone.utc),
            deterministic_stylometry=StylometryMetrics(
                top_greetings=[GreetingFrequency(pattern="Hello {first_name},", pct=100)],
                exact_signoff="Regards, Chirag",
                avg_sentence_length_words=16.0,
            ),
            global_style_card=GlobalStyleCard(
                formality="semi-formal", tone="blunt-technical", directness="balanced",
                vocabulary_level="standard-professional", sentence_structure="short & punchy",
                formatting_preferences=[], characteristic_phrases=[], source="heuristic",
                model="heuristic", sampled_email_count=0,
            ),
            corpus_statistics=CorpusStatistics(total_sent_emails=12, clean_emails_retained=8),
            global_learned_rules=list(rules or []),
        )
        store.save_profile(model)
        store.upsert_recipient_profile(RecipientProfile(
            recipient_email="kamisama7892@gmail.com",
            recipient_domain="gmail.com",
            preferred_greeting="Hey Jatin,",
            learned_rules_json=[CASUAL_RULE],
            sent_count=5,
        ))
        return store

    def _stage_draft(self, account_id: str, draft_id: str = "draft-under-test") -> str:
        account_settings = self.settings.for_account(account_id)
        store = self._write_profile(account_id)
        sessions = ChatSessionStore(account_settings.chat_sessions_path)
        session = sessions.create_session(account_id, title="Audience test")
        card = sessions.upsert_draft_card(
            session_id=session["session_id"],
            to=["kamisama7892@gmail.com"], cc=[], bcc=[],
            subject="Original subject", body="Original body",
            status="PENDING_REVIEW", draft_id=draft_id,
        )
        with sqlite3.connect(account_settings.sqlite_path) as connection:
            connection.execute(
                """INSERT INTO pending_drafts
                   (draft_id, profile_id, request_json, draft, created_at,
                    recipient_profiles_json, audience_type, resolution_meta_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    draft_id, "profile-under-test",
                    json.dumps({
                        "to": ["kamisama7892@gmail.com"], "cc": [], "bcc": [],
                        "subject": "Original subject", "session_id": session["session_id"],
                        "card_id": card["card_id"],
                    }),
                    "Original body", datetime.now(timezone.utc).isoformat(), "{}",
                    "1on1_private", "{}",
                ),
            )
        return session["session_id"]

    @staticmethod
    def _retrieval_mock(captured: dict[str, Any]):
        def fake_retrieve(_self, **kwargs):
            captured["retrieval"] = kwargs
            mode = kwargs.get("target_audience_mode", "1on1_private")
            captured.setdefault("retrieved_for", []).append(mode)
            return [_example(mode)]
        return fake_retrieve


class DraftPatchAudienceTests(_APITestBase):
    """PATCH /api/draft/{id} recomputes and persists audience on edits."""

    def test_adding_and_removing_cc_updates_stored_audience(self) -> None:
        account_id = self._create_account("patch@example.com")
        headers = self._headers(account_id)
        session_id = self._stage_draft(account_id)
        draft_id = "draft-under-test"

        added = self.client.patch(
            f"/api/draft/{draft_id}",
            json={"cc": ["watcher@example.com"]},
            headers=headers,
        )
        self.assertEqual(added.status_code, 200, added.text)
        self.assertEqual(added.json()["audience_type"], "group_cc")

        account_settings = self.settings.for_account(account_id)
        pending = ProfileStore(account_settings).load_pending_draft(draft_id)
        assert pending is not None
        self.assertEqual(pending["audience_type"], "group_cc")
        self.assertEqual(pending["request"]["cc"], ["watcher@example.com"])
        detail = self.client.get(f"/api/chat/sessions/{session_id}", headers=headers).json()
        self.assertEqual(detail["draft_cards"][0]["audience_type"], "group_cc")

        removed = self.client.patch(f"/api/draft/{draft_id}", json={"cc": []}, headers=headers)
        self.assertEqual(removed.json()["audience_type"], "1on1_private")
        pending = ProfileStore(account_settings).load_pending_draft(draft_id)
        assert pending is not None
        self.assertEqual(pending["audience_type"], "1on1_private")

    def test_bcc_edit_switches_to_broadcast(self) -> None:
        account_id = self._create_account("bcc@example.com")
        headers = self._headers(account_id)
        self._stage_draft(account_id)
        response = self.client.patch(
            "/api/draft/draft-under-test",
            json={"bcc": ["hidden@example.com"]},
            headers=headers,
        )
        self.assertEqual(response.json()["audience_type"], "broadcast_bcc")

    def test_patch_is_isolated_per_account(self) -> None:
        owner = self._create_account("owner@example.com")
        intruder = self._create_account("intruder@example.com")
        self._stage_draft(owner)
        response = self.client.patch(
            "/api/draft/draft-under-test", json={"cc": ["x@example.com"]},
            headers=self._headers(intruder),
        )
        self.assertEqual(response.status_code, 404)
        pending = ProfileStore(self.settings.for_account(owner)).load_pending_draft("draft-under-test")
        assert pending is not None
        self.assertEqual(pending["audience_type"], "1on1_private")


class TweakRecalculationTests(_APITestBase):
    """POST /api/draft/tweak re-resolves audience and re-filters retrieval."""

    def _tweak(self, headers: dict[str, str], *, cc: list[str], instruction: str = "make it shorter"):
        captured: dict[str, Any] = {}
        with patch(
            "backend.main.QwenDrafter.revise_email_draft", autospec=True,
            side_effect=lambda self, **kwargs: (
                captured.update({"drafter": kwargs}) or
                {"subject": "Revised", "body": "Revised body"}
            ),
        ), patch(
            "backend.main.LanceDBVectorStore.retrieve_few_shot_examples", autospec=True,
            side_effect=self._retrieval_mock(captured),
        ):
            response = self.client.post(
                "/api/draft/tweak",
                json={
                    "draft_id": "draft-under-test",
                    "tweak_instruction": instruction,
                    "current_to": ["kamisama7892@gmail.com"],
                    "current_cc": cc,
                    "current_bcc": [],
                    "current_subject": "Original subject",
                    "current_body": "Original body",
                },
                headers=headers,
            )
        return response, captured

    def test_adding_cc_shifts_tweak_to_group_and_persists(self) -> None:
        account_id = self._create_account("tweak@example.com")
        headers = self._headers(account_id)
        session_id = self._stage_draft(account_id)

        response, captured = self._tweak(headers, cc=["watcher@example.com"])
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["audience_type"], "group_cc")
        self.assertEqual(body["subject"], "Revised")
        self.assertEqual(body["resolution_meta"]["account_id"], account_id)

        context = captured["drafter"]["context"]
        self.assertEqual(context["audience_type"], "group_cc")
        self.assertEqual([ex["audience_mode"] for ex in context["examples"]], ["group_cc"])
        self.assertTrue(any(CASUAL_RULE in rule for rule in context["suppressed_rules"]))
        self.assertEqual(captured["retrieval"]["target_audience_mode"], "group_cc")
        self.assertTrue(captured["retrieval"]["strict_audience"])

        pending = ProfileStore(self.settings.for_account(account_id)).load_pending_draft("draft-under-test")
        assert pending is not None
        self.assertEqual(pending["audience_type"], "group_cc")
        self.assertEqual(pending["draft"], "Revised body")
        detail = ChatSessionStore(
            self.settings.for_account(account_id).chat_sessions_path
        ).get_session(session_id)
        assert detail is not None
        card = detail["draft_cards"][0]
        self.assertEqual(card["audience_type"], "group_cc")

        # Removing the Cc restores the recipient's 1:1 rules on the next tweak.
        removed, removed_captured = self._tweak(headers, cc=[])
        self.assertEqual(removed.json()["audience_type"], "1on1_private")
        restored = removed_captured["drafter"]["context"]
        self.assertTrue(any(CASUAL_RULE in rule for rule in restored["applied_rules"]))
        self.assertEqual([ex["audience_mode"] for ex in restored["examples"]], ["1on1_private"])

    def test_tweak_is_isolated_per_account(self) -> None:
        owner = self._create_account("tweak-owner@example.com")
        intruder = self._create_account("tweak-intruder@example.com")
        self._stage_draft(owner)
        response, _ = self._tweak(self._headers(intruder), cc=["watcher@example.com"])
        self.assertEqual(response.status_code, 404)
        pending = ProfileStore(self.settings.for_account(owner)).load_pending_draft("draft-under-test")
        assert pending is not None
        self.assertEqual(pending["audience_type"], "1on1_private")


class InitialGenerationTests(_APITestBase):
    """Initial generation routes through the resolver before prompting."""

    def test_generate_uses_resolved_group_context(self) -> None:
        account_id = self._create_account("generate@example.com")
        self._write_profile(account_id)
        captured: dict[str, Any] = {}
        with patch(
            "backend.main.QwenDrafter.generate_draft", autospec=True,
            side_effect=lambda self, **kwargs: (
                captured.update({"context": kwargs.get("context")}) or "Generated body"
            ),
        ), patch(
            "backend.main.LanceDBVectorStore.retrieve_few_shot_examples", autospec=True,
            side_effect=self._retrieval_mock(captured),
        ):
            response = self.client.post(
                "/api/draft/generate",
                json={
                    "intent_bullets": "- Share the rollout plan\n- Ask for feedback",
                    "recipient_email": "kamisama7892@gmail.com",
                    "cc": ["watcher@example.com"],
                },
                headers=self._headers(account_id),
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["audience_type"], "group_cc")
        self.assertEqual(captured["context"]["audience_type"], "group_cc")
        self.assertEqual([ex["audience_mode"] for ex in response.json()["retrieved_examples"]], ["group_cc"])


if __name__ == "__main__":
    unittest.main()
