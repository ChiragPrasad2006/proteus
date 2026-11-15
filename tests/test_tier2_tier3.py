"""Behavioral tests for the Tier 2 Retrieval and Tier 3 Generation backend."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from backend.config import Settings
from backend.main import create_app
from backend.schemas import (
    CleanedSentEmail,
    DraftRequest,
    GlobalStyleCard,
    RawSentEmail,
    RetrievedExample,
    StylometryMetrics,
    UserStyleProfile,
)


class Tier2RetrievalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.settings = Settings(
            local_user_data_dir=Path(self.temp_dir.name),
            profiler_mode="heuristic",
            model_name="not-installed-for-test",
        )
        self.app = create_app(settings=self.settings)
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _seed_and_build(self) -> UserStyleProfile:
        """Helper to seed demo data and build a profile."""
        seeded = self.client.post("/api/onboarding/demo-seed")
        self.assertEqual(seeded.status_code, 200)
        profile = self.client.post("/api/onboarding/build-profile")
        self.assertEqual(profile.status_code, 200)
        return UserStyleProfile.model_validate(profile.json())

    def test_retrieval_reindex_indexes_all_cleaned_emails(self) -> None:
        self._seed_and_build()
        # Reindex endpoint
        response = self.client.post("/api/retrieval/reindex")
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data["indexed_count"], 18)
        self.assertEqual(data["table_name"], "sent_emails")

    def test_retrieval_search_returns_examples_for_recipient(self) -> None:
        self._seed_and_build()
        self.client.post("/api/retrieval/reindex")

        # Search for exact recipient
        response = self.client.post(
            "/api/retrieval/search",
            json={
                "query_text": "migration checkpoint",
                "recipient_email": "alex@acme.example",
                "k": 2,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertGreaterEqual(len(data["examples"]), 1)
        self.assertEqual(data["examples"][0]["recipient_email"], "alex@acme.example")

    def test_retrieval_search_falls_back_to_domain(self) -> None:
        self._seed_and_build()
        self.client.post("/api/retrieval/reindex")

        # Search for a recipient not in the corpus but same domain
        response = self.client.post(
            "/api/retrieval/search",
            json={
                "query_text": "budget",
                "recipient_email": "newperson@acme.example",
                "recipient_domain": "acme.example",
                "k": 2,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        # Should backfill from same domain
        self.assertGreaterEqual(len(data["examples"]), 1)
        for ex in data["examples"]:
            self.assertEqual(ex["recipient_domain"], "acme.example")

    def test_retrieval_search_semantic_fallback(self) -> None:
        self._seed_and_build()
        self.client.post("/api/retrieval/reindex")

        # Search without recipient - pure semantic
        response = self.client.post(
            "/api/retrieval/search",
            json={"query_text": "migration rollout", "k": 2},
        )
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertGreaterEqual(len(data["examples"]), 1)


class Tier3GenerationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.settings = Settings(
            local_user_data_dir=Path(self.temp_dir.name),
            profiler_mode="heuristic",
            model_name="not-installed-for-test",
        )
        self.app = create_app(settings=self.settings)
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _seed_build_index(self) -> UserStyleProfile:
        """Helper to seed demo data, build profile, and index."""
        seeded = self.client.post("/api/onboarding/demo-seed")
        self.assertEqual(seeded.status_code, 200)
        profile = self.client.post("/api/onboarding/build-profile")
        self.assertEqual(profile.status_code, 200)
        profile_data = UserStyleProfile.model_validate(profile.json())
        self.client.post("/api/retrieval/reindex")
        return profile_data

    def test_draft_generate_returns_draft_with_heuristic_profile(self) -> None:
        """Test that draft generation works with heuristic profile (no model)."""
        self._seed_build_index()

        response = self.client.post(
            "/api/draft/generate",
            json={
                "intent_bullets": "- Project kickoff next Monday\n- Need stakeholder approval by Friday\n- Budget review required",
                "recipient_email": "alex@acme.example",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertIn("draft", data)
        self.assertIsInstance(data["draft"], str)
        self.assertGreater(len(data["draft"]), 50)
        # Get the profile that was created during _seed_build_index
        profile_response = self.client.get("/api/profile")
        self.assertEqual(profile_response.status_code, 200)
        self.assertEqual(data["profile_id"], profile_response.json()["profile_id"])
        self.assertIn("retrieved_examples", data)

    def test_draft_generate_includes_signoff_from_profile(self) -> None:
        """Test that generated draft uses the profile's exact sign-off."""
        profile = self._seed_build_index()
        # Verify profile has signoff
        self.assertIn("Best", profile.deterministic_stylometry.exact_signoff)

        response = self.client.post(
            "/api/draft/generate",
            json={
                "intent_bullets": "- Quick status update\n- All green",
                "recipient_email": "alex@acme.example",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        draft = response.json()["draft"]
        # The draft should end with the user's signoff (or at least contain it)
        self.assertIn("Best", draft)

    def test_draft_generate_fails_without_profile(self) -> None:
        """Test that draft generation fails gracefully without a profile."""
        response = self.client.post(
            "/api/draft/generate",
            json={"intent_bullets": "- Test", "recipient_email": "test@example.com"},
        )
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()