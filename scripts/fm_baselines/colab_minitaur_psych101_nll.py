#!/usr/bin/env python3
"""Reproduce Minitaur NLL on Psych-101-test (held-out participants)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import torch

ROOT = Path("/content/fm_baselines")
DATA = ROOT / "data" / "Psych-101-test" / "prompts_testing_t1.jsonl"
RESULTS = ROOT / "results" / "minitaur"
MODEL = "marcelbinz/Llama-3.1-Minitaur-8B-adapter"
# T4 OOM'd at 8192; 4096 fits T4. Override with MAX_SEQ env. Paper uses up to 32768 on A100.
MAX_SEQ = int(os.environ.get("MAX_SEQ", "4096"))


def sh(cmd: str) -> None:
    print("+", cmd, flush=True)
    subprocess.run(cmd, shell=True, check=True)


def install() -> None:
    sh(f"{sys.executable} -m pip install -q -U pip")
    # unsloth stack
    sh(f"{sys.executable} -m pip install -q 'unsloth' transformers accelerate bitsandbytes peft datasets trl sentencepiece protobuf")


def main() -> None:
    assert DATA.exists(), f"missing {DATA}"
    install()
    from unsloth import FastLanguageModel

    print("Loading", MODEL, flush=True)
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=MODEL,
        max_seq_length=MAX_SEQ,
        dtype=None,
        load_in_4bit=True,
    )
    FastLanguageModel.for_inference(model)

    rows = [json.loads(l) for l in DATA.read_text().splitlines() if l.strip()]
    print(f"loaded {len(rows)} test rows", flush=True)

    # Per-experiment aggregate NLL on response tokens inside << >>
    l_id = tokenizer(" <<").input_ids[1:]
    r_id = tokenizer(">>").input_ids[1:]

    experiments = sorted({r["experiment"].split("/")[0] for r in rows})
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = {}

    def nll_for_text(text: str) -> float | None:
        # Find <<...>> spans and score those tokens only
        if "<<" not in text or ">>" not in text:
            return None
        # Teacher-force full sequence; mask loss outside responses
        enc = tokenizer(text, return_tensors="pt", truncation=True, max_length=MAX_SEQ)
        input_ids = enc.input_ids.to(model.device)
        with torch.no_grad():
            logits = model(input_ids=input_ids).logits
        # shift
        shift_logits = logits[:, :-1, :].float()
        shift_labels = input_ids[:, 1:]
        # Build mask: tokens that are inside << >>
        # Reconstruct with offset mapping is hard without offsets; approximate via token search
        ids = input_ids[0].tolist()
        # Find all << and >> token sequences
        def find_subseq(hay, needle):
            hits = []
            n = len(needle)
            for i in range(len(hay) - n + 1):
                if hay[i : i + n] == needle:
                    hits.append(i)
            return hits

        lefts = find_subseq(ids, l_id)
        rights = find_subseq(ids, r_id)
        # Pair left->next right
        mask = torch.zeros_like(shift_labels, dtype=torch.bool)
        ri = 0
        for li in lefts:
            # response tokens start after left template
            start = li + len(l_id)
            while ri < len(rights) and rights[ri] < start:
                ri += 1
            if ri >= len(rights):
                break
            end = rights[ri]  # exclusive of >>
            # labels index is position-1 relative to input; mask positions start..end-1 in labels => (start-1)..(end-2)? 
            # shift_labels[t] predicts token at t+1, so to score tokens [start, end), mask indices start-1 .. end-2
            a = max(start - 1, 0)
            b = max(end - 1, 0)
            if b > a:
                mask[0, a:b] = True
            ri += 1
        if not mask.any():
            return None
        log_probs = torch.log_softmax(shift_logits, dim=-1)
        token_lp = log_probs.gather(-1, shift_labels.unsqueeze(-1)).squeeze(-1)
        # NLL = -sum logp over response tokens (paper uses sum of CE over response tokens per item then aggregates)
        nll = -token_lp[mask].sum().item()
        return nll

    # Smoke: first 20 rows
    smoke_n = int(os.environ.get("SMOKE_N", "0"))
    use_rows = rows[:smoke_n] if smoke_n > 0 else rows

    from collections import defaultdict

    sums = defaultdict(float)
    counts = defaultdict(int)
    for i, r in enumerate(use_rows):
        exp = r["experiment"].split("/")[0]
        val = nll_for_text(r["text"])
        if val is None:
            continue
        sums[exp] += val
        counts[exp] += 1
        if (i + 1) % 50 == 0:
            print(f"scored {i+1}/{len(use_rows)}", flush=True)
            (RESULTS / "PROGRESS.json").write_text(
                json.dumps({"scored": i + 1, "total": len(use_rows), "max_seq": MAX_SEQ})
            )

    for exp in experiments:
        if counts[exp]:
            out[exp] = {"nll_sum": sums[exp], "n_items": counts[exp], "nll_mean": sums[exp] / counts[exp]}
    (RESULTS / "minitaur_psych101_nll.json").write_text(json.dumps(out, indent=2))
    total_nll = sum(sums.values())
    total_n = sum(counts.values())
    summary = {"model": MODEL, "total_nll_sum": total_nll, "n_items": total_n, "n_experiments": len(out), "max_seq": MAX_SEQ}
    (RESULTS / "SUMMARY.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
