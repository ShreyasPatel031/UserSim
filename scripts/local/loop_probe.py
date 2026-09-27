"""Run the generic step loop on (url, task) pairs in local Chromium, in parallel.

Usage: python scripts/local/loop_probe.py URL "task" [URL "task" ...]
Prints each step and the stop reason. No Browserbase session is opened.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from mvp.a11y_agent import complete_task_on_page  # noqa: E402


async def one(browser, n: int, url: str, task: str) -> str:
    ctx = await browser.new_context(viewport={"width": 1440, "height": 900})
    page = await ctx.new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=15000)
    except Exception as exc:  # noqa: BLE001
        print(f"[{n}] goto {exc!r}", flush=True)
    out = await complete_task_on_page(
        page, task=task, url=url, deadline=time.monotonic() + float(os.environ.get("PROBE_S", "150")), agent_id=f"p{n}"
    )
    lines = [f"==== [{n}] {url} | {task}"]
    for row in out.get("logs") or []:
        lines.append(f"  {row['step']:>2} {row['executed'][:70]:<70} {row.get('how')} -> {row['url_after'][:90]}")
    lines.append(f"  STOP {out.get('stop_reason')} failed={out.get('failed')} final={out.get('read', {}).get('url')}")
    shot = ROOT / "results" / "probe" / f"{n}.png"
    shot.parent.mkdir(parents=True, exist_ok=True)
    try:
        await page.screenshot(path=str(shot))
    except Exception:
        pass
    await ctx.close()
    return "\n".join(lines)


async def main() -> None:
    from playwright.async_api import async_playwright

    pairs = list(zip(sys.argv[1::2], sys.argv[2::2]))
    async with async_playwright() as pw:
        exe = os.environ.get("PROBE_CHROME") or None
        browser = await pw.chromium.launch(headless=True, executable_path=exe)
        results = await asyncio.gather(*(one(browser, i, u, t) for i, (u, t) in enumerate(pairs)))
        await browser.close()
    print("\n".join(results))


if __name__ == "__main__":
    asyncio.run(main())
