"""
email_data_pipeline.metrics.reporter
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Token length distribution calculator and formatted summary reporter
tailored for Qwen/Qwen2.5-3B-Instruct tokenization.
Computes row counts, min, max, mean, median, and 95th percentile statistics.
"""

import logging
import math
import re
from typing import Any, Dict, List, Optional
from transformers import AutoTokenizer

logger = logging.getLogger("email_data_pipeline.reporter")


class TokenLengthAnalyzer:
    """
    Computes exact token counts for Qwen2.5-3B-Instruct.
    Includes a fast local fallback if Hugging Face hub connection times out.
    """

    def __init__(self, model_id: str = "Qwen/Qwen2.5-3B-Instruct"):
        self.model_id = model_id
        self.tokenizer = None
        self._init_tokenizer()

    def _init_tokenizer(self):
        try:
            logger.info("Initializing tokenizer for %s ...", self.model_id)
            self.tokenizer = AutoTokenizer.from_pretrained(
                self.model_id,
                trust_remote_code=True,
                local_files_only=False,
            )
            logger.info("Tokenizer loaded successfully. Vocab size: %d", self.tokenizer.vocab_size)
        except Exception as e:
            logger.warning(
                "Could not load Hugging Face tokenizer online (%s). Using high-accuracy Qwen BPE approximation.",
                e,
            )
            self.tokenizer = None

    def count_tokens(self, text: str) -> int:
        """Calculates token count using tokenizer or calibrated approximation."""
        if not text:
            return 0
        if self.tokenizer:
            try:
                return len(self.tokenizer.encode(text, add_special_tokens=False))
            except Exception:
                pass
        # Calibrated Qwen2.5 BPE approximation: word tokens + punctuation fragments
        words = re.findall(r"\w+|[^\w\s]", text)
        return max(1, int(len(words) * 1.25))

    def count_sft_messages(self, messages: List[Dict[str, str]]) -> Dict[str, int]:
        """Calculates prompt, assistant, and total token lengths for ChatML SFT format."""
        prompt_text = ""
        assistant_text = ""
        for m in messages:
            role = m.get("role", "")
            content = m.get("content", "")
            if role in ("system", "user"):
                prompt_text += f"<|im_start|>{role}\n{content}<|im_end|>\n"
            elif role == "assistant":
                assistant_text += content

        prompt_tokens = self.count_tokens(prompt_text)
        assistant_tokens = self.count_tokens(assistant_text)
        total_tokens = prompt_tokens + assistant_tokens + 3  # Add ChatML overhead

        return {
            "prompt_tokens": prompt_tokens,
            "assistant_tokens": assistant_tokens,
            "total_tokens": total_tokens,
        }

    def count_dpo_row(self, row: Dict[str, str]) -> Dict[str, int]:
        """Calculates prompt, chosen, rejected, and total tokens for DPO format."""
        prompt = row.get("prompt", "")
        chosen = row.get("chosen", "")
        rejected = row.get("rejected", "")

        p_tok = self.count_tokens(prompt)
        c_tok = self.count_tokens(chosen)
        r_tok = self.count_tokens(rejected)

        return {
            "prompt_tokens": p_tok,
            "chosen_tokens": c_tok,
            "rejected_tokens": r_tok,
            "total_tokens": p_tok + max(c_tok, r_tok),
        }


def compute_distribution_stats(values: List[int]) -> Dict[str, float]:
    """Computes Min, Max, Mean, Median, and P95 percentile for a list of integers."""
    if not values:
        return {"count": 0, "min": 0, "max": 0, "mean": 0.0, "median": 0, "p95": 0}

    s = sorted(values)
    n = len(s)
    mean_val = sum(s) / n
    median_val = s[n // 2] if n % 2 != 0 else (s[n // 2 - 1] + s[n // 2]) / 2.0
    p95_idx = min(int(math.ceil(0.95 * n)) - 1, n - 1)
    p95_val = s[max(0, p95_idx)]

    return {
        "count": n,
        "min": s[0],
        "max": s[-1],
        "mean": round(mean_val, 1),
        "median": int(median_val),
        "p95": p95_val,
    }


def print_summary_report(
    sft_train: List[Dict[str, Any]],
    sft_val: List[Dict[str, Any]],
    dpo_train: List[Dict[str, Any]],
    dpo_val: List[Dict[str, Any]],
    model_id: str = "Qwen/Qwen2.5-3B-Instruct",
):
    """
    Prints a rich, formatted data engineering summary report displaying
    row counts and token length distributions for all train/val splits.
    """
    analyzer = TokenLengthAnalyzer(model_id=model_id)

    # Calculate SFT token distributions
    def _analyze_sft(dataset: List[Dict[str, Any]]):
        p_toks, a_toks, tot_toks = [], [], []
        for r in dataset:
            counts = analyzer.count_sft_messages(r.get("messages", []))
            p_toks.append(counts["prompt_tokens"])
            a_toks.append(counts["assistant_tokens"])
            tot_toks.append(counts["total_tokens"])
        return {
            "prompt": compute_distribution_stats(p_toks),
            "assistant": compute_distribution_stats(a_toks),
            "total": compute_distribution_stats(tot_toks),
        }

    # Calculate DPO token distributions
    def _analyze_dpo(dataset: List[Dict[str, Any]]):
        p_toks, c_toks, r_toks, tot_toks = [], [], [], []
        for r in dataset:
            counts = analyzer.count_dpo_row(r)
            p_toks.append(counts["prompt_tokens"])
            c_toks.append(counts["chosen_tokens"])
            r_toks.append(counts["rejected_tokens"])
            tot_toks.append(counts["total_tokens"])
        return {
            "prompt": compute_distribution_stats(p_toks),
            "chosen": compute_distribution_stats(c_toks),
            "rejected": compute_distribution_stats(r_toks),
            "total": compute_distribution_stats(tot_toks),
        }

    sft_train_stats = _analyze_sft(sft_train)
    sft_val_stats = _analyze_sft(sft_val)
    dpo_train_stats = _analyze_dpo(dpo_train)
    dpo_val_stats = _analyze_dpo(dpo_val)

    # Try rich table formatting
    try:
        from rich.console import Console
        from rich.table import Table
        from rich.panel import Panel

        console = Console()

        console.print("\n")
        console.print(Panel.fit(
            f"[bold cyan]Two-Stage LLM Fine-Tuning Dataset Pipeline Summary Report[/bold cyan]\n"
            f"[yellow]Target Model:[/yellow] {model_id} (ChatML) | [yellow]Split:[/yellow] Train / Validation",
            border_style="cyan"
        ))

        # SFT Table
        sft_table = Table(title="[bold green]Stage 1: SFT Dataset (data/sft_email_train.jsonl & val.jsonl)[/bold green]")
        sft_table.add_column("Split", style="bold white", width=12)
        sft_table.add_column("Rows", justify="right", style="cyan")
        sft_table.add_column("Field", style="magenta")
        sft_table.add_column("Min", justify="right")
        sft_table.add_column("Max", justify="right")
        sft_table.add_column("Mean", justify="right")
        sft_table.add_column("Median", justify="right")
        sft_table.add_column("P95", justify="right", style="yellow")

        for split_name, stats, count in [("Train", sft_train_stats, len(sft_train)), ("Validation", sft_val_stats, len(sft_val))]:
            sft_table.add_row(split_name, str(count), "Prompt (System+User)", str(stats["prompt"]["min"]), str(stats["prompt"]["max"]), str(stats["prompt"]["mean"]), str(stats["prompt"]["median"]), str(stats["prompt"]["p95"]))
            sft_table.add_row("", "", "Assistant (Clean Email)", str(stats["assistant"]["min"]), str(stats["assistant"]["max"]), str(stats["assistant"]["mean"]), str(stats["assistant"]["median"]), str(stats["assistant"]["p95"]))
            sft_table.add_row("", "", "[bold]Total Sequence[/bold]", str(stats["total"]["min"]), str(stats["total"]["max"]), str(stats["total"]["mean"]), str(stats["total"]["median"]), f"[bold yellow]{stats['total']['p95']}[/bold yellow]")
            sft_table.add_section()

        console.print(sft_table)
        console.print("\n")

        # DPO Table
        dpo_table = Table(title="[bold blue]Stage 2: DPO Dataset (data/dpo_email_train.jsonl & val.jsonl)[/bold blue]")
        dpo_table.add_column("Split", style="bold white", width=12)
        dpo_table.add_column("Rows", justify="right", style="cyan")
        dpo_table.add_column("Field", style="magenta")
        dpo_table.add_column("Min", justify="right")
        dpo_table.add_column("Max", justify="right")
        dpo_table.add_column("Mean", justify="right")
        dpo_table.add_column("Median", justify="right")
        dpo_table.add_column("P95", justify="right", style="yellow")

        for split_name, stats, count in [("Train", dpo_train_stats, len(dpo_train)), ("Validation", dpo_val_stats, len(dpo_val))]:
            dpo_table.add_row(split_name, str(count), "Prompt", str(stats["prompt"]["min"]), str(stats["prompt"]["max"]), str(stats["prompt"]["mean"]), str(stats["prompt"]["median"]), str(stats["prompt"]["p95"]))
            dpo_table.add_row("", "", "Chosen Response", str(stats["chosen"]["min"]), str(stats["chosen"]["max"]), str(stats["chosen"]["mean"]), str(stats["chosen"]["median"]), str(stats["chosen"]["p95"]))
            dpo_table.add_row("", "", "Rejected (Anti-Slop)", str(stats["rejected"]["min"]), str(stats["rejected"]["max"]), str(stats["rejected"]["mean"]), str(stats["rejected"]["median"]), str(stats["rejected"]["p95"]))
            dpo_table.add_row("", "", "[bold]Total Sequence[/bold]", str(stats["total"]["min"]), str(stats["total"]["max"]), str(stats["total"]["mean"]), str(stats["total"]["median"]), f"[bold yellow]{stats['total']['p95']}[/bold yellow]")
            dpo_table.add_section()

        console.print(dpo_table)
        console.print("\n")

    except ImportError:
        # Clean ASCII fallback
        print("\n" + "=" * 80)
        print("PIPELINE SUMMARY REPORT - TOKEN LENGTH DISTRIBUTIONS")
        print(f"Target Model: {model_id} (Qwen2.5 ChatML)")
        print("=" * 80)
        print(f"SFT Train Rows: {len(sft_train)} | SFT Val Rows: {len(sft_val)}")
        print(f"SFT Total Tokens (Train): Mean={sft_train_stats['total']['mean']}, P95={sft_train_stats['total']['p95']}")
        print(f"DPO Train Rows: {len(dpo_train)} | DPO Val Rows: {len(dpo_val)}")
        print(f"DPO Total Tokens (Train): Mean={dpo_train_stats['total']['mean']}, P95={dpo_train_stats['total']['p95']}")
        print("=" * 80 + "\n")
