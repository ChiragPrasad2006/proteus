"""Local Qwen-backed global style profiling with deep reasoning mode (think=True)."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import httpx

from backend.config import Settings
from backend.schemas import CleanedSentEmail, GlobalStyleCard, StylometryMetrics

PROFILE_SYSTEM_PROMPT = """You are a local style-analysis component for a personalized email writer.
Analyze only the supplied sent-email samples. Return strict JSON and no markdown.
The downstream Qwen email model was trained with this style-profile vocabulary:
- formality: choose exactly one of casual, semi-formal, strict-executive, blunt-technical
- sentence_structure: choose exactly one of short & punchy, detailed & analytical, warm & conversational
Its chat system prompt is: You are a personalized email writer. Adopt the persona and style profile
provided in the prompt, write concise, high-impact emails, and avoid corporate AI clichés.
Do not infer private facts beyond writing habits."""

LOCAL_STYLE_CARD_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "formality",
        "tone",
        "directness",
        "vocabulary_level",
        "sentence_structure",
        "formatting_preferences",
        "characteristic_phrases",
    ],
    "properties": {
        "formality": {"type": "string", "enum": ["casual", "semi-formal", "strict-executive", "blunt-technical"]},
        "tone": {"type": "string"},
        "directness": {"type": "string", "enum": ["low", "balanced", "high"]},
        "vocabulary_level": {"type": "string", "enum": ["simple", "standard-professional", "advanced-technical"]},
        "sentence_structure": {"type": "string", "enum": ["short & punchy", "detailed & analytical", "warm & conversational"]},
        "formatting_preferences": {"type": "array", "maxItems": 6, "items": {"type": "string"}},
        "characteristic_phrases": {"type": "array", "maxItems": 5, "items": {"type": "string"}},
    },
}


class ProfilerUnavailable(RuntimeError):
    """No permitted local inference runtime could profile the corpus."""


class QwenStyleProfiler:
    """Sample local mail and derive GlobalStyleCard with local Qwen using deep reasoning mode (think=True)."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @staticmethod
    def select_diverse_sample(messages: list[CleanedSentEmail], target: int = 18) -> list[CleanedSentEmail]:
        """Deterministically rotate recipient domains while spanning short/medium/long emails."""
        if len(messages) <= target:
            return list(messages)
        by_domain: dict[str, list[CleanedSentEmail]] = defaultdict(list)
        for message in sorted(messages, key=lambda item: (item.word_count, item.message_id)):
            by_domain[message.recipient_domain or "unknown"].append(message)
        selected: list[CleanedSentEmail] = []
        positions = {domain: 0 for domain in by_domain}
        domains = sorted(by_domain)
        while len(selected) < target:
            added = False
            for domain in domains:
                items = by_domain[domain]
                position = positions[domain]
                if position < len(items):
                    selected.append(items[position])
                    positions[domain] += 1
                    added = True
                    if len(selected) == target:
                        break
            if not added:
                break
        return selected

    def availability(self) -> dict[str, Any]:
        """Report local runtime availability without loading model weights."""
        ollama_models: list[str] = []
        ollama_error = ""
        try:
            response = httpx.get(f"{self.settings.ollama_url.rstrip('/')}/api/tags", timeout=5.0)
            response.raise_for_status()
            ollama_models = [item.get("name", "") for item in response.json().get("models", [])]
        except Exception as exc:  # Health checks should not make the API unavailable.
            ollama_error = str(exc)
        exported_hf = (self.settings.exported_model_dir / "config.json").is_file()
        gguf_files = list(self.settings.exported_model_dir.rglob("*.gguf")) if self.settings.exported_model_dir.exists() else []
        return {
            "ollama_url": self.settings.ollama_url,
            "ollama_available_models": ollama_models,
            "preferred_ollama_model_available": any(
                model in ollama_models for model in self.settings.ollama_models
            ),
            "ollama_error": ollama_error,
            "exported_transformers_model_available": exported_hf,
            "local_gguf_available": bool(gguf_files),
            "profiler_mode": self.settings.profiler_mode,
        }

    def profile(self, messages: list[CleanedSentEmail], metrics: StylometryMetrics) -> GlobalStyleCard:
        """Profile a stratified sample through a local model, never a hosted LLM."""
        sample = self.select_diverse_sample(messages)
        if not sample:
            raise ProfilerUnavailable("No cleaned sent emails are available to profile.")
        if self.settings.profiler_mode == "heuristic":
            return self._heuristic_profile(sample, metrics)
        failures: list[str] = []
        for model_name in self.settings.ollama_models:
            try:
                return self._profile_with_ollama(sample, model_name)
            except ProfilerUnavailable as exc:
                failures.append(str(exc))
        try:
            return self._profile_with_transformers(sample)
        except ProfilerUnavailable as exc:
            failures.append(str(exc))
        try:
            return self._profile_with_llama_cpp(sample)
        except ProfilerUnavailable as exc:
            failures.append(str(exc))
        raise ProfilerUnavailable("; ".join(failures))

    def _prompt(self, sample: list[CleanedSentEmail]) -> str:
        rendered = []
        for index, message in enumerate(sample, start=1):
            rendered.append(
                f"EMAIL {index} (recipient domain: {message.recipient_domain or 'unknown'}):\n{message.clean_body}\n"
                f"SIGNATURE: {message.signature or '[none]'}"
            )
        return (
            "The response schema is enforced separately. Derive every value from the samples. "
            "For tone, formatting_preferences, and characteristic_phrases, use observed habits only; "
            "do not emit generic placeholder text or copied prompt wording.\n\nSENT-EMAIL SAMPLES:\n"
            + "\n\n---\n\n".join(rendered)
        )

    @staticmethod
    def _repair_json(content: str) -> dict[str, Any]:
        """Remove common code fences and parse the first JSON object returned by a small model."""
        cleaned = re.sub(r"^\s*```(?:json)?\s*", "", content.strip(), flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```\s*$", "", cleaned)
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end < start:
            raise ValueError("response did not contain a JSON object")
        return json.loads(cleaned[start : end + 1])

    @staticmethod
    def _card_from_response(
        content: str, source: str, model: str, sampled_email_count: int
    ) -> GlobalStyleCard:
        """Validate local-model JSON against the project's strict card schema."""
        payload = QwenStyleProfiler._repair_json(content)
        payload.update(source=source, model=model, sampled_email_count=sampled_email_count)
        return GlobalStyleCard.model_validate(payload)

    @staticmethod
    def _is_copied_prompt_example(card: GlobalStyleCard) -> bool:
        """Detect the exact illustrative card that an instruction-following model may copy."""
        return (
            card.formality == "semi-formal"
            and card.tone == "clear and collaborative"
            and card.directness == "balanced"
            and card.vocabulary_level == "standard-professional"
            and card.sentence_structure == "warm & conversational"
            and card.formatting_preferences == ["opens with a greeting", "uses short paragraphs"]
            and card.characteristic_phrases == ["please review", "before Thursday"]
        )

    def _profile_with_ollama(self, sample: list[CleanedSentEmail], model_name: str) -> GlobalStyleCard:
        """Ask a locally running Ollama model with deep reasoning mode (think=True)."""
        endpoint = f"{self.settings.ollama_url.rstrip('/')}/api/chat"
        last_error = "no Ollama response"
        messages = [
            {"role": "system", "content": PROFILE_SYSTEM_PROMPT},
            {"role": "user", "content": self._prompt(sample)},
        ]
        content = ""
        for attempt in range(2):
            try:
                response = httpx.post(
                    endpoint,
                    json={
                        "model": model_name,
                        "messages": messages,
                        "stream": False,
                        "format": LOCAL_STYLE_CARD_SCHEMA,
                        "options": {
                            "temperature": 0.6,
                            "top_p": 0.95,
                            "top_k": 20,
                            "num_ctx": self.settings.ollama_num_ctx,
                            "think": True,  # Deep reasoning mode for profiling
                        },
                    },
                    timeout=180,
                )
                if response.status_code == 404:
                    raise ProfilerUnavailable(f"Ollama model '{model_name}' is not installed.")
                response.raise_for_status()
                content = response.json().get("message", {}).get("content", "")
                # Strip thinking blocks if present
                if "question" in content and "answer" in content:
                    content = re.sub(r"question.*?answer", "", content, flags=re.DOTALL).strip()
                card = self._card_from_response(content, "ollama", model_name, len(sample))
                if self._is_copied_prompt_example(card):
                    raise ValueError("model copied the prompt example instead of analyzing the email sample")
                return card
            except (httpx.HTTPError, ValueError) as exc:
                last_error = str(exc)
                if attempt == 0 and content:
                    messages.extend(
                        [
                            {"role": "assistant", "content": content},
                            {
                                "role": "user",
                                "content": "Correct the previous response to match every JSON enum and field exactly. Return JSON only.",
                            },
                        ]
                    )
        raise ProfilerUnavailable(f"Ollama profiler '{model_name}' failed: {last_error}")

    def _profile_with_transformers(self, sample: list[CleanedSentEmail]) -> GlobalStyleCard:
        """Use only an already-exported local Hugging Face model; never download a base model."""
        if not (self.settings.exported_model_dir / "config.json").is_file():
            raise ProfilerUnavailable("No exported local Transformers model directory was found.")
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer

            tokenizer = AutoTokenizer.from_pretrained(self.settings.exported_model_dir, local_files_only=True)
            model = AutoModelForCausalLM.from_pretrained(
                self.settings.exported_model_dir,
                local_files_only=True,
                device_map="auto" if torch.cuda.is_available() else None,
                torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
            )
            chat = [
                {"role": "system", "content": PROFILE_SYSTEM_PROMPT},
                {"role": "user", "content": self._prompt(sample)},
            ]
            prompt = tokenizer.apply_chat_template(chat, tokenize=False, add_generation_prompt=True)
            device = next(model.parameters()).device
            inputs = tokenizer(prompt, return_tensors="pt").to(device)
            with torch.no_grad():
                output = model.generate(**inputs, do_sample=False, max_new_tokens=400)
            content = tokenizer.decode(output[0][inputs.input_ids.shape[1] :], skip_special_tokens=True)
            return self._card_from_response(content, "transformers", str(self.settings.exported_model_dir), len(sample))
        except Exception as exc:
            raise ProfilerUnavailable(f"Local Transformers profiler failed: {exc}") from exc

    def _profile_with_llama_cpp(self, sample: list[CleanedSentEmail]) -> GlobalStyleCard:
        """Use a local GGUF when present and llama-cpp-python is installed."""
        gguf_files = list(self.settings.exported_model_dir.rglob("*.gguf")) if self.settings.exported_model_dir.exists() else []
        if not gguf_files:
            raise ProfilerUnavailable("No local GGUF model was found.")
        try:
            from llama_cpp import Llama

            model_path = gguf_files[0]
            llm = Llama(model_path=str(model_path), n_ctx=8192, verbose=False)
            prompt = (
                " quadrant system\n" + PROFILE_SYSTEM_PROMPT + " \u25a1\n"
                " quadrant user\n" + self._prompt(sample) + " \u25a1 quadrant assistant\n"
            )
            result = llm(prompt, max_tokens=400, temperature=0, stop=[" \u25a1"])
            content = result["choices"][0]["text"]
            return self._card_from_response(content, "llama_cpp", str(model_path), len(sample))
        except Exception as exc:
            raise ProfilerUnavailable(f"Local llama.cpp profiler failed: {exc}") from exc

    @staticmethod
    def _heuristic_profile(sample: list[CleanedSentEmail], metrics: StylometryMetrics) -> GlobalStyleCard:
        """Explicit test/development fallback; it is never selected by normal local mode."""
        greeting = metrics.top_greetings[0].pattern if metrics.top_greetings else ""
        if greeting.startswith("Dear"):
            formality = "strict-executive"
        elif metrics.avg_sentence_length_words < 12:
            formality = "blunt-technical"
        else:
            formality = "semi-formal"
        sentence_structure = (
            "short & punchy"
            if metrics.avg_sentence_length_words < 12
            else "detailed & analytical"
            if metrics.avg_sentence_length_words > 20
            else "warm & conversational"
        )
        directness = "high" if metrics.avg_sentence_length_words < 15 else "balanced"
        formatting = [
            f"Uses {greeting}" if greeting else "Often opens directly without a salutation",
            f"Typical sign-off: {metrics.exact_signoff}" if metrics.exact_signoff else "Often omits a sign-off",
            "Uses bullet lists" if metrics.uses_bullet_lists_pct >= 25 else "Primarily writes in paragraphs",
        ]
        phrases = QwenStyleProfiler._frequent_phrases(sample)
        return GlobalStyleCard(
            formality=formality,
            tone="clear and professional",
            directness=directness,
            vocabulary_level="standard-professional",
            sentence_structure=sentence_structure,
            formatting_preferences=formatting,
            characteristic_phrases=phrases,
            source="heuristic",
            model="deterministic-local-fallback",
            sampled_email_count=len(sample),
        )

    @staticmethod
    def _frequent_phrases(sample: list[CleanedSentEmail]) -> list[str]:
        """Collect stable repeated bigrams, falling back to no phrases instead of inventing one."""
        counts: Counter[str] = Counter()
        for message in sample:
            words = [word.lower() for word in re.findall(r"[A-Za-z][A-Za-z'-]+", message.clean_body)]
            for left, right in zip(words, words[1:]):
                if left not in {"hi", "hey", "hello", "dear"}:
                    counts[f"{left} {right}"] += 1
        return [phrase for phrase, count in counts.most_common(5) if count > 1]