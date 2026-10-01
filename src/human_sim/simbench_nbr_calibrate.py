"""Variant C: calibrate retr6 outputs, binned by the retrieved neighbours' entropy.

The model's own predicted entropy does not say which way to correct a prediction
(logged result: a tempering rule keyed on it scored the same as raw). The retrieved
neighbours' real entropy is an outside signal, known before the model answers.

Protocol (no tuning on eval):
  1. choose (feature, n_bins, transform) by repeated K-fold CV on the DEV set only;
  2. fit that config on all of DEV and apply it to the full EVAL set;
  3. as a robustness check, also report K-fold CV inside EVAL.

Usage:
  PYTHONPATH=src python -m human_sim.simbench_nbr_calibrate --model claude-haiku-4-5
"""

from __future__ import annotations

import argparse
import itertools
import json
import random

import numpy as np

from human_sim.simbench_ablate import (
    OUT_DIR,
    _demo_pool,
    _rank_by_similarity,
    _sorted_probs,
    DEV_GROUPED,
    DEV_POP,
    build_env,
    dataset_norms,
)

BETAS = [0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.15, 1.3, 1.5, 1.75, 2.0]
LAMBDAS = [0.0, 0.05, 0.1, 0.15, 0.2, 0.3, 0.4]
TRANSFORMS = {
    "power": ([b for b in BETAS], [0.0]),
    "shrink": ([1.0], LAMBDAS),
    "both": (BETAS, LAMBDAS),
}
FEATURES = ("h", "top1")
BINS = (1, 2, 3, 5)


def _norm(v: np.ndarray) -> np.ndarray:
    v = np.clip(v, 1e-9, None)
    return v / v.sum()


def _apply(pred: np.ndarray, beta: float, lam: float) -> np.ndarray:
    p = _norm(pred**beta)
    return (1 - lam) * p + lam / len(p)


def _score(case: dict, beta: float, lam: float) -> float:
    q = _apply(case["pred"], beta, lam)
    return 100 * (1 - 0.5 * np.abs(q - case["human"]).sum() / case["norm"])


def load_cases(arm: str, model: str, tag: str, sample, ctx, norms, k: int = 6) -> list[dict]:
    path = OUT_DIR / f"{arm}_{model}_{tag}.json"
    rows = {r["i"]: r for r in json.loads(path.read_text())["rows"] if r.get("ok")}
    cases = []
    for idx, row in sample.iterrows():
        r = rows.get(int(idx))
        if r is None:
            continue
        keys = list(row["human_answer"].keys())
        pred = np.array([r["llm_answer"][key] for key in keys], dtype=float)
        human = np.array([row["human_answer"][key] for key in keys], dtype=float)
        human = human / human.sum()
        nbrs = _rank_by_similarity(row, _demo_pool(row, ctx), ctx)[:k]
        cases.append(
            {
                "i": int(idx),
                "pred": pred,
                "human": human,
                "norm": norms[row["dataset_name"]],
                "h": float(np.mean([d["h"] for d in nbrs])) if nbrs else 0.5,
                "top1": float(np.mean([_sorted_probs(d["human_answer"])[0] for d in nbrs])) if nbrs else 0.5,
            }
        )
    return cases


def _fit_bin(cases: list[dict], transform: str) -> tuple[float, float]:
    betas, lams = TRANSFORMS[transform]
    best, best_s = (1.0, 0.0), -1e9
    for beta, lam in itertools.product(betas, lams):
        s = float(np.mean([_score(c, beta, lam) for c in cases]))
        if s > best_s:
            best, best_s = (beta, lam), s
    return best


def fit(cases: list[dict], feature: str, n_bins: int, transform: str) -> dict:
    vals = np.array([c[feature] for c in cases])
    edges = list(np.quantile(vals, np.linspace(0, 1, n_bins + 1)[1:-1])) if n_bins > 1 else []
    params = []
    for b in range(n_bins):
        members = [c for c in cases if _bin(c[feature], edges) == b] or cases
        params.append(_fit_bin(members, transform))
    return {"feature": feature, "edges": edges, "params": params}


def _bin(value: float, edges: list[float]) -> int:
    return sum(value >= e for e in edges)


def predict_score(model: dict, case: dict) -> float:
    beta, lam = model["params"][_bin(case[model["feature"]], model["edges"])]
    return _score(case, beta, lam)


def cv_score(cases: list[dict], feature: str, n_bins: int, transform: str, folds=5, repeats=3) -> float:
    scores = []
    for rep in range(repeats):
        idx = list(range(len(cases)))
        random.Random(rep).shuffle(idx)
        for f in range(folds):
            test = {idx[j] for j in range(f, len(idx), folds)}
            train = [cases[j] for j in idx if j not in test]
            model = fit(train, feature, n_bins, transform)
            scores += [predict_score(model, cases[j]) for j in test]
    return float(np.mean(scores))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="claude-haiku-4-5")
    ap.add_argument("--arm", default="retr6")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    dev_sample, dev_norms, dev_ctx = build_env(25, 100, args.seed, "dev")
    ev_sample, ev_norms, ev_ctx = build_env(25, 100, args.seed, "eval")
    dev = load_cases(args.arm, args.model, f"p25g100s{args.seed}dev{DEV_POP}x{DEV_GROUPED}", dev_sample, dev_ctx, dev_norms)
    ev = load_cases(args.arm, args.model, f"p25g100s{args.seed}", ev_sample, ev_ctx, ev_norms)
    print(f"dev cases={len(dev)} eval cases={len(ev)}")

    raw_dev = float(np.mean([_score(c, 1.0, 0.0) for c in dev]))
    raw_eval = float(np.mean([_score(c, 1.0, 0.0) for c in ev]))
    grid = []
    for feature, n_bins, transform in itertools.product(FEATURES, BINS, TRANSFORMS):
        if n_bins == 1 and feature != FEATURES[0]:
            continue  # one bin ignores the feature
        grid.append(
            {
                "feature": feature,
                "n_bins": n_bins,
                "transform": transform,
                "dev_cv_S": round(cv_score(dev, feature, n_bins, transform), 2),
            }
        )
    grid.sort(key=lambda g: -g["dev_cv_S"])
    for g in grid:
        print(g)
    best = grid[0]
    model = fit(dev, best["feature"], best["n_bins"], best["transform"])
    out = {
        "arm": args.arm,
        "model": args.model,
        "dev_raw_S": round(raw_dev, 2),
        "grid": grid,
        "best": best,
        "fitted": {"edges": [float(e) for e in model["edges"]], "params": model["params"]},
        "eval_raw_S": round(raw_eval, 2),
        "eval_calibrated_S_fit_on_dev": round(float(np.mean([predict_score(model, c) for c in ev])), 2),
        "eval_cv_S_inside_eval": round(
            cv_score(ev, best["feature"], best["n_bins"], best["transform"]), 2
        ),
        "eval_global_shrink_cv_S_inside_eval": round(cv_score(ev, "h", 1, "shrink"), 2),
    }
    print(json.dumps({k: v for k, v in out.items() if k != "grid"}, indent=1))
    (OUT_DIR / f"nbr_calibration_{args.model}.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
