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


def prime_sessions(n: int = 0) -> None:
    """Pre-click browsers. This harness keeps the count at 0.

    A positive ``n`` still fills the queue for a caller that opts in.
    ``n <= 0`` creates nothing, including no ``study_id=prime`` sessions.
    """
    global _PRIME_STARTED
    if _PRIME_STARTED:
        return
    _PRIME_STARTED = True
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
    // Toolbars, radio groups, menus, and tabs use a roving tabindex of -1 on real controls.
    const roving = !!el.closest('[role="toolbar"], [role="radiogroup"], [role="menu"], [role="menubar"], [role="tablist"], [role="listbox"], [role="grid"], [role="tree"], [role="dialog"]');
    const inert = ((tab === '-1') && !href && !roving) || !!el.disabled || el.getAttribute('aria-disabled') === 'true' || !!el.closest('[aria-hidden="true"], [inert]');
    let name = (
      el.getAttribute('aria-label')
      || el.getAttribute('placeholder')
      || el.getAttribute('title')
      || el.innerText
      || el.getAttribute('name')
      || el.getAttribute('data-testid')
      || ''
    ).replace(/\\s+/g, ' ').trim().slice(0, 80);
    if (!name && el.tagName === 'INPUT') name = (el.getAttribute('type') || 'input') + ' field';
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
      value: ((el.tagName === 'INPUT' && !/password|hidden|checkbox|radio/i.test(el.type || '')) || el.tagName === 'TEXTAREA') ? String(el.value || '').slice(0, 60) : (el.isContentEditable ? String(el.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 60) : ''),
      on: el.getAttribute('aria-pressed') === 'true' || el.getAttribute('aria-checked') === 'true' || el.getAttribute('aria-selected') === 'true' || el.getAttribute('aria-expanded') === 'true' || !!el.checked,
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
  const visible = (el) => { const r = el.getBoundingClientRect(); return r.width > 2 && r.height > 2; };
  const password = Array.from(document.querySelectorAll('input[type="password"]')).some(visible);
  const email_input = Array.from(document.querySelectorAll('input[type="email"], input[autocomplete="email"], input[autocomplete="username"], input[name*="email" i]')).some(visible);
  const dialog = !!document.querySelector('[role="dialog"]:not([aria-hidden="true"]), dialog[open]');
  const shapes = document.querySelectorAll('svg path, svg rect, svg ellipse, [data-shape-type], .tl-shape').length;
  let focus = null;
  const act = document.activeElement;
  if (act && act !== document.body && act !== document.documentElement) {
    const editable = act.isContentEditable || act.tagName === 'TEXTAREA' || act.tagName === 'INPUT';
    focus = {
      tag: act.tagName.toLowerCase(),
      editable: editable,
      name: (act.getAttribute('aria-label') || act.getAttribute('placeholder') || '').slice(0, 60),
      value: String(act.value || (act.isContentEditable ? act.innerText : '') || '').slice(0, 120),
    };
  }
  return { url, title, text, canvas, nodes, password, email_input, dialog, shapes, focus };
}"""


def fast_action_model() -> str:
    """Model for each step decision.

    gemini-2.5-flash with thinking off: about a second per step, and unlike
    the lite model it follows "tool selected, now drag" and account walls.
    """
    chosen = (os.environ.get("MVP_AGENT_ACTION_MODEL") or "").strip()
    return chosen or "gemini-2.5-flash"


def format_ax(nodes: list[dict[str, Any]], *, limit: int = AX_CAP) -> str:
    lines: list[str] = []
    for node in (nodes or [])[:limit]:
        if not isinstance(node, dict):
            continue
        name = str(node.get("name") or "")
        href = str(node.get("href") or "")
        inert = " inert" if node.get("inert") else " (selected)" if node.get("on") else ""
        extra = f" {href}" if href else ""
        value = str(node.get("value") or "").strip()
        if value and value != name:
            extra += f" = {value!r}"
        lines.append(
            f"{int(node.get('i') or 0)} {node.get('role') or 'el'} {name}{inert}{extra}".rstrip()
        )
    return "\n".join(lines)


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
    """Which goal this task is asking the agent to reach.

    A compound task ("draw a box, then export it") is judged on its last step.
    """
    text = (task or "").lower()
    parts = re.split(r"\bthen\b|\band then\b", text)
    if len(parts) > 1 and parts[-1].strip():
        text = parts[-1]
    if re.search(r"\b(?:rectangle|draw|square|box|shape|sketch|diagram)\b", text):
        return "draw"
    if re.search(r"\bexport\b", text) or ("share" in text and "drawing" in text):
        return "export"
    if re.search(r"\b(?:keyboard )?shortcuts?\b", text):
        return "help"
    if any(word in text for word in ("changelog", "what shipped", "shipped recently")):
        return "changelog"
    if re.search(r"\bpric(?:e|es|ing)\b|\bplans?\b|free plan", text):
        return "pricing"
    if "issue" in text:
        return "issue"
    return ""


def goal_visible(task: str, read: dict[str, Any]) -> bool:
    """True only when this page itself shows the task goal.

    Generic evidence only. A docs, help, or blog page never counts: it
    explains how to do the task, it does not show the task done. A nav label
    on the opening page is not the pricing page either.
    """
    read = read or {}
    url = str(read.get("url") or "")
    if docs_page(url):
        return False
    title = str(read.get("title") or "").lower()
    kind = task_kind(task)
    path = _page_key(url)[1].lower()
    if kind == "pricing":
        return bool(re.search(r"pric|plans", path)) or "pricing" in title
    if kind == "changelog":
        return "changelog" in path or "changelog" in title or "release notes" in title
    if kind == "draw":
        # The tool being selected is not a drawing. The page has to show ink:
        # a canvas sample that changed, or new vector shapes after a drag.
        if not read.get("drew"):
            return False
        opened = str(read.get("opened_canvas") or "")
        current = str(read.get("canvas") or "")
        if opened and current and "taint" not in opened and "taint" not in current:
            a, b = _canvas_dark(opened), _canvas_dark(current)
            if a >= 0 and b >= 0 and abs(b - a) >= 8:
                return True
        return int(read.get("shapes") or 0) > int(read.get("opened_shapes") or 0)
    if kind == "export" and read.get("downloaded"):
        return True
    # Export, help, create, and other outcomes cannot be decided from page
    # text alone. The loop asks a separate screenshot check instead.
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
        if prev is not None and prev.get("changed") is True:
            # The last click moved the view (a wizard's next "Skip"), so the
            # same label again is on a new screen.
            progressed = True
        elif prev is not None:
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
        text = str(action.get("text") or "").strip()
        field = str(action.get("name") or "").strip()
        if text and field and field != text:
            return f"type {text!r} into {field[:40]}"
        return f"type {text or field}".strip()
    if act == "press":
        return f"press {action.get('key') or name or 'Enter'}".strip()
    if act == "back":
        return "go back"
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


def trace_canvas(previous: str, current: str, url: str, task: str) -> str:
    """Canvas sample stored on a trace step. Only a draw task keeps canvas changes."""
    if task_kind(task) == "draw":
        return current or ""
    return previous or ""


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


def stamp_published_step(
    step: dict[str, Any],
    *,
    task: str = "",
    read: dict[str, Any] | None = None,
    screenshot_url: str = "",
) -> dict[str, Any]:
    """Write final_screenshot_url, state_sig.text, and goal_visible onto one step.

    The study persists whatever is on the step at save time. Insights can cite
    a past-homepage screenshot only when those three fields are already there.
    Canvas flicker stays off the signature except for an Excalidraw drawing.
    """
    if not isinstance(step, dict):
        return step
    live = read if isinstance(read, dict) else {}
    sig = step.get("state_sig") if isinstance(step.get("state_sig"), dict) else {}
    text = str(live.get("text") or sig.get("text") or step.get("observation") or "")
    url = str(live.get("url") or step.get("url") or "")
    prior_canvas = str(sig.get("canvas") or "")
    current_canvas = str(live.get("canvas") or prior_canvas)
    if task:
        canvas = trace_canvas(prior_canvas, current_canvas, url, task)
    else:
        canvas = prior_canvas or current_canvas
    step["url"] = url
    step["state_sig"] = {"text": text[:1500], "canvas": canvas}
    if text:
        step["observation"] = text[:400]
    visible_read = {
        "url": url,
        "text": text,
        "title": str(live.get("title") or ""),
        "canvas": str(live.get("canvas") or current_canvas),
        "opened_canvas": str(live.get("opened_canvas") or ""),
        "drew": bool(live.get("drew")),
        "shapes": live.get("shapes"),
        "opened_shapes": live.get("opened_shapes"),
        "dialog": live.get("dialog"),
    }
    if task:
        step["goal_visible"] = bool(goal_visible(task, visible_read))
    elif "goal_visible" not in step:
        step["goal_visible"] = False
    shot = str(
        screenshot_url or step.get("final_screenshot_url") or step.get("screenshot_url") or ""
    ).strip()
    if shot:
        step["screenshot_url"] = shot
        step["final_screenshot_url"] = shot
    nodes = live.get("nodes")
    if nodes:
        ax = format_ax(nodes)
        if ax:
            step["accessibility_tree"] = ax
            step["ax_tree"] = ax
    return step


def _stamp_observation(
    trace: list[dict[str, Any]],
    read: dict[str, Any],
    task: str = "",
) -> None:
    """Write the live page onto the latest step before the study saves it.

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
    stamp_published_step(last, task=task, read=read)


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
        # One shared read per site. The first agent of a site whose own page
        # commits does it; every agent of that site takes it as its step-0 read.
        self._site_events: dict[str, asyncio.Event] = {}
        self._site_readers: set[str] = set()

    def _site_event(self, site_key: str) -> asyncio.Event:
        ev = self._site_events.get(site_key)
        if ev is None:
            ev = asyncio.Event()
            self._site_events[site_key] = ev
        return ev

    async def site_read(
        self,
        site_key: str,
        page: Any,
        url: str,
        *,
        wait_s: float = 4.0,
    ) -> dict[str, Any] | None:
        """The one shared read for ``site_key``.

        The first caller reads its own freshly opened page and publishes it
        for the whole site. Later callers wait for that read (never for
        another site's read) and never re-read. Returns None when no read
        landed in time; the caller then lets the loop take its own first read.
        """
        ev = self._site_event(site_key)
        snap = self.snapshots.get(site_key)
        if snap is not None:
            return snap
        if site_key not in self._site_readers:
            self._site_readers.add(site_key)
            try:
                snap = await asyncio.wait_for(self._read_page(page, url), timeout=wait_s + 2)
            except Exception as exc:  # noqa: BLE001
                print(f"[a11y] shared read {site_key} failed: {exc!r}", flush=True)
                snap = None
            if snap is not None and _host(str(snap.get("url") or "")) == _host(url):
                self.snapshots[site_key] = snap
                try:
                    self._publish_site(site_key, snap)
                except Exception as exc:  # noqa: BLE001
                    print(f"[a11y] publish {site_key} failed: {exc!r}", flush=True)
                ev.set()
                return snap
            # Let the next agent of this site try its own page instead.
            self._site_readers.discard(site_key)
            return None
        try:
            await asyncio.wait_for(ev.wait(), timeout=wait_s)
        except asyncio.TimeoutError:
            return None
        return self.snapshots.get(site_key)

    async def _read_page(self, page: Any, url: str) -> dict[str, Any]:
        """Text accessibility read of an already-open page (no navigation, no screenshot)."""
        t0 = time.perf_counter()
        try:
            await page.wait_for_selector("a, button, canvas", timeout=2500)
        except Exception:
            pass
        raw: Any = None
        for _ in range(2):
            try:
                raw = await page.evaluate(_READ_JS)
            except Exception as exc:  # noqa: BLE001
                print(f"[a11y] read failed {url}: {exc!r}", flush=True)
                raw = None
            if isinstance(raw, dict) and len(raw.get("nodes") or []) >= 3:
                break
            try:
                await page.wait_for_timeout(400)
            except Exception:
                break
        if not isinstance(raw, dict):
            raw = {"url": url, "title": "", "text": "", "canvas": "", "nodes": []}
        opened = time.time()
        raw["url"] = str(raw.get("url") or url)
        raw["nodes"] = list(raw.get("nodes") or [])[:AX_CAP]
        raw["session_ready_at_ts"] = opened
        raw["page_open_at_ts"] = opened
        raw["phase_ms"] = {"read_ms": int(round((time.perf_counter() - t0) * 1000))}
        return raw

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
        archetypes = [
            ("Maya Chen", "first-time evaluator", "skims the page and clicks the most obvious call to action", "28–35", "Team lead"),
            ("Dev Patel", "keyboard-first power user", "is impatient with marketing pages and wants the real product fast", "30–40", "Senior engineer"),
            ("Priya Nair", "careful buyer", "reads plan limits and pricing before committing to anything", "35–45", "Operations manager"),
            ("Sam Ortiz", "non-technical teammate", "needs clear labels and gives up on jargon", "25–32", "Coordinator"),
            ("Lena Weber", "switcher from a competitor", "expects the same shortcuts and layout as the tool they use today", "30–40", "Product manager"),
        ]
        study.personas = []
        for i in range(1, want + 1):
            name, kind, habit, age, job = archetypes[(i - 1) % len(archetypes)]
            study.personas.append(
                {
                    "id": f"p{i}",
                    "name": name,
                    "bio": f"{name} is a {kind} from {segment.rstrip('.')}; {habit}.",
                    "age_range": age,
                    "occupation": job,
                    "location": "Remote",
                    "goals": ["Finish the task", "Notice what is confusing"],
                }
            )
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
        """Install the plan and let agents start at once.

        There is no separate read browser. Each site's first agent does the
        shared read on its own page (see ``site_read``), so the study uses
        exactly one Browserbase session per agent and product agents never
        wait on a competitor read.
        """
        self._started = time.time()
        self.install_fast_plan()
        self.published.set()

    async def _playwright(self) -> Any:
        if self._pw is None:
            from playwright.async_api import async_playwright

            self._pw = await async_playwright().start()
        return self._pw

    async def _create_one(self, i: int, enqueue: bool = True) -> Any | None:
        from capability.browserbase_client import create_session, study_session_owner

        if _PRIMED is not None:
            try:
                bb = _PRIMED.get_nowait()
                print(f"[a11y] using primed session for {i + 1}", flush=True)
                if enqueue:
                    await self.pool.put(bb)
                return bb
            except asyncio.QueueEmpty:
                pass
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
                await asyncio.sleep(5)
                continue
            if enqueue:
                await self.pool.put(bb)
            return bb
        print(f"[a11y] session {i + 1} not created before the study budget", flush=True)
        return None

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
            # The shared read is display only. created_at_ts and page_open_at_ts
            # are stamped when this agent's own navigation commits, so the 5s
            # and 10s clocks do not start while browsers are still being created.
            step0 = _step_from_read(step=0, action=f"Opened {url}", read=snap)
            step0["session_ready_at_ts"] = snap.get("session_ready_at_ts")
            step0["accessibility_tree"] = ax
            sess["trace"] = [step0]
            sess["num_steps"] = 1
            sess["last_action"] = step0["action"]
            sess.pop("pending_action", None)
            apply_gate_fields(
                sess,
                session_ready_at_ts=snap.get("session_ready_at_ts"),
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
                    continue
                handle = snap.pop("_handle", None) if isinstance(snap, dict) else None
                page = (handle or {}).get("page") if isinstance(handle, dict) else None
                try:
                    closed = page is None or page.is_closed()
                except Exception:
                    closed = True
                if closed or not isinstance(handle, dict):
                    print(f"[a11y] shared read {key} had no live page (retrying)", flush=True)
                    continue
                handle["site_key"] = key
                handle["read"] = snap
                async with self._handle_cv:
                    self._handles.append(handle)
                    self.contexts[key] = handle
                    self._handle_cv.notify_all()
                self.snapshots[key] = snap
                self._publish_site(key, snap)
                await _close_agent_session(handle.get("browser"), handle.get("bb"))
                return
            print(f"[a11y] no live page for {key}", flush=True)

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
    return bool(_AUTH_PATH_RE.search(text)) or bool(_AUTH_HOST_RE.match(_host(text) or ""))


_OAUTH_RE = re.compile(
    r"\b(?:authenticate|connect|continue|sign (?:in|up)|log ?in|link|import from|integrate)\b.{0,12}\b"
    r"(?:with )?(?:google|github|gitlab|slack|microsoft|apple|jira|asana|figma|zoom|outlook|sso|saml)\b",
    re.I,
)


def _typed_item_visible(typed: list[str], read: dict[str, Any]) -> bool:
    """A title the agent typed now shows as page text outside any field (the item exists)."""
    text = " ".join(str((read or {}).get("text") or "").lower().split())
    if not text:
        return False
    values = {
        " ".join(str(n.get("value") or "").lower().split())
        for n in ((read or {}).get("nodes") or [])
        if isinstance(n, dict) and n.get("value")
    }
    for item in typed[-3:]:
        low = " ".join(item.lower().split())
        if len(low) >= 4 and low in text and low not in values:
            return True
    return False


def _nodes_for_model(
    nodes: list[dict[str, Any]],
    skip: set[str],
    *,
    allow_auth: bool = False,
    signed_in: bool = False,
) -> list[dict[str, Any]]:
    """Drop inert controls and controls already clicked with no change.

    Login and signup controls stay visible only for tasks that need an account.
    """
    skipped = {str(item).lower() for item in skip if str(item).strip()}
    kept: list[dict[str, Any]] = []
    for node in nodes or []:
        if not isinstance(node, dict) or node.get("inert"):
            continue
        name = str(node.get("name") or "").strip().lower()
        href = str(node.get("href") or "").strip().lower()
        if not allow_auth and (name in _AUTH_NAMES or _auth_href(href)):
            continue
        if signed_in and _OAUTH_RE.search(name):
            # Already signed in: third-party connect and SSO buttons only open
            # popups the agent cannot finish.
            continue
        if name and name in skipped:
            continue
        if href and href in skipped:
            continue
        kept.append(node)
    return kept


def _focus_text(focus: Any) -> str:
    if not isinstance(focus, dict):
        return "none"
    kind = "editable " if focus.get("editable") else ""
    value = str(focus.get("value") or "")
    name = str(focus.get("name") or "")
    return f"{kind}{focus.get('tag') or 'element'}{(' ' + repr(name)) if name else ''} containing {value!r}"


_ACTS = ("click", "type", "press", "scroll", "back", "drag", "done")


async def _model_action(
    *,
    task: str,
    read: dict[str, Any],
    history: list[str],
    changed_nothing: bool = False,
    account_task: bool = False,
    all_nodes: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """One model decision for the next browser action. No site hints."""
    from capability.gemini_config import extract_json, gemini_chat

    ax = format_ax(read.get("nodes") or [])
    flag = (
        "Your previous action changed nothing on the page. Pick something different.\n"
        if changed_nothing
        else "Your previous action changed the page.\n"
        if history
        else ""
    )
    access = (
        "You are signed in with a brand-new account. Get past any onboarding quickly: fill required fields, "
        "choose Skip, Continue, or Later for optional steps (integrations, invites, imports), then do the task.\n"
        if read.get("signed_in")
        else "This task needs the product itself. If the product asks you to sign up or log in, "
        "go to that sign-up or log-in page; do not read docs instead.\n"
        if account_task
        else "This task can be done on the public site without an account. Do not log in or sign up.\n"
    )
    canvas = "yes" if any(str(n.get("role") or "") == "canvas" for n in (read.get("nodes") or []) if isinstance(n, dict)) else "no"
    prompt = (
        "You are a real first-time user doing one task in a web browser. "
        "Pick the single next action. Reply with one JSON object only.\n"
        f"Task: {task[:400]}\n"
        f"URL: {read.get('url') or ''}\n"
        f"Title: {read.get('title') or ''}\n"
        f"Dialog open: {'yes' if read.get('dialog') else 'no'}. Drawing canvas on page: {canvas}.\n"
        f"Focused element: {_focus_text(read.get('focus'))}\n"
        f"Visible text: {str(read.get('text') or '')[:900]}\n"
        f"Interactive elements (i role name href):\n{ax}\n"
        f"Actions so far: {'; '.join(history[-8:]) or 'none'}\n"
        f"{flag}{access}"
        'JSON: {"act":"click|type|press|scroll|back|drag|done","i":0,"text":"","key":"","reason":"","friction":"","easy":""}\n'
        "click, type, and scroll use an element i from the list. type puts text into that field. "
        "press sends one keyboard key or shortcut in key (for example Enter, Escape, r). "
        "back returns to the previous page. drag draws by dragging across the largest canvas; select a drawing tool first. "
        "Do the task in the product the way a user would. Reading a docs, help, or blog article about the task "
        "does not do the task. "
        "Buttons inside a product screenshot or animated preview on a marketing page do nothing; do not click them. "
        "Elements marked (selected) are already on: a selected drawing tool means the next action is drag, not another click. "
        "done as soon as the current page shows the finished outcome the task asked for "
        "(for example the typed text is already in the note, or the item now exists); do not redo work. "
        "reason: at most 12 words. friction: at most 15 words if something was confusing, else empty. "
        "easy: at most 15 words naming something that was obvious, else empty."
    )
    try:
        raw = await gemini_chat(
            [{"role": "user", "content": prompt}],
            model=fast_action_model(),
            temperature=0,
            json_mode=True,
            max_retries=2,
        )
        data = extract_json(raw)
    except Exception as exc:  # noqa: BLE001
        print(f"[a11y] model action failed: {exc!r}", flush=True)
        return None
    if not isinstance(data, dict):
        return None
    act = str(data.get("act") or "click").lower().strip()
    if act not in _ACTS:
        act = "click"
    try:
        index = int(data.get("i") if data.get("i") is not None else -1)
    except (TypeError, ValueError):
        index = -1
    nodes = read.get("nodes") or []
    node = next((n for n in nodes if isinstance(n, dict) and int(n.get("i") or 0) == index), None)
    if node is None and act in {"click", "type"}:
        hidden = next(
            (n for n in (all_nodes or []) if isinstance(n, dict) and int(n.get("i") or 0) == index),
            None,
        )
        if hidden is not None:
            return {"act": "blocked", "name": str(hidden.get("name") or "")[:80]}
        print(f"[a11y] model picked no listed element: {str(raw)[:200]!r}", flush=True)
        return None
    return {
        "act": act,
        "i": index,
        "text": str(data.get("text") or "")[:120],
        "key": str(data.get("key") or "")[:24],
        "reason": str(data.get("reason") or "")[:160],
        "friction": str(data.get("friction") or "")[:180],
        "easy": str(data.get("easy") or "")[:180],
        "name": str((node or {}).get("name") or (data.get("key") if act == "press" else "") or "")[:80],
        "href": str((node or {}).get("href") or "")[:180],
        "role": str((node or {}).get("role") or ("canvas" if act == "drag" else "")),
        "x": int((node or {}).get("x") or 0),
        "y": int((node or {}).get("y") or 0),
    }


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


_LAST_FRAME: dict[str, bytes] = {}
_FRAME_TASKS: set[Any] = set()


def _spawn_last_frame(page: Any, agent_id: str) -> None:
    async def grab() -> None:
        try:
            blob = await page.screenshot(type="png", full_page=False, timeout=6000)
        except Exception:
            return
        if blob:
            _LAST_FRAME[agent_id] = blob

    try:
        task = asyncio.get_running_loop().create_task(grab())
    except RuntimeError:
        return
    _FRAME_TASKS.add(task)
    task.add_done_callback(_FRAME_TASKS.discard)


async def _escape_to_app(page: Any, read: dict[str, Any], signed_in: bool, escapes: list[str]) -> bool:
    """Once per run, a signed-in agent stuck on a setup screen opens the site's home page.

    That is what a person does when onboarding will not let go: type the
    address again. Signed in, the home page usually lands in the app.
    """
    from urllib.parse import urlsplit

    if not signed_in or escapes:
        return False
    parts = urlsplit(str(read.get("url") or ""))
    if not parts.scheme.startswith("http") or not parts.netloc:
        return False
    home = f"{parts.scheme}://{parts.netloc}/"
    escapes.append(home)
    print(f"[a11y] stuck while signed in; reopening {home}", flush=True)
    try:
        await page.goto(home, wait_until="domcontentloaded", timeout=10000)
    except Exception as exc:  # noqa: BLE001
        # SPA redirects often abort the first navigation; the page still moved.
        print(f"[a11y] reopen {home}: {str(exc)[:120]}", flush=True)
    await _wait_for_page(page)
    return True


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
        # Several controls can share a name (carousel slides, hidden
        # duplicates). Click the one the agent saw: on screen and nearest
        # to where the snapshot put it.
        size0 = getattr(page, "viewport_size", None) or {"width": 1440, "height": 900}
        vw, vh = int(size0.get("width") or 1440), int(size0.get("height") or 900)
        ax, ay = int(action.get("x") or 0), int(action.get("y") or 0)
        ranked: list[tuple[float, int]] = []
        for idx in range(min(count, 8)):
            item = loc.nth(idx)
            try:
                if not await item.is_visible():
                    continue
                box = await item.bounding_box()
            except Exception:
                continue
            if not box:
                continue
            cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
            off = not (box["x"] + box["width"] > 0 and box["x"] < vw and box["y"] + box["height"] > 0 and box["y"] < vh)
            dist = ((cx - ax) ** 2 + (cy - ay) ** 2) ** 0.5 if (ax or ay) else 0.0
            ranked.append(((1e6 if off else 0.0) + dist, idx))
        for _score, idx in sorted(ranked):
            try:
                await loc.nth(idx).click(timeout=2500)
                return "role"
            except Exception:
                continue
    href = str(action.get("href") or "")
    if href.startswith("http") and "#" not in href.split("//", 1)[-1][:1]:
        # The link exists in the tree but is not clickable where it sits
        # (hidden duplicate, off screen). Following it is what the click does.
        try:
            await page.goto(href, wait_until="domcontentloaded", timeout=8000)
            return "href"
        except Exception:
            pass
    x = int(action.get("x") or 0)
    y = int(action.get("y") or 0)
    size = getattr(page, "viewport_size", None) or {"width": 1440, "height": 900}
    if (x or y) and 0 <= y <= int(size.get("height") or 900) and 0 <= x <= int(size.get("width") or 1440):
        await page.mouse.click(x, y)
        return "xy"
    if name:
        loc = page.get_by_text(name, exact=False)
        for idx in range(min(await loc.count(), 6)):
            item = loc.nth(idx)
            try:
                if not await item.is_visible():
                    continue
                await item.click(timeout=2500)
                return "text"
            except Exception:
                continue
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
    """Drag across the middle of the largest canvas box from the tree."""
    cx = int(action.get("canvas_x") or 0)
    cy = int(action.get("canvas_y") or 0)
    cw = int(action.get("canvas_w") or 0)
    ch = int(action.get("canvas_h") or 0)
    if cw > 200 and ch > 200 and (cx or cy):
        x1 = int(cx - cw * 0.12)
        y1 = int(cy - ch * 0.05)
        x2 = int(cx + cw * 0.15)
        y2 = int(cy + ch * 0.2)
    else:
        size = getattr(page, "viewport_size", None) or {"width": 1280, "height": 800}
        w, h = int(size.get("width") or 1280), int(size.get("height") or 800)
        x1, y1, x2, y2 = int(w * 0.38), int(h * 0.4), int(w * 0.6), int(h * 0.62)
    await page.mouse.move(x1, y1)
    await page.mouse.down()
    await page.mouse.move(x2, y2, steps=12)
    await page.mouse.up()


async def _act(page: Any, action: dict[str, Any]) -> str:
    """Run one action. Returns how it was performed."""
    act = str(action.get("act") or "click")
    if act == "scroll":
        await page.mouse.wheel(0, int(action.get("dy") or 600))
        return "scroll"
    if act == "type":
        role = str(action.get("role") or "").lower()
        field = role in {"input", "textarea", "textbox", "searchbox", "combobox"}
        editing = False
        if not field:
            # A shape or note already in edit mode has focus. Clicking again
            # would move the caret or deselect it, so type straight in.
            try:
                editing = bool(
                    await page.evaluate(
                        "() => { const a = document.activeElement; return !!a && a !== document.body && "
                        "(a.isContentEditable || a.tagName === 'TEXTAREA' || (a.tagName === 'INPUT' && !['button','submit','checkbox','radio'].includes(a.type))); }"
                    )
                )
            except Exception:
                editing = False
        if editing:
            how = "focused"
        else:
            how = await _click_named(page, action)
        if text_value := str(action.get("text") or ""):
            # Replace what the field holds, the way a user retypes a value.
            try:
                await page.keyboard.press("Control+A")
            except Exception:
                pass
            await page.keyboard.type(text_value, delay=0)
        return f"type/{how}"

    if act == "press":
        key = str(action.get("key") or action.get("text") or "").strip() or "Enter"
        await page.keyboard.press(key)
        return "press"
    if act == "back":
        await page.go_back(wait_until="domcontentloaded", timeout=5000)
        return "back"
    if act == "drag":
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

    Canvas samples on marketing pages flicker. Only a draw task treats a
    canvas or vector-shape change as a real change.
    """
    before_key = _page_key(str(before.get("url") or ""))
    after_key = _page_key(str(after.get("url") or ""))
    if before_key != ("", "", "") and after_key != ("", "", "") and before_key != after_key:
        return True
    if bool(before.get("dialog")) != bool(after.get("dialog")):
        return True
    before_text = str(before.get("text") or "")
    after_text = str(after.get("text") or "")
    if before_text != after_text and abs(len(after_text) - len(before_text)) >= 40:
        return True
    before_names = {str(n.get("name") or "") for n in before.get("nodes") or [] if isinstance(n, dict)}
    after_names = {str(n.get("name") or "") for n in after.get("nodes") or [] if isinstance(n, dict)}
    if len(after_names - before_names) >= 3:
        return True
    live_before = {str(n.get("name") or "") for n in before.get("nodes") or [] if isinstance(n, dict) and not n.get("inert")}
    live_after = {str(n.get("name") or "") for n in after.get("nodes") or [] if isinstance(n, dict) and not n.get("inert")}
    if (live_after - live_before) and before_text != after_text:
        # A wizard step swaps its buttons and heading ("Connect GitHub" to
        # "Connect Slack") without much change in length.
        return True
    before_on = {str(n.get("name") or "") for n in before.get("nodes") or [] if isinstance(n, dict) and n.get("on")}
    after_on = {str(n.get("name") or "") for n in after.get("nodes") or [] if isinstance(n, dict) and n.get("on")}
    if before_on != after_on:
        return True
    if task_kind(task) != "draw":
        return False
    before_dark = _canvas_dark(str(before.get("canvas") or ""))
    after_dark = _canvas_dark(str(after.get("canvas") or ""))
    if before_dark >= 0 and after_dark >= 0 and abs(after_dark - before_dark) >= 8:
        return True
    return int(after.get("shapes") or 0) != int(before.get("shapes") or 0)


async def _fresh_read(page: Any, fallback_url: str) -> dict[str, Any]:
    """One accessibility read, retried once if the page was mid-navigation."""
    fresh = await _one_read(page, fallback_url)
    if fresh.get("error") and not browser_dead(str(fresh.get("error"))):
        fresh = await _one_read(page, fallback_url)
    return fresh


_SUBMIT_RE = re.compile(
    r"\b(?:create|save|add|submit|publish|done|confirm|send|post|finish|schedule|book|invite|upload)\b", re.I
)

_DOCS_HOST_LABELS = frozenset(
    "docs doc help support developers developer learn academy community guide guides "
    "university kb knowledge knowledgebase manual wiki blog".split()
)
_DOCS_PATH_SEGMENTS = frozenset(
    "docs doc documentation help support guide guides learn academy tutorials tutorial "
    "blog developers developer api reference community kb knowledge-base hc articles "
    "article faq manual wiki".split()
)
_AUTH_PATH_RE = re.compile(
    r"/(?:login|log-in|signin|sign-in|signup|sign-up|register|join|auth|oauth|sso|"
    r"accounts?/(?:login|signup|new)|u/login|session/new|users/sign_in|get-started/signup)\b",
    re.I,
)
_AUTH_HOST_RE = re.compile(r"^(?:accounts?|auth|login|id|signin|sso)\.", re.I)
_PUBLIC_TASK_RE = re.compile(
    r"^\s*(?:find|look|learn|read|browse|check|compare|see|explore|skim|review|search for|figure out)\b"
    r"|pricing|price|plans?\b|how much|changelog|what shipped",
    re.I,
)


def docs_page(url: str) -> bool:
    """A docs, help, guide, or blog article. It explains a task; it never completes one."""
    host = _host(url)
    if not host:
        return False
    labels = host.split(".")
    if len(labels) > 2 and labels[0] in _DOCS_HOST_LABELS:
        return True
    path = _page_key(url)[1].strip("/").lower()
    first = path.split("/", 1)[0] if path else ""
    if first in _DOCS_PATH_SEGMENTS:
        return True
    # Locale prefix: /en/docs/..., /en-us/help/...
    parts = path.split("/")
    if len(parts) >= 2 and re.fullmatch(r"[a-z]{2}(?:-[a-z]{2})?", parts[0] or "") and parts[1] in _DOCS_PATH_SEGMENTS:
        return True
    return False


def auth_page(read: dict[str, Any]) -> bool:
    """A login or signup wall: an auth URL, or a visible password / sign-in form."""
    url = str((read or {}).get("url") or "")
    host = _host(url)
    if _AUTH_PATH_RE.search(_page_key(url)[1] or "") or _AUTH_HOST_RE.match(host or ""):
        return True
    if (read or {}).get("password"):
        return True
    text = str((read or {}).get("text") or "").lower()
    if (read or {}).get("email_input") and any(
        phrase in text
        for phrase in ("continue with google", "continue with email", "sign in", "log in", "sign up", "create your account", "create an account")
    ) and len(text) < 1500:
        return True
    return False


def public_task(task: str) -> bool:
    """A task a logged-out visitor can finish (find, look up, pricing). Others need an account."""
    return bool(_PUBLIC_TASK_RE.search(task or ""))


def looping(trace: list[dict[str, Any]], window: int = 8) -> bool:
    """True when the last ``window`` actions bounce between at most two action/page pairs."""
    rows = [
        s for s in trace
        if isinstance(s, dict) and isinstance(s.get("step"), int) and int(s["step"]) >= 1
    ][-window:]
    if len(rows) < window:
        return False
    pairs = {(str(s.get("action") or ""), _page_key(str(s.get("url") or ""))) for s in rows}
    return len(pairs) <= 2


def _goal_reached_heuristic(task: str, read: dict[str, Any]) -> bool | None:
    """Cheap, generic evidence. True/False when the page decides it; None when it cannot."""
    url = str((read or {}).get("url") or "")
    if docs_page(url) or auth_page(read):
        return False
    return goal_visible(task, read) or None


async def _verify_done(
    task: str, read: dict[str, Any], opened: dict[str, Any], page: Any = None
) -> bool:
    """Separate check, with a screenshot, when the model says done and the page cannot decide."""
    import base64

    from capability.gemini_config import extract_json, gemini_chat

    url = str(read.get("url") or "")
    if docs_page(url) or auth_page(read):
        return False
    prompt = (
        "Decide if a browser task is finished, from the current page only. Reply JSON only.\n"
        f"Task: {task[:300]}\n"
        f"Start page: {opened.get('url') or ''}\n"
        f"Current URL: {url}\n"
        f"Current title: {read.get('title') or ''}\n"
        f"Current visible text: {str(read.get('text') or '')[:1200]}\n"
        f"File downloaded during the task: {read.get('downloaded') or 'none'}\n"
        f"Focused element: {_focus_text(read.get('focus'))}\n"
        "finished=true only if this page itself shows the outcome the task asked for "
        "(the created item, the drawn shape, the requested page or dialog). "
        "A docs, help, blog or marketing page that explains how is not finished. "
        "An unchanged start page is not finished.\n"
        'JSON: {"finished": true|false, "why": "short"}'
    )
    message: dict[str, Any] = {"role": "user", "content": prompt}
    if page is not None:
        try:
            blob = await page.screenshot(type="jpeg", quality=50, full_page=False, timeout=6000)
            if blob:
                message["image_b64"] = base64.b64encode(blob).decode("ascii")
                message["content"] = prompt.replace(
                    "from the current page only", "from the current page and its screenshot"
                )
        except Exception as exc:  # noqa: BLE001
            print(f"[a11y] done check screenshot skipped: {exc!r}", flush=True)
    try:
        raw = await asyncio.wait_for(
            gemini_chat(
                [message],
                model=os.environ.get("MVP_DONE_CHECK_MODEL") or "gemini-2.5-flash",
                temperature=0,
                json_mode=True,
                max_retries=2,
            ),
            timeout=15,
        )
        data = extract_json(raw)
    except Exception as exc:  # noqa: BLE001
        print(f"[a11y] done check failed: {exc!r}", flush=True)
        return False
    if os.environ.get("MVP_LOOP_DEBUG"):
        print(f"[a11y] done check: {data!r}", flush=True)
    return bool(isinstance(data, dict) and data.get("finished") is True)


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
    opening_nodes: list[dict[str, Any]] | None = None,
    initial_read: dict[str, Any] | None = None,
    max_steps: int | None = None,
    signed_in: bool = False,
) -> dict[str, Any]:
    """Generic step loop: read, one model decision, act, re-read.

    Step 0 is ``initial_read`` (the site's shared read) when given; after
    that every step reads the live page once. There are no site-specific
    moves and no scripted first click. A docs or help page never counts as
    done. A login or signup wall on an account task returns needs_account.
    """
    trace = list(trace or [])
    history = list(history or [])
    cap = int(max_steps or os.environ.get("MVP_A11Y_MAX_STEPS", "30") or 30)
    account_task = not public_task(task)
    read: dict[str, Any] = {"url": url, "text": "", "canvas": "", "nodes": [], "title": ""}
    seed: dict[str, Any] | None = None
    if isinstance(initial_read, dict) and (initial_read.get("nodes") or initial_read.get("text")):
        seed = dict(initial_read)
    elif opening_nodes:
        seed = {"url": url, "text": "", "canvas": "", "nodes": list(opening_nodes), "title": ""}
    opened: dict[str, Any] = {}
    drew = False
    failed: dict[str, Any] | None = None
    stop_reason = ""
    signup_url = ""
    skip: set[str] = set()
    escapes: list[str] = []
    typed_again = 0
    typed: list[str] = []
    logs: list[dict[str, Any]] = []
    changed_nothing = False
    model_misses = 0
    done_rejects = 0
    acted = 0
    downloads: list[str] = []
    repeats = 0

    def _on_download(download: Any) -> None:
        try:
            downloads.append(str(download.suggested_filename or "file"))
        except Exception:
            downloads.append("file")

    try:
        page.on("download", _on_download)
    except Exception:
        pass

    def _miss(reason: str = "page did not show the goal", phase: str = "act") -> None:
        nonlocal stop_reason, failed
        stop_reason = reason
        failed = {"phase": phase, "reason": reason, "step": step_no}

    while failed is None and stop_reason != "done":
        if deadline is not None and time.monotonic() >= deadline:
            _miss("study budget", "study_budget")
            break
        if acted >= cap:
            _miss(f"step cap {cap}")
            break
        if seed is not None:
            fresh, seed = seed, None
        else:
            try:
                fresh = await asyncio.wait_for(_fresh_read(page, str(read.get("url") or url)), timeout=12)
            except asyncio.TimeoutError:
                fresh = {"error": "accessibility read timed out", "url": str(read.get("url") or url)}
        if fresh.get("error"):
            if browser_dead(str(fresh.get("error"))):
                print(f"[{agent_id}] session ended: {fresh.get('error')}", flush=True)
                _miss("session ended", "read")
                break
            if not read.get("nodes"):
                read = {**read, **{k: v for k, v in fresh.items() if k != "error"}}
        else:
            read = fresh
        if not opened:
            opened = dict(read)
            if not opened_canvas:
                opened_canvas = str(read.get("canvas") or "")
        read["opened_canvas"] = opened_canvas
        read["opened_shapes"] = opened.get("shapes")
        read["drew"] = drew
        if acted and _goal_reached_heuristic(task, read):
            stop_reason = "done"
            drew = drew or task_kind(task) == "draw"
            break
        if acted and account_task and auth_page(read):
            signup_url = str(read.get("url") or "")
            print(f"[{agent_id}] needs account at {signup_url}", flush=True)
            _miss("needs_account", "needs_account")
            break
        if looping(trace):
            _miss("looping between the same pages")
            break
        model_read = dict(read)
        model_read["nodes"] = _nodes_for_model(
            list(read.get("nodes") or []), skip, allow_auth=account_task and not signed_in, signed_in=signed_in
        )
        model_read["signed_in"] = signed_in
        action = None
        for attempt in range(2):
            try:
                action = await asyncio.wait_for(
                    _model_action(
                        task=task,
                        read=model_read,
                        history=history,
                        changed_nothing=changed_nothing,
                        account_task=account_task,
                        all_nodes=list(read.get("nodes") or []),
                    ),
                    timeout=10 if not acted else 20,
                )
            except asyncio.TimeoutError:
                print(f"[{agent_id}] model action timed out", flush=True)
                action = None
            if isinstance(action, dict):
                break
        if not isinstance(action, dict):
            model_misses += 1
            if model_misses >= 3:
                _miss("model returned no action")
                break
            changed_nothing = True
            history.append("model returned no action")
            continue
        act = str(action.get("act") or "click")
        if os.environ.get("MVP_LOOP_DEBUG"):
            print(f"[{agent_id}] decide {act} {action.get('name')!r} text={action.get('text')!r} why={action.get('reason')!r}", flush=True)
        if act == "blocked":
            model_misses += 1
            if model_misses == 2 and action.get("name"):
                # Slow pages: give the control one more real try.
                skip.discard(str(action.get("name") or "").strip().lower())
            if model_misses >= 4 and await _escape_to_app(page, read, signed_in, escapes):
                model_misses = 0
                skip.clear()
                seed = None
                history.append("reopened the product's home page to get past the stuck screen")
                continue
            if model_misses >= 4:
                _miss("kept choosing a control that does nothing")
                break
            changed_nothing = True
            history.append(
                f"{action.get('name') or 'that control'} was already tried and changed nothing; it is not available now"
            )
            continue
        model_misses = 0
        if act == "done":
            if not acted:
                verdict = False
            else:
                heuristic = _goal_reached_heuristic(task, read)
                verdict = bool(heuristic) if heuristic is not None else await _verify_done(task, read, opened, page)
                if heuristic is None and verdict and _page_key(str(read.get("url") or "")) == _page_key(str(opened.get("url") or "")) and not _observation_changed(opened, read, task=task) and task_kind(task) != "draw":
                    verdict = False
                if not verdict and signed_in and _typed_item_visible(typed, read):
                    # The title the agent typed now shows on the page outside any field.
                    verdict = True
            if verdict:
                stop_reason = "done"
                break
            done_rejects += 1
            if done_rejects >= 3:
                _miss("model said done before the goal was visible")
                break
            changed_nothing = True
            where = "a docs or help page" if docs_page(str(read.get("url") or "")) else "this page"
            history.append(f"done rejected: the goal is not visible on {where}")
            continue
        chosen = str(action.get("name") or "").strip().lower()
        if act == "click" and chosen and chosen in skip:
            changed_nothing = True
            history.append(f"skipped repeat {chosen}")
            continue
        if act == "drag":
            box = _canvas_box(list(read.get("nodes") or []))
            if box:
                action["canvas_x"] = int(box.get("x") or 0)
                action["canvas_y"] = int(box.get("y") or 0)
                action["canvas_w"] = int(box.get("w") or 0)
                action["canvas_h"] = int(box.get("h") or 0)
        label = action_label(action)
        if act == "type" and trace and str(trace[-1].get("action") or "") == label:
            typed_again += 1
            if typed_again >= 3:
                _miss("typed the same text over and over")
                break
            changed_nothing = True
            history.append(f"{label} was just done and the field holds that text; submit it or take the next step")
            continue
        if would_repeat_action(trace, label, read):
            repeats += 1
            if repeats >= 3 and await _escape_to_app(page, read, signed_in, escapes):
                repeats = 0
                skip.clear()
                seed = None
                history.append("reopened the product's home page to get past the stuck screen")
                continue
            if repeats >= 3:
                _miss("repeated an action that changed nothing")
                break
            changed_nothing = True
            history.append(f"{label} already changed nothing; do something else")
            continue
        step_no += 1
        if act == "type" and str(action.get("text") or "").strip():
            typed.append(str(action.get("text")).strip())
        row = _step_from_read(step=step_no, action=label, read=read, thought=str(action.get("reason") or "")[:200])
        row["decision_source"] = "model"
        row["decision"] = {
            "act": act,
            "name": action.get("name"),
            "href": action.get("href"),
            "role": action.get("role"),
            "source": "model",
            "easy": action.get("easy") or "",
            "friction": action.get("friction") or "",
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
            skip.add(chosen)
        except Exception as exc:  # noqa: BLE001
            if browser_dead(exc):
                print(f"[{agent_id}] session ended: {exc!r}", flush=True)
                _miss("session ended")
                break
            print(f"[{agent_id}] action error (continuing): {str(exc)[:160]!r}", flush=True)
            how = f"error:{str(exc)[:120]}"
        acted += 1
        await _wait_for_page(page)
        after = await _fresh_read(page, str(read.get("url") or url))
        if after.get("error") and browser_dead(str(after.get("error"))):
            print(f"[{agent_id}] session ended: {after.get('error')}", flush=True)
            _miss("session ended", "read")
            break
        if not after.get("error"):
            if not account_task and auth_page(after):
                # A public task does not need the login page. Go back and avoid that control.
                skip.add(chosen)
                href = str(action.get("href") or "").lower()
                if href:
                    skip.add(href)
                try:
                    await page.go_back(wait_until="domcontentloaded", timeout=4000)
                except Exception:
                    pass
                await _wait_for_page(page)
                backed = await _fresh_read(page, str(read.get("url") or url))
                if not backed.get("error"):
                    after = backed
            changed = _observation_changed(read, after, task=task)
            if act == "drag":
                before_dark = _canvas_dark(str(read.get("canvas") or ""))
                after_dark = _canvas_dark(str(after.get("canvas") or ""))
                inked = before_dark >= 0 and after_dark >= 0 and abs(after_dark - before_dark) >= 8
                if inked or int(after.get("shapes") or 0) > int(read.get("shapes") or 0):
                    changed = True
                    drew = True
            if act in {"type", "press"} and not str(how).endswith("miss"):
                changed = True
            if downloads:
                changed = True
                after["downloaded"] = downloads[-1]
            if not changed and act == "click":
                # Single-page apps often swap the view a beat later. Look once more.
                try:
                    await page.wait_for_timeout(1000)
                except Exception:
                    pass
                later = await _fresh_read(page, str(read.get("url") or url))
                if not later.get("error") and _observation_changed(read, later, task=task):
                    after = later
                    changed = True
            if changed:
                # A new view: controls skipped on the old one (another "Skip" or
                # "Continue") are fair game again.
                skip.clear()
            if not changed and act in {"click", "type"}:
                skip.add(chosen)
                href = str(action.get("href") or "").lower()
                if href:
                    skip.add(href)
            changed_nothing = not changed
            row["changed"] = changed
            after["opened_canvas"] = opened_canvas
            after["opened_shapes"] = opened.get("shapes")
            after["drew"] = drew
            read = after
            seed = dict(after)  # this read is the next step's read
            if changed and agent_id:
                # Keep the latest frame. If the browser dies later, the report
                # still has the last screen the agent really saw.
                _spawn_last_frame(page, agent_id)
            row["url"] = str(read.get("url") or "")
            row["state_sig"] = {
                "text": str(read.get("text") or "")[:1500],
                "canvas": str(read.get("canvas") or ""),
            }
            row["accessibility_tree"] = format_ax(read.get("nodes") or [])
            row["ax_tree"] = row["accessibility_tree"]
            stamp_published_step(row, task=task, read=read)
            if on_step is not None:
                maybe = on_step(row)
                if asyncio.iscoroutine(maybe):
                    await maybe
        if (
            changed_nothing is False
            and act == "click"
            and account_task
            and _SUBMIT_RE.search(chosen or "")
            and not docs_page(str(read.get("url") or ""))
            and not auth_page(read)
        ):
            # The agent just submitted something. Check the outcome now rather
            # than letting it redo the task.
            if await _verify_done(task, read, opened, page):
                stop_reason = "done"
        logs.append(
            {
                "step": step_no,
                "decision": row.get("decision"),
                "executed": label,
                "how": how,
                "url_after": str(read.get("url") or ""),
            }
        )

    if stop_reason == "done":
        _stamp_observation(trace, read, task=task)
        failed = {"phase": "done", "reason": "task complete", "step": step_no}
    if stop_reason:
        print(f"[{agent_id}] stop reason: {stop_reason}", flush=True)
    if not isinstance(failed, dict):
        failed = {"phase": "act", "reason": "page did not show the goal", "step": step_no}
    return {
        "stop_reason": stop_reason or str(failed.get("reason") or ""),
        "failed": failed,
        "trace": trace,
        "history": history,
        "step_no": step_no,
        "read": read,
        "drew": drew,
        "opened_canvas": opened_canvas,
        "logs": logs,
        "needs_account": stop_reason == "needs_account",
        "signup_url": signup_url,
    }


async def _create_session_or_close(study_id: str | None, timeout: float = 3.5) -> Any:
    """Create one session. If it arrives after the cap, close it so the slot is free."""
    import threading

    from capability.browserbase_client import close_session, create_session, study_session_owner

    loop = asyncio.get_running_loop()
    fut: asyncio.Future[Any] = loop.create_future()

    def _work() -> None:
        try:
            bb = create_session(
                proxies=False,
                keep_alive=True,
                solve_captchas=False,
                advanced_stealth=False,
                owner=study_session_owner(),
                study_id=study_id,
            )
        except Exception as exc:  # noqa: BLE001
            err = exc

            def _fail() -> None:
                if not fut.done():
                    fut.set_exception(err)

            loop.call_soon_threadsafe(_fail)
            return

        def _deliver() -> None:
            if fut.done():
                sid = str(getattr(bb, "id", "") or "")
                if sid:
                    try:
                        close_session(sid)
                    except Exception:
                        pass
                return
            fut.set_result(bb)

        loop.call_soon_threadsafe(_deliver)

    threading.Thread(target=_work, daemon=True).start()
    return await asyncio.wait_for(fut, timeout)


async def _open_agent_session(boot: A11yBoot, url: str) -> tuple[Any, Any, Any, float, float]:
    """A new Browserbase session for this agent only.

    Returns browser, page, the attempt start, and the navigation-commit time.
    The page-open clock starts at goto, not at the Browserbase create call.
    A navigation that does not commit within 4.5s is closed and replaced.
    A create that finishes after its own cap is closed so it cannot hold a slot.
    """
    last = "no browser session"
    for attempt in range(1, 5):
        bb = None
        browser = None
        try:
            try:
                bb = boot.pool.get_nowait()
            except asyncio.QueueEmpty:
                bb = None
            if bb is None:
                try:
                    bb = await _create_session_or_close(
                        getattr(boot.study, "id", None),
                        timeout=12,
                    )
                except Exception as exc:  # noqa: BLE001
                    last = repr(exc)
                    print(f"[a11y] agent create attempt {attempt} replaced: {exc!r}", flush=True)
                    await asyncio.sleep(0.25)
                    continue
            pw = await boot._playwright()
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
            # Creation for the 5s gate is this navigation, after the session exists.
            started = time.time()
            try:
                await page.goto(url, wait_until="commit", timeout=4500)
            except Exception as exc:  # noqa: BLE001
                last = repr(exc)
                print(f"[a11y] agent goto attempt {attempt} replaced: {exc!r}", flush=True)
                await _close_agent_session(browser, bb)
                continue
            opened = time.time()
            if opened - started > 4.5 or opened <= started:
                print(f"[a11y] agent open attempt {attempt} missed 4.5s, replacing", flush=True)
                await _close_agent_session(browser, bb)
                continue
            return bb, browser, page, started, opened
        except Exception as exc:  # noqa: BLE001
            last = repr(exc)
            await _close_agent_session(browser, bb)
            print(f"[a11y] agent session attempt {attempt} replaced: {exc!r}", flush=True)
    raise RuntimeError(last)


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


def _visited(trace: list[dict[str, Any]], start: str, final: str) -> list[str]:
    seen: list[str] = []
    for item in [start] + [str(s.get("url") or "") for s in trace if isinstance(s, dict)] + [final]:
        if item and item not in seen:
            seen.append(item)
    return seen[:40]


def insession_signup_enabled() -> bool:
    """Study agents call signup_in_session on the same page when an account wall appears."""
    return os.environ.get("MVP_INSESSION_SIGNUP", "1").strip().lower() not in {"0", "false", "no", "off"}


def signup_block_label(reason: str) -> str:
    """Plain words for a live signup that did not finish."""
    low = (reason or "").lower()
    if "email_rejected" in low or "rejected" in low:
        return "blocked at signup: throwaway email rejected"
    if "email_timeout" in low:
        return "blocked at signup: no verification email reached the throwaway inbox"
    if "captcha" in low:
        return "blocked at signup: captcha"
    if "inbox" in low:
        return "blocked at signup: could not create a throwaway inbox"
    return f"signup did not finish ({(reason or 'unknown').split(':', 1)[0][:40]})"


_SIGNUP_GATE: dict[str, Any] = {"lock": None, "last": 0.0}


async def _stagger_signup() -> None:
    """Start live signups a few seconds apart; throwaway inbox APIs rate-limit new addresses."""
    gap = float(os.environ.get("MVP_SIGNUP_STAGGER_S") or 3.0)
    if _SIGNUP_GATE["lock"] is None:
        _SIGNUP_GATE["lock"] = asyncio.Lock()
    async with _SIGNUP_GATE["lock"]:
        wait = _SIGNUP_GATE["last"] + gap - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        _SIGNUP_GATE["last"] = time.monotonic()


async def _signup_then_resume(
    page: Any,
    *,
    outcome: dict[str, Any],
    url: str,
    task: str,
    persona: dict[str, Any],
    agent_id: str,
    on_step: Any | None,
    deadline: float | None,
    sess: dict[str, Any],
) -> dict[str, Any] | None:
    """The task hit a login or signup wall. Sign up in this same browser, then resume.

    Uses mvp.signup_in_session when it is installed. Without it the agent
    stops with needs_account, which the report shows as an account wall.
    """
    try:
        from mvp.signup_in_session import signup_in_session  # type: ignore
    except Exception:
        return None
    remaining = (deadline - time.monotonic()) if deadline is not None else 180.0
    if remaining < 45:
        return None
    trace = list(outcome.get("trace") or [])
    step_no = int(outcome.get("step_no") or 0) + 1
    wall = str(outcome.get("signup_url") or (outcome.get("read") or {}).get("url") or url)
    row = {
        "step": step_no,
        "action": "sign up for an account (the task needs one)",
        "url": wall,
        "thought": "account wall",
        "decision_source": "signup",
        "decision": {"act": "signup", "source": "signup"},
    }
    trace.append(row)
    if on_step is not None:
        maybe = on_step(row)
        if asyncio.iscoroutine(maybe):
            await maybe
    sess["signup_status"] = "signing up"
    started = time.time()
    try:
        import inspect

        await _stagger_signup()
        remaining = (deadline - time.monotonic()) if deadline is not None else 240.0
        cap = float(os.environ.get("MVP_SIGNUP_IN_SESSION_TIMEOUT_S") or 220)
        budget = max(30.0, min(cap, remaining - 45))
        kwargs: dict[str, Any] = {"timeout_s": budget, "tag": None}
        params = inspect.signature(signup_in_session).parameters
        if "signup_url" in params:
            kwargs["signup_url"] = wall
        if "on_step" in params and on_step is not None:
            async def _progress(event: Any) -> None:
                # Show each signup move live on this agent's row.
                if not isinstance(event, dict):
                    return
                what = str(event.get("thought") or event.get("status") or "").strip()
                if what:
                    row["action"] = f"signing up: {what}"[:140]
                if event.get("url"):
                    row["url"] = str(event.get("url"))
                maybe = on_step(row)
                if asyncio.iscoroutine(maybe):
                    await maybe

            kwargs["on_step"] = _progress
        result = await asyncio.wait_for(
            signup_in_session(page, url, persona, **kwargs),
            timeout=budget + 10,
        )
    except Exception as exc:  # noqa: BLE001
        result = {"ok": False, "reason": repr(exc)[:160]}
    result = dict(result or {}) if isinstance(result, dict) else {"ok": bool(result)}
    public = {
        "ok": bool(result.get("ok")),
        "reason": str(result.get("reason") or "")[:200],
        "email": str(result.get("email") or "")[:120],
        "seconds": round(time.time() - started, 1),
    }
    sess["signup_status"] = "signed up" if public["ok"] else "signup failed"
    sess["signup"] = public
    row["signup"] = public
    row["action"] = (
        f"signed up as {public['email'] or 'a new user'} in {public['seconds']}s"
        if public["ok"]
        else signup_block_label(public["reason"])
    )
    try:
        row["url"] = str(page.url or wall)
    except Exception:
        pass
    if on_step is not None:
        maybe = on_step(row)
        if asyncio.iscoroutine(maybe):
            await maybe
    if not public["ok"]:
        failed = {"phase": "needs_account", "reason": signup_block_label(public["reason"]), "step": step_no}
        return {**outcome, "trace": trace, "step_no": step_no, "failed": failed, "signup": public}
    resumed = await complete_task_on_page(
        page,
        task=task,
        url=str(getattr(page, "url", "") or url),
        trace=trace,
        history=list(outcome.get("history") or []) + [row["action"]],
        step_no=step_no,
        opened_canvas=str(outcome.get("opened_canvas") or ""),
        on_step=on_step,
        deadline=deadline,
        agent_id=agent_id,
        signed_in=True,
    )
    resumed["signup"] = public
    resumed["logs"] = list(outcome.get("logs") or []) + list(resumed.get("logs") or [])
    return resumed


async def signup_and_resume(
    page: Any,
    *,
    task: str,
    url: str,
    persona: dict[str, Any] | None,
    outcome: dict[str, Any],
    on_step: Any | None = None,
    deadline: float | None = None,
    agent_id: str = "agent",
    sess: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """needs_account -> signup_in_session on this page -> resume signed_in=True.

    Same contract as the signup-branch hook. Uses the richer study-path
    ``_signup_then_resume`` (live progress, stagger, block labels).
    """
    row = sess if isinstance(sess, dict) else {}
    resumed = await _signup_then_resume(
        page,
        outcome=outcome,
        url=url,
        task=task,
        persona=persona or {},
        agent_id=agent_id,
        on_step=on_step,
        deadline=deadline,
        sess=row,
    )
    if resumed is None:
        return {"ok": False, "reason": "signup unavailable or study budget too short"}, outcome
    su = resumed.get("signup") if isinstance(resumed.get("signup"), dict) else dict(row.get("signup") or {})
    return su, resumed


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
    """One Browserbase session for this agent, step 0 from the site's shared read."""
    return await _run_a11y_agent_unlocked(
        boot=boot,
        study_id=study_id,
        agent_id=agent_id,
        url=url,
        task_prompt=task_prompt,
        persona=persona,
        on_step=on_step,
        deadline=deadline,
        site_key=site_key,
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
    site_key: str = "product",
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
    outcome_flags: dict[str, Any] = {}
    try:
        opened_at = None
        try:
            bb, browser, page, created_at, opened_at = await _open_agent_session(boot, url)
        except Exception as exc:  # noqa: BLE001
            print(f"[{agent_id}] session ended: {exc!r}", flush=True)
            stop_reason = "session ended"
            failed = {"phase": "session", "reason": "session ended", "step": 0}
        if page is not None and failed is None and opened_at is not None:
            # First time this agent is visible. created_at_ts is goto start
            # and page_open_at_ts is navigation commit on this agent's page.
            sess["created_at_ts"] = created_at
            sess["page_open_at_ts"] = opened_at
            sess["phase"] = "acting"
            trace = list(sess.get("trace") or trace)
            if trace and isinstance(trace[0], dict):
                trace[0]["page_open_at_ts"] = opened_at
                trace[0]["session_ready_at_ts"] = created_at
            apply_gate_fields(
                sess,
                page_open_at_ts=opened_at,
                session_ready_at_ts=created_at,
                page_url=url,
                accessibility_tree=str(sess.get("accessibility_tree") or "") or "0 document page",
                phase_ms={
                    "session_ready": 0,
                    "page_open": _ms(created_at, opened_at) or 0,
                    "first_action": 0,
                    "final_screenshot": 0,
                },
            )
            # created_at is this attempt's start. page_open is navigation commit.
            # first_action stays unset until a click, type, or scroll is saved.
            sess.pop("first_action_at_ts", None)
            boot.study.live_sessions[agent_id] = sess
            boot._touch()
            # Step 0 is this site's one shared read, taken on the first
            # agent's own page. Never wait on another site and never re-read.
            opening_nodes: list[dict[str, Any]] = []
            initial_read: dict[str, Any] | None = None
            snap = await boot.site_read(site_key, page, url)
            if isinstance(snap, dict) and _host(str(snap.get("url") or "")) == _host(url):
                opening_nodes = [
                    node for node in (snap.get("nodes") or []) if isinstance(node, dict)
                ]
                initial_read = dict(snap)
            trace = list(sess.get("trace") or trace)
            if trace and isinstance(trace[0], dict):
                trace[0]["page_open_at_ts"] = opened_at
                trace[0]["session_ready_at_ts"] = created_at
            sess["page_open_at_ts"] = opened_at
            sess["created_at_ts"] = created_at
            apply_gate_fields(
                sess,
                page_open_at_ts=opened_at,
                session_ready_at_ts=created_at,
                accessibility_tree=format_ax(opening_nodes)
                or str(sess.get("accessibility_tree") or "")
                or "0 document page",
            )
            sess["phase"] = "acting"
            boot.study.live_sessions[agent_id] = sess
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
                opening_nodes=opening_nodes,
                initial_read=initial_read,
            )
            if outcome.get("needs_account") and insession_signup_enabled():
                sess["phase"] = "signing_up"
                boot.study.live_sessions[agent_id] = sess
                _su, outcome = await signup_and_resume(
                    page,
                    task=task_prompt,
                    url=url,
                    persona=persona,
                    outcome=outcome,
                    on_step=on_step,
                    deadline=deadline,
                    agent_id=agent_id,
                    sess=sess,
                )
                sess["signup"] = outcome.get("signup") or {"ok": False, "reason": _su.get("reason")}
                sess["phase"] = "acting"
            stop_reason = str(outcome.get("stop_reason") or "")
            outcome_flags = {"needs_account": outcome.get("needs_account"), "signup": outcome.get("signup")}
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
            dest = MVP_RUNS_DIR / study_id / agent_id / "screenshots"
            dest.mkdir(parents=True, exist_ok=True)
            path = dest / "final.png"
            t_shot = time.perf_counter()
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=6000)
            except Exception:
                pass
            try:
                await page.screenshot(path=str(path), full_page=False, timeout=8000)
                shot_ms = int(round((time.perf_counter() - t_shot) * 1000))
                from mvp.opening_shot import upload_final_verified

                # Keep the URL only after GCS returns the same PNG bytes.
                if await asyncio.to_thread(upload_final_verified, study_id, agent_id, path):
                    shot_url = f"/api/studies/{study_id}/agents/{agent_id}/screenshots/final.png"
                else:
                    print(f"[{agent_id}] final PNG did not round-trip through GCS", flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f"[{agent_id}] final capture failed: {exc!r}", flush=True)
                frame = _LAST_FRAME.get(agent_id)
                if frame and not shot_url:
                    try:
                        path.write_bytes(frame)
                        from mvp.opening_shot import upload_final_verified

                        if await asyncio.to_thread(upload_final_verified, study_id, agent_id, path):
                            shot_url = f"/api/studies/{study_id}/agents/{agent_id}/screenshots/final.png"
                            print(f"[{agent_id}] final.png is the last frame before the browser ended", flush=True)
                    except Exception as exc2:  # noqa: BLE001
                        print(f"[{agent_id}] last-frame fallback failed: {exc2!r}", flush=True)
                if not shot_url:
                    failed = failed or {
                        "phase": "final_screenshot",
                        "reason": "final capture failed",
                        "step": step_no,
                    }
            if shot_url and trace:
                trace[-1]["screenshot_url"] = shot_url
                trace[-1]["final_screenshot_url"] = shot_url
        _LAST_FRAME.pop(agent_id, None)

        # Report where the agent really ended. Replacing an off-host final URL
        # with the start URL hid docs/subdomain detours from the judge.
        final_url = str(read.get("url") or url)
        ax = format_ax(read.get("nodes") or []) or str(sess.get("accessibility_tree") or "") or "0 document page"
        final_dom = str(read.get("text") or "")[:1500] or ax
        if not isinstance(failed, dict) or not str(failed.get("phase") or "").strip():
            if stop_reason == "done" or goal_visible(task_prompt, read):
                failed = {"phase": "done", "reason": "task complete", "step": step_no}
            else:
                failed = {"phase": "act", "reason": "page did not show the goal", "step": step_no}
        phase_ms = dict(sess.get("phase_ms") or {})
        phase_ms["page_open"] = _ms(sess.get("created_at_ts"), sess.get("page_open_at_ts")) or int(
            phase_ms.get("page_open") or 0
        )
        phase_ms["first_action"] = _ms(sess.get("page_open_at_ts"), sess.get("first_action_at_ts")) or 0
        phase_ms["final_screenshot"] = shot_ms
        phase_ms["final_screenshot_ms"] = shot_ms
        if shot_url and trace:
            stamp_published_step(
                trace[-1],
                task=task_prompt,
                read=read,
                screenshot_url=shot_url,
            )

        result = {
            "agent_id": agent_id,
            "persona_id": persona.get("id"),
            "task_id": agent_id,
            "completed": stop_reason == "done",
            "final_url": final_url,
            "final_dom": final_dom,
            "visited_urls": _visited(trace, url, final_url),
            "finished_at_ts": time.time(),
            "needs_account": bool(outcome_flags.get("needs_account")),
            "signup": outcome_flags.get("signup") or {},
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
        # The harness reads the live row. Copy the gate fields onto it before
        # this agent returns, including a failed open that never got a click.
        if sess.get("created_at_ts") and sess.get("page_open_at_ts"):
            apply_gate_fields(sess, **{k: result.get(k) for k in GATE_FIELDS})
            sess["trace"] = trace
            sess["final_screenshot_url"] = shot_url
            sess["final_screenshot"] = shot_url
            sess["failed_step"] = failed
            boot.study.live_sessions[agent_id] = sess
            boot._touch()
        return result
    finally:
        await _close_agent_session(browser, bb)
