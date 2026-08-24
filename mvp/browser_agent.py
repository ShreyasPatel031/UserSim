"""Browser Use agent runs for MVP — screenshots with DOM bounding boxes."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from auth import vertex_credentials
from capability import CAPABLE_AGENT_PREAMBLE, USER_AGENT, VIEWPORT
from config import GCP_LOCATION, GCP_PROJECT, MODEL as GEMINI_MODEL

from mvp.paths import MVP_RUNS_DIR

# Enough steps to leave the landing page: land, scroll, open a nav item, read, come back.
MVP_MAX_STEPS = int(os.environ.get("MVP_MAX_BROWSER_STEPS", "12"))


def _history_to_actions(history) -> list[dict]:
    actions = []
    try:
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
                    act = [
                        a.model_dump() if hasattr(a, "model_dump") else str(a)
                        for a in (act if isinstance(act, list) else [act])
                    ]
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


def _mvp_browser_profile(headless: bool | None = None):
    from browser_use.browser.profile import BrowserProfile

    if headless is None:
        headless = os.environ.get("MVP_BROWSER_HEADLESS", "true").lower() not in {"0", "false", "no"}

    return BrowserProfile(
        headless=headless,
        viewport=VIEWPORT,
        user_agent=USER_AGENT,
        disable_security=True,
        cross_origin_iframes=False,
        enable_default_extensions=False,
        captcha_solver=False,
        highlight_elements=False,
        dom_highlight_elements=True,
        minimum_wait_page_load_time=float(os.environ.get("MVP_MIN_WAIT", "2.0")),
        wait_for_network_idle_page_load_time=float(os.environ.get("MVP_NETWORK_IDLE", "2.0")),
        wait_between_actions=0.5,
    )


def _trace_step_from_history_item(
    h: Any,
    step_no: int,
    *,
    study_id: str,
    agent_id: str,
    screenshot_dir: Path,
) -> dict[str, Any]:
    model_out = getattr(h, "model_output", None)
    state = getattr(h, "state", None)
    url = getattr(state, "url", None) if state else None
    shot_src = getattr(state, "screenshot_path", None) if state else None

    raw_action = None
    if model_out is not None:
        raw_action = getattr(model_out, "action", None) or getattr(model_out, "actions", None)
    action = _action_label(raw_action)
    observation = _result_text(getattr(h, "result", None))

    screenshot_name = None
    if (screenshot_dir / f"bbox_{step_no}.png").exists():
        screenshot_name = f"bbox_{step_no}.png"
    elif shot_src and Path(shot_src).exists():
        screenshot_name = f"step_{step_no}.png"
        shutil.copy2(shot_src, screenshot_dir / screenshot_name)

    thought_fields: dict[str, str] = {}
    if model_out:
        for field in ("thinking", "evaluation_previous_goal", "next_goal", "memory"):
            val = getattr(model_out, field, None)
            if val:
                thought_fields[field] = str(val).strip()
    thought_summary = (
        thought_fields.get("next_goal")
        or thought_fields.get("evaluation_previous_goal")
        or thought_fields.get("thinking")
        or ""
    )

    return {
        "step": step_no,
        "action": action,
        "observation": observation,
        "thought": thought_summary,
        "thought_detail": thought_fields,
        "url": url,
        "screenshot_url": (
            f"/api/studies/{study_id}/agents/{agent_id}/screenshots/{screenshot_name}"
            if screenshot_name
            else None
        ),
        "outcome": "neutral",
    }


def _make_step_hooks(
    screenshot_dir: Path,
    *,
    study_id: str,
    agent_id: str,
    on_step: Callable[[dict[str, Any]], Awaitable[None] | None] | None = None,
):
    """Capture a screenshot with DOM bounding boxes drawn on it, once per step.

    browser-use takes its own screenshot *before* injecting highlights (see
    DOMWatchdog.on_BrowserStateRequestEvent), so history screenshots are always clean.
    Re-injecting the overlay here is the only way to get boxed frames.
    """
    state = {"step": 0}

    async def on_step_end(agent: Any) -> None:
        state["step"] += 1
        step_no = state["step"]
        session = getattr(agent, "browser_session", None)
        if session is None:
            return
        try:
            # The cached selector map is stale once the step's action has run (often empty
            # after a navigation), so rebuild the state to get live element boxes.
            summary = await asyncio.wait_for(session.get_browser_state_summary(), timeout=25)
            selector_map = {}
            if summary is not None and getattr(summary, "dom_state", None) is not None:
                selector_map = summary.dom_state.selector_map or {}
            if not selector_map:
                selector_map = await asyncio.wait_for(session.get_selector_map(), timeout=10)
            if not selector_map:
                return
            await asyncio.wait_for(session.add_highlights(selector_map), timeout=10)
            await asyncio.sleep(0.3)
            await asyncio.wait_for(
                session.take_screenshot(path=str(screenshot_dir / f"bbox_{step_no}.png")),
                timeout=20,
            )
        except Exception:  # noqa: BLE001
            return
        finally:
            try:
                await asyncio.wait_for(session.remove_highlights(), timeout=5)
            except Exception:  # noqa: BLE001
                pass

        history = getattr(agent, "history", None)
        items = list(getattr(history, "history", None) or [])
        if not items:
            return
        step = _trace_step_from_history_item(
            items[-1],
            step_no,
            study_id=study_id,
            agent_id=agent_id,
            screenshot_dir=screenshot_dir,
        )
        if on_step is not None:
            maybe = on_step(step)
            if asyncio.iscoroutine(maybe):
                await maybe

    return on_step_end


def _action_label(action: Any) -> str:
    """Render a browser-use action as human-readable text, not a pydantic repr."""
    if action is None:
        return "—"
    if isinstance(action, list):
        return "; ".join(_action_label(a) for a in action)

    payload = action
    root = getattr(payload, "root", None)
    if root is not None:
        payload = root
    dumped = payload.model_dump(exclude_none=True) if hasattr(payload, "model_dump") else None
    if not isinstance(dumped, dict) or not dumped:
        return str(action)[:300]

    name, args = next(iter(dumped.items()))
    if not isinstance(args, dict):
        return f"{name}: {args}"[:300]
    detail = ", ".join(f"{k}={v}" for k, v in args.items() if v not in (None, "", False))
    return (f"{name} — {detail}" if detail else name)[:300]


def _result_text(result: Any) -> str:
    if not result:
        return ""
    items = result if isinstance(result, list) else [result]
    parts: list[str] = []
    for item in items:
        extracted = getattr(item, "extracted_content", None)
        if extracted:
            parts.append(str(extracted)[:400])
            continue
        memory = getattr(item, "long_term_memory", None)
        if memory:
            parts.append(str(memory)[:400])
            continue
        parts.append(str(item)[:300])
    return " | ".join(parts)


def _history_to_trace(
    history,
    *,
    study_id: str,
    agent_id: str,
    screenshot_dir: Path,
) -> list[dict[str, Any]]:
    trace: list[dict[str, Any]] = []
    items = list(getattr(history, "history", None) or [])
    for i, h in enumerate(items, start=1):
        trace.append(
            _trace_step_from_history_item(
                h, i, study_id=study_id, agent_id=agent_id, screenshot_dir=screenshot_dir
            )
        )
    return trace


async def run_browser_agent(
    *,
    study_id: str,
    agent_id: str,
    url: str,
    task_prompt: str,
    persona: dict[str, Any],
    segment: str,
    model: str | None = None,
    max_steps: int | None = None,
    headless: bool | None = None,
    on_step: Callable[[dict[str, Any]], Awaitable[None] | None] | None = None,
) -> dict[str, Any]:
    """Run Browser Use with a local Chromium session; return actions + bbox screenshot trace."""
    from browser_use import Agent
    from browser_use.llm.google import ChatGoogle

    model = model or GEMINI_MODEL
    if max_steps is None:
        max_steps = MVP_MAX_STEPS
    os.environ.setdefault("BROWSER_USE_ACTION_TIMEOUT_S", "240")

    run_dir = MVP_RUNS_DIR / study_id / agent_id
    screenshot_dir = run_dir / "screenshots"
    run_dir.mkdir(parents=True, exist_ok=True)
    screenshot_dir.mkdir(parents=True, exist_ok=True)

    session_url = None
    llm = ChatGoogle(
        model=model,
        vertexai=True,
        project=GCP_PROJECT,
        location=GCP_LOCATION,
        credentials=vertex_credentials(),
        temperature=0,
        max_retries=int(os.environ.get("MVP_LLM_MAX_RETRIES", "6")),
    )
    profile = _mvp_browser_profile(headless)
    persona_line = f"You are {persona.get('name')}: {persona.get('bio')}"
    agent_task = (
        f"{CAPABLE_AGENT_PREAMBLE}\n\n"
        f"{persona_line}\n"
        f"Customer segment: {segment}\n"
        f"Open {url} if not already there.\n"
        f"Task: {task_prompt}\n"
        f"Behave like this persona would — note confusion, pricing concerns, and UX friction.\n"
        f"Do not judge the site from the landing page alone. If the answer is not visible, "
        f"click into the nav links (blog, docs, use cases, about, pricing) and read the real "
        f"pages before forming an opinion. Only conclude something is missing after you have "
        f"actually looked for it.\n"
        f"Stop when the task is done or you would realistically give up."
    )
    agent = Agent(
        task=agent_task,
        llm=llm,
        browser_profile=profile,
        use_vision=True,
        use_judge=False,
        max_actions_per_step=2,
        calculate_cost=True,
        file_system_path=str(run_dir),
        save_conversation_path=str(run_dir / "conversation"),
        extend_system_message=(
            "You are a real user in a usability study, not an optimizer. "
            "Prefer obvious UI paths; comment on clarity and trust."
        ),
    )
    history = await agent.run(
        max_steps=max_steps,
        on_step_end=_make_step_hooks(
            screenshot_dir,
            study_id=study_id,
            agent_id=agent_id,
            on_step=on_step,
        ),
    )

    actions = _history_to_actions(history)
    trace = _history_to_trace(
        history, study_id=study_id, agent_id=agent_id, screenshot_dir=screenshot_dir
    )

    final_url = ""
    try:
        urls = history.urls() if hasattr(history, "urls") else []
        final_url = urls[-1] if urls else ""
    except Exception:
        final_url = actions[-1].get("url") or url if actions else url

    is_done = False
    try:
        is_done = bool(history.is_done()) if hasattr(history, "is_done") else False
    except Exception:
        pass

    visited_urls: list[str] = []
    for step in trace:
        step_url = step.get("url")
        if step_url and step_url not in visited_urls:
            visited_urls.append(step_url)

    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "study_id": study_id,
                "agent_id": agent_id,
                "task_prompt": task_prompt,
                "persona": persona,
                "actions": actions,
                "trace": trace,
                "final_url": final_url,
                "visited_urls": visited_urls,
                "completed": is_done,
                "browserbase_session_url": session_url,
            },
            indent=2,
            default=str,
        )
    )

    return {
        "agent_id": agent_id,
        "persona_id": persona.get("id"),
        "task_id": agent_id,
        "completed": is_done,
        "final_url": final_url,
        "visited_urls": visited_urls,
        "actions": actions,
        "trace": trace,
        "browserbase_session_url": session_url,
        "run_dir": str(run_dir),
        "num_steps": len(trace),
    }
