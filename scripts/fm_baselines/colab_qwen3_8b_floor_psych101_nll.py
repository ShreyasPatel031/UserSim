#!/usr/bin/env python3
"""Qwen3-8B-Base floor: Psych-101-test NLL (batched, resume-capable).

Same metric as Minitaur: sum of token NLLs inside <<...>> spans, MAX_SEQ=4096.
Faster than the naive loop:
  - length-bucketed micro-batches
  - CrossEntropy (no full-vocab float32 log_softmax)
  - optional SHARD_ID/NUM_SHARDS for multi-VM

ROOT defaults to /opt/usersim_fm on GCP, /content/fm_baselines on Colab.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import torch
import torch.nn.functional as F

ROOT = Path(os.environ.get("FM_ROOT", "/opt/usersim_fm"))
if not ROOT.exists():
    ROOT = Path("/content/fm_baselines")
DATA = Path(
    os.environ.get(
        "PSYCH101_DATA",
        str(ROOT / "data" / "Psych-101-test" / "prompts_testing_t1.jsonl"),
    )
)
RESULTS = ROOT / "results" / "qwen3_8b_floor_psych101"
MODEL = os.environ.get("FLOOR_MODEL", "Qwen/Qwen3-8B-Base")
MAX_SEQ = int(os.environ.get("MAX_SEQ", "4096"))
MODE = os.environ.get("MODE", "full").strip().lower()
SMOKE_N = int(os.environ.get("SMOKE_N", "20"))
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "4"))
NUM_SHARDS = max(1, int(os.environ.get("NUM_SHARDS", "1")))
SHARD_ID = int(os.environ.get("SHARD_ID", "0"))


def sh(cmd: str) -> None:
    print("+", cmd, flush=True)
    subprocess.run(cmd, shell=True, check=True)


def install() -> None:
    sh(f"{sys.executable} -m pip install -q -U pip")
    sh(
        f"{sys.executable} -m pip install -q -U transformers accelerate "
        "bitsandbytes peft datasets sentencepiece protobuf"
    )


def spans_for(text: str) -> list[tuple[int, int]]:
    return [(m.start(1), m.end(1)) for m in re.finditer(r"<<(.*?)>>", text, flags=re.S)]


def mask_from_offsets(offsets: list[tuple[int, int]], spans: list[tuple[int, int]], tlen: int) -> torch.Tensor:
    """Bool mask over shift positions (length tlen-1)."""
    mask = torch.zeros(tlen - 1, dtype=torch.bool)
    for ts, te in spans:
        for i, (s, e) in enumerate(offsets):
            if i == 0 or e <= s:
                continue
            if s >= ts and e <= te:
                mask[i - 1] = True
    return mask


@torch.inference_mode()
def nll_batch(model, tokenizer, texts: list[str]) -> list[float | None]:
    """Batched NLL with char-offset <<...>> masks. Do not use tokenizer(' <<')."""
    outs: list[float | None] = []
    # Drop empty / no-span early
    prepared: list[tuple[int, str, list[tuple[int, int]]]] = []
    for i, text in enumerate(texts):
        if "<<" not in text or ">>" not in text:
            outs.append(None)
            continue
        spans = spans_for(text)
        if not spans:
            outs.append(None)
            continue
        prepared.append((i, text, spans))
        outs.append(None)  # placeholder

    if not prepared:
        return outs

    # Bucket by tokenized length so padding waste stays low
    enc_single = []
    for _, text, spans in prepared:
        enc = tokenizer(
            text,
            truncation=True,
            max_length=MAX_SEQ,
            return_offsets_mapping=True,
            add_special_tokens=True,
        )
        enc_single.append((enc, spans))

    order = sorted(range(len(enc_single)), key=lambda j: len(enc_single[j][0]["input_ids"]))
    device = next(model.parameters()).device

    for start in range(0, len(order), BATCH_SIZE):
        idxs = order[start : start + BATCH_SIZE]
        batch_enc = [enc_single[j][0] for j in idxs]
        batch_spans = [enc_single[j][1] for j in idxs]
        max_len = max(len(e["input_ids"]) for e in batch_enc)
        pad_id = tokenizer.pad_token_id
        if pad_id is None:
            pad_id = tokenizer.eos_token_id

        input_ids = torch.full((len(idxs), max_len), pad_id, dtype=torch.long, device=device)
        attn = torch.zeros((len(idxs), max_len), dtype=torch.long, device=device)
        masks = []
        for bi, e in enumerate(batch_enc):
            ids = e["input_ids"]
            L = len(ids)
            input_ids[bi, :L] = torch.tensor(ids, dtype=torch.long, device=device)
            attn[bi, :L] = 1
            masks.append(mask_from_offsets(e["offset_mapping"], batch_spans[bi], L))

        logits = model(input_ids=input_ids, attention_mask=attn).logits  # [B,T,V]
        # CE on shift; keep model dtype (bf16/fp16) — much cheaper than float32 log_softmax
        shift_logits = logits[:, :-1, :].contiguous()
        shift_labels = input_ids[:, 1:].contiguous()
        B, Tm1, V = shift_logits.shape
        per_tok = F.cross_entropy(
            shift_logits.reshape(-1, V),
            shift_labels.reshape(-1),
            reduction="none",
        ).view(B, Tm1)

        for bi, j in enumerate(idxs):
            L = len(batch_enc[bi]["input_ids"])
            m = masks[bi].to(device)
            # only real tokens (exclude pad region)
            m = m & (attn[bi, 1:L].bool())
            if not m.any():
                val = None
            else:
                val = float(per_tok[bi, : L - 1][m].sum().item())
            orig_i = prepared[j][0]
            outs[orig_i] = val
    return outs


def write_progress(scored: int, total: int, extra: dict | None = None) -> None:
    payload = {
        "scored": scored,
        "total": total,
        "max_seq": MAX_SEQ,
        "model": MODEL,
        "engine": "transformers-4bit-batched",
        "mode": MODE,
        "batch_size": BATCH_SIZE,
        "shard_id": SHARD_ID,
        "num_shards": NUM_SHARDS,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if extra:
        payload.update(extra)
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "PROGRESS.json").write_text(json.dumps(payload))
    if NUM_SHARDS > 1:
        (RESULTS / f"PROGRESS.shard{SHARD_ID}.json").write_text(json.dumps(payload))


def main() -> None:
    assert DATA.exists(), f"missing {DATA}"
    if os.environ.get("SKIP_INSTALL", "").strip() not in {"1", "true", "TRUE"}:
        install()

    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    if MODE not in {"smoke", "full"}:
        raise SystemExit(f"MODE must be smoke|full, got {MODE}")
    if not (0 <= SHARD_ID < NUM_SHARDS):
        raise SystemExit(f"SHARD_ID={SHARD_ID} out of range for NUM_SHARDS={NUM_SHARDS}")
    if MODE == "full":
        smoke_ok = RESULTS / "SMOKE_OK.json"
        if not smoke_ok.exists():
            raise SystemExit("PROTOCOL: missing SMOKE_OK.json. Run MODE=smoke first.")
        if os.environ.get("WATCHDOG_ARMED", "").strip() not in {"1", "true", "TRUE"}:
            if not Path(os.environ.get("WATCHDOG_MARKER", str(ROOT / "WATCHDOG_ARMED"))).exists():
                raise SystemExit("PROTOCOL: watchdog not armed.")

    RESULTS.mkdir(parents=True, exist_ok=True)
    scores_name = "scores.jsonl" if NUM_SHARDS == 1 else f"scores.shard{SHARD_ID}.jsonl"
    scores_path = RESULTS / scores_name

    done: set[int] = set()
    if scores_path.exists():
        for line in scores_path.read_text().splitlines():
            if line.strip():
                done.add(json.loads(line)["i"])
        print(f"resuming: {len(done)} scored", flush=True)

    print("Loading", MODEL, "BATCH_SIZE", BATCH_SIZE, "shard", SHARD_ID, "/", NUM_SHARDS, flush=True)
    tok = AutoTokenizer.from_pretrained(MODEL, trust_remote_code=True)
    if tok.pad_token_id is None:
        tok.pad_token = tok.eos_token
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
        attn_implementation="sdpa",
    )
    model.eval()
    torch.backends.cuda.matmul.allow_tf32 = True
    torch.backends.cudnn.allow_tf32 = True

    rows = [json.loads(l) for l in DATA.read_text().splitlines() if l.strip()]
    smoke_n = SMOKE_N if MODE == "smoke" else 0
    if smoke_n > 0:
        rows = rows[:smoke_n]
    # shard after smoke slice so smoke stays identical on every shard host
    indices = [i for i in range(len(rows)) if i % NUM_SHARDS == SHARD_ID]
    print(f"rows={len(rows)} shard_rows={len(indices)} already={len(done)}", flush=True)

    sums: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    if scores_path.exists():
        for line in scores_path.read_text().splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec.get("nll") is None:
                continue
            sums[rec["experiment"]] += rec["nll"]
            counts[rec["experiment"]] += 1

    todo = [i for i in indices if i not in done]
    t_wall0 = time.time()
    scored_session = 0
    with scores_path.open("a") as fout:
        # dynamic batch: group upcoming by rough char length
        todo_sorted = sorted(todo, key=lambda i: len(rows[i]["text"]))
        pos = 0
        while pos < len(todo_sorted):
            # pick batch; shrink if texts are huge
            batch_idx = []
            while pos < len(todo_sorted) and len(batch_idx) < BATCH_SIZE:
                i = todo_sorted[pos]
                # long prompts: force batch 1-2
                if len(rows[i]["text"]) > 20000 and len(batch_idx) >= 2:
                    break
                if len(rows[i]["text"]) > 50000 and len(batch_idx) >= 1:
                    break
                batch_idx.append(i)
                pos += 1
            texts = [rows[i]["text"] for i in batch_idx]
            t0 = time.time()
            vals = nll_batch(model, tok, texts)
            dt = time.time() - t0
            for i, val in zip(batch_idx, vals):
                exp = rows[i]["experiment"].split("/")[0]
                fout.write(json.dumps({"i": i, "experiment": exp, "nll": val, "shard": SHARD_ID}) + "\n")
                if val is not None:
                    sums[exp] += val
                    counts[exp] += 1
                done.add(i)
                scored_session += 1
            fout.flush()
            rate = len(batch_idx) / max(dt, 1e-6) * 60
            write_progress(
                scored=len(done),
                total=len(indices) if MODE == "full" else len(rows),
                extra={"items_per_min": rate, "last_batch": len(batch_idx), "last_batch_s": round(dt, 2)},
            )
            print(
                f"scored {len(done)}/{len(indices)} batch={len(batch_idx)} "
                f"{rate:.1f}/min dt={dt:.1f}s",
                flush=True,
            )

    per_exp = {
        exp: {
            "nll_sum": sums[exp],
            "n_items": counts[exp],
            "nll_mean": sums[exp] / counts[exp],
        }
        for exp in sorted(counts)
        if counts[exp]
    }
    total_n = sum(counts.values())
    expected = len(indices) if MODE == "full" else len(rows)
    complete = bool(total_n >= expected and smoke_n == 0 and NUM_SHARDS == 1)
    summary = {
        "model": MODEL,
        "role": "base_floor",
        "complete": complete,
        "total_nll_sum": sum(sums.values()),
        "n_items": total_n,
        "n_experiments": len(per_exp),
        "max_seq": MAX_SEQ,
        "engine": "transformers-4bit-batched",
        "batch_size": BATCH_SIZE,
        "shard_id": SHARD_ID,
        "num_shards": NUM_SHARDS,
        "per_experiment": per_exp,
        "wall_s": time.time() - t_wall0,
        "coverage": {
            "actual": total_n,
            "expected": expected,
            "unit": "items",
            "complete": complete,
        },
    }
    out_summary = RESULTS / ("SUMMARY.json" if NUM_SHARDS == 1 else f"SUMMARY.shard{SHARD_ID}.json")
    out_summary.write_text(json.dumps(summary, indent=2))
    print(json.dumps({k: summary[k] for k in summary if k != "per_experiment"}, indent=2), flush=True)

    if MODE == "smoke":
        valid = sum(
            1
            for rec in (json.loads(l) for l in scores_path.read_text().splitlines() if l.strip())
            if rec.get("nll") is not None
        )
        if valid < 1:
            raise SystemExit("PROTOCOL: smoke produced zero valid NLLs")
        (RESULTS / "SMOKE_OK.json").write_text(
            json.dumps(
                {
                    "passed": True,
                    "engine": "transformers-4bit-batched",
                    "valid_nll": valid,
                    "n": len(rows),
                    "batch_size": BATCH_SIZE,
                    "items_per_min": scored_session / max((time.time() - t_wall0) / 60.0, 1e-6),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
                indent=2,
            )
        )
        print("SMOKE_PASSED", flush=True)


if __name__ == "__main__":
    main()
