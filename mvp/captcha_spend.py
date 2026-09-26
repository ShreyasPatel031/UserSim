"""CapSolver research budget.

The key is read only from ``CAPSOLVER_API_KEY``. This module never logs it.

Hard caps, enforced before every ``createTask``:

- $15 total (the other $5 of a $20 balance stays untouched)
- $1.50 per site
- 3 solves per signup attempt
- 2 signup attempts per site

Only task types on CapSolver's published price list are sent. Arkose/FunCaptcha
and hCaptcha are not on that list (docs.capsolver.com/en/pricing/, 2026-09-25),
so those calls are refused with no HTTP request.
"""

from __future__ import annotations

import json
import os
import threading
import time
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

# USD per solve from https://docs.capsolver.com/en/pricing/ (per 1,000 tokens).
PRICED_TASKS_USD: dict[str, float] = {
    "ReCaptchaV2TaskProxyLess": 0.80 / 1000,
    "ReCaptchaV2EnterpriseTaskProxyLess": 1.00 / 1000,
    "ReCaptchaV3TaskProxyLess": 1.00 / 1000,
    "ReCaptchaV3EnterpriseTaskProxyLess": 3.00 / 1000,
    "AntiTurnstileTaskProxyLess": 1.20 / 1000,
}

TOTAL_CAP_USD = 15.0
PER_SITE_CAP_USD = 1.50
MAX_SOLVES_PER_ATTEMPT = 3
MAX_SIGNUP_ATTEMPTS = 2

_LOCK = threading.Lock()
_SITE: ContextVar[str] = ContextVar("captcha_spend_site", default="")
_ATTEMPT: ContextVar[int] = ContextVar("captcha_spend_attempt", default=0)


class SpendCapError(RuntimeError):
    pass


def ledger_path() -> Path:
    raw = (os.environ.get("CAPTCHA_SPEND_LEDGER") or "").strip()
    if raw:
        return Path(raw)
    return ROOT / "results" / "captcha_spend" / "ledger.jsonl"


def capsolver_key() -> str:
    """Research key. Env only — never the vault, never a log line."""
    return (os.environ.get("CAPSOLVER_API_KEY") or "").strip()


def paid_hosts() -> set[str]:
    raw = os.environ.get("MVP_CAPTCHA_PAID_HOSTS") or ""
    return {h.strip().lower().removeprefix("www.") for h in raw.split(",") if h.strip()}


def bind_signup(site: str, attempt: int) -> None:
    _SITE.set((site or "").strip().lower().removeprefix("www."))
    _ATTEMPT.set(int(attempt))


def current_site() -> str:
    return _SITE.get() or ""


def current_attempt() -> int:
    return int(_ATTEMPT.get() or 0)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_rows() -> list[dict[str, Any]]:
    path = ledger_path()
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _append(row: dict[str, Any]) -> None:
    # Drop anything that could carry the key if a caller passes a response blob.
    clean = {k: v for k, v in row.items() if k.lower() not in {"clientkey", "api_key", "key"}}
    path = ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        with path.open("a") as fh:
            fh.write(json.dumps(clean, sort_keys=True) + "\n")


def signup_attempts(site: str) -> int:
    site = (site or "").strip().lower()
    return sum(
        1
        for row in _read_rows()
        if row.get("event") == "signup_start" and row.get("site") == site
    )


def solves_for_attempt(site: str, attempt: int) -> int:
    return sum(
        1
        for row in _read_rows()
        if row.get("event") == "createTask"
        and row.get("site") == site
        and int(row.get("attempt") or 0) == int(attempt)
    )


def spent_usd(*, site: str | None = None) -> float:
    total = 0.0
    for row in _read_rows():
        if row.get("event") != "createTask":
            continue
        if site is not None and row.get("site") != site:
            continue
        try:
            total += float(row.get("cost") or 0)
        except (TypeError, ValueError):
            continue
    return round(total, 6)


def bind_study_signup(site: str) -> int:
    """Open a CapSolver attempt for one in-study signup.

    Dollar caps and the three-solves-per-attempt cap still apply. The
    two-attempt research cap stays on ``begin_signup_attempt`` so a 24-agent
    study can sign up without turning that runner's limit off.
    """
    host = (site or "").strip().lower().removeprefix("www.")
    if not host:
        raise SpendCapError("signup attempt missing site")
    attempt = int(time.time() * 1000) % 1_000_000_000
    _append(
        {
            "event": "study_signup",
            "site": host,
            "attempt": attempt,
            "ts": _now(),
        }
    )
    bind_signup(host, attempt)
    return attempt


def begin_signup_attempt(site: str) -> int:
    """Record one fresh-alias signup. Refuses a third attempt for this site."""
    host = (site or "").strip().lower().removeprefix("www.")
    if not host:
        raise SpendCapError("signup attempt missing site")
    n = signup_attempts(host)
    if n >= MAX_SIGNUP_ATTEMPTS:
        raise SpendCapError(
            f"signup cap: {host} already has {n} attempts (max {MAX_SIGNUP_ATTEMPTS})"
        )
    attempt = n + 1
    _append({"event": "signup_start", "site": host, "attempt": attempt, "ts": _now()})
    bind_signup(host, attempt)
    return attempt


def refusal_reason(task_type: str, *, site: str | None = None, attempt: int | None = None) -> str | None:
    """Why createTask must not be called, or None if it is allowed."""
    host = (site if site is not None else current_site()).strip().lower()
    att = current_attempt() if attempt is None else int(attempt)
    allowed = paid_hosts()
    if not host or host not in allowed:
        return "host_not_paid"
    if att < 1:
        return "no_signup_attempt"
    if task_type not in PRICED_TASKS_USD:
        return "unsupported_or_unpriced"
    if solves_for_attempt(host, att) >= MAX_SOLVES_PER_ATTEMPT:
        return "solve_attempt_cap"
    if spent_usd(site=host) >= PER_SITE_CAP_USD:
        return "per_site_cap"
    if spent_usd() >= TOTAL_CAP_USD:
        return "total_cap"
    # A priced solve must not be able to cross the cap by itself.
    price = PRICED_TASKS_USD[task_type]
    if spent_usd() + price > TOTAL_CAP_USD + 1e-9:
        return "total_cap"
    if spent_usd(site=host) + price > PER_SITE_CAP_USD + 1e-9:
        return "per_site_cap"
    return None


def get_balance(key: str | None = None) -> float | None:
    """CapSolver getBalance. Returns USD or None. Does not log the key."""
    import httpx

    token = key if key is not None else capsolver_key()
    if not token:
        return None
    try:
        payload = httpx.post(
            "https://api.capsolver.com/getBalance",
            json={"clientKey": token},
            timeout=20.0,
        ).json()
    except Exception:
        return None
    if payload.get("errorId"):
        return None
    try:
        return round(float(payload.get("balance")), 6)
    except (TypeError, ValueError):
        return None


def record_balance(site: str, *, when: str) -> float | None:
    balance = get_balance()
    _append(
        {
            "event": "balance",
            "site": site,
            "when": when,
            "balance": balance,
            "attempt": current_attempt(),
            "ts": _now(),
        }
    )
    return balance


def record_task(
    *,
    site: str,
    captcha_type: str,
    task_type: str,
    task_id: str | None,
    solved: bool,
    cost: float | None,
    balance_before: float | None,
    balance_after: float | None,
    note: str = "",
) -> None:
    delta = None
    if balance_before is not None and balance_after is not None:
        try:
            delta = round(max(0.0, float(balance_before) - float(balance_after)), 6)
        except (TypeError, ValueError):
            delta = None
    _append(
        {
            "event": "createTask",
            "site": site,
            "captcha_type": captcha_type,
            "task_type": task_type,
            "task_id": task_id,
            "solved": bool(solved),
            "cost": None if cost is None else round(float(cost), 6),
            "list_price": PRICED_TASKS_USD.get(task_type),
            "balance_before": balance_before,
            "balance_after": balance_after,
            "balance_delta": delta,
            "attempt": current_attempt(),
            "note": note[:200],
            "ts": _now(),
        }
    )


def record_skip(*, site: str, captcha_type: str, task_type: str, reason: str) -> None:
    _append(
        {
            "event": "skip",
            "site": site,
            "captcha_type": captcha_type,
            "task_type": task_type,
            "reason": reason,
            "attempt": current_attempt(),
            "ts": _now(),
        }
    )
