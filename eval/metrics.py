#!/usr/bin/env python3
"""
Automated Metrics for 3-Baseline Personalization Benchmark.

Computes per-draft and per-category metrics comparing baseline_a, baseline_b, and proteus.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_CLOSING_LINE_RE = re.compile(
    r"^(?:best(?:\s+regards)?|regards|warm\s+regards|kind\s+regards|"
    r"thanks|cheers|sincerely|respectfully|talk\s+soon)[,!]?$",
    re.IGNORECASE,
)
_WORD_CHAR_PATTERN_RE = re.compile(r"^[A-Za-z0-9\s'.,!?-]+$")


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


def check_audience_accuracy(draft: str, expected_audience: str, context: dict[str, Any]) -> tuple[bool, str]:
    """Check if predicted/resolved audience matches expected audience type."""
    actual = context.get("audience_type", "unknown")
    return actual == expected_audience, f"expected={expected_audience}, actual={actual}"


def check_confidence_accuracy(draft: str, expected_confidence: str, context: dict[str, Any]) -> tuple[bool, str]:
    """Check if confidence level matches expected confidence."""
    actual = context.get("confidence_level", "unknown")
    return actual == expected_confidence, f"expected={expected_confidence}, actual={actual}"


def _pattern_present(draft_lower: str, pattern: str) -> bool:
    """Match forbidden pattern safely (word boundaries for prose tokens, substring for syntax markers)."""
    pat_lower = pattern.lower()
    stripped = pat_lower.strip()
    if not stripped:
        return False
    # Patterns with punctuation/symbols like "**" or "{first_name}" use exact substring matching.
    if "**" in pat_lower or "{" in pat_lower or "}" in pat_lower:
        return pat_lower in draft_lower
    # Patterns ending with a space/comma (e.g. "Hi ") match at word start.
    if pat_lower != stripped or not _WORD_CHAR_PATTERN_RE.match(stripped):
        return bool(re.search(r"(?<!\w)" + re.escape(pat_lower), draft_lower))
    # Word/phrase patterns use non-word boundaries so "Hi" never matches "this" and "Hey" never matches "they".
    return bool(re.search(r"(?<!\w)" + re.escape(stripped) + r"(?!\w)", draft_lower))


def count_leakage_violations(
    draft: str,
    forbidden_patterns: list[str],
    audience_type: str,
) -> tuple[int, list[str]]:
    """Count forbidden pattern violations, casual 1:1 leakage in group/broadcast, and duplicate sign-offs."""
    violations: list[str] = []
    draft_lower = draft.lower()

    for pattern in forbidden_patterns:
        if _pattern_present(draft_lower, pattern):
            violations.append(pattern)

    # Check casual 1:1 leakage against the scenario's true audience topology.
    if audience_type in ("group_cc", "broadcast_bcc"):
        casual_indicators = [
            r"\bhey\b",
            r"\byo\b",
            r"\bbro\b",
            r"\blol\b",
            r"\bcheers\b",
            r"usual friday deploy",
            r"friday 4pm standup",
        ]
        for ind in casual_indicators:
            if re.search(ind, draft_lower):
                violations.append(f"casual_leakage:{ind}")

    # Check for duplicate standalone sign-off lines.
    non_empty_lines = [line.strip() for line in draft.splitlines() if line.strip()]
    closing_count = sum(1 for line in non_empty_lines if _CLOSING_LINE_RE.match(line))
    if closing_count > 1:
        violations.append(f"duplicate_signoff:{closing_count}")

    return len(violations), violations


def compute_factual_coverage(draft: str, required_facts: list[str]) -> tuple[float, list[str], list[str]]:
    """Compute fraction of required facts present in draft."""
    draft_lower = draft.lower()
    found: list[str] = []
    missing: list[str] = []

    for fact in required_facts:
        fact_lower = fact.lower().strip()
        if not fact_lower:
            continue
        if fact_lower in draft_lower:
            found.append(fact)
            continue
        fact_words = [w for w in re.split(r"\s+", fact_lower) if w]
        if len(fact_words) > 1 and all(
            re.search(r"(?<!\w)" + re.escape(w) + r"(?!\w)", draft_lower) for w in fact_words
        ):
            found.append(fact)
        else:
            missing.append(fact)

    total = len(found) + len(missing)
    coverage = len(found) / total if total > 0 else 1.0
    return coverage, found, missing


def _derive_voice_target(scenario: dict[str, Any], seed_corpus: dict[str, Any] | None) -> dict[str, Any]:
    """Derive expected greeting, signoff, and target sentence length from persona + scenario."""
    if not seed_corpus:
        return {"greeting": "", "signoff": "", "target_sentence_length": 16.0}

    persona = seed_corpus.get("persona", {})
    stylometry = persona.get("deterministic_stylometry", {})
    base_len = float(stylometry.get("avg_sentence_length_words") or 16.0)
    exact_signoff = str(stylometry.get("exact_signoff") or "Best,\nAlex").strip()

    to_list = scenario.get("to") or []
    primary = str(to_list[0]).strip() if to_list else ""
    local = primary.split("@", 1)[0] if "@" in primary else primary
    for sep in (".", "_", "-", "+"):
        local = local.split(sep)[0]
    first_name = local.capitalize() if local.isalpha() and 2 <= len(local) <= 20 else ""

    contacts = {
        str(c.get("recipient_email", "")).lower(): c
        for c in seed_corpus.get("contacts", [])
    }
    contact = contacts.get(primary.lower(), {})

    expected_audience = scenario.get("expected_audience", "1on1_private")
    expected_confidence = scenario.get("expected_confidence", "low")

    if expected_audience == "broadcast_bcc":
        greeting = "Hello everyone,"
        signoff = exact_signoff
        target_len = max(15.0, min(20.0, base_len))
    elif expected_audience == "group_cc":
        greeting = f"Hi {first_name}," if first_name else "Hi everyone,"
        signoff = exact_signoff
        target_len = max(14.0, min(20.0, base_len))
    else:
        if expected_confidence == "low":
            greeting = f"Hi {first_name}," if first_name else "Hello,"
            signoff = exact_signoff
        else:
            greeting = str(contact.get("preferred_greeting") or "").strip() or (
                f"Hi {first_name}," if first_name else "Hi,"
            )
            # Match contact's established signoff if they have a distinct formal/creative register.
            if primary.lower() == "thomas.ng@regulatory.gov":
                signoff = "Sincerely,\nAlex Chen"
            elif primary.lower() == "priya.sharma@healthtech.io":
                signoff = "Thanks,\nAlex"
            elif primary.lower() == "elena.rossi@designstudio.agency":
                signoff = "Talk soon,\nAlex"
            else:
                signoff = exact_signoff
        target_len = base_len

    return {
        "greeting": greeting,
        "signoff": signoff,
        "target_sentence_length": target_len,
    }


def compute_voice_adherence(
    draft: str,
    scenario: dict[str, Any],
    context: dict[str, Any],
    seed_corpus: dict[str, Any] | None = None,
) -> tuple[float, dict[str, Any]]:
    """Compute voice adherence: greeting match (0.4) + sign-off match (0.3) + sentence length (0.3)."""
    derived = _derive_voice_target(scenario, seed_corpus)
    expected_greeting = str(context.get("greeting") or derived["greeting"]).strip().rstrip(",")
    expected_signoff = str(context.get("signoff") or derived["signoff"]).strip()
    target_length = float(context.get("target_sentence_length") or derived["target_sentence_length"] or 16.0)

    score = 0.0
    details: dict[str, Any] = {}

    draft_lines = [line.strip() for line in draft.splitlines() if line.strip()]
    actual_greeting = draft_lines[0].rstrip(",:") if draft_lines else ""

    greeting_match = bool(expected_greeting) and (expected_greeting.lower() == actual_greeting.lower())
    details["expected_greeting"] = expected_greeting
    details["actual_greeting"] = actual_greeting
    details["greeting_match"] = greeting_match
    if greeting_match:
        score += 0.4

    # Extract trailing sign-off block (up to last 3 non-empty lines).
    actual_signoff_lines: list[str] = []
    for idx, line in enumerate(draft_lines[-4:]):
        if _CLOSING_LINE_RE.match(line) or any(
            line.lower().startswith(p)
            for p in ("best", "regards", "thanks", "cheers", "sincerely", "respectfully", "talk soon")
        ):
            actual_signoff_lines = draft_lines[-4 + idx :]
            break
    actual_signoff = "\n".join(actual_signoff_lines).strip()

    signoff_match = False
    if expected_signoff and actual_signoff:
        expected_first = expected_signoff.splitlines()[0].strip().rstrip(",").lower()
        actual_first = actual_signoff.splitlines()[0].strip().rstrip(",").lower()
        if expected_first == actual_first:
            expected_parts = [p.strip().lower() for p in expected_signoff.splitlines() if p.strip()]
            actual_parts = [p.strip().lower() for p in actual_signoff.splitlines() if p.strip()]
            # Exact block match or matching closing phrase + name line.
            signoff_match = (expected_parts == actual_parts) or (
                len(expected_parts) == 1 or len(actual_parts) >= 2 and expected_parts[1] in actual_parts[1]
            )
    details["expected_signoff"] = expected_signoff
    details["actual_signoff"] = actual_signoff
    details["signoff_match"] = signoff_match
    if signoff_match:
        score += 0.3

    # Strip greeting and sign-off lines before computing body sentence length.
    body_lines = list(draft_lines)
    if body_lines and actual_greeting and body_lines[0].rstrip(",:").lower() == actual_greeting.lower():
        body_lines = body_lines[1:]
    if actual_signoff_lines and len(body_lines) >= len(actual_signoff_lines):
        if body_lines[-len(actual_signoff_lines) :] == actual_signoff_lines:
            body_lines = body_lines[: -len(actual_signoff_lines)]

    body_text = "\n".join(body_lines)
    sentences = [s.strip() for s in re.split(r"[.!?]+", body_text) if s.strip()]
    if sentences:
        avg_len = sum(len(s.split()) for s in sentences) / len(sentences)
        deviation = abs(avg_len - target_length) / target_length if target_length > 0 else 1.0
        length_score = max(0.0, 1.0 - deviation)
        score += 0.3 * length_score
        details["target_sentence_length"] = round(target_length, 1)
        details["actual_avg_sentence_length"] = round(avg_len, 1)
        details["length_deviation"] = round(deviation, 3)
    else:
        details["target_sentence_length"] = round(target_length, 1)
        details["actual_avg_sentence_length"] = 0.0
        details["length_deviation"] = 1.0

    return min(1.0, score), details


def _load_human_edits(
    human_edited_path: Path | None,
    blind_key_path: Path | None = None,
) -> dict[tuple[str, str], str]:
    """Load human-edited bodies keyed by (scenario_id, config_name)."""
    if not human_edited_path or not human_edited_path.exists():
        return {}
    human_data = json.loads(human_edited_path.read_text(encoding="utf-8"))
    blind_key: dict[str, dict[str, str]] = {}
    if blind_key_path and blind_key_path.exists():
        blind_key = json.loads(blind_key_path.read_text(encoding="utf-8")).get("mapping", {})
    elif isinstance(human_data.get("blind_key"), dict):
        blind_key = human_data["blind_key"]

    edits: dict[tuple[str, str], str] = {}
    for item in human_data.get("reviews", []):
        edited_body = (item.get("edited_body") or "").strip()
        if not edited_body:
            continue
        sid = item["scenario_id"]
        if "config_name" in item and item["config_name"]:
            edits[(sid, item["config_name"])] = edited_body
        else:
            preferred_label = item.get("preferred_draft", "")
            config_name = blind_key.get(sid, {}).get(preferred_label)
            if config_name:
                edits[(sid, config_name)] = edited_body
    return edits


def compute_metrics(
    run_results_path: Path,
    scenarios_path: Path,
    human_edited_path: Path | None = None,
    seed_corpus_path: Path | None = None,
    blind_key_path: Path | None = None,
) -> list[MetricResult]:
    """Compute all metrics for a run."""
    run_data = json.loads(run_results_path.read_text(encoding="utf-8"))
    scenarios_data = json.loads(scenarios_path.read_text(encoding="utf-8"))
    scenarios = {s["id"]: s for s in scenarios_data["scenarios"]}

    resolved_seed_path = seed_corpus_path or (scenarios_path.parent / "seed_corpus.json")
    seed_corpus = (
        json.loads(resolved_seed_path.read_text(encoding="utf-8"))
        if resolved_seed_path.exists()
        else None
    )

    human_edits = _load_human_edits(human_edited_path, blind_key_path)

    by_scenario = defaultdict(list)
    for r in run_data["results"]:
        by_scenario[r["scenario_id"]].append(r)

    results: list[MetricResult] = []
    for scenario_id, scenario_results in by_scenario.items():
        scenario = scenarios.get(scenario_id, {})
        category = scenario.get("category", "unknown")
        required_facts = scenario.get("required_facts", [])
        forbidden_patterns = scenario.get("forbidden_patterns", [])
        expected_audience = scenario.get("expected_audience", "1on1_private")
        expected_confidence = scenario.get("expected_confidence", "low")

        for r in scenario_results:
            draft = r["draft"]
            context = dict(r.get("resolution_meta", {}))
            context["audience_type"] = r.get("audience_type", "unknown")
            context["confidence_level"] = r.get("confidence_level", "unknown")

            aud_acc, aud_detail = check_audience_accuracy(draft, expected_audience, context)
            conf_acc, conf_detail = check_confidence_accuracy(draft, expected_confidence, context)
            # Check leakage against the scenario's TRUE expected_audience so baselines cannot hide casual leakage.
            leak_count, leak_details = count_leakage_violations(
                draft, forbidden_patterns, expected_audience
            )
            fact_cov, fact_found, fact_missing = compute_factual_coverage(draft, required_facts)
            voice_score, voice_details = compute_voice_adherence(
                draft, scenario, context, seed_corpus=seed_corpus
            )

            edit_dist = None
            if (scenario_id, r["config_name"]) in human_edits:
                edit_dist = normalized_edit_distance(draft, human_edits[(scenario_id, r["config_name"])])

            results.append(
                MetricResult(
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
                )
            )

    return results


def _summarize_bucket(vals: dict[str, list[Any]]) -> dict[str, Any]:
    def mean(lst: list[Any]) -> float:
        return sum(lst) / len(lst) if lst else 0.0

    edits = vals.get("edit_distance", [])
    return {
        "audience_accuracy": round(mean(vals["audience_accuracy"]), 3),
        "confidence_accuracy": round(mean(vals["confidence_accuracy"]), 3),
        "leakage_violations_mean": round(mean(vals["leakage_violations"]), 3),
        "factual_coverage": round(mean(vals["factual_coverage"]), 3),
        "voice_adherence": round(mean(vals["voice_adherence"]), 3),
        "edit_distance_mean": round(mean(edits), 3) if edits else None,
        "count": len(vals["audience_accuracy"]),
    }


def aggregate_metrics(metrics: list[MetricResult]) -> dict[str, Any]:
    """Aggregate metrics by config and category."""
    by_config: dict[str, dict[str, list[Any]]] = defaultdict(lambda: defaultdict(list))
    by_category: dict[str, dict[str, dict[str, list[Any]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(list))
    )

    for m in metrics:
        for bucket in (by_config[m.config_name], by_category[m.category][m.config_name]):
            bucket["audience_accuracy"].append(m.audience_accuracy)
            bucket["confidence_accuracy"].append(m.confidence_accuracy)
            bucket["leakage_violations"].append(m.leakage_violations)
            bucket["factual_coverage"].append(m.factual_coverage)
            bucket["voice_adherence"].append(m.voice_adherence)
            if m.edit_distance is not None:
                bucket["edit_distance"].append(m.edit_distance)

    return {
        "overall": {config: _summarize_bucket(vals) for config, vals in by_config.items()},
        "by_category": {
            cat: {config: _summarize_bucket(vals) for config, vals in configs.items()}
            for cat, configs in by_category.items()
        },
    }


def print_report(agg: dict[str, Any]) -> None:
    """Print formatted metrics report."""
    print("\n" + "=" * 80)
    print("AUTOMATED METRICS REPORT")
    print("=" * 80)

    configs = ["baseline_a", "baseline_b", "proteus"]
    header = f"{'Config':<15} {'Aud.Acc':>8} {'Conf.Acc':>8} {'Leakage':>8} {'FactCov':>8} {'Voice':>8} {'EditDist':>8} {'N':>4}"

    print("\n--- OVERALL ---")
    print(header)
    print("-" * len(header))
    for config in configs:
        if config in agg["overall"]:
            v = agg["overall"][config]
            ed = f"{v['edit_distance_mean']:.3f}" if v["edit_distance_mean"] is not None else "N/A"
            print(
                f"{config:<15} {v['audience_accuracy']:>8.3f} {v['confidence_accuracy']:>8.3f} "
                f"{v['leakage_violations_mean']:>8.3f} {v['factual_coverage']:>8.3f} "
                f"{v['voice_adherence']:>8.3f} {ed:>8} {v['count']:>4}"
            )

    print("\n--- BY CATEGORY ---")
    for cat in sorted(agg["by_category"].keys()):
        print(f"\n{cat}:")
        print(header)
        print("-" * len(header))
        for config in configs:
            if config in agg["by_category"][cat]:
                v = agg["by_category"][cat][config]
                ed = f"{v['edit_distance_mean']:.3f}" if v["edit_distance_mean"] is not None else "N/A"
                print(
                    f"{config:<15} {v['audience_accuracy']:>8.3f} {v['confidence_accuracy']:>8.3f} "
                    f"{v['leakage_violations_mean']:>8.3f} {v['factual_coverage']:>8.3f} "
                    f"{v['voice_adherence']:>8.3f} {ed:>8} {v['count']:>4}"
                )


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute automated metrics for benchmark run")
    parser.add_argument("--run", type=Path, required=True, help="Run results JSON path")
    parser.add_argument("--scenarios", type=Path, default=Path("eval/scenarios.json"), help="Scenarios JSON path")
    parser.add_argument("--seed-corpus", type=Path, help="Seed corpus JSON path")
    parser.add_argument("--human-edited", type=Path, help="Human-edited drafts / completed_review.json path")
    parser.add_argument("--blind-key", type=Path, help="Blind key JSON path (if passing completed_review.json)")
    parser.add_argument("--output", type=Path, help="Output metrics JSON path")
    args = parser.parse_args()

    metrics = compute_metrics(
        args.run,
        args.scenarios,
        human_edited_path=args.human_edited,
        seed_corpus_path=args.seed_corpus,
        blind_key_path=args.blind_key,
    )
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
        args.output.write_text(json.dumps(output_data, indent=2), encoding="utf-8")
        print(f"\nMetrics saved to {args.output}")


if __name__ == "__main__":
    main()
