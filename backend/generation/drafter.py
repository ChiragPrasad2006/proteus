"""Personalized email draft generation using fine-tuned Qwen3-8B with audience topology prompting."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import httpx

from backend.config import Settings
from backend.retrieval import LanceDBVectorStore, LocalEmbedder
from backend.schemas import (
    CleanedSentEmail,
    GlobalStyleCard,
    RecipientProfile,
    UserStyleProfile,
    AudienceMode,
    RelationshipTier,
)


class DrafterUnavailable(RuntimeError):
    """No permitted local inference runtime could generate a draft."""


class QwenDrafter:
    """Generate personalized email drafts using local Qwen3-8B model with audience topology."""

    SYSTEM_PROMPT_TEMPLATE = """You are a personalized email writer. Adopt the persona and style profile provided in the prompt, write concise, high-impact emails, and avoid corporate AI clichés (such as 'I hope this email finds you well', 'delve', 'tapestry', 'furthermore')."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.embedder = LocalEmbedder()
        self.vector_store = LanceDBVectorStore(settings)

    def availability(self) -> dict[str, Any]:
        """Report local inference availability."""
        ollama_models = []
        ollama_error = ""
        try:
            response = httpx.get(f"{self.settings.ollama_url.rstrip('/')}/api/tags", timeout=2.0)
            response.raise_for_status()
            ollama_models = [item.get("name", "") for item in response.json().get("models", [])]
        except Exception as exc:
            ollama_error = str(exc)

        exported_hf = (self.settings.exported_model_dir / "config.json").is_file()
        return {
            "ollama_url": self.settings.ollama_url,
            "ollama_available_models": ollama_models,
            "preferred_ollama_model_available": any(
                m in ollama_models for m in self.settings.ollama_models
            ),
            "ollama_error": ollama_error,
            "exported_transformers_model_available": exported_hf,
            "profiler_mode": self.settings.profiler_mode,
        }

    def _format_style_profile(self, profile: UserStyleProfile) -> str:
        """Format the user's style profile for the system prompt."""
        det = profile.deterministic_stylometry
        gsc = profile.global_style_card

        parts = [
            f"Formality: {gsc.formality}",
            f"Tone: {gsc.tone}",
            f"Directness: {gsc.directness}",
            f"Vocabulary Level: {gsc.vocabulary_level}",
            f"Sentence Structure: {gsc.sentence_structure}",
        ]

        if gsc.formatting_preferences:
            parts.append("Formatting Preferences: " + "; ".join(gsc.formatting_preferences))
        if gsc.characteristic_phrases:
            parts.append("Characteristic Phrases: " + ", ".join(gsc.characteristic_phrases))

        if det.exact_signoff:
            parts.append(f"Exact Sign-off: {det.exact_signoff}")
        if det.top_greetings:
            top_greeting = det.top_greetings[0].pattern
            parts.append(f"Primary Greeting: {top_greeting}")

        # Global learned rules
        if profile.global_learned_rules:
            parts.append("Global Learned Rules: " + "; ".join(profile.global_learned_rules))

        return "\n".join(parts)

    def _format_recipient_profile(self, profile: RecipientProfile | None, recipient_email: str) -> str:
        """Format recipient-specific profile for the audience topology section."""
        if not profile:
            return f"Recipient: {recipient_email} (no prior history - first contact)"

        parts = [
            f"Recipient: {recipient_email}",
            f"Relationship Tier: {profile.relationship_tier}",
            f"Prior Emails Sent: {profile.sent_count}",
        ]
        if profile.preferred_greeting:
            parts.append(f"Preferred Greeting: {profile.preferred_greeting}")
        if profile.learned_rules_json:
            parts.append("Recipient-Specific Learned Rules: " + "; ".join(profile.learned_rules_json))
        return "\n".join(parts)

    def _format_audience_topology(
        self,
        to_recipients: list[str],
        cc_recipients: list[str],
        bcc_recipients: list[str],
        profile: UserStyleProfile,
    ) -> str:
        """Build the Audience Topology section for the system prompt."""
        parts = ["=== AUDIENCE TOPOLOGY ==="]

        # Primary Addressee (To)
        primary_to = to_recipients[0] if to_recipients else ""
        recipient_profile = None
        if primary_to:
            # Try to load recipient profile from storage
            pass  # Will be filled in by generate_draft

        parts.append(f"Primary Addressee (To): {primary_to}")
        if recipient_profile:
            parts.append(self._format_recipient_profile(recipient_profile, primary_to))

        # Visible Observers (Cc)
        if cc_recipients:
            parts.append(f"\nVisible Observers (Cc): {len(cc_recipients)} recipient(s)")
            for cc in cc_recipients:
                parts.append(f"  - {cc}")
            parts.append(
                "INSTRUCTION: Visible CC recipients are present—write for a shared multi-stakeholder audience "
                "rather than a private 1-on-1 exchange; keep context self-contained and avoid private shorthand."
            )
        else:
            parts.append("\nVisible Observers (Cc): None")

        # Hidden Recipients (Bcc)
        if bcc_recipients:
            parts.append(f"\nHidden Recipients (Bcc): {len(bcc_recipients)} recipient(s) - addresses hidden from To/Cc")
            parts.append(
                "INSTRUCTION: BCC recipients are hidden from To/CC—do not address or mention them in the email body."
            )
        else:
            parts.append("\nHidden Recipients (Bcc): None")

        return "\n".join(parts)

    def _format_reference_examples(self, examples: list[dict[str, Any]]) -> str:
        """Format retrieved few-shot examples for the prompt."""
        if not examples:
            return "No reference examples available."

        formatted = []
        for i, ex in enumerate(examples, 1):
            greeting = ex.get("greeting", "")
            signoff = ex.get("signoff", "")
            body = ex.get("clean_body", "")
            subject = ex.get("subject", "")
            audience_mode = ex.get("audience_mode", "1on1_private")
            formatted.append(
                f"Reference Example {i} (to {ex.get('recipient_email', 'unknown')} [{audience_mode}]):\n"
                f"Subject: {subject}\n"
                f"Body: {body}\n"
                f"Greeting: {greeting}\n"
                f"Sign-off: {signoff}"
            )
        return "\n\n".join(formatted)

    def _build_system_prompt(
        self,
        profile: UserStyleProfile,
        examples: list[dict[str, Any]],
        to_recipients: list[str],
        cc_recipients: list[str],
        bcc_recipients: list[str],
        recipient_profiles: dict[str, RecipientProfile] | None = None,
    ) -> str:
        """Build the complete system prompt with style profile, audience topology, and reference examples."""
        style_text = self._format_style_profile(profile)

        # Build recipient profiles dict for audience topology
        if recipient_profiles is None:
            recipient_profiles = {}

        audience_topology = self._format_audience_topology(to_recipients, cc_recipients, bcc_recipients, profile)
        examples_text = self._format_reference_examples(examples)

        return (
            f"{self.SYSTEM_PROMPT_TEMPLATE}\n\n"
            f"=== USER STYLE PROFILE ===\n{style_text}\n\n"
            f"{audience_topology}\n\n"
            f"=== REFERENCE EXAMPLES FROM USER'S PAST SENT EMAILS ===\n{examples_text}"
        )

    def _build_user_prompt(
        self,
        intent_bullets: str,
        incoming_context: str | None = None,
    ) -> str:
        """Build the user prompt with optional incoming context and intent bullets."""
        parts = []
        if incoming_context:
            parts.append(f"Incoming Email Context:\n{incoming_context}\n")
        parts.append("Draft an email covering these points:\n" + intent_bullets)
        return "\n".join(parts)

    def _repair_json(self, content: str) -> str:
        """Remove markdown fences and extract the email draft."""
        cleaned = re.sub(r"^```(?:json)?\s*", "", content.strip(), flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned, flags=re.IGNORECASE)

        try:
            data = json.loads(cleaned)
            if isinstance(data, dict):
                for field in ("email", "draft", "email_output", "chosen_email", "body"):
                    if field in data and data[field]:
                        return str(data[field])
        except json.JSONDecodeError:
            pass

        return cleaned.strip()

    def _post_process_draft(self, draft: str, profile: UserStyleProfile) -> str:
        """Clean up the draft and ensure it respects the user's sign-off habit."""
        draft = re.sub(r"<\|im_end\|>", "", draft)
        draft = re.sub(r"<\|im_start\|>", "", draft)
        draft = re.sub(r"<\|.*?\|>", "", draft)

        exact_signoff = profile.deterministic_stylometry.exact_signoff
        if exact_signoff:
            lines = draft.rstrip().splitlines()
            while lines and lines[-1].strip():
                last = lines[-1].strip().lower()
                if any(last.startswith(s) for s in ("best", "regards", "thanks", "cheers", "sincerely", "respectfully")):
                    lines.pop()
                else:
                    break
            draft = "\n".join(lines).rstrip()
            if not draft.endswith(exact_signoff):
                draft = draft + "\n\n" + exact_signoff

        return draft.strip()

    def generate_draft(
        self,
        profile: UserStyleProfile,
        cleaned_emails: list[CleanedSentEmail],
        intent_bullets: str,
        recipient_email: str | None = None,
        incoming_context: str | None = None,
        model_name: str | None = None,
        cc_recipients: list[str] | None = None,
        bcc_recipients: list[str] | None = None,
        recipient_profiles: dict[str, RecipientProfile] | None = None,
    ) -> str:
        """Generate a personalized email draft with audience topology."""
        to_recipients = [recipient_email] if recipient_email else []
        cc_recipients = cc_recipients or []
        bcc_recipients = bcc_recipients or []

        # Retrieve few-shot examples
        query_text = " ".join([incoming_context or "", intent_bullets]).strip()
        recipient_domain = None
        if recipient_email:
            recipient_domain = recipient_email.split("@")[-1] if "@" in recipient_email else None

        # Determine target audience mode based on CC/BCC
        target_audience_mode: AudienceMode = "1on1_private"
        if cc_recipients:
            target_audience_mode = "group_cc"
        elif bcc_recipients and len(bcc_recipients) >= 2:
            target_audience_mode = "broadcast_bcc"

        examples = self.vector_store.retrieve_few_shot_examples(
            embedder=self.embedder,
            recipient_email=recipient_email,
            recipient_domain=recipient_domain,
            query_text=query_text,
            k=2,
            target_audience_mode=target_audience_mode,
        )

        # Build prompts with audience topology
        system_prompt = self._build_system_prompt(
            profile, examples, to_recipients, cc_recipients, bcc_recipients, recipient_profiles
        )
        user_prompt = self._build_user_prompt(intent_bullets, incoming_context)

        # Try Ollama first with think=False (fast drafting mode)
        if model_name is None:
            model_name = self.settings.model_name

        for candidate_model in self.settings.ollama_models:
            try:
                return self._generate_with_ollama(
                    model_name=candidate_model,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    profile=profile,
                    think=False,  # Fast drafting mode
                )
            except DrafterUnavailable:
                continue

        # Fallback to transformers if available
        if (self.settings.exported_model_dir / "config.json").is_file():
            try:
                return self._generate_with_transformers(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    profile=profile,
                )
            except DrafterUnavailable:
                pass

        raise DrafterUnavailable("No local inference runtime available for draft generation")

    def _generate_with_ollama(
        self,
        model_name: str,
        system_prompt: str,
        user_prompt: str,
        profile: UserStyleProfile,
        think: bool = False,
    ) -> str:
        """Generate draft using local Ollama with think parameter."""
        endpoint = f"{self.settings.ollama_url.rstrip('/')}/api/chat"
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        options = {
            "temperature": 0.7 if not think else 0.6,
            "top_p": 0.8 if not think else 0.95,
            "top_k": 20,
            "num_ctx": self.settings.ollama_num_ctx,
        }
        if think:
            options["think"] = True

        try:
            response = httpx.post(
                endpoint,
                json={
                    "model": model_name,
                    "messages": messages,
                    "stream": False,
                    "options": options,
                },
                timeout=180 if think else 120,
            )
        except httpx.HTTPError as exc:
            # Ollama not running / unreachable is a "no runtime" condition, not a crash.
            raise DrafterUnavailable(f"Ollama unreachable at {endpoint}: {exc}") from exc

        if response.status_code == 404:
            raise DrafterUnavailable(f"Ollama model '{model_name}' not installed")
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise DrafterUnavailable(f"Ollama request for '{model_name}' failed: {exc}") from exc

        result = response.json()
        content = result.get("message", {}).get("content", "")

        # Strip thinking blocks if present (qwen3 thinking mode)
        if think and "<think>" in content and "</think>" in content:
            # Extract only the non-thinking part
            content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()

        if not content:
            raise DrafterUnavailable("Ollama returned empty response")

        draft = self._repair_json(content)
        return self._post_process_draft(draft, profile)

    def _generate_with_transformers(
        self,
        system_prompt: str,
        user_prompt: str,
        profile: UserStyleProfile,
    ) -> str:
        """Generate draft using local Transformers model."""
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
            from peft import PeftModel
        except ImportError as exc:
            raise DrafterUnavailable(f"Transformers dependencies not available: {exc}")

        tokenizer = AutoTokenizer.from_pretrained(
            "Qwen/Qwen2.5-3B-Instruct", trust_remote_code=True
        )

        base_model = AutoModelForCausalLM.from_pretrained(
            "Qwen/Qwen2.5-3B-Instruct",
            dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32,
            device_map="auto" if torch.cuda.is_available() else None,
            trust_remote_code=True,
            low_cpu_mem_usage=True,
        )

        adapter_path = self.settings.adapter_model_dir
        if not (adapter_path / "adapter_config.json").exists():
            adapter_path = self.settings.project_root / "checkpoints" / "qwen-email-sft-best"

        if (adapter_path / "adapter_config.json").exists():
            model = PeftModel.from_pretrained(base_model, str(adapter_path))
            model = model.merge_and_unload()
        else:
            model = base_model

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        prompt = tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )

        device = next(model.parameters()).device
        inputs = tokenizer(prompt, return_tensors="pt").to(device)

        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=512,
                temperature=0.7,
                top_p=0.9,
                do_sample=True,
                repetition_penalty=1.1,
                pad_token_id=tokenizer.eos_token_id,
            )

        generated_ids = outputs[0][inputs["input_ids"].shape[1] :]
        content = tokenizer.decode(generated_ids, skip_special_tokens=True).strip()

        draft = self._repair_json(content)
        return self._post_process_draft(draft, profile)