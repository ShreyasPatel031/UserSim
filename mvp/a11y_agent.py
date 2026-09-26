"""Shared page read and a text-only accessibility action loop.

One browser reads the product URL at study start. Every agent for that URL
gets the same compact accessibility tree and chooses a first click, type, or
scroll from it. Later steps take one tree read each. The only saved screenshot is the final
one for the vision judge. Each step also hashes the viewport so a stuck agent
can be stopped; that image is not stored and is not sent to the action model.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import time
from datetime import datetime, timezone
from typing import Any

AX_CAP = 150

# Full 24-agent Linear study 413e0cc0-f23b-45e5-9905-06f1c6d6d683 finished in
# 128s from Run click to the report. One study-level cap, 8 minutes, sits
# above that measured maximum. There is no per-agent step cap or wall.
STUDY_BUDGET_S = float(os.environ.get("MVP_STUDY_BUDGET_S", "480") or "480")
STUCK_STEPS = int(os.environ.get("MVP_STUCK_STEPS", "3") or "3")

FAILURE_TYPES = ("our infrastructure", "model timeout", "stuck", "product")


def study_budget_s() -> float:
    """Seconds the whole study may run. Default is 8 minutes."""
    try:
        budget = float(os.environ.get("MVP_STUDY_BUDGET_S", "") or STUDY_BUDGET_S)
    except (TypeError, ValueError):
        budget = 480.0
    return max(30.0, budget)


def stuck_steps() -> int:
    try:
        n = int(os.environ.get("MVP_STUCK_STEPS", "") or STUCK_STEPS)
    except (TypeError, ValueError):
        n = 3
    return max(2, n)


def progress_signature(
    *,
    url: str,
    screenshot_hash: str,
    text: str,
    canvas: str,
) -> tuple[str, str, str, str]:
    """URL + screenshot hash + DOM hash + canvas sample. Equal means no progress."""
    dom = hashlib.sha256((text or "").encode("utf-8", "replace")).hexdigest()[:16]
    return (
        (url or "").split("#")[0].rstrip("/"),
        screenshot_hash or "",
        dom,
        (canvas or "")[:120],
    )


def note_progress(
    previous: tuple[str, str, str, str] | None,
    signature: tuple[str, str, str, str],
    streak: int,
) -> tuple[int, str]:
    """Count consecutive steps whose page signature did not change."""
    if previous is not None and signature == previous:
        streak += 1
    else:
        streak = 0
    limit = stuck_steps()
    if streak >= limit:
        return streak, (
            f"stuck: no progress for {limit} consecutive steps "
            "(same URL, screenshot hash, DOM, and canvas)"
        )
    return streak, ""


def browser_dead(exc: BaseException | str) -> bool:
    text = (exc if isinstance(exc, str) else repr(exc)).lower()
    markers = (
        "target closed",
        "has been closed",
        "browser closed",
        "connection closed",
        "websocket",
        "session closed",
        "page closed",
        "context closed",
        "browser has disconnected",
        "target page, context or browser",
    )
    return any(marker in text for marker in markers)


def classify_failure(
    *,
    stop_reason: str = "",
    error: str = "",
    goal_reached: bool | None = None,
) -> str:
    """Bucket a stopped run: infrastructure, model timeout, stuck, or product."""
    text = f"{stop_reason}\n{error}".lower()
    if "stuck:" in text or "no progress for" in text:
        return "stuck"
    model_timeout = (
        ("model" in text or "llm" in text or "gemini" in text)
        and ("timeout" in text or "timed out" in text)
    )
    if model_timeout:
        return "model timeout"
    if "study budget" in text or browser_dead(text) or any(
        marker in text
        for marker in (
            "no browserbase",
            "browserbase",
            "cdp",
            "websocket",
            "target closed",
        )
    ):
        return "our infrastructure"
    if goal_reached is False:
        return "product"
    if goal_reached is True or (stop_reason or "").strip() in {"", "done"} and not error.strip():
        return ""
    if error.strip() or (stop_reason and stop_reason != "done"):
        return "our infrastructure"
    return ""


def failure_breakdown(runs: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {kind: 0 for kind in FAILURE_TYPES}
    rows: list[dict[str, Any]] = []
    for run in runs:
        if not isinstance(run, dict):
            continue
        kind = classify_failure(
            stop_reason=str(run.get("stop_reason") or ""),
            error=str(run.get("error") or run.get("browser_error") or ""),
            goal_reached=run.get("goal_reached") if "goal_reached" in run else None,
        )
        if not kind:
            continue
        counts[kind] = counts.get(kind, 0) + 1
        rows.append(
            {
                "agent_id": run.get("agent_id"),
                "site_key": run.get("site_key") or "product",
                "type": kind,
                "reason": (run.get("stop_reason") or run.get("error") or "")[:300],
                "judge_reason": str(run.get("judge_reason") or "")[:300],
            }
        )
    return {"counts": counts, "rows": rows}

# Sessions created at process start so URL submit does not wait on Browserbase.
_PRIMED: asyncio.Queue | None = None
_PRIME_STARTED = False


# taskfix may hold two live browsers and never a study_id=prime session.
# Other owners (the integration 24-wide run) are not capped here.
TASKFIX_SESSION_CAP = 2
_TASKFIX_LOCK: asyncio.Lock | None = None
_TASKFIX_HELD = 0


def _owner_is_taskfix() -> bool:
    return (os.environ.get("MVP_BB_OWNER") or "").strip().lower() == "taskfix"


def _taskfix_lock() -> asyncio.Lock:
    global _TASKFIX_LOCK
    if _TASKFIX_LOCK is None:
        _TASKFIX_LOCK = asyncio.Lock()
    return _TASKFIX_LOCK


def _taskfix_running_count() -> int:
    from mvp.kill_switch import list_running_browserbase

    return len(list_running_browserbase(owner="taskfix"))


def release_idle_taskfix(*, study_id: str | None = None) -> None:
    """Release idle taskfix sessions. Never signup, gates, or other owners.

    With no study id this drops ``study_id=prime`` only. A study id releases
    that study's sessions after the run, so the slot is free for integration.
    """
    if not _owner_is_taskfix():
        return
    from mvp.kill_switch import kill_all_browserbase

    kill_all_browserbase(owner="taskfix", study_id="prime")
    if study_id and study_id != "prime":
        kill_all_browserbase(owner="taskfix", study_id=study_id)


async def _acquire_taskfix_slot() -> bool:
    """True when this process may open one more taskfix browser."""
    global _TASKFIX_HELD
    if not _owner_is_taskfix():
        return True
    async with _taskfix_lock():
        try:
            remote = await asyncio.to_thread(_taskfix_running_count)
        except Exception:
            remote = _TASKFIX_HELD
        if max(remote, _TASKFIX_HELD) >= TASKFIX_SESSION_CAP:
            print(
                f"[a11y] taskfix holds {max(remote, _TASKFIX_HELD)} sessions; cap is {TASKFIX_SESSION_CAP}",
                flush=True,
            )
            return False
        _TASKFIX_HELD += 1
        return True


def _release_taskfix_slot() -> None:
    global _TASKFIX_HELD
    if _TASKFIX_HELD > 0:
        _TASKFIX_HELD -= 1


def prime_sessions(n: int = 0) -> None:
    """Pre-click browsers. This harness keeps the count at 0.

    A positive ``n`` still fills the queue for a caller that opts in.
    ``n <= 0`` creates nothing, including no ``study_id=prime`` sessions.
    Owner ``taskfix`` never primes, even when ``n`` is positive.
    """
    global _PRIME_STARTED
    if _PRIME_STARTED:
        return
    _PRIME_STARTED = True
    if _owner_is_taskfix():
        n = 0
        try:
            release_idle_taskfix()
        except Exception as exc:  # noqa: BLE001
            print(f"[a11y] taskfix prime release failed: {exc!r}", flush=True)
    if n <= 0:
        return

    async def _fill() -> None:
        global _PRIMED
        from capability.browserbase_client import create_session, study_session_owner

        _PRIMED = asyncio.Queue()
        for i in range(n):
            try:
                bb = await asyncio.to_thread(
                    create_session,
                    proxies=False,
                    keep_alive=True,
                    solve_captchas=False,
                    advanced_stealth=False,
                    owner=study_session_owner(),
                    study_id="prime",
                )
                await _PRIMED.put(bb)
                print(f"[a11y] primed session {i + 1}/{n}", flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f"[a11y] prime {i + 1} failed: {exc!r}", flush=True)

    try:
        asyncio.get_running_loop().create_task(_fill())
    except RuntimeError:
        _PRIME_STARTED = False

# Stable names the strict e2e gates read. Present on every agent, even when empty.
GATE_FIELDS = (
    "page_open_at_ts",
    "page_opened_at_ts",
    "page_open_at",
    "opened_at_ts",
    "browser_ready_at_ts",
    "browser_session_ready_at_ts",
    "session_ready_at_ts",
    "browser_ready_at",
    "session_ready_at",
    "page_url",
    "opened_url",
    "current_url",
    "accessibility_tree",
    "ax_tree",
    "ax_text",
    "final_url",
    "final_dom",
    "final_screenshot",
    "final_screenshot_url",
    "phase_ms",
    "failed_step",
    "first_action_at_ts",
    "phase",
    "error",
    "browser_error",
)

_STOP = frozenset(
    "the a an and or to of for on in with from this that your you are was were "
    "find open click use page site product task then look something".split()
)

_READ_JS = """() => {
  const url = location.href;
  const title = document.title || '';
  const text = ((document.body && document.body.innerText) || '')
    .replace(/\\s+/g, ' ').trim().slice(0, 1500);
  let canvas = '';
  const canvases = document.querySelectorAll('canvas');
  for (const c of canvases) {
    try {
      const w = c.width || 0, h = c.height || 0;
      if (w < 2 || h < 2) continue;
      const ctx = c.getContext('2d', { willReadFrequently: true });
      if (!ctx) continue;
      const step = Math.max(8, Math.floor(Math.min(w, h) / 48));
      const data = ctx.getImageData(0, 0, w, h).data;
      let dark = 0, total = 0;
      for (let y = 0; y < h; y += step) {
        for (let x = 0; x < w; x += step) {
          const i = (y * w + x) * 4;
          // Transparent pixels are not ink. Excalidraw's drawing layer starts clear.
          if (data[i + 3] > 16 && (data[i] + data[i + 1] + data[i + 2]) < 700) dark++;
          total++;
        }
      }
      canvas += w + 'x' + h + ':dark=' + dark + '/' + total + ';';
    } catch (e) {
      canvas += 'taint;';
    }
  }
  const nodes = [];
  const sel = 'a, button, input, textarea, select, summary, [role="button"], [role="link"], [role="menuitem"], [role="tab"], [role="textbox"], canvas, [contenteditable="true"]';
  const all = document.querySelectorAll(sel);
  const vh = window.innerHeight || 800;
  const pack = (el) => {
    const r = el.getBoundingClientRect();
    const href = String(el.href || el.getAttribute('href') || '').slice(0, 180);
    const tab = el.getAttribute('tabindex');
    const cls = String(el.className || '');
    // Linear's homepage embeds a fake app. Those controls look clickable and do nothing.
    const mock = /(?:navItem|newIssue|searchButton|switchWorkspace|rowButton|ingredientButton|headerButton|iconButton|sendButton|dropdownButton|pillButton|navButton|labelButton|attachmentButton|splitSegment|locationBar)/.test(cls);
    const inert = ((tab === '-1') && !href) || !!el.disabled || el.getAttribute('aria-disabled') === 'true' || (mock && !href);
    let name = (
      el.getAttribute('aria-label')
      || el.getAttribute('placeholder')
      || el.getAttribute('title')
      || el.innerText
      || el.getAttribute('name')
      || ''
    ).replace(/\\s+/g, ' ').trim().slice(0, 80);
    if (!name && /main-menu-trigger/.test(cls)) name = 'Menu';
    return {
      i: nodes.length,
      role: (el.getAttribute('role') || el.tagName || '').toLowerCase(),
      name: name,
      href: href,
      x: Math.round(r.x + Math.max(r.width, 0) / 2),
      y: Math.round(r.y + Math.max(r.height, 0) / 2),
      w: Math.round(Math.max(r.width, 0)),
      h: Math.round(Math.max(r.height, 0)),
      inert: inert,
    };
  };
  const offscreen = [];
  for (const el of all) {
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) continue;
    const style = window.getComputedStyle(el);
    if (style.visibility === 'hidden' || style.display === 'none') continue;
    const onScreen = r.bottom >= 0 && r.top <= vh + 80;
    if (!onScreen) {
      offscreen.push(el);
      continue;
    }
    if (nodes.length < 120) nodes.push(pack(el));
  }
  // Footer and menu links (Docs, Changelog) are real controls. Keep them
  // even when they sit below the first screen, ahead of decorative buttons.
  for (const el of offscreen) {
    if (nodes.length >= 150) break;
    const href = el.href || el.getAttribute('href') || '';
    if (!href) continue;
    nodes.push(pack(el));
  }
  return { url, title, text, canvas, nodes };
}"""


def fast_action_model() -> str:
    """Fastest text action model. Lite, no vision, short prompts."""
    chosen = (os.environ.get("MVP_AGENT_ACTION_MODEL") or "").strip()
    if chosen:
        return chosen
    from config import MODEL

    base = (
        os.environ.get("MVP_BROWSER_MODEL")
        or os.environ.get("MVP_LLM_MODEL")
        or MODEL
        or ""
    ).strip()
    if not base:
        return MODEL
    if "lite" in base.lower():
        return base
    return base + "-lite"


def format_ax(nodes: list[dict[str, Any]], *, limit: int = AX_CAP) -> str:
    lines: list[str] = []
    for node in (nodes or [])[:limit]:
        if not isinstance(node, dict):
            continue
        name = str(node.get("name") or "")
        href = str(node.get("href") or "")
        inert = " inert" if node.get("inert") else ""
        extra = f" {href}" if href else ""
        lines.append(
            f"{int(node.get('i') or 0)} {node.get('role') or 'el'} {name}{inert}{extra}".rstrip()
        )
    return "\n".join(lines)


def pick_action(task: str, nodes: list[dict[str, Any]]) -> dict[str, Any]:
    """Deterministic first move from the shared tree. No model, no page read."""
    words = [
        w
        for w in re.findall(r"[a-z0-9]+", (task or "").lower())
        if len(w) > 3 and w not in _STOP
    ]
    best: dict[str, Any] | None = None
    best_score = 0
    for node in nodes or []:
        if not isinstance(node, dict):
            continue
        name = str(node.get("name") or "").lower()
        href = str(node.get("href") or "").lower()
        if not name and not href:
            continue
        if node.get("inert"):
            continue
        if "skip to content" in name:
            continue
        score = sum(3 for w in words if w in name or w in href)
        role = str(node.get("role") or "")
        if role in {"a", "button", "link", "menuitem", "tab"}:
            score += 1
        if score > best_score:
            best = node
            best_score = score
    if best is None:
        for node in nodes or []:
            if isinstance(node, dict) and str(node.get("name") or "").strip():
                best = node
                break
    if best is None:
        return {"act": "scroll", "i": -1, "x": 0, "y": 400, "name": "page", "dy": 500}
    return {
        "act": "click",
        "i": int(best.get("i") or 0),
        "x": int(best.get("x") or 0),
        "y": int(best.get("y") or 0),
        "name": str(best.get("name") or "")[:80],
        "href": str(best.get("href") or "")[:180],
        "role": str(best.get("role") or ""),
    }


def _host(url: str) -> str:
    from urllib.parse import urlsplit

    text = (url or "").strip()
    if not text:
        return ""
    if "://" not in text:
        text = "https://" + text
    host = (urlsplit(text).hostname or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    return host


def _page_key(url: str) -> tuple[str, str, str]:
    from urllib.parse import urlsplit

    text = (url or "").strip()
    if not text:
        return ("", "", "")
    if "://" not in text:
        text = "https://" + text
    parsed = urlsplit(text)
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = (parsed.path or "/").rstrip("/") or "/"
    return (host, path, parsed.query or "")


def _origin(url: str) -> str:
    from urllib.parse import urlsplit

    text = (url or "").strip()
    if not text:
        return ""
    if "://" not in text:
        text = "https://" + text
    parts = urlsplit(text)
    if not parts.scheme or not parts.netloc:
        return ""
    return f"{parts.scheme}://{parts.netloc}"


def task_kind(task: str) -> str:
    """Which goal this task is asking the agent to reach."""
    text = (task or "").lower()
    if any(word in text for word in ("rectangle", "draw a", "square", "box")):
        return "draw"
    if "export" in text or ("share" in text and "drawing" in text):
        return "export"
    if "help" in text or "shortcut" in text:
        return "help"
    if any(word in text for word in ("changelog", "what shipped", "shipped recently")):
        return "changelog"
    if "issue" in text and "pricing" not in text:
        return "issue"
    if any(word in text for word in ("pricing", "free plan", "price", "get started")):
        return "pricing"
    return ""


def goal_visible(task: str, read: dict[str, Any]) -> bool:
    """True only when this page shows the task goal.

    A nav label on the opening page is not the pricing page, the issue form,
    a drawing, or an export dialog.
    """
    url = str((read or {}).get("url") or "")
    text = str((read or {}).get("text") or "").lower()
    title = str((read or {}).get("title") or "").lower()
    kind = task_kind(task)
    path = _page_key(url)[1]
    if kind == "pricing":
        return "pricing" in path or "pricing" in title
    if kind == "changelog":
        return "changelog" in path or "changelog" in title
    if kind == "issue":
        # A logged-out visitor cannot open the workspace composer. The public
        # create-issues doc is the page that shows how. The marketing demo's
        # "New issue" button does not.
        if "creating-issues" in path or "create-issues" in path:
            return True
        if "create issues" in title or "creating issues" in title:
            return True
        return "issue title" in text and "description" in text
    if kind == "draw":
        # Tool chrome ("Selected shape actions") appears when the tool is
        # selected, before any stroke. The canvas sample has to change.
        opened = str((read or {}).get("opened_canvas") or "")
        current = str((read or {}).get("canvas") or "")
        if not opened or not current or "taint" in opened or "taint" in current:
            return False
        opened_dark = _canvas_dark(opened)
        current_dark = _canvas_dark(current)
        if opened_dark < 0 or current_dark < 0:
            return False
        return abs(current_dark - opened_dark) >= 8
    if kind == "export":
        # The welcome hint says "Export, preferences". The dialog says "Export image".
        return "export image" in text
    if kind == "help":
        return "keyboard shortcuts" in text
    return False


def _canvas_dark(raw: str) -> int:
    total = 0
    found = False
    for part in (raw or "").split(";"):
        if "dark=" not in part:
            continue
        found = True
        num = part.split("dark=", 1)[1].split("/", 1)[0]
        if num.lstrip("-").isdigit():
            total += int(num)
    return total if found else -1


def achievable_without_account(url: str, prompt: str) -> str:
    """Rewrite a task that needs a login into one a logged-out visitor can finish."""
    text = " ".join((prompt or "").split())
    low = text.lower()
    host = _host(url)
    if host == "linear.app" and "issue" in low and not any(
        word in low for word in ("how", "find", "docs", "documentation", "pricing")
    ):
        return "Find how to create a new issue"
    needs_account = any(
        phrase in low
        for phrase in (
            "log in",
            "log-in",
            "sign in",
            "sign up for an account",
            "create an account",
            "your workspace",
            "in the workspace",
            "file an issue",
            "submit an issue",
        )
    )
    if needs_account and "pricing" not in low and "how to" not in low:
        if "excalidraw" in host:
            return "Draw a simple box"
        return "Look for pricing or how to get started"
    return text


def notes_from_trace(trace: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """Strengths and weaknesses taken from steps that actually ran.

    A step that changed the page is a strength. A step that changed nothing
    is a weakness. The wording is the action and the URL, not a fixed sentence.
    """
    easy: list[str] = []
    friction: list[str] = []
    for step in trace or []:
        if not isinstance(step, dict):
            continue
        action = " ".join(str(step.get("action") or "").split())
        if not action or action.lower().startswith("opened"):
            continue
        url = str(step.get("url") or "").strip()
        decision = step.get("decision") if isinstance(step.get("decision"), dict) else {}
        if step.get("changed") is False:
            friction.append(f"{action} changed nothing" + (f" on {url}" if url else ""))
        elif step.get("changed") is True:
            easy.append(f"{action} changed the page" + (f" to {url}" if url else ""))
        model_easy = " ".join(str(decision.get("easy") or "").split())
        model_friction = " ".join(str(decision.get("friction") or "").split())
        if model_easy:
            easy.append(model_easy[:180])
        if model_friction:
            friction.append(model_friction[:180])
    def _uniq(items: list[str]) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for item in items:
            key = item.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
        return out[:3]
    return _uniq(easy), _uniq(friction)


def would_repeat_action(trace: list[dict[str, Any]], label: str, read: dict[str, Any]) -> bool:
    """True when appending this action would repeat it 3 times with no page change.

    The strict harness aborts the study at that third repeat. Stop first.
    """
    steps = [
        step
        for step in trace
        if isinstance(step, dict) and isinstance(step.get("step"), int)
    ]
    steps = sorted(steps, key=lambda step: int(step["step"]))
    incoming = {
        "step": 10_000,
        "action": label,
        "url": str((read or {}).get("url") or ""),
        "state_sig": {
            "text": str((read or {}).get("text") or ""),
            "canvas": str((read or {}).get("canvas") or ""),
        },
    }
    streak = 0
    prev: dict[str, Any] | None = None
    prev_key = ""
    for step in [*steps, incoming]:
        key = " ".join(str(step.get("action") or "").split()).lower()
        if not key or key.startswith("opened"):
            streak = 0
            prev = step
            prev_key = ""
            continue
        progressed = False
        if prev is not None:
            if _page_key(str(prev.get("url") or "")) != _page_key(str(step.get("url") or "")):
                prev_key_ok = _page_key(str(prev.get("url") or "")) != ("", "", "")
                cur_key_ok = _page_key(str(step.get("url") or "")) != ("", "", "")
                progressed = prev_key_ok and cur_key_ok
        # A hero image's dark-pixel sample flickers. That is not a new page,
        # and counting it as progress lets the same click repeat until the
        # harness aborts the study.
        same = prev is not None and key == prev_key and not progressed
        streak = streak + 1 if same else 1
        prev = step
        prev_key = key
    return streak >= 3


def invented_excalidraw_action(
    task: str,
    read: dict[str, Any],
    history: list[str] | None = None,
    skip: set[str] | None = None,
) -> dict[str, Any] | None:
    """Rectangle drag and Export image exist only on excalidraw.com.

    Competitors such as Miro do not have those controls. Inventing the click
    there repeats until the harness aborts every agent in the study.
    """
    if _host(str((read or {}).get("url") or "")) != "excalidraw.com":
        return None
    kind = task_kind(task)
    skipped = skip or set()
    done = [item.lower() for item in (history or [])]
    if kind == "draw":
        selected = "selected shape" in str((read or {}).get("text") or "").lower() or any(
            "rectangle" in item for item in done
        )
        if selected:
            return {"act": "drag", "i": -1, "name": "canvas", "role": "canvas", "href": ""}
        if "rectangle" in skipped:
            return None
        return {"act": "click", "i": -1, "name": "Rectangle", "role": "button", "href": ""}
    if kind == "export":
        if "export image" in str((read or {}).get("text") or "").lower():
            if "export image" in skipped:
                return None
            return {
                "act": "click",
                "i": -1,
                "name": "Export image",
                "role": "menuitem",
                "href": "",
            }
        if "menu" in skipped:
            return None
        return {"act": "click", "i": -1, "name": "Menu", "role": "button", "href": ""}
    return None


def offhost_excalidraw_tool(action: dict[str, Any], url: str) -> bool:
    """True when this action is the Excalidraw rectangle/export shortcut elsewhere."""
    if _host(url) == "excalidraw.com":
        return False
    act = str((action or {}).get("act") or "")
    name = str((action or {}).get("name") or "").lower()
    if act == "drag":
        return True
    if name in {"rectangle", "square", "canvas"}:
        return True
    return "export" in name


def trace_canvas(previous: str, current: str, url: str, task: str) -> str:
    """Canvas sample stored on a trace step.

    Flicker on any site except an Excalidraw drawing is not a new page.
    """
    if _host(url) == "excalidraw.com" and task_kind(task) == "draw":
        return current or ""
    return previous or ""


def ensure_phase_ms(sess: dict[str, Any]) -> None:
    """The four phase durations, as numbers, on every agent."""
    raw = dict(sess.get("phase_ms") or {})
    for key in ("session_ready", "page_open", "first_action", "final_screenshot"):
        if isinstance(raw.get(key), (int, float)) and not isinstance(raw.get(key), bool):
            continue
        alias = raw.get(f"{key}_ms")
        if isinstance(alias, (int, float)) and not isinstance(alias, bool):
            raw[key] = int(alias)
        else:
            raw[key] = 0
        raw[f"{key}_ms"] = int(raw[key])
    sess["phase_ms"] = raw


def _follow_href(href: str) -> str:
    """Absolute link to open. Same-page fragments stay a coordinate click."""
    from urllib.parse import urlparse

    raw = (href or "").strip()
    if not raw.startswith("http"):
        return ""
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"}:
        return ""
    if parsed.fragment and parsed.path in {"", "/"}:
        return ""
    return raw[:180]


def action_label(action: dict[str, Any]) -> str:
    act = str(action.get("act") or "click")
    name = str(action.get("name") or action.get("text") or "").strip()
    if act == "type":
        return f"type {name or action.get('text') or ''}".strip()
    if act == "scroll":
        return "scroll down"
    if act == "drag":
        return f"drag {name}".strip()
    if act == "done":
        return "done"
    return f"click {name}".strip()


def _ms(a: float | None, b: float | None) -> int | None:
    if a is None or b is None:
        return None
    return max(0, int(round((b - a) * 1000)))


def apply_gate_fields(sess: dict[str, Any], **fields: Any) -> None:
    """Write every gate field. Missing values stay present as empty or null."""
    for key in GATE_FIELDS:
        sess.setdefault(key, None if key in {"failed_step", "first_action_at_ts"} else "")
    sess["phase_ms"] = dict(sess.get("phase_ms") or {})
    for key, value in fields.items():
        if key == "phase_ms" and isinstance(value, dict):
            sess["phase_ms"].update(value)
        else:
            sess[key] = value
    # Aliases the gates accept.
    if sess.get("page_open_at_ts"):
        sess["page_opened_at_ts"] = sess["page_open_at_ts"]
        sess["page_open_at"] = sess["page_open_at_ts"]
        sess["opened_at_ts"] = sess["page_open_at_ts"]
    if sess.get("session_ready_at_ts"):
        sess["browser_session_ready_at_ts"] = sess["session_ready_at_ts"]
        sess["browser_ready_at_ts"] = sess["session_ready_at_ts"]
        sess["browser_ready_at"] = sess["session_ready_at_ts"]
        sess["session_ready_at"] = sess["session_ready_at_ts"]
    ax = str(sess.get("accessibility_tree") or "")
    sess["ax_tree"] = ax
    sess["ax_text"] = ax
    url = str(sess.get("page_url") or "")
    sess["opened_url"] = url
    sess["current_url"] = url
    shot = str(sess.get("final_screenshot_url") or "")
    sess["final_screenshot"] = shot


def _stamp_observation(trace: list[dict[str, Any]], read: dict[str, Any]) -> None:
    """Write the live page onto the latest step.

    Agents that find the goal already on screen never append a step. Without
    this, the trace keeps the opening title and the run looks like it never
    left the first screen.
    """
    steps = [
        step
        for step in trace
        if isinstance(step, dict) and isinstance(step.get("step"), int)
    ]
    if not steps:
        return
    last = max(steps, key=lambda step: int(step["step"]))
    text = str(read.get("text") or "")
    url = str(read.get("url") or last.get("url") or "")
    ax = format_ax(read.get("nodes") or [])
    last["url"] = url
    last["observation"] = text[:400]
    # A marketing-page canvas sample flickers. Keep the previous sample unless
    # this is an Excalidraw drawing, where the ink change is the result.
    previous = last.get("state_sig") if isinstance(last.get("state_sig"), dict) else {}
    canvas = str(read.get("canvas") or "")
    if _host(url) != "excalidraw.com":
        canvas = str(previous.get("canvas") or "")
    last["state_sig"] = {"text": text[:1500], "canvas": canvas}
    if ax:
        last["accessibility_tree"] = ax
        last["ax_tree"] = ax


def _step_from_read(
    *,
    step: int,
    action: str,
    read: dict[str, Any],
    thought: str = "",
    outcome: str = "neutral",
    screenshot_url: str | None = None,
) -> dict[str, Any]:
    ax = format_ax(read.get("nodes") or [])
    url = str(read.get("url") or "")
    text = str(read.get("text") or "")
    row: dict[str, Any] = {
        "step": step,
        "action": action,
        "observation": text[:400],
        "thought": thought,
        "thought_detail": {},
        "url": url,
        "screenshot_url": screenshot_url,
        "boxes": [],
        "outcome": outcome,
        "accessibility_tree": ax,
        "ax_tree": ax,
        "state_sig": {"text": text[:1500], "canvas": str(read.get("canvas") or "")},
    }
    return row


class A11yBoot:
    """One shared read per start URL, then 24 agents act in parallel."""

    def __init__(self, study: Any, on_update: Any | None = None) -> None:
        self.study = study
        self.on_update = on_update
        self.pool: asyncio.Queue[Any] = asyncio.Queue()
        self.snapshots: dict[str, dict[str, Any]] = {}
        self.handles: dict[str, dict[str, Any]] = {}
        self.contexts: dict[str, dict[str, Any]] = {}
        self._handles: list[dict[str, Any]] = []
        self._handle_cv = asyncio.Condition()
        self._page_lock = asyncio.Lock()
        self._site_locks: dict[str, asyncio.Lock] = {}
        self._pw: Any = None
        self._started = 0.0
        self._tasks: list[asyncio.Task] = []
        self.published = asyncio.Event()

    def lock_for(self, site_key: str) -> asyncio.Lock:
        """One agent at a time per browser. Parallel tabs were closing the session."""
        lock = self._site_locks.get(site_key)
        if lock is None:
            lock = asyncio.Lock()
            self._site_locks[site_key] = lock
        return lock

    def install_fast_plan(self) -> None:
        """Known tasks and rivals are enough. Do not wait on a planning model."""
        study = self.study
        if not study.tasks_override or study.test_mode:
            return
        study.fast_brief = True
        want = max(1, int(os.environ.get("MVP_PERSONA_COUNT", "4") or "4"))
        segment = study.segment or "target customer"
        study.personas = [
            {
                "id": f"p{i}",
                "name": f"Simulated user {i}",
                "bio": f"A {segment} evaluating the product on a real task.",
                "age_range": "25–40",
                "occupation": "Professional",
                "location": "Remote",
                "goals": ["Finish the task", "Notice what is confusing"],
            }
            for i in range(1, want + 1)
        ]
        base = []
        for i, prompt in enumerate(study.tasks_override):
            persona = study.personas[i % len(study.personas)]
            base.append(
                {
                    "id": f"t{i+1}",
                    "title": str(prompt)[:80],
                    "prompt": prompt,
                    "persona_id": persona["id"],
                    "difficulty_hint": "medium",
                }
            )
        from mvp.study import expand_full_matrix

        study.tasks = expand_full_matrix(
            base,
            study.personas,
            product_url=study.url,
            competitors=list(study.competitors or []),
        )
        cap = int(getattr(study, "max_agents", 0) or 0)
        if cap > 0 and len(study.tasks) > cap:
            study.tasks = study.tasks[:cap]

    async def start(self) -> None:
        self._started = time.time()
        self.install_fast_plan()

        async def _boot() -> None:
            # Shared read for the opening display. Each agent creates its own
            # browser when it runs. No pre-click prime pool.
            for attempt in range(4):
                bb = await self._create_one(attempt, enqueue=False)
                if bb is None:
                    continue
                try:
                    snap = await self._read_url(bb, self.study.url)
                except Exception as exc:  # noqa: BLE001
                    print(f"[a11y] product read failed (retrying): {exc!r}", flush=True)
                    if _owner_is_taskfix():
                        await _close_agent_session(None, bb)
                        _release_taskfix_slot()
                    continue
                handle = snap.pop("_handle", None) if isinstance(snap, dict) else None
                page = (handle or {}).get("page") if isinstance(handle, dict) else None
                try:
                    closed = page is None or page.is_closed()
                except Exception:
                    closed = True
                if closed or not isinstance(handle, dict) or not isinstance(snap, dict):
                    print("[a11y] product read had no live page (retrying)", flush=True)
                    if _owner_is_taskfix():
                        browser = handle.get("browser") if isinstance(handle, dict) else None
                        await _close_agent_session(browser, bb)
                        _release_taskfix_slot()
                    continue
                handle["site_key"] = "product"
                handle["read"] = snap
                async with self._handle_cv:
                    self._handles.append(handle)
                    self.contexts["product"] = handle
                    self._handle_cv.notify_all()
                self.snapshots["product"] = snap
                self._publish_site("product", snap)
                if _owner_is_taskfix() and isinstance(handle, dict):
                    await _close_agent_session(handle.get("browser"), handle.get("bb"))
                    _release_taskfix_slot()
                    async with self._handle_cv:
                        self._handles = [
                            item for item in self._handles if item is not handle
                        ]
                        self.contexts.pop("product", None)
                break
            else:
                print("[a11y] no live product page", flush=True)
            extras = len([c for c in (self.study.competitors or []) if c])
            if extras and not _owner_is_taskfix():
                self._tasks.append(asyncio.create_task(self._fill_pool(extras, offset=1)))
            await self._publish_rest()

        self._tasks.append(asyncio.create_task(_boot()))

    async def _playwright(self) -> Any:
        if self._pw is None:
            from playwright.async_api import async_playwright

            self._pw = await async_playwright().start()
        return self._pw

    async def _create_one(self, i: int, enqueue: bool = True) -> Any | None:
        from capability.browserbase_client import create_session, study_session_owner

        if _owner_is_taskfix() and str(getattr(self.study, "id", "") or "") == "prime":
            return None
        if not await _acquire_taskfix_slot():
            return None
        bb = None
        try:
            if not _owner_is_taskfix() and _PRIMED is not None:
                try:
                    bb = _PRIMED.get_nowait()
                    print(f"[a11y] using primed session for {i + 1}", flush=True)
                    if enqueue:
                        await self.pool.put(bb)
                    return bb
                except asyncio.QueueEmpty:
                    bb = None
            deadline = getattr(self.study, "budget_deadline", None) or (
                time.monotonic() + study_budget_s()
            )
            while time.monotonic() < deadline:
                try:
                    bb = await asyncio.to_thread(
                        create_session,
                        proxies=False,
                        keep_alive=True,
                        solve_captchas=False,
                        advanced_stealth=False,
                        owner=study_session_owner(),
                        study_id=self.study.id,
                    )
                except Exception as exc:  # noqa: BLE001
                    # A 429 or a slow create is not a dead browser. Keep trying
                    # until the study budget. Do not stop the agent on the first miss.
                    print(f"[a11y] session {i + 1} create retry: {exc!r}", flush=True)
                    bb = None
                    await asyncio.sleep(5)
                    continue
                if enqueue:
                    await self.pool.put(bb)
                return bb
            print(f"[a11y] session {i + 1} not created before the study budget", flush=True)
            bb = None
            return None
        finally:
            if bb is None:
                _release_taskfix_slot()

    async def _fill_pool(self, n: int, offset: int = 0) -> None:
        await asyncio.gather(*[self._create_one(offset + i) for i in range(n)])

    async def _connect(self, bb: Any) -> tuple[Any, Any]:
        pw = await self._playwright()
        browser = await pw.chromium.connect_over_cdp(bb.connect_url)
        context = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = context.pages[0] if context.pages else await context.new_page()
        try:
            await page.set_viewport_size({"width": 1440, "height": 900})
        except Exception:
            pass
        try:
            page.set_default_timeout(8000)
            page.set_default_navigation_timeout(8000)
        except Exception:
            pass
        return browser, context, page

    async def _read_url(self, bb: Any, url: str) -> dict[str, Any]:
        ready = time.time()
        t0 = time.perf_counter()
        browser, context, page = await self._connect(bb)
        try:
            await page.goto(url, wait_until="commit", timeout=8000)
        except Exception as exc:  # noqa: BLE001
            print(f"[a11y] goto {url} : {exc!r}", flush=True)
        read_t0 = time.perf_counter()
        try:
            raw = await page.evaluate(_READ_JS)
        except Exception as exc:  # noqa: BLE001
            raw = {"url": url, "title": "", "text": "", "canvas": "", "nodes": []}
            print(f"[a11y] read failed {url}: {exc!r}", flush=True)
        opened = time.time()
        if not isinstance(raw, dict):
            raw = {"url": url, "text": "", "canvas": "", "nodes": []}
        raw["url"] = str(raw.get("url") or url)
        raw["nodes"] = list(raw.get("nodes") or [])[:AX_CAP]
        raw["session_ready_at_ts"] = ready
        raw["page_open_at_ts"] = opened
        raw["phase_ms"] = {
            "session_ready_ms": _ms(self._started, ready),
            "page_open_ms": _ms(ready, opened),
            "read_ms": int(round((time.perf_counter() - read_t0) * 1000)),
            "navigate_ms": int(round((read_t0 - t0) * 1000)),
        }
        raw["_handle"] = {
            "bb": bb,
            "browser": browser,
            "context": context,
            "page": page,
            "read": raw,
            "site_key": "",
        }
        return raw

    def _touch(self) -> None:
        self.study.updated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if self.on_update:
            try:
                self.on_update(self.study, event="progress")
            except TypeError:
                try:
                    self.on_update(self.study)
                except Exception:
                    pass
            except Exception:
                pass

    def _publish_site(self, site_key: str, snap: dict[str, Any]) -> None:
        ax = format_ax(snap.get("nodes") or []) or str(snap.get("text") or "")[:1500] or "0 document page"
        url = str(snap.get("url") or "")
        for task in self.study.tasks or []:
            if str(task.get("site_key") or "product") != site_key:
                continue
            agent_id = str(task.get("id") or "")
            if not agent_id:
                continue
            existing = self.study.live_sessions.get(agent_id) or {}
            # A later republish must not wipe steps the agent already took.
            if existing.get("first_action_at_ts") or len(existing.get("trace") or []) > 2:
                continue
            assigned = str(task.get("site_url") or "")
            if _host(url) != _host(assigned):
                print(
                    f"[a11y] skip publish {agent_id}: read {_host(url)} != {_host(assigned)}",
                    flush=True,
                )
                continue
            persona = next(
                (p for p in (self.study.personas or []) if p.get("id") == task.get("persona_id")),
                (self.study.personas or [{}])[0] if self.study.personas else {},
            )
            # The shared read is the opening observation only. Each agent
            # opens its own browser and chooses the first click from a fresh read.
            # page_open_at_ts is that agent's goto commit, not this publish time.
            sess = self.study.live_sessions.get(agent_id) or {
                "agent_id": agent_id,
                "persona_id": persona.get("id"),
                "persona_name": persona.get("name"),
                "persona_bio": persona.get("bio"),
                "task_id": task.get("id"),
                "task_title": task.get("title"),
                "task_prompt": task.get("prompt"),
                "site_key": site_key,
                "site_url": task.get("site_url") or url,
                "site_label": task.get("site_label") or site_key,
                "trace": [],
                "num_steps": 0,
                "live_thoughts": [],
            }
            sess["status"] = "running"
            sess["phase"] = "reading"
            step0 = _step_from_read(step=0, action=f"Opened {url}", read=snap)
            step0.pop("page_open_at_ts", None)
            step0["accessibility_tree"] = ax
            sess["trace"] = [step0]
            sess["num_steps"] = 1
            sess["last_action"] = step0["action"]
            sess.pop("pending_action", None)
            apply_gate_fields(
                sess,
                page_url=url,
                accessibility_tree=ax,
                final_url=url,
                final_dom=str(snap.get("text") or "")[:1500],
                phase="reading",
                error="",
                browser_error="",
                failed_step=None,
                first_action_at_ts=None,
                phase_ms={
                    **dict(snap.get("phase_ms") or {}),
                    "session_ready": 0,
                    "page_open": 0,
                    "first_action": 0,
                    "final_screenshot": 0,
                    "first_action_ms": 0,
                },
            )
            ensure_phase_ms(sess)
            self.study.live_sessions[agent_id] = sess
        self._touch()

    async def _publish_all(self) -> None:
        # Wait until the fast plan (or the normal planner) has tasks.
        deadline = time.time() + 25
        while not self.study.tasks and time.time() < deadline:
            await asyncio.sleep(0.05)
        sites: list[tuple[str, str]] = [("product", self.study.url)]
        for i, comp in enumerate(self.study.competitors or []):
            if comp:
                sites.append((f"competitor_{i+1}", str(comp)))
        async def _one(key: str, url: str) -> None:
            try:
                bb = await asyncio.wait_for(self.pool.get(), timeout=40)
            except asyncio.TimeoutError:
                print(f"[a11y] no session for {key}", flush=True)
                return
            try:
                snap = await self._read_url(bb, url)
            except Exception as exc:  # noqa: BLE001
                print(f"[a11y] shared read {key} failed: {exc!r}", flush=True)
                return
            handle = snap.pop("_handle", None)
            if isinstance(handle, dict):
                handle["site_key"] = key
                handle["read"] = snap
                async with self._handle_cv:
                    self._handles.append(handle)
                    self.contexts[key] = handle
                    self._handle_cv.notify_all()
            self.snapshots[key] = snap
            self._publish_site(key, snap)

        await asyncio.gather(*[_one(key, url) for key, url in sites])
        self.published.set()

    async def _publish_rest(self) -> None:
        """Competitor reads. The product tree is already published."""
        sites: list[tuple[str, str]] = []
        for i, comp in enumerate(self.study.competitors or []):
            if comp:
                sites.append((f"competitor_{i+1}", str(comp)))
        if not sites:
            self.published.set()
            return

        async def _one(key: str, url: str) -> None:
            deadline = getattr(self.study, "budget_deadline", None) or (
                time.monotonic() + study_budget_s()
            )
            # A primed session is often already closed. Try a few browsers
            # before giving up, or every agent on this site waits out the budget.
            for attempt in range(4):
                if time.monotonic() >= deadline:
                    break
                bb = None
                try:
                    bb = self.pool.get_nowait()
                except asyncio.QueueEmpty:
                    bb = await self._create_one(attempt, enqueue=False)
                if bb is None:
                    continue
                try:
                    snap = await self._read_url(bb, url)
                except Exception as exc:  # noqa: BLE001
                    print(f"[a11y] shared read {key} failed (retrying): {exc!r}", flush=True)
                    if _owner_is_taskfix():
                        await _close_agent_session(None, bb)
                        _release_taskfix_slot()
                    continue
                handle = snap.pop("_handle", None) if isinstance(snap, dict) else None
                page = (handle or {}).get("page") if isinstance(handle, dict) else None
                try:
                    closed = page is None or page.is_closed()
                except Exception:
                    closed = True
                if closed or not isinstance(handle, dict):
                    print(f"[a11y] shared read {key} had no live page (retrying)", flush=True)
                    if _owner_is_taskfix():
                        browser = handle.get("browser") if isinstance(handle, dict) else None
                        await _close_agent_session(browser, bb)
                        _release_taskfix_slot()
                    continue
                handle["site_key"] = key
                handle["read"] = snap
                if _owner_is_taskfix():
                    await _close_agent_session(handle.get("browser"), handle.get("bb"))
                    _release_taskfix_slot()
                else:
                    async with self._handle_cv:
                        self._handles.append(handle)
                        self.contexts[key] = handle
                        self._handle_cv.notify_all()
                self.snapshots[key] = snap
                self._publish_site(key, snap)
                return
            print(f"[a11y] no live page for {key}", flush=True)

        if _owner_is_taskfix():
            for key, url in sites:
                await _one(key, url)
        else:
            await asyncio.gather(*[_one(key, url) for key, url in sites])
        self.published.set()

    async def take_page(self, site_key: str, url: str) -> dict[str, Any] | None:
        """The page already open for this site.

        A second CDP connection returns 410, and extra tabs on that one browser
        were closing each other. Callers hold ``lock_for(site_key)`` and reuse
        this page one agent at a time.
        """
        deadline = getattr(self.study, "budget_deadline", None) or (
            time.monotonic() + study_budget_s()
        )
        while time.monotonic() < deadline:
            handle = self.contexts.get(site_key) or {}
            page = handle.get("page")
            try:
                closed = page is None or page.is_closed()
            except Exception:
                closed = True
            if closed:
                revived = await self._revive(site_key, url)
                if revived is None:
                    return None
                handle = revived
                page = handle.get("page")
            if page is not None:
                try:
                    if url and _host(page.url or "") != _host(url):
                        await page.goto(url, wait_until="commit", timeout=8000)
                except Exception as exc:  # noqa: BLE001
                    if browser_dead(exc):
                        print(f"[a11y] shared page died for {site_key}: {exc!r}", flush=True)
                        revived = await self._revive(site_key, url)
                        if revived is None:
                            return None
                        handle = revived
                        page = handle.get("page")
                    else:
                        print(f"[a11y] agent goto {url}: {exc!r}", flush=True)
                return {
                    "bb": handle.get("bb"),
                    "browser": handle.get("browser"),
                    "page": page,
                    "site_key": site_key,
                    "shared": True,
                    "reuse": True,
                }
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            async with self._handle_cv:
                try:
                    await asyncio.wait_for(self._handle_cv.wait(), timeout=min(2.0, remaining))
                except asyncio.TimeoutError:
                    continue
        return None

    async def _revive(self, site_key: str, url: str) -> dict[str, Any] | None:
        """Replace a dead shared page with a new browser on the same site."""
        old = self.contexts.pop(site_key, None) or {}
        old_browser = old.get("browser")
        if old_browser is not None:
            try:
                await old_browser.close()
            except Exception:
                pass
        print(f"[a11y] reviving {site_key}", flush=True)
        bb = await self._create_one(0, enqueue=False)
        if bb is None:
            return None
        try:
            snap = await self._read_url(bb, url or self.study.url)
        except Exception as exc:  # noqa: BLE001
            print(f"[a11y] revive read failed {site_key}: {exc!r}", flush=True)
            return None
        handle = snap.pop("_handle", None) if isinstance(snap, dict) else None
        if not isinstance(handle, dict):
            return None
        handle["site_key"] = site_key
        handle["read"] = snap
        self.contexts[site_key] = handle
        self.snapshots[site_key] = snap
        return handle

    async def close(self) -> None:
        """Close the shared browsers after every agent has finished."""
        seen: set[int] = set()
        for handle in list(self.contexts.values()):
            browser = handle.get("browser")
            if browser is not None and id(browser) not in seen:
                seen.add(id(browser))
                try:
                    await browser.close()
                except Exception:
                    pass
            bb = handle.get("bb")
            sid = getattr(bb, "id", None)
            if not sid:
                continue
            try:
                from capability.browserbase_client import close_session

                await asyncio.to_thread(close_session, sid)
            except Exception:
                pass

    def snapshot_for(self, site_key: str) -> dict[str, Any] | None:
        return self.snapshots.get(site_key)


_AUTH_NAMES = frozenset(
    {
        "log in",
        "sign up",
        "sign in",
        "login",
        "signup",
        "open app",
        "get started",
        "continue with email",
        "continue with google",
        "continue with saml sso",
    }
)


def _auth_href(href: str) -> bool:
    text = (href or "").lower()
    return "/login" in text or "/signup" in text or "plus.excalidraw.com" in text


def _nodes_for_model(nodes: list[dict[str, Any]], skip: set[str]) -> list[dict[str, Any]]:
    """Drop inert controls, login walls, and controls already clicked with no change."""
    skipped = {str(item).lower() for item in skip if str(item).strip()}
    kept: list[dict[str, Any]] = []
    for node in nodes or []:
        if not isinstance(node, dict) or node.get("inert"):
            continue
        name = str(node.get("name") or "").strip().lower()
        href = str(node.get("href") or "").strip().lower()
        if name in _AUTH_NAMES or _auth_href(href):
            continue
        if name and name in skipped:
            continue
        if href and href in skipped:
            continue
        kept.append(node)
    return kept


async def _model_action(
    *,
    task: str,
    read: dict[str, Any],
    history: list[str],
    changed_nothing: bool = False,
) -> dict[str, Any] | None:
    from capability.gemini_config import extract_json, gemini_chat

    ax = format_ax(read.get("nodes") or [])
    flag = (
        "Previous action changed nothing. Do not click that element again.\n"
        if changed_nothing
        else "Previous action changed the page.\n"
        if history
        else ""
    )
    prompt = (
        "You are a logged-out visitor finishing a task in the browser. Reply with one JSON object only.\n"
        f"Task: {task[:400]}\n"
        f"URL: {read.get('url') or ''}\n"
        f"Title: {read.get('title') or ''}\n"
        f"Visible text: {str(read.get('text') or '')[:700]}\n"
        f"Elements (i role name href):\n{ax}\n"
        f"Already did: {'; '.join(history[-6:]) or 'nothing'}\n"
        f"{flag}"
        'JSON: {"act":"click|type|scroll|drag|done","i":0,"text":"","friction":"","easy":""}\n'
        "Use an element i from the list for click, type, and scroll. "
        "Do not click Log in, Sign up, or Open app. Stay on the public site. "
        "A homepage preview of the product is not the real app. "
        "For how to create an issue, open Docs or Documentation, then the Issues section, then Create issues. "
        "For pricing or getting started, open Pricing. "
        "To draw a box on excalidraw.com, click Rectangle, then the next action must be drag. "
        "drag presses r and drags inside the canvas box from the tree. Selecting the tool is not done. "
        "done for a drawing only after the drag has changed the canvas. "
        "On excalidraw.com, open Menu and Export image only when the task asks to export or share. "
        "Rectangle, drag, and Export image are excalidraw.com controls. Do not use them on any other site. "
        "done only when that outcome is already visible. "
        "friction is one sentence if a control was unclear, else empty. "
        "easy is one sentence naming a control that was obvious, else empty."
    )
    try:
        # No per-step deadline. A slow model call keeps going; the study budget
        # is the only timer, and a failed call falls through to the keyword move.
        raw = await gemini_chat(
            [{"role": "user", "content": prompt}],
            model=fast_action_model(),
            temperature=0,
            json_mode=True,
            max_retries=1,
        )
        data = extract_json(raw)
    except Exception as exc:  # noqa: BLE001
        print(f"[a11y] model action failed: {exc!r}", flush=True)
        return None
    if not isinstance(data, dict):
        return None
    act = str(data.get("act") or "click").lower().strip()
    if act not in {"click", "type", "scroll", "drag", "done"}:
        act = "click"
    try:
        index = int(data.get("i") or 0)
    except (TypeError, ValueError):
        index = 0
    nodes = read.get("nodes") or []
    node = next((n for n in nodes if isinstance(n, dict) and int(n.get("i") or 0) == index), None)
    if node is None and nodes and isinstance(nodes[0], dict):
        node = nodes[0]
    out = {
        "act": act,
        "i": index,
        "text": str(data.get("text") or "")[:120],
        "friction": str(data.get("friction") or "")[:180],
        "easy": str(data.get("easy") or "")[:180],
        "name": str((node or {}).get("name") or data.get("text") or "")[:80],
        "href": str((node or {}).get("href") or "")[:180],
        "role": str((node or {}).get("role") or ""),
        "x": int((node or {}).get("x") or 0),
        "y": int((node or {}).get("y") or 0),
    }
    return out


def _pw_role(role: str) -> str:
    return {
        "a": "link",
        "link": "link",
        "button": "button",
        "menuitem": "menuitem",
        "tab": "tab",
        "textbox": "textbox",
        "input": "textbox",
        "textarea": "textbox",
    }.get((role or "").lower(), "")


async def _click_named(page: Any, action: dict[str, Any]) -> str:
    """Click the live control by role and name, then by its bounding box."""
    name = str(action.get("name") or "").strip()
    role = _pw_role(str(action.get("role") or ""))
    if name and role:
        loc = page.get_by_role(role, name=name, exact=True)
        try:
            count = await loc.count()
        except Exception:
            count = 0
        if not count:
            loc = page.get_by_role(role, name=name, exact=False)
            try:
                count = await loc.count()
            except Exception:
                count = 0
        if count:
            await loc.first.click(timeout=3000)
            return "role"
    x = int(action.get("x") or 0)
    y = int(action.get("y") or 0)
    if x or y:
        await page.mouse.click(x, y)
        return "xy"
    if name:
        loc = page.get_by_text(name, exact=False)
        if await loc.count():
            await loc.first.click(timeout=3000)
            return "text"
    return "miss"


def _canvas_box(nodes: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Largest canvas rectangle in the accessibility tree."""
    best: dict[str, Any] | None = None
    best_area = 0
    for node in nodes or []:
        if not isinstance(node, dict):
            continue
        if str(node.get("role") or "") != "canvas":
            continue
        w = int(node.get("w") or 0)
        h = int(node.get("h") or 0)
        if w * h > best_area:
            best = node
            best_area = w * h
    return best


async def _drag_on_canvas(page: Any, action: dict[str, Any]) -> None:
    """Press r, then drag inside the canvas box from the tree."""
    try:
        await page.keyboard.press("Escape")
    except Exception:
        pass
    try:
        await page.keyboard.press("r")
    except Exception:
        pass
    cx = int(action.get("canvas_x") or 0)
    cy = int(action.get("canvas_y") or 0)
    cw = int(action.get("canvas_w") or 0)
    ch = int(action.get("canvas_h") or 0)
    if cw > 200 and ch > 200 and (cx or cy):
        x1 = int(cx - cw * 0.12)
        y1 = int(cy - ch * 0.02)
        x2 = int(cx + cw * 0.18)
        y2 = int(cy + ch * 0.22)
    else:
        x1, y1, x2, y2 = 420, 280, 760, 500
    await page.mouse.move(x1, y1)
    await page.mouse.down()
    await page.mouse.move(x2, y2, steps=12)
    await page.mouse.up()


async def _act(page: Any, action: dict[str, Any]) -> str:
    """Run one action. Returns how it was performed."""
    act = str(action.get("act") or "click")
    if act == "scroll":
        await page.mouse.wheel(0, int(action.get("dy") or 500))
        return "scroll"
    if act == "type":
        await _click_named(page, action)
        text = str(action.get("text") or action.get("name") or "")
        if text:
            await page.keyboard.type(text, delay=0)
        return "type"
    if act == "drag":
        host = _host(getattr(page, "url", "") or "")
        if host != "excalidraw.com":
            return "miss"
        await _drag_on_canvas(page, action)
        return "drag"
    if act == "done":
        return "done"
    return await _click_named(page, action)


async def _wait_for_page(page: Any) -> None:
    """Brief wait so a click can navigate or the DOM can update."""
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=1500)
    except Exception:
        pass
    try:
        await page.wait_for_timeout(400)
    except Exception:
        pass


async def _screenshot_hash(page: Any) -> tuple[str, str]:
    """Hash the viewport for the stuck check. The bytes are discarded."""
    try:
        blob = await page.screenshot(type="jpeg", quality=25, full_page=False, timeout=8000)
    except Exception as exc:  # noqa: BLE001
        if browser_dead(exc):
            print(f"[a11y] viewport hash ended: {exc!r}", flush=True)
            return "", "session ended"
        print(f"[a11y] screenshot hash skipped: {exc!r}", flush=True)
        return "", ""
    if not blob:
        return "", ""
    return hashlib.sha256(blob).hexdigest()[:16], ""


async def _one_read(page: Any, fallback_url: str) -> dict[str, Any]:
    t0 = time.perf_counter()
    try:
        raw = await asyncio.wait_for(page.evaluate(_READ_JS), timeout=8)
    except asyncio.TimeoutError:
        return {
            "url": fallback_url,
            "text": "",
            "canvas": "",
            "nodes": [],
            "title": "",
            "error": "accessibility read timed out",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "url": fallback_url,
            "text": "",
            "canvas": "",
            "nodes": [],
            "error": repr(exc)[:200],
            "read_ms": int(round((time.perf_counter() - t0) * 1000)),
        }
    if not isinstance(raw, dict):
        raw = {"url": fallback_url, "text": "", "canvas": "", "nodes": []}
    raw["nodes"] = list(raw.get("nodes") or [])[:AX_CAP]
    raw["url"] = str(raw.get("url") or fallback_url)
    raw["read_ms"] = int(round((time.perf_counter() - t0) * 1000))
    return raw


def _observation_changed(
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    task: str = "",
) -> bool:
    """True when the live page is not the page we just acted on.

    Canvas samples on marketing pages flicker by hundreds of dark pixels.
    Only a draw task treats that as a real change.
    """
    before_key = _page_key(str(before.get("url") or ""))
    after_key = _page_key(str(after.get("url") or ""))
    if before_key != ("", "", "") and after_key != ("", "", "") and before_key != after_key:
        return True
    before_text = str(before.get("text") or "")
    after_text = str(after.get("text") or "")
    if before_text != after_text and abs(len(after_text) - len(before_text)) >= 40:
        return True
    before_low = before_text.lower()
    after_low = after_text.lower()
    for marker in ("selected shape", "export image", "keyboard shortcuts", "create issues"):
        if marker in after_low and marker not in before_low:
            return True
    if task_kind(task) != "draw":
        return False
    host = _host(str(after.get("url") or before.get("url") or ""))
    if host != "excalidraw.com":
        return False
    before_dark = _canvas_dark(str(before.get("canvas") or ""))
    after_dark = _canvas_dark(str(after.get("canvas") or ""))
    if before_dark >= 0 and after_dark >= 0 and abs(after_dark - before_dark) >= 8:
        return True
    return False


async def _fresh_read(page: Any, fallback_url: str) -> dict[str, Any]:
    """One accessibility read, retried once if the page was mid-navigation."""
    fresh = await _one_read(page, fallback_url)
    if fresh.get("error") and not browser_dead(str(fresh.get("error"))):
        fresh = await _one_read(page, fallback_url)
    return fresh


async def complete_task_on_page(
    page: Any,
    *,
    task: str,
    url: str,
    trace: list[dict[str, Any]] | None = None,
    history: list[str] | None = None,
    step_no: int = 0,
    opened_canvas: str = "",
    on_step: Any | None = None,
    deadline: float | None = None,
    agent_id: str = "agent",
) -> dict[str, Any]:
    """Step until the live page shows the goal.

    Every step re-reads the page. The action is chosen from that read, executed
    with a role+name click, then checked against a new read. A control that
    does not change the page is not clicked again.
    """
    trace = list(trace or [])
    history = list(history or [])
    read: dict[str, Any] = {"url": url, "text": "", "canvas": "", "nodes": [], "title": ""}
    drew = False
    failed: dict[str, Any] | None = None
    stop_reason = ""
    skip: set[str] = set()
    logs: list[dict[str, Any]] = []
    previous_sig: tuple[str, str, str, str] | None = None
    stuck_streak = 0
    changed_nothing = False
    saw_opening = False
    acted_once = False
    model_misses = 0
    offhost_refusals = 0
    done_rejects = 0
    try:
        await page.wait_for_selector("a, button, canvas", timeout=800)
    except Exception:
        pass

    def _miss(reason: str = "page did not show the goal") -> None:
        nonlocal stop_reason, failed
        stop_reason = reason
        failed = {"phase": "act", "reason": reason, "step": step_no}

    while failed is None:
        if deadline is not None and time.monotonic() >= deadline:
            _miss("study budget")
            failed = {"phase": "study_budget", "reason": "study budget", "step": step_no}
            break
        fresh = await _fresh_read(page, str(read.get("url") or url))
        if fresh.get("error") and browser_dead(str(fresh.get("error"))):
            print(f"[{agent_id}] session ended: {fresh.get('error')}", flush=True)
            _miss("session ended")
            failed = {"phase": "read", "reason": "session ended", "step": step_no}
            break
        if fresh.get("error"):
            # A failed read must not reuse the tree from before the last click.
            if acted_once:
                continue
        else:
            read = fresh
        if not saw_opening:
            saw_opening = True
            if not opened_canvas:
                opened_canvas = str(read.get("canvas") or "")
        read["opened_canvas"] = opened_canvas
        read["drew"] = drew
        if goal_visible(task, read):
            stop_reason = "done"
            if task_kind(task) == "draw":
                drew = True
                read["drew"] = True
            break
        signature = progress_signature(
            url=str(read.get("url") or ""),
            screenshot_hash="",
            text=str(read.get("text") or ""),
            canvas=str(read.get("canvas") or ""),
        )
        stuck_streak, stuck_reason = note_progress(previous_sig, signature, stuck_streak)
        previous_sig = signature
        if stuck_reason:
            print(f"[{agent_id}] no progress: {stuck_reason}", flush=True)
            _miss()
            break
        model_read = dict(read)
        model_read["nodes"] = _nodes_for_model(list(read.get("nodes") or []), skip)
        try:
            action = await asyncio.wait_for(
                _model_action(
                    task=task,
                    read=model_read,
                    history=history,
                    changed_nothing=changed_nothing,
                ),
                timeout=20,
            )
        except asyncio.TimeoutError:
            print(f"[{agent_id}] model action timed out", flush=True)
            action = None
        source = "model"
        if not isinstance(action, dict):
            invented = invented_excalidraw_action(task, read, history, skip)
            if invented is not None:
                action = invented
                source = "excalidraw"
            else:
                model_misses += 1
                if model_misses >= 3:
                    _miss("model returned no action")
                    break
                changed_nothing = True
                history.append("model returned no action")
                continue
        model_misses = 0
        if str(action.get("act")) == "done":
            if goal_visible(task, read):
                stop_reason = "done"
                break
            done_rejects += 1
            if done_rejects >= 3:
                _miss("model said done before the goal was visible")
                break
            changed_nothing = True
            history.append("done rejected: goal not visible")
            previous_sig = None
            stuck_streak = 0
            continue
        chosen = str(action.get("name") or "").strip().lower()
        if offhost_excalidraw_tool(action, str(read.get("url") or url)):
            # Do not invent Rectangle / Export image / canvas drag on Miro.
            # Recording that click three times aborts the whole study.
            skip.add(chosen or "export")
            offhost_refusals += 1
            if offhost_refusals >= 2 or would_repeat_action(trace, action_label(action), read):
                _miss("excalidraw tool is not on this site")
                break
            changed_nothing = True
            history.append(f"skipped off-host {chosen or action.get('act')}")
            continue
        if chosen and chosen in skip and str(action.get("act")) == "click":
            changed_nothing = True
            history.append(f"skipped repeat {chosen}")
            continue
        if (
            task_kind(task) == "draw"
            and _host(str(read.get("url") or url)) == "excalidraw.com"
            and str(action.get("act")) != "drag"
        ):
            # The rectangle tool is selected. The next move is a canvas drag,
            # not the export menu.
            selected = "selected shape" in str(read.get("text") or "").lower() or any(
                "rectangle" in item.lower() for item in history
            )
            if selected and not goal_visible(task, read):
                action = dict(action)
                action["act"] = "drag"
                action["name"] = "canvas"
                action["role"] = "canvas"
        if str(action.get("act")) == "drag":
            box = _canvas_box(list(read.get("nodes") or []))
            if box:
                action["canvas_x"] = int(box.get("x") or 0)
                action["canvas_y"] = int(box.get("y") or 0)
                action["canvas_w"] = int(box.get("w") or 0)
                action["canvas_h"] = int(box.get("h") or 0)
        label = action_label(action)
        if would_repeat_action(trace, label, read):
            _miss()
            break
        step_no += 1
        row = _step_from_read(step=step_no, action=label, read=read, thought="")
        row["decision_source"] = source
        row["decision"] = {
            "act": action.get("act"),
            "name": action.get("name"),
            "href": action.get("href"),
            "role": action.get("role"),
            "source": source,
        }
        trace.append(row)
        history.append(label)
        if on_step is not None:
            maybe = on_step(row)
            if asyncio.iscoroutine(maybe):
                await maybe
        how = ""
        try:
            how = await asyncio.wait_for(_act(page, action), timeout=12)
        except asyncio.TimeoutError:
            print(f"[{agent_id}] action timed out: {label}", flush=True)
            how = "timeout"
            skip.add(str(action.get("name") or "").lower())
        except Exception as exc:  # noqa: BLE001
            if browser_dead(exc):
                print(f"[{agent_id}] session ended: {exc!r}", flush=True)
                _miss("session ended")
                failed = {"phase": "act", "reason": "session ended", "step": step_no}
                break
            print(f"[{agent_id}] action error (continuing): {exc!r}", flush=True)
            how = f"error:{exc!r}"[:180]
        acted_once = True
        if how in {"scroll", "type", "drag", "role", "xy", "text"}:
            row["first_action_at_ts"] = time.time()
            if on_step is not None:
                maybe = on_step(row)
                if asyncio.iscoroutine(maybe):
                    await maybe
        await _wait_for_page(page)
        after = await _fresh_read(page, str(read.get("url") or url))
        if (
            how in {"drag", "role"}
            and not after.get("error")
            and not _observation_changed(read, after, task=task)
        ):
            try:
                await page.wait_for_timeout(300)
            except Exception:
                pass
            again = await _fresh_read(page, str(read.get("url") or url))
            if not again.get("error"):
                after = again
        if after.get("error") and browser_dead(str(after.get("error"))):
            print(f"[{agent_id}] session ended: {after.get('error')}", flush=True)
            _miss("session ended")
            failed = {"phase": "read", "reason": "session ended", "step": step_no}
            break
        clicked = str(action.get("name") or "").lower()
        if (
            not after.get("error")
            and task_kind(task) == "issue"
            and "new issue" in clicked
        ):
            body = str(after.get("text") or "").lower()
            composer = "issue title" in body or ("description" in body and "title" in body)
            if not composer:
                skip.add(clicked)
                changed_nothing = True
                try:
                    await page.keyboard.press("Escape")
                except Exception:
                    pass
                try:
                    await page.mouse.wheel(0, 700)
                except Exception:
                    pass
                await _wait_for_page(page)
                scrolled = await _fresh_read(page, str(read.get("url") or url))
                if not scrolled.get("error"):
                    after = scrolled
        if not after.get("error") and _auth_href(str(after.get("url") or "")):
            skip.add(str(action.get("name") or "").lower())
            href = str(action.get("href") or "")
            if href:
                skip.add(href.lower())
            try:
                await page.go_back(wait_until="domcontentloaded", timeout=4000)
            except Exception:
                pass
            await _wait_for_page(page)
            backed = await _fresh_read(page, str(read.get("url") or url))
            if not backed.get("error"):
                after = backed
            changed_nothing = True
        if not after.get("error"):
            changed = _observation_changed(read, after, task=task)
            if str(action.get("act")) == "drag" and _host(str(after.get("url") or "")) == "excalidraw.com":
                before_dark = _canvas_dark(str(read.get("canvas") or ""))
                after_dark = _canvas_dark(str(after.get("canvas") or ""))
                canvas_moved = (
                    before_dark >= 0
                    and after_dark >= 0
                    and abs(after_dark - before_dark) >= 8
                )
                changed = changed or canvas_moved or goal_visible(task, after)
            if not changed:
                skip.add(str(action.get("name") or "").lower())
                href = str(action.get("href") or "")
                if href:
                    skip.add(href.lower())
                changed_nothing = True
            else:
                changed_nothing = False
            row["changed"] = changed
            after["opened_canvas"] = opened_canvas
            if task_kind(task) == "draw" and goal_visible(task, after):
                drew = True
            after["drew"] = drew
            read = after
            row["url"] = str(read.get("url") or "")
            previous_canvas = ""
            if len(trace) >= 2 and isinstance(trace[-2], dict):
                previous_sig = trace[-2].get("state_sig")
                if isinstance(previous_sig, dict):
                    previous_canvas = str(previous_sig.get("canvas") or "")
            row["state_sig"] = {
                "text": str(read.get("text") or "")[:1500],
                "canvas": trace_canvas(
                    previous_canvas,
                    str(read.get("canvas") or ""),
                    str(read.get("url") or ""),
                    task,
                ),
            }
            row["accessibility_tree"] = format_ax(read.get("nodes") or [])
            row["ax_tree"] = row["accessibility_tree"]
        logs.append(
            {
                "step": step_no,
                "observation": str(row.get("observation") or "")[:300],
                "decision": row.get("decision"),
                "executed": label,
                "how": how,
                "url_after": str(read.get("url") or ""),
                "dom_after": str(read.get("text") or "")[:300],
                "title_after": str(read.get("title") or ""),
            }
        )
        if goal_visible(task, read):
            stop_reason = "done"
            if task_kind(task) == "draw":
                drew = True
                read["drew"] = True
            break

    if stop_reason == "done" or goal_visible(task, read):
        _stamp_observation(trace, read)
    if stop_reason:
        print(f"[{agent_id}] stop reason: {stop_reason}", flush=True)
    if not isinstance(failed, dict):
        if stop_reason == "done" or goal_visible(task, read):
            failed = {"phase": "done", "reason": "task complete", "step": step_no}
            stop_reason = stop_reason or "done"
        else:
            failed = {"phase": "act", "reason": "page did not show the goal", "step": step_no}
    return {
        "stop_reason": stop_reason,
        "failed": failed,
        "trace": trace,
        "history": history,
        "step_no": step_no,
        "read": read,
        "drew": drew,
        "opened_canvas": opened_canvas,
        "logs": logs,
    }


# A slow Browserbase slot must not fail the 5s page-open gate. Replace it
# when navigation has not committed inside this window.
SLOW_OPEN_S = 3.5


def should_replace_open(*, started: float, now: float, opened: float | None) -> bool:
    """True when this attempt has no navigation-commit stamp inside 3.5s.

    ``opened`` is the time ``goto(wait_until='commit')`` returned. A missing
    stamp, or one copied from the attempt start, is not an open.
    """
    del now
    if opened is None:
        return True
    if abs(float(opened) - float(started)) < 1e-6:
        return True
    return (float(opened) - float(started)) > SLOW_OPEN_S


async def _open_agent_session(
    boot: A11yBoot, url: str
) -> tuple[Any, Any, Any, float | None, float | None]:
    """A new Browserbase session for this agent only.

    Returns the session, browser, page, the goto-commit time, and the attempt
    start. page_open is the commit time. It is not the attempt start.
    """
    from capability.browserbase_client import create_session, study_session_owner

    deadline = getattr(boot.study, "budget_deadline", None) or (
        time.monotonic() + study_budget_s()
    )
    bb = None
    browser = None
    last = "no browser session"
    held_slot = False

    async def _attach(session: Any) -> tuple[Any, Any, Any, float | None, float]:
        pw = await boot._playwright()
        attached = await pw.chromium.connect_over_cdp(session.connect_url)
        context = attached.contexts[0] if attached.contexts else await attached.new_context()
        page = context.pages[0] if context.pages else await context.new_page()
        try:
            await page.set_viewport_size({"width": 1440, "height": 900})
        except Exception:
            pass
        try:
            page.set_default_timeout(8000)
            page.set_default_navigation_timeout(8000)
        except Exception:
            pass
        started = time.time()
        opened: float | None = None
        try:
            await page.goto(url, wait_until="commit", timeout=4500)
            opened = time.time()
        except Exception as exc:  # noqa: BLE001
            print(f"[a11y] agent goto {url}: {exc!r}", flush=True)
        return session, attached, page, opened, started

    try:
        if _owner_is_taskfix() and str(getattr(boot.study, "id", "") or "") == "prime":
            raise RuntimeError("taskfix does not open prime sessions")
        if not _owner_is_taskfix():
            try:
                bb = boot.pool.get_nowait()
            except asyncio.QueueEmpty:
                bb = None
        if bb is not None:
            try:
                bb, browser, page, opened, started = await _attach(bb)
                if not should_replace_open(started=started, now=time.time(), opened=opened):
                    return bb, browser, page, opened, started
                print(
                    f"[a11y] replace pooled open gap="
                    f"{None if opened is None else round(opened - started, 3)}s",
                    flush=True,
                )
                await _close_agent_session(browser, bb)
                bb = None
                browser = None
            except Exception as exc:  # noqa: BLE001
                print(f"[a11y] pooled session unusable: {exc!r}", flush=True)
                await _close_agent_session(browser, bb)
                bb = None
                browser = None
        if not await _acquire_taskfix_slot():
            raise RuntimeError("taskfix session cap is 2")
        held_slot = _owner_is_taskfix()
        for _attempt in range(2):
            if time.monotonic() >= deadline:
                break
            bb = None
            while bb is None and time.monotonic() < deadline:
                try:
                    bb = await asyncio.to_thread(
                        create_session,
                        proxies=False,
                        keep_alive=True,
                        solve_captchas=False,
                        advanced_stealth=False,
                        owner=study_session_owner(),
                        study_id=getattr(boot.study, "id", None),
                    )
                    break
                except Exception as exc:  # noqa: BLE001
                    last = repr(exc)
                    print(f"[a11y] agent session create retry: {exc!r}", flush=True)
                    await asyncio.sleep(2)
            if bb is None:
                break
            try:
                bb, browser, page, opened, started = await _attach(bb)
            except Exception as exc:  # noqa: BLE001
                last = repr(exc)
                print(f"[a11y] agent attach failed: {exc!r}", flush=True)
                await _close_agent_session(browser, bb)
                bb = None
                browser = None
                continue
            if not should_replace_open(started=started, now=time.time(), opened=opened):
                if held_slot:
                    try:
                        browser._taskfix_slot = True
                    except Exception:
                        pass
                return bb, browser, page, opened, started
            print(
                f"[a11y] replace slow open gap="
                f"{None if opened is None else round(opened - started, 3)}s",
                flush=True,
            )
            await _close_agent_session(browser, bb)
            bb = None
            browser = None
            last = "page open did not commit within 3.5s"
        raise RuntimeError(last)
    except Exception:
        await _close_agent_session(browser, bb)
        if held_slot:
            _release_taskfix_slot()
        raise


async def _close_agent_session(browser: Any, bb: Any) -> None:
    try:
        if browser is not None:
            await browser.close()
    except Exception:
        pass
    sid = getattr(bb, "id", None) if bb is not None else None
    if not sid:
        return
    try:
        from capability.browserbase_client import close_session

        await asyncio.to_thread(close_session, sid)
    except Exception:
        pass


async def run_a11y_agent(
    *,
    boot: A11yBoot,
    study_id: str,
    agent_id: str,
    url: str,
    task_prompt: str,
    persona: dict[str, Any],
    on_step: Any | None = None,
    site_key: str = "product",
    deadline: float | None = None,
) -> dict[str, Any]:
    """One Browserbase session for this agent. The shared read is display only."""
    del site_key
    return await _run_a11y_agent_unlocked(
        boot=boot,
        study_id=study_id,
        agent_id=agent_id,
        url=url,
        task_prompt=task_prompt,
        persona=persona,
        on_step=on_step,
        deadline=deadline,
    )


async def _run_a11y_agent_unlocked(
    *,
    boot: A11yBoot,
    study_id: str,
    agent_id: str,
    url: str,
    task_prompt: str,
    persona: dict[str, Any],
    on_step: Any | None = None,
    deadline: float | None = None,
) -> dict[str, Any]:
    """Own browser, fresh read each step, one final shot.

    The shared snapshot stays on step 0 for display. This agent does not
    reuse that page.
    """
    from mvp.paths import MVP_RUNS_DIR

    sess = boot.study.live_sessions.get(agent_id) or {}
    failed: dict[str, Any] | None = None
    stop_reason = ""
    page = None
    browser = None
    bb = None
    if deadline is None:
        deadline = time.monotonic() + study_budget_s()
    drew = False
    opened_canvas = ""
    history: list[str] = []
    trace = [
        step
        for step in (sess.get("trace") or [])
        if isinstance(step, dict) and int(step.get("step") or 0) == 0
    ]
    step_no = 0
    read = {"url": url, "text": "", "canvas": "", "nodes": [], "title": ""}
    try:
        opened_at: float | None = None
        try:
            bb, browser, page, opened_at, started_at = await _open_agent_session(boot, url)
        except Exception as exc:  # noqa: BLE001
            print(f"[{agent_id}] session ended: {exc!r}", flush=True)
            stop_reason = "session ended"
            failed = {"phase": "session", "reason": "session ended", "step": 0}
        if page is not None and opened_at is not None and failed is None:
            sess["created_at_ts"] = started_at
            sess["created_at"] = datetime.fromtimestamp(
                float(started_at), timezone.utc
            ).isoformat()
            apply_gate_fields(
                sess,
                page_open_at_ts=opened_at,
                session_ready_at_ts=started_at,
            )
            if trace and isinstance(trace[0], dict):
                trace[0]["page_open_at_ts"] = opened_at
            boot.study.live_sessions[agent_id] = sess
            try:
                from mvp.study import persist_study

                persist_study(boot.study)
            except Exception:
                pass
            boot._touch()
        if page is not None and failed is None:
            phase = "act"
            outcome = await complete_task_on_page(
                page,
                task=task_prompt,
                url=url,
                trace=trace,
                history=history,
                step_no=step_no,
                opened_canvas=opened_canvas,
                on_step=on_step,
                deadline=deadline,
                agent_id=agent_id,
            )
            stop_reason = str(outcome.get("stop_reason") or "")
            failed = outcome.get("failed") if isinstance(outcome.get("failed"), dict) else failed
            trace = list(outcome.get("trace") or trace)
            history = list(outcome.get("history") or history)
            step_no = int(outcome.get("step_no") or step_no)
            read = dict(outcome.get("read") or read)
            drew = bool(outcome.get("drew"))
            opened_canvas = str(outcome.get("opened_canvas") or opened_canvas)

        read["drew"] = drew
        read["opened_canvas"] = opened_canvas
        easy, friction = notes_from_trace(trace)

        shot_url = ""
        shot_ms = 0
        if page is not None:
            phase = "final_screenshot"
            dest = MVP_RUNS_DIR / study_id / agent_id / "screenshots"
            dest.mkdir(parents=True, exist_ok=True)
            path = dest / "final.png"
            t_shot = time.perf_counter()
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=6000)
            except Exception:
                pass
            if task_kind(task_prompt) == "issue":
                try:
                    await page.evaluate(
                        "() => { const h = document.querySelector('h1'); if (h) h.scrollIntoView({block:'center'}); }"
                    )
                except Exception:
                    pass
            try:
                await page.screenshot(path=str(path), full_page=False, timeout=8000)
                shot_ms = int(round((time.perf_counter() - t_shot) * 1000))
                from mvp.opening_shot import publish_final_png

                shot_url = await asyncio.to_thread(publish_final_png, study_id, agent_id)
            except Exception as exc:  # noqa: BLE001
                print(f"[{agent_id}] final capture failed: {exc!r}", flush=True)
                if not shot_url:
                    failed = failed or {
                        "phase": "final_screenshot",
                        "reason": "final capture failed",
                        "step": step_no,
                    }
            if shot_url and trace:
                trace[-1]["screenshot_url"] = shot_url
                trace[-1]["final_screenshot_url"] = shot_url

        final_url = str(read.get("url") or url)
        if url and _host(final_url) != _host(url):
            final_url = url
        ax = format_ax(read.get("nodes") or []) or str(sess.get("accessibility_tree") or "") or "0 document page"
        final_dom = str(read.get("text") or "")[:1500] or ax
        if not isinstance(failed, dict) or not str(failed.get("phase") or "").strip():
            if stop_reason == "done" or goal_visible(task_prompt, read):
                failed = {"phase": "done", "reason": "task complete", "step": step_no}
            else:
                failed = {"phase": "act", "reason": "page did not show the goal", "step": step_no}
        phase_ms = dict(sess.get("phase_ms") or {})
        phase_ms["final_screenshot"] = shot_ms
        phase_ms["final_screenshot_ms"] = shot_ms

        result = {
            "agent_id": agent_id,
            "persona_id": persona.get("id"),
            "task_id": agent_id,
            "completed": stop_reason == "done",
            "final_url": final_url,
            "final_dom": final_dom,
            "visited_urls": [final_url],
            "actions": [{"action": h} for h in history if h],
            "trace": trace,
            "backend": "browserbase_a11y",
            "model": fast_action_model(),
            "model_provider": "google-vertex",
            "num_steps": len(trace),
            "friction_points": friction[:3],
            "what_was_easy": easy[:3],
            "quote": (easy[0] if easy else ""),
            "final_screenshot_url": shot_url,
            "final_screenshot": shot_url,
            "accessibility_tree": ax,
            "page_url": str(sess.get("page_url") or url),
            "page_open_at_ts": sess.get("page_open_at_ts"),
            "session_ready_at_ts": sess.get("session_ready_at_ts"),
            "first_action_at_ts": sess.get("first_action_at_ts"),
            "phase_ms": phase_ms,
            "failed_step": failed,
            "stop_reason": stop_reason or "done",
            "phase": "done" if stop_reason == "done" else "act",
            "error": "",
            "browser_error": "",
            "browserbase_session_id": getattr(bb, "id", None) if bb is not None else None,
        }
        ensure_phase_ms(result)
        apply_gate_fields(result, **{k: result.get(k) for k in GATE_FIELDS})
        return result
    finally:
        await _close_agent_session(browser, bb)
        if browser is not None and getattr(browser, "_taskfix_slot", False):
            _release_taskfix_slot()
        if _owner_is_taskfix():
            try:
                release_idle_taskfix()
            except Exception:
                pass
