"""One quick model call that turns a bare product URL into a study plan.

A URL typed on the home page with no tasks used to wait on competitor
research and persona planning (about 20s) before any agent opened a page.
This asks Gemini once for the segment, two rival URLs, and two short tasks:
one core task done in the product (it may need an account) and one public
task (pricing or plans). The study then starts on the fast path.
"""

from __future__ import annotations

import asyncio
import os
import re
from typing import Any
from urllib.parse import urlsplit

_PROMPT = """You plan a short usability study for a web product. Reply with JSON only.
Product URL: {url}
Page title: {title}
Page text: {text}

Return:
{{"product": "short product name",
  "segment": "one short phrase naming who evaluates this product",
  "competitors": ["https://rival-one.com/", "https://rival-two.com/"],
  "tasks": ["core task", "public task"]}}

Rules:
- competitors: the two best-known direct rivals, as homepage URLs of real public sites.
- tasks[0]: the one thing a new user comes to do in the product itself, 3-8 words,
  imperative, generic enough to try on the rivals too (for example "Create a new project",
  "Draw a rectangle on the canvas", "Create a new event type").
- tasks[1]: "Look for pricing or how to get started".
- No quotes inside tasks. No explanations."""


def _clean_url(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    if "://" not in text:
        text = "https://" + text
    parts = urlsplit(text)
    if not parts.hostname or "." not in parts.hostname:
        return ""
    return f"https://{parts.hostname}/"


async def _page_hint(url: str) -> tuple[str, str]:
    """Title and a little text from the product homepage, 3s max."""
    import httpx

    try:
        async with httpx.AsyncClient(timeout=3.0, follow_redirects=True, headers={"user-agent": "Mozilla/5.0"}) as client:
            resp = await client.get(url)
        html = resp.text[:200_000]
    except Exception:
        return "", ""
    title = ""
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    if m:
        title = " ".join(m.group(1).split())[:120]
    desc = ""
    m = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)', html, re.I)
    if m:
        desc = m.group(1)
    body = re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", html, flags=re.S | re.I)
    body = " ".join(body.split())[:600]
    return title, f"{desc} {body}".strip()[:800]


async def plan_from_url(url: str, *, timeout: float = 9.0) -> dict[str, Any] | None:
    """{"segment", "competitors", "tasks"} for a bare URL, or None on any failure."""
    from capability.gemini_config import extract_json, gemini_chat

    async def _run() -> dict[str, Any] | None:
        title, text = await _page_hint(url)
        raw = await gemini_chat(
            [{"role": "user", "content": _PROMPT.format(url=url, title=title, text=text)}],
            model=os.environ.get("MVP_FAST_PLAN_MODEL") or "gemini-2.5-flash",
            temperature=0.2,
            json_mode=True,
            max_retries=2,
        )
        data = extract_json(raw)
        if not isinstance(data, dict):
            return None
        own = urlsplit(url).hostname or ""
        own = own.removeprefix("www.")
        comps: list[str] = []
        for item in data.get("competitors") or []:
            clean = _clean_url(str(item))
            host = (urlsplit(clean).hostname or "").removeprefix("www.")
            if clean and host and host != own and clean not in comps:
                comps.append(clean)
        if comps:
            from mvp.server import _landing_url

            comps = list(await asyncio.gather(*(_landing_url(c) for c in comps[:2])))
        tasks = [" ".join(str(t).split())[:120] for t in (data.get("tasks") or []) if str(t).strip()]
        if not tasks:
            return None
        if len(tasks) < 2:
            tasks.append("Look for pricing or how to get started")
        return {
            "product": str(data.get("product") or "")[:60],
            "segment": " ".join(str(data.get("segment") or "").split())[:140],
            "competitors": comps[:2],
            "tasks": tasks[:2],
        }

    try:
        return await asyncio.wait_for(_run(), timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        print(f"[fast_plan] skipped: {exc!r}", flush=True)
        return None
