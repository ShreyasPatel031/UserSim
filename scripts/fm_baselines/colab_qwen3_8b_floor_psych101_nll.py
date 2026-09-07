#!/usr/bin/env python3
"""Qwen3-8B-Base floor: Psych-101-test NLL (same metric as Minitaur).

Resumes via scores.jsonl. Writes SUMMARY.json when all items scored.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import torch

ROOT = Path("/content/fm_baselines")
DATA = ROOT / "data" / "Psych-101-test" / "prompts_testing_t1.jsonl"
RESULTS = ROOT / "results" / "qwen3_8b_floor_psych101"
MODEL = os.environ.get("FLOOR_MODEL", "Qwen/Qwen3-8B-Base")
MAX_SEQ = int(os.environ.get("MAX_SEQ", "4096"))


def sh(cmd: str) -> None:
    print("+", cmd, flush=True)
    subprocess.run(cmd, shell=True, check=True)


def install() -> None:
    sh(f"{sys.executable} -m pip install -q -U pip")
    sh(
        f"{sys.executable} -m pip install -q -U transformers accelerate "
        "bitsandbytes peft datasets sentencepiece protobuf"
    )


def nll_for_text(model, tokenizer, text: str) -> float | None:
    if "<<" not in text or ">>" not in text:
        return None
    l_id = tokenizer(" <<").input_ids[1:]
    r_id = tokenizer(">>").input_ids[1:]
    enc = tokenizer(text, return_tensors="pt", truncation=True, max_length=MAX_SEQ)
    input_ids = enc.input_ids.to(model.device)
    with torch.no_grad():
        logits = model(input_ids=input_ids).logits
    shift_logits = logits[:, :-1, :].float()
    shift_labels = input_ids[:, 1:]
    ids = input_ids[0].tolist()

    def find_subseq(hay, needle):
        hits = []
        n = len(needle)
        for i in range(len(hay) - n + 1):
            if hay[i : i + n] == needle:
                hits.append(i)
        return hits

    lefts = find_subseq(ids, l_id)
    rights = find_subseq(ids, r_id)
    mask = torch.zeros_like(shift_labels, dtype=torch.bool)
    ri = 0
    for li in lefts:
        start = li + len(l_id)
        while ri < len(rights) and rights[ri] < start:
            ri += 1
        if ri >= len(rights):
            break
        end = rights[ri]
        a = max(start - 1, 0)
        b = max(end - 1, 0)
        if b > a:
            mask[0, a:b] = True
        ri += 1
    if not mask.any():
        return None
    log_probs = torch.log_softmax(shift_logits, dim=-1)
    token_lp = log_probs.gather(-1, shift_labels.unsqueeze(-1)).squeeze(-1)
    return float(-token_lp[mask].sum().item())


def main() -> None:
    assert DATA.exists(), f"missing {DATA}"
    if os.environ.get("SKIP_INSTALL", "").strip() not in {"1", "true", "TRUE"}:
        install()

    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    RESULTS.mkdir(parents=True, exist_ok=True)
    scores_path = RESULTS / "scores.jsonl"

    done: set[int] = set()
    if scores_path.exists():
        for line in scores_path.read_text().splitlines():
            if line.strip():
                done.add(json.loads(line)["i"])
        print(f"resuming: {len(done)} scored", flush=True)

    print("Loading", MODEL, flush=True)
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

    rows = [json.loads(l) for l in DATA.read_text().splitlines() if l.strip()]
    smoke_n = int(os.environ.get("SMOKE_N", "0"))
    if smoke_n > 0:
        rows = rows[:smoke_n]
    print(f"rows={len(rows)} already={len(done)}", flush=True)

    sums: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    # reload prior scores into aggregates
    if scores_path.exists():
        for line in scores_path.read_text().splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec.get("nll") is None:
                continue
            sums[rec["experiment"]] += rec["nll"]
            counts[rec["experiment"]] += 1

    with scores_path.open("a") as fout:
        for i, r in enumerate(rows):
            if i in done:
                continue
            exp = r["experiment"].split("/")[0]
            val = nll_for_text(model, tok, r["text"])
            fout.write(json.dumps({"i": i, "experiment": exp, "nll": val}) + "\n")
            fout.flush()
            if val is not None:
                sums[exp] += val
                counts[exp] += 1
            scored = len(done) + 1
            done.add(i)
            if scored % 25 == 0 or i + 1 == len(rows):
                print(f"scored {len(done)}/{len(rows)}", flush=True)
                (RESULTS / "PROGRESS.json").write_text(
                    json.dumps(
                        {
                            "scored": len(done),
                            "total": len(rows),
                            "max_seq": MAX_SEQ,
                            "model": MODEL,
                        }
                    )
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
    summary = {
        "model": MODEL,
        "role": "base_floor",
        "total_nll_sum": sum(sums.values()),
        "n_items": total_n,
        "n_experiments": len(per_exp),
        "max_seq": MAX_SEQ,
        "per_experiment": per_exp,
        "coverage": {
            "actual": total_n,
            "expected": len(rows),
            "unit": "items",
            "complete": total_n >= len(rows) and smoke_n == 0,
        },
    }
    (RESULTS / "SUMMARY.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps({k: summary[k] for k in summary if k != "per_experiment"}, indent=2), flush=True)


if __name__ == "__main__":
    main()
