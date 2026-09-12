#!/usr/bin/env python3
"""Qwen3-8B-Base floor: SocSci210 unseen Wasserstein via vLLM (resume-capable).

Same prompt/sampling contract as Socrates eval (temp=0.6, top_p=0.9, chat template).
Writes predictions.jsonl then SUMMARY.json.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from socrates_metric import PAPER_TARGET, parse_numeric, score  # noqa: E402

ROOT = Path(os.environ.get("ROOT", "/opt/usersim_fm"))
if not ROOT.exists():
    ROOT = Path("/content/fm_baselines")
RESULTS = Path(
    os.environ.get("RESULTS_DIR", str(ROOT / "results" / "qwen3_8b_floor_socrates"))
)
MODEL = os.environ.get("FLOOR_MODEL", "Qwen/Qwen3-8B-Base")
# Optional LoRA adapter: same metric, same prompts, adapter-served weights.
LORA_PATH = os.environ.get("LORA_PATH", "").strip()
SYSTEM = (
    "You are a participant in a survey experiment. "
    "Answer with a single number only when a numeric response is required."
)
EXPECTED_STUDIES = 40
EXPECTED_ROWS = 482642
CHUNK = int(os.environ.get("CHUNK", "512"))
MAX_MODEL_LEN = int(os.environ.get("MAX_MODEL_LEN", "4096"))
MAX_NUM_SEQS = int(os.environ.get("MAX_NUM_SEQS", "128"))


def sh(cmd: str) -> None:
    print("+", cmd, flush=True)
    subprocess.run(cmd, shell=True, check=True)


def sample_id(r: dict) -> str:
    return (
        f"{r['study_id']}|{r['sample_id']}|{r['condition_num']}|"
        f"{r['task_num']}|{r['participant']}"
    )


def read_predictions(path: Path) -> list[dict]:
    """Read predictions, tolerating the partial line a preemption leaves behind.

    Spot VMs die mid-write, so the last record can be truncated or NUL-padded.
    Crashing here means systemd restarts into the same corrupt file forever, so
    unreadable lines are dropped and the run rewrites those samples instead.
    """
    records: list[dict] = []
    skipped = 0
    with path.open("r", errors="replace") as f:
        for raw in f:
            line = raw.strip().rstrip("\x00")
            if not line:
                # A killed append leaves the block NUL-padded; those bytes are
                # valid UTF-8, so only json.loads notices, at "char 0".
                if raw.strip():
                    skipped += 1
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                skipped += 1
                continue
            if isinstance(rec, dict) and "sample_id" in rec:
                records.append(rec)
            else:
                skipped += 1
    if skipped:
        print(f"skipped {skipped} unreadable prediction line(s) in {path}", flush=True)
    return records


def check_gate(summary: dict) -> None:
    """Refuse to call a run valid when the generations or the score are junk.

    A W threshold alone can't distinguish a working model from a broken one, so
    the binding check is against `uniform_control` -- the same metric scored
    with uniform draws. Anything that fails to beat random guessing is not a
    measurement, and burning a full sweep on it wastes the GPU. Defaults are
    tuned to pass a sane run and fail loudly otherwise; set GATE=0 to inspect a
    known-bad run without aborting.
    """
    if os.environ.get("GATE", "1").strip() in {"0", "false", "FALSE"}:
        print("gate disabled (GATE=0)", flush=True)
        return

    min_parse = float(os.environ.get("MIN_PARSE_RATE", "0.98"))
    min_bare = float(os.environ.get("MIN_BARE_NUMERIC_RATE", "0.90"))
    max_vs_ctl = float(os.environ.get("MAX_W_VS_CONTROL", "0.95"))

    parse = summary.get("parse") or {}
    w = summary.get("wasserstein_mean")
    ctl = summary.get("uniform_control")
    fail: list[str] = []

    rate = parse.get("parse_rate")
    if rate is None or rate < min_parse:
        fail.append(f"parse_rate={rate} < {min_parse}")
    bare = parse.get("bare_numeric_rate")
    if bare is not None and bare < min_bare:
        fail.append(
            f"bare_numeric_rate={bare:.3f} < {min_bare} "
            "(model is not obeying 'a single number only')"
        )
    if w is None or not np.isfinite(w):
        fail.append(f"wasserstein_mean={w} is not finite")
    elif w > 1.0:
        fail.append(f"wasserstein_mean={w:.4f} > 1.0 on a [0,1] scale")
    elif ctl is not None and w > max_vs_ctl * ctl:
        fail.append(
            f"wasserstein_mean={w:.4f} does not beat uniform guessing "
            f"(control={ctl:.4f}, need <= {max_vs_ctl * ctl:.4f})"
        )

    verdict = {
        "gate": "fail" if fail else "pass",
        "wasserstein_mean": w,
        "uniform_control": ctl,
        "paper_target": PAPER_TARGET,
        "parse": parse,
        "failures": fail,
    }
    (RESULTS / "GATE.json").write_text(json.dumps(verdict, indent=2))
    print(json.dumps(verdict, indent=2), flush=True)
    if fail:
        raise SystemExit("EVAL GATE FAILED: " + "; ".join(fail))


def main() -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    if os.environ.get("SKIP_INSTALL", "").strip() not in {"1", "true", "TRUE"}:
        sh(f"{sys.executable} -m pip install -q -U pip")
        sh(f"{sys.executable} -m pip install -q -U 'vllm>=0.6.0' datasets huggingface_hub transformers")

    from datasets import load_dataset
    from huggingface_hub import hf_hub_download
    from transformers import AutoTokenizer
    from vllm import LLM, SamplingParams

    meta = Path(
        os.environ.get(
            "SOCSCI_MAPPING",
            hf_hub_download(
                "socratesft/SocSci210",
                "metadata/participant_mapping.json",
                repo_type="dataset",
            ),
        )
    )
    unseen = set(json.loads(meta.read_text())["unseen"])
    print(f"unseen studies: {len(unseen)}", flush=True)

    ds = load_dataset("socratesft/SocSci210", split="train")
    keep = [s in unseen for s in ds["study_id"]]
    ds = ds.filter(lambda _, i: keep[i], with_indices=True, num_proc=2)
    rows = ds.to_list()
    smoke = int(os.environ.get("SMOKE_STUDIES", "0"))
    if smoke > 0:
        keep_ids = set(sorted(unseen)[:smoke])
        rows = [r for r in rows if r["study_id"] in keep_ids]
    print(f"rows={len(rows)}", flush=True)

    preds_path = RESULTS / "predictions.jsonl"
    done: set[str] = set()
    if preds_path.exists():
        for rec in read_predictions(preds_path):
            done.add(rec["sample_id"])
        print(f"resuming: {len(done)}", flush=True)

    todo = [r for r in rows if sample_id(r) not in done]
    if todo:
        tok = AutoTokenizer.from_pretrained(MODEL, trust_remote_code=True)
        print("Starting vLLM", MODEL, flush=True)
        lora_request = None
        llm_kwargs = {}
        if LORA_PATH:
            from vllm.lora.request import LoRARequest

            print("with LoRA adapter", LORA_PATH, flush=True)
            llm_kwargs = {
                "enable_lora": True,
                "max_lora_rank": int(os.environ.get("MAX_LORA_RANK", "64")),
            }
            lora_request = LoRARequest("socrates_sft", 1, LORA_PATH)
        llm = LLM(
            model=MODEL,
            trust_remote_code=True,
            max_model_len=MAX_MODEL_LEN,
            gpu_memory_utilization=float(os.environ.get("GPU_MEM_UTIL", "0.90")),
            max_num_seqs=MAX_NUM_SEQS,
            dtype="half",
            **llm_kwargs,
        )
        sampling = SamplingParams(temperature=0.6, top_p=0.9, max_tokens=32)

        with preds_path.open("a") as fout:
            for start in range(0, len(todo), CHUNK):
                batch = todo[start : start + CHUNK]
                prompts = []
                for r in batch:
                    messages = [
                        {"role": "system", "content": SYSTEM},
                        {"role": "user", "content": r["prompt"]},
                    ]
                    text = tok.apply_chat_template(
                        messages, tokenize=False, add_generation_prompt=True
                    )
                    prompts.append(text)
                t0 = time.time()
                outs = llm.generate(
                    prompts, sampling, use_tqdm=False, lora_request=lora_request
                )
                dt = time.time() - t0
                for r, out in zip(batch, outs):
                    gen = out.outputs[0].text if out.outputs else ""
                    pred = parse_numeric(gen)
                    rec = {
                        "sample_id": sample_id(r),
                        "study_id": r["study_id"],
                        "condition_num": str(r["condition_num"]),
                        "task_num": str(r["task_num"]),
                        "human": r["response"],
                        "pred_raw": gen,
                        "pred": pred,
                    }
                    fout.write(json.dumps(rec) + "\n")
                fout.flush()
                done_n = len(done) + start + len(batch)
                rate = len(batch) / max(dt, 1e-6) * 60
                print(
                    f"preds {min(done_n, len(rows))}/{len(rows)} "
                    f"chunk={len(batch)} {rate:.0f}/min",
                    flush=True,
                )
                (RESULTS / "PROGRESS.json").write_text(
                    json.dumps(
                        {
                            "scored": min(len(done) + start + len(batch), len(rows)),
                            "total": len(rows),
                            "model": MODEL,
                        }
                    )
                )

    preds = read_predictions(preds_path)
    # dedupe
    by_id = {p["sample_id"]: p for p in preds}
    preds = list(by_id.values())
    agg = score(preds)
    n_studies = agg["n_studies"]
    n_preds = len(preds)
    complete = (
        smoke == 0
        and n_studies >= EXPECTED_STUDIES
        and n_preds >= EXPECTED_ROWS
    )
    summary = {
        "model": MODEL,
        "lora": LORA_PATH or None,
        "role": "sft_adapter" if LORA_PATH else "base_floor",
        "n_studies": n_studies,
        "n_cells": agg["n_cells"],
        "n_preds": n_preds,
        "wasserstein_mean": agg["wasserstein_mean"],
        "uniform_control": agg["uniform_control"],
        "target_paper_socrates": PAPER_TARGET,
        "parse": agg["parse"],
        "per_study": agg["per_study"],
        "skipped": agg["skipped"],
        "smoke_studies": smoke,
        "coverage": {
            "actual": n_studies,
            "expected": EXPECTED_STUDIES,
            "unit": "studies",
            "complete": complete,
            "n_preds": n_preds,
            "expected_rows": EXPECTED_ROWS,
        },
    }
    (RESULTS / "SUMMARY.json").write_text(json.dumps(summary, indent=2))
    (RESULTS / "cells.json").write_text(json.dumps(agg["cell_rows"], indent=2))
    print(
        json.dumps(
            {k: summary[k] for k in summary if k not in ("per_study", "parse")},
            indent=2,
        ),
        flush=True,
    )
    print(json.dumps({"parse": agg["parse"]}, indent=2), flush=True)
    check_gate(summary)


if __name__ == "__main__":
    main()
