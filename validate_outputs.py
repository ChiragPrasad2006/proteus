#!/usr/bin/env python3
"""
validate_outputs.py
~~~~~~~~~~~~~~~~~~~
Post-generation QA harness for the two-stage dataset.

Checks per output file:
  1. Line counts vs target splits.
  2. Strict JSON parsing of every line (truncation / malformed detection).
  3. Schema validation (SFT ChatML messages, TRL DPO prompt/chosen/rejected).
  4. AI-slop regex scan: assistant / chosen must be clean, rejected must carry slop.
  5. Token length distributions via Qwen/Qwen2.5-3B-Instruct tokenizer.
  6. Train/val leakage check (no shared prompt/assistant content across splits).
"""

import importlib.util
import json
import sys
from pathlib import Path

rich_spec = importlib.util.find_spec("rich")

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from email_data_pipeline.config import AI_SLOP_REGEX  # noqa: E402

DATA = ROOT / "data"
MODEL_ID = "Qwen/Qwen2.5-3B-Instruct"

TARGETS = {
    "sft_email_train.jsonl": (9000, 12000),   # loose bounds around ~10,800
    "sft_email_val.jsonl": (500, 3000),
    "dpo_email_train.jsonl": (4000, 5000),
    "dpo_email_val.jsonl": (300, 800),
}


def load_jsonl(path: Path):
    rows, bad_lines = [], []
    with open(path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                bad_lines.append((i + 1, str(e)[:80]))
    return rows, bad_lines


def main() -> int:
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(MODEL_ID, trust_remote_code=True)

    def n_tokens(text: str) -> int:
        return len(tok.encode(text, add_special_tokens=False))

    report = {}
    exit_code = 0

    for fname, (lo, hi) in TARGETS.items():
        path = DATA / fname
        if not path.exists():
            print(f"[FAIL] {fname}: missing")
            exit_code = 1
            continue
        rows, bad = load_jsonl(path)
        n = len(rows)
        is_sft = fname.startswith("sft")

        # ---- JSON integrity ----
        ok_json = not bad

        # ---- Schema ----
        schema_ok = True
        slop_clean = 0
        slop_dirty = []
        rej_slop = 0
        prompts = []
        assts = []
        tok_p, tok_a, tok_tot = [], [], []

        for r in rows:
            if is_sft:
                msgs = r.get("messages") if isinstance(r, dict) else None
                if not isinstance(msgs, list) or len(msgs) != 3:
                    schema_ok = False
                    continue
                roles = [m.get("role") for m in msgs]
                if roles != ["system", "user", "assistant"]:
                    schema_ok = False
                    continue
                sys_c, usr_c, ast_c = (m.get("content", "") for m in msgs)
                if not sys_c or not usr_c or not ast_c:
                    schema_ok = False
                    continue
                if AI_SLOP_REGEX.search(ast_c):
                    slop_dirty.append(ast_c[:60])
                else:
                    slop_clean += 1
                assts.append(ast_c)
                # ChatML-formatted totals
                fmt = [
                    {"role": "system", "content": sys_c},
                    {"role": "user", "content": usr_c},
                    {"role": "assistant", "content": ast_c},
                ]
                try:
                    rendered = tok.apply_chat_template(fmt, tokenize=False)
                    total = n_tokens(rendered)
                except Exception:
                    prompt_text = f"<|im_start|>system\n{sys_c}<|im_end|>\n<|im_start|>user\n{usr_c}<|im_end|>\n<|im_start|>assistant\n"
                    total = n_tokens(prompt_text) + n_tokens(ast_c) + 3
                tok_tot.append(total)
                prompts.append(usr_c[:100])
            else:
                if not all(k in r for k in ("prompt", "chosen", "rejected")):
                    schema_ok = False
                    continue
                p, c, rej = str(r["prompt"]), str(r["chosen"]), str(r["rejected"])
                if not p or not c or not rej:
                    schema_ok = False
                    continue
                if AI_SLOP_REGEX.search(c):
                    slop_dirty.append(c[:60])
                else:
                    slop_clean += 1
                if AI_SLOP_REGEX.search(rej):
                    rej_slop += 1
                prompts.append(p[:100])
                tc, tr = n_tokens(c), n_tokens(rej)
                tp = n_tokens(p)
                tok_p.append(tp)
                tok_tot.append(tp + max(tc, tr))

        # ---- Token stats ----
        def pct(vals, q):
            s = sorted(vals)
            if not s:
                return 0
            idx = min(int(len(s) * q), len(s) - 1)
            return s[idx]

        n_tot = len(tok_tot)
        stats = None
        if n_tot:
            stats = (
                min(tok_tot),
                int(sum(tok_tot) / n_tot),
                pct(tok_tot, 0.5),
                pct(tok_tot, 0.95),
                max(tok_tot),
            )

        counts_ok = lo <= n <= hi
        clean_ok = not slop_dirty
        rej_ok = True
        if not is_sft and n:
            rej_ok = rej_slop == n  # every rejected must contain slop

        status = "OK  " if (ok_json and schema_ok and counts_ok and clean_ok and rej_ok) else "FAIL"
        if status == "FAIL":
            exit_code = 1

        print(f"[{status}] {fname}")
        print(f"      rows: {n} (target range {lo}-{hi}) {'OK' if counts_ok else 'OUT OF RANGE'}")
        print(f"      json: {'OK' if ok_json else 'BAD LINES ' + str(len(bad))} {'| ' + str(bad[:2]) if bad else ''}")
        print(f"      schema: {'OK' if schema_ok else 'INVALID'}")
        if is_sft:
            print(f"      assistant slop-free: {slop_clean}/{n}{' DIRTY: ' + str(slop_dirty[:2]) if slop_dirty else ''}")
        else:
            print(f"      chosen slop-free: {slop_clean}/{n}{' DIRTY: ' + str(slop_dirty[:2]) if slop_dirty else ''}")
            print(f"      rejected has-slop: {rej_slop}/{n}")
        if stats:
            print(f"      total tokens: min={stats[0]} mean={stats[1]} median={stats[2]} p95={stats[3]} max={stats[4]}")
        report[fname] = {"rows": n, "tokens": stats}

    # ---- Leakage checks ----
    def overlap(a: Path, b: Path, key_fn):
        ra, _ = load_jsonl(a)
        rb, _ = load_jsonl(b)
        return len(set(map(key_fn, ra)) & set(map(key_fn, rb)))

    ov_sft = overlap(DATA / "sft_email_train.jsonl", DATA / "sft_email_val.jsonl", lambda r: r["messages"][2]["content"][:150])
    ov_dpo = overlap(DATA / "dpo_email_train.jsonl", DATA / "dpo_email_val.jsonl", lambda r: r["chosen"][:150])
    print(f"[{'OK  ' if ov_sft == 0 else 'WARN'}] SFT train/val overlap: {ov_sft}")
    print(f"[{'OK  ' if ov_dpo == 0 else 'WARN'}] DPO train/val overlap: {ov_dpo}")

    total_sft = report.get("sft_email_train.jsonl", {}).get("rows", 0) + report.get("sft_email_val.jsonl", {}).get("rows", 0)
    total_dpo = report.get("dpo_email_train.jsonl", {}).get("rows", 0) + report.get("dpo_email_val.jsonl", {}).get("rows", 0)
    print(f"\nTOTALS: SFT={total_sft} (target ~12,000) | DPO={total_dpo} (target ~5,000)")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
