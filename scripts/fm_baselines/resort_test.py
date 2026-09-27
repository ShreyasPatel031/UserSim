#!/usr/bin/env python3
"""Re-sort test: ckpt-425 multiset with Qwen3-14B rank order.

For each (study, condition, question) cell, keeps ckpt-425's multiset of
predicted values but assigns them to individuals in the rank order of
Qwen3-14B's predictions for those same individuals.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

# Use the PR31 version of socrates_metric with correct raw-scale W
import importlib.util
spec = importlib.util.spec_from_file_location("socrates_metric_pr31", "/tmp/socrates_metric_pr31.py")
socrates_metric = importlib.util.module_from_spec(spec)
spec.loader.exec_module(socrates_metric)
score = socrates_metric.score


def cell_key(row: dict) -> tuple:
    return (row["study_id"], str(row["condition_num"]), str(row["task_num"]))

SCREEN_STUDIES = ["326nv", "3muqx", "3pcdm", "3rvgz", "53kjy"]
RNG_SEED = 42


def load_ckpt425_preds(path: str) -> list[dict]:
    """Load ckpt-425 predictions.jsonl."""
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                rows.append(row)
            except json.JSONDecodeError:
                # Some lines may be corrupted - try splitting on }{ pattern
                parts = line.replace("}{", "}\n{").split("\n")
                for part in parts:
                    part = part.strip()
                    if part:
                        try:
                            rows.append(json.loads(part))
                        except json.JSONDecodeError:
                            pass
    return rows


def load_qwen3_14b_preds(folder: str) -> list[dict]:
    """Load Qwen3-14B per-study jsonl files."""
    rows = []
    folder = Path(folder)
    for p in folder.glob("*.jsonl"):
        if p.name.endswith(".done"):
            continue
        study_id = p.stem
        with open(p) as f:
            for line in f:
                row = json.loads(line)
                row["study_id"] = study_id
                rows.append(row)
    return rows


def build_lookup(rows: list[dict]) -> dict[tuple, dict]:
    """Build {(study, cond, task, person_id): row} lookup."""
    lookup = {}
    for r in rows:
        key = (r["study_id"], str(r.get("condition_num", r.get("condition"))), 
               str(r.get("task_num", r.get("question_num", r.get("task")))), 
               r.get("person_id", r.get("index", r.get("row_idx"))))
        lookup[key] = r
    return lookup


def get_person_key(row: dict) -> str:
    """Get a unique person identifier from a row.
    
    sample_id format: study_id|row_idx|condition_num|task_num|...
    """
    sample_id = row.get("sample_id", "")
    if sample_id:
        parts = sample_id.split("|")
        if len(parts) >= 2:
            return parts[1]  # row index (unique within study)
    return str(row.get("person_id", row.get("index", row.get("row_idx", ""))))


def resort_predictions(
    ckpt_rows: list[dict],
    qwen_rows: list[dict],
    rng_seed: int = RNG_SEED,
) -> list[dict]:
    """Reassign ckpt-425 predictions in Qwen3-14B's rank order."""
    rng = np.random.default_rng(rng_seed)
    
    # Group by cell
    ckpt_by_cell: dict[tuple, list[dict]] = defaultdict(list)
    for r in ckpt_rows:
        ckpt_by_cell[cell_key(r)].append(r)
    
    qwen_by_cell: dict[tuple, list[dict]] = defaultdict(list)
    for r in qwen_rows:
        ckpt_key = (r["study_id"], str(r.get("condition_num", r.get("condition"))),
                   str(r.get("task_num", r.get("question_num", r.get("task")))))
        qwen_by_cell[ckpt_key].append(r)
    
    resorted = []
    for key, ckpt_items in ckpt_by_cell.items():
        qwen_items = qwen_by_cell.get(key, [])
        
        # Get ckpt predictions and qwen predictions for ranking
        ckpt_preds = []
        for item in ckpt_items:
            pred = item.get("pred")
            if pred is not None:
                ckpt_preds.append(float(pred))
        
        if not ckpt_preds or not qwen_items:
            # No matching qwen predictions - keep original
            for item in ckpt_items:
                resorted.append(item.copy())
            continue
        
        # Match people between datasets
        ckpt_by_person = {get_person_key(r): r for r in ckpt_items}
        qwen_by_person = {get_person_key(r): r for r in qwen_items}
        
        common_people = set(ckpt_by_person.keys()) & set(qwen_by_person.keys())
        if not common_people:
            # No overlapping people - keep original
            for item in ckpt_items:
                resorted.append(item.copy())
            continue
        
        # Get qwen predictions for ranking
        qwen_vals = []
        for pid in common_people:
            qwen_row = qwen_by_person[pid]
            qwen_pred = qwen_row.get("pred")
            if qwen_pred is not None:
                # Add random noise for tie-breaking
                qwen_vals.append((pid, float(qwen_pred) + rng.uniform(-1e-9, 1e-9)))
            else:
                qwen_vals.append((pid, rng.uniform(-1e6, -1e5)))  # Missing -> bottom
        
        # Sort people by qwen prediction
        qwen_vals.sort(key=lambda x: x[1])
        rank_order = [pid for pid, _ in qwen_vals]
        
        # Get ckpt predictions for these people (sorted ascending)
        ckpt_vals = []
        for pid in common_people:
            ckpt_row = ckpt_by_person[pid]
            pred = ckpt_row.get("pred")
            if pred is not None:
                ckpt_vals.append(float(pred))
        ckpt_vals.sort()
        
        # Assign ckpt values to people in qwen rank order
        for i, pid in enumerate(rank_order):
            if i < len(ckpt_vals):
                new_row = ckpt_by_person[pid].copy()
                new_row["pred"] = ckpt_vals[i]
                new_row["resorted"] = True
                resorted.append(new_row)
            else:
                new_row = ckpt_by_person[pid].copy()
                resorted.append(new_row)
        
        # Add remaining people not in common
        for pid in ckpt_by_person:
            if pid not in common_people:
                resorted.append(ckpt_by_person[pid].copy())
    
    return resorted


def make_mix_predictions(
    ckpt_rows: list[dict],
    qwen_rows: list[dict],
    prob_ckpt: float = 0.29,
    rng_seed: int = RNG_SEED,
) -> list[dict]:
    """Per-person mix: use ckpt w.p. prob_ckpt, else qwen (LOSO style)."""
    rng = np.random.default_rng(rng_seed)
    
    qwen_lookup = build_lookup(qwen_rows)
    mixed = []
    
    for r in ckpt_rows:
        new_row = r.copy()
        key = (r["study_id"], str(r.get("condition_num")), 
               str(r.get("task_num")), get_person_key(r))
        
        if rng.random() < prob_ckpt:
            # Use ckpt prediction
            mixed.append(new_row)
        else:
            # Try to use qwen prediction
            qwen_row = qwen_lookup.get(key)
            if qwen_row and qwen_row.get("pred") is not None:
                new_row["pred"] = qwen_row.get("pred")
                new_row["source"] = "qwen"
            mixed.append(new_row)
    
    return mixed


def paper_accuracy(preds: list[dict], clip: bool) -> float | None:
    """Paper accuracy: 1 - normalized MAE.
    
    MAE is normalized by the human response range per cell.
    """
    cells: dict[tuple, list] = defaultdict(list)
    for p in preds:
        if p.get("pred") is None:
            continue
        try:
            h = float(p["human"])
            m = float(p["pred"])
        except (TypeError, ValueError):
            continue
        if not (np.isfinite(h) and np.isfinite(m)):
            continue
        cells[cell_key(p)].append((h, m))
    
    ranges = {}
    for key, items in cells.items():
        hs = [h for h, _ in items]
        rmin, rmax = min(hs), max(hs)
        if rmax > rmin:
            ranges[key] = (rmin, rmax)
    
    per_study: dict[str, list] = defaultdict(list)
    for p in preds:
        if p.get("pred") is None:
            continue
        try:
            h = float(p["human"])
            m = float(p["pred"])
        except (TypeError, ValueError):
            continue
        key = cell_key(p)
        if key not in ranges:
            continue
        rmin, rmax = ranges[key]
        if clip:
            m = min(max(m, rmin), rmax)
        per_study[p["study_id"]].append(abs(m - h) / (rmax - rmin))
    
    study_acc = {s: 1.0 - float(np.mean(errs)) for s, errs in per_study.items() if errs}
    return float(np.mean(list(study_acc.values()))) if study_acc else None


def accuracy_raw(preds: list[dict]) -> float:
    """Paper accuracy (1 - normalized MAE), raw."""
    return paper_accuracy(preds, clip=False) or 0.0


def accuracy_clipped(preds: list[dict]) -> float:
    """Paper accuracy (1 - normalized MAE), clipped to human range."""
    return paper_accuracy(preds, clip=True) or 0.0


def filter_studies(rows: list[dict], study_ids: list[str]) -> list[dict]:
    """Filter to only specified studies."""
    return [r for r in rows if r.get("study_id") in study_ids]


def compute_all_metrics(preds: list[dict], name: str) -> dict:
    """Compute W, acc_raw, acc_clipped for predictions."""
    result = score(preds)
    return {
        "name": name,
        "W": result["wasserstein_mean"],
        "acc_raw": accuracy_raw(preds),
        "acc_clipped": accuracy_clipped(preds),
        "n_studies": result["n_studies"],
        "n_cells": result["n_cells"],
        "n_preds": result["n_preds"],
    }


def main():
    ckpt_path = "/tmp/resort_test/ckpt425/predictions.jsonl"
    qwen_folder = "/tmp/resort_test/qwen3_14b"
    
    print("Loading predictions...")
    ckpt_rows = load_ckpt425_preds(ckpt_path)
    qwen_rows = load_qwen3_14b_preds(qwen_folder)
    
    print(f"Loaded {len(ckpt_rows)} ckpt-425 predictions")
    print(f"Loaded {len(qwen_rows)} Qwen3-14B predictions")
    
    # Resort predictions
    print("Re-sorting predictions...")
    resorted = resort_predictions(ckpt_rows, qwen_rows)
    print(f"Generated {len(resorted)} re-sorted predictions")
    
    # Make mix predictions
    print("Making mix predictions (p=0.29 ckpt)...")
    mixed = make_mix_predictions(ckpt_rows, qwen_rows, prob_ckpt=0.29)
    
    # Compute metrics for screen studies (5)
    screen_ckpt = filter_studies(ckpt_rows, SCREEN_STUDIES)
    screen_qwen = filter_studies(qwen_rows, SCREEN_STUDIES)
    screen_resorted = filter_studies(resorted, SCREEN_STUDIES)
    screen_mixed = filter_studies(mixed, SCREEN_STUDIES)
    
    print("\n" + "=" * 70)
    print("SCREEN STUDIES (5):", SCREEN_STUDIES)
    print("=" * 70)
    
    screen_results = []
    for preds, name in [
        (screen_ckpt, "ckpt-425"),
        (screen_qwen, "Qwen3-14B"),
        (screen_resorted, "re-sorted"),
        (screen_mixed, "mix (p=0.29)"),
    ]:
        metrics = compute_all_metrics(preds, name)
        screen_results.append(metrics)
        print(f"\n{name}:")
        print(f"  W = {metrics['W']:.4f}" if metrics['W'] else "  W = N/A")
        print(f"  acc_raw = {metrics['acc_raw']*100:.1f}%")
        print(f"  acc_clipped = {metrics['acc_clipped']*100:.1f}%")
        print(f"  n_studies={metrics['n_studies']}, n_cells={metrics['n_cells']}")
    
    # Compute metrics for full 40 studies
    print("\n" + "=" * 70)
    print("FULL 40 STUDIES")
    print("=" * 70)
    
    full_results = []
    for preds, name in [
        (ckpt_rows, "ckpt-425"),
        (qwen_rows, "Qwen3-14B"),
        (resorted, "re-sorted"),
        (mixed, "mix (p=0.29)"),
    ]:
        metrics = compute_all_metrics(preds, name)
        full_results.append(metrics)
        print(f"\n{name}:")
        print(f"  W = {metrics['W']:.4f}" if metrics['W'] else "  W = N/A")
        print(f"  acc_raw = {metrics['acc_raw']*100:.1f}%")
        print(f"  acc_clipped = {metrics['acc_clipped']*100:.1f}%")
        print(f"  n_studies={metrics['n_studies']}, n_cells={metrics['n_cells']}")
    
    # Check pass bar for screen
    print("\n" + "=" * 70)
    print("PASS BAR CHECK (screen studies)")
    print("W <= 0.160, acc_raw >= 65.0%, acc_clipped >= 70.0%, beats mix")
    print("=" * 70)
    
    resorted_screen = screen_results[2]
    mix_screen = screen_results[3]
    
    checks = {
        "W <= 0.160": resorted_screen["W"] is not None and resorted_screen["W"] <= 0.160,
        "acc_raw >= 65.0%": resorted_screen["acc_raw"] >= 0.65,
        "acc_clipped >= 70.0%": resorted_screen["acc_clipped"] >= 0.70,
        "beats mix on W": resorted_screen["W"] is not None and mix_screen["W"] is not None and resorted_screen["W"] <= mix_screen["W"],
        "beats mix on acc_clipped": resorted_screen["acc_clipped"] >= mix_screen["acc_clipped"],
    }
    
    all_pass = all(checks.values())
    for check, passed in checks.items():
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"  {status}: {check}")
    
    print(f"\nOVERALL: {'PASS' if all_pass else 'FAIL'}")
    
    # Save results
    results = {
        "screen_studies": SCREEN_STUDIES,
        "screen_results": screen_results,
        "full_results": full_results,
        "pass_checks": checks,
        "overall_pass": all_pass,
    }
    
    out_path = Path(__file__).parent / "resort_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to {out_path}")
    
    return results


if __name__ == "__main__":
    main()
