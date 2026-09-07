#!/usr/bin/env python3
"""Qwen3-8B-Base floor: Psych-101-test NLL (same metric as Minitaur).

Resumes via scores.jsonl. Writes SUMMARY.json when all items scored.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import torch

ROOT = Path("/content/fm_baselines")
DATA = ROOT / "data" / "Psych-101-test" / "prompts_testing_t1.jsonl"
RESULTS = ROOT / "results" / "qwen3_8b_floor_psych101"
MODEL = os.environ.get("FLOOR_MODEL", "Qwen/Qwen3-8B-Base")
MAX_SEQ = int(os.environ.get("MAX_SEQ", "4096"))
MODE = os.environ.get("MODE", "full").strip().lower()
SMOKE_N = int(os.environ.get("SMOKE_N", "20"))


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
    """Char-offset <<...>> mask. Do not search tokenizer(' <<') subsequences."""
    if "<<" not in text or ">>" not in text:
        return None
    spans = [(m.start(1), m.end(1)) for m in re.finditer(r"<<(.*?)>>", text, flags=re.S)]
    if not spans:
        return None
    enc = tokenizer(
        text,
        return_tensors="pt",
        truncation=True,
        max_length=MAX_SEQ,
        return_offsets_mapping=True,
    )
    offsets = enc.pop("offset_mapping")[0].tolist()
    input_ids = enc.input_ids.to(model.device)
    with torch.no_grad():
        logits = model(input_ids=input_ids).logits
    shift_logits = logits[:, :-1, :].float()
    shift_labels = input_ids[:, 1:]
    mask = torch.zeros_like(shift_labels, dtype=torch.bool)
    for ts, te in spans:
        for i, (s, e) in enumerate(offsets):
            if i == 0:
                continue
            if e <= s:
                continue
            if s >= ts and e <= te:
                mask[0, i - 1] = True
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

    if MODE not in {"smoke", "full"}:
        raise SystemExit(f"MODE must be smoke|full, got {MODE}")
    if MODE == "full":
        smoke_ok = RESULTS / "SMOKE_OK.json"
        if not smoke_ok.exists():
            raise SystemExit("PROTOCOL: missing SMOKE_OK.json. Run MODE=smoke first.")
        if os.environ.get("WATCHDOG_ARMED", "").strip() not in {"1", "true", "TRUE"}:
            if not Path(os.environ.get("WATCHDOG_MARKER", "/content/fm_baselines/WATCHDOG_ARMED")).exists():
                raise SystemExit("PROTOCOL: watchdog not armed.")

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
    smoke_n = SMOKE_N if MODE == "smoke" else 0
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
            (RESULTS / "PROGRESS.json").write_text(
                json.dumps(
                    {
                        "scored": len(done),
                        "total": len(rows),
                        "max_seq": MAX_SEQ,
                        "model": MODEL,
                        "engine": "transformers-4bit",
                        "mode": MODE,
                    }
                )
            )
            if scored % 5 == 0 or i + 1 == len(rows):
                print(f"scored {len(done)}/{len(rows)}", flush=True)

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
    complete = bool(total_n >= len(rows) and smoke_n == 0)
    summary = {
        "model": MODEL,
        "role": "base_floor",
        "complete": complete,
        "total_nll_sum": sum(sums.values()),
        "n_items": total_n,
        "n_experiments": len(per_exp),
        "max_seq": MAX_SEQ,
        "per_experiment": per_exp,
        "coverage": {
            "actual": total_n,
            "expected": len(rows),
            "unit": "items",
            "complete": complete,
        },
    }
    (RESULTS / "SUMMARY.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps({k: summary[k] for k in summary if k != "per_experiment"}, indent=2), flush=True)
    if MODE == "smoke":
        valid = sum(1 for rec in (json.loads(l) for l in scores_path.read_text().splitlines() if l.strip()) if rec.get("nll") is not None)
        if valid < 1:
            raise SystemExit("PROTOCOL: smoke produced zero valid NLLs")
        (RESULTS / "SMOKE_OK.json").write_text(
            json.dumps(
                {
                    "passed": True,
                    "engine": "transformers-4bit",
                    "valid_nll": valid,
                    "n": len(rows),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
                indent=2,
            )
        )
        print("SMOKE_PASSED", flush=True)


if __name__ == "__main__":
    main()
