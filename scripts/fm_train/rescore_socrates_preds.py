#!/usr/bin/env python3
"""Rescore an existing Socrates predictions.jsonl with the paper metric.

Does not regenerate. Reads preds already produced by vLLM (DPO or SFT)
and writes SUMMARY_PAPER.json + DECISION.json using socrates_metric.score.
"""
from __future__ import annotations

import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "fm_baselines"))
from socrates_metric import score  # noqa: E402

ROOT = Path(os.environ.get("ROOT", "/opt/usersim_fm"))
RESULTS = Path(
    os.environ.get(
        "RESULTS_DIR",
        str(ROOT / "results" / "socrates_dpo" / "eval_full"),
    )
)
PREDS = Path(os.environ.get("PREDS", str(RESULTS / "predictions.jsonl")))
LORA = os.environ.get("LORA_PATH", str(ROOT / "adapters" / "ckpt425_dpo"))
BASELINE_W = float(os.environ.get("BASELINE_W", "0.1418"))
BASELINE_ACC = float(os.environ.get("BASELINE_ACC", "0.606"))
W_MAX = float(os.environ.get("W_MAX", "0.16"))
ACC_MIN = float(os.environ.get("ACC_MIN", "0.61"))


def load_preds(path: Path) -> list[dict]:
    rows: list[dict] = []
    skipped = 0
    with path.open("r", errors="replace") as f:
        for raw in f:
            line = raw.strip().rstrip("\x00")
            if not line:
                if raw.strip():
                    skipped += 1
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                skipped += 1
                continue
            if isinstance(rec, dict) and "sample_id" in rec:
                rows.append(rec)
            else:
                skipped += 1
    if skipped:
        print(f"skipped {skipped} unreadable line(s)", flush=True)
    # last write wins on duplicate sample_id
    by_id = {r["sample_id"]: r for r in rows}
    return list(by_id.values())


def accuracies(preds: list[dict]) -> dict:
    cells: dict[tuple, list[float]] = defaultdict(list)
    for r in preds:
        if r.get("human") is None:
            continue
        key = (r["study_id"], str(r["condition_num"]), str(r["task_num"]))
        cells[key].append(float(r["human"]))
    ranges = {k: (min(v), max(v)) for k, v in cells.items()}

    n = 0
    exact = 0
    clip_round = 0
    within1 = 0
    clip_within1 = 0
    for r in preds:
        h, p = r.get("human"), r.get("pred")
        if h is None or p is None:
            continue
        h = float(h)
        p = float(p)
        key = (r["study_id"], str(r["condition_num"]), str(r["task_num"]))
        rmin, rmax = ranges[key]
        pc = min(max(p, rmin), rmax)
        n += 1
        if round(p) == round(h):
            exact += 1
        if round(pc) == round(h):
            clip_round += 1
        if abs(round(p) - round(h)) <= 1:
            within1 += 1
        if abs(round(pc) - round(h)) <= 1:
            clip_within1 += 1
    if not n:
        return {"n": 0}
    return {
        "n": n,
        "exact_round": exact / n,
        "clip_to_cell_range_then_round": clip_round / n,
        "round_within_1": within1 / n,
        "clip_round_within_1": clip_within1 / n,
    }


def main() -> None:
    if not PREDS.exists():
        raise SystemExit(f"missing preds: {PREDS}")
    preds = load_preds(PREDS)
    print(f"preds={len(preds)} from {PREDS}", flush=True)
    agg = score(preds)
    acc = accuracies(preds)
    # Individual Acc = exact match after rounding (paper-style).
    # Also report the ±1 / clip variants used in earlier ckpt-425 notes.
    individual_acc = acc.get("exact_round")
    w = agg["wasserstein_mean"]
    w_ok = w is not None and float(w) <= W_MAX
    acc_ok = individual_acc is not None and float(individual_acc) > ACC_MIN
    keep = bool(w_ok and acc_ok)

    summary = {
        "model": "Qwen/Qwen3-8B-Base",
        "lora": LORA,
        "role": "dpo_adapter",
        "scorer": "socrates_metric.score (paper [0,1] clip)",
        "n_studies": agg["n_studies"],
        "n_cells": agg["n_cells"],
        "n_preds": agg["n_preds"],
        "wasserstein_mean": w,
        "uniform_control": agg["uniform_control"],
        "target_paper_socrates": agg["paper_target"],
        "parse": agg["parse"],
        "accuracy": individual_acc,
        "accuracy_variants": acc,
        "per_study": agg["per_study"],
        "skipped": agg["skipped"],
        "rescored_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "SUMMARY_PAPER.json").write_text(json.dumps(summary, indent=2) + "\n")
    try:
        (RESULTS / "SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n")
    except OSError as exc:
        print(f"WARN could not overwrite SUMMARY.json: {exc}", flush=True)

    decision = {
        "keep": keep,
        "kill": not keep,
        "wasserstein_mean": w,
        "accuracy": individual_acc,
        "accuracy_variants": acc,
        "uniform_control": agg["uniform_control"],
        "baseline_ckpt425": {"wasserstein_mean": BASELINE_W, "accuracy": BASELINE_ACC},
        "rules": {
            "acc_must_clearly_beat": ACC_MIN,
            "acc_definition": "exact_round",
            "w_max": W_MAX,
            "w_definition": "paper [0,1] human-range standardize + clip",
        },
        "reasons": [
            *([] if w_ok else [f"W={w} > {W_MAX} (ckpt-425 had {BASELINE_W})"]),
            *(
                []
                if acc_ok
                else [
                    f"Acc={individual_acc} does not clearly beat {ACC_MIN} "
                    f"(ckpt-425 reported {BASELINE_ACC}; exact-round on this dump)"
                ]
            ),
        ],
        "parse": agg["parse"],
        "n_studies": agg["n_studies"],
        "scorer": "socrates_metric.score",
        "lora": LORA,
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    (RESULTS / "DECISION.json").write_text(json.dumps(decision, indent=2) + "\n")
    print(json.dumps({k: summary[k] for k in summary if k != "per_study"}, indent=2))
    print(json.dumps(decision, indent=2))


if __name__ == "__main__":
    main()
