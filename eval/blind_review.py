#!/usr/bin/env python3
"""
Blind Human Review Generator & Aggregator for 3-Baseline Benchmark.

Supports both flag-style CLI (--export / --score) and subcommands (export / score):
    python -m eval.blind_review --export eval/results/dry_run.json
    python -m eval.blind_review --score eval/results/completed_review.json
    python -m eval.blind_review export --run eval/results/dry_run.json --output-dir eval/results
    python -m eval.blind_review score --review completed_review.json --key eval/results/blind_key.json
"""

from __future__ import annotations

import argparse
import html
import json
import random
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from eval.metrics import normalized_edit_distance

RUBRIC_DIMENSIONS = [
    ("voice_consistency", "Voice Consistency - matches persona style"),
    ("recipient_appropriateness", "Recipient Appropriateness - tone for this person"),
    ("audience_formality", "Audience Formality - correct for To/CC/BCC"),
    ("contextual_relevance", "Contextual Relevance - addresses the task"),
    ("factual_correctness", "Factual Correctness - preserves required facts"),
]
DRAFT_LABELS = ["Draft A", "Draft B", "Draft C"]
CONFIG_NAMES = ["baseline_a", "baseline_b", "proteus"]


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
    drafts: dict[str, str]  # Draft A/B/C -> draft text
    mapping: dict[str, str]  # Draft A/B/C -> config_name


# Self-contained local HTML review page: zero external CDNs, zero embedded blind key.
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
  --hairline: rgba(243,239,230,0.28);
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background: var(--cobalt);
  color: var(--paper);
  line-height: 1.6;
  min-height: 100vh;
  padding: 2rem 1rem;
}}
h1, h2, h3 {{ font-family: Georgia, 'Times New Roman', serif; font-weight: 400; line-height: 1.2; }}
h1 {{ font-size: clamp(2rem, 5vw, 3.2rem); margin-bottom: 0.5rem; }}
h3 {{ font-size: 1.15rem; margin: 1.25rem 0 0.5rem; }}
.container {{ max-width: 960px; margin: 0 auto; }}
.card {{
  background: var(--cobalt-deep);
  border: 1px solid var(--hairline);
  border-radius: 4px;
  padding: 1.5rem;
  margin: 1.5rem 0;
}}
.card-header {{
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 1rem; padding-bottom: 0.5rem; border-bottom: 1px solid var(--hairline);
}}
.scenario-id {{ font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.08em; color: var(--foam); }}
.category {{ font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 0.75rem; background: var(--ink); padding: 0.2rem 0.5rem; border-radius: 3px; }}
.prompt-box {{
  background: var(--ink);
  border: 1px solid var(--hairline);
  border-radius: 3px;
  padding: 1rem;
  margin: 0.75rem 0;
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 0.88rem;
  white-space: pre-wrap;
  overflow-x: auto;
}}
.draft-panel {{
  background: var(--ink);
  border: 1px solid var(--hairline);
  border-radius: 3px;
  padding: 1rem;
  margin: 1rem 0;
}}
.draft-label {{ font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 0.85rem; color: var(--foam); margin-bottom: 0.5rem; font-weight: 600; }}
.draft-content {{ white-space: pre-wrap; line-height: 1.65; margin-bottom: 1rem; padding-bottom: 0.75rem; border-bottom: 1px solid var(--hairline); }}
.rubric {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(175px, 1fr));
  gap: 0.75rem;
}}
.rubric-item {{
  background: rgba(255,255,255,0.04);
  border: 1px solid var(--hairline);
  border-radius: 3px;
  padding: 0.65rem;
}}
.rubric-label {{ font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 0.72rem; color: var(--paper-muted); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.4rem; }}
.rubric-select {{ width: 100%; background: var(--cobalt-deep); border: 1px solid var(--hairline); color: var(--paper); padding: 0.45rem; border-radius: 3px; font-family: inherit; }}
.rubric-select:focus {{ outline: 2px solid var(--foam); border-color: var(--foam); }}
.preferred {{ margin-top: 1.25rem; padding-top: 1rem; border-top: 1px solid var(--hairline); display: flex; flex-wrap: wrap; gap: 1.25rem; align-items: center; }}
.btn {{
  background: var(--cobalt);
  color: var(--paper);
  border: 1px solid var(--foam);
  padding: 0.75rem 1.5rem;
  border-radius: 9999px;
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 0.85rem;
  cursor: pointer;
}}
.btn:hover {{ background: var(--foam); color: var(--ink); }}
.btn:disabled {{ opacity: 0.5; cursor: not-allowed; }}
.btn-primary {{ background: var(--foam); color: var(--ink); }}
.footer {{ margin-top: 3rem; padding-top: 1.5rem; border-top: 1px solid var(--hairline); text-align: center; color: var(--paper-muted); font-size: 0.9rem; }}
.completed {{ border-color: var(--foam) !important; border-width: 2px; }}
</style>
</head>
<body>
<div class="container">
  <header>
    <h1>Proteus Blind Review</h1>
    <p style="color: var(--paper-muted);">Run: {run_id} | {total_scenarios} scenarios | 3 anonymized drafts each</p>
  </header>

  <main id="scenarios">
    {scenario_cards}
  </main>

  <div class="footer">
    <button id="download-btn" class="btn btn-primary" onclick="downloadResults()" disabled>Download Completed Review</button>
    <p style="margin-top: 0.75rem;">Complete all scenarios to enable download (or <button class="btn" style="padding: 0.3rem 0.8rem; font-size: 0.75rem;" onclick="downloadResults(true)">Export Partial</button>)</p>
  </div>
</div>

<script>
const SCENARIOS = {scenarios_json};
const RUN_ID = {run_id_json};

function isCardComplete(card) {{
  const selects = card.querySelectorAll('select');
  for (const s of selects) {{
    if (!s.value) return false;
  }}
  const sid = card.dataset.scenario;
  const preferred = card.querySelector(`input[name="preferred_${{sid}}"]:checked`);
  return Boolean(preferred);
}}

function updateProgress() {{
  const cards = document.querySelectorAll('.scenario-card');
  let completed = 0;
  cards.forEach(card => {{
    const done = isCardComplete(card);
    card.classList.toggle('completed', done);
    if (done) completed++;
  }});
  const btn = document.getElementById('download-btn');
  btn.disabled = completed < SCENARIOS.length;
  btn.textContent = completed === SCENARIOS.length
    ? 'Download Completed Review'
    : `Complete ${{completed}}/${{SCENARIOS.length}} scenarios`;
}}

function getScenarioData(scenarioId) {{
  const card = document.querySelector(`[data-scenario="${{scenarioId}}"]`);
  const scores = {{}};
  card.querySelectorAll('select').forEach(s => {{
    const label = s.dataset.draft;
    const metric = s.dataset.metric;
    if (!scores[label]) scores[label] = {{}};
    if (s.value) scores[label][metric] = parseInt(s.value, 10);
  }});
  const preferred = card.querySelector(`input[name="preferred_${{scenarioId}}"]:checked`);
  const edited = card.querySelector('textarea[name="edited_body"]');
  const data = {{
    scenario_id: scenarioId,
    scores: scores,
    preferred_draft: preferred ? preferred.value : null,
  }};
  if (edited && edited.value.trim()) {{
    data.edited_body = edited.value.trim();
  }}
  return {{ data, complete: isCardComplete(card) }};
}}

function downloadResults(allowPartial = false) {{
  const results = {{ run_id: RUN_ID, reviews: [] }};
  let allComplete = true;
  SCENARIOS.forEach(s => {{
    const {{ data, complete }} = getScenarioData(s.id);
    if (!complete) allComplete = false;
    if (complete || allowPartial) {{
      results.reviews.push(data);
    }}
  }});
  if (!allowPartial && !allComplete) {{
    alert('Please complete all ratings before downloading.');
    return;
  }}
  const blob = new Blob([JSON.stringify(results, null, 2)], {{ type: 'application/json' }});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'completed_review.json';
  a.click();
  URL.revokeObjectURL(url);
}}

document.querySelectorAll('.scenario-card').forEach(card => {{
  card.querySelectorAll('select, input[type="radio"]').forEach(el => {{
    el.addEventListener('change', updateProgress);
  }});
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
    """Export blind review packet: blind_key.json (private), blind_review_sheet.json, blind_review_sheet.html."""
    run_data = json.loads(run_results_path.read_text(encoding="utf-8"))
    scenarios_data = json.loads(scenarios_path.read_text(encoding="utf-8"))
    scenarios = {s["id"]: s for s in scenarios_data["scenarios"]}

    run_id = str(run_data.get("run_id", "unknown"))
    output_dir.mkdir(parents=True, exist_ok=True)

    by_scenario: dict[str, dict[str, str]] = {}
    for r in run_data["results"]:
        by_scenario.setdefault(r["scenario_id"], {})[r["config_name"]] = r["draft"]

    rng = random.Random(seed)
    blind_items: list[BlindReviewItem] = []
    blind_key: dict[str, dict[str, str]] = {}

    for scenario_id, drafts_by_config in by_scenario.items():
        scenario = scenarios[scenario_id]
        for c in CONFIG_NAMES:
            if c not in drafts_by_config:
                drafts_by_config[c] = "[MISSING]"

        paired = [(c, drafts_by_config[c]) for c in CONFIG_NAMES]
        rng.shuffle(paired)

        mapping = {label: config for label, (config, _) in zip(DRAFT_LABELS, paired)}
        draft_dict = {label: draft for label, (_, draft) in zip(DRAFT_LABELS, paired)}
        blind_key[scenario_id] = mapping

        blind_items.append(
            BlindReviewItem(
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
            )
        )

    key_path = output_dir / "blind_key.json"
    key_path.write_text(
        json.dumps({"run_id": run_id, "seed": seed, "mapping": blind_key}, indent=2),
        encoding="utf-8",
    )

    sheet_path = output_dir / "blind_review_sheet.json"
    sheet_path.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "seed": seed,
                "rubric_dimensions": [dim for dim, _ in RUBRIC_DIMENSIONS],
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
                        "scores": {
                            label: {dim: None for dim, _ in RUBRIC_DIMENSIONS}
                            for label in DRAFT_LABELS
                        },
                        "preferred_draft": None,
                        "edited_body": "",
                    }
                    for item in blind_items
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    html_path = output_dir / "blind_review_sheet.html"
    scenario_cards: list[str] = []

    for item in blind_items:
        sid_esc = html.escape(item.scenario_id, quote=True)
        drafts_html = ""
        for label in DRAFT_LABELS:
            rubric_html = ""
            for metric, desc in RUBRIC_DIMENSIONS:
                rubric_html += (
                    f'<div class="rubric-item">'
                    f'<div class="rubric-label">{html.escape(desc)}</div>'
                    f'<select class="rubric-select" data-scenario="{sid_esc}" '
                    f'data-draft="{html.escape(label, quote=True)}" data-metric="{html.escape(metric, quote=True)}">'
                    f'<option value="">-- 1 to 5 --</option>'
                    f'<option value="1">1 - Poor</option>'
                    f'<option value="2">2 - Below Average</option>'
                    f'<option value="3">3 - Acceptable</option>'
                    f'<option value="4">4 - Good</option>'
                    f'<option value="5">5 - Excellent</option>'
                    f"</select></div>"
                )
            drafts_html += (
                f'<div class="draft-panel">'
                f'<div class="draft-label">{html.escape(label)}</div>'
                f'<div class="draft-content">{html.escape(item.drafts[label])}</div>'
                f'<div class="rubric">{rubric_html}</div>'
                f"</div>"
            )

        preferred_html = "".join(
            f'<label style="display:flex;align-items:center;gap:0.4rem;cursor:pointer;">'
            f'<input type="radio" name="preferred_{sid_esc}" value="{html.escape(opt, quote=True)}">'
            f"<span>{html.escape(opt)}</span></label>"
            for opt in [*DRAFT_LABELS, "Tie"]
        )

        context_html = (
            f'<div class="prompt-box"><strong>Incoming Context:</strong>\n{html.escape(item.incoming_context)}</div>'
            if item.incoming_context
            else ""
        )

        card = (
            f'<article class="card scenario-card" data-scenario="{sid_esc}">'
            f'<div class="card-header">'
            f'<span class="scenario-id">{sid_esc}</span>'
            f'<span class="category">{html.escape(item.category)}</span>'
            f"</div>"
            f'<div class="prompt-box"><strong>Task:</strong>\n{html.escape(item.task_prompt)}</div>'
            f"{context_html}"
            f"<h3>Drafts (Anonymous)</h3>"
            f"{drafts_html}"
            f'<div class="preferred">'
            f'<span class="rubric-label" style="margin:0;">Preferred Draft:</span>'
            f"{preferred_html}"
            f"</div>"
            f'<div style="margin-top:1rem;">'
            f'<div class="rubric-label">Edited Version of Preferred Draft (optional, for edit-distance measurement)</div>'
            f'<textarea name="edited_body" class="rubric-select" style="min-height:90px;resize:vertical;" '
            f'data-scenario="{sid_esc}" placeholder="Paste or edit your preferred draft here..."></textarea>'
            f"</div>"
            f'<details style="margin-top:1rem;">'
            f'<summary style="cursor:pointer;color:var(--paper-muted);">Reviewer Notes (click to expand)</summary>'
            f'<div style="margin-top:0.5rem;color:var(--paper-muted);font-size:0.9rem;">{html.escape(item.reviewer_notes)}</div>'
            f"</details>"
            f"</article>"
        )
        scenario_cards.append(card)

    html_content = HTML_TEMPLATE.format(
        run_id=html.escape(run_id),
        run_id_json=json.dumps(run_id),
        total_scenarios=len(blind_items),
        scenario_cards="\n".join(scenario_cards),
        scenarios_json=json.dumps([{"id": item.scenario_id} for item in blind_items]),
    )
    html_path.write_text(html_content, encoding="utf-8")

    print("Exported blind review packet:")
    print(f"  Private key: {key_path}")
    print(f"  Review sheet (JSON): {sheet_path}")
    print(f"  Review sheet (HTML): {html_path}")
    print(f"\nShare {sheet_path.name} and {html_path.name} with reviewers.")
    print(f"KEEP {key_path.name} PRIVATE - do not share!")

    return key_path, sheet_path, html_path


def _extract_draft_scores_by_config(
    review: dict[str, Any],
    mapping: dict[str, str],
    preferred_config: str,
) -> dict[str, dict[str, float]]:
    """Support both per-draft scores ({Draft A: {...}}) and legacy flat scenario ratings."""
    dim_keys = [dim for dim, _ in RUBRIC_DIMENSIONS]
    scores_by_config: dict[str, dict[str, float]] = {}
    raw_scores = review.get("scores")
    if isinstance(raw_scores, dict):
        for label, dim_map in raw_scores.items():
            config = mapping.get(label)
            if not config or not isinstance(dim_map, dict):
                continue
            valid = {k: float(dim_map[k]) for k in dim_keys if dim_map.get(k) is not None}
            if valid:
                scores_by_config[config] = valid
    elif preferred_config in CONFIG_NAMES:
        valid = {k: float(review[k]) for k in dim_keys if review.get(k) is not None}
        if valid:
            scores_by_config[preferred_config] = valid
    return scores_by_config


def _load_original_drafts(
    blind_key_path: Path,
    run_results_path: Path | None = None,
) -> dict[tuple[str, str], str]:
    """Load original drafts keyed by (scenario_id, config_name) from run JSON or blind sheet."""
    drafts: dict[tuple[str, str], str] = {}
    if run_results_path and run_results_path.exists():
        run_data = json.loads(run_results_path.read_text(encoding="utf-8"))
        for r in run_data.get("results", []):
            drafts[(r["scenario_id"], r["config_name"])] = r.get("draft", "")
        return drafts

    sheet_path = blind_key_path.parent / "blind_review_sheet.json"
    key_data = json.loads(blind_key_path.read_text(encoding="utf-8")).get("mapping", {})
    if sheet_path.exists():
        sheet_data = json.loads(sheet_path.read_text(encoding="utf-8"))
        for s in sheet_data.get("scenarios", []):
            sid = s["scenario_id"]
            mapping = key_data.get(sid, {})
            for label, draft_text in s.get("drafts", {}).items():
                config = mapping.get(label)
                if config:
                    drafts[(sid, config)] = draft_text
    return drafts


def score_review(
    completed_review_path: Path,
    blind_key_path: Path,
    metrics_path: Path | None,
    output_path: Path,
    scenarios_path: Path,
    run_results_path: Path | None = None,
) -> Path:
    """Aggregate completed human reviews with blind key + automated metrics -> report.md."""
    completed = json.loads(completed_review_path.read_text(encoding="utf-8"))
    blind_key = json.loads(blind_key_path.read_text(encoding="utf-8"))["mapping"]
    scenarios_data = json.loads(scenarios_path.read_text(encoding="utf-8"))
    scenarios = {s["id"]: s for s in scenarios_data["scenarios"]}

    metrics_data: dict[str, Any] = {}
    if metrics_path and metrics_path.exists():
        metrics_data = json.loads(metrics_path.read_text(encoding="utf-8"))

    original_drafts = _load_original_drafts(blind_key_path, run_results_path)

    human_reviews: dict[str, dict[str, Any]] = {}
    config_dim_scores: dict[str, list[dict[str, float]]] = {c: [] for c in CONFIG_NAMES}
    edit_distances: dict[str, list[float]] = {c: [] for c in CONFIG_NAMES}

    for review in completed.get("reviews", []):
        sid = review["scenario_id"]
        mapping = blind_key.get(sid, {})
        preferred_label = review.get("preferred_draft")
        if preferred_label == "Tie":
            preferred_config = "tie"
        else:
            preferred_config = mapping.get(preferred_label, "unknown")

        per_cfg_scores = _extract_draft_scores_by_config(review, mapping, preferred_config)
        for cfg, dim_map in per_cfg_scores.items():
            if cfg in config_dim_scores:
                config_dim_scores[cfg].append(dim_map)

        edited_body = (review.get("edited_body") or "").strip()
        if edited_body and preferred_config in edit_distances:
            orig = original_drafts.get((sid, preferred_config))
            if orig is not None:
                edit_distances[preferred_config].append(normalized_edit_distance(orig, edited_body))

        human_reviews[sid] = {
            "preferred_draft": preferred_label,
            "preferred_config": preferred_config,
            "scores": per_cfg_scores,
            "edited_body": edited_body,
        }

    run_id = completed.get("run_id", "unknown")
    pref_counts = {"proteus": 0, "baseline_b": 0, "baseline_a": 0, "tie": 0}
    for hr in human_reviews.values():
        cfg = hr["preferred_config"]
        if cfg in pref_counts:
            pref_counts[cfg] += 1

    total_prefs = sum(pref_counts.values())
    report_lines = [
        "# Proteus 3-Baseline Benchmark Report",
        "",
        f"**Run ID:** {run_id}",
        f"**Date:** {datetime.now(timezone.utc).isoformat()}",
        f"**Reviewed Scenarios:** {len(human_reviews)}",
        "",
        "## Overall Win / Tie / Loss Matrix",
        "",
        "| Config | Preferred Count | Win Rate |",
        "|--------|----------------|----------|",
    ]
    for cfg in ("proteus", "baseline_b", "baseline_a", "tie"):
        cnt = pref_counts[cfg]
        rate = cnt / total_prefs if total_prefs > 0 else 0.0
        report_lines.append(f"| {cfg} | {cnt} | {rate:.1%} |")

    # Pairwise Proteus vs Baselines using per-draft scores when available, else preferred counts.
    report_lines.extend(["", "### Pairwise: Proteus vs Baselines", ""])
    report_lines.append("| Comparison | Proteus Wins | Ties | Proteus Losses |")
    report_lines.append("|------------|--------------|------|----------------|")
    for baseline in ("baseline_b", "baseline_a"):
        wins = ties = losses = 0
        for hr in human_reviews.values():
            scores = hr["scores"]
            if "proteus" in scores and baseline in scores:
                p_avg = sum(scores["proteus"].values()) / len(scores["proteus"])
                b_avg = sum(scores[baseline].values()) / len(scores[baseline])
                if abs(p_avg - b_avg) < 1e-9:
                    ties += 1
                elif p_avg > b_avg:
                    wins += 1
                else:
                    losses += 1
            else:
                if hr["preferred_config"] == "proteus":
                    wins += 1
                elif hr["preferred_config"] == baseline:
                    losses += 1
                elif hr["preferred_config"] == "tie":
                    ties += 1
        report_lines.append(f"| proteus vs {baseline} | {wins} | {ties} | {losses} |")

    report_lines.extend(
        [
            "",
            "## Mean Human Scores (1-5)",
            "",
            "| Config | Voice | Recipient | Audience | Context | Factual | Overall | N |",
            "|--------|-------|-----------|----------|---------|---------|---------|---|",
        ]
    )
    for cfg in ("proteus", "baseline_b", "baseline_a"):
        items = config_dim_scores[cfg]
        if items:
            avgs = []
            for dim, _ in RUBRIC_DIMENSIONS:
                vals = [d[dim] for d in items if dim in d]
                avgs.append(sum(vals) / len(vals) if vals else 0.0)
            overall = sum(avgs) / len(avgs)
            report_lines.append(
                f"| {cfg} | {avgs[0]:.2f} | {avgs[1]:.2f} | {avgs[2]:.2f} | "
                f"{avgs[3]:.2f} | {avgs[4]:.2f} | {overall:.2f} | {len(items)} |"
            )
        else:
            report_lines.append(f"| {cfg} | N/A | N/A | N/A | N/A | N/A | N/A | 0 |")

    report_lines.extend(
        [
            "",
            "## Mean Human Edit Distance (Normalized Levenshtein, 0.0 = zero edits)",
            "",
            "| Config | Mean Edit Distance | Edited Count |",
            "|--------|-------------------|--------------|",
        ]
    )
    for cfg in ("proteus", "baseline_b", "baseline_a"):
        dists = edit_distances[cfg]
        if dists:
            report_lines.append(f"| {cfg} | {sum(dists) / len(dists):.3f} | {len(dists)} |")
        else:
            report_lines.append(f"| {cfg} | N/A | 0 |")

    if "aggregated" in metrics_data and metrics_data["aggregated"].get("overall"):
        overall_auto = metrics_data["aggregated"]["overall"]
        report_lines.extend(
            [
                "",
                "## Automated Metrics Summary",
                "",
                "| Config | Aud.Acc | Conf.Acc | Leakage | FactCov | Voice |",
                "|--------|---------|----------|---------|---------|-------|",
            ]
        )
        for cfg in ("proteus", "baseline_b", "baseline_a"):
            if cfg in overall_auto:
                v = overall_auto[cfg]
                report_lines.append(
                    f"| {cfg} | {v['audience_accuracy']:.3f} | {v['confidence_accuracy']:.3f} | "
                    f"{v['leakage_violations_mean']:.3f} | {v['factual_coverage']:.3f} | {v['voice_adherence']:.3f} |"
                )

    report_lines.extend(["", "## Per-Category Breakdown", ""])
    by_cat_auto = metrics_data.get("aggregated", {}).get("by_category", {})
    categories = sorted(set(s["category"] for s in scenarios.values()))
    for cat in categories:
        cat_scenarios = [s for s in scenarios.values() if s["category"] == cat]
        cat_prefs = {"proteus": 0, "baseline_b": 0, "baseline_a": 0, "tie": 0}
        for s in cat_scenarios:
            if s["id"] in human_reviews:
                c = human_reviews[s["id"]]["preferred_config"]
                if c in cat_prefs:
                    cat_prefs[c] += 1

        report_lines.append(f"### {cat} ({len(cat_scenarios)} scenarios)")
        report_lines.append("")
        report_lines.append("| Config | Preferred | Aud.Acc | Conf.Acc | Leakage | FactCov | Voice |")
        report_lines.append("|--------|-----------|---------|----------|---------|---------|-------|")
        for cfg in ("proteus", "baseline_b", "baseline_a"):
            auto = by_cat_auto.get(cat, {}).get(cfg)
            if auto:
                report_lines.append(
                    f"| {cfg} | {cat_prefs[cfg]} | {auto['audience_accuracy']:.3f} | "
                    f"{auto['confidence_accuracy']:.3f} | {auto['leakage_violations_mean']:.3f} | "
                    f"{auto['factual_coverage']:.3f} | {auto['voice_adherence']:.3f} |"
                )
            else:
                report_lines.append(f"| {cfg} | {cat_prefs[cfg]} | N/A | N/A | N/A | N/A | N/A |")
        report_lines.append("")

    report_lines.extend(["## Where Proteus Wins", ""])
    proteus_wins = [sid for sid, hr in human_reviews.items() if hr["preferred_config"] == "proteus"]
    if proteus_wins:
        for sid in proteus_wins:
            s = scenarios.get(sid, {})
            report_lines.append(f"- **{sid}** ({s.get('category', 'unknown')}): {s.get('reviewer_notes', '')}")
    else:
        report_lines.append("- None recorded in this review.")

    report_lines.extend(["", "## Where Proteus Fails", ""])
    proteus_losses = [sid for sid, hr in human_reviews.items() if hr["preferred_config"] != "proteus"]
    if proteus_losses:
        for sid in proteus_losses:
            s = scenarios.get(sid, {})
            winner = human_reviews[sid]["preferred_config"]
            report_lines.append(
                f"- **{sid}** ({s.get('category', 'unknown')}): Outcome `{winner}` - {s.get('reviewer_notes', '')}"
            )
    else:
        report_lines.append("- No human-preference losses recorded in this review.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    print(f"Report written to {output_path}")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Blind Review Generator & Aggregator")
    # Flag-style CLI matching original spec (--export / --score)
    parser.add_argument("--export", type=Path, help="Run results JSON to export as blind review packet")
    parser.add_argument("--score", type=Path, help="Completed review JSON to score into report.md")
    parser.add_argument("--scenarios", type=Path, default=Path("eval/scenarios.json"), help="Scenarios JSON")
    parser.add_argument("--output-dir", type=Path, default=Path("eval/results"), help="Export output directory")
    parser.add_argument("--seed", type=int, default=42, help="Shuffle seed")
    parser.add_argument("--key", type=Path, help="Blind key JSON path (defaults to <review_dir>/blind_key.json or eval/results/blind_key.json)")
    parser.add_argument("--metrics", type=Path, help="Automated metrics JSON path")
    parser.add_argument("--run", type=Path, help="Original run results JSON path (for edit distance)")
    parser.add_argument("--output", type=Path, default=Path("eval/results/report.md"), help="Output report.md path")

    subparsers = parser.add_subparsers(dest="command")
    export_parser = subparsers.add_parser("export", help="Export blind review packet")
    export_parser.add_argument("--run", type=Path, required=True, help="Run results JSON")
    export_parser.add_argument("--scenarios", type=Path, default=Path("eval/scenarios.json"), help="Scenarios JSON")
    export_parser.add_argument("--output-dir", type=Path, default=Path("eval/results"), help="Output directory")
    export_parser.add_argument("--seed", type=int, default=42, help="Shuffle seed")

    score_parser = subparsers.add_parser("score", help="Score completed review")
    score_parser.add_argument("--review", type=Path, required=True, help="Completed review JSON")
    score_parser.add_argument("--key", type=Path, required=True, help="Blind key JSON")
    score_parser.add_argument("--metrics", type=Path, help="Automated metrics JSON")
    score_parser.add_argument("--run", type=Path, help="Original run results JSON (for edit distance)")
    score_parser.add_argument("--output", type=Path, default=Path("eval/results/report.md"), help="Output report path")
    score_parser.add_argument("--scenarios", type=Path, default=Path("eval/scenarios.json"), help="Scenarios JSON")

    args = parser.parse_args()

    if args.command == "export":
        export_blind_review(args.run, args.scenarios, args.output_dir, args.seed)
    elif args.command == "score":
        score_review(args.review, args.key, args.metrics, args.output, args.scenarios, args.run)
    elif args.export:
        export_blind_review(args.export, args.scenarios, args.output_dir, args.seed)
    elif args.score:
        key_path = args.key
        if not key_path:
            candidate = args.score.parent / "blind_key.json"
            key_path = candidate if candidate.exists() else Path("eval/results/blind_key.json")
        metrics_path = args.metrics
        if not metrics_path:
            candidate_m = key_path.parent / "metrics.json"
            if candidate_m.exists():
                metrics_path = candidate_m
        score_review(args.score, key_path, metrics_path, args.output, args.scenarios, args.run)
    else:
        parser.error("Provide --export PATH, --score PATH, or a subcommand (export / score).")


if __name__ == "__main__":
    main()
