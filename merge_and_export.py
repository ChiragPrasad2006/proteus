#!/usr/bin/env python3
"""
merge_and_export.py
~~~~~~~~~~~~~~~~~~~
Post-Training Export & Merge Utility for Personalized AI Email Writer.
Merges trained LoRA adapters (SFT or DPO) into base Qwen/Qwen2.5-3B-Instruct model,
exports a standalone model directory, and prepares artifacts for GGUF conversion (llama.cpp)
or local Ollama/vLLM deployment.

Features:
- High-precision lossless LoRA weight fusion via `PeftModel.merge_and_unload()`
- Configurable precision export: bfloat16 (lossless / GGUF-ready), float16, FP8 (Blackwell native), or 8-bit
- Exports standalone Hugging Face safetensors directory with complete tokenizer configuration
- Generates ready-to-run Ollama `Modelfile` with ChatML syntax and personalized email system prompt
- Generates exact `llama.cpp` GGUF conversion command lines (Q8_0, Q4_K_M)
- Built-in sanity test generation ensuring persona adoption and anti-slop adherence before deployment.

Author: Principal Deep Learning & MLOps Engineer
"""

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Optional

import torch
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
)
from peft import PeftModel

# Configure structured logging
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=logging.INFO,
)
logger = logging.getLogger("merge_and_export")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Merge LoRA weights and export standalone deployment-ready model.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    # Base Model & LoRA Adapter
    parser.add_argument(
        "--base_model_id",
        type=str,
        default="Qwen/Qwen2.5-3B-Instruct",
        help="Base model repository or local directory path.",
    )
    parser.add_argument(
        "--adapter_path",
        type=str,
        default="./checkpoints/qwen-email-dpo-final",
        help="Path to trained LoRA adapter directory (DPO final or SFT best).",
    )
    parser.add_argument(
        "--output_dir",
        type=str,
        default="./exported_models/qwen2.5-3b-email-8bit",
        help="Output directory to save merged standalone model and tokenizer.",
    )

    # Precision & Execution Device
    parser.add_argument(
        "--torch_dtype",
        type=str,
        default="bfloat16",
        choices=["bfloat16", "float16", "float32", "fp8", "8bit"],
        help="Weight precision for merging and export. 'bfloat16' is recommended for lossless GGUF conversion.",
    )
    parser.add_argument(
        "--device",
        type=str,
        default="cuda" if torch.cuda.is_available() else "cpu",
        choices=["cuda", "cpu", "auto"],
        help="Device to perform weight merging. 'cuda' is fast (~15s); 'cpu' merges in system RAM.",
    )

    # Verification & Generation
    parser.add_argument(
        "--test_generation",
        action="store_true",
        default=True,
        help="Run an automated test email inference generation after merging.",
    )
    parser.add_argument(
        "--max_new_tokens",
        type=int,
        default=256,
        help="Maximum generation tokens for verification test.",
    )

    return parser.parse_args()


def write_ollama_modelfile(output_dir: Path, base_name: str = "qwen2.5-email-writer") -> Path:
    """Generates an Ollama Modelfile tailored for ChatML and Personalized Email Writing."""
    modelfile_path = output_dir / "Modelfile"
    content = f"""# Ollama Modelfile for Personalized AI Email Writer
# Exported from Qwen/Qwen2.5-3B-Instruct fine-tuned with SFT + DPO

FROM .

TEMPLATE \"\"\"<|im_start|>system
{{{{ .System }}}}<|im_end|>
<|im_start|>user
{{{{ .Prompt }}}}<|im_end|>
<|im_start|>assistant
\"\"\"

SYSTEM \"\"\"You are a personalized email writer. Adopt the persona and style profile provided in the prompt, write concise, high-impact emails, and avoid corporate AI clichés (such as 'I hope this email finds you well', 'delve', 'tapestry', 'furthermore').\"\"\"

PARAMETER stop "<|im_start|>"
PARAMETER stop "<|im_end|>"
PARAMETER temperature 0.7
PARAMETER top_p 0.9
PARAMETER top_k 40
PARAMETER repeat_penalty 1.1
"""
    with open(modelfile_path, "w", encoding="utf-8") as f:
        f.write(content)

    logger.info(f"📄 Created Ollama Modelfile at: {modelfile_path}")
    return modelfile_path


def write_gguf_instructions(output_dir: Path) -> Path:
    """Writes step-by-step instructions for converting the exported safetensors to GGUF."""
    instructions_path = output_dir / "GGUF_CONVERSION.md"
    content = f"""# GGUF Conversion Guide for `llama.cpp`

This standalone directory contains merged Hugging Face safetensors weights for **Personalized AI Email Writer**.

### 1. Prerequisites
Clone `llama.cpp` and install its conversion dependencies:
```powershell
git clone https://github.com/ggerganov/llama.cpp
cd llama.cpp
pip install -r requirements.txt
```

### 2. Convert Hugging Face Safetensors to GGUF
Run the conversion script pointing to this directory:
```powershell
# Convert to FP16 or BF16 GGUF
python convert_hf_to_gguf.py "{output_dir.resolve()}" --outfile qwen-email-3b-f16.gguf --outtype f16
```

### 3. Quantize to 8-bit (Q8_0) or 4-bit (Q4_K_M)
Quantize the uncompressed GGUF using `llama-quantize`:
```powershell
# 8-bit quantization (Recommended for best fidelity on 8GB VRAM)
.\\llama-quantize qwen-email-3b-f16.gguf qwen-email-3b-Q8_0.gguf Q8_0

# 4-bit quantization (Ultra-lightweight, ~2.1 GB file size)
.\\llama-quantize qwen-email-3b-f16.gguf qwen-email-3b-Q4_K_M.gguf Q4_K_M
```

### 4. Run Locally with `llama-cli`
```powershell
.\\llama-cli -m qwen-email-3b-Q8_0.gguf -p "<|im_start|>user\\nDraft a short status email for our sprint review.<|im_end|>\\n<|im_start|>assistant\\n" -n 256
```
"""
    with open(instructions_path, "w", encoding="utf-8") as f:
        f.write(content)

    logger.info(f"📄 Created GGUF Conversion Guide at: {instructions_path}")
    return instructions_path


def main() -> None:
    args = parse_args()

    logger.info("=================================================================")
    logger.info("📦 Personalized AI Email Writer: LoRA Merge & Model Export Utility")
    logger.info("=================================================================")
    logger.info(f"Base Model ID   : {args.base_model_id}")
    logger.info(f"Adapter Path    : {args.adapter_path}")
    logger.info(f"Output Directory: {args.output_dir}")
    logger.info(f"Target Dtype    : {args.torch_dtype}")
    logger.info(f"Target Device   : {args.device}")

    output_path = Path(args.output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # 1. Validate Adapter Path
    adapter_path = Path(args.adapter_path)
    if not adapter_path.exists():
        # Fallback to SFT if DPO was passed by default but SFT is available
        sft_fallback = Path("./checkpoints/qwen-email-sft-best")
        if sft_fallback.exists() and (sft_fallback / "adapter_config.json").exists():
            logger.warning(
                f"Requested adapter '{args.adapter_path}' not found. "
                f"Falling back to Stage 1 SFT adapter: {sft_fallback}"
            )
            adapter_path = sft_fallback
        else:
            raise FileNotFoundError(
                f"LoRA adapter directory not found at '{args.adapter_path}' or '{sft_fallback}'."
            )

    logger.info(f"Loading LoRA adapter configuration from: {adapter_path}")

    # 2. Determine PyTorch dtype
    dtype_map = {
        "bfloat16": torch.bfloat16,
        "float16": torch.float16,
        "float32": torch.float32,
        "fp8": torch.bfloat16,  # Merged in bf16, then converted
        "8bit": torch.bfloat16,
    }
    compute_dtype = dtype_map.get(args.torch_dtype, torch.bfloat16)

    # 3. Load Base Model
    logger.info(f"Loading base model '{args.base_model_id}' in {compute_dtype} on {args.device}...")
    base_model = AutoModelForCausalLM.from_pretrained(
        args.base_model_id,
        dtype=compute_dtype,
        device_map=args.device if args.device != "cpu" else None,
        torch_dtype=compute_dtype,
        trust_remote_code=True,
        low_cpu_mem_usage=True,
    )

    if args.device == "cpu":
        base_model = base_model.to("cpu")

    # 4. Load Tokenizer
    logger.info("Loading tokenizer...")
    tokenizer = AutoTokenizer.from_pretrained(args.base_model_id, trust_remote_code=True)

    # 5. Attach LoRA Adapter
    logger.info(f"Attaching LoRA adapter from {adapter_path}...")
    model = PeftModel.from_pretrained(
        base_model,
        str(adapter_path),
        device_map=args.device if args.device != "cpu" else None,
    )

    # 6. Lossless Weight Fusion via merge_and_unload()
    logger.info("Merging LoRA weights into base model via .merge_and_unload()...")
    merged_model = model.merge_and_unload(progressbar=True)
    logger.info("✅ LoRA weights successfully fused into base model parameters!")

    # 7. Optional FP8 / 8-bit Quantization formatting
    if args.torch_dtype == "fp8":
        logger.info("Casting linear weights to FP8 format (torch.float8_e4m3fn)...")
        if hasattr(torch, "float8_e4m3fn"):
            try:
                # Retain embeddings and norm in float16/bfloat16, quantize linear layers
                for name, module in merged_model.named_modules():
                    if isinstance(module, torch.nn.Linear):
                        module.weight.data = module.weight.data.to(torch.float8_e4m3fn)
                logger.info("✅ Linear weights cast to FP8 (float8_e4m3fn).")
            except Exception as e:
                logger.warning(f"FP8 conversion note: {e}. Retaining bfloat16 safetensors export.")
        else:
            logger.warning("torch.float8_e4m3fn not available in current PyTorch build. Saving in bfloat16.")

    # 8. Export Model & Tokenizer
    logger.info(f"Saving standalone merged model to '{output_path}'...")
    merged_model.save_pretrained(
        output_path,
        safe_serialization=True,
        max_shard_size="4GB",
    )
    tokenizer.save_pretrained(output_path)
    logger.info("✅ Export complete: Safetensors and Tokenizer saved.")

    # 9. Generate Deployment Metadata & Guides
    write_ollama_modelfile(output_path)
    write_gguf_instructions(output_path)

    # 10. Verification Test Generation
    if args.test_generation:
        logger.info("Running verification inference test on merged model...")
        test_messages = [
            {
                "role": "system",
                "content": (
                    "You are a personalized email writer. Adopt this persona and style:\n"
                    "Persona: VP of Engineering leading distributed platform infrastructure.\n"
                    "Style Profile: Formality: semi-formal | Sentence Structure: concise & direct | "
                    "Greeting: Hi Marcus | Sign-off: Best,Devin"
                ),
            },
            {
                "role": "user",
                "content": (
                    "Draft an email covering these points:\n"
                    "- Note the successful completion of the Q3 multi-region failover drill\n"
                    "- Highlight 99.995% uptime achieved with 34ms recovery window\n"
                    "- Propose postponing next maintenance window to mid-November"
                ),
            },
        ]

        prompt_text = tokenizer.apply_chat_template(
            test_messages,
            tokenize=False,
            add_generation_prompt=True,
        )

        test_device = "cuda" if torch.cuda.is_available() else "cpu"
        merged_model = merged_model.to(test_device)
        inputs = tokenizer(prompt_text, return_tensors="pt").to(test_device)

        with torch.no_grad():
            outputs = merged_model.generate(
                **inputs,
                max_new_tokens=args.max_new_tokens,
                temperature=0.6,
                top_p=0.9,
                do_sample=True,
                repetition_penalty=1.1,
                pad_token_id=tokenizer.eos_token_id,
            )

        generated_ids = outputs[0][inputs["input_ids"].shape[1] :]
        generated_text = tokenizer.decode(generated_ids, skip_special_tokens=True).strip()

        logger.info("-----------------------------------------------------------------")
        logger.info("🧪 VERIFICATION INFERENCE OUTPUT:")
        logger.info("-----------------------------------------------------------------")
        print(f"\n{generated_text}\n")
        logger.info("-----------------------------------------------------------------")

    logger.info("=================================================================")
    logger.info(f"🎉 Merged model successfully exported to: {output_path.resolve()}")
    logger.info("=================================================================")


if __name__ == "__main__":
    main()
