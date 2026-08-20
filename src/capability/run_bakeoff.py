"""Capability bakeoff runner — successive-halving plan."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from capability import BAKEOFF_MODEL, OUT_DIR, location_for
from capability.browser_use_runner import run_browser_use
from capability.native_cu import run_native_cu
from capability.tasks import BAKEOFF5_INDICES, SMOKE_INDICES, TASK_INDICES, load_tasks


RUNNERS = {
    "native_cu": run_native_cu,
    "browser_use": run_browser_use,
}


def _model_slug(model: str) -> str:
    return model.replace(".", "").replace("/", "-")


def _save_manifest(name: str, runs: list[dict], *, model: str, stage: str, harness: str) -> Path:
    path = OUT_DIR / f"{name}.json"
    eligible = [r for r in runs if r.get("status") != "BLOCKED"]
    successes_eligible = sum(1 for r in eligible if r.get("success"))
    summary = {
        "stage": stage,
        "harness": harness if harness != "browser_use" else "browser_use_oss",
        "model": model,
        "location": location_for(model),
        "n": len(runs),
        "n_total": len(runs),
        "n_eligible": len(eligible),
        "successes": sum(1 for r in runs if r.get("success")),
        "successes_eligible": successes_eligible,
        "success_rate_eligible": round(successes_eligible / max(1, len(eligible)), 4),
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
    print(
        json.dumps(
            {
                k: summary[k]
                for k in (
                    "model",
                    "n",
                    "n_eligible",
                    "successes",
                    "successes_eligible",
                    "success_rate_eligible",
                    "by_status",
                    "total_cost_usd",
                )
            },
            indent=2,
        )
    )
    return path


def _run_one(h: str, task: dict, model: str) -> dict:
    print(f"START {h} | {task['website']} | idx={task['eval_index']}", flush=True)
    try:
        result = RUNNERS[h](task, model=model, location=location_for(model))
    except TypeError:
        # native_cu may not take location=
        try:
            result = RUNNERS[h](task, model=model)
        except Exception as exc:  # noqa: BLE001
            result = {
                "run_id": f"err_{task['eval_index']}",
                "task_id": task["task_id"],
                "eval_index": task["eval_index"],
                "task": task["task"],
                "website": task["website"],
                "model": model,
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
    except Exception as exc:  # noqa: BLE001
        result = {
            "run_id": f"err_{task['eval_index']}",
            "task_id": task["task_id"],
            "eval_index": task["eval_index"],
            "task": task["task"],
            "website": task["website"],
            "model": model,
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
    print(
        f"DONE  {h} | {task['website']} | {result.get('status')} "
        f"success={result.get('success')} actions={result.get('num_actions')} "
        f"cost=${result.get('estimated_cost_usd', 0):.3f}",
        flush=True,
    )
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["smoke", "bakeoff5", "full10", "one"], required=True)
    ap.add_argument("--harness", choices=["native_cu", "browser_use", "both"], default="both")
    ap.add_argument("--model", default=BAKEOFF_MODEL)
    ap.add_argument("--eval-index", type=int, default=None)
    ap.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Parallel task workers (ThreadPool). Use 10 for full parallel.",
    )
    ap.add_argument(
        "--tag",
        default=None,
        help="Optional suffix for output filename (default: model slug).",
    )
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

    jobs = [(h, task) for task in tasks for h in harnesses]
    tag = args.tag or _model_slug(args.model)
    # Keep frozen 3.6 full10 filename stable when model is the freeze default
    if args.model == BAKEOFF_MODEL and args.harness != "both" and args.workers <= 1:
        out_name = f"{args.stage}_{args.harness}"
    else:
        out_name = f"{args.stage}_{args.harness}_{tag}"

    runs: list[dict] = []
    workers = max(1, min(args.workers, len(jobs)))
    print(
        f"Running {len(jobs)} jobs with {workers} workers | model={args.model} "
        f"location={location_for(args.model)} -> {out_name}.json",
        flush=True,
    )

    if workers == 1:
        for h, task in jobs:
            runs.append(_run_one(h, task, args.model))
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = {
                pool.submit(_run_one, h, task, args.model): (h, task["eval_index"])
                for h, task in jobs
            }
            for fut in as_completed(futs):
                runs.append(fut.result())

    # Stable order by eval_index then harness
    harness_order = {h: i for i, h in enumerate(harnesses)}
    runs.sort(key=lambda r: (r.get("eval_index", 0), harness_order.get(r.get("harness"), 0)))
    _save_manifest(out_name, runs, model=args.model, stage=args.stage, harness=args.harness)


if __name__ == "__main__":
    main()
