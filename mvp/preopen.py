"""Open the product agents' browsers while the fast plan is still being written.

URL submit -> first click used to be serial: landing-URL resolve, the ~2s fast
plan, then Browserbase create + CDP connect + goto (~3s), then waiting for the
page to render before the first read (~2.5s on linear.app), then the first
decision. The product URL is known at submit, so the product agents' browsers
(personas x ~2 tasks = 8 by default) can be created and navigated in parallel
with the plan. When the agents start they take an already-open, already-rendered
page (``claim``) instead of creating one; anything unclaimed is closed at the end
of the study (``release``) or after ``MVP_PREOPEN_TTL_S``.

Only runs when the browser queue would admit the study at once (no other study
active or queued here, enough free sessions and create tokens), and then marks
the study admitted so ``browser_slots.acquire`` does not re-count its own
pre-opened sessions as someone else's. ``MVP_PREOPEN=0`` turns it off.
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import Any
from urllib.parse import urlparse

_POOLS: dict[str, dict[str, Any]] = {}
_ADMITTED: set[str] = set()
_PW: Any = None
_PW_LOCK: asyncio.Lock | None = None


def _host(url: str) -> str:
    try:
        h = (urlparse(url).hostname or "").lower()
    except Exception:
        return ""
    return h[4:] if h.startswith("www.") else h


def preopen_count(study: Any) -> int:
    try:
        cap = int(os.environ.get("MVP_PREOPEN", "8") or "0")
    except ValueError:
        cap = 8
    if cap <= 0 or getattr(study, "test_mode", False):
        return 0
    try:
        personas = max(1, int(os.environ.get("MVP_PERSONA_COUNT", "4") or "4"))
    except ValueError:
        personas = 4
    tasks = len(getattr(study, "tasks_override", None) or []) or 2
    n = min(cap, personas * tasks)
    max_agents = int(getattr(study, "max_agents", 0) or 0)
    if max_agents > 0:
        n = min(n, max_agents)
    return max(0, n)


def admitted(study_id: str | None) -> bool:
    return bool(study_id) and study_id in _ADMITTED


def take_admission(study_id: str | None) -> bool:
    """browser_slots.acquire: this study already passed the queue check when its browsers were pre-opened."""
    if not study_id or study_id not in _ADMITTED:
        return False
    _ADMITTED.discard(study_id)
    return True


def busy_elsewhere(study_id: str) -> bool:
    return any(sid != study_id for sid in _ADMITTED)


async def _playwright() -> Any:
    global _PW, _PW_LOCK
    if _PW_LOCK is None:
        _PW_LOCK = asyncio.Lock()
    async with _PW_LOCK:
        if _PW is None:
            from playwright.async_api import async_playwright

            _PW = await async_playwright().start()
    return _PW


async def _open_one(study_id: str, url: str, pool: dict[str, Any]) -> None:
    from capability.bb_rate import PRIORITY_PRODUCT
    from mvp.a11y_agent import _close_agent_session, _create_session_or_close

    entry: dict[str, Any] | None = None
    bb = browser = None
    try:
        bb = await _create_session_or_close(study_id, timeout=12, priority=PRIORITY_PRODUCT, wait_s=12)
        pw = await _playwright()
        browser = await pw.chromium.connect_over_cdp(bb.connect_url)
        context = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = context.pages[0] if context.pages else await context.new_page()
        try:
            await page.set_viewport_size({"width": 1440, "height": 900})
        except Exception:
            pass
        try:
            page.set_default_timeout(8000)
            page.set_default_navigation_timeout(8000)
        except Exception:
            pass
        started = time.time()
        await page.goto(url, wait_until="commit", timeout=4500)
        opened = time.time()
        if opened - started > 4.5 or opened <= started:
            raise RuntimeError("pre-open goto missed 4.5s")
        entry = {"bb": bb, "browser": browser, "page": page, "started": started, "opened": opened}
    except Exception as exc:  # noqa: BLE001
        print(f"[preopen] {study_id[:8]} open failed: {exc!r}", flush=True)
        if bb is not None or browser is not None:
            await _close_agent_session(browser, bb)
        entry = None
    if entry is not None and pool.get("closed"):
        await _close_agent_session(entry["browser"], entry["bb"])
        entry = None
    await pool["q"].put(entry)


async def _start(study: Any, url: str, n: int) -> None:
    from mvp import browser_slots

    study_id = str(study.id)
    try:
        counted = await browser_slots._count(max_age_s=5.0)
    except Exception:
        counted = None
    need = browser_slots.needed_sessions(study)
    if counted is None:
        return
    free = browser_slots.session_cap() - int(counted.get("n") or 0)
    burst = browser_slots.burst_state(need, counted)
    if free < need or not burst.get("ok"):
        print(f"[preopen] {study_id[:8]} skipped: free={free} need={need} burst_ok={burst.get('ok')}", flush=True)
        return
    if browser_slots._ACTIVE or browser_slots._TICKETS or busy_elsewhere(study_id):
        return
    _ADMITTED.add(study_id)
    pool = {"q": asyncio.Queue(), "n": n, "claims": 0, "host": _host(url), "url": url, "closed": False, "t0": time.time()}
    _POOLS[study_id] = pool
    print(f"[preopen] {study_id[:8]} opening {n} product browsers on {url}", flush=True)
    for _ in range(n):
        asyncio.get_running_loop().create_task(_open_one(study_id, url, pool))
    try:
        ttl = float(os.environ.get("MVP_PREOPEN_TTL_S", "90") or "90")
    except ValueError:
        ttl = 90.0

    async def _expire() -> None:
        await asyncio.sleep(ttl)
        await release(study_id, reason="ttl")

    asyncio.get_running_loop().create_task(_expire())


def start_preopen(study: Any, url: str) -> None:
    """Fire-and-forget: create + navigate the product agents' browsers now."""
    from mvp import browser_slots

    if not browser_slots._enabled():
        return
    if os.environ.get("MVP_A11Y_LOOP", "1").lower() in {"0", "false", "no"}:
        return
    n = preopen_count(study)
    if n <= 0 or browser_slots._ACTIVE or browser_slots._TICKETS or busy_elsewhere(str(study.id)):
        return
    try:
        asyncio.get_running_loop().create_task(_start(study, url, n))
    except RuntimeError:
        return


async def claim(study_id: str | None, url: str, wait_s: float = 8.0) -> tuple[Any, Any, Any, float, float] | None:
    """An open page on ``url`` for this study's agent, or None (the caller creates its own)."""
    if not study_id:
        return None
    pool = _POOLS.get(study_id)
    if not pool or pool.get("closed") or _host(url) != pool.get("host"):
        return None
    if pool["claims"] >= pool["n"]:
        return None
    pool["claims"] += 1
    try:
        entry = await asyncio.wait_for(pool["q"].get(), timeout=wait_s)
    except asyncio.TimeoutError:
        return None
    if not entry:
        return None
    page, browser = entry["page"], entry["browser"]
    try:
        alive = (not page.is_closed()) and browser.is_connected()
    except Exception:
        alive = False
    if not alive:
        from mvp.a11y_agent import _close_agent_session

        await _close_agent_session(browser, entry["bb"])
        return None
    print(f"[preopen] {study_id[:8]} claimed a page opened {time.time() - entry['opened']:.1f}s ago", flush=True)
    return entry["bb"], browser, page, entry["started"], entry["opened"]


async def release(study_id: str | None, *, reason: str = "end", keep_admitted: bool = False) -> int:
    """Close pre-opened pages nobody claimed. Returns how many were closed."""
    if not study_id:
        return 0
    if not keep_admitted:
        _ADMITTED.discard(study_id)
    pool = _POOLS.pop(study_id, None)
    if not pool:
        return 0
    pool["closed"] = True
    from mvp.a11y_agent import _close_agent_session

    closed = 0
    while True:
        try:
            entry = pool["q"].get_nowait()
        except asyncio.QueueEmpty:
            break
        if entry:
            await _close_agent_session(entry["browser"], entry["bb"])
            closed += 1
    if closed:
        print(f"[preopen] {study_id[:8]} closed {closed} unclaimed browsers ({reason})", flush=True)
    return closed
