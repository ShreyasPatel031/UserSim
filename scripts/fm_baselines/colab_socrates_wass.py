#!/usr/bin/env python3
"""Reproduce Socrates Wasserstein on SocSci210 unseen studies (paper §5.3).

Metric (paper): for each (condition, outcome) cell, standardize responses to
[0,1] with human rmin/rmax, compute Wasserstein-1 between human and model
response arrays, average over cells in a study, then average over studies.
Target: W≈0.151 for socrates-qwen2.5-14b-sft on unseen studies.
Inference: temperature=0.6, top_p=0.9.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path("/content/fm_baselines")
RESULTS = ROOT / "results" / "socrates"
META = ROOT / "data" / "SocSci210_meta" / "metadata" / "participant_mapping.json"
MODEL = os.environ.get("SOCRATES_MODEL", "socratesft/socrates-qwen2.5-14b-sft")
SMOKE_STUDIES = int(os.environ.get("SMOKE_STUDIES", "0"))  # 0 = all 40 unseen
MAX_PER_CELL = int(os.environ.get("MAX_PER_CELL", "0"))  # 0 = all humans in cell
SYSTEM = (
    "You are simulating a survey respondent. Answer exactly as instructed, "
    "following the specified response format without additional commentary."
)


def sh(cmd: str) -> None:
    print("+", cmd, flush=True)
    subprocess.run(cmd, shell=True, check=True)


def install() -> None:
    sh(f"{sys.executable} -m pip install -q -U pip")
    sh(
        f"{sys.executable} -m pip install -q "
        "torch transformers accelerate bitsandbytes datasets huggingface_hub "
        "scipy numpy sentencepiece protobuf"
    )


def parse_numeric(text: str) -> float | None:
    if text is None:
        return None
    t = text.strip()
    # common formats: "5", "5.", "Answer: 5", "I choose 2"
    m = re.search(r"(?<![\d.])(-?\d+(?:\.\d+)?)(?![\d])", t)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def wasserstein_1d(a: np.ndarray, b: np.ndarray) -> float:
    # Pure numpy 1D Wasserstein (Earth Mover) for 1D samples
    a = np.sort(a.astype(float))
    b = np.sort(b.astype(float))
    # quantile matching
    n = 256
    qa = np.quantile(a, np.linspace(0, 1, n))
    qb = np.quantile(b, np.linspace(0, 1, n))
    return float(np.mean(np.abs(qa - qb)))


def main() -> None:
    install()
    RESULTS.mkdir(parents=True, exist_ok=True)

    import torch
    from datasets import load_dataset
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from huggingface_hub import hf_hub_download

    # mapping
    if META.exists():
        mapping = json.loads(META.read_text())
    else:
        path = hf_hub_download(
            "socratesft/SocSci210",
            "metadata/participant_mapping.json",
            repo_type="dataset",
        )
        mapping = json.loads(Path(path).read_text())
    unseen = set(mapping["unseen"])
    print(f"unseen studies: {len(unseen)}", flush=True)

    print(f"Loading model {MODEL} (4-bit → fits T4/L4)", flush=True)
    from transformers import BitsAndBytesConfig

    tok = AutoTokenizer.from_pretrained(MODEL, trust_remote_code=True)
    quant = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
        bnb_4bit_quant_type="nf4",
    )
    model = AutoModelForCausalLM.from_pretrained(
        MODEL,
        quantization_config=quant,
        device_map="auto",
        trust_remote_code=True,
    )
    model.eval()
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token

    print("Loading SocSci210 (filter unseen)...", flush=True)
    ds = load_dataset("socratesft/SocSci210", split="train")
    rows = [r for r in ds if r["study_id"] in unseen]
    print(f"unseen rows: {len(rows)}", flush=True)

    # optional smoke: first N studies
    if SMOKE_STUDIES > 0:
        keep = set(sorted(unseen)[:SMOKE_STUDIES])
        rows = [r for r in rows if r["study_id"] in keep]
        print(f"smoke studies={SMOKE_STUDIES} rows={len(rows)}", flush=True)

    # group by (study, condition, task/outcome)
    cells: dict[tuple, list] = defaultdict(list)
    for r in rows:
        key = (r["study_id"], str(r["condition_num"]), str(r["task_num"]))
        cells[key].append(r)
    print(f"cells: {len(cells)}", flush=True)

    preds_path = RESULTS / "predictions.jsonl"
    # resume support
    done_ids = set()
    if preds_path.exists():
        for line in preds_path.read_text().splitlines():
            if line.strip():
                done_ids.add(json.loads(line)["sample_id"])
        print(f"resuming, already have {len(done_ids)} preds", flush=True)

    n_gen = 0
    with preds_path.open("a") as fout:
        for key, items in cells.items():
            if MAX_PER_CELL > 0:
                items = items[:MAX_PER_CELL]
            for r in items:
                sid = f"{r['study_id']}|{r['sample_id']}|{r['condition_num']}|{r['task_num']}|{r['participant']}"
                if sid in done_ids:
                    continue
                messages = [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": r["prompt"]},
                ]
                text = tok.apply_chat_template(
                    messages, tokenize=False, add_generation_prompt=True
                )
                inputs = tok([text], return_tensors="pt", truncation=True, max_length=4096).to(
                    model.device
                )
                with torch.no_grad():
                    out = model.generate(
                        **inputs,
                        max_new_tokens=32,
                        do_sample=True,
                        temperature=0.6,
                        top_p=0.9,
                        pad_token_id=tok.pad_token_id,
                    )
                gen = tok.decode(out[0][inputs.input_ids.shape[1] :], skip_special_tokens=True)
                pred = parse_numeric(gen)
                rec = {
                    "sample_id": sid,
                    "study_id": r["study_id"],
                    "condition_num": str(r["condition_num"]),
                    "task_num": str(r["task_num"]),
                    "human": r["response"],
                    "pred_raw": gen,
                    "pred": pred,
                }
                fout.write(json.dumps(rec) + "\n")
                fout.flush()
                n_gen += 1
                if n_gen % 25 == 0:
                    print(f"generated {n_gen}", flush=True)

    # load all preds
    preds = [json.loads(l) for l in preds_path.read_text().splitlines() if l.strip()]
    by_cell: dict[tuple, list] = defaultdict(list)
    for p in preds:
        by_cell[(p["study_id"], p["condition_num"], p["task_num"])].append(p)

    study_scores: dict[str, list[float]] = defaultdict(list)
    cell_rows = []
    for key, items in by_cell.items():
        humans, models = [], []
        for it in items:
            try:
                h = float(it["human"])
            except Exception:
                continue
            if it["pred"] is None:
                continue
            humans.append(h)
            models.append(float(it["pred"]))
        if len(humans) < 2 or len(models) < 2:
            continue
        h = np.array(humans, dtype=float)
        m = np.array(models, dtype=float)
        rmin, rmax = float(h.min()), float(h.max())
        if rmax <= rmin:
            continue
        h_s = (h - rmin) / (rmax - rmin)
        m_s = (m - rmin) / (rmax - rmin)
        # clip model to scale (paper standardizes with human bounds)
        m_s = np.clip(m_s, 0.0, 1.0)
        w = wasserstein_1d(h_s, m_s)
        study_scores[key[0]].append(w)
        cell_rows.append({"study_id": key[0], "condition": key[1], "task": key[2], "W": w, "n": len(h)})

    per_study = {s: float(np.mean(v)) for s, v in study_scores.items() if v}
    overall = float(np.mean(list(per_study.values()))) if per_study else None
    summary = {
        "model": MODEL,
        "n_studies": len(per_study),
        "n_cells": len(cell_rows),
        "n_preds": len(preds),
        "wasserstein_mean": overall,
        "target_paper": 0.151,
        "empirical_best_paper": 0.125,
        "per_study": per_study,
    }
    (RESULTS / "SUMMARY.json").write_text(json.dumps(summary, indent=2))
    (RESULTS / "cells.json").write_text(json.dumps(cell_rows, indent=2))
    print(json.dumps({k: summary[k] for k in summary if k != "per_study"}, indent=2), flush=True)


if __name__ == "__main__":
    main()
