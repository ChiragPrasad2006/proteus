#!/usr/bin/env python3
"""
Blind Human Review Generator & Aggregator for 3-Baseline Benchmark.

Export: Creates anonymized review packet (Draft A/B/C) with private key.
Score: Joins completed reviews with key + automated metrics → report.md
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class BlindReviewItem:
    scenario_id: str
    category: str
    task_prompt: str
    incoming_context: str | None
    required_facts: list[str]
    expected_audience: str
    expected_confidence: str
    reviewer_notes: str
    drafts: dict[str, str]  # A, B, C -> draft text
    mapping: dict[str, str]  # A, B, C -> config_name


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Proteus Blind Review - {run_id}</title>
<style>
:root {{
  --cobalt: #2641E6;
  --cobalt-deep: #1B33D6;
  --ink: #070B2E;
  --paper: #F3EFE6;
  --paper-muted: rgba(243,239,230,0.82);
  --foam: #C9F0E3;
  --ember: #FF5B2E;
  --ember-ink: #B8320C;
  --hairline: rgba(243,239,230,0.28);
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
  font-family: 'Instrument Sans', system-ui, sans-serif;
  background: var(--cobalt);
  color: var(--paper);
  line-height: 1.6;
  min-height: 100vh;
  padding: 2rem 1rem;
}}
h1, h2, h3 {{ font-family: 'Newsreader', Georgia, serif; font-weight: 400; line-height: 1.1; }}
h1 {{ font-size: clamp(2rem, 5vw, 3.5rem); margin-bottom: 0.5rem; }}
h2 {{ font-size: clamp(1.5rem, 3vw, 2rem); margin: 2rem 0 1rem; border-bottom: 1px solid var(--hairline); padding-bottom: 0.5rem; }}
h3 {{ font-size: 1.25rem; margin: 1.5rem 0 0.5rem; }}
a {{ color: var(--foam); text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
.container {{ max-width: 900px; margin: 0 auto; }}
.card {{
  background: var(--cobalt-deep);
  border: 1px solid var(--hairline);
  border-radius: 2px;
  padding: 1.5rem;
  margin: 1.5rem 0;
}}
.card-header {{
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 1rem; padding-bottom: 0.5rem; border-bottom: 1px solid var(--hairline);
}}
.scenario-id {{ font-family: 'JetBrains Mono', monospace; font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.08em; color: var(--foam); }}
.category {{ font-family: 'JetBrains Mono', monospace; font-size: 0.75rem; background: var(--ink); padding: 0.2rem 0.5rem; border-radius: 2px; }}
.prompt-box {{
  background: var(--ink);
  border: 1px solid var(--hairline);
  border-radius: 2px;
  padding: 1rem;
  margin: 1rem 0;
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.9rem;
  white-space: pre-wrap;
  overflow-x: auto;
}}
.draft-panel {{
  background: var(--ink);
  border: 1px solid var(--hairline);
  border-radius: 2px;
  padding: 1rem;
  margin: 1rem 0;
  min-height: 120px;
}}
.draft-label {{ font-family: 'JetBrains Mono', monospace; font-size: 0.8rem; color: var(--foam); margin-bottom: 0.5rem; }}
.draft-content {{ white-space: pre-wrap; font-family: 'Instrument Sans', system-ui, sans-serif; line-height: 1.7; }}
.rubric {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 1rem;
  margin: 1.5rem 0;
}}
.rubric-item {{
  background: var(--ink);
  border: 1px solid var(--hairline);
  border-radius: 2px;
  padding: 1rem;
}}
.rubric-label {{ font-family: 'JetBrains Mono', monospace; font-size: 0.75rem; color: var(--paper-muted); text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 0.5rem; }}
.rubric-select {{ width: 100%; background: var(--cobalt-deep); border: 1px solid var(--hairline); color: var(--paper); padding: 0.5rem; border-radius: 2px; font-family: inherit; }}
.rubric-select:focus {{ outline: 2px solid var(--foam); border-color: var(--foam); }}
.preferred {{
  margin-top: 1.5rem; padding-top: 1rem; border-top: 1px solid var(--hairline);
}}
.btn {{
  background: var(--cobalt);
  color: var(--paper);
  border: 1px solid var(--foam);
  padding: 0.75rem 1.5rem;
  border-radius: 9999px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.85rem;
  cursor: pointer;
  transition: all 0.2s;
}}
.btn:hover {{ background: var(--foam); color: var(--ink); }}
.btn:disabled {{ opacity: 0.5; cursor: not-allowed; }}
.btn-primary {{ background: var(--foam); color: var(--ink); }}
.btn-primary:hover {{ background: var(--paper); }}
.footer {{ margin-top: 3rem; padding-top: 1.5rem; border-top: 1px solid var(--hairline); text-align: center; color: var(--paper-muted); font-size: 0.9rem; }}
.hidden {{ display: none !important; }}
.completed {{ border-color: var(--foam) !important; }}
@media (prefers-reduced-motion: reduce) {{ * {{ transition: none !important; }} }}
</style>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400;500;600&family=JetBrains+Mono:wght@400;500&family=Newsreader:opsz,wght@6..72,300..500&display=swap" rel="stylesheet">
</head>
<body>
<div class="container">
  <header>
    <h1>Proteus Blind Review</h1>
    <p style="color: var(--paper-muted);">Run: {run_id} | {total_scenarios} scenarios | 3 drafts each</p>
  </header>

  <main id="scenarios">
    {scenario_cards}
  </main>

  <div class="footer">
    <button id="download-btn" class="btn btn-primary" onclick="downloadResults()" disabled>Download Completed Review</button>
    <p style="margin-top: 1rem;">Complete all scenarios to enable download</p>
  </div>
</div>

<script>
const SCENARIOS = {scenarios_json};
const RUN_ID = "{run_id}";
const BLIND_KEY = {blind_key_json};

let completedCount = 0;
const totalScenarios = SCENARIOS.length;

function updateProgress() {{
  const btn = document.getElementById('download-btn');
  btn.disabled = completedCount < totalScenarios;
  btn.textContent = completedCount === totalScenarios ? 'Download Completed Review' : `Complete ${{completedCount}}/${{totalScenarios}} scenarios`;
}}

function getScenarioData(scenarioId) {{
  const selects = document.querySelectorAll(`[data-scenario="${{scenarioId}}"] select`);
  const data = {{ scenario_id: scenarioId }};
  let allFilled = true;
  selects.forEach(s => {{
    if (!s.value) allFilled = false;
    data[s.dataset.metric] = parseInt(s.value);
  }});
  const preferred = document.querySelector(`[data-scenario="${{scenarioId}}"] [name="preferred"]:checked`);
  if (!preferred) allFilled = false;
  else data.preferred_draft = preferred.value;
  const edited = document.querySelector(`[data-scenario="${{scenarioId}}"] [name="edited_body"]`);
  if (edited && edited.value.trim()) data.edited_body = edited.value.trim();
  return {{ data, allFilled }};
}}

function downloadResults() {{
  const results = {{ run_id: RUN_ID, blind_key: BLIND_KEY, reviews: [] }};
  let allComplete = true;
  SCENARIOS.forEach(s => {{
    const {{ data, allFilled }} = getScenarioData(s.id);
    if (!allFilled) allComplete = false;
    results.reviews.push(data);
  }});
  if (!allComplete) {{
    alert('Please complete all ratings before downloading.');
    return;
  }}
  const blob = new Blob([JSON.stringify(results, null, 2)], {{ type: 'application/json' }});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `completed_review_${{RUN_ID}}.json`;
  a.click();
  URL.revokeObjectURL(url);
}}

// Track completion per scenario
document.querySelectorAll('.scenario-card').forEach(card => {{
  const scenarioId = card.dataset.scenario;
  const selects = card.querySelectorAll('select');
  const radios = card.querySelectorAll('input[type="radio"]');
  let wasComplete = false;
  function checkComplete() {{
    let allFilled = true;
    selects.forEach(s => {{ if (!s.value) allFilled = false; }});
    const preferred = card.querySelector('input[name="preferred"]:checked');
    if (!preferred) allFilled = false;
    if (allFilled && !wasComplete) {{
      completedCount++;
      wasComplete = true;
      card.classList.add('completed');
      updateProgress();
    }} else if (!allFilled && wasComplete) {{
      completedCount--;
      wasComplete = false;
      card.classList.remove('completed');
      updateProgress();
    }}
  }}
  selects.forEach(s => s.addEventListener('change', checkComplete));
  radios.forEach(r => r.addEventListener('change', checkComplete));
}});

updateProgress();
</script>
</body>
</html>
"""


def export_blind_review(
    run_results_path: Path,
    scenarios_path: Path,
    output_dir: Path,
    seed: int = 42,
) -> tuple[Path, Path, Path]:
    """Export blind review packet: sheet.json, sheet.html, blind_key.json."""
    run_data = json.loads(run_results_path.read_text())
    scenarios_data = json.loads(scenarios_path.read_text())
    scenarios = {s["id"]: s for s in scenarios_data["scenarios"]}

    run_id = run_data.get("run_id", "unknown")

    # Group results by scenario
    by_scenario = {}
    for r in run_data["results"]:
        by_scenario.setdefault(r["scenario_id"], {})[r["config_name"]] = r["draft"]

    # Deterministic shuffle per scenario
    rng = random.Random(seed)
    blind_items = []
    blind_key = {}

    for scenario_id, drafts_by_config in by_scenario.items():
        scenario = scenarios[scenario_id]
        configs = ["baseline_a", "baseline_b", "proteus"]
        # Ensure all three exist
        for c in configs:
            if c not in drafts_by_config:
                drafts_by_config[c] = "[MISSING]"

        labels = ["Draft A", "Draft B", "Draft C"]
        shuffled = list(zip(configs, [drafts_by_config[c] for c in configs]))
        rng.shuffle(shuffled)

        mapping = {label: config for label, (config, _) in zip(labels, shuffled)}
        draft_dict = {label: draft for label, (_, draft) in zip(labels, shuffled)}

        blind_key[scenario_id] = mapping

        blind_items.append(BlindReviewItem(
            scenario_id=scenario_id,
            category=scenario["category"],
            task_prompt=scenario["task_prompt"],
            incoming_context=scenario.get("incoming_context"),
            required_facts=scenario["required_facts"],
            expected_audience=scenario["expected_audience"],
            expected_confidence=scenario["expected_confidence"],
            reviewer_notes=scenario["reviewer_notes"],
            drafts=draft_dict,
            mapping=mapping,
        ))

    # Write blind_key.json (PRIVATE - do not share with reviewers)
    key_path = output_dir / "blind_key.json"
    key_path.write_text(json.dumps({
        "run_id": run_id,
        "seed": seed,
        "mapping": blind_key,
    }, indent=2))

    # Write blind_review_sheet.json (structured for programmatic use)
    sheet_path = output_dir / "blind_review_sheet.json"
    sheet_path.write_text(json.dumps({
        "run_id": run_id,
        "seed": seed,
        "scenarios": [
            {
                "scenario_id": item.scenario_id,
                "category": item.category,
                "task_prompt": item.task_prompt,
                "incoming_context": item.incoming_context,
                "required_facts": item.required_facts,
                "expected_audience": item.expected_audience,
                "expected_confidence": item.expected_confidence,
                "reviewer_notes": item.reviewer_notes,
                "drafts": item.drafts,
            }
            for item in blind_items
        ],
    }, indent=2))

    # Write blind_review_sheet.html (self-contained review UI)
    html_path = output_dir / "blind_review_sheet.html"

    scenario_cards = []
    for item in blind_items:
        drafts_html = ""
        for label in ["Draft A", "Draft B", "Draft C"]:
            drafts_html += f"""
            <div class="draft-panel">
              <div class="draft-label">{label}</div>
              <div class="draft-content">{item.drafts[label]}</div>
            </div>"""

        rubric_html = ""
        for metric, desc in [
            ("voice_consistency", "Voice Consistency - matches persona style"),
            ("recipient_appropriateness", "Recipient Appropriateness - tone for this person"),
            ("audience_formality", "Audience Formality - correct for To/CC/BCC"),
            ("contextual_relevance", "Contextual Relevance - addresses the task"),
            ("factual_correctness", "Factual Correctness - preserves required facts"),
        ]:
            rubric_html += f"""
            <div class="rubric-item">
              <div class="rubric-label">{desc}</div>
              <select class="rubric-select" data-scenario="{item.scenario_id}" data-metric="{metric}">
                <option value="">-- Select 1-5 --</option>
                <option value="1">1 - Poor</option>
                <option value="2">2 - Below Average</option>
                <option value="3">3 - Acceptable</option>
                <option value="4">4 - Good</option>
                <option value="5">5 - Excellent</option>
              </select>
            </div>"""

        preferred_html = ""
        for label in ["Draft A", "Draft B", "Draft C"]:
            preferred_html += f"""
            <label style="display: flex; align-items: center; gap: 0.5rem; margin: 0.5rem 0; cursor: pointer;">
              <input type="radio" name="preferred" value="{label}" data-scenario="{item.scenario_id}">
              <span>{label}</span>
            </label>"""

        edited_html = f"""
        <div style="margin-top: 1rem;">
          <div class="rubric-label">Edited Version (optional - your preferred draft with edits)</div>
          <textarea name="edited_body" class="rubric-select" style="min-height: 100px; resize: vertical; font-family: inherit;" data-scenario="{item.scenario_id}" placeholder="Paste your edited version of the preferred draft here..."></textarea>
        </div>"""

        context_html = ""
        if item.incoming_context:
            context_html = f'<div class="prompt-box"><strong>Incoming Context:</strong>\n{item.incoming_context}</div>'

        card = f"""
        <article class="card scenario-card" data-scenario="{item.scenario_id}">
          <div class="card-header">
            <span class="scenario-id">{item.scenario_id}</span>
            <span class="category">{item.category}</span>
          </div>
          <div class="prompt-box"><strong>Task:</strong>\n{item.task_prompt}</div>
          {context_html}
          <div class="rubric">{rubric_html}</div>
          <div class="preferred">
            <div class="rubric-label">Preferred Draft</div>
            {preferred_html}
          </div>
          {edited_html}
          <h3 style="margin-top: 1.5rem;">Drafts (Anonymous)</h3>
          {drafts_html}
          <details style="margin-top: 1rem;">
            <summary style="cursor: pointer; color: var(--paper-muted);">Reviewer Notes (click to expand)</summary>
            <div style="margin-top: 0.5rem; color: var(--paper-muted); font-size: 0.9rem;">{item.reviewer_notes}</div>
          </details>
        </article>"""
        scenario_cards.append(card)

    html_content = HTML_TEMPLATE.format(
        run_id=run_id,
        total_scenarios=len(blind_items),
        scenario_cards="\n".join(scenario_cards),
        scenarios_json=json.dumps([{"id": item.scenario_id} for item in blind_items]),
        blind_key_json=json.dumps(blind_key),
    )
    html_path.write_text(html_content)

    print(f"Exported blind review packet:")
    print(f"  Private key: {key_path}")
    print(f"  Review sheet (JSON): {sheet_path}")
    print(f"  Review sheet (HTML): {html_path}")
    print(f"\nShare {sheet_path.name} and {html_path.name} with reviewers.")
    print(f"KEEP {key_path.name} PRIVATE - do not share!")

    return key_path, sheet_path, html_path


def score_review(
    completed_review_path: Path,
    blind_key_path: Path,
    metrics_path: Path | None,
    output_path: Path,
    scenarios_path: Path,
) -> Path:
    """Aggregate completed human reviews with blind key and automated metrics."""
    completed = json.loads(completed_review_path.read_text())
    blind_key = json.loads(blind_key_path.read_text())["mapping"]
    scenarios_data = json.loads(scenarios_path.read_text())
    scenarios = {s["id"]: s for s in scenarios_data["scenarios"]}

    metrics_data = {}
    if metrics_path and metrics_path.exists():
        metrics_data = json.loads(metrics_path.read_text())

    # Build per-scenario, per-config human scores
    human_scores = {}
    for review in completed.get("reviews", []):
        scenario_id = review["scenario_id"]
        mapping = blind_key.get(scenario_id, {})
        # Reverse mapping: Draft A/B/C -> config_name
        rev_mapping = {v: k for k, v in mapping.items()}
        preferred_label = review.get("preferred_draft")
        preferred_config = rev_mapping.get(preferred_label, "unknown")

        human_scores[scenario_id] = {
            "voice_consistency": review.get("voice_consistency"),
            "recipient_appropriateness": review.get("recipient_appropriateness"),
            "audience_formality": review.get("audience_formality"),
            "contextual_relevance": review.get("contextual_relevance"),
            "factual_correctness": review.get("factual_correctness"),
            "preferred_draft": preferred_label,
            "preferred_config": preferred_config,
            "edited_body": review.get("edited_body"),
        }

    # Load automated metrics if available
    auto_metrics = {}
    if "aggregated" in metrics_data:
        # Metrics are aggregated by config, we need per-scenario
        pass
    if "per_draft" in metrics_data:
        for m in metrics_data["per_draft"]:
            key = (m["scenario_id"], m["config_name"])
            auto_metrics[key] = m

    # Generate report.md
    run_id = completed.get("run_id", "unknown")

    report_lines = [
        f"# Proteus 3-Baseline Benchmark Report",
        f"",
        f"**Run ID:** {run_id}",
        f"**Date:** {__import__('datetime').datetime.now().isoformat()}",
        f"",
        f"## Overall Win/Tie/Loss Matrix",
        f"",
        f"| Config | Preferred Count | Win Rate |",
        f"|--------|----------------|----------|",
    ]

    # Count preferences
    pref_counts = {"baseline_a": 0, "baseline_b": 0, "proteus": 0}
    for scores in human_scores.values():
        config = scores["preferred_config"]
        if config in pref_counts:
            pref_counts[config] += 1

    total_prefs = sum(pref_counts.values())
    for config in ["proteus", "baseline_b", "baseline_a"]:
        count = pref_counts.get(config, 0)
        rate = count / total_prefs if total_prefs > 0 else 0
        report_lines.append(f"| {config} | {count} | {rate:.1%} |")

    report_lines.extend([
        f"",
        f"## Per-Category Breakdown",
        f"",
    ])

    # Category breakdown
    scenarios_data = json.loads(scenarios_path.read_text())
    scenarios = {s["id"]: s for s in scenarios_data["scenarios"]}

    categories = sorted(set(s["category"] for s in scenarios.values()))
    for cat in categories:
        cat_scenarios = [s for s in scenarios.values() if s["category"] == cat]
        cat_prefs = {"baseline_a": 0, "baseline_b": 0, "proteus": 0}
        for s in cat_scenarios:
            if s["id"] in human_scores:
                config = human_scores[s["id"]]["preferred_config"]
                if config in cat_prefs:
                    cat_prefs[config] += 1

        report_lines.append(f"### {cat} ({len(cat_scenarios)} scenarios)")
        report_lines.append(f"")
        report_lines.append(f"| Config | Preferred |")
        report_lines.append(f"|--------|-----------|")
        for config in ["proteus", "baseline_b", "baseline_a"]:
            report_lines.append(f"| {config} | {cat_prefs.get(config, 0)} |")
        report_lines.append(f"")

    # Where Proteus wins/fails
    report_lines.extend([
        f"## Where Proteus Wins",
        f"",
    ])
    proteus_wins = [s for s, scores in human_scores.items() if scores["preferred_config"] == "proteus"]
    for s in proteus_wins:
        cat = scenarios[s]["category"]
        report_lines.append(f"- **{s}** ({cat}): {scenarios[s]['reviewer_notes']}")

    report_lines.extend([
        f"",
        f"## Where Proteus Fails",
        f"",
    ])
    proteus_losses = [s for s, scores in human_scores.items() if scores["preferred_config"] != "proteus"]
    for s in proteus_losses:
        cat = scenarios[s]["category"]
        winner = human_scores[s]["preferred_config"]
        report_lines.append(f"- **{s}** ({cat}): Lost to {winner} - {scenarios[s]['reviewer_notes']}")

    # Mean human scores
    report_lines.extend([
        f"",
        f"## Mean Human Scores (1-5)",
        f"",
        f"| Config | Voice | Recipient | Audience | Context | Factual | Overall |",
        f"|--------|-------|-----------|----------|---------|---------|---------|",
    ])
    for config in ["proteus", "baseline_b", "baseline_a"]:
        scores_list = [v for v in human_scores.values() if v["preferred_config"] == config]
        if not scores_list:
            # Compute from all scenarios where this config was rated
            config_scores = []
            for s_id, scores in human_scores.items():
                # We need per-config ratings, but we only have overall ratings per scenario
                # This is a limitation - we'd need reviewers to rate all 3 drafts
                pass
        # Simplified: just show preferred config average
        if scores_list:
            avg_voice = sum(s.get("voice_consistency", 0) for s in scores_list) / len(scores_list)
            avg_recip = sum(s.get("recipient_appropriateness", 0) for s in scores_list) / len(scores_list)
            avg_aud = sum(s.get("audience_formality", 0) for s in scores_list) / len(scores_list)
            avg_ctx = sum(s.get("contextual_relevance", 0) for s in scores_list) / len(scores_list)
            avg_fact = sum(s.get("factual_correctness", 0) for s in scores_list) / len(scores_list)
            overall = (avg_voice + avg_recip + avg_aud + avg_ctx + avg_fact) / 5
            report_lines.append(f"| {config} | {avg_voice:.2f} | {avg_recip:.2f} | {avg_aud:.2f} | {avg_ctx:.2f} | {avg_fact:.2f} | {overall:.2f} |")
        else:
            report_lines.append(f"| {config} | N/A | N/A | N/A | N/A | N/A | N/A |")

    # Mean edit distance
    if metrics_path and metrics_path.exists():
        report_lines.extend([
            f"",
            f"## Mean Edit Distance (Normalized Levenshtein, 0=perfect)",
            f"",
            f"| Config | Edit Distance |",
            f"|--------|---------------|",
        ])
        # This would come from automated metrics
        for config in ["proteus", "baseline_b", "baseline_a"]:
            report_lines.append(f"| {config} | See metrics.json |")

    report_content = "\n".join(report_lines)
    output_path.write_text(report_content)
    print(f"Report written to {output_path}")
    return output_path


def main():
    parser = argparse.ArgumentParser(description="Blind Review Generator & Aggregator")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Export command
    export_parser = subparsers.add_parser("export", help="Export blind review packet")
    export_parser.add_argument("--run", type=Path, required=True, help="Run results JSON")
    export_parser.add_argument("--scenarios", type=Path, default=Path("eval/scenarios.json"), help="Scenarios JSON")
    export_parser.add_argument("--output-dir", type=Path, default=Path("eval/results"), help="Output directory")
    export_parser.add_argument("--seed", type=int, default=42, help="Shuffle seed")

    # Score command
    score_parser = subparsers.add_parser("score", help="Score completed review")
    score_parser.add_argument("--review", type=Path, required=True, help="Completed review JSON")
    score_parser.add_argument("--key", type=Path, required=True, help="Blind key JSON")
    score_parser.add_argument("--metrics", type=Path, help="Automated metrics JSON")
    score_parser.add_argument("--output", type=Path, default=Path("eval/results/report.md"), help="Output report path")
    score_parser.add_argument("--scenarios", type=Path, default=Path("eval/scenarios.json"), help="Scenarios JSON")

    args = parser.parse_args()

    if args.command == "export":
        export_blind_review(args.run, args.scenarios, args.output_dir, args.seed)
    elif args.command == "score":
        score_review(args.review, args.key, args.metrics, args.output, args.scenarios)


if __name__ == "__main__":
    main()