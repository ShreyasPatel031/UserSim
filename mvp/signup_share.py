"""Share one signed-in session per (study, site) when a site stops sending sign-in emails.

Zo (study 7b5f0af9) treats every Gmail plus-alias as the same account and sent
exactly 10 "Log in to Zo" emails for the first 10 of 20 parallel signups, then
none: the other 10 agents waited 190-270s for mail that never came (6
email_timeout, 4 TimeoutError) and fell back to reading the website. The same
10-then-nothing pattern happened in study 50f0954c half an hour earlier.

When a signup on a site fails waiting for its email (or times out) while
another agent of the same study already signed in on that site, this module
copies that agent's cookies into the failing agent's browser and opens the app
URL it reached; the signed-in check decides whether it worked. Every agent still
tries its own fresh signup first, so sites that do create separate accounts keep
doing so. localStorage tokens are not copied: a site that keeps its session only
there falls back to the old outcome (signup failed).
"""

from __future__ import annotations

import os
import time
from typing import Any

_SHARED: dict[tuple[str, str], dict[str, Any]] = {}
_TTL_S = 3600.0

# Signup failures that mean "the email or the clock ran out", not "the site said no".
_RETRYABLE = ("email_timeout", "timeout", "timeouterror", "no time left")


def enabled() -> bool:
    return os.environ.get("MVP_SIGNUP_SHARE", "1").strip().lower() not in {"0", "false", "no"}


def retryable(reason: str) -> bool:
    low = str(reason or "").strip().lower()
    return any(low.startswith(r) or r in low for r in _RETRYABLE)


def remember(key: str, site: str, cookies: list[dict[str, Any]], url: str, email: str = "") -> None:
    if not key or not site or not cookies:
        return
    _SHARED[(key, site)] = {"cookies": list(cookies), "url": url, "email": email, "ts": time.time()}


def get(key: str, site: str) -> dict[str, Any] | None:
    row = _SHARED.get((key, site))
    if not row or time.time() - float(row.get("ts") or 0) > _TTL_S:
        return None
    return row


def has(key: str, site: str) -> bool:
    return enabled() and get(key, site) is not None


async def save_from_page(page: Any, key: str, site: str, email: str = "") -> bool:
    """After a signup succeeded: keep this browser's cookies for the site's later failures."""
    if not enabled() or not key or not site:
        return False
    try:
        cookies = await page.context.cookies()
    except Exception:  # noqa: BLE001
        return False
    mine = [c for c in cookies if site in str(c.get("domain") or "")]
    remember(key, site, mine or cookies, str(getattr(page, "url", "") or ""), email)
    return bool(mine or cookies)


async def reuse(page: Any, key: str, site: str) -> dict[str, Any] | None:
    """Sign this browser in with the study's shared session. Returns a signup result or None."""
    row = get(key, site) if enabled() else None
    if not row:
        return None
    from mvp.signup_in_session import _settle, _snapshot, _verify_signed_in

    started = time.time()
    try:
        await page.context.add_cookies(row["cookies"])
        await page.goto(row["url"], wait_until="domcontentloaded", timeout=15000)
        await _settle(page, 2500)
        snap = await _snapshot(page)
        ok, evidence = await _verify_signed_in(snap)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": f"shared_session_failed: {exc!r}"[:160]}
    if not ok:
        return {"ok": False, "reason": "shared_session_not_signed_in", "evidence": evidence}
    return {
        "ok": True,
        "reason": "shared_session",
        "email": row.get("email") or "",
        "evidence": evidence,
        "elapsed_s": round(time.time() - started, 1),
        "final_url": str(getattr(page, "url", "") or ""),
    }


# ---------------------------------------------------------------- one shared account

_LEADING: dict[tuple[str, str], bool] = {}
_DONE_EVENTS: dict[tuple[str, str], Any] = {}
_FRESH: dict[tuple[str, str], int] = {}


def shared_account_hosts() -> set[str]:
    """Sites where every agent of a study uses ONE test account.

    MVP_SIGNUP_SHARED_ACCOUNT_HOSTS, comma separated, default "zo.computer".
    Zo treats every alias of the test Gmail inbox (plus tags, dots,
    googlemail.com) as the same account and sends about 10 sign-in mails before
    going quiet, so 18 parallel signups cannot each get an account. Set it to
    "" once separate inboxes exist (e.g. a catch-all domain) to give each agent
    its own account again.
    """
    raw = os.environ.get("MVP_SIGNUP_SHARED_ACCOUNT_HOSTS")
    if raw is None:
        raw = "zo.computer"
    return {h.strip().lower().removeprefix("www.") for h in raw.split(",") if h.strip()}


def shares_account(site: str) -> bool:
    return enabled() and (site or "").lower().removeprefix("www.") in shared_account_hosts()


def _max_fresh() -> int:
    try:
        return max(1, int(os.environ.get("MVP_SIGNUP_SHARED_MAX_FRESH") or 3))
    except ValueError:
        return 3


async def signup_or_share(
    page: Any,
    key: str,
    site: str,
    run_signup: Any,
    *,
    wait_s: float,
    log: Any = print,
) -> dict[str, Any]:
    """One agent signs up (gets the magic link); the rest wait and reuse its session.

    ``run_signup`` is an async callable returning a signup result dict. If the
    leading signup fails, the next waiting agent tries its own, up to
    MVP_SIGNUP_SHARED_MAX_FRESH fresh signups per study and site. Results that
    came from the shared session carry ``shared_account=True``.
    """
    import asyncio

    k = (key, site)
    started = time.time()
    while True:
        if has(key, site):
            shared = await reuse(page, key, site)
            if shared and shared.get("ok"):
                log(f"[signup] {site}: signed in with the study's shared test account ({shared.get('elapsed_s')}s)")
                return {**shared, "reason": "shared_account", "shared_account": True}
            log(f"[signup] {site}: shared account reuse failed: {(shared or {}).get('reason')}")
        if not _LEADING.get(k):
            if _FRESH.get(k, 0) >= _max_fresh():
                return {"ok": False, "reason": f"shared account signup failed after {_FRESH[k]} tries"}
            _LEADING[k] = True
            _FRESH[k] = _FRESH.get(k, 0) + 1
            event = _DONE_EVENTS[k] = asyncio.Event()
            log(f"[signup] {site}: fresh signup #{_FRESH[k]} for the study's shared test account")
            result: dict[str, Any] = {"ok": False, "reason": "signup crashed"}
            try:
                result = dict(await run_signup() or {})
                if result.get("ok"):
                    saved = await save_from_page(page, key, site, str(result.get("email") or ""))
                    log(f"[signup] {site}: shared test account {'saved' if saved else 'NOT saved'}")
            finally:
                _LEADING[k] = False
                event.set()
            result["shared_account_leader"] = True
            return result
        left = wait_s - (time.time() - started)
        if left <= 1:
            return {"ok": False, "reason": "timeout waiting for the shared account signup"}
        try:
            await asyncio.wait_for(_DONE_EVENTS[k].wait(), timeout=left)
        except asyncio.TimeoutError:
            return {"ok": False, "reason": "timeout waiting for the shared account signup"}
