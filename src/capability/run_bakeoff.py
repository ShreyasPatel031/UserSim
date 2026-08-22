"""Capability bakeoff runner — successive-halving plan + full benchmark."""

from __future__ import annotations

import argparse
import json
import sys
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from capability import (
    ACTION_BUFFER,
    BAKEOFF_MODEL,
    MAX_ACTIONS,
    MAX_HUMAN_STEPS,
    OUT_DIR,
    location_for,
)
from capability.browser_use_runner import run_browser_use
from capability.native_cu import run_native_cu
from capability.tasks import (
    ALL_INDICES,
    BAKEOFF5_INDICES,
    GENUINE_FAIL_INDICES,
    HARD20_INDICES,
    SMOKE_INDICES,
    TASK_INDICES,
    load_tasks,
)


RUNNERS = {
    "native_cu": run_native_cu,
    "browser_use": run_browser_use,
}


def _model_slug(model: str) -> str:
    return model.replace(".", "").replace("/", "-")


def _err_result(task: dict, model: str, h: str, exc: Exception) -> dict:
    return {
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


def _save_manifest(name: str, runs: list[dict], *, model: str, stage: str, harness: str) -> Path:
    path = OUT_DIR / f"{name}.json"
    eligible = [r for r in runs if r.get("status") != "BLOCKED"]
    successes_eligible = sum(1 for r in eligible if r.get("success"))
    summary = {
        "stage": stage,
        "harness": harness if harness != "browser_use" else "browser_use_oss",
        "model": model,
        "location": location_for(model),
        "max_actions_budget": (runs[0].get("max_actions_budget") if runs else MAX_ACTIONS),
        "max_human_steps": MAX_HUMAN_STEPS,
        "action_buffer": ACTION_BUFFER,
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
                    "max_actions_budget",
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
        ),
        flush=True,
    )
    return path


def _run_one(h: str, task: dict, model: str, max_actions: int) -> dict:
    print(
        f"START {h} | {task['website']} | idx={task['eval_index']} | max_actions={max_actions}",
        flush=True,
    )
    try:
        result = RUNNERS[h](
            task, model=model, location=location_for(model), max_actions=max_actions
        )
    except TypeError:
        try:
            result = RUNNERS[h](task, model=model, max_actions=max_actions)
        except TypeError:
            try:
                result = RUNNERS[h](task, model=model)
            except Exception as exc:  # noqa: BLE001
                result = _err_result(task, model, h, exc)
        except Exception as exc:  # noqa: BLE001
            result = _err_result(task, model, h, exc)
    except Exception as exc:  # noqa: BLE001
        result = _err_result(task, model, h, exc)
    result["max_actions_budget"] = max_actions
    print(
        f"DONE  {h} | {task['website']} | idx={task['eval_index']} | {result.get('status')} "
        f"success={result.get('success')} actions={result.get('num_actions')} "
        f"cost=${result.get('estimated_cost_usd', 0):.3f}",
        flush=True,
    )
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--stage",
        choices=["smoke", "bakeoff5", "full10", "full100", "hard20", "genuine27", "one"],
        required=True,
    )
    ap.add_argument("--harness", choices=["native_cu", "browser_use", "both"], default="both")
    ap.add_argument("--model", default=BAKEOFF_MODEL)
    ap.add_argument("--eval-index", type=int, default=None)
    ap.add_argument(
        "--max-actions",
        type=int,
        default=None,
        help=(
            f"Override step budget (default derived: max_human={MAX_HUMAN_STEPS}"
            f"+buffer={ACTION_BUFFER} => {MAX_ACTIONS})."
        ),
    )
    ap.add_argument("--workers", type=int, default=1, help="Parallel task workers (ThreadPool).")
    ap.add_argument("--tag", default=None, help="Optional suffix for output filename.")
    ap.add_argument(
        "--resume",
        action="store_true",
        help="Skip eval_index+harness pairs already present in the output manifest.",
    )
    args = ap.parse_args()
    max_actions = args.max_actions if args.max_actions is not None else MAX_ACTIONS

    if args.stage == "smoke":
        indices = SMOKE_INDICES
    elif args.stage == "bakeoff5":
        indices = BAKEOFF5_INDICES
    elif args.stage == "full10":
        indices = TASK_INDICES
    elif args.stage == "full100":
        indices = ALL_INDICES
    elif args.stage == "hard20":
        indices = HARD20_INDICES
    elif args.stage == "genuine27":
        indices = GENUINE_FAIL_INDICES
    else:
        if args.eval_index is None:
            raise SystemExit("--eval-index required for --stage one")
        indices = [args.eval_index]

    tasks = load_tasks(indices)
    harnesses = (
        ["native_cu", "browser_use"] if args.harness == "both" else [args.harness]
    )

    jobs = [(h, task) for task in tasks for h in harnesses]
    tag = args.tag or f"{_model_slug(args.model)}_m{max_actions}"
    out_name = f"{args.stage}_{args.harness}_{tag}"

    out_path = OUT_DIR / f"{out_name}.json"
    runs: list[dict] = []
    done_keys: set[tuple] = set()
    if args.resume and out_path.exists():
        prev = json.loads(out_path.read_text())
        runs = list(prev.get("runs") or [])
        for r in runs:
            h = r.get("harness")
            if h == "browser_use_oss":
                done_keys.add((r.get("eval_index"), "browser_use"))
            else:
                done_keys.add((r.get("eval_index"), h))
        print(f"Resume: loaded {len(runs)} existing runs from {out_path.name}", flush=True)

    pending = [(h, t) for h, t in jobs if (t["eval_index"], h) not in done_keys]
    workers = max(1, min(args.workers, max(1, len(pending))))
    print(
        f"Running {len(pending)}/{len(jobs)} jobs with {workers} workers | model={args.model} "
        f"location={location_for(args.model)} max_actions={max_actions} "
        f"(human_max={MAX_HUMAN_STEPS}+buffer={ACTION_BUFFER}) -> {out_name}.json",
        flush=True,
    )

    lock = threading.Lock()
    harness_order = {h: i for i, h in enumerate(harnesses)}

    def _persist() -> None:
        with lock:
            ordered = sorted(
                runs,
                key=lambda r: (
                    r.get("eval_index", 0),
                    harness_order.get(
                        "browser_use" if r.get("harness") == "browser_use_oss" else r.get("harness"),
                        0,
                    ),
                ),
            )
            _save_manifest(
                out_name, ordered, model=args.model, stage=args.stage, harness=args.harness
            )

    def _on_done(result: dict) -> None:
        with lock:
            runs.append(result)
            n = len(runs)
            ok = sum(1 for r in runs if r.get("success"))
            cost = sum(float(r.get("estimated_cost_usd") or 0) for r in runs)
        print(f"PROGRESS {n}/{len(jobs)} success={ok} cost=${cost:.2f}", flush=True)
        if n % 5 == 0 or n == len(jobs):
            _persist()

    if not pending:
        print("Nothing to run (all jobs already present).", flush=True)
        _persist()
        return

    if workers == 1:
        for h, task in pending:
            _on_done(_run_one(h, task, args.model, max_actions))
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = [
                pool.submit(_run_one, h, task, args.model, max_actions) for h, task in pending
            ]
            for fut in as_completed(futs):
                _on_done(fut.result())

    _persist()


if __name__ == "__main__":
    main()
