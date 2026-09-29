#!/usr/bin/env python3
"""Socrates/SocSci210 scoring metric (Wasserstein-1 on human-range-standardized values).

Paper metric: for each (condition, outcome) cell, standardize responses to [0,1]
using human rmin/rmax, compute Wasserstein-1 between human and model response
arrays, average over cells in a study, then average over studies.

NO CLIPPING: model predictions that fall outside [0,1] after standardization
contribute their full distance (they are not clamped back onto [0,1]).
"""
from __future__ import annotations

import re
from collections import defaultdict

import numpy as np


def parse_numeric(text: str | None) -> float | None:
    """Parse text only if it is a bare number (after stripping whitespace).

    Returns None if the text contains anything other than an optional sign,
    digits, and an optional decimal point. Does NOT extract numbers from prose.
    """
    if text is None:
        return None
    t = str(text).strip()
    if not re.fullmatch(r"[-+]?\d+(?:\.\d+)?", t):
        return None
    try:
        return float(t)
    except ValueError:
        return None


def wasserstein_1d(a: np.ndarray, b: np.ndarray) -> float:
    """1D Wasserstein (Earth Mover) distance via quantile matching."""
    a = np.sort(a.astype(float))
    b = np.sort(b.astype(float))
    n = 256
    qa = np.quantile(a, np.linspace(0, 1, n))
    qb = np.quantile(b, np.linspace(0, 1, n))
    return float(np.mean(np.abs(qa - qb)))


def _effective_pred(row: dict) -> float | None:
    """Return the effective prediction, or None if pred_raw is not a bare number.

    If pred_raw is present and is not a bare number (after stripping whitespace),
    return None so the row contributes no number to accuracy or Wasserstein.
    If pred_raw is absent, return the stored pred value.
    """
    pred_raw = row.get("pred_raw")
    if pred_raw is not None:
        raw = str(pred_raw).strip()
        if not re.fullmatch(r"[-+]?\d+(?:\.\d+)?", raw):
            return None
    return row.get("pred")


def score(preds: list[dict]) -> dict:
    """Compute Socrates paper Wasserstein metric (no clipping).

    Args:
        preds: List of dicts with keys: study_id, condition_num, task_num,
               human (ground truth), pred (model prediction or None),
               optionally pred_raw (raw text output).

    Returns:
        Dict with wasserstein_mean, n_studies, n_cells, n_preds, uniform_control,
        paper_target, parse stats, per_study scores, and skipped counts.
    """
    cells: dict[tuple, list] = defaultdict(list)
    parse_stats = {"n": 0, "unparsed": 0, "n_with_raw": 0, "bare_numeric": 0}

    for p in preds:
        key = (p["study_id"], str(p["condition_num"]), str(p["task_num"]))
        cells[key].append(p)
        parse_stats["n"] += 1
        eff_pred = _effective_pred(p)
        if eff_pred is None:
            parse_stats["unparsed"] += 1
        if p.get("pred_raw") is not None:
            parse_stats["n_with_raw"] += 1
            raw = str(p["pred_raw"]).strip()
            if re.fullmatch(r"[-+]?\d+(?:\.\d+)?", raw):
                parse_stats["bare_numeric"] += 1

    per_study: dict[str, list[float]] = defaultdict(list)
    uniform_scores: list[float] = []
    skipped = {"too_few": 0, "degenerate_human_range": 0}

    for key, items in cells.items():
        humans, models = [], []
        for it in items:
            try:
                h = float(it["human"])
            except (TypeError, ValueError):
                continue
            eff_pred = _effective_pred(it)
            if eff_pred is None:
                continue
            humans.append(h)
            models.append(float(eff_pred))

        if len(humans) < 2:
            skipped["too_few"] += 1
            continue

        h = np.array(humans, dtype=float)
        m = np.array(models, dtype=float)
        rmin, rmax = float(h.min()), float(h.max())

        if rmax <= rmin:
            skipped["degenerate_human_range"] += 1
            continue

        h_s = (h - rmin) / (rmax - rmin)
        m_s = (m - rmin) / (rmax - rmin)

        w = wasserstein_1d(h_s, m_s)
        per_study[key[0]].append(w)

        u = np.random.default_rng(42).uniform(0, 1, len(h))
        uniform_scores.append(wasserstein_1d(h_s, u))

    study_means = {s: float(np.mean(ws)) for s, ws in per_study.items() if ws}
    overall = float(np.mean(list(study_means.values()))) if study_means else None
    uniform_control = float(np.mean(uniform_scores)) if uniform_scores else None

    return {
        "wasserstein_mean": overall,
        "n_studies": len(study_means),
        "n_cells": sum(len(ws) for ws in per_study.values()),
        "n_preds": parse_stats["n"],
        "uniform_control": uniform_control,
        "paper_target": 0.151,
        "parse": {
            "n": parse_stats["n"],
            "unparsed": parse_stats["unparsed"],
            "parse_rate": (
                (parse_stats["n"] - parse_stats["unparsed"]) / parse_stats["n"]
                if parse_stats["n"] > 0
                else 0.0
            ),
            "n_with_raw": parse_stats["n_with_raw"],
            "bare_numeric_rate": (
                parse_stats["bare_numeric"] / parse_stats["n_with_raw"]
                if parse_stats["n_with_raw"] > 0
                else 0.0
            ),
        },
        "per_study": study_means,
        "skipped": skipped,
    }
