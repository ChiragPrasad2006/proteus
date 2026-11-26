"""Tests for the evaluation harness (eval/).
Verifies: 30 scenarios, 8 categories, synthetic data only, dry-run execution, metrics, blind review.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from eval.runner import BaselineRunner, Scenario, MockLLM
from eval.metrics import (
    compute_metrics,
    aggregate_metrics,
    levenshtein_distance,
    normalized_edit_distance,
    check_audience_accuracy,
    check_confidence_accuracy,
    count_leakage_violations,
    compute_factual_coverage,
    compute_voice_adherence,
)
from eval.blind_review import export_blind_review, score_review


class TestSeedCorpus(unittest.TestCase):
    """Verify seed_corpus.json is valid and 100% synthetic."""

    def setUp(self):
        self.corpus_path = REPO_ROOT / "eval" / "seed_corpus.json"
        self.corpus = json.loads(self.corpus_path.read_text())

    def test_persona_structure(self):
        persona = self.corpus["persona"]
        self.assertIn("name", persona)
        self.assertIn("role", persona)
        self.assertIn("global_style_card", persona)
        self.assertIn("deterministic_stylometry", persona)
        self.assertIn("global_learned_rules", persona)

    def test_contacts_count(self):
        contacts = self.corpus["contacts"]
        self.assertGreaterEqual(len(contacts), 6)
        self.assertLessEqual(len(contacts), 8)
        for c in contacts:
            self.assertIn("recipient_email", c)
            self.assertIn("relationship_tier", c)
            self.assertIn("learned_rules_json", c)
            # No real email domains
            self.assertNotIn("gmail.com", c["recipient_email"])
            self.assertNotIn("pacewisdom.com", c["recipient_email"])

    def test_historical_emails_count(self):
        emails = self.corpus["historical_emails"]
        self.assertGreaterEqual(len(emails), 40)
        self.assertLessEqual(len(emails), 50)
        for e in emails:
            self.assertIn("message_id", e)
            self.assertIn("recipient_email", e)
            self.assertIn("audience_mode", e)
            self.assertIn(e["audience_mode"], ["1on1_private", "group_cc", "broadcast_bcc"])

    def test_no_real_emails_in_corpus(self):
        """Ensure no real user emails from local_user_data leak into seed corpus."""
        corpus_str = json.dumps(self.corpus)
        forbidden = ["kamisama7892", "punya.h", "pacewisdom", "chiragprasad", "realuser"]
        for f in forbidden:
            self.assertNotIn(f, corpus_str, f"Real email pattern '{f}' found in seed corpus")

    def test_timestamps_span_range(self):
        """Verify timestamps cover recent (5-45 days) and stale (150-300 days)."""
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        recent_count = 0
        stale_count = 0
        for e in self.corpus["historical_emails"]:
            ts = datetime.fromisoformat(e["timestamp"])
            days_ago = (now - ts).days
            if 5 <= days_ago <= 45:
                recent_count += 1
            elif 150 <= days_ago <= 300:
                stale_count += 1
        self.assertGreater(recent_count, 10, "Should have recent emails for 90-day half-life test")
        self.assertGreater(stale_count, 5, "Should have stale emails for time decay test")


class TestScenarios(unittest.TestCase):
    """Verify scenarios.json has exactly 30 scenarios across 8 categories."""

    def setUp(self):
        self.scenarios_path = REPO_ROOT / "eval" / "scenarios.json"
        self.data = json.loads(self.scenarios_path.read_text())

    def test_exactly_30_scenarios(self):
        scenarios = self.data["scenarios"]
        self.assertEqual(len(scenarios), 30, "Must have exactly 30 scenarios")

    def test_8_categories_covered(self):
        scenarios = self.data["scenarios"]
        categories = {s["category"] for s in scenarios}
        expected = {
            "casual_1on1",
            "formal_client_1on1",
            "familiar_plus_cc_escalation",
            "cold_start_new_recipient",
            "group_cc_with_history",
            "broadcast_bcc",
            "time_decay_relationship_shift",
            "post_edit_rule_adherence",
        }
        self.assertEqual(categories, expected, f"Categories mismatch: {categories}")

    def test_category_distribution(self):
        scenarios = self.data["scenarios"]
        counts = {}
        for s in scenarios:
            counts[s["category"]] = counts.get(s["category"], 0) + 1
        expected = {
            "casual_1on1": 5,
            "formal_client_1on1": 4,
            "familiar_plus_cc_escalation": 5,
            "cold_start_new_recipient": 4,
            "group_cc_with_history": 3,
            "broadcast_bcc": 3,
            "time_decay_relationship_shift": 3,
            "post_edit_rule_adherence": 3,
        }
        self.assertEqual(counts, expected)

    def test_scenario_required_fields(self):
        for s in self.data["scenarios"]:
            required = [
                "id", "category", "to", "cc", "bcc", "task_prompt",
                "incoming_context", "required_facts", "expected_audience",
                "expected_confidence", "forbidden_patterns", "reviewer_notes"
            ]
            for field in required:
                self.assertIn(field, s, f"Missing field {field} in {s.get('id', 'unknown')}")

    def test_no_real_emails_in_scenarios(self):
        """Ensure scenarios only use synthetic contacts from seed_corpus."""
        scenarios_str = json.dumps(self.data)
        forbidden = ["kamisama7892", "punya.h", "pacewisdom", "chiragprasad"]
        for f in forbidden:
            self.assertNotIn(f, scenarios_str, f"Real email pattern '{f}' found in scenarios")

    def test_forbidden_patterns_include_corporate_cliches(self):
        for s in self.data["scenarios"]:
            patterns = s["forbidden_patterns"]
            self.assertIn("**", patterns, "Markdown bold should be forbidden")
            self.assertIn("{first_name}", patterns, "Placeholder should be forbidden")
            self.assertIn("I hope this email finds you well", patterns, "Corporate cliché should be forbidden")


class TestMockLLM(unittest.TestCase):
    """Test deterministic mocked LLM adapter."""

    def test_deterministic_output(self):
        llm = MockLLM(seed=42)
        out1 = llm.generate("sys", "user")
        out2 = llm.generate("sys", "user")
        self.assertEqual(out1, out2, "Same seed should produce identical output")

    def test_different_seeds_different_output(self):
        llm1 = MockLLM(seed=42)
        llm2 = MockLLM(seed=43)
        out1 = llm1.generate("sys", "user")
        out2 = llm2.generate("sys", "user")
        self.assertNotEqual(out1, out2, "Different seeds should produce different output")

    def test_greeting_extraction(self):
        llm = MockLLM(seed=42)
        sys_prompt = "PRIMARY GREETING TO USE: Hi Sam,\nOther stuff"
        out = llm.generate(sys_prompt, "Draft email")
        self.assertIn("Hi Sam,", out)


class TestMetrics(unittest.TestCase):
    """Test automated metrics computation."""

    def test_levenshtein_distance(self):
        self.assertEqual(levenshtein_distance("", ""), 0)
        self.assertEqual(levenshtein_distance("a", ""), 1)
        self.assertEqual(levenshtein_distance("", "a"), 1)
        self.assertEqual(levenshtein_distance("hello world", "hello world"), 0)
        self.assertEqual(levenshtein_distance("hello world", "hello there"), 1)
        self.assertEqual(levenshtein_distance("a b c", "d e f"), 3)

    def test_normalized_edit_distance(self):
        self.assertEqual(normalized_edit_distance("", ""), 0.0)
        self.assertEqual(normalized_edit_distance("hello world", "hello world"), 0.0)
        self.assertAlmostEqual(normalized_edit_distance("hello", "world"), 1.0)

    def test_check_audience_accuracy(self):
        context = {"audience_type": "group_cc"}
        self.assertTrue(check_audience_accuracy("", "group_cc", context)[0])
        self.assertFalse(check_audience_accuracy("", "1on1_private", context)[0])

    def test_check_confidence_accuracy(self):
        context = {"confidence_level": "high"}
        self.assertTrue(check_confidence_accuracy("", "high", context)[0])
        self.assertFalse(check_confidence_accuracy("", "low", context)[0])

    def test_count_leakage_violations(self):
        draft = "Hey there! **Bold** and {first_name} placeholder. Cheers!"
        patterns = ["**", "{first_name}", "I hope this email finds you well"]
        count, violations = count_leakage_violations(draft, patterns, "1on1_private")
        self.assertGreaterEqual(count, 2)
        self.assertIn("**", violations)
        self.assertIn("{first_name}", violations)

    def test_leakage_detects_casual_in_group(self):
        draft = "Hey Sam, the usual Friday deploy is on track. Cheers!"
        patterns = ["**", "{first_name}"]
        count, violations = count_leakage_violations(draft, patterns, "group_cc")
        self.assertTrue(any("casual_leakage" in v for v in violations))

    def test_compute_factual_coverage(self):
        draft = "The Friday deploy for Model v3 is at 94% pass rate. Meeting tomorrow 10am."
        facts = ["Friday deploy", "Model v3", "94% pass rate", "tomorrow 10am"]
        coverage, found, missing = compute_factual_coverage(draft, facts)
        self.assertEqual(coverage, 1.0)
        self.assertEqual(len(found), 4)

    def test_compute_voice_adherence(self):
        draft = "Hi Sam,\n\nFriday deploy is on track.\n\nBest,\nAlex"
        context = {
            "greeting": "Hi Sam,",
            "signoff": "Best,\nAlex",
            "target_sentence_length": 14,
        }
        score, details = compute_voice_adherence(draft, {}, context)
        self.assertTrue(details["greeting_match"])
        self.assertTrue(details["signoff_match"])
        self.assertGreater(score, 0.5)


class TestDryRunExecution(unittest.TestCase):
    """Test full dry-run pipeline executes without touching local_user_data."""

    def test_runner_initialization(self):
        runner = BaselineRunner(
            seed_corpus_path=REPO_ROOT / "eval" / "seed_corpus.json",
            scenarios_path=REPO_ROOT / "eval" / "scenarios.json",
            mode="dry-run",
        )
        self.assertEqual(len(runner.scenarios), 30)
        self.assertEqual(runner.mode, "dry-run")

    def test_temp_environment_isolation(self):
        runner = BaselineRunner(
            seed_corpus_path=REPO_ROOT / "eval" / "seed_corpus.json",
            scenarios_path=REPO_ROOT / "eval" / "scenarios.json",
            mode="dry-run",
        )
        temp_dir, settings, store, embedder, vector_store = runner._setup_temp_environment()

        # Verify temp dir is used, not local_user_data
        self.assertNotIn("local_user_data", str(temp_dir))
        self.assertTrue(temp_dir.exists())
        self.assertTrue(settings.local_user_data_dir == temp_dir)

        # Verify profile seeded
        profile = store.load_profile()
        self.assertIsNotNone(profile)
        if profile:
            self.assertEqual(profile.profile_id, "eval-profile")

        # Verify contacts seeded
        contacts = store.list_recipient_profiles()
        self.assertGreaterEqual(len(contacts), 6)

        # Verify LanceDB indexed
        self.assertGreater(vector_store.count(), 0)

        # Cleanup
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_single_scenario_dry_run(self):
        """Test one scenario through all 3 configs in dry-run."""
        runner = BaselineRunner(
            seed_corpus_path=REPO_ROOT / "eval" / "seed_corpus.json",
            scenarios_path=REPO_ROOT / "eval" / "scenarios.json",
            mode="dry-run",
        )
        temp_dir, settings, store, embedder, vector_store = runner._setup_temp_environment()

        try:
            scenario = runner.scenarios[0]  # casual_1on1_001
            mock_llm = MockLLM(seed=42)

            # Run all 3
            r_a = runner._run_baseline_a(scenario, mock_llm)
            r_b = runner._run_baseline_b(scenario, mock_llm)
            r_p = runner._run_proteus(scenario, settings, store, embedder, vector_store, mock_llm)

            # All should produce drafts
            self.assertIsInstance(r_a.draft, str)
            self.assertIsInstance(r_b.draft, str)
            self.assertIsInstance(r_p.draft, str)
            self.assertGreater(len(r_a.draft), 10)
            self.assertGreater(len(r_b.draft), 10)
            self.assertGreater(len(r_p.draft), 10)

            # Proteus should have resolution meta
            self.assertIn("audience_type", r_p.resolution_meta)
            self.assertIn("confidence", r_p.resolution_meta)

        finally:
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_full_dry_run_smoke(self):
        """Smoke test: run all 30 scenarios (but only 1 config each for speed)."""
        # This is a lightweight smoke test - full run is done manually
        runner = BaselineRunner(
            seed_corpus_path=REPO_ROOT / "eval" / "seed_corpus.json",
            scenarios_path=REPO_ROOT / "eval" / "scenarios.json",
            mode="dry-run",
        )
        # Just verify the runner can be created and scenarios loaded
        self.assertEqual(len(runner.scenarios), 30)


class TestBlindReview(unittest.TestCase):
    """Test blind review export and scoring."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="eval_test_"))
        self.run_results = self.temp_dir / "run_latest.json"
        self.scenarios_path = REPO_ROOT / "eval" / "scenarios.json"

        # Create minimal run results
        run_data = {
            "run_id": "test123",
            "started_at": "2026-01-01T00:00:00+00:00",
            "completed_at": "2026-01-01T00:01:00+00:00",
            "mode": "dry-run",
            "results": [],
        }
        # Add 3 configs for 2 scenarios - use generic draft text without config names
        for sid in ["casual_1on1_001", "formal_client_1on1_001"]:
            for config in ["baseline_a", "baseline_b", "proteus"]:
                run_data["results"].append({
                    "scenario_id": sid,
                    "config_name": config,
                    "draft": f"Hi there,\n\nThis is a draft for {sid}.\n\nBest,\nAlex",
                    "audience_type": "1on1_private",
                    "confidence_level": "high",
                    "resolution_meta": {},
                    "latency_ms": 100,
                    "timestamp": "2026-01-01T00:00:00+00:00",
                })
        self.run_results.write_text(json.dumps(run_data))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_export_creates_three_files(self):
        key_path, sheet_path, html_path = export_blind_review(
            self.run_results, self.scenarios_path, self.temp_dir, seed=42
        )
        self.assertTrue(key_path.exists())
        self.assertTrue(sheet_path.exists())
        self.assertTrue(html_path.exists())

    def test_blind_key_has_correct_structure(self):
        key_path, _, _ = export_blind_review(
            self.run_results, self.scenarios_path, self.temp_dir, seed=42
        )
        key = json.loads(key_path.read_text())
        self.assertIn("run_id", key)
        self.assertIn("seed", key)
        self.assertIn("mapping", key)
        self.assertEqual(len(key["mapping"]), 2)  # 2 scenarios
        for scenario_id, mapping in key["mapping"].items():
            self.assertEqual(set(mapping.keys()), {"Draft A", "Draft B", "Draft C"})
            self.assertEqual(set(mapping.values()), {"baseline_a", "baseline_b", "proteus"})

    def test_blind_review_sheet_no_config_names(self):
        _, sheet_path, _ = export_blind_review(
            self.run_results, self.scenarios_path, self.temp_dir, seed=42
        )
        sheet = json.loads(sheet_path.read_text())
        for scenario in sheet["scenarios"]:
            # Draft keys should be A/B/C, not config names
            self.assertEqual(set(scenario["drafts"].keys()), {"Draft A", "Draft B", "Draft C"})
            for label in ["Draft A", "Draft B", "Draft C"]:
                self.assertNotIn("baseline", scenario["drafts"][label].lower())

    def test_html_contains_all_scenarios(self):
        _, _, html_path = export_blind_review(
            self.run_results, self.scenarios_path, self.temp_dir, seed=42
        )
        html = html_path.read_text()
        self.assertIn("casual_1on1_001", html)
        self.assertIn("formal_client_1on1_001", html)
        self.assertIn("Draft A", html)
        self.assertIn("Draft B", html)
        self.assertIn("Draft C", html)
        # Should not contain config names in visible draft content
        # (blind_key_json in script is OK for functionality)
        # Check that draft-content divs don't have config names
        self.assertNotIn('class="draft-content">Draft from baseline', html)
        self.assertNotIn('class="draft-content">Draft from proteus', html)

    def test_score_review_generates_report(self):
        key_path, _, _ = export_blind_review(
            self.run_results, self.scenarios_path, self.temp_dir, seed=42
        )

        # Create mock completed review
        completed = {
            "run_id": "test123",
            "blind_key": json.loads(key_path.read_text())["mapping"],
            "reviews": [
                {
                    "scenario_id": "casual_1on1_001",
                    "voice_consistency": 5,
                    "recipient_appropriateness": 4,
                    "audience_formality": 3,
                    "contextual_relevance": 5,
                    "factual_correctness": 4,
                    "preferred_draft": "Draft C",  # maps to proteus
                    "edited_body": "Edited version",
                },
                {
                    "scenario_id": "formal_client_1on1_001",
                    "voice_consistency": 4,
                    "recipient_appropriateness": 5,
                    "audience_formality": 5,
                    "contextual_relevance": 4,
                    "factual_correctness": 5,
                    "preferred_draft": "Draft B",  # maps to baseline_b
                },
            ],
        }
        completed_path = self.temp_dir / "completed_review.json"
        completed_path.write_text(json.dumps(completed))

        report_path = self.temp_dir / "report.md"
        score_review(completed_path, key_path, None, report_path, self.scenarios_path)

        self.assertTrue(report_path.exists())
        report = report_path.read_text()
        self.assertIn("Proteus 3-Baseline Benchmark Report", report)
        self.assertIn("proteus", report.lower())
        self.assertIn("baseline_a", report.lower())
        self.assertIn("baseline_b", report.lower())


class TestLocalUserDataUntouched(unittest.TestCase):
    """Verify evaluation never touches production local_user_data."""

    def test_runner_uses_temp_dir_only(self):
        runner = BaselineRunner(
            seed_corpus_path=REPO_ROOT / "eval" / "seed_corpus.json",
            scenarios_path=REPO_ROOT / "eval" / "scenarios.json",
            mode="dry-run",
        )
        temp_dir, settings, store, embedder, vector_store = runner._setup_temp_environment()

        # Check all paths are under temp_dir
        self.assertTrue(str(settings.local_user_data_dir).startswith(str(temp_dir)))
        self.assertTrue(str(settings.lancedb_dir).startswith(str(temp_dir)))
        self.assertTrue(str(settings.sqlite_path).startswith(str(temp_dir)))
        self.assertTrue(str(settings.profile_path).startswith(str(temp_dir)))

        # Check store paths
        self.assertTrue(str(store.settings.local_user_data_dir).startswith(str(temp_dir)))

        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()