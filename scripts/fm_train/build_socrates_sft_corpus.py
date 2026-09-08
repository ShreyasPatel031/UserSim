#!/usr/bin/env python3
"""Build the SocSci210 SFT corpus from the 170 *seen* studies only.

Hard rule: the 40 unseen studies are the eval split and must never appear in
training. This script asserts that, writes the corpus and a card, and refuses
to emit anything if the leakage check fails.

Memory: the seen split is ~2.3M rows of long survey prompts, which does not fit
in a 32 GB box once converted to Python objects. Everything here streams in
Arrow batches and writes JSONL incrementally; peak RSS stays near the batch
size. Subsampling is a two-pass scheme (count per cell, then pick a
deterministic random subset of within-cell indices) so it stays exact without
buffering rows.

Usage:
  python3 build_socrates_sft_corpus.py [--max-per-cell N] [--out PATH]
"""
from __future__ import annotations

import argparse
import json
import os
import random
from collections import Counter, defaultdict
from pathlib import Path

from socrates_format import sample_id

ROOT = Path(os.environ.get("ROOT", "/opt/usersim_fm"))
KEY_COLS = ["study_id", "condition_num", "task_num"]
ROW_COLS = ["study_id", "sample_id", "condition_num", "task_num", "participant", "prompt", "response"]
BATCH = 2000


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--out",
        default=os.environ.get("SFT_CORPUS", str(ROOT / "data" / "socrates_sft.jsonl")),
    )
    ap.add_argument(
        "--max-per-cell",
        type=int,
        default=int(os.environ.get("MAX_PER_CELL", "0")),
        help="0 = keep every participant; N = subsample N per (study, condition, task)",
    )
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--limit-studies", type=int, default=0, help="smoke only")
    return ap.parse_args()


def load_mapping() -> dict:
    local = ROOT / "data" / "SocSci210_meta" / "metadata" / "participant_mapping.json"
    if local.exists():
        return json.loads(local.read_text())
    from huggingface_hub import hf_hub_download

    path = hf_hub_download(
        "socratesft/SocSci210",
        "metadata/participant_mapping.json",
        repo_type="dataset",
    )
    return json.loads(Path(path).read_text())


def cell_key(row: dict) -> tuple:
    return (row["study_id"], str(row["condition_num"]), str(row["task_num"]))


def iter_batches(ds, cols: list[str]):
    view = ds.select_columns(cols)
    for batch in view.iter(batch_size=BATCH):
        n = len(batch[cols[0]])
        for i in range(n):
            yield {c: batch[c][i] for c in cols}


def main() -> None:
    args = parse_args()
    from datasets import load_dataset

    mapping = load_mapping()
    seen = set(mapping["seen"])
    unseen = set(mapping["unseen"])
    if seen & unseen:
        raise SystemExit(f"mapping overlap: {sorted(seen & unseen)[:5]}")
    if args.limit_studies:
        seen = set(sorted(seen)[: args.limit_studies])
    print(f"target studies={len(seen)} unseen excluded={len(unseen)}", flush=True)

    ds = load_dataset("socratesft/SocSci210", split="train")
    print(f"dataset rows={ds.num_rows}", flush=True)

    keep_indices: dict[tuple, set[int]] | None = None
    if args.max_per_cell > 0:
        counts: Counter = Counter()
        for row in iter_batches(ds, KEY_COLS):
            if row["study_id"] in seen:
                counts[cell_key(row)] += 1
        rng = random.Random(args.seed)
        keep_indices = {}
        for key, total in counts.items():
            if total <= args.max_per_cell:
                keep_indices[key] = set(range(total))
            else:
                keep_indices[key] = set(rng.sample(range(total), args.max_per_cell))
        print(
            f"cells={len(counts)} rows_available={sum(counts.values())} "
            f"rows_selected={sum(len(v) for v in keep_indices.values())} "
            f"(max_per_cell={args.max_per_cell})",
            flush=True,
        )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".partial")

    seen_positions: dict[tuple, int] = defaultdict(int)
    studies_written: set[str] = set()
    n_written = 0
    n_leaked = 0
    with tmp.open("w") as f:
        for row in iter_batches(ds, ROW_COLS):
            sid = row["study_id"]
            if sid not in seen:
                continue
            if sid in unseen:
                n_leaked += 1
                continue
            key = cell_key(row)
            pos = seen_positions[key]
            seen_positions[key] = pos + 1
            if keep_indices is not None and pos not in keep_indices.get(key, ()):
                continue
            f.write(
                json.dumps(
                    {
                        "sample_id": sample_id(row),
                        "study_id": sid,
                        "condition_num": str(row["condition_num"]),
                        "task_num": str(row["task_num"]),
                        "prompt": row["prompt"],
                        "response": row["response"],
                    }
                )
                + "\n"
            )
            studies_written.add(sid)
            n_written += 1
            if n_written % 25000 == 0:
                print(f"written={n_written}", flush=True)

    if n_leaked:
        tmp.unlink(missing_ok=True)
        raise SystemExit(f"LEAKAGE: {n_leaked} rows from unseen studies reached the writer")
    if n_written == 0:
        tmp.unlink(missing_ok=True)
        raise SystemExit("no rows written")
    tmp.replace(out)

    card = {
        "source": "socratesft/SocSci210",
        "split": "seen studies (participant_mapping.json)",
        "n_rows": n_written,
        "n_studies": len(studies_written),
        "n_cells": len(seen_positions),
        "unseen_studies_excluded": len(unseen),
        "max_per_cell": args.max_per_cell,
        "leakage_check": "passed: zero unseen study_ids",
        "format": "socrates_format.py (system + user prompt -> assistant response)",
        "out": str(out),
    }
    card_name = "corpus_card_smoke.json" if args.limit_studies else "corpus_card.json"
    card_path = ROOT / "results" / "socrates_sft" / card_name
    card_path.parent.mkdir(parents=True, exist_ok=True)
    card_path.write_text(json.dumps(card, indent=2) + "\n")
    print(json.dumps(card, indent=2), flush=True)


if __name__ == "__main__":
    main()
