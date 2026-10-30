# Personalized AI Email Writer: Two-Stage Fine-Tuning Data Pipeline

A complete, production-grade, modular Python data engineering pipeline built with Hugging Face `datasets` for preparing training data for a **Two-Stage LLM Fine-Tuning Workflow** targeting **`Qwen/Qwen2.5-3B-Instruct`**:
- **Stage 1: Supervised Fine-Tuning (SFT)** &rarr; Adopting detailed personas, custom style profiles, and writing email drafts from raw user intent bullet points.
- **Stage 2: Direct Preference Optimization (DPO)** &rarr; Penalizing robotic AI clichés and corporate slop (*"I hope this email finds you well"*, *"delve"*, *"testament"*, *"tapestry"*, *"furthermore"*, *"in conclusion"*).

---

## 🏗️ Architecture & Pipeline Overview

```
                      ┌────────────────────────────────────────────────────────┐
                      │                   Input Datasets                       │
                      └───────┬──────────────────┬───────────────────┬─────────┘
                              │                  │                   │
                              ▼                  ▼                   ▼
                     [ FinePersonas ]      [ PersonaHub ]      [ Capybara DPO ]
                     (Synthetic Email)       ('persona')          (Binarized)
                              │                  │                   │
                              │                  │                   │
┌─────────────────────────────┼──────────────────┼───────────────────┼──────────────────────────────┐
│ Filters & Transformers      │                  │                   │                              │
│                             ▼                  ▼                   ▼                              │
│                      [Email Regex]      [Workplace Filter]  [Task Filter: Writing]                │
│                      - Case-insensitive - Exclude NPCs      - Exclude code/math                   │
│                      - Drop < 150 chars - Exclude fantasy   - Turn length <= 6                    │
│                             │                  │                   │                              │
│                             ▼                  ▼                   ▼                              │
│                      [De-Slop Target]   [Async Synthesizer] [Anti-Slop Logic]                     │
│                      - Strip buzzwords  - Scenarios         - Chosen: Clean only                  │
│                      - Style Extract    - Intent Bullets    - Rejected: Penalize slop             │
│                      - Intent Bullets   - Style Profile     - Slop Augment fallback               │
└─────────────────────────────┬──────────────────┬───────────────────┬──────────────────────────────┘
                              │                  │                   │
                              ▼                  ▼                   │
                     ┌──────────────────────────────────┐            │
                     │ MinHash & Exact SHA-256 Dedupe   │            │
                     └────────────────┬─────────────────┘            │
                                      │                              │
                                      ▼                              ▼
                         [ Stage 1: SFT Dataset ]       [ Stage 2: DPO Dataset ]
                         Standard HF Messages           TRL DPOTrainer Format
                                      │                              │
                                      ▼                              ▼
                         data/sft_email_train.jsonl     data/dpo_email_train.jsonl
                         data/sft_email_val.jsonl       data/dpo_email_val.jsonl
```

---

## 📦 Package Layout

```
Email-writer-2.5-3B/
├── email_data_pipeline/
│   ├── __init__.py
│   ├── config.py              # Central pipeline configurations, regexes, and dataclasses
│   ├── filters/
│   │   ├── __init__.py
│   │   ├── deslop.py          # AI buzzword regex detection and slop penalization
│   │   ├── persona_filter.py  # Workplace persona classifier & fantasy/NPC exclusion
│   │   └── text_cleaner.py    # Markdown/HTML cleaning, length checks, email keywords
│   ├── deduplication/
│   │   ├── __init__.py
│   │   └── deduplicator.py    # Exact xxhash + 64-perm MinHash Jaccard deduplicator
│   ├── synthesis/
│   │   ├── __init__.py
│   │   ├── scenarios.py       # Workplace scenario templates (salary negotiation, outages, etc.)
│   │   ├── style_extractor.py # Deterministic tone, greeting, sign-off, sentence length extractor
│   │   └── llm_synthesizer.py # Batched async LLM client (Ollama/vLLM/OpenAI) + offline generator
│   ├── processors/
│   │   ├── __init__.py
│   │   ├── base.py            # Base processor abstract class
│   │   ├── dataset_a.py       # FinePersonas email conversation processor
│   │   ├── dataset_b.py       # PersonaHub workplace synthesizer
│   │   └── dataset_c.py       # Capybara DPO processor with anti-slop pair logic
│   ├── metrics/
│   │   ├── __init__.py
│   │   └── reporter.py        # Token distribution analyzer (Qwen2.5) & Rich summary reporter
│   └── pipeline.py            # Orchestrator with streaming, batching, and train/val splits
├── pipeline.py                # Top-level CLI entry point
├── requirements.txt           # Dependencies
└── data/                      # Output JSONL datasets
    ├── sft_email_train.jsonl
    ├── sft_email_val.jsonl
    ├── dpo_email_train.jsonl
    └── dpo_email_val.jsonl
```

---

## 💾 Memory Efficiency (16GB RAM Constraints)

To run cleanly on local developer machines with 16GB RAM:
1. **Streaming Execution (`streaming=True`)**: Shards are fetched incrementally from Hugging Face Hub using PyArrow / Parquet streams. Datasets never reside entirely in RAM.
2. **Batched Processing (`.map(..., batched=True)`)**: Processing and async LLM synthesis operate in chunks of 100–250 rows.
3. **Buffered JSONL Writer**: Memory-buffered file writers with periodic `.flush()` prevent object accumulation in memory.
4. **Lightweight Deduplication**: Uses 64-bit integer hashes for exact deduplication and a fixed-window MinHash ring buffer, keeping memory footprint below **60MB**.
5. **Garbage Collection**: Explicit `gc.collect()` calls between pipeline stages.

---

## 📋 Target Output Schemas

### Output File 1: SFT (`data/sft_email_train.jsonl` & `val.jsonl`)
Standard Hugging Face ChatML messages schema:
```json
{
  "messages": [
    {
      "role": "system",
      "content": "You are a personalized email writer. Adopt this persona and style:\nPersona: A senior engineering director managing distributed infrastructure teams.\nStyle Profile: Tone: Executive, Decisive & Concise | Greeting: Direct (No Salutation) | Sign-off: Concise ('Best') | Sentence Structure: Short & Punchy (~11 words/sentence)"
    },
    {
      "role": "user",
      "content": "Draft an email covering these points:\n- Outline proposed $45k compute allocation for local LLM fine-tuning.\n- Contrast internal model ROI against recurring proprietary API costs (projected 4.2x savings).\n- Request sign-off ahead of the Q1 procurement cutoff."
    },
    {
      "role": "assistant",
      "content": "Team,\n\nFollowing up on our infrastructure budget planning for Q1. We are requesting approval for a $45,000 compute allocation for self-hosted LLM fine-tuning.\n\nMigrating our high-volume workflows from third-party APIs to an in-house model will deliver approximately 4.2x savings over the next twelve months based on current query telemetry.\n\nPlease review and provide procurement sign-off by Thursday at 3 PM.\n\nBest,\nMarcus"
    }
  ]
}
```

### Output File 2: DPO (`data/dpo_email_train.jsonl` & `val.jsonl`)
TRL `DPOTrainer` schema:
```json
{
  "prompt": "<|im_start|>user\nCould you review this project update memo before we send it to stakeholders?<|im_end|>\n<|im_start|>assistant\n",
  "chosen": "Here is a refined version that cuts unnecessary jargon, clarifies the delivery date, and highlights the key technical deliverables...",
  "rejected": "Dear Colleague,\n\nI hope this email finds you well in today's fast-paced corporate landscape.\n\nFurthermore, as we delve into the multifaceted dimensions of this initiative, it is important to remember that our collaboration stands as a profound testament to innovation within our organizational tapestry.\n\nIn conclusion, navigating this landscape will seamlessly foster synergy across all key verticals.\n\nBest regards,\nAutomated System"
}
```

---

## 🚀 Quickstart & Usage

### 1. Environment Setup
```powershell
# install dependencies
pip install -r requirements.txt
```

### 2. Run with Local Ollama / vLLM Server (Live Synthesis)
Ensure Ollama or vLLM is running locally:
```powershell
# In terminal 1 (start Ollama):
ollama run qwen2.5:3b

# In terminal 2 (run pipeline):
python pipeline.py --llm-base-url http://localhost:11434/v1 --llm-model qwen2.5:3b --max-samples-a 5000 --max-samples-b 3000 --max-samples-c 4000
```

### 3. Run in Offline / Deterministic Synthesis Mode
If no local LLM server is running, use `--offline-synthesis` for instant, deterministic generation:
```powershell
python pipeline.py --offline-synthesis --max-samples-a 5000 --max-samples-b 3000 --max-samples-c 4000
```

### 4. Fast Verification Dry Run
```powershell
python pipeline.py --max-samples-a 50 --max-samples-b 50 --max-samples-c 50 --offline-synthesis
```

---

## 📊 Summary Report Example
Before saving datasets to disk, the pipeline computes and prints exact token length distributions using the target `Qwen/Qwen2.5-3B-Instruct` tokenizer:

```
+-----------------------------------------------------------------------------+
| Two-Stage LLM Fine-Tuning Dataset Pipeline Summary Report                   |
| Target Model: Qwen/Qwen2.5-3B-Instruct (ChatML) | Split: Train / Validation |
+-----------------------------------------------------------------------------+
         Stage 1: SFT Dataset (data/sft_email_train.jsonl & val.jsonl)         
+-----------------------------------------------------------------------------+
| Split        | Rows | Field              | Min | Max |  Mean | Median | P95 |
|--------------+------+--------------------+-----+-----+-------+--------+-----|
| Train        | 4500 | Prompt (Sys+User)  | 110 | 185 | 145.2 |    144 | 172 |
|              |      | Assistant (Email)  |  65 | 450 | 170.1 |    162 | 335 |
|              |      | Total Sequence     | 185 | 620 | 318.4 |    310 | 505 |
|--------------+------+--------------------+-----+-----+-------+--------+-----|
| Validation   |  500 | Total Sequence     | 190 | 590 | 312.0 |    305 | 495 |
+-----------------------------------------------------------------------------+
```

---

## 🎯 Fine-Tuning with TRL

### Stage 1: SFT with `SFTTrainer`
```python
from datasets import load_dataset
from trl import SFTTrainer, SFTConfig
from transformers import AutoModelForCausalLM, AutoTokenizer

model_id = "Qwen/Qwen2.5-3B-Instruct"
tokenizer = AutoTokenizer.from_pretrained(model_id)
model = AutoModelForCausalLM.from_pretrained(model_id, torch_dtype="bfloat16", device_map="auto")

dataset = load_dataset("json", data_files={"train": "data/sft_email_train.jsonl", "validation": "data/sft_email_val.jsonl"})

training_args = SFTConfig(
    output_dir="./qwen2.5-email-sft",
    max_seq_length=1024,
    per_device_train_batch_size=4,
    gradient_accumulation_steps=4,
    learning_rate=2e-5,
    bf16=True,
    num_train_epochs=3,
    logging_steps=10,
)

trainer = SFTTrainer(
    model=model,
    train_dataset=dataset["train"],
    eval_dataset=dataset["validation"],
    args=training_args,
)
trainer.train()
```

### Stage 2: DPO with `DPOTrainer`
```python
from datasets import load_dataset
from trl import DPOTrainer, DPOConfig
from transformers import AutoModelForCausalLM, AutoTokenizer

sft_model_path = "./qwen2.5-email-sft"
model = AutoModelForCausalLM.from_pretrained(sft_model_path, torch_dtype="bfloat16", device_map="auto")
tokenizer = AutoTokenizer.from_pretrained(sft_model_path)

dataset = load_dataset("json", data_files={"train": "data/dpo_email_train.jsonl", "validation": "data/dpo_email_val.jsonl"})

dpo_args = DPOConfig(
    output_dir="./qwen2.5-email-dpo",
    beta=0.1,
    learning_rate=5e-7,
    per_device_train_batch_size=2,
    gradient_accumulation_steps=8,
    bf16=True,
    num_train_epochs=1,
)

dpo_trainer = DPOTrainer(
    model=model,
    train_dataset=dataset["train"],
    eval_dataset=dataset["validation"],
    tokenizer=tokenizer,
    args=dpo_args,
)
dpo_trainer.train()
```
