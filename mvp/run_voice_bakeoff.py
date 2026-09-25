#!/usr/bin/env python3
"""Run comprehensive voice AI platform bakeoff: Retell vs Bland vs Vapi.

This runs identical personas and tasks across all 3 products to enable
fair comparison. Includes both public site tasks and dashboard tasks.

Configuration:
- 4 personas × 5 tasks × 3 products = 60 runs
- 8-minute wall timeout per run, 40 steps max
- Tracks harness timeouts separately from product failures
- Uses local browser for stability (Browserbase has CDP issues)
"""

import asyncio
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

# Load secrets
sa = ROOT / "secrets" / "sa.json"
if sa.is_file():
    os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", str(sa))

# Configuration for robust runs
os.environ["MVP_FORCE_LOCAL_BROWSER"] = "1"
os.environ["MVP_BROWSER_HEADLESS"] = "1"
os.environ["MVP_AGENT_WALL_S"] = "480"  # 8 minutes
os.environ["MVP_BROWSER_CONCURRENCY"] = "3"  # 3 concurrent (one per product)
os.environ["BROWSER_USE_CDP_TIMEOUT_S"] = "120"
os.environ["BROWSER_USE_ACTION_TIMEOUT_S"] = "180"
os.environ["BB_OWNER_TAG"] = "report"

# Products to compare
PRODUCTS = {
    "retell": {
        "name": "Retell AI",
        "url": "https://www.retellai.com",
        "dashboard": "https://dashboard.retellai.com",
        "docs": "https://docs.retellai.com",
    },
    "bland": {
        "name": "Bland AI", 
        "url": "https://www.bland.ai",
        "dashboard": "https://app.bland.ai",
        "docs": "https://docs.bland.ai",
    },
    "vapi": {
        "name": "Vapi",
        "url": "https://vapi.ai",
        "dashboard": "https://dashboard.vapi.ai",
        "docs": "https://docs.vapi.ai",
    },
}

# Personas - represent different user types (3 personas for efficient comparison)
PERSONAS = [
    {
        "id": "p1_engineer",
        "name": "Platform Engineer",
        "bio": "Alex evaluates voice AI APIs for integration. Prioritizes documentation quality, SDK availability, webhooks, and API design.",
    },
    {
        "id": "p2_pm",
        "name": "Product Manager",
        "bio": "Sam compares voice AI platforms for customer support automation. Focuses on pricing clarity, feature comparison, and ease of initial setup.",
    },
    {
        "id": "p3_founder",
        "name": "Startup Founder",
        "bio": "Jordan is a founder building an MVP. Needs to quickly understand capabilities, pricing, and get a proof-of-concept running.",
    },
]

# Tasks - PUBLIC SITE tasks that don't require login
# Dashboard tasks skipped since we don't have test credentials configured
TASKS = [
    {
        "id": "t1_pricing",
        "title": "Find and evaluate pricing",
        "prompt": "Find pricing information for this voice AI platform. Navigate to the pricing page and understand: (1) cost per minute/call, (2) plans available, (3) what's included in each tier, (4) any free tier or trial. Note how easy or hard it is to find and understand pricing compared to competitors.",
        "requires_login": False,
    },
    {
        "id": "t2_docs",
        "title": "Find and evaluate API documentation",
        "prompt": "Find the API documentation and developer resources. Look for: (1) SDKs (Python, Node, etc.), (2) webhooks documentation, (3) REST API reference, (4) getting started guides. Note the quality, organization, and accessibility of documentation.",
        "requires_login": False,
    },
    {
        "id": "t3_features",
        "title": "Explore voice agent capabilities",
        "prompt": "Explore what voice agent capabilities are available without signing up. Look for: (1) voice options and customization, (2) LLM/AI model options, (3) conversation flow/prompt configuration, (4) phone number and telephony options. Note what's discoverable from the public site.",
        "requires_login": False,
    },
    {
        "id": "t4_integrations",
        "title": "Find integration and webhook info",
        "prompt": "Find information about integrations, webhooks, and API connectivity. Look for: (1) webhook documentation, (2) CRM/tool integrations, (3) event callbacks, (4) API authentication methods. Note what a developer can learn before signing up.",
        "requires_login": False,
    },
    {
        "id": "t5_getting_started",
        "title": "Evaluate getting started experience",
        "prompt": "Find the getting started or quickstart guide. Follow the steps mentally and note: (1) how many steps to first voice call, (2) what's required to get started, (3) clarity of instructions. Compare the onboarding experience to competitors.",
        "requires_login": False,
    },
]

# Run configuration
MAX_STEPS = 40  # Enough for comprehensive exploration
WALL_TIMEOUT_S = 480  # 8 minutes
MAX_CONCURRENT_PER_PRODUCT = 1  # Sequential within product for login state
MAX_TOTAL_CONCURRENT = 3  # One per product in parallel


@dataclass
class RunResult:
    """Result of a single agent run."""
    agent_id: str
    product: str
    persona_id: str
    persona_name: str
    task_id: str
    task_title: str
    success: bool
    completed: bool
    harness_timeout: bool  # True if hit wall clock, not product issue
    num_steps: int
    elapsed_s: float
    final_url: str
    error: str | None
    trace: list
    actions: list


def log(msg: str) -> None:
    print(f"[bakeoff] {msg}", flush=True)


async def run_single_task(
    study_id: str,
    product_key: str,
    persona: dict,
    task: dict,
    semaphore: asyncio.Semaphore,
    login_state: dict,  # Shared login state per product
) -> RunResult:
    """Run a single task for a persona on a product."""
    from mvp.browser_agent import run_browser_agent
    
    product = PRODUCTS[product_key]
    agent_id = f"{task['id']}__{persona['id']}__{product_key}"
    
    # Determine start URL
    if task.get("requires_login") and not login_state.get(product_key):
        # Skip dashboard tasks if not logged in
        return RunResult(
            agent_id=agent_id,
            product=product_key,
            persona_id=persona["id"],
            persona_name=persona["name"],
            task_id=task["id"],
            task_title=task["title"],
            success=False,
            completed=False,
            harness_timeout=False,
            num_steps=0,
            elapsed_s=0,
            final_url="",
            error="Skipped: requires login but signup not complete",
            trace=[],
            actions=[],
        )
    
    start_url = product["dashboard"] if task.get("requires_login") else product["url"]
    
    async with semaphore:
        log(f"Starting {persona['name']} on {product['name']}: {task['title']}")
        start = time.time()
        harness_timeout = False
        
        try:
            result = await asyncio.wait_for(
                run_browser_agent(
                    study_id=study_id,
                    agent_id=agent_id,
                    url=start_url,
                    task_prompt=task["prompt"],
                    persona=persona,
                    segment=f"Evaluating {product['name']} voice AI platform",
                    max_steps=MAX_STEPS,
                    local=True,
                ),
                timeout=WALL_TIMEOUT_S + 30,  # Extra buffer for cleanup
            )
            
            elapsed = time.time() - start
            completed = result.get("completed", False)
            
            # Check if we hit the agent wall (harness timeout, not product failure)
            if not completed and elapsed >= WALL_TIMEOUT_S * 0.9:
                harness_timeout = True
            
            # Mark signup complete if successful
            if task.get("is_signup") and completed:
                login_state[product_key] = True
                log(f"  ✓ Signup complete for {product['name']}")
            
            success = completed and not harness_timeout
            status = "✓" if success else ("⏱" if harness_timeout else "✗")
            log(f"  {status} {persona['name']} on {product['name']}: {task['title']} ({result.get('num_steps', 0)} steps, {elapsed:.0f}s)")
            
            return RunResult(
                agent_id=agent_id,
                product=product_key,
                persona_id=persona["id"],
                persona_name=persona["name"],
                task_id=task["id"],
                task_title=task["title"],
                success=success,
                completed=completed,
                harness_timeout=harness_timeout,
                num_steps=result.get("num_steps", 0),
                elapsed_s=elapsed,
                final_url=result.get("final_url", ""),
                error=None,
                trace=result.get("trace", []),
                actions=result.get("actions", []),
            )
            
        except asyncio.TimeoutError:
            elapsed = time.time() - start
            log(f"  ⏱ {persona['name']} on {product['name']}: {task['title']} - HARNESS TIMEOUT ({elapsed:.0f}s)")
            return RunResult(
                agent_id=agent_id,
                product=product_key,
                persona_id=persona["id"],
                persona_name=persona["name"],
                task_id=task["id"],
                task_title=task["title"],
                success=False,
                completed=False,
                harness_timeout=True,
                num_steps=0,
                elapsed_s=elapsed,
                final_url="",
                error="Harness timeout",
                trace=[],
                actions=[],
            )
            
        except Exception as e:
            elapsed = time.time() - start
            log(f"  ✗ {persona['name']} on {product['name']}: {task['title']} - ERROR: {e!r}")
            return RunResult(
                agent_id=agent_id,
                product=product_key,
                persona_id=persona["id"],
                persona_name=persona["name"],
                task_id=task["id"],
                task_title=task["title"],
                success=False,
                completed=False,
                harness_timeout=False,
                num_steps=0,
                elapsed_s=elapsed,
                final_url="",
                error=str(e),
                trace=[],
                actions=[],
            )


async def run_product_tasks(
    study_id: str,
    product_key: str,
    personas: list,
    tasks: list,
) -> list[RunResult]:
    """Run all tasks for all personas on a single product."""
    product = PRODUCTS[product_key]
    log(f"\n=== Starting {product['name']} ===")
    
    # Semaphore for sequential execution within a product
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_PER_PRODUCT)
    login_state = {}  # Track if signup completed (unused now since all public tasks)
    
    results = []
    
    # Run all personas through all tasks
    for persona in personas:
        for task in tasks:
            result = await run_single_task(
                study_id, product_key, persona, task, semaphore, login_state
            )
            results.append(result)
    
    return results


async def run_bakeoff():
    """Run the full bakeoff comparison."""
    study_id = f"voice-bakeoff-{uuid.uuid4().hex[:8]}"
    
    log("=" * 60)
    log("VOICE AI PLATFORM BAKEOFF")
    log("=" * 60)
    log(f"Study ID: {study_id}")
    log(f"Products: {', '.join(p['name'] for p in PRODUCTS.values())}")
    log(f"Personas: {len(PERSONAS)}")
    log(f"Tasks: {len(TASKS)}")
    log(f"Max steps per run: {MAX_STEPS}")
    log(f"Wall timeout: {WALL_TIMEOUT_S}s ({WALL_TIMEOUT_S // 60} min)")
    log("")
    
    # Create output directory
    from mvp.paths import MVP_RUNS_DIR
    run_dir = MVP_RUNS_DIR / study_id
    run_dir.mkdir(parents=True, exist_ok=True)
    
    start_time = time.time()
    
    # Run all products in parallel
    product_tasks = [
        run_product_tasks(study_id, product_key, PERSONAS, TASKS)
        for product_key in PRODUCTS.keys()
    ]
    
    all_results_by_product = await asyncio.gather(*product_tasks)
    
    # Flatten results
    all_results = []
    for results in all_results_by_product:
        all_results.extend(results)
    
    elapsed = time.time() - start_time
    
    # Build summary
    log("\n" + "=" * 60)
    log("BAKEOFF COMPLETE")
    log("=" * 60)
    log(f"Total time: {elapsed:.0f}s ({elapsed / 60:.1f} min)")
    log(f"Total runs: {len(all_results)}")
    
    # Stats by product
    for product_key, product in PRODUCTS.items():
        product_results = [r for r in all_results if r.product == product_key]
        successes = sum(1 for r in product_results if r.success)
        timeouts = sum(1 for r in product_results if r.harness_timeout)
        failures = sum(1 for r in product_results if not r.success and not r.harness_timeout)
        log(f"\n{product['name']}:")
        log(f"  ✓ Success: {successes}")
        log(f"  ⏱ Harness timeout: {timeouts}")
        log(f"  ✗ Product failure: {failures}")
    
    # Build study data
    study_data = {
        "id": study_id,
        "type": "voice_bakeoff",
        "products": PRODUCTS,
        "personas": PERSONAS,
        "tasks": TASKS,
        "status": "complete",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
        "elapsed_s": elapsed,
        "agent_results": [
            {
                "agent_id": r.agent_id,
                "product": r.product,
                "product_name": PRODUCTS[r.product]["name"],
                "persona_id": r.persona_id,
                "persona_name": r.persona_name,
                "task_id": r.task_id,
                "task_title": r.task_title,
                "success": r.success,
                "completed": r.completed,
                "harness_timeout": r.harness_timeout,
                "num_steps": r.num_steps,
                "elapsed_s": r.elapsed_s,
                "final_url": r.final_url,
                "error": r.error,
                "trace": r.trace,
            }
            for r in all_results
        ],
        "summary": {
            "total_runs": len(all_results),
            "by_product": {
                product_key: {
                    "name": product["name"],
                    "success": sum(1 for r in all_results if r.product == product_key and r.success),
                    "harness_timeout": sum(1 for r in all_results if r.product == product_key and r.harness_timeout),
                    "failure": sum(1 for r in all_results if r.product == product_key and not r.success and not r.harness_timeout),
                }
                for product_key, product in PRODUCTS.items()
            },
        },
    }
    
    # Save results
    output_path = ROOT / "mvp" / "experiment_results" / f"{study_id}_result.json"
    output_path.parent.mkdir(exist_ok=True)
    output_path.write_text(json.dumps(study_data, indent=2, default=str))
    log(f"\nSaved to: {output_path}")
    
    # Also save to run directory
    (run_dir / "study.json").write_text(json.dumps(study_data, indent=2, default=str))
    
    return study_data


async def main():
    """Entry point."""
    result = await run_bakeoff()
    
    if result:
        log("\n" + "=" * 60)
        log("STUDY COMPLETE")
        log("=" * 60)
        log(f"Study ID: {result.get('id')}")
        log(f"View at: http://localhost:3000/study/{result.get('id')}")
        log(f"API: http://localhost:3000/api/experiment/{result.get('id')}")
    
    return result


if __name__ == "__main__":
    asyncio.run(main())
