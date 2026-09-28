#!/usr/bin/env python3
"""Build Socrates demographic-contrastive DPO pairs.

Paper recipe (Kolluri et al. EMNLP 2025 §4): for focal persona p_pos with
response r_pos under (condition c, outcome o), sample another response r_neg
from the same cell with a different value. Prompt q uses p_pos for both sides;
chosen=r_pos, rejected=r_neg.

Default input is the already-filtered SFT corpus (`socrates_sft.jsonl`, seen
studies only, MAX_PER_CELL capped) so this stays memory-safe on the L4 box.
"""
from __future__ import annotations

import argparse
import json
import os
import random
from collections import defaultdict
from pathlib import Path

ROOT = Path(os.environ.get("ROOT", "/opt/usersim_fm"))


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--sft-corpus",
        default=os.environ.get("SFT_CORPUS", str(ROOT / "data" / "socrates_sft.jsonl")),
        help="Seen-study SFT JSONL (prompt/response already leakage-filtered).",
    )
    ap.add_argument(
        "--out",
        default=os.environ.get(
            "DPO_CORPUS", str(ROOT / "data" / "socrates_dpo_pairs.jsonl")
        ),
    )
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument(
        "--max-pairs",
        type=int,
        default=int(os.environ.get("MAX_PAIRS", "0")),
        help="Optional hard cap (0 = one pair per eligible focal row).",
    )
    ap.add_argument(
        "--limit-rows",
        type=int,
        default=int(os.environ.get("LIMIT_ROWS", "0")),
        help="Smoke: only read first N SFT rows before pairing.",
    )
    return ap.parse_args()


def cell_key(row: dict) -> tuple:
    return (row["study_id"], str(row["condition_num"]), str(row["task_num"]))


def main() -> None:
    args = parse_args()
    src = Path(args.sft_corpus)
    if not src.exists():
        raise SystemExit(
            f"SFT corpus missing: {src}. Build it with build_socrates_sft_corpus.py first."
        )

    # Group by cell.
    cells: dict[tuple, list[dict]] = defaultdict(list)
    n_in = 0
    with src.open() as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            row["response"] = str(row["response"]).strip()
            cells[cell_key(row)].append(row)
            n_in += 1
            if args.limit_rows and n_in >= args.limit_rows:
                break
    print(f"sft_rows={n_in} cells={len(cells)}", flush=True)

    rng = random.Random(args.seed)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".partial")

    n_pairs = 0
    n_skip = 0
    studies: set[str] = set()
    with tmp.open("w") as f:
        for key, rows in cells.items():
            by_resp: dict[str, list[dict]] = defaultdict(list)
            for r in rows:
                by_resp[r["response"]].append(r)
            if len(by_resp) < 2:
                n_skip += len(rows)
                continue
            distinct = list(by_resp.keys())
            for focal in rows:
                chosen = focal["response"]
                alts = [r for r in distinct if r != chosen]
                if not alts:
                    n_skip += 1
                    continue
                rejected = rng.choice(alts)
                pair = {
                    "prompt": focal["prompt"],
                    "chosen": chosen,
                    "rejected": rejected,
                    "study_id": focal["study_id"],
                    "condition_num": str(focal["condition_num"]),
                    "task_num": str(focal["task_num"]),
                    "sample_id": focal.get("sample_id"),
                    "pair_type": "demographic_contrastive",
                }
                f.write(json.dumps(pair) + "\n")
                studies.add(focal["study_id"])
                n_pairs += 1
                if args.max_pairs and n_pairs >= args.max_pairs:
                    break
            if args.max_pairs and n_pairs >= args.max_pairs:
                break

    if n_pairs == 0:
        tmp.unlink(missing_ok=True)
        raise SystemExit("no DPO pairs written (need cells with ≥2 distinct responses)")
    tmp.replace(out)

    card = {
        "source_corpus": str(src),
        "recipe": (
            "paper demographic-contrastive DPO: same prompt (p_pos); "
            "chosen=r_pos; rejected=r_neg from same (study,condition,task)"
        ),
        "n_sft_rows_read": n_in,
        "n_pairs": n_pairs,
        "n_studies": len(studies),
        "n_cells": len(cells),
        "skipped_rows_no_alt": n_skip,
        "out": str(out),
    }
    smoke = bool(args.limit_rows or args.max_pairs)
    name = "dpo_corpus_card_smoke.json" if smoke else "dpo_corpus_card.json"
    card_path = ROOT / "results" / "socrates_dpo" / name
    card_path.parent.mkdir(parents=True, exist_ok=True)
    card_path.write_text(json.dumps(card, indent=2) + "\n")
    print(json.dumps(card, indent=2), flush=True)


if __name__ == "__main__":
    main()
