#!/usr/bin/env python3
"""
pipeline.py
~~~~~~~~~~~
Two-Stage LLM Fine-Tuning Data Engineering Pipeline for a Personalized AI Email Writer.
Targets: Qwen/Qwen2.5-3B-Instruct (ChatML / standard HF messages & TRL DPOTrainer formats).

Datasets Processed:
1. Dataset A: argilla/FinePersonas-Synthetic-Email-Conversations (or FinePersonas-v0.1)
2. Dataset B: proj-persona/PersonaHub (subset 'persona' or 'instruction')
3. Dataset C: argilla/distilabel-capybara-dpo-7k-binarized

Usage:
    # Full run (offline / synthetic fallback mode):
    python pipeline.py --offline-synthesis

    # Live run with local Ollama or vLLM server:
    python pipeline.py --llm-base-url http://localhost:11434/v1 --llm-model qwen2.5:3b

    # Fast test / verification dry run:
    python pipeline.py --max-samples-a 50 --max-samples-b 50 --max-samples-c 50
"""

import argparse
import sys
from pathlib import Path

# Add project root to path for modular imports
sys.path.insert(0, str(Path(__file__).resolve().parent))

from email_data_pipeline.config import PipelineConfig
from email_data_pipeline.pipeline import DataPipeline


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Two-Stage LLM Fine-Tuning Data Pipeline (SFT & DPO) for Personalized AI Email Writer.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    # Model & Tokenizer
    parser.add_argument(
        "--model-id",
        type=str,
        default="Qwen/Qwen2.5-3B-Instruct",
        help="Target base model identifier for tokenization and ChatML format.",
    )

    # Sample limits (Aligned with 3B-4B Model Proportions: ~12k SFT, ~5k DPO)
    parser.add_argument(
        "--max-samples-a",
        type=int,
        default=6000,
        help="Maximum rows to process from Dataset A (FinePersonas). Set 0 for unlimited.",
    )
    parser.add_argument(
        "--max-samples-b",
        type=int,
        default=6000,
        help="Maximum rows to process from Dataset B (PersonaHub SFT). Set 0 for unlimited.",
    )
    parser.add_argument(
        "--max-samples-b-dpo",
        type=int,
        default=2500,
        help="Maximum email DPO pairs to harvest from Dataset B synthesis.",
    )
    parser.add_argument(
        "--max-samples-c",
        type=int,
        default=2500,
        help="Maximum rows to process from Dataset C (Capybara DPO). Set 0 for unlimited.",
    )

    # Dataset Sources
    parser.add_argument(
        "--dataset-a-name",
        type=str,
        default="argilla/FinePersonas-Synthetic-Email-Conversations",
        help="Dataset A Hugging Face hub repository path.",
    )
    parser.add_argument(
        "--dataset-b-name",
        type=str,
        default="proj-persona/PersonaHub",
        help="Dataset B Hugging Face hub repository path.",
    )
    parser.add_argument(
        "--dataset-b-subset",
        type=str,
        default="persona",
        help="Subset config for Dataset B ('persona' or 'instruction').",
    )
    parser.add_argument(
        "--dataset-c-name",
        type=str,
        default="argilla/distilabel-capybara-dpo-7k-binarized",
        help="Dataset C Hugging Face hub repository path.",
    )

    # Output paths
    parser.add_argument(
        "--output-dir",
        type=str,
        default="data",
        help="Target directory for output JSONL files.",
    )

    # Split and Seed
    parser.add_argument(
        "--val-split-ratio",
        type=float,
        default=0.10,
        help="Validation split percentage (0.10 = 10% validation).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for deterministic dataset shuffling and splitting.",
    )

    # Memory & Batching (16GB RAM constraints)
    parser.add_argument(
        "--batch-size",
        type=int,
        default=250,
        help="Batch size for Hugging Face streaming and async synthesis chunks.",
    )
    parser.add_argument(
        "--min-email-chars",
        type=int,
        default=150,
        help="Minimum character threshold for clean email assistant messages.",
    )

    # LLM Synthesis settings (Ollama / vLLM / OpenAI compatible)
    parser.add_argument(
        "--llm-base-url",
        type=str,
        default="http://localhost:11434/v1",
        help="Base URL for OpenAI-compatible LLM endpoint (Ollama/vLLM).",
    )
    parser.add_argument(
        "--llm-api-key",
        type=str,
        default="EMPTY",
        help="API Key for OpenAI-compatible LLM endpoint.",
    )
    parser.add_argument(
        "--llm-model",
        type=str,
        default="qwen2.5:3b",
        help="Model identifier on the local/remote LLM server.",
    )
    parser.add_argument(
        "--llm-concurrency",
        type=int,
        default=8,
        help="Maximum concurrent asynchronous synthesis requests.",
    )
    parser.add_argument(
        "--offline-synthesis",
        action="store_true",
        default=False,
        help="Force offline deterministic synthesis without querying an external LLM server.",
    )

    # Deduplication settings
    parser.add_argument(
        "--dedup-threshold",
        type=float,
        default=0.85,
        help="MinHash Jaccard similarity threshold for near-duplicate rejection.",
    )

    return parser.parse_args()


def main():
    args = parse_args()

    out_dir = Path(args.output_dir)

    config = PipelineConfig(
        model_id=args.model_id,
        dataset_a_name=args.dataset_a_name,
        dataset_b_name=args.dataset_b_name,
        dataset_b_subset=args.dataset_b_subset,
        dataset_c_name=args.dataset_c_name,
        output_dir=out_dir,
        sft_train_path=out_dir / "sft_email_train.jsonl",
        sft_val_path=out_dir / "sft_email_val.jsonl",
        dpo_train_path=out_dir / "dpo_email_train.jsonl",
        dpo_val_path=out_dir / "dpo_email_val.jsonl",
        max_samples_a=args.max_samples_a if args.max_samples_a > 0 else None,
        max_samples_b=args.max_samples_b if args.max_samples_b > 0 else None,
        max_samples_b_dpo=args.max_samples_b_dpo if args.max_samples_b_dpo > 0 else None,
        max_samples_c=args.max_samples_c if args.max_samples_c > 0 else None,
        val_split_ratio=args.val_split_ratio,
        seed=args.seed,
        batch_size=args.batch_size,
        min_email_chars=args.min_email_chars,
        llm_base_url=args.llm_base_url,
        llm_api_key=args.llm_api_key,
        llm_model=args.llm_model,
        llm_concurrency=args.llm_concurrency,
        offline_synthesis=args.offline_synthesis,
        dedup_threshold=args.dedup_threshold,
    )

    pipeline = DataPipeline(config)
    results = pipeline.run()

    print("\nProcessing complete.")
    print(f"SFT Train samples: {results['sft_train_count']}")
    print(f"SFT Val samples:   {results['sft_val_count']}")
    print(f"DPO Train samples: {results['dpo_train_count']}")
    print(f"DPO Val samples:   {results['dpo_val_count']}")


if __name__ == "__main__":
    main()
