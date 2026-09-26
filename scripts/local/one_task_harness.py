"""One persona, one task, one local Chromium session.

Prints the observation, the decision, the executed action, and the URL and
DOM after every step. No Browserbase session is opened.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from mvp.a11y_agent import complete_task_on_page, goal_visible  # noqa: E402

TASKS = [
    ("linear", "https://linear.app/", "Find how to create a new issue"),
    ("linear", "https://linear.app/", "Look for pricing or how to get started"),
    ("excalidraw", "https://excalidraw.com/", "Draw a simple box"),
    ("excalidraw", "https://excalidraw.com/", "Find how to export or share"),
]

# Sites this loop was not hand-tuned for. Draw uses a shape tool plus the
# largest canvas. Export and help click whatever role and name the tree shows.
GENERIC_TASKS = [
    ("tldraw", "https://www.tldraw.com/", "Draw a simple box"),
    ("tldraw", "https://www.tldraw.com/", "Find how to export or share"),
    ("figma", "https://www.figma.com/", "Look for pricing or how to get started"),
    # etsy.com returns 403 to headless Chromium. IKEA is the commerce page that loads.
    ("ikea", "https://www.ikea.com/us/en/", "Find help or how to contact support"),
]


def _trim(text: object, limit: int = 280) -> str:
    return " ".join(str(text or "").split())[:limit]


async def run_one(browser, site: str, url: str, task: str) -> dict:
    page = await browser.new_page(
        viewport={"width": 1440, "height": 900},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
    )
    print(f"\n======== {site} | {task}", flush=True)
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=20000)
    except Exception as exc:  # noqa: BLE001
        print(f"goto: {exc!r}", flush=True)
    outcome = await complete_task_on_page(
        page,
        task=task,
        url=url,
        deadline=time.monotonic() + 90,
        agent_id=f"{site}",
    )
    for row in outcome.get("logs") or []:
        print(f"\nSTEP {row.get('step')}", flush=True)
        print(f"observation: {_trim(row.get('observation'))}", flush=True)
        print(f"decision: {_trim(json.dumps(row.get('decision'), ensure_ascii=False), 400)}", flush=True)
        print(f"executed: {row.get('executed')} via {row.get('how')}", flush=True)
        print(f"url after: {row.get('url_after')}", flush=True)
        print(f"dom after: {_trim(row.get('dom_after'))}", flush=True)
    read = outcome.get("read") or {}
    ok = outcome.get("stop_reason") == "done" and goal_visible(task, read)
    shot_dir = ROOT / "results" / "taskfix" / "shots"
    shot_dir.mkdir(parents=True, exist_ok=True)
    slug = task[:32].replace(" ", "_").replace("/", "-")
    shot = shot_dir / f"{site}-{slug}.png"
    try:
        await page.screenshot(path=str(shot), timeout=8000)
    except Exception as exc:  # noqa: BLE001
        print(f"screenshot: {exc!r}", flush=True)
        shot = Path()
    print(
        f"RESULT {'PASS' if ok else 'FAIL'} {outcome.get('stop_reason')} {read.get('url')} {read.get('title')}",
        flush=True,
    )
    await page.close()
    return {
        "site": site,
        "task": task,
        "pass": bool(ok),
        "stop_reason": outcome.get("stop_reason"),
        "final_url": read.get("url"),
        "title": read.get("title"),
        "logs": outcome.get("logs") or [],
        "screenshot": str(shot) if str(shot) else "",
    }


async def main() -> None:
    from playwright.async_api import async_playwright

    generic = "--generic" in sys.argv
    tasks = GENERIC_TASKS if generic else TASKS
    out_name = "generic_agent.json" if generic else "one_agent.json"
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        results = []
        for site, url, task in tasks:
            results.append(await run_one(browser, site, url, task))
        await browser.close()
    out = ROOT / "results" / "taskfix"
    out.mkdir(parents=True, exist_ok=True)
    (out / out_name).write_text(json.dumps(results, indent=2))
    passed = sum(1 for row in results if row["pass"])
    print(f"\n==== {passed}/{len(results)} passed", flush=True)
    if passed < len(results):
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
