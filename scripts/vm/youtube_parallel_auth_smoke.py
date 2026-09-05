"""One authenticated YouTube Browser Use worker for the two-VM smoke test."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from browser_use import Agent, ChatGoogle
from browser_use.browser.profile import BrowserProfile, ProxySettings
from playwright.async_api import async_playwright

from auth import vertex_credentials
from config import GCP_PROJECT


async def verify_signed_in(state_path: Path) -> dict:
    proxy_url = os.environ.get("BROWSER_PROXY")
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            proxy={"server": proxy_url} if proxy_url else None,
        )
        context = await browser.new_context(storage_state=str(state_path))
        page = await context.new_page()
        await page.goto("https://www.youtube.com/", wait_until="domcontentloaded", timeout=60_000)
        await page.wait_for_timeout(6_000)
        result = {
            "url": page.url,
            "avatar_count": await page.locator("#avatar-btn, button#avatar-btn").count(),
            "feed_items": await page.locator("ytd-rich-item-renderer").count(),
            "sign_in_links": await page.locator('a:has-text("Sign in")').count(),
        }
        await context.close()
        await browser.close()
        return result


async def run_worker(query: str, state_path: Path, out_path: Path) -> int:
    started = datetime.now(timezone.utc)
    verify = await verify_signed_in(state_path)
    if verify["avatar_count"] < 1:
        out_path.write_text(json.dumps({"ok": False, "reason": "not_signed_in", "verify": verify}, indent=2))
        return 2

    if os.environ.get("USE_GCE_ADC") == "1":
        import urllib.request

        from google.oauth2.credentials import Credentials

        request = urllib.request.Request(
            "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",
            headers={"Metadata-Flavor": "Google"},
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            token = json.load(response)["access_token"]
        credentials = Credentials(token=token)
    else:
        credentials = vertex_credentials()
    llm = ChatGoogle(
        model="gemini-2.5-flash-lite",
        vertexai=True,
        credentials=credentials,
        project=GCP_PROJECT,
        location="us-central1",
        temperature=0,
    )
    proxy_url = os.environ.get("BROWSER_PROXY")
    profile = BrowserProfile(
        headless=True,
        storage_state=str(state_path),
        proxy=ProxySettings(server=proxy_url) if proxy_url else None,
        viewport={"width": 1280, "height": 800},
        disable_security=True,
    )
    task = (
        "You are already signed into YouTube. Go directly to https://www.youtube.com/. "
        f"Search YouTube for {query!r}. Do not open any video and do not like, subscribe, "
        "comment, or change account settings. Read the first three non-sponsored video "
        "results and finish with their exact visible titles and channels."
    )
    agent = Agent(
        task=task,
        llm=llm,
        browser_profile=profile,
        use_vision=True,
        max_actions_per_step=3,
    )
    t0 = time.time()
    history = await agent.run(max_steps=10)
    elapsed = round(time.time() - t0, 3)
    try:
        final_result = history.final_result()
    except Exception:
        final_result = str(history)[-2000:]
    try:
        urls = history.urls()
    except Exception:
        urls = []
    finished = datetime.now(timezone.utc)
    out = {
        "ok": True,
        "model": "gemini-2.5-flash-lite",
        "query": query,
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "elapsed_s": elapsed,
        "signed_in_verify": verify,
        "final_url": urls[-1] if urls else "",
        "final_result": final_result,
    }
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(json.dumps(out, indent=2, default=str), flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", required=True)
    parser.add_argument("--state", type=Path, default=Path("secrets/youtube_state.json"))
    parser.add_argument("--out", type=Path, default=Path("result.json"))
    args = parser.parse_args()
    return asyncio.run(run_worker(args.query, args.state, args.out))


if __name__ == "__main__":
    raise SystemExit(main())
