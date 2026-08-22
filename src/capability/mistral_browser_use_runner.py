"""Browser Use + Mistral multimodal API (Pixtral / Medium) for hackathon evals."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path

from browser_use import Agent, ChatOpenAI
from browser_use.browser.profile import BrowserProfile

from capability import CAPABLE_AGENT_PREAMBLE, MAX_ACTIONS, OUT_DIR, USER_AGENT, VIEWPORT
from capability.browser_use_runner import _history_to_actions
from capability.judge import judge_task
from capability.mistral_config import (
    DEFAULT_MISTRAL_MODEL,
    MISTRAL_API_BASE,
    mistral_api_key,
    mistral_cost_usd,
)


async def _run_async(
    task: dict, model: str, max_actions: int, run_dir: Path
) -> dict:
    run_id = run_dir.name
    run_dir.mkdir(parents=True, exist_ok=True)

    llm = ChatOpenAI(
        model=model,
        api_key=mistral_api_key(),
        base_url=MISTRAL_API_BASE,
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
    history = await agent.run(max_steps=max_actions)

    actions = _history_to_actions(history)
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

    prompt_tokens = output_tokens = 0
    try:
        usage = history.usage if hasattr(history, "usage") else None
        if usage:
            prompt_tokens = int(
                getattr(usage, "total_prompt_tokens", 0) or getattr(usage, "prompt_tokens", 0) or 0
            )
            output_tokens = int(
                getattr(usage, "total_completion_tokens", 0)
                or getattr(usage, "completion_tokens", 0)
                or 0
            )
    except Exception:
        pass

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
        if status in {"BLOCKED", "SITE_CHANGED"}:
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
        "provider": "mistral",
        "observation_mode": "browser_use_dom_vision",
        "start_url": task["start_url"],
        "actions": actions,
        "num_actions": len(actions),
        "stop_reason": "agent_done" if is_done else ("max_actions" if len(actions) >= max_actions else "unknown"),
        "success": success,
        "status": status,
        "judge_reason": judgment.get("reason"),
        "judge_evidence": judgment.get("evidence"),
        "failure_category": failure_category,
        "final_url": final_url,
        "final_title": end_title,
        "input_tokens": prompt_tokens,
        "output_tokens": output_tokens,
        "estimated_cost_usd": mistral_cost_usd(model, prompt_tokens, output_tokens)
        + float(judgment.get("estimated_cost_usd") or 0),
        "trace_dir": str(run_dir),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    (run_dir / "run.json").write_text(__import__("json").dumps(out, indent=2, default=str))
    try:
        (run_dir / "history.txt").write_text(str(history)[:50000])
    except Exception:
        pass
    return out


def run_mistral_browser_use(
    task: dict,
    model: str = DEFAULT_MISTRAL_MODEL,
    max_actions: int = MAX_ACTIONS,
    run_dir: Path | None = None,
) -> dict:
    run_dir = run_dir or (OUT_DIR / "traces" / f"mistral_{task['eval_index']}_{uuid.uuid4().hex[:8]}")
    return asyncio.run(_run_async(task, model, max_actions, run_dir))
