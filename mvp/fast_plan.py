"""One quick model call that turns a bare product URL into a study plan.

A URL typed on the home page with no tasks used to wait on competitor
research and persona planning (about 20s) before any agent opened a page.
This asks Gemini once for the segment, two rival URLs, and two short tasks:
one core task done in the product (it may need an account) and one task
grounded in the opening page read: a public task only when the page's links
expose it (pricing needs a pricing link), else a second in-app task. The
study then starts on the fast path.
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
Links and buttons on the page (label -> target): {links}

Return:
{{"product": "short product name",
  "segment": "one short phrase naming who evaluates this product",
  "competitors": ["https://rival-one.com/", "https://rival-two.com/"],
  "core_task": "core task",
  "public_task": "public task",
  "app_task": "second task done in the product"}}

Rules:
- competitors: the two best-known direct rivals, as homepage URLs of real public sites. Use the
  rival product's own site, not a parent company's homepage that sells many products.
- core_task: the one thing a new user comes to do in the product itself, 3-8 words,
  an imperative verb and a concrete object (never a tagline), generic enough to try on the rivals too (for example "Create a new project",
  "Draw a rectangle on the canvas", "Create a new event type"). One action whose result shows on
  one screen, never a broad activity (not "Design and prototype an interface"; say "Create a new
  design file"). If doing it needs an account,
  keep it that way; never turn it into a logged-out task.
- public_task: 3-8 words a logged-out visitor can finish from this page using only the links,
  buttons and text listed above. Use "Look for pricing or how to get started" only when a
  pricing or plans link is listed. Never name a page, link or feature that is not listed.
- app_task: a second simple action in the product itself with a visible result, 3-8 words
  (for example "Add a text label that says hello", "Add a second task to the list"); used
  when the page is the app and lists no links.
- No quotes inside tasks. No explanations."""

_PRICING_TASK = "Look for pricing or how to get started"
_PRICING_RE = re.compile(r"pric|\bplans?\b|upgrade|billing|subscri", re.I)
_STOP = {
    "a", "an", "the", "or", "and", "to", "for", "of", "on", "in", "into", "with", "how", "get", "your",
    "look", "find", "open", "see", "view", "read", "check", "browse", "go", "visit", "try", "page", "site",
    "started", "start", "new", "what", "is", "are", "about", "out", "more", "learn", "explore", "section",
}


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


def page_read_from_html(html: str) -> dict[str, Any]:
    """The opening page as the planner sees it: title, text, and the links and buttons.

    A client-rendered app ships an almost empty document, so ``links`` is
    empty there and the plan stays inside the product.
    """
    html = (html or "")[:600_000]
    title = ""
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    if m:
        title = _plain(m.group(1))[:120]
    desc = ""
    m = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)', html, re.I)
    if m:
        desc = _plain(m.group(1))
    body = re.sub(r"<script.*?</script>|<style.*?</style>|<svg.*?</svg>", " ", html, flags=re.S | re.I)
    links: list[tuple[str, str]] = []
    seen: set[str] = set()
    for m in re.finditer(r"<(a|button)\b([^>]*)>(.*?)</\1>", body, re.S | re.I):
        attrs, inner = m.group(2), m.group(3)
        href = ""
        hm = re.search(r'href=["\']([^"\']+)["\']', attrs, re.I)
        if hm:
            href = hm.group(1)
        label = _plain(re.sub(r"<[^>]+>", " ", inner))
        if not label:
            am = re.search(r'aria-label=["\']([^"\']+)["\']', attrs, re.I)
            label = _plain(am.group(1)) if am else ""
        if not label or len(label) > 60 or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        key = label.lower()
        if key in seen:
            continue
        seen.add(key)
        links.append((label, href[:80]))
    text = _plain(re.sub(r"<[^>]+>", " ", body))
    return {"title": title, "text": f"{desc} {text}".strip()[:800], "links": links[:300]}


def _plain(text: str) -> str:
    import html as _html

    return " ".join(_html.unescape(text or "").split())


async def _page_read(url: str) -> dict[str, Any]:
    """The product homepage read over HTTP, 3s max. Empty on any failure."""
    import httpx

    try:
        async with httpx.AsyncClient(timeout=3.0, follow_redirects=True, headers={"user-agent": "Mozilla/5.0"}) as client:
            resp = await client.get(url)
        if resp.status_code >= 400:
            return {"title": "", "text": "", "links": [], "failed": True}
        return page_read_from_html(resp.text)
    except Exception:
        return {"title": "", "text": "", "links": [], "failed": True}


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9+]{3,}", (text or "").lower()) if w not in _STOP}


def task_grounded(task: str, read: dict[str, Any]) -> bool:
    """True when a logged-out task only names things this page exposes.

    Pricing needs a pricing or plans link. Any other public task needs one
    of its content words in a link label, a link target, or the page text.
    """
    links = list(read.get("links") or [])
    exposed = " ".join(f"{label} {href}" for label, href in links)
    if _PRICING_RE.search(task or ""):
        return bool(_PRICING_RE.search(exposed))
    words = _words(task)
    if not words:
        return False
    pool = _words(exposed) | _words(str(read.get("title") or "")) | _words(str(read.get("text") or ""))
    return bool(words & pool)


def choose_tasks(data: dict[str, Any], read: dict[str, Any]) -> list[str]:
    """[core task, second task]: the public task when the page exposes it, else a second in-app task."""

    def clean(value: Any) -> str:
        return " ".join(str(value or "").split())[:120]

    legacy = [clean(t) for t in (data.get("tasks") or []) if clean(t)]
    core = clean(data.get("core_task")) or (legacy[0] if legacy else "")
    public = clean(data.get("public_task")) or (legacy[1] if len(legacy) > 1 else "")
    app = clean(data.get("app_task"))
    if not core:
        return []
    links = list(read.get("links") or [])
    if read.get("failed"):
        # The page could not be read: nothing to ground on, keep the usual pair.
        return [core, public or _PRICING_TASK]
    if links and task_grounded(_PRICING_TASK, read):
        # The page links to pricing: the one public task every rival can be
        # judged on the same way (the pricing page itself).
        second = _PRICING_TASK
    elif links and public and task_grounded(public, read) and _checkable(public):
        second = public
    elif app and app.lower() != core.lower():
        # The page is the app (no links) or exposes no checkable public page:
        # a second thing to do in the product.
        second = app
    else:
        second = ""
    return [core, second] if second else [core]


def _checkable(task: str) -> bool:
    """A public task whose finish the agent can check from the page it lands on."""
    from mvp.a11y_agent import task_kind

    return task_kind(task) in {"pricing", "changelog", "help", "export"}


def _links_for_prompt(read: dict[str, Any]) -> str:
    links = list(read.get("links") or [])
    if not links:
        return "none (the page lists no links; it is probably the app itself)"
    # Mega-menus list dozens of features first; keep pricing and sign-up links in view.
    key = [pair for pair in links if _PRICING_RE.search(" ".join(pair)) or re.search(r"sign|log ?in|start|try", pair[0], re.I)]
    shown = links[:40] + [pair for pair in key if pair not in links[:40]][:8]
    return "; ".join(f"{label} -> {href}" if href else label for label, href in shown)


async def plan_from_url(url: str, *, timeout: float = 9.0) -> dict[str, Any] | None:
    """{"segment", "competitors", "tasks"} for a bare URL, or None on any failure."""
    from capability.gemini_config import extract_json, gemini_chat

    async def _run() -> dict[str, Any] | None:
        read = await _page_read(url)
        prompt = _PROMPT.format(
            url=url, title=read.get("title") or "", text=read.get("text") or "", links=_links_for_prompt(read)
        )
        raw = await gemini_chat(
            [{"role": "user", "content": prompt}],
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
        tasks = choose_tasks(data, read)
        if not tasks:
            return None
        print(f"[fast_plan] {url} links={len(read.get('links') or [])} tasks={tasks}", flush=True)
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
