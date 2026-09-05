"""Supervised recalibration of logged SimBench distributions.

Suresh et al. (ACL 2026) report that fitting a monotone map from predicted
per-option probability to human probability beats spending the same gold
distributions as in-context examples. This runs that comparison on our logged
arms, with cross-validation by test case so no case is scored by a calibrator
fit on itself.

Three calibrators, all fit on train folds only:
  shrink    p' = (1-lam) p + lam/K              (1 global param)
  power     p' = p^beta / sum p^beta            (1 global param)
  isotonic  per-dataset isotonic regression on (p_pred, p_human) pairs

Usage:
  PYTHONPATH=src python -m human_sim.simbench_calibrate
"""

from __future__ import annotations

import json
from collections import defaultdict

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression

from human_sim.simbench_ablate import (
    OUT_DIR,
    dataset_norms,
    load_split,
    stratified_sample,
    tvd,
)

TAG = "gemini-2.5-flash_p25g100s7"
ARMS = [
    "base",
    "no_persona",
    "swap_persona",
    "cot",
    "plural",
    "fewshot",
    "plural_fewshot",
    "ensemble",
]
FOLDS = 5


def _norm(dist: dict) -> dict:
    total = sum(dist.values()) or 1.0
    return {k: v / total for k, v in dist.items()}


def _renorm(values: np.ndarray) -> np.ndarray:
    values = np.clip(values, 1e-9, None)
    return values / values.sum()


def load_cases(arm: str) -> list[dict]:
    path = OUT_DIR / f"{arm}_{TAG}.json"
    if not path.exists():
        return []
    result = json.loads(path.read_text())
    cases = []
    for row in result["rows"]:
        if not row.get("ok"):
            continue
        keys = list(row["human_answer"].keys())
        human = _norm(row["human_answer"])
        pred = _norm(row["llm_answer"])
        cases.append(
            {
                "i": row["i"],
                "dataset": row["dataset_name"],
                "split": row.get("split"),
                "keys": keys,
                "human": np.array([human[k] for k in keys]),
                "pred": np.array([pred.get(k, 0.0) for k in keys]),
            }
        )
    return cases


def score(cases: list[dict], preds: list[np.ndarray], norms: dict) -> float:
    scores = []
    for case, pred in zip(cases, preds):
        norm = norms.get(case["dataset"])
        if not norm:
            continue
        human = {k: v for k, v in zip(case["keys"], case["human"])}
        model = {k: v for k, v in zip(case["keys"], pred)}
        scores.append(100 * (1 - tvd(human, model) / norm))
    return float(np.mean(scores)) if scores else float("nan")


def fit_shrink(train: list[dict]) -> float:
    best, best_tv = 0.0, 1e9
    for lam in np.arange(0.0, 0.55, 0.025):
        total = 0.0
        for case in train:
            k = len(case["pred"])
            adjusted = (1 - lam) * case["pred"] + lam / k
            total += 0.5 * np.abs(case["human"] - adjusted).sum()
        if total < best_tv:
            best, best_tv = float(lam), total
    return best


def apply_shrink(case: dict, lam: float) -> np.ndarray:
    k = len(case["pred"])
    return _renorm((1 - lam) * case["pred"] + lam / k)


def fit_power(train: list[dict]) -> float:
    best, best_tv = 1.0, 1e9
    for beta in np.arange(0.2, 1.85, 0.05):
        total = 0.0
        for case in train:
            adjusted = _renorm(np.power(np.clip(case["pred"], 1e-9, None), beta))
            total += 0.5 * np.abs(case["human"] - adjusted).sum()
        if total < best_tv:
            best, best_tv = float(beta), total
    return best


def apply_power(case: dict, beta: float) -> np.ndarray:
    return _renorm(np.power(np.clip(case["pred"], 1e-9, None), beta))


def fit_isotonic(train: list[dict]) -> dict[str, IsotonicRegression]:
    by_dataset = defaultdict(lambda: ([], []))
    for case in train:
        xs, ys = by_dataset[case["dataset"]]
        xs.extend(case["pred"].tolist())
        ys.extend(case["human"].tolist())
    models = {}
    pooled_x: list[float] = []
    pooled_y: list[float] = []
    for dataset, (xs, ys) in by_dataset.items():
        pooled_x.extend(xs)
        pooled_y.extend(ys)
        if len(xs) < 40:
            continue
        model = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
        model.fit(np.array(xs), np.array(ys))
        models[dataset] = model
    fallback = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
    fallback.fit(np.array(pooled_x), np.array(pooled_y))
    models["__pooled__"] = fallback
    return models


def apply_isotonic(case: dict, models: dict) -> np.ndarray:
    model = models.get(case["dataset"], models["__pooled__"])
    return _renorm(model.predict(case["pred"]))


def cross_validate(cases: list[dict], norms: dict, seed: int = 0) -> dict:
    rng = np.random.default_rng(seed)
    order = rng.permutation(len(cases))
    folds = np.array_split(order, FOLDS)

    preds = {
        "raw": [None] * len(cases),
        "shrink": [None] * len(cases),
        "power": [None] * len(cases),
        "isotonic": [None] * len(cases),
    }
    params = defaultdict(list)

    for fold in folds:
        test_idx = set(int(i) for i in fold)
        train = [c for j, c in enumerate(cases) if j not in test_idx]
        lam = fit_shrink(train)
        beta = fit_power(train)
        iso = fit_isotonic(train)
        params["shrink_lambda"].append(lam)
        params["power_beta"].append(beta)
        for j in fold:
            case = cases[int(j)]
            preds["raw"][int(j)] = _renorm(case["pred"])
            preds["shrink"][int(j)] = apply_shrink(case, lam)
            preds["power"][int(j)] = apply_power(case, beta)
            preds["isotonic"][int(j)] = apply_isotonic(case, iso)

    out = {
        method: round(score(cases, values, norms), 2)
        for method, values in preds.items()
    }
    out["shrink_lambda_mean"] = round(float(np.mean(params["shrink_lambda"])), 3)
    out["power_beta_mean"] = round(float(np.mean(params["power_beta"])), 3)
    out["n"] = len(cases)
    return out


def main() -> None:
    pop = load_split("Pop")
    grouped = load_split("Grouped")
    pop_eval, _ = stratified_sample(pop, 25, 7, reserve=3)
    grp_eval, _ = stratified_sample(grouped, 100, 7, reserve=3)
    sample = pd.concat([pop_eval, grp_eval]).reset_index(drop=True)
    norms = dataset_norms(sample)

    print(
        f"{'arm':<16}{'raw':>8}{'shrink':>9}{'power':>8}{'isotonic':>10}"
        f"{'best Δ':>9}{'λ':>7}{'β':>7}"
    )
    print("-" * 74)
    report = []
    for arm in ARMS:
        cases = load_cases(arm)
        if not cases:
            continue
        result = cross_validate(cases, norms)
        best_method = max(
            ("shrink", "power", "isotonic"), key=lambda m: result[m]
        )
        delta = result[best_method] - result["raw"]
        row = {"arm": arm, "best_method": best_method, "best_delta": round(delta, 2)}
        row.update(result)
        report.append(row)
        print(
            f"{arm:<16}{result['raw']:>8.2f}{result['shrink']:>9.2f}"
            f"{result['power']:>8.2f}{result['isotonic']:>10.2f}"
            f"{delta:>+9.2f}{result['shrink_lambda_mean']:>7.2f}"
            f"{result['power_beta_mean']:>7.2f}"
        )

    (OUT_DIR / "calibration_report.json").write_text(json.dumps(report, indent=2))
    print(
        "\nAll calibrators are cross-validated over 5 folds by test case; "
        "no case is scored by a map fit on itself."
    )
    print(f"wrote {OUT_DIR / 'calibration_report.json'}")


if __name__ == "__main__":
    main()
