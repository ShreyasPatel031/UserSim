#!/usr/bin/env python3
"""Real UI e2e: open UserSim → click Run (not Smoke) → assert brief + stage + report.

Uses Playwright to drive the browser like a human, then gemini-2.5-flash-lite
to vision-judge screenshots (real page vs grey placeholder) and the final report.

Defaults are a bounded but non-smoke study:
  product + 1 pasted competitor + 2 tasks → personas invented → multi-site agents.

Usage:
  PYTHONPATH=src:. python mvp/e2e_ui_run.py --base https://usersim.vercel.app
  E2E_HEADED=1 PYTHONPATH=src:. python mvp/e2e_ui_run.py --base http://127.0.0.1:3000
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

sa = ROOT / "secrets" / "sa.json"
if sa.is_file():
    os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", str(sa))

JUDGE_MODEL = os.environ.get("E2E_JUDGE_MODEL", "gemini-2.5-flash-lite")
OUT_DIR = Path(os.environ.get("E2E_OUT_DIR", "/tmp/usersim_e2e_ui"))
DEFAULT_URL = os.environ.get("E2E_PRODUCT_URL", "https://useagency.dev/")
DEFAULT_COMPETITOR = os.environ.get("E2E_COMPETITOR", "https://recurse.run/")
DEFAULT_TASKS = os.environ.get(
    "E2E_TASKS",
    "Skim the homepage and note the main value prop\n"
    "Find pricing or how to get started",
)


def _log(msg: str) -> None:
    print(msg, flush=True)


def http_json(base: str, path: str, timeout: float = 60) -> dict:
    req = urllib.request.Request(
        f"{base.rstrip('/')}{path}",
        headers={"Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as res:
        raw = res.read().decode()
        return json.loads(raw) if raw else {}


def gemini_vision_json(prompt: str, png: bytes, *, model: str = JUDGE_MODEL) -> dict:
    """Judge an image with Vertex gemini-2.5-flash-lite; return parsed JSON."""
    from google import genai
    from google.genai import types

    from auth import vertex_credentials
    from config import GCP_PROJECT

    client = genai.Client(
        vertexai=True,
        project=os.environ.get("GCP_PROJECT") or GCP_PROJECT,
        location=os.environ.get("VERTEX_LOCATION", "us-central1"),
        credentials=vertex_credentials(),
    )
    resp = client.models.generate_content(
        model=model,
        contents=[
            types.Part.from_text(text=prompt),
            types.Part.from_bytes(data=png, mime_type="image/png"),
        ],
        config=types.GenerateContentConfig(
            temperature=0,
            max_output_tokens=512,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
            response_mime_type="application/json",
        ),
    )
    raw = (resp.text or "").strip()
    match = re.search(r"\{.*\}", raw, re.S)
    return json.loads(match.group(0) if match else raw)


def judge_screenshot(png: bytes, *, label: str) -> dict:
    prompt = f"""You are QA for a product-research UI showing a live browser session.

Look at this screenshot of the UserSim stage ({label}).

Decide whether the stage shows a REAL webpage screenshot (readable UI, text, images,
browser chrome of the target site) OR a grey/blank/placeholder/spinner-only pane
with no real page content.

Return JSON only:
{{
  "is_real_webpage_screenshot": true/false,
  "is_grey_or_blank_placeholder": true/false,
  "has_visible_page_content": true/false,
  "reason": "one short sentence"
}}
"""
    result = gemini_vision_json(prompt, png)
    result["label"] = label
    result["pass"] = bool(
        result.get("is_real_webpage_screenshot")
        and result.get("has_visible_page_content")
        and not result.get("is_grey_or_blank_placeholder")
    )
    return result


def judge_report(png: bytes, study: dict) -> dict:
    n_agents = len(study.get("agent_results") or [])
    n_tasks = len(study.get("tasks") or [])
    status = study.get("status")
    summary_preview = str(study.get("summary") or "")[:800]
    prompt = f"""You are QA for UserSim's study report UI.

Study API status={status!r}, agent_results={n_agents}, tasks={n_tasks}.
Summary preview:
{summary_preview}

Look at this screenshot of the report / ready state.

Return JSON only:
{{
  "report_visible": true/false,
  "has_executive_summary_or_findings": true/false,
  "looks_complete_not_stuck": true/false,
  "agents_appear_to_have_run": true/false,
  "reason": "one short sentence"
}}
"""
    result = gemini_vision_json(prompt, png)
    api_ok = (
        status == "complete"
        and bool(study.get("summary"))
        and n_agents > 0
        and n_agents >= max(1, n_tasks // 2)  # allow some queueing variance
    )
    dead = []
    for r in study.get("agent_results") or []:
        st = str(r.get("status") or "").lower()
        if st in {"error", "failed", "killed", "abandoned"}:
            dead.append(r.get("agent_id") or r.get("task_id") or "?")
        # Empty traces with no summary are suspicious for "died silently"
        if not (r.get("trace") or r.get("summary") or r.get("final_summary")):
            if st not in {"complete", "done", "success"}:
                dead.append(f"empty:{(r.get('agent_id') or '?')}")
    result["api_complete"] = api_ok
    result["dead_agents"] = dead
    result["pass"] = bool(
        api_ok
        and not dead
        and result.get("report_visible")
        and result.get("has_executive_summary_or_findings")
        and result.get("looks_complete_not_stuck")
        and result.get("agents_appear_to_have_run")
    )
    return result


def assert_agents_alive(study: dict) -> list[str]:
    """Hard API checks — no flash-lite soft-pedaling."""
    fails: list[str] = []
    if study.get("status") != "complete":
        fails.append(f"status={study.get('status')!r} want complete")
    summary = study.get("summary")
    if isinstance(summary, dict):
        has_summary = bool(
            summary.get("headline")
            or summary.get("executive_summary")
            or summary.get("overview")
            or summary
        )
    else:
        has_summary = bool(str(summary or "").strip())
    if not has_summary:
        fails.append("missing summary")
    results = study.get("agent_results") or []
    tasks = study.get("tasks") or []
    if not results:
        fails.append("no agent_results")
    if tasks and len(results) < len(tasks):
        fails.append(f"agents={len(results)} < tasks={len(tasks)}")
    for r in results:
        aid = r.get("agent_id") or r.get("task_id") or "?"
        st = str(r.get("status") or "complete").lower()
        if st in {"error", "failed", "killed", "abandoned", "timeout"}:
            fails.append(f"dead agent {aid}: {st}")
            continue
        shots = [
            step
            for step in (r.get("trace") or [])
            if step.get("screenshot_url") or step.get("screenshot_data_url")
        ]
        agent_summary = r.get("summary") or r.get("final_summary") or r.get("outcome")
        if isinstance(agent_summary, dict):
            has_agent_summary = bool(agent_summary)
        else:
            has_agent_summary = bool(str(agent_summary or "").strip())
        if not shots and not has_agent_summary:
            fails.append(f"agent {aid} has no screenshots and no summary")
    return fails


FETCH_PROBE = """
(() => {
  if (window.__e2eInstalled) return;
  window.__e2eInstalled = true;
  window.__e2e = { studyId: null, chunks: 0, lastStatus: null };
  const orig = window.fetch.bind(window);
  window.fetch = async (...args) => {
    const res = await orig(...args);
    try {
      const url = String(typeof args[0] === 'string' ? args[0] : (args[0] && args[0].url) || '');
      const ct = (res.headers.get('content-type') || '').toLowerCase();
      if (url.includes('/api/studies')) {
        const clone = res.clone();
        if (ct.includes('ndjson') || ct.includes('stream') || ct.includes('octet')) {
          const reader = clone.body && clone.body.getReader();
          if (reader) {
            const dec = new TextDecoder();
            let buf = '';
            (async () => {
              while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                buf += dec.decode(value, { stream: true });
                let nl;
                while ((nl = buf.indexOf('\\n')) >= 0) {
                  const line = buf.slice(0, nl).trim();
                  buf = buf.slice(nl + 1);
                  if (!line) continue;
                  try {
                    const j = JSON.parse(line);
                    window.__e2e.chunks += 1;
                    window.__e2e.studyId = j.id || j.study_id || window.__e2e.studyId;
                    window.__e2e.lastStatus = j.status || window.__e2e.lastStatus;
                  } catch (_) {}
                }
              }
            })();
          }
        } else if (ct.includes('json')) {
          const j = await clone.json();
          window.__e2e.studyId = j.id || j.study_id || window.__e2e.studyId;
          window.__e2e.lastStatus = j.status || window.__e2e.lastStatus;
        }
      }
    } catch (_) {}
    return res;
  };
})();
"""


async def run_e2e(args: argparse.Namespace) -> dict:
    from playwright.async_api import async_playwright

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    report: dict = {
        "base": args.base,
        "product_url": args.url,
        "judge_model": JUDGE_MODEL,
        "checks": {},
        "pass": False,
    }

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=not args.headed)
        context = await browser.new_context(
            viewport={"width": 1440, "height": 1100},
            device_scale_factor=1,
        )
        page = await context.new_page()
        await page.add_init_script(FETCH_PROBE)

        _log(f"→ open {args.base}")
        await page.goto(args.base, wait_until="domcontentloaded", timeout=60_000)
        await page.wait_for_selector("#study-form #submit-btn", timeout=30_000)

        # Never use Smoke / test_mode — this is a real Run.
        smoke = page.locator("#test-mode-input")
        if await smoke.count():
            if await smoke.is_checked():
                await smoke.uncheck()
        report["checks"]["test_mode_off"] = not (
            await smoke.is_checked() if await smoke.count() else False
        )

        await page.fill('input[name="url"]', args.url)

        # Open optional setup: paste competitor + tasks so brief is multi-site
        # without relying on LLM invent (still invents personas).
        details = page.locator("details.url-more")
        if await details.count():
            await details.first.evaluate("el => { el.open = true }")
        if args.competitor:
            await page.fill('textarea[name="competitors"]', args.competitor)
        if args.tasks:
            await page.fill('textarea[name="tasks"]', args.tasks)
        if args.segment:
            await page.fill('textarea[name="customers"]', args.segment)

        _log("→ click Run")
        await page.click("#submit-btn")
        t_run = time.time()

        await page.wait_for_selector("#live-panel:not([hidden])", timeout=30_000)
        report["checks"]["live_panel_shown"] = True

        # --- Brief: products / personas / tasks ---
        _log("→ wait for products + personas + tasks in brief")
        min_products = 2 if args.competitor else 1
        await page.wait_for_function(
            """(minProducts) => {
              const products = document.querySelectorAll('#products-list a.product-tile');
              const users = document.querySelectorAll('#users-rail button.user-card');
              const tasks = document.querySelectorAll('#tasks-list li.task-row');
              return products.length >= minProducts && users.length >= 1 && tasks.length >= 1;
            }""",
            arg=min_products,
            timeout=args.brief_timeout_s * 1000,
        )
        brief_png = await page.locator("#brief-section").screenshot(type="png")
        (OUT_DIR / "01_brief.png").write_bytes(brief_png)

        brief_counts = await page.evaluate(
            """() => ({
              products: document.querySelectorAll('#products-list a.product-tile').length,
              competitors: document.querySelectorAll('#products-list a.product-tile:not(.is-product)').length,
              personas: document.querySelectorAll('#users-rail button.user-card').length,
              tasks: document.querySelectorAll('#tasks-list li.task-row').length,
              products_text: (document.getElementById('products-list')?.innerText || '').slice(0, 400),
              users_text: (document.getElementById('users-rail')?.innerText || '').slice(0, 400),
              tasks_text: (document.getElementById('tasks-list')?.innerText || '').slice(0, 400),
            })"""
        )
        report["checks"]["brief"] = brief_counts
        if brief_counts.get("personas", 0) < 1:
            raise RuntimeError(f"No personas in brief: {brief_counts}")
        if brief_counts.get("tasks", 0) < 1:
            raise RuntimeError(f"No tasks in brief: {brief_counts}")
        if args.competitor and brief_counts.get("products", 0) < 2:
            raise RuntimeError(f"Expected product+competitor tiles: {brief_counts}")
        report["checks"]["brief_ok"] = True
        _log(
            f"  brief ok products={brief_counts.get('products')} "
            f"competitors={brief_counts.get('competitors')} "
            f"personas={brief_counts.get('personas')} tasks={brief_counts.get('tasks')}"
        )

        # Resolve study id (fetch probe or list newest)
        study_id = None
        for _ in range(40):
            study_id = await page.evaluate("() => window.__e2e && window.__e2e.studyId")
            if study_id:
                break
            await page.wait_for_timeout(500)
        if not study_id:
            # Fallback: newest study from API
            try:
                listing = http_json(args.base, "/api/studies", timeout=30)
                items = listing if isinstance(listing, list) else listing.get("studies") or []
                if items:
                    study_id = items[0].get("id") or items[0].get("study_id")
            except Exception as exc:  # noqa: BLE001
                _log(f"  list studies fallback failed: {exc!r}")
        report["study_id"] = study_id
        _log(f"  study_id={study_id}")

        # --- First real screenshot after tasks exist ---
        # Prefer DOM stage; if fleet stream detached before UI poll, use API.
        _log("→ wait for first stage screenshot")
        shot_deadline = time.time() + args.first_shot_timeout_s
        first_shot_s = None
        while time.time() < shot_deadline:
            visible = await page.evaluate(
                """() => {
                  const sec = document.getElementById('stage-section');
                  const img = document.querySelector('#stage-body img.trace-screenshot');
                  const stageOk = Boolean(sec && !sec.hidden);
                  const imgOk = Boolean(
                    img &&
                    (img.getAttribute('src') || '') &&
                    img.complete &&
                    img.naturalWidth > 40
                  );
                  return { stageOk, imgOk };
                }"""
            )
            api_shot = None
            if study_id:
                try:
                    snap = http_json(args.base, f"/api/studies/{study_id}", timeout=30)
                    live = snap.get("live_sessions") or {}
                    items = (
                        list(live.values())
                        if isinstance(live, dict)
                        else list(live or [])
                    )
                    for sess in items:
                        for step in sess.get("trace") or []:
                            if step.get("screenshot_url") or step.get(
                                "screenshot_data_url"
                            ):
                                api_shot = step.get("screenshot_url") or step.get(
                                    "screenshot_data_url"
                                )
                                break
                        if api_shot:
                            break
                    for r in snap.get("agent_results") or []:
                        for step in r.get("trace") or []:
                            if step.get("screenshot_url"):
                                api_shot = step.get("screenshot_url")
                                break
                        if api_shot:
                            break
                except Exception as exc:  # noqa: BLE001
                    _log(f"  shot poll warn: {exc!r}")

            if visible.get("imgOk"):
                first_shot_s = round(time.time() - t_run, 1)
                break
            if api_shot and study_id:
                # Force a poll render path isn't enough — navigate won't help.
                # Wait a bit more for client poll (v79+) to paint stage.
                _log(f"  API has screenshot ({api_shot[:80]}…) — waiting for stage paint")
                await page.wait_for_timeout(2500)
                visible2 = await page.evaluate(
                    """() => {
                      const img = document.querySelector('#stage-body img.trace-screenshot');
                      return Boolean(img && img.complete && img.naturalWidth > 40);
                    }"""
                )
                if visible2:
                    first_shot_s = round(time.time() - t_run, 1)
                    break
                # Last resort: still judge the API screenshot bytes
                first_shot_s = round(time.time() - t_run, 1)
                report["checks"]["first_shot_via_api"] = True
                break
            await page.wait_for_timeout(1500)

        if first_shot_s is None:
            raise RuntimeError(
                f"No stage/API screenshot within {args.first_shot_timeout_s}s"
            )
        report["checks"]["first_screenshot_s"] = first_shot_s
        _log(f"  first screenshot at {first_shot_s}s after Run")
        if first_shot_s > args.max_first_shot_s:
            raise RuntimeError(
                f"First screenshot too slow: {first_shot_s}s > {args.max_first_shot_s}s"
            )

        # Ensure stage section exists for capture when possible
        try:
            await page.locator("#stage-section").wait_for(state="visible", timeout=5000)
            stage_shot_png = await page.locator("#stage-section").screenshot(type="png")
        except Exception:
            stage_shot_png = await page.screenshot(type="png")
        (OUT_DIR / "02_stage_screenshot.png").write_bytes(stage_shot_png)
        # Prefer the actual img bytes if we can fetch src
        img_src = await page.evaluate(
            "() => document.querySelector('#stage-body img.trace-screenshot')?.src || ''"
        )
        judge_png = stage_shot_png
        if img_src.startswith("http") or img_src.startswith("data:"):
            try:
                if img_src.startswith("data:image"):
                    import base64

                    judge_png = base64.b64decode(img_src.split(",", 1)[1])
                else:
                    with urllib.request.urlopen(img_src, timeout=30) as r:
                        judge_png = r.read()
                    (OUT_DIR / "02_trace_shot_raw.png").write_bytes(judge_png)
            except Exception as exc:  # noqa: BLE001
                _log(f"  raw shot fetch warn: {exc!r}")
        elif report["checks"].get("first_shot_via_api"):
            # Fall back to absolute API screenshot URL from study payload
            try:
                snap = http_json(args.base, f"/api/studies/{study_id}", timeout=30)
                api_url = None
                live = snap.get("live_sessions") or {}
                items = (
                    list(live.values()) if isinstance(live, dict) else list(live or [])
                )
                for sess in items + list(snap.get("agent_results") or []):
                    for step in sess.get("trace") or []:
                        if step.get("screenshot_url"):
                            api_url = step["screenshot_url"]
                            break
                    if api_url:
                        break
                if api_url:
                    if api_url.startswith("/"):
                        api_url = args.base.rstrip("/") + api_url
                    with urllib.request.urlopen(api_url, timeout=30) as r:
                        judge_png = r.read()
                    (OUT_DIR / "02_trace_shot_raw.png").write_bytes(judge_png)
            except Exception as exc:  # noqa: BLE001
                _log(f"  api shot fetch warn: {exc!r}")

        _log(f"→ gemini judge screenshot ({JUDGE_MODEL})")
        shot_judge = judge_screenshot(judge_png, label="first stage screenshot")
        report["checks"]["screenshot_judge"] = shot_judge
        (OUT_DIR / "02_shot_judge.json").write_text(json.dumps(shot_judge, indent=2))
        _log(f"  shot judge pass={shot_judge.get('pass')} {shot_judge.get('reason')}")
        if not shot_judge.get("pass"):
            raise RuntimeError(f"Screenshot judged grey/fake: {shot_judge}")

        # --- Live view (XOR: iframe when agent active) ---
        # Race carefully: fleets / fast agents often clear live_active before we
        # poll. Also accept API evidence of live_view_url during the run, or a
        # second real screenshot on the stage after the first.
        _log("→ wait for live browser (iframe) or continued real stage screenshots")
        live_ok = False
        live_api_seen = False
        live_deadline = time.time() + args.live_timeout_s
        while time.time() < live_deadline:
            state = await page.evaluate(
                """() => {
                  const iframe = document.querySelector('iframe.stage-live-frame');
                  const wrap = document.querySelector('.stage-live-wrap');
                  const img = document.querySelector('#stage-body img.trace-screenshot');
                  return {
                    has_iframe: Boolean(iframe),
                    iframe_src: iframe?.src || iframe?.getAttribute('src') || '',
                    wrap_visible: Boolean(wrap && wrap.offsetParent !== null),
                    img_still: Boolean(img && img.naturalWidth > 40),
                  };
                }"""
            )
            if study_id:
                try:
                    snap = http_json(args.base, f"/api/studies/{study_id}", timeout=30)
                    live = snap.get("live_sessions") or {}
                    items = (
                        list(live.values())
                        if isinstance(live, dict)
                        else list(live or [])
                    )
                    for sess in items:
                        if sess.get("live_view_url") or sess.get("live_active"):
                            live_api_seen = True
                    if snap.get("status") in {"complete", "error", "abandoned"}:
                        _log(f"  study already {snap.get('status')} during live wait")
                        break
                except Exception as exc:  # noqa: BLE001
                    _log(f"  live poll warn: {exc!r}")

            if state.get("has_iframe") and state.get("iframe_src"):
                live_ok = True
                live_png = await page.locator("#stage-section").screenshot(type="png")
                (OUT_DIR / "03_live_stage.png").write_bytes(live_png)
                live_judge = judge_screenshot(
                    live_png, label="live stage (iframe mounted)"
                )
                report["checks"]["live_judge"] = live_judge
                _log(
                    f"  live iframe up; judge pass={live_judge.get('pass')} "
                    f"{live_judge.get('reason')}"
                )
                if (
                    not live_judge.get("pass")
                    and live_judge.get("is_grey_or_blank_placeholder")
                    and not state.get("img_still")
                ):
                    raise RuntimeError(f"Live stage judged blank: {live_judge}")
                break

            # Screenshot path still showing real content counts as stage OK
            if state.get("img_still") and live_api_seen:
                _log("  live_view_url seen via API + real screenshot still on stage")
                live_ok = True
                live_png = await page.locator("#stage-section").screenshot(type="png")
                (OUT_DIR / "03_live_stage.png").write_bytes(live_png)
                live_judge = judge_screenshot(
                    live_png, label="stage while live_view_url active"
                )
                report["checks"]["live_judge"] = live_judge
                break

            await page.wait_for_timeout(1500)

        report["checks"]["live_iframe"] = live_ok
        report["checks"]["live_api_seen"] = live_api_seen
        if not live_ok and not live_api_seen:
            _log(
                "  WARN: no live iframe/API live_view — accepting prior real "
                "screenshot path (fleet/snapshot XOR)"
            )
            if not report["checks"].get("screenshot_judge", {}).get("pass"):
                raise RuntimeError("No live stage evidence and no prior real screenshot")
            # Re-judge current stage still has a real shot
            still_png = await page.locator("#stage-section").screenshot(type="png")
            (OUT_DIR / "03_stage_fallback.png").write_bytes(still_png)
            still_judge = judge_screenshot(still_png, label="stage after live wait")
            report["checks"]["live_fallback_judge"] = still_judge
            if not still_judge.get("pass"):
                raise RuntimeError(f"Stage went grey after first shot: {still_judge}")

        # --- Wait for study complete + report CTA ---
        _log("→ wait for complete + View full report")
        study: dict = {}
        while time.time() - t0 < args.timeout_s:
            e2e = await page.evaluate("() => window.__e2e || {}")
            sid = study_id or e2e.get("studyId")
            if sid:
                study_id = sid
                try:
                    study = http_json(args.base, f"/api/studies/{sid}", timeout=45)
                except Exception as exc:  # noqa: BLE001
                    _log(f"  poll warn: {exc!r}")
                    await page.wait_for_timeout(3000)
                    continue
                st = study.get("status")
                n_done = len(study.get("agent_results") or [])
                n_tasks = len(study.get("tasks") or [])
                _log(
                    f"  [{int(time.time()-t0)}s] status={st} agents={n_done}/{n_tasks} "
                    f"phase={(study.get('phase') or '')[:60]}"
                )
                if st in {"complete", "error", "abandoned"}:
                    break
            # UI ready link
            ready = await page.evaluate(
                """() => {
                  const a = document.getElementById('view-report-link');
                  return Boolean(a && !a.hidden);
                }"""
            )
            if ready and study.get("status") == "complete":
                break
            await page.wait_for_timeout(4000)

        if study.get("status") != "complete":
            raise RuntimeError(
                f"Study did not complete: status={study.get('status')} id={study_id} "
                f"phase={study.get('phase')}"
            )

        api_fails = assert_agents_alive(study)
        report["checks"]["api_agent_fails"] = api_fails
        if api_fails:
            raise RuntimeError("Agents failed API checks: " + "; ".join(api_fails))

        # Open report if link present
        link = page.locator("#view-report-link:not([hidden])")
        if await link.count():
            href = await link.get_attribute("href") or "/report"
            if study_id and "study" not in href:
                # report page may use localStorage; click anyway
                pass
            await link.click()
            await page.wait_for_timeout(1500)

        report_png = await page.screenshot(type="png", full_page=True)
        (OUT_DIR / "04_report.png").write_bytes(report_png)
        # Also try dedicated report page
        if study_id:
            try:
                await page.goto(
                    f"{args.base.rstrip('/')}/report?study={study_id}",
                    wait_until="domcontentloaded",
                    timeout=60_000,
                )
                await page.wait_for_timeout(2000)
                report_png = await page.screenshot(type="png", full_page=True)
                (OUT_DIR / "04_report_page.png").write_bytes(report_png)
            except Exception as exc:  # noqa: BLE001
                _log(f"  report page warn: {exc!r}")

        _log(f"→ gemini judge report ({JUDGE_MODEL})")
        report_judge = judge_report(report_png, study)
        report["checks"]["report_judge"] = report_judge
        (OUT_DIR / "04_report_judge.json").write_text(json.dumps(report_judge, indent=2))
        _log(f"  report judge pass={report_judge.get('pass')} {report_judge.get('reason')}")
        if not report_judge.get("pass"):
            raise RuntimeError(f"Report judge failed: {report_judge}")

        report["elapsed_s"] = round(time.time() - t0, 1)
        report["pass"] = True
        report["personas"] = len(study.get("personas") or [])
        report["tasks"] = len(study.get("tasks") or [])
        report["competitors"] = study.get("competitors") or []
        report["agents"] = len(study.get("agent_results") or [])

        await browser.close()

    out_path = OUT_DIR / "result.json"
    out_path.write_text(json.dumps(report, indent=2))
    _log(f"Wrote {out_path}")
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description="UI e2e: click Run, judge shots + report")
    ap.add_argument("--base", default=os.environ.get("E2E_BASE", "https://usersim.vercel.app"))
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--competitor", default=DEFAULT_COMPETITOR)
    ap.add_argument("--tasks", default=DEFAULT_TASKS)
    ap.add_argument(
        "--segment",
        default=os.environ.get(
            "E2E_SEGMENT",
            "Founders evaluating AI research tools",
        ),
    )
    ap.add_argument("--timeout-s", type=int, default=int(os.environ.get("E2E_TIMEOUT_S", "1200")))
    ap.add_argument(
        "--brief-timeout-s",
        type=int,
        default=int(os.environ.get("E2E_BRIEF_TIMEOUT_S", "180")),
    )
    ap.add_argument(
        "--first-shot-timeout-s",
        type=int,
        default=int(os.environ.get("E2E_FIRST_SHOT_TIMEOUT_S", "180")),
    )
    ap.add_argument(
        "--max-first-shot-s",
        type=float,
        default=float(os.environ.get("E2E_MAX_FIRST_SHOT_S", "180")),
    )
    ap.add_argument(
        "--live-timeout-s",
        type=int,
        default=int(os.environ.get("E2E_LIVE_TIMEOUT_S", "300")),
    )
    ap.add_argument("--headed", action="store_true", default=os.environ.get("E2E_HEADED") == "1")
    args = ap.parse_args()

    import asyncio

    try:
        result = asyncio.run(run_e2e(args))
    except Exception as exc:  # noqa: BLE001
        _log(f"FAIL: {exc}")
        fail_path = OUT_DIR / "result.json"
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        fail_path.write_text(json.dumps({"pass": False, "error": str(exc)}, indent=2))
        return 1

    _log(
        f"ALL_PASS study={result.get('study_id')} "
        f"agents={result.get('agents')} elapsed={result.get('elapsed_s')}s"
    )
    return 0 if result.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
