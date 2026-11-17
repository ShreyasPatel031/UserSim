"""One signup per site per study; every other cell starts signed in from it (Shreyas, Nov 17: "do one signup agent and
then all the other start from that point").

Per (study, site):
  ready      a LIVE saved state exists (mvp/sim_mcp/site_states.py): every cell starts signed in from it, on the app URL
  pending    no state: exactly ONE signup cell is admitted (the study's signup task, first persona); every other cell on
             the site is held (start_session answers "busy, retry"; the cell stays queued)
  signing_up that signup cell is running
  blocked    the signup cell failed twice (second try: next persona's signup cell): the site's remaining cells end as
             "blocked at signup", a finding about the site, not a run failure; no more cells are spent on it
When the signup cell ends with its signed-in state saved, the gate turns ready and the held cells start from it.
Signup-task cells of the other personas start signed in too and are judged on the post-signup part (first-run
onboarding); their rows carry post_signup_only.

Only on seed_vm with seed_saved_accounts on (otherwise every cell runs as before). State is in memory per server
process; after a restart it is rebuilt from the rows (a written state = ready).
"""

from __future__ import annotations

import re
import threading
import time
from typing import Any

MAX_SIGNUP_ATTEMPTS = 2
HOLD_RETRY_S = 60
# The client chooses which cell to start. If the designated signup cell is not started this long after the first held
# cell asked, the asking cell becomes the signup cell (a client that runs one pilot cell per site must not deadlock).
TAKEOVER_S = 120
_SIGNUP_TASK_RE = re.compile(
    r"sign ?up|create (?:a |an |your |a new )?(?:new )?account|register|registration|verify your email", re.I)
_LOCK = threading.RLock()
GATES: dict[tuple[str, str], dict[str, Any]] = {}

POST_SIGNUP_NOTE = (
    "Another simulated user already created this site's account for the study, so the signup step of your task is "
    "done and you start signed in. Do the rest of the task: what a new user does right after signing up (first-run "
    "onboarding, setup, the first thing the product asks you to create).")


class Held(Exception):
    """This cell must wait for its site's signup cell."""


class Blocked(Exception):
    """The site could not be signed up for; the cell was ended as a finding."""


def active() -> bool:
    from mvp.sim_mcp import site_states
    from mvp.sim_mcp.sessions import browser_backend

    return browser_backend() == "seed_vm" and site_states.enabled()


def is_signup_task(prompt: str) -> bool:
    return bool(_SIGNUP_TASK_RE.search(prompt or ""))


def _domain(url: str) -> str:
    from mvp.sim_mcp import site_states

    return site_states.domain_of(url)


def _site_rows(study: Any, domain: str) -> list[dict[str, Any]]:
    return [r for r in study.live_sessions.values() if _domain(str(r.get("site_url") or "")) == domain]


def _persona_order(study: Any) -> list[str]:
    return [str(p.get("id")) for p in getattr(study, "personas", None) or [] if isinstance(p, dict)]


def pick_signup_cell(study: Any, domain: str, tried_personas: list[str]) -> str:
    """The study's signup-task cell for the first persona not tried yet; with no signup task, that persona's first
    cell (it signs up as a prerequisite). '' when every persona was tried."""
    rows = [r for r in _site_rows(study, domain) if r.get("status") == "queued"]
    order = _persona_order(study)
    rank = {pid: i for i, pid in enumerate(order)}
    rows.sort(key=lambda r: (rank.get(str(r.get("persona_id")), 99), str(r.get("agent_id"))))
    for want_signup in (True, False):
        for r in rows:
            if str(r.get("persona_id")) in tried_personas:
                continue
            if is_signup_task(str(r.get("task_prompt") or "")) == want_signup:
                return str(r["agent_id"])
    return ""


def gate(study: Any, site_url: str) -> dict[str, Any]:
    """The gate for this study's site, created on first use."""
    from mvp.sim_mcp import site_states

    domain = _domain(site_url)
    key = (study.id, domain)
    with _LOCK:
        g = GATES.get(key)
        if g is not None:
            return g
        rows = _site_rows(study, domain)
        if any(r.get("saved_account_written") for r in rows) or site_states.load(domain):
            g = {"status": "ready", "domain": domain, "since": time.time()}
        else:
            g = {"status": "pending", "domain": domain, "signup_cell": pick_signup_cell(study, domain, []),
                 "attempts": 0, "tried": []}
            if not g["signup_cell"]:
                g["status"] = "ready"  # nothing left to sign up with: let cells run as before
        GATES[key] = g
        return g


def admit(study: Any, row: dict[str, Any]) -> str:
    """Before a cell opens a browser. Returns 'signed_in' (start from the saved state), 'signup' (this is the site's
    signup cell) or 'normal'; raises Held or Blocked."""
    if not active():
        return "normal"
    with _LOCK:
        g = gate(study, str(row.get("site_url") or ""))
        cid = str(row.get("agent_id"))
        if g["status"] == "ready":
            row["gate"] = "signed_in"
            if is_signup_task(str(row.get("task_prompt") or "")):
                row["post_signup_only"] = True
            return "signed_in"
        if g["status"] == "signing_up":
            _expire_stale(study, g)
        if g["status"] == "blocked":
            raise Blocked(g.get("reason") or "blocked at signup")
        if g["status"] == "pending" and cid != g.get("signup_cell") and str(row.get("persona_id")) not in g["tried"]:
            now = time.time()
            waited = now - g.setdefault("held_since", now)
            if is_signup_task(str(row.get("task_prompt") or "")) or waited > TAKEOVER_S:
                g["signup_cell"] = cid  # the client started this one first; it does the site's signup
        if g["status"] in ("pending", "signing_up") and cid == g.get("signup_cell"):  # also its retry after a failed open
            g["status"] = "signing_up"
            g["started"] = time.time()
            row["gate"] = "signup"
            row["signup_attempt"] = g["attempts"] + 1
            return "signup"
        raise Held(f"waiting for this site's signup run ({g.get('signup_cell')}) to finish; every other run on "
                   f"{g['domain']} starts signed in from it")


def cell_ended(study: Any, row: dict[str, Any], *, signed_in_saved: bool) -> list[str]:
    """After a cell ends. For the site's signup cell: ready (held cells start signed in) when its state was saved,
    else retry with the next persona once, else block the site. Returns the cell ids it ended as blocked."""
    if not active() or row.get("gate") != "signup" or row.get("gate_done"):
        return []
    row["gate_done"] = True
    with _LOCK:
        g = gate(study, str(row.get("site_url") or ""))
        if str(row.get("agent_id")) != g.get("signup_cell"):
            return []
        if signed_in_saved:
            g.update(status="ready", since=time.time(), signed_up_by=row.get("agent_id"))
            return []
        last = (row.get("page_verdict") or {}).get("reason") or row.get("driver_notes") or ""
        return _fail_attempt(study, g, str(row.get("persona_id")), str(last))


def _fail_attempt(study: Any, g: dict[str, Any], persona_id: str, last: str) -> list[str]:
    g["attempts"] += 1
    g["tried"].append(persona_id)
    g.pop("held_since", None)
    nxt = pick_signup_cell(study, g["domain"], g["tried"]) if g["attempts"] < MAX_SIGNUP_ATTEMPTS else ""
    if nxt:
        g.update(status="pending", signup_cell=nxt)
        return []
    reason = (f"{g['domain']} blocked at signup: {g['attempts']} signup run(s) "
              f"(personas {', '.join(g['tried'])}) could not get a signed-in account on our browsers")
    if last:
        reason += f". Last: {last[:200]}"
    g.update(status="blocked", reason=reason)
    ended = []
    for r in _site_rows(study, g["domain"]):
        if r.get("status") == "queued":
            r.update(status="skipped", blocked_at_signup=reason, live_active=False)
            ended.append(str(r.get("agent_id")))
    return ended


def _expire_stale(study: Any, g: dict[str, Any]) -> None:
    """A signup run that never reported back (client died) within its budget counts as a failed attempt."""
    from mvp.sim_mcp.sessions import budget_s

    if time.time() - float(g.get("started") or 0) <= budget_s() + 300:
        return
    row = study.live_sessions.get(g.get("signup_cell") or "") or {}
    if row.get("status") in ("starting", "running"):
        return  # the session is still alive; the reaper will end it
    row["gate_done"] = True
    _fail_attempt(study, g, str(row.get("persona_id")), "the signup run never finished")


def state_died(study: Any, site_url: str) -> None:
    """A cell found the site's saved state dead at open: the site needs a signup cell again."""
    if not active():
        return
    with _LOCK:
        g = gate(study, site_url)
        if g["status"] != "ready":
            return
        cell = pick_signup_cell(study, g["domain"], [])
        if cell:
            g.update(status="pending", signup_cell=cell, attempts=0, tried=[])


def summary(study: Any) -> dict[str, Any]:
    with _LOCK:
        return {d: {k: v for k, v in g.items() if k in ("status", "signup_cell", "attempts", "reason", "signed_up_by")}
                for (sid, d), g in GATES.items() if sid == study.id}
