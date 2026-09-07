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
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path("/content/fm_baselines")
RESULTS = ROOT / "results" / "qwen3_8b_floor_socrates"
MODEL = os.environ.get("FLOOR_MODEL", "Qwen/Qwen3-8B-Base")
SYSTEM = (
    "You are a participant in a survey experiment. "
    "Answer with a single number only when a numeric response is required."
)
EXPECTED_STUDIES = 40
EXPECTED_ROWS = 482642
CHUNK = int(os.environ.get("CHUNK", "512"))
MAX_MODEL_LEN = int(os.environ.get("MAX_MODEL_LEN", "4096"))
MAX_NUM_SEQS = int(os.environ.get("MAX_NUM_SEQS", "64"))
MODE = os.environ.get("MODE", "full").strip().lower()
SMOKE_N = int(os.environ.get("SMOKE_N", "32"))
# T4 is ~15.6GB; 8B fp16 does not fit. 4-bit vLLM is required below 20GB.
GPU_MEM_GB_4BIT = 20.0


def sh(cmd: str) -> None:
    print("+", cmd, flush=True)
    subprocess.run(cmd, shell=True, check=True)


def parse_numeric(text: str) -> float | None:
    m = re.search(r"[-+]?\d*\.?\d+", text.replace(",", ""))
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def wasserstein_1d(a: np.ndarray, b: np.ndarray) -> float:
    a = np.sort(a.astype(float))
    b = np.sort(b.astype(float))
    n = max(len(a), len(b))
    if len(a) != n:
        a = np.interp(np.linspace(0, 1, n), np.linspace(0, 1, len(a)), a)
    if len(b) != n:
        b = np.interp(np.linspace(0, 1, n), np.linspace(0, 1, len(b)), b)
    return float(np.mean(np.abs(a - b)))


def sample_id(r: dict) -> str:
    return (
        f"{r['study_id']}|{r['sample_id']}|{r['condition_num']}|"
        f"{r['task_num']}|{r['participant']}"
    )


def aggregate(preds: list[dict]) -> dict:
    cells: dict[tuple, list] = defaultdict(list)
    for p in preds:
        if p.get("pred") is None:
            continue
        key = (p["study_id"], str(p["condition_num"]), str(p["task_num"]))
        cells[key].append(p)
    per_study: dict[str, list] = defaultdict(list)
    skipped = {"cell_degenerate_range": 0}
    cell_rows = []
    for key, items in cells.items():
        h = np.array([x["human"] for x in items], dtype=float)
        m = np.array([x["pred"] for x in items], dtype=float)
        if len(h) < 2 or (h.max() - h.min() == 0 and m.max() - m.min() == 0):
            skipped["cell_degenerate_range"] += 1
            continue
        w = wasserstein_1d(h, m)
        per_study[key[0]].append(w)
        cell_rows.append({"study_id": key[0], "condition_num": key[1], "task_num": key[2], "w": w, "n": len(items)})
    study_means = {s: float(np.mean(ws)) for s, ws in per_study.items() if ws}
    overall = float(np.mean(list(study_means.values()))) if study_means else float("nan")
    return {
        "n_studies": len(study_means),
        "n_cells": len(cell_rows),
        "wasserstein_mean": overall,
        "per_study": study_means,
        "cell_rows": cell_rows,
        "skipped": skipped,
    }


def gpu_mem_gb() -> float:
    try:
        import torch

        return torch.cuda.get_device_properties(0).total_memory / 1e9
    except Exception:
        return 0.0


def make_llm():
    from vllm import LLM

    mem = gpu_mem_gb()
    use_4bit = mem < GPU_MEM_GB_4BIT or os.environ.get("VLLM_4BIT", "").strip() in {"1", "true", "TRUE"}
    kwargs = dict(
        model=MODEL,
        trust_remote_code=True,
        max_model_len=MAX_MODEL_LEN,
        gpu_memory_utilization=float(os.environ.get("GPU_MEM_UTIL", "0.90")),
        max_num_seqs=MAX_NUM_SEQS,
        dtype="half",
    )
    if use_4bit:
        print(f"vLLM 4-bit bitsandbytes (gpu={mem:.1f}GB < {GPU_MEM_GB_4BIT})", flush=True)
        kwargs["quantization"] = "bitsandbytes"
        kwargs["load_format"] = "bitsandbytes"
    else:
        print(f"vLLM fp16 (gpu={mem:.1f}GB)", flush=True)
    return LLM(**kwargs), ("vllm-4bit" if use_4bit else "vllm")


def main() -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    if MODE not in {"smoke", "full"}:
        raise SystemExit(f"MODE must be smoke|full, got {MODE}")
    if MODE == "full":
        smoke_ok = RESULTS / "SMOKE_OK.json"
        if not smoke_ok.exists():
            raise SystemExit("PROTOCOL: missing SMOKE_OK.json. Run MODE=smoke first.")
        if os.environ.get("WATCHDOG_ARMED", "").strip() not in {"1", "true", "TRUE"}:
            if not Path(os.environ.get("WATCHDOG_MARKER", "/content/fm_baselines/WATCHDOG_ARMED")).exists():
                raise SystemExit("PROTOCOL: watchdog not armed.")

    if os.environ.get("SKIP_INSTALL", "").strip() not in {"1", "true", "TRUE"}:
        sh(f"{sys.executable} -m pip install -q -U pip")
        sh(
            f"{sys.executable} -m pip install -q -U 'vllm>=0.6.0' bitsandbytes "
            "datasets huggingface_hub transformers"
        )

    from datasets import load_dataset
    from huggingface_hub import hf_hub_download
    from transformers import AutoTokenizer
    from vllm import SamplingParams

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
    smoke_studies = int(os.environ.get("SMOKE_STUDIES", "0"))
    if MODE == "smoke":
        if smoke_studies > 0:
            keep_ids = set(sorted(unseen)[:smoke_studies])
            rows = [r for r in rows if r["study_id"] in keep_ids][:SMOKE_N]
        else:
            rows = rows[:SMOKE_N]
    print(f"mode={MODE} rows={len(rows)}", flush=True)

    preds_path = RESULTS / "predictions.jsonl"
    done: set[str] = set()
    if preds_path.exists():
        for line in preds_path.read_text().splitlines():
            if line.strip():
                done.add(json.loads(line)["sample_id"])
        print(f"resuming: {len(done)}", flush=True)

    todo = [r for r in rows if sample_id(r) not in done]
    engine = "vllm"
    if todo:
        tok = AutoTokenizer.from_pretrained(MODEL, trust_remote_code=True)
        print("Starting vLLM", MODEL, flush=True)
        llm, engine = make_llm()
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
                outs = llm.generate(prompts, sampling, use_tqdm=False)
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
                            "engine": engine,
                            "mode": MODE,
                            "max_num_seqs": MAX_NUM_SEQS,
                        }
                    )
                )

    preds = []
    for line in preds_path.read_text().splitlines():
        if line.strip():
            preds.append(json.loads(line))
    # dedupe
    by_id = {p["sample_id"]: p for p in preds}
    preds = list(by_id.values())
    agg = aggregate(preds)
    n_studies = agg["n_studies"]
    n_preds = len(preds)
    parsed = sum(1 for p in preds if p.get("pred") is not None)
    complete = (
        MODE == "full"
        and n_studies >= EXPECTED_STUDIES
        and n_preds >= EXPECTED_ROWS
    )
    if MODE == "smoke":
        if parsed < 1:
            raise SystemExit("PROTOCOL: smoke produced zero parsed numeric predictions")
        (RESULTS / "SMOKE_OK.json").write_text(
            json.dumps(
                {
                    "passed": True,
                    "engine": "vllm",
                    "engine_detail": engine,
                    "parsed": parsed,
                    "n": n_preds,
                    "n_studies": n_studies,
                    "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                },
                indent=2,
            )
        )
        print("SMOKE_PASSED", flush=True)
        return

    summary = {
        "model": MODEL,
        "role": "base_floor",
        "complete": complete,
        "n_studies": n_studies,
        "n_cells": agg["n_cells"],
        "n_preds": n_preds,
        "parsed": parsed,
        "wasserstein_mean": agg["wasserstein_mean"],
        "target_paper_socrates": 0.151,
        "per_study": agg["per_study"],
        "skipped": agg["skipped"],
        "engine": engine,
        "mode": MODE,
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
    print(
        json.dumps({k: summary[k] for k in summary if k != "per_study"}, indent=2),
        flush=True,
    )


if __name__ == "__main__":
    main()
