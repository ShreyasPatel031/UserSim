"""Provision two Runloop Devboxes and run concurrent Chromium searches.

The API key is read with getpass and never written to disk or command output.
Every Devbox is shut down in a finally block.
"""

from __future__ import annotations

import asyncio
import getpass
import json
import shlex
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import quote_plus

from runloop_api_client import AsyncRunloopSDK


QUERIES = ("motivational videos", "personal productivity videos")
BLUEPRINT = "runloop/universal-ubuntu-24.04-x86_64"


@dataclass
class Result:
    worker: int
    query: str
    devbox_id: str
    create_s: float
    browse_s: float
    exit_code: int | None
    evidence: dict | None
    stderr_tail: str


async def one(sdk: AsyncRunloopSDK, worker: int, query: str) -> Result:
    create_started = time.monotonic()
    devbox = await sdk.devbox.create(
        name=f"usersim-runloop-smoke-{int(time.time())}-{worker}",
        blueprint_name=BLUEPRINT,
    )
    create_s = time.monotonic() - create_started
    try:
        setup = await devbox.cmd.exec(
            command=(
                "python3 -m venv /tmp/browser-venv && "
                "/tmp/browser-venv/bin/pip -q install playwright && "
                "/tmp/browser-venv/bin/playwright install --with-deps chromium"
            )
        )
        if setup.exit_code != 0:
            return Result(
                worker, query, devbox.id, round(create_s, 3), 0.0,
                setup.exit_code, None, (await setup.stderr())[-2000:],
            )

        target = "https://www.youtube.com/results?search_query=" + quote_plus(query)
        code = (
            "import asyncio,json\n"
            "from playwright.async_api import async_playwright\n"
            f"URL={target!r}\n"
            "async def main():\n"
            " async with async_playwright() as p:\n"
            "  b=await p.chromium.launch(headless=True,args=['--no-sandbox']); "
            "  page=await b.new_page(viewport={'width':1280,'height':800}); "
            "  await page.goto(URL,wait_until='domcontentloaded',timeout=90000); "
            "  await page.wait_for_timeout(5000); "
            "  titles=[t.strip() for t in await page.locator('a#video-title').all_text_contents() if t.strip()][:5]; "
            "  print(json.dumps({'url':page.url,'title':await page.title(),'video_titles':titles,'video_count':len(titles)})); "
            "  await b.close()\n"
            "asyncio.run(main())"
        )
        browse_started = time.monotonic()
        execution = await devbox.cmd.exec(
            command=f"/tmp/browser-venv/bin/python -c {shlex.quote(code)}"
        )
        browse_s = time.monotonic() - browse_started
        stdout = (await execution.stdout()).strip().splitlines()
        evidence = None
        for line in reversed(stdout):
            try:
                evidence = json.loads(line)
                break
            except json.JSONDecodeError:
                continue
        return Result(
            worker=worker,
            query=query,
            devbox_id=devbox.id,
            create_s=round(create_s, 3),
            browse_s=round(browse_s, 3),
            exit_code=execution.exit_code,
            evidence=evidence,
            stderr_tail=(await execution.stderr())[-2000:],
        )
    finally:
        await devbox.shutdown()


async def main() -> int:
    key = getpass.getpass("Runloop API key: ")
    sdk = AsyncRunloopSDK(bearer_token=key)
    started = time.monotonic()
    rows = await asyncio.gather(*(one(sdk, i, q) for i, q in enumerate(QUERIES)))
    summary = {
        "elapsed_s": round(time.monotonic() - started, 3),
        "workers": len(rows),
        "passed": sum(
            row.exit_code == 0
            and bool(row.evidence)
            and row.evidence.get("video_count", 0) > 0
            for row in rows
        ),
        "results": [asdict(row) for row in rows],
    }
    out = Path("results/runloop_video/two_devbox_smoke.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return 0 if summary["passed"] == len(rows) else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
