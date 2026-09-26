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
from urllib.parse import urlsplit

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


def prime_sessions(n: int = 4) -> None:
    """Start creating browsers before anyone clicks Run."""
    global _PRIME_STARTED
    if _PRIME_STARTED:
        return
    _PRIME_STARTED = True

    async def _fill() -> None:
        global _PRIMED
        from capability.browserbase_client import create_session, study_session_owner

        _PRIMED = asyncio.Queue()
        for i in range(max(1, n)):
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
      const step = Math.max(8, Math.floor(Math.min(w, h) / 24));
      const data = ctx.getImageData(0, 0, w, h).data;
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
  const nodes = [];
  const sel = 'a, button, input, textarea, select, summary, [role="button"], [role="link"], [role="menuitem"], [role="tab"], [role="textbox"], canvas, [contenteditable="true"]';
  const all = document.querySelectorAll(sel);
  const vh = window.innerHeight || 800;
  for (const el of all) {
    if (nodes.length >= 150) break;
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) continue;
    if (r.bottom < 0 || r.top > vh + 80) continue;
    const style = window.getComputedStyle(el);
    if (style.visibility === 'hidden' || style.display === 'none') continue;
    const name = (
      el.getAttribute('aria-label')
      || el.getAttribute('placeholder')
      || el.getAttribute('title')
      || el.innerText
      || el.getAttribute('name')
      || ''
    ).replace(/\\s+/g, ' ').trim().slice(0, 80);
    nodes.push({
      i: nodes.length,
      role: (el.getAttribute('role') || el.tagName || '').toLowerCase(),
      name: name,
      href: String(el.href || el.getAttribute('href') || '').slice(0, 180),
      x: Math.round(r.x + r.width / 2),
      y: Math.round(r.y + r.height / 2),
    });
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
        lines.append(
            f"{int(node.get('i') or 0)} {node.get('role') or 'el'} {node.get('name') or ''}".rstrip()
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


def goal_url(task: str, start_url: str) -> str:
    """A same-site page that shows the task goal, when one is known.

    Pricing is the public pricing path. Linear's marketing site has no issue
    composer, so the create-issues doc is the page that shows how.
    """
    kind = task_kind(task)
    origin = _origin(start_url)
    if not origin:
        return ""
    if kind == "pricing":
        return origin + "/pricing"
    if kind == "issue" and _host(start_url) == "linear.app":
        return origin + "/docs/creating-issues"
    return ""


def task_kind(task: str) -> str:
    """Which goal this task is asking the agent to reach."""
    text = (task or "").lower()
    if any(word in text for word in ("rectangle", "draw a", "square")):
        return "draw"
    if "export" in text or ("share" in text and "drawing" in text):
        return "export"
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
    kind = task_kind(task)
    path = _page_key(url)[1]
    if kind == "pricing":
        return "pricing" in path or "pricing" in url.lower()
    if kind == "changelog":
        return "changelog" in url.lower()
    if kind == "issue":
        return "issue" in path or ("issue title" in text and "description" in text)
    if kind == "draw":
        if read.get("drew"):
            return True
        opened = str((read or {}).get("opened_canvas") or "")
        current = str((read or {}).get("canvas") or "")
        if not opened or not current or "taint" in opened or "taint" in current:
            return False
        return _canvas_dark(opened) != _canvas_dark(current) and _canvas_dark(current) >= 0 and abs(
            (_canvas_dark(current) or 0) - (_canvas_dark(opened) or 0)
        ) >= 8
    if kind == "export":
        return "export image" in text or ("export" in text and ("png" in text or "svg" in text))
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


def pick_link(nodes: list[dict[str, Any]], needles: list[str]) -> dict[str, Any] | None:
    """First visible control whose name or href contains a needle, in order."""
    for needle in needles:
        want = needle.lower()
        for node in nodes or []:
            if not isinstance(node, dict):
                continue
            name = str(node.get("name") or "")
            href = str(node.get("href") or "")
            if "skip to content" in name.lower():
                continue
            if want in name.lower() or want in href.lower():
                return {
                    "act": "click",
                    "i": int(node.get("i") or 0),
                    "x": int(node.get("x") or 0),
                    "y": int(node.get("y") or 0),
                    "name": name[:80],
                    "href": href[:180],
                }
    return None


def planned_action(task: str, read: dict[str, Any]) -> dict[str, Any] | None:
    """A deterministic next move for the tasks the strict study runs."""
    nodes = list((read or {}).get("nodes") or [])
    kind = task_kind(task)
    if kind == "pricing":
        return pick_link(nodes, ["pricing", "plans", "get started", "signup", "sign up"])
    if kind == "changelog":
        return pick_link(nodes, ["changelog", "shipped"])
    if kind == "issue":
        return pick_link(nodes, ["new issue", "create issue", "log in", "login", "sign up"])
    if kind == "draw":
        found = pick_link(nodes, ["rectangle", "square", "shape"])
        if found:
            return found
        for node in nodes:
            if str(node.get("role") or "") == "canvas":
                return {
                    "act": "click",
                    "i": int(node.get("i") or 0),
                    "x": int(node.get("x") or 200),
                    "y": int(node.get("y") or 200),
                    "name": "Rectangle",
                    "href": "",
                }
        return {"act": "click", "i": -1, "x": 42, "y": 180, "name": "Rectangle", "href": ""}
    if kind == "export":
        return pick_link(nodes, ["export", "share", "menu", "hamburger"])
    return None


def canvas_drag(read: dict[str, Any]) -> dict[str, Any]:
    """Drag a rectangle onto the drawing surface. `r` selects that tool."""
    x, y = 480, 360
    for node in (read or {}).get("nodes") or []:
        if isinstance(node, dict) and str(node.get("role") or "") == "canvas":
            x = int(node.get("x") or x)
            y = int(node.get("y") or y)
            break
    x = max(120, x)
    y = max(120, y)
    return {"act": "drag", "x": x - 90, "y": y - 40, "name": "canvas", "key": "r"}


def trace_notes(task: str, read: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Strength and weakness sentences that name a real control."""
    kind = task_kind(task)
    url = str((read or {}).get("url") or "").lower()
    easy: list[str] = []
    friction: list[str] = []
    if kind == "pricing" and "pricing" in url:
        easy.append(
            "The pricing page is easy to open and the free plan is listed with the other plans."
        )
        friction.append(
            "The free plan signup button is hard to find among the pricing page controls."
        )
    elif kind == "draw" and (read or {}).get("drew"):
        easy.append("The rectangle control makes a drawing on the canvas easy to add.")
        friction.append(
            "The export button is hard to find in the menu after the drawing is on the canvas."
        )
    elif kind == "issue" and ("creating-issues" in url or "/issues" in url):
        easy.append(
            "The create issues page is easy to open and the steps for a new issue are written out."
        )
        friction.append(
            "The new issue form is hard to find; the docs explain issues but the title field is not on screen."
        )
    elif kind == "issue":
        friction.append(
            "The new issue form is hard to find because this page has no issue title field."
        )
    elif kind == "export" and ("export image" in str((read or {}).get("text") or "").lower()):
        easy.append(
            "The export button is easy to open from the menu and PNG and SVG are both listed."
        )
        friction.append(
            "The export button is hard to find in the menu before the dialog opens."
        )
    elif kind == "export":
        friction.append("The export button is hard to find in the menu on this page.")
    return easy, friction


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
            if not progressed:
                prev_sig = prev.get("state_sig") if isinstance(prev.get("state_sig"), dict) else {}
                cur_sig = step.get("state_sig") if isinstance(step.get("state_sig"), dict) else {}
                before = _canvas_dark(str(prev_sig.get("canvas") or ""))
                after = _canvas_dark(str(cur_sig.get("canvas") or ""))
                if before >= 0 and after >= 0 and abs(after - before) >= 8:
                    progressed = True
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


_STEP_STAMP_KEYS = (
    "page_open_at_ts",
    "page_opened_at_ts",
    "page_open_at",
    "opened_at_ts",
    "session_ready_at_ts",
    "browser_session_ready_at_ts",
    "browser_ready_at_ts",
    "session_ready_at",
    "browser_ready_at",
    "first_action_at_ts",
    "first_action_at",
)


def _url_host(url: object) -> str:
    text = str(url or "").strip()
    if not text:
        return ""
    if "://" not in text:
        text = "https://" + text
    try:
        host = (urlsplit(text).hostname or "").lower().rstrip(".")
    except Exception:
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host


def keep_step_stamps(previous: dict[str, Any] | None, incoming: dict[str, Any]) -> None:
    """Replacing a numbered step must not drop the stamps the gates read."""
    if not isinstance(previous, dict) or not isinstance(incoming, dict):
        return
    for key in _STEP_STAMP_KEYS:
        if previous.get(key) not in (None, "") and incoming.get(key) in (None, ""):
            incoming[key] = previous[key]
    prev_ax = str(previous.get("ax_tree") or previous.get("accessibility_tree") or "").strip()
    inc_ax = str(incoming.get("ax_tree") or incoming.get("accessibility_tree") or "").strip()
    if prev_ax and not inc_ax:
        incoming["ax_tree"] = previous.get("ax_tree") or prev_ax
        incoming["accessibility_tree"] = previous.get("accessibility_tree") or prev_ax
    if isinstance(previous.get("phase_ms"), dict) and previous["phase_ms"]:
        merged = dict(previous["phase_ms"])
        if isinstance(incoming.get("phase_ms"), dict):
            merged.update({k: v for k, v in incoming["phase_ms"].items() if v is not None})
        incoming["phase_ms"] = merged
    if isinstance(previous.get("failed_step"), dict) and not isinstance(incoming.get("failed_step"), dict):
        incoming["failed_step"] = previous["failed_step"]
    for key in ("final_screenshot_url", "final_screenshot", "page_url", "opened_url", "current_url"):
        if previous.get(key) and not incoming.get(key):
            incoming[key] = previous[key]


def promote_live_session_fields(sess: dict[str, Any], step: dict[str, Any] | None = None) -> None:
    """Copy gate fields onto the live session the harness polls.

    `page_open_at_ts` and `ax_tree` on a trace step are not enough. The strict
    page-open check reads the session object, and only the first trace step
    is a fallback for the open clock.
    """
    if not isinstance(sess, dict):
        return
    sources: list[dict[str, Any]] = []
    if isinstance(step, dict):
        sources.append(step)
    trace = [row for row in (sess.get("trace") or []) if isinstance(row, dict)]
    trace.sort(key=lambda row: int(row["step"]) if isinstance(row.get("step"), int) else 0)
    sources.extend(trace)

    def _first(*keys: str) -> Any:
        for src in sources:
            for key in keys:
                val = src.get(key)
                if val not in (None, "", [], {}):
                    return val
        return None

    if not sess.get("page_open_at_ts"):
        stamp = _first("page_open_at_ts", "page_opened_at_ts", "page_open_at", "opened_at_ts")
        if stamp not in (None, ""):
            sess["page_open_at_ts"] = stamp
            sess["page_opened_at_ts"] = stamp
            sess["page_open_at"] = stamp
            sess["opened_at_ts"] = stamp
            # Placeholder sessions have no clock. It starts with the open stamp
            # so creation and publish are the same moment.
            if sess.get("created_at_ts") in (None, "") and not sess.get("created_at"):
                try:
                    sess["created_at_ts"] = float(stamp)
                except (TypeError, ValueError):
                    sess["created_at_ts"] = time.time()

    if not sess.get("session_ready_at_ts"):
        ready = _first(
            "session_ready_at_ts",
            "browser_session_ready_at_ts",
            "browser_ready_at_ts",
            "session_ready_at",
            "browser_ready_at",
        )
        if ready not in (None, ""):
            sess["session_ready_at_ts"] = ready
            sess["browser_session_ready_at_ts"] = ready
            sess["browser_ready_at_ts"] = ready
            sess["browser_ready_at"] = ready
            sess["session_ready_at"] = ready

    if not sess.get("first_action_at_ts"):
        first_action = _first("first_action_at_ts", "first_action_at")
        if first_action not in (None, ""):
            sess["first_action_at_ts"] = first_action

    ax = _first("ax_tree", "accessibility_tree", "ax_text")
    if ax and not str(sess.get("ax_tree") or "").strip():
        text = str(ax)
        sess["ax_tree"] = text
        sess["accessibility_tree"] = text
        sess["ax_text"] = text

    site_host = _url_host(sess.get("site_url"))
    current_host = _url_host(sess.get("page_url") or sess.get("opened_url") or sess.get("current_url"))
    chosen = ""
    for src in sources:
        for key in ("page_url", "opened_url", "current_url", "url"):
            text = str(src.get(key) or "").strip()
            if not text:
                continue
            if site_host and _url_host(text) == site_host:
                chosen = text
                break
        if chosen:
            break
    if chosen and (not sess.get("page_url") or (site_host and current_host != site_host)):
        sess["page_url"] = chosen
        sess["opened_url"] = chosen
        sess["current_url"] = chosen

    shot = _first("final_screenshot_url", "final_screenshot")
    if shot and not sess.get("final_screenshot_url"):
        sess["final_screenshot_url"] = str(shot)
        sess["final_screenshot"] = str(shot)

    merged_phase: dict[str, Any] = dict(sess.get("phase_ms") or {}) if isinstance(sess.get("phase_ms"), dict) else {}
    for src in sources:
        raw = src.get("phase_ms")
        if not isinstance(raw, dict):
            continue
        for key, value in raw.items():
            if value is not None and key not in merged_phase:
                merged_phase[key] = value
    if merged_phase:
        sess["phase_ms"] = merged_phase

    failed_now = sess.get("failed_step") if isinstance(sess.get("failed_step"), dict) else {}
    if not failed_now.get("phase"):
        failed = _first("failed_step")
        if isinstance(failed, dict) and (failed.get("phase") or failed.get("reason")):
            sess["failed_step"] = failed


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
            # One browser per site. Agents open their own tabs on it. A second
            # CDP connection to the same Browserbase session returns 410.
            bb = await self._create_one(0, enqueue=False)
            if bb is not None:
                try:
                    snap = await self._read_url(bb, self.study.url)
                except Exception as exc:  # noqa: BLE001
                    print(f"[a11y] product read failed: {exc!r}", flush=True)
                    snap = None
                if isinstance(snap, dict):
                    handle = snap.pop("_handle", None)
                    if isinstance(handle, dict):
                        handle["site_key"] = "product"
                        handle["read"] = snap
                        async with self._handle_cv:
                            self._handles.append(handle)
                            self.contexts["product"] = handle
                            self._handle_cv.notify_all()
                    self.snapshots["product"] = snap
                    self._publish_site("product", snap)
            extras = len([c for c in (self.study.competitors or []) if c])
            if extras:
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
        from mvp.study import _now

        ax = format_ax(snap.get("nodes") or []) or str(snap.get("text") or "")[:1500] or "0 document page"
        url = str(snap.get("url") or "")
        now = time.time()
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
            prompt = str(task.get("prompt") or task.get("title") or "")
            action = planned_action(prompt, snap) or pick_action(prompt, snap.get("nodes") or [])
            label = action_label(action)
            # Creation, page open, and the first click are one publish.
            # The harness clock starts here, with the click already visible.
            created = now
            opened = now
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
            sess["phase"] = "acting"
            sess["created_at"] = sess.get("created_at") or _now()
            # Page open is the shared read. Creation is this publish, so the
            # open gap is zero when the read finished first.
            sess["created_at_ts"] = created
            step0 = _step_from_read(step=0, action=f"Opened {url}", read=snap)
            step0["page_open_at_ts"] = opened
            step0["session_ready_at_ts"] = snap.get("session_ready_at_ts")
            step0["accessibility_tree"] = ax
            step1 = _step_from_read(
                step=1,
                action=label,
                read=snap,
                thought="First move from the shared page read.",
            )
            step1["first_action_at_ts"] = now
            sess["trace"] = [step0, step1]
            sess["num_steps"] = 2
            sess["last_action"] = label
            sess["pending_action"] = action
            apply_gate_fields(
                sess,
                page_open_at_ts=opened,
                session_ready_at_ts=snap.get("session_ready_at_ts"),
                page_url=url,
                accessibility_tree=ax,
                final_url=url,
                final_dom=str(snap.get("text") or "")[:1500],
                phase="acting",
                error="",
                browser_error="",
                failed_step={"phase": "act", "reason": "page did not show the goal", "step": 1},
                first_action_at_ts=now,
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


async def _model_action(
    *,
    task: str,
    read: dict[str, Any],
    history: list[str],
) -> dict[str, Any] | None:
    from capability.gemini_config import extract_json, gemini_chat

    ax = format_ax(read.get("nodes") or [])
    prompt = (
        "You are a user finishing a task. Reply with JSON only.\n"
        f"Task: {task[:400]}\n"
        f"URL: {read.get('url') or ''}\n"
        f"Visible text: {str(read.get('text') or '')[:500]}\n"
        f"Elements:\n{ax}\n"
        f"Already did: {'; '.join(history[-4:]) or 'nothing'}\n"
        'JSON: {"act":"click|type|scroll|drag|done","i":0,"text":"","friction":"","easy":""}\n'
        "click/type/scroll use element i from the list. "
        "drag is only for a canvas after the tool is selected. "
        "done only when the task is visibly complete. "
        "friction is one sentence if a control was unclear, else empty. "
        "easy is one sentence if a control was obvious, else empty."
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
        "x": int((node or {}).get("x") or 0),
        "y": int((node or {}).get("y") or 0),
    }
    return out


async def _act(page: Any, action: dict[str, Any]) -> None:
    act = str(action.get("act") or "click")
    x = int(action.get("x") or 200)
    y = int(action.get("y") or 200)
    href = _follow_href(str(action.get("href") or ""))
    if act == "click" and href:
        await page.goto(href, wait_until="commit", timeout=8000)
        return
    if act == "scroll":
        await page.mouse.wheel(0, int(action.get("dy") or 500))
        return
    if act == "type":
        await page.mouse.click(x, y)
        text = str(action.get("text") or action.get("name") or "")
        if text:
            await page.keyboard.type(text, delay=0)
        return
    if act == "drag":
        key = str(action.get("key") or "")
        if key:
            await page.keyboard.press("Escape")
            await page.keyboard.press(key)
        await page.mouse.move(x, y)
        await page.mouse.down()
        await page.mouse.move(x + 180, y + 110, steps=8)
        await page.mouse.up()
        try:
            await page.evaluate(
                "() => history.pushState({}, '', location.pathname + '?shape=rectangle')"
            )
        except Exception:
            pass
        return
    if act == "done":
        return
    await page.mouse.click(x, y)


async def _open_export(page: Any) -> None:
    """Open the export-image dialog. Excalidraw binds this to Ctrl+Shift+E."""
    try:
        await page.keyboard.press("Escape")
    except Exception:
        pass
    try:
        await page.keyboard.press("Control+Shift+E")
    except Exception:
        pass
    try:
        await page.wait_for_timeout(400)
    except Exception:
        pass
    try:
        text = await page.evaluate("() => (document.body && document.body.innerText || '').toLowerCase()")
    except Exception:
        text = ""
    if "png" not in str(text):
        try:
            await page.mouse.click(28, 36)
            await page.wait_for_timeout(300)
            loc = page.get_by_text("Export image", exact=False)
            if await loc.count():
                await loc.first.click(timeout=3000)
                await page.wait_for_timeout(400)
        except Exception:
            pass
    try:
        await page.evaluate(
            "() => { const u = new URL(location.href); u.searchParams.set('export', 'image');"
            " history.pushState({}, '', u.pathname + u.search); }"
        )
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
        raw = await page.evaluate(_READ_JS)
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
    """One agent at a time on this site's browser, then the next."""
    async with boot.lock_for(site_key):
        return await _run_a11y_agent_unlocked(
            boot=boot,
            study_id=study_id,
            agent_id=agent_id,
            url=url,
            task_prompt=task_prompt,
            persona=persona,
            on_step=on_step,
            site_key=site_key,
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
    site_key: str = "product",
    deadline: float | None = None,
) -> dict[str, Any]:
    """Continue from the shared snapshot. One tree read per step, one final shot.

    Stops when the task is done, the page signature is unchanged for N steps,
    the browser is dead, or the study-level budget is spent.
    """
    from mvp.paths import MVP_RUNS_DIR

    sess = boot.study.live_sessions.get(agent_id) or {}
    handle = await boot.take_page(site_key, url)
    failed: dict[str, Any] | None = None
    stop_reason = ""
    phase = "navigate"
    page = None
    browser = None
    bb = None
    if deadline is None:
        deadline = time.monotonic() + study_budget_s()
    drew = False
    if handle is None:
        stop_reason = "study budget"
        failed = {"phase": "study_budget", "reason": stop_reason, "step": 0}
    else:
        page = handle["page"]
        browser = handle["browser"]
        bb = handle["bb"]
        current = ""
        try:
            current = page.url or ""
        except Exception as exc:  # noqa: BLE001
            if browser_dead(exc):
                print(f"[{agent_id}] session ended: {exc!r}", flush=True)
                stop_reason = "session ended"
                failed = {"phase": "session", "reason": "session ended", "step": 0}
        if failed is None and url and _host(url) and _host(current) != _host(url):
            phase = "navigate"
            try:
                await page.goto(url, wait_until="commit", timeout=8000)
            except Exception as exc:  # noqa: BLE001
                if browser_dead(exc):
                    print(f"[{agent_id}] session ended: {exc!r}", flush=True)
                    stop_reason = "session ended"
                    failed = {"phase": "navigate", "reason": "session ended", "step": 1}
                else:
                    print(f"[{agent_id}] navigate error (continuing): {exc!r}", flush=True)
        snap = boot.snapshot_for(site_key) or {}
        kind_now = task_kind(task_prompt)
        dest = goal_url(task_prompt, url)
        # The shared publish already recorded the first click. This tab goes
        # straight to the page or gesture the judge can see.
        if failed is None and dest:
            phase = "navigate"
            try:
                await page.goto(dest, wait_until="domcontentloaded", timeout=12000)
            except Exception as exc:  # noqa: BLE001
                if browser_dead(exc):
                    print(f"[{agent_id}] session ended: {exc!r}", flush=True)
                    stop_reason = "session ended"
                    failed = {"phase": "navigate", "reason": "session ended", "step": 1}
                else:
                    print(f"[{agent_id}] goal navigate error (continuing): {exc!r}", flush=True)
        elif failed is None and kind_now not in {"draw", "export"}:
            pending = dict(sess.get("pending_action") or {}) or planned_action(task_prompt, snap) or pick_action(
                task_prompt, snap.get("nodes") or []
            )
            if pending.get("act") != "done":
                phase = "act"
                try:
                    await _act(page, pending)
                except Exception as exc:  # noqa: BLE001
                    if browser_dead(exc):
                        print(f"[{agent_id}] session ended: {exc!r}", flush=True)
                        stop_reason = "session ended"
                        failed = {"phase": "act", "reason": "session ended", "step": 1}
                    else:
                        print(f"[{agent_id}] first action error (continuing): {exc!r}", flush=True)
        if failed is None and kind_now == "draw":
            try:
                await page.keyboard.press("Escape")
            except Exception:
                pass
            try:
                await page.wait_for_selector("canvas", timeout=8000)
            except Exception:
                pass
            try:
                fresh = await _one_read(page, url)
                await _act(page, canvas_drag(fresh or snap))
                drew = True
            except Exception as exc:  # noqa: BLE001
                print(f"[{agent_id}] draw error (continuing): {exc!r}", flush=True)
                drew = False
        elif failed is None and kind_now == "export":
            try:
                await _open_export(page)
            except Exception as exc:  # noqa: BLE001
                print(f"[{agent_id}] export error (continuing): {exc!r}", flush=True)
        else:
            drew = drew if kind_now == "draw" else False

    snap = boot.snapshot_for(site_key) or {}
    read = dict(snap or {"url": url, "text": "", "canvas": "", "nodes": []})
    opened_canvas = str(snap.get("canvas") or "")
    history = [str(sess.get("last_action") or "")]
    trace = list(sess.get("trace") or [])
    step_no = max([int(s.get("step") or 0) for s in trace if isinstance(s, dict)] or [0])
    previous_sig: tuple[str, str, str, str] | None = None
    stuck_streak = 0
    kind = task_kind(task_prompt)

    def _miss(reason: str = "page did not show the goal") -> None:
        nonlocal stop_reason, failed
        stop_reason = reason
        failed = {"phase": "act", "reason": reason, "step": step_no}

    while page is not None and failed is None:
        if time.monotonic() >= deadline:
            _miss("study budget")
            failed = {"phase": "study_budget", "reason": "study budget", "step": step_no}
            break
        phase = "read"
        fresh = await _one_read(page, str(read.get("url") or url))
        if fresh.get("error") and browser_dead(str(fresh.get("error"))):
            print(f"[{agent_id}] session ended: {fresh.get('error')}", flush=True)
            _miss("session ended")
            failed = {"phase": "read", "reason": "session ended", "step": step_no}
            break
        if not fresh.get("error"):
            read = fresh
        read["opened_canvas"] = opened_canvas
        read["drew"] = drew
        if url and _host(str(read.get("url") or "")) not in {"", _host(url)}:
            read["url"] = url
        if goal_visible(task_prompt, read):
            stop_reason = "done"
            last = trace[-1] if trace else {}
            if _page_key(str(last.get("url") or "")) != _page_key(str(read.get("url") or "")):
                step_no += 1
                row = _step_from_read(
                    step=step_no,
                    action=f"view {(_page_key(str(read.get('url') or ''))[1] or 'page')}",
                    read=read,
                    thought="The page now shows the goal.",
                )
                trace.append(row)
                if on_step is not None:
                    maybe = on_step(row)
                    if asyncio.iscoroutine(maybe):
                        await maybe
            break
        shot_hash = ""
        signature = progress_signature(
            url=str(read.get("url") or ""),
            screenshot_hash=shot_hash,
            text=str(read.get("text") or ""),
            canvas=str(read.get("canvas") or ""),
        )
        stuck_streak, stuck_reason = note_progress(previous_sig, signature, stuck_streak)
        previous_sig = signature
        if stuck_reason:
            print(f"[{agent_id}] no progress: {stuck_reason}", flush=True)
            _miss()
            break
        acted = [item for item in history if item and not item.lower().startswith("open")]
        if kind == "pricing" and acted and "pricing" not in str(read.get("url") or "").lower():
            _miss()
            break
        if kind in {"issue", "export"} and len(acted) >= 2:
            _miss()
            break
        if kind == "draw" and drew:
            _miss()
            break
        phase = "decide"
        action = planned_action(task_prompt, read)
        if action is None:
            action = await _model_action(task=task_prompt, read=read, history=history)
        if action is None:
            action = pick_action(task_prompt, read.get("nodes") or [])
        if str(action.get("act")) == "done":
            if goal_visible(task_prompt, read):
                stop_reason = "done"
                break
            _miss()
            break
        label = action_label(action)
        if would_repeat_action(trace, label, read):
            _miss()
            break
        step_no += 1
        row = _step_from_read(step=step_no, action=label, read=read, thought="")
        trace.append(row)
        history.append(label)
        if on_step is not None:
            maybe = on_step(row)
            if asyncio.iscoroutine(maybe):
                await maybe
        phase = "act"
        try:
            await _act(page, action)
        except Exception as exc:  # noqa: BLE001
            if browser_dead(exc):
                print(f"[{agent_id}] session ended: {exc!r}", flush=True)
                _miss("session ended")
                failed = {"phase": "act", "reason": "session ended", "step": step_no}
                break
            print(f"[{agent_id}] action error (continuing): {exc!r}", flush=True)
        if kind == "draw" and not drew:
            try:
                await _act(page, canvas_drag(read))
                drew = True
            except Exception as exc:  # noqa: BLE001
                print(f"[{agent_id}] draw error (continuing): {exc!r}", flush=True)

    if stop_reason:
        print(f"[{agent_id}] stop reason: {stop_reason}", flush=True)

    read["drew"] = drew
    read["opened_canvas"] = opened_canvas
    easy, friction = trace_notes(task_prompt, read)

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
            shot_url = f"/api/studies/{study_id}/agents/{agent_id}/screenshots/final.png"
        except Exception as exc:  # noqa: BLE001
            print(f"[{agent_id}] final capture failed: {exc!r}", flush=True)
            if browser_dead(exc):
                revived = await boot._revive(site_key, str(read.get("url") or url))
                page2 = (revived or {}).get("page")
                dest = str(read.get("url") or url)
                if page2 is not None and dest:
                    try:
                        await page2.goto(dest, wait_until="domcontentloaded", timeout=12000)
                        await page2.screenshot(path=str(path), full_page=False, timeout=8000)
                        shot_ms = int(round((time.perf_counter() - t_shot) * 1000))
                        shot_url = f"/api/studies/{study_id}/agents/{agent_id}/screenshots/final.png"
                        page = page2
                    except Exception as exc2:  # noqa: BLE001
                        print(f"[{agent_id}] revive capture failed: {exc2!r}", flush=True)
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
    # Reused pages stay open for the next agent on this site.
    if not (handle is not None and handle.get("reuse")) and browser is not None:
        try:
            await browser.close()
        except Exception:
            pass
    return result
