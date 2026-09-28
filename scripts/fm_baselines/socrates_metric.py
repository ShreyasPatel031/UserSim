#!/usr/bin/env python3
"""Socrates Wasserstein metric for SocSci210 evaluation.

Metric (paper): for each (condition, outcome) cell, standardize responses to
[0,1] with human rmin/rmax, compute Wasserstein-1 between human and model
response arrays, average over cells in a study, then average over studies.
"""
from __future__ import annotations

from collections import defaultdict

import numpy as np


def wasserstein_1d(a: np.ndarray, b: np.ndarray) -> float:
    """Pure numpy 1D Wasserstein (Earth Mover) for 1D samples."""
    a = np.sort(a.astype(float))
    b = np.sort(b.astype(float))
    n = 256
    qa = np.quantile(a, np.linspace(0, 1, n))
    qb = np.quantile(b, np.linspace(0, 1, n))
    return float(np.mean(np.abs(qa - qb)))


def score(preds: list[dict]) -> dict:
    """Compute Socrates Wasserstein metric from prediction records.
    
    Args:
        preds: List of dicts with keys: study_id, condition_num, task_num, human, pred
        
    Returns:
        Dict with wasserstein_mean, uniform_control, per_study scores
    """
    by_cell: dict[tuple, list] = defaultdict(list)
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
        key = (p["study_id"], str(p["condition_num"]), str(p["task_num"]))
        by_cell[key].append((h, m))

    study_scores: dict[str, list[float]] = defaultdict(list)
    study_uniform: dict[str, list[float]] = defaultdict(list)
    
    for key, items in by_cell.items():
        if len(items) < 2:
            continue
        humans = np.array([h for h, _ in items], dtype=float)
        models = np.array([m for _, m in items], dtype=float)
        
        rmin, rmax = float(humans.min()), float(humans.max())
        if rmax <= rmin:
            continue
            
        h_s = (humans - rmin) / (rmax - rmin)
        m_s = (models - rmin) / (rmax - rmin)
        m_s = np.clip(m_s, 0.0, 1.0)
        
        w = wasserstein_1d(h_s, m_s)
        study_scores[key[0]].append(w)
        
        uniform = np.random.uniform(0, 1, size=len(models))
        w_uniform = wasserstein_1d(h_s, uniform)
        study_uniform[key[0]].append(w_uniform)

    per_study = {s: float(np.mean(v)) for s, v in study_scores.items() if v}
    per_uniform = {s: float(np.mean(v)) for s, v in study_uniform.items() if v}
    
    overall = float(np.mean(list(per_study.values()))) if per_study else None
    uniform_control = float(np.mean(list(per_uniform.values()))) if per_uniform else None
    
    return {
        "wasserstein_mean": overall,
        "uniform_control": uniform_control,
        "per_study": per_study,
    }
