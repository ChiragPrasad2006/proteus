"""Tests for the evaluation harness (eval/).
Verifies: 30 scenarios, 8 categories, synthetic data only, dry-run execution,
live-mode experimental controls, metrics, and blind review export/scoring.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from eval.blind_review import export_blind_review, score_review
from eval.metrics import (
    aggregate_metrics,
    check_audience_accuracy,
    check_confidence_accuracy,
    compute_factual_coverage,
    compute_metrics,
    compute_voice_adherence,
    count_leakage_violations,
    levenshtein_distance,
    normalized_edit_distance,
)
from eval.runner import (
    CONTROL_MODEL,
    CONTROL_NUM_PREDICT,
    CONTROL_SEED,
    CONTROL_TEMPERATURE,
    CONTROL_THINK,
    BaselineRunner,
    MockLLM,
)


class TestSeedCorpus(unittest.TestCase):
    """Verify seed_corpus.json is valid and 100% synthetic."""

    def setUp(self):
        self.corpus_path = REPO_ROOT / "eval" / "seed_corpus.json"
        self.corpus = json.loads(self.corpus_path.read_text(encoding="utf-8"))

    def test_persona_structure(self):
        persona = self.corpus["persona"]
        for field in (
            "name",
            "role",
            "global_style_card",
            "deterministic_stylometry",
            "global_learned_rules",
        ):
            self.assertIn(field, persona)

    def test_contacts_count(self):
        contacts = self.corpus["contacts"]
        self.assertGreaterEqual(len(contacts), 6)
        self.assertLessEqual(len(contacts), 8)
        for c in contacts:
            self.assertIn("recipient_email", c)
            self.assertIn("relationship_tier", c)
            self.assertIn("learned_rules_json", c)
            self.assertLessEqual(len(c["learned_rules_json"]), 2)
            self.assertNotIn("gmail.com", c["recipient_email"])
            self.assertNotIn("pacewisdom.com", c["recipient_email"])

    def test_historical_emails_count_and_word_counts(self):
        emails = self.corpus["historical_emails"]
        self.assertGreaterEqual(len(emails), 40)
        self.assertLessEqual(len(emails), 50)
        for e in emails:
            self.assertIn("message_id", e)
            self.assertIn("recipient_email", e)
            self.assertIn("audience_mode", e)
            self.assertIn(e["audience_mode"], ["1on1_private", "group_cc", "broadcast_bcc"])
            actual_words = len(e["clean_body"].split())
            self.assertEqual(e["word_count"], actual_words, f"Word count mismatch in {e['message_id']}")
            self.assertGreaterEqual(actual_words, 25, f"{e['message_id']} below LanceDB min_word_count=25")

    def test_no_real_emails_in_corpus(self):
        """Ensure no real user emails from local_user_data leak into seed corpus."""
        corpus_str = json.dumps(self.corpus).lower()
        forbidden = ["kamisama7892", "punya.h", "pacewisdom", "chiragprasad", "realuser"]
        for f in forbidden:
            self.assertNotIn(f, corpus_str, f"Real email pattern '{f}' found in seed corpus")

    def test_timestamps_span_range(self):
        """Verify timestamps cover recent (5-45 days) and stale (150-300 days)."""
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
        self.data = json.loads(self.scenarios_path.read_text(encoding="utf-8"))

    def test_exactly_30_scenarios(self):
        self.assertEqual(len(self.data["scenarios"]), 30, "Must have exactly 30 scenarios")

    def test_8_categories_covered(self):
        categories = {s["category"] for s in self.data["scenarios"]}
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
        self.assertEqual(categories, expected)

    def test_category_distribution(self):
        counts: dict[str, int] = {}
        for s in self.data["scenarios"]:
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
        required = [
            "id",
            "category",
            "to",
            "cc",
            "bcc",
            "task_prompt",
            "incoming_context",
            "required_facts",
            "expected_audience",
            "expected_confidence",
            "forbidden_patterns",
            "reviewer_notes",
        ]
        for s in self.data["scenarios"]:
            for field in required:
                self.assertIn(field, s, f"Missing field {field} in {s.get('id', 'unknown')}")

    def test_no_real_emails_in_scenarios(self):
        scenarios_str = json.dumps(self.data).lower()
        for f in ("kamisama7892", "punya.h", "pacewisdom", "chiragprasad"):
            self.assertNotIn(f, scenarios_str)

    def test_forbidden_patterns_include_corporate_cliches(self):
        for s in self.data["scenarios"]:
            patterns = s["forbidden_patterns"]
            self.assertIn("**", patterns)
            self.assertIn("{first_name}", patterns)
            self.assertIn("I hope this email finds you well", patterns)


class TestMockLLM(unittest.TestCase):
    """Test deterministic mocked LLM adapter."""

    def test_deterministic_output(self):
        llm = MockLLM(seed=42)
        out1 = llm.generate("sys", "Draft an email covering these points:\nConfirm deploy.")
        out2 = llm.generate("sys", "Draft an email covering these points:\nConfirm deploy.")
        self.assertEqual(out1, out2)

    def test_different_seeds_different_output(self):
        llm1 = MockLLM(seed=42)
        llm2 = MockLLM(seed=43)
        # Check across multiple prompts that seed affects rng-dependent branches.
        outputs_differ = any(
            llm1.generate("sys", f"Draft an email covering these points:\nPoint {i}.")
            != llm2.generate("sys", f"Draft an email covering these points:\nPoint {i}.")
            for i in range(15)
        )
        self.assertTrue(outputs_differ)

    def test_greeting_signoff_and_facts_extraction(self):
        llm = MockLLM(seed=42)
        sys_prompt = "PRIMARY GREETING TO USE: Hi Sam,\nSign-off to use: Best,\nAlex\nTarget sentence length: 14"
        user_prompt = "Draft an email covering these points:\nConfirm Friday deploy and 94% pass rate."
        out = llm.generate(sys_prompt, user_prompt)
        self.assertTrue(out.startswith("Hi Sam,"))
        self.assertIn("Friday deploy", out)
        self.assertIn("94% pass rate", out)
        self.assertTrue(out.endswith("Best,\nAlex"))


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

    def test_check_audience_and_confidence_accuracy(self):
        self.assertTrue(check_audience_accuracy("", "group_cc", {"audience_type": "group_cc"})[0])
        self.assertFalse(check_audience_accuracy("", "1on1_private", {"audience_type": "group_cc"})[0])
        self.assertTrue(check_confidence_accuracy("", "high", {"confidence_level": "high"})[0])
        self.assertFalse(check_confidence_accuracy("", "low", {"confidence_level": "high"})[0])

    def test_leakage_no_false_positive_on_substrings(self):
        draft = "Hello everyone,\n\nThis policy ensures they verify CSP headers while shipping.\n\nBest,\nAlex"
        patterns = ["Hey", "Hi ", "Hi,", "Cheers", "**", "{first_name}"]
        count, violations = count_leakage_violations(draft, patterns, "broadcast_bcc")
        self.assertEqual(count, 0, f"Unexpected false-positive violations: {violations}")

    def test_leakage_detects_casual_in_group(self):
        draft = "Hey Sam,\n\nThe usual Friday deploy is on track.\n\nCheers,\nAlex"
        patterns = ["**", "{first_name}"]
        count, violations = count_leakage_violations(draft, patterns, "group_cc")
        self.assertGreaterEqual(count, 2)
        self.assertTrue(any("casual_leakage" in v for v in violations))

    def test_compute_metrics_uses_expected_audience_for_leakage(self):
        """Even if a baseline reports 1on1_private, group_cc leakage must still be caught."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            run_path = tmp_path / "run.json"
            run_path.write_text(
                json.dumps(
                    {
                        "run_id": "t1",
                        "results": [
                            {
                                "scenario_id": "familiar_plus_cc_escalation_001",
                                "config_name": "baseline_b",
                                "draft": "Hey Sam,\n\nThe usual Friday deploy is set for Friday Model v3 94% James Vertex integration.\n\nBest,\nAlex",
                                "audience_type": "1on1_private",
                                "confidence_level": "medium",
                                "resolution_meta": {},
                                "latency_ms": 1.0,
                                "timestamp": "2026-01-01T00:00:00+00:00",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            results = compute_metrics(run_path, REPO_ROOT / "eval" / "scenarios.json")
            self.assertEqual(len(results), 1)
            self.assertGreater(results[0].leakage_violations, 0)
            self.assertGreater(results[0].factual_coverage, 0.9)
            self.assertGreater(results[0].voice_adherence, 0.0)

    def test_compute_factual_coverage(self):
        draft = "The Friday deploy for Model v3 is at 94% pass rate. Meeting tomorrow 10am."
        facts = ["Friday deploy", "Model v3", "94% pass rate", "tomorrow 10am"]
        coverage, found, _ = compute_factual_coverage(draft, facts)
        self.assertEqual(coverage, 1.0)
        self.assertEqual(len(found), 4)

    def test_compute_voice_adherence(self):
        draft = "Hi Sam,\n\nFriday deploy is on track for tomorrow.\n\nBest,\nAlex"
        context = {
            "greeting": "Hi Sam,",
            "signoff": "Best,\nAlex",
            "target_sentence_length": 14,
        }
        score, details = compute_voice_adherence(draft, {}, context)
        self.assertTrue(details["greeting_match"])
        self.assertTrue(details["signoff_match"])
        self.assertGreater(score, 0.7)


class TestDryRunAndControls(unittest.TestCase):
    """Test full 30-scenario dry-run execution, isolation, and live experimental controls."""

    def test_full_30_scenario_dry_run_isolated(self):
        with tempfile.TemporaryDirectory(prefix="eval_full_dry_") as tmp:
            out_path = Path(tmp) / "dry_run.json"
            runner = BaselineRunner(
                seed_corpus_path=REPO_ROOT / "eval" / "seed_corpus.json",
                scenarios_path=REPO_ROOT / "eval" / "scenarios.json",
                mode="dry-run",
                output_path=out_path,
            )
            results = runner.run()
            self.assertEqual(len(results), 90)
            self.assertTrue(out_path.exists())

            proteus_results = [r for r in results if r.config_name == "proteus"]
            self.assertEqual(len(proteus_results), 30)
            for r in proteus_results:
                self.assertIn("audience_type", r.resolution_meta)
                self.assertIn("confidence", r.resolution_meta)

            # Verify metrics are non-degenerate in dry-run (factual coverage & voice adherence > 0).
            metrics = compute_metrics(out_path, REPO_ROOT / "eval" / "scenarios.json")
            agg = aggregate_metrics(metrics)
            self.assertEqual(agg["overall"]["proteus"]["audience_accuracy"], 1.0)
            self.assertGreater(agg["overall"]["proteus"]["factual_coverage"], 0.8)
            self.assertGreater(agg["overall"]["proteus"]["voice_adherence"], 0.5)

    def test_live_mode_experimental_controls(self):
        """Mock Ollama HTTP calls to verify identical controlled params across all 3 arms."""
        runner = BaselineRunner(
            seed_corpus_path=REPO_ROOT / "eval" / "seed_corpus.json",
            scenarios_path=REPO_ROOT / "eval" / "scenarios.json",
            mode="live",
        )
        temp_dir, settings, store, embedder, vector_store = runner._setup_temp_environment()
        captured_payloads = []

        def fake_post(url, json=None, timeout=None):
            captured_payloads.append(json)
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json.return_value = {
                "message": {"content": "Hi Sam,\n\nFriday deploy is on track.\n\nBest,\nAlex"}
            }
            return resp

        try:
            from backend.generation.drafter import QwenDrafter

            drafter = QwenDrafter(settings)
            scenario = runner.scenarios[0]
            with patch("eval.runner.httpx.post", side_effect=fake_post):
                runner._run_baseline_a(scenario, settings, drafter)
                runner._run_baseline_b(scenario, settings, drafter)
                runner._run_proteus(scenario, settings, store, embedder, vector_store, drafter)

            self.assertEqual(len(captured_payloads), 3)
            user_prompts = set()
            for payload in captured_payloads:
                self.assertEqual(payload["model"], CONTROL_MODEL)
                self.assertEqual(payload["think"], CONTROL_THINK)
                self.assertEqual(payload["options"]["temperature"], CONTROL_TEMPERATURE)
                self.assertEqual(payload["options"]["seed"], CONTROL_SEED)
                self.assertEqual(payload["options"]["num_predict"], CONTROL_NUM_PREDICT)
                user_prompts.add(payload["messages"][1]["content"])
            self.assertEqual(len(user_prompts), 1, "All 3 arms must receive identical user_prompt")
        finally:
            del vector_store, store
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_temp_environment_never_touches_local_user_data(self):
        runner = BaselineRunner(
            seed_corpus_path=REPO_ROOT / "eval" / "seed_corpus.json",
            scenarios_path=REPO_ROOT / "eval" / "scenarios.json",
            mode="dry-run",
        )
        temp_dir, settings, store, embedder, vector_store = runner._setup_temp_environment()
        try:
            self.assertNotIn("local_user_data", str(temp_dir))
            self.assertTrue(str(settings.local_user_data_dir).startswith(str(temp_dir)))
            self.assertTrue(str(settings.lancedb_dir).startswith(str(temp_dir)))
            self.assertTrue(str(settings.sqlite_path).startswith(str(temp_dir)))
            self.assertTrue(str(store.settings.local_user_data_dir).startswith(str(temp_dir)))
            self.assertGreater(vector_store.count(), 0)
        finally:
            del vector_store, store
            shutil.rmtree(temp_dir, ignore_errors=True)


class TestBlindReview(unittest.TestCase):
    """Test blind review export, unblinding safety, CLI flags, and scoring."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="eval_test_"))
        self.run_results = self.temp_dir / "run_latest.json"
        self.scenarios_path = REPO_ROOT / "eval" / "scenarios.json"

        run_data = {
            "run_id": "test123",
            "started_at": "2026-01-01T00:00:00+00:00",
            "completed_at": "2026-01-01T00:01:00+00:00",
            "mode": "dry-run",
            "results": [],
        }
        for sid in ("casual_1on1_001", "formal_client_1on1_004"):
            for config in ("baseline_a", "baseline_b", "proteus"):
                run_data["results"].append(
                    {
                        "scenario_id": sid,
                        "config_name": config,
                        "draft": f"Hi there,\n\nLatency p99 < 200ms draft for {sid}.\n\nBest,\nAlex",
                        "audience_type": "1on1_private",
                        "confidence_level": "high",
                        "resolution_meta": {},
                        "latency_ms": 100,
                        "timestamp": "2026-01-01T00:00:00+00:00",
                    }
                )
        self.run_results.write_text(json.dumps(run_data), encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_export_does_not_leak_key_or_external_cdns(self):
        key_path, sheet_path, html_path = export_blind_review(
            self.run_results, self.scenarios_path, self.temp_dir, seed=42
        )
        self.assertTrue(key_path.exists())
        self.assertTrue(sheet_path.exists())
        self.assertTrue(html_path.exists())

        sheet_text = sheet_path.read_text(encoding="utf-8")
        html_text = html_path.read_text(encoding="utf-8")

        for leaked in ("baseline_a", "baseline_b", "proteus", "BLIND_KEY", "fonts.googleapis.com", "https://"):
            self.assertNotIn(leaked, html_text, f"Leak or external CDN found in HTML: {leaked}")
        self.assertNotIn("baseline_a", sheet_text)
        self.assertNotIn("baseline_b", sheet_text)
        self.assertNotIn("proteus", sheet_text)

        # Unique radio group per scenario and escaped `< 200ms`.
        self.assertIn('name="preferred_casual_1on1_001"', html_text)
        self.assertIn('name="preferred_formal_client_1on1_004"', html_text)
        self.assertIn("&lt; 200ms", html_text)

    def test_score_review_computes_scores_and_edit_distance(self):
        key_path, _, _ = export_blind_review(
            self.run_results, self.scenarios_path, self.temp_dir, seed=42
        )
        key_map = json.loads(key_path.read_text(encoding="utf-8"))["mapping"]
        rev_001 = {v: k for k, v in key_map["casual_1on1_001"].items()}
        rev_004 = {v: k for k, v in key_map["formal_client_1on1_004"].items()}

        completed = {
            "run_id": "test123",
            "reviews": [
                {
                    "scenario_id": "casual_1on1_001",
                    "scores": {
                        rev_001["proteus"]: {
                            "voice_consistency": 5,
                            "recipient_appropriateness": 5,
                            "audience_formality": 5,
                            "contextual_relevance": 5,
                            "factual_correctness": 5,
                        },
                        rev_001["baseline_b"]: {
                            "voice_consistency": 4,
                            "recipient_appropriateness": 3,
                            "audience_formality": 3,
                            "contextual_relevance": 4,
                            "factual_correctness": 4,
                        },
                        rev_001["baseline_a"]: {
                            "voice_consistency": 2,
                            "recipient_appropriateness": 2,
                            "audience_formality": 2,
                            "contextual_relevance": 3,
                            "factual_correctness": 4,
                        },
                    },
                    "preferred_draft": rev_001["proteus"],
                    "edited_body": "Hi there,\n\nLatency p99 < 200ms draft for casual_1on1_001 updated.\n\nBest,\nAlex",
                },
                {
                    "scenario_id": "formal_client_1on1_004",
                    "preferred_draft": rev_004["baseline_b"],
                    "voice_consistency": 4,
                    "recipient_appropriateness": 4,
                    "audience_formality": 4,
                    "contextual_relevance": 4,
                    "factual_correctness": 4,
                },
            ],
        }
        completed_path = self.temp_dir / "completed_review.json"
        completed_path.write_text(json.dumps(completed), encoding="utf-8")

        report_path = self.temp_dir / "report.md"
        score_review(
            completed_path,
            key_path,
            None,
            report_path,
            self.scenarios_path,
            run_results_path=self.run_results,
        )

        report = report_path.read_text(encoding="utf-8")
        self.assertIn("Overall Win / Tie / Loss Matrix", report)
        self.assertIn("Pairwise: Proteus vs Baselines", report)
        self.assertIn("Mean Human Edit Distance", report)
        self.assertNotIn("See metrics.json", report)
        self.assertIn("| proteus | 1 | 50.0% |", report)

    def test_cli_export_and_score_flags(self):
        """Verify --export and --score flags work cleanly from CLI."""
        res_exp = subprocess.run(
            [
                sys.executable,
                "-m",
                "eval.blind_review",
                "--export",
                str(self.run_results),
                "--output-dir",
                str(self.temp_dir),
                "--scenarios",
                str(self.scenarios_path),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertIn("Exported blind review packet", res_exp.stdout)

        key_map = json.loads((self.temp_dir / "blind_key.json").read_text(encoding="utf-8"))["mapping"]
        rev_001 = {v: k for k, v in key_map["casual_1on1_001"].items()}
        completed_path = self.temp_dir / "completed_review.json"
        completed_path.write_text(
            json.dumps(
                {
                    "run_id": "test123",
                    "reviews": [
                        {
                            "scenario_id": "casual_1on1_001",
                            "preferred_draft": rev_001["proteus"],
                            "voice_consistency": 5,
                            "recipient_appropriateness": 5,
                            "audience_formality": 5,
                            "contextual_relevance": 5,
                            "factual_correctness": 5,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        report_path = self.temp_dir / "cli_report.md"
        res_score = subprocess.run(
            [
                sys.executable,
                "-m",
                "eval.blind_review",
                "--score",
                str(completed_path),
                "--key",
                str(self.temp_dir / "blind_key.json"),
                "--output",
                str(report_path),
                "--scenarios",
                str(self.scenarios_path),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertIn("Report written", res_score.stdout)
        self.assertTrue(report_path.exists())


if __name__ == "__main__":
    unittest.main()
