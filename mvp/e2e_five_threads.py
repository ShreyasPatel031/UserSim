#!/usr/bin/env python3
"""Bounded 5-thread UI e2e: personas × tasks × competitor, not the full 5×5×3.

Captures for each of 5 agents:
  1. Real website pixels immediately after tasks appear (≤2s SLA)
  2. Next agent step — screen must change, or live iframe must be up
  3. Every later step — live view required (stale screenshot is a fail)

Then gemini-2.5-flash-lite judges:
  - each landing PNG: is this the real assigned site?
  - each later step: previous vs new — is the screen progressing
    (click, new page, scroll) or stuck on the same frame?

Usage:
  PYTHONPATH=src:. python mvp/e2e_five_threads.py --base https://usersim.vercel.app
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from mvp.e2e_ui_run import (  # noqa: E402
    FETCH_PROBE,
    JUDGE_MODEL,
    _hostname,
    _log,
    http_json,
    judge_progress,
    judge_screenshot,
)

sa = ROOT / "secrets" / "sa.json"
if sa.is_file():
    os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", str(sa))

OUT_DIR = Path(os.environ.get("E2E_FIVE_OUT", ROOT / "results" / "e2e_five_threads"))
PRODUCT = os.environ.get("E2E_PRODUCT_URL", "https://useagency.dev/")
COMPETITOR = os.environ.get("E2E_COMPETITOR", "https://recurse.run/")
TASKS = os.environ.get(
    "E2E_TASKS",
    "Skim the homepage and say the main promise in one sentence\n"
    "Find how to get started or see pricing",
)
SEGMENT = os.environ.get(
    "E2E_SEGMENT",
    "Two people only: a creative marketer evaluating research tools, "
    "and a technical founder comparing vendors.",
)


def _sessions(study: dict) -> list[dict]:
    live = study.get("live_sessions") or {}
    items = list(live.values()) if isinstance(live, dict) else list(live or [])
    return [s for s in items if isinstance(s, dict)]


def _numbered_shots(sess: dict) -> list[dict]:
    out = []
    for step in sess.get("trace") or []:
        if not isinstance(step, dict):
            continue
        if not isinstance(step.get("step"), int):
            continue
        if step.get("progress_only"):
            continue
        if not (step.get("screenshot_url") or step.get("screenshot_data_url")):
            continue
        out.append(step)
    out.sort(key=lambda s: int(s.get("step") or 0))
    return out


def _download(base: str, url: str) -> bytes | None:
    if not url:
        return None
    if url.startswith("data:image"):
        import base64

        try:
            return base64.b64decode(url.split(",", 1)[1])
        except Exception:
            return None
    if url.startswith("/"):
        url = base.rstrip("/") + url
    try:
        with urllib.request.urlopen(url, timeout=45) as resp:
            raw = resp.read()
        return raw if raw and len(raw) > 200 else None
    except Exception:
        return None


def _png_hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()[:16]


def _write_index(out: Path, report: dict) -> None:
    rows = []
    for thread in report.get("threads") or []:
        blocks = []
        for s in thread.get("shots") or []:
            kind = s.get("kind") or ""
            if kind == "after_tasks" or int(s.get("step") or 0) == 0:
                blocks.append(
                    f'<figure><img src="{html_escape(s.get("rel", ""))}" '
                    f'alt="{html_escape(s.get("label", ""))}"/>'
                    f"<figcaption>LANDING · "
                    f"{'PASS' if s.get('judge_pass') else 'FAIL'} · "
                    f"{html_escape(s.get('judge_reason', ''))}</figcaption></figure>"
                )
                continue
            prev = s.get("prev_rel") or ""
            pair = ""
            if prev:
                pair = (
                    f'<div class="pair">'
                    f'<figure><img src="{html_escape(prev)}"/><figcaption>PREVIOUS</figcaption></figure>'
                    f'<figure><img src="{html_escape(s.get("rel", ""))}"/>'
                    f"<figcaption>NEW · step {html_escape(s.get('step'))}</figcaption></figure>"
                    f"</div>"
                )
            else:
                pair = (
                    f'<figure><img src="{html_escape(s.get("rel", ""))}" '
                    f'alt="{html_escape(s.get("label", ""))}"/></figure>'
                )
            verdict = "PASS" if s.get("progress_pass") else "FAIL"
            blocks.append(
                f"<div class=step>{pair}"
                f"<p class={'pass' if s.get('progress_pass') else 'fail'}>"
                f"PROGRESS {verdict} · {html_escape(s.get('progress_reason') or s.get('judge_reason') or '')}"
                f"</p></div>"
            )
        rows.append(
            f"<section><h2>{html_escape(thread.get('agent_id', ''))}</h2>"
            f"<p>{html_escape(thread.get('persona', ''))} · "
            f"{html_escape(thread.get('task', ''))} · "
            f"{html_escape(thread.get('site', ''))}</p>{''.join(blocks)}</section>"
        )
    html = f"""<!doctype html><html><head><meta charset="utf-8"/>
<title>e2e five threads</title>
<style>
body{{font:15px/1.4 ui-sans-serif,system-ui;margin:24px;background:#111;color:#eee}}
img{{max-width:100%;height:auto;border:1px solid #333;background:#000}}
figure{{margin:0 0 1.25rem}}
figcaption{{font-size:12px;color:#bbb;margin-top:.35rem}}
h1,h2{{font-weight:600}}
.pass{{color:#4ade80}}.fail{{color:#f87171}}
.pair{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}
.step{{margin:0 0 1.5rem;padding-bottom:1rem;border-bottom:1px solid #333}}
</style></head><body>
<h1>5-thread e2e {'<span class=pass>PASS</span>' if report.get('pass') else '<span class=fail>FAIL</span>'}</h1>
<pre>{html_escape(json.dumps({k: report.get(k) for k in ('study_id','elapsed_s','after_tasks_s','fails')}, indent=2))}</pre>
{''.join(rows)}
</body></html>"""
    (out / "index.html").write_text(html)


def html_escape(s: str) -> str:
    return (
        str(s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


async def _select_session(page, sess: dict) -> None:
    site_key = sess.get("site_key") or "product"
    site_url = sess.get("site_url") or ""
    persona = sess.get("persona_id") or ""
    raw_id = sess.get("task_id") or sess.get("agent_id") or ""
    task_base = str(raw_id).split("__")[0]
    await page.evaluate(
        """({key, url}) => {
          const chips = [...document.querySelectorAll('#stage-site-switch button')];
          const btn = chips.find((b) => b.getAttribute('data-stage-site-key') === key)
            || chips.find((b) => (b.getAttribute('data-stage-site-url') || '').replace(/\\/$/, '')
                 === String(url || '').replace(/\\/$/, ''));
          btn?.click();
        }""",
        {"key": site_key, "url": site_url},
    )
    await page.wait_for_timeout(200)
    if persona:
        try:
            await page.select_option("#stage-user-select", persona)
        except Exception:
            pass
    if task_base:
        try:
            await page.select_option("#stage-task-select", task_base)
        except Exception:
            pass
    await page.wait_for_timeout(300)


def _stage_state_js() -> str:
    return """() => {
      const sec = document.getElementById('stage-section');
      const img = document.querySelector('#stage-body img.trace-screenshot');
      const iframe = document.querySelector('iframe.stage-live-frame');
      const waiting = document.querySelector('#stage-body .stage-waiting');
      return {
        stageOk: Boolean(sec && !sec.hidden),
        imgOk: Boolean(img && img.complete && img.naturalWidth > 40),
        imgSrc: img?.getAttribute('src') || img?.dataset?.shotSrc || '',
        liveOk: Boolean(iframe && (iframe.src || iframe.getAttribute('src'))),
        liveSrc: iframe?.src || iframe?.getAttribute('src') || '',
        waiting: Boolean(waiting),
        caption: (document.querySelector('#stage-body figcaption')?.innerText || '').slice(0, 160),
      };
    }"""


async def run(args: argparse.Namespace) -> dict:
    from playwright.async_api import async_playwright

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for old in OUT_DIR.glob("*"):
        if old.is_file():
            old.unlink()

    t0 = time.time()
    report: dict = {
        "base": args.base,
        "product_url": args.url,
        "competitor": args.competitor,
        "judge_model": JUDGE_MODEL,
        "threads": [],
        "fails": [],
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

        start_url = args.base.rstrip("/") + "/?max_agents=5"
        _log(f"→ open {start_url}")
        await page.goto(start_url, wait_until="domcontentloaded", timeout=60_000)
        await page.wait_for_selector("#study-form #submit-btn", timeout=30_000)

        smoke = page.locator("#test-mode-input")
        if await smoke.count() and await smoke.is_checked():
            await smoke.uncheck()

        await page.fill('input[name="url"]', args.url)
        details = page.locator("details.url-more")
        if await details.count():
            await details.first.evaluate("el => { el.open = true }")
        await page.fill('textarea[name="customers"]', args.segment)
        await page.fill('textarea[name="competitors"]', args.competitor)
        await page.fill('textarea[name="tasks"]', args.tasks)

        _log("→ click Run (not smoke), max_agents=5")
        await page.click("#submit-btn")

        await page.wait_for_selector("#tasks-list li.task-row", timeout=args.brief_timeout_s * 1000)
        t_tasks = time.time()
        _log(f"  tasks visible at +{t_tasks - t0:.1f}s from start")
        (OUT_DIR / "00_tasks.png").write_bytes(
            await page.locator("#tasks-panel").screenshot(type="png")
        )

        # SLA: real website on stage within 2s of task creation.
        after_tasks_s = None
        stage_png = None
        deadline = t_tasks + args.after_tasks_s
        while time.time() < deadline + 8:  # small grace for paint, still record exact
            st = await page.evaluate(_stage_state_js())
            if st.get("imgOk") or st.get("liveOk"):
                after_tasks_s = round(time.time() - t_tasks, 2)
                stage_png = await page.locator("#stage-section").screenshot(type="png")
                break
            await page.wait_for_timeout(150)
        report["after_tasks_s"] = after_tasks_s
        if stage_png:
            (OUT_DIR / "01_stage_after_tasks.png").write_bytes(stage_png)
        if after_tasks_s is None:
            report["fails"].append("no screenshot or live view after tasks")
        elif after_tasks_s > args.after_tasks_s:
            report["fails"].append(
                f"first screen {after_tasks_s}s after tasks (need ≤{args.after_tasks_s}s)"
            )
        _log(f"  first screen {after_tasks_s}s after tasks")

        study_id = None
        for _ in range(40):
            study_id = await page.evaluate("() => window.__e2e && window.__e2e.studyId")
            if study_id:
                break
            await page.wait_for_timeout(250)
        if not study_id:
            listing = http_json(args.base, "/api/studies", timeout=30)
            items = listing.get("studies") or []
            if items:
                study_id = items[0].get("id")
        report["study_id"] = study_id
        _log(f"  study_id={study_id}")
        if not study_id:
            raise RuntimeError("no study id")

        # Wait until 5 live sessions exist (or timeout).
        agents: list[dict] = []
        wait_agents = time.time() + 90
        while time.time() < wait_agents:
            snap = http_json(args.base, f"/api/studies/{study_id}", timeout=45)
            agents = _sessions(snap)
            if len(agents) >= 5 or (agents and snap.get("phase", "").lower().startswith("opening")):
                if len(agents) >= 1:
                    break
            await page.wait_for_timeout(1000)
        snap = http_json(args.base, f"/api/studies/{study_id}", timeout=45)
        agents = _sessions(snap)
        if len(agents) > 5:
            agents = agents[:5]
        report["agent_count"] = len(agents)
        report["personas"] = [p.get("name") for p in (snap.get("personas") or [])]
        report["tasks_brief"] = [t.get("title") for t in (snap.get("tasks") or [])][:8]
        report["competitors"] = snap.get("competitors") or []
        _log(f"  threads={len(agents)} personas={report['personas']}")

        # Per-thread first landing PNG (must be the assigned site, not a random frame).
        for i, sess in enumerate(agents):
            aid = sess.get("agent_id") or f"a{i}"
            host = _hostname(sess.get("site_url") or args.url)
            thread = {
                "agent_id": aid,
                "persona": sess.get("persona_name"),
                "task": sess.get("task_title"),
                "site": sess.get("site_url") or args.url,
                "site_key": sess.get("site_key"),
                "shots": [],
            }
            # Wait briefly for step 0 of THIS agent.
            raw0 = None
            step0 = None
            for _ in range(40):
                snap = http_json(args.base, f"/api/studies/{study_id}", timeout=45)
                cur = next((s for s in _sessions(snap) if s.get("agent_id") == aid), sess)
                shots = _numbered_shots(cur)
                if shots:
                    step0 = shots[0]
                    raw0 = _download(
                        args.base,
                        step0.get("screenshot_data_url") or step0.get("screenshot_url") or "",
                    )
                    if raw0:
                        break
                await page.wait_for_timeout(500)
            if raw0:
                name = f"t{i}_{aid}_step0.png"
                (OUT_DIR / name).write_bytes(raw0)
                try:
                    judge = judge_screenshot(raw0, label=f"{aid} step0", expected_host=host)
                except Exception as exc:  # noqa: BLE001
                    judge = {"pass": False, "reason": f"landing judge error: {exc}"}
                thread["shots"].append(
                    {
                        "kind": "after_tasks",
                        "step": step0.get("step") if step0 else 0,
                        "label": f"{aid} step 0 — {host}",
                        "rel": name,
                        "sha": _png_hash(raw0),
                        "judge_pass": bool(judge.get("pass")),
                        "judge_reason": judge.get("reason"),
                        "judge": judge,
                    }
                )
                if not judge.get("pass"):
                    report["fails"].append(f"{aid} step0 not the real {host} site: {judge.get('reason')}")
                _log(f"  {aid} step0 judge={judge.get('pass')} {judge.get('reason')}")
            else:
                report["fails"].append(f"{aid} missing landing PNG")
            thread["sha0"] = thread["shots"][-1]["sha"] if thread["shots"] else None
            thread["last_rel"] = thread["shots"][-1]["rel"] if thread["shots"] else None
            thread["last_site_raw"] = raw0
            await _select_session(page, sess)
            try:
                thread["last_ui_raw"] = await page.locator("#stage-section").screenshot(type="png")
            except Exception:
                thread["last_ui_raw"] = raw0
            report["threads"].append(thread)

        # Follow steps until each agent has step>=1 or study ends.
        seen: dict[str, set[int]] = {t["agent_id"]: set() for t in report["threads"]}
        for t in report["threads"]:
            if t["shots"]:
                seen[t["agent_id"]].add(int(t["shots"][0].get("step") or 0))

        follow_deadline = time.time() + args.steps_timeout_s
        while time.time() < follow_deadline:
            snap = http_json(args.base, f"/api/studies/{study_id}", timeout=45)
            st = snap.get("status")
            for i, thread in enumerate(report["threads"]):
                aid = thread["agent_id"]
                cur = next((s for s in _sessions(snap) if s.get("agent_id") == aid), None)
                if not cur:
                    continue
                host = _hostname(cur.get("site_url") or args.url)
                for step in _numbered_shots(cur):
                    n = int(step.get("step") or 0)
                    if n in seen[aid]:
                        continue
                    raw = _download(
                        args.base,
                        step.get("screenshot_data_url") or step.get("screenshot_url") or "",
                    )
                    await _select_session(page, cur)
                    ui_state = await page.evaluate(_stage_state_js())
                    ui_png = await page.locator("#stage-section").screenshot(type="png")
                    ui_name = f"t{i}_{aid}_step{n}_ui.png"
                    (OUT_DIR / ui_name).write_bytes(ui_png)

                    live_required = n >= 1
                    live_ok = bool(ui_state.get("liveOk"))
                    changed = True
                    sha = None
                    site_png = raw
                    if raw:
                        fname = f"t{i}_{aid}_step{n}.png"
                        (OUT_DIR / fname).write_bytes(raw)
                        sha = _png_hash(raw)
                        if thread.get("sha0") and sha == thread["sha0"] and n >= 1:
                            changed = False
                    else:
                        fname = ui_name
                        # Missing file for later step — only OK if live is showing.
                        if not live_ok:
                            report["fails"].append(f"{aid} step {n} PNG missing and no live view")
                        changed = live_ok

                    if live_required and not live_ok:
                        report["fails"].append(
                            f"{aid} step {n}: live screen required, still showing screenshot only"
                        )
                    if live_required and not changed and not live_ok:
                        report["fails"].append(
                            f"{aid} step {n}: pixels identical to step 0 (screen did not change)"
                        )

                    prev_rel = thread.get("last_rel")
                    if site_png and thread.get("last_site_raw"):
                        prev_raw, new_raw = thread["last_site_raw"], site_png
                    else:
                        prev_raw, new_raw = thread.get("last_ui_raw"), ui_png
                    progress = None
                    progress_pass = False
                    progress_reason = ""
                    if n >= 1 and prev_raw and new_raw:
                        action = str(step.get("action") or "")
                        try:
                            progress = judge_progress(
                                prev_raw,
                                new_raw,
                                label=f"{aid} step{n-1}→{n}",
                                persona=str(thread.get("persona") or ""),
                                task=str(thread.get("task") or ""),
                                action=action,
                                expected_host=host,
                            )
                        except Exception as exc:  # noqa: BLE001
                            progress = {
                                "pass": False,
                                "stuck": True,
                                "reason": f"progress judge error: {exc}",
                            }
                        progress_pass = bool(progress.get("pass"))
                        progress_reason = str(progress.get("reason") or "")
                        if not progress_pass:
                            report["fails"].append(
                                f"{aid} step {n}: not progressing vs previous — {progress_reason}"
                            )
                        _log(
                            f"  {aid} step {n} progress={progress_pass} "
                            f"same={progress.get('screens_look_the_same')} "
                            f"{progress_reason}"
                        )
                    elif n >= 1:
                        progress_reason = "no previous+new PNG pair to judge"
                        report["fails"].append(f"{aid} step {n}: {progress_reason}")

                    judge = None
                    judge_pass = progress_pass if n >= 1 else live_ok
                    reason = progress_reason or ("live iframe mounted" if live_ok else "")
                    if site_png and n == 0:
                        judge = judge_screenshot(
                            site_png, label=f"{aid} step{n}", expected_host=host
                        )
                        judge_pass = bool(judge.get("pass"))
                        reason = judge.get("reason") or reason
                        if not judge_pass:
                            report["fails"].append(f"{aid} step{n} judge fail: {reason}")

                    thread["shots"].append(
                        {
                            "kind": "step" if n >= 1 else "after_tasks",
                            "step": n,
                            "label": f"{aid} step {n} — {step.get('action') or ''} "
                            f"{'(LIVE)' if live_ok else '(shot)'}",
                            "rel": fname,
                            "prev_rel": prev_rel,
                            "ui_rel": ui_name,
                            "sha": sha,
                            "changed_from_step0": changed,
                            "live_ok": live_ok,
                            "judge_pass": judge_pass,
                            "judge_reason": reason,
                            "judge": judge,
                            "progress_pass": progress_pass,
                            "progress_reason": progress_reason,
                            "progress": progress,
                        }
                    )
                    thread["last_rel"] = fname
                    if site_png:
                        thread["last_site_raw"] = site_png
                    thread["last_ui_raw"] = ui_png
                    seen[aid].add(n)
                    _log(
                        f"  {aid} step {n} live={live_ok} changed={changed} "
                        f"judge={judge_pass} {reason}"
                    )
            if st in {"complete", "error", "abandoned"}:
                break
            # Need at least one step>=1 on every thread, or keep going until timeout.
            have_next = all(
                any(int(s.get("step") or 0) >= 1 for s in t.get("shots") or [])
                for t in report["threads"]
            )
            if have_next and all(len(t.get("shots") or []) >= 2 for t in report["threads"]):
                # Collect a bit more, then stop if study still running too long.
                if time.time() - t0 > 180:
                    break
            await page.wait_for_timeout(2000)

        await browser.close()

    for t in report["threads"]:
        if not any(s.get("kind") == "after_tasks" for s in t.get("shots") or []):
            report["fails"].append(f"{t['agent_id']} never got after-tasks website shot")
        if not any(int(s.get("step") or 0) >= 1 for s in t.get("shots") or []):
            report["fails"].append(f"{t['agent_id']} never reached step ≥ 1")

    report["elapsed_s"] = round(time.time() - t0, 1)
    report["pass"] = not report["fails"]
    for t in report["threads"]:
        t.pop("last_raw", None)
        t.pop("last_site_raw", None)
        t.pop("last_ui_raw", None)
    (OUT_DIR / "result.json").write_text(json.dumps(report, indent=2, default=str))
    _write_index(OUT_DIR, report)
    _log(f"Wrote {OUT_DIR / 'result.json'} pass={report['pass']} fails={report['fails']}")
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description="5-thread UI e2e with flash-lite judges")
    ap.add_argument("--base", default=os.environ.get("E2E_BASE", "https://usersim.vercel.app"))
    ap.add_argument("--url", default=PRODUCT)
    ap.add_argument("--competitor", default=COMPETITOR)
    ap.add_argument("--tasks", default=TASKS)
    ap.add_argument("--segment", default=SEGMENT)
    ap.add_argument("--brief-timeout-s", type=int, default=180)
    ap.add_argument("--after-tasks-s", type=float, default=2.0)
    ap.add_argument("--steps-timeout-s", type=int, default=600)
    ap.add_argument("--headed", action="store_true", default=os.environ.get("E2E_HEADED") == "1")
    args = ap.parse_args()
    import asyncio

    try:
        result = asyncio.run(run(args))
    except Exception as exc:  # noqa: BLE001
        _log(f"FAIL: {exc}")
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        (OUT_DIR / "result.json").write_text(json.dumps({"pass": False, "error": str(exc)}, indent=2))
        return 1
    return 0 if result.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
