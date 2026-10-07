"""E2E: one simulated user driven over MCP, on a real product, in our Browserbase.

A scripted MCP client (fixed actions, no LLM) plays the coding agent:
start a session, open watch_url in Chromium and require the live Browserbase
iframe on the same stage a website Run shows, act, finish, then require
proof.pass in the report. Run against a local server or the deployed site:

  PYTHONPATH=src:. python -m mvp.e2e_mcp --base http://127.0.0.1:8787
  PYTHONPATH=src:. python -m mvp.e2e_mcp --base https://usersim.vercel.app
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from typing import Any

PRODUCT_URL = "https://books.toscrape.com/"
TASK = "Find a travel book you might like and open its page to see the price."
PERSONA = "A retired teacher who buys books online a few times a year; comfortable with the web but not a power user."
SCRIPT = [
    ({"type": "scroll", "dy": 500}, "Let me look down the page to see what's here."),
    ({"type": "scroll", "dy": -500}, "There is a category list on the left; going back up."),
    (
        {"type": "navigate", "url": "https://books.toscrape.com/catalogue/category/books/travel_2/index.html"},
        "I'll open the Travel category.",
    ),
    (
        {"type": "navigate", "url": "https://books.toscrape.com/catalogue/its-only-the-himalayas_981/index.html"},
        "This one looks interesting, opening it.",
    ),
]


def _meta(result: Any) -> dict[str, Any]:
    for item in result.content:
        if getattr(item, "type", "") == "text":
            try:
                return json.loads(item.text)
            except ValueError:
                return {"text": item.text}
    return {}


def _has_image(result: Any) -> bool:
    return any(getattr(item, "type", "") == "image" and len(getattr(item, "data", "")) > 1000 for item in result.content)


async def _watch_live(watch_url: str, timeout_s: float = 45.0) -> dict[str, Any]:
    """The study page mounts the Browserbase live iframe while the user is working."""
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        exe = os.environ.get("PLAYWRIGHT_CHROMIUM_PATH") or None
        browser = await pw.chromium.launch(executable_path=exe)
        page = await browser.new_page(viewport={"width": 1400, "height": 900})
        await page.goto(watch_url, wait_until="domcontentloaded")
        deadline = time.time() + timeout_s
        src = ""
        while time.time() < deadline:
            src = await page.evaluate(
                "() => (document.querySelector('iframe.stage-live-frame') || {}).src || ''"
            )
            if src:
                break
            await asyncio.sleep(1)
        shot = await page.screenshot()
        await browser.close()
    return {"live_iframe_src": src[:120], "stage_png_bytes": len(shot)}


async def run(base: str, watch: bool) -> dict[str, Any]:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    fails: list[str] = []
    out: dict[str, Any] = {"base": base}
    async with streamablehttp_client(f"{base.rstrip('/')}/mcp") as (read, write, _):
        async with ClientSession(read, write) as mcp:
            await mcp.initialize()
            tools = {t.name for t in (await mcp.list_tools()).tools}
            prompts = {p.name for p in (await mcp.list_prompts()).prompts}
            want = {"usersim_start_session", "usersim_observe", "usersim_act", "usersim_finish", "usersim_get_report"}
            if not want <= tools:
                fails.append(f"missing tools: {sorted(want - tools)}")
            if "usersim_simulate_user" not in prompts:
                fails.append("missing prompt usersim_simulate_user")

            bad = _meta(await mcp.call_tool("usersim_start_session", {"product_url": "http://localhost:3000", "task": "x", "persona": "y"}))
            if "error" not in bad:
                fails.append("localhost product_url was accepted")

            t0 = time.time()
            start = await mcp.call_tool("usersim_start_session", {"product_url": PRODUCT_URL, "task": TASK, "persona": PERSONA})
            meta = _meta(start)
            out["start_s"] = round(time.time() - t0, 1)
            if "error" in meta:
                raise SystemExit(f"start failed: {meta['error']}")
            sid, study_id = meta["session_id"], meta["study_id"]
            out.update(study_id=study_id, watch_url=meta.get("watch_url"), engine_version=meta.get("engine_version"))
            if not _has_image(start):
                fails.append("start returned no screenshot")
            if meta.get("driver_model"):
                fails.append(f"start response names a driver model: {meta.get('driver_model')!r}")

            try:
                await _drive(mcp, sid, study_id, meta, watch, fails, out)
            finally:
                if "finish" not in out:
                    await mcp.call_tool("usersim_finish", {"session_id": sid, "outcome": "blocked", "notes": "e2e aborted"})
    out["fails"] = fails
    out["pass"] = not fails
    return out


async def _drive(mcp: Any, sid: str, study_id: str, meta: dict[str, Any], watch: bool, fails: list[str], out: dict[str, Any]) -> None:
    watch_task = asyncio.create_task(_watch_live(meta["watch_url"])) if watch else None

    off = _meta(await mcp.call_tool("usersim_act", {"session_id": sid, "action": {"type": "navigate", "url": "https://example.org/"}, "thought": "x"}))
    if "error" not in off:
        fails.append("off-site navigate was allowed")

    for action, thought in SCRIPT:
        res = await mcp.call_tool("usersim_act", {"session_id": sid, "action": action, "thought": thought})
        m = _meta(res)
        if "error" in m:
            fails.append(f"act {action['type']} failed: {m['error']}")
        elif not _has_image(res):
            fails.append(f"act {action['type']} returned no screenshot")
    if watch_task is not None:
        live = await watch_task
        out["watch"] = live
        if not live["live_iframe_src"]:
            fails.append("watch_url never mounted the live Browserbase iframe")

    fin = _meta(await mcp.call_tool("usersim_finish", {"session_id": sid, "outcome": "completed", "notes": "Found the travel category quickly."}))
    out["finish"] = fin
    rep = json.loads(_meta_text(await mcp.call_tool("usersim_get_report", {"study_id": study_id, "format": "json"})))
    md = _meta_text(await mcp.call_tool("usersim_get_report", {"study_id": study_id}))
    out["proof"] = rep["proof"]
    out["judge"] = rep["judge"]
    out["num_steps"] = rep["num_steps"]
    if not rep["proof"].get("pass"):
        fails.append("proof failed: " + ", ".join(c["name"] for c in rep["proof"]["checks"] if not c["pass"]))
    if rep["num_steps"] < 1 + len(SCRIPT):
        fails.append(f"report has {rep['num_steps']} steps, want {1 + len(SCRIPT)}")
    if "# UserSim report" not in md:
        fails.append("markdown report missing")
    after = _meta(await mcp.call_tool("usersim_act", {"session_id": sid, "action": {"type": "wait"}, "thought": "x"}))
    if "error" not in after:
        fails.append("act after finish was allowed")


def _meta_text(result: Any) -> str:
    return next((i.text for i in result.content if getattr(i, "type", "") == "text"), "")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8787")
    ap.add_argument("--no-watch", action="store_true", help="skip the Chromium check of watch_url")
    args = ap.parse_args()
    result = asyncio.run(run(args.base, watch=not args.no_watch))
    print(json.dumps(result, indent=1))
    sys.exit(0 if result["pass"] else 1)


if __name__ == "__main__":
    main()
