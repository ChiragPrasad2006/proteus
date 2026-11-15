#!/usr/bin/env python3
"""
train_sft.py
~~~~~~~~~~~~
Stage 1: Supervised Fine-Tuning (SFT) for Personalized AI Email Writer.
Targets: Qwen/Qwen2.5-3B-Instruct with QLoRA (NF4 4-bit) on RTX 5060 Ti (8GB VRAM).

Architecture & Optimizations:
- BitsAndBytes NF4 4-bit Quantization + Double Quantization (bnb_4bit_compute_dtype=bfloat16)
- PEFT LoRA on all 7 linear projections (q, k, v, o, gate, up, down) with r=16, alpha=32
- PyTorch Native Scaled Dot-Product Attention (attn_implementation="sdpa")
- Non-reentrant Gradient Checkpointing (slashing activation memory by ~60%)
- Paged AdamW 8-bit Optimizer (pages optimizer states to host RAM if VRAM spikes)
- Completion-only Loss Masking: Trains ONLY on assistant responses using DataCollatorForCompletionOnlyLM
- Step-based Saving & Evaluation (eval_steps=100, save_steps=100, save_total_limit=3, load_best_model_at_end)
- Auto-resume from checkpoint (--resume_from_checkpoint latest or path)
- Strict VRAM budgeting keeping peak usage under 7.2 GB on Windows.

Author: Principal Deep Learning & MLOps Engineer
"""

import argparse
import glob
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import torch
from datasets import Dataset, load_dataset
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    DataCollatorForSeq2Seq,
    PreTrainedTokenizerBase,
    TrainerCallback,
    TrainerControl,
    TrainerState,
    TrainingArguments,
    set_seed,
)
from peft import (
    LoraConfig,
    PeftModel,
    get_peft_model,
    prepare_model_for_kbit_training,
)

# TRL imports with backward/forward compatibility
try:
    from trl import SFTConfig, SFTTrainer
except ImportError:
    raise ImportError("trl is required. Please install it via `pip install trl`.")

# Configure structured logging
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=logging.INFO,
)
logger = logging.getLogger("train_sft")


# ---------------------------------------------------------------------------
# VRAM Memory Telemetry Utilities
# ---------------------------------------------------------------------------
def log_gpu_vram(stage: str = "") -> None:
    """Logs current GPU VRAM allocation, reserved memory, and peak usage."""
    if not torch.cuda.is_available():
        logger.warning(f"[{stage}] CUDA is not available. Running on CPU.")
        return

    device = torch.cuda.current_device()
    allocated_mb = torch.cuda.memory_allocated(device) / (1024**2)
    reserved_mb = torch.cuda.memory_reserved(device) / (1024**2)
    max_allocated_mb = torch.cuda.max_memory_allocated(device) / (1024**2)
    total_mb = torch.cuda.get_device_properties(device).total_memory / (1024**2)

    logger.info(
        f"[{stage}] VRAM Telemetry -> Allocated: {allocated_mb:.1f} MB | "
        f"Reserved: {reserved_mb:.1f} MB | Peak Allocated: {max_allocated_mb:.1f} MB | "
        f"Total Device: {total_mb:.1f} MB ({(allocated_mb / total_mb) * 100:.1f}%)"
    )
    if max_allocated_mb > 7200.0:
        logger.warning(
            f"⚠️ Peak VRAM ({max_allocated_mb:.1f} MB) exceeds safe ceiling of 7200 MB! "
            "Risk of Windows DWM paging thrashing."
        )


class VRAMMonitoringCallback(TrainerCallback):
    """Callback to log VRAM consumption and ensure allocation stays under ceiling."""

    def on_step_end(
        self,
        args: TrainingArguments,
        state: TrainerState,
        control: TrainerControl,
        **kwargs,
    ):
        if state.global_step % args.logging_steps == 0 and torch.cuda.is_available():
            peak_mb = torch.cuda.max_memory_allocated() / (1024**2)
            if peak_mb > 7200.0:
                logger.warning(
                    f"⚠️ Step {state.global_step}: VRAM peak at {peak_mb:.1f} MB (Ceiling: 7200 MB)"
                )


# ---------------------------------------------------------------------------
# Loss Masking: Completion-Only Collator
# ---------------------------------------------------------------------------
class DataCollatorForCompletionOnlyLM(DataCollatorForSeq2Seq):
    """
    Data collator that masks prompt tokens in labels with -100 so cross-entropy loss
    is calculated ONLY on assistant email completions following `response_template`.

    Prevents gradient backpropagation into system personas or user instructions.
    Works robustly across all HuggingFace and TRL version variants.
    """

    def __init__(
        self,
        response_template: Union[str, List[int]],
        tokenizer: PreTrainedTokenizerBase,
        *args,
        mlm: bool = False,
        ignore_index: int = -100,
        **kwargs,
    ):
        super().__init__(tokenizer=tokenizer, *args, **kwargs)
        if isinstance(response_template, str):
            self.response_token_ids = self.tokenizer.encode(
                response_template, add_special_tokens=False
            )
        else:
            self.response_token_ids = list(response_template)

        self.ignore_index = ignore_index
        logger.info(
            f"Initialized DataCollatorForCompletionOnlyLM: response_template tokens = {self.response_token_ids}"
        )

    def __call__(self, features: List[Dict[str, Any]], return_tensors=None) -> Dict[str, Any]:
        # Shallow copy features to avoid in-place mutation of the dataset cache
        features = [{k: (v.copy() if isinstance(v, list) else v) for k, v in f.items()} for f in features]

        # Ensure labels exist before padding
        for f in features:
            if "labels" not in f or f["labels"] is None:
                f["labels"] = list(f["input_ids"])

        batch = super().__call__(features, return_tensors=return_tensors)
        labels = batch["labels"].clone()

        template_len = len(self.response_token_ids)
        for i in range(len(features)):
            input_ids = batch["input_ids"][i].tolist()
            start_idx = None

            # Subsequence search for response template tokens
            for idx in range(len(input_ids) - template_len + 1):
                if input_ids[idx : idx + template_len] == self.response_token_ids:
                    start_idx = idx
                    break

            if start_idx is None:
                # If template was truncated or not found, mask entire sequence to prevent unprompted loss
                labels[i, :] = self.ignore_index
            else:
                # Mask prompt up to and including the response template tokens
                end_idx = start_idx + template_len
                labels[i, :end_idx] = self.ignore_index

        batch["labels"] = labels
        return batch


# ---------------------------------------------------------------------------
# Checkpoint Resolution & Auto-Resume
# ---------------------------------------------------------------------------
def resolve_checkpoint(output_dir: str, resume_arg: Optional[str]) -> Optional[str]:
    """
    Resolves the checkpoint path to resume from.
    - If `latest` or `True`, scans output_dir for `checkpoint-<step>` with largest step number.
    - If a valid directory path, returns that path.
    - If None or `none`, returns None (fresh start).
    """
    if not resume_arg or resume_arg.lower() in ("none", "false", "0"):
        logger.info("Starting fresh training run (no resume).")
        return None

    if resume_arg.lower() in ("latest", "true", "1", "auto"):
        if not os.path.isdir(output_dir):
            logger.warning(f"Output directory '{output_dir}' does not exist yet. Starting fresh.")
            return None

        checkpoints = glob.glob(os.path.join(output_dir, "checkpoint-*"))
        if not checkpoints:
            logger.warning(f"No existing checkpoints found in '{output_dir}'. Starting fresh.")
            return None

        # Sort by step number integer
        def extract_step(path_str: str) -> int:
            try:
                return int(os.path.basename(path_str).split("-")[-1])
            except (ValueError, IndexError):
                return -1

        valid_checkpoints = [cp for cp in checkpoints if extract_step(cp) >= 0]
        if not valid_checkpoints:
            logger.warning(f"No valid checkpoint-* subdirectories in '{output_dir}'. Starting fresh.")
            return None

        latest_cp = max(valid_checkpoints, key=extract_step)
        logger.info(f"🔄 Auto-resume resolved latest checkpoint: {latest_cp}")
        return latest_cp

    # Explicit path passed
    if os.path.isdir(resume_arg):
        logger.info(f"🔄 Resuming from explicit checkpoint path: {resume_arg}")
        return resume_arg

    logger.warning(f"Checkpoint path '{resume_arg}' does not exist. Starting fresh training.")
    return None


# ---------------------------------------------------------------------------
# CLI Argument Parser
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Stage 1: Production SFT Training for Personalized AI Email Writer (Qwen2.5-3B-Instruct)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    # Model & Tokenizer
    parser.add_argument(
        "--model_id",
        type=str,
        default="Qwen/Qwen2.5-3B-Instruct",
        help="Hugging Face hub base model identifier or local directory.",
    )
    parser.add_argument(
        "--train_file",
        type=str,
        default="data/sft_email_train.jsonl",
        help="Path to training JSONL dataset.",
    )
    parser.add_argument(
        "--val_file",
        type=str,
        default="data/sft_email_val.jsonl",
        help="Path to validation JSONL dataset.",
    )
    parser.add_argument(
        "--output_dir",
        type=str,
        default="./checkpoints/qwen-email-sft-best",
        help="Directory to save checkpoints and final LoRA adapter.",
    )

    # QLoRA Hyperparameters
    parser.add_argument("--lora_r", type=int, default=16, help="LoRA rank dimension.")
    parser.add_argument("--lora_alpha", type=int, default=32, help="LoRA scaling factor.")
    parser.add_argument("--lora_dropout", type=float, default=0.05, help="LoRA dropout rate.")

    # Sequence & Batch Geometry (Tunable for 8GB VRAM)
    parser.add_argument("--max_seq_length", type=int, default=1024, help="Maximum sequence token length.")
    parser.add_argument("--batch_size", type=int, default=2, help="Per-device train batch size.")
    parser.add_argument("--eval_batch_size", type=int, default=2, help="Per-device eval batch size.")
    parser.add_argument(
        "--gradient_accumulation_steps",
        type=int,
        default=8,
        help="Gradient accumulation steps (effective batch size = batch_size * grad_accum).",
    )

    # Optimizer & Scheduler
    parser.add_argument("--learning_rate", type=float, default=2e-4, help="Peak learning rate.")
    parser.add_argument("--lr_scheduler_type", type=str, default="cosine", help="LR scheduler type.")
    parser.add_argument("--warmup_ratio", type=float, default=0.05, help="Warmup step ratio.")
    parser.add_argument("--weight_decay", type=float, default=0.01, help="L2 weight decay.")
    parser.add_argument("--num_train_epochs", type=float, default=3.0, help="Number of training epochs.")
    parser.add_argument("--max_steps", type=int, default=-1, help="If > 0: set total number of training steps to perform (overrides epochs).")

    # Evaluation, Checkpointing & Resume
    parser.add_argument("--eval_steps", type=int, default=100, help="Step interval for validation loss.")
    parser.add_argument("--save_steps", type=int, default=100, help="Step interval for checkpoint saving.")
    parser.add_argument("--save_total_limit", type=int, default=3, help="Max checkpoints to retain on disk.")
    parser.add_argument(
        "--resume_from_checkpoint",
        type=str,
        default=None,
        help="Resume from checkpoint ('latest', path, or None).",
    )

    # Performance & System
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility.")
    parser.add_argument("--dataloader_num_workers", type=int, default=2, help="DataLoader worker processes.")
    parser.add_argument("--dataloader_pin_memory", action="store_true", default=True, help="Pin host memory for GPU transfers.")

    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main Training Routine
# ---------------------------------------------------------------------------
def main() -> None:
    args = parse_args()
    set_seed(args.seed)

    # 1. Environment & GPU Verification
    logger.info("=================================================================")
    logger.info("🚀 Personalized AI Email Writer: Stage 1 Supervised Fine-Tuning")
    logger.info("=================================================================")
    logger.info(f"Target Base Model   : {args.model_id}")
    logger.info(f"Train Dataset       : {args.train_file}")
    logger.info(f"Validation Dataset  : {args.val_file}")
    logger.info(f"Output Directory    : {args.output_dir}")
    logger.info(f"Max Sequence Length : {args.max_seq_length}")
    logger.info(f"Per-Device Batch    : {args.batch_size} (Grad Accum: {args.gradient_accumulation_steps})")
    logger.info(f"Effective Batch Size: {args.batch_size * args.gradient_accumulation_steps}")
    logger.info(f"Learning Rate       : {args.learning_rate} (Cosine, Warmup: {args.warmup_ratio})")

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for QLoRA training on RTX 5060 Ti.")

    gpu_name = torch.cuda.get_device_name(0)
    gpu_capability = torch.cuda.get_device_capability(0)
    logger.info(f"Active GPU Device   : {gpu_name} (Compute Capability: {gpu_capability[0]}.{gpu_capability[1]})")
    log_gpu_vram("Initial State")

    # 2. BitsAndBytes 4-bit NF4 Quantization Configuration
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
    )

    # 3. Load Tokenizer
    logger.info("Loading tokenizer with ChatML support...")
    tokenizer = AutoTokenizer.from_pretrained(
        args.model_id,
        trust_remote_code=True,
        padding_side="right",
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
        tokenizer.pad_token_id = tokenizer.eos_token_id

    # 4. Load Base Model in 4-bit with SDPA Native Attention
    logger.info("Loading base model in 4-bit NF4 precision with PyTorch Native SDPA...")
    model = AutoModelForCausalLM.from_pretrained(
        args.model_id,
        quantization_config=bnb_config,
        device_map="auto",
        attn_implementation="sdpa",
        dtype=torch.bfloat16,
        trust_remote_code=True,
    )

    # Prepare model for k-bit training and enable input gradients for checkpointing
    model = prepare_model_for_kbit_training(
        model,
        use_gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
    )
    model.enable_input_require_grads()
    log_gpu_vram("Post Base-Model Load")

    # 5. PEFT LoRA Configuration
    target_modules = [
        "q_proj",
        "k_proj",
        "v_proj",
        "o_proj",
        "gate_proj",
        "up_proj",
        "down_proj",
    ]
    peft_config = LoraConfig(
        task_type="CAUSAL_LM",
        r=args.lora_r,
        lora_alpha=args.lora_alpha,
        lora_dropout=args.lora_dropout,
        bias="none",
        target_modules=target_modules,
    )
    model = get_peft_model(model, peft_config)
    model.print_trainable_parameters()
    log_gpu_vram("Post LoRA Attachment")

    # 6. Load & Preprocess Datasets
    logger.info("Loading JSONL datasets...")
    if not os.path.exists(args.train_file) or not os.path.exists(args.val_file):
        raise FileNotFoundError(
            f"Dataset files not found. Expected '{args.train_file}' and '{args.val_file}'."
        )

    raw_datasets = load_dataset(
        "json",
        data_files={"train": args.train_file, "validation": args.val_file},
    )

    # ChatML formatting & tokenization
    logger.info("Applying ChatML template to datasets...")

    def preprocess_chatml(batch: Dict[str, List[Any]]) -> Dict[str, Any]:
        """Renders messages through tokenizer's chat template and tokenizes."""
        rendered_texts = [
            tokenizer.apply_chat_template(
                msgs,
                tokenize=False,
                add_generation_prompt=False,
            )
            for msgs in batch["messages"]
        ]
        tokenized = tokenizer(
            rendered_texts,
            truncation=True,
            max_length=args.max_seq_length,
            padding=False,  # Padded dynamically by the data collator
            add_special_tokens=False,
        )
        return tokenized

    tokenized_train = raw_datasets["train"].map(
        preprocess_chatml,
        batched=True,
        batch_size=500,
        remove_columns=["messages"],
        desc="Tokenizing SFT train split",
    )
    tokenized_val = raw_datasets["validation"].map(
        preprocess_chatml,
        batched=True,
        batch_size=500,
        remove_columns=["messages"],
        desc="Tokenizing SFT val split",
    )

    logger.info(
        f"Dataset loaded: {len(tokenized_train)} train rows, {len(tokenized_val)} validation rows."
    )

    # 7. Initialize Completion-Only Data Collator
    # Qwen ChatML response template for assistant turn
    response_template = "<|im_start|>assistant\n"
    data_collator = DataCollatorForCompletionOnlyLM(
        response_template=response_template,
        tokenizer=tokenizer,
        pad_to_multiple_of=8,
    )

    # 8. SFTConfig / TrainingArguments Setup
    checkpoint_dir = Path(args.output_dir)
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    # Detect version-specific parameter names across transformers 4.x and 5.x
    import inspect
    sig = inspect.signature(SFTConfig.__init__)
    adaptive_kwargs = {}

    # Warmup parameter (transformers 4.x warmup_ratio vs 5.x warmup_steps as float ratio)
    if "warmup_ratio" in sig.parameters:
        adaptive_kwargs["warmup_ratio"] = args.warmup_ratio
    elif "warmup_steps" in sig.parameters:
        adaptive_kwargs["warmup_steps"] = args.warmup_ratio

    # Evaluation strategy parameter (transformers 4.x eval_strategy / evaluation_strategy)
    if "eval_strategy" in sig.parameters:
        adaptive_kwargs["eval_strategy"] = "steps"
    elif "evaluation_strategy" in sig.parameters:
        adaptive_kwargs["evaluation_strategy"] = "steps"

    # Configure SFT training arguments with memory and speed optimizations
    training_args = SFTConfig(
        output_dir=args.output_dir,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.eval_batch_size,
        gradient_accumulation_steps=args.gradient_accumulation_steps,
        learning_rate=args.learning_rate,
        lr_scheduler_type=args.lr_scheduler_type,
        weight_decay=args.weight_decay,
        num_train_epochs=args.num_train_epochs,
        max_steps=args.max_steps,
        bf16=True,
        optim="paged_adamw_8bit",
        gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        max_length=args.max_seq_length,
        # Step-based saving & evaluation
        eval_steps=args.eval_steps,
        save_strategy="steps",
        save_steps=args.save_steps,
        save_total_limit=args.save_total_limit,
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        logging_steps=10,
        dataloader_pin_memory=args.dataloader_pin_memory,
        dataloader_num_workers=args.dataloader_num_workers,
        report_to="none",
        dataset_kwargs={"skip_prepare_dataset": True},  # Already tokenized with chat template
        **adaptive_kwargs,
    )

    # 9. Initialize SFTTrainer
    trainer = SFTTrainer(
        model=model,
        args=training_args,
        train_dataset=tokenized_train,
        eval_dataset=tokenized_val,
        data_collator=data_collator,
        callbacks=[VRAMMonitoringCallback()],
    )

    # 10. Checkpoint Resolution & Execution
    resume_checkpoint = resolve_checkpoint(args.output_dir, args.resume_from_checkpoint)

    logger.info("Starting training loop...")
    log_gpu_vram("Pre-Training Start")
    train_result = trainer.train(resume_from_checkpoint=resume_checkpoint)

    # 11. Save Best Model Artifacts & Tokenizer
    logger.info("Training complete. Saving best LoRA adapter and tokenizer...")
    trainer.save_model(args.output_dir)
    tokenizer.save_pretrained(args.output_dir)

    # Log metrics
    metrics = train_result.metrics
    trainer.log_metrics("train", metrics)
    trainer.save_metrics("train", metrics)
    trainer.save_state()

    log_gpu_vram("Final State")
    logger.info(f"✅ SFT Training succeeded! Best LoRA adapter saved to: {args.output_dir}")


if __name__ == "__main__":
    main()
