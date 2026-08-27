"""Lightweight journey validators for full270 (URL/state heuristics).

Primary grading still uses the LLM judge against journey success_criteria.
These helpers flag obvious failures (login walls) and feed rejudge/audit.
Keep robustness / reserve-session analysis separate from the primary 270.
"""

from __future__ import annotations

from urllib.parse import urlparse


def is_login_url(url: str) -> bool:
    u = (url or "").lower()
    return any(x in u for x in ("/login", "/signin", "/sign-in", "/auth", "accounts.google"))


def validate_journey(run: dict) -> dict:
    """Return {ok: bool, reason: str, validator_id: str} — heuristic only."""
    vid = run.get("validator_id") or "unknown"
    url = run.get("final_url") or ""
    path = urlparse(url).path.lower()
    if is_login_url(url):
        return {"ok": False, "reason": "landed_on_login", "validator_id": vid}

    checks: dict[str, tuple[str, ...]] = {
        "rapid_setup": ("agent", "assistant", "pathway", "create", "build", "dashboard"),
        "knowledge_support": ("knowledge", "document", "file", "memory", "agent", "assistant", "pathway"),
        "logic_routing": ("agent", "assistant", "pathway", "flow", "node", "intent", "transfer"),
        "integration": ("tool", "function", "webhook", "api", "agent", "assistant"),
        "testing_debug": ("test", "simulat", "play", "log", "analytic", "call", "agent"),
    }
    needles = checks.get(vid, ("dashboard", "agent", "assistant"))
    if any(n in path or n in url.lower() for n in needles):
        return {"ok": True, "reason": "url_matches_journey_surface", "validator_id": vid}
    if run.get("success"):
        return {"ok": True, "reason": "judge_success_url_weak", "validator_id": vid}
    return {"ok": False, "reason": "url_does_not_match_expected_surface", "validator_id": vid}
