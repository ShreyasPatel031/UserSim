#!/usr/bin/env python3
"""e2e2: real Run button → 5 users × 5 tasks × 3 sites → 75 flash-lite YESes.

Clicks Run (never Smoke). While agents run, Ready/View-full-report must stay
hidden. Then toggles every site × task × user control and vision-judges the
*agent screenshot bytes of the target website* (not UserSim chrome, not a
Preparing pulse, not a grey pane).

  PYTHONPATH=src:. python mvp/e2e2_matrix.py --base https://usersim.vercel.app
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
EXPECTED = 75  # 5 personas × 5 tasks × 3 sites


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


def _best_shot(sess: dict) -> dict | None:
    bad = re.compile(r"^(preparing|opening|thinking|signed-in cookies|waiting)\b", re.I)
    best = None
    for step in sess.get("trace") or []:
        if not isinstance(step, dict) or not isinstance(step.get("step"), int):
            continue
        if not step.get("screenshot_url"):
            continue
        if bad.search(str(step.get("action") or "")):
            continue
        if best is None or int(step["step"]) >= int(best["step"]):
            best = step
    return best


def _fetch_png(base: str, url: str) -> bytes:
    if url.startswith("/"):
        url = base.rstrip("/") + url
    with urllib.request.urlopen(url, timeout=45) as resp:
        return resp.read()


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


async def run_e2e2(args: argparse.Namespace) -> dict:
    from playwright.async_api import async_playwright

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    report: dict = {
        "base": args.base,
        "judge_model": JUDGE_MODEL,
        "expected": EXPECTED,
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

        _log(f"→ open {args.base}")
        await page.goto(args.base, wait_until="domcontentloaded", timeout=60_000)
        await page.wait_for_selector("#study-form #submit-btn", timeout=30_000)

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

        study_id = ""
        study: dict = {}
        judged: dict[str, dict] = {}

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
            _log(
                f"  [{int(time.time()-t0)}s] status={study.get('status')} "
                f"users={len(personas)} tasks={n_unique_tasks} "
                f"sites={1+len(comps)} agents={len(sessions)} "
                f"yeses={len(judged)} phase={(study.get('phase') or '')[:50]}"
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
                    await page.locator("#stage-section").wait_for(
                        state="visible", timeout=15_000
                    )
                    await _toggle_session(page, sess)
                    await _assert_ready_hidden(page, study)
                    raw = _fetch_png(args.base, shot["screenshot_url"])
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
                        f"  judge {len(judged)}/{EXPECTED} {aid} "
                        f"host={host} pass={verdict.get('pass')} "
                        f"{verdict.get('reason')}"
                    )
                    if not verdict.get("pass"):
                        raise RuntimeError(f"flash-lite NO for {aid}: {verdict}")
                except RuntimeError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    _log(f"  judge skip {aid}: {exc!r}")

            if (
                study.get("status") == "complete"
                and study.get("summary")
                and len(sessions) >= EXPECTED
                and len(judged) >= EXPECTED
            ):
                break
            if study.get("status") in {"error", "abandoned"}:
                raise RuntimeError(
                    f"Study {study.get('status')}: {study.get('error') or study.get('phase')}"
                )
            await page.wait_for_timeout(4000)

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
        report["elapsed_s"] = round(time.time() - t0, 1)

        fails = []
        if report["personas"] < 5:
            fails.append(f"personas={report['personas']} want 5")
        if report["task_bases"] < 5:
            fails.append(f"tasks={report['task_bases']} want 5")
        if report["sites"] < 3:
            fails.append(f"sites={report['sites']} want 3")
        if report["agents"] < EXPECTED:
            fails.append(f"agents={report['agents']} want {EXPECTED}")
        if report["yeses"] < EXPECTED:
            fails.append(f"yeses={report['yeses']} want {EXPECTED}")
        if study.get("status") != "complete":
            fails.append(f"status={study.get('status')}")
        if not study.get("summary"):
            fails.append("missing summary")
        nos = [v["agent_id"] for v in judged.values() if not v.get("pass")]
        if nos:
            fails.append(f"flash-lite NO: {nos[:8]}")

        # Ready may show only now.
        ready = await page.evaluate(_ready_visible_js())
        report["ready_after_complete"] = ready
        if study.get("status") == "complete" and not ready:
            _log("  WARN: Ready still hidden after complete")

        report["fail_reasons"] = fails
        report["pass"] = not fails
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
                    "Skim the homepage and note the main value prop",
                    "Find pricing or how to get started",
                    "Look for a sign-up, demo, or contact path",
                    "Scan navigation and name the main product areas",
                    "Find social proof, customers, or examples",
                ]
            ),
        ),
    )
    ap.add_argument(
        "--segment",
        default=os.environ.get("E2E2_SEGMENT", "Founders evaluating AI research tools"),
    )
    ap.add_argument("--timeout-s", type=int, default=int(os.environ.get("E2E2_TIMEOUT_S", "2400")))
    ap.add_argument("--headed", action="store_true", default=os.environ.get("E2E_HEADED") == "1")
    args = ap.parse_args()
    try:
        result = asyncio.run(run_e2e2(args))
    except Exception as exc:  # noqa: BLE001
        _log(f"FAIL: {exc}")
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        (OUT_DIR / "result.json").write_text(
            json.dumps({"pass": False, "error": str(exc)}, indent=2)
        )
        return 1
    _log(
        f"ALL_PASS study={result.get('study_id')} "
        f"yeses={result.get('yeses')}/{EXPECTED} elapsed={result.get('elapsed_s')}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
