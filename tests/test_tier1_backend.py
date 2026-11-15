"""Behavioral tests for the Tier 1 local personalization backend."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.config import Settings
from backend.main import create_app
from backend.processing.cleaner import clean_raw_email
from backend.processing.stylometry import compute_stylometry
from backend.profiler.qwen_profiler import QwenStyleProfiler
from backend.schemas import GlobalStyleCard, RawSentEmail


class Tier1BackendTests(unittest.TestCase):
    def test_cleaner_removes_html_reply_history_and_signature(self) -> None:
        raw = RawSentEmail(
            message_id="m-1",
            recipient_email="alex@example.com",
            recipient_domain="example.com",
            subject="Project update",
            raw_body="""
                <div>Hi Alex,</div><div><br></div>
                <div>The migration completed today. Please review the rollout notes and
                share any concerns before Thursday's checkpoint.</div>
                <div><br></div><div>Best,</div><div>Sam</div>
                <div><br></div><div>On Tue, May 7, Alex wrote:</div>
                <div>&gt; Can you send the current status?</div>
            """,
            timestamp="2026-11-14T10:00:00Z",
            thread_id="thread-1",
        )

        cleaned = clean_raw_email(raw, minimum_words=15)

        self.assertIsNotNone(cleaned)
        assert cleaned is not None
        self.assertNotIn("On Tue", cleaned.clean_body)
        self.assertNotIn("Can you send", cleaned.clean_body)
        self.assertEqual(cleaned.signature, "Best,\nSam")
        self.assertTrue(cleaned.clean_body.startswith("Hi Alex,"))

    def test_stylometry_reports_normalized_greeting_and_exact_signoff(self) -> None:
        messages = [
            RawSentEmail(
                message_id=f"m-{index}",
                recipient_email="alex@example.com",
                recipient_domain="example.com",
                subject="Status",
                raw_body=(
                    f"Hey Alex,\n\nThis is a detailed project update number {index}. "
                    "The deployment completed today and the monitoring checks are green. "
                    "Please share any feedback before Thursday.\n\nBest,\nSam"
                ),
                timestamp="2026-11-14T10:00:00Z",
                thread_id=f"thread-{index}",
            )
            for index in range(3)
        ]
        cleaned = [clean_raw_email(message, minimum_words=10) for message in messages]

        metrics = compute_stylometry([message for message in cleaned if message is not None])

        self.assertEqual(metrics.top_greetings[0].pattern, "Hey {first_name},")
        self.assertEqual(metrics.top_greetings[0].pct, 100.0)
        self.assertEqual(metrics.exact_signoff, "Best,\nSam")
        self.assertGreater(metrics.avg_sentence_length_words, 1.0)

    def test_demo_seed_and_build_profile_work_without_cloud_services(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(
                local_user_data_dir=Path(directory),
                profiler_mode="heuristic",
                model_name="not-installed-for-test",
            )
            app = create_app(settings=settings)
            with TestClient(app) as client:
                seeded = client.post("/api/onboarding/demo-seed")
                self.assertEqual(seeded.status_code, 200, seeded.text)
                self.assertGreaterEqual(seeded.json()["clean_emails_retained"], 15)

                profile = client.post("/api/onboarding/build-profile")
                self.assertEqual(profile.status_code, 200, profile.text)
                payload = profile.json()
                self.assertEqual(payload["global_style_card"]["source"], "heuristic")
                self.assertIn("formality", payload["global_style_card"])
                self.assertGreater(payload["corpus_statistics"]["clean_emails_retained"], 0)

                loaded = client.get("/api/profile")
                self.assertEqual(loaded.status_code, 200, loaded.text)
                self.assertEqual(loaded.json()["profile_id"], payload["profile_id"])

    def test_model_profile_rejects_schema_option_strings(self) -> None:
        invalid = """{
            "formality": "casual | semi-formal | strict-executive | blunt-technical",
            "tone": "short & punchy",
            "directness": "high",
            "vocabulary_level": "simple",
            "sentence_structure": "short & punchy",
            "formatting_preferences": ["list of observed habits"],
            "characteristic_phrases": []
        }"""

        with self.assertRaises(ValidationError):
            QwenStyleProfiler._card_from_response(invalid, "ollama", "qwen2.5:3b", 18)

    def test_profiler_detects_copied_prompt_example(self) -> None:
        copied = GlobalStyleCard(
            formality="semi-formal",
            tone="clear and collaborative",
            directness="balanced",
            vocabulary_level="standard-professional",
            sentence_structure="warm & conversational",
            formatting_preferences=["opens with a greeting", "uses short paragraphs"],
            characteristic_phrases=["please review", "before Thursday"],
            source="ollama",
            model="qwen2.5:3b",
            sampled_email_count=18,
        )

        self.assertTrue(QwenStyleProfiler._is_copied_prompt_example(copied))

    def test_style_card_rejects_more_than_five_characteristic_phrases(self) -> None:
        with self.assertRaises(ValidationError):
            GlobalStyleCard(
                formality="semi-formal",
                tone="clear",
                directness="balanced",
                vocabulary_level="standard-professional",
                sentence_structure="short & punchy",
                formatting_preferences=["short paragraphs"],
                characteristic_phrases=[f"phrase {index}" for index in range(6)],
                source="ollama",
                model="qwen2.5:3b",
                sampled_email_count=18,
            )


if __name__ == "__main__":
    unittest.main()
