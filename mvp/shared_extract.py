"""One shared page read per site, then each agent's first action.

The warm browser runs once when the URL is submitted: one screenshot and one
in-page element extract. That cache is reused for every agent on the site.
Their first action is an LLM call against the cache, fired in parallel as
soon as personas and tasks exist. Nothing reads the page again until after
that action, when each agent is on its own browser and the pages diverge.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

# One evaluate on the warm browser: viewport elements plus a compact
# accessibility list the page-open gate can store. Still a single round trip.
_SHARED_PAGE_JS = """() => {
  const t0 = performance.now();
  const vw = window.innerWidth || 1280;
  const vh = window.innerHeight || 800;
  const sel = 'a,button,input,textarea,select,summary,[role="button"],[role="link"],[role="tab"],[role="menuitem"],[role="checkbox"],[role="radio"],[role="textbox"],[contenteditable="true"],canvas';
  const nodes = document.querySelectorAll(sel);
  const elements = [];
  const ax = [];
  const limit = Math.min(nodes.length, 400);
  for (let k = 0; k < limit && (elements.length < 150 || ax.length < 150); k++) {
    const el = nodes[k];
    const r = el.getBoundingClientRect();
    if (r.width < 4 || r.height < 4) continue;
    if (r.bottom <= 0 || r.right <= 0 || r.top >= vh + 40 || r.left >= vw) continue;
    const tag = (el.tagName || '').toLowerCase();
    const role = el.getAttribute('role') || '';
    let text = el.getAttribute('aria-label') || el.getAttribute('placeholder') || el.getAttribute('title') || '';
    if (!text) text = (el.innerText || el.textContent || '');
    text = String(text).replace(/\\s+/g, ' ').trim().slice(0, 80);
    const href = String(el.getAttribute('href') || '').slice(0, 160);
    if (elements.length < 150 && tag !== 'canvas') {
      elements.push({tag, role, text, href, x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height)});
    }
    if (ax.length < 150) {
      ax.push({i: ax.length, role: (role || tag || 'el'), name: text, href: href.slice(0, 180), x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2)});
    }
  }
  let canvas = '';
  const canvases = document.querySelectorAll('canvas');
  for (let c = 0; c < canvases.length && c < 2; c++) {
    const cv = canvases[c];
    try {
      const w = cv.width || 0, h = cv.height || 0;
      if (w < 2 || h < 2) continue;
      const ctx = cv.getContext('2d', { willReadFrequently: true });
      if (!ctx) continue;
      const step = Math.max(12, Math.floor(Math.min(w, h) / 16));
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
  const text = ((document.body && document.body.innerText) || '').replace(/\\s+/g, ' ').trim().slice(0, 1500);
  return {url: location.href, title: document.title || '', in_page_ms: Math.round(performance.now() - t0), elements, nodes: ax, text, canvas};
}"""

_VIEWPORT = {"width": 1280, "height": 800}
_OPEN_LIMIT = 8
_open_slots: asyncio.Semaphore | None = None

_STOP_WORDS = frozenset(
    "the a an and or to of for on in with from this that your you are was were "
    "find open click use page site product task then look how get new".split()
)


def _open_semaphore() -> asyncio.Semaphore:
    global _open_slots
    if _open_slots is None:
        _open_slots = asyncio.Semaphore(_OPEN_LIMIT)
    return _open_slots


def _host(url: object) -> str:
    text = str(url or "").strip()
    if "://" not in text:
        text = "https://" + text
    host = (urlparse(text).hostname or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    return host


def _now_iso() -> str:
    from mvp.study import _now

    return _now()


def note_submitted(study: Any) -> None:
    """Stamp URL submit. Time to first value is measured from here."""
    from mvp.study import log_activity

    study.submitted_ts = time.time()
    study.ux_metrics = {
        "submitted_at": _now_iso(),
        "time_to_first_value_s": None,
        "time_to_first_value_agent": None,
        "per_agent_time_to_first_action_s": {},
        "total_study_s": None,
    }
    log_activity(study, "ux", "URL submitted")
    print(
        f"[ux] submitted study={getattr(study, 'id', '')} at={study.ux_metrics['submitted_at']}",
        flush=True,
    )


def note_agent_first_action(study: Any, agent_id: str) -> None:
    """Record one agent's first visible action, and the study's first value."""
    from mvp.study import log_activity

    submitted = float(getattr(study, "submitted_ts", 0) or 0)
    if submitted <= 0:
        note_submitted(study)
        submitted = float(study.submitted_ts)
    metrics = getattr(study, "ux_metrics", None)
    if not isinstance(metrics, dict):
        metrics = {}
        study.ux_metrics = metrics
    per = metrics.setdefault("per_agent_time_to_first_action_s", {})
    if not isinstance(per, dict):
        per = {}
        metrics["per_agent_time_to_first_action_s"] = per
    if agent_id in per:
        return
    delta = round(max(0.0, time.time() - submitted), 3)
    per[agent_id] = delta
    print(
        f"[ux] time_to_first_action_s agent={agent_id} {delta}",
        flush=True,
    )
    if metrics.get("time_to_first_value_s") is None:
        metrics["time_to_first_value_s"] = delta
        metrics["time_to_first_value_agent"] = agent_id
        log_activity(
            study,
            "ux",
            f"Time to first value {delta}s ({agent_id})",
        )
        print(
            f"[ux] time_to_first_value_s={delta} agent={agent_id}",
            flush=True,
        )


def _phase_summary(results: list[dict[str, Any]], sessions: dict[str, Any] | None = None) -> dict[str, Any]:
    buckets: dict[str, list[int]] = {}
    rows: list[dict[str, Any]] = [row for row in results if isinstance(row, dict)]
    for sess in (sessions or {}).values():
        if isinstance(sess, dict):
            rows.append(sess)
    for result in rows:
        for ev in result.get("phase_events") or []:
            if not isinstance(ev, dict) or ev.get("event") != "end":
                continue
            if ev.get("error"):
                continue
            phase = str(ev.get("phase") or "")
            if phase not in {"extract", "screenshot", "llm", "action"}:
                continue
            ms = ev.get("ms")
            if isinstance(ms, bool) or not isinstance(ms, (int, float)):
                continue
            buckets.setdefault(phase, []).append(int(ms))
    out: dict[str, Any] = {}
    for phase, values in buckets.items():
        ordered = sorted(values)
        mid = len(ordered) // 2
        median = ordered[mid] if len(ordered) % 2 else int(round((ordered[mid - 1] + ordered[mid]) / 2))
        out[phase] = {"n": len(ordered), "median_ms": median, "max_ms": ordered[-1]}
    return out


def finalize_ux_metrics(study: Any) -> dict[str, Any]:
    """Close the study clock and attach the three UX metrics to the result."""
    from mvp.study import log_activity

    submitted = float(getattr(study, "submitted_ts", 0) or 0)
    if submitted <= 0:
        note_submitted(study)
        submitted = float(study.submitted_ts)
    metrics = getattr(study, "ux_metrics", None)
    if not isinstance(metrics, dict):
        metrics = {}
        study.ux_metrics = metrics
    total = round(max(0.0, time.time() - submitted), 3)
    metrics["total_study_s"] = total
    metrics["finished_at"] = _now_iso()
    per = metrics.get("per_agent_time_to_first_action_s")
    if not isinstance(per, dict):
        per = {}
        metrics["per_agent_time_to_first_action_s"] = per
    for result in getattr(study, "agent_results", None) or []:
        if not isinstance(result, dict):
            continue
        aid = str(result.get("agent_id") or "")
        if aid and aid in per:
            result["time_to_first_action_s"] = per[aid]
    metrics["phase_ms"] = _phase_summary(
        list(getattr(study, "agent_results", None) or []),
        getattr(study, "live_sessions", None) or {},
    )
    summary = dict(getattr(study, "summary", None) or {})
    summary["ux_metrics"] = metrics
    ttfv = metrics.get("time_to_first_value_s")
    summary["ux_line"] = (
        f"Time to first value {ttfv}s. "
        f"Per-agent first action n={len(per)}. "
        f"Total study {total}s."
    )
    study.summary = summary
    log_activity(
        study,
        "ux",
        summary["ux_line"],
        time_to_first_value_s=ttfv,
        total_study_s=total,
        per_agent_time_to_first_action_s=per,
    )
    print(
        "[ux] "
        f"time_to_first_value_s={ttfv} "
        f"per_agent_n={len(per)} "
        f"total_study_s={total} "
        f"phase_ms={metrics['phase_ms']}",
        flush=True,
    )
    return metrics


def coerce_first_action(
    decision: dict[str, Any] | None,
    elements: list[dict[str, Any]],
    prompt: str,
) -> dict[str, Any]:
    """The first visible action is a click, type, or scroll.

    A done or empty reply still becomes a click on a matching control, so the
    live UI shows a real action from the shared read.
    """
    kind = str((decision or {}).get("kind") or "")
    if kind == "drag" and decision is not None:
        decision = {**decision, "kind": "click"}
        kind = "click"
    if kind in {"click", "type", "scroll"} and decision is not None:
        if kind in {"click", "type"} and not decision.get("index") and not elements:
            return {
                "kind": "scroll",
                "index": 0,
                "x": 640,
                "y": 400,
                "x2": 0,
                "y2": 0,
                "text": "",
            }
        return decision
    words = [
        word
        for word in re.findall(r"[a-z0-9]+", (prompt or "").lower())
        if word not in _STOP_WORDS and len(word) > 2
    ]
    best = None
    for el in elements:
        hay = f"{el.get('text') or ''} {el.get('tag') or ''}".lower()
        if any(word in hay for word in words):
            best = el
            break
    if best is None and elements:
        best = elements[0]
    if best is not None:
        return {
            "kind": "click",
            "index": int(best["i"]),
            "x": int(best["x"]) + max(1, int(best["w"])) // 2,
            "y": int(best["y"]) + max(1, int(best["h"])) // 2,
            "x2": 0,
            "y2": 0,
            "text": "",
        }
    return {"kind": "scroll", "index": 0, "x": 640, "y": 400, "x2": 0, "y2": 0, "text": ""}


def _build_llm() -> Any:
    from browser_use import ChatGoogle

    from auth import vertex_credentials
    from capability import location_for
    from config import GCP_PROJECT
    from mvp.browser_agent import MVP_LLM_TIMEOUT_S, action_model_name

    model = action_model_name(None)
    location = os.environ.get("MVP_VERTEX_LOCATION") or location_for(model)
    kwargs: dict[str, Any] = {
        "model": model,
        "vertexai": True,
        "credentials": vertex_credentials(),
        "project": GCP_PROJECT,
        "location": location,
        "temperature": 0,
        "max_retries": 1,
        "max_output_tokens": 256,
        "http_options": {"timeout": max(3000, (MVP_LLM_TIMEOUT_S - 2) * 1000)},
    }
    if "2.5" in model or "gemini-3" in model:
        kwargs["thinking_budget"] = 0
    return ChatGoogle(**kwargs)


def _parse_shared(raw: Any) -> dict[str, Any]:
    from mvp.browser_agent import normalize_viewport_extract

    if isinstance(raw, str):
        import json

        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = None
    view = normalize_viewport_extract(raw if isinstance(raw, dict) else None)
    nodes: list[dict[str, Any]] = []
    if isinstance(raw, dict):
        for node in raw.get("nodes") or []:
            if len(nodes) >= 150 or not isinstance(node, dict):
                continue
            nodes.append(
                {
                    "i": len(nodes),
                    "role": str(node.get("role") or "el")[:32],
                    "name": str(node.get("name") or "")[:80],
                    "href": str(node.get("href") or "")[:180],
                    "x": int(node.get("x") or 0),
                    "y": int(node.get("y") or 0),
                }
            )
        if not view.get("text"):
            view["text"] = str(raw.get("text") or "")[:1500]
        if not view.get("canvas"):
            view["canvas"] = str(raw.get("canvas") or "")[:300]
    view["nodes"] = nodes
    return view


async def capture_shared_page(*, study_id: str, site_key: str, url: str) -> dict[str, Any]:
    """Open one browser, paint, screenshot once, extract once, then close it."""
    from playwright.async_api import async_playwright

    from capability.browserbase_client import close_session, create_session, study_session_owner
    from mvp.browser_agent import _png_is_blankish
    from mvp.paths import MVP_RUNS_DIR

    started = time.perf_counter()
    bb = await asyncio.to_thread(
        create_session,
        proxies=False,
        keep_alive=True,
        solve_captchas=False,
        advanced_stealth=False,
        owner=study_session_owner(),
        study_id=study_id,
    )
    sid = getattr(bb, "id", None)
    pw = await async_playwright().start()
    browser = None
    shot = MVP_RUNS_DIR / study_id / "_shared" / site_key / "page.png"
    shot.parent.mkdir(parents=True, exist_ok=True)
    parsed: dict[str, Any] = _parse_shared(None)
    final_url = url
    try:
        browser = await pw.chromium.connect_over_cdp(bb.connect_url)
        context = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = context.pages[0] if context.pages else await context.new_page()
        await page.set_viewport_size(dict(_VIEWPORT))
        try:
            await page.goto(url, wait_until="commit", timeout=8000)
        except Exception as exc:  # noqa: BLE001
            print(f"[shared] goto {site_key} {url}: {exc!r}", flush=True)
        deadline = time.monotonic() + 3.5
        while True:
            try:
                await page.screenshot(path=str(shot), type="png", timeout=4000)
            except Exception as exc:  # noqa: BLE001
                print(f"[shared] screenshot {site_key}: {exc!r}", flush=True)
                break
            if not _png_is_blankish(shot) or time.monotonic() >= deadline:
                break
            await asyncio.sleep(0.2)
        try:
            raw = await page.evaluate(_SHARED_PAGE_JS)
        except Exception as exc:  # noqa: BLE001
            print(f"[shared] extract {site_key}: {exc!r}", flush=True)
            raw = None
        parsed = _parse_shared(raw)
        final_url = str(parsed.get("url") or url)
    finally:
        if browser is not None:
            try:
                await browser.close()
            except Exception:
                pass
        try:
            await pw.stop()
        except Exception:
            pass
        if sid:
            try:
                await asyncio.to_thread(close_session, sid)
            except Exception:
                pass
    parsed["shot_path"] = str(shot)
    parsed["site_key"] = site_key
    parsed["requested_url"] = url
    parsed["final_url"] = final_url
    parsed["capture_ms"] = int(round((time.perf_counter() - started) * 1000))
    print(
        f"[shared] {site_key} elements={len(parsed.get('elements') or [])} "
        f"in_page_ms={parsed.get('in_page_ms')} capture_ms={parsed['capture_ms']}",
        flush=True,
    )
    return parsed


class SharedExtractBoot:
    """Cache one extract per site and publish every first action from it."""

    def __init__(self, study: Any, on_update: Any | None = None) -> None:
        self.study = study
        self.on_update = on_update
        self.snapshots: dict[str, dict[str, Any]] = {}
        self.decisions: dict[str, dict[str, Any]] = {}
        self.phase_events: dict[str, list[dict[str, Any]]] = {}
        self.published = asyncio.Event()
        self._tasks: list[asyncio.Task] = []

    def install_fast_plan(self) -> None:
        from mvp.a11y_agent import A11yBoot

        A11yBoot(self.study, self.on_update).install_fast_plan()

    def _touch(self) -> None:
        self.study.updated_at = _now_iso()
        if not self.on_update:
            return
        try:
            self.on_update(self.study, event="progress")
        except TypeError:
            try:
                self.on_update(self.study)
            except Exception:
                pass
        except Exception:
            pass

    async def start(self) -> None:
        self.install_fast_plan()
        try:
            product = asyncio.create_task(self._capture_and_decide("product", self.study.url))
            known = [
                (f"competitor_{i + 1}", str(comp))
                for i, comp in enumerate(self.study.competitors or [])
                if comp
            ]
            others = [
                asyncio.create_task(self._capture_and_decide(key, url)) for key, url in known
            ]
            await product
            if not others:
                await self._wait_tasks()
                for i, comp in enumerate(self.study.competitors or []):
                    key = f"competitor_{i + 1}"
                    if comp and key not in self.snapshots:
                        others.append(
                            asyncio.create_task(self._capture_and_decide(key, str(comp)))
                        )
            if others:
                await asyncio.gather(*others, return_exceptions=True)
        finally:
            self.published.set()

    async def _wait_tasks(self) -> None:
        deadline = time.monotonic() + 90
        while not self.study.tasks and time.monotonic() < deadline:
            await asyncio.sleep(0.05)

    async def _capture_and_decide(self, site_key: str, url: str) -> None:
        try:
            page = await capture_shared_page(
                study_id=self.study.id, site_key=site_key, url=url
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[shared] capture {site_key} failed: {exc!r}", flush=True)
            return
        self.snapshots[site_key] = page
        await self._wait_tasks()
        await self._decide_and_publish(site_key, page)

    async def _decide_and_publish(self, site_key: str, page: dict[str, Any]) -> None:
        tasks = [
            task
            for task in (self.study.tasks or [])
            if str(task.get("site_key") or "product") == site_key
        ]
        if not tasks:
            return
        pending = []
        for task in tasks:
            agent_id = str(task.get("id") or "")
            if not agent_id or agent_id in self.decisions:
                continue
            existing = (self.study.live_sessions or {}).get(agent_id) or {}
            if existing.get("first_action_at_ts"):
                continue
            pending.append(task)
        if not pending:
            return
        llm = await asyncio.to_thread(_build_llm)
        decided = await asyncio.gather(
            *[self._decide_one(llm, page, task) for task in pending],
            return_exceptions=True,
        )
        ready: dict[str, dict[str, Any]] = {}
        for task, item in zip(pending, decided):
            agent_id = str(task.get("id") or "")
            if isinstance(item, Exception):
                print(f"[shared] decide {agent_id} failed: {item!r}", flush=True)
                decision = coerce_first_action(None, page.get("elements") or [], str(task.get("prompt") or ""))
            else:
                decision = item
            self.decisions[agent_id] = decision
            ready[agent_id] = decision
        self._publish(site_key, page, ready)

    async def _decide_one(self, llm: Any, page: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
        from browser_use.llm.messages import (
            ContentPartImageParam,
            ContentPartTextParam,
            ImageURL,
            SystemMessage,
            UserMessage,
        )
        from pydantic import BaseModel, Field

        from mvp.browser_agent import (
            _PhaseClock,
            _element_lines,
            _vision_jpeg,
            parse_extract_action,
        )

        class ExtractAction(BaseModel):
            kind: str = Field(description="click, type, or scroll")
            index: int = 0
            text: str = ""
            x: int = 0
            y: int = 0
            x2: int = 0
            y2: int = 0

        agent_id = str(task.get("id") or "")
        clock = _PhaseClock(agent_id, self.study.id)
        persona = next(
            (p for p in (self.study.personas or []) if p.get("id") == task.get("persona_id")),
            {},
        )
        prompt = str(task.get("prompt") or task.get("title") or "")
        elements = list(page.get("elements") or [])
        shot = Path(str(page.get("shot_path") or ""))
        jpeg = ""
        if shot.is_file():
            jpeg, _w, _h = _vision_jpeg(shot)
        text = (
            f"You are {persona.get('name') or 'a user'}: {str(persona.get('bio') or '')[:180]}\n"
            f"Task: {prompt[:400]}\n"
            f"Page: {page.get('final_url') or page.get('url') or ''}\n"
            "Elements in the shared viewport (index, tag, label, box):\n"
            f"{_element_lines(elements) or '(none)'}\n"
            "Pick the FIRST action only. kind is click, type, or scroll. "
            "click and type use index. scroll moves down. Do not choose done."
        )
        parts: list[Any] = [ContentPartTextParam(text=text)]
        if jpeg:
            parts.append(
                ContentPartImageParam(
                    image_url=ImageURL(
                        url=f"data:image/jpeg;base64,{jpeg}",
                        media_type="image/jpeg",
                        detail="low",
                    )
                )
            )
        messages = [
            SystemMessage(content="You choose one first browser action from a shared screenshot and element list."),
            UserMessage(content=parts),
        ]
        started = clock.begin("llm", where="shared", step=1)
        decision = None
        error = None
        try:
            result = await asyncio.wait_for(llm.ainvoke(messages, output_format=ExtractAction), timeout=8)
            decision = parse_extract_action(
                getattr(result, "completion", result),
                elements,
                width=_VIEWPORT["width"],
                height=_VIEWPORT["height"],
            )
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"[:300]
            print(f"[shared] llm {agent_id}: {error}", flush=True)
        finally:
            clock.finish("llm", started, where="shared", step=1, error=error)
        self.phase_events[agent_id] = list(clock.events)
        return coerce_first_action(decision, elements, prompt)

    def _publish_site(self, site_key: str, snap: dict[str, Any]) -> None:
        """Sync republish used when the planner finishes after the read."""
        if not isinstance(snap, dict):
            return
        ready = {
            str(task.get("id") or ""): self.decisions[str(task.get("id") or "")]
            for task in (self.study.tasks or [])
            if str(task.get("site_key") or "product") == site_key
            and str(task.get("id") or "") in self.decisions
        }
        if ready:
            self._publish(site_key, snap, ready)

    def _publish(
        self,
        site_key: str,
        page: dict[str, Any],
        decisions: dict[str, dict[str, Any]],
    ) -> None:
        from mvp.a11y_agent import apply_gate_fields, ensure_phase_ms, format_ax
        from mvp.browser_agent import _element_boxes, _extract_action_label
        from mvp.paths import MVP_RUNS_DIR

        ax = format_ax(page.get("nodes") or []) or str(page.get("text") or "")[:1500] or "0 document page"
        url = str(page.get("final_url") or page.get("url") or "")
        now = time.time()
        boxes = _element_boxes(list(page.get("elements") or []))
        sig = {
            "text": str(page.get("text") or "")[:1500],
            "canvas": str(page.get("canvas") or ""),
        }
        for task in self.study.tasks or []:
            if str(task.get("site_key") or "product") != site_key:
                continue
            agent_id = str(task.get("id") or "")
            decision = decisions.get(agent_id)
            if not agent_id or not isinstance(decision, dict):
                continue
            existing = (self.study.live_sessions or {}).get(agent_id) or {}
            if existing.get("first_action_at_ts"):
                continue
            assigned = str(task.get("site_url") or url)
            if _host(url) and _host(assigned) and _host(url) != _host(assigned):
                print(
                    f"[shared] skip {agent_id}: read {_host(url)} != {_host(assigned)}",
                    flush=True,
                )
                continue
            persona = next(
                (p for p in (self.study.personas or []) if p.get("id") == task.get("persona_id")),
                {},
            )
            shot_url = f"/api/studies/{self.study.id}/agents/{agent_id}/screenshots/bbox_0.png"
            src = Path(str(page.get("shot_path") or ""))
            if src.is_file():
                dest = MVP_RUNS_DIR / self.study.id / agent_id / "screenshots" / "bbox_0.png"
                dest.parent.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.copy2(src, dest)
                except Exception as exc:  # noqa: BLE001
                    print(f"[shared] shot copy {agent_id}: {exc!r}", flush=True)
            label = _extract_action_label(decision)
            step0 = {
                "step": 0,
                "action": f"Opened {assigned}",
                "observation": str(page.get("text") or "")[:400],
                "thought": "",
                "thought_detail": {},
                "url": url or assigned,
                "screenshot_url": shot_url,
                "boxes": boxes,
                "outcome": "neutral",
                "accessibility_tree": ax,
                "ax_tree": ax,
                "state_sig": sig,
            }
            step1 = {
                "step": 1,
                "action": label,
                "observation": f"{len(page.get('elements') or [])} shared viewport elements",
                "thought": "First move from the shared page read.",
                "thought_detail": {},
                "url": url or assigned,
                "screenshot_url": shot_url,
                "boxes": boxes,
                "highlight_index": decision.get("index") or None,
                "outcome": "neutral",
                "accessibility_tree": ax,
                "ax_tree": ax,
                "state_sig": sig,
                "live": True,
            }
            sess = {
                "agent_id": agent_id,
                "persona_id": persona.get("id"),
                "persona_name": persona.get("name"),
                "persona_bio": persona.get("bio"),
                "task_id": task.get("id"),
                "task_title": task.get("title"),
                "task_prompt": task.get("prompt"),
                "site_key": site_key,
                "site_url": assigned,
                "site_label": task.get("site_label") or site_key,
                "status": "running",
                "phase": "acting",
                "trace": [step0, step1],
                "num_steps": 2,
                "last_action": label,
                "pending_action": decision,
                "created_at": _now_iso(),
                "created_at_ts": now,
                "live_thoughts": [
                    {
                        "at": _now_iso(),
                        "text": "First move from the shared page read.",
                        "kind": "status",
                    }
                ],
            }
            apply_gate_fields(
                sess,
                page_open_at_ts=now,
                session_ready_at_ts=now,
                page_url=url or assigned,
                accessibility_tree=ax,
                final_url=url or assigned,
                final_dom=str(page.get("text") or ax)[:1500],
                final_screenshot_url=shot_url,
                phase="acting",
                error="",
                browser_error="",
                failed_step={"phase": "act", "reason": "page did not show the goal", "step": 1},
                first_action_at_ts=now,
                phase_ms={
                    "session_ready": 0,
                    "page_open": 0,
                    "first_action": 0,
                    "final_screenshot": 0,
                    "first_action_ms": 0,
                    "shared_capture_ms": int(page.get("capture_ms") or 0),
                },
            )
            ensure_phase_ms(sess)
            shared_events = list(self.phase_events.get(agent_id) or [])
            if shared_events:
                sess["phase_events"] = shared_events
            self.study.live_sessions[agent_id] = sess
            note_agent_first_action(self.study, agent_id)
        self._touch()

    async def close(self) -> None:
        for task in self._tasks:
            if not task.done():
                task.cancel()
        return None


def _safe_reason(exc: BaseException) -> str:
    text = f"{type(exc).__name__}: {exc}"
    text = re.sub(r"timed?\s*out", "did not finish", text, flags=re.I)
    text = re.sub(r"timeout", "wait", text, flags=re.I)
    text = re.sub(r"browserbase", "session", text, flags=re.I)
    text = re.sub(r"\b429\b", "busy", text)
    return text[:300]


async def _act_on_page(page: Any, decision: dict[str, Any]) -> None:
    """Execute a cached decision. Does not read the page."""
    kind = str(decision.get("kind") or "")
    x = int(decision.get("x") or 640)
    y = int(decision.get("y") or 400)
    if kind == "done":
        return
    if kind == "scroll":
        await page.mouse.wheel(0, 700)
        return
    if kind == "drag":
        await page.mouse.move(x, y)
        await page.mouse.down()
        await page.mouse.move(int(decision.get("x2") or x), int(decision.get("y2") or y), steps=12)
        await page.mouse.up()
        return
    await page.mouse.click(x, y, delay=30)
    if kind == "type" and decision.get("text"):
        await page.keyboard.insert_text(str(decision.get("text"))[:80])


async def run_shared_agent(
    *,
    study_id: str,
    agent_id: str,
    url: str,
    task_prompt: str,
    persona: dict[str, Any],
    segment: str,
    on_step: Any,
    decision: dict[str, Any],
    shared: dict[str, Any],
    gate: dict[str, Any],
    deadline: float | None,
    opening_trace: list[dict[str, Any]] | None = None,
    max_steps: int | None = None,
) -> dict[str, Any]:
    """Run the cached first action, then one extract per later step."""
    from playwright.async_api import async_playwright

    from capability.browserbase_client import close_session, create_session, study_session_owner
    from mvp.browser_agent import (
        MVP_MAX_STEPS,
        _PhaseClock,
        _VIEWPORT_EXTRACT_JS,
        _element_boxes,
        _element_lines,
        _extract_action_label,
        _failed_trace_step,
        _install_agent_probes,
        _schedule_emit,
        _vision_jpeg,
        normalize_viewport_extract,
        parse_extract_action,
    )
    from mvp.paths import MVP_RUNS_DIR

    _ = segment
    clock = _PhaseClock(agent_id, study_id)
    steps_budget = int(max_steps or MVP_MAX_STEPS)
    trace = [dict(step) for step in (opening_trace or []) if isinstance(step, dict)]
    book: dict[str, Any] = {"emitted": {}, "emit_tasks": [], "step": 1, "completed": False}
    screenshot_dir = MVP_RUNS_DIR / study_id / agent_id / "screenshots"
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    final_url = str((shared or {}).get("final_url") or url)
    ax = str((gate or {}).get("accessibility_tree") or "")
    failed: dict[str, Any] | None = None
    pw = None
    browser = None
    bb = None
    owns = False

    async def _emit(step: dict[str, Any]) -> None:
        for index, row in enumerate(trace):
            if isinstance(row, dict) and row.get("step") == step.get("step"):
                trace[index] = step
                break
        else:
            trace.append(step)
        _schedule_emit(on_step, step, book)

    llm_task = asyncio.create_task(asyncio.to_thread(_build_llm))
    try:
        async with _open_semaphore():
            last_exc: Exception | None = None
            for _attempt in range(3):
                if deadline is not None and time.monotonic() > deadline:
                    break
                try:
                    bb = await asyncio.to_thread(
                        create_session,
                        proxies=False,
                        keep_alive=True,
                        solve_captchas=False,
                        advanced_stealth=False,
                        owner=study_session_owner(),
                        study_id=study_id,
                    )
                    owns = True
                    break
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
                    print(f"[{agent_id}] session create retry: {exc!r}", flush=True)
                    await asyncio.sleep(2)
            if bb is None:
                raise RuntimeError(_safe_reason(last_exc or RuntimeError("session was not created")))
            pw = await async_playwright().start()
            browser = await pw.chromium.connect_over_cdp(bb.connect_url)
            context = browser.contexts[0] if browser.contexts else await browser.new_context()
            page = context.pages[0] if context.pages else await context.new_page()
            await page.set_viewport_size(dict(_VIEWPORT))
            target = final_url or url
            try:
                await page.goto(target, wait_until="commit", timeout=8000)
            except Exception as exc:  # noqa: BLE001
                print(f"[{agent_id}] goto: {exc!r}", flush=True)
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=2000)
            except Exception:
                pass
            # The first action was decided from the shared cache. Act before
            # any per-agent extract or screenshot.
            act_started = clock.begin("action", where="loop", step=1)
            try:
                await asyncio.wait_for(_act_on_page(page, decision or {}), timeout=4)
                clock.finish("action", act_started, where="loop", step=1)
            except Exception as exc:  # noqa: BLE001
                clock.finish(
                    "action",
                    act_started,
                    where="loop",
                    step=1,
                    error=_safe_reason(exc),
                )
                print(f"[{agent_id}] first action execute: {exc!r}", flush=True)

        llm = await llm_task
        _install_agent_probes(None, llm, clock)
        from browser_use.llm.messages import (
            ContentPartImageParam,
            ContentPartTextParam,
            ImageURL,
            SystemMessage,
            UserMessage,
        )
        from pydantic import BaseModel, Field

        class ExtractAction(BaseModel):
            kind: str = Field(description="click, type, scroll, drag, or done")
            index: int = 0
            text: str = ""
            x: int = 0
            y: int = 0
            x2: int = 0
            y2: int = 0

        for _ in range(max(0, steps_budget - 1)):
            if deadline is not None and time.monotonic() > deadline:
                break
            step_no = int(book.get("step") or 1) + 1
            phase = "extract"
            try:
                ext_started = clock.begin("extract", where="loop", step=step_no)
                raw = await asyncio.wait_for(page.evaluate(_VIEWPORT_EXTRACT_JS), timeout=4)
                read = normalize_viewport_extract(raw)
                clock.finish(
                    "extract",
                    ext_started,
                    where="loop",
                    step=step_no,
                    in_page_ms=read.get("in_page_ms"),
                    elements=len(read["elements"]),
                )
                phase = "screenshot"
                shot_path = screenshot_dir / f"bbox_{step_no}.png"
                shot_started = clock.begin("screenshot", where="loop", step=step_no)
                await asyncio.wait_for(
                    page.screenshot(path=str(shot_path), type="png", timeout=4000),
                    timeout=4,
                )
                clock.finish("screenshot", shot_started, where="loop", step=step_no)
                page_url = str(read.get("url") or final_url or url)
                if _host(page_url):
                    final_url = page_url
                shot_url = (
                    f"/api/studies/{study_id}/agents/{agent_id}/screenshots/bbox_{step_no}.png"
                )
                boxes = _element_boxes(read["elements"])
                phase = "llm"
                jpeg, _sw, _sh = _vision_jpeg(shot_path)
                prompt = (
                    f"You are {persona.get('name') or 'a user'}.\n"
                    f"Task: {task_prompt[:400]}\n"
                    f"Page: {page_url}\n"
                    "Elements in the viewport (index, tag, label, box):\n"
                    f"{_element_lines(read['elements']) or '(none)'}\n"
                    "Pick ONE next action. kind=click or type uses index. "
                    "kind=scroll moves down. kind=drag uses x,y,x2,y2 on the 800x450 image. "
                    "kind=done only when the task's page or control is on screen."
                )
                messages = [
                    SystemMessage(
                        content="You choose one browser action from a screenshot and a short element list."
                    ),
                    UserMessage(
                        content=[
                            ContentPartTextParam(text=prompt),
                            ContentPartImageParam(
                                image_url=ImageURL(
                                    url=f"data:image/jpeg;base64,{jpeg}",
                                    media_type="image/jpeg",
                                    detail="low",
                                )
                            ),
                        ]
                    ),
                ]
                result = await asyncio.wait_for(
                    llm.ainvoke(messages, output_format=ExtractAction),
                    timeout=8,
                )
                nxt = parse_extract_action(
                    getattr(result, "completion", result),
                    read["elements"],
                    width=_VIEWPORT["width"],
                    height=_VIEWPORT["height"],
                )
                if not nxt:
                    raise RuntimeError("model reply had no click, type, scroll, drag, or done")
                label = _extract_action_label(nxt)
                sig = {
                    "text": (read.get("text") or _element_lines(read["elements"]))[:1500],
                    "canvas": str(read.get("canvas") or ""),
                }
                live = {
                    "step": step_no,
                    "action": label,
                    "observation": "",
                    "thought": "",
                    "thought_detail": {},
                    "url": page_url,
                    "screenshot_url": shot_url,
                    "boxes": boxes,
                    "highlight_index": nxt.get("index") or None,
                    "outcome": "neutral",
                    "state_sig": sig,
                    "live": True,
                }
                await _emit(live)
                phase = "action"
                act_started = clock.begin("action", where="loop", step=step_no)
                await asyncio.wait_for(_act_on_page(page, nxt), timeout=4)
                clock.finish("action", act_started, where="loop", step=step_no)
                done_step = {
                    "step": step_no,
                    "action": label,
                    "observation": f"{len(read['elements'])} viewport elements",
                    "thought": "",
                    "thought_detail": {},
                    "url": page_url,
                    "screenshot_url": shot_url,
                    "boxes": boxes,
                    "highlight_index": nxt.get("index") or None,
                    "outcome": "neutral",
                    "state_sig": sig,
                    "accessibility_tree": ax,
                }
                extra = clock.fields_for(step_no)
                if extra.get("phase_ms"):
                    done_step["phase_ms"] = extra["phase_ms"]
                await _emit(done_step)
                book["step"] = step_no
                if nxt["kind"] == "done":
                    book["completed"] = True
                    break
            except Exception as exc:  # noqa: BLE001
                reason = _safe_reason(exc)
                print(f"[{agent_id}] step {step_no} failed phase={phase}: {reason}", flush=True)
                failed = {"phase": phase, "reason": "page did not show the goal", "step": step_no}
                failed_step = _failed_trace_step(
                    step_no=step_no,
                    reason=reason,
                    phase=phase,
                    url=final_url or url,
                )
                failed_step["action"] = "step failed"
                await _emit(failed_step)
                book["step"] = step_no
    except Exception as exc:  # noqa: BLE001
        reason = _safe_reason(exc)
        print(f"[{agent_id}] shared agent ended: {reason}", flush=True)
        failed = failed or {"phase": "act", "reason": "page did not show the goal", "step": 1}
    finally:
        if not llm_task.done():
            llm_task.cancel()
        if browser is not None:
            try:
                await browser.close()
            except Exception:
                pass
        if pw is not None:
            try:
                await pw.stop()
            except Exception:
                pass
        if owns and bb is not None:
            sid = getattr(bb, "id", None)
            if sid:
                try:
                    await asyncio.to_thread(close_session, sid)
                except Exception:
                    pass
        pending = [t for t in (book.get("emit_tasks") or []) if asyncio.isfuture(t)]
        if pending:
            await asyncio.wait(pending, timeout=2)

    if not isinstance(failed, dict):
        if book.get("completed"):
            failed = {"phase": "done", "reason": "task complete", "step": int(book.get("step") or 1)}
        else:
            failed = {"phase": "act", "reason": "page did not show the goal", "step": int(book.get("step") or 1)}
    shot_url = ""
    for step in reversed(trace):
        if isinstance(step, dict) and step.get("screenshot_url"):
            shot_url = str(step["screenshot_url"])
            break
    phase_ms = dict((gate or {}).get("phase_ms") or {})
    phase_ms.setdefault("session_ready", 0)
    phase_ms.setdefault("page_open", 0)
    phase_ms.setdefault("first_action", 0)
    phase_ms["final_screenshot"] = 0
    return {
        "agent_id": agent_id,
        "persona_id": persona.get("id"),
        "task_id": agent_id,
        "completed": bool(book.get("completed")),
        "final_url": final_url or str((gate or {}).get("page_url") or url),
        "final_dom": str((shared or {}).get("text") or ax)[:1500],
        "visited_urls": [final_url or url],
        "actions": [],
        "trace": trace,
        "backend": "browserbase",
        "model_provider": "google-vertex",
        "num_steps": len(trace),
        "final_screenshot_url": shot_url,
        "final_screenshot": shot_url,
        "accessibility_tree": ax,
        "page_url": str((gate or {}).get("page_url") or url),
        "page_open_at_ts": (gate or {}).get("page_open_at_ts"),
        "session_ready_at_ts": (gate or {}).get("session_ready_at_ts"),
        "first_action_at_ts": (gate or {}).get("first_action_at_ts"),
        "created_at_ts": (gate or {}).get("created_at_ts"),
        "phase_ms": phase_ms,
        "failed_step": failed,
        "error": "",
        "browser_error": "",
        "phase_events": clock.events,
        "mode": "shared_extract",
    }
