"""Browser Use agent runs for MVP — screenshots with DOM bounding boxes."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from capability import CAPABLE_AGENT_PREAMBLE, USER_AGENT, VIEWPORT
from capability.browserbase_client import close_session, create_session
from capability.mistral_config import MISTRAL_API_BASE, mistral_api_key, mistral_model

from mvp.paths import MVP_RUNS_DIR

# Enough steps to leave the landing page: land, scroll, open a nav item, read, come back.
MVP_MAX_STEPS = int(os.environ.get("MVP_MAX_BROWSER_STEPS", "12"))


def _history_to_actions(history) -> list[dict]:
    actions: list[dict] = []
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
    if isinstance(dumped, dict) and dumped:
        name, args = next(iter(dumped.items()))
        if isinstance(args, dict):
            detail = ", ".join(f"{k}={v}" for k, v in args.items() if v not in (None, "", False))
            return (f"{name} — {detail}" if detail else name)[:300]
        return f"{name}: {args}"[:300]
    if isinstance(action, dict) and action:
        name, args = next(iter(action.items()))
        if isinstance(args, dict):
            detail = ", ".join(f"{k}={v}" for k, v in args.items() if v not in (None, "", False))
            return (f"{name} — {detail}" if detail else str(name))[:300]
        return f"{name}: {args}"[:300]
    return str(action)[:300]


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
        memory = getattr(item, "long_term_memory", None) or getattr(item, "memory", None)
        if memory:
            parts.append(str(memory)[:400])
            continue
        parts.append(str(item)[:300])
    return " | ".join(parts)


def _browserbase_profile(cdp_url: str):
    from browser_use.browser.profile import BrowserProfile

    from mvp.captcha import captcha_solver_enabled

    return BrowserProfile(
        cdp_url=cdp_url,
        is_local=False,
        viewport=VIEWPORT,
        user_agent=USER_AGENT,
        disable_security=True,
        cross_origin_iframes=False,
        enable_default_extensions=False,
        captcha_solver=captcha_solver_enabled(),
        highlight_elements=False,
        dom_highlight_elements=True,
        minimum_wait_page_load_time=float(os.environ.get("BROWSERBB_MIN_WAIT", "2.0")),
        wait_for_network_idle_page_load_time=float(os.environ.get("BROWSERBB_NETWORK_IDLE", "2.0")),
        wait_between_actions=0.5,
    )


def _local_browser_profile(
    *,
    storage_state: Any | None = None,
    headless: bool | None = None,
    user_data_dir: str | None = None,
):
    from browser_use.browser.profile import BrowserProfile

    from mvp.captcha import captcha_solver_enabled

    if headless is None:
        headless = os.environ.get("MVP_BROWSER_HEADLESS", "1").lower() not in {
            "0",
            "false",
            "no",
        }
    kwargs: dict[str, Any] = {
        "is_local": True,
        "headless": headless,
        "viewport": VIEWPORT,
        "user_agent": USER_AGENT,
        "disable_security": True,
        "cross_origin_iframes": False,
        "enable_default_extensions": False,
        "captcha_solver": captcha_solver_enabled(),
        "highlight_elements": False,
        "dom_highlight_elements": True,
        "minimum_wait_page_load_time": float(os.environ.get("MVP_LOCAL_MIN_WAIT", "1.0")),
        "wait_for_network_idle_page_load_time": float(
            os.environ.get("MVP_LOCAL_NETWORK_IDLE", "1.5")
        ),
        "wait_between_actions": 0.4,
    }
    # Prefer real Chrome when available — YouTube treats stock Chromium more harshly.
    if os.environ.get("MVP_BROWSER_CHANNEL", "chrome").lower() not in {"", "0", "none"}:
        kwargs["channel"] = os.environ.get("MVP_BROWSER_CHANNEL", "chrome")
    if user_data_dir:
        # A cloned signed-in profile: the only thing Google accepts.
        kwargs["user_data_dir"] = user_data_dir
    elif storage_state:
        kwargs["storage_state"] = storage_state
        # browser-use warns and fights itself if both storage_state and a temp
        # user_data_dir are set — keep cookies-only for parallel agents.
        kwargs["user_data_dir"] = None
    return BrowserProfile(**kwargs)


def _cdp_cookies(state: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Convert a Playwright storage_state into CDP Network.setCookies params.

    browser-use 0.13 drives Chrome over CDP, so the profile's ``storage_state``
    is never read — cookies have to be pushed in by hand once the session is up.
    Note this is a fallback: Google binds its session cookies to the profile, so
    only a cloned profile (see mvp.profile_pool) actually signs in there.
    """
    out: list[dict[str, Any]] = []
    for c in (state or {}).get("cookies") or []:
        if not c.get("name"):
            continue
        cookie: dict[str, Any] = {
            "name": c["name"],
            "value": c.get("value") or "",
            "domain": c.get("domain") or "",
            "path": c.get("path") or "/",
            "secure": bool(c.get("secure")),
            "httpOnly": bool(c.get("httpOnly")),
        }
        if c.get("sameSite") in {"Strict", "Lax", "None"}:
            cookie["sameSite"] = c["sameSite"]
        expires = c.get("expires")
        # -1 marks a session cookie; CDP wants the field omitted entirely.
        if isinstance(expires, (int, float)) and expires > 0:
            cookie["expires"] = float(expires)
        out.append(cookie)
    return out


async def _inject_cookies(session: Any, state: dict[str, Any] | None) -> int:
    cookies = _cdp_cookies(state)
    if not cookies:
        return 0
    try:
        cdp = await session.get_or_create_cdp_session()
        await cdp.cdp_client.send.Network.setCookies(
            {"cookies": cookies}, session_id=cdp.session_id
        )
    except Exception:
        return 0
    return len(cookies)


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

    screenshot_name = None
    if (screenshot_dir / f"bbox_{step_no}.png").exists():
        screenshot_name = f"bbox_{step_no}.png"
    elif shot_src and Path(shot_src).exists():
        screenshot_name = f"step_{step_no}.png"
        shutil.copy2(shot_src, screenshot_dir / screenshot_name)

    act_raw = None
    if model_out is not None:
        act_raw = getattr(model_out, "action", None) or getattr(model_out, "actions", None)
    action = _action_label(act_raw)
    observation = _result_text(getattr(h, "result", None))

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

    browser-use takes its own screenshot *before* injecting highlights, so history
    screenshots are always clean. Re-injecting the overlay here is the only way to
    get boxed frames like the Bland bakeoff traces.
    """
    state = {"step": 0}

    async def on_step_end(agent: Any) -> None:
        state["step"] += 1
        step_no = state["step"]
        session = getattr(agent, "browser_session", None)
        if session is None:
            return
        try:
            # Cached selector map is stale after the step action (often empty post-nav).
            summary = await asyncio.wait_for(session.get_browser_state_summary(), timeout=25)
            selector_map = {}
            if summary is not None and getattr(summary, "dom_state", None) is not None:
                selector_map = summary.dom_state.selector_map or {}
            if not selector_map:
                selector_map = await asyncio.wait_for(session.get_selector_map(), timeout=10)
            if selector_map:
                await asyncio.wait_for(session.add_highlights(selector_map), timeout=10)
                await asyncio.sleep(0.3)
            await asyncio.wait_for(
                session.take_screenshot(path=str(screenshot_dir / f"bbox_{step_no}.png")),
                timeout=20,
            )
        except Exception:  # noqa: BLE001
            pass
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


def _history_to_trace(
    history,
    *,
    study_id: str,
    agent_id: str,
    screenshot_dir: Path,
) -> list[dict[str, Any]]:
    items = list(getattr(history, "history", None) or [])
    return [
        _trace_step_from_history_item(
            h, i, study_id=study_id, agent_id=agent_id, screenshot_dir=screenshot_dir
        )
        for i, h in enumerate(items, start=1)
    ]


async def run_browser_agent(
    *,
    study_id: str,
    agent_id: str,
    url: str,
    task_prompt: str,
    persona: dict[str, Any],
    segment: str,
    model: str | None = None,
    max_steps: int = MVP_MAX_STEPS,
    on_step: Callable[[dict[str, Any]], Awaitable[None] | None] | None = None,
    bb_session: Any | None = None,
    local: bool = False,
) -> dict[str, Any]:
    """Run Browser Use (Browserbase or local Chromium) and return a bbox screenshot trace."""
    from browser_use import Agent, ChatOpenAI

    model = model or mistral_model()
    os.environ.setdefault("BROWSER_USE_CDP_TIMEOUT_S", "120")
    os.environ.setdefault("BROWSER_USE_ACTION_TIMEOUT_S", "240")

    run_dir = MVP_RUNS_DIR / study_id / agent_id
    screenshot_dir = run_dir / "screenshots"
    run_dir.mkdir(parents=True, exist_ok=True)
    screenshot_dir.mkdir(parents=True, exist_ok=True)

    from mvp.profile_pool import clone_for_url, discard as discard_profile

    from mvp.auth_state import (
        ensure_site_auth,
        youtube_bootstrap_url,
        youtube_is_signed_in,
        youtube_needs_content_bootstrap,
    )

    # Load auth first so YouTube can use a real signed-in home feed when available.
    # With MVP_AUTO_SIGNIN=1 this also performs the login when the vault has creds.
    storage_state = await asyncio.to_thread(ensure_site_auth, url)
    start_url = url
    yt_hint = ""
    if youtube_needs_content_bootstrap(url, storage_state):
        # Signed-out home/feed is empty in automation Chromium. Search always has tiles.
        start_url = youtube_bootstrap_url(task_prompt, persona.get("name") or "")
        yt_hint = (
            "YouTube's signed-out home feed is often empty in automation. You were opened on "
            "search results with real videos — use those, refine the query, or open a video. "
            "If you can sign in / avatar is visible, you may also open Home afterward.\n"
        )
    elif youtube_is_signed_in(storage_state if isinstance(storage_state, dict) else None):
        yt_hint = (
            "You are signed into YouTube (Gmail session cookies loaded). Use the personalized "
            "home feed, subscriptions, and account UI as a real logged-in user would.\n"
        )

    cookie_state = storage_state if isinstance(storage_state, dict) else None
    if storage_state:
        state_path = run_dir / "storage_state.json"
        state_path.write_text(json.dumps(storage_state))
        storage_state = str(state_path)

    force_local = local or os.environ.get("MVP_FORCE_LOCAL_BROWSER", "").lower() in {
        "1",
        "true",
        "yes",
    }

    owns_session = False
    session_url: str | None = None
    profile_clone = None
    if force_local:
        # A cloned signed-in profile beats cookie injection: Google binds session
        # cookies to the profile, so transplanted cookies report LOGGED_IN=false.
        profile_clone = await asyncio.to_thread(clone_for_url, url)
        if profile_clone:
            cookie_state = None
            # Signed in, so the real home feed works — no search-results detour.
            start_url = url
            yt_hint = (
                "You are signed in on this site. Use the personalized home feed, "
                "subscriptions, and account UI as a real logged-in user would.\n"
            )
        profile = _local_browser_profile(
            storage_state=None if profile_clone else storage_state,
            user_data_dir=str(profile_clone) if profile_clone else None,
        )
        backend = "local_playwright"
    else:
        # create_session/close_session block on a threading semaphore + sleep for the
        # Browserbase create-rate limit; off-loop or they freeze every other agent.
        owns_session = bb_session is None
        if owns_session:
            bb_session = await asyncio.to_thread(create_session, proxies=False, keep_alive=False)
        session_url = getattr(bb_session, "session_url", None)
        connect = getattr(bb_session, "connect_url", None)
        if not connect:
            raise RuntimeError("Browserbase session missing connect_url")
        profile = _browserbase_profile(connect)
        backend = "browserbase"

    history = None
    browser_session = None
    try:
        llm = ChatOpenAI(
            model=model,
            api_key=mistral_api_key(),
            base_url=MISTRAL_API_BASE,
            temperature=0,
            # Concurrent agents burst against the Mistral rate limit; without retries a
            # single 429 drops the whole session into snapshot fallback.
            max_retries=int(os.environ.get("MVP_LLM_MAX_RETRIES", "6")),
            timeout=120.0,
        )
        persona_line = f"You are {persona.get('name')}: {persona.get('bio')}"
        agent_task = (
            f"{CAPABLE_AGENT_PREAMBLE}\n\n"
            f"{persona_line}\n"
            f"Customer segment: {segment}\n"
            f"{yt_hint}"
            f"Open {start_url} if not already there (product URL: {url}).\n"
            f"Task: {task_prompt}\n"
            f"Behave like this persona would — note confusion, pricing concerns, and UX friction.\n"
            f"Do not judge the site from the landing page alone. If the answer is not visible, "
            f"click into the nav links (blog, docs, use cases, about, pricing) and read the real "
            f"pages before forming an opinion. Only conclude something is missing after you have "
            f"actually looked for it.\n"
            f"Stop when the task is done or you would realistically give up."
        )
        if cookie_state:
            from browser_use import BrowserSession

            browser_session = BrowserSession(browser_profile=profile)
            await browser_session.start()
            injected = await _inject_cookies(browser_session, cookie_state)
            print(f"[{agent_id}] injected {injected} cookies via CDP", flush=True)

        agent = Agent(
            task=agent_task,
            llm=llm,
            browser_session=browser_session,
            browser_profile=None if browser_session else profile,
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
    finally:
        if browser_session is not None:
            try:
                await browser_session.kill()
            except Exception:
                pass
        if profile_clone is not None:
            await asyncio.to_thread(discard_profile, profile_clone)
        if owns_session and bb_session is not None:
            sid = getattr(bb_session, "id", None)
            if sid:
                await asyncio.to_thread(close_session, sid)

    actions = _history_to_actions(history) if history is not None else []
    trace = (
        _history_to_trace(
            history, study_id=study_id, agent_id=agent_id, screenshot_dir=screenshot_dir
        )
        if history is not None
        else []
    )

    final_url = ""
    try:
        urls = history.urls() if history is not None and hasattr(history, "urls") else []
        final_url = urls[-1] if urls else ""
    except Exception:
        final_url = actions[-1].get("url") or url if actions else url

    is_done = False
    try:
        is_done = (
            bool(history.is_done()) if history is not None and hasattr(history, "is_done") else False
        )
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
                "backend": backend,
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
        "backend": backend,
        "browserbase_session_url": session_url,
        "run_dir": str(run_dir),
        "num_steps": len(trace),
    }
