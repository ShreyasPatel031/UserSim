"""Stack B: Gemini via ChatGoogle(vertexai=True) + open-source Browser Use."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path

from browser_use import Agent, ChatGoogle
from browser_use.browser.profile import BrowserProfile

from auth import vertex_credentials
from capability import (
    BAKEOFF_MODEL,
    CAPABLE_AGENT_PREAMBLE,
    MAX_ACTIONS,
    OUT_DIR,
    USER_AGENT,
    VIEWPORT,
    cost_usd,
    location_for,
)
from capability.judge import JUDGE_ERROR, judge_task
from config import GCP_PROJECT
from capability.site_preflight import PreflightResult, preflight_start_url


def task_wall_timeout_s(max_actions: int) -> float:
    """Per-task wall clock cap so hung Chromium does not freeze a shard."""
    return float(max_actions) * 40.0 + 120.0


def _preflight_blocked_result(
    task: dict,
    model: str,
    run_dir: Path,
    pf: PreflightResult,
    *,
    run_id: str,
) -> dict:
    if pf.screenshot:
        (run_dir / "preflight.png").write_bytes(pf.screenshot)
    return {
        "run_id": run_id,
        "task_id": task["task_id"],
        "eval_index": task["eval_index"],
        "task": task["task"],
        "website": task["website"],
        "model": model,
        "harness": "browser_use_oss",
        "provider": "vertex",
        "observation_mode": "browser_use_dom_vision",
        "start_url": task["start_url"],
        "actions": [],
        "num_actions": 0,
        "stop_reason": f"preflight_blocked:{pf.reason}",
        "success": False,
        "status": "BLOCKED",
        "judge_reason": pf.reason,
        "judge_evidence": pf.title or pf.final_url,
        "failure_category": "BLOCKED",
        "final_url": pf.final_url,
        "final_title": pf.title,
        "input_tokens": 0,
        "output_tokens": 0,
        "estimated_cost_usd": 0.0,
        "trace_dir": str(run_dir),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def _history_to_actions(history) -> list[dict]:
    actions = []
    try:
        # AgentHistoryList API varies; be defensive
        items = list(getattr(history, "history", None) or history or [])
    except Exception:
        items = []
    for i, h in enumerate(items, start=1):
        model_out = getattr(h, "model_output", None)
        result = getattr(h, "result", None)
        url = None
        state = getattr(h, "state", None)
        if state is not None:
            url = getattr(state, "url", None)
        act = None
        if model_out is not None:
            act = getattr(model_out, "action", None) or getattr(model_out, "actions", None)
            if act is not None and not isinstance(act, (str, dict, list)):
                try:
                    act = [a.model_dump() if hasattr(a, "model_dump") else str(a) for a in (act if isinstance(act, list) else [act])]
                except Exception:
                    act = str(act)
        actions.append(
            {
                "i": i,
                "action": act,
                "result": str(result)[:500] if result is not None else None,
                "url": url,
            }
        )
    return actions


async def _run_async(
    task: dict, model: str, max_actions: int, run_dir: Path, location: str | None = None, *, preflight: bool = True
) -> dict:
    run_id = run_dir.name
    run_dir.mkdir(parents=True, exist_ok=True)
    loc = location or location_for(model)

    if preflight:
        pf = await preflight_start_url(task["start_url"])
        if pf.blocked:
            out = _preflight_blocked_result(task, model, run_dir, pf, run_id=run_id)
            (run_dir / "run.json").write_text(__import__("json").dumps(out, indent=2, default=str))
            return out

    creds = vertex_credentials()
    llm = ChatGoogle(
        model=model,
        vertexai=True,
        credentials=creds,
        project=GCP_PROJECT,
        location=loc,
        temperature=0,
    )
    profile = BrowserProfile(
        headless=True,
        viewport=VIEWPORT,
        user_agent=USER_AGENT,
        disable_security=True,
    )
    agent_task = (
        f"{CAPABLE_AGENT_PREAMBLE}\n\n"
        f"Open {task['start_url']} if not already there.\n"
        f"Task: {task['task']}\n"
        f"Satisfy every constraint. Stop only when fully done."
    )
    agent = Agent(
        task=agent_task,
        llm=llm,
        browser_profile=profile,
        use_vision=True,
        max_actions_per_step=3,
        calculate_cost=True,
        extend_system_message=(
            "You are optimizing for task completion, not human imitation. "
            "Apply all required filters and finish the stated goal."
        ),
        save_conversation_path=str(run_dir / "conversation"),
    )
    wall_s = task_wall_timeout_s(max_actions)
    try:
        history = await asyncio.wait_for(agent.run(max_steps=max_actions), timeout=wall_s)
    except asyncio.TimeoutError:
        out = {
            "run_id": run_id,
            "task_id": task["task_id"],
            "eval_index": task["eval_index"],
            "task": task["task"],
            "website": task["website"],
            "model": model,
            "harness": "browser_use_oss",
            "provider": "vertex",
            "observation_mode": "browser_use_dom_vision",
            "start_url": task["start_url"],
            "actions": [],
            "num_actions": 0,
            "stop_reason": f"task_wall_timeout:{int(wall_s)}s",
            "success": False,
            "status": "FAILURE",
            "failure_category": "HARNESS",
            "final_url": task["start_url"],
            "input_tokens": 0,
            "output_tokens": 0,
            "estimated_cost_usd": 0.0,
            "trace_dir": str(run_dir),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        (run_dir / "run.json").write_text(__import__("json").dumps(out, indent=2, default=str))
        print(
            f"TIMEOUT browser_use | {task['website']} | idx={task['eval_index']} | "
            f"task_wall_timeout:{int(wall_s)}s",
            flush=True,
        )
        return out

    actions = _history_to_actions(history)
    # Extract URLs / final state
    final_url = ""
    try:
        final_url = history.urls()[-1] if hasattr(history, "urls") and history.urls() else ""
    except Exception:
        final_url = actions[-1].get("url") or "" if actions else ""
    is_done = False
    try:
        is_done = bool(history.is_done()) if hasattr(history, "is_done") else False
    except Exception:
        pass

    # Token / cost if available
    prompt_tokens = output_tokens = 0
    try:
        usage = history.usage if hasattr(history, "usage") else None
        if usage:
            prompt_tokens = int(getattr(usage, "total_prompt_tokens", 0) or getattr(usage, "prompt_tokens", 0) or 0)
            output_tokens = int(getattr(usage, "total_completion_tokens", 0) or getattr(usage, "completion_tokens", 0) or 0)
    except Exception:
        pass

    # Final screenshot via a quick playwright open of final_url if needed
    screenshot = None
    end_title = ""
    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(viewport=VIEWPORT, user_agent=USER_AGENT)
            if final_url:
                await page.goto(final_url, wait_until="domcontentloaded", timeout=20000)
                await page.wait_for_timeout(500)
                end_title = await page.title()
                screenshot = await page.screenshot(type="png")
                (run_dir / "final.png").write_bytes(screenshot)
            await browser.close()
    except Exception as exc:  # noqa: BLE001
        (run_dir / "screenshot_error.txt").write_text(str(exc)[:400])

    summary_lines = []
    for a in actions:
        summary_lines.append(f"{a['i']}. {a.get('action')} -> {a.get('result')} @ {a.get('url')}")
    if is_done:
        summary_lines.append("(agent signaled done)")
    judgment = judge_task(
        task["task"], final_url or task["start_url"], "\n".join(summary_lines), screenshot, end_title
    )
    prompt_tokens += judgment.get("prompt_tokens", 0)
    output_tokens += judgment.get("output_tokens", 0)
    status = judgment["status"]
    success = status == "SUCCESS"

    failure_category = None
    if not success:
        if status in {"BLOCKED", "SITE_CHANGED", JUDGE_ERROR}:
            failure_category = status
        elif len(actions) >= max_actions:
            failure_category = "PLANNING"
        elif is_done:
            failure_category = "PREMATURE_STOP"
        else:
            failure_category = "MODEL_REASONING"

    out = {
        "run_id": run_id,
        "task_id": task["task_id"],
        "eval_index": task["eval_index"],
        "task": task["task"],
        "website": task["website"],
        "model": model,
        "harness": "browser_use_oss",
        "provider": "vertex",
        "observation_mode": "browser_use_dom_vision",
        "start_url": task["start_url"],
        "actions": actions,
        "num_actions": len(actions),
        "stop_reason": (
            "max_actions"
            if len(actions) >= max_actions
            else "agent_done"
            if is_done
            else "unknown"
        ),
        "success": success,
        "status": status,
        "judge_reason": judgment.get("reason"),
        "judge_evidence": judgment.get("evidence"),
        "failure_category": failure_category,
        "final_url": final_url,
        "final_title": end_title,
        "input_tokens": prompt_tokens,
        "output_tokens": output_tokens,
        "estimated_cost_usd": cost_usd(model, prompt_tokens, output_tokens)
        + float(judgment.get("estimated_cost_usd") or 0),
        "trace_dir": str(run_dir),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    (run_dir / "run.json").write_text(__import__("json").dumps(out, indent=2, default=str))
    # stash history string
    try:
        (run_dir / "history.txt").write_text(str(history)[:50000])
    except Exception:
        pass
    return out


def run_browser_use(
    task: dict,
    model: str = BAKEOFF_MODEL,
    max_actions: int = MAX_ACTIONS,
    run_dir: Path | None = None,
    location: str | None = None,
    *,
    preflight: bool = True,
) -> dict:
    run_dir = run_dir or (OUT_DIR / "traces" / f"bu_{task['eval_index']}_{uuid.uuid4().hex[:8]}")
    return asyncio.run(_run_async(task, model, max_actions, run_dir, location=location, preflight=preflight))
