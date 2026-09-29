#!/usr/bin/env python3
"""Fast Socrates unseen-40 eval using next-token probabilities.

Instead of generating 482k samples (one per participant), this script:
1. Groups data by unique (study, condition, task) cells (~803 prompts)
2. For each prompt, computes probability distribution over answer tokens
3. Samples from that distribution to match participant count per cell
4. Computes Wasserstein and accuracy metrics

Target: ~1 hour per model on L4 (vs ~29 hours with generation-based approach).
"""
from __future__ import annotations

import argparse
import json
import os
import re
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


def wasserstein_1d(a: np.ndarray, b: np.ndarray) -> float:
    """Wasserstein-1 distance using quantile matching."""
    a = np.sort(a.astype(float))
    b = np.sort(b.astype(float))
    n = 256
    qa = np.quantile(a, np.linspace(0, 1, n))
    qb = np.quantile(b, np.linspace(0, 1, n))
    return float(np.mean(np.abs(qa - qb)))


def get_digit_token_ids(tok) -> dict[int, int]:
    """Get token IDs for single digit tokens (0-9)."""
    digit_tokens = {}
    for d in range(10):
        # Try different formats
        for fmt in [str(d), f" {d}", f"{d} "]:
            tokens = tok.encode(fmt, add_special_tokens=False)
            if len(tokens) == 1:
                digit_tokens[d] = tokens[0]
                break
    return digit_tokens


def get_answer_logprobs(
    model, tok, prompt: str, answer_range: tuple[int, int]
) -> dict[int, float]:
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
        logits = outputs.logits[0, -1, :]  # Last token logits
        log_probs = torch.log_softmax(logits, dim=-1)
    
    answer_logprobs = {}
    for ans in range(answer_range[0], answer_range[1] + 1):
        # Get token ID for this answer
        ans_str = str(ans)
        tokens = tok.encode(ans_str, add_special_tokens=False)
        if len(tokens) >= 1:
            # Use first token (handles multi-digit)
            token_id = tokens[0]
            answer_logprobs[ans] = log_probs[token_id].item()
    
    return answer_logprobs


def sample_from_probs(
    logprobs: dict[int, float], n_samples: int, seed: int = 42
) -> list[int]:
    """Sample n_samples from the probability distribution."""
    answers = sorted(logprobs.keys())
    log_vals = np.array([logprobs[a] for a in answers])
    probs = np.exp(log_vals - np.max(log_vals))  # Normalize
    probs = probs / probs.sum()
    
    rng = np.random.default_rng(seed)
    samples = rng.choice(answers, size=n_samples, p=probs)
    return samples.tolist()


def expected_value_from_probs(logprobs: dict[int, float]) -> float:
    """Compute expected value from log probabilities."""
    answers = sorted(logprobs.keys())
    log_vals = np.array([logprobs[a] for a in answers])
    probs = np.exp(log_vals - np.max(log_vals))
    probs = probs / probs.sum()
    return float(np.sum(np.array(answers) * probs))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="Qwen/Qwen3-14B", help="Base model")
    ap.add_argument("--lora", default=None, help="LoRA adapter path")
    ap.add_argument("--name", default="model", help="Model name for output")
    ap.add_argument("--out", default="./results", help="Output directory")
    ap.add_argument("--method", default="sample", choices=["sample", "expected"],
                    help="sample: sample from probs, expected: use expected value")
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
    
    # Group by cell (study, condition, task)
    cells: dict[tuple, list] = defaultdict(list)
    for r in rows:
        key = (r["study_id"], str(r["condition_num"]), str(r["task_num"]))
        cells[key].append(r)
    print(f"Unique cells: {len(cells)}", flush=True)
    
    # Load model
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
    
    if args.lora:
        print(f"Loading LoRA adapter from {args.lora}...", flush=True)
        model = PeftModel.from_pretrained(model, args.lora)
    
    model.eval()
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    
    # Check for resume
    preds_path = out_dir / "predictions.jsonl"
    done_cells = set()
    if preds_path.exists():
        with preds_path.open() as f:
            for line in f:
                if line.strip():
                    rec = json.loads(line)
                    done_cells.add((rec["study_id"], rec["condition_num"], rec["task_num"]))
        print(f"Resuming: {len(done_cells)} cells already done", flush=True)
    
    pending_cells = [(k, v) for k, v in cells.items() if k not in done_cells]
    print(f"Pending cells: {len(pending_cells)}", flush=True)
    
    start_time = time.time()
    
    with preds_path.open("a") as fout:
        for i, (key, items) in enumerate(pending_cells):
            study_id, cond, task = key
            prompt = items[0]["prompt"]  # Same prompt for all participants in cell
            
            # Determine answer range from human responses
            human_responses = [float(r["response"]) for r in items]
            rmin, rmax = int(min(human_responses)), int(max(human_responses))
            # Extend range slightly for model predictions
            ans_min = max(0, rmin - 2)
            ans_max = rmax + 2
            
            # Get logprobs for answer range
            logprobs = get_answer_logprobs(model, tok, prompt, (ans_min, ans_max))
            
            if not logprobs:
                print(f"  Warning: no logprobs for cell {key}", flush=True)
                continue
            
            # Generate predictions for each participant
            if args.method == "sample":
                preds = sample_from_probs(logprobs, len(items), seed=hash(key) % (2**31))
            else:
                ev = expected_value_from_probs(logprobs)
                preds = [ev] * len(items)
            
            # Write predictions (one per participant for compatibility with metric)
            for r, pred in zip(items, preds):
                rec = {
                    "study_id": study_id,
                    "condition_num": cond,
                    "task_num": task,
                    "participant": r.get("participant", r.get("sample_id", "")),
                    "human": r["response"],
                    "pred": pred,
                    "method": args.method,
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
    
    # Load all predictions and compute metrics
    print("\nComputing metrics...", flush=True)
    preds = []
    with preds_path.open() as f:
        for line in f:
            if line.strip():
                preds.append(json.loads(line))
    
    # Group by cell for Wasserstein
    by_cell: dict[tuple, list] = defaultdict(list)
    for p in preds:
        if p.get("pred") is None:
            continue
        try:
            h = float(p["human"])
            m = float(p["pred"])
        except (TypeError, ValueError):
            continue
        key = (p["study_id"], p["condition_num"], p["task_num"])
        by_cell[key].append((h, m))
    
    # Compute Wasserstein
    study_scores: dict[str, list[float]] = defaultdict(list)
    raw_errors = []
    clipped_errors = []
    
    for key, items in by_cell.items():
        if len(items) < 2:
            continue
        humans = np.array([h for h, _ in items], dtype=float)
        models = np.array([m for _, m in items], dtype=float)
        
        rmin, rmax = float(humans.min()), float(humans.max())
        if rmax <= rmin:
            continue
        
        h_s = (humans - rmin) / (rmax - rmin)
        m_s = (models - rmin) / (rmax - rmin)
        m_s_clip = np.clip(m_s, 0.0, 1.0)
        
        w = wasserstein_1d(h_s, m_s_clip)
        study_scores[key[0]].append(w)
        
        # Accuracy: 1 - normalized MAE
        raw_errors.extend(np.abs(h_s - m_s).tolist())
        clipped_errors.extend(np.abs(h_s - m_s_clip).tolist())
    
    per_study = {s: float(np.mean(v)) for s, v in study_scores.items() if v}
    w_mean = float(np.mean(list(per_study.values()))) if per_study else None
    acc_raw = 1 - float(np.mean(raw_errors)) if raw_errors else None
    acc_clip = 1 - float(np.mean(clipped_errors)) if clipped_errors else None
    
    summary = {
        "model": args.model,
        "lora": args.lora,
        "name": args.name,
        "method": args.method,
        "n_cells": len(by_cell),
        "n_studies": len(per_study),
        "n_preds": len(preds),
        "wasserstein_mean": w_mean,
        "accuracy_raw": acc_raw,
        "accuracy_clipped": acc_clip,
        "per_study": per_study,
        "elapsed_seconds": time.time() - start_time,
    }
    
    (out_dir / "SUMMARY.json").write_text(json.dumps(summary, indent=2))
    
    print(f"\n{'='*60}", flush=True)
    print(f"Model: {args.name}", flush=True)
    print(f"Method: {args.method}", flush=True)
    print(f"Studies: {len(per_study)}/40", flush=True)
    print(f"Wasserstein W: {w_mean:.4f}" if w_mean else "W: N/A", flush=True)
    print(f"Accuracy (raw): {100*acc_raw:.2f}%" if acc_raw else "Acc raw: N/A", flush=True)
    print(f"Accuracy (clipped): {100*acc_clip:.2f}%" if acc_clip else "Acc clip: N/A", flush=True)
    print(f"Time: {(time.time() - start_time)/60:.1f} minutes", flush=True)
    print(f"{'='*60}", flush=True)
    
    # Reference: Zero-shot W=0.215, raw=67.0%, clipped=73.2%
    print("\nReference (zero-shot generation-based):", flush=True)
    print("  W=0.215, raw=67.0%, clipped=73.2%", flush=True)


if __name__ == "__main__":
    main()
