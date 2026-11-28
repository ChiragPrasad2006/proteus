"""Offline tests for first-launch vector DB, persona & inbox sync.

Zero real IMAP/SMTP/Gmail/Outlook/Zoho/Ollama calls: connectors, embedder, and
Ollama are mocked, and all state lives inside temporary directories.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx
import numpy as np
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.config import Settings
from backend.ingestion.initial_sync import start_initial_sync
from backend.main import create_app
from backend.retrieval.vector_store import LanceDBVectorStore
from backend.schemas import RawSentEmail
from backend.storage.account_manager import AccountManager
from backend.storage.profile_store import ProfileStore


class _FakeEmbedder:
    """Fast deterministic 384-dim embedder for offline tests."""

    def load(self) -> None:
        return None

    @staticmethod
    def prepare_text(subject: str, clean_body: str) -> str:
        return f"{subject}\n{clean_body}"

    def encode(self, texts: list[str]) -> np.ndarray:
        return np.ones((len(texts), 384), dtype=np.float32) * 0.1


class _FakeConnector:
    """Mocked email connector returning deterministic Sent and read-only Inbox records."""

    def __init__(self, sent_records: list[RawSentEmail], inbox_threads: list[dict[str, Any]]) -> None:
        self._sent = sent_records
        self._inbox = inbox_threads
        self.sent_calls = 0
        self.inbox_calls = 0

    def fetch_sent_emails(self, limit: int = 250) -> list[RawSentEmail]:
        self.sent_calls += 1
        return list(self._sent[:limit])

    def fetch_inbox_threads(self, limit: int = 25) -> list[dict[str, Any]]:
        self.inbox_calls += 1
        return list(self._inbox[:limit])


def _sample_sent_emails() -> list[RawSentEmail]:
    now = datetime(2026, 11, 20, 10, 0, tzinfo=timezone.utc)
    return [
        RawSentEmail(
            message_id=f"<msg-{i}@example.com>",
            recipient_email="manu@example.com",
            subject=f"Launch milestone {i}",
            raw_body=(
                f"Hi Manu,\n\n"
                f"Here is update #{i} on the Q4 launch plan. I reviewed the deployment checklist, "
                f"updated the release timeline, and confirmed the staging environment is ready for testing.\n\n"
                f"Best,\nAlex"
            ),
            timestamp=now,
            thread_id=f"thread-{i}",
        )
        for i in range(4)
    ] + [
        RawSentEmail(
            message_id="<msg-team@example.com>",
            recipient_email="jatin@example.com",
            subject="Weekly sync",
            raw_body=(
                "Hi team,\n\n"
                "Sharing the weekly engineering notes for everyone ahead of tomorrow's standup. "
                "Please review the open pull requests and add any blockers before noon.\n\n"
                "Thanks,\nAlex"
            ),
            timestamp=now,
            thread_id="thread-team",
        )
    ]


def _sample_inbox_threads() -> list[dict[str, Any]]:
    return [
        {
            "thread_id": "inbox-1",
            "subject": "Re: Launch milestone",
            "snippet": "Looks good to me.",
            "last_message_at": "2026-11-26T10:00:00+00:00",
            "message_count": 2,
            "participants": ["manu@example.com"],
            "unread": True,
            "latest_sender_name": "Manu",
            "latest_sender_email": "manu@example.com",
        }
    ]


class InitialSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.settings = Settings(local_user_data_dir=self.root)
        self.settings.ensure_local_directories()
        self.account_mgr = AccountManager(self.root)
        self.account_a = self.account_mgr.create_account(
            email="alex@example.com",
            display_name="Alex",
            provider="gmail",
            mailbox_connected=True,
        )
        self.account_b = self.account_mgr.create_account(
            email="other@example.com",
            display_name="Other",
            provider="outlook",
            mailbox_connected=True,
        )
        self.account_mgr.set_active_account(self.account_a.account_id)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_first_launch_sync_indexes_lancedb_personas_and_inbox_with_ollama_offline(self) -> None:
        connector = _FakeConnector(_sample_sent_emails(), _sample_inbox_threads())

        with (
            patch("backend.ingestion.initial_sync.get_connector_for_account", return_value=connector),
            patch("backend.ingestion.initial_sync.LocalEmbedder", return_value=_FakeEmbedder()),
            patch("backend.ingestion.initial_sync.httpx.post", side_effect=httpx.ConnectError("ollama offline")),
            patch("backend.profiler.qwen_profiler.httpx.post", side_effect=httpx.ConnectError("ollama offline")),
        ):
            state = start_initial_sync(
                self.account_a.account_id,
                self.settings,
                self.account_mgr,
                background=False,
            )

        self.assertEqual(state["error"], "")
        self.assertTrue(state["initial_sync_completed"])
        self.assertEqual(state["stage"], "completed")
        self.assertEqual(state["sent_processed"], 5)
        self.assertEqual(state["sent_total"], 5)
        self.assertEqual(state["personas_built"], 1)  # manu@example.com has 4 >= 3 emails
        self.assertEqual(state["inbox_threads_indexed"], 1)

        acc_a_settings = self.settings.for_account(self.account_a.account_id)
        store_a = ProfileStore(acc_a_settings)
        # Global profile + recipient persona saved in SQLite despite Ollama being offline
        self.assertIsNotNone(store_a.load_profile())
        manu_profile = store_a.get_recipient_profile("manu@example.com")
        self.assertIsNotNone(manu_profile)
        self.assertEqual(manu_profile.sent_count, 4)
        self.assertGreaterEqual(len(manu_profile.learned_rules_json), 1)

        # Warm inbox cache populated
        cached_threads = store_a.load_inbox_threads_cache(limit=25)
        self.assertEqual(len(cached_threads), 1)
        self.assertEqual(cached_threads[0]["thread_id"], "inbox-1")

        # LanceDB indexed 5 unique rows
        table = LanceDBVectorStore(acc_a_settings)._get_or_create_table()
        self.assertEqual(table.count_rows(), 5)

        # Strict X-Account-ID isolation: Account B has zero sync state, personas, or inbox cache
        store_b = ProfileStore(self.settings.for_account(self.account_b.account_id))
        state_b = store_b.get_initial_sync_state()
        self.assertFalse(state_b["initial_sync_completed"])
        self.assertEqual(state_b["stage"], "idle")
        self.assertEqual(store_b.load_inbox_threads_cache(), [])
        self.assertIsNone(store_b.get_recipient_profile("manu@example.com"))

    def test_idempotency_without_force_and_no_lancedb_duplicates_on_force(self) -> None:
        connector = _FakeConnector(_sample_sent_emails(), _sample_inbox_threads())

        with (
            patch("backend.ingestion.initial_sync.get_connector_for_account", return_value=connector),
            patch("backend.ingestion.initial_sync.LocalEmbedder", return_value=_FakeEmbedder()),
            patch("backend.ingestion.initial_sync.httpx.post", side_effect=httpx.ConnectError("ollama offline")),
            patch("backend.profiler.qwen_profiler.httpx.post", side_effect=httpx.ConnectError("ollama offline")),
        ):
            first = start_initial_sync(self.account_a.account_id, self.settings, self.account_mgr, background=False)
            self.assertEqual(first["error"], "")
            self.assertEqual(connector.sent_calls, 1)

            # Second trigger without force=True is a no-op
            second = start_initial_sync(self.account_a.account_id, self.settings, self.account_mgr, force=False, background=False)
            self.assertTrue(second["initial_sync_completed"])
            self.assertEqual(connector.sent_calls, 1)

            # Force re-sync runs again and deduplicates LanceDB rows by message_id
            start_initial_sync(self.account_a.account_id, self.settings, self.account_mgr, force=True, background=False)
            self.assertEqual(connector.sent_calls, 2)

        table = LanceDBVectorStore(self.settings.for_account(self.account_a.account_id))._get_or_create_table()
        self.assertEqual(table.count_rows(), 5)

    def test_api_endpoints_scoped_to_account_id(self) -> None:
        app = create_app(self.settings)
        client = TestClient(app)

        res_status_a = client.get("/api/onboarding/initial-sync/status", headers={"X-Account-ID": self.account_a.account_id})
        self.assertEqual(res_status_a.status_code, 200)
        self.assertEqual(res_status_a.json()["stage"], "idle")

        with patch("backend.main.start_initial_sync", return_value={
            "initial_sync_completed": False,
            "running": True,
            "stage": "fetching_sent",
            "sent_processed": 0,
            "sent_total": 0,
            "personas_built": 0,
            "inbox_threads_indexed": 0,
            "last_synced_at": "",
            "error": "",
        }) as mock_start:
            res_post = client.post(
                "/api/onboarding/initial-sync?force=true",
                headers={"X-Account-ID": self.account_a.account_id},
            )
            self.assertEqual(res_post.status_code, 200)
            self.assertTrue(res_post.json()["running"])
            mock_start.assert_called_once()
