"""Run one task per fresh local Chrome page through the real step loop and print each step.

Usage: python scripts/local/canvas_probe.py URL "task" [--reps N] [--headless]
No Browserbase. Uses patchright headed Chrome on $DISPLAY when available.
"""
from __future__ import annotations

import argparse, asyncio, json, os, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT))
from mvp.a11y_agent import complete_task_on_page, goal_visible, task_kind  # noqa: E402


async def one(ctx, url, task, idx, out):
    page = await ctx.new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=20000)
    except Exception as exc:  # noqa: BLE001
        print("goto", exc)
    t0 = time.monotonic()
    o = await complete_task_on_page(page, task=task, url=url, deadline=time.monotonic() + 90, agent_id=f"probe{idx}")
    read = o.get("read") or {}
    # The loop's own acceptance: "done" already required the page heuristic or
    # its screenshot check. Draw and pricing tasks must also pass the page check.
    ok = o.get("stop_reason") == "done" and (task_kind(task) not in {"draw", "pricing"} or goal_visible(task, read))
    steps = []
    for row in o.get("logs") or []:
        steps.append(f"{row.get('step')}: {row.get('executed')} via {row.get('how')} changed={row.get('changed')}")
    print(f"[{idx}] ok={ok} stop={o.get('stop_reason')} {time.monotonic()-t0:.1f}s drew={read.get('drew')} shapes={read.get('opened_shapes')}->{read.get('shapes')}", flush=True)
    for s in steps:
        print("    ", s[:200], flush=True)
    try:
        await page.screenshot(path=f"{out}/{idx}.png")
    except Exception:
        pass
    await page.close()
    return ok, o


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url"); ap.add_argument("task")
    ap.add_argument("--reps", type=int, default=4); ap.add_argument("--headless", action="store_true")
    ap.add_argument("--out", default="/workspace/signup-work/canvas")
    a = ap.parse_args()
    Path(a.out).mkdir(parents=True, exist_ok=True)
    try:
        from patchright.async_api import async_playwright
    except Exception:
        from playwright.async_api import async_playwright
    async with async_playwright() as p:
        oks = 0
        for i in range(a.reps):
            import shutil; shutil.rmtree(f"/tmp/canvas-probe-{os.getpid()}-{i}", ignore_errors=True)
            ctx = await p.chromium.launch_persistent_context(
                f"/tmp/canvas-probe-{os.getpid()}-{i}", channel="chrome", headless=a.headless, no_viewport=not a.headless,
                viewport={"width": 1440, "height": 900} if a.headless else None,
            )
            ok, _ = await one(ctx, a.url, a.task, i, a.out)
            oks += ok
            await ctx.close()
        print(f"RESULT {oks}/{a.reps} :: {a.url} :: {a.task}", flush=True)

asyncio.run(main())
