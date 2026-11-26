#!/usr/bin/env python3
"""
3-Baseline Personalization Benchmark Harness (Priority 2).

Evaluates Proteus's recipient-conditioned memory, deterministic policy resolver
(Priority 0), and confidence-aware fallback (Priority 1) against simpler baselines.

Usage:
    python -m eval.runner --mode dry-run --output eval/results/run_latest.json
    python -m eval.runner --mode live --output eval/results/run_latest.json
    python -m eval.runner --mode live --resume --output eval/results/run_latest.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.config import Settings
from backend.generation.context_resolver import classify_audience, resolve_draft_context
from backend.generation.drafter import QwenDrafter
from backend.retrieval import LanceDBVectorStore, LocalEmbedder
from backend.schemas import (
    CleanedSentEmail,
    CorpusStatistics,
    GlobalStyleCard,
    RecipientProfile,
    StylometryMetrics,
    UserStyleProfile,
)
from backend.storage import ProfileStore

# Strict experimental controls shared across all 3 arms in live mode.
CONTROL_MODEL = "qwen3:8b"
CONTROL_TEMPERATURE = 0.2
CONTROL_SEED = 42
CONTROL_NUM_PREDICT = 512
CONTROL_THINK = False


@dataclass
class Scenario:
    id: str
    category: str
    to: list[str]
    cc: list[str]
    bcc: list[str]
    task_prompt: str
    incoming_context: str | None
    required_facts: list[str]
    expected_audience: str
    expected_confidence: str
    forbidden_patterns: list[str]
    reviewer_notes: str


@dataclass
class DraftResult:
    scenario_id: str
    config_name: str
    draft: str
    audience_type: str
    confidence_level: str
    resolution_meta: dict[str, Any]
    latency_ms: float
    timestamp: str


@dataclass
class RunResult:
    run_id: str
    started_at: str
    completed_at: str | None
    mode: str
    results: list[DraftResult] = field(default_factory=list)


def _extract_prompt_field(system_prompt: str, prefix: str) -> str:
    """Extract a single-line field value from a formatted system prompt."""
    for line in system_prompt.splitlines():
        if prefix in line:
            return line.split(prefix, 1)[1].strip()
    return ""


def _extract_signoff(system_prompt: str) -> str:
    """Extract a single- or multi-line sign-off from a system prompt."""
    lines = system_prompt.splitlines()
    stop_prefixes = (
        "Target sentence length:",
        "Policy directives",
        "Active rules",
        "Suppressed rules",
        "Cold-start fallback:",
        "Primary Greeting:",
        "Global Learned Rules:",
        "===",
    )
    for idx, line in enumerate(lines):
        for marker in ("Sign-off to use:", "Exact Sign-off:"):
            if marker in line:
                collected = [line.split(marker, 1)[1].strip()]
                if idx + 1 < len(lines):
                    nxt = lines[idx + 1].strip()
                    if nxt and not nxt.startswith(stop_prefixes):
                        collected.append(nxt)
                return "\n".join(part for part in collected if part)
    return "Best,\nAlex"


def _extract_user_task_and_context(user_prompt: str) -> tuple[str, str]:
    """Extract incoming context and task text from drafter-formatted user prompt."""
    marker = "Draft an email covering these points:"
    incoming = ""
    task = user_prompt.strip()
    if marker in user_prompt:
        before, after = user_prompt.split(marker, 1)
        task = after.strip()
        ctx_marker = "Incoming Email Context:"
        if ctx_marker in before:
            incoming = before.split(ctx_marker, 1)[1].strip()
    return task, incoming


def _call_ollama_controlled(
    system_prompt: str,
    user_prompt: str,
    settings: Settings,
    model_name: str = CONTROL_MODEL,
) -> str:
    """Call local Ollama /api/chat with identical controlled decoding parameters."""
    endpoint = f"{settings.ollama_url.rstrip('/')}/api/chat"
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "think": CONTROL_THINK,
        "stream": False,
        "options": {
            "temperature": CONTROL_TEMPERATURE,
            "seed": CONTROL_SEED,
            "num_predict": CONTROL_NUM_PREDICT,
            "num_ctx": settings.ollama_num_ctx,
        },
    }
    try:
        response = httpx.post(endpoint, json=payload, timeout=120.0)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Ollama request failed at {endpoint}: {exc}") from exc

    content = response.json().get("message", {}).get("content", "")
    # Clean stray thinking blocks if emitted by older Ollama builds.
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
    content = re.sub(r"thinking.*?\*/", "", content, flags=re.DOTALL).strip()
    if not content:
        raise RuntimeError("Ollama returned empty response")
    return content


class MockLLM:
    """Deterministic mocked LLM adapter for offline dry-run mode."""

    def __init__(self, seed: int = CONTROL_SEED):
        self.seed = seed

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        think: bool = False,
        **kwargs,
    ) -> str:
        """Generate a deterministic mock draft faithfully reflecting prompt instructions."""
        prompt_hash = hashlib.md5(
            (system_prompt + "\n---\n" + user_prompt + f"\n{self.seed}").encode("utf-8")
        ).hexdigest()
        var_rng = np.random.default_rng(int(prompt_hash[:8], 16))

        greeting = (
            _extract_prompt_field(system_prompt, "PRIMARY GREETING TO USE:")
            or _extract_prompt_field(system_prompt, "Greeting to use:")
            or _extract_prompt_field(system_prompt, "Primary Greeting:")
            or "Hi there,"
        )
        signoff = _extract_signoff(system_prompt)
        task_text, incoming = _extract_user_task_and_context(user_prompt)

        is_baseline_a = "USER STYLE PROFILE" not in system_prompt and "Adopt this style profile" not in system_prompt
        is_group_or_broadcast = (
            "AUDIENCE POLICY (group_cc)" in system_prompt
            or "AUDIENCE POLICY (broadcast_bcc)" in system_prompt
        )
        prefers_bullets = "prefers bullets" in system_prompt.lower() and not is_group_or_broadcast

        # Build body preserving the task content cleanly without markdown or report headings.
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", task_text) if s.strip()]
        if not sentences:
            sentences = ["Following up on the requested items."]

        body_blocks: list[str] = []
        if is_baseline_a and var_rng.random() < 0.2:
            body_blocks.append("I hope this email finds you well.")

        if prefers_bullets and len(sentences) >= 2:
            body_blocks.append("Here are the priority items:")
            body_blocks.append("\n".join(f"- {s}" for s in sentences))
        else:
            # Keep paragraphs short (2-3 sentences)
            if len(sentences) <= 2:
                body_blocks.append(" ".join(sentences))
            else:
                mid = (len(sentences) + 1) // 2
                body_blocks.append(" ".join(sentences[:mid]))
                body_blocks.append(" ".join(sentences[mid:]))

        if incoming and "Reply" not in body_blocks[0]:
            # Subtle acknowledgement without corporate filler
            if "AUDIENCE POLICY (group_cc)" in system_prompt:
                body_blocks.insert(0, "Sharing an update for everyone on the thread.")

        return f"{greeting}\n\n" + "\n\n".join(body_blocks) + f"\n\n{signoff}"


class BaselineRunner:
    """Runs the 3-baseline evaluation."""

    def __init__(
        self,
        seed_corpus_path: Path,
        scenarios_path: Path,
        mode: str = "dry-run",
        output_path: Path | None = None,
        resume: bool = False,
    ):
        self.seed_corpus_path = seed_corpus_path
        self.scenarios_path = scenarios_path
        self.mode = mode
        self.output_path = output_path or Path("eval/results/run_latest.json")
        self.resume = resume

        self.seed_corpus = json.loads(seed_corpus_path.read_text(encoding="utf-8"))
        self.scenarios = [
            Scenario(**s)
            for s in json.loads(scenarios_path.read_text(encoding="utf-8"))["scenarios"]
        ]

        self.run_id = str(uuid.uuid4())[:8]
        self.started_at = datetime.now(timezone.utc).isoformat()

        self.existing_results: dict[tuple[str, str], DraftResult] = {}
        if resume and self.output_path.exists():
            self._load_existing_results()

    def _load_existing_results(self) -> None:
        data = json.loads(self.output_path.read_text(encoding="utf-8"))
        for r in data.get("results", []):
            key = (r["scenario_id"], r["config_name"])
            self.existing_results[key] = DraftResult(**r)
        if data.get("run_id"):
            self.run_id = data["run_id"]
        print(f"Resumed: loaded {len(self.existing_results)} existing results")

    def _save_results(self, results: list[DraftResult]) -> None:
        # Preserve deterministic (scenario order, config order) output.
        scenario_order = {s.id: idx for idx, s in enumerate(self.scenarios)}
        config_order = {"baseline_a": 0, "baseline_b": 1, "proteus": 2}
        ordered = sorted(
            results,
            key=lambda r: (scenario_order.get(r.scenario_id, 999), config_order.get(r.config_name, 9)),
        )
        run_data = {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "mode": self.mode,
            "model": CONTROL_MODEL,
            "controls": {
                "think": CONTROL_THINK,
                "temperature": CONTROL_TEMPERATURE,
                "seed": CONTROL_SEED,
                "num_predict": CONTROL_NUM_PREDICT,
            },
            "results": [
                {
                    "scenario_id": r.scenario_id,
                    "config_name": r.config_name,
                    "draft": r.draft,
                    "audience_type": r.audience_type,
                    "confidence_level": r.confidence_level,
                    "resolution_meta": r.resolution_meta,
                    "latency_ms": r.latency_ms,
                    "timestamp": r.timestamp,
                }
                for r in ordered
            ],
        }
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.write_text(json.dumps(run_data, indent=2), encoding="utf-8")
        print(f"Saved {len(ordered)} results to {self.output_path}")

    def _setup_temp_environment(
        self,
    ) -> tuple[Path, Settings, ProfileStore, LocalEmbedder, LanceDBVectorStore]:
        """Create isolated temp directory with seeded synthetic data."""
        temp_dir = Path(tempfile.mkdtemp(prefix="proteus_eval_"))
        settings = Settings(
            local_user_data_dir=temp_dir,
            lancedb_dir=temp_dir / "lancedb",
            profiler_mode="heuristic",
            model_name=CONTROL_MODEL,
        )
        settings.ensure_local_directories()

        store = ProfileStore(settings)
        embedder = LocalEmbedder()
        embedder.load()
        vector_store = LanceDBVectorStore(settings)

        persona = self.seed_corpus["persona"]
        profile = UserStyleProfile(
            profile_id="eval-profile",
            created_at=datetime.now(timezone.utc),
            deterministic_stylometry=StylometryMetrics(**persona["deterministic_stylometry"]),
            global_style_card=GlobalStyleCard(**persona["global_style_card"]),
            corpus_statistics=CorpusStatistics(
                total_sent_emails=len(self.seed_corpus["historical_emails"]),
                clean_emails_retained=len(self.seed_corpus["historical_emails"]),
                top_recipients=[],
            ),
            global_learned_rules=persona["global_learned_rules"],
        )
        store.save_profile(profile)

        for contact in self.seed_corpus["contacts"]:
            rp = RecipientProfile(**contact)
            store.upsert_recipient_profile(rp)

        cleaned_emails = []
        for he in self.seed_corpus["historical_emails"]:
            email = CleanedSentEmail(
                message_id=he["message_id"],
                recipient_email=he["recipient_email"],
                recipient_domain=he["recipient_domain"],
                subject=he["subject"],
                raw_body=he["clean_body"],
                clean_body=he["clean_body"],
                signature=he.get("signoff", ""),
                word_count=he["word_count"],
                timestamp=datetime.fromisoformat(he["timestamp"]),
                thread_id="",
            )
            cleaned_emails.append(email)

        store.save_cleaned_emails(cleaned_emails)

        vector_store._get_or_create_table(force_recreate=True)
        texts = [embedder.prepare_text(e.subject, e.clean_body) for e in cleaned_emails]
        vectors = embedder.encode(texts)

        data = []
        for email, vector, he in zip(cleaned_emails, vectors, self.seed_corpus["historical_emails"]):
            timestamp_str = email.timestamp.isoformat() if email.timestamp else ""
            timestamp_epoch = email.timestamp.timestamp() if email.timestamp else 0.0
            data.append(
                {
                    "message_id": email.message_id,
                    "recipient_email": email.recipient_email,
                    "recipient_domain": email.recipient_domain,
                    "subject": email.subject,
                    "clean_body": email.clean_body,
                    "greeting": he["greeting"],
                    "signoff": he["signoff"],
                    "word_count": email.word_count,
                    "timestamp": timestamp_str,
                    "timestamp_epoch": timestamp_epoch,
                    "audience_mode": he["audience_mode"],
                    "cc_count": he["cc_count"],
                    "bcc_count": he["bcc_count"],
                    "vector": vector.tolist(),
                }
            )

        vector_store._get_or_create_table().add(data)
        return temp_dir, settings, store, embedder, vector_store

    def _run_baseline_a(
        self,
        scenario: Scenario,
        settings: Settings,
        drafter: QwenDrafter,
        mock_llm: MockLLM | None = None,
    ) -> DraftResult:
        """Baseline A: Generic LLM - task/context only (no style, no memory, no audience policy)."""
        start = time.perf_counter()

        system_prompt = (
            "You are an email writer. Write a concise, professional email.\n"
            "Write plain-text only. No markdown. No report headings."
        )
        user_prompt = drafter._build_user_prompt(scenario.task_prompt, scenario.incoming_context)

        if self.mode == "dry-run" and mock_llm:
            draft = mock_llm.generate(system_prompt, user_prompt)
        else:
            draft = _call_ollama_controlled(system_prompt, user_prompt, settings)

        latency = (time.perf_counter() - start) * 1000
        return DraftResult(
            scenario_id=scenario.id,
            config_name="baseline_a",
            draft=draft,
            audience_type="1on1_private",
            confidence_level="low",
            resolution_meta={"baseline": "a", "note": "no personalization"},
            latency_ms=latency,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    def _run_baseline_b(
        self,
        scenario: Scenario,
        settings: Settings,
        drafter: QwenDrafter,
        mock_llm: MockLLM | None = None,
    ) -> DraftResult:
        """Baseline B: Global style card + global learned rules only (no recipient memory, no audience precedence)."""
        start = time.perf_counter()

        persona = self.seed_corpus["persona"]
        style_card = persona["global_style_card"]
        stylometry = persona["deterministic_stylometry"]
        global_rules = persona["global_learned_rules"]

        style_parts = [
            f"Formality: {style_card['formality']}",
            f"Tone: {style_card['tone']}",
            f"Directness: {style_card['directness']}",
            f"Vocabulary Level: {style_card['vocabulary_level']}",
            f"Sentence Structure: {style_card['sentence_structure']}",
        ]
        if style_card.get("formatting_preferences"):
            style_parts.append("Formatting Preferences: " + "; ".join(style_card["formatting_preferences"]))
        if style_card.get("characteristic_phrases"):
            style_parts.append("Characteristic Phrases: " + ", ".join(style_card["characteristic_phrases"]))
        if stylometry.get("exact_signoff"):
            style_parts.append(f"Exact Sign-off: {stylometry['exact_signoff']}")
        if stylometry.get("top_greetings"):
            style_parts.append(f"Primary Greeting: {stylometry['top_greetings'][0]['pattern']}")
        if global_rules:
            style_parts.append("Global Learned Rules: " + "; ".join(global_rules))
        style_text = "\n".join(style_parts)

        top_greeting = stylometry.get("top_greetings", [{}])[0].get("pattern", "Hi {first_name},")
        local = scenario.to[0].split("@")[0] if scenario.to else ""
        for sep in (".", "_", "-", "+"):
            local = local.split(sep)[0]
        first_name = local.capitalize() if local.isalpha() and 2 <= len(local) <= 20 else ""
        greeting = (
            top_greeting.replace("{first_name}", first_name)
            if first_name
            else top_greeting.replace("{first_name}", "").strip()
        )
        greeting = re.sub(r"\s+", " ", greeting).strip()
        if greeting and not greeting.endswith(","):
            greeting += ","

        system_prompt = (
            "You are a personalized email writer. Adopt this style profile:\n\n"
            f"{style_text}\n\n"
            "Write plain-text human emails ONLY. Never use Markdown formatting.\n"
            "Write flowing, conversational paragraphs.\n\n"
            f"PRIMARY GREETING TO USE: {greeting}"
        )
        user_prompt = drafter._build_user_prompt(scenario.task_prompt, scenario.incoming_context)

        if self.mode == "dry-run" and mock_llm:
            draft = mock_llm.generate(system_prompt, user_prompt)
        else:
            draft = _call_ollama_controlled(system_prompt, user_prompt, settings)

        latency = (time.perf_counter() - start) * 1000
        return DraftResult(
            scenario_id=scenario.id,
            config_name="baseline_b",
            draft=draft,
            audience_type="1on1_private",
            confidence_level="medium",
            resolution_meta={"baseline": "b", "style": "global_only"},
            latency_ms=latency,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    def _run_proteus(
        self,
        scenario: Scenario,
        settings: Settings,
        store: ProfileStore,
        embedder: LocalEmbedder,
        vector_store: LanceDBVectorStore,
        drafter: QwenDrafter,
        mock_llm: MockLLM | None = None,
    ) -> DraftResult:
        """Proteus: Full pipeline with LanceDB retrieval, resolver, confidence, drafter prompt + post-processor."""
        start = time.perf_counter()

        profile = store.load_profile()
        assert profile is not None

        recipient_profile_objs: dict[str, RecipientProfile] = {}
        recipient_profile_dicts: dict[str, dict[str, Any]] = {}
        for email in scenario.to + scenario.cc:
            rp = store.get_recipient_profile(email)
            if rp:
                recipient_profile_objs[email.lower()] = rp
                recipient_profile_dicts[email.lower()] = rp.model_dump(mode="json")

        global_profile = profile.model_dump(mode="json")

        query_text = " ".join(filter(None, [scenario.incoming_context, scenario.task_prompt]))
        primary = scenario.to[0] if scenario.to else ""
        domain = primary.split("@")[-1] if "@" in primary else None
        target_audience = classify_audience(scenario.to, scenario.cc, scenario.bcc)

        retrieved = vector_store.retrieve_few_shot_examples(
            embedder=embedder,
            recipient_email=primary,
            recipient_domain=domain,
            query_text=query_text,
            k=5,
            target_audience_mode=target_audience,
            strict_audience=True,
        )

        context = resolve_draft_context(
            to=scenario.to,
            cc=scenario.cc,
            bcc=scenario.bcc,
            account_id="eval-account",
            retrieved_emails=retrieved,
            recipient_profiles=recipient_profile_dicts,
            global_profile=global_profile,
            current_instructions="",
        )

        first_name = drafter._resolve_first_name(primary, recipient_profile_objs)
        system_prompt = drafter._build_system_prompt(
            profile=profile,
            examples=context.get("examples", []),
            to_recipients=scenario.to,
            cc_recipients=scenario.cc,
            bcc_recipients=scenario.bcc,
            recipient_profiles=recipient_profile_objs,
            first_name=first_name,
            context=context,
        )
        user_prompt = drafter._build_user_prompt(scenario.task_prompt, scenario.incoming_context)
        resolved_signoff = str(context.get("signoff") or "") or None

        if self.mode == "dry-run" and mock_llm:
            raw_draft = mock_llm.generate(system_prompt, user_prompt)
        else:
            raw_draft = _call_ollama_controlled(system_prompt, user_prompt, settings)

        draft = drafter._post_process_draft(
            drafter._repair_json(raw_draft),
            profile,
            signoff=resolved_signoff,
        )

        latency = (time.perf_counter() - start) * 1000
        return DraftResult(
            scenario_id=scenario.id,
            config_name="proteus",
            draft=draft,
            audience_type=context.get("audience_type", "1on1_private"),
            confidence_level=context.get("confidence", {}).get("level", "unknown"),
            resolution_meta=context.get("resolution_meta", {}),
            latency_ms=latency,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    def run(self) -> list[DraftResult]:
        """Run all scenarios across all 3 configurations."""
        mock_llm = MockLLM(seed=CONTROL_SEED) if self.mode == "dry-run" else None
        temp_dir, settings, store, embedder, vector_store = self._setup_temp_environment()
        drafter = QwenDrafter(settings)

        all_results: list[DraftResult] = list(self.existing_results.values())

        try:
            for i, scenario in enumerate(self.scenarios):
                print(f"\n[{i+1}/{len(self.scenarios)}] {scenario.id} ({scenario.category})")

                scenario_ran = False
                for config_name in ("baseline_a", "baseline_b", "proteus"):
                    key = (scenario.id, config_name)
                    if key in self.existing_results:
                        print(f"  {config_name}: SKIPPED (cached)")
                        continue

                    scenario_ran = True
                    print(f"  {config_name}: running...")
                    try:
                        if config_name == "baseline_a":
                            result = self._run_baseline_a(scenario, settings, drafter, mock_llm)
                        elif config_name == "baseline_b":
                            result = self._run_baseline_b(scenario, settings, drafter, mock_llm)
                        else:
                            result = self._run_proteus(
                                scenario, settings, store, embedder, vector_store, drafter, mock_llm
                            )
                        all_results.append(result)
                        print(
                            f"    audience={result.audience_type}, "
                            f"confidence={result.confidence_level}, latency={result.latency_ms:.0f}ms"
                        )
                    except Exception as exc:
                        print(f"    ERROR: {exc}")
                        all_results.append(
                            DraftResult(
                                scenario_id=scenario.id,
                                config_name=config_name,
                                draft=f"[ERROR: {exc}]",
                                audience_type="error",
                                confidence_level="error",
                                resolution_meta={"error": str(exc)},
                                latency_ms=0.0,
                                timestamp=datetime.now(timezone.utc).isoformat(),
                            )
                        )

                # Checkpoint after every scenario in live mode so interrupted runs can resume cleanly.
                if self.mode == "live" and scenario_ran:
                    self._save_results(all_results)

        finally:
            del vector_store, store, drafter
            shutil.rmtree(temp_dir, ignore_errors=True)

        self._save_results(all_results)
        return all_results


def main() -> None:
    parser = argparse.ArgumentParser(description="3-Baseline Personalization Benchmark Harness")
    parser.add_argument(
        "--mode",
        choices=["dry-run", "live"],
        default="dry-run",
        help="dry-run uses deterministic mocked LLM; live calls local Ollama",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("eval/results/run_latest.json"),
        help="Output JSON path",
    )
    parser.add_argument("--resume", action="store_true", help="Resume from existing output file")
    parser.add_argument(
        "--seed-corpus",
        type=Path,
        default=Path("eval/seed_corpus.json"),
        help="Seed corpus JSON path",
    )
    parser.add_argument(
        "--scenarios",
        type=Path,
        default=Path("eval/scenarios.json"),
        help="Scenarios JSON path",
    )
    args = parser.parse_args()

    runner = BaselineRunner(
        seed_corpus_path=args.seed_corpus,
        scenarios_path=args.scenarios,
        mode=args.mode,
        output_path=args.output,
        resume=args.resume,
    )

    print(f"Starting run {runner.run_id} in {args.mode} mode (model={CONTROL_MODEL})")
    print(f"Scenarios: {len(runner.scenarios)}")
    print(f"Output: {args.output}")

    results = runner.run()
    print(f"\nCompleted: {len(results)} total results")
    print(f"Results saved to {args.output}")


if __name__ == "__main__":
    main()
