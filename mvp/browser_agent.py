"""Browser Use agent runs for MVP — screenshots with DOM bounding boxes."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from capability import CAPABLE_AGENT_PREAMBLE, USER_AGENT, VIEWPORT, location_for
from capability.browserbase_client import close_session, create_session
from auth import vertex_credentials
from config import GCP_PROJECT, MODEL

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


def _is_noop_action(action: str | None) -> bool:
    a = (action or "").strip()
    return (not a) or a in {"—", "-", "–", "None", "null", "none"}


def _png_bytes_equal(a: Path, b: Path) -> bool:
    try:
        if not a.is_file() or not b.is_file():
            return False
        if a.stat().st_size < 100 or b.stat().st_size < 100:
            return False
        return a.read_bytes() == b.read_bytes()
    except OSError:
        return False


def _shots_visually_same(a: Path, b: Path) -> bool:
    """True when two PNGs are the same viewport (ignore tiny highlight noise)."""
    if _png_bytes_equal(a, b):
        return True
    try:
        from PIL import Image

        if not a.is_file() or not b.is_file():
            return False
        ia = Image.open(a).convert("L").resize((64, 36))
        ib = Image.open(b).convert("L").resize((64, 36))
        pa, pb = ia.getdata(), ib.getdata()
        if len(pa) != len(pb) or not pa:
            return False
        # Mean absolute difference on a tiny grayscale thumb.
        mad = sum(abs(x - y) for x, y in zip(pa, pb)) / float(len(pa))
        return mad < 2.0
    except Exception:
        return False


_CONSENT_CLICK_JS = """
() => {
  const texts = [
    'accept all', 'accept all cookies', 'accept cookies', 'i agree', 'agree',
    'allow all', 'got it', 'ok', 'okay', 'continue', 'consent', 'alle akzeptieren',
  ];
  const nodes = [
    ...document.querySelectorAll('button, [role="button"], input[type="button"], input[type="submit"], a'),
  ];
  for (const el of nodes) {
    const label = ((el.innerText || el.value || el.getAttribute('aria-label') || '') + '').trim().toLowerCase();
    if (!label || label.length > 48) continue;
    if (!texts.some((t) => label === t || label.startsWith(t))) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 8 || r.height < 8) continue;
    el.click();
    return label;
  }
  return '';
}
"""


async def _dismiss_consent_banners(browser_session: Any, *, agent_id: str) -> None:
    """Best-effort click through common cookie/consent interstitials (any site)."""
    try:
        page = await asyncio.wait_for(browser_session.get_current_page(), timeout=8)
        if page is None:
            return
        for _ in range(2):
            clicked = await asyncio.wait_for(page.evaluate(_CONSENT_CLICK_JS), timeout=5)
            if not clicked:
                break
            print(f"[{agent_id}] dismissed consent control: {clicked!r}", flush=True)
            await asyncio.sleep(0.4)
    except Exception as exc:  # noqa: BLE001
        print(f"[{agent_id}] consent dismiss skipped: {exc!r}", flush=True)


async def _ensure_on_host(browser_session: Any, *, target_url: str, agent_id: str) -> None:
    """If the agent wandered off-host, navigate back to the assigned URL."""
    want = (urlparse(target_url).hostname or "").lower().removeprefix("www.")
    if not want:
        return
    try:
        current = ""
        try:
            current = str(browser_session.get_current_page_url() or "")
        except Exception:
            page = await asyncio.wait_for(browser_session.get_current_page(), timeout=5)
            current = str(getattr(page, "url", "") or "") if page is not None else ""
        host = (urlparse(current).hostname or "").lower().removeprefix("www.")
        if not host or host == want or host.endswith(f".{want}") or want.endswith(f".{host}"):
            return
        print(f"[{agent_id}] off-site {host!r} → returning to {target_url}", flush=True)
        await asyncio.wait_for(browser_session.navigate_to(target_url), timeout=30)
    except Exception as exc:  # noqa: BLE001
        print(f"[{agent_id}] host lock failed: {exc!r}", flush=True)


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
    # Default: bundled Chromium. channel=chrome will attach to an already-open
    # Google Chrome (e.g. the UserSim debug window on :9222) and agents get stuck
    # on http://127.0.0.1:8787/live. Opt in with MVP_BROWSER_CHANNEL=chrome.
    channel = os.environ.get("MVP_BROWSER_CHANNEL", "").lower()
    if channel and channel not in {"", "0", "none", "chromium"}:
        kwargs["channel"] = channel
    if user_data_dir:
        # A cloned signed-in profile: the only thing Google accepts.
        kwargs["user_data_dir"] = user_data_dir
    elif storage_state:
        kwargs["storage_state"] = storage_state
        # browser-use warns and fights itself if both storage_state and a temp
        # user_data_dir are set — keep cookies-only for parallel agents.
        kwargs["user_data_dir"] = None
    else:
        # Isolated temp profile so parallel local fallbacks never share cookies
        # or attach to an existing Chrome user-data dir.
        import tempfile

        kwargs["user_data_dir"] = tempfile.mkdtemp(prefix="usersim-local-")
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
    target_url: str = "",
    on_step: Callable[[dict[str, Any]], Awaitable[None] | None] | None = None,
):
    """Capture a screenshot with DOM bounding boxes drawn on it, once per step.

    browser-use takes its own screenshot *before* injecting highlights, so history
    screenshots are always clean. Re-injecting the overlay here is the only way to
    get boxed frames like the Bland bakeoff traces.
    """
    state = {"step": 0, "emitted_done": False, "noop_streak": 0}

    async def _emit(step: dict[str, Any]) -> None:
        if on_step is None:
            return
        maybe = on_step(step)
        if asyncio.iscoroutine(maybe):
            await maybe

    async def on_step_start(agent: Any) -> None:
        nxt = state["step"] + 1
        # Stream a thinking pulse before the LLM finishes this step's tokens.
        await _emit(
            {
                "step": None,
                "progress_only": True,
                "action": f"Thinking — step {nxt}",
                "observation": "",
                "thought": f"Deciding what to do next (step {nxt})…",
                "thought_detail": {
                    "thinking": f"Looking at the page and choosing the next action for step {nxt}."
                },
                "url": None,
                "screenshot_url": None,
                "outcome": "neutral",
            }
        )

    async def on_step_end(agent: Any) -> None:
        state["step"] += 1
        step_no = state["step"]
        session = getattr(agent, "browser_session", None)
        if session is None:
            return
        if target_url:
            await _ensure_on_host(session, target_url=target_url, agent_id=agent_id)
            await _dismiss_consent_banners(session, agent_id=agent_id)
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
        action = str(step.get("action") or "")
        prev_shot = screenshot_dir / f"bbox_{step_no - 1}.png"
        if step_no == 1:
            prev_shot = screenshot_dir / "bbox_0.png"
        cur_shot = screenshot_dir / f"bbox_{step_no}.png"
        same_pixels = _shots_visually_same(prev_shot, cur_shot)
        # Empty "—" actions with identical frames are freezes, not progress.
        # Fold them (and duplicate done rows) into pulses so the progress judge
        # and step rail stay honest.
        fold = False
        if action.lower().startswith("done"):
            if state.get("emitted_done"):
                fold = True
            else:
                state["emitted_done"] = True
        if _is_noop_action(action) and same_pixels:
            fold = True
        # Any claimed action that left the viewport unchanged is not a new step.
        if same_pixels and step_no > 0:
            fold = True
        if fold:
            state["noop_streak"] = int(state.get("noop_streak") or 0) + 1
            await _emit(
                {
                    "step": None,
                    "progress_only": True,
                    "action": action if not _is_noop_action(action) else "waiting — no visual change",
                    "thought": step.get("thought") or "",
                    "thought_detail": step.get("thought_detail") or {},
                    "observation": step.get("observation") or "",
                    "url": step.get("url"),
                    "screenshot_url": None,
                    "outcome": "neutral",
                }
            )
            return
        state["noop_streak"] = 0
        await _emit(step)

    return on_step_start, on_step_end


async def _emit_opening_frame(
    browser_session: Any,
    *,
    screenshot_dir: Path,
    study_id: str,
    agent_id: str,
    url: str,
    on_step: Callable[[dict[str, Any]], Awaitable[None] | None] | None = None,
) -> None:
    """Navigate + full-viewport screenshot before the LLM agent loop."""
    try:
        await asyncio.wait_for(browser_session.navigate_to(url), timeout=30)
    except Exception as exc:  # noqa: BLE001
        print(f"[{agent_id}] opening navigate failed: {exc!r}", flush=True)
    await _dismiss_consent_banners(browser_session, agent_id=agent_id)
    # Scroll to top so we don't capture a footer-only viewport.
    try:
        page = await asyncio.wait_for(browser_session.get_current_page(), timeout=8)
        if page is not None:
            await asyncio.wait_for(
                page.evaluate("() => window.scrollTo(0, 0)"),
                timeout=5,
            )
    except Exception as exc:  # noqa: BLE001
        print(f"[{agent_id}] opening scrollTop failed: {exc!r}", flush=True)
    await asyncio.sleep(0.2)
    shot_name = "bbox_0.png"
    shot_path = screenshot_dir / shot_name
    try:
        await asyncio.wait_for(
            browser_session.take_screenshot(path=str(shot_path), full_page=False),
            timeout=20,
        )
    except TypeError:
        # Older browser-use: no full_page kwarg.
        try:
            await asyncio.wait_for(
                browser_session.take_screenshot(path=str(shot_path)),
                timeout=20,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[{agent_id}] opening screenshot failed: {exc!r}", flush=True)
            return
    except Exception as exc:  # noqa: BLE001
        print(f"[{agent_id}] opening screenshot failed: {exc!r}", flush=True)
        return
    if not shot_path.is_file() or shot_path.stat().st_size < 100:
        print(f"[{agent_id}] opening screenshot missing/empty", flush=True)
        return
    final_url = url
    try:
        got = browser_session.get_current_page_url()
        if asyncio.iscoroutine(got):
            got = await asyncio.wait_for(got, timeout=5)
        if got:
            final_url = got
    except Exception:
        pass
    step = {
        "step": 0,
        "action": f"Opened {final_url}",
        "observation": "Landing page screenshot",
        "thought": "",
        "thought_detail": {},
        "url": final_url,
        "screenshot_url": f"/api/studies/{study_id}/agents/{agent_id}/screenshots/{shot_name}",
        "boxes": [],
        "outcome": "neutral",
        "evidence_label": "Opening frame · before agent steps",
    }
    if on_step is not None:
        maybe = on_step(step)
        if asyncio.iscoroutine(maybe):
            await maybe
    print(
        f"[{agent_id}] opening frame ready ({shot_path.stat().st_size} bytes) {final_url}",
        flush=True,
    )


def _history_to_trace(
    history,
    *,
    study_id: str,
    agent_id: str,
    screenshot_dir: Path,
) -> list[dict[str, Any]]:
    items = list(getattr(history, "history", None) or [])
    out: list[dict[str, Any]] = []
    seen_done = False
    prev_path: Path | None = screenshot_dir / "bbox_0.png"
    for i, h in enumerate(items, start=1):
        step = _trace_step_from_history_item(
            h, i, study_id=study_id, agent_id=agent_id, screenshot_dir=screenshot_dir
        )
        action = str(step.get("action") or "")
        cur_path = screenshot_dir / f"bbox_{i}.png"
        same = bool(prev_path and _shots_visually_same(prev_path, cur_path))
        if action.lower().startswith("done"):
            if seen_done:
                continue
            seen_done = True
        if same:
            continue
        if _is_noop_action(action) and same:
            continue
        out.append(step)
        if cur_path.is_file():
            prev_path = cur_path
    return out


def _urls_match(a: str, b: str) -> bool:
    def norm(u: str) -> str:
        p = urlparse((u or "").strip())
        host = (p.hostname or "").lower().removeprefix("www.")
        path = (p.path or "/").rstrip("/") or "/"
        return f"{host}{path}"

    return bool(a and b and norm(a) == norm(b))


async def warm_opening_session(
    *, study_id: str, url: str, slot: str = "product"
) -> dict[str, Any] | None:
    """Create Browserbase + navigate + screenshot while brief LLMs run.

    Returns a live browser_session already on ``url`` with bbox_0.png written under
    ``MVP_RUNS_DIR / study_id / _warm_{slot}``. Caller must either hand this to
    ``run_browser_agent(..., warm=...)`` or ``close_warm_opening``.
    """
    if os.environ.get("MVP_FORCE_LOCAL_BROWSER", "").lower() in {"1", "true", "yes"}:
        return None
    safe_slot = re.sub(r"[^a-zA-Z0-9._-]+", "_", slot or "product")[:48] or "product"
    run_dir = MVP_RUNS_DIR / study_id / f"_warm_{safe_slot}"
    screenshot_dir = run_dir / "screenshots"
    run_dir.mkdir(parents=True, exist_ok=True)
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    bb_session = None
    browser_session = None
    try:
        from browser_use import BrowserSession

        bb_session = await asyncio.to_thread(create_session, proxies=False, keep_alive=True)
        connect = getattr(bb_session, "connect_url", None)
        if not connect:
            raise RuntimeError("Browserbase session missing connect_url")
        browser_session = BrowserSession(browser_profile=_browserbase_profile(connect))
        await browser_session.start()
        await _emit_opening_frame(
            browser_session,
            screenshot_dir=screenshot_dir,
            study_id=study_id,
            agent_id="_warm",
            url=url,
            on_step=None,
        )
        shot = screenshot_dir / "bbox_0.png"
        if not shot.is_file() or shot.stat().st_size < 100:
            raise RuntimeError("warm opening screenshot missing")
        live_view = None
        try:
            from capability.browserbase_client import session_live_view_url

            sid = getattr(bb_session, "id", None)
            if sid:
                live_view = await asyncio.to_thread(session_live_view_url, str(sid))
        except Exception as live_exc:  # noqa: BLE001
            print(f"[warm] live view url failed: {live_exc!r}", flush=True)
        print(f"[warm] first pixels ready for {url}", flush=True)
        return {
            "url": url,
            "bb_session": bb_session,
            "browser_session": browser_session,
            "shot_path": shot,
            "owns_session": True,
            "live_view_url": live_view,
            "browserbase_session_id": getattr(bb_session, "id", None),
        }
    except Exception as exc:  # noqa: BLE001
        print(f"[warm] opening session failed: {exc!r}", flush=True)
        if browser_session is not None:
            try:
                await browser_session.kill()
            except Exception:
                pass
        if bb_session is not None:
            sid = getattr(bb_session, "id", None)
            if sid:
                try:
                    await asyncio.to_thread(close_session, sid)
                except Exception:
                    pass
        return None


async def close_warm_opening(warm: dict[str, Any] | None) -> None:
    if not warm:
        return
    browser_session = warm.get("browser_session")
    bb_session = warm.get("bb_session")
    if browser_session is not None:
        try:
            await browser_session.kill()
        except Exception:
            pass
        warm["browser_session"] = None
    if warm.get("owns_session") and bb_session is not None:
        sid = getattr(bb_session, "id", None)
        if sid:
            try:
                await asyncio.to_thread(close_session, sid)
            except Exception:
                pass
        warm["bb_session"] = None
        warm["owns_session"] = False


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
    warm: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run Browser Use (Browserbase or local Chromium) and return a bbox screenshot trace.

    First real pixels are emitted as soon as the target URL is open — before the
    LLM agent loop and before waiting on optional auth vault I/O.
    If ``warm`` is a matching pre-opened session from ``warm_opening_session``,
    the landing screenshot is published immediately and the LLM continues on it.

    Same path for every host — no site-specific bootstrap, signed-in cookie
    shortcuts, or prompt hints.
    """
    if os.environ.get("VERCEL") or os.environ.get("VERCEL_ENV"):
        home = Path("/tmp/usersim-home")
        home.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("HOME", str(home))
        os.environ.setdefault("TMPDIR", "/tmp")
        os.environ.setdefault("XDG_CONFIG_HOME", str(home / ".config"))
        os.environ.setdefault("XDG_CACHE_HOME", str(home / ".cache"))
        Path(os.environ["XDG_CONFIG_HOME"]).mkdir(parents=True, exist_ok=True)
        Path(os.environ["XDG_CACHE_HOME"]).mkdir(parents=True, exist_ok=True)

    model = model or os.environ.get("MVP_BROWSER_MODEL") or MODEL or "gemini-2.5-flash-lite"
    os.environ.setdefault("BROWSER_USE_CDP_TIMEOUT_S", "120")
    os.environ.setdefault("BROWSER_USE_ACTION_TIMEOUT_S", "240")

    run_dir = MVP_RUNS_DIR / study_id / agent_id
    screenshot_dir = run_dir / "screenshots"
    run_dir.mkdir(parents=True, exist_ok=True)
    screenshot_dir.mkdir(parents=True, exist_ok=True)

    from mvp.profile_pool import clone_for_url, discard as discard_profile

    from mvp.auth_state import ensure_site_auth

    start_url = url
    signed_hint = ""

    force_local = local or os.environ.get("MVP_FORCE_LOCAL_BROWSER", "").lower() in {
        "1",
        "true",
        "yes",
    }

    use_warm = (
        not force_local
        and isinstance(warm, dict)
        and warm.get("browser_session") is not None
        and _urls_match(str(warm.get("url") or ""), url)
        and warm.get("shot_path")
        and Path(warm["shot_path"]).is_file()
    )

    # Same for every site: open first, optionally refresh vault auth in parallel.
    auth_task: asyncio.Task | None = None
    storage_state: Any = None
    cookie_state: dict[str, Any] | None = None

    async def _pulse(text: str, *, thinking: bool = False) -> None:
        if on_step is None:
            return
        maybe = on_step(
            {
                "step": None,
                "progress_only": True,
                "action": text,
                "thought": text,
                "thought_detail": {"thinking": text} if thinking else {},
                "observation": "",
                "url": start_url,
                "screenshot_url": None,
                "outcome": "neutral",
            }
        )
        if asyncio.iscoroutine(maybe):
            await maybe

    if not use_warm:
        await _pulse(f"Opening {url}…")
        auth_task = asyncio.create_task(asyncio.to_thread(ensure_site_auth, url))

    owns_session = False
    session_url: str | None = None
    profile_clone = None
    browser_session = None
    history = None
    backend = "browserbase"
    warm_live_url = None
    warm_bb_id = None

    if use_warm:
        browser_session = warm["browser_session"]
        bb_session = warm.get("bb_session") or bb_session
        owns_session = bool(warm.get("owns_session", True))
        session_url = getattr(bb_session, "session_url", None) if bb_session else None
        backend = "browserbase"
        warm_live_url = warm.get("live_view_url")
        warm_bb_id = warm.get("browserbase_session_id") or getattr(bb_session, "id", None)
        # Publish warm pixels under this agent id immediately.
        dest = screenshot_dir / "bbox_0.png"
        try:
            if Path(warm["shot_path"]) != dest:
                shutil.copy2(warm["shot_path"], dest)
        except Exception as exc:  # noqa: BLE001
            print(f"[{agent_id}] warm shot copy failed: {exc!r}", flush=True)
            use_warm = False
            if auth_task is None:
                auth_task = asyncio.create_task(asyncio.to_thread(ensure_site_auth, url))
        if use_warm:
            step = {
                "step": 0,
                "action": f"Opened {url}",
                "observation": "Landing page screenshot",
                "thought": "",
                "thought_detail": {},
                "url": url,
                "screenshot_url": (
                    f"/api/studies/{study_id}/agents/{agent_id}/screenshots/bbox_0.png"
                ),
                "boxes": [],
                "outcome": "neutral",
                "evidence_label": "Opening frame · before agent steps",
            }
            if on_step is not None:
                maybe = on_step(step)
                if asyncio.iscoroutine(maybe):
                    await maybe
            # Stash live URL only — live_active flips when agent.run starts.
            if on_step is not None and (warm_live_url or bb_session is not None):
                maybe = on_step(
                    {
                        "step": None,
                        "progress_only": True,
                        "live_active": False,
                        "live_view_url": warm_live_url,
                        "browserbase_session_id": warm_bb_id,
                        "action": "Page open — starting simulated user",
                        "thought": "Page is open. Starting the simulated user…",
                        "thought_detail": {},
                        "observation": "",
                        "url": url,
                        "screenshot_url": None,
                        "outcome": "neutral",
                    }
                )
                if asyncio.iscoroutine(maybe):
                    await maybe
            print(f"[{agent_id}] warm opening frame published immediately", flush=True)
            # Prevent double-close if caller also holds the warm dict.
            warm["browser_session"] = None
            warm["bb_session"] = None
            warm["owns_session"] = False

    if not use_warm:
        if force_local:
            # Optional per-host profile from secrets/product_profiles — generic, any site.
            profile_clone = await asyncio.to_thread(clone_for_url, url)
            if profile_clone:
                cookie_state = None
                if auth_task is not None and not auth_task.done():
                    auth_task.cancel()
                    try:
                        await auth_task
                    except Exception:
                        pass
                    auth_task = None
                start_url = url
                signed_hint = (
                    "You appear signed in on this site. Use the account UI as a real "
                    "logged-in user would.\n"
                )
            profile = _local_browser_profile(
                storage_state=None
                if profile_clone
                else (storage_state if isinstance(storage_state, str) else None),
                user_data_dir=str(profile_clone) if profile_clone else None,
            )
            backend = "local_playwright"
        else:
            # create_session may contend on a threading lock; off-loop so parallel agents progress.
            owns_session = bb_session is None
            if owns_session:
                # keep_alive=True so parallel agents don't lose CDP mid-run (410 Gone).
                bb_session = await asyncio.to_thread(
                    create_session, proxies=False, keep_alive=True
                )
            session_url = getattr(bb_session, "session_url", None)
            connect = getattr(bb_session, "connect_url", None)
            if not connect:
                raise RuntimeError("Browserbase session missing connect_url")
            profile = _browserbase_profile(connect)
            backend = "browserbase"
            await _pulse("Browser ready — loading the page…")

        try:
            from browser_use import BrowserSession

            # Own the session before agent.run so we navigate + show a frame
            # the moment the task URL is known — not after the LLM's first thought.
            browser_session = BrowserSession(browser_profile=profile)
            await browser_session.start()

            await _emit_opening_frame(
                browser_session,
                screenshot_dir=screenshot_dir,
                study_id=study_id,
                agent_id=agent_id,
                url=start_url,
                on_step=on_step,
            )
            await _pulse("First screenshot captured — starting the simulated user…", thinking=True)
        except Exception:
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
            raise

    try:
        # Warm openings skipped the consent pass above — clear banners before acting.
        if use_warm and browser_session is not None:
            await _dismiss_consent_banners(browser_session, agent_id=agent_id)
        def _build_llm() -> Any:
            from browser_use import ChatGoogle

            return ChatGoogle(
                model=model,
                vertexai=True,
                credentials=vertex_credentials(),
                project=GCP_PROJECT,
                location=location_for(model),
                temperature=0,
            )

        llm_task = asyncio.create_task(asyncio.to_thread(_build_llm))

        if auth_task is not None:
            try:
                # Cap wait so a slow vault never owns TTFT; skip cookies if late.
                storage_state = await asyncio.wait_for(auth_task, timeout=2.5)
            except asyncio.TimeoutError:
                print(f"[{agent_id}] deferred auth timed out — starting without cookies", flush=True)
                auth_task.cancel()
                try:
                    await auth_task
                except Exception:
                    pass
                storage_state = None
            except Exception as exc:  # noqa: BLE001
                print(f"[{agent_id}] deferred auth failed: {exc!r}", flush=True)
                storage_state = None
            cookie_state = storage_state if isinstance(storage_state, dict) else None
            if cookie_state:
                state_path = run_dir / "storage_state.json"
                state_path.write_text(json.dumps(cookie_state))
                storage_state = str(state_path)

        if cookie_state and browser_session is not None:
            injected = await _inject_cookies(browser_session, cookie_state)
            print(f"[{agent_id}] injected {injected} cookies via CDP", flush=True)

        from browser_use import Agent

        llm = await llm_task
        persona_line = f"You are {persona.get('name')}: {persona.get('bio')}"
        site_host = (urlparse(start_url).hostname or start_url).lower()
        stay_put = (
            f"CRITICAL: Stay on {start_url} and its own pages/subdomains only "
            f"({site_host}). Do not navigate to unrelated products or competitors. "
            f"Evaluate the task using THIS site’s UI, search, and docs.\n"
        )
        consent_rule = (
            "If a cookie/consent/privacy banner, age gate, 'Before you continue', "
            "Accept all / Reject all / Agree, or similar interstitial blocks the page, "
            "clear it first the way a normal user would (prefer Accept all / Agree when "
            "that is the obvious path), then continue the task. Do not stop on the banner.\n"
        )
        agent_task = (
            f"{CAPABLE_AGENT_PREAMBLE}\n\n"
            f"{persona_line}\n"
            f"Customer segment: {segment}\n"
            f"{signed_hint}"
            f"{stay_put}"
            f"{consent_rule}"
            f"You are already on {start_url}. Continue from this page.\n"
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
            browser_session=browser_session,
            browser_profile=None,
            use_vision=True,
            use_judge=False,
            max_actions_per_step=2,
            calculate_cost=True,
            file_system_path=str(run_dir),
            save_conversation_path=str(run_dir / "conversation"),
            extend_system_message=(
                "You are a real user in a usability study, not an optimizer. "
                "Prefer obvious UI paths; comment on clarity and trust. "
                "Never claim to see content that is only 'implied' or absent from the "
                "current screenshot/DOM. Stay on the product site you were given. "
                "Dismiss cookie/consent/login interstitials before judging the product."
            ),
        )
        # Signal UI: agent loop is starting — replace screenshot with live view now.
        if on_step is not None and bb_session is not None:
            live_url = warm_live_url
            if not live_url:
                try:
                    from capability.browserbase_client import session_live_view_url

                    sid = getattr(bb_session, "id", None)
                    if sid:
                        live_url = await asyncio.to_thread(session_live_view_url, str(sid))
                except Exception:
                    live_url = None
            maybe = on_step(
                {
                    "step": None,
                    "progress_only": True,
                    "live_active": True,
                    "live_view_url": live_url,
                    "browserbase_session_id": getattr(bb_session, "id", None) or warm_bb_id,
                    "action": "Agent started — live browser on",
                    "thought": "I'm on the page now. Looking around before I click…",
                    "thought_detail": {
                        "thinking": "Landing page is open. Reading what's visible and choosing a first action."
                    },
                    "observation": "",
                    "url": start_url,
                    "screenshot_url": None,
                    "outcome": "neutral",
                }
            )
            if asyncio.iscoroutine(maybe):
                await maybe
        on_step_start, on_step_end = _make_step_hooks(
            screenshot_dir,
            study_id=study_id,
            agent_id=agent_id,
            target_url=start_url,
            on_step=on_step,
        )
        print(f"[{agent_id}] agent.run starting (warm={use_warm})", flush=True)
        history = await agent.run(
            max_steps=max_steps,
            on_step_start=on_step_start,
            on_step_end=on_step_end,
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
    # Keep the pre-agent landing frame (bbox_0) ahead of LLM steps.
    opening = screenshot_dir / "bbox_0.png"
    if opening.is_file() and opening.stat().st_size > 100:
        open_url = url
        try:
            if history is not None and hasattr(history, "urls"):
                urls0 = history.urls() or []
                if urls0:
                    open_url = urls0[0]
        except Exception:
            pass
        if not any(s.get("step") == 0 for s in trace):
            trace = [
                {
                    "step": 0,
                    "action": f"Opened {open_url}",
                    "observation": "Landing page loaded — agent starting…",
                    "thought": "",
                    "thought_detail": {},
                    "url": open_url,
                    "screenshot_url": (
                        f"/api/studies/{study_id}/agents/{agent_id}/screenshots/bbox_0.png"
                    ),
                    "boxes": [],
                    "outcome": "neutral",
                    "evidence_label": "Opening frame · before agent steps",
                },
                *trace,
            ]

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
