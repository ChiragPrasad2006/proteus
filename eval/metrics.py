#!/usr/bin/env python3
"""
Automated Metrics for 3-Baseline Personalization Benchmark.

Computes per-draft and per-category metrics comparing baseline_a, baseline_b, and proteus.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class MetricResult:
    scenario_id: str
    category: str
    config_name: str
    audience_accuracy: bool
    confidence_accuracy: bool
    leakage_violations: int
    factual_coverage: float
    voice_adherence: float
    edit_distance: float | None
    details: dict[str, Any]


def levenshtein_distance(a: str, b: str) -> int:
    """Word-level Levenshtein distance."""
    a_words = a.split()
    b_words = b.split()
    n, m = len(a_words), len(b_words)
    if n == 0:
        return m
    if m == 0:
        return n

    dp = list(range(m + 1))
    for i in range(1, n + 1):
        prev = dp[0]
        dp[0] = i
        for j in range(1, m + 1):
            cur = dp[j]
            if a_words[i - 1] == b_words[j - 1]:
                dp[j] = prev
            else:
                dp[j] = 1 + min(dp[j], dp[j - 1], prev)
            prev = cur
    return dp[m]


def normalized_edit_distance(a: str, b: str) -> float:
    """Normalized word-level Levenshtein (0.0 = identical, 1.0 = completely different)."""
    dist = levenshtein_distance(a, b)
    max_len = max(len(a.split()), len(b.split()))
    return dist / max_len if max_len > 0 else 0.0


def check_audience_accuracy(draft: str, expected_audience: str, context: dict) -> tuple[bool, str]:
    """Check if draft matches expected audience type."""
    actual = context.get("audience_type", "unknown")
    return actual == expected_audience, f"expected={expected_audience}, actual={actual}"


def check_confidence_accuracy(draft: str, expected_confidence: str, context: dict) -> tuple[bool, str]:
    """Check if confidence level matches expected."""
    actual = context.get("confidence_level", "unknown")
    return actual == expected_confidence, f"expected={expected_confidence}, actual={actual}"


def count_leakage_violations(draft: str, forbidden_patterns: list[str], audience_type: str) -> tuple[int, list[str]]:
    """Count forbidden pattern violations."""
    violations = []
    draft_lower = draft.lower()

    for pattern in forbidden_patterns:
        pattern_lower = pattern.lower()
        if pattern_lower in draft_lower:
            violations.append(pattern)

    # Additional audience-specific checks
    if audience_type in ("group_cc", "broadcast_bcc"):
        # Check for casual 1:1 leakage
        casual_indicators = [
            r"\bhey\b", r"\byo\b", r"\bbro\b", r"\blol\b", r"\bcheers\b",
            r"usual friday deploy", r"friday 4pm standup", r"ship date doesn't move",
        ]
        for ind in casual_indicators:
            if re.search(ind, draft_lower):
                violations.append(f"casual_leakage:{ind}")

    # Check for duplicate sign-offs
    signoff_lines = [l.strip().lower() for l in draft.split("\n") if l.strip()]
    closing_phrases = ("best", "regards", "thanks", "cheers", "sincerely", "respectfully", "kind regards", "warm regards")
    closing_count = sum(1 for l in signoff_lines if any(l.startswith(p) for p in closing_phrases))
    if closing_count > 1:
        violations.append(f"duplicate_signoff:{closing_count}")

    return len(violations), violations


def compute_factual_coverage(draft: str, required_facts: list[str]) -> tuple[float, list[str], list[str]]:
    """Compute fraction of required facts present in draft."""
    draft_lower = draft.lower()
    found = []
    missing = []

    for fact in required_facts:
        fact_lower = fact.lower()
        # Simple substring match for facts
        if fact_lower in draft_lower:
            found.append(fact)
        else:
            # Try word-level matching for multi-word facts
            fact_words = fact_lower.split()
            if len(fact_words) > 1:
                if all(w in draft_lower for w in fact_words):
                    found.append(fact)
                else:
                    missing.append(fact)
            else:
                missing.append(fact)

    coverage = len(found) / len(required_facts) if required_facts else 1.0
    return coverage, found, missing


def compute_voice_adherence(draft: str, scenario: dict, context: dict) -> tuple[float, dict]:
    """Compute voice adherence: greeting/sign-off match + sentence length deviation."""
    score = 0.0
    details = {}

    # Expected greeting from context
    expected_greeting = context.get("greeting", "").strip().rstrip(",")
    draft_lines = [l.strip() for l in draft.split("\n") if l.strip()]
    actual_greeting = draft_lines[0].rstrip(",") if draft_lines else ""

    greeting_match = expected_greeting.lower() == actual_greeting.lower()
    details["expected_greeting"] = expected_greeting
    details["actual_greeting"] = actual_greeting
    details["greeting_match"] = greeting_match
    if greeting_match:
        score += 0.4

    # Expected sign-off
    expected_signoff = context.get("signoff", "").strip()
    # Find sign-off in last few lines
    actual_signoff = ""
    for line in reversed(draft_lines[-3:]):
        line_lower = line.lower()
        if any(line_lower.startswith(p) for p in ("best", "regards", "thanks", "cheers", "sincerely", "respectfully")):
            actual_signoff = line
            break
    # More flexible signoff matching
    signoff_match = False
    if expected_signoff and actual_signoff:
        expected_first = expected_signoff.split("\n")[0].strip().lower()
        actual_first = actual_signoff.split("\n")[0].strip().lower()
        signoff_match = expected_first in actual_first or actual_first in expected_first
    details["expected_signoff"] = expected_signoff
    details["actual_signoff"] = actual_signoff
    details["signoff_match"] = signoff_match
    if signoff_match:
        score += 0.3

    # Sentence length adherence
    target_length = context.get("target_sentence_length", 16)
    sentences = re.split(r"[.!?]+", draft)
    sentences = [s.strip() for s in sentences if s.strip()]
    if sentences:
        avg_len = sum(len(s.split()) for s in sentences) / len(sentences)
        deviation = abs(avg_len - target_length) / target_length
        length_score = max(0, 1 - deviation)
        score += 0.3 * length_score
        details["target_sentence_length"] = target_length
        details["actual_avg_sentence_length"] = round(avg_len, 1)
        details["length_deviation"] = round(deviation, 3)
    else:
        details["target_sentence_length"] = target_length
        details["actual_avg_sentence_length"] = 0
        details["length_deviation"] = 1.0

    return min(1.0, score), details


def compute_metrics(
    run_results_path: Path,
    scenarios_path: Path,
    human_edited_path: Path | None = None,
) -> list[MetricResult]:
    """Compute all metrics for a run."""
    run_data = json.loads(run_results_path.read_text())
    scenarios_data = json.loads(scenarios_path.read_text())
    scenarios = {s["id"]: s for s in scenarios_data["scenarios"]}

    # Load human edits if provided
    human_edits = {}
    if human_edited_path and human_edited_path.exists():
        human_data = json.loads(human_edited_path.read_text())
        for item in human_data.get("reviews", []):
            human_edits[(item["scenario_id"], item["config_name"])] = item.get("edited_body", "")

    # Group results by scenario
    by_scenario = defaultdict(list)
    for r in run_data["results"]:
        by_scenario[r["scenario_id"]].append(r)

    results = []
    for scenario_id, scenario_results in by_scenario.items():
        scenario = scenarios.get(scenario_id, {})
        category = scenario.get("category", "unknown")
        required_facts = scenario.get("required_facts", [])
        forbidden_patterns = scenario.get("forbidden_patterns", [])
        expected_audience = scenario.get("expected_audience", "1on1_private")
        expected_confidence = scenario.get("expected_confidence", "low")

        for r in scenario_results:
            draft = r["draft"]
            context = r.get("resolution_meta", {})
            context["audience_type"] = r.get("audience_type", "unknown")
            context["confidence_level"] = r.get("confidence_level", "unknown")

            # Audience accuracy
            aud_acc, aud_detail = check_audience_accuracy(draft, expected_audience, context)

            # Confidence accuracy
            conf_acc, conf_detail = check_confidence_accuracy(draft, expected_confidence, context)

            # Leakage violations
            leak_count, leak_details = count_leakage_violations(
                draft, forbidden_patterns, r.get("audience_type", "unknown")
            )

            # Factual coverage
            fact_cov, fact_found, fact_missing = compute_factual_coverage(draft, required_facts)

            # Voice adherence
            voice_score, voice_details = compute_voice_adherence(draft, scenario, context)

            # Edit distance (if human edits available)
            edit_dist = None
            if (scenario_id, r["config_name"]) in human_edits:
                edit_dist = normalized_edit_distance(draft, human_edits[(scenario_id, r["config_name"])])

            results.append(MetricResult(
                scenario_id=scenario_id,
                category=category,
                config_name=r["config_name"],
                audience_accuracy=aud_acc,
                confidence_accuracy=conf_acc,
                leakage_violations=leak_count,
                factual_coverage=fact_cov,
                voice_adherence=voice_score,
                edit_distance=edit_dist,
                details={
                    "audience_detail": aud_detail,
                    "confidence_detail": conf_detail,
                    "leakage_details": leak_details,
                    "facts_found": fact_found,
                    "facts_missing": fact_missing,
                    "voice_details": voice_details,
                },
            ))

    return results


def aggregate_metrics(metrics: list[MetricResult]) -> dict[str, Any]:
    """Aggregate metrics by config and category."""
    by_config = defaultdict(lambda: defaultdict(list))
    by_category = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))

    for m in metrics:
        by_config[m.config_name]["audience_accuracy"].append(m.audience_accuracy)
        by_config[m.config_name]["confidence_accuracy"].append(m.confidence_accuracy)
        by_config[m.config_name]["leakage_violations"].append(m.leakage_violations)
        by_config[m.config_name]["factual_coverage"].append(m.factual_coverage)
        by_config[m.config_name]["voice_adherence"].append(m.voice_adherence)
        if m.edit_distance is not None:
            by_config[m.config_name]["edit_distance"].append(m.edit_distance)

        by_category[m.category][m.config_name]["audience_accuracy"].append(m.audience_accuracy)
        by_category[m.category][m.config_name]["confidence_accuracy"].append(m.confidence_accuracy)
        by_category[m.category][m.config_name]["leakage_violations"].append(m.leakage_violations)
        by_category[m.category][m.config_name]["factual_coverage"].append(m.factual_coverage)
        by_category[m.category][m.config_name]["voice_adherence"].append(m.voice_adherence)
        if m.edit_distance is not None:
            by_category[m.category][m.config_name]["edit_distance"].append(m.edit_distance)

    def mean(lst):
        return sum(lst) / len(lst) if lst else 0

    agg = {
        "overall": {},
        "by_category": {},
    }

    for config, vals in by_config.items():
        agg["overall"][config] = {
            "audience_accuracy": round(mean(vals["audience_accuracy"]), 3),
            "confidence_accuracy": round(mean(vals["confidence_accuracy"]), 3),
            "leakage_violations_mean": round(mean(vals["leakage_violations"]), 3),
            "factual_coverage": round(mean(vals["factual_coverage"]), 3),
            "voice_adherence": round(mean(vals["voice_adherence"]), 3),
            "edit_distance_mean": round(mean(vals.get("edit_distance", [])), 3) if vals.get("edit_distance") else None,
            "count": len(vals["audience_accuracy"]),
        }

    for cat, configs in by_category.items():
        agg["by_category"][cat] = {}
        for config, vals in configs.items():
            agg["by_category"][cat][config] = {
                "audience_accuracy": round(mean(vals["audience_accuracy"]), 3),
                "confidence_accuracy": round(mean(vals["confidence_accuracy"]), 3),
                "leakage_violations_mean": round(mean(vals["leakage_violations"]), 3),
                "factual_coverage": round(mean(vals["factual_coverage"]), 3),
                "voice_adherence": round(mean(vals["voice_adherence"]), 3),
                "edit_distance_mean": round(mean(vals.get("edit_distance", [])), 3) if vals.get("edit_distance") else None,
                "count": len(vals["audience_accuracy"]),
            }

    return agg


def print_report(agg: dict[str, Any]):
    """Print formatted metrics report."""
    print("\n" + "=" * 80)
    print("AUTOMATED METRICS REPORT")
    print("=" * 80)

    print("\n--- OVERALL ---")
    configs = ["baseline_a", "baseline_b", "proteus"]
    header = f"{'Config':<15} {'Aud.Acc':>8} {'Conf.Acc':>8} {'Leakage':>8} {'FactCov':>8} {'Voice':>8} {'EditDist':>8} {'N':>4}"
    print(header)
    print("-" * len(header))
    for config in configs:
        if config in agg["overall"]:
            v = agg["overall"][config]
            print(f"{config:<15} {v['audience_accuracy']:>8.3f} {v['confidence_accuracy']:>8.3f} "
                  f"{v['leakage_violations_mean']:>8.3f} {v['factual_coverage']:>8.3f} "
                  f"{v['voice_adherence']:>8.3f} {str(v['edit_distance_mean'] or 'N/A'):>8} {v['count']:>4}")

    print("\n--- BY CATEGORY ---")
    for cat in sorted(agg["by_category"].keys()):
        print(f"\n{cat}:")
        header = f"{'Config':<15} {'Aud.Acc':>8} {'Conf.Acc':>8} {'Leakage':>8} {'FactCov':>8} {'Voice':>8} {'EditDist':>8} {'N':>4}"
        print(header)
        print("-" * len(header))
        for config in configs:
            if config in agg["by_category"][cat]:
                v = agg["by_category"][cat][config]
                print(f"{config:<15} {v['audience_accuracy']:>8.3f} {v['confidence_accuracy']:>8.3f} "
                      f"{v['leakage_violations_mean']:>8.3f} {v['factual_coverage']:>8.3f} "
                      f"{v['voice_adherence']:>8.3f} {str(v['edit_distance_mean'] or 'N/A'):>8} {v['count']:>4}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Compute automated metrics for benchmark run")
    parser.add_argument("--run", type=Path, required=True, help="Run results JSON path")
    parser.add_argument("--scenarios", type=Path, default=Path("eval/scenarios.json"), help="Scenarios JSON path")
    parser.add_argument("--human-edited", type=Path, help="Human-edited drafts JSON path")
    parser.add_argument("--output", type=Path, help="Output metrics JSON path")
    args = parser.parse_args()

    metrics = compute_metrics(args.run, args.scenarios, args.human_edited)
    agg = aggregate_metrics(metrics)
    print_report(agg)

    if args.output:
        output_data = {
            "per_draft": [
                {
                    "scenario_id": m.scenario_id,
                    "category": m.category,
                    "config_name": m.config_name,
                    "audience_accuracy": m.audience_accuracy,
                    "confidence_accuracy": m.confidence_accuracy,
                    "leakage_violations": m.leakage_violations,
                    "factual_coverage": m.factual_coverage,
                    "voice_adherence": m.voice_adherence,
                    "edit_distance": m.edit_distance,
                    "details": m.details,
                }
                for m in metrics
            ],
            "aggregated": agg,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(output_data, indent=2))
        print(f"\nMetrics saved to {args.output}")


if __name__ == "__main__":
    main()