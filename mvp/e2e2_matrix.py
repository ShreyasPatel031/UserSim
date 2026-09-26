#!/usr/bin/env python3
"""e2e2: real Run button → matrix of users × tasks × sites → strict gates.

Clicks Run (never Smoke). While agents run, Ready/View-full-report must stay
hidden. Vision checks use the screenshot bytes the agents already saved
(not UserSim chrome, not a Preparing pulse, not a grey pane) and do not
click through the live stage during the run.

Startup gates still apply (24 agents, each first real screenshot within 5s,
a vision YES). The study budget is 8 minutes (480s), confirmed above the
observed strict-e2e maximum of 408s. There is no per-agent time limit; a stuck
agent repeats the same action 3 times with no URL or DOM change. While the
study runs, the harness aborts if any agent still has no click/type/scroll
once the time_to_first_action max is clearly blown (default 10s after that
agent's first real screenshot; --first-action-s loosens only that abort), if
Root CDP client init fails, or if Browserbase session drops pass 25% of agents.
Vision and screenshot checks read PNGs the agents already saved. They do not
drive the live page while agents run. The summary leads with two clocks from
the Run click: time_to_first_value (<= 10s until the first click/type/scroll
is visible) and total_time (until the report is ready, within 8 minutes).
pass=true only when the independent
goal-judge verdicts and the report checks all pass. Agent summaries are not a
pass signal. Failed runs are written to failures.json.

  MVP_BB_OWNER=testfix PYTHONPATH=src:. python mvp/e2e2_matrix.py \\
    --base http://127.0.0.1:3000 --url https://linear.app \\
    --competitors $'https://asana.com/\\nhttps://trello.com/' \\
    --tasks $'Find how to create a new issue\\nLook for pricing or how to get started' \\
    --segment 'Product managers comparing issue trackers' \\
    --expected 24 --max-agents 24 --max-elapsed-s 480 --first-shot-s 5 \\
    --first-action-s 10
"""

from __future__ import annotations

import argparse
import asyncio
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

from mvp.e2e_ui_run import (  # noqa: E402
    FETCH_PROBE,
    JUDGE_MODEL,
    _hostname,
    judge_screenshot,
    http_json,
)
from mvp.e2e2_gates import (  # noqa: E402
    DEFAULT_STUDY_BUDGET_S,
    DEFAULT_TTFA_ABORT_S,
    DEFAULT_TTFA_MAX_S,
    DEFAULT_TTFA_MEDIAN_S,
    assess_infrastructure_abort,
    assess_stuck_abort,
    assess_time_to_first_action,
    build_early_failures,
    coerce_verdict,
    evaluate_strict_gates,
    final_dom_of,
    final_url_of,
    has_click_type_scroll,
    iter_runs,
    judge_goal_screenshot,
    render_markdown,
)

sa = ROOT / "secrets" / "sa.json"
if sa.is_file():
    os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", str(sa))

OUT_DIR = Path(os.environ.get("E2E2_OUT_DIR", "/tmp/usersim_e2e2"))
# Default: 4 personas × 2 tasks × 3 sites = 24 (fits Browserbase 25-slot budget).
DEFAULT_EXPECTED = int(os.environ.get("E2E2_EXPECTED", "24") or "24")
# Only a full 24-agent matrix can PASS. Smaller runs are smoke-only.
PASS_AGENT_BAR = int(os.environ.get("E2E2_PASS_AGENT_BAR", "24") or "24")
# Study-level budget. Observed strict-e2e max is 408s (YouTube baseline);
# saved 24-agent studies finished in <= 358s wall, measured e2e2 elapsed <= 378s.
DEFAULT_MAX_ELAPSED_S = float(
    os.environ.get("E2E2_MAX_ELAPSED_S", str(int(DEFAULT_STUDY_BUDGET_S)))
    or str(int(DEFAULT_STUDY_BUDGET_S))
)
# Per-agent: first screenshot must land within this many seconds of that
# session's own creation (Shreyas: a few seconds after task creation).
DEFAULT_FIRST_SHOT_S = float(os.environ.get("E2E2_FIRST_SHOT_S", "5") or "5")


def _log(msg: str) -> None:
    print(msg, flush=True)


def _sessions(study: dict) -> list[dict]:
    live = study.get("live_sessions") or {}
    items = list(live.values()) if isinstance(live, dict) else list(live or [])
    by_id: dict[str, dict] = {}
    for s in items:
        if isinstance(s, dict) and (s.get("agent_id") or s.get("task_id")):
            by_id[str(s.get("agent_id") or s.get("task_id"))] = s
    for r in study.get("agent_results") or []:
        if not isinstance(r, dict):
            continue
        rid = str(r.get("agent_id") or r.get("task_id") or "")
        if rid:
            by_id[rid] = {**by_id.get(rid, {}), **r}
    return list(by_id.values())


def _parse_ts(value: object) -> float | None:
    """Parse server-side epoch float or ISO timestamp into epoch seconds."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        pass
    try:
        from datetime import datetime

        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text).timestamp()
    except Exception:
        return None


def _sess_created_ts(sess: dict) -> float | None:
    return _parse_ts(sess.get("created_at_ts")) or _parse_ts(sess.get("created_at"))


def _sess_has_real_shot(sess: dict) -> bool:
    """True when trace has a judge-acceptable (non-placeholder, non-blankish) frame."""
    for step in sess.get("trace") or []:
        if not isinstance(step, dict):
            continue
        if not isinstance(step.get("step"), int) or not step.get("screenshot_url"):
            continue
        if step.get("opening_placeholder") or step.get("opening_blankish"):
            continue
        return True
    return False


def _sess_first_shot_ts(sess: dict) -> float | None:
    """First REAL screenshot time — placeholders / blank splash do not count."""
    if not _sess_has_real_shot(sess):
        return None
    stamped = _parse_ts(sess.get("first_screenshot_at_ts")) or _parse_ts(
        sess.get("first_screenshot_at")
    )
    if stamped is not None:
        return stamped
    # Fallback for older servers: no step-level timestamp available.
    return None


def _percentile(sorted_vals: list[float], p: float) -> float | None:
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return round(sorted_vals[0], 3)
    idx = (len(sorted_vals) - 1) * (p / 100.0)
    lo = int(idx)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = idx - lo
    return round(sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac, 3)


def _per_agent_shot_latencies(sessions: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for sess in sessions:
        aid = str(sess.get("agent_id") or sess.get("task_id") or "")
        created = _sess_created_ts(sess)
        shot = _sess_first_shot_ts(sess)
        gap = None
        if created is not None and shot is not None:
            gap = round(shot - created, 3)
        rows.append(
            {
                "agent_id": aid,
                "created_at_ts": created,
                "first_screenshot_at_ts": shot,
                "creation_to_first_shot_s": gap,
            }
        )
    return rows


def _timing_summary(t0: float, sessions: list[dict], expected: int) -> dict:
    rows = _per_agent_shot_latencies(sessions)
    created_list = sorted(
        r["created_at_ts"] for r in rows if r["created_at_ts"] is not None
    )
    gaps = sorted(
        r["creation_to_first_shot_s"]
        for r in rows
        if r["creation_to_first_shot_s"] is not None
    )
    first_created_s = (
        round(created_list[0] - t0, 3) if created_list else None
    )
    all_created_s = None
    if created_list and len(created_list) >= expected:
        all_created_s = round(created_list[expected - 1] - t0, 3)
    elif created_list:
        all_created_s = round(created_list[-1] - t0, 3)
    return {
        "run_click_to_first_task_created_s": first_created_s,
        "run_click_to_all_tasks_created_s": all_created_s,
        "creation_to_first_shot_s": {
            "p50": _percentile(gaps, 50),
            "p95": _percentile(gaps, 95),
            "max": round(max(gaps), 3) if gaps else None,
            "n": len(gaps),
            "missing_shot": sum(1 for r in rows if r["first_screenshot_at_ts"] is None),
            "missing_created": sum(1 for r in rows if r["created_at_ts"] is None),
        },
        "per_agent": rows,
    }


def _best_shot(sess: dict) -> dict | None:
    bad = re.compile(r"^(preparing|opening|thinking|signed-in cookies|waiting)\b", re.I)
    ranked: list[dict] = []
    for step in sess.get("trace") or []:
        if not isinstance(step, dict) or not isinstance(step.get("step"), int):
            continue
        if not step.get("screenshot_url"):
            continue
        if bad.search(str(step.get("action") or "")):
            continue
        # Immediate-start placeholders / blankish warm splash — wait for paint.
        if step.get("opening_placeholder") or step.get("opening_blankish"):
            continue
        ranked.append(step)
    ranked.sort(key=lambda s: int(s.get("step") or 0), reverse=True)
    return ranked[0] if ranked else None


def _png_looks_blank(raw: bytes) -> bool:
    """Skip judging pure-black / splash frames while the agent is still painting.

    Dark SaaS themes (Linear, etc.) are real pages with low mean luminance but
    substantial PNG payloads — only treat those as blank when nearly uniform.
    """
    if len(raw) < 2500:
        return True
    try:
        from io import BytesIO

        from PIL import Image

        im = Image.open(BytesIO(raw)).convert("RGB").resize((64, 40))
        pixels = list(im.getdata())
        lums = [0.2126 * r + 0.7152 * g + 0.0722 * b for r, g, b in pixels]
        mean = sum(lums) / max(1, len(lums))
        var = sum((x - mean) ** 2 for x in lums) / max(1, len(lums))
        # Small payloads: logo-on-black splash (~32KB) or empty pane.
        if len(raw) < 48000:
            if mean < 25.0:
                return True
            if mean < 40.0 and var < 250.0:
                return True
            return False
        # Large payloads: only reject near-uniform near-black (empty canvas),
        # not dark but textured product UIs.
        if mean < 12.0 and var < 80.0:
            return True
        return False
    except Exception:
        return len(raw) < 48000


def _fetch_png(base: str, url: str, *, study_id: str = "", agent_id: str = "") -> bytes:
    candidates = [url]
    if "/screenshots/" in url:
        name = url.rstrip("/").split("/")[-1]
        prefix = url[: url.rfind("/") + 1]
        m = re.fullmatch(r"(step|bbox)_(\d+)\.png", name)
        if m:
            kind, num = m.group(1), m.group(2)
            candidates.append(prefix + ("bbox" if kind == "step" else "step") + f"_{num}.png")
            if num != "0":
                candidates.append(prefix + "step_0.png")
    last_err: Exception | None = None
    for cand in candidates:
        href = cand if cand.startswith("http") else base.rstrip("/") + cand
        try:
            with urllib.request.urlopen(href, timeout=45) as resp:
                raw = resp.read()
            if raw[:8] == b"\x89PNG\r\n\x1a\n" and len(raw) > 2000:
                return raw
        except Exception as exc:  # noqa: BLE001
            last_err = exc
    if study_id and agent_id:
        try:
            from mvp.gcs_store import gcs_download_bytes, screenshot_gcs_uri

            for name in ("step_0.png", "bbox_1.png", "bbox_0.png"):
                raw = gcs_download_bytes(screenshot_gcs_uri(study_id, agent_id, name))
                if raw and raw[:8] == b"\x89PNG\r\n\x1a\n" and len(raw) > 2000:
                    return raw
        except Exception as exc:  # noqa: BLE001
            last_err = exc
    raise RuntimeError(f"no downloadable PNG ({last_err!r})")


def _ready_visible_js() -> str:
    return """() => {
      const el = document.getElementById('view-report-link');
      if (!el) return false;
      const st = getComputedStyle(el);
      return (
        !el.hidden &&
        st.display !== 'none' &&
        st.visibility !== 'hidden' &&
        st.opacity !== '0'
      );
    }"""


async def _assert_ready_hidden(page, study: dict) -> None:
    status = str(study.get("status") or "")
    if status == "complete" and study.get("summary"):
        return
    visible = await page.evaluate(_ready_visible_js())
    if visible:
        raise RuntimeError(
            f"Ready/View full report is VISIBLE while status={status!r} "
            f"phase={(study.get('phase') or '')[:80]!r}"
        )


def _score_saved_frames(
    *,
    base: str,
    product_url: str,
    study: dict,
    sessions: list,
    study_id: str,
    judged: dict,
    expected: int,
) -> None:
    """Vision-check PNGs the agents already saved. Does not drive a browser."""
    for sess in sessions:
        aid = str(sess.get("agent_id") or sess.get("task_id") or "")
        if not aid or aid in judged:
            continue
        shot = _best_shot(sess)
        if not shot:
            continue
        try:
            raw = _fetch_png(
                base,
                shot["screenshot_url"],
                study_id=study_id,
                agent_id=aid,
            )
            if _png_looks_blank(raw):
                if study.get("status") == "running":
                    _log(
                        f"  skip blankish shot {aid} step={shot.get('step')} "
                        f"({len(raw)} bytes) — waiting for paint"
                    )
                    continue
                _log(
                    f"  blankish after complete {aid} step={shot.get('step')} "
                    f"({len(raw)} bytes) — counting as miss"
                )
                judged[aid] = {
                    "agent_id": aid,
                    "host": _hostname(sess.get("site_url") or shot.get("url") or product_url),
                    "step": shot.get("step"),
                    "bytes": len(raw),
                    "pass": False,
                    "reason": "blank/splash frame after study complete",
                }
                continue
            host = _hostname(sess.get("site_url") or shot.get("url") or product_url)
            verdict = judge_screenshot(
                raw,
                label=f"{aid} step={shot.get('step')}",
                expected_host=host,
            )
            (OUT_DIR / f"{aid}.png").write_bytes(raw)
            judged[aid] = {
                "agent_id": aid,
                "host": host,
                "step": shot.get("step"),
                "bytes": len(raw),
                **verdict,
            }
            _log(
                f"  judge {len(judged)}/{expected} {aid} "
                f"host={host} pass={verdict.get('pass')} "
                f"{verdict.get('reason')}"
            )
            if not verdict.get("pass") and study.get("status") == "running":
                _log(
                    f"  defer NO {aid} step={shot.get('step')}: "
                    f"{verdict.get('reason')}"
                )
                judged.pop(aid, None)
        except Exception as exc:  # noqa: BLE001
            _log(f"  judge skip {aid}: {exc!r}")


def _release_testfix_sessions(study_id: str = "") -> None:
    """Release only strict-e2e sessions. Never signup, report, or other e2e owners."""
    try:
        from mvp.kill_switch import kill_all_browserbase

        released = kill_all_browserbase(
            owner="testfix",
            study_id=study_id or None,
        )
        _log(f"released browserbase owner=testfix study={study_id or '*'} {released}")
    except Exception as exc:  # noqa: BLE001
        _log(f"browserbase release failed: {exc!r}")


def _stop_study(base: str, study_id: str) -> None:
    """Stop this study via the API, then release its owner-tagged sessions."""
    if not study_id:
        return
    body = json.dumps(
        {
            "agents": True,
            "vms": False,
            "seeds": False,
            "study_id": study_id,
        }
    ).encode()
    req = urllib.request.Request(
        base.rstrip("/") + "/api/runtime/kill",
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            payload = resp.read().decode("utf-8", "replace")
        _log(f"  stopped study {study_id} via /api/runtime/kill ({len(payload)} bytes)")
    except Exception as exc:  # noqa: BLE001
        _log(f"  stop study via API failed: {exc!r}")
    _release_testfix_sessions(study_id)


def _fetch_report_html(base: str, study_id: str) -> tuple[str, str]:
    url = f"{base.rstrip('/')}/report?study={study_id}"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            return resp.read().decode("utf-8", "replace"), url
    except Exception as exc:  # noqa: BLE001
        _log(f"  report page fetch failed: {exc!r}")
        return "", url


def _screenshot_loader(base: str, study_id: str):
    cache: dict[str, bool] = {}

    def loads(url: str) -> bool:
        if url in cache:
            return cache[url]
        try:
            raw = _fetch_png(base, url, study_id=study_id)
            ok = bool(raw) and raw[:8] == b"\x89PNG\r\n\x1a\n"
        except Exception:
            ok = False
        cache[url] = ok
        return ok

    return loads


def _final_trace_shot(run: dict) -> dict | None:
    last = None
    for step in run.get("trace") or []:
        if isinstance(step, dict) and step.get("screenshot_url") and isinstance(step.get("step"), int):
            if step.get("opening_placeholder") or step.get("opening_blankish"):
                continue
            last = step
    return last


def _goal_verdicts(study: dict, base: str) -> dict[str, dict]:
    """Judge every run from its final screenshot, URL, and DOM.

    The verdict is independent of the agent's summary. Runs with no screenshot
    get an explicit NO rather than a skip.
    """
    verdicts: dict[str, dict] = {}
    study_id = str(study.get("id") or "")
    for run in iter_runs(study):
        aid = str(run.get("agent_id") or run.get("task_id") or "")
        if not aid:
            continue
        start = str(run.get("site_url") or study.get("url") or "")
        task = str(run.get("task_prompt") or run.get("task_title") or "")
        final_url = final_url_of(run)
        dom = final_dom_of(run)
        shot = _final_trace_shot(run)
        if not shot:
            verdicts[aid] = coerce_verdict(
                {
                    "goal_reached": False,
                    "still_on_opening_screen": True,
                    "reason": "No final screenshot to judge.",
                }
            )
            _log(f"  goal {aid} reached=False (no final screenshot)")
            continue
        try:
            raw = _fetch_png(base, shot["screenshot_url"], study_id=study_id, agent_id=aid)
            verdict = judge_goal_screenshot(
                raw,
                task=task,
                start_url=start,
                final_url=final_url,
                dom=dom,
            )
            verdicts[aid] = verdict
            _log(
                f"  goal {aid} reached={verdict.get('goal_reached')} "
                f"opening={verdict.get('still_on_opening_screen')} "
                f"url={final_url} {verdict.get('reason')}"
            )
        except Exception as exc:  # noqa: BLE001
            verdicts[aid] = coerce_verdict(
                {
                    "goal_reached": False,
                    "still_on_opening_screen": False,
                    "reason": f"Judge failed: {exc}",
                }
            )
            _log(f"  goal judge failed {aid}: {exc!r}")
    return verdicts


async def run_e2e2(args: argparse.Namespace) -> dict:
    from playwright.async_api import async_playwright

    expected = int(args.expected)
    want_personas = int(args.min_personas)
    want_tasks = int(args.min_tasks)
    want_sites = int(args.min_sites)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    report: dict = {
        "base": args.base,
        "product_url": args.url,
        "judge_model": JUDGE_MODEL,
        "expected": expected,
        "pass": False,
        "yeses": 0,
        "judgements": [],
    }

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=not args.headed)
        page = await (await browser.new_context(
            viewport={"width": 1440, "height": 1100}
        )).new_page()
        await page.add_init_script(FETCH_PROBE)

        start = args.base.rstrip("/")
        if args.max_agents and args.max_agents > 0:
            start = f"{start}/?max_agents={int(args.max_agents)}"
        _log(f"→ open {start} url={args.url}")
        await page.goto(start, wait_until="domcontentloaded", timeout=60_000)
        await page.wait_for_selector("#study-form #submit-btn", timeout=30_000)

        study_id = args.study_id
        t_submit: float | None = None
        t_first_value: float | None = None
        t_report_ready: float | None = None
        first_value_agent = ""
        if not study_id:
            smoke = page.locator("#test-mode-input")
            if await smoke.count() and await smoke.is_checked():
                await smoke.uncheck()

            await page.fill('input[name="url"]', args.url)
            details = page.locator("details.url-more")
            if await details.count():
                await details.first.evaluate("el => { el.open = true }")
            await page.fill('textarea[name="competitors"]', args.competitors)
            await page.fill('textarea[name="tasks"]', args.tasks)
            if args.segment:
                await page.fill('textarea[name="customers"]', args.segment)

            _log("→ click Run (not Smoke)")
            t_submit = time.time()
            await page.click("#submit-btn")
        else:
            _log(f"→ attach study {study_id} (no new Run)")
        study: dict = {}
        judged: dict[str, dict] = {}
        t_first_task: float | None = None
        t_all_tasks: float | None = None
        queued_hits = 0
        abort_reason: str | None = None
        early_abort: dict | None = None
        elapsed_at_abort: float | None = None
        ttfa_check: dict | None = None
        action_seen_at: dict[str, float] = {}
        since_task_last: float | None = None
        action_clock_open = True

        while time.time() - t0 < args.timeout_s:
            if not study_id:
                e2e = await page.evaluate("() => window.__e2e || {}")
                study_id = e2e.get("studyId") or ""
            if study_id:
                try:
                    study = http_json(args.base, f"/api/studies/{study_id}", timeout=8)
                except Exception as exc:  # noqa: BLE001
                    _log(f"  poll warn: {exc!r}")
                    await asyncio.sleep(0.4)
                    continue
            await _assert_ready_hidden(page, study)
            if (
                t_report_ready is None
                and study.get("status") == "complete"
                and study.get("summary")
            ):
                t_report_ready = time.time()
                anchor = t_submit if t_submit is not None else t0
                _log(f"  report_ready +{t_report_ready - anchor:.1f}s")

            personas = study.get("personas") or []
            tasks = study.get("tasks") or []
            comps = study.get("competitors") or []
            sessions = _sessions(study)
            n_unique_tasks = len({
                str(t.get("id") or "").split("__")[0] for t in tasks if t.get("id")
            })
            done_n = sum(1 for s in sessions if s.get("status") == "complete")
            step_n = sum(
                1
                for s in sessions
                for st in (s.get("trace") or [])
                if isinstance(st, dict) and isinstance(st.get("step"), int)
            )
            if sessions and t_first_task is None:
                t_first_task = time.time()
                _log(f"  first_task_created +{t_first_task - t0:.1f}s n={len(sessions)}")
            if (
                sessions
                and t_all_tasks is None
                and len(sessions) >= expected
            ):
                t_all_tasks = time.time()
                _log(f"  all_tasks_created +{t_all_tasks - t0:.1f}s n={len(sessions)}")

            # Per-agent immediate start: creation → first screenshot ≤ budget.
            now = time.time()
            overdue: list[str] = []
            for sess in sessions:
                aid = str(sess.get("agent_id") or sess.get("task_id") or "")
                created = _sess_created_ts(sess)
                shot = _sess_first_shot_ts(sess)
                if created is None:
                    continue
                if shot is not None:
                    gap = shot - created
                    if gap > args.first_shot_s:
                        overdue.append(f"{aid}={gap:.2f}s")
                elif (now - created) > args.first_shot_s:
                    overdue.append(f"{aid}>={now - created:.2f}s(no-shot)")
            if overdue and abort_reason is None:
                abort_reason = (
                    f"IMMEDIATE_START: {len(overdue)} agent(s) first screenshot "
                    f">{args.first_shot_s:.0f}s after own creation: "
                    + ", ".join(overdue[:8])
                )
                _log(f"  {abort_reason}")
                break

            # No excuse for queue theatre when fleet ≤ Browserbase concurrency.
            queued = [
                s
                for s in sessions
                if s.get("status") == "pending"
                or "waiting for a browser slot" in str(s.get("last_action") or "").lower()
                or "queued — waiting" in str(s.get("last_action") or "").lower()
            ]
            if queued and t_first_task is not None and (time.time() - t_first_task) > 8:
                queued_hits += 1
                if queued_hits >= 3:
                    abort_reason = (
                        "IMMEDIATE_START: "
                        f"{len(queued)}/{len(sessions)} agents still queued "
                        "more than 8s after first task created "
                        "(no excuse with 25 Browserbase slots)"
                    )
                    _log(f"  {abort_reason}")
                    break
            acted_n = sum(1 for sess in sessions if has_click_type_scroll(sess))
            since_task = None
            now_poll = time.time()
            if sessions and t_first_task is not None:
                created_ts = [
                    ts
                    for sess in sessions
                    if (ts := _sess_created_ts(sess)) is not None
                ]
                anchor = min(created_ts) if created_ts else t_first_task
                since_task = now_poll - anchor
                since_task_last = since_task
                study_phase = str(study.get("phase") or "")
                for sess in sessions:
                    if not sess.get("phase"):
                        sess["phase"] = study_phase
                infra = assess_infrastructure_abort(sessions)
                stuck = (
                    {"abort": False}
                    if infra.get("abort")
                    else assess_stuck_abort(sessions)
                )
                ttfa_check = assess_time_to_first_action(
                    sessions,
                    now=now_poll,
                    action_seen_at=action_seen_at,
                    abort_after_s=args.first_action_s,
                    expected=max(expected, PASS_AGENT_BAR),
                )
                if t_first_value is None and action_seen_at:
                    first_value_agent, t_first_value = min(
                        action_seen_at.items(), key=lambda item: item[1]
                    )
                    if t_submit is not None:
                        _log(
                            f"  first_value +{t_first_value - t_submit:.1f}s "
                            f"agent={first_value_agent}"
                        )
                need_actions = max(expected, PASS_AGENT_BAR)
                action_clock_open = (
                    len(sessions) < need_actions
                    or int(ttfa_check.get("n") or 0) < need_actions
                )
                chosen = None
                if infra.get("abort"):
                    chosen = infra
                elif stuck.get("abort"):
                    chosen = stuck
                elif ttfa_check.get("abort"):
                    chosen = ttfa_check
                if chosen:
                    abort_reason = str(chosen.get("reason") or "FAIL early")
                    early_abort = chosen
                    elapsed_at_abort = time.time()
                    _log(f"  {abort_reason}")
                    _stop_study(args.base, str(study_id or ""))
                    break
            ttfa_med = None if not ttfa_check else ttfa_check.get("median_s")
            ttfa_max = None if not ttfa_check else ttfa_check.get("max_s")
            _log(
                f"  [{int(time.time()-t0)}s] status={study.get('status')} "
                f"users={len(personas)} tasks={n_unique_tasks} "
                f"sites={1+len(comps)} agents={len(sessions)} "
                f"acted={acted_n}/{len(sessions)} "
                f"ttfa_median={ttfa_med} ttfa_max={ttfa_max} "
                f"since_task={'' if since_task is None else f'{since_task:.0f}s'} "
                f"steps={step_n} done={done_n} "
                f"yeses={len(judged)} phase={(study.get('phase') or '')[:50]}"
            )

            # Score frames the agents already saved. Skip while the action
            # clock is open so Gemini cannot push a 10s abort out to a minute.
            if sessions and not action_clock_open:
                _score_saved_frames(
                    base=args.base,
                    product_url=args.url,
                    study=study,
                    sessions=sessions,
                    study_id=str(study_id or ""),
                    judged=judged,
                    expected=expected,
                )

            if (
                study.get("status") == "complete"
                and study.get("summary")
                and not action_clock_open
            ):
                # Allow post-agent shot backfill to land, then re-judge blanks.
                t_complete = report.setdefault("_t_complete", time.time())
                # Drop prior blank/miss judgements so backfilled PNGs get scored.
                for aid, verd in list(judged.items()):
                    reason = str(verd.get("reason") or "").lower()
                    if not verd.get("pass") and (
                        "blank" in reason
                        or "splash" in reason
                        or "no screenshot" in reason
                    ):
                        judged.pop(aid, None)
                # Directly probe bbox_0 on disk via API — GCS hydrate can clobber
                # backfilled traces out of the study JSON while files are correct.
                for sess in sessions:
                    aid = str(sess.get("agent_id") or sess.get("task_id") or "")
                    if not aid or aid in judged:
                        continue
                    shot = _best_shot(sess)
                    url = (
                        (shot or {}).get("screenshot_url")
                        or f"/api/studies/{study_id}/agents/{aid}/screenshots/bbox_0.png"
                    )
                    try:
                        raw = _fetch_png(
                            args.base, url, study_id=study_id, agent_id=aid
                        )
                    except Exception:
                        continue
                    if _png_looks_blank(raw):
                        continue
                    host = _hostname(sess.get("site_url") or args.url)
                    verdict = judge_screenshot(
                        raw, label=f"{aid} backfill", expected_host=host
                    )
                    (OUT_DIR / f"{aid}.png").write_bytes(raw)
                    judged[aid] = {
                        "agent_id": aid,
                        "host": host,
                        "step": 0,
                        "bytes": len(raw),
                        **verdict,
                    }
                    _log(
                        f"  judge {len(judged)}/{expected} {aid} "
                        f"host={host} pass={verdict.get('pass')} "
                        f"{verdict.get('reason')}"
                    )
                if time.time() - t_complete < 12 and len(judged) < expected:
                    await asyncio.sleep(1.0)
                    continue
                for sess in sessions:
                    aid = str(sess.get("agent_id") or sess.get("task_id") or "")
                    if not aid or aid in judged:
                        continue
                    judged[aid] = {
                        "agent_id": aid,
                        "host": _hostname(sess.get("site_url") or args.url),
                        "pass": False,
                        "reason": "no screenshot after study complete",
                    }
                if len(sessions) >= expected and len(judged) >= min(expected, len(sessions)):
                    break
            if study.get("status") in {"error", "abandoned"}:
                abort_reason = (
                    f"Study {study.get('status')}: {study.get('error') or study.get('phase')}"
                )
                _log(f"  {abort_reason}")
                break
            await asyncio.sleep(0.4 if action_clock_open else 1.0)

        # Frames skipped while the action clock was open, including an early abort.
        # Fetched PNGs only — this does not click the live stage.
        _score_saved_frames(
            base=args.base,
            product_url=args.url,
            study=study,
            sessions=_sessions(study),
            study_id=str(study_id or ""),
            judged=judged,
            expected=expected,
        )

        report["study_id"] = study_id
        report["yeses"] = sum(1 for v in judged.values() if v.get("pass"))
        report["judgements"] = list(judged.values())
        report["agents"] = len(_sessions(study))
        report["personas"] = len(study.get("personas") or [])
        report["task_bases"] = len({
            str(t.get("id") or "").split("__")[0]
            for t in (study.get("tasks") or [])
        })
        report["sites"] = 1 + len(study.get("competitors") or [])
        report["elapsed_s"] = round((elapsed_at_abort or time.time()) - t0, 1)
        report["since_first_task_s"] = (
            None if since_task_last is None else round(since_task_last, 1)
        )
        report["time_to_first_action"] = ttfa_check
        report["time_to_first_value_s"] = (
            None
            if t_first_value is None or t_submit is None
            else round(t_first_value - t_submit, 3)
        )
        report["total_time_s"] = (
            None
            if t_report_ready is None or t_submit is None
            else round(t_report_ready - t_submit, 3)
        )
        report["report_ready"] = t_report_ready is not None
        report["time_to_first_value_agent"] = first_value_agent
        report["early_abort"] = (
            None
            if not early_abort
            else {
                "type": early_abort.get("type"),
                "reason": early_abort.get("reason"),
            }
        )
        timing = _timing_summary(t0, _sessions(study), expected)
        report["timing"] = timing
        report["t_first_task_created_s"] = timing["run_click_to_first_task_created_s"]
        report["t_all_tasks_created_s"] = timing["run_click_to_all_tasks_created_s"]
        report["creation_to_first_real_shot"] = timing["creation_to_first_shot_s"]
        report["creation_to_first_shot"] = timing["creation_to_first_shot_s"]
        # Surface warm breakdown when present on the study activity log.
        warm_timing = {}
        for row in study.get("activity_log") or []:
            if isinstance(row, dict) and row.get("warm_timing"):
                warm_timing = row["warm_timing"]
        report["warm_timing"] = warm_timing or None
        report["t_first_task_poll_s"] = (
            round(t_first_task - t0, 1) if t_first_task else None
        )
        report["t_all_tasks_poll_s"] = (
            round(t_all_tasks - t0, 1) if t_all_tasks else None
        )
        _log(
            "  timing: run→first_task="
            f"{timing['run_click_to_first_task_created_s']}s "
            f"run→all_tasks={timing['run_click_to_all_tasks_created_s']}s "
            f"REAL shot p50/p95/max="
            f"{timing['creation_to_first_shot_s']['p50']}/"
            f"{timing['creation_to_first_shot_s']['p95']}/"
            f"{timing['creation_to_first_shot_s']['max']}s "
            f"missing_real={timing['creation_to_first_shot_s']['missing_shot']} "
            f"warm={warm_timing or '{}'}"
        )

        shot_stats = timing["creation_to_first_shot_s"]
        slow_agents = [
            r
            for r in timing["per_agent"]
            if r["creation_to_first_shot_s"] is not None
            and r["creation_to_first_shot_s"] > args.first_shot_s
        ]
        missing_shot = [
            r["agent_id"]
            for r in timing["per_agent"]
            if r["first_screenshot_at_ts"] is None
        ]
        nos = [v["agent_id"] for v in judged.values() if not v.get("pass")]
        if study_id and not study.get("id"):
            study["id"] = study_id
        if early_abort:
            vision_goal = {}
            report_html, report_url = "", ""
            shot_loader = lambda _url: False  # noqa: E731
        else:
            vision_goal = _goal_verdicts(study, args.base) if study_id else {}
            report_html, report_url = (
                _fetch_report_html(args.base, study_id) if study_id else ("", "")
            )
            shot_loader = _screenshot_loader(args.base, study_id) if study_id else (lambda _url: False)
        report["goal_verdicts"] = vision_goal
        strict = evaluate_strict_gates(
            study,
            startup={
                "expected": expected,
                "pass_agent_bar": PASS_AGENT_BAR,
                "yeses": report["yeses"],
                "elapsed_s": report["elapsed_s"],
                "missing_shot": len(missing_shot),
                "max_creation_to_shot_s": shot_stats.get("max"),
                "slow_agents": len(slow_agents),
                "vision_nos": len(nos),
                "personas": report["personas"],
                "task_bases": report["task_bases"],
                "sites": report["sites"],
                "min_personas": want_personas,
                "min_tasks": want_tasks,
                "min_sites": want_sites,
                "max_elapsed_s": args.max_elapsed_s,
                "study_budget_s": args.max_elapsed_s,
                "first_shot_s": args.first_shot_s,
                "first_action_s": args.first_action_s,
                "first_action_frac": args.first_action_frac,
                "ttfa_median_s": DEFAULT_TTFA_MEDIAN_S,
                "ttfa_max_s": DEFAULT_TTFA_MAX_S,
                "time_to_first_action_check": ttfa_check,
                "time_to_first_value_s": report["time_to_first_value_s"],
                "time_to_first_value_agent": first_value_agent,
                "total_time_s": report["total_time_s"],
                "report_ready": report["report_ready"],
                "base": args.base,
                "study_id": study_id,
                "status": study.get("status"),
                "has_summary": bool(study.get("summary")),
            },
            vision_goal=vision_goal,
            screenshot_loads=shot_loader,
            report_html=report_html,
            report_url=report_url,
            abort_reason=abort_reason,
        )
        product = strict["product_task_success"]
        report["task_success_n"] = product["success_n"]
        report["task_success_of"] = product["n"]
        report["task_success_rate"] = (
            round(100 * product["success_n"] / product["n"]) if product["n"] else 0
        )
        report["gates"] = strict["gates"]
        report["competitor_task_success"] = strict["competitor_task_success"]
        report["browserbase_concurrency_losses"] = strict["browserbase_concurrency_losses"]
        report["product_task_success"] = product
        report["report_url"] = report_url
        report["fail_reasons"] = strict["fail_reasons"]
        report["goal_verdicts"] = strict.get("verdicts") or vision_goal
        report["pass"] = bool(strict["pass"])
        failure_path = OUT_DIR / "failures.json"
        if early_abort:
            failure_doc = build_early_failures(
                study,
                _sessions(study),
                early_abort,
                base_url=args.base.rstrip("/"),
            )
            strict["failures"] = failure_doc
        else:
            failure_doc = strict.get("failures") or {}
        failure_path.write_text(json.dumps(failure_doc, indent=2))
        report["failure_file"] = str(failure_path)
        summary_md = render_markdown(
            strict,
            study_id=str(study_id or ""),
            product_url=str(args.url or ""),
            failure_file=str(failure_path),
        )
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        (OUT_DIR / "summary.md").write_text(summary_md)
        (OUT_DIR / "result.json").write_text(json.dumps(report, indent=2))
        _log(f"Wrote {failure_path} ({len(failure_doc.get('failed_runs') or [])} failed runs)")
        _log(summary_md)

        # Ready may show only now — give the UI a beat to apply the final poll.
        ready = False
        if early_abort:
            report["ready_after_complete"] = False
        else:
            for _ in range(5):
                try:
                    await page.evaluate(
                        """(data) => {
                          if (typeof updateReportCta === 'function') {
                            updateReportCta(data);
                          } else if (typeof window.applyStudyUpdate === 'function') {
                            window.applyStudyUpdate(data);
                          }
                        }""",
                        study,
                    )
                except Exception:
                    pass
                ready = await page.evaluate(_ready_visible_js())
                if ready:
                    break
                await page.wait_for_timeout(1000)
            report["ready_after_complete"] = ready
        if study.get("status") == "complete" and not ready and not early_abort:
            _log("  WARN: Ready still hidden after complete")

        report["smoke_only"] = expected < PASS_AGENT_BAR
        await browser.close()

    (OUT_DIR / "result.json").write_text(json.dumps(report, indent=2))
    _log(f"Wrote {OUT_DIR / 'result.json'}")
    _log(f"Wrote {OUT_DIR / 'summary.md'}")
    if not report["pass"]:
        lead = ""
        if early_abort and early_abort.get("reason"):
            lead = str(early_abort.get("reason")) + " || "
        raise RuntimeError(
            lead + "e2e2 failed: " + "; ".join(report.get("fail_reasons") or ["unknown"])
        )
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.environ.get("E2E_BASE", "https://usersim.vercel.app"))
    ap.add_argument("--url", default=os.environ.get("E2E2_URL", "https://useagency.dev/"))
    ap.add_argument(
        "--competitors",
        default=os.environ.get(
            "E2E2_COMPETITORS",
            "https://recurse.run/\nhttps://www.langchain.com/",
        ),
    )
    ap.add_argument(
        "--tasks",
        default=os.environ.get(
            "E2E2_TASKS",
            "\n".join(
                [
                    "Skim the homepage and note what stands out",
                    "Find something to open or watch and try it",
                ]
            ),
        ),
    )
    ap.add_argument(
        "--segment",
        default=os.environ.get("E2E2_SEGMENT", "People looking for videos to watch"),
    )
    ap.add_argument(
        "--expected",
        type=int,
        default=DEFAULT_EXPECTED,
        help="Required agent / YES count (env E2E2_EXPECTED, default 24 = 4×2×3)",
    )
    ap.add_argument("--min-personas", type=int, default=int(os.environ.get("E2E2_MIN_PERSONAS", "4")))
    ap.add_argument("--min-tasks", type=int, default=int(os.environ.get("E2E2_MIN_TASKS", "2")))
    ap.add_argument("--min-sites", type=int, default=int(os.environ.get("E2E2_MIN_SITES", "3")))
    ap.add_argument(
        "--max-agents",
        type=int,
        default=int(os.environ.get("E2E2_MAX_AGENTS", "24") or "24"),
        help="Cap via /?max_agents=N (default 24 for Browserbase budget)",
    )
    ap.add_argument("--timeout-s", type=int, default=int(os.environ.get("E2E2_TIMEOUT_S", "1800")))
    ap.add_argument(
        "--stall-s",
        type=float,
        default=float(os.environ.get("E2E2_STALL_S", "0")),
        help=(
            "Ignored. Agents are not timed out. A stuck agent is flagged when "
            "3 consecutive trace steps show no URL, DOM, or canvas change."
        ),
    )
    ap.add_argument(
        "--max-elapsed-s",
        type=float,
        default=DEFAULT_MAX_ELAPSED_S,
        help=(
            "Study-level budget in seconds (default 480 = 8 minutes). "
            "Observed strict-e2e max is 408s. Not a per-agent limit."
        ),
    )
    ap.add_argument(
        "--first-shot-s",
        type=float,
        default=DEFAULT_FIRST_SHOT_S,
        help=(
            "Max seconds from EACH agent's creation to THAT agent's first "
            "screenshot (env E2E2_FIRST_SHOT_S, default 5)"
        ),
    )
    ap.add_argument(
        "--first-action-s",
        type=float,
        default=float(
            os.environ.get("E2E2_FIRST_ACTION_S", str(DEFAULT_TTFA_ABORT_S))
            or str(DEFAULT_TTFA_ABORT_S)
        ),
        help=(
            "Abort when any agent still has no click, type, or scroll this many "
            "seconds after its own first real screenshot (default 10). "
            "The pass bar stays median <= 5s and max <= 10s. "
            "A larger value only loosens the early abort."
        ),
    )
    ap.add_argument(
        "--first-action-frac",
        type=float,
        default=float(os.environ.get("E2E2_FIRST_ACTION_FRAC", "0.5") or "0.5"),
        help="Ignored. Kept so older commands still parse. The abort is per agent.",
    )
    ap.add_argument("--headed", action="store_true", default=os.environ.get("E2E_HEADED") == "1")
    ap.add_argument("--study-id", default=os.environ.get("E2E2_STUDY_ID", ""))
    args = ap.parse_args()
    expected = int(args.expected)
    _release_testfix_sessions()
    code = 0
    try:
        result = asyncio.run(run_e2e2(args))
    except Exception as exc:  # noqa: BLE001
        _log(f"FAIL: {exc}")
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        # Preserve a full report if run_e2e2 already wrote one (judgements etc.).
        existing: dict = {}
        result_path = OUT_DIR / "result.json"
        if result_path.is_file():
            try:
                existing = json.loads(result_path.read_text())
            except Exception:
                existing = {}
        if existing.get("gates") or existing.get("judgements") or existing.get("yeses") is not None:
            existing["pass"] = False
            existing["error"] = str(exc)
            existing.setdefault("product_url", args.url)
            result_path.write_text(json.dumps(existing, indent=2))
        else:
            result_path.write_text(
                json.dumps(
                    {"pass": False, "error": str(exc), "product_url": args.url},
                    indent=2,
                )
            )
        code = 1
    else:
        _log(
            f"ALL_PASS study={result.get('study_id')} "
            f"yeses={result.get('yeses')}/{expected} "
            f"task_success={result.get('task_success_n')}/{result.get('task_success_of')} "
            f"elapsed={result.get('elapsed_s')}s "
            f"url={args.url}"
        )
    finally:
        _release_testfix_sessions()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
