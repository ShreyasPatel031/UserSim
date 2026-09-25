#!/usr/bin/env python3
"""Run a real Retell AI study with strict concurrency control.

This runs a focused study on Retell's PUBLIC website (no login required):
- Max 2 concurrent Browserbase sessions tagged owner=report
- 3 personas × 4 tasks = 12 runs (sequential batches of 2)
- Captures real screenshots and traces for LLM synthesis
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

# Load secrets
sa = ROOT / "secrets" / "sa.json"
if sa.is_file():
    os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", str(sa))

# CRITICAL: Use local browser for stability (Browserbase has CDP issues)
# Extended timeouts for LLM inference time
os.environ["MVP_FORCE_LOCAL_BROWSER"] = "1"
os.environ["MVP_BROWSER_HEADLESS"] = "1"
os.environ["MVP_AGENT_WALL_S"] = "150"  # Extended wall for LLM inference
os.environ["MVP_BROWSER_CONCURRENCY"] = "1"  # Sequential to avoid resource contention
os.environ["BROWSER_USE_CDP_TIMEOUT_S"] = "60"
os.environ["BROWSER_USE_ACTION_TIMEOUT_S"] = "90"

# Session tagging for any Browserbase fallback
OWNER_TAG = "report"
os.environ["BB_OWNER_TAG"] = OWNER_TAG

# Study configuration - PUBLIC SITE only (no login, no voice credits)
PERSONAS = [
    {
        "id": "p1_engineer",
        "name": "Platform Engineer",
        "bio": "Alex is a platform engineer evaluating voice AI APIs for integration. Prioritizes clear documentation, SDK availability, and webhook support.",
    },
    {
        "id": "p2_pm",
        "name": "Product Manager",
        "bio": "Sam is a PM comparing voice AI platforms for a customer support automation project. Focuses on pricing, features, and ease of setup.",
    },
    {
        "id": "p3_founder",
        "name": "Startup Founder",
        "bio": "Jordan is a founder exploring voice AI for an MVP demo. Needs to quickly understand capabilities, pricing, and time-to-first-call.",
    },
]

TASKS = [
    {
        "id": "t1_pricing",
        "title": "Find pricing information",
        "prompt": "Find pricing information for Retell AI. Navigate to the pricing page and note the cost structure, plans available, and what's included in each tier. Note if pricing is easy or hard to find.",
    },
    {
        "id": "t2_docs",
        "title": "Find API documentation",
        "prompt": "Find the API documentation and developer resources. Look for SDKs, webhooks, and integration options. Note the quality and accessibility of docs.",
    },
    {
        "id": "t3_features",
        "title": "Explore voice agent features",
        "prompt": "Explore what voice agent features are available. Find information about creating agents, voice options, and customization. Note what's clear vs confusing.",
    },
]

SEGMENT = """Evaluate Retell AI's voice platform from multiple perspectives:
- Platform engineers looking for API docs and integration guides
- Product managers comparing pricing and features  
- Founders evaluating for quick proof-of-concept

Focus on public website navigation, documentation quality, and ease of finding key information."""

MAX_CONCURRENT = 1  # Sequential for stability
MAX_STEPS = 8  # Enough steps to find info
STUDY_URL = "https://www.retellai.com"


def log(msg: str) -> None:
    print(f"[retell-study] {msg}", flush=True)


async def run_single_agent(
    study_id: str,
    agent_id: str,
    persona: dict,
    task: dict,
    semaphore: asyncio.Semaphore,
) -> dict:
    """Run a single browser agent with semaphore-controlled concurrency."""
    from mvp.browser_agent import run_browser_agent
    
    async with semaphore:
        log(f"Starting {persona['name']} - {task['title']}")
        start = time.time()
        
        try:
            result = await run_browser_agent(
                study_id=study_id,
                agent_id=agent_id,
                url=STUDY_URL,
                task_prompt=task["prompt"],
                persona=persona,
                segment=SEGMENT,
                max_steps=MAX_STEPS,
                local=True,  # Use local browser for stability
            )
            
            elapsed = time.time() - start
            success = result.get("completed", False)
            steps = result.get("num_steps", 0)
            status = "✓" if success else "✗"
            log(f"  {status} {persona['name']}: {task['title']} ({steps} steps, {elapsed:.1f}s)")
            
            return {
                "agent_id": agent_id,
                "persona_id": persona["id"],
                "persona_name": persona["name"],
                "persona_bio": persona["bio"],
                "task_id": task["id"],
                "task_title": task["title"],
                "task_prompt": task["prompt"],
                "success": success,
                "completed": success,
                "num_steps": steps,
                "final_url": result.get("final_url", ""),
                "visited_urls": result.get("visited_urls", []),
                "trace": result.get("trace", []),
                "actions": result.get("actions", []),
                "elapsed_s": elapsed,
                "backend": result.get("backend", "browserbase"),
            }
            
        except Exception as e:
            elapsed = time.time() - start
            log(f"  ✗ {persona['name']}: {task['title']} - ERROR: {e!r}")
            return {
                "agent_id": agent_id,
                "persona_id": persona["id"],
                "persona_name": persona["name"],
                "task_id": task["id"],
                "task_title": task["title"],
                "success": False,
                "error": str(e),
                "elapsed_s": elapsed,
                "trace": [],
            }


async def run_retell_study():
    """Run the Retell study with controlled concurrency."""
    import uuid
    
    study_id = f"retell-live-{uuid.uuid4().hex[:8]}"
    log(f"Starting Retell AI live study: {study_id}")
    log(f"URL: {STUDY_URL}")
    log(f"Personas: {len(PERSONAS)}")
    log(f"Tasks: {len(TASKS)}")
    log(f"Total runs: {len(PERSONAS) * len(TASKS)}")
    log(f"Max concurrent: {MAX_CONCURRENT}")
    log("")
    
    # Create output directory
    from mvp.paths import MVP_RUNS_DIR
    run_dir = MVP_RUNS_DIR / study_id
    run_dir.mkdir(parents=True, exist_ok=True)
    
    # Kill any existing report sessions first
    try:
        from mvp.kill_switch import kill_all_browserbase
        killed = kill_all_browserbase(owner=OWNER_TAG)
        if killed:
            log(f"Released {killed} stale owner={OWNER_TAG} sessions")
    except Exception as e:
        log(f"Could not cleanup old sessions: {e}")
    
    # Semaphore for concurrent control
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    
    # Build task assignments (3 personas × 4 tasks = 12 runs)
    assignments = []
    for persona in PERSONAS:
        for task in TASKS:
            agent_id = f"{task['id']}__{persona['id']}"
            assignments.append((agent_id, persona, task))
    
    log(f"Running {len(assignments)} agent tasks with max {MAX_CONCURRENT} concurrent...")
    start_time = time.time()
    
    # Run all agents with semaphore controlling concurrency
    tasks = [
        run_single_agent(study_id, agent_id, persona, task, semaphore)
        for agent_id, persona, task in assignments
    ]
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Process results
    agent_results = []
    for r in results:
        if isinstance(r, Exception):
            log(f"  Task failed with exception: {r!r}")
            continue
        agent_results.append(r)
    
    elapsed = time.time() - start_time
    success_count = sum(1 for r in agent_results if r.get("success"))
    
    log(f"\n=== Study Complete ===")
    log(f"Study ID: {study_id}")
    log(f"Total time: {elapsed:.1f}s")
    log(f"Results: {success_count}/{len(agent_results)} tasks succeeded")
    
    # Build study data structure
    study_data = {
        "id": study_id,
        "url": STUDY_URL,
        "product_name": "Retell AI",
        "segment": SEGMENT,
        "status": "complete",
        "phase": "Complete",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
        "personas": PERSONAS,
        "tasks": [
            {
                "id": t["id"],
                "title": t["title"],
                "prompt": t["prompt"],
            }
            for t in TASKS
        ],
        "agent_results": agent_results,
        "summary": {
            "total_runs": len(agent_results),
            "successes": success_count,
            "total_time_s": elapsed,
        },
    }
    
    # Save results
    output_path = ROOT / "mvp" / "experiment_results" / f"{study_id}_result.json"
    output_path.parent.mkdir(exist_ok=True)
    output_path.write_text(json.dumps(study_data, indent=2, default=str))
    log(f"Saved to: {output_path}")
    
    # Also save to run directory
    (run_dir / "study.json").write_text(json.dumps(study_data, indent=2, default=str))
    
    return study_data


async def main():
    log("=" * 60)
    log("RETELL AI LIVE STUDY")
    log("=" * 60)
    log(f"Max concurrent sessions: {MAX_CONCURRENT}")
    log(f"Session owner tag: {OWNER_TAG}")
    log("")
    
    # Check current Browserbase status
    try:
        from mvp.kill_switch import list_running_browserbase
        sessions = list_running_browserbase(owner="*")
        our_sessions = [s for s in sessions if (s.get("userMetadata") or {}).get("owner") == OWNER_TAG]
        log(f"Browserbase status: {len(sessions)} total, {len(our_sessions)} owner={OWNER_TAG}")
    except Exception as e:
        log(f"Could not check Browserbase status: {e}")
    
    result = await run_retell_study()
    
    if result:
        log("\n" + "=" * 60)
        log("STUDY COMPLETE")
        log("=" * 60)
        log(f"Study ID: {result.get('id')}")
        log(f"View at: http://localhost:3000/study/{result.get('id')}")
        log(f"API: http://localhost:3000/api/studies/{result.get('id')}")
    else:
        log("\nStudy failed")
    
    return result


if __name__ == "__main__":
    asyncio.run(main())
