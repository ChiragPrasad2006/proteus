"""Offline unit & integration tests for read-only Inbox threads and manual reply drafting.

Zero real IMAP/SMTP/Gmail/Ollama calls: connectors, LLM, and SMTP are mocked,
and all SQLite/LanceDB state lives inside temporary directories.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.config import Settings
from backend.connectors.imap_mbox import ImapConnector
from backend.main import create_app
from backend.schemas import (
    CorpusStatistics,
    GlobalStyleCard,
    GreetingFrequency,
    RecipientProfile,
    StylometryMetrics,
    UserStyleProfile,
)
from backend.storage import ProfileStore
from backend.storage.secret_vault import protect_secret


def _raw_rfc822(
    *,
    msg_id: str,
    sender: str,
    to: str,
    cc: str = "",
    subject: str = "Q4 Roadmap Sync",
    date: str = "Thu, 26 Nov 2026 10:00:00 +0000",
    body: str = "Let us review the Q4 timeline.",
    html_only: bool = False,
    in_reply_to: str = "",
    references: str = "",
) -> bytes:
    msg = EmailMessage()
    msg["Message-ID"] = msg_id
    msg["From"] = sender
    msg["To"] = to
    if cc:
        msg["Cc"] = cc
    msg["Subject"] = subject
    msg["Date"] = date
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = references
    if html_only:
        msg.add_alternative(f"<html><body><p>{body}</p><script>bad()</script></body></html>", subtype="html")
    else:
        msg.set_content(body)
    return msg.as_bytes()


def _seed_account_profile(acc_settings: Settings, email_addr: str) -> None:
    store = ProfileStore(acc_settings)
    profile = UserStyleProfile(
        profile_id=f"prof-{email_addr}",
        created_at=datetime.now(timezone.utc),
        deterministic_stylometry=StylometryMetrics(
            top_greetings=[GreetingFrequency(pattern="Hi {first_name},", pct=100.0)],
            exact_signoff="Best,\nAlex",
            avg_sentence_length_words=14.0,
            avg_email_length_words=50.0,
            avg_paragraph_count=2.0,
        ),
        global_style_card=GlobalStyleCard(
            formality="semi-formal",
            tone="clear and direct",
            directness="balanced",
            vocabulary_level="standard-professional",
            sentence_structure="short & punchy",
            formatting_preferences=["No markdown"],
            characteristic_phrases=[],
            source="heuristic",
            model="heuristic",
            sampled_email_count=5,
        ),
        corpus_statistics=CorpusStatistics(total_sent_emails=5, clean_emails_retained=5, top_recipients=[]),
        global_learned_rules=["Keep replies concise"],
    )
    store.save_profile(profile)
    store.upsert_recipient_profile(
        RecipientProfile(
            recipient_email="sam.park@vertex.ai",
            recipient_domain="vertex.ai",
            relationship_tier="peer",
            preferred_greeting="Hey Sam,",
            sent_count=8,
            learned_rules_json=["Use a casual Hey greeting and slang like bro"],
        )
    )


class TestImapPeekAndGrouping(unittest.TestCase):
    """Verify IMAP uses BODY.PEEK[] and groups threads chronologically."""

    def test_imap_uses_body_peek_only_and_groups_threads(self) -> None:
        m1 = _raw_rfc822(
            msg_id="<m1@vertex.ai>",
            sender="Sam Park <sam.park@vertex.ai>",
            to="alex@nexus.ai",
            subject="Vertex Deploy",
            date="Thu, 26 Nov 2026 09:00:00 +0000",
            body="Can we ship on Friday?",
            html_only=True,
        )
        m2 = _raw_rfc822(
            msg_id="<m2@nexus.ai>",
            sender="Alex <alex@nexus.ai>",
            to="sam.park@vertex.ai",
            subject="Re: Vertex Deploy",
            date="Thu, 26 Nov 2026 09:30:00 +0000",
            body="Yes, Friday looks good.",
            in_reply_to="<m1@vertex.ai>",
            references="<m1@vertex.ai>",
        )
        m3 = _raw_rfc822(
            msg_id="<m3@vertex.ai>",
            sender="Sam Park <sam.park@vertex.ai>",
            to="alex@nexus.ai",
            cc="director@client.com",
            subject="Re: Vertex Deploy",
            date="Thu, 26 Nov 2026 10:15:00 +0000",
            body="Looping in our director for visibility.",
            in_reply_to="<m2@nexus.ai>",
            references="<m1@vertex.ai> <m2@nexus.ai>",
        )
        raw_map = {b"1": m1, b"2": m2, b"3": m3}
        fetch_args: list[str] = []

        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.select.return_value = ("OK", [b"3"])
        mock_client.search.side_effect = lambda _charset, criteria: (
            ("OK", [b"3"]) if criteria == "UNSEEN" else ("OK", [b"1 2 3"])
        )

        def fake_fetch(num: bytes, parts: str):
            fetch_args.append(parts)
            return ("OK", [(b"1 (BODY[] {1})", raw_map[num])])

        mock_client.fetch.side_effect = fake_fetch

        with patch("backend.connectors.imap_mbox.imaplib.IMAP4_SSL", return_value=mock_client):
            conn = ImapConnector("imap.gmail.com", "alex@nexus.ai", "abcd1234efgh5678")
            summaries = conn.fetch_inbox_threads(limit=25)
            self.assertEqual(len(summaries), 1)
            t = summaries[0]
            self.assertEqual(t["message_count"], 3)
            self.assertTrue(t["unread"])
            self.assertEqual(t["latest_sender_email"], "sam.park@vertex.ai")

            detail = conn.fetch_thread_messages(t["thread_id"])
            self.assertIsNotNone(detail)
            assert detail is not None
            self.assertEqual([m["message_id"] for m in detail["messages"]], ["<m1@vertex.ai>", "<m2@nexus.ai>", "<m3@vertex.ai>"])
            self.assertIn("Can we ship on Friday?", detail["messages"][0]["body_text"])
            self.assertNotIn("<script>", detail["messages"][0]["body_text"])

        mock_client.select.assert_any_call("INBOX", readonly=True)
        self.assertTrue(all(arg == "(BODY.PEEK[])" for arg in fetch_args))
        self.assertFalse(any("RFC822" in arg or arg == "(BODY[])" for arg in fetch_args))


class TestInboxReplyEndpoints(unittest.TestCase):
    """End-to-end API tests with mocked connectors, LLM, and SMTP."""

    def setUp(self) -> None:
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="proteus_inbox_test_"))
        self.settings = Settings(local_user_data_dir=self.tmp_dir, lancedb_dir=self.tmp_dir / "lancedb")
        self.app = create_app(self.settings)
        self.client = TestClient(self.app)

        # Create Account A (Google Identity + App Password without gmail.readonly -> IMAP fallback)
        r_a = self.client.post("/api/auth/identity", json={"email": "alex@nexus.ai", "display_name": "Alex"})
        self.assertEqual(r_a.status_code, 200)
        self.account_a = r_a.json()["account"]["account_id"]
        acc_a_settings = self.settings.for_account(self.account_a)
        _seed_account_profile(acc_a_settings, "alex@nexus.ai")
        (acc_a_settings.local_user_data_dir / "app_password.bin").write_text(
            protect_secret("abcd1234efgh5678", acc_a_settings.local_user_data_dir),
            encoding="utf-8",
        )

        # Create Account B (separate isolated account)
        r_b = self.client.post("/api/auth/identity", json={"email": "other@company.io", "display_name": "Other"})
        self.assertEqual(r_b.status_code, 200)
        self.account_b = r_b.json()["account"]["account_id"]

        self.sample_thread = {
            "thread_id": "imap_1234567890abcdef",
            "subject": "Vertex Deploy Plan",
            "participants": ["sam.park@vertex.ai", "alex@nexus.ai", "director@client.com"],
            "messages": [
                {
                    "message_id": "<msg-1@vertex.ai>",
                    "from_name": "Sam Park",
                    "from_email": "sam.park@vertex.ai",
                    "to": ["alex@nexus.ai", "peer@vertex.ai"],
                    "cc": ["director@client.com", "alex@nexus.ai"],
                    "date": "2026-11-26T10:00:00+00:00",
                    "subject": "Vertex Deploy Plan",
                    "body_text": "Can we confirm Friday deploy with the client director CC'd?",
                    "in_reply_to": "",
                    "references": ["<root-0@vertex.ai>"],
                }
            ],
        }
        self.sample_summary = {
            "thread_id": self.sample_thread["thread_id"],
            "subject": self.sample_thread["subject"],
            "snippet": "Can we confirm Friday deploy...",
            "last_message_at": "2026-11-26T10:00:00+00:00",
            "message_count": 1,
            "participants": self.sample_thread["participants"],
            "unread": True,
            "latest_sender_name": "Sam Park",
            "latest_sender_email": "sam.park@vertex.ai",
        }

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_reply_vs_reply_all_and_group_cc_precedence(self) -> None:
        captured_contexts: list[dict[str, Any]] = []

        def fake_generate_draft(self_drafter, **kwargs):
            captured_contexts.append(kwargs.get("context") or {})
            return "Hi Sam,\n\nConfirmed for Friday.\n\nBest,\nAlex"

        with patch("backend.connectors.gmail_app_password.GmailAppPasswordConnector.fetch_inbox_threads", return_value=[self.sample_summary]), \
             patch("backend.connectors.gmail_app_password.GmailAppPasswordConnector.fetch_thread_messages", return_value=self.sample_thread), \
             patch("backend.main.QwenDrafter.generate_draft", new=fake_generate_draft):

            # 1. List threads for Account A
            res_list = self.client.get("/api/inbox/threads", headers={"X-Account-ID": self.account_a})
            self.assertEqual(res_list.status_code, 200)
            self.assertEqual(len(res_list.json()["threads"]), 1)

            # 2. Reply mode (1:1 only to Sam, no CC)
            res_reply = self.client.post(
                f"/api/inbox/threads/{self.sample_thread['thread_id']}/draft-reply",
                json={"reply_mode": "reply", "instruction": "Confirm Friday"},
                headers={"X-Account-ID": self.account_a},
            )
            self.assertEqual(res_reply.status_code, 200)
            d_reply = res_reply.json()
            self.assertEqual(d_reply["status"], "PENDING_REVIEW")
            self.assertEqual(d_reply["to"], ["sam.park@vertex.ai"])
            self.assertEqual(d_reply["cc"], [])
            self.assertEqual(d_reply["subject"], "Re: Vertex Deploy Plan")
            self.assertEqual(d_reply["in_reply_to"], "<msg-1@vertex.ai>")
            self.assertEqual(d_reply["references"], ["<root-0@vertex.ai>", "<msg-1@vertex.ai>"])
            self.assertEqual(d_reply["audience_type"], "1on1_private")

            # 3. Reply All mode -> excludes self, triggers group_cc & suppresses casual 1:1 rule
            res_all = self.client.post(
                f"/api/inbox/threads/{self.sample_thread['thread_id']}/draft-reply",
                json={"reply_mode": "reply_all", "instruction": "Confirm Friday for everyone"},
                headers={"X-Account-ID": self.account_a},
            )
            self.assertEqual(res_all.status_code, 200)
            d_all = res_all.json()
            self.assertEqual(d_all["status"], "PENDING_REVIEW")
            self.assertEqual(d_all["to"], ["sam.park@vertex.ai", "peer@vertex.ai"])
            self.assertEqual(d_all["cc"], ["director@client.com"])
            self.assertNotIn("alex@nexus.ai", d_all["to"] + d_all["cc"])
            self.assertEqual(d_all["audience_type"], "group_cc")

            group_ctx = captured_contexts[-1]
            self.assertTrue(any("casual" in r.lower() for r in group_ctx["suppressed_rules"]))
            self.assertFalse(any("slang like bro" in r.lower() for r in group_ctx["applied_rules"]))

    def test_approve_and_learn_propagates_headers_and_learns_rules(self) -> None:
        sent_messages: list[Any] = []

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
                sent_messages.append(message)

        with patch("backend.connectors.gmail_app_password.GmailAppPasswordConnector.fetch_thread_messages", return_value=self.sample_thread), \
             patch("backend.main.QwenDrafter.generate_draft", return_value="Hi Sam,\n\nSounds good.\n\nBest,\nAlex"):
            res = self.client.post(
                f"/api/inbox/threads/{self.sample_thread['thread_id']}/draft-reply",
                json={"reply_mode": "reply_all"},
                headers={"X-Account-ID": self.account_a},
            )
            self.assertEqual(res.status_code, 200)
            draft_id = res.json()["draft_id"]

        with patch("backend.connectors.gmail_app_password.smtplib.SMTP_SSL", FakeSMTP), \
             patch("backend.automation.style_learner.StyleLearner._extract_rules_from_diff", return_value=["Keep group replies structured with explicit milestones."]):
            approve_res = self.client.post(
                "/api/email/approve-and-learn",
                json={
                    "draft_id": draft_id,
                    "final_subject": "Re: Vertex Deploy Plan",
                    "final_body": "Hi Sam,\n\nFriday deployment is confirmed.\n- Milestone 1: staging\n\nBest,\nAlex",
                },
                headers={"X-Account-ID": self.account_a},
            )
            self.assertEqual(approve_res.status_code, 200)
            body = approve_res.json()
            self.assertEqual(body["status"], "SENT")
            self.assertEqual(body["extracted_rules"], ["Keep group replies structured with explicit milestones."])

        self.assertEqual(len(sent_messages), 1)
        smtp_msg = sent_messages[0]
        self.assertEqual(smtp_msg["In-Reply-To"], "<msg-1@vertex.ai>")
        self.assertEqual(smtp_msg["References"], "<root-0@vertex.ai> <msg-1@vertex.ai>")
        self.assertEqual(smtp_msg["Subject"], "Re: Vertex Deploy Plan")

        acc_a_store = ProfileStore(self.settings.for_account(self.account_a))
        self.assertIn("Keep group replies structured with explicit milestones.", acc_a_store.load_profile().global_learned_rules)

    def test_account_isolation_blocks_cross_account_inbox_access(self) -> None:
        # Account B has no App Password / gmail.readonly and cannot access Account A's thread.
        res_list_b = self.client.get("/api/inbox/threads", headers={"X-Account-ID": self.account_b})
        self.assertEqual(res_list_b.status_code, 400)

        res_draft_b = self.client.post(
            f"/api/inbox/threads/{self.sample_thread['thread_id']}/draft-reply",
            json={"reply_mode": "reply"},
            headers={"X-Account-ID": self.account_b},
        )
        self.assertEqual(res_draft_b.status_code, 404)


if __name__ == "__main__":
    unittest.main()
