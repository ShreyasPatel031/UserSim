"""Mini-2 harness bakeoff: gemini-3.6-flash × {browser_use_oss, seeact_lite}.

Tasks are Online-Mind2Web items validated on strong HAL agents (see mini2_tasks.py).
Keep this probe tiny — do not expand to Hard-20 here.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from capability import BAKEOFF_MODEL, MAX_ACTIONS, OUT_DIR, location_for
from capability.browser_use_runner import run_browser_use
from capability.mini2_tasks import MINI2_TASKS
from capability.seeact_lite_runner import run_seeact_lite


RUNNERS = {
    "browser_use": run_browser_use,
    "seeact_lite": run_seeact_lite,
}


def _tasks() -> list[dict]:
    out = []
    for i, t in enumerate(MINI2_TASKS):
        out.append(
            {
                "task_id": t["task_id"],
                "eval_index": f"mini2_{i}",
                "website": t["website"],
                "task": t["task"],
                "start_url": t["start_url"],
                "level": t.get("level"),
                "hal_validated": t.get("hal_validated"),
                "why": t.get("why"),
            }
        )
    return out


def _err(task: dict, model: str, h: str, exc: Exception) -> dict:
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


def _run_one(h: str, task: dict, model: str, max_actions: int) -> dict:
    print(
        f"START {h} | {task['website']} | {task['eval_index']} | max_actions={max_actions}",
        flush=True,
    )
    try:
        result = RUNNERS[h](
            task, model=model, location=location_for(model), max_actions=max_actions
        )
    except TypeError:
        try:
            result = RUNNERS[h](task, model=model, max_actions=max_actions)
        except Exception as exc:  # noqa: BLE001
            result = _err(task, model, h, exc)
    except Exception as exc:  # noqa: BLE001
        result = _err(task, model, h, exc)
    result["max_actions_budget"] = max_actions
    print(
        f"DONE  {h} | {task['website']} | {task['eval_index']} | {result.get('status')} "
        f"success={result.get('success')} actions={result.get('num_actions')} "
        f"cost=${float(result.get('estimated_cost_usd') or 0):.4f}",
        flush=True,
    )
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description="Mini-2 harness bakeoff (3.6 Flash)")
    ap.add_argument("--model", default=BAKEOFF_MODEL)
    ap.add_argument(
        "--harness",
        nargs="+",
        default=["browser_use", "seeact_lite"],
        choices=list(RUNNERS),
    )
    ap.add_argument("--max-actions", type=int, default=MAX_ACTIONS)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument(
        "--task-ids",
        nargs="*",
        default=None,
        help="Optional subset of Mini-2 task_ids",
    )
    args = ap.parse_args()

    tasks = _tasks()
    if args.task_ids:
        want = set(args.task_ids)
        tasks = [t for t in tasks if t["task_id"] in want]
    if not tasks:
        raise SystemExit("No Mini-2 tasks selected")

    jobs = [(h, t) for h in args.harness for t in tasks]
    runs: list[dict] = []
    lock = threading.Lock()

    def _job(pair):
        h, t = pair
        r = _run_one(h, t, args.model, args.max_actions)
        with lock:
            runs.append(r)
        return r

    if args.workers <= 1:
        for j in jobs:
            _job(j)
    else:
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = [ex.submit(_job, j) for j in jobs]
            for f in as_completed(futs):
                f.result()

    # stable order: harness then mini2 index (normalize browser_use_oss → browser_use)
    def _hkey(h: str | None) -> str:
        h = h or ""
        return "browser_use" if h in {"browser_use", "browser_use_oss"} else h

    order = {(h, t["eval_index"]): i for i, (h, t) in enumerate(jobs)}
    runs.sort(key=lambda r: order.get((_hkey(r.get("harness")), r.get("eval_index")), 999))

    slug = args.model.replace(".", "").replace("/", "-")
    name = f"mini2_harness_{slug}"
    path = OUT_DIR / f"{name}.json"
    by_harness = {}
    for h in sorted({r.get("harness") for r in runs}):
        subset = [r for r in runs if r.get("harness") == h]
        by_harness[h] = {
            "n": len(subset),
            "success": sum(1 for r in subset if r.get("success")),
            "by_status": dict(Counter(r.get("status") for r in subset)),
            "avg_actions": round(
                sum(r.get("num_actions") or 0 for r in subset) / max(1, len(subset)), 2
            ),
            "cost_usd": round(sum(float(r.get("estimated_cost_usd") or 0) for r in subset), 4),
            "failures": dict(
                Counter(r.get("failure_category") for r in subset if not r.get("success"))
            ),
        }
    summary = {
        "stage": "mini2_harness",
        "model": args.model,
        "location": location_for(args.model),
        "max_actions_budget": args.max_actions,
        "selection": "HAL-validated Online-Mind2Web (see mini2_tasks.py)",
        "n": len(runs),
        "successes": sum(1 for r in runs if r.get("success")),
        "by_harness": by_harness,
        "total_cost_usd": round(sum(float(r.get("estimated_cost_usd") or 0) for r in runs), 4),
        "runs": runs,
    }
    path.write_text(json.dumps(summary, indent=2, default=str))
    print(json.dumps({k: summary[k] for k in ("model", "n", "successes", "by_harness", "total_cost_usd")}, indent=2), flush=True)
    print(f"Wrote {path}", flush=True)


if __name__ == "__main__":
    main()
