"""Study submits from harnesses that wait out the server's start cap (429 + Retry-After).

The server admits at most ``MVP_MAX_STUDY_STARTS`` studies per window and
answers the rest with 429. A harness that submits several studies back to
back waits the advertised time and retries, up to
``MVP_HARNESS_429_MAX_WAIT_S`` in total (default 900s, beyond the 600s window).
"""
from __future__ import annotations

import asyncio
import os
import time
import urllib.error
import urllib.request
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Mapping

DEFAULT_WAIT_S = 30.0
MAX_ATTEMPTS = 12


def max_wait_s() -> float:
    try:
        return max(0.0, float(os.environ.get("MVP_HARNESS_429_MAX_WAIT_S") or "900"))
    except ValueError:
        return 900.0


def retry_after_s(headers: Mapping[str, str] | Any) -> float:
    """Seconds from a Retry-After header (seconds or HTTP date); DEFAULT_WAIT_S when absent or bad."""
    raw = ""
    try:
        raw = str(headers.get("Retry-After") or headers.get("retry-after") or "").strip()
    except Exception:
        raw = ""
    if not raw:
        return DEFAULT_WAIT_S
    try:
        return max(1.0, float(raw))
    except ValueError:
        pass
    try:
        return max(1.0, parsedate_to_datetime(raw).timestamp() - time.time())
    except Exception:
        return DEFAULT_WAIT_S


class _Budget:
    def __init__(self, limit_s: float | None) -> None:
        self.limit = max_wait_s() if limit_s is None else float(limit_s)
        self.waited = 0.0
        self.attempts = 0

    def next_wait(self, wanted: float) -> float | None:
        """How long to sleep before the next try, or None when the budget is spent."""
        left = self.limit - self.waited
        if self.attempts >= MAX_ATTEMPTS or left <= 0 or wanted > left:
            return None
        self.attempts += 1
        self.waited += wanted
        return wanted


def urlopen_submit(
    req: urllib.request.Request,
    *,
    timeout: float,
    max_wait: float | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> Any:
    """``urllib.request.urlopen(req)`` that retries 429s after Retry-After, within the budget."""
    budget = _Budget(max_wait)
    while True:
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as exc:
            if exc.code != 429:
                raise
            wait = budget.next_wait(retry_after_s(exc.headers))
            if wait is None:
                raise
            print(f"study submit got 429; retrying in {wait:.0f}s ({budget.waited:.0f}s waited)", flush=True)
            sleep(wait)


async def click_run(page: Any, selector: str = "#submit-btn", *, max_wait: float | None = None) -> float:
    """Click Run in the UI; on a 429 from POST /api/studies wait Retry-After and click again.

    Returns the wall time of the click the server accepted, so harness clocks
    that start at Run do not include the wait.
    """
    from urllib.parse import urlsplit

    def _is_submit(resp: Any) -> bool:
        return resp.request.method == "POST" and urlsplit(resp.url).path.rstrip("/") == "/api/studies"

    budget = _Budget(max_wait)
    while True:
        clicked_at = time.time()
        async with page.expect_response(_is_submit, timeout=120_000) as info:
            await page.click(selector)
        resp = await info.value
        if resp.status != 429:
            return clicked_at
        wait = budget.next_wait(retry_after_s(resp.headers))
        if wait is None:
            raise RuntimeError(f"study submit still rate limited after {budget.waited:.0f}s")
        print(f"Run got 429; clicking again in {wait:.0f}s", flush=True)
        await asyncio.sleep(wait)
        await page.wait_for_selector(f"{selector}:not([disabled])", timeout=30_000)
