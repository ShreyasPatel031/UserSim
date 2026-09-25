"""Voice AI public site bakeoff — Retell vs Bland vs Vapi marketing sites.

Uses the proven browser_use_runner harness with fresh browser per run.
Tasks are public marketing site explorations (no login required).
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from capability import BAKEOFF_MODEL, OUT_DIR, location_for
from capability.browser_use_runner import run_browser_use

PLATFORMS = ["retell", "bland", "vapi"]
PLATFORM_LABEL = {"retell": "Retell AI", "bland": "Bland AI", "vapi": "Vapi"}
PLATFORM_URL = {
    "retell": "https://www.retell.ai/",
    "bland": "https://www.bland.ai/",
    "vapi": "https://vapi.ai/",
}

PERSONAS = [
    {
        "id": "p1_engineer",
        "name": "Platform Engineer",
        "bio": "Senior engineer evaluating voice AI APIs for integration into a SaaS product.",
        "cares_about": "API documentation, integration guides, webhooks, pricing per call",
    },
    {
        "id": "p2_pm",
        "name": "Product Manager",
        "bio": "PM at a mid-size company exploring voice AI for customer support automation.",
        "cares_about": "features, use cases, pricing, demos, getting started",
    },
    {
        "id": "p3_founder",
        "name": "Startup Founder",
        "bio": "Technical founder evaluating voice AI platforms for a new product.",
        "cares_about": "pricing, capabilities, ease of integration, time to first agent",
    },
]

TASKS = [
    {
        "id": "t1_pricing",
        "title": "Find and evaluate pricing",
        "goal": "Find the pricing page and understand the cost structure for voice AI calls.",
        "success": "Reached a pricing page with visible pricing tiers, per-minute costs, or plan comparison.",
    },
    {
        "id": "t2_docs",
        "title": "Find and evaluate API documentation",
        "goal": "Find the API documentation or developer docs to understand how to integrate.",
        "success": "Reached API docs, developer documentation, or integration guides page.",
    },
    {
        "id": "t3_features",
        "title": "Explore voice agent capabilities",
        "goal": "Find information about what voice agents can do - features, capabilities, use cases.",
        "success": "Found a features page, capabilities overview, or use cases section with details.",
    },
    {
        "id": "t4_integrations",
        "title": "Find integration and webhook info",
        "goal": "Find information about integrations, webhooks, or connecting to other systems.",
        "success": "Found integrations page, webhook docs, or third-party connection information.",
    },
    {
        "id": "t5_getting_started",
        "title": "Evaluate getting started experience",
        "goal": "Find the getting started guide or quick start to understand onboarding.",
        "success": "Found getting started guide, quickstart, or clear path to begin using the platform.",
    },
]

MAX_ACTIONS = 25


def build_task(persona: dict, task: dict, platform: str) -> dict:
    """Build a task dict compatible with browser_use_runner."""
    platform_name = PLATFORM_LABEL[platform]
    start_url = PLATFORM_URL[platform]
    
    task_text = (
        f"PERSONA: {persona['name']} — {persona['bio']}\n"
        f"You care about: {persona['cares_about']}.\n\n"
        f"PLATFORM: {platform_name} public website (not logged in).\n"
        f"Start URL: {start_url}\n\n"
        f"USER GOAL: {task['goal']}\n\n"
        f"SUCCESS CRITERIA: {task['success']}\n\n"
        f"INSTRUCTIONS:\n"
        f"1. Navigate the {platform_name} website to accomplish the goal.\n"
        f"2. Click links, scroll, and explore to find the information.\n"
        f"3. When you find what you're looking for, stop and report what you found.\n"
        f"4. In your final answer, describe:\n"
        f"   - What you found and where\n"
        f"   - 2-3 things you LIKED about the experience\n"
        f"   - 2-3 things you DISLIKED or found confusing\n"
        f"   - Overall difficulty (easy/medium/hard)"
    )
    
    task_id = f"{task['id']}__{persona['id']}__{platform}"
    eval_index = hash(task_id) % 100000
    
    return {
        "task_id": task_id,
        "eval_index": eval_index,
        "website": platform,
        "task": task_text,
        "start_url": start_url,
        "persona_id": persona["id"],
        "persona_name": persona["name"],
        "task_key": task["id"],
        "task_title": task["title"],
        "product": platform,
        "max_actions_hint": MAX_ACTIONS,
    }


def all_tasks() -> list[dict]:
    """Generate all task combinations."""
    out = []
    for persona in PERSONAS:
        for task in TASKS:
            for platform in PLATFORMS:
                out.append(build_task(persona, task, platform))
    return out


def _err(task: dict, model: str, exc: Exception) -> dict:
    return {
        "run_id": f"err_{task['eval_index']}",
        "task_id": task["task_id"],
        "eval_index": task["eval_index"],
        "task": task["task"],
        "website": task["website"],
        "product": task.get("product", task["website"]),
        "persona_id": task.get("persona_id"),
        "persona_name": task.get("persona_name"),
        "task_key": task.get("task_key"),
        "task_title": task.get("task_title"),
        "model": model,
        "harness": "browser_use_oss",
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
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def _run_one(task: dict, model: str, max_actions: int) -> dict:
    print(
        f"START {task['product']:8} | {task['task_title'][:35]:35} | {task['persona_name'][:20]:20} | max={max_actions}",
        flush=True,
    )
    try:
        result = run_browser_use(
            task, model=model, location=location_for(model), max_actions=max_actions, preflight=True
        )
    except TypeError:
        try:
            result = run_browser_use(task, model=model, max_actions=max_actions, preflight=True)
        except Exception as exc:
            result = _err(task, model, exc)
    except Exception as exc:
        result = _err(task, model, exc)
    
    result["max_actions_budget"] = max_actions
    result["product"] = task.get("product", task["website"])
    result["persona_id"] = task.get("persona_id")
    result["persona_name"] = task.get("persona_name")
    result["task_key"] = task.get("task_key")
    result["task_title"] = task.get("task_title")
    
    print(
        f"DONE  {result['product']:8} | {result.get('task_title', '')[:35]:35} | "
        f"{result.get('status', 'UNKNOWN'):10} | actions={result.get('num_actions', 0)} | "
        f"cost=${float(result.get('estimated_cost_usd') or 0):.4f}",
        flush=True,
    )
    return result


def classify_failure(result: dict) -> str:
    """Classify a failure into: HARNESS, BOT_WALL, PRODUCT_FAILURE."""
    if result.get("success"):
        return "SUCCESS"
    
    failure_cat = result.get("failure_category", "")
    stop_reason = result.get("stop_reason", "")
    num_actions = result.get("num_actions", 0)
    status = result.get("status", "")
    
    if status == "BLOCKED" or failure_cat == "BLOCKED":
        return "BOT_WALL"
    
    if failure_cat == "HARNESS":
        return "HARNESS"
    
    if "timeout" in stop_reason.lower() or "wall" in stop_reason.lower():
        return "HARNESS"
    
    if num_actions < 3:
        return "HARNESS"
    
    if failure_cat in ("PREMATURE_STOP", "PLANNING", "MODEL_REASONING"):
        return "PRODUCT_FAILURE"
    
    if num_actions >= 3:
        return "PRODUCT_FAILURE"
    
    return "HARNESS"


def main() -> None:
    ap = argparse.ArgumentParser(description="Voice AI public site bakeoff")
    ap.add_argument("--model", default=BAKEOFF_MODEL)
    ap.add_argument("--max-actions", type=int, default=MAX_ACTIONS)
    ap.add_argument("--workers", type=int, default=1, help="Parallel workers (1 = sequential)")
    ap.add_argument("--platforms", nargs="*", default=None, help="Filter platforms (retell, bland, vapi)")
    ap.add_argument("--tasks", nargs="*", default=None, help="Filter task IDs (t1_pricing, t2_docs, etc)")
    ap.add_argument("--personas", nargs="*", default=None, help="Filter persona IDs")
    ap.add_argument("--resume", type=str, default=None, help="Path to previous run to resume from")
    args = ap.parse_args()

    tasks = all_tasks()
    
    if args.platforms:
        tasks = [t for t in tasks if t["product"] in args.platforms]
    if args.tasks:
        tasks = [t for t in tasks if t["task_key"] in args.tasks]
    if args.personas:
        tasks = [t for t in tasks if t["persona_id"] in args.personas]
    
    if not tasks:
        raise SystemExit("No tasks selected")

    runs: list[dict] = []
    done_keys: set[str] = set()
    
    if args.resume and Path(args.resume).is_file():
        prev = json.loads(Path(args.resume).read_text())
        prev_runs = prev.get("runs", [])
        for r in prev_runs:
            cls = classify_failure(r)
            if cls != "HARNESS":
                runs.append(r)
                done_keys.add(r.get("task_id", ""))
                print(f"RESUME {r.get('task_id', '')[:50]} -> {cls}", flush=True)
    
    pending = [t for t in tasks if t["task_id"] not in done_keys]
    
    print(f"\nRunning {len(pending)}/{len(tasks)} tasks (workers={args.workers}, model={args.model})\n", flush=True)

    lock = threading.Lock()

    def _job(t):
        r = _run_one(t, args.model, args.max_actions)
        with lock:
            runs.append(r)
        return r

    if args.workers <= 1:
        for t in pending:
            _job(t)
    else:
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = [ex.submit(_job, t) for t in pending]
            for f in as_completed(futs):
                f.result()

    runs.sort(key=lambda r: (r.get("product", ""), r.get("task_key", ""), r.get("persona_id", "")))

    by_product = {}
    by_task = {}
    for r in runs:
        prod = r.get("product", "unknown")
        task_key = r.get("task_key", "unknown")
        cls = classify_failure(r)
        
        if prod not in by_product:
            by_product[prod] = {"success": 0, "harness": 0, "bot_wall": 0, "product_failure": 0}
        if cls == "SUCCESS":
            by_product[prod]["success"] += 1
        elif cls == "HARNESS":
            by_product[prod]["harness"] += 1
        elif cls == "BOT_WALL":
            by_product[prod]["bot_wall"] += 1
        else:
            by_product[prod]["product_failure"] += 1
        
        if task_key not in by_task:
            by_task[task_key] = {}
        if prod not in by_task[task_key]:
            by_task[task_key][prod] = {"success": 0, "total": 0}
        by_task[task_key][prod]["total"] += 1
        if cls == "SUCCESS":
            by_task[task_key][prod]["success"] += 1

    task_winners = {}
    for task_key, prods in by_task.items():
        max_success = max(p["success"] for p in prods.values())
        winners = [prod for prod, stats in prods.items() if stats["success"] == max_success and max_success > 0]
        if len(winners) == 1:
            task_winners[task_key] = winners[0]
        elif len(winners) > 1:
            task_winners[task_key] = "tie:" + ",".join(sorted(winners))
        else:
            task_winners[task_key] = "none"

    run_id = f"voice-public-{uuid.uuid4().hex[:8]}"
    out_path = OUT_DIR / f"{run_id}.json"
    
    summary = {
        "id": run_id,
        "stage": "voice_public_bakeoff",
        "model": args.model,
        "location": location_for(args.model),
        "max_actions_budget": args.max_actions,
        "harness": "browser_use_oss",
        "n": len(runs),
        "successes": sum(1 for r in runs if r.get("success")),
        "by_product": by_product,
        "by_task": by_task,
        "task_winners": task_winners,
        "by_status": dict(Counter(r.get("status") for r in runs)),
        "by_failure_category": dict(Counter(classify_failure(r) for r in runs)),
        "total_cost_usd": round(sum(float(r.get("estimated_cost_usd") or 0) for r in runs), 4),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "runs": runs,
    }
    
    out_path.write_text(json.dumps(summary, indent=2, default=str))
    
    print("\n" + "=" * 70)
    print("VOICE AI PUBLIC BAKEOFF RESULTS")
    print("=" * 70)
    print(f"\nModel: {args.model}")
    print(f"Total runs: {len(runs)}")
    print(f"Total successes: {summary['successes']}")
    print(f"Total cost: ${summary['total_cost_usd']:.2f}")
    
    print("\n--- BY PRODUCT ---")
    for prod in PLATFORMS:
        stats = by_product.get(prod, {})
        total = sum(stats.values())
        print(f"{PLATFORM_LABEL[prod]:12}: {stats.get('success', 0)}/{total} success, "
              f"{stats.get('harness', 0)} harness, {stats.get('bot_wall', 0)} bot_wall, "
              f"{stats.get('product_failure', 0)} product_fail")
    
    print("\n--- BY TASK ---")
    for task in TASKS:
        task_key = task["id"]
        winner = task_winners.get(task_key, "?")
        print(f"{task['title'][:35]:35} -> Winner: {winner}")
        for prod in PLATFORMS:
            stats = by_task.get(task_key, {}).get(prod, {"success": 0, "total": 0})
            print(f"  {PLATFORM_LABEL[prod]:12}: {stats['success']}/{stats['total']}")
    
    print(f"\nWrote results to: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
