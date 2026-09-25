"""Experiment runner: define and execute product studies from JSON specs.

Experiment spec format:
{
    "id": "retell-study-2026",
    "product_name": "Retell AI",
    "product_url": "https://www.retellai.com",
    "lede": "Voice AI platform UX study...",
    "comparison_note": "Compared against Bland AI and Vapi data...",
    "personas": [
        {
            "id": "p1_dev",
            "name": "Alex Rivera",
            "bio": "Platform engineer setting up voice AI...",
            "occupation": "Platform Engineer"
        }
    ],
    "tasks": [
        {
            "id": "t1_create_agent",
            "title": "Create a voice agent",
            "prompt": "As a first-time user, navigate to create a new voice agent...",
            "success_criteria": "Agent creation form is visible",
            "journey": "J1"
        }
    ],
    "assignments": [
        {"persona_id": "p1_dev", "task_id": "t1_create_agent"},
        {"persona_id": "p1_dev", "task_id": "t2_configure_voice"}
    ],
    "config": {
        "max_steps": 25,
        "timeout_s": 180,
        "browserbase_owner": "report"
    }
}
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

EXPERIMENTS_DIR = Path(__file__).resolve().parent / "experiments"
EXPERIMENTS_DIR.mkdir(exist_ok=True)

RESULTS_DIR = Path(__file__).resolve().parent / "experiment_results"
RESULTS_DIR.mkdir(exist_ok=True)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ExperimentSpec:
    id: str
    product_name: str
    product_url: str
    lede: str = ""
    comparison_note: str = ""
    personas: list[dict] = field(default_factory=list)
    tasks: list[dict] = field(default_factory=list)
    assignments: list[dict] = field(default_factory=list)
    config: dict = field(default_factory=dict)
    
    @classmethod
    def from_dict(cls, data: dict) -> "ExperimentSpec":
        return cls(
            id=data.get("id") or str(uuid.uuid4())[:8],
            product_name=data.get("product_name", "Product"),
            product_url=data.get("product_url", ""),
            lede=data.get("lede", ""),
            comparison_note=data.get("comparison_note", ""),
            personas=data.get("personas", []),
            tasks=data.get("tasks", []),
            assignments=data.get("assignments", []),
            config=data.get("config", {}),
        )
    
    @classmethod
    def from_file(cls, path: str | Path) -> "ExperimentSpec":
        path = Path(path)
        data = json.loads(path.read_text())
        return cls.from_dict(data)
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "product_name": self.product_name,
            "product_url": self.product_url,
            "lede": self.lede,
            "comparison_note": self.comparison_note,
            "personas": self.personas,
            "tasks": self.tasks,
            "assignments": self.assignments,
            "config": self.config,
        }
    
    def save(self, path: str | Path | None = None) -> Path:
        if path is None:
            path = EXPERIMENTS_DIR / f"{self.id}.json"
        path = Path(path)
        path.write_text(json.dumps(self.to_dict(), indent=2))
        return path


@dataclass
class ExperimentResult:
    spec: ExperimentSpec
    status: str = "pending"
    created_at: str = field(default_factory=_now)
    completed_at: str | None = None
    agent_results: list[dict] = field(default_factory=list)
    error: str | None = None
    credits_used: dict = field(default_factory=dict)
    
    def to_study_dict(self) -> dict:
        """Convert to the format expected by study_report.js"""
        return {
            "id": self.spec.id,
            "url": self.spec.product_url,
            "product_name": self.spec.product_name,
            "lede": self.spec.lede,
            "comparison_note": self.spec.comparison_note,
            "segment": self.spec.lede,
            "status": self.status,
            "phase": "Complete" if self.status == "complete" else self.status.title(),
            "created_at": self.created_at,
            "updated_at": self.completed_at or _now(),
            "personas": self.spec.personas,
            "tasks": [
                {
                    "id": t["id"],
                    "title": t.get("title", t["id"]),
                    "prompt": t.get("prompt", ""),
                    "persona_id": next(
                        (a["persona_id"] for a in self.spec.assignments if a["task_id"] == t["id"]),
                        None
                    ),
                }
                for t in self.spec.tasks
            ],
            "agent_results": self.agent_results,
            "live_sessions": {},
            "summary": self._build_summary(),
            "error": self.error,
            "credits_used": self.credits_used,
        }
    
    def _build_summary(self) -> dict:
        if not self.agent_results:
            return {}
        
        friction = []
        strengths = []
        for r in self.agent_results:
            for d in r.get("dislikes") or r.get("friction_points") or []:
                if d and d not in friction:
                    friction.append(d)
            for lk in r.get("likes") or r.get("what_was_easy") or []:
                if lk and lk not in strengths:
                    strengths.append(lk)
        
        success_count = sum(1 for r in self.agent_results if r.get("success"))
        total = len(self.agent_results)
        
        return {
            "headline": f"{self.spec.product_name} study: {success_count}/{total} tasks completed",
            "top_friction": friction[:5],
            "top_strengths": strengths[:5],
            "segment_fit_score": round(10 * success_count / max(1, total)),
            "segment_fit_rationale": f"Based on {total} simulated user sessions",
            "conversion_outlook": f"{success_count} of {total} users completed their tasks",
            "recommendations": [],
        }
    
    def save(self, path: str | Path | None = None) -> Path:
        if path is None:
            path = RESULTS_DIR / f"{self.spec.id}_result.json"
        path = Path(path)
        path.write_text(json.dumps(self.to_study_dict(), indent=2))
        return path


class ExperimentRunner:
    """Run experiments with real browsers or dry-run mode."""
    
    def __init__(
        self,
        spec: ExperimentSpec,
        *,
        dry_run: bool = False,
        max_concurrent: int = 2,
        browserbase_owner: str = "report",
        on_progress: Callable[[str, dict], None] | None = None,
    ):
        self.spec = spec
        self.dry_run = dry_run
        self.max_concurrent = max_concurrent
        self.browserbase_owner = browserbase_owner
        self.on_progress = on_progress or (lambda msg, data: None)
        self.result = ExperimentResult(spec=spec)
        self._semaphore = asyncio.Semaphore(max_concurrent)
    
    def _log(self, msg: str, **data: Any) -> None:
        print(f"[experiment:{self.spec.id}] {msg}", flush=True)
        self.on_progress(msg, data)
    
    async def run(self) -> ExperimentResult:
        """Execute all assignments in the experiment."""
        self.result.status = "running"
        self._log(f"Starting experiment: {self.spec.product_name}", 
                  assignments=len(self.spec.assignments), dry_run=self.dry_run)
        
        try:
            tasks = []
            for assignment in self.spec.assignments:
                persona = next(
                    (p for p in self.spec.personas if p["id"] == assignment["persona_id"]),
                    {"id": assignment["persona_id"], "name": assignment["persona_id"]}
                )
                task = next(
                    (t for t in self.spec.tasks if t["id"] == assignment["task_id"]),
                    {"id": assignment["task_id"], "title": assignment["task_id"], "prompt": ""}
                )
                tasks.append(self._run_assignment(persona, task))
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for r in results:
                if isinstance(r, Exception):
                    self._log(f"Assignment failed: {r!r}")
                    self.result.agent_results.append({
                        "status": "error",
                        "error": str(r),
                        "success": False,
                    })
                elif r:
                    self.result.agent_results.append(r)
            
            self.result.status = "complete"
            self.result.completed_at = _now()
            self._log(f"Experiment complete: {len(self.result.agent_results)} results")
            
        except Exception as exc:
            self.result.status = "error"
            self.result.error = str(exc)
            self._log(f"Experiment failed: {exc!r}")
        
        return self.result
    
    async def _run_assignment(self, persona: dict, task: dict) -> dict:
        """Run a single persona-task assignment."""
        async with self._semaphore:
            agent_id = f"{persona['id']}_{task['id']}"
            self._log(f"Running: {persona['name']} — {task['title']}", agent_id=agent_id)
            
            if self.dry_run:
                return await self._dry_run_assignment(persona, task)
            else:
                return await self._live_run_assignment(persona, task)
    
    async def _dry_run_assignment(self, persona: dict, task: dict) -> dict:
        """Simulate an assignment without real browser."""
        await asyncio.sleep(0.5)
        
        import random
        success = random.random() > 0.2
        num_actions = random.randint(3, 15)
        
        return {
            "agent_id": f"{persona['id']}_{task['id']}",
            "task_id": task["id"],
            "goal_key": task["id"],
            "persona_id": persona["id"],
            "persona_name": persona.get("name", persona["id"]),
            "task_title": task.get("title", task["id"]),
            "task_prompt": task.get("prompt", ""),
            "platform": self.spec.product_name.lower().replace(" ", "_"),
            "status": "complete",
            "success": success,
            "judge_status": "SUCCESS" if success else "FAIL",
            "final_url": self.spec.product_url,
            "num_actions": num_actions,
            "difficulty": random.choice(["easy", "medium", "hard"]),
            "likes": [f"[DRY RUN] {task['title']} was straightforward"] if success else [],
            "dislikes": [] if success else [f"[DRY RUN] Could not complete {task['title']}"],
            "friction_points": [] if success else ["[DRY RUN] Simulated friction"],
            "what_was_easy": [f"[DRY RUN] Navigation was clear"] if success else [],
            "trace": [
                {
                    "step": i,
                    "action": f"[DRY RUN] Step {i}",
                    "url": self.spec.product_url,
                    "screenshot_url": None,
                }
                for i in range(1, num_actions + 1)
            ],
            "dry_run": True,
        }
    
    async def _live_run_assignment(self, persona: dict, task: dict) -> dict:
        """Run assignment with real Browserbase browser."""
        from mvp.browser_agent import run_browser_agent
        from mvp.paths import MVP_RUNS_DIR
        
        study_id = f"exp_{self.spec.id}"
        agent_id = f"{persona['id']}_{task['id']}"
        
        config = self.spec.config or {}
        max_steps = config.get("max_steps", 25)
        timeout_s = config.get("timeout_s", 180)
        
        full_prompt = self._build_agent_prompt(persona, task)
        
        result_dir = MVP_RUNS_DIR / study_id / agent_id
        result_dir.mkdir(parents=True, exist_ok=True)
        
        persona_dict = {
            "id": persona.get("id"),
            "name": persona.get("name", persona["id"]),
            "bio": persona.get("bio", ""),
            "occupation": persona.get("occupation", "Professional"),
            "goals": persona.get("goals", []),
        }
        
        try:
            result = await asyncio.wait_for(
                run_browser_agent(
                    url=self.spec.product_url,
                    task_prompt=full_prompt,
                    persona=persona_dict,
                    segment=self.spec.lede or "Product evaluation",
                    study_id=study_id,
                    agent_id=agent_id,
                    max_steps=max_steps,
                ),
                timeout=timeout_s,
            )
            
            trace = result.get("trace") or []
            for i, step in enumerate(trace):
                if not step.get("screenshot_url"):
                    shot_path = result_dir / "screenshots" / f"bbox_{i+1}.png"
                    if shot_path.is_file():
                        step["screenshot_url"] = f"/api/experiment/{self.spec.id}/agents/{agent_id}/screenshots/bbox_{i+1}.png"
            
            return {
                "agent_id": agent_id,
                "task_id": task["id"],
                "goal_key": task["id"],
                "persona_id": persona["id"],
                "persona_name": persona.get("name", persona["id"]),
                "task_title": task.get("title", task["id"]),
                "task_prompt": task.get("prompt", ""),
                "platform": self.spec.product_name.lower().replace(" ", "_"),
                "status": "complete",
                "success": result.get("success", False),
                "judge_status": "SUCCESS" if result.get("success") else "FAIL",
                "final_url": result.get("final_url", self.spec.product_url),
                "num_actions": result.get("num_actions", len(trace)),
                "difficulty": result.get("difficulty", "medium"),
                "likes": result.get("likes") or result.get("what_was_easy") or [],
                "dislikes": result.get("dislikes") or result.get("friction_points") or [],
                "friction_points": result.get("friction_points") or [],
                "what_was_easy": result.get("what_was_easy") or [],
                "quote": result.get("quote", ""),
                "product_feedback": result.get("product_feedback", ""),
                "trace": trace,
                "judge_reason": result.get("judge_reason", ""),
            }
            
        except asyncio.TimeoutError:
            self._log(f"Timeout for {agent_id}", timeout_s=timeout_s)
            return {
                "agent_id": agent_id,
                "task_id": task["id"],
                "goal_key": task["id"],
                "persona_id": persona["id"],
                "persona_name": persona.get("name", persona["id"]),
                "task_title": task.get("title", task["id"]),
                "task_prompt": task.get("prompt", ""),
                "status": "timeout",
                "success": False,
                "judge_status": "TIMEOUT",
                "error": f"Timed out after {timeout_s}s",
                "trace": [],
            }
        except Exception as exc:
            self._log(f"Error for {agent_id}: {exc!r}")
            return {
                "agent_id": agent_id,
                "task_id": task["id"],
                "goal_key": task["id"],
                "persona_id": persona["id"],
                "persona_name": persona.get("name", persona["id"]),
                "task_title": task.get("title", task["id"]),
                "task_prompt": task.get("prompt", ""),
                "status": "error",
                "success": False,
                "judge_status": "ERROR",
                "error": str(exc),
                "trace": [],
            }
    
    def _build_agent_prompt(self, persona: dict, task: dict) -> str:
        """Build the full prompt for the browser agent."""
        persona_context = f"""You are {persona.get('name', 'a user')}.
{persona.get('bio', '')}
Occupation: {persona.get('occupation', 'Professional')}
"""
        
        task_prompt = task.get("prompt", task.get("title", "Explore the product"))
        success_criteria = task.get("success_criteria", "")
        
        full_prompt = f"""{persona_context}

YOUR TASK: {task_prompt}

{f'SUCCESS CRITERIA: {success_criteria}' if success_criteria else ''}

After completing (or if you get stuck), provide feedback:
1. What did you LIKE about this experience?
2. What did you DISLIKE or find frustrating?
3. How hard did this feel? (easy / medium / hard)

Use 'done' action when finished with a summary of what you accomplished.
"""
        return full_prompt


async def run_experiment(
    spec: ExperimentSpec | dict | str | Path,
    *,
    dry_run: bool = False,
    max_concurrent: int = 2,
    save_result: bool = True,
) -> ExperimentResult:
    """Convenience function to run an experiment."""
    if isinstance(spec, (str, Path)):
        spec = ExperimentSpec.from_file(spec)
    elif isinstance(spec, dict):
        spec = ExperimentSpec.from_dict(spec)
    
    runner = ExperimentRunner(spec, dry_run=dry_run, max_concurrent=max_concurrent)
    result = await runner.run()
    
    if save_result:
        result.save()
    
    return result


def load_experiment_result(experiment_id: str) -> dict | None:
    """Load a saved experiment result."""
    path = RESULTS_DIR / f"{experiment_id}_result.json"
    if path.is_file():
        return json.loads(path.read_text())
    
    for p in RESULTS_DIR.glob("*.json"):
        try:
            data = json.loads(p.read_text())
            if data.get("id") == experiment_id:
                return data
        except Exception:
            continue
    
    return None


def list_experiments() -> list[dict]:
    """List all experiment specs."""
    specs = []
    for path in EXPERIMENTS_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text())
            specs.append({
                "id": data.get("id", path.stem),
                "product_name": data.get("product_name", "Unknown"),
                "path": str(path),
            })
        except Exception:
            continue
    return specs


def list_experiment_results() -> list[dict]:
    """List all experiment results."""
    results = []
    for path in RESULTS_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text())
            results.append({
                "id": data.get("id", path.stem.replace("_result", "")),
                "product_name": data.get("product_name", "Unknown"),
                "status": data.get("status", "unknown"),
                "path": str(path),
            })
        except Exception:
            continue
    return results
