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
import json
import os
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from backend.config import Settings
from backend.generation.confidence import ConfidenceThresholds
from backend.generation.context_resolver import resolve_draft_context
from backend.generation.drafter import QwenDrafter
from backend.retrieval import LanceDBVectorStore, LocalEmbedder
from backend.schemas import (
    CleanedSentEmail,
    GlobalStyleCard,
    RecipientProfile,
    UserStyleProfile,
    AudienceMode,
    RelationshipTier,
    StylometryMetrics,
    CorpusStatistics,
    GreetingFrequency,
)
from backend.storage import ProfileStore


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


class MockLLM:
    """Deterministic mocked LLM adapter for dry-run mode."""

    def __init__(self, seed: int = 42):
        self.seed = seed
        self.rng = np.random.default_rng(seed)

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        think: bool = False,
        **kwargs,
    ) -> str:
        """Generate a deterministic mock draft based on prompts."""
        # Use a hash of the prompts + seed for deterministic but varied output
        import hashlib
        prompt_hash = hashlib.md5((system_prompt + user_prompt + str(self.seed)).encode()).hexdigest()
        var_rng = np.random.default_rng(int(prompt_hash[:8], 16))

        # Extract key info from prompts for deterministic output
        lines = []

        # Greeting from system prompt
        greeting = "Hi there,"
        if "PRIMARY GREETING TO USE:" in system_prompt:
            for line in system_prompt.split("\n"):
                if "PRIMARY GREETING TO USE:" in line:
                    greeting = line.split("PRIMARY GREETING TO USE:")[1].strip()
                    break
        elif "Primary Greeting:" in system_prompt:
            for line in system_prompt.split("\n"):
                if "Primary Greeting:" in line:
                    greeting = line.split("Primary Greeting:")[1].strip()
                    break

        # Sign-off from system prompt
        signoff = "Best,\nAlex"
        if "Sign-off to use:" in system_prompt:
            for line in system_prompt.split("\n"):
                if "Sign-off to use:" in line:
                    signoff = line.split("Sign-off to use:")[1].strip()
                    break
        elif "Exact Sign-off:" in system_prompt:
            for line in system_prompt.split("\n"):
                if "Exact Sign-off:" in line:
                    signoff = line.split("Exact Sign-off:")[1].strip()
                    break

        # Build draft
        lines.append(greeting)
        lines.append("")

        # Extract intent from user prompt
        intent_lines = []
        for line in user_prompt.split("\n"):
            if line.strip().startswith("-") or line.strip().startswith("Draft an email"):
                intent_lines.append(line.strip().lstrip("- ").strip())

        if intent_lines:
            # Create a concise paragraph from intent
            body = " ".join(intent_lines[:3])
            lines.append(body)
        else:
            lines.append("Following up on the requested items as discussed.")

        lines.append("")
        lines.append(signoff)

        # Add a small variation based on prompt hash for different seeds
        if var_rng.random() < 0.5:
            lines.insert(-1, "")  # Extra blank line

        return "\n".join(lines)


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

        self.seed_corpus = json.loads(seed_corpus_path.read_text())
        self.scenarios = [Scenario(**s) for s in json.loads(scenarios_path.read_text())["scenarios"]]

        self.run_id = str(uuid.uuid4())[:8]
        self.started_at = datetime.now(timezone.utc).isoformat()

        # Load existing results if resuming
        self.existing_results: dict[str, dict[str, DraftResult]] = {}
        if resume and self.output_path.exists():
            self._load_existing_results()

    def _load_existing_results(self):
        data = json.loads(self.output_path.read_text())
        for r in data.get("results", []):
            key = (r["scenario_id"], r["config_name"])
            self.existing_results[key] = DraftResult(**r)
        print(f"Resumed: loaded {len(self.existing_results)} existing results")

    def _save_results(self, results: list[DraftResult]):
        run_data = {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "mode": self.mode,
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
                for r in results
            ],
        }
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.write_text(json.dumps(run_data, indent=2))
        print(f"Saved {len(results)} results to {self.output_path}")

    def _setup_temp_environment(self) -> tuple[Path, Settings, ProfileStore, LocalEmbedder, LanceDBVectorStore]:
        """Create isolated temp directory with seeded data."""
        temp_dir = Path(tempfile.mkdtemp(prefix="proteus_eval_"))
        settings = Settings(
            local_user_data_dir=temp_dir,
            lancedb_dir=temp_dir / "lancedb",
            profiler_mode="heuristic",
            model_name="qwen3:8b",
        )
        settings.ensure_local_directories()

        store = ProfileStore(settings)
        embedder = LocalEmbedder()
        embedder.load()
        vector_store = LanceDBVectorStore(settings)

        # Seed profile
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

        # Seed recipient profiles
        for contact in self.seed_corpus["contacts"]:
            rp = RecipientProfile(**contact)
            store.upsert_recipient_profile(rp)

        # Seed historical emails into LanceDB
        cleaned_emails = []
        for he in self.seed_corpus["historical_emails"]:
            email = CleanedSentEmail(
                message_id=he["message_id"],
                recipient_email=he["recipient_email"],
                recipient_domain=he["recipient_domain"],
                subject=he["subject"],
                raw_body=he["clean_body"],  # Required field from EmailMessage parent
                clean_body=he["clean_body"],
                signature=he.get("signoff", ""),
                word_count=he["word_count"],
                timestamp=datetime.fromisoformat(he["timestamp"]),
                thread_id="",
            )
            cleaned_emails.append(email)

        # Also save to JSONL for drafter
        store.save_cleaned_emails(cleaned_emails)

        # Index into LanceDB with audience metadata
        vector_store._get_or_create_table(force_recreate=True)
        texts = [embedder.prepare_text(e.subject, e.clean_body) for e in cleaned_emails]
        vectors = embedder.encode(texts)

        data = []
        for email, vector, he in zip(cleaned_emails, vectors, self.seed_corpus["historical_emails"]):
            timestamp_str = email.timestamp.isoformat() if email.timestamp else ""
            timestamp_epoch = email.timestamp.timestamp() if email.timestamp else 0.0

            data.append({
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
            })

        vector_store._get_or_create_table().add(data)

        return temp_dir, settings, store, embedder, vector_store

    def _run_baseline_a(self, scenario: Scenario, mock_llm: MockLLM | None = None) -> DraftResult:
        """Baseline A: Generic LLM - no style, no memory, no audience policy."""
        start = time.perf_counter()

        # Minimal system prompt - no style, no audience topology
        system_prompt = """You are an email writer. Write a concise, professional email.
Write plain-text only. No markdown. No report headings."""
        user_prompt = f"Draft an email covering these points:\n{scenario.task_prompt}"

        if self.mode == "dry-run" and mock_llm:
            draft = mock_llm.generate(system_prompt, user_prompt)
            audience_type = "1on1_private"
            confidence_level = "low"
            resolution_meta = {"baseline": "a", "note": "no personalization"}
        else:
            # Live mode would call Ollama here
            draft = "[LIVE MODE NOT IMPLEMENTED FOR BASELINE A]"
            audience_type = "1on1_private"
            confidence_level = "low"
            resolution_meta = {"baseline": "a", "error": "live mode requires Ollama"}

        latency = (time.perf_counter() - start) * 1000
        return DraftResult(
            scenario_id=scenario.id,
            config_name="baseline_a",
            draft=draft,
            audience_type=audience_type,
            confidence_level=confidence_level,
            resolution_meta=resolution_meta,
            latency_ms=latency,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    def _run_baseline_b(self, scenario: Scenario, mock_llm: MockLLM | None = None) -> DraftResult:
        """Baseline B: Global Style Only - style card + global rules, no recipient memory, no audience precedence."""
        start = time.perf_counter()

        persona = self.seed_corpus["persona"]
        style_card = persona["global_style_card"]
        stylometry = persona["deterministic_stylometry"]
        global_rules = persona["global_learned_rules"]

        # Build style profile text
        style_text = "\n".join([
            f"Formality: {style_card['formality']}",
            f"Tone: {style_card['tone']}",
            f"Directness: {style_card['directness']}",
            f"Vocabulary Level: {style_card['vocabulary_level']}",
            f"Sentence Structure: {style_card['sentence_structure']}",
        ])
        if style_card.get("formatting_preferences"):
            style_text += "\nFormatting Preferences: " + "; ".join(style_card["formatting_preferences"])
        if style_card.get("characteristic_phrases"):
            style_text += "\nCharacteristic Phrases: " + ", ".join(style_card["characteristic_phrases"])
        if stylometry.get("exact_signoff"):
            style_text += f"\nExact Sign-off: {stylometry['exact_signoff']}"
        if stylometry.get("top_greetings"):
            style_text += f"\nPrimary Greeting: {stylometry['top_greetings'][0]['pattern']}"
        if global_rules:
            style_text += "\nGlobal Learned Rules: " + "; ".join(global_rules)

        # Determine greeting from global stylometry (no recipient profile)
        top_greeting = stylometry.get("top_greetings", [{}])[0].get("pattern", "Hi {first_name},")
        first_name = scenario.to[0].split("@")[0].split(".")[0].capitalize() if scenario.to else ""
        greeting = top_greeting.replace("{first_name}", first_name) if first_name else top_greeting.replace("{first_name}", "").strip()
        greeting = greeting.replace("  ", " ").strip()
        if not greeting.endswith(","):
            greeting += ","

        signoff = stylometry.get("exact_signoff", "Best,\nAlex")

        system_prompt = f"""You are a personalized email writer. Adopt this style profile:

{style_text}

Write plain-text human emails ONLY. Never use Markdown formatting.
Write flowing, conversational paragraphs.

PRIMARY GREETING TO USE: {greeting}"""

        user_prompt = f"Draft an email covering these points:\n{scenario.task_prompt}"

        if self.mode == "dry-run" and mock_llm:
            draft = mock_llm.generate(system_prompt, user_prompt)
            audience_type = "1on1_private"
            confidence_level = "medium"
            resolution_meta = {"baseline": "b", "style": "global_only"}
        else:
            draft = "[LIVE MODE NOT IMPLEMENTED FOR BASELINE B]"
            audience_type = "1on1_private"
            confidence_level = "medium"
            resolution_meta = {"baseline": "b", "error": "live mode requires Ollama"}

        latency = (time.perf_counter() - start) * 1000
        return DraftResult(
            scenario_id=scenario.id,
            config_name="baseline_b",
            draft=draft,
            audience_type=audience_type,
            confidence_level=confidence_level,
            resolution_meta=resolution_meta,
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
        mock_llm: MockLLM | None = None,
    ) -> DraftResult:
        """Proteus: Full pipeline with retrieval, resolver, confidence, drafter."""
        start = time.perf_counter()

        profile = store.load_profile()
        recipient_profiles = {}
        for email in scenario.to + scenario.cc:
            rp = store.get_recipient_profile(email)
            if rp:
                recipient_profiles[email.lower()] = rp.model_dump(mode="json")

        global_profile = profile.model_dump(mode="json") if profile else None

        # Retrieve examples
        query_text = " ".join(filter(None, [scenario.incoming_context, scenario.task_prompt]))
        primary = scenario.to[0] if scenario.to else ""
        domain = primary.split("@")[-1] if "@" in primary else None

        from backend.generation.context_resolver import classify_audience
        target_audience = classify_audience(scenario.to, scenario.cc, scenario.bcc)

        retrieved = vector_store.retrieve_few_shot_examples(
            embedder=embedder,
            recipient_email=primary,
            recipient_domain=domain,
            query_text=query_text,
            k=2,
            target_audience_mode=target_audience,
            strict_audience=True,
        )

        # Resolve context
        context = resolve_draft_context(
            to=scenario.to,
            cc=scenario.cc,
            bcc=scenario.bcc,
            account_id="eval-account",
            retrieved_emails=retrieved,
            recipient_profiles=recipient_profiles,
            global_profile=global_profile,
            current_instructions="",
        )

        # Generate draft
        drafter = QwenDrafter(settings)

        if self.mode == "dry-run" and mock_llm:
            # Build system prompt like drafter would
            system_prompt = drafter._build_system_prompt(
                profile=profile,
                examples=context.get("examples", []),
                to_recipients=scenario.to,
                cc_recipients=scenario.cc,
                bcc_recipients=scenario.bcc,
                recipient_profiles=recipient_profiles,
                first_name="",
                context=context,
            )
            user_prompt = drafter._build_user_prompt(scenario.task_prompt, scenario.incoming_context)
            draft = mock_llm.generate(system_prompt, user_prompt)
        else:
            # Live mode - use actual drafter
            try:
                draft = drafter.generate_draft(
                    profile=profile,
                    cleaned_emails=store.load_cleaned_emails(),
                    intent_bullets=scenario.task_prompt,
                    recipient_email=scenario.to[0] if scenario.to else None,
                    incoming_context=scenario.incoming_context,
                    cc_recipients=scenario.cc,
                    bcc_recipients=scenario.bcc,
                    recipient_profiles=recipient_profiles,
                    context=context,
                )
            except Exception as e:
                draft = f"[ERROR: {e}]"

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
        mock_llm = MockLLM(seed=42) if self.mode == "dry-run" else None

        # Setup temp environment for Proteus
        temp_dir, settings, store, embedder, vector_store = self._setup_temp_environment()

        all_results = []

        # Load existing results if resuming
        for key, result in self.existing_results.items():
            all_results.append(result)

        try:
            for i, scenario in enumerate(self.scenarios):
                print(f"\n[{i+1}/{len(self.scenarios)}] {scenario.id} ({scenario.category})")

                for config_name in ["baseline_a", "baseline_b", "proteus"]:
                    key = (scenario.id, config_name)
                    if key in self.existing_results:
                        print(f"  {config_name}: SKIPPED (cached)")
                        continue

                    print(f"  {config_name}: running...")
                    try:
                        if config_name == "baseline_a":
                            result = self._run_baseline_a(scenario, mock_llm)
                        elif config_name == "baseline_b":
                            result = self._run_baseline_b(scenario, mock_llm)
                        else:
                            result = self._run_proteus(
                                scenario, settings, store, embedder, vector_store, mock_llm
                            )
                        all_results.append(result)
                        print(f"    audience={result.audience_type}, confidence={result.confidence_level}, latency={result.latency_ms:.0f}ms")
                    except Exception as e:
                        print(f"    ERROR: {e}")
                        error_result = DraftResult(
                            scenario_id=scenario.id,
                            config_name=config_name,
                            draft=f"[ERROR: {e}]",
                            audience_type="error",
                            confidence_level="error",
                            resolution_meta={"error": str(e)},
                            latency_ms=0,
                            timestamp=datetime.now(timezone.utc).isoformat(),
                        )
                        all_results.append(error_result)

                    # Checkpoint after each scenario
                    if self.mode == "live":
                        self._save_results(all_results)

        finally:
            # Cleanup temp dir
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)

        self._save_results(all_results)
        return all_results


def main():
    parser = argparse.ArgumentParser(description="3-Baseline Personalization Benchmark Harness")
    parser.add_argument("--mode", choices=["dry-run", "live"], default="dry-run",
                        help="dry-run uses mocked LLM; live calls Ollama")
    parser.add_argument("--output", type=Path, default=Path("eval/results/run_latest.json"),
                        help="Output JSON path")
    parser.add_argument("--resume", action="store_true",
                        help="Resume from existing output file")
    parser.add_argument("--seed-corpus", type=Path, default=Path("eval/seed_corpus.json"),
                        help="Seed corpus JSON path")
    parser.add_argument("--scenarios", type=Path, default=Path("eval/scenarios.json"),
                        help="Scenarios JSON path")
    args = parser.parse_args()

    runner = BaselineRunner(
        seed_corpus_path=args.seed_corpus,
        scenarios_path=args.scenarios,
        mode=args.mode,
        output_path=args.output,
        resume=args.resume,
    )

    print(f"Starting run {runner.run_id} in {args.mode} mode")
    print(f"Scenarios: {len(runner.scenarios)}")
    print(f"Output: {args.output}")

    results = runner.run()
    print(f"\nCompleted: {len(results)} total results")
    print(f"Results saved to {args.output}")


if __name__ == "__main__":
    main()