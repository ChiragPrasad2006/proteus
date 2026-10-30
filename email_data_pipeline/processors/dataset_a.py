"""
email_data_pipeline.processors.dataset_a
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Processor for Dataset A (argilla/FinePersonas-Synthetic-Email-Conversations
or FinePersonas instruction/conversation subsets).
Performs case-insensitive regex filtering for email keywords, text cleaning,
de-slopping, style extraction, and formatting for Qwen SFT.
"""

import logging
import re
import time
from typing import Any, Dict, Generator, List, Optional
from datasets import load_dataset

from ..config import PipelineConfig, EMAIL_KEYWORDS_REGEX
from ..deduplication.deduplicator import Deduplicator
from ..filters.deslop import contains_ai_slop, clean_markdown_and_html, is_valid_email_candidate
from ..filters.text_cleaner import matches_email_keywords
from ..filters.persona_filter import sanitize_persona_description
from ..synthesis.style_extractor import extract_style_metadata, extract_user_intent_bullets
from .base import BaseDatasetProcessor

logger = logging.getLogger("email_data_pipeline.dataset_a")


class DatasetAProcessor(BaseDatasetProcessor):
    """
    Downloads, filters, cleans, and formats FinePersonas email data.
    Streamed or batched with memory constraints (16GB RAM limit).
    """

    def __init__(self, config: PipelineConfig, deduplicator: Deduplicator):
        super().__init__(config, deduplicator)
        self.dataset_name = config.dataset_a_name

    def process(self) -> Generator[Dict[str, Any], None, None]:
        """
        Loads the dataset in streaming mode, applies batched filtering/cleaning,
        and yields standard Hugging Face SFT messages rows.
        """
        logger.info("Loading Dataset A: %s", self.dataset_name)

        dataset = None
        for attempt in range(6):
            try:
                # Stream the dataset to preserve memory
                dataset = load_dataset(self.dataset_name, split="train", streaming=True)
                break
            except Exception as e:
                wait = 5.0 * (attempt + 1)
                logger.warning("Hub load attempt %d for %s failed (%s). Retrying in %.0fs ...", attempt + 1, self.dataset_name, e, wait)
                time.sleep(wait)
        if dataset is None:
            self.dataset_name = self.config.dataset_a_fallback
            logger.warning("Primary source failed after retries. Trying fallback %s", self.dataset_name)
            dataset = self._load_with_retry(self.dataset_name, None)
        if dataset is None:
            logger.error("Could not load Dataset A fallback: %s", self.dataset_name)
            return

        for row in dataset:
            self.total_processed += 1
            if self.config.max_samples_a and self.total_accepted >= self.config.max_samples_a:
                logger.info("Dataset A reached target sample limit (%d).", self.config.max_samples_a)
                break

            items = self._extract_email_records(row)
            for item in items:
                formatted = self._format_and_validate(item)
                if formatted:
                    self.total_accepted += 1
                    yield formatted
                    if self.config.max_samples_a and self.total_accepted >= self.config.max_samples_a:
                        break

    def _load_with_retry(self, name: str, subset: Optional[str]) -> Any:
        """Loads a hub dataset with retry/backoff to survive transient DNS/network failures."""
        last_err: Exception = RuntimeError("unavailable")
        for attempt in range(5):
            try:
                return load_dataset(name, split="train", streaming=True)
            except Exception as e:  # noqa: BLE001
                last_err = e
                wait = 5.0 * (attempt + 1)
                logger.warning("Hub load attempt %d failed (%s). Retrying in %.0fs ...", attempt + 1, e, wait)
                time.sleep(wait)
        logger.error("Could not load %s after retries: %s", name, last_err)
        return None

    def _extract_email_records(self, row: Dict[str, Any]) -> List[Dict[str, str]]:
        """Extracts individual email units from varying dataset schemas."""
        records = []
        persona = sanitize_persona_description(row.get("persona") or "A professional workplace communicator.")

        # Schema 1: Synthetic Email Conversations with formatted_emails list
        if "formatted_emails" in row and isinstance(row["formatted_emails"], list):
            for email_entry in row["formatted_emails"]:
                if isinstance(email_entry, dict):
                    body = email_entry.get("body", "")
                    subject = email_entry.get("subject", "")
                    full_text = f"Subject: {subject}\n\n{body}" if subject else body
                    records.append({"persona": persona, "email_text": full_text})

        # Schema 2: Raw emails text block
        elif "raw_emails" in row and isinstance(row["raw_emails"], str):
            raw = row["raw_emails"]
            # Split emails on <email> tags or email boundaries
            parts = re.split(r"<\s*/?\s*email\s*>", raw, flags=re.IGNORECASE)
            for p in parts:
                p_clean = p.strip()
                if len(p_clean) >= self.config.min_email_chars:
                    records.append({"persona": persona, "email_text": p_clean})

        # Schema 3: Generic Instruction / Response format
        elif "instruction" in row and "response" in row:
            inst = row["instruction"]
            resp = row["response"]
            if matches_email_keywords(inst) or matches_email_keywords(resp):
                records.append({
                    "persona": persona,
                    "email_text": resp,
                    "instruction": inst,
                })

        # Schema 4: Persona only (fallback)
        elif "persona" in row and not any(k in row for k in ["formatted_emails", "raw_emails", "response"]):
            # Persona row without built-in emails
            pass

        return records

    def _format_and_validate(self, item: Dict[str, str]) -> Optional[Dict[str, Any]]:
        """Filters, cleans, de-slops, and creates standard SFT message schema."""
        raw_email = item.get("email_text", "")
        persona = item.get("persona", "A seasoned professional.")

        # 1. Email Keyword Filter (case-insensitive regex for keywords:
        # 'email', 'subject:', 'dear ', 'sincerely', 'best regards', 'follow-up', 'cold outreach', 'reply to')
        if not matches_email_keywords(raw_email):
            # Check if instruction has it
            inst = item.get("instruction", "")
            if not matches_email_keywords(inst):
                self.total_dropped += 1
                return None

        # 2. Markdown & HTML Cleaning
        clean_email = clean_markdown_and_html(raw_email)

        # 3. Minimum Character Filter
        if not is_valid_email_candidate(clean_email, min_chars=self.config.min_email_chars):
            self.total_dropped += 1
            self.dropped_for_length += 1
            return None

        # 4. Regex De-Slopping: DROP if assistant email contains robotic AI buzzwords
        if contains_ai_slop(clean_email):
            self.total_dropped += 1
            self.dropped_for_slop += 1
            return None

        # 5. Extract Style Profile and 3 Intent Bullets
        style_meta = extract_style_metadata(clean_email, persona)
        style_profile_str = style_meta.to_profile_string()
        user_intent_bullets = extract_user_intent_bullets(clean_email)

        # 6. Construct Target Prompt & Assistant Output
        system_content = (
            f"You are a personalized email writer. Adopt this persona and style:\n"
            f"Persona: {persona}\n"
            f"Style Profile: {style_profile_str}"
        )
        user_content = f"Draft an email covering these points:\n{user_intent_bullets}"
        assistant_content = clean_email

        # 7. Deduplication Check
        if self.deduplicator.check_and_add(user_content, assistant_content):
            self.total_dropped += 1
            self.dropped_for_dupe += 1
            return None

        # Standard Hugging Face ChatML SFT format
        return {
            "messages": [
                {"role": "system", "content": system_content},
                {"role": "user", "content": user_content},
                {"role": "assistant", "content": assistant_content},
            ]
        }
