#!/usr/bin/env python3
"""Single source of truth for the Socrates/SocSci210 Wasserstein metric.

The paper scores each (study, condition, task) cell by standardizing responses
to [0,1] using the *human* min/max, clipping model predictions into that range,
then taking Wasserstein-1 between the human and model distributions. Cell scores
are averaged within a study and studies are averaged unweighted.

The standardization is not cosmetic. Without it a raw-scale W is incomparable to
the paper's 0.151, and an unclipped out-of-range generation (a base model
answering "1997" on a 1-7 scale) moves the mean by an unbounded amount. This
module exists because that scorer was duplicated and the copies diverged; every
caller must import from here rather than reimplementing.
"""
from __future__ import annotations

import re
from collections import defaultdict

import numpy as np

# Paper reference points on the standardized [0,1] scale.
PAPER_TARGET = 0.151
PAPER_EMPIRICAL_BEST = 0.125

_NUM = re.compile(r"[-+]?\d*\.?\d+")
_BARE_NUM = re.compile(r"\s*[-+]?\d+(?:\.\d+)?\s*\Z")


def parse_numeric(text: str) -> float | None:
    """First number in the generation, or None when there isn't one."""
    if text is None:
        return None
    m = _NUM.search(str(text).replace(",", ""))
    if not m:
        return None
    try:
        v = float(m.group(0))
    except ValueError:
        return None
    if not np.isfinite(v):
        return None
    return v


def is_bare_numeric(text: str) -> bool:
    """True when the generation is only a number, as the prompt demands."""
    return bool(text is not None and _BARE_NUM.match(str(text)))


def wasserstein_1d(a: np.ndarray, b: np.ndarray) -> float:
    """Wasserstein-1 between two empirical 1-D samples via quantile matching."""
    a = np.sort(np.asarray(a, dtype=float))
    b = np.sort(np.asarray(b, dtype=float))
    n = max(len(a), len(b))
    if len(a) != n:
        a = np.interp(np.linspace(0, 1, n), np.linspace(0, 1, len(a)), a)
    if len(b) != n:
        b = np.interp(np.linspace(0, 1, n), np.linspace(0, 1, len(b)), b)
    return float(np.mean(np.abs(a - b)))


def cell_key(row: dict) -> tuple:
    return (row["study_id"], str(row["condition_num"]), str(row["task_num"]))


def score(preds: list[dict], rng_seed: int = 0) -> dict:
    """Paper-standardized Socrates score plus the diagnostics a gate needs.

    `preds` rows need `study_id`, `condition_num`, `task_num`, `human`, `pred`,
    and optionally `pred_raw` for parse diagnostics.

    Alongside the score this returns a `uniform_control`: the same metric with
    model predictions replaced by uniform draws on the human range. It is the
    floor any real predictor must beat, and it is what makes a smoke gate
    meaningful -- an absolute W threshold can't tell a working model from a
    broken one, because W's scale depends on the response distributions.
    """
    rng = np.random.default_rng(rng_seed)
    cells: dict[tuple, list] = defaultdict(list)
    for p in preds:
        cells[cell_key(p)].append(p)

    per_study: dict[str, list[float]] = defaultdict(list)
    per_study_ctl: dict[str, list[float]] = defaultdict(list)
    cell_rows: list[dict] = []
    skipped = {"too_few": 0, "degenerate_human_range": 0}

    for key, items in cells.items():
        humans, models = [], []
        for it in items:
            if it.get("pred") is None:
                continue
            try:
                h = float(it["human"])
                m = float(it["pred"])
            except (TypeError, ValueError):
                continue
            if not (np.isfinite(h) and np.isfinite(m)):
                continue
            humans.append(h)
            models.append(m)
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
        m_s = np.clip((m - rmin) / (rmax - rmin), 0.0, 1.0)
        w = wasserstein_1d(h_s, m_s)
        w_ctl = wasserstein_1d(h_s, rng.uniform(0.0, 1.0, size=len(h_s)))

        per_study[key[0]].append(w)
        per_study_ctl[key[0]].append(w_ctl)
        cell_rows.append(
            {
                "study_id": key[0],
                "condition_num": key[1],
                "task_num": key[2],
                "W": w,
                "n": len(h),
                "human_range": [rmin, rmax],
                "frac_model_out_of_range": float(
                    np.mean((m < rmin) | (m > rmax))
                ),
            }
        )

    study_means = {s: float(np.mean(v)) for s, v in per_study.items() if v}
    ctl_means = {s: float(np.mean(v)) for s, v in per_study_ctl.items() if v}
    overall = float(np.mean(list(study_means.values()))) if study_means else None
    overall_ctl = float(np.mean(list(ctl_means.values()))) if ctl_means else None

    return {
        "n_studies": len(study_means),
        "n_cells": len(cell_rows),
        "n_preds": len(preds),
        "wasserstein_mean": overall,
        "uniform_control": overall_ctl,
        "paper_target": PAPER_TARGET,
        "paper_empirical_best": PAPER_EMPIRICAL_BEST,
        "per_study": study_means,
        "skipped": skipped,
        "parse": parse_diagnostics(preds),
        "cell_rows": cell_rows,
    }


def parse_diagnostics(preds: list[dict]) -> dict:
    """How well the generations obeyed "a single number only"."""
    n = len(preds)
    if not n:
        return {"n": 0}
    unparsed = sum(1 for p in preds if p.get("pred") is None)
    raws = [p.get("pred_raw") for p in preds if p.get("pred_raw") is not None]
    bare = sum(1 for r in raws if is_bare_numeric(r))
    return {
        "n": n,
        "unparsed": unparsed,
        "parse_rate": (n - unparsed) / n,
        "n_with_raw": len(raws),
        "bare_numeric_rate": (bare / len(raws)) if raws else None,
    }
