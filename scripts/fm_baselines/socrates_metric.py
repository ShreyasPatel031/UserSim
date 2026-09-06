#!/usr/bin/env python3
"""Socrates SocSci210 Wasserstein metric — single source of truth.

Extracted verbatim from colab_socrates_wass.py so that the single-VM runner,
the sharded vLLM workers, and the merge step cannot drift apart. Any change
here changes every consumer, which is the point: gates.yaml requires
`same_metric_code_from_upstream`.

Scoring, per the paper's §5.3 protocol as implemented upstream:
  - group predictions into (study, condition, task) cells
  - min-max scale human and model responses onto the human range for that cell
  - 1-D Wasserstein between the two distributions
  - mean over cells within a study, then mean over studies
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

import numpy as np

SYSTEM = (
    "You are simulating a survey respondent. Answer exactly as instructed, "
    "following the specified response format without additional commentary."
)


def parse_numeric(text: str) -> float | None:
    if text is None:
        return None
    t = text.strip()
    m = re.search(r"(?<![\d.])(-?\d+(?:\.\d+)?)(?![\d])", t)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def wasserstein_1d(a: np.ndarray, b: np.ndarray) -> float:
    a = np.sort(a.astype(float))
    b = np.sort(b.astype(float))
    n = 256
    qa = np.quantile(a, np.linspace(0, 1, n))
    qb = np.quantile(b, np.linspace(0, 1, n))
    return float(np.mean(np.abs(qa - qb)))


def cell_key(rec: dict[str, Any]) -> tuple[str, str, str]:
    return (rec["study_id"], str(rec["condition_num"]), str(rec["task_num"]))


def sample_id(row: dict[str, Any]) -> str:
    """Stable per-row id. Must match colab_socrates_wass.py exactly."""
    return (
        f"{row['study_id']}|{row['sample_id']}|{row['condition_num']}"
        f"|{row['task_num']}|{row['participant']}"
    )


def aggregate(preds: list[dict[str, Any]]) -> dict[str, Any]:
    """Cell -> study -> overall Wasserstein.

    Cells are visited in sorted key order so that a merge of N shard files
    scores identically regardless of which shard produced which row.
    """
    by_cell: dict[tuple, list] = defaultdict(list)
    for p in preds:
        by_cell[cell_key(p)].append(p)

    study_scores: dict[str, list[float]] = defaultdict(list)
    cell_rows: list[dict[str, Any]] = []
    skipped: dict[str, int] = defaultdict(int)

    for key in sorted(by_cell):
        items = by_cell[key]
        humans, models = [], []
        for it in items:
            try:
                h = float(it["human"])
            except Exception:
                skipped["human_unparseable"] += 1
                continue
            if it["pred"] is None:
                skipped["pred_unparseable"] += 1
                continue
            humans.append(h)
            models.append(float(it["pred"]))
        if len(humans) < 2 or len(models) < 2:
            skipped["cell_too_small"] += 1
            continue
        h = np.array(humans, dtype=float)
        m = np.array(models, dtype=float)
        rmin, rmax = float(h.min()), float(h.max())
        if rmax <= rmin:
            skipped["cell_degenerate_range"] += 1
            continue
        h_s = (h - rmin) / (rmax - rmin)
        m_s = (m - rmin) / (rmax - rmin)
        m_s = np.clip(m_s, 0.0, 1.0)
        w = wasserstein_1d(h_s, m_s)
        study_scores[key[0]].append(w)
        cell_rows.append(
            {
                "study_id": key[0],
                "condition": key[1],
                "task": key[2],
                "W": w,
                "n": len(h),
            }
        )

    per_study = {s: float(np.mean(v)) for s, v in sorted(study_scores.items()) if v}
    overall = float(np.mean(list(per_study.values()))) if per_study else None
    return {
        "per_study": per_study,
        "wasserstein_mean": overall,
        "cell_rows": cell_rows,
        "n_studies": len(per_study),
        "n_cells": len(cell_rows),
        "skipped": dict(skipped),
    }


def shard_cells(
    cell_sizes: dict[tuple, int], num_shards: int
) -> list[list[tuple]]:
    """Split cells across shards, balancing row counts (greedy longest-first).

    Cells are kept whole so a shard's output is self-contained, and the
    assignment is a pure function of the cell sizes — every worker computes the
    same partition without coordinating.
    """
    loads = [0] * num_shards
    buckets: list[list[tuple]] = [[] for _ in range(num_shards)]
    for key in sorted(cell_sizes, key=lambda k: (-cell_sizes[k], k)):
        i = min(range(num_shards), key=lambda j: (loads[j], j))
        buckets[i].append(key)
        loads[i] += cell_sizes[key]
    return buckets
