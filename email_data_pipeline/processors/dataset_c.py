"""
email_data_pipeline.processors.dataset_c
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Processor for Dataset C (argilla/distilabel-capybara-dpo-7k-binarized).
Filters for writing, communication, rewriting, and tone tasks (excluding math/coding),
restricts to single-turn or short multi-turn conversations,
enforces absence of AI slop in 'chosen', and penalizes/augments AI slop in 'rejected'.
Outputs format compatible with TRL DPOTrainer.
"""

import logging
import re
import time
from typing import Any, Dict, Generator, List, Optional, Tuple
from datasets import load_dataset

from ..config import (
    PipelineConfig,
    WRITING_TASK_INCLUDE_REGEX,
    CODE_MATH_EXCLUDE_REGEX,
)
from ..deduplication.deduplicator import Deduplicator
from ..filters.deslop import (
    contains_ai_slop,
    clean_markdown_and_html,
    inject_robotic_slop,
    is_valid_email_candidate,
)
from .base import BaseDatasetProcessor

logger = logging.getLogger("email_data_pipeline.dataset_c")


class DatasetCProcessor(BaseDatasetProcessor):
    """
    Downloads, filters, cleans, and formats Capybara DPO pairs for TRL DPOTrainer.
    """

    def __init__(self, config: PipelineConfig, deduplicator: Deduplicator):
        super().__init__(config, deduplicator)
        self.dataset_name = config.dataset_c_name
        self.slop_augmented_count: int = 0
        self.natural_slop_pairs_count: int = 0

    def process(self) -> Generator[Dict[str, str], None, None]:
        """Loads and processes Capybara DPO dataset in streaming mode."""
        logger.info("Loading Dataset C: %s", self.dataset_name)

        dataset = None
        for attempt in range(6):
            try:
                dataset = load_dataset(self.dataset_name, split="train", streaming=True)
                break
            except Exception as e:
                wait = 5.0 * (attempt + 1)
                logger.warning("Hub load attempt %d failed (%s). Retrying in %.0fs ...", attempt + 1, e, wait)
                time.sleep(wait)
        if dataset is None:
            logger.error("Could not load Dataset C: %s", self.dataset_name)
            return

        for row in dataset:
            self.total_processed += 1
            if self.config.max_samples_c and self.total_accepted >= self.config.max_samples_c:
                logger.info("Dataset C reached target sample limit (%d).", self.config.max_samples_c)
                break

            dpo_item = self._extract_and_filter(row)
            if dpo_item:
                self.total_accepted += 1
                yield dpo_item
                if self.config.max_samples_c and self.total_accepted >= self.config.max_samples_c:
                    break

    def _extract_and_filter(self, row: Dict[str, Any]) -> Optional[Dict[str, str]]:
        """Extracts prompt, chosen, and rejected texts; filters and enforces DPO anti-slop pair logic."""
        prompt_text = ""
        chosen_text = ""
        rejected_text = ""

        raw_chosen = row.get("chosen")
        raw_rejected = row.get("rejected")
        raw_prompt = row.get("prompt")

        # Handle list-of-turns schema (e.g. standard distilabel / Capybara format)
        if isinstance(raw_chosen, list) and isinstance(raw_rejected, list):
            # Short-ish multi-turn restriction (at most 6 full turns = 12 messages;
            # Capybara conversations are naturally long, so keep a usable window)
            if len(raw_chosen) > 12 or len(raw_rejected) > 12:
                self.total_dropped += 1
                return None

            # Extract the final assistant responses
            if not raw_chosen or not raw_rejected:
                self.total_dropped += 1
                return None

            # Last turn must be assistant
            last_c = raw_chosen[-1]
            last_r = raw_rejected[-1]
            if last_c.get("role") != "assistant" or last_r.get("role") != "assistant":
                self.total_dropped += 1
                return None

            chosen_text = last_c.get("content", "")
            rejected_text = last_r.get("content", "")

            # Format preceding context as the prompt
            preceding_turns = raw_chosen[:-1]
            if len(preceding_turns) == 1:
                prompt_text = preceding_turns[0].get("content", "")
            elif len(preceding_turns) > 1:
                # Format multi-turn prompt using clean ChatML markers
                formatted_turns = []
                for turn in preceding_turns:
                    role = turn.get("role", "user")
                    content = turn.get("content", "")
                    formatted_turns.append(f"<|im_start|>{role}\n{content}<|im_end|>")
                formatted_turns.append("<|im_start|>assistant\n")
                prompt_text = "\n".join(formatted_turns)
            else:
                prompt_text = str(raw_prompt or "")
        else:
            prompt_text = str(raw_prompt or "")
            chosen_text = str(raw_chosen or "")
            rejected_text = str(raw_rejected or "")

        # 1. Clean markdown and HTML
        clean_prompt = clean_markdown_and_html(prompt_text)
        clean_chosen = clean_markdown_and_html(chosen_text)
        clean_rejected = clean_markdown_and_html(rejected_text)

        if not clean_prompt or not clean_chosen or not clean_rejected:
            self.total_dropped += 1
            return None

        # 2. Exclude Pure Coding, Math, and Logic Puzzles
        combined_text = f"{clean_prompt}\n{clean_chosen}"
        if CODE_MATH_EXCLUDE_REGEX.search(combined_text):
            self.total_dropped += 1
            return None

        # 3. Include Writing, Communication, Tone, Rewriting, Summary tasks
        source = str(row.get("source") or "").lower()
        is_writing_source = any(s in source for s in ["airoboros", "capybara", "writing", "communication"])
        matches_writing = bool(WRITING_TASK_INCLUDE_REGEX.search(combined_text))

        if not (matches_writing or is_writing_source):
            self.total_dropped += 1
            return None

        # 4. Length checks: Minimum 100 characters for meaningful communication
        if len(clean_chosen) < 100 or len(clean_rejected) < 100:
            self.total_dropped += 1
            self.dropped_for_length += 1
            return None

        # 5. DPO Anti-Slop Enforcement Logic:
        # Rule A: The CHOSEN response must NEVER contain AI buzzwords
        if contains_ai_slop(clean_chosen):
            self.total_dropped += 1
            self.dropped_for_slop += 1
            return None

        # Rule B: Check if REJECTED naturally contains AI buzzwords
        has_rejected_slop = contains_ai_slop(clean_rejected)

        if has_rejected_slop:
            # Ideal organic pair: clean chosen vs. robotic rejected
            self.natural_slop_pairs_count += 1
            final_rejected = clean_rejected
        else:
            # Augment rejected to explicitly penalize classic AI robotic phrases
            # ("I hope this email finds you well", "delve", "testament", "tapestry", "furthermore", "in conclusion")
            final_rejected = inject_robotic_slop(clean_rejected)
            self.slop_augmented_count += 1

        # 6. Deduplication Check
        if self.deduplicator.check_and_add(clean_prompt, clean_chosen):
            self.total_dropped += 1
            self.dropped_for_dupe += 1
            return None

        # Standard TRL DPOTrainer schema: {"prompt": "...", "chosen": "...", "rejected": "..."}
        return {
            "prompt": clean_prompt,
            "chosen": clean_chosen,
            "rejected": final_rejected,
        }

    def get_stats(self) -> Dict[str, Any]:
        stats = super().get_stats()
        stats["natural_slop_pairs"] = self.natural_slop_pairs_count
        stats["slop_augmented_pairs"] = self.slop_augmented_count
        return stats
