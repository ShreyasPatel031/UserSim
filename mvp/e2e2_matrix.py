#!/usr/bin/env python3
"""e2e2: real Run button → matrix of users × tasks × sites → flash-lite YESes.

Clicks Run (never Smoke). While agents run, Ready/View-full-report must stay
hidden. Then toggles every site × task × user control and vision-judges the
*agent screenshot bytes of the target website* (not UserSim chrome, not a
Preparing pulse, not a grey pane).

  PYTHONPATH=src:. python mvp/e2e2_matrix.py --base https://usersim.vercel.app
  E2E2_URL=https://www.youtube.com/ E2E2_EXPECTED=9 E2E2_MAX_AGENTS=9 \\
    ./mvp/run_e2e2.sh http://127.0.0.1:3000
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

sa = ROOT / "secrets" / "sa.json"
if sa.is_file():
    os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", str(sa))

OUT_DIR = Path(os.environ.get("E2E2_OUT_DIR", "/tmp/usersim_e2e2"))
# Default: 4 personas × 2 tasks × 3 sites = 24 (fits Browserbase 25-slot budget).
DEFAULT_EXPECTED = int(os.environ.get("E2E2_EXPECTED", "24") or "24")
# Only a full 24-agent matrix can PASS. Smaller runs are smoke-only.
PASS_AGENT_BAR = int(os.environ.get("E2E2_PASS_AGENT_BAR", "24") or "24")
# Prior YouTube 9-agent run was ~408s — full 24-agent budget must still be faster.
DEFAULT_MAX_ELAPSED_S = float(os.environ.get("E2E2_MAX_ELAPSED_S", "360") or "360")
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


async def _toggle_session(page, sess: dict) -> None:
    site_key = sess.get("site_key") or "product"
    persona = sess.get("persona_id") or ""
    task_base = str(sess.get("task_id") or sess.get("agent_id") or "").split("__")[0]
    if site_key:
        btn = page.locator(f'#stage-site-switch [data-stage-site-key="{site_key}"]')
        if await btn.count():
            await btn.first.click()
            await page.wait_for_timeout(200)
    if task_base:
        task_sel = page.locator("#stage-task-select")
        if await task_sel.count():
            try:
                await task_sel.select_option(task_base)
            except Exception:
                pass
            await page.wait_for_timeout(150)
    if persona:
        user_sel = page.locator("#stage-user-select")
        if await user_sel.count():
            try:
                await user_sel.select_option(persona)
            except Exception:
                pass
            await page.wait_for_timeout(150)
    await page.wait_for_timeout(400)


def _attach_task_success(report: dict, study: dict, judged: dict, fallback_url: str) -> None:
    """Record task success beside screenshot yeses, including the product gate."""
    from mvp.report_insights import product_completion_gate, task_succeeded

    runs = [
        r
        for r in (study.get("agent_results") or _sessions(study) or [])
        if isinstance(r, dict)
    ]
    by_id = {str(r.get("agent_id") or r.get("task_id") or ""): r for r in runs}
    n_ok = 0
    for aid, row in judged.items():
        run = by_id.get(str(aid))
        ok = False
        if isinstance(run, dict):
            start = str(run.get("site_url") or fallback_url or "")
            try:
                ok = bool(task_succeeded(run, start))
            except Exception:
                ok = False
        row["task_success"] = ok
        if ok:
            n_ok += 1
    report["task_success_n"] = n_ok
    report["task_success_of"] = len(judged)
    report["task_success_rate"] = round(100 * n_ok / len(judged)) if judged else 0
    gate = product_completion_gate(runs, str(study.get("url") or fallback_url or ""))
    report["product_task_gate"] = gate
    report["product_task_success_n"] = gate["success_n"]
    report["product_task_success_of"] = gate["product_n"]
    report["product_task_success_rate"] = gate["success_rate"]
    report["product_first_screen_failures"] = gate["first_screen_failures"]


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
            await page.click("#submit-btn")
        else:
            _log(f"→ attach study {study_id} (no new Run)")
        study: dict = {}
        judged: dict[str, dict] = {}
        last_steps = -1
        last_done = -1
        last_move_t = time.time()
        t_first_task: float | None = None
        t_all_tasks: float | None = None
        queued_hits = 0
        immediate_start_failed: str | None = None

        while time.time() - t0 < args.timeout_s:
            e2e = await page.evaluate("() => window.__e2e || {}")
            study_id = study_id or e2e.get("studyId") or ""
            if study_id:
                try:
                    study = http_json(args.base, f"/api/studies/{study_id}", timeout=45)
                except Exception as exc:  # noqa: BLE001
                    _log(f"  poll warn: {exc!r}")
                    await page.wait_for_timeout(2000)
                    continue
            await _assert_ready_hidden(page, study)

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
            if overdue and immediate_start_failed is None:
                immediate_start_failed = (
                    f"IMMEDIATE_START: {len(overdue)} agent(s) first screenshot "
                    f">{args.first_shot_s:.0f}s after own creation: "
                    + ", ".join(overdue[:8])
                )
                _log(f"  {immediate_start_failed}")
                timing = _timing_summary(t0, sessions, expected)
                report["study_id"] = study_id
                report["agents"] = len(sessions)
                report["timing"] = timing
                report["t_first_task_created_s"] = timing[
                    "run_click_to_first_task_created_s"
                ]
                report["t_all_tasks_created_s"] = timing[
                    "run_click_to_all_tasks_created_s"
                ]
                report["creation_to_first_shot"] = timing["creation_to_first_shot_s"]
                report["fail_reasons"] = [immediate_start_failed]
                report["pass"] = False
                report["elapsed_s"] = round(time.time() - t0, 1)
                (OUT_DIR / "result.json").write_text(json.dumps(report, indent=2))
                raise RuntimeError(immediate_start_failed)

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
                    raise RuntimeError(
                        "IMMEDIATE_START: "
                        f"{len(queued)}/{len(sessions)} agents still queued "
                        "more than 8s after first task created "
                        "(no excuse with 25 Browserbase slots)"
                    )
            if step_n > last_steps or done_n > last_done:
                last_steps = step_n
                last_done = done_n
                last_move_t = time.time()
            _log(
                f"  [{int(time.time()-t0)}s] status={study.get('status')} "
                f"users={len(personas)} tasks={n_unique_tasks} "
                f"sites={1+len(comps)} agents={len(sessions)} "
                f"yeses={len(judged)} phase={(study.get('phase') or '')[:50]}"
            )

            # Stall fail-fast: frozen fleet must not burn the full timeout.
            if sessions and (time.time() - last_move_t) > args.stall_s:
                raise RuntimeError(
                    f"STALL: no new steps/dones for {args.stall_s:.0f}s "
                    f"(steps={step_n}, done={done_n}/{len(sessions)}, "
                    f"phase={study.get('phase')!r})"
                )

            # Toggle + judge any session that now has a real numbered shot.
            for sess in sessions:
                aid = str(sess.get("agent_id") or sess.get("task_id") or "")
                if not aid or aid in judged:
                    continue
                shot = _best_shot(sess)
                if not shot:
                    continue
                try:
                    raw = _fetch_png(
                        args.base,
                        shot["screenshot_url"],
                        study_id=study_id,
                        agent_id=aid,
                    )
                    # Don't fail the whole matrix on a black splash while the
                    # agent is still browsing — wait for a real paint.
                    if _png_looks_blank(raw):
                        if study.get("status") == "running":
                            _log(
                                f"  skip blankish shot {aid} step={shot.get('step')} "
                                f"({len(raw)} bytes) — waiting for paint"
                            )
                            continue
                        # Study finished with only a splash — count as a miss,
                        # don't spin forever skipping after complete.
                        _log(
                            f"  blankish after complete {aid} step={shot.get('step')} "
                            f"({len(raw)} bytes) — counting as miss"
                        )
                        judged[aid] = {
                            "agent_id": aid,
                            "host": _hostname(
                                sess.get("site_url") or shot.get("url") or args.url
                            ),
                            "step": shot.get("step"),
                            "bytes": len(raw),
                            "pass": False,
                            "reason": "blank/splash frame after study complete",
                        }
                        continue
                    try:
                        if await page.locator("#stage-section:not([hidden])").count():
                            await _toggle_session(page, sess)
                    except Exception:
                        pass
                    await _assert_ready_hidden(page, study)
                    host = _hostname(sess.get("site_url") or shot.get("url") or args.url)
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
                    if not verdict.get("pass"):
                        # Keep waiting for a later real frame while the study runs.
                        # Hard-aborting mid-run on one NO kills the whole matrix
                        # (signup flows often lack hostname chrome in the PNG).
                        if study.get("status") == "running":
                            _log(
                                f"  defer NO {aid} step={shot.get('step')}: "
                                f"{verdict.get('reason')}"
                            )
                            judged.pop(aid, None)
                            continue
                        _log(
                            f"  NO after complete {aid}: {verdict.get('reason')}"
                        )
                        # Keep the NO in judged; final gate counts yeses.
                except Exception as exc:  # noqa: BLE001
                    _log(f"  judge skip {aid}: {exc!r}")

            if study.get("status") == "complete" and study.get("summary"):
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
                    await page.wait_for_timeout(2000)
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
                raise RuntimeError(
                    f"Study {study.get('status')}: {study.get('error') or study.get('phase')}"
                )
            await page.wait_for_timeout(4000)

        report["study_id"] = study_id
        report["yeses"] = sum(1 for v in judged.values() if v.get("pass"))
        _attach_task_success(report, study, judged, args.url)
        report["judgements"] = list(judged.values())
        report["agents"] = len(_sessions(study))
        report["personas"] = len(study.get("personas") or [])
        report["task_bases"] = len({
            str(t.get("id") or "").split("__")[0]
            for t in (study.get("tasks") or [])
        })
        report["sites"] = 1 + len(study.get("competitors") or [])
        report["elapsed_s"] = round(time.time() - t0, 1)
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
        gate = report.get("product_task_gate") or {}
        _log(
            "  product task gate: "
            f"{gate.get('success_n')}/{gate.get('product_n')} "
            f"want ≥{gate.get('required_n')} "
            f"first_screen_fail={len(gate.get('first_screen_failures') or [])} "
            f"pass={gate.get('pass')}"
        )

        fails = []
        # 24 agents is the only PASS bar — smaller runs are smoke-only.
        if expected < PASS_AGENT_BAR:
            fails.append(
                f"smoke-only expected={expected}; PASS requires {PASS_AGENT_BAR} agents"
            )
        if report["personas"] < want_personas:
            fails.append(f"personas={report['personas']} want {want_personas}")
        if report["task_bases"] < want_tasks:
            fails.append(f"tasks={report['task_bases']} want {want_tasks}")
        if report["sites"] < want_sites:
            fails.append(f"sites={report['sites']} want {want_sites}")
        if report["agents"] < PASS_AGENT_BAR:
            fails.append(
                f"agents={report['agents']} want {PASS_AGENT_BAR} "
                "(8-agent smoke does not count as PASS)"
            )
        elif report["agents"] < expected:
            fails.append(f"agents={report['agents']} want {expected}")
        if report["yeses"] < expected:
            fails.append(f"yeses={report['yeses']} want {expected}")
        if study.get("status") != "complete":
            fails.append(f"status={study.get('status')}")
        if not study.get("summary"):
            fails.append("missing summary")
        if report["elapsed_s"] > args.max_elapsed_s:
            fails.append(
                f"elapsed={report['elapsed_s']}s want ≤{args.max_elapsed_s:.0f}s "
                f"(prior YouTube baseline ~408s)"
            )
        # Per-agent creation → first screenshot gate.
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
        if missing_shot:
            fails.append(
                f"no first screenshot for {len(missing_shot)} agent(s): "
                + ", ".join(missing_shot[:8])
            )
        if slow_agents:
            fails.append(
                f"creation→first_shot >{args.first_shot_s:.0f}s for "
                f"{len(slow_agents)} agent(s) "
                f"(max={shot_stats['max']}s p95={shot_stats['p95']}s): "
                + ", ".join(
                    f"{r['agent_id']}={r['creation_to_first_shot_s']}s"
                    for r in slow_agents[:8]
                )
            )
        nos = [v["agent_id"] for v in judged.values() if not v.get("pass")]
        if nos:
            fails.append(f"flash-lite NO: {nos[:8]}")
        gate = report.get("product_task_gate") or {}
        if not gate.get("pass"):
            stuck = gate.get("first_screen_failures") or []
            fails.append(
                f"product task success {gate.get('success_n')}/{gate.get('product_n')} "
                f"want ≥{gate.get('required_n')} "
                f"({len(stuck)} stayed on the first screen)"
            )

        # Ready may show only now — give the UI a beat to apply the final poll.
        ready = False
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
        if study.get("status") == "complete" and not ready:
            _log("  WARN: Ready still hidden after complete")

        report["fail_reasons"] = fails
        report["pass"] = not fails
        report["smoke_only"] = expected < PASS_AGENT_BAR
        await browser.close()

    (OUT_DIR / "result.json").write_text(json.dumps(report, indent=2))
    _log(f"Wrote {OUT_DIR / 'result.json'}")
    if not report["pass"]:
        raise RuntimeError("e2e2 failed: " + "; ".join(fails))
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
        default=float(os.environ.get("E2E2_STALL_S", "90")),
        help="Fail if no new steps/dones for this many seconds",
    )
    ap.add_argument(
        "--max-elapsed-s",
        type=float,
        default=DEFAULT_MAX_ELAPSED_S,
        help="Hard ceiling vs prior ~408s YouTube baseline",
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
    ap.add_argument("--headed", action="store_true", default=os.environ.get("E2E_HEADED") == "1")
    ap.add_argument("--study-id", default=os.environ.get("E2E2_STUDY_ID", ""))
    args = ap.parse_args()
    expected = int(args.expected)
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
        if existing.get("judgements") or existing.get("yeses") is not None:
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
        return 1
    _log(
        f"ALL_PASS study={result.get('study_id')} "
        f"yeses={result.get('yeses')}/{expected} "
        f"task_success={result.get('task_success_n')}/{result.get('task_success_of')} "
        f"product_task={result.get('product_task_success_n')}/"
        f"{result.get('product_task_success_of')} "
        f"elapsed={result.get('elapsed_s')}s "
        f"url={args.url}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
