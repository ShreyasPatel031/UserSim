"""Transform proven harness results to voice_bakeoff page format."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional


def classify_failure(result: dict) -> str:
    """Classify a failure into: SUCCESS, HARNESS, BOT_WALL, PRODUCT_FAILURE."""
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

    if status == "JUDGE_ERROR" or failure_cat == "JUDGE_ERROR":
        return "JUDGE_ERROR"
    
    if "timeout" in stop_reason.lower() or "wall" in stop_reason.lower():
        return "HARNESS"
    
    if num_actions < 3:
        return "HARNESS"
    
    if failure_cat in ("PREMATURE_STOP", "PLANNING", "MODEL_REASONING"):
        return "PRODUCT_FAILURE"
    
    if num_actions >= 3:
        return "PRODUCT_FAILURE"
    
    return "HARNESS"


def refresh_manifest_counts(data: dict) -> dict:
    """Recompute summary fields from runs so they cannot drift from the array."""
    from collections import Counter

    runs = data.get("runs") or []
    platforms = ["retell", "bland", "vapi"]
    by_product = {
        p: {"success": 0, "harness": 0, "bot_wall": 0, "product_failure": 0, "judge_error": 0}
        for p in platforms
    }
    by_task: dict = {}
    for r in runs:
        plat = r.get("website") or r.get("product") or "unknown"
        task = r.get("task_key") or "unknown"
        cls = classify_failure(r)
        by_product.setdefault(
            plat,
            {"success": 0, "harness": 0, "bot_wall": 0, "product_failure": 0, "judge_error": 0},
        )
        cell = by_task.setdefault(task, {}).setdefault(plat, {"success": 0, "total": 0})
        cell["total"] += 1
        if cls == "SUCCESS":
            by_product[plat]["success"] += 1
            cell["success"] += 1
        elif cls == "HARNESS":
            by_product[plat]["harness"] += 1
        elif cls == "BOT_WALL":
            by_product[plat]["bot_wall"] += 1
        elif cls == "JUDGE_ERROR":
            by_product[plat]["judge_error"] += 1
        else:
            by_product[plat]["product_failure"] += 1
    data["by_product"] = by_product
    data["by_task"] = by_task
    data["task_winners"] = compute_task_winners(by_task)
    data["successes"] = sum(1 for r in runs if r.get("success"))
    data["by_status"] = dict(Counter(r.get("status") for r in runs))
    data["by_failure_category"] = dict(
        Counter(r.get("failure_category") for r in runs if r.get("failure_category"))
    )
    return data


def compute_task_winners(by_task: dict) -> dict:
    """Compute winners with tie handling."""
    task_winners = {}
    for task_key, prods in by_task.items():
        max_success = max((p.get("success", 0) for p in prods.values()), default=0)
        if max_success == 0:
            task_winners[task_key] = "none"
            continue
        
        winners = [prod for prod, stats in prods.items() if stats.get("success", 0) == max_success]
        if len(winners) == 1:
            task_winners[task_key] = winners[0]
        else:
            task_winners[task_key] = "tie:" + ",".join(sorted(winners))
    
    return task_winners


def transform_proven_harness_results(data: dict) -> dict:
    """Transform proven harness output to voice_bakeoff page format."""
    runs = data.get("runs", [])
    
    PLATFORMS = ["retell", "bland", "vapi"]
    PLATFORM_LABEL = {"retell": "Retell AI", "bland": "Bland AI", "vapi": "Vapi"}
    
    by_product = {}
    by_task = {}
    agent_results = []
    
    for r in runs:
        prod = r.get("product") or r.get("website", "unknown")
        task_key = r.get("task_key", r.get("task_id", "").split("__")[0] if "__" in r.get("task_id", "") else "unknown")
        task_title = r.get("task_title", task_key)
        persona_id = r.get("persona_id", "unknown")
        persona_name = r.get("persona_name", "Unknown")
        
        cls = classify_failure(r)
        
        if prod not in by_product:
            by_product[prod] = {
                "name": PLATFORM_LABEL.get(prod, prod),
                "success": 0,
                "harness_failure": 0,
                "bot_wall": 0,
                "product_failure": 0,
                "judge_error_excluded": 0,
            }
        
        if cls == "SUCCESS":
            by_product[prod]["success"] += 1
        elif cls == "HARNESS":
            by_product[prod]["harness_failure"] += 1
        elif cls == "BOT_WALL":
            by_product[prod]["bot_wall"] += 1
        elif cls == "JUDGE_ERROR":
            by_product[prod]["judge_error_excluded"] += 1
        else:
            by_product[prod]["product_failure"] += 1
        
        if task_key not in by_task:
            by_task[task_key] = {}
        if prod not in by_task[task_key]:
            by_task[task_key][prod] = {"success": 0, "harness": 0, "product_failure": 0, "total": 0}
        by_task[task_key][prod]["total"] += 1
        if cls == "SUCCESS":
            by_task[task_key][prod]["success"] += 1
        elif cls == "HARNESS":
            by_task[task_key][prod]["harness"] += 1
        else:
            by_task[task_key][prod]["product_failure"] += 1
        
        trace_dir = r.get("trace_dir", "")
        trace = []
        if trace_dir:
            trace_path = Path(trace_dir)
            screenshots_dir = trace_path / "screenshots" if trace_path.is_dir() else None
            if screenshots_dir and screenshots_dir.is_dir():
                for i, png in enumerate(sorted(screenshots_dir.glob("step_*.png"))):
                    trace.append({
                        "step": i,
                        "action": f"Step {i}",
                        "screenshot_url": f"/bakeoff-traces/{trace_path.name}/screenshots/{png.name}",
                    })
            final_png = trace_path / "final.png" if trace_path.is_dir() else None
            if final_png and final_png.is_file():
                trace.append({
                    "step": len(trace),
                    "action": "Final state",
                    "screenshot_url": f"/bakeoff-traces/{trace_path.name}/final.png",
                })
        
        agent_result = {
            "agent_id": r.get("run_id", f"{prod}_{task_key}_{persona_id}"),
            "product": prod,
            "persona_id": persona_id,
            "persona_name": persona_name,
            "task_id": task_key,
            "task_title": task_title,
            "task_prompt": r.get("task", ""),
            "success": r.get("success", False),
            "harness_timeout": cls == "HARNESS",
            "failure_category": cls,
            "num_steps": r.get("num_actions", 0),
            "elapsed_s": 0,
            "final_url": r.get("final_url", ""),
            "judge_reason": r.get("judge_reason", ""),
            "judge_evidence": r.get("judge_evidence", ""),
            "trace": trace,
        }
        agent_results.append(agent_result)
    
    task_winners = compute_task_winners(by_task)
    
    personas = []
    seen_personas = set()
    for r in runs:
        pid = r.get("persona_id", "unknown")
        if pid not in seen_personas:
            seen_personas.add(pid)
            personas.append({
                "id": pid,
                "name": r.get("persona_name", pid),
            })
    
    tasks = []
    seen_tasks = set()
    for r in runs:
        tid = r.get("task_key", "unknown")
        if tid not in seen_tasks:
            seen_tasks.add(tid)
            tasks.append({
                "id": tid,
                "title": r.get("task_title", tid),
            })
    
    total_runs = len(runs)
    total_success = sum(1 for r in runs if r.get("success"))
    
    summary = {
        "total_runs": total_runs,
        "by_product": by_product,
        "by_task": by_task,
        "task_winners": task_winners,
        "insights_synthesized": False,
    }
    
    return {
        "id": data.get("id", "voice-public-bakeoff"),
        "product_name": "Voice AI Bakeoff",
        "url": "",
        "personas": personas,
        "tasks": tasks,
        "agent_results": agent_results,
        "summary": summary,
        "created_at": data.get("created_at", ""),
    }


def load_and_transform(path: str) -> dict:
    """Load proven harness results and transform to page format."""
    data = json.loads(Path(path).read_text())
    return transform_proven_harness_results(data)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python transform_bakeoff_results.py <path_to_results.json>")
        sys.exit(1)
    
    result = load_and_transform(sys.argv[1])
    print(json.dumps(result, indent=2, default=str))
