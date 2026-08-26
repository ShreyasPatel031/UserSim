"""Browser Use + Mistral multimodal API (Pixtral / Medium) for hackathon evals."""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from browser_use import Agent
from browser_use.browser.profile import BrowserProfile

from capability import CAPABLE_AGENT_PREAMBLE, MAX_ACTIONS, OUT_DIR, USER_AGENT, VIEWPORT
from capability.browser_use_runner import _history_to_actions
from capability.browser_use_harness import (
    allowed_domains_for_start_url,
    stage1_agent_kwargs,
    stage1_config_snapshot,
    stage1_enabled,
    stage1_llm_stack,
    stage1_profile_kwargs,
)
from capability.judge import JUDGE_ERROR, judge_task
from capability.browserbase_client import (
    browserbase_enabled,
    close_session,
    create_session,
)
from capability.mistral_config import DEFAULT_MISTRAL_MODEL, mistral_cost_usd
from capability.site_preflight import PreflightResult, preflight_start_url, preflight_start_url_browserbase
from capability.widget_tools import build_harness_tools
from capability.verify_done import make_verify_done_hook, verify_done_enabled


def _preflight_blocked_result(
    task: dict,
    model: str,
    run_dir: Path,
    pf: PreflightResult,
    *,
    use_vision: bool,
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
        "provider": "mistral",
        "observation_mode": "browser_use_vision" if use_vision else "browser_use_dom",
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


def _browser_headless(headed: bool | None) -> bool:
    if headed is not None:
        return not headed
    return os.environ.get("BROWSER_USE_HEADED", "").lower() not in ("1", "true", "yes")


def _use_vision_for_model(model: str) -> bool:
    if os.environ.get("BROWSER_USE_DOM_ONLY", "").lower() in {"1", "true", "yes"}:
        return False
    # Ministral 3B: DOM-only avoids screenshot/CDP timeouts under local load.
    return not model.lower().startswith("ministral-3b")


# Fleet VMs run several Chromium instances per box, so a bakeoff shard is CPU-bound
# long before it is memory- or network-bound: 4 workers on a 2-vCPU e2-standard-2 was
# measured at load 6.25, roughly 3x oversubscribed, which stretched a step from ~10s to
# ~27s. These flags strip work that does not change what the agent perceives.
_LEAN_CHROMIUM_ARGS = [
    "--disable-gpu",
    "--disable-software-rasterizer",
    "--disable-dev-shm-usage",
    "--disable-background-networking",
    "--disable-sync",
    "--disable-default-apps",
    "--disable-component-update",
    "--metrics-recording-only",
    "--no-first-run",
    "--no-default-browser-check",
    "--mute-audio",
]


def _lean_browser_args() -> list[str]:
    args = list(_LEAN_CHROMIUM_ARGS)
    # Blocking images is a large CPU/bandwidth win but it *does* change what a vision
    # run sees, so it stays opt-in rather than riding along with the safe flags.
    if os.environ.get("BROWSER_USE_NO_IMAGES", "").lower() in {"1", "true", "yes"}:
        args.append("--blink-settings=imagesEnabled=false")
    return args


def _remote_browser_profile(cdp_url: str, start_url: str) -> BrowserProfile:
    """Browser Use over Browserbase CDP — lighter DOM, longer waits."""
    kwargs = stage1_profile_kwargs(
        start_url,
        {
            "cdp_url": cdp_url,
            "is_local": False,
            "viewport": VIEWPORT,
            "user_agent": USER_AGENT,
            "disable_security": True,
            "cross_origin_iframes": False,
            "enable_default_extensions": False,
            "captcha_solver": False,
            "minimum_wait_page_load_time": float(os.environ.get("BROWSERBB_MIN_WAIT", "2.0")),
            "wait_for_network_idle_page_load_time": float(os.environ.get("BROWSERBB_NETWORK_IDLE", "2.0")),
            "wait_between_actions": 0.5,
        },
    )
    return BrowserProfile(**kwargs)


def _skip_browserbase_preflight() -> bool:
    return os.environ.get("BROWSERBASE_SKIP_PREFLIGHT", "1").lower() in {"1", "true", "yes"}


def task_wall_timeout_s(max_actions: int) -> float:
    """Hard wall-clock budget for one agent run.

    browser-use's per-step timeout alone is not enough: BrowserStartEvent / CDP /
    LLM retries can hang outside the step loop and freeze a worker forever.
    Default: ~40s/step + 2 min start buffer, overridable via CAPABILITY_TASK_TIMEOUT_S.
    """
    raw = (os.environ.get("CAPABILITY_TASK_TIMEOUT_S") or "").strip()
    if raw:
        return max(60.0, float(raw))
    return float(max(max_actions * 40, 300) + 120)


def _timeout_result(
    task: dict,
    model: str,
    run_dir: Path,
    *,
    use_vision: bool,
    run_id: str,
    max_actions: int,
    timeout_s: float,
    actions: list | None = None,
) -> dict:
    actions = actions or []
    return {
        "run_id": run_id,
        "task_id": task["task_id"],
        "eval_index": task["eval_index"],
        "task": task["task"],
        "website": task["website"],
        "model": model,
        "harness": "browser_use_oss",
        "provider": "mistral",
        "observation_mode": "browser_use_vision" if use_vision else "browser_use_dom",
        "start_url": task["start_url"],
        "actions": actions,
        "num_actions": len(actions),
        "stop_reason": f"task_wall_timeout:{int(timeout_s)}s",
        "success": False,
        "status": "FAILURE",
        "judge_reason": f"Agent exceeded hard wall timeout of {int(timeout_s)}s",
        "judge_evidence": None,
        "failure_category": "HARNESS",
        "final_url": task["start_url"],
        "final_title": "",
        "input_tokens": 0,
        "output_tokens": 0,
        "estimated_cost_usd": 0.0,
        "max_actions_budget": max_actions,
        "trace_dir": str(run_dir),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


async def _close_agent(agent: Agent | None) -> None:
    if agent is None:
        return
    for name in ("close", "stop"):
        fn = getattr(agent, name, None)
        if callable(fn):
            try:
                result = fn()
                if asyncio.iscoroutine(result):
                    await asyncio.wait_for(result, timeout=15)
                return
            except Exception:
                pass
    session = getattr(agent, "browser_session", None) or getattr(agent, "browser", None)
    if session is not None:
        for name in ("kill", "stop", "close", "reset"):
            fn = getattr(session, name, None)
            if callable(fn):
                try:
                    result = fn()
                    if asyncio.iscoroutine(result):
                        await asyncio.wait_for(result, timeout=10)
                    return
                except Exception:
                    pass


async def _run_async(
    task: dict,
    model: str,
    max_actions: int,
    run_dir: Path,
    *,
    headed: bool | None = None,
    preflight: bool = True,
) -> dict:
    run_id = run_dir.name
    run_dir.mkdir(parents=True, exist_ok=True)
    use_vision = _use_vision_for_model(model)
    bb_session = None
    use_bb = browserbase_enabled()
    if use_bb:
        os.environ.setdefault("BROWSER_USE_CDP_TIMEOUT_S", "120")
        os.environ.setdefault("BROWSER_USE_ACTION_TIMEOUT_S", "240")
        bb_session = create_session(
            proxies=os.environ.get("BROWSERBASE_PROXIES", "").lower() in {"1", "true", "yes"},
            keep_alive=True,
        )
        (run_dir / "browserbase_session.txt").write_text(bb_session.session_url)

    run_preflight = preflight and not (use_bb and _skip_browserbase_preflight())
    if run_preflight:
        if use_bb and bb_session:
            pf = await preflight_start_url_browserbase(
                task["start_url"], connect_url=bb_session.connect_url
            )
        else:
            pf = await preflight_start_url(task["start_url"])
        if pf.blocked:
            out = _preflight_blocked_result(task, model, run_dir, pf, use_vision=use_vision, run_id=run_id)
            (run_dir / "run.json").write_text(__import__("json").dumps(out, indent=2, default=str))
            if bb_session:
                close_session(bb_session.id)
            return out
        if use_bb and bb_session:
            # Preflight Playwright connect closes CDP; agent needs a fresh session.
            close_session(bb_session.id)
            bb_session = create_session(
                proxies=os.environ.get("BROWSERBASE_PROXIES", "").lower() in {"1", "true", "yes"}
            )
            (run_dir / "browserbase_session.txt").write_text(bb_session.session_url)

    llm, extraction_llm, fallback_llm = stage1_llm_stack(model)
    headless = _browser_headless(headed)
    if use_bb and bb_session:
        profile = _remote_browser_profile(bb_session.connect_url, task["start_url"])
        if os.environ.get("BROWSER_USE_DOM_ONLY", "").lower() in {"1", "true", "yes"}:
            use_vision = False
    else:
        profile = BrowserProfile(
            **stage1_profile_kwargs(
                task["start_url"],
                {
                    "headless": headless,
                    "viewport": VIEWPORT,
                    "user_agent": USER_AGENT,
                    "disable_security": True,
                    # Already set on the Browserbase path; the local/fleet path was
                    # paying for extensions and cross-origin iframe work it never used.
                    "enable_default_extensions": False,
                    "cross_origin_iframes": False,
                    "args": _lean_browser_args(),
                },
            )
        )
    agent_task = (
        f"{CAPABLE_AGENT_PREAMBLE}\n\n"
        f"Open {task['start_url']} if not already there.\n"
        f"Task: {task['task']}\n"
        f"Satisfy every constraint. Stop only when fully done."
    )
    agent_kwargs = {
        "task": agent_task,
        "llm": llm,
        "browser_profile": profile,
        "use_vision": use_vision,
        "calculate_cost": True,
        "save_conversation_path": str(run_dir / "conversation"),
        **stage1_agent_kwargs(use_vision=use_vision),
    }
    if extraction_llm is not None:
        agent_kwargs["page_extraction_llm"] = extraction_llm
    if fallback_llm is not None:
        agent_kwargs["fallback_llm"] = fallback_llm
    domains = allowed_domains_for_start_url(task["start_url"]) if stage1_enabled() else None
    harness_tools = build_harness_tools(allowed_domains=domains)
    if harness_tools is not None:
        agent_kwargs["tools"] = harness_tools
    on_step_end = None
    verify_stats = None
    if verify_done_enabled():
        on_step_end, verify_stats = make_verify_done_hook(task["task"], llm=extraction_llm)
    agent = Agent(**agent_kwargs)
    wall_s = task_wall_timeout_s(max_actions)
    history = None
    try:
        try:
            history = await asyncio.wait_for(
                agent.run(max_steps=max_actions, on_step_end=on_step_end),
                timeout=wall_s,
            )
        except asyncio.TimeoutError:
            print(
                f"TIMEOUT mistral | {task['website']} | idx={task['eval_index']} | "
                f"wall={int(wall_s)}s — killing agent",
                flush=True,
            )
            await _close_agent(agent)
            out = _timeout_result(
                task,
                model,
                run_dir,
                use_vision=use_vision,
                run_id=run_id,
                max_actions=max_actions,
                timeout_s=wall_s,
            )
            (run_dir / "run.json").write_text(__import__("json").dumps(out, indent=2, default=str))
            return out
    finally:
        if bb_session:
            close_session(bb_session.id)
            bb_session = None

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
        "provider": "mistral",
        "observation_mode": "browser_use_vision" if use_vision else "browser_use_dom",
        "harness_config": stage1_config_snapshot(),
        "allowed_domains": allowed_domains_for_start_url(task["start_url"]) if stage1_enabled() else None,
        "start_url": task["start_url"],
        "actions": actions,
        "num_actions": len(actions),
        # Budget exhaustion is checked first: browser-use emits a final Done when it
        # runs out of steps, so keying on is_done reports "agent_done" for runs that
        # were actually cut off and hides the step cap entirely.
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
        "estimated_cost_usd": mistral_cost_usd(model, prompt_tokens, output_tokens)
        + float(judgment.get("estimated_cost_usd") or 0),
        "trace_dir": str(run_dir),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if verify_stats is not None:
        out.update(verify_stats.as_dict())
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
    *,
    headed: bool | None = None,
    preflight: bool = True,
) -> dict:
    run_dir = run_dir or (OUT_DIR / "traces" / f"mistral_{task['eval_index']}_{uuid.uuid4().hex[:8]}")
    return asyncio.run(_run_async(task, model, max_actions, run_dir, headed=headed, preflight=preflight))
