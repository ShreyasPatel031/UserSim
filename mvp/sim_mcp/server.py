"""The UserSim MCP endpoint (streamable HTTP at /mcp on the UserSim server).

The coding agent is the simulated user. Every tool here is served by the same
process that runs the website, so the prompt, action set, judge, proof checks
and report can't drift between clients.
"""

from __future__ import annotations

import json
import os
from contextlib import AsyncExitStack
from typing import Any

from mcp.server.fastmcp import Context, FastMCP, Image
from mcp.server.transport_security import TransportSecuritySettings

from mvp.sim_mcp import sessions as S
from mvp.sim_mcp.report import (
    build_report,
    build_study_report,
    finalize,
    is_matrix,
    maybe_finish_study,
    report_markdown,
    report_url,
    study_report_markdown,
    watch_url,
)

INSTRUCTIONS = """UserSim lets you act as a simulated user of a real web product, in a real cloud browser that UserSim runs and records.

The simulated user is whatever model is calling these tools. UserSim does not name or require a model. If the human asked for a specific model, use that. Otherwise use the model you are already running as.

Flow:
1. Get a PUBLIC product URL from the human (localhost won't work; a preview/staging deploy is fine). That is the only thing they must provide.
2. Draft a realistic persona (one or two sentences: who they are, what they know, why they are here) and ONE task, using the codebase / recent changes if helpful. Show both to the human and wait for approval.
3. Call usersim_start_session. Open the returned watch_url for the human (e.g. `open <url>` on macOS, `xdg-open <url>` on Linux) so they can watch the browser live.
4. Run the simulated user as a subagent on the model chosen above. Give it the session_id, persona, task and the usersim_simulate_user prompt. It loops usersim_act until done, then calls usersim_finish.
5. Call usersim_get_report and summarise it for the human. The judge verdict and proof checks come from UserSim, not from the simulated user.

Several users, tasks or competitors (a study, like the UserSim website runs):
1. Draft the personas and tasks (each can name the site it `favors`), show them with the competitor URLs, wait for approval.
2. Call usersim_start_study once. It returns study_id, watch_url, report_url and one cell per persona x task x site.
3. For every cell, run one subagent in parallel on that same model: it calls usersim_start_session with study_id + cell_id (nothing else), then plays that cell's persona and task with usersim_act and ends with usersim_finish.
   If a start says UserSim is at its limit, wait for running cells to finish and start the rest then.
4. When the last cell finishes, UserSim writes the full study report (same page as a website study). Call usersim_get_report with the study_id; if it says the report is still being written, wait ~30 s and call again.
   If some cells will never run, call usersim_finish_study to write the report from the cells that did.
"""

SIMULATE_USER_PROMPT = """You are a simulated user testing a web product. You are NOT a coding assistant right now.

Persona: {persona}
Task: {task}
Session: {session_id}

Rules:
- Stay in the persona. Act on what you SEE in the screenshot, the way that person would.
- One action per usersim_act call. Coordinates are pixels in the {width}x{height} screenshot you were given.
- Every usersim_act call needs a short first-person `thought`: what you see, what you expect, what confuses you. These thoughts are the research data — be honest about friction.
- Don't navigate by guessing URLs; use the page like a person would. `navigate` exists for typing an address a person would actually know.
- Stop when the task is done, when you're stuck, or when a real person in this persona would give up. Then call usersim_finish with outcome completed / gave_up / blocked and notes on what was hard or easy.
- Need an account? Call usersim_signup_identity for a fresh email alias + password and sign up with EMAIL only (never Google/GitHub).
  Then usersim_wait_for_verification_code or usersim_wait_for_verification_link (+ usersim_open_verification_link with link_number=1 for the first link). Captcha in the way: solve it like a person (click the checkbox, drag the slider, press_and_hold), or call usersim_solve_captcha.
  If the site asks for a username, workspace, team or subdomain name, use the username / workspace from usersim_signup_identity (they are unique; names you invent are often already taken by other simulated users).
  After signing up, always check for the verification email and open its link, even if the site already let you in: an unverified signup does not count.
  If verifying sends you to a login page, sign in with the SAME email and password from usersim_signup_identity; that is still your new account.
  If the app still says "verify your email" after you opened the link, reload the page (or sign out and sign in again) so it picks up the verified state.
  After clicking a submit button, wait for it to finish (a spinner / disabled button in `fields`) instead of clicking again; double submits cause errors.
  Verification mail can take a few minutes: call the wait tool again (or use the site's "resend") before giving up.
- Finish as soon as the task is done; do not spend remaining steps.
- Limits: {max_steps} steps, {budget_min} minutes. The server enforces them.
"""

mcp = FastMCP(
    name="usersim",
    instructions=INSTRUCTIONS,
    stateless_http=True,
    json_response=True,
    streamable_http_path="/mcp",
    # Served behind the usersim.vercel.app proxy, so the Host header is not localhost.
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


_TOKENS: list[str] = []  # bearer tokens configured at mount(); a valid one makes the caller a token owner


def _headers(ctx: Context | None) -> tuple[dict[str, str], str]:
    try:
        req = ctx.request_context.request  # type: ignore[union-attr]
        client = getattr(req, "client", None)
        return {k.lower(): v for k, v in req.headers.items()}, (getattr(client, "host", "") or "")
    except Exception:  # noqa: BLE001
        return {}, ""


def _owner(ctx: Context | None) -> str:
    """Who owns the sessions and studies this caller creates. A valid bearer token: a fingerprint of that token
    (every holder of one shared token is the same owner). No token (the public, open endpoint): 'anon:' plus a
    fingerprint of the client IP, so callers without a token see only what their own IP created, and the caps in
    limits.json apply to them."""
    import hashlib
    import hmac

    from mvp.sim_mcp import limits as L

    if ctx is None:
        return ""  # internal call, not a client request
    headers, peer = _headers(ctx)
    got = headers.get("authorization") or ""
    tok = got[7:].strip() if got.startswith("Bearer ") else ""
    if tok and any(hmac.compare_digest(tok, t) for t in _TOKENS):
        return hashlib.sha256(tok.encode()).hexdigest()[:16]
    return "anon:" + hashlib.sha256(L.client_ip(headers, peer).encode()).hexdigest()[:16]


def _client_id(ctx: Context | None) -> str:
    from mvp.sim_mcp import limits as L

    headers, peer = _headers(ctx)
    return L.client_ip(headers, peer)


def _spend(owner: str, what: str, *, session: bool = False, dry: bool = False) -> None:
    """Charge the estimated cost of one step (or one session start) to a caller without a token.
    Raises limits.CapExceeded with the message for the client when a daily cap is hit."""
    from mvp.sim_mcp import limits as L

    if not S.is_anon(owner):
        return
    usd = float(L.get("est_usd_per_session" if session else "est_usd_per_step"))
    L.charge(owner, usd, what, dry=dry)


def _cap_fail(exc: Exception) -> str:
    return json.dumps({"error": str(exc), "limit": getattr(exc, "limit", ""),
                       "limits_file": "https://github.com/ShreyasPatel031/UserSim/blob/main/mvp/sim_mcp/limits.json"})


def _obs_content(sim: S.SimSession, obs: dict[str, Any], extra: dict[str, Any] | None = None) -> list[Any]:
    meta = {
        "session_id": sim.id,
        "step": obs["step"],
        "url": obs["url"],
        "title": obs["title"],
        "steps_left": obs["steps_left"],
        "seconds_left": obs["seconds_left"],
    }
    if obs.get("fields"):
        meta["fields"] = obs["fields"]
    unfilled = [f.get("label") or f.get("kind") for f in (obs.get("fields") or [])
                if f.get("filled") is False and f.get("kind") in ("text", "email", "password", "tel", "textarea", "number", "url")
                and not f.get("disabled")]
    if unfilled and any(f.get("filled") for f in (obs.get("fields") or [])):
        # a half-filled form: name the empty boxes (Formester: "Confirm Password" stayed empty, Sign up did nothing)
        meta["unfilled_fields"] = unfilled[:6]
    if obs.get("hidden_fields"):
        meta["hidden_fields"] = obs["hidden_fields"]  # not clickable: invisible, covered, off-screen or a bot trap
    if obs.get("page_errors"):
        meta["page_errors"] = obs["page_errors"]
    if obs.get("note"):
        meta["note"] = obs["note"]  # e.g. a click that only jumped to an in-page #anchor (Oct 11 OpenReplay)
    if obs.get("alias_rejected"):
        current = sim.inbox.address if sim.inbox is not None else ""
        if current and "+" not in current:
            # Loop 6 (FormBold): the old rejection text stays on the page after switching; the hint used to keep
            # saying "call no_plus" and Gemini called usersim_signup_identity 30 times in a row.
            meta["email_hint"] = (f"you already have the no-plus address {current}: clear the email field, type exactly that "
                                  "address, and submit again (the old rejection message may still be showing)")
        else:
            meta["email_hint"] = "this site rejects '+' email aliases: call usersim_signup_identity with no_plus=true and use that address"
    if obs.get("work_email_required"):
        # Overrides the no_plus hint: no Gmail alias can pass a company-domain check, so retrying only burns steps.
        meta["email_hint"] = ("this site only accepts company email domains. UserSim's signup inbox is a Gmail address, so no "
                              "alias will be accepted (no_plus does not help). Stop trying to sign up: finish with outcome "
                              "'blocked' and say the site requires a work email, unless the task can be done without an account")
    if obs.get("captcha"):
        c = obs["captcha"]
        meta["captcha"] = {**c, "hint": "captcha token ready; submit" if c.get("token_ready") else
                           "invisible captcha: it runs when you submit. If you already submitted and the button shows a spinner, "
                           "do not click submit again (that restarts it): call usersim_solve_captcha, which waits for it. If "
                           "nothing happens at all, look for an empty required field (filled:false) or an error message" if c.get("invisible") else
                           "a captcha challenge is open on screen: call usersim_solve_captcha (it may take ~20 s), then look at the page" if c.get("challenge_open") else
                           "captcha not passed yet: submitting now will fail silently. Click its checkbox if visible, or call usersim_solve_captcha, then submit"}
    if obs.get("error"):
        meta["action_error"] = obs["error"]
    if extra:
        meta.update(extra)
    return [json.dumps(meta), Image(data=S.jpeg(obs["png"]), format="jpeg")]


def _fail(exc: Exception) -> str:
    return json.dumps({"error": str(exc)})


@mcp.tool(structured_output=False)
async def usersim_start_study(
    ctx: Context,
    product_url: str,
    personas: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    competitors: list[str] | None = None,
) -> str:
    """Create a study: every persona tries every task on the product and on each competitor.

    product_url: public URL of the product.
    competitors: public URLs of competing products (optional, up to 4).
    personas: [{"name": "Maya Ortiz", "bio": "who they are, what they know, why they're here", "favors": "<site URL or name it is aimed at, optional>"}]
    tasks: [{"prompt": "one goal, in the user's words", "favors": "<site URL or name, optional>"}]
    Ask the human to approve personas, tasks and competitors first.
    Returns study_id, watch_url, report_url and cells. Run each cell with usersim_start_session(study_id=..., cell_id=...).
    """
    comps = list(competitors or [])
    if len(comps) > 4:
        return _fail(S.SessionError("at most 4 competitors"))
    try:
        study = S.create_matrix_study(product_url=product_url, competitors=comps, personas=personas, tasks=tasks,
                                      owner=_owner(ctx))
    except S.SessionError as exc:
        return _fail(exc)
    return json.dumps(
        {
            "study_id": study.id,
            "watch_url": watch_url(study.id),
            "report_url": report_url(study.id),
            "runs": len(study.tasks),
            "cells": S.cells_of(study),
            "rules": {"max_steps": S.max_steps(), "budget_s": S.budget_s(), "idle_timeout_s": S.idle_s(), "max_parallel": S.max_per_client()},
            "next": "Open watch_url for the human, then start one simulated-user subagent per cell (usersim_start_session with study_id + cell_id).",
        },
        indent=1,
    )


@mcp.tool(structured_output=False)
async def usersim_finish_study(ctx: Context, study_id: str) -> str:
    """Write the study report now from the cells that ran; cells never started are marked skipped.

    Only needed if some cells will not be run. Running cells must be finished first.
    """
    from mvp.study import STUDIES

    study = STUDIES.get(study_id)
    if study is None or not S.owns_study(study, _owner(ctx)):
        return _fail(S.SessionError(f"unknown study_id {study_id!r}"))
    try:
        started = await maybe_finish_study(study, force=True)
    except RuntimeError as exc:
        return _fail(exc)
    return json.dumps({"study_id": study_id, "started": started, "status": study.status, "phase": study.phase, "next": "Call usersim_get_report in ~30 s."})


@mcp.tool(structured_output=False)
async def usersim_start_session(
    ctx: Context,
    product_url: str = "",
    task: str = "",
    persona: str = "",
    study_id: str = "",
    cell_id: str = "",
) -> list[Any] | str:
    """Open a real cloud browser on the product and start one simulated user.

    In a study: pass only study_id and cell_id (from usersim_start_study); the site, persona and task come from the cell.
    On its own: pass product_url (public; preview/staging deploys are fine, localhost is not reachable),
    task (one goal the persona is trying to achieve, in their words) and persona (one or two sentences — who
    they are, what they know, why they're here). Ask the human to approve the persona and task first.
    Returns session_id, watch_url (open it for the human), the persona, task, rules, and the first screenshot.
    """
    from mvp.sim_mcp import limits as L

    owner = _owner(ctx)
    try:
        _spend(owner, "a new browser session", session=True, dry=True)
    except L.CapExceeded as exc:
        return _cap_fail(exc)
    try:
        sim = await S.start_session(
            product_url=product_url, task=task, persona=persona, client=_client_id(ctx), study_id=study_id, cell_id=cell_id,
            owner=owner,
        )
        _spend(owner, "a new browser session", session=True)
    except L.CapExceeded as exc:
        return _cap_fail(exc)
    except S.SessionError as exc:
        return _fail(exc)
    except Exception as exc:  # noqa: BLE001
        return _fail(RuntimeError(f"could not open the browser: {exc}"))
    try:
        obs = await S.observe(sim)
    except Exception as exc:  # noqa: BLE001
        # The caller never gets this session_id, so nothing else would free the seat.
        await S.close(sim, reason=f"First screenshot failed: {exc!r}"[:300], status="error")
        return _fail(RuntimeError(f"could not open the browser: {exc}"))
    return _obs_content(
        sim,
        obs,
        {
            "study_id": sim.study.id,
            "cell_id": sim.agent_id,
            "persona": sim.persona,
            "task": sim.task,
            "site": sim.product_url,
            "watch_url": watch_url(sim.study.id),
            "rules": sim.rules(),
            "engine_version": sim.study.engine_version,
            "next": "Open watch_url for the human, then run the simulated user (usersim_simulate_user prompt) with usersim_act.",
        },
    )


@mcp.tool(structured_output=False)
async def usersim_observe(ctx: Context, session_id: str) -> list[Any] | str:
    """Current screenshot, URL and title of the simulated user's browser, without acting."""
    try:
        sim = S.get_session(session_id, _owner(ctx))
        return _obs_content(sim, await S.observe(sim))
    except S.SessionError as exc:
        return _fail(exc)


@mcp.tool(structured_output=False)
async def usersim_act(ctx: Context, session_id: str, action: dict[str, Any] | str, thought: str,
                      x: int | str | None = None, y: int | str | None = None, text: str | None = None,
                      keys: str | None = None, dy: int | str | None = None, url: str | None = None) -> list[Any] | str:
    """Do ONE thing on the page, the way the persona would, and get the new screenshot.

    action (pixel coordinates in the screenshot):
      {"type":"click","x":..,"y":..} · {"type":"click","text":"Continue"} (a visible button/link by its text, scrolled into view) · {"type":"double_click","x":..,"y":..} · {"type":"triple_click","x":..,"y":..} (select a field's text) · {"type":"right_click","x":..,"y":..}
      {"type":"hover","x":..,"y":..} · {"type":"type","text":"...","x":..,"y":..,"submit":false} (clicks the field at x,y, clears it, types; omit x,y to type into the focused field)
    Each observation lists visible `fields` (kind, label, exact x,y, filled/checked) and `page_errors` (inline form errors, JS errors): use those coordinates for form fields and read the errors before retrying.
      {"type":"key","keys":"Enter"|"Tab"|"Escape"|"Control+A"} · {"type":"scroll","dy":600,"x":..,"y":..} (dy>0 = down)
      {"type":"back"} · {"type":"reload"} · {"type":"clear_cookies"} (log out: clears cookies + site storage, reloads) · {"type":"wait","ms":1000} · {"type":"navigate","url":"..."} (same site only)
      {"type":"select","x":..,"y":..,"option":"visible option text","field":"the dropdown's label"} (dropdowns, native or custom; native popups never appear in screenshots, so pick from the `options` listed for that field in `fields`; `field`, e.g. "Organization size", picks the dropdown by its label when several sit close together)
      {"type":"press_and_hold","x":..,"y":..,"ms":4000} (press-and-hold human checks)
      {"type":"drag","x":..,"y":..,"to_x":..,"to_y":..} (slider / puzzle captchas)
    Google / GitHub sign-in is blocked: always use the email signup.
    thought: first-person, what you see / expect / find confusing. Recorded as research data.
    """
    if isinstance(action, str):
        # Haiku sometimes sends the action as a JSON string, or flattened: {"action": "click", "x": "888", "y": "31"}
        # (16 of 3,992 calls in studies f80f043a-2e8d7db5). Rebuild the object from the flat fields.
        flat = {"x": x, "y": y, "text": text, "keys": keys, "dy": dy, "url": url}
        if action.strip() in S.ACTION_TYPES:
            action = {"type": action.strip(), **{k: v for k, v in flat.items() if v is not None}}
            for k in ("x", "y", "dy"):
                if isinstance(action.get(k), str) and action[k].strip().lstrip("-").isdigit():
                    action[k] = int(action[k])
        else:
            try:
                action = json.loads(action)
            except ValueError:
                action = None
        if not isinstance(action, dict):
            return _fail(S.SessionError('action must be ONE object, e.g. {"type":"click","x":640,"y":400} or '
                                        '{"type":"type","text":"hello","x":640,"y":300}; put x, y, text inside it'))
    from mvp.sim_mcp import limits as L

    try:
        owner = _owner(ctx)
        sim = S.get_session(session_id, owner)
        _spend(owner, "one step")
        extra = None
        if str((action or {}).get("type")) in {"click", "key"}:
            await _refresh_v3_token(sim)
            extra = await _maybe_paid_presolve(sim)
        obs = await S.act(sim, action, thought)
        return _obs_content(sim, obs, {"captcha_presolve": extra} if extra else None)
    except L.CapExceeded as exc:
        return _cap_fail(exc)
    except S.SessionError as exc:
        return _fail(exc)


@mcp.tool(structured_output=False)
async def usersim_finish(ctx: Context, session_id: str, outcome: str, notes: str) -> str:
    """End the simulated user's session. outcome: completed | gave_up | blocked.

    notes: what was easy, what was hard, where the persona got confused, why they stopped.
    UserSim then closes the browser, runs its own judge and proof checks. Call usersim_get_report next.
    """
    from mvp.sim_mcp.report import signup_verified

    try:
        sim = S.get_session(session_id, _owner(ctx))
    except S.SessionError as exc:
        return _fail(exc)
    if (str(outcome).strip().lower() == "completed" and sim.inbox is not None and not sim.verify_nudged
            and not signup_verified(sim.row) and sim.seconds_left() > 60):
        # Study f80f043a: Youform let agents into the builder before verifying, they finished without opening the
        # mail, and the signup bar (email-verified) failed real accounts. Ask once; a second call finishes anyway.
        sim.verify_nudged = True
        return json.dumps({
            "session_id": sim.id,
            "finished": False,
            "next": ("Not finished yet: you signed up but never opened the verification email, and an unverified signup "
                     "does not count. Call usersim_wait_for_verification_link (or usersim_wait_for_verification_code), "
                     "open the link with usersim_open_verification_link, check you are still signed in, then call "
                     "usersim_finish again. If no mail arrives, call usersim_finish again with the same arguments."),
        })
    async with sim.lock:
        study = await finalize(sim, outcome=outcome, notes=notes)
    if sim.matrix:
        row = sim.row
        return json.dumps(
            {
                "study_id": sim.study.id,
                "cell_id": sim.agent_id,
                "goal_reached": bool((row.get("page_verdict") or {}).get("goal_reached")),
                "proof_pass": (row.get("mcp_proof") or {}).get("pass"),
                "study_phase": sim.study.phase,
                "next": "Done with this cell. The study report is written when the last cell finishes.",
            }
        )
    rep = build_report(study)
    return json.dumps(
        {"study_id": rep["study_id"], "headline": rep["headline"], "proof_pass": rep["proof"].get("pass"), "next": "Call usersim_get_report."}
    )


@mcp.tool(structured_output=False)
async def usersim_get_report(ctx: Context, study_id: str, format: str = "markdown") -> str:
    """The study report: independent judge verdict, proof checks, friction, every step with screenshot links.

    format: "markdown" (default) or "json".
    """
    from mvp.study import STUDIES, load_local_study, load_study_from_gcs, study_to_dict

    live = STUDIES.get(study_id)
    data = study_to_dict(live) if live is not None else (load_local_study(study_id) or load_study_from_gcs(study_id))
    if not data or not S.owns_study(data, _owner(ctx)):
        return _fail(S.SessionError(f"unknown study_id {study_id!r}"))
    if is_matrix(data):
        srep = build_study_report(data)
        if data.get("status") != "complete":
            srep["note"] = f"Study not finished yet ({data.get('phase')}). Call again in ~30 s."
        return json.dumps(srep, indent=1) if format == "json" else study_report_markdown(srep)
    rep = build_report(data)
    if data.get("status") != "complete":
        rep["note"] = "Study is not finished yet; call usersim_finish first."
    return json.dumps(rep, indent=1) if format == "json" else report_markdown(rep)


# ---------------------------------------------------------------- signup tools (shared core: mvp.signup_tools)


def _host(sim: S.SimSession) -> str:
    from urllib.parse import urlsplit

    return (urlsplit(sim.product_url).hostname or "").removeprefix("www.")


@mcp.tool(structured_output=False)
async def usersim_signup_identity(ctx: Context, session_id: str, no_plus: bool = False) -> str:
    """Fresh, never-used email alias (a real inbox UserSim reads) plus password, name and username for signing up.

    Same alias for the whole session. Sign up with this email only; never Google or GitHub sign-in.
    no_plus=true: the site rejected a "+" address; returns a fresh dot-variant address of the same inbox instead
    (replaces the earlier alias for this session).
    """
    import asyncio
    import re
    import time

    from mvp.signup_tools import new_signup

    from mvp.sim_mcp import limits as L

    try:
        owner = _owner(ctx)
        sim = S.get_session(session_id, owner)
        shared_ok = not S.is_anon(owner) or bool(L.get("anon_allow_shared_aliases"))
        if no_plus and not shared_ok:
            # A dot-variant (or plain) address can be issued again to another session, which could then read this
            # session's mail. Callers without a token only get unique +tag aliases.
            raise S.SessionError("cap anon_allow_shared_aliases: no_plus addresses are not available without a token. "
                                 "This site rejects '+' aliases, so finish with outcome 'blocked' and say so")
        if no_plus and sim.inbox is not None and "+" in sim.inbox.address:
            sim.inbox = None
        issued_now = sim.inbox is None
        if sim.inbox is None:
            tag = re.sub(r"[^a-z0-9]", "", _host(sim).split(".")[0])[:10] or "site"
            inbox, identity = await asyncio.to_thread(new_signup, _host(sim), tag, None, dotted=bool(no_plus))
            if not shared_ok and "+" not in inbox.address:
                # MVP_SIGNUP_PLAIN_HOSTS gives the bare inbox address, which every caller would share.
                raise S.SessionError("cap anon_allow_shared_aliases: this site only gets the shared plain signup address, "
                                     "which is not available without a token. Finish with outcome 'blocked'")
            sim.inbox, sim.identity = inbox, identity
            sim.mail_since = time.time() - 30
            sim.row["signup_email"] = sim.inbox.address
        ident = {k: v for k, v in sim.identity.items() if k != "code"}
        repeats = int(sim.row.get("identity_repeat_calls") or 0)
        if not issued_now:
            repeats += 1
            sim.row["identity_repeat_calls"] = repeats
            if repeats >= 3:
                return json.dumps({**ident, "error": f"identity already issued ({sim.inbox.address}); calling again changes nothing. "
                                            "Act on the page: type that email into the form and submit."})
            return json.dumps({**ident, "next": "Same identity as before (already issued). Type it into the form now; "
                                                "do not call usersim_signup_identity again."})
        sim.row["identity_repeat_calls"] = 0
        return json.dumps({**ident, "next": "Type these into the signup form (use username / workspace for any username, team or subdomain field), submit, then wait for the verification mail."})
    except Exception as exc:  # noqa: BLE001
        return _fail(exc)


async def _wait(ctx: Context, session_id: str, timeout_s: int, want: str) -> str:
    import asyncio

    from mvp.signup_tools import wait_mail

    try:
        sim = S.get_session(session_id, _owner(ctx))
        if sim.inbox is None:
            raise S.SessionError("call usersim_signup_identity and submit the signup form first")
        # Many MCP clients give a tool call 60 s (Claude Code's default MCP_TOOL_TIMEOUT); Haiku asked for 180 s and the
        # client gave up first (study e7c5d942). Each call waits at most MVP_MCP_WAIT_MAX_S; the agent calls again.
        t = max(10, min(int(timeout_s or 45), S._env_int("MVP_MCP_WAIT_MAX_S", 50)))
        msg = await asyncio.to_thread(wait_mail, sim.inbox, _host(sim), since=sim.mail_since, timeout_s=t, seen=sim.mail_seen, want=want)
        sim.last_used = __import__("time").time()
        if not msg:
            return json.dumps({"found": False, "note": f"no verification mail with a {want} yet (waited {t}s). Mail often takes "
                               "1-3 minutes: call this tool again. If several calls find nothing, check the form was "
                               "really submitted, or use the site's resend link"})
        # keep links from earlier mails openable too (the verify mail and a welcome mail can arrive together)
        sim.mail_links = list(msg.get("links") or []) + [u for u in sim.mail_links if u not in (msg.get("links") or [])]
        for u, t in zip(msg.get("links") or [], msg.get("link_texts") or []):
            if t:
                sim.mail_link_texts[u] = t
        if msg.get("code"):
            # Received is not used: signup_code_used is set only once the code is typed (sessions.note_code_typed).
            sim.row["signup_code_received"] = True
            if msg["code"] not in sim.signup_codes:
                sim.signup_codes.append(msg["code"])
        sim.row.setdefault("signup_mail", []).append({"subject": msg.get("subject"), "sender": msg.get("sender")})
        return json.dumps({"found": True, "subject": msg.get("subject"), "sender": msg.get("sender"),
                           "code": msg.get("code"), "links": sim.mail_links[:5], "link_texts": (msg.get("link_texts") or [])[:5],
                           "next": "to open a link call usersim_open_verification_link with link_number=1 (first link) "
                                   "rather than copying its URL"})
    except Exception as exc:  # noqa: BLE001
        return _fail(exc)


@mcp.tool(structured_output=False)
async def usersim_wait_for_verification_code(ctx: Context, session_id: str, timeout_s: int = 45) -> str:
    """Wait for the signup email for this session's alias and return the verification code in it.

    Each call waits at most ~50 s (MCP clients often time out at 60 s). If found is false, call it again.
    """
    return await _wait(ctx, session_id, timeout_s, "code")


@mcp.tool(structured_output=False)
async def usersim_wait_for_verification_link(ctx: Context, session_id: str, timeout_s: int = 45) -> str:
    """Wait for the signup email for this session's alias and return its verification links (best first).

    Each call waits at most ~50 s (MCP clients often time out at 60 s). If found is false, call it again.
    """
    return await _wait(ctx, session_id, timeout_s, "link")


def resolve_mail_link(links: list[str], url: str, number: int) -> str:
    """The mail link the agent means: by 1-based number, exactly, or a near-exact copy of exactly one link.

    Haiku garbles long tokens when copying them (repeated base64 chunks; Baserow, study e7c5d942), so a URL that
    differs only inside the token still opens the one link it clearly came from.
    """
    import difflib

    if number:
        if 1 <= int(number) <= len(links):
            return links[int(number) - 1]
        raise S.SessionError(f"link_number must be 1..{len(links)} (call usersim_wait_for_verification_link first)")
    if url in links:
        return url
    if not links:
        raise S.SessionError("no verification mail yet: call usersim_wait_for_verification_link first")
    scored = sorted(((difflib.SequenceMatcher(None, url, u).ratio(), u) for u in links), reverse=True)
    best, runner = scored[0], (scored[1] if len(scored) > 1 else (0.0, ""))
    same_prefix = url[:40] == best[1][:40]
    if same_prefix and best[0] >= 0.85 and best[0] - runner[0] >= 0.1:
        return best[1]
    raise S.SessionError("only links returned by usersim_wait_for_verification_link can be opened. "
                         "Pass link_number=1 (the first link) instead of copying the URL")


@mcp.tool(structured_output=False)
async def usersim_open_verification_link(ctx: Context, session_id: str, url: str = "", thought: str = "I click the link in the email.",
                                        link_number: int = 0) -> list[Any] | str:
    """Open a link from the verification email in the browser (like clicking it in the email).

    Prefer link_number: 1 = the first link usersim_wait_for_verification_link returned (the best one), 2 = the second.
    Long tokens are easy to mistype; with link_number you never copy the URL.
    """
    from mvp.sim_mcp import limits as L

    try:
        owner = _owner(ctx)
        sim = S.get_session(session_id, owner)
        url = resolve_mail_link(sim.mail_links, url, link_number)
        try:
            _spend(owner, "one step")
        except L.CapExceeded as exc:
            return _cap_fail(exc)
        opened = sim.row.setdefault("opened_links", [])
        if url in opened:
            raise S.SessionError("this link was already opened; continue on the page (it is the current page)")
        opened.append(url)
        async with sim.lock:
            S._check_open(sim)
            err = ""
            chain = [url]
            try:
                resp = await sim.page.goto(url, wait_until="domcontentloaded", timeout=30000)
                # the redirect chain the browser followed (click-tracking link -> real verify URL -> app)
                req = resp.request if resp is not None else None
                hops = []
                while req is not None:
                    hops.append(req.url)
                    req = req.redirected_from
                chain = [url] + [h for h in reversed(hops) if h != url]
            except Exception as exc:  # noqa: BLE001
                err = str(exc).splitlines()[0][:200]
            if sim.page.url and sim.page.url not in chain:
                chain.append(sim.page.url)
            sim.row.setdefault("opened_link_chains", {})[url] = [c[:300] for c in chain[:8]]
            if sim.mail_link_texts.get(url):
                sim.row.setdefault("opened_link_texts", {})[url] = sim.mail_link_texts[url][:80]
            await S._settle(sim.page)
            obs = await S.record_step(sim, kind="navigate", action_text="open verification link from email",
                                      args={"url": url[:200]}, thought=thought, error=err)
        return _obs_content(sim, obs)
    except Exception as exc:  # noqa: BLE001
        return _fail(exc)


def _sms_allowed(owner: str) -> None:
    from mvp.sim_mcp import limits as L

    if S.is_anon(owner) and not L.get("anon_allow_sms"):
        raise S.SessionError("cap anon_allow_sms: SMS verification is not available without a token. Finish with outcome "
                             "'blocked' and say the site requires a phone number")


@mcp.tool(structured_output=False)
async def usersim_signup_phone(ctx: Context, session_id: str) -> str:
    """Phone number for an SMS step (only if the site insists on one). Then call usersim_wait_for_sms_code."""
    import asyncio
    import time

    try:
        owner = _owner(ctx)
        sim = S.get_session(session_id, owner)
        _sms_allowed(owner)
        from mvp.sms_provider import lease_number

        sim.sms_number = await asyncio.to_thread(lease_number, _host(sim))
        sim.row["sms_since"] = time.time()
        return json.dumps({"phone": sim.sms_number.phone})
    except Exception as exc:  # noqa: BLE001
        return _fail(RuntimeError(f"no SMS number available: {exc}"))


@mcp.tool(structured_output=False)
async def usersim_wait_for_sms_code(ctx: Context, session_id: str, timeout_s: int = 90) -> str:
    """Wait for the SMS verification code sent to the number from usersim_signup_phone."""
    import asyncio

    try:
        owner = _owner(ctx)
        sim = S.get_session(session_id, owner)
        _sms_allowed(owner)
        if sim.sms_number is None:
            raise S.SessionError("call usersim_signup_phone first")
        from mvp.sms_provider import wait_for_sms

        code = await asyncio.to_thread(wait_for_sms, sim.sms_number, timeout_s=max(15, min(int(timeout_s), 180)),
                                       newer_than=sim.row.get("sms_since"))
        return json.dumps({"found": bool(code), "code": code})
    except Exception as exc:  # noqa: BLE001
        return _fail(exc)


@mcp.tool(structured_output=False)
async def usersim_solve_captcha(ctx: Context, session_id: str) -> list[Any] | str:
    """Try to get past a captcha on the current page (the same solver path the website driver uses).

    Prefer solving it yourself first like a person (checkbox click, drag, press_and_hold). This tries the free
    audio route for reCAPTCHA; a paid solver only runs when the server enables it (MVP_MCP_PAID_CAPTCHA=1).
    """
    import os

    from mvp.sim_mcp import limits as L

    try:
        owner = _owner(ctx)
        sim = S.get_session(session_id, owner)
        try:
            _spend(owner, "one step")
        except L.CapExceeded as exc:
            return _cap_fail(exc)
        from mvp import captcha as cap

        async with sim.lock:
            S._check_open(sim)
            calls = sim.row.setdefault("captcha_calls", {})
            calls[sim.page.url] = int(calls.get(sim.page.url) or 0) + 1
            if calls[sim.page.url] > 3:
                obs = await S.record_step(sim, kind="captcha", action_text="captcha attempt (refused: repeated)",
                                          args={}, thought="I try to get past the captcha again.", error="")
                return _obs_content(sim, obs, {"captcha": {"note": "already tried 3 times on this page; calling again will not "
                                               "help. Wait, go back and retry the flow once, or finish with outcome 'blocked'."}})
            title = ""
            try:
                title = (await sim.page.title()) or ""
            except Exception:  # noqa: BLE001
                pass
            if "just a moment" in title.lower() or "attention required" in title.lower():
                # Cloudflare interstitial: it verifies on its own; clicking mid-"Verifying..." restarts it. Wait first.
                import asyncio as _a0

                for _ in range(20):
                    await _a0.sleep(1.5)
                    try:
                        if "just a moment" not in ((await sim.page.title()) or "").lower():
                            break
                    except Exception:  # noqa: BLE001
                        break
            pre = await S.captcha_state(sim.page) or {}
            if pre.get("kind") == "recaptcha" and pre.get("invisible") and not pre.get("token_ready"):
                # Loop 14 Featurebase: after a submit the invisible reCAPTCHA can take >6 s to show its grid. Wait for it
                # here (or for a token / navigation) instead of reporting "nothing to solve" while it is still coming.
                import asyncio as _a1

                url0 = sim.page.url
                for _ in range(24):
                    await _a1.sleep(0.5)
                    st0 = await S.captcha_state(sim.page) or {}
                    if st0.get("challenge_open") or st0.get("token_ready") or sim.page.url != url0 or not st0:
                        break
            info = await cap.detect_sitekey(sim.page)
            result: dict[str, Any] = {"detected": info or None}
            state = await S.captcha_state(sim.page) or {}
            if state.get("kind") == "turnstile" and not state.get("token_ready"):
                # Turnstile: click the widget's checkbox like a person if it is visible, then wait for the token
                # (Browserbase's built-in solver also works on it while we wait).
                import asyncio as _a

                try:
                    fr = sim.page.locator('iframe[src*="challenges.cloudflare.com"]')
                    for i in range(await fr.count()):
                        box = await fr.nth(i).bounding_box()
                        if box and box["width"] > 40 and box["height"] > 20:
                            await sim.page.mouse.move(box["x"] + 30, box["y"] + box["height"] / 2, steps=12)
                            await sim.page.mouse.click(box["x"] + 30, box["y"] + box["height"] / 2)
                            result["turnstile_clicked"] = True
                            break
                except Exception as exc:  # noqa: BLE001
                    result["turnstile_click_error"] = repr(exc)[:120]
                for _ in range(20):
                    st = await S.captcha_state(sim.page) or {}
                    if st.get("token_ready"):
                        break
                    await _a.sleep(1.5)
                result["turnstile_token_ready"] = bool((await S.captcha_state(sim.page) or {}).get("token_ready"))
            if info and "recaptcha" in str(info.get("type") or info).lower() and state.get("kind") != "turnstile":
                try:
                    from mvp.signup_captcha_audio import solve_recaptcha_audio

                    result["audio"] = await solve_recaptcha_audio(sim.page)
                except Exception as exc:  # noqa: BLE001
                    result["audio_error"] = repr(exc)[:200]
                if not (result.get("audio") or {}).get("ok"):
                    # Loop 14 Featurebase: the audio route found no audio, but Browserbase's built-in solver cleared the
                    # image challenge a few seconds later and the site moved on. Wait for that before reporting.
                    import asyncio as _a2

                    for _ in range(16):
                        if not await S.recaptcha_challenge_open(sim.page):
                            break
                        await _a2.sleep(1.5)
                    result["challenge_cleared"] = not await S.recaptcha_challenge_open(sim.page)
            state = await S.captcha_state(sim.page) or {}
            if result.get("challenge_cleared") and not state.get("challenge_open"):
                result["note"] = ("the challenge is gone; look at the page: it may already have moved on (e.g. a "
                                  "code screen). Submit again only if the form is still showing")
            elif state.get("invisible") and not state.get("token_ready"):
                result["note"] = ("invisible reCAPTCHA with no challenge on screen: there is nothing to solve. Do not call this "
                                  "again; fill any field with filled:false and submit")
            if os.environ.get("MVP_MCP_PAID_CAPTCHA") == "1" and state and not state.get("token_ready"):
                result["paid"] = await _paid_token(sim, state.get("kind") or "", info or {})
            await S._settle(sim.page)
            obs = await S.record_step(sim, kind="captcha", action_text="captcha attempt",
                                      args={}, thought="I try to get past the captcha.", error="")
        return _obs_content(sim, obs, {"captcha": json.loads(json.dumps(result, default=str))})
    except Exception as exc:  # noqa: BLE001
        return _fail(exc)


_PAID_JS = """([kind, token]) => {
  const set = (sel) => document.querySelectorAll(sel).forEach(t => {
    const d = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(t), 'value');
    d && d.set ? d.set.call(t, token) : (t.value = token);
    t.dispatchEvent(new Event('input', {bubbles: true})); t.dispatchEvent(new Event('change', {bubbles: true}));
  });
  if (kind === 'turnstile') {
    set('input[name="captcha"], [name="cf-turnstile-response"]');
    if (window.turnstile) {
      window.turnstile.getResponse = () => token;
      window.turnstile.execute = (el, o) => { o && o.callback && o.callback(token); };
      const r = window.turnstile.render;
      window.turnstile.render = (el, o) => { setTimeout(() => o && o.callback && o.callback(token), 50); return 'usersim'; };
    }
  } else {
    set('textarea[name="g-recaptcha-response"], input[name="g-recaptcha-response"]');
    // v2 (checkbox or invisible, explicit render) hands the token to the widget's callback, not to execute()'s
    // return value: find the callbacks the site registered in ___grecaptcha_cfg and call them with the token.
    const cbs = [];
    const walk = (o, d) => {
      if (!o || typeof o !== 'object' || d > 5) return;
      for (const k of Object.keys(o)) {
        let v; try { v = o[k]; } catch (e) { continue; }
        if (k === 'callback' && typeof v === 'function') cbs.push(v);
        else if (k === 'callback' && typeof v === 'string' && typeof window[v] === 'function') cbs.push(window[v]);
        else if (v && typeof v === 'object' && !(v instanceof Node) && v !== window) walk(v, d + 1);
      }
    };
    try { walk((window.___grecaptcha_cfg || {}).clients, 0); } catch (e) {}
    const fire = () => { cbs.forEach(cb => { try { cb(token); } catch (e) {} }); };
    if (window.grecaptcha) {
      const g = window.grecaptcha;
      g.execute = () => { setTimeout(fire, 0); return Promise.resolve(token); };
      if (g.enterprise) g.enterprise.execute = () => { setTimeout(fire, 0); return Promise.resolve(token); };
      g.getResponse = () => token;
      if (g.enterprise) g.enterprise.getResponse = () => token;
    }
    fire();
    return {callbacks: cbs.length};
  }
  return true;
}"""

# Which reCAPTCHA this is: v3 loads api.js?render=<sitekey> and never opens a bframe challenge; v2 (checkbox or
# invisible) renders explicitly / via .g-recaptcha and may open a bframe. Enterprise loads enterprise.js.
_RECAPTCHA_KIND_JS = """() => {
  // api.js is often injected by script and only shows up in resource timing
  const srcs = [...document.scripts].map(s => s.src || '').concat(performance.getEntriesByType('resource').map(e => e.name))
    .filter(u => /recaptcha\\/(api|enterprise)\\.js/.test(u));
  let v3 = false;
  for (const u of srcs) { try { const k = new URL(u).searchParams.get('render'); if (k && k !== 'explicit' && k !== 'onload') v3 = true; } catch (e) {} }
  const fr = [...document.querySelectorAll('iframe')].map(i => i.src || '').filter(u => u.includes('/recaptcha/'));
  const bframe = fr.some(u => u.includes('/bframe'));
  const invisible = fr.some(u => /[?&]size=invisible/.test(u)) || !!document.querySelector('[data-size="invisible"]');
  const enterprise = srcs.some(u => /enterprise\\.js/.test(u)) || fr.some(u => u.includes('/enterprise/'));
  return {v3: v3 && !bframe, invisible, enterprise, bframe};
}"""


def _paid_captcha_type(kind: str, detected: str, probe: dict | None, override: str = "") -> tuple[str, bool]:
    """(CapSolver captcha_type, isInvisible) for the paid path. A plain 'recaptcha' from detect_sitekey means
    'not known to be v3', so it is solved as v2 unless the page loads api.js?render=<sitekey> (v3)."""
    if kind == "turnstile":
        return "turnstile", False
    probe = probe or {}
    invisible = bool(probe.get("invisible"))
    d = (detected or "").lower()
    if override:
        return override, invisible and "v2" in override
    if "v3" in d:
        return d, False
    if "v2" in d:
        return d, invisible
    v3 = bool(probe.get("v3"))
    if probe.get("enterprise") or "enterprise" in d:
        return ("recaptcha_v3_enterprise" if v3 else "recaptcha_v2_enterprise"), (invisible and not v3)
    return ("recaptcha_v3" if v3 else "recaptcha_v2"), (invisible and not v3)

_SITEKEY_JS = """(kind) => {
  const html = document.documentElement.outerHTML;
  if (kind === 'turnstile') {
    const el = document.querySelector('[data-sitekey]'); if (el) return el.getAttribute('data-sitekey');
    const m = html.match(/0x4[A-Za-z0-9_-]{18,}/); if (m) return m[0];
    // explicit render from JS: the widget lives in a closed shadow root, but its challenge-platform request
    // URL (.../turnstile/.../0x4.../...) is in the page's resource timing even when that request failed
    const urls = performance.getEntriesByType('resource').map(e => e.name).filter(u => u.includes('challenges.cloudflare.com'));
    for (const u of urls.reverse()) { const k = u.match(/[/](0x4[A-Za-z0-9_-]{18,})(?:[/]|$)/); if (k) return k[1]; }
    return '';
  }
  const s = [...document.scripts].map(x => x.src).find(u => /recaptcha.*render=/.test(u));
  if (s) { const k = new URL(s).searchParams.get('render'); if (k && k !== 'explicit') return k; }
  const f = [...document.querySelectorAll('iframe')].map(i => i.src).find(u => u.includes('/recaptcha/'));
  if (f) { const k = new URL(f).searchParams.get('k'); if (k) return k; }
  const m = html.match(/6L[A-Za-z0-9_-]{38}/); return m ? m[0] : '';
}"""


# reCAPTCHA v3 sites often run grecaptcha.execute() once on page load and keep the token in a hidden field. v3 tokens
# expire after 2 minutes, so a form that takes longer to fill posts a dead token (Loop 16 FeedBear: "reCAPTCHA
# verification failed"). The field is non-empty, so captcha_state said token_ready and nothing ever refreshed it.
_V3_ACTION_JS = """() => {
  if (window.__usersimV3Action) return window.__usersimV3Action;  // recorded by sessions.V3_ACTION_HOOK
  for (const s of document.scripts) {
    if (s.src) continue;
    const m = s.textContent.match(/execute\\(\\s*['"][^'"]+['"]\\s*,\\s*\\{\\s*action\\s*:\\s*['"]([A-Za-z0-9_/]+)['"]/);
    if (m) return m[1];
  }
  return '';
}"""

_V3_REFRESH_JS = """async (action) => {
  const g = window.grecaptcha;
  const src = [...document.scripts].map(s => s.src || '').concat(performance.getEntriesByType('resource').map(e => e.name))
    .find(u => /recaptcha\\/api\\.js\\?[^#]*render=/.test(u));
  if (!g || !g.execute || !src) return {refreshed: false};
  const key = new URL(src).searchParams.get('render');
  if (!key || key === 'explicit' || key === 'onload') return {refreshed: false};
  const fields = [...document.querySelectorAll('input[name="g-recaptcha-response"], textarea[name="g-recaptcha-response"], input[name^="g-recaptcha-response-data"]')];
  if (!fields.length) return {refreshed: false};
  try {
    const token = await new Promise((res, rej) => { g.ready(() => g.execute(key, {action: action || 'submit'}).then(res, rej)); setTimeout(() => rej('timeout'), 8000); });
    fields.forEach(f => { f.value = token; });
    return {refreshed: true, len: String(token).length};
  } catch (e) { return {refreshed: false, error: String(e).slice(0, 80)}; }
}"""

_CAPTCHA_FAILED_RE = __import__("re").compile(
    r"(?i)re-?captcha[^.\n]{0,40}(fail|invalid|expired|could not|couldn.t|try again)|captcha (verification )?(failed|invalid|expired)")


async def _refresh_v3_token(sim: S.SimSession) -> None:
    """Free: before a click on a reCAPTCHA v3 page that keeps a token field, mint a fresh token with the page's own
    grecaptcha and action (no solver, no cost)."""
    try:
        probe = await sim.page.evaluate(_RECAPTCHA_KIND_JS) or {}
        if not probe.get("v3"):
            return
        action = await sim.page.evaluate(_V3_ACTION_JS) or ""
        out = await sim.page.evaluate(_V3_REFRESH_JS, action)
        if isinstance(out, dict) and out.get("refreshed"):
            sim.row["v3_refreshes"] = int(sim.row.get("v3_refreshes") or 0) + 1
            sim.row["v3_action"] = action
    except Exception:  # noqa: BLE001
        return


async def _captcha_rejected(page) -> bool:
    try:
        text = await page.evaluate("() => (document.body && document.body.innerText || '').slice(0, 20000)")
    except Exception:  # noqa: BLE001
        return False
    return bool(_CAPTCHA_FAILED_RE.search(text or ""))


async def _maybe_paid_presolve(sim: S.SimSession) -> dict | None:
    """Before a click on an approved paid host, if an invisible captcha has no token yet, get one first."""
    from urllib.parse import urlsplit

    from mvp import captcha_spend as cs

    if os.environ.get("MVP_MCP_PAID_CAPTCHA") != "1" or not _paid_allowed(sim):
        return None
    host = (urlsplit(sim.product_url).hostname or "").removeprefix("www.")
    if host not in cs.paid_hosts() or int(sim.row.get("capsolver_tries") or 0) >= 2:
        return None
    if not sim.row.get("signup_email"):
        return None  # only once the signup form is being filled
    state = await S.captcha_state(sim.page) or {}
    if not state:
        return None
    # a token in the field is not proof it works: the site may have just said the captcha failed (expired v3 token,
    # low score). Then pay for one even though the field is filled.
    if state.get("token_ready") and not await _captcha_rejected(sim.page):
        return None
    # Loop 16 FeedBear: the rejection banner stays on ?captcha_failed=true, so the click on the agree checkbox and the
    # click on Register each bought a token on the same page. One paid token per page load: the marker dies on navigation.
    try:
        if await sim.page.evaluate("() => !!window.__usersimPaidAt"):
            return None
    except Exception:  # noqa: BLE001
        pass
    kind = state.get("kind") or ""
    if "v3" in kind and int(sim.row.get("capsolver_v3_paid") or 0) >= 1 and await _captcha_rejected(sim.page):
        # a paid v3 token reached the server (it is posted, see test_paid_v3_token_is_posted) and was still
        # refused: the site wants a higher score than a standard token gives. Paying again buys the same refusal.
        sim.row["v3_paid_rejected"] = True
        return {"ok": False, "detail": "site refused a paid reCAPTCHA v3 token (score); not paying again"}
    sim.row["capsolver_tries"] = int(sim.row.get("capsolver_tries") or 0) + 1
    if "v3" in kind:
        sim.row["capsolver_v3_paid"] = int(sim.row.get("capsolver_v3_paid") or 0) + 1
    from mvp import captcha as cap

    try:
        out = await _paid_token(sim, kind, await cap.detect_sitekey(sim.page) or {})
        if isinstance(out, dict) and out.get("ok"):
            try:
                await sim.page.evaluate("() => { window.__usersimPaidAt = Date.now(); }")
            except Exception:  # noqa: BLE001
                pass
        return out
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "detail": repr(exc)[:200]}


_UUID_RE = __import__("re").compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", __import__("re").I)
_HCAPTCHA_JS = """() => !!(window.hcaptcha || document.querySelector('iframe[src*="hcaptcha.com"], script[src*="hcaptcha.com"], [data-hcaptcha-widget-id]'))"""


async def _is_hcaptcha(page, info: dict) -> bool:
    """hCaptcha, including recaptchacompat mode: a UUID sitekey or hcaptcha.com frames/scripts on the page."""
    if _UUID_RE.match(str((info or {}).get("sitekey") or "").strip()):
        return True
    try:
        return bool(await page.evaluate(_HCAPTCHA_JS))
    except Exception:  # noqa: BLE001
        return False


def _paid_allowed(sim: S.SimSession) -> bool:
    from mvp.sim_mcp import limits as L

    return not S.is_anon(getattr(sim, "owner", "")) or bool(L.get("anon_allow_paid_captcha"))


async def _paid_token(sim: S.SimSession, kind: str, info: dict) -> dict:
    """Approved paid path (MVP_MCP_PAID_CAPTCHA=1): one CapSolver token through the metered ledger, injected
    the way the site's own widget would deliver it. Spend caps live in mvp.captcha_spend."""
    import asyncio
    from urllib.parse import urlsplit

    from mvp import captcha as cap
    from mvp import captcha_spend as cs

    if not _paid_allowed(sim):
        return {"ok": False, "detail": "cap anon_allow_paid_captcha: the paid captcha solver is not available without a token"}
    host = (urlsplit(sim.product_url).hostname or "").removeprefix("www.")
    if "turnstile" not in kind and await _is_hcaptcha(sim.page, info):
        # Oct 11 Chatwoot: invisible hCaptcha in recaptchacompat mode exposes grecaptcha + g-recaptcha-response, so it
        # looked like reCAPTCHA v2; its UUID sitekey sent as a ReCaptchaV2 task was refused 3 times (no task id).
        # CapSolver has no hCaptcha task: do not pay, do not count an attempt.
        sim.row["hcaptcha_seen"] = True
        return {"ok": False, "type": "hcaptcha",
                "detail": "hCaptcha (reCAPTCHA-compat mode); the paid solver has no hCaptcha task, not paying"}
    if not sim.row.get("capsolver_attempt"):
        sim.row["capsolver_attempt"] = cs.begin_inrun_attempt(host)
    cs.bind_signup(host, sim.row["capsolver_attempt"])
    sitekey = info.get("sitekey") or await sim.page.evaluate(_SITEKEY_JS, kind)
    probe: dict = {}
    if kind != "turnstile":
        try:
            probe = await sim.page.evaluate(_RECAPTCHA_KIND_JS) or {}
        except Exception:  # noqa: BLE001
            probe = {}
    ctype, invisible = _paid_captcha_type(kind, str(info.get("type") or ""), probe,
                                          os.environ.get("MVP_MCP_RECAPTCHA_KIND") or "")
    v3_action = os.environ.get("MVP_MCP_RECAPTCHA_ACTION") or None
    if "v3" in ctype and not v3_action:
        try:  # the action the page itself passes to grecaptcha.execute (a mismatched action fails server-side)
            v3_action = await sim.page.evaluate(_V3_ACTION_JS) or "submit"
        except Exception:  # noqa: BLE001
            v3_action = "submit"
    if not sitekey:
        return {"ok": False, "detail": "no sitekey found"}
    before = cs.spent_usd()
    token = await asyncio.to_thread(cap.solve_sitekey, sitekey=sitekey, page_url=sim.page.url, captcha_type=ctype,
                                    action=v3_action, timeout_s=120, blocking=True,
                                    invisible=invisible)
    cost = round(cs.spent_usd() - before, 5)
    sim.row["capsolver_usd"] = round(float(sim.row.get("capsolver_usd") or 0) + cost, 5)
    if not token:
        return {"ok": False, "type": ctype, "cost_usd": cost, "detail": "solver returned no token (see ledger)"}
    injected = await sim.page.evaluate(_PAID_JS, [kind, token])
    cbs = injected.get("callbacks") if isinstance(injected, dict) else None
    return {"ok": True, "type": ctype, "invisible": invisible, "cost_usd": cost, "callbacks": cbs,
            "detail": "token injected; submit the form now"}


@mcp.prompt()
def usersim_simulate_user(session_id: str, persona: str, task: str) -> str:
    """Instructions for the subagent that plays the simulated user."""
    return SIMULATE_USER_PROMPT.format(
        session_id=session_id,
        persona=persona,
        task=task,
        width=S.VIEWPORT["width"],
        height=S.VIEWPORT["height"],
        max_steps=S.max_steps(),
        budget_min=S.budget_s() // 60,
    )


# ---------------------------------------------------------------- mounting

_STACK: AsyncExitStack | None = None


def _client_token() -> str:
    """Bearer token(s) on /mcp. MVP_MCP_TOKEN, or the file at MVP_MCP_TOKEN_FILE. Several tokens (comma /
    whitespace separated) = separate callers; each sees only its own sessions and studies.
    Tokens are optional: since Oct 17 /mcp is open to anyone with the URL (limits.json allow_anonymous), and callers
    without a token get the caps in limits.json. A valid token skips those caps."""
    tok = (os.environ.get("MVP_MCP_TOKEN") or "").strip()
    path = (os.environ.get("MVP_MCP_TOKEN_FILE") or "").strip()
    if not tok and path:
        try:
            with open(path) as fh:
                tok = fh.read().strip()
        except OSError:
            raise RuntimeError(f"MVP_MCP_TOKEN_FILE set but unreadable: {path}") from None
    return tok


def _require_bearer(endpoint: Any, token: str | None) -> Any:
    """ASGI wrapper. No Authorization header: allowed when limits.json allow_anonymous is true (the caller is then
    'anon' and capped), else 401. A bearer token that is sent must match one of the tokens (constant-time), else
    401, so a client with a stale token finds out instead of silently running with the caps."""
    import hmac
    import re

    from starlette.responses import JSONResponse

    from mvp.sim_mcp import limits as L

    tokens = [t for t in re.split(r"[\s,]+", token or "") if t]

    class Guarded:  # a class instance, so Starlette's Route treats it as a raw ASGI app
        async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
            await guarded(scope, receive, send)

    async def guarded(scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") == "http":
            headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers") or []}
            got = headers.get("authorization", "").strip()
            if not got:
                if not L.get("allow_anonymous"):
                    await JSONResponse({"error": "this UserSim server needs a bearer token right now (limits.json "
                                                 "allow_anonymous is false)"}, status_code=401,
                                       headers={"WWW-Authenticate": "Bearer"})(scope, receive, send)
                    return
            else:
                sent = got[7:].strip() if got.startswith("Bearer ") else ""
                if not (sent and any(hmac.compare_digest(sent, t) for t in tokens)):
                    await JSONResponse({"error": "wrong bearer token (or remove the Authorization header: "
                                                 "no token is needed)"}, status_code=401,
                                       headers={"WWW-Authenticate": "Bearer"})(scope, receive, send)
                    return
        await endpoint(scope, receive, send)

    return Guarded()


def mount(app: Any) -> None:
    """Serve POST/GET /mcp from the FastAPI app and run the MCP session manager with it."""
    import re

    from starlette.responses import JSONResponse
    from starlette.routing import Route

    from mvp.sim_mcp import limits as L

    inner = mcp.streamable_http_app()
    route = next(r for r in inner.routes if getattr(r, "path", "") == "/mcp")
    token = _client_token()
    _TOKENS[:] = [t for t in re.split(r"[\s,]+", token or "") if t]
    endpoint = _require_bearer(route.endpoint, token)
    app.router.routes.insert(0, Route("/mcp", endpoint=endpoint, methods=["GET", "POST", "DELETE"]))

    async def _limits(request: Any) -> Any:
        return JSONResponse(L.snapshot())

    app.router.routes.insert(0, Route("/api/mcp/limits", endpoint=_limits, methods=["GET"]))
    L.load_bundled()

    @app.on_event("startup")
    async def _start_mcp() -> None:
        global _STACK
        _STACK = AsyncExitStack()
        await _STACK.enter_async_context(mcp.session_manager.run())
        L.get("refresh_s")  # starts the first fetch of limits.json from main

    @app.on_event("shutdown")
    async def _stop_mcp() -> None:
        if _STACK is not None:
            await _STACK.aclose()
