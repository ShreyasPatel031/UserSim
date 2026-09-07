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
    """NLL on response tokens inside <<...>> (Centaur/Minitaur metric).

    Uses char offsets so Qwen/Llama tokenization of '<<'/'>>' cannot miss spans.
    """
    import re

    if "<<" not in text or ">>" not in text:
        return None
    # Prefer offset mapping (fast tokenizers). Fall back without specials if needed.
    try:
        enc = tokenizer(
            text,
            return_tensors="pt",
            truncation=True,
            max_length=MAX_SEQ,
            return_offsets_mapping=True,
        )
    except Exception:
        enc = tokenizer(text, return_tensors="pt", truncation=True, max_length=MAX_SEQ)
        enc["offset_mapping"] = None

    input_ids = enc.input_ids.to(model.device)
    with torch.no_grad():
        logits = model(input_ids=input_ids).logits
    shift_logits = logits[:, :-1, :].float()
    shift_labels = input_ids[:, 1:]
    mask = torch.zeros_like(shift_labels, dtype=torch.bool)

    truncated = tokenizer.decode(input_ids[0], skip_special_tokens=False)
    # Work in original `text` char space up to truncation length via offsets.
    offsets = enc.get("offset_mapping")
    if offsets is None:
        # Slow path: rebuild offsets manually is hard; use decode alignment via
        # scanning decoded pieces — still better than brittle multi-token needles.
        return None
    offsets = offsets[0].tolist()

    # Content inside <<...>> only (same as Minitaur: after <<, before >>).
    for m in re.finditer(r"<<(.*?)>>", text, flags=re.DOTALL):
        a, b = m.start(1), m.end(1)
        if a >= b:
            continue
        tok_idxs = [
            ti
            for ti, (s, e) in enumerate(offsets)
            if not (e <= a or s >= b) and not (s == 0 and e == 0)
        ]
        for ti in tok_idxs:
            # shift_labels[t] predicts token at t+1 → to score token ti, mask ti-1
            if ti >= 1:
                mask[0, ti - 1] = True

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
    smoke_n = int(os.environ.get("SMOKE_N", "0"))
    scores_path = RESULTS / ("scores.smoke.jsonl" if smoke_n > 0 else "scores.jsonl")
    if os.environ.get("FORCE_RESCORE", "").strip() in {"1", "true", "TRUE"} and scores_path.exists():
        scores_path.unlink()
        print(f"FORCE_RESCORE cleared {scores_path}", flush=True)

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
