#!/usr/bin/env python3
"""Drive the real UI on 3 product URLs. For each:

  - loading card is visible while the study runs
  - email capture lives on that loading card
  - when done, email is gone and the → report arrow is shown
  - /report?study=… has a real executive summary
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from mvp.e2e_ui_run import FETCH_PROBE, _log, http_json  # noqa: E402

sa = ROOT / "secrets" / "sa.json"
if sa.is_file():
    os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", str(sa))

OUT_DIR = Path(os.environ.get("E2E_THREE_OUT", ROOT / "results" / "e2e_three_reports"))

SITES = [
    {
        "url": os.environ.get("E2E_SITE_1", "https://useagency.dev/"),
        "name": "agency",
        "segment": "Two people: a creative marketer and a technical founder.",
        "tasks": "Skim the homepage and say the main promise\nFind pricing or how to get started",
    },
    {
        "url": os.environ.get("E2E_SITE_2", "https://recurse.run/"),
        "name": "recurse",
        "segment": "Two people: a platform engineer and a startup founder.",
        "tasks": "Skim the homepage and say the main promise\nFind how to get started",
    },
    {
        "url": os.environ.get("E2E_SITE_3", "https://www.langchain.com/"),
        "name": "langchain",
        "segment": "Two people: an ML engineer and a product manager.",
        "tasks": "Skim the homepage and say the main promise\nFind docs or how to get started",
    },
]


def _cta_js() -> str:
    return """() => {
      const running = document.getElementById('report-running');
      const email = document.getElementById('report-email-prompt');
      const emailInput = document.getElementById('report-email-input');
      const link = document.getElementById('view-report-link');
      const runningVisible = Boolean(running && !running.hidden);
      const emailInRunning = Boolean(
        runningVisible && email && !email.hidden && running.contains(email) && emailInput
      );
      return {
        running: runningVisible,
        email: emailInRunning,
        report: Boolean(link && !link.hidden),
        href: link?.getAttribute('href') || '',
        runningText: (running?.innerText || '').slice(0, 160),
      };
    }"""


def _report_js() -> str:
    return """() => {
      const empty = document.getElementById('report-empty');
      const results = document.getElementById('results');
      const headline = document.getElementById('headline');
      const friction = document.getElementById('top-friction');
      const recs = document.getElementById('recommendations');
      return {
        empty: Boolean(empty && !empty.hidden),
        results: Boolean(results && !results.hidden),
        headline: (headline?.innerText || '').trim(),
        friction: friction ? friction.querySelectorAll('li').length : 0,
        recs: recs ? recs.querySelectorAll('.rec-card').length : 0,
      };
    }"""


async def _run_one(page, args, site: dict, idx: int) -> dict:
    out: dict = {"url": site["url"], "name": site["name"], "fails": [], "pass": False}
    prefix = f"{idx}_{site['name']}"
    start_url = args.base.rstrip("/") + f"/?max_agents={args.max_agents}"
    _log(f"→ [{site['name']}] open {start_url}")
    await page.goto(start_url, wait_until="domcontentloaded", timeout=60_000)
    await page.wait_for_selector("#study-form #submit-btn", timeout=30_000)

    smoke = page.locator("#test-mode-input")
    if await smoke.count() and await smoke.is_checked():
        await smoke.uncheck()

    await page.fill('input[name="url"]', site["url"])
    details = page.locator("details.url-more")
    if await details.count():
        await details.first.evaluate("el => { el.open = true }")
    await page.fill('textarea[name="customers"]', site["segment"])
    await page.fill('textarea[name="competitors"]', "")
    await page.fill('textarea[name="tasks"]', site["tasks"])

    _log(f"  [{site['name']}] click Run")
    await page.click("#submit-btn")

    # Loading + email must appear while the study is in flight.
    loading_ok = False
    deadline = time.time() + 45
    while time.time() < deadline:
        cta = await page.evaluate(_cta_js())
        if cta.get("running") and cta.get("email") and not cta.get("report"):
            loading_ok = True
            (OUT_DIR / f"{prefix}_loading.png").write_bytes(await page.screenshot(type="png"))
            break
        await page.wait_for_timeout(250)
    out["loading"] = loading_ok
    if not loading_ok:
        out["fails"].append("loading card + email box not visible during study")
        (OUT_DIR / f"{prefix}_loading.png").write_bytes(await page.screenshot(type="png"))
    else:
        _log(f"  [{site['name']}] loading+email visible")

    study_id = None
    for _ in range(80):
        study_id = await page.evaluate("() => window.__e2e && window.__e2e.studyId")
        if study_id:
            break
        await page.wait_for_timeout(250)
    if not study_id:
        listing = http_json(args.base, "/api/studies", timeout=30)
        items = listing.get("studies") or []
        if items:
            study_id = items[0].get("id")
    out["study_id"] = study_id
    _log(f"  [{site['name']}] study_id={study_id}")

    # Wait until the report arrow replaces the email/loading card.
    done = False
    href = ""
    wait_s = args.per_site_timeout_s
    t0 = time.time()
    while time.time() - t0 < wait_s:
        cta = await page.evaluate(_cta_js())
        if cta.get("report") and not cta.get("running") and not cta.get("email"):
            done = True
            href = cta.get("href") or ""
            (OUT_DIR / f"{prefix}_ready.png").write_bytes(await page.screenshot(type="png"))
            break
        await page.wait_for_timeout(2000)
    out["ready_cta"] = done
    out["report_href"] = href
    if not done:
        out["fails"].append("report arrow never replaced the email/loading card")
        (OUT_DIR / f"{prefix}_ready.png").write_bytes(await page.screenshot(type="png"))
        return out
    _log(f"  [{site['name']}] report arrow → {href}")

    if not href or "study=" not in href:
        out["fails"].append(f"report href missing study id: {href!r}")
        return out

    report_url = href if href.startswith("http") else args.base.rstrip("/") + href
    await page.goto(report_url, wait_until="domcontentloaded", timeout=60_000)
    await page.wait_for_timeout(800)
    # Report page may poll; wait for headline.
    headline = ""
    for _ in range(40):
        info = await page.evaluate(_report_js())
        headline = info.get("headline") or ""
        if headline and info.get("results") and not info.get("empty"):
            out["report"] = info
            break
        await page.wait_for_timeout(500)
    (OUT_DIR / f"{prefix}_report.png").write_bytes(await page.screenshot(type="png", full_page=True))
    if not headline:
        out["fails"].append("report page has no executive headline")
    else:
        _log(f"  [{site['name']}] report headline={headline[:80]!r}")
    info = out.get("report") or {}
    if int(info.get("friction") or 0) < 1 and int(info.get("recs") or 0) < 1:
        # Headline alone is the minimum; warn-as-fail if the body is empty.
        snap = {}
        if study_id:
            try:
                snap = http_json(args.base, f"/api/studies/{study_id}", timeout=45)
            except Exception:
                snap = {}
        if not (snap.get("summary") or {}).get("headline"):
            out["fails"].append("API summary missing headline")
        else:
            out["report"] = {
                **info,
                "headline": snap["summary"].get("headline"),
                "api_ok": True,
            }

    out["pass"] = not out["fails"]
    return out


async def run(args: argparse.Namespace) -> dict:
    from playwright.async_api import async_playwright

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for old in OUT_DIR.glob("*"):
        if old.is_file():
            old.unlink()

    report: dict = {
        "base": args.base,
        "sites": [],
        "fails": [],
        "pass": False,
    }
    t0 = time.time()
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=not args.headed)
        context = await browser.new_context(
            viewport={"width": 1440, "height": 1100},
            device_scale_factor=1,
        )
        page = await context.new_page()
        await page.add_init_script(FETCH_PROBE)
        for i, site in enumerate(SITES):
            one = await _run_one(page, args, site, i)
            report["sites"].append(one)
            report["fails"].extend(f"{site['name']}: {f}" for f in one.get("fails") or [])
        await browser.close()

    report["elapsed_s"] = round(time.time() - t0, 1)
    report["pass"] = not report["fails"] and all(s.get("pass") for s in report["sites"])
    (OUT_DIR / "result.json").write_text(json.dumps(report, indent=2, default=str))
    _log(f"Wrote {OUT_DIR / 'result.json'} pass={report['pass']} fails={report['fails']}")
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description="3-site UI e2e: loading email + report arrow")
    ap.add_argument("--base", default=os.environ.get("E2E_BASE", "https://usersim.vercel.app"))
    ap.add_argument("--max-agents", type=int, default=int(os.environ.get("E2E_MAX_AGENTS", "3")))
    ap.add_argument("--per-site-timeout-s", type=int, default=int(os.environ.get("E2E_SITE_TIMEOUT_S", "420")))
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
