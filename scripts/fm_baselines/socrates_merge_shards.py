#!/usr/bin/env python3
"""Merge Socrates shard predictions and write SUMMARY.json (Gate 0 artifact).

Reads predictions.shard*.jsonl from --in-dir (or GCS), dedupes by sample_id,
runs socrates_metric.aggregate, and writes SUMMARY.json only when coverage is
complete (40 studies + expected row count).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from gate_contract import coverage_block, write_summary_or_partial  # noqa: E402
from socrates_metric import aggregate  # noqa: E402

EXPECTED_STUDIES = 40
EXPECTED_ROWS = 482642
MODEL = "socratesft/socrates-qwen2.5-14b-sft"


def load_preds(in_dir: Path) -> list[dict]:
    files = sorted(in_dir.glob("predictions.shard*.jsonl"))
    if not files:
        # also accept the single-VM name
        single = in_dir / "predictions.jsonl"
        files = [single] if single.exists() else []
    if not files:
        raise SystemExit(f"no predictions*.jsonl under {in_dir}")

    by_id: dict[str, dict] = {}
    for f in files:
        for line in f.read_text().splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            by_id[rec["sample_id"]] = rec
        print(f"loaded {f.name}: running unique={len(by_id)}", flush=True)
    return list(by_id.values())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in-dir", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, default=None)
    args = ap.parse_args()
    out = args.out_dir or args.in_dir
    out.mkdir(parents=True, exist_ok=True)

    preds = load_preds(args.in_dir)
    agg = aggregate(preds)
    n_studies = agg["n_studies"]
    n_preds = len(preds)
    complete = n_studies >= EXPECTED_STUDIES and n_preds >= EXPECTED_ROWS
    cov = coverage_block(
        actual=n_studies,
        expected=EXPECTED_STUDIES,
        unit="studies",
        complete=complete,
        failed=[],
        extra={"n_preds": n_preds, "expected_rows": EXPECTED_ROWS},
    )
    summary = {
        "model": MODEL,
        "n_studies": n_studies,
        "n_cells": agg["n_cells"],
        "n_preds": n_preds,
        "wasserstein_mean": agg["wasserstein_mean"],
        "target_paper": 0.151,
        "empirical_best_paper": 0.125,
        "per_study": agg["per_study"],
        "coverage": cov,
        "smoke_studies": 0,
        "max_per_cell": 0,
        "engine": "vllm_fp8_shard",
        "skipped": agg["skipped"],
    }
    (out / "cells.json").write_text(json.dumps(agg["cell_rows"], indent=2))
    reason = None
    if not complete:
        reason = f"n_preds_{n_preds}_of_{EXPECTED_ROWS}_studies_{n_studies}"
    write_summary_or_partial(out, summary, complete=complete, reason=reason)
    print(
        json.dumps(
            {k: summary[k] for k in summary if k != "per_study"},
            indent=2,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
