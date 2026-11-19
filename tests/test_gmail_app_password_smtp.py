from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.config import Settings
from backend.connectors.base import ConnectorError
from backend.connectors.gmail_app_password import GmailAppPasswordConnector
from backend.connectors.gmail_connector import GmailConnector, GOOGLE_IDENTITY_SCOPES
from backend.main import create_app
from backend.schemas import (
    CorpusStatistics,
    GlobalStyleCard,
    OutboundEmailRequest,
    StylometryMetrics,
    UserStyleProfile,
)
from backend.storage import ChatSessionStore, ProfileStore, protect_secret


class GmailAppPasswordSMTPTests(unittest.TestCase):
    def test_send_email_uses_smtp_ssl_and_preserves_envelope_headers(self) -> None:
        sent: dict[str, object] = {}

        class FakeSMTP:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def login(self, username: str, password: str) -> None:
                sent["login"] = (username, password)

            def send_message(self, message, *, from_addr: str, to_addrs: list[str]) -> None:
                sent["message"] = message
                sent["from_addr"] = from_addr
                sent["to_addrs"] = to_addrs

        connector = GmailAppPasswordConnector("kamisama7892@gmail.com", "abcdefghijklmnop")
        request = OutboundEmailRequest(
            to=["kamisama7892@gmail.com"],
            cc=["copy@example.test"],
            bcc=["hidden@example.test"],
            subject="Local SMTP test",
            body="Testing the staged SMTP send.",
            thread_id="<thread@example.test>",
            in_reply_to="<parent@example.test>",
        )
        with patch("backend.connectors.gmail_app_password.smtplib.SMTP_SSL", return_value=FakeSMTP()) as smtp_ssl:
            receipt = connector.send_email(request)

        smtp_ssl.assert_called_once_with("smtp.gmail.com", 465)
        self.assertEqual(sent["login"], ("kamisama7892@gmail.com", "abcdefghijklmnop"))
        self.assertEqual(sent["from_addr"], "kamisama7892@gmail.com")
        self.assertEqual(sent["to_addrs"], ["kamisama7892@gmail.com", "copy@example.test", "hidden@example.test"])
        message = sent["message"]
        self.assertEqual(message["From"], "kamisama7892@gmail.com")
        self.assertEqual(message["To"], "kamisama7892@gmail.com")
        self.assertEqual(message["Cc"], "copy@example.test")
        self.assertEqual(message["Bcc"], "hidden@example.test")
        self.assertEqual(message["Subject"], "Local SMTP test")
        self.assertEqual(message["In-Reply-To"], "<parent@example.test>")
        self.assertEqual(message["References"], "<thread@example.test>")
        self.assertEqual(receipt.status, "sent")
    def test_oauth_identity_token_is_rejected_for_gmail_api_send(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            token_file = Path(directory) / "identity-token.json"
            token_file.write_text(json.dumps({
                "token": "not-a-real-token",
                "refresh_token": "not-a-real-refresh-token",
                "token_uri": "https://oauth2.googleapis.com/token",
                "client_id": "client-id",
                "client_secret": "client-secret",
                "scopes": GOOGLE_IDENTITY_SCOPES,
            }), encoding="utf-8")
            connector = GmailConnector(Path(directory) / "client.json", token_file, scopes=GOOGLE_IDENTITY_SCOPES)
            with self.assertRaisesRegex(ConnectorError, "gmail.send"):
                connector._get_credentials(require_send=True)
    def test_approve_and_learn_uses_saved_app_password_smtp_connector(self) -> None:
        target = "kamisama7892@gmail.com"
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(local_user_data_dir=Path(directory), profiler_mode="heuristic")
            app = create_app(settings=settings)
            client = TestClient(app)
            account = app.state.account_manager.create_account(target, "Self Test")
            account_settings = settings.for_account(account.account_id)
            store = ProfileStore(account_settings)
            profile = UserStyleProfile(
                profile_id="profile-test",
                created_at=datetime.now(timezone.utc),
                deterministic_stylometry=StylometryMetrics(),
                global_style_card=GlobalStyleCard(
                    formality="casual",
                    tone="direct",
                    directness="balanced",
                    vocabulary_level="standard-professional",
                    sentence_structure="warm & conversational",
                    formatting_preferences=[],
                    characteristic_phrases=[],
                    source="heuristic",
                    sampled_email_count=0,
                ),
                corpus_statistics=CorpusStatistics(total_sent_emails=0, clean_emails_retained=0),
            )
            store.save_profile(profile)
            secret_path = account_settings.local_user_data_dir / "app_password.bin"
            secret_path.write_text(
                protect_secret("abcdefghijklmnop", account_settings.local_user_data_dir),
                encoding="utf-8",
            )
            app.state.account_manager.update_account(account.account_id, mailbox_connected=True)

            sessions = ChatSessionStore(account_settings.chat_sessions_path)
            session = sessions.create_session(account.account_id, title="SMTP delivery test")
            draft_id = "draft-smtp-test"
            original_body = "Hi, this is a safe self-addressed SMTP test."
            request_data = {
                "to": [target], "cc": [], "bcc": [], "subject": "SMTP test",
                "provider": "gmail", "thread_id": None, "in_reply_to": None,
                "intent_bullets": "safe test", "session_id": session["session_id"],
            }
            connection = sqlite3.connect(account_settings.sqlite_path)
            try:
                connection.execute(
                    "INSERT INTO pending_drafts (draft_id, profile_id, request_json, draft, created_at, recipient_profiles_json) VALUES (?, ?, ?, ?, ?, ?)",
                    (draft_id, profile.profile_id, json.dumps(request_data), original_body, datetime.now(timezone.utc).isoformat(), "{}"),
                )
                connection.commit()
            finally:
                connection.close()
            card = sessions.upsert_draft_card(
                session_id=session["session_id"], to=[target], cc=[], bcc=[],
                subject="SMTP test", body=original_body, status="PENDING_REVIEW", draft_id=draft_id,
            )
            sessions.append_message(session["session_id"], "assistant", "Draft ready.", metadata={"card_id": card["card_id"]})
            sent: dict[str, object] = {}

            class FakeSMTP:
                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    return False

                def login(self, username: str, password: str) -> None:
                    sent["login"] = (username, password)

                def send_message(self, message, *, from_addr: str, to_addrs: list[str]) -> None:
                    sent["message"] = message
                    sent["from_addr"] = from_addr
                    sent["to_addrs"] = to_addrs

            with (
                patch("backend.connectors.gmail_app_password.smtplib.SMTP_SSL", return_value=FakeSMTP()) as smtp_ssl,
                patch("backend.retrieval.embedder.LocalEmbedder.load", return_value=None),
                patch("backend.retrieval.vector_store.LanceDBVectorStore.upsert_sent_email", return_value=None),
            ):
                response = client.post(
                    "/api/email/approve-and-learn",
                    headers={"X-Account-ID": account.account_id},
                    json={"draft_id": draft_id, "final_subject": "SMTP test", "final_body": original_body},
                )

            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["status"], "SENT")
            self.assertEqual(response.json()["receipt"]["status"], "sent")
            self.assertEqual(sent["to_addrs"], [target])
            self.assertEqual(sent["from_addr"], target)
            smtp_ssl.assert_called_once_with("smtp.gmail.com", 465)
            self.assertIsNone(store.load_pending_draft(draft_id))
            updated_card = sessions.get_draft_card(card["card_id"])
            self.assertIsNotNone(updated_card)
            assert updated_card is not None
            self.assertEqual(updated_card["status"], "SENT")

    def test_chat_staged_draft_is_approved_through_smtp_not_demo_outbox(self) -> None:
        """A draft created in chat must be sent over SMTP when the account uses an App Password."""
        target = "kamisama7892@gmail.com"
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(local_user_data_dir=Path(directory), profiler_mode="heuristic")
            app = create_app(settings=settings)
            client = TestClient(app)
            account = app.state.account_manager.create_account(target, "Self Test")
            account_settings = settings.for_account(account.account_id)
            store = ProfileStore(account_settings)
            profile = UserStyleProfile(
                profile_id="profile-chat-smtp",
                created_at=datetime.now(timezone.utc),
                deterministic_stylometry=StylometryMetrics(),
                global_style_card=GlobalStyleCard(
                    formality="casual",
                    tone="direct",
                    directness="balanced",
                    vocabulary_level="standard-professional",
                    sentence_structure="warm & conversational",
                    formatting_preferences=[],
                    characteristic_phrases=[],
                    source="heuristic",
                    sampled_email_count=0,
                ),
                corpus_statistics=CorpusStatistics(total_sent_emails=0, clean_emails_retained=0),
            )
            store.save_profile(profile)
            secret_path = account_settings.local_user_data_dir / "app_password.bin"
            secret_path.write_text(
                protect_secret("abcdefghijklmnop", account_settings.local_user_data_dir),
                encoding="utf-8",
            )
            app.state.account_manager.update_account(account.account_id, mailbox_connected=True)

            # Seed the recipient so the chat turn resolves a concrete address.
            from backend.automation.contact_resolver import Contact, ContactResolver

            resolver = ContactResolver(account_settings.contacts_path)
            resolver.upsert_contact(Contact(email=target, full_name="Kamisama"))

            session = client.post(
                "/api/chat/sessions",
                headers={"X-Account-ID": account.account_id},
                json={"title": "SMTP chat draft"},
            ).json()

            sent: dict[str, object] = {}

            class FakeSMTP:
                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    return False

                def login(self, username: str, password: str) -> None:
                    sent["login"] = (username, password)

                def send_message(self, message, *, from_addr: str, to_addrs: list[str]) -> None:
                    sent["message"] = message
                    sent["from_addr"] = from_addr
                    sent["to_addrs"] = to_addrs

            with (
                patch("backend.connectors.gmail_app_password.smtplib.SMTP_SSL", return_value=FakeSMTP()) as smtp_ssl,
                patch("backend.retrieval.embedder.LocalEmbedder.load", return_value=None),
                patch("backend.retrieval.vector_store.LanceDBVectorStore.upsert_sent_email", return_value=None),
                patch("backend.generation.drafter.QwenDrafter.generate_draft", return_value="Hi,\n\nDraft body."),
            ):
                turn = client.post(
                    "/api/chat/turn",
                    headers={"X-Account-ID": account.account_id},
                    json={
                        "session_id": session["session_id"],
                        "user_message": f"send an email to {target} about the release",
                    },
                )
                self.assertEqual(turn.status_code, 200, turn.text)
                self.assertEqual(turn.json()["status"], "PENDING_REVIEW")
                draft_id = turn.json()["draft_card"]["draft_id"]
                self.assertTrue(draft_id)

                staged = store.load_pending_draft(draft_id)
                self.assertIsNotNone(staged)
                assert staged is not None
                self.assertEqual(staged["request"]["provider"], "gmail")

                approved = client.post(
                    "/api/email/approve-and-learn",
                    headers={"X-Account-ID": account.account_id},
                    json={"draft_id": draft_id, "final_subject": "Release", "final_body": "Hi,\n\nDraft body."},
                )

            self.assertEqual(approved.status_code, 200, approved.text)
            self.assertEqual(approved.json()["status"], "SENT", approved.text)
            smtp_ssl.assert_called_once_with("smtp.gmail.com", 465)
            self.assertEqual(sent["to_addrs"], [target])
            self.assertEqual(sent["from_addr"], target)
            self.assertIsNone(store.load_pending_draft(draft_id))


if __name__ == "__main__":
    unittest.main()
