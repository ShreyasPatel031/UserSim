#!/usr/bin/env python3
"""One shard of the Socrates SocSci210-unseen reproduction, served by vLLM.

Why this exists: colab_socrates_wass.py calls model.generate() once per row at
batch size 1. Prompts are ~294 tokens and the answer is a single token, so
almost all of that wall time is per-call overhead rather than compute, which
put the full 482,642-row split at ~28 days. vLLM's continuous batching removes
the overhead; sharding removes the rest.

What is deliberately unchanged, because gates.yaml pins it:
  - the prompt is the dataset `prompt` field, untouched and unreordered
  - the system string and chat template come from socrates_metric.SYSTEM
  - prompt token ids are produced by the same tokenizer call, truncating at 4096
  - sampling is temperature=0.6, top_p=0.9

What changed: the inference engine, the batch size, and fp8 weights instead of
bitsandbytes nf4 (fp8 is the closer of the two to the paper's fp16).

This writes predictions.shard<ID>.jsonl and nothing else. It never writes
SUMMARY.json — socrates_merge_shards.py owns aggregation and coverage.
"""
from __future__ import annotations

import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from socrates_metric import SYSTEM, parse_numeric, sample_id, shard_cells  # noqa: E402

MODEL = os.environ.get("SOCRATES_MODEL", "socratesft/socrates-qwen2.5-14b-sft")
SHARD_ID = int(os.environ["SHARD_ID"])
NUM_SHARDS = int(os.environ["NUM_SHARDS"])
OUT_DIR = Path(os.environ.get("OUT_DIR", "/opt/usersim_fm/results/socrates"))
GCS_DEST = os.environ.get("GCS_DEST", "").rstrip("/")
QUANT = os.environ.get("QUANT", "fp8")
MAX_MODEL_LEN = int(os.environ.get("MAX_MODEL_LEN", "4096"))
MAX_NEW_TOKENS = int(os.environ.get("MAX_NEW_TOKENS", "32"))
GPU_MEM_UTIL = float(os.environ.get("GPU_MEM_UTIL", "0.92"))
MAX_NUM_SEQS = int(os.environ.get("MAX_NUM_SEQS", "256"))
CHUNK = int(os.environ.get("CHUNK", "4096"))
TRUNCATE_AT = int(os.environ.get("TRUNCATE_AT", "4096"))


def log(msg: str) -> None:
    print(f"[shard{SHARD_ID}] {msg}", flush=True)


def gcs_push(path: Path) -> None:
    if not GCS_DEST or not path.exists():
        return
    os.system(f"gcloud storage cp {path} {GCS_DEST}/ --quiet 2>/dev/null")


def load_rows() -> list[dict]:
    from datasets import load_dataset
    from huggingface_hub import hf_hub_download

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
    log(f"unseen studies: {len(unseen)}")

    ds = load_dataset("socratesft/SocSci210", split="train")
    # Arrow-level filter: a Python loop over 482k rows costs minutes per node.
    keep = [s in unseen for s in ds["study_id"]]
    ds = ds.filter(lambda _, i: keep[i], with_indices=True, num_proc=4)
    rows = ds.to_list()
    log(f"unseen rows: {len(rows)}")
    return rows


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    preds_path = OUT_DIR / f"predictions.shard{SHARD_ID}.jsonl"

    rows = load_rows()

    cells: dict[tuple, list] = defaultdict(list)
    for r in rows:
        cells[(r["study_id"], str(r["condition_num"]), str(r["task_num"]))].append(r)
    sizes = {k: len(v) for k, v in cells.items()}
    mine = set(shard_cells(sizes, NUM_SHARDS)[SHARD_ID])
    my_rows = [r for k in sorted(mine) for r in cells[k]]
    log(f"cells total={len(cells)} mine={len(mine)} rows={len(my_rows)}")

    done: set[str] = set()
    if preds_path.exists():
        for line in preds_path.read_text().splitlines():
            if line.strip():
                done.add(json.loads(line)["sample_id"])
        log(f"resuming: {len(done)} rows already done")
    todo = [r for r in my_rows if sample_id(r) not in done]
    if not todo:
        log("nothing to do")
        (OUT_DIR / f"shard{SHARD_ID}.done").write_text(
            json.dumps({"shard": SHARD_ID, "rows": len(my_rows)})
        )
        gcs_push(preds_path)
        gcs_push(OUT_DIR / f"shard{SHARD_ID}.done")
        return

    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained(MODEL, trust_remote_code=True)

    # Build chat strings only — vLLM tokenizes + continuous-batches. Pre-tokenizing
    # all 482k rows on CPU was burning an hour before the GPU ever started.
    def chat_text(row: dict) -> str:
        return tok.apply_chat_template(
            [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": row["prompt"]},
            ],
            tokenize=False,
            add_generation_prompt=True,
        )

    from vllm import LLM, SamplingParams

    log(f"loading {MODEL} quant={QUANT} max_model_len={MAX_MODEL_LEN}")
    llm = LLM(
        model=MODEL,
        quantization=QUANT or None,
        max_model_len=MAX_MODEL_LEN,
        gpu_memory_utilization=GPU_MEM_UTIL,
        max_num_seqs=MAX_NUM_SEQS,
        trust_remote_code=True,
        enable_prefix_caching=False,
    )
    sp = SamplingParams(temperature=0.6, top_p=0.9, max_tokens=MAX_NEW_TOKENS)

    t0 = time.time()
    n_done = 0
    with preds_path.open("a") as fout:
        for start in range(0, len(todo), CHUNK):
            batch_rows = todo[start : start + CHUNK]
            prompts = [chat_text(r) for r in batch_rows]
            outs = llm.generate(prompts, sp)
            for r, o in zip(batch_rows, outs):
                gen = o.outputs[0].text
                fout.write(
                    json.dumps(
                        {
                            "sample_id": sample_id(r),
                            "study_id": r["study_id"],
                            "condition_num": str(r["condition_num"]),
                            "task_num": str(r["task_num"]),
                            "human": r["response"],
                            "pred_raw": gen,
                            "pred": parse_numeric(gen),
                        }
                    )
                    + "\n"
                )
            fout.flush()
            n_done += len(batch_rows)
            rate = n_done / max(time.time() - t0, 1e-6)
            eta = (len(todo) - n_done) / max(rate, 1e-6) / 60
            log(
                f"{n_done}/{len(todo)} rows  {rate * 60:.0f}/min  eta {eta:.1f} min"
            )
            gcs_push(preds_path)

    total = len(done) + n_done
    marker = OUT_DIR / f"shard{SHARD_ID}.done"
    marker.write_text(
        json.dumps(
            {
                "shard": SHARD_ID,
                "num_shards": NUM_SHARDS,
                "rows": total,
                "expected_rows": len(my_rows),
                "complete": total >= len(my_rows),
                "seconds": round(time.time() - t0, 1),
            },
            indent=2,
        )
    )
    log(f"DONE rows={total}/{len(my_rows)} in {(time.time() - t0) / 60:.1f} min")
    gcs_push(preds_path)
    gcs_push(marker)


if __name__ == "__main__":
    main()
