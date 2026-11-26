"""Offline tests for Layer 4D Pre-Send Explainability and Local-Only Pilot Metrics.

Zero network calls, zero Ollama/SMTP calls, temporary directories only.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch
import numpy as np

from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.automation.contact_resolver import Contact, ContactResolver  # noqa: E402
from backend.config import Settings  # noqa: E402
from backend.generation.context_resolver import resolve_draft_context  # noqa: E402
from backend.main import create_app  # noqa: E402
from backend.schemas import (  # noqa: E402
    CorpusStatistics,
    ExplainabilityPayload,
    GlobalStyleCard,
    GreetingFrequency,
    PilotMetricsResponse,
    RecipientProfile,
    StylometryMetrics,
    UserStyleProfile,
)
from backend.storage import ProfileStore  # noqa: E402
from backend.storage.secret_vault import protect_secret  # noqa: E402

CASUAL_RULE = "Use a casual Hey greeting and slang like bro"
NON_CASUAL_RULE = "Include ticket numbers when relevant"
GLOBAL_RULE = "Keep updates concise and action-oriented"


def _iso_days_ago(days: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _make_example(
    *,
    audience_mode: str = "1on1_private",
    similarity: float = 0.85,
    days_ago: float = 4.0,
    account_id: str = "acct-a",
    idx: int = 1,
) -> dict[str, Any]:
    return {
        "message_id": f"msg-{audience_mode}-{idx}",
        "recipient_email": "sam.park@vertex.ai",
        "recipient_domain": "vertex.ai",
        "subject": "Weekly Roadmap Sync",
        "clean_body": "Hi Sam,\n\nLet us align on Friday.\n\nBest",
        "greeting": "Hey Sam," if audience_mode == "1on1_private" else "Hi everyone,",
        "signoff": "Best",
        "word_count": 45,
        "audience_mode": audience_mode,
        "cc_count": 1 if audience_mode == "group_cc" else 0,
        "bcc_count": 2 if audience_mode == "broadcast_bcc" else 0,
        "similarity": similarity,
        "timestamp": _iso_days_ago(days_ago),
        "account_id": account_id,
    }


def _seed_profile(acc_settings: Settings, account_id: str) -> ProfileStore:
    store = ProfileStore(acc_settings)
    profile = UserStyleProfile(
        profile_id=f"prof-{account_id}",
        created_at=datetime.now(timezone.utc),
        deterministic_stylometry=StylometryMetrics(
            top_greetings=[GreetingFrequency(pattern="Hi {first_name},", pct=100.0)],
            exact_signoff="Best,\nAlex",
            avg_sentence_length_words=14.0,
            avg_email_length_words=45.0,
            avg_paragraph_count=2.0,
        ),
        global_style_card=GlobalStyleCard(
            formality="semi-formal",
            tone="clear and direct",
            directness="balanced",
            vocabulary_level="standard-professional",
            sentence_structure="short & punchy",
            formatting_preferences=[],
            characteristic_phrases=[],
            source="heuristic",
            model="heuristic",
            sampled_email_count=5,
        ),
        corpus_statistics=CorpusStatistics(total_sent_emails=5, clean_emails_retained=5, top_recipients=[]),
        global_learned_rules=[GLOBAL_RULE],
    )
    store.save_profile(profile)
    store.upsert_recipient_profile(
        RecipientProfile(
            recipient_email="sam.park@vertex.ai",
            recipient_domain="vertex.ai",
            relationship_tier="peer",
            preferred_greeting="Hey Sam,",
            sent_count=8,
            learned_rules_json=[CASUAL_RULE, NON_CASUAL_RULE],
        )
    )
    contact_resolver = ContactResolver(acc_settings.contacts_path)
    for contact in [
        Contact(email="sam.park@vertex.ai", full_name="Sam Park", first_name="Sam"),
        Contact(email="director@client.com", full_name="Director Lee", first_name="Director"),
        Contact(email="list-member@partner.org", full_name="Partner List", first_name="Partner"),
    ]:
        contact_resolver.upsert_contact(contact)
    return store


class ResolverExplainabilityUnitTests(unittest.TestCase):
    """Pure deterministic unit tests for resolution_meta['explainability']."""

    def _global_profile_dict(self) -> dict[str, Any]:
        return {
            "account_id": "acct-a",
            "global_style_card": {"formality": "semi-formal", "tone": "clear"},
            "deterministic_stylometry": {"exact_signoff": "Best regards", "avg_sentence_length_words": 15.0},
            "global_learned_rules": [GLOBAL_RULE],
        }

    def _recipient_profiles_dict(self) -> dict[str, Any]:
        return {
            "sam.park@vertex.ai": {
                "account_id": "acct-a",
                "preferred_greeting": "Hey Sam,",
                "preferred_signoff": "Cheers",
                "learned_rules_json": [CASUAL_RULE, NON_CASUAL_RULE],
            }
        }

    def test_1on1_high_confidence_explainability(self) -> None:
        examples = [_make_example(audience_mode="1on1_private", idx=i) for i in range(3)]
        ctx = resolve_draft_context(
            to=["sam.park@vertex.ai"],
            cc=[],
            bcc=[],
            account_id="acct-a",
            retrieved_emails=examples,
            recipient_profiles=self._recipient_profiles_dict(),
            global_profile=self._global_profile_dict(),
        )
        exp = ExplainabilityPayload.model_validate(ctx["resolution_meta"]["explainability"]).model_dump()
        self.assertEqual(exp["audience_type"], "1on1_private")
        self.assertEqual(exp["audience_label"], "1:1 Private")
        self.assertEqual(exp["audience_reason"], "1 recipient in To, no Cc/Bcc")
        self.assertEqual(exp["confidence_level"], "high")
        self.assertEqual(exp["retrieved_examples_count"], 3)
        self.assertIn("3 relevant 1:1", exp["retrieved_examples_summary"])
        self.assertEqual(exp["recipient_rules_used"], [CASUAL_RULE, NON_CASUAL_RULE])
        self.assertEqual(exp["global_rules_used"], [GLOBAL_RULE])
        self.assertEqual(exp["suppressed_rules"], [])
        self.assertFalse(exp["default_style_used"])
        self.assertIsNone(exp["default_style_reason"])

    def test_group_cc_escalation_suppresses_casual_and_falls_back_when_cold_start(self) -> None:
        # Only 1:1 examples exist -> Group CC gets cold-start fallback & suppresses casual rule
        examples = [_make_example(audience_mode="1on1_private", idx=i) for i in range(4)]
        ctx = resolve_draft_context(
            to=["sam.park@vertex.ai"],
            cc=["director@client.com"],
            bcc=[],
            account_id="acct-a",
            retrieved_emails=examples,
            recipient_profiles=self._recipient_profiles_dict(),
            global_profile=self._global_profile_dict(),
        )
        exp = ExplainabilityPayload.model_validate(ctx["resolution_meta"]["explainability"]).model_dump()
        self.assertEqual(exp["audience_type"], "group_cc")
        self.assertEqual(exp["audience_label"], "Group CC")
        self.assertIn("Cc", exp["audience_reason"])
        self.assertEqual(exp["confidence_level"], "low")
        self.assertEqual(exp["retrieved_examples_count"], 0)
        self.assertEqual(exp["retrieved_examples_summary"], "No prior group conversations found")
        self.assertIn(NON_CASUAL_RULE, exp["recipient_rules_used"])
        self.assertNotIn(CASUAL_RULE, exp["recipient_rules_used"])
        suppressed = exp["suppressed_rules"]
        self.assertEqual(len(suppressed), 1)
        self.assertEqual(suppressed[0]["rule"], CASUAL_RULE)
        self.assertIn("Cc", suppressed[0]["reason"])
        self.assertTrue(exp["default_style_used"])
        self.assertIsNotNone(exp["default_style_reason"])
        self.assertIn("Group CC", exp["default_style_reason"] or "")

    def test_broadcast_bcc_explainability(self) -> None:
        ctx = resolve_draft_context(
            to=["sam.park@vertex.ai"],
            cc=[],
            bcc=["one@partner.org", "two@partner.org"],
            account_id="acct-a",
            retrieved_emails=[],
            recipient_profiles=self._recipient_profiles_dict(),
            global_profile=self._global_profile_dict(),
        )
        exp = ExplainabilityPayload.model_validate(ctx["resolution_meta"]["explainability"]).model_dump()
        self.assertEqual(exp["audience_type"], "broadcast_bcc")
        self.assertEqual(exp["audience_label"], "Broadcast BCC")
        self.assertIn("Bcc", exp["audience_reason"])
        self.assertEqual(exp["recipient_rules_used"], [])
        self.assertEqual(len(exp["suppressed_rules"]), 2)
        self.assertTrue(exp["default_style_used"])
        self.assertIsNotNone(exp["default_style_reason"])


class ExplainabilityAndPilotMetricsApiTests(unittest.TestCase):
    """End-to-end API tests across all 4 draft paths + GET /api/pilot/metrics."""

    def setUp(self) -> None:
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="proteus_p4_test_"))
        self.settings = Settings(
            local_user_data_dir=self.tmp_dir,
            lancedb_dir=self.tmp_dir / "lancedb",
            profiler_mode="heuristic",
            model_name="not-installed-for-test",
        )
        self.app = create_app(settings=self.settings)
        self.client = TestClient(self.app)

        r_a = self.client.post("/api/auth/identity", json={"email": "alex@nexus.ai", "display_name": "Alex"})
        self.assertEqual(r_a.status_code, 200)
        self.account_a = r_a.json()["account"]["account_id"]
        self.acc_a_settings = self.settings.for_account(self.account_a)
        _seed_profile(self.acc_a_settings, self.account_a)
        (self.acc_a_settings.local_user_data_dir / "app_password.bin").write_text(
            protect_secret("abcd1234efgh5678", self.acc_a_settings.local_user_data_dir),
            encoding="utf-8",
        )

        r_b = self.client.post("/api/auth/identity", json={"email": "other@company.io", "display_name": "Other"})
        self.assertEqual(r_b.status_code, 200)
        self.account_b = r_b.json()["account"]["account_id"]
        _seed_profile(self.settings.for_account(self.account_b), self.account_b)

        self.headers_a = {"X-Account-ID": self.account_a}
        self.headers_b = {"X-Account-ID": self.account_b}

        self.sample_thread = {
            "thread_id": "imap_thread_p4",
            "subject": "Q4 Launch Alignment",
            "participants": ["sam.park@vertex.ai", "alex@nexus.ai", "director@client.com"],
            "messages": [
                {
                    "message_id": "<m-1@vertex.ai>",
                    "from_name": "Sam Park",
                    "from_email": "sam.park@vertex.ai",
                    "to": ["alex@nexus.ai"],
                    "cc": ["director@client.com"],
                    "date": "2026-11-26T10:00:00+00:00",
                    "subject": "Q4 Launch Alignment",
                    "body_text": "Can we confirm the release checklist for everyone?",
                    "in_reply_to": "",
                    "references": [],
                }
            ],
        }

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_all_draft_paths_emit_explainability_and_live_cc_toggle_updates(self) -> None:
        examples_1on1 = [_make_example(audience_mode="1on1_private", account_id=self.account_a, idx=i) for i in range(3)]

        with patch("backend.main.LanceDBVectorStore.retrieve_few_shot_examples", return_value=examples_1on1), \
             patch("backend.main.LocalEmbedder.load", return_value=None), \
             patch("backend.main.QwenDrafter.generate_draft", return_value="Hey Sam,\n\nConfirmed.\n\nBest,\nAlex"), \
             patch("backend.main.QwenDrafter.revise_email_draft", return_value={"subject": "Re: Q4 Launch", "body": "Hi Sam,\n\nUpdated for the group.\n\nBest,\nAlex"}), \
             patch("backend.connectors.gmail_app_password.GmailAppPasswordConnector.fetch_thread_messages", return_value=self.sample_thread):

            # 1. POST /api/draft/generate
            gen_res = self.client.post(
                "/api/draft/generate",
                json={
                    "intent_bullets": "- confirm Friday sync",
                    "recipient_email": "sam.park@vertex.ai",
                    "cc": [],
                    "bcc": [],
                },
                headers=self.headers_a,
            )
            self.assertEqual(gen_res.status_code, 200, gen_res.text)
            gen_exp = ExplainabilityPayload.model_validate(
                gen_res.json()["resolution_meta"]["explainability"]
            ).model_dump()
            self.assertEqual(gen_exp["audience_type"], "1on1_private")
            self.assertEqual(gen_exp["confidence_level"], "high")
            self.assertFalse(gen_exp["default_style_used"])
            self.assertIn(CASUAL_RULE, gen_exp["recipient_rules_used"])

            # 2. POST /api/chat/turn (broadcast_bcc)
            sess_id = self.client.post("/api/chat/sessions", json={"title": "Broadcast"}, headers=self.headers_a).json()["session_id"]
            turn_res = self.client.post(
                "/api/chat/turn",
                json={
                    "session_id": sess_id,
                    "user_message": "Send an email to sam.park@vertex.ai bcc list-member@partner.org subject Launch Update saying we shipped today",
                },
                headers=self.headers_a,
            )
            self.assertEqual(turn_res.status_code, 200, turn_res.text)
            card = turn_res.json()["draft_card"]
            self.assertIsNotNone(card)
            bcc_exp = ExplainabilityPayload.model_validate(card["resolution_meta"]["explainability"]).model_dump()
            self.assertEqual(bcc_exp["audience_type"], "broadcast_bcc")
            self.assertEqual(bcc_exp["audience_label"], "Broadcast BCC")
            self.assertTrue(bcc_exp["default_style_used"])
            self.assertTrue(any(item["rule"] == CASUAL_RULE for item in bcc_exp["suppressed_rules"]))

            # 3. POST /api/inbox/threads/{thread_id}/draft-reply (reply_all -> group_cc)
            reply_res = self.client.post(
                f"/api/inbox/threads/{self.sample_thread['thread_id']}/draft-reply",
                json={"reply_mode": "reply_all", "instruction": "Confirm checklist"},
                headers=self.headers_a,
            )
            self.assertEqual(reply_res.status_code, 200, reply_res.text)
            reply_data = reply_res.json()
            reply_exp = ExplainabilityPayload.model_validate(reply_data["resolution_meta"]["explainability"]).model_dump()
            self.assertEqual(reply_exp["audience_type"], "group_cc")
            self.assertEqual(reply_exp["audience_label"], "Group CC")
            self.assertTrue(any(item["rule"] == CASUAL_RULE for item in reply_exp["suppressed_rules"]))

            # 4a. Live PATCH /api/draft/{id} removing Cc restores 1:1 rules; adding Cc back suppresses them
            draft_id = reply_data["draft_id"]
            patch_1on1 = self.client.patch(
                f"/api/draft/{draft_id}",
                json={"to": ["sam.park@vertex.ai"], "cc": [], "bcc": []},
                headers=self.headers_a,
            )
            self.assertEqual(patch_1on1.status_code, 200, patch_1on1.text)
            p_exp_1 = ExplainabilityPayload.model_validate(
                patch_1on1.json()["resolution_meta"]["explainability"]
            ).model_dump()
            self.assertEqual(p_exp_1["audience_type"], "1on1_private")
            self.assertIn(CASUAL_RULE, p_exp_1["recipient_rules_used"])
            self.assertEqual(p_exp_1["suppressed_rules"], [])
            self.assertFalse(p_exp_1["default_style_used"])

            # 4b. Live POST /api/draft/tweak adding Cc escalates to group_cc
            tweak_cc = self.client.post(
                "/api/draft/tweak",
                json={
                    "draft_id": draft_id,
                    "tweak_instruction": "Keep this crisp for the director",
                    "current_to": ["sam.park@vertex.ai"],
                    "current_cc": ["director@client.com"],
                    "current_bcc": [],
                },
                headers=self.headers_a,
            )
            self.assertEqual(tweak_cc.status_code, 200, tweak_cc.text)
            t_exp = ExplainabilityPayload.model_validate(
                tweak_cc.json()["resolution_meta"]["explainability"]
            ).model_dump()
            self.assertEqual(t_exp["audience_type"], "group_cc")
            self.assertTrue(any(item["rule"] == CASUAL_RULE for item in t_exp["suppressed_rules"]))
            self.assertTrue(t_exp["default_style_used"])

    def test_pilot_metrics_accuracy_isolation_and_zero_pii(self) -> None:
        # Missing header -> 400; unknown header -> 404
        self.assertEqual(self.client.get("/api/pilot/metrics").status_code, 400)
        self.assertEqual(self.client.get("/api/pilot/metrics", headers={"X-Account-ID": "does-not-exist"}).status_code, 404)

        class FakeSMTP:
            def __init__(self, *args, **kwargs):
                pass
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def login(self, *args):
                pass
            def send_message(self, message, **kwargs):
                pass

        with patch("backend.main.LanceDBVectorStore.retrieve_few_shot_examples", return_value=[]), \
             patch("backend.main.LocalEmbedder.load", return_value=None), \
             patch("backend.main.QwenDrafter.generate_draft", return_value="Hi Sam,\n\nSecret project body text.\n\nBest,\nAlex"), \
             patch("backend.main.QwenDrafter.revise_email_draft", return_value={"subject": "Re: Secret Subject", "body": "Refined secret body text."}), \
             patch("backend.retrieval.embedder.LocalEmbedder.encode", return_value=np.zeros((1, 384), dtype=np.float32)), \
             patch("backend.connectors.gmail_app_password.GmailAppPasswordConnector.fetch_thread_messages", return_value=self.sample_thread), \
             patch("backend.connectors.gmail_app_password.smtplib.SMTP_SSL", FakeSMTP), \
             patch("backend.automation.style_learner.StyleLearner._extract_rules_from_diff", return_value=[]):

            # 1. Generate via /api/draft/generate (1on1)
            r1 = self.client.post(
                "/api/draft/generate",
                json={"intent_bullets": "- ping", "recipient_email": "sam.park@vertex.ai"},
                headers=self.headers_a,
            )
            self.assertEqual(r1.status_code, 200)

            # 2. Outbound compose via /api/chat/turn (1on1 -> will discard)
            sess_id = self.client.post("/api/chat/sessions", json={"title": "Secret Subject"}, headers=self.headers_a).json()["session_id"]
            r2 = self.client.post(
                "/api/chat/turn",
                json={"session_id": sess_id, "user_message": "Email sam.park@vertex.ai subject Secret Subject about confidential roadmap"},
                headers=self.headers_a,
            )
            self.assertEqual(r2.status_code, 200)
            discard_draft_id = r2.json()["draft_card"]["draft_id"]
            self.assertEqual(self.client.delete(f"/api/draft/{discard_draft_id}", headers=self.headers_a).status_code, 200)

            # 3. Inbox reply_all (group_cc) -> refine -> approve & send
            r3 = self.client.post(
                f"/api/inbox/threads/{self.sample_thread['thread_id']}/draft-reply",
                json={"reply_mode": "reply_all", "instruction": "Confirm"},
                headers=self.headers_a,
            )
            self.assertEqual(r3.status_code, 200)
            reply_draft_id = r3.json()["draft_id"]

            self.assertEqual(
                self.client.post(
                    "/api/draft/tweak",
                    json={"draft_id": reply_draft_id, "tweak_instruction": "Make concise"},
                    headers=self.headers_a,
                ).status_code,
                200,
            )
            self.assertEqual(
                self.client.post(
                    "/api/email/approve-and-learn",
                    json={"draft_id": reply_draft_id, "final_subject": "Re: Secret Subject", "final_body": "Refined secret body text."},
                    headers=self.headers_a,
                ).status_code,
                200,
            )

        # Check Account A metrics
        res_a = self.client.get("/api/pilot/metrics", headers=self.headers_a)
        self.assertEqual(res_a.status_code, 200, res_a.text)
        metrics_a = PilotMetricsResponse.model_validate(res_a.json()).model_dump()
        self.assertEqual(metrics_a["total_drafts_generated"], 3)
        self.assertEqual(metrics_a["inbox_replies_drafted"], 1)
        self.assertEqual(metrics_a["drafts_refined"], 1)
        self.assertEqual(metrics_a["drafts_sent"], 1)
        self.assertEqual(metrics_a["drafts_discarded"], 1)
        self.assertGreaterEqual(metrics_a["active_days"], 1)
        self.assertEqual(len(metrics_a["active_dates"]), metrics_a["active_days"])
        self.assertEqual(metrics_a["learned_rules_count"], 3)  # 1 global + 2 recipient
        self.assertEqual(metrics_a["audience_breakdown"]["1on1_private"], 2)
        self.assertEqual(metrics_a["audience_breakdown"]["group_cc"], 1)
        self.assertEqual(metrics_a["audience_breakdown"]["broadcast_bcc"], 0)

        # Strict privacy check: zero PII / email body / subject / address strings
        serialized = json.dumps(res_a.json()).lower()
        for forbidden in (
            "sam.park@vertex.ai",
            "director@client.com",
            "alex@nexus.ai",
            "secret project",
            "secret subject",
            "refined secret",
            "confidential roadmap",
        ):
            self.assertNotIn(forbidden, serialized)

        # Strict X-Account-ID isolation: Account B has zero activity
        res_b = self.client.get("/api/pilot/metrics", headers=self.headers_b)
        self.assertEqual(res_b.status_code, 200)
        metrics_b = PilotMetricsResponse.model_validate(res_b.json()).model_dump()
        self.assertEqual(metrics_b["total_drafts_generated"], 0)
        self.assertEqual(metrics_b["inbox_replies_drafted"], 0)
        self.assertEqual(metrics_b["drafts_refined"], 0)
        self.assertEqual(metrics_b["drafts_sent"], 0)
        self.assertEqual(metrics_b["drafts_discarded"], 0)
        self.assertEqual(metrics_b["active_days"], 0)
        self.assertEqual(metrics_b["active_dates"], [])
        self.assertEqual(metrics_b["learned_rules_count"], 3)


if __name__ == "__main__":
    unittest.main()
