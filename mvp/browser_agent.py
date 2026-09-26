"""Browser Use agent runs for MVP — screenshots with DOM bounding boxes."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
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
# Per-agent walls and step caps are gone. The study budget is the only timer.
# These match that budget so browser-use does not apply its own 15s/60s kill,
# and max_failures is not used to stop an agent on a slow model call.
def _study_budget_timeout() -> int:
    try:
        from mvp.a11y_agent import study_budget_s

        return max(30, int(study_budget_s()))
    except Exception:
        return 480


MVP_LLM_TIMEOUT_S = int(os.environ.get("MVP_LLM_TIMEOUT_S", "") or _study_budget_timeout())
MVP_STEP_TIMEOUT_S = int(os.environ.get("MVP_STEP_TIMEOUT_S", "") or _study_budget_timeout())
MVP_HOLD_S = float(os.environ.get("MVP_PRESS_HOLD_S", "10") or "10")


def llm_run_concurrency() -> int:
    """How many browser agents may hold a live session at once.

    Eight parallel flash agents leave Linear (8/8). Twenty-four at once time out
    on navigate and never leave the homepage (0/8). Sixteen lets the other
    sixteen agents overlap that work so a 24-agent matrix still finishes inside
    the 360s e2e budget. Navigations stay capped separately.
    """
    raw = (os.environ.get("MVP_LLM_RUN_CONCURRENCY") or "16").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 16


def nav_concurrency() -> int:
    """How many agents may create a session and navigate at once.

    The 24-wide failure was the navigation burst, not the later clicks.
    """
    raw = (os.environ.get("MVP_NAV_CONCURRENCY") or "8").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 8


_NAV_SEMAPHORE: asyncio.Semaphore | None = None


def _nav_semaphore() -> asyncio.Semaphore:
    global _NAV_SEMAPHORE
    if _NAV_SEMAPHORE is None:
        _NAV_SEMAPHORE = asyncio.Semaphore(nav_concurrency())
    return _NAV_SEMAPHORE


def _study_bb_owner() -> str:
    from capability.browserbase_client import study_session_owner

    return study_session_owner()


def _png_is_blankish(path: Path) -> bool:
    """True when the shot is basically black / empty (loading splash).

    Align with e2e2 `_png_looks_blank`: small logo-on-black splashes (~32KB)
    are blank; large dark product UIs (Linear, etc.) with real texture are not.
    """
    try:
        if not path.is_file() or path.stat().st_size < 2500:
            return True
        size = path.stat().st_size
    except OSError:
        return True
    try:
        from PIL import Image

        im = Image.open(path).convert("RGB").resize((64, 40))
        pixels = list(im.getdata())
        lums = [0.2126 * r + 0.7152 * g + 0.0722 * b for r, g, b in pixels]
        mean = sum(lums) / max(1, len(lums))
        var = sum((x - mean) ** 2 for x in lums) / max(1, len(lums))
        # Small payloads: logo-on-black splash or empty pane.
        if size < 48000:
            if mean < 25.0:
                return True
            if mean < 40.0 and var < 250.0:
                return True
            return False
        # Large payloads: only near-uniform near-black (empty canvas).
        if mean < 12.0 and var < 80.0:
            return True
        return False
    except Exception:
        return size < 48000


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


def action_model_name(explicit: str | None = None) -> str:
    """Action-step model.

    The configured flash model is the one that leaves the homepage. Forcing its
    lite sibling (commit 1526a5a restored that downgrade) dropped Linear product
    task success from 8/8 to 1/8 on the same 8-agent harness. Set
    ``MVP_AGENT_ACTION_MODEL`` to pin a different model.
    """
    chosen = (explicit or os.environ.get("MVP_AGENT_ACTION_MODEL") or "").strip()
    if chosen:
        return chosen
    base = (os.environ.get("MVP_BROWSER_MODEL") or os.environ.get("MVP_LLM_MODEL") or MODEL or "").strip()
    return base or MODEL


def _product_session_call_kwargs() -> dict[str, Any]:
    """Signup's richest Browserbase flags. ``create_session`` walks the ladder.

    Proxies + captcha solve, then solve without proxies, then bare.
    ``advanced_stealth`` stays off (Hobby returns 403).
    """
    return {"proxies": True, "solve_captchas": True, "advanced_stealth": False}


_PAGE_STATE_JS = """() => {
  const text = ((document.body && document.body.innerText) || '')
    .replace(/\\s+/g, ' ').trim().slice(0, 2500);
  let canvas = '';
  for (const c of document.querySelectorAll('canvas')) {
    try {
      const w = c.width || 0, h = c.height || 0;
      if (w < 2 || h < 2) continue;
      const ctx = c.getContext('2d');
      if (!ctx) continue;
      const data = ctx.getImageData(0, 0, w, h).data;
      // A thin stroke misses an 8x8 grid. Count non-white pixels on a denser grid.
      const step = Math.max(4, Math.floor(Math.min(w, h) / 48));
      let dark = 0, total = 0;
      for (let y = 0; y < h; y += step) {
        for (let x = 0; x < w; x += step) {
          const i = (y * w + x) * 4;
          if ((data[i] + data[i + 1] + data[i + 2]) < 700) dark++;
          total++;
        }
      }
      canvas += w + 'x' + h + ':dark=' + dark + '/' + total + ';';
    } catch (e) {
      canvas += 'taint;';
    }
  }
  return {text, canvas};
}"""

_CAPTCHA_JS = """() => {
  const text = ((document.body && document.body.innerText) || '').slice(0, 8000);
  const html = ((document.documentElement && document.documentElement.innerHTML) || '').slice(0, 180000);
  const blob = html + '\\n' + text;
  const markers = [];
  if (/press\\s*(?:&|and)\\s*hold/i.test(text) || /press\\s*(?:&|and)\\s*hold/i.test(html))
    markers.push('press-and-hold');
  if (/px-captcha|perimeterx|\\b_px\\b|human challenge/i.test(blob)) markers.push('perimeterx');
  if (/datadome|captcha-delivery\\.com/i.test(blob)) markers.push('datadome');
  if (/challenges\\.cloudflare\\.com|cf-turnstile|just a moment/i.test(blob)) markers.push('turnstile');
  if (/hcaptcha/i.test(blob)) markers.push('hcaptcha');
  if (/recaptcha|g-recaptcha/i.test(blob)) markers.push('recaptcha');
  if (/arkoselabs|funcaptcha/i.test(blob)) markers.push('arkose');
  if (/access denied|are you a robot|verify you are human|bot detection/i.test(text))
    markers.push('bot-wall');
  let box = null;
  const nodes = document.querySelectorAll('button, [role=button], div, span, p, a, iframe, #px-captcha, .px-captcha, [id*="px-captcha"]');
  for (const el of nodes) {
    const t = (el.innerText || el.getAttribute('aria-label') || el.title || '').trim();
    const id = ((el.id || '') + ' ' + (el.className || '') + ' ' + (el.src || '')).toLowerCase();
    const hold = /press\\s*(?:&|and)?\\s*hold/i.test(t) || /\\bhold\\b/i.test(t) && t.length < 48 || id.includes('px-captcha') || id.includes('perimeterx');
    if (!hold) continue;
    if (t.length > 180 && !id.includes('px-captcha')) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 24 || r.height < 12) continue;
    if (r.bottom < 0 || r.top > (window.innerHeight || 800)) continue;
    box = {
      x: Math.round(r.x + r.width / 2),
      y: Math.round(r.y + r.height / 2),
      text: (t || id).slice(0, 80),
    };
    break;
  }
  return {markers, box, title: document.title || '', snippet: text.slice(0, 280)};
}"""


async def _eval_page(session: Any, expression: str) -> Any:
    page = await asyncio.wait_for(session.get_current_page(), timeout=8)
    if page is None:
        return None
    # browser-use Page.evaluate returns a string. Objects arrive as JSON.
    raw = await asyncio.wait_for(page.evaluate(expression), timeout=8)
    if isinstance(raw, str):
        text = raw.strip()
        if text.startswith("{") or text.startswith("["):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return text
    return raw


async def _page_state(session: Any) -> dict[str, str] | None:
    try:
        raw = await _eval_page(session, _PAGE_STATE_JS)
    except Exception as exc:  # noqa: BLE001
        print(f"page state capture failed: {exc!r}"[:240], flush=True)
        return None
    if not isinstance(raw, dict):
        return None
    return {
        "text": str(raw.get("text") or "")[:2500],
        "canvas": str(raw.get("canvas") or "")[:4000],
    }


async def _mouse_path(session: Any, points: list[tuple[int, int]], *, hold_s: float = 0.0) -> None:
    """Mouse down, optional hold, stepped move, mouse up. Real CDP events."""
    if not points:
        return
    cdp = await session.get_or_create_cdp_session()
    client = cdp.cdp_client
    sid = cdp.session_id

    async def send(params: dict[str, Any]) -> None:
        await client.send.Input.dispatchMouseEvent(params, session_id=sid)

    x, y = points[0]
    await send({"type": "mouseMoved", "x": x, "y": y})
    await send(
        {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1}
    )
    if hold_s > 0:
        await asyncio.sleep(hold_s)
    for px, py in points[1:]:
        await send(
            {
                "type": "mouseMoved",
                "x": px,
                "y": py,
                "button": "left",
                "buttons": 1,
            }
        )
        await asyncio.sleep(0.02)
    lx, ly = points[-1]
    await send(
        {"type": "mouseReleased", "x": lx, "y": ly, "button": "left", "clickCount": 1}
    )


def _line_points(x0: int, y0: int, x1: int, y1: int, steps: int = 8) -> list[tuple[int, int]]:
    points = []
    steps = max(2, steps)
    for i in range(steps + 1):
        t = i / steps
        points.append((int(round(x0 + (x1 - x0) * t)), int(round(y0 + (y1 - y0) * t))))
    return points


async def _detect_captcha(session: Any) -> dict[str, Any] | None:
    try:
        raw = await _eval_page(session, _CAPTCHA_JS)
    except Exception:
        return None
    if not isinstance(raw, dict):
        return None
    markers = [str(m) for m in (raw.get("markers") or []) if m]
    if not markers and not raw.get("box"):
        return None
    return {
        "markers": markers,
        "box": raw.get("box") if isinstance(raw.get("box"), dict) else None,
        "title": str(raw.get("title") or "")[:120],
        "snippet": str(raw.get("snippet") or "")[:280],
    }


async def _maybe_press_and_hold(session: Any, *, agent_id: str) -> dict[str, Any] | None:
    """Hold a press-and-hold widget with the mouse. No CapSolver."""
    found = await _detect_captcha(session)
    if not found:
        return None
    markers = found.get("markers") or []
    box = found.get("box") or {}
    kind = "press-and-hold" if "press-and-hold" in markers else (markers[0] if markers else "")
    held = False
    if kind == "press-and-hold" and box.get("x") is not None and box.get("y") is not None:
        x, y = int(box["x"]), int(box["y"])
        print(
            f"[{agent_id}] captcha {markers} — holding mouse at ({x},{y}) for {MVP_HOLD_S:.0f}s",
            flush=True,
        )
        try:
            await _mouse_path(session, [(x, y)], hold_s=MVP_HOLD_S)
            held = True
            await asyncio.sleep(1.0)
        except Exception as exc:  # noqa: BLE001
            print(f"[{agent_id}] press-and-hold failed: {exc!r}", flush=True)
    else:
        print(f"[{agent_id}] captcha markers={markers} (no mouse hold)", flush=True)
    return {
        "kind": kind or ",".join(markers),
        "markers": markers,
        "held": held,
        "box": box or None,
        "title": found.get("title") or "",
        "snippet": found.get("snippet") or "",
    }


def _study_tools() -> Any:
    from browser_use import Tools
    from browser_use.agent.views import ActionResult

    tools = Tools(exclude_actions=["write_file", "replace_file"])

    @tools.action(
        "Draw or drag. Mouse down at start_x,start_y, move in a straight line to "
        "end_x,end_y, then mouse up. Selecting a rectangle or line tool does not "
        "place a shape — drag across the canvas. Coordinates are viewport pixels."
    )
    async def drag(start_x: int, start_y: int, end_x: int, end_y: int, browser_session):  # noqa: ANN001
        if browser_session is None:
            return ActionResult(error="No browser session for drag")
        try:
            await _mouse_path(
                browser_session,
                _line_points(int(start_x), int(start_y), int(end_x), int(end_y)),
            )
        except Exception as exc:  # noqa: BLE001
            return ActionResult(error=f"Drag failed: {exc}")
        return ActionResult(
            extracted_content=f"Dragged from ({start_x},{start_y}) to ({end_x},{end_y}).",
            long_term_memory=f"Dragged from ({start_x},{start_y}) to ({end_x},{end_y}).",
        )

    @tools.action(
        "Press and hold the left mouse button at x,y, then release. Use this on a "
        "Press and Hold or PerimeterX check. Do not call an external captcha solver."
    )
    async def press_and_hold(x: int, y: int, browser_session, seconds: int = 10):  # noqa: ANN001
        if browser_session is None:
            return ActionResult(error="No browser session for press_and_hold")
        # PerimeterX ignores a short press. Always hold about 10s.
        hold = 10.0
        try:
            await _mouse_path(browser_session, [(int(x), int(y))], hold_s=hold)
        except Exception as exc:  # noqa: BLE001
            return ActionResult(error=f"Press-and-hold failed: {exc}")
        return ActionResult(
            extracted_content=f"Held the mouse at ({x},{y}) for {hold:.0f}s.",
            long_term_memory=f"Held the mouse at ({x},{y}) for {hold:.0f}s.",
        )

    return tools


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

    step_latency_s = None
    meta = getattr(h, "metadata", None)
    if meta is not None:
        try:
            step_latency_s = round(float(meta.duration_seconds), 3)
        except Exception:
            step_latency_s = None

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
        "step_latency_s": step_latency_s,
    }


_INTERACT_ACTIONS = {
    "click",
    "input",
    "input_text",
    "type",
    "send_keys",
    "go_to_url",
    "search",
    "search_page",
    "scroll",
    "select_dropdown",
    "select_dropdown_option",
    "upload_file",
    "drag",
    "press_and_hold",
    "switch_tab",
}
_BLOCKED_MARKERS = (
    "captcha",
    "press & hold",
    "press and hold",
    "verification",
    "access denied",
    "login wall",
    "sign in to continue",
    "sign in required",
)


def _action_name(action: Any) -> str:
    label = _action_label(action).lower()
    return label.split("—")[0].split(":")[0].strip()


def _same_page(url: str | None, start_url: str | None) -> bool:
    if not url or not start_url:
        return True

    def key(raw: str) -> tuple[str, str, str]:
        try:
            parsed = urlparse(raw)
        except Exception:
            return ("", raw, "")
        host = (parsed.hostname or "").lower().removeprefix("www.")
        path = (parsed.path or "/").rstrip("/") or "/"
        return (host, path, parsed.query or "")

    return key(url) == key(start_url)


def _history_interact_count(agent: Any) -> int:
    history = getattr(agent, "history", None)
    items = list(getattr(history, "history", None) or [])
    count = 0
    for item in items:
        model_out = getattr(item, "model_output", None)
        actions = getattr(model_out, "action", None) if model_out is not None else None
        if actions is None:
            continue
        if not isinstance(actions, list):
            actions = [actions]
        for action in actions:
            if _action_name(action) in _INTERACT_ACTIONS:
                count += 1
    return count


def reject_early_done(agent: Any, start_url: str) -> bool:
    """Undo a done action that only describes the page the agent opened.

    Returns True when the done flag was cleared so the loop keeps going.
    A done call stands when the agent left the start URL, interacted at least
    twice, or the page is clearly blocked.
    """
    history = getattr(agent, "history", None)
    if history is None or not history.is_done():
        return False
    items = list(getattr(history, "history", None) or [])
    if not items:
        return False
    results = list(getattr(items[-1], "result", None) or [])
    if not results:
        return False
    last = results[-1]
    blob = " ".join(
        str(getattr(last, field, "") or "")
        for field in ("extracted_content", "long_term_memory", "error")
    ).lower()
    state = getattr(items[-1], "state", None)
    url = str(getattr(state, "url", None) or start_url)
    blocked = any(marker in blob for marker in _BLOCKED_MARKERS)
    # One click, drag, or typed field is enough. Requiring two made canvas
    # runs call done, get rejected, and spend the rest of the step cap repeating it.
    if blocked or not _same_page(url, start_url) or _history_interact_count(agent) >= 1:
        return False
    # success=True is invalid once is_done is cleared.
    if getattr(last, "success", None) is True:
        last.success = None
    last.is_done = False
    last.error = (
        "Still on the start page without doing the task. Click, type, or open the "
        "section the task asks for. Call done only when that page or state is open, "
        "or when a captcha or login wall blocks you."
    )
    print(f"rejected early done on {url}", flush=True)
    return True


def _make_step_hooks(
    screenshot_dir: Path,
    *,
    study_id: str,
    agent_id: str,
    start_url: str = "",
    on_step: Callable[[dict[str, Any]], Awaitable[None] | None] | None = None,
    page_state: dict[str, Any] | None = None,
):
    """Capture a screenshot with DOM bounding boxes drawn on it, once per step.

    browser-use takes its own screenshot *before* injecting highlights, so history
    screenshots are always clean. Re-injecting the overlay here is the only way to
    get boxed frames like the Bland bakeoff traces.

    Page-state signatures are taken before highlights so the overlay is not a
    false DOM change.
    """
    state = {"step": 0}
    book = page_state if isinstance(page_state, dict) else {}

    async def _emit(step: dict[str, Any]) -> None:
        if on_step is None:
            return
        maybe = on_step(step)
        if asyncio.iscoroutine(maybe):
            await maybe

    async def on_step_start(agent: Any) -> None:
        nxt = state["step"] + 1
        session = getattr(agent, "browser_session", None)
        holds = int(book.get("holds") or 0)
        if session is not None and holds < 1:
            try:
                found = await _maybe_press_and_hold(session, agent_id=agent_id)
            except Exception as exc:  # noqa: BLE001
                print(f"[{agent_id}] captcha check failed: {exc!r}", flush=True)
                found = None
            if found:
                book["captcha"] = found
                if found.get("held"):
                    book["holds"] = holds + 1
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
        try:
            reject_early_done(agent, start_url)
        except Exception as exc:  # noqa: BLE001
            print(f"[{agent_id}] early-done check failed: {exc!r}", flush=True)
        state["step"] += 1
        step_no = state["step"]
        if book.get("t0") is not None and book.get("first_action_s") is None:
            book["first_action_s"] = round(time.monotonic() - float(book["t0"]), 3)
        session = getattr(agent, "browser_session", None)
        if session is None:
            return
        try:
            sig = await _page_state(session)
            if sig:
                book.setdefault("sigs", {})[step_no] = sig
        except Exception:
            pass
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
        sigs = book.get("sigs") if isinstance(book.get("sigs"), dict) else {}
        if step_no in sigs:
            step["state_sig"] = sigs[step_no]
        await _emit(step)

    return on_step_start, on_step_end


_CONSENT_CLICK_JS = """
() => {
  const texts = [
    'accept all', 'accept all cookies', 'accept cookies', 'i agree', 'agree',
    'allow all', 'got it', 'ok', 'okay', 'continue', 'consent',
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


async def _ensure_cdp_connected(browser_session: Any, *, agent_id: str) -> None:
    """Reconnect if the socket died while this agent waited for a run slot.

    browser-use raises 'Root CDP client not initialized' once the websocket
    leaves OPEN. connect() tears down a dead client and opens a new one.
    """
    if browser_session is None:
        return
    try:
        connected = bool(browser_session.is_cdp_connected)
    except Exception:
        connected = False
    if connected:
        return
    print(f"[{agent_id}] CDP down — reconnecting before agent.run", flush=True)
    try:
        await asyncio.wait_for(browser_session.connect(), timeout=30)
    except Exception as exc:  # noqa: BLE001
        print(f"[{agent_id}] CDP reconnect failed: {exc!r}", flush=True)


async def _dismiss_consent_banners(browser_session: Any, *, agent_id: str) -> None:
    try:
        page = await asyncio.wait_for(browser_session.get_current_page(), timeout=8)
        if page is None:
            return
        for _ in range(2):
            clicked = await asyncio.wait_for(page.evaluate(_CONSENT_CLICK_JS), timeout=5)
            if not clicked:
                break
            print(f"[{agent_id}] dismissed consent: {clicked!r}", flush=True)
            await asyncio.sleep(0.4)
    except Exception as exc:  # noqa: BLE001
        print(f"[{agent_id}] consent dismiss skipped: {exc!r}", flush=True)


async def _emit_opening_frame(
    browser_session: Any,
    *,
    screenshot_dir: Path,
    study_id: str,
    agent_id: str,
    url: str,
    on_step: Callable[[dict[str, Any]], Awaitable[None] | None] | None = None,
    shot_name: str = "bbox_0.png",
) -> None:
    """Navigate + full-viewport screenshot before the LLM agent loop."""
    try:
        await asyncio.wait_for(browser_session.navigate_to(url), timeout=45)
    except Exception as exc:  # noqa: BLE001
        print(f"[{agent_id}] opening navigate failed: {exc!r}", flush=True)

    await _dismiss_consent_banners(browser_session, agent_id=agent_id)
    # Wait for real paint — 0.2s was capturing Vimeo/Dailymotion black splashes.
    page = None
    try:
        page = await asyncio.wait_for(browser_session.get_current_page(), timeout=8)
    except Exception as exc:  # noqa: BLE001
        print(f"[{agent_id}] opening get_current_page failed: {exc!r}", flush=True)
    if page is not None:
        try:
            await asyncio.wait_for(page.wait_for_load_state("domcontentloaded"), timeout=15)
        except Exception:
            pass
        # Extra settle — 24-way Browserbase fleets often still show splash at DOMContentLoaded.
        try:
            await asyncio.sleep(2.5)
        except Exception:
            pass
        try:
            await asyncio.wait_for(
                page.wait_for_function(
                    "() => document.body && (document.body.innerText || '').trim().length > 40",
                    timeout=8000,
                ),
                timeout=10,
            )
        except Exception:
            pass
        try:
            await asyncio.wait_for(
                page.evaluate("() => window.scrollTo(0, 0)"),
                timeout=5,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[{agent_id}] opening scrollTop failed: {exc!r}", flush=True)
        # Cookie / consent banners that cover the page.
        try:
            await asyncio.wait_for(
                page.evaluate(
                    """() => {
                      const labels = ['accept all','accept','agree','got it','i agree','allow all','ok'];
                      const els = [...document.querySelectorAll('button,[role=button],a')];
                      for (const el of els) {
                        const t = (el.innerText || el.textContent || '').trim().toLowerCase();
                        if (!t || t.length > 40) continue;
                        if (!labels.some(l => t === l || t.startsWith(l))) continue;
                        const r = el.getBoundingClientRect();
                        if (r.width < 8 || r.height < 8) continue;
                        el.click();
                        return t;
                      }
                      return '';
                    }"""
                ),
                timeout=5,
            )
        except Exception:
            pass

    shot_path = screenshot_dir / shot_name

    async def _snap_once() -> bool:
        try:
            await asyncio.wait_for(
                browser_session.take_screenshot(path=str(shot_path), full_page=False),
                timeout=20,
            )
            return True
        except TypeError:
            try:
                await asyncio.wait_for(
                    browser_session.take_screenshot(path=str(shot_path)),
                    timeout=20,
                )
                return True
            except Exception as exc:  # noqa: BLE001
                print(f"[{agent_id}] opening screenshot failed: {exc!r}", flush=True)
                return False
        except Exception as exc:  # noqa: BLE001
            print(f"[{agent_id}] opening screenshot failed: {exc!r}", flush=True)
            return False

    ok = False
    # Heavy marketing / SPA landings (Linear, etc.) often stay on a ~32KB logo
    # splash for several seconds under parallel Browserbase load — wait longer.
    for attempt in range(8):
        await asyncio.sleep(1.2 if attempt == 0 else 2.5)
        if not await _snap_once():
            continue
        if not _png_is_blankish(shot_path):
            ok = True
            break
        print(
            f"[{agent_id}] opening frame blankish (attempt {attempt + 1}/8) — waiting for paint",
            flush=True,
        )
        if page is not None:
            try:
                await asyncio.wait_for(page.reload(wait_until="domcontentloaded"), timeout=10)
            except Exception:
                try:
                    await asyncio.wait_for(browser_session.navigate_to(url), timeout=15)
                except Exception:
                    pass

    if not ok:
        if not shot_path.is_file() or shot_path.stat().st_size < 100:
            print(f"[{agent_id}] opening screenshot missing/empty", flush=True)
            return
        if _png_is_blankish(shot_path):
            print(
                f"[{agent_id}] opening frame still blank after extended wait — "
                "publishing best effort so same-site backfill can replace it",
                flush=True,
            )
            # Fall through and publish — backfill_site_opening_shots can replace
            # blank splash from a same-site donor once any agent gets real paint.
        else:
            print(
                f"[{agent_id}] opening frame marginal — publishing best effort",
                flush=True,
            )

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
    return [
        _trace_step_from_history_item(
            h, i, study_id=study_id, agent_id=agent_id, screenshot_dir=screenshot_dir
        )
        for i, h in enumerate(items, start=1)
    ]


def _urls_match(a: str, b: str) -> bool:
    def norm(u: str) -> str:
        p = urlparse((u or "").strip())
        host = (p.hostname or "").lower().removeprefix("www.")
        path = (p.path or "/").rstrip("/") or "/"
        return f"{host}{path}"

    return bool(a and b and norm(a) == norm(b))


async def _page_block_reason(browser_session: Any) -> str | None:
    """Return a classify_page_block reason if the open tab is a WAF/deny interstitial."""
    try:
        from capability.site_preflight import classify_page_block

        page = await asyncio.wait_for(browser_session.get_current_page(), timeout=5)
        title = ""
        final_url = ""
        body = ""
        try:
            title = await asyncio.wait_for(page.title(), timeout=3)
        except Exception:
            pass
        try:
            final_url = str(page.url or "")
        except Exception:
            pass
        try:
            body = await asyncio.wait_for(
                page.evaluate(
                    "() => (document.body && (document.body.innerText || '')) "
                    ".slice(0, 4000)"
                ),
                timeout=5,
            )
            body = str(body or "")
        except Exception:
            body = ""
        blocked, reason = classify_page_block(
            final_url=final_url, title=title or "", body=body or ""
        )
        return reason if blocked else None
    except Exception as exc:  # noqa: BLE001
        print(f"[warm] block classify skipped: {exc!r}", flush=True)
        return None


async def warm_opening_session(
    *, study_id: str, url: str, proxies: bool = False
) -> dict[str, Any] | None:
    """Create Browserbase + navigate + screenshot while brief LLMs run.

    Returns a live browser_session already on ``url`` with bbox_0.png written under
    ``MVP_RUNS_DIR / study_id / _warm``. Caller must either hand this to
    ``run_browser_agent(..., warm=...)`` or ``close_warm_opening``.

    If the landing page is a WAF/access-denied interstitial, retries once with
    residential proxies (generic — not site-specific).
    """
    if os.environ.get("MVP_FORCE_LOCAL_BROWSER", "").lower() in {"1", "true", "yes"}:
        return None
    run_dir = MVP_RUNS_DIR / study_id / "_warm"
    screenshot_dir = run_dir / "screenshots"
    run_dir.mkdir(parents=True, exist_ok=True)
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    bb_session = None
    browser_session = None
    t0 = time.time()
    t_bb_create: float | None = None
    t_navigate_done: float | None = None
    t_paint: float | None = None
    try:
        from browser_use import BrowserSession

        bb_session = await asyncio.to_thread(
            create_session,
            keep_alive=True,
            owner=_study_bb_owner(),
            study_id=study_id,
            **_product_session_call_kwargs(),
        )
        t_bb_create = time.time() - t0
        connect = getattr(bb_session, "connect_url", None)
        if not connect:
            raise RuntimeError("Browserbase session missing connect_url")
        browser_session = BrowserSession(browser_profile=_browserbase_profile(connect))
        await browser_session.start()
        t_nav0 = time.time()
        # YouTube signed-out home is often an empty splash in automation —
        # warm a search-results URL so we get a real product frame for e2e.
        paint_url = url
        try:
            host = (urlparse(url).hostname or "").lower()
            if "youtube.com" in host or "youtu.be" in host:
                from mvp.auth_state import youtube_bootstrap_url

                paint_url = youtube_bootstrap_url("videos to watch", "warm")
                print(f"[warm] YouTube bootstrap paint via {paint_url}", flush=True)
        except Exception as yt_exc:  # noqa: BLE001
            print(f"[warm] YouTube bootstrap skipped: {yt_exc!r}", flush=True)
            paint_url = url
        await _emit_opening_frame(
            browser_session,
            screenshot_dir=screenshot_dir,
            study_id=study_id,
            agent_id="_warm",
            url=paint_url,
            on_step=None,
        )
        t_navigate_done = time.time() - t_nav0
        shot = screenshot_dir / "bbox_0.png"
        if not shot.is_file() or shot.stat().st_size < 100:
            raise RuntimeError("warm opening screenshot missing")
        block_reason = await _page_block_reason(browser_session)
        if block_reason and not proxies:
            print(
                f"[warm] blocked interstitial for {url}: {block_reason} — "
                "retrying with proxies",
                flush=True,
            )
            try:
                await close_warm_opening(
                    {
                        "bb_session": bb_session,
                        "browser_session": browser_session,
                        "owns_session": True,
                    }
                )
            except Exception:
                pass
            bb_session = None
            browser_session = None
            return await warm_opening_session(
                study_id=study_id, url=url, proxies=True
            )
        t_paint = time.time() - t0
        live_view = None
        try:
            from capability.browserbase_client import session_live_view_url

            sid = getattr(bb_session, "id", None)
            if sid:
                live_view = await asyncio.to_thread(session_live_view_url, str(sid))
        except Exception as live_exc:  # noqa: BLE001
            print(f"[warm] live view url failed: {live_exc!r}", flush=True)
        timing = {
            "bb_create_s": round(t_bb_create, 3) if t_bb_create is not None else None,
            "navigate_and_paint_s": round(t_navigate_done, 3)
            if t_navigate_done is not None
            else None,
            "first_paint_total_s": round(t_paint, 3) if t_paint is not None else None,
            "blankish": _png_is_blankish(shot),
            "blocked": bool(block_reason),
            "block_reason": block_reason,
            "proxies": bool(proxies),
        }
        print(
            f"[warm] first pixels ready for {url} "
            f"bb_create={timing['bb_create_s']}s "
            f"nav+paint={timing['navigate_and_paint_s']}s "
            f"total={timing['first_paint_total_s']}s "
            f"blankish={timing['blankish']} blocked={timing['blocked']} "
            f"proxies={timing['proxies']}",
            flush=True,
        )
        return {
            "url": url,
            "bb_session": bb_session,
            "browser_session": browser_session,
            "shot_path": shot,
            "owns_session": True,
            "live_view_url": live_view,
            "browserbase_session_id": getattr(bb_session, "id", None),
            "timing": timing,
            "blocked": bool(block_reason),
            "block_reason": block_reason,
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
    wall_s: float | None = None,
) -> dict[str, Any]:
    """Run Browser Use (Browserbase or local Chromium) and return a bbox screenshot trace.

    First real pixels are emitted as soon as the target URL is open — before the
    LLM agent loop, and (for non-YouTube) before waiting on auth vault I/O.
    If ``warm`` is a matching pre-opened session from ``warm_opening_session``,
    the landing screenshot is published immediately and the LLM continues on it.
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

    model = action_model_name(model)
    # wall_s is ignored. A hung browser is stopped by the study budget, or by
    # the accessibility loop's stuck detector on the path studies actually run.
    _ = wall_s
    _budget = _study_budget_timeout()
    os.environ.setdefault("BROWSER_USE_CDP_TIMEOUT_S", str(_budget))
    os.environ.setdefault("BROWSER_USE_ACTION_TIMEOUT_S", str(_budget))

    run_dir = MVP_RUNS_DIR / study_id / agent_id
    screenshot_dir = run_dir / "screenshots"
    run_dir.mkdir(parents=True, exist_ok=True)
    screenshot_dir.mkdir(parents=True, exist_ok=True)

    from mvp.profile_pool import clone_for_url, discard as discard_profile

    from mvp.auth_state import (
        ensure_site_auth,
        storage_state_for_url,
        youtube_bootstrap_url,
        youtube_is_signed_in,
        youtube_needs_content_bootstrap,
    )

    start_url = url
    yt_hint = ""
    host = (urlparse(url).hostname or "").lower()
    is_youtube = "youtube.com" in host or "youtu.be" in host

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

    # YouTube: never block the UI on vault I/O before first pixels.
    # Load disk cookies fast → open browser → screenshot; refresh auth in parallel.
    auth_task: asyncio.Task | None = None
    storage_state: Any = None

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

    if is_youtube:
        await _pulse(f"Preparing YouTube session for {url}…")
        # Instant disk cookies so we can open a browser without waiting on sign-in.
        storage_state = storage_state_for_url(url)
        # Background refresh only when auto sign-in/sign-up is enabled.
        if os.environ.get("MVP_AUTO_SIGNUP", "").lower() in {"1", "true", "yes"} or os.environ.get(
            "MVP_AUTO_SIGNIN", ""
        ).lower() in {"1", "true", "yes"}:
            auth_task = asyncio.create_task(asyncio.to_thread(ensure_site_auth, url))
        if youtube_needs_content_bootstrap(url, storage_state):
            start_url = youtube_bootstrap_url(task_prompt, persona.get("name") or "")
            yt_hint = (
                "YouTube's signed-out home feed is often empty in automation. You were opened on "
                "search results with real videos — use those, refine the query, or open a video. "
                "If you can sign in / avatar is visible, you may also open Home afterward.\n"
            )
            await _pulse(f"Opening search results — {start_url.split('search_query=')[-1][:40]}…")
        elif youtube_is_signed_in(
            storage_state if isinstance(storage_state, dict) else None
        ):
            yt_hint = (
                "You are signed into YouTube (Gmail session cookies loaded). Use the personalized "
                "home feed, subscriptions, and account UI as a real logged-in user would.\n"
            )
            await _pulse("Signed-in cookies ready — opening YouTube…")
        else:
            await _pulse("Opening YouTube…")
    elif not use_warm:
        await _pulse(f"Opening {url}…")
        auth_task = asyncio.create_task(asyncio.to_thread(ensure_site_auth, url))

    cookie_state = storage_state if isinstance(storage_state, dict) else None
    if storage_state and isinstance(storage_state, dict):
        state_path = run_dir / "storage_state.json"
        state_path.write_text(json.dumps(storage_state))
        storage_state = str(state_path)

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
            if not is_youtube and auth_task is None:
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
            # Stash live URL and turn live view ON immediately — page is open.
            if on_step is not None and (warm_live_url or bb_session is not None):
                maybe = on_step(
                    {
                        "step": None,
                        "progress_only": True,
                        "live_active": True,
                        "live_view_url": warm_live_url,
                        "browserbase_session_id": warm_bb_id,
                        "action": "Page open — live browser on",
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

    # Only a few navigations at once. The run slot above this stays held so
    # the model loop can overlap once the page is actually open.
    hold_nav = not use_warm
    if hold_nav:
        await _nav_semaphore().acquire()
    try:
        if not use_warm:
            if force_local:
                # A cloned signed-in profile beats cookie injection: Google binds session
                # cookies to the profile, so transplanted cookies report LOGGED_IN=false.
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
                    yt_hint = (
                        "You are signed in on this site. Use the personalized home feed, "
                        "subscriptions, and account UI as a real logged-in user would.\n"
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
                        create_session,
                        keep_alive=True,
                        owner=_study_bb_owner(),
                        study_id=study_id,
                        **_product_session_call_kwargs(),
                    )
                    print(
                        f"[{agent_id}] browserbase flags={getattr(bb_session, 'flags', None)}",
                        flush=True,
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
                # Flip live view ON immediately — don't wait for LLM / agent.run.
                if on_step is not None and bb_session is not None and not force_local:
                    live_url = None
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
                            "browserbase_session_id": getattr(bb_session, "id", None),
                            "action": "Live browser on",
                            "thought": "Page is open — live view connected.",
                            "thought_detail": {},
                            "observation": "",
                            "url": start_url,
                            "screenshot_url": None,
                            "outcome": "neutral",
                        }
                    )
                    if asyncio.iscoroutine(maybe):
                        await maybe
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
    finally:
        if hold_nav:
            _nav_semaphore().release()

    page_state: dict[str, Any] = {
        "sigs": {},
        "holds": 0,
        "captcha": None,
        "t0": None,
        "first_action_s": None,
    }
    try:
        # Auth/cookies after first pixels (non-YouTube, non-warm).
        # Warm sessions skip this — first click should not wait on vault I/O.
        # Build the LLM in parallel with any remaining auth wait.
        def _build_llm() -> Any:
            from browser_use import ChatGoogle

            kwargs: dict[str, Any] = {
                "model": model,
                "vertexai": True,
                "credentials": vertex_credentials(),
                "project": GCP_PROJECT,
                "location": location_for(model),
                "temperature": 0,
                # One attempt. A slow call is aborted by http timeout and the next
                # agent step retries, instead of five backoffs eating the wall.
                "max_retries": 1,
                "max_output_tokens": 768,
                "http_options": {"timeout": max(3000, (MVP_LLM_TIMEOUT_S - 2) * 1000)},
            }
            # Gemini 2.5 thinking is what stretched the first call past a minute.
            if "2.5" in model or "gemini-3" in model:
                kwargs["thinking_budget"] = 0
            return ChatGoogle(**kwargs)

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
            if storage_state and isinstance(storage_state, dict):
                state_path = run_dir / "storage_state.json"
                state_path.write_text(json.dumps(storage_state))
                storage_state = str(state_path)

        if cookie_state and browser_session is not None:
            injected = await _inject_cookies(browser_session, cookie_state)
            print(f"[{agent_id}] injected {injected} cookies via CDP", flush=True)

        from browser_use import Agent

        llm = await llm_task
        persona_line = f"You are {persona.get('name')}: {persona.get('bio')}"
        stay_put = (
            f"CRITICAL: Stay on {start_url} and its own pages/subdomains only. "
            f"Do not navigate to other products or competitors (especially not YouTube, "
            f"Vimeo, or Dailymotion unless that is exactly this site). "
            f"Evaluate the task using THIS site’s UI, search, and docs.\n"
        )
        agent_task = (
            f"{CAPABLE_AGENT_PREAMBLE}\n\n"
            f"{persona_line}\n"
            f"Customer segment: {segment}\n"
            f"{yt_hint}"
            f"{stay_put}"
            f"You are already on {start_url}. Continue from this page.\n"
            f"Task: {task_prompt}\n"
            f"Behave like this persona would — note confusion, pricing concerns, and UX friction.\n"
            f"Do not judge the site from the landing page alone. The task is not done when you "
            f"can describe the first screen.\n"
            f"Click, type, and open the specific page or control the task names. "
            f"Call done only after that page or state is on screen, or when a captcha, "
            f"login wall, or missing control blocks you. Say which.\n"
            f"On a drawing canvas, clicking a shape tool does not place a shape. "
            f"Select the tool, then use drag (mouse down, move, mouse up) across the canvas.\n"
            f"If the page says Press and Hold, use press_and_hold on that control. "
            f"Do not use an external captcha service.\n"
            f"Do not write todo files. Do not wait if the page is already visible.\n"
        )

        agent = Agent(
            task=agent_task,
            llm=llm,
            browser_session=browser_session,
            browser_profile=None,
            tools=_study_tools(),
            use_vision=True,
            vision_detail_level="low",
            use_thinking=False,
            # flash_mode emits actions the controller drops ("no handler"),
            # so the step fails without a click. Planning stays off so the
            # first action is a click, not a todo file.
            flash_mode=False,
            enable_planning=False,
            use_judge=False,
            # Do not stop the agent because a model call was slow or failed.
            max_failures=10_000,
            llm_timeout=MVP_LLM_TIMEOUT_S,
            step_timeout=MVP_STEP_TIMEOUT_S,
            llm_screenshot_size=(800, 450),
            message_compaction=False,
            max_actions_per_step=2,
            calculate_cost=True,
            file_system_path=str(run_dir),
            save_conversation_path=str(run_dir / "conversation"),
            # We already navigated + screenshotted. Default True makes browser-use
            # re-navigate to the URL in the task text BEFORE the first hooked step —
            # live iframe up, step rail stuck at opening, looks frozen on YouTube.
            directly_open_url=False,
            extend_system_message=(
                "You are a real user in a usability study, not an optimizer. "
                "Prefer obvious UI paths; comment on clarity and trust. "
                "Never claim to see content that is only 'implied' or absent from the "
                "current screenshot/DOM. Stay on the product site you were given. "
                "If a cookie/consent banner blocks the page, Accept all / Agree first, "
                "then continue the task. "
                "Do not call done on the landing page. Do not spend a step writing notes "
                "or waiting. Act on the task. "
                "To draw, call drag with viewport coordinates. A click on the rectangle "
                "tool is not a rectangle. "
                "On a Press and Hold check, call press_and_hold. Never call CapSolver "
                "or another captcha API."
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
        page_state["t0"] = time.monotonic()
        if browser_session is not None:
            try:
                sig0 = await _page_state(browser_session)
                if sig0:
                    page_state["sigs"][0] = sig0
            except Exception:
                pass
            try:
                found = await _maybe_press_and_hold(browser_session, agent_id=agent_id)
                if found:
                    page_state["captcha"] = found
                    if found.get("held"):
                        page_state["holds"] = 1
                        sig_after = await _page_state(browser_session)
                        if sig_after:
                            page_state["sigs"][0] = sig_after
            except Exception as exc:  # noqa: BLE001
                print(f"[{agent_id}] opening captcha check failed: {exc!r}", flush=True)
        on_step_start, on_step_end = _make_step_hooks(
            screenshot_dir,
            study_id=study_id,
            agent_id=agent_id,
            start_url=start_url,
            on_step=on_step,
            page_state=page_state,
        )
        await _ensure_cdp_connected(browser_session, agent_id=agent_id)
        print(
            f"[{agent_id}] agent.run starting model={model} provider=google-vertex "
            f"llm_timeout={MVP_LLM_TIMEOUT_S}s step_timeout={MVP_STEP_TIMEOUT_S}s "
            f"(warm={use_warm}, max_steps={max_steps}, study_budget={_budget}s)",
            flush=True,
        )
        history = None
        try:
            history = await agent.run(
                max_steps=max_steps,
                on_step_start=on_step_start,
                on_step_end=on_step_end,
            )
        except asyncio.CancelledError:
            raise
        except Exception as run_exc:  # noqa: BLE001
            # Prefer partial opening frames over raising into study retry.
            print(f"[{agent_id}] agent.run failed: {run_exc!r} — returning partial", flush=True)
    finally:
        if browser_session is not None:
            try:
                await asyncio.wait_for(browser_session.kill(), timeout=8)
            except Exception:
                pass
            browser_session = None
        if profile_clone is not None:
            try:
                await asyncio.wait_for(
                    asyncio.to_thread(discard_profile, profile_clone), timeout=5
                )
            except Exception:
                pass
        if owns_session and bb_session is not None:
            sid = getattr(bb_session, "id", None)
            if sid:
                try:
                    await asyncio.wait_for(
                        asyncio.to_thread(close_session, sid), timeout=8
                    )
                except Exception:
                    pass

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

    sigs = page_state.get("sigs") if isinstance(page_state.get("sigs"), dict) else {}
    for step in trace:
        n = step.get("step")
        if isinstance(n, int) and n in sigs and not step.get("state_sig"):
            step["state_sig"] = sigs[n]

    visited_urls: list[str] = []
    for step in trace:
        step_url = step.get("url")
        if step_url and step_url not in visited_urls:
            visited_urls.append(step_url)

    bb_flags = getattr(bb_session, "flags", None) if bb_session is not None else None
    captcha = page_state.get("captcha")
    first_action_s = page_state.get("first_action_s")

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
                "browserbase_flags": bb_flags,
                "model": model,
                "model_provider": "google-vertex",
                "captcha": captcha,
                "first_action_s": first_action_s,
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
        "browserbase_flags": bb_flags,
        "model": model,
        "model_provider": "google-vertex",
        "captcha": captcha,
        "first_action_s": first_action_s,
        "run_dir": str(run_dir),
        "num_steps": len(trace),
    }
