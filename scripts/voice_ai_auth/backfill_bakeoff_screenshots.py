#!/usr/bin/env python3
"""Re-capture final.png for bakeoff traces where judge screenshot failed."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from capability import USER_AGENT, VIEWPORT
from capability.voice_ai_dashboards import browser_profile_overrides, dashboard_for_url, load_storage_state


async def capture_one(run_path: Path) -> bool:
    from playwright.async_api import async_playwright

    run = json.loads(run_path.read_text())
    final_url = run.get("final_url") or run.get("start_url")
    if not final_url:
        return False
    trace_dir = run_path.parent
    if (trace_dir / "final.png").is_file():
        return True
    dash = dashboard_for_url(run.get("start_url") or final_url)
    storage_state = load_storage_state(dash.key) if dash else None
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx_kw: dict = {"viewport": VIEWPORT, "user_agent": USER_AGENT}
        if storage_state:
            ctx_kw["storage_state"] = storage_state
        context = await browser.new_context(**ctx_kw)
        page = await context.new_page()
        await page.goto(final_url, wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(1500)
        (trace_dir / "final.png").write_bytes(await page.screenshot(type="png"))
        await context.close()
        await browser.close()
    err = trace_dir / "screenshot_error.txt"
    if err.is_file():
        err.unlink()
    return True


async def main_async(manifest: Path | None, limit: int) -> int:
    paths: list[Path] = []
    if manifest:
        data = json.loads(manifest.read_text())
        for r in data.get("runs") or []:
            td = r.get("trace_dir")
            if td:
                paths.append(Path(td) / "run.json")
    else:
        traces = ROOT / "results" / "capability" / "traces"
        paths = list(traces.glob("bu_*/run.json"))
    ok = fail = skip = 0
    for i, rp in enumerate(paths[:limit] if limit else paths):
        if not rp.is_file():
            continue
        png = rp.parent / "final.png"
        if png.is_file():
            skip += 1
            continue
        try:
            await capture_one(rp)
            ok += 1
            print(f"OK  {rp.parent.name}")
        except Exception as exc:  # noqa: BLE001
            fail += 1
            (rp.parent / "screenshot_error.txt").write_text(str(exc)[:400])
            print(f"FAIL {rp.parent.name}: {exc}")
    print(f"done: captured={ok} skipped={skip} failed={fail}")
    return 0 if fail == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", help="Only traces listed in this manifest")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    manifest = Path(args.manifest) if args.manifest else None
    return asyncio.run(main_async(manifest, args.limit))


if __name__ == "__main__":
    raise SystemExit(main())
