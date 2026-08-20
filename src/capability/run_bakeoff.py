"""Capability bakeoff runner — successive-halving plan."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from capability import BAKEOFF_MODEL, OUT_DIR
from capability.browser_use_runner import run_browser_use
from capability.native_cu import run_native_cu
from capability.tasks import BAKEOFF5_INDICES, SMOKE_INDICES, TASK_INDICES, load_tasks


RUNNERS = {
    "native_cu": run_native_cu,
    "browser_use": run_browser_use,
}


def _save_manifest(name: str, runs: list[dict]) -> Path:
    path = OUT_DIR / f"{name}.json"
    summary = {
        "n": len(runs),
        "successes": sum(1 for r in runs if r.get("success")),
        "by_status": dict(Counter(r.get("status") for r in runs)),
        "by_harness": {},
        "total_cost_usd": round(sum(float(r.get("estimated_cost_usd") or 0) for r in runs), 4),
        "runs": runs,
    }
    for h in sorted({r.get("harness") for r in runs}):
        subset = [r for r in runs if r.get("harness") == h]
        summary["by_harness"][h] = {
            "n": len(subset),
            "success": sum(1 for r in subset if r.get("success")),
            "avg_actions": round(
                sum(r.get("num_actions") or 0 for r in subset) / max(1, len(subset)), 2
            ),
            "cost_usd": round(sum(float(r.get("estimated_cost_usd") or 0) for r in subset), 4),
            "failures": dict(Counter(r.get("failure_category") for r in subset if not r.get("success"))),
        }
    path.write_text(json.dumps(summary, indent=2, default=str))
    print(json.dumps({k: summary[k] for k in ("n", "successes", "by_status", "by_harness", "total_cost_usd")}, indent=2))
    return path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["smoke", "bakeoff5", "full10", "one"], required=True)
    ap.add_argument("--harness", choices=["native_cu", "browser_use", "both"], default="both")
    ap.add_argument("--model", default=BAKEOFF_MODEL)
    ap.add_argument("--eval-index", type=int, default=None)
    args = ap.parse_args()

    if args.stage == "smoke":
        indices = SMOKE_INDICES
    elif args.stage == "bakeoff5":
        indices = BAKEOFF5_INDICES
    elif args.stage == "full10":
        indices = TASK_INDICES
    else:
        if args.eval_index is None:
            raise SystemExit("--eval-index required for --stage one")
        indices = [args.eval_index]

    tasks = load_tasks(indices)
    harnesses = (
        ["native_cu", "browser_use"] if args.harness == "both" else [args.harness]
    )

    runs = []
    for task in tasks:
        for h in harnesses:
            print(f"\n=== {h} | {task['website']} | {task['task'][:70]}")
            try:
                result = RUNNERS[h](task, model=args.model)
            except Exception as exc:  # noqa: BLE001
                result = {
                    "run_id": f"err_{task['eval_index']}",
                    "task_id": task["task_id"],
                    "eval_index": task["eval_index"],
                    "task": task["task"],
                    "website": task["website"],
                    "model": args.model,
                    "harness": h,
                    "success": False,
                    "status": "FAILURE",
                    "failure_category": "HARNESS",
                    "stop_reason": f"exception:{exc}"[:400],
                    "num_actions": 0,
                    "actions": [],
                    "estimated_cost_usd": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "final_url": "",
                }
            runs.append(result)
            print(
                f" -> {result.get('status')} success={result.get('success')} "
                f"actions={result.get('num_actions')} cost=${result.get('estimated_cost_usd', 0):.3f} "
                f"stop={result.get('stop_reason')} cat={result.get('failure_category')}"
            )
            print(f"    judge: {result.get('judge_reason')}")

    _save_manifest(f"{args.stage}_{args.harness}", runs)


if __name__ == "__main__":
    main()
