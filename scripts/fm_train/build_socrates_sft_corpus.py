#!/usr/bin/env python3
"""Build the SocSci210 SFT corpus from the 170 *seen* studies only.

Hard rule: the 40 unseen studies are the eval split and must never appear in
training. This script asserts that, writes the corpus and a card, and refuses
to emit anything if the leakage check fails.

Usage:
  python3 build_socrates_sft_corpus.py [--max-per-cell N] [--out PATH]
"""
from __future__ import annotations

import argparse
import json
import os
import random
from collections import defaultdict
from pathlib import Path

from socrates_format import sample_id

ROOT = Path(os.environ.get("ROOT", "/opt/usersim_fm"))


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


def main() -> None:
    args = parse_args()
    from datasets import load_dataset

    mapping = load_mapping()
    seen = set(mapping["seen"])
    unseen = set(mapping["unseen"])
    if seen & unseen:
        raise SystemExit(f"mapping overlap: {sorted(seen & unseen)[:5]}")
    print(f"seen={len(seen)} unseen={len(unseen)}", flush=True)

    ds = load_dataset("socratesft/SocSci210", split="train")
    study_ids = ds["study_id"]
    keep = [s in seen for s in study_ids]
    ds = ds.filter(lambda _, i: keep[i], with_indices=True, num_proc=2)
    rows = ds.to_list()
    print(f"seen rows={len(rows)}", flush=True)

    if args.limit_studies:
        pick = set(sorted(seen)[: args.limit_studies])
        rows = [r for r in rows if r["study_id"] in pick]
        print(f"smoke limit → {len(rows)} rows from {len(pick)} studies", flush=True)

    leaked = [r["study_id"] for r in rows if r["study_id"] in unseen]
    if leaked:
        raise SystemExit(f"LEAKAGE: unseen studies present in train: {set(leaked)}")

    if args.max_per_cell > 0:
        rng = random.Random(args.seed)
        by_cell: dict[tuple, list] = defaultdict(list)
        for r in rows:
            by_cell[(r["study_id"], str(r["condition_num"]), str(r["task_num"]))].append(r)
        subsampled = []
        for items in by_cell.values():
            if len(items) > args.max_per_cell:
                subsampled.extend(rng.sample(items, args.max_per_cell))
            else:
                subsampled.extend(items)
        print(
            f"subsample max_per_cell={args.max_per_cell}: "
            f"{len(rows)} → {len(subsampled)} over {len(by_cell)} cells",
            flush=True,
        )
        rows = subsampled

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    n_studies = len({r["study_id"] for r in rows})
    with out.open("w") as f:
        for r in rows:
            f.write(
                json.dumps(
                    {
                        "sample_id": sample_id(r),
                        "study_id": r["study_id"],
                        "condition_num": str(r["condition_num"]),
                        "task_num": str(r["task_num"]),
                        "prompt": r["prompt"],
                        "response": r["response"],
                    }
                )
                + "\n"
            )

    card = {
        "source": "socratesft/SocSci210",
        "split": "seen studies (participant_mapping.json)",
        "n_rows": len(rows),
        "n_studies": n_studies,
        "n_seen_studies_available": len(seen),
        "unseen_studies_excluded": len(unseen),
        "max_per_cell": args.max_per_cell,
        "leakage_check": "passed: zero unseen study_ids",
        "format": "socrates_format.py (system + user prompt → assistant response)",
        "out": str(out),
    }
    card_path = ROOT / "results" / "socrates_sft" / "corpus_card.json"
    card_path.parent.mkdir(parents=True, exist_ok=True)
    card_path.write_text(json.dumps(card, indent=2) + "\n")
    print(json.dumps(card, indent=2), flush=True)


if __name__ == "__main__":
    main()
