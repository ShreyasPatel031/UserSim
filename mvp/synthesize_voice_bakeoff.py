"""Synthesize insights for voice AI bakeoff with proper evidence citations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from mvp.transform_bakeoff_results import classify_failure


PLATFORMS = ["retell", "bland", "vapi"]
PLATFORM_LABEL = {"retell": "Retell AI", "bland": "Bland AI", "vapi": "Vapi"}


def synthesize_product_insights(data: dict) -> dict:
    """Generate per-product strengths and weaknesses with evidence."""
    runs = data.get("runs", [])
    if not runs:
        runs = data.get("agent_results", [])
    
    insights = {}
    
    for platform in PLATFORMS:
        platform_runs = [r for r in runs if (r.get("product") or r.get("website")) == platform]
        
        if not platform_runs:
            continue
        
        successes = [r for r in platform_runs if r.get("success")]
        failures = [r for r in platform_runs if not r.get("success")]
        
        strengths = []
        weaknesses = []
        
        for run in successes:
            task_title = run.get("task_title", run.get("task_key", "unknown task"))
            run_id = run.get("run_id", run.get("agent_id", "unknown"))
            steps = run.get("num_actions", run.get("num_steps", 0))
            final_url = run.get("final_url", "")
            
            strength = {
                "text": f"Successfully completed '{task_title}' in {steps} steps",
                "run_id": run_id,
                "task": task_title,
                "steps": steps,
                "final_url": final_url,
            }
            strengths.append(strength)
        
        for run in failures:
            task_title = run.get("task_title", run.get("task_key", "unknown task"))
            run_id = run.get("run_id", run.get("agent_id", "unknown"))
            failure_cat = classify_failure(run)
            judge_reason = run.get("judge_reason", "")
            
            if failure_cat == "PRODUCT_FAILURE":
                weakness = {
                    "text": f"Failed to complete '{task_title}': {judge_reason[:100] if judge_reason else 'task not completed'}",
                    "run_id": run_id,
                    "task": task_title,
                    "failure_category": failure_cat,
                    "judge_reason": judge_reason,
                }
                weaknesses.append(weakness)
        
        insights[platform] = {
            "name": PLATFORM_LABEL[platform],
            "total_runs": len(platform_runs),
            "successes": len(successes),
            "strengths": strengths[:5],
            "weaknesses": weaknesses[:5],
        }
    
    return insights


def compute_comparative_insights(data: dict) -> dict:
    """Compare platforms on success rate, efficiency, and specific tasks."""
    runs = data.get("runs", [])
    if not runs:
        runs = data.get("agent_results", [])
    
    by_platform = {}
    by_task = {}
    
    for run in runs:
        platform = run.get("product") or run.get("website", "unknown")
        task_key = run.get("task_key") or run.get("task_title", "unknown")
        success = run.get("success", False)
        steps = run.get("num_actions") or run.get("num_steps", 0)
        
        if platform not in by_platform:
            by_platform[platform] = {"successes": 0, "total": 0, "total_steps": 0, "successful_steps": 0}
        by_platform[platform]["total"] += 1
        if success:
            by_platform[platform]["successes"] += 1
            by_platform[platform]["successful_steps"] += steps
        
        if task_key not in by_task:
            by_task[task_key] = {}
        if platform not in by_task[task_key]:
            by_task[task_key][platform] = {"success": 0, "total": 0, "steps": []}
        by_task[task_key][platform]["total"] += 1
        if success:
            by_task[task_key][platform]["success"] += 1
            by_task[task_key][platform]["steps"].append(steps)
    
    success_rates = {}
    avg_steps = {}
    for platform, stats in by_platform.items():
        success_rates[platform] = round(100 * stats["successes"] / max(1, stats["total"]), 1)
        avg_steps[platform] = round(stats["successful_steps"] / max(1, stats["successes"]), 1) if stats["successes"] > 0 else None
    
    task_winners = {}
    for task_key, platforms_data in by_task.items():
        max_success = max((p["success"] for p in platforms_data.values()), default=0)
        if max_success == 0:
            task_winners[task_key] = {"winner": "none", "tied": [], "by_platform": platforms_data}
            continue
        
        winners = [plat for plat, stats in platforms_data.items() if stats["success"] == max_success]
        
        if len(winners) == 1:
            task_winners[task_key] = {"winner": winners[0], "tied": [], "by_platform": platforms_data}
        else:
            min_avg_steps = float("inf")
            efficiency_winner = None
            for w in winners:
                steps_list = platforms_data[w]["steps"]
                if steps_list:
                    avg = sum(steps_list) / len(steps_list)
                    if avg < min_avg_steps:
                        min_avg_steps = avg
                        efficiency_winner = w
            
            if efficiency_winner:
                task_winners[task_key] = {"winner": "tie:" + ",".join(sorted(winners)), "tied": winners, "efficiency_winner": efficiency_winner, "by_platform": platforms_data}
            else:
                task_winners[task_key] = {"winner": "tie:" + ",".join(sorted(winners)), "tied": winners, "by_platform": platforms_data}
    
    recommendations = []
    
    best_success = max(success_rates.items(), key=lambda x: x[1])
    if best_success[1] > 0:
        recommendations.append(f"For highest success rate, {PLATFORM_LABEL.get(best_success[0], best_success[0])} leads at {best_success[1]}%")
    
    best_efficiency = min(((p, s) for p, s in avg_steps.items() if s is not None), key=lambda x: x[1], default=None)
    if best_efficiency:
        recommendations.append(f"For fastest task completion, {PLATFORM_LABEL.get(best_efficiency[0], best_efficiency[0])} averages {best_efficiency[1]} steps")
    
    return {
        "success_rates": success_rates,
        "avg_steps": avg_steps,
        "task_winners": task_winners,
        "recommendations": recommendations,
    }


def generate_summary_insights(data: dict) -> dict:
    """Generate all summary insights."""
    product_insights = synthesize_product_insights(data)
    comparative = compute_comparative_insights(data)
    
    retell_strengths = []
    retell_weaknesses = []
    bland_strengths = []
    bland_weaknesses = []
    vapi_strengths = []
    vapi_weaknesses = []
    
    for platform, insights in product_insights.items():
        strengths_texts = [s["text"] for s in insights.get("strengths", [])]
        weaknesses_texts = [w["text"] for w in insights.get("weaknesses", [])]
        
        if platform == "retell":
            retell_strengths = strengths_texts
            retell_weaknesses = weaknesses_texts
        elif platform == "bland":
            bland_strengths = strengths_texts
            bland_weaknesses = weaknesses_texts
        elif platform == "vapi":
            vapi_strengths = strengths_texts
            vapi_weaknesses = weaknesses_texts
    
    summary = {
        "retell_strengths": retell_strengths,
        "retell_weaknesses": retell_weaknesses,
        "bland_strengths": bland_strengths,
        "bland_weaknesses": bland_weaknesses,
        "vapi_strengths": vapi_strengths,
        "vapi_weaknesses": vapi_weaknesses,
        "task_winners": {k: v.get("winner", "none") for k, v in comparative.get("task_winners", {}).items()},
        "recommendations": {
            "highest_success": comparative.get("recommendations", []),
        },
        "insights_synthesized": True,
    }
    
    return summary


def add_synthesis_to_results(data: dict) -> dict:
    """Add synthesis to transformed results."""
    summary = generate_summary_insights(data)
    
    data.setdefault("summary", {}).update(summary)
    
    return data


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python synthesize_voice_bakeoff.py <path_to_results.json>")
        sys.exit(1)
    
    raw_data = json.loads(Path(sys.argv[1]).read_text())
    
    from mvp.transform_bakeoff_results import transform_proven_harness_results
    transformed = transform_proven_harness_results(raw_data)
    
    result = add_synthesis_to_results(transformed)
    
    print(json.dumps(result["summary"], indent=2, default=str))
