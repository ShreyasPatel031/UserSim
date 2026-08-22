#!/usr/bin/env python3
"""Run Fara1.5 on Online-Mind2Web tasks (batch)."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# vendor/fara must be on path when fara is installed editable, or via PYTHONPATH
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "vendor" / "fara" / "src"))

from fara.agents.fara.fara15_agent import Fara15Agent, Fara15AgentConfig
from fara.core.data_point import SolverStatus, Task, UserMessage, UserMessageType, get_actions
from fara.core.run_context import RunContext
from fara.environments.playwright.environment import PlaywrightEnvironment

from capability import OUT_DIR
from capability.judge import judge_task
from capability.om2w_tasks import load_om2w_tasks


def _action_summary(run_context) -> str:
    lines = []
    for i, step in enumerate(get_actions(run_context.solver_log.events), start=1):
        name = getattr(step, "action_name", None) or getattr(step, "content", step)
        lines.append(f"{i}. {name}")
    return "\n".join(lines) or "(no actions logged)"


async def _run_one(
    task: dict,
    endpoint: dict,
    out_root: Path,
    max_rounds: int,
    browserbase: bool,
    headless: bool,
) -> dict:
    run_id = f"fara_{task['eval_index']}_{uuid.uuid4().hex[:8]}"
    run_dir = out_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    env = PlaywrightEnvironment(
        viewport_width=1440,
        viewport_height=900,
        headless=headless,
        browser_channel="chromium",
        start_page=task["start_url"],
        single_tab_mode=True,
        use_browserbase=browserbase,
    )
    agent = Fara15Agent(
        Fara15AgentConfig(
            client_config=endpoint,
            max_rounds=max_rounds,
            identity="fara_qwen35",
            critical_points="fara-1.5",
            save_screenshots=True,
            auto_user_reply=True,
            captcha_timeout_limit=0,
            max_n_images=1,
        )
    )

    status = "FAILURE"
    success = False
    failure_category = None
    final_url = task["start_url"]
    screenshot = None
    final_answer = ""
    err = None
    run_context = None

    try:
        await env.initialize()
        dp_task = Task(task_id=task["task_id"], instruction=task["task"])
        run_context = RunContext.create(environment=env, task=dp_task, output_dir=run_dir)
        await agent.initialize(run_context)
        final_answer, _, _ = await agent.run(run_context)

        while run_context.solver_log.status == SolverStatus.WAITING_FOR_USER:
            run_context.add_observation(
                UserMessage(
                    content="Proceed with publicly available information only.",
                    message_type=UserMessageType.CRITICAL_POINT_RESPONSE,
                )
            )
            final_answer, _, _ = await agent.run(run_context)

        summary = _action_summary(run_context)
        if final_answer:
            summary += f"\nFinal answer: {final_answer}"
        try:
            final_url = env.page.url if getattr(env, "page", None) else task["start_url"]
        except Exception:
            final_url = task["start_url"]
        shots = sorted(run_dir.glob("screenshot_*.png"))
        if shots:
            screenshot = shots[-1].read_bytes()
        elif (run_dir / "final.png").exists():
            screenshot = (run_dir / "final.png").read_bytes()

        judgment = judge_task(task["task"], final_url, summary, screenshot)
        status = judgment["status"]
        success = status == "SUCCESS"
        if not success and status in {"BLOCKED", "SITE_CHANGED"}:
            failure_category = status
        elif not success:
            failure_category = "MODEL_REASONING"
    except Exception as exc:  # noqa: BLE001
        err = str(exc)[:500]
        status = "FAILURE"
        failure_category = "HARNESS"
    finally:
        if run_context is not None:
            try:
                await agent.close(run_context)
            except Exception:
                pass
        try:
            await env.close()
        except Exception:
            pass

    out = {
        "run_id": run_id,
        "task_id": task["task_id"],
        "eval_index": task["eval_index"],
        "task": task["task"],
        "website": task["website"],
        "start_url": task["start_url"],
        "model": endpoint.get("model", "Fara1.5-4B"),
        "harness": "fara15_playwright",
        "success": success,
        "status": status,
        "failure_category": failure_category,
        "final_answer": final_answer,
        "final_url": final_url,
        "error": err,
        "trace_dir": str(run_dir),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    (run_dir / "om2w_result.json").write_text(json.dumps(out, indent=2))
    return out


async def _main_async(args: argparse.Namespace) -> int:
    tasks = load_om2w_tasks(
        limit=args.limit,
        mini2_only=args.mini2,
        task_ids=args.task_ids.split(",") if args.task_ids else None,
    )
    endpoint = {
        "model": args.model,
        "base_url": args.base_url,
        "api_key": args.api_key,
    }
    out_root = Path(args.out_dir)
    out_root.mkdir(parents=True, exist_ok=True)

    results = []
    for task in tasks:
        print(f"START {task['eval_index']} | {task['website']} | {task['task_id']}", flush=True)
        r = await _run_one(
            task,
            endpoint,
            out_root,
            max_rounds=args.max_rounds,
            browserbase=args.browserbase,
            headless=not args.headful,
        )
        results.append(r)
        print(f"DONE  {task['eval_index']} | {r['status']} | success={r['success']}", flush=True)

    n = len(results)
    succ = sum(1 for r in results if r["success"])
    blocked = sum(1 for r in results if r["status"] == "BLOCKED")
    summary = {
        "benchmark": "Online-Mind2Web",
        "model": endpoint["model"],
        "harness": "fara15_playwright",
        "judge": "gemini-2.5-flash (in-repo; not official WebJudge o4-mini)",
        "n": n,
        "successes": succ,
        "success_rate": round(succ / n, 4) if n else 0.0,
        "blocked": blocked,
        "browserbase": args.browserbase,
        "max_rounds": args.max_rounds,
        "mini2": args.mini2,
        "results": results,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    out_path = OUT_DIR / args.summary_name
    out_path.write_text(json.dumps(summary, indent=2))
    print(json.dumps({"n": n, "successes": succ, "rate": summary["success_rate"], "out": str(out_path)}))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Fara1.5 Online-Mind2Web batch eval")
    p.add_argument("--base-url", default="http://127.0.0.1:5000/v1")
    p.add_argument("--model", default="Fara1.5-4B")
    p.add_argument("--api-key", default="not-needed")
    p.add_argument("--max-rounds", type=int, default=100)
    p.add_argument("--limit", type=int, default=None, help="First N OM2W tasks")
    p.add_argument("--mini2", action="store_true", help="Run 2 reachable mini2 tasks only")
    p.add_argument("--task-ids", type=str, default=None, help="Comma-separated OM2W task_ids")
    p.add_argument("--browserbase", action="store_true")
    p.add_argument("--headful", action="store_true")
    p.add_argument("--out-dir", default=str(OUT_DIR / "fara_om2w_traces"))
    p.add_argument("--summary-name", default="fara_om2w_results.json")
    args = p.parse_args()
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
