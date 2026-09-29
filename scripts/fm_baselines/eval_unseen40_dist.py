#!/usr/bin/env python3
"""Socrates unseen-40 eval storing RAW probability distributions per cell.

This script stores the per-cell logprob distributions so they can be:
1. Re-scored with different temperature/top_p settings (calibration check)
2. Used for cross-fitted temperature evaluation

Output format (cell_distributions.jsonl):
  {study_id, condition_num, task_num, answer_range: [min, max], logprobs: {answer: logp}, 
   human_responses: [...], n_participants: int}

This enables CPU-only re-scoring without GPU for temperature calibration.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import torch
from datasets import load_dataset
from huggingface_hub import hf_hub_download
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

SYSTEM = (
    "You are simulating a survey respondent. Answer exactly as instructed, "
    "following the specified response format without additional commentary."
)


def get_answer_logprobs(
    model, tok, prompt: str, answer_range: tuple[int, int]
) -> dict[str, float]:
    """Get log probabilities for each answer in the range."""
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": prompt},
    ]
    text = tok.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True, enable_thinking=False
    )
    inputs = tok(text, return_tensors="pt", truncation=True, max_length=4096)
    inputs = {k: v.to(model.device) for k, v in inputs.items()}
    
    with torch.no_grad():
        outputs = model(**inputs)
        logits = outputs.logits[0, -1, :]
        log_probs = torch.log_softmax(logits, dim=-1)
    
    answer_logprobs = {}
    for ans in range(answer_range[0], answer_range[1] + 1):
        ans_str = str(ans)
        tokens = tok.encode(ans_str, add_special_tokens=False)
        if len(tokens) >= 1:
            token_id = tokens[0]
            answer_logprobs[ans_str] = log_probs[token_id].item()
    
    return answer_logprobs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="Qwen/Qwen3-14B", help="Base model")
    ap.add_argument("--lora", default=None, help="LoRA adapter path (local or gs://)")
    ap.add_argument("--name", default="model", help="Model name for output")
    ap.add_argument("--out", default="./results", help="Output directory")
    args = ap.parse_args()
    
    out_dir = Path(args.out) / args.name
    out_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Loading metadata...", flush=True)
    path = hf_hub_download(
        "socratesft/SocSci210",
        "metadata/participant_mapping.json",
        repo_type="dataset",
    )
    mapping = json.loads(Path(path).read_text())
    unseen = set(mapping["unseen"])
    print(f"Unseen studies: {len(unseen)}", flush=True)
    
    print("Loading dataset...", flush=True)
    ds = load_dataset("socratesft/SocSci210", split="train")
    rows = [r for r in ds if r["study_id"] in unseen]
    print(f"Total rows: {len(rows)}", flush=True)
    
    cells: dict[tuple, list] = defaultdict(list)
    for r in rows:
        key = (r["study_id"], str(r["condition_num"]), str(r["task_num"]))
        cells[key].append(r)
    print(f"Unique cells: {len(cells)}", flush=True)
    
    # Fetch adapter from GCS if needed
    lora_path = args.lora
    if lora_path and lora_path.startswith("gs://"):
        import subprocess
        local_dir = Path.home() / ".cache" / "simbench_adapters" / lora_path[5:].replace("/", "__")
        local_dir.mkdir(parents=True, exist_ok=True)
        need = ["adapter_config.json", "adapter_model.safetensors"]
        if not all((local_dir / f).exists() for f in need):
            print(f"Fetching adapter from {lora_path}...", flush=True)
            for f in need:
                src = f"{lora_path.rstrip('/')}/{f}"
                subprocess.run(["gsutil", "-q", "cp", src, str(local_dir)], check=True)
        lora_path = str(local_dir)
    
    print(f"Loading model {args.model} in 4-bit nf4...", flush=True)
    quant = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
        bnb_4bit_quant_type="nf4",
    )
    tok = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        args.model,
        quantization_config=quant,
        device_map="auto",
        trust_remote_code=True,
        torch_dtype=torch.bfloat16,
    )
    
    if lora_path:
        print(f"Loading LoRA adapter from {lora_path}...", flush=True)
        model = PeftModel.from_pretrained(model, lora_path)
    
    model.eval()
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    
    # Check for resume
    dist_path = out_dir / "cell_distributions.jsonl"
    done_cells = set()
    if dist_path.exists():
        with dist_path.open() as f:
            for line in f:
                if line.strip():
                    rec = json.loads(line)
                    done_cells.add((rec["study_id"], rec["condition_num"], rec["task_num"]))
        print(f"Resuming: {len(done_cells)} cells already done", flush=True)
    
    pending_cells = [(k, v) for k, v in cells.items() if k not in done_cells]
    print(f"Pending cells: {len(pending_cells)}", flush=True)
    
    start_time = time.time()
    
    with dist_path.open("a") as fout:
        for i, (key, items) in enumerate(pending_cells):
            study_id, cond, task = key
            prompt = items[0]["prompt"]
            
            human_responses = [float(r["response"]) for r in items]
            rmin, rmax = int(min(human_responses)), int(max(human_responses))
            ans_min = max(0, rmin - 2)
            ans_max = rmax + 2
            
            logprobs = get_answer_logprobs(model, tok, prompt, (ans_min, ans_max))
            
            if not logprobs:
                print(f"  Warning: no logprobs for cell {key}", flush=True)
                continue
            
            rec = {
                "study_id": study_id,
                "condition_num": cond,
                "task_num": task,
                "answer_range": [ans_min, ans_max],
                "logprobs": logprobs,
                "human_responses": human_responses,
                "n_participants": len(items),
            }
            fout.write(json.dumps(rec) + "\n")
            fout.flush()
            os.fsync(fout.fileno())
            
            elapsed = time.time() - start_time
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            eta = (len(pending_cells) - i - 1) / rate if rate > 0 else 0
            
            if (i + 1) % 50 == 0 or i == 0:
                print(
                    f"  Cell {i+1}/{len(pending_cells)}: {study_id}/{cond}/{task} "
                    f"rate={rate:.2f} cells/s ETA={eta/60:.1f}m",
                    flush=True
                )
    
    elapsed = time.time() - start_time
    print(f"\n{'='*60}", flush=True)
    print(f"Model: {args.name}", flush=True)
    print(f"Cells processed: {len(pending_cells)}", flush=True)
    print(f"Time: {elapsed/60:.1f} minutes", flush=True)
    print(f"Output: {dist_path}", flush=True)
    print(f"{'='*60}", flush=True)


if __name__ == "__main__":
    main()
