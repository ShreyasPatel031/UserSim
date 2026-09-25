#!/usr/bin/env python3
"""Zero-shot accuracy probe: Qwen3-14B, thinking off, greedy, 5 unseen studies.

Does not train. Scores paper individual accuracy (1 - normalized MAE),
plus the clipped variant. Writes predictions and SUMMARY under RESULTS_DIR.
"""
from __future__ import annotations

import json
import os
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

# Official FP8 checkpoint of Qwen3-14B. bf16 does not fit a 24GB L4, and this
# vLLM build has no bitsandbytes loader. Weights are the post-trained model.
MODEL = os.environ.get("PROBE_MODEL", "Qwen/Qwen3-14B-FP8")
N_STUDIES = int(os.environ.get("SMOKE_STUDIES", "5"))
RESULTS = Path(os.environ.get("RESULTS_DIR", "/opt/usersim_fm/results/acc_probe_qwen3_14b"))
SYSTEM = (
    "You are a participant in a survey experiment. "
    "Answer with a single number only when a numeric response is required."
)


def paper_accuracy(preds: list[dict], clip: bool) -> tuple[float | None, int, int]:
    cells: dict[tuple, list] = defaultdict(list)
    for p in preds:
        if p.get("pred") is None:
            continue
        try:
            h = float(p["human"])
            m = float(p["pred"])
        except (TypeError, ValueError):
            continue
        if not (np.isfinite(h) and np.isfinite(m)):
            continue
        cells[(p["study_id"], str(p["condition_num"]), str(p["task_num"]))].append((h, m))
    ranges = {}
    for key, items in cells.items():
        hs = [h for h, _ in items]
        rmin, rmax = min(hs), max(hs)
        if rmax > rmin:
            ranges[key] = (rmin, rmax)
    per: dict[str, list] = defaultdict(list)
    used = 0
    for p in preds:
        if p.get("pred") is None:
            continue
        try:
            h = float(p["human"])
            m = float(p["pred"])
        except (TypeError, ValueError):
            continue
        key = (p["study_id"], str(p["condition_num"]), str(p["task_num"]))
        if key not in ranges:
            continue
        rmin, rmax = ranges[key]
        if clip:
            m = min(max(m, rmin), rmax)
        per[p["study_id"]].append(abs(m - h) / (rmax - rmin))
        used += 1
    study = {s: 1.0 - float(np.mean(errs)) for s, errs in per.items() if errs}
    overall = float(np.mean(list(study.values()))) if study else None
    return overall, len(study), used


def main() -> None:
    from datasets import load_dataset
    from huggingface_hub import hf_hub_download
    from transformers import AutoTokenizer
    from vllm import LLM, SamplingParams

    RESULTS.mkdir(parents=True, exist_ok=True)
    mapping = json.loads(
        Path(
            hf_hub_download(
                "socratesft/SocSci210",
                "metadata/participant_mapping.json",
                repo_type="dataset",
            )
        ).read_text()
    )
    keep = set(sorted(mapping["unseen"])[:N_STUDIES])
    print(f"studies={sorted(keep)} model={MODEL}", flush=True)

    tok = AutoTokenizer.from_pretrained(MODEL, trust_remote_code=True)
    cache = RESULTS / "rows.jsonl"
    if cache.exists() and cache.stat().st_size > 0:
        rows = [json.loads(line) for line in cache.read_text().splitlines() if line.strip()]
        print(f"rows={len(rows)} from cache", flush=True)
    else:
        print("loading rows", flush=True)
        rows = []
        ds = load_dataset("socratesft/SocSci210", split="train")
        for rec in ds:
            if rec["study_id"] in keep:
                rows.append(rec)
        with cache.open("w") as fout:
            for rec in rows:
                fout.write(json.dumps(rec) + "\n")
        print(f"rows={len(rows)}", flush=True)

    prompts = []
    meta = []
    for rec in rows:
        messages = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": rec["prompt"]},
        ]
        prompts.append(
            tok.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
                enable_thinking=False,
            )
        )
        meta.append(rec)
    # enable_thinking=False still inserts an empty, already-closed <think> block
    # so generation starts after it. An unclosed tag means thinking is still on.
    for sample in prompts[:8]:
        if "<think>" in sample and "</think>" not in sample:
            raise SystemExit("thinking still open in the prompt")

    print("loading model", flush=True)
    llm = LLM(
        model=MODEL,
        max_model_len=4096,
        gpu_memory_utilization=0.90,
        trust_remote_code=True,
    )
    temperature = float(os.environ.get("TEMPERATURE", "0"))
    top_p = float(os.environ.get("TOP_P", "0.9"))
    if temperature <= 0:
        sampling = SamplingParams(temperature=0.0, max_tokens=16)
    else:
        sampling = SamplingParams(temperature=temperature, top_p=top_p, max_tokens=16)
    print(f"sampling temperature={temperature} top_p={top_p}", flush=True)
    preds_path = RESULTS / "predictions.jsonl"
    done_ids: set[str] = set()
    if preds_path.exists():
        for line in preds_path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                done_ids.add(json.loads(line)["sample_id"])
            except (json.JSONDecodeError, KeyError):
                continue
        print(f"resume already={len(done_ids)}", flush=True)
    started = time.time()
    n = len(done_ids)
    bare = 0
    pending = [
        (prompt, rec)
        for prompt, rec in zip(prompts, meta)
        if (
            f"{rec['study_id']}|{rec['sample_id']}|{rec['condition_num']}|"
            f"{rec['task_num']}|{rec['participant']}"
        )
        not in done_ids
    ]
    with preds_path.open("a") as fout:
        chunk = 256
        for i in range(0, len(pending), chunk):
            batch = pending[i : i + chunk]
            outs = llm.generate([p for p, _ in batch], sampling)
            for (rec_prompt, rec), out in zip(batch, outs):
                del rec_prompt
                text = out.outputs[0].text if out.outputs else ""
                pred = None
                stripped = text.strip()
                try:
                    pred = float(stripped)
                except ValueError:
                    import re

                    m = re.search(r"[-+]?\d*\.?\d+", stripped.replace(",", ""))
                    if m:
                        try:
                            pred = float(m.group(0))
                        except ValueError:
                            pred = None
                if stripped and re_fullmatch_number(stripped):
                    bare += 1
                row = {
                    "sample_id": (
                        f"{rec['study_id']}|{rec['sample_id']}|{rec['condition_num']}|"
                        f"{rec['task_num']}|{rec['participant']}"
                    ),
                    "study_id": rec["study_id"],
                    "condition_num": str(rec["condition_num"]),
                    "task_num": str(rec["task_num"]),
                    "human": rec["response"],
                    "pred_raw": text,
                    "pred": pred,
                }
                fout.write(json.dumps(row) + "\n")
                n += 1
            fout.flush()
            print(f"generated {n}/{len(prompts)}", flush=True)

    preds = [json.loads(line) for line in preds_path.read_text().splitlines() if line.strip()]
    acc_raw, n_studies, used = paper_accuracy(preds, clip=False)
    acc_clip, _, _ = paper_accuracy(preds, clip=True)
    parsed = sum(1 for p in preds if p.get("pred") is not None)
    summary = {
        "model": MODEL,
        "role": "zero_shot_instruct_probe",
        "thinking": False,
        "temperature": temperature,
        "top_p": top_p if temperature > 0 else None,
        "studies": sorted(keep),
        "n_preds": len(preds),
        "n_parsed": parsed,
        "bare_numeric": bare,
        "parse_rate": parsed / len(preds) if preds else None,
        "accuracy_raw": acc_raw,
        "accuracy_clipped": acc_clip,
        "n_studies": n_studies,
        "n_used": used,
        "elapsed_s": round(time.time() - started, 1),
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    (RESULTS / "SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2), flush=True)


def re_fullmatch_number(text: str) -> bool:
    import re

    return bool(re.fullmatch(r"[-+]?\d+(?:\.\d+)?", text.strip()))


if __name__ == "__main__":
    main()
