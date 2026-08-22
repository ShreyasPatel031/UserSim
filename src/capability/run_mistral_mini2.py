"""Mini-2 with Mistral multimodal + Browser Use — hackathon smoke."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from capability import MAX_ACTIONS, OUT_DIR
from capability.mini2_tasks import MINI2_TASKS
from capability.mistral_browser_use_runner import run_mistral_browser_use
from capability.mistral_config import DEFAULT_MISTRAL_MODEL


def main() -> int:
    p = argparse.ArgumentParser(description="Mistral + Browser Use on Mini-2")
    p.add_argument("--model", default=DEFAULT_MISTRAL_MODEL)
    p.add_argument("--max-actions", type=int, default=MAX_ACTIONS)
    p.add_argument("--task-index", type=int, default=None, help="Run one task (0 or 1)")
    args = p.parse_args()

    tasks = MINI2_TASKS
    if args.task_index is not None:
        tasks = [MINI2_TASKS[args.task_index]]

    results = []
    for i, t in enumerate(tasks):
        task = {**t, "eval_index": f"mini2_{i}"}
        print(f"START mistral | {task['website']} | {task['eval_index']}", flush=True)
        try:
            row = run_mistral_browser_use(task, model=args.model, max_actions=args.max_actions)
        except Exception as exc:  # noqa: BLE001
            row = {
                "eval_index": task["eval_index"],
                "website": task["website"],
                "model": args.model,
                "success": False,
                "status": "FAILURE",
                "stop_reason": str(exc)[:400],
            }
        print(f"DONE  mistral | {task['website']} | {row.get('status')}", flush=True)
        results.append(row)

    slug = args.model.replace("/", "_").replace(".", "-")
    out = OUT_DIR / f"mini2_mistral_{slug}.json"
    payload = {
        "stage": "mini2_mistral",
        "model": args.model,
        "harness": "browser_use_oss",
        "provider": "mistral",
        "max_actions": args.max_actions,
        "results": results,
    }
    out.write_text(json.dumps(payload, indent=2, default=str))
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
