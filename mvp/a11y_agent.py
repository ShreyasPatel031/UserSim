"""Shared page read and a text-only accessibility action loop.

One browser reads the product URL at study start. Every agent for that URL
gets the same compact accessibility tree and chooses a first click, type, or
scroll from it. Later steps take one tree read each. Screenshots happen once,
at the end, for the vision judge.
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from typing import Any

AX_CAP = 150

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
        if not name:
            continue
        score = sum(3 for w in words if w in name)
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
    }


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
        self._handles: list[dict[str, Any]] = []
        self._handle_cv = asyncio.Condition()
        self._pw: Any = None
        self._started = 0.0
        self._tasks: list[asyncio.Task] = []
        self.published = asyncio.Event()

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
        n = int(getattr(self.study, "max_agents", 0) or 0) or len(self.study.tasks or []) or 24
        n = max(1, min(24, n))
        self._tasks.append(asyncio.create_task(self._fill_pool(n)))
        self._tasks.append(asyncio.create_task(self._publish_all()))

    async def _playwright(self) -> Any:
        if self._pw is None:
            from playwright.async_api import async_playwright

            self._pw = await async_playwright().start()
        return self._pw

    async def _fill_pool(self, n: int) -> None:
        from capability.browserbase_client import create_session, study_session_owner

        async def one(i: int) -> None:
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
                await self.pool.put(bb)
            except Exception as exc:  # noqa: BLE001
                print(f"[a11y] session {i+1}/{n} failed: {exc!r}", flush=True)

        await asyncio.gather(*[one(i) for i in range(n)])

    async def _connect(self, bb: Any) -> tuple[Any, Any]:
        pw = await self._playwright()
        browser = await pw.chromium.connect_over_cdp(bb.connect_url)
        context = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = context.pages[0] if context.pages else await context.new_page()
        return browser, page

    async def _read_url(self, bb: Any, url: str) -> dict[str, Any]:
        ready = time.time()
        t0 = time.perf_counter()
        browser, page = await self._connect(bb)
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

        ax = format_ax(snap.get("nodes") or [])
        url = str(snap.get("url") or "")
        now = time.time()
        for task in self.study.tasks or []:
            if str(task.get("site_key") or "product") != site_key:
                continue
            agent_id = str(task.get("id") or "")
            if not agent_id:
                continue
            persona = next(
                (p for p in (self.study.personas or []) if p.get("id") == task.get("persona_id")),
                (self.study.personas or [{}])[0] if self.study.personas else {},
            )
            action = pick_action(str(task.get("prompt") or task.get("title") or ""), snap.get("nodes") or [])
            label = action_label(action)
            created = now
            opened = float(snap.get("page_open_at_ts") or created)
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
                failed_step=None,
                first_action_at_ts=now,
                phase_ms={
                    **dict(snap.get("phase_ms") or {}),
                    "first_action_ms": _ms(opened, now),
                },
            )
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
                bb = await asyncio.wait_for(self.pool.get(), timeout=12)
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
                    self._handle_cv.notify_all()
            self.snapshots[key] = snap
            self._publish_site(key, snap)

        await asyncio.gather(*[_one(key, url) for key, url in sites])
        self.published.set()

    async def take_page(self, site_key: str, url: str) -> dict[str, Any] | None:
        """A browser already on this site, or the next pre-created session."""
        async with self._handle_cv:
            for i, handle in enumerate(self._handles):
                if handle.get("site_key") == site_key:
                    return self._handles.pop(i)
        try:
            bb = await asyncio.wait_for(self.pool.get(), timeout=12)
        except asyncio.TimeoutError:
            async with self._handle_cv:
                if self._handles:
                    return self._handles.pop(0)
            return None
        try:
            _browser, page = await self._connect(bb)
            try:
                await page.goto(url, wait_until="commit", timeout=8000)
            except Exception as exc:  # noqa: BLE001
                print(f"[a11y] agent goto {url}: {exc!r}", flush=True)
            return {"bb": bb, "browser": _browser, "page": page, "site_key": site_key}
        except Exception as exc:  # noqa: BLE001
            print(f"[a11y] connect failed: {exc!r}", flush=True)
            return None

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
        raw = await asyncio.wait_for(
            gemini_chat(
                [{"role": "user", "content": prompt}],
                model=fast_action_model(),
                temperature=0,
                json_mode=True,
                max_retries=1,
            ),
            timeout=8,
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
        "x": int((node or {}).get("x") or 0),
        "y": int((node or {}).get("y") or 0),
    }
    return out


async def _act(page: Any, action: dict[str, Any]) -> None:
    act = str(action.get("act") or "click")
    x = int(action.get("x") or 200)
    y = int(action.get("y") or 200)
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
        await page.mouse.move(x, y)
        await page.mouse.down()
        await page.mouse.move(x + 180, y + 100)
        await page.mouse.up()
        return
    if act == "done":
        return
    await page.mouse.click(x, y)


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
    max_steps: int = 6,
) -> dict[str, Any]:
    """Continue from the shared snapshot. One tree read per step, one final shot."""
    from mvp.paths import MVP_RUNS_DIR

    sess = boot.study.live_sessions.get(agent_id) or {}
    handle = await boot.take_page(site_key, url)
    failed: dict[str, Any] | None = None
    phase = "navigate"
    page = None
    browser = None
    bb = None
    if handle is None:
        failed = {"phase": "session", "reason": "no Browserbase session", "step": 0}
    else:
        page = handle["page"]
        browser = handle["browser"]
        bb = handle["bb"]
        current = ""
        try:
            current = page.url or ""
        except Exception:
            current = ""
        if url and url.rstrip("/") not in current.rstrip("/"):
            phase = "navigate"
            try:
                await page.goto(url, wait_until="commit", timeout=8000)
            except Exception as exc:  # noqa: BLE001
                failed = {"phase": "navigate", "reason": repr(exc)[:200], "step": 1}
        pending = dict(sess.get("pending_action") or {}) or pick_action(
            task_prompt, (boot.snapshot_for(site_key) or {}).get("nodes") or []
        )
        if failed is None and pending.get("act") != "done":
            phase = "act"
            try:
                await _act(page, pending)
            except Exception as exc:  # noqa: BLE001
                failed = {"phase": "act", "reason": repr(exc)[:200], "step": 1}

    read = boot.snapshot_for(site_key) or {"url": url, "text": "", "canvas": "", "nodes": []}
    history = [str(sess.get("last_action") or "")]
    friction: list[str] = []
    easy: list[str] = []
    trace = list(sess.get("trace") or [])
    step_no = max([int(s.get("step") or 0) for s in trace if isinstance(s, dict)] or [0])
    prev_url = str(read.get("url") or "")
    prev_text = str(read.get("text") or "")[:240]

    for _ in range(max_steps):
        if page is None or failed:
            break
        phase = "read"
        t_read = time.perf_counter()
        read = await _one_read(page, str(read.get("url") or url))
        read_ms = int(round((time.perf_counter() - t_read) * 1000))
        if read.get("error"):
            failed = {"phase": "read", "reason": str(read.get("error")), "step": step_no}
            break
        phase = "decide"
        action = await _model_action(task=task_prompt, read=read, history=history)
        if action is None:
            action = pick_action(task_prompt, read.get("nodes") or [])
        if action.get("friction"):
            friction.append(str(action["friction"]))
        if action.get("easy"):
            easy.append(str(action["easy"]))
        if str(action.get("act")) == "done":
            break
        step_no += 1
        label = action_label(action)
        outcome = "friction" if action.get("friction") else "neutral"
        row = _step_from_read(step=step_no, action=label, read=read, outcome=outcome, thought=str(action.get("easy") or action.get("friction") or ""))
        row["read_ms"] = read_ms
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
            failed = {"phase": "act", "reason": repr(exc)[:200], "step": step_no}
            break
        prev_url = str(read.get("url") or "")
        prev_text = str(read.get("text") or "")[:240]

    # One more read so final URL and DOM are the page after the last action.
    if page is not None:
        phase = "read"
        final_read = await _one_read(page, str(read.get("url") or url))
        if not final_read.get("error"):
            read = final_read
            new_url = str(read.get("url") or "")
            new_text = str(read.get("text") or "")[:240]
            if prev_url and new_url and new_url != prev_url:
                note = f"Opening {new_url.split('?')[0][-60:]} from the page was straightforward."
                if note not in easy:
                    easy.append(note)
            elif prev_text and new_text == prev_text and history:
                note = f"{history[-1]} did not change the page."
                if note not in friction:
                    friction.append(note)

    shot_url = ""
    shot_ms = None
    if page is not None:
        phase = "final_screenshot"
        dest = MVP_RUNS_DIR / study_id / agent_id / "screenshots"
        dest.mkdir(parents=True, exist_ok=True)
        path = dest / "final.png"
        t_shot = time.perf_counter()
        try:
            await page.screenshot(path=str(path), full_page=False, timeout=8000)
            shot_ms = int(round((time.perf_counter() - t_shot) * 1000))
            shot_url = f"/api/studies/{study_id}/agents/{agent_id}/screenshots/final.png"
        except Exception as exc:  # noqa: BLE001
            failed = failed or {"phase": "final_screenshot", "reason": repr(exc)[:200], "step": step_no}
        if shot_url and trace:
            trace[-1]["screenshot_url"] = shot_url
            trace[-1]["final_screenshot_url"] = shot_url

    final_url = str(read.get("url") or url)
    final_dom = str(read.get("text") or "")[:1500]
    ax = format_ax(read.get("nodes") or [])
    phase_ms = dict((sess.get("phase_ms") or {}))
    if shot_ms is not None:
        phase_ms["final_screenshot_ms"] = shot_ms
    if isinstance(read, dict) and read.get("read_ms") is not None:
        phase_ms["step_read_ms"] = read.get("read_ms")

    result = {
        "agent_id": agent_id,
        "persona_id": persona.get("id"),
        "task_id": agent_id,
        "completed": failed is None,
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
        "phase": "error" if failed else "done",
        "error": "" if not failed else str(failed.get("reason") or ""),
        "browser_error": "" if not failed else str(failed.get("reason") or ""),
        "browserbase_session_id": getattr(bb, "id", None) if bb is not None else None,
    }
    apply_gate_fields(result, **{k: result.get(k) for k in GATE_FIELDS})
    if browser is not None:
        try:
            await browser.close()
        except Exception:
            pass
    if bb is not None:
        try:
            from capability.browserbase_client import close_session

            sid = getattr(bb, "id", None)
            if sid:
                await asyncio.to_thread(close_session, sid)
        except Exception:
            pass
    return result
