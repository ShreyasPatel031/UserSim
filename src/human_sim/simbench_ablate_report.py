"""Paired report over cached SimBench ablation arms.

Compares every arm to `base` on the test cases both arms answered, with a
bootstrap CI on the paired delta, and sweeps post-hoc shrinkage toward uniform.

Usage:
  PYTHONPATH=src python -m human_sim.simbench_ablate_report
"""

from __future__ import annotations

import json
import random
from collections import defaultdict

import pandas as pd

from human_sim.simbench_ablate import (
    OUT_DIR,
    dataset_norms,
    load_split,
    stratified_sample,
    tvd,
)

TAG = "gemini-2.5-flash_p25g100s7"
ARM_ORDER = [
    "base",
    "no_persona",
    "swap_persona",
    "cot",
    "plural",
    "fewshot",
    "plural_fewshot",
    "ensemble",
]


def _norm(dist: dict) -> dict:
    total = sum(dist.values()) or 1.0
    return {k: v / total for k, v in dist.items()}


def per_case_scores(
    result: dict, norms: dict[str, float], shrink: float = 0.0
) -> dict[int, float]:
    out = {}
    for row in result["rows"]:
        if not row.get("ok"):
            continue
        norm = norms.get(row["dataset_name"])
        if not norm:
            continue
        pred = _norm(row["llm_answer"])
        if shrink:
            k = len(pred)
            pred = {key: (1 - shrink) * v + shrink / k for key, v in pred.items()}
        out[row["i"]] = 100 * (1 - tvd(_norm(row["human_answer"]), pred) / norm)
    return out


def bootstrap_ci(deltas: list[float], iterations: int = 4000, seed: int = 0):
    rng = random.Random(seed)
    n = len(deltas)
    means = []
    for _ in range(iterations):
        means.append(sum(deltas[rng.randrange(n)] for _ in range(n)) / n)
    means.sort()
    return means[int(0.025 * iterations)], means[int(0.975 * iterations)]


def main() -> None:
    pop = load_split("Pop")
    grouped = load_split("Grouped")
    pop_eval, _ = stratified_sample(pop, 25, 7, reserve=3)
    grp_eval, _ = stratified_sample(grouped, 100, 7, reserve=3)
    sample = pd.concat([pop_eval, grp_eval]).reset_index(drop=True)
    norms = dataset_norms(sample)
    split_of = {i: row["split"] for i, row in sample.iterrows()}

    results = {}
    for arm in ARM_ORDER:
        path = OUT_DIR / f"{arm}_{TAG}.json"
        if path.exists():
            results[arm] = json.loads(path.read_text())

    base_scores = per_case_scores(results["base"], norms)
    report = []

    print(f"{'arm':<15}{'S':>8}{'ΔS vs base':>13}{'95% CI':>18}{'n':>7}{'$':>8}")
    print("-" * 72)
    for arm, result in results.items():
        scores = per_case_scores(result, norms)
        shared = sorted(set(scores) & set(base_scores))
        deltas = [scores[i] - base_scores[i] for i in shared]
        mean_s = sum(scores.values()) / len(scores)
        mean_delta = sum(deltas) / len(deltas)
        low, high = bootstrap_ci(deltas) if arm != "base" else (0.0, 0.0)
        by_split = defaultdict(list)
        for i, value in scores.items():
            by_split[split_of.get(i, "?")].append(value)
        best_shrink, best_shrink_s = 0.0, mean_s
        for lam in [0.05 * i for i in range(11)]:
            swept = per_case_scores(result, norms, shrink=lam)
            value = sum(swept.values()) / len(swept)
            if value > best_shrink_s:
                best_shrink, best_shrink_s = lam, value
        row = {
            "arm": arm,
            "S": round(mean_s, 2),
            "delta_vs_base_paired": round(mean_delta, 2),
            "ci95": [round(low, 2), round(high, 2)],
            "n_scored": len(scores),
            "n_paired": len(shared),
            "cost_usd": result.get("estimated_cost_usd"),
            "fail": result.get("fail"),
            "S_by_split": {
                k: round(sum(v) / len(v), 2) for k, v in sorted(by_split.items())
            },
            "best_shrink_lambda": round(best_shrink, 2),
            "S_with_shrink": round(best_shrink_s, 2),
        }
        report.append(row)
        ci = "—" if arm == "base" else f"[{low:+.2f}, {high:+.2f}]"
        delta = "—" if arm == "base" else f"{mean_delta:+.2f}"
        print(
            f"{arm:<15}{mean_s:>8.2f}{delta:>13}{ci:>18}"
            f"{len(scores):>7}{result.get('estimated_cost_usd', 0):>8.2f}"
        )

    print("\nPost-hoc shrinkage toward uniform (free, no extra calls):")
    for row in report:
        print(
            f"  {row['arm']:<15} S {row['S']:>6.2f} -> {row['S_with_shrink']:>6.2f} "
            f"(lambda={row['best_shrink_lambda']:.2f})"
        )

    print("\nPop vs Grouped:")
    for row in report:
        print(f"  {row['arm']:<15} {row['S_by_split']}")

    (OUT_DIR / "paired_report.json").write_text(json.dumps(report, indent=2))
    print(f"\nwrote {OUT_DIR / 'paired_report.json'}")


if __name__ == "__main__":
    main()
