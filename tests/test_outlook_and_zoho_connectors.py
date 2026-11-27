"""Offline unit and integration tests for Outlook (Graph OAuth2) and Zoho Mail connectors."""

from __future__ import annotations

import email
import json
import tempfile
import time
import unittest
from email.message import EmailMessage
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

import numpy as np
from fastapi.testclient import TestClient

from backend.auth.microsoft_oauth import load_outlook_tokens, save_outlook_tokens
from backend.auth.zoho_oauth import ZOHO_REGIONS, get_zoho_region_config
from backend.config import Settings
from backend.connectors import (
    OutlookGraphConnector,
    ZohoMailConnector,
    get_connector_for_account,
)
from backend.main import create_app
from backend.schemas import (
    CorpusStatistics,
    GlobalStyleCard,
    OutboundEmailRequest,
    StylometryMetrics,
    UserStyleProfile,
)
from backend.storage import ProfileStore


def _sample_profile() -> UserStyleProfile:
    return UserStyleProfile(
        profile_id="prof-1",
        created_at=datetime(2026, 11, 27, 10, 0, 0, tzinfo=timezone.utc),
        deterministic_stylometry=StylometryMetrics(
            exact_signoff="Best,",
            avg_sentence_length_words=12.0,
            avg_email_length_words=45.0,
        ),
        global_style_card=GlobalStyleCard(
            formality="semi-formal",
            tone="Direct and warm",
            directness="high",
            vocabulary_level="standard-professional",
            sentence_structure="short & punchy",
            formatting_preferences=["short paragraphs"],
            characteristic_phrases=["Sounds good"],
            source="heuristic",
            model="heuristic",
            sampled_email_count=10,
        ),
        corpus_statistics=CorpusStatistics(total_sent_emails=10, clean_emails_retained=10),
        global_learned_rules=["Keep updates concise"],
    )


class TestOutlookGraphConnector(unittest.TestCase):
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

    def test_outlook_oauth_config_start_callback_and_token_refresh(self) -> None:
        st0 = self.client.get("/api/auth/outlook/status")
        self.assertEqual(st0.status_code, 200)
        self.assertFalse(st0.json()["configured"])

        cfg_res = self.client.post(
            "/api/auth/outlook/configure",
            json={"client_id": "ms-client-123", "tenant_id": "common"},
        )
        self.assertEqual(cfg_res.status_code, 200)
        self.assertTrue(cfg_res.json()["configured"])
        self.assertFalse(cfg_res.json()["has_client_secret"])

        start_res = self.client.post("/api/auth/outlook/start")
        self.assertEqual(start_res.status_code, 200)
        start_data = start_res.json()
        parsed = urlparse(start_data["auth_url"])
        qs = parse_qs(parsed.query)
        self.assertEqual(qs["client_id"][0], "ms-client-123")
        self.assertEqual(qs["code_challenge_method"][0], "S256")
        self.assertIn("Mail.Read", qs["scope"][0])
        self.assertIn("Mail.Send", qs["scope"][0])

        mock_token_resp = MagicMock()
        mock_token_resp.raise_for_status = MagicMock()
        mock_token_resp.json.return_value = {
            "access_token": "ms-access-1",
            "refresh_token": "ms-refresh-1",
            "expires_in": 3600,
        }
        mock_me_resp = MagicMock()
        mock_me_resp.raise_for_status = MagicMock()
        mock_me_resp.json.return_value = {
            "mail": "alex.mercer@outlook.com",
            "displayName": "Alex Mercer",
        }

        with patch("backend.auth.microsoft_oauth.httpx.post", return_value=mock_token_resp), \
             patch("backend.auth.microsoft_oauth.httpx.get", return_value=mock_me_resp), \
             patch("backend.main.OutlookGraphConnector.fetch_sent_emails", return_value=[]):
            cb = self.client.get(
                f"/api/auth/outlook/callback?code=auth-code-1&state={start_data['state']}",
                follow_redirects=False,
            )
        self.assertEqual(cb.status_code, 307)
        location = cb.headers["location"]
        self.assertIn("/workspace?auth=success&account_id=", location)
        account_id = parse_qs(urlparse(location).query)["account_id"][0]

        acc = self.app.state.account_manager.get_account(account_id)
        self.assertIsNotNone(acc)
        self.assertEqual(acc.provider, "outlook")
        self.assertTrue(acc.mailbox_connected)

        # Verify encrypted token storage and automatic refresh
        acc_settings = self.settings.for_account(account_id)
        saved = load_outlook_tokens(acc_settings)
        assert saved is not None
        self.assertEqual(saved["access_token"], "ms-access-1")
        saved["expires_at"] = time.time() - 120
        save_outlook_tokens(acc_settings, saved)

        refresh_resp = MagicMock()
        refresh_resp.raise_for_status = MagicMock()
        refresh_resp.json.return_value = {
            "access_token": "ms-access-refreshed",
            "refresh_token": "ms-refresh-2",
            "expires_in": 3600,
        }
        me_resp = MagicMock()
        me_resp.raise_for_status = MagicMock()
        me_resp.json.return_value = {"mail": "alex.mercer@outlook.com", "displayName": "Alex Mercer"}

        conn = get_connector_for_account(account_id, self.settings, self.app.state.account_manager)
        self.assertIsInstance(conn, OutlookGraphConnector)
        with patch("backend.auth.microsoft_oauth.httpx.post", return_value=refresh_resp) as p_post, \
             patch("backend.connectors.outlook_connector.httpx.get", return_value=me_resp):
            info = conn.test_connection()
        self.assertTrue(info["ok"])
        self.assertTrue(p_post.called)
        self.assertEqual(load_outlook_tokens(acc_settings)["access_token"], "ms-access-refreshed")

    def test_outlook_sent_inbox_and_threaded_send(self) -> None:
        conn = OutlookGraphConnector(access_token="tok-1")

        sent_resp = MagicMock()
        sent_resp.raise_for_status = MagicMock()
        sent_resp.json.return_value = {
            "value": [
                {
                    "id": "m1",
                    "internetMessageId": "<sent-1@outlook.com>",
                    "conversationId": "conv-1",
                    "toRecipients": [{"emailAddress": {"address": "sam@example.com"}}],
                    "subject": "Roadmap",
                    "body": {"contentType": "html", "content": "<p>Hi Sam,</p><p>Let us ship Friday.</p>"},
                    "sentDateTime": "2026-11-27T09:00:00Z",
                }
            ]
        }
        with patch("backend.connectors.outlook_connector.httpx.get", return_value=sent_resp):
            sent = conn.fetch_sent_emails(limit=10)
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0].recipient_email, "sam@example.com")
        self.assertIn("Let us ship Friday.", sent[0].raw_body)

        inbox_resp = MagicMock()
        inbox_resp.raise_for_status = MagicMock()
        inbox_resp.json.return_value = {
            "value": [
                {
                    "id": "in-1",
                    "internetMessageId": "<in-1@outlook.com>",
                    "conversationId": "conv-abc",
                    "from": {"emailAddress": {"name": "Priya", "address": "priya@client.io"}},
                    "toRecipients": [{"emailAddress": {"address": "alex@outlook.com"}}],
                    "ccRecipients": [],
                    "subject": "Contract Review",
                    "body": {"contentType": "text", "content": "Can we review clause 4?"},
                    "receivedDateTime": "2026-11-27T10:00:00Z",
                    "isRead": False,
                },
                {
                    "id": "in-2",
                    "internetMessageId": "<in-2@outlook.com>",
                    "conversationId": "conv-abc",
                    "from": {"emailAddress": {"name": "Priya", "address": "priya@client.io"}},
                    "toRecipients": [{"emailAddress": {"address": "alex@outlook.com"}}],
                    "ccRecipients": [],
                    "subject": "Re: Contract Review",
                    "body": {"contentType": "text", "content": "Following up on clause 4."},
                    "receivedDateTime": "2026-11-27T11:00:00Z",
                    "isRead": True,
                },
            ]
        }
        with patch("backend.connectors.outlook_connector.httpx.get", return_value=inbox_resp) as g_get, \
             patch("backend.connectors.outlook_connector.httpx.patch") as g_patch:
            threads = conn.fetch_inbox_threads(limit=10)
            detail = conn.fetch_thread_messages("conv-abc")
        g_patch.assert_not_called()
        self.assertTrue(g_get.called)
        self.assertEqual(len(threads), 1)
        self.assertEqual(threads[0]["thread_id"], "conv-abc")
        self.assertEqual(threads[0]["message_count"], 2)
        self.assertTrue(threads[0]["unread"])
        self.assertIsNotNone(detail)
        self.assertEqual(len(detail["messages"]), 2)

        send_resp = MagicMock()
        send_resp.status_code = 202
        send_resp.headers = {"request-id": "graph-req-1"}
        with patch("backend.connectors.outlook_connector.httpx.post", return_value=send_resp) as g_post:
            receipt = conn.send_email(
                OutboundEmailRequest(
                    to=["priya@client.io"],
                    subject="Re: Contract Review",
                    body="Approved.",
                    thread_id="conv-abc",
                    in_reply_to="<in-2@outlook.com>",
                    references=["<in-1@outlook.com>", "<in-2@outlook.com>"],
                )
            )
        self.assertEqual(receipt.status, "sent")
        sent_json = g_post.call_args.kwargs["json"]["message"]
        self.assertEqual(sent_json["conversationId"], "conv-abc")
        header_map = {h["name"]: h["value"] for h in sent_json["internetMessageHeaders"]}
        self.assertEqual(header_map["In-Reply-To"], "<in-2@outlook.com>")
        self.assertIn("<in-1@outlook.com>", header_map["References"])


class TestZohoMailConnector(unittest.TestCase):
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

    def test_region_mapping(self) -> None:
        for region in ("in", "com", "eu", "com.au", "jp"):
            cfg = get_zoho_region_config(region)
            self.assertEqual(cfg["imap_port"], 993)
            self.assertEqual(cfg["smtp_port"], 465)
            self.assertIn(region, ZOHO_REGIONS)
            self.assertTrue(cfg["imap_pro"].startswith("imappro.zoho."))
            self.assertTrue(cfg["imap_free"].startswith("imap.zoho."))

    def test_zoho_pro_to_free_fallback_and_connect_endpoint(self) -> None:
        imap_hosts_tried: list[str] = []
        smtp_hosts_tried: list[str] = []

        raw_sent = EmailMessage()
        raw_sent["From"] = "kiran@zoho.in"
        raw_sent["To"] = "partner@acme.in"
        raw_sent["Subject"] = "Q4 Plan"
        raw_sent["Message-ID"] = "<z-sent-1@zoho.in>"
        raw_sent.set_content("Hi team, here is the Q4 plan with all milestones and deliverables." * 2)
        raw_sent_bytes = raw_sent.as_bytes()

        class FakeIMAP:
            def __init__(self, host: str, port: int) -> None:
                imap_hosts_tried.append(host)
                self.host = host
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def login(self, user: str, pwd: str) -> None:
                if self.host.startswith("imappro."):
                    raise OSError("imappro rejected free account")
            def select(self, folder: str, readonly: bool = False):
                assert readonly is True
                return ("OK", [b"1"])
            def search(self, charset, criteria):
                return ("OK", [b"1"])
            def fetch(self, num, spec):
                assert spec == "(BODY.PEEK[])"
                return ("OK", [(b"1 (BODY[] {100})", raw_sent_bytes)])

        class FakeSMTP:
            def __init__(self, host: str, port: int) -> None:
                smtp_hosts_tried.append(host)
                self.host = host
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def login(self, user: str, pwd: str) -> None:
                if self.host.startswith("smtppro."):
                    raise OSError("smtppro rejected free account")
            def send_message(self, msg, from_addr=None, to_addrs=None):
                return {}

        with patch("backend.connectors.zoho_connector.imaplib.IMAP4_SSL", FakeIMAP), \
             patch("backend.connectors.zoho_connector.smtplib.SMTP_SSL", FakeSMTP), \
             patch("backend.main.LocalEmbedder.encode", return_value=np.zeros((1, 384), dtype=np.float32)):
            res = self.client.post(
                "/api/onboarding/connect-zoho",
                json={
                    "email": "kiran@zoho.in",
                    "display_name": "Kiran",
                    "app_password": "zoho-app-pw-1234",
                    "region": "in",
                },
            )
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertEqual(body["account"]["provider"], "zoho")
        self.assertTrue(body["account"]["mailbox_connected"])
        self.assertEqual(imap_hosts_tried[:2], ["imappro.zoho.in", "imap.zoho.in"])
        self.assertEqual(smtp_hosts_tried[0], "smtp.zoho.in")

        account_id = body["account"]["account_id"]
        conn = get_connector_for_account(account_id, self.settings, self.app.state.account_manager)
        self.assertIsInstance(conn, ZohoMailConnector)
        self.assertEqual(conn.imap_host, "imap.zoho.in")
        self.assertEqual(conn.smtp_host, "smtp.zoho.in")

    def test_zoho_readonly_inbox_and_threaded_smtp_send(self) -> None:
        msg1 = EmailMessage()
        msg1["From"] = "Client <client@vendor.com>"
        msg1["To"] = "kiran@zoho.in"
        msg1["Subject"] = "Invoice #42"
        msg1["Message-ID"] = "<inv-42@vendor.com>"
        msg1["Date"] = "Fri, 27 Nov 2026 09:00:00 +0000"
        msg1.set_content("Please confirm Invoice #42.")

        observed_selects: list[tuple[str, bool]] = []
        observed_fetches: list[str] = []
        sent_messages: list[EmailMessage] = []

        class FakeIMAP:
            def __init__(self, host: str, port: int) -> None: pass
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def login(self, user: str, pwd: str) -> None: pass
            def select(self, folder: str, readonly: bool = False):
                observed_selects.append((folder, readonly))
                return ("OK", [b"1"])
            def search(self, charset, criteria):
                return ("OK", [b"1"])
            def fetch(self, num, spec):
                observed_fetches.append(spec)
                return ("OK", [(b"1 (BODY[] {100})", msg1.as_bytes())])

        class FakeSMTP:
            def __init__(self, host: str, port: int) -> None: pass
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def login(self, user: str, pwd: str) -> None: pass
            def send_message(self, msg, from_addr=None, to_addrs=None):
                sent_messages.append(msg)

        conn = ZohoMailConnector("kiran@zoho.in", "zoho-pw", region="eu")
        with patch("backend.connectors.imap_mbox.imaplib.IMAP4_SSL", FakeIMAP):
            threads = conn.fetch_inbox_threads(limit=5)
            self.assertEqual(len(threads), 1)
            detail = conn.fetch_thread_messages(threads[0]["thread_id"])
        self.assertIsNotNone(detail)
        self.assertTrue(all(ro is True for _, ro in observed_selects))
        self.assertTrue(all(spec == "(BODY.PEEK[])" for spec in observed_fetches))

        with patch("backend.connectors.zoho_connector.smtplib.SMTP_SSL", FakeSMTP):
            receipt = conn.send_email(
                to=["client@vendor.com"],
                subject="Re: Invoice #42",
                body="Confirmed.",
                in_reply_to="<inv-42@vendor.com>",
                references=["<inv-42@vendor.com>"],
            )
        self.assertEqual(receipt.status, "sent")
        self.assertEqual(sent_messages[0]["In-Reply-To"], "<inv-42@vendor.com>")
        self.assertEqual(sent_messages[0]["References"], "<inv-42@vendor.com>")


class TestPriorityPipelineCompatibilityAndIsolation(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.settings = Settings(
            local_user_data_dir=Path(self.temp_dir.name),
            profiler_mode="heuristic",
            model_name="not-installed-for-test",
        )
        self.app = create_app(settings=self.settings)
        self.client = TestClient(self.app)

        self.outlook_id = self.app.state.account_manager.create_account(
            email="out@outlook.com", display_name="Outlook User", provider="outlook", mailbox_connected=True
        ).account_id
        self.zoho_id = self.app.state.account_manager.create_account(
            email="zoho@zoho.in", display_name="Zoho User", provider="zoho", mailbox_connected=True
        ).account_id

        ProfileStore(self.settings.for_account(self.outlook_id)).save_profile(_sample_profile())
        ProfileStore(self.settings.for_account(self.zoho_id)).save_profile(_sample_profile())
        save_outlook_tokens(self.settings.for_account(self.outlook_id), {"access_token": "tok-o", "expires_at": time.time() + 3600})
        from backend.automation.contact_resolver import Contact, ContactResolver
        from backend.storage import protect_secret
        z_dir = self.settings.for_account(self.zoho_id).local_user_data_dir
        (z_dir / "zoho_credentials.bin").write_text(
            protect_secret(json.dumps({"email": "zoho@zoho.in", "app_password": "pw", "region": "in"}), z_dir),
            encoding="utf-8",
        )
        for aid in (self.outlook_id, self.zoho_id):
            ContactResolver(self.settings.for_account(aid).contacts_path).upsert_contact(
                Contact(email="partner@acme.com", full_name="Partner Acme", first_name="Partner", last_name="Acme")
            )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_outbound_and_inbox_reply_on_outlook_and_zoho_with_isolation(self) -> None:
        sample_thread = {
            "thread_id": "t-1",
            "subject": "Partnership Sync",
            "participants": ["partner@acme.com"],
            "messages": [
                {
                    "message_id": "<p-1@acme.com>",
                    "from_name": "Partner",
                    "from_email": "partner@acme.com",
                    "to": ["user@example.com"],
                    "cc": [],
                    "date": "2026-11-27T10:00:00Z",
                    "subject": "Partnership Sync",
                    "body_text": "Are we good for Tuesday?",
                    "in_reply_to": "",
                    "references": [],
                }
            ],
        }

        with patch("backend.main.QwenDrafter.generate_draft", return_value="Hi Partner,\n\nYes, Tuesday works.\n\nBest," ), \
             patch("backend.connectors.outlook_connector.OutlookGraphConnector.fetch_thread_messages", return_value=sample_thread), \
             patch("backend.connectors.zoho_connector.ZohoMailConnector.fetch_thread_messages", return_value=sample_thread):
            for acct_id in (self.outlook_id, self.zoho_id):
                headers = {"X-Account-ID": acct_id}
                sess = self.client.post("/api/chat/sessions", json={"title": "Test"}, headers=headers)
                self.assertEqual(sess.status_code, 200)
                sid = sess.json()["session_id"]

                turn = self.client.post(
                    "/api/chat/turn",
                    json={"session_id": sid, "user_message": "Email partner@acme.com about Tuesday sync", "auto_send": False},
                    headers=headers,
                )
                self.assertEqual(turn.status_code, 200, turn.text)
                t_data = turn.json()
                draft_meta = (t_data.get("draft_card") or t_data).get("resolution_meta", {})
                self.assertIn("explainability", draft_meta)
                self.assertIn("confidence", draft_meta)

                reply = self.client.post(
                    "/api/inbox/threads/t-1/draft-reply",
                    json={"reply_mode": "reply", "instruction": "Confirm Tuesday"},
                    headers=headers,
                )
                self.assertEqual(reply.status_code, 200, reply.text)
                r_data = reply.json()
                self.assertIn("explainability", r_data["resolution_meta"])

                metrics = self.client.get("/api/pilot/metrics", headers=headers)
                self.assertEqual(metrics.status_code, 200)
                m_data = metrics.json()
                self.assertGreaterEqual(m_data["total_drafts_generated"], 2)
                self.assertEqual(m_data["inbox_replies_drafted"], 1)

        # Cross-account session isolation check
        o_sessions = self.client.get("/api/chat/sessions", headers={"X-Account-ID": self.outlook_id}).json()["sessions"]
        z_sessions = self.client.get("/api/chat/sessions", headers={"X-Account-ID": self.zoho_id}).json()["sessions"]
        self.assertTrue({s["session_id"] for s in o_sessions}.isdisjoint({s["session_id"] for s in z_sessions}))
