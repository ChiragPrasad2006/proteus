"""
email_data_pipeline.processors.dataset_b
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Processor for Dataset B (proj-persona/PersonaHub).
Filters for professional/corporate/academic/workplace personas, excludes fantasy/NPCs,
pairs personas with scenarios, executes batched async synthesis,
and outputs dual-yield datasets:
  1. Standard Hugging Face ChatML SFT messages for Stage 1.
  2. Domain-specific (chosen_email, rejected_email) DPO pairs for Stage 2.
"""

import asyncio
import logging
import random
import time
from typing import Any, Dict, Generator, List, Optional, Tuple
from datasets import load_dataset

from ..config import PipelineConfig, EMAIL_SCENARIOS
from ..deduplication.deduplicator import Deduplicator
from ..filters.deslop import contains_ai_slop, clean_markdown_and_html, inject_robotic_slop
from ..filters.persona_filter import is_workplace_persona, sanitize_persona_description
from ..synthesis.llm_synthesizer import AsyncEmailSynthesizer
from ..synthesis.scenarios import get_random_scenario
from .base import BaseDatasetProcessor

logger = logging.getLogger("email_data_pipeline.dataset_b")


class DatasetBProcessor(BaseDatasetProcessor):
    """
    Downloads PersonaHub, extracts workplace personas, and synthesizes
    high-quality persona-conditioned email training examples for both SFT and DPO.
    """

    def __init__(self, config: PipelineConfig, deduplicator: Deduplicator):
        super().__init__(config, deduplicator)
        self.dataset_name = config.dataset_b_name
        self.subset = config.dataset_b_subset
        self.synthesizer = AsyncEmailSynthesizer(config)
        self.total_dpo_emitted: int = 0

    def _load_with_retry(self, name: str, subset: Optional[str]) -> Any:
        """Loads a hub dataset with retry/backoff to survive transient DNS/network failures."""
        last_err: Exception = RuntimeError("unavailable")
        for attempt in range(6):
            try:
                if subset:
                    return load_dataset(name, subset, split="train", streaming=True)
                return load_dataset(name, split="train", streaming=True)
            except Exception as e:  # noqa: BLE001 - hub errors are heterogeneous
                last_err = e
                wait = 5.0 * (attempt + 1)
                logger.warning("Hub load attempt %d failed (%s). Retrying in %.0fs ...", attempt + 1, e, wait)
                time.sleep(wait)
        logger.error("Could not load %s after retries: %s", name, last_err)
        return None

    def process(self) -> Generator[Dict[str, Any], None, None]:
        """
        Runs batched async processing over streaming PersonaHub dataset,
        yielding dicts containing both 'sft' and 'dpo' formatted training pairs.
        """
        logger.info("Loading Dataset B: %s (subset: %s)", self.dataset_name, self.subset)

        dataset = self._load_with_retry(self.dataset_name, self.subset)
        if dataset is None:
            logger.warning("Streaming PersonaHub (%s) failed. Trying 'persona' config.", self.subset)
            self.subset = "persona"
            dataset = self._load_with_retry(self.dataset_name, self.subset)
        if dataset is None:
            return

        # Check LLM endpoint status before starting batch loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        is_live = loop.run_until_complete(self.synthesizer.check_endpoint_health())
        if not is_live and not self.config.offline_synthesis:
            logger.warning("Live LLM endpoint offline. Activating high-fidelity deterministic synthesis engine.")
            self.synthesizer.offline_mode = True

        batch_pairs: List[Tuple[str, Dict[str, str]]] = []
        batch_size = min(self.config.batch_size, 100)

        for row in dataset:
            self.total_processed += 1
            if self.config.max_samples_b and self.total_accepted >= self.config.max_samples_b:
                logger.info("Dataset B reached target sample limit (%d).", self.config.max_samples_b)
                break

            # Handle different possible column keys ('persona' or 'input persona')
            raw_persona = row.get("persona") or row.get("input persona") or ""
            if not is_workplace_persona(raw_persona):
                self.total_dropped += 1
                continue

            clean_p = sanitize_persona_description(raw_persona)
            scenario = get_random_scenario()
            batch_pairs.append((clean_p, scenario))

            if len(batch_pairs) >= batch_size:
                # Execute async generation for the batch
                synthesized_items = loop.run_until_complete(
                    self.synthesizer.generate_batch(batch_pairs)
                )
                batch_pairs.clear()

                for item in synthesized_items:
                    formatted = self._format_and_validate(item)
                    if formatted:
                        self.total_accepted += 1
                        yield formatted
                        if self.config.max_samples_b and self.total_accepted >= self.config.max_samples_b:
                            break

        # Process any remaining items in final batch
        if batch_pairs and (not self.config.max_samples_b or self.total_accepted < self.config.max_samples_b):
            synthesized_items = loop.run_until_complete(
                self.synthesizer.generate_batch(batch_pairs)
            )
            for item in synthesized_items:
                formatted = self._format_and_validate(item)
                if formatted:
                    self.total_accepted += 1
                    yield formatted
                    if self.config.max_samples_b and self.total_accepted >= self.config.max_samples_b:
                        break

        loop.close()

    def _format_and_validate(self, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Validates synthesized item, verifies absence of slop, and outputs dual SFT and DPO formats."""
        persona = item.get("persona", "")
        chosen_email = clean_markdown_and_html(item.get("chosen_email") or item.get("email_output") or "")
        rejected_email = clean_markdown_and_html(item.get("rejected_email") or "")
        user_bullets = item.get("user_intent_bullets", "")
        style_meta = item.get("style_profile") or item.get("style_metadata", "")
        incoming_context = item.get("incoming_context") or "None (New Thread)"

        # Length validation
        if len(chosen_email) < self.config.min_email_chars:
            self.total_dropped += 1
            self.dropped_for_length += 1
            return None

        # De-slopping validation: DROP if chosen email contains robotic buzzwords
        if contains_ai_slop(chosen_email):
            self.total_dropped += 1
            self.dropped_for_slop += 1
            return None

        # Ensure rejected email contains robotic contrast
        if not rejected_email or not contains_ai_slop(rejected_email):
            rejected_email = inject_robotic_slop(chosen_email)

        system_content = (
            f"You are a personalized email writer. Adopt this persona and style:\n"
            f"Persona: {persona}\n"
            f"Style Profile: {style_meta}"
        )

        if incoming_context and incoming_context.lower() != "none (new thread)":
            user_content = f"Incoming Context: {incoming_context}\n\nDraft an email covering these points:\n{user_bullets}"
        else:
            user_content = f"Draft an email covering these points:\n{user_bullets}"

        assistant_content = chosen_email

        # Deduplication check
        if self.deduplicator.check_and_add(user_content, assistant_content):
            self.total_dropped += 1
            self.dropped_for_dupe += 1
            return None

        # 1. Stage 1 SFT format
        sft_entry = {
            "messages": [
                {"role": "system", "content": system_content},
                {"role": "user", "content": user_content},
                {"role": "assistant", "content": assistant_content},
            ]
        }

        # 2. Stage 2 DPO format
        prompt_chatml = (
            f"<|im_start|>system\n{system_content}<|im_end|>\n"
            f"<|im_start|>user\n{user_content}<|im_end|>\n"
            f"<|im_start|>assistant\n"
        )
        dpo_entry = {
            "prompt": prompt_chatml,
            "chosen": chosen_email,
            "rejected": rejected_email,
        }

        self.total_dpo_emitted += 1
        return {"sft": sft_entry, "dpo": dpo_entry}
