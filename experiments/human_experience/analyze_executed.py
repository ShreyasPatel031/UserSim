"""Rating errors on the cases whose execution actually ran, plus context-only cells on all 12.

Evaluator-only (reads pack/evaluator_only). Expected-score absolute error per case, averaged per cell, with
per-case rows so the denominators are visible. Writes results/executed_cases.csv.
"""

from __future__ import annotations

import csv
import glob
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
TARGETS = ["ease_of_use_rating", "functionality_rating", "overall_rating"]
CELLS = ["B0", "B1", "B2", "B3", "B4", "B5"]
NO_RUN = {"environment_failure", "blocked_login_wall", "blocked_captcha", "blocked_site_error", "blocked_paid_plan"}


def main() -> None:
    preds = {(r["case_id"], r["condition"]): r for r in map(json.loads, open(HERE / "results/predictions.jsonl"))}
    gold = {g["case_id"]: g for g in map(json.loads, open(HERE / "pack/evaluator_only/outcomes.jsonl"))}
    runs = {}
    for f in glob.glob(str(HERE / "results/execution/*.json")):
        r = json.load(open(f))
        runs[(r["case_id"], r["context"], r["engine"])] = r["status"]
    tasks = [json.loads(l) for l in open(HERE / "pack/inputs/e2e_tasks.jsonl")]
    executed = sorted(t["case_id"] for t in tasks
                      if all(runs.get((t["case_id"], x, e), "environment_failure") not in NO_RUN
                             for x in ("base", "full") for e in ("generic", "usersim")))

    def err(c: str, cell: str, t: str) -> float | None:
        p = preds.get((c, cell))
        y = gold[c]["ratings"][t]
        if not p or not p["ratings"].get(t) or y is None:
            return None
        return abs(sum((i + 1) * v for i, v in enumerate(p["ratings"][t]["probabilities"])) - y)

    rows = []
    for c in executed:
        for cell in CELLS:
            rows.append({"case_id": c, "product": gold[c]["product"], "cell": cell,
                         **{t: round(err(c, cell, t), 3) for t in TARGETS},
                         **{f"run_{x}_{e}": runs.get((c, x, e), "") for x in ("base", "full") for e in ("generic", "usersim")}})
    with open(HERE / "results/executed_cases.csv", "w") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    print(f"executed cases: {len(executed)} {executed}")
    print(f"{'cell':4} " + " ".join(f"{t.split('_')[0]:>8}" for t in TARGETS))
    for cell in CELLS:
        means = [sum(r[t] for r in rows if r["cell"] == cell) / len(executed) for t in TARGETS]
        print(f"{cell:4} " + " ".join(f"{m:8.2f}" for m in means))
    all12 = [t["case_id"] for t in tasks]
    print("context-only cells on all 12 cases:")
    for cell in ["B0", "B1"]:
        means = [sum(err(c, cell, t) for c in all12) / len(all12) for t in TARGETS]
        print(f"{cell:4} " + " ".join(f"{m:8.2f}" for m in means))


if __name__ == "__main__":
    main()
