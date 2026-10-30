"""
email_data_pipeline.pipeline
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Master orchestration engine for the Two-Stage LLM Fine-Tuning Data Pipeline.
Coordinates streaming dataset extraction, filtering, synthesis, deduplication,
anti-slop validation, train/val splitting, token distribution reporting, and JSONL disk persistence.
"""

import gc
import json
import logging
import random
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .config import PipelineConfig
from .deduplication.deduplicator import Deduplicator
from .metrics.reporter import print_summary_report
from .processors.dataset_a import DatasetAProcessor
from .processors.dataset_b import DatasetBProcessor
from .processors.dataset_c import DatasetCProcessor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("email_data_pipeline")


class DataPipeline:
    """
    Two-Stage Fine-Tuning Data Pipeline orchestrator.
    Designed for memory efficiency on 16GB RAM machines.
    """

    def __init__(self, config: Optional[PipelineConfig] = None):
        self.config = config or PipelineConfig()
        self.deduplicator = Deduplicator(
            jaccard_threshold=self.config.dedup_threshold,
            num_perm=self.config.minhash_num_perm,
            k_shingle=self.config.k_shingle_size,
        )

    def run(self) -> Dict[str, Any]:
        """Executes the complete two-stage data engineering pipeline."""
        logger.info("=" * 70)
        logger.info("STARTING TWO-STAGE LLM FINE-TUNING DATA PIPELINE")
        logger.info("Target Model: %s", self.config.model_id)
        logger.info("Output Directory: %s", self.config.output_dir.resolve())
        logger.info("=" * 70)

        self.config.output_dir.mkdir(parents=True, exist_ok=True)

        # -------------------------------------------------------------------
        # Stage 1: SFT Data Processing (Dataset A + Dataset B)
        # -------------------------------------------------------------------
        logger.info("\n>>> Processing Stage 1: SFT Datasets (FinePersonas + PersonaHub) ...")

        sft_rows: List[Dict[str, Any]] = []

        # Process Dataset A
        proc_a = DatasetAProcessor(self.config, self.deduplicator)
        count_a = 0
        for row in proc_a.process():
            sft_rows.append(row)
            count_a += 1
            if count_a % 500 == 0:
                logger.info("  Dataset A: %d accepted rows...", count_a)

        logger.info("Dataset A Completed. Accepted: %d, Stats: %s", count_a, proc_a.get_stats())
        gc.collect()

        # Process Dataset B (Dual-yield: SFT + Email DPO pairs)
        proc_b = DatasetBProcessor(self.config, self.deduplicator)
        count_b = 0
        dpo_email_rows: List[Dict[str, str]] = []
        for dual_item in proc_b.process():
            if isinstance(dual_item, dict):
                if "sft" in dual_item:
                    sft_rows.append(dual_item["sft"])
                if "dpo" in dual_item and (
                    not self.config.max_samples_b_dpo
                    or len(dpo_email_rows) < self.config.max_samples_b_dpo
                ):
                    dpo_email_rows.append(dual_item["dpo"])
            count_b += 1
            if count_b % 500 == 0:
                logger.info("  Dataset B: %d accepted rows...", count_b)

        logger.info(
            "Dataset B Completed. Accepted: %d (SFT: %d, Email DPO pairs: %d)",
            count_b,
            count_b,
            len(dpo_email_rows),
        )
        gc.collect()

        logger.info("Total Combined SFT Rows: %d", len(sft_rows))

        # Shuffle with seeded RNG, then split with disjointness guarantee
        rng = random.Random(self.config.seed)
        rng.shuffle(sft_rows)

        sft_train, sft_val = self._disjoint_split(
            sft_rows,
            key_fn=lambda r: r["messages"][2]["content"][:150],
            val_ratio=self.config.val_split_ratio,
        )

        logger.info("SFT Split: Train = %d, Validation = %d", len(sft_train), len(sft_val))
        gc.collect()

        # -------------------------------------------------------------------
        # Stage 2: DPO Data Processing (Dataset B Email Pairs + Dataset C Capybara)
        # -------------------------------------------------------------------
        logger.info("\n>>> Processing Stage 2: DPO Dataset (PersonaHub Email Pairs + Capybara DPO) ...")

        dpo_rows: List[Dict[str, str]] = list(dpo_email_rows)
        logger.info("Incorporated %d domain-specific email DPO pairs from Dataset B.", len(dpo_rows))

        proc_c = DatasetCProcessor(self.config, self.deduplicator)
        count_c = 0
        for row in proc_c.process():
            dpo_rows.append(row)
            count_c += 1
            if count_c % 500 == 0:
                logger.info("  Dataset C: %d accepted rows...", count_c)

        logger.info("Dataset C Completed. Accepted: %d. Total Combined DPO Rows: %d", count_c, len(dpo_rows))
        gc.collect()

        # Shuffle, then split DPO pairs disjointly on the chosen response
        rng.shuffle(dpo_rows)
        dpo_train, dpo_val = self._disjoint_split(
            dpo_rows,
            key_fn=lambda r: str(r.get("chosen", ""))[:150],
            val_ratio=self.config.val_split_ratio,
        )

        logger.info("DPO Split: Train = %d, Validation = %d", len(dpo_train), len(dpo_val))
        gc.collect()

        # -------------------------------------------------------------------
        # Summary Report: Token Length Distributions & Counts
        # -------------------------------------------------------------------
        logger.info("\n>>> Generating Token Length Distribution and Summary Report ...")
        print_summary_report(
            sft_train=sft_train,
            sft_val=sft_val,
            dpo_train=dpo_train,
            dpo_val=dpo_val,
            model_id=self.config.model_id,
        )

        # -------------------------------------------------------------------
        # Save Formatted Datasets to Disk (.jsonl)
        # -------------------------------------------------------------------
        logger.info(">>> Saving formatted datasets to disk ...")

        self._write_jsonl(self.config.sft_train_path, sft_train)
        self._write_jsonl(self.config.sft_val_path, sft_val)
        self._write_jsonl(self.config.dpo_train_path, dpo_train)
        self._write_jsonl(self.config.dpo_val_path, dpo_val)

        logger.info("=" * 70)
        logger.info("PIPELINE EXECUTION COMPLETED SUCCESSFULLY!")
        logger.info("Output Files:")
        logger.info("  - SFT Train: %s (%d rows)", self.config.sft_train_path.resolve(), len(sft_train))
        logger.info("  - SFT Val:   %s (%d rows)", self.config.sft_val_path.resolve(), len(sft_val))
        logger.info("  - DPO Train: %s (%d rows)", self.config.dpo_train_path.resolve(), len(dpo_train))
        logger.info("  - DPO Val:   %s (%d rows)", self.config.dpo_val_path.resolve(), len(dpo_val))
        logger.info("Deduplication Stats: %s", self.deduplicator.stats())
        logger.info("=" * 70)

        return {
            "sft_train_count": len(sft_train),
            "sft_val_count": len(sft_val),
            "dpo_train_count": len(dpo_train),
            "dpo_val_count": len(dpo_val),
            "dedup_stats": self.deduplicator.stats(),
        }

    def _disjoint_split(self, rows: List[Dict[str, Any]], key_fn, val_ratio: float):
        """
        Shuffle + split that guarantees train/val are disjoint on a normalized
        content key (assistant text for SFT, chosen text for DPO).
        All rows sharing a duplicate key are quarantined into train; val is drawn
        only from unique-key rows, preserving shuffled order.
        """
        from collections import defaultdict

        key_groups: Dict[str, List[int]] = defaultdict(list)
        for i, r in enumerate(rows):
            key_groups[key_fn(r)].append(i)

        n_val = int(len(rows) * val_ratio)
        val_rows: List[Dict[str, Any]] = []
        val_index_set = set()
        for key, indices in key_groups.items():
            if len(val_rows) >= n_val:
                break
            if len(indices) == 1:  # unique-key rows only
                val_index_set.add(indices[0])
                val_rows.append(rows[indices[0]])
        train_rows = [r for j, r in enumerate(rows) if j not in val_index_set]
        return train_rows, val_rows

    def _write_jsonl(self, path: Path, data: List[Dict[str, Any]]):
        """Writes items in buffered batches to avoid memory accumulation."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            for i, item in enumerate(data):
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
                if (i + 1) % self.config.writer_buffer_size == 0:
                    f.flush()
            f.flush()
        file_size_mb = path.stat().st_size / (1024 * 1024)
        logger.info("Saved %s (%.2f MB, %d rows)", path.name, file_size_mb, len(data))
