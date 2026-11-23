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

    SYSTEM_PROMPT_TEMPLATE = """You are a personalized email writer. Adopt the persona and style profile provided in the prompt, write concise, high-impact emails, and avoid corporate AI clichés (such as 'I hope this email finds you well', 'delve', 'tapestry', 'furthermore').

Write plain-text human emails ONLY. Never use Markdown formatting (**bold**, *italics*, ### headings, code blocks).

Write flowing, conversational paragraphs the way a person would actually type the email. NEVER write report, ticket, or memo headings and NEVER write field labels such as "Project Deadline", "Severity Score", "SLA allowed hours", "Request", "Confirmation", "Outstanding Issues", "Action Items", "Summary", "Priority", "Status" or "Next Steps". Put that information into ordinary sentences instead.

Use the reference emails ONLY to match tone, cadence, greeting, and sign-off. NEVER copy facts, metrics, severity scores, SLA hours, or unrelated details from reference emails or templates."""

    #: Report/ticket labels that must never survive as headings in a drafted email.
    REPORT_HEADING_LABELS = {
        "project deadline", "deadline", "severity score", "severity", "sla allowed hours",
        "sla", "outstanding issues", "outstanding issue", "action items", "action item",
        "next steps", "impact", "resolution", "category", "priority", "timeline",
        "assigned to", "reported by", "reference id", "ticket id", "issue date",
        "request", "confirmation", "summary", "status", "subject", "re",
    }

    #: Labels whose value reads better as a plain sentence than as "The X is Y".
    REPORT_HEADING_VALUE_ONLY_LABELS = {
        "request", "confirmation", "summary", "status", "subject", "re", "issue date",
    }

    #: Labels whose *standalone* form is a report artefact and is dropped.
    #: Ambiguous words (subject, status, summary, request, …) are only rewritten
    #: when they carry a value, so plain headings keep their text.
    REPORT_HEADING_DROP_IF_BARE = {
        "project deadline", "deadline", "severity score", "severity", "sla allowed hours",
        "sla", "outstanding issues", "outstanding issue", "action items", "action item",
        "next steps", "impact", "resolution", "category", "priority", "timeline",
        "assigned to", "reported by", "reference id", "ticket id",
    }

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.embedder = LocalEmbedder()
        self.vector_store = LanceDBVectorStore(settings)

    def availability(self) -> dict[str, Any]:
        """Report local inference availability."""
        ollama_models = []
        ollama_error = ""
        try:
            response = httpx.get(f"{self.settings.ollama_url.rstrip('/')}/api/tags", timeout=5.0)
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

    def _resolve_first_name(self, recipient_email: str, recipient_profiles: dict[str, RecipientProfile] | None) -> str:
        """Resolve the recipient's first name from profile or derive from email local-part.
        
        Returns a clean first name if clearly alphabetic; empty string if unknown (like kamisama7892@gmail.com).
        """
        if not recipient_email:
            return ""
        
        # Try to get from recipient profile first
        if recipient_profiles:
            profile = recipient_profiles.get(recipient_email.lower())
            if profile and profile.preferred_greeting:
                # Extract name from preferred greeting like "Hi Jatin," or "Hello Jatin"
                match = re.search(r"(?:hi|hello|dear)\s+([A-Za-z]+)", profile.preferred_greeting, re.IGNORECASE)
                if match:
                    return match.group(1).strip()
        
        # Derive from email local-part, but only if clearly alphabetic
        local = recipient_email.split("@")[0] if "@" in recipient_email else recipient_email
        # Split on common separators and take the first token
        for separator in (".", "_", "-", "+"):
            local = local.split(separator)[0]
        
        # Only return if it looks like a real name (alphabetic, reasonable length)
        if local.isalpha() and 2 <= len(local) <= 20:
            return local.capitalize()
        
        return ""

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
                "INSTRUCTION: Visible CC recipients are present\u2014write for a shared multi-stakeholder audience "
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
        """Format retrieved few-shot examples for the prompt as STYLE-ONLY examples."""
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
                f"=== STYLE-ONLY EXAMPLE {i} (to {ex.get('recipient_email', 'unknown')} [{audience_mode}]) ===\n"
                f"Subject: {subject}\n"
                f"Body: {body}\n"
                f"Greeting: {greeting}\n"
                f"Sign-off: {signoff}\n"
                f"[USE THIS EXAMPLE ONLY FOR TONE, GREETING STYLE, AND SIGN-OFF PATTERN. DO NOT COPY FACTS, METRICS, OR CONTENT.]"
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
        first_name: str = "",
    ) -> str:
        """Build the complete system prompt with style profile, audience topology, and reference examples."""
        style_text = self._format_style_profile(profile)

        # Build recipient profiles dict for audience topology
        if recipient_profiles is None:
            recipient_profiles = {}

        audience_topology = self._format_audience_topology(to_recipients, cc_recipients, bcc_recipients, profile)
        examples_text = self._format_reference_examples(examples)

        # Resolve greeting with first_name
        greeting_instruction = ""
        if profile.deterministic_stylometry.top_greetings:
            top_greeting = profile.deterministic_stylometry.top_greetings[0].pattern
            if "{first_name}" in top_greeting:
                resolved_greeting = top_greeting.replace("{first_name}", first_name) if first_name else top_greeting.replace("{first_name}", "").strip()
                # Clean up any double spaces or trailing commas
                resolved_greeting = re.sub(r"\s+", " ", resolved_greeting).strip()
                resolved_greeting = re.sub(r",\s*,", ",", resolved_greeting)
                greeting_instruction = f"\nPRIMARY GREETING TO USE: {resolved_greeting}"
            else:
                greeting_instruction = f"\nPRIMARY GREETING TO USE: {top_greeting}"

        return (
            f"{self.SYSTEM_PROMPT_TEMPLATE}\n\n"
            f"=== USER STYLE PROFILE ===\n{style_text}\n\n"
            f"{audience_topology}\n\n"
            f"=== REFERENCE EXAMPLES FROM USER'S PAST SENT EMAILS (STYLE ONLY) ===\n{examples_text}"
            f"{greeting_instruction}"
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

    def _strip_report_headings(self, draft: str) -> str:
        """Rewrite report/ticket label lines as plain conversational sentences.

        ``Project Deadline: Monday`` becomes ``The project deadline is Monday.`` and a
        bare ``Request``/``Outstanding Issues`` heading is dropped; ordinary prose is
        left untouched.
        """
        lines = draft.split("\n")
        rewritten: list[str] = []
        for index, raw_line in enumerate(lines):
            stripped = raw_line.strip()
            if not stripped:
                rewritten.append(raw_line)
                continue
            candidate = re.sub(r"^(?:[-*•]|\d+[.)])\s*", "", stripped).strip()
            candidate = candidate.replace("**", "").strip()
            if not candidate:
                rewritten.append(raw_line)
                continue
            match = re.match(r"^(?P<label>[A-Za-z][A-Za-z0-9 /&]{1,40}?)\s*:\s*(?P<value>.+)$", candidate)
            if match:
                label = match.group("label").strip().lower()
                value = match.group("value").strip()
                if label in self.REPORT_HEADING_LABELS:
                    if not value:
                        continue  # label-only heading -> drop it
                    if label in self.REPORT_HEADING_VALUE_ONLY_LABELS:
                        sentence = value if value.endswith((".", "!", "?")) else f"{value}."
                    else:
                        sentence = f"The {label} is {value}"
                        sentence = sentence if sentence.endswith((".", "!", "?")) else f"{sentence}."
                    rewritten.append(sentence[0].upper() + sentence[1:])
                    continue
            bare = candidate.lower().rstrip(":")
            if len(candidate) <= 40 and bare in self.REPORT_HEADING_DROP_IF_BARE:
                continue  # standalone report heading -> drop it
            # An ambiguous label ("Request", "Summary", …) is only a heading when it
            # introduces a list; "Subject" over prose stays as prose.
            if len(candidate) <= 40 and bare in self.REPORT_HEADING_VALUE_ONLY_LABELS:
                following = ""
                for lookahead in lines[index + 1:]:
                    if lookahead.strip():
                        following = lookahead.strip()
                        break
                if following.startswith(("-", "*", "•")) or re.match(r"^\d+[.)]\s", following):
                    continue  # label introducing a list -> drop it
            rewritten.append(raw_line)
        return "\n".join(rewritten)

    def _post_process_draft(self, draft: str, profile: UserStyleProfile) -> str:
        """Clean up the draft: strip placeholders, markdown, leading Subject:, report headings, and deduplicate sign-off."""
        # Remove special tokens
        draft = re.sub(r"<\|im_end\|>", "", draft)
        draft = re.sub(r"<\|im_start\|>", "", draft)
        draft = re.sub(r"<\|.*?\|>", "", draft)

        # Strip leading "Subject:" line if present
        lines = draft.splitlines()
        while lines and lines[0].strip().lower().startswith("subject:"):
            lines.pop(0)
        # Also strip any leading blank lines after subject removal
        while lines and not lines[0].strip():
            lines.pop(0)
        draft = "\n".join(lines)

        # Strip markdown bold/heading markers
        draft = re.sub(r"\*\*(.+?)\*\*", r"\1", draft)  # **bold** -> bold
        draft = re.sub(r"^#{1,6}\s*(.+)$", r"\1", draft, flags=re.MULTILINE)  # ### heading -> heading
        draft = re.sub(r"`(.+?)`", r"\1", draft)  # `code` -> code

        # Strip common placeholders
        placeholders = [
            r"\{first_name\}",
            r"\[Name\]",
            r"\[Recipient\]",
            r"\(date if known\)",
            r"\[Date\]",
            r"\{date\}",
        ]
        for ph in placeholders:
            draft = re.sub(ph, "", draft, flags=re.IGNORECASE)

        # Report/ticket headings must not survive as headings in a human email.
        draft = self._strip_report_headings(draft)

        # Deduplicate sign-off
        exact_signoff = profile.deterministic_stylometry.exact_signoff
        if exact_signoff:
            lines = draft.rstrip().splitlines()
            # Remove any existing closing phrases at the end (check last few lines as a block)
            closing_phrases = ("regards", "best", "thanks", "cheers", "sincerely", "respectfully", "kind regards", "warm regards")
            
            # Keep removing trailing lines that look like closing phrases or names following them
            # We need to check from the end backwards for sign-off blocks
            i = len(lines) - 1
            while i >= 0:
                line = lines[i].strip().lower()
                if any(line.startswith(s) for s in closing_phrases):
                    # Found a closing phrase - remove this line and potentially the next one (name)
                    lines.pop(i)
                    # After removing closing phrase, check if the new last line (which was the next line)
                    # looks like a name - if so, remove it too
                    if i < len(lines):
                        next_line = lines[i].strip()
                        if next_line and not any(next_line.lower().startswith(s) for s in closing_phrases):
                            # Heuristic: if it's short and looks like a name, remove it
                            if len(next_line) <= 40 and re.match(r"^[A-Za-z\s\.\-']+$", next_line):
                                lines.pop(i)
                    i -= 1  # Continue checking earlier lines
                else:
                    i -= 1
            
            # Now check if the exact_signoff is already present at the end (as a block)
            draft_wo_trailing = "\n".join(lines).rstrip()
            if not draft_wo_trailing.endswith(exact_signoff.rstrip()):
                draft = draft_wo_trailing + "\n\n" + exact_signoff
            else:
                draft = draft_wo_trailing
        else:
            # No exact_signoff defined, just remove trailing closing phrases
            lines = draft.rstrip().splitlines()
            closing_phrases = ("regards", "best", "thanks", "cheers", "sincerely", "respectfully", "kind regards", "warm regards")
            while lines and lines[-1].strip():
                last = lines[-1].strip().lower()
                if any(last.startswith(s) for s in closing_phrases):
                    lines.pop()
                else:
                    break
            draft = "\n".join(lines).rstrip()

        # Collapse multiple consecutive blank lines to at most 2
        draft = re.sub(r"\n{3,}", "\n\n", draft)

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

        # Resolve first_name for greeting
        first_name = self._resolve_first_name(recipient_email or "", recipient_profiles or {})

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
            profile, examples, to_recipients, cc_recipients, bcc_recipients, recipient_profiles, first_name
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

    def revise_email_draft(
        self,
        profile: UserStyleProfile,
        subject: str,
        body: str,
        tweak_instruction: str,
        to_recipients: list[str],
        cc_recipients: list[str],
        bcc_recipients: list[str],
    ) -> dict[str, str]:
        """Revise only the content/tone of a pending email and return subject/body JSON."""
        endpoint = f"{self.settings.ollama_url.rstrip('/')}/api/chat"
        system_prompt = (
            "You revise an existing email draft. Apply only the user's requested tone/content change. "
            "Preserve facts, commitments, dates, recipients, and audience topology. Do not add boilerplate, "
            "SLA/severity blocks, new claims, or unrelated content. Return only JSON with string keys subject and body.\n\n"
            "Write plain-text human emails ONLY. Never use Markdown formatting (**bold**, *italics*, ### headings, code blocks).\n\n"
            "Write flowing, conversational paragraphs. Never write report/ticket headings or field labels such as "
            '"Project Deadline", "Severity Score", "SLA allowed hours", "Request", "Confirmation" or "Outstanding Issues".\n\n'
            f"USER STYLE PROFILE:\n{self._format_style_profile(profile)}"
        )
        user_prompt = (
            f"To: {', '.join(to_recipients)}\nCc: {', '.join(cc_recipients)}\n"
            f"Bcc: {', '.join(bcc_recipients)}\n\nCurrent subject:\n{subject}\n\n"
            f"Current body:\n{body}\n\nUser's revision instruction:\n{tweak_instruction}\n\n"
            'Return exactly {"subject":"...","body":"..."}.'
        )
        last_error = "No local inference runtime available for draft revision"
        for model_name in self.settings.ollama_models:
            try:
                response = httpx.post(
                    endpoint,
                    json={
                        "model": model_name,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        "format": "json",
                        "think": False,
                        "stream": False,
                        "options": {"temperature": 0.2, "top_p": 0.8, "top_k": 20, "num_ctx": self.settings.ollama_num_ctx},
                    },
                    timeout=120,
                )
                if response.status_code == 404:
                    last_error = f"Ollama model '{model_name}' not installed"
                    continue
                response.raise_for_status()
                content = response.json().get("message", {}).get("content", "")
                content = re.sub(r"thinking.*?\*/", "", content, flags=re.DOTALL).strip()
                start, end = content.find("{"), content.rfind("}")
                if start < 0 or end < start:
                    raise ValueError("Model response did not contain a JSON object.")
                revised = json.loads(content[start:end + 1])
                revised_subject = revised.get("subject")
                revised_body = revised.get("body")
                if not isinstance(revised_subject, str) or not isinstance(revised_body, str):
                    raise ValueError("Model response must contain string subject and body fields.")
                # Post-process the revised body too
                revised_body = self._post_process_draft(revised_body, profile)
                return {"subject": revised_subject.strip(), "body": revised_body.strip()}
            except (httpx.HTTPError, ValueError, TypeError) as exc:
                last_error = str(exc)
        raise DrafterUnavailable(f"Draft revision failed: {last_error}")

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
        if think and "thinking" in content and "*/" in content:
            # Extract only the non-thinking part
            content = re.sub(r"thinking.*?\*/", "", content, flags=re.DOTALL).strip()

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
                pad_token_id=tokenizer.eol_token_id,
            )

        generated_ids = outputs[0][inputs["input_ids"].shape[1] :]
        content = tokenizer.decode(generated_ids, skip_special_tokens=True).strip()

        draft = self._repair_json(content)
        return self._post_process_draft(draft, profile)
