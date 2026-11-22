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
from pydantic import BaseModel, ConfigDict, Field
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

Two modes:
- HUMAN MODE (the flow below): a simulated user really uses the product in a cloud browser; UserSim records and judges it.
- AGENT MODE (usersim_predict_experience): no browser. Predicts how a kind of user will experience a product from live
  G2/Capterra/TrustRadius/Gartner reviews of the product and its named rivals: expected ratings, pros, cons, overall experience. Takes 1-2 min
  on the first call (status "pending" means call again). Use it to set expectations before, or instead of, human mode.
- HUMAN MODE ON TOP OF AGENT MODE (for a prediction): usersim_plan_human_run gives the task that adds signal (the core
  job done for real, not onboarding); run it with the flow below; then usersim_combine_human_run adds what the run saw
  to the agent-mode prediction in the amount that held up on real reviewers (ratings unchanged; pros/cons rewritten
  with the run's product observations).

Human mode flow:
1. Get a PUBLIC product URL from the human (localhost won't work; a preview/staging deploy is fine). That is the only thing they must provide.
2. Draft a realistic persona (one or two sentences: who they are, what they know, why they are here) and ONE task, using the codebase / recent changes if helpful. Show both to the human and wait for approval.
3. Call usersim_start_session. Open the returned watch_url for the human (e.g. `open <url>` on macOS, `xdg-open <url>` on Linux) so they can watch the browser live.
4. Run the simulated user as a subagent on the model chosen above. Give it the session_id, persona, task and the usersim_simulate_user prompt. It loops usersim_act until done, then calls usersim_finish.
5. Call usersim_get_report and summarise it for the human. The judge verdict and proof checks come from UserSim, not from the simulated user.

Full comparison study (the only study shape UserSim runs — see docs/E2E_TEST.md):
1. Draft exactly six personas, six tasks, and two competitor URLs (target product + 2 rivals = 3 products). Show them to the human and wait for approval. Omitted rivals or personas/tasks can be auto-filled, but never fewer than the full matrix.
2. Call usersim_start_study once. It returns study_id, watch_url, report_url and 108 cells (6 personas × 6 tasks × 3 sites).
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
  Then usersim_wait_for_verification_code or usersim_wait_for_verification_link (+ usersim_open_verification_link with link_number=1 for the first link). Captcha in the way: click the checkbox, drag the slider or press_and_hold once like a person. If it opens an image grid ("select all squares with ..."), NEVER click tiles: call usersim_solve_captcha, then look at the page and continue. If the grid is still there after two calls, or an observation says captcha_stuck, call usersim_finish with outcome blocked.
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
_ROLES: dict[str, str] = {}  # token value -> role: "user" (default), "reader" or "admin"
ROLE_RANK = {"anon": 0, "user": 1, "reader": 2, "admin": 3}
PH_SITE_BASE_DEFAULT = "https://usersim.vercel.app"


def parse_tokens(raw: str) -> list[tuple[str, str]]:
    """Token list -> [(token, role)]. Entries are comma/whitespace separated. 'admin=TOKEN' and 'reader=TOKEN' give a
    role; a bare TOKEN is role 'user' (what every token was before roles: skips the anonymous caps, sees only its own
    studies). Roles: reader = user + can pull the website's information and every saved study report; admin = reader +
    server overview. A token's role is never taken from the request, only from this configuration."""
    import re

    out: list[tuple[str, str]] = []
    for part in re.split(r"[\s,]+", raw or ""):
        if not part:
            continue
        m = re.match(r"^(admin|reader|user)=(.+)$", part)
        out.append((m.group(2), m.group(1)) if m else (part, "user"))
    return out


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
    fingerprint of the client IP; the caps in limits.json are counted per that key. Ownership checks use
    sessions.same_owner: callers without a token keep their sessions and studies when their IP changes between
    requests (NAT/relay pools), and a session_id (random, returned only to its creator) is their credential."""
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


def _role(ctx: Context | None) -> str:
    """'anon' (no valid token), or the role of the token the caller sent: user, reader or admin."""
    import hmac

    if ctx is None:
        return "anon"
    headers, _peer = _headers(ctx)
    got = headers.get("authorization") or ""
    tok = got[7:].strip() if got.startswith("Bearer ") else ""
    if not tok:
        return "anon"
    for t in _TOKENS:
        if hmac.compare_digest(tok, t):
            return _ROLES.get(t, "user")
    return "anon"


def _needs(ctx: Context | None, minimum: str) -> str | None:
    """None when the caller's role is at least `minimum`; otherwise the JSON error to return."""
    have = _role(ctx)
    if ROLE_RANK[have] >= ROLE_RANK[minimum]:
        return None
    return json.dumps({"error": f"this tool needs a {minimum} token (you are: {have}). Ask the UserSim owner for one "
                                "and send it as 'Authorization: Bearer <token>'."})


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


class StudyPersona(BaseModel):
    """One simulated person. bio is required."""

    model_config = ConfigDict(extra="allow")
    name: str = Field(default="", description='Display name, e.g. "Maya Ortiz". Optional.')
    bio: str = Field(description="Required. One or two sentences: who they are, what they know, why they are here.")
    favors: str | None = Field(default=None, description="Optional: the site URL or name this persona is aimed at.")


class StudyTask(BaseModel):
    """One goal every persona tries on every site. prompt is required."""

    model_config = ConfigDict(extra="allow")
    prompt: str = Field(description='Required. One goal in the user\'s own words, e.g. "Sign up and create your first project".')
    title: str | None = Field(default=None, description="Optional short label for the report; defaults to the prompt.")
    favors: str | None = Field(default=None, description="Optional: the site URL or name this task is aimed at.")


@mcp.tool(structured_output=False)
async def usersim_start_study(
    ctx: Context,
    product_url: str = Field(description="Public URL of the target product (https://...)."),
    personas: list[StudyPersona] = Field(
        description="Exactly 6 buyer personas, or [] to auto-generate. Each needs bio. See docs/E2E_TEST.md.",
    ),
    tasks: list[StudyTask] = Field(
        description="Exactly 6 tasks, or [] to auto-generate. Include signup + email verification as one task. See docs/E2E_TEST.md.",
    ),
    competitors: list[str] | None = Field(
        default=None,
        description="Exactly 2 public competitor URLs, or omit/[] to auto-discover. Target + 2 rivals = 3 products. See docs/E2E_TEST.md.",
    ),
) -> str:
    """Start a full UserSim e2e study (docs/E2E_TEST.md): 3 products, 6 personas, 6 tasks, 108 cells, comparison report.

    Partial lists with the wrong length are rejected. Empty competitors/personas/tasks are filled using the same planner as the website.
    Returns study_id, watch_url, report_url and cells. Run each cell with usersim_start_session(study_id=..., cell_id=...).
    """
    from mvp.e2e_study import E2EStudyRejected, ensure_full_study_inputs

    personas_in = [p.model_dump(exclude_none=True) if isinstance(p, BaseModel) else p for p in personas]
    tasks_in = [t.model_dump(exclude_none=True) if isinstance(t, BaseModel) else t for t in tasks]
    try:
        comps, personas_in, tasks_in = await ensure_full_study_inputs(
            product_url, list(competitors or []), personas_in, tasks_in
        )
    except E2EStudyRejected as exc:
        return _fail(S.SessionError(str(exc)))
    try:
        study = S.create_matrix_study(
            product_url=product_url, competitors=comps, personas=personas_in, tasks=tasks_in, owner=_owner(ctx)
        )
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
    _allow_paid_captcha_host(sim)
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
        stuck_note = None
        if str((action or {}).get("type")) in {"click", "key"}:
            await _refresh_v3_token(sim)
            extra = await _maybe_paid_presolve(sim)
            stuck = await _image_challenge_guard(sim)
            if isinstance(stuck, str):
                return _fail(S.SessionError(stuck))
            if stuck:
                stuck_note = stuck
        obs = await S.act(sim, action, thought)
        notes = {}
        if extra:
            notes["captcha_presolve"] = extra
        if stuck_note:
            notes["captcha_stuck"] = stuck_note
        return _obs_content(sim, obs, notes or None)
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
            and not sim.row.get("login_email")
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
    try:
        from mvp.sim_mcp.report import signup_verified as _sv

        if not sim.row.get("login_email") and _sv(sim.row):
            S.save_host_account(sim)
    except Exception:  # noqa: BLE001
        pass
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
    if not data or not (ROLE_RANK[_role(ctx)] >= ROLE_RANK["reader"] or S.owns_study(data, _owner(ctx))):
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


# ---------------------------------------------------------------- reader / admin tools (token roles)

_PH_LAUNCH_KEYS = ("id", "name", "tagline", "slug", "topics", "actual_rank", "current_rank", "votes", "board_rank",
                   "board_votes")
_PH_POINT_KEYS = ("key", "label", "time_pt", "data_cut_pt", "made_at", "data_up_to", "method", "sees", "ranks",
                  "exp_votes", "vote_err", "backtest_line", "fallback", "late")


def _fetch_site_json(url: str) -> dict[str, Any]:
    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": "usersim-mcp/1"})
    with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310 (fixed https base, validated day)
        return json.loads(resp.read().decode())


def ph_page_view(raw: dict[str, Any]) -> dict[str, Any]:
    """What the website's Product Hunt page shows, trimmed to named fields: product names and ranks, the published
    midnight forecast, the accuracy record and how fresh each feed is. No people, no usernames."""
    return {
        "day": raw.get("day"),
        "status": raw.get("status"),
        "board": raw.get("board"),
        "launches": [{k: x.get(k) for k in _PH_LAUNCH_KEYS} for x in raw.get("launches") or []],
        "forecast_points": [{k: x.get(k) for k in _PH_POINT_KEYS} for x in raw.get("points") or []],
        "accuracy": raw.get("accuracy"),
        "freshness": raw.get("freshness"),
        "why": raw.get("why"),
        "days_available": raw.get("days"),
    }


@mcp.tool(structured_output=False)
async def usersim_ph_page(ctx: Context, day: str = "") -> str:
    """READER or ADMIN token. The information on the website's Product Hunt page: the day's launches with live ranks
    and votes, the published midnight forecast (ranks and expected votes, when it was written and what it saw), the
    accuracy record and feed freshness. day: YYYY-MM-DD (Pacific time) for a past day, empty for today. Names and
    numbers only; no people."""
    import asyncio
    import re

    denied = _needs(ctx, "reader")
    if denied:
        return denied
    if day and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        return _fail(S.SessionError("day must look like 2026-11-22"))
    base = (os.environ.get("MVP_PH_SITE_BASE") or PH_SITE_BASE_DEFAULT).rstrip("/")
    url = f"{base}/api/ph/today" + (f"?day={day}" if day else "")
    try:
        raw = await asyncio.to_thread(_fetch_site_json, url)
    except Exception as exc:  # noqa: BLE001
        return _fail(S.SessionError(f"could not read the website's page data: {exc}"))
    return json.dumps(ph_page_view(raw), indent=1)


def _post_site_json(path: str, body: dict[str, Any], timeout: float = 60.0) -> tuple[int, dict[str, Any]]:
    """POST JSON to the website's own /api/try/* steps. Returns (status, json). Network errors raise."""
    import urllib.error
    import urllib.request

    base = (os.environ.get("MVP_PH_SITE_BASE") or PH_SITE_BASE_DEFAULT).rstrip("/")
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "User-Agent": "usersim-mcp/1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (fixed https base)
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read().decode() or "{}")
        except Exception:  # noqa: BLE001
            return exc.code, {"error": f"HTTP {exc.code}"}


def quick_run_card(analysis: dict[str, Any], name: str, people: dict[str, Any], launch: dict[str, Any],
                   reactions: dict[str, Any], asks: dict[str, Any]) -> str:
    """The pre-launch card for a product that is not on the line-up: the same layout as the launch card, built from the
    quick run. No team network and no competitor finishes (those need a real launch), and it says so."""
    title = (analysis.get("name") if isinstance(analysis, dict) else None) or name or "This product"
    tagline = (analysis.get("tagline") if isinstance(analysis, dict) else "") or ""
    concerns = [c for c in (asks.get("concerns") or []) if isinstance(c, str)]
    worry = concerns[0] if concerns else None
    question = asks.get("question") if isinstance(asks.get("question"), str) else None
    rb, vb = launch.get("rank_band") or {}, launch.get("votes_band") or {}
    segs = [x for x in (people.get("segments") or []) if isinstance(x, dict)][:3]
    md = [f"# {title}", tagline, "", "## Overview"]
    if worry:
        md.append(f"- Top worry: {worry}")
    if rb.get("likely"):
        md.append(f"- Where it may land: likely rank {rb['likely'][0]}–{rb['likely'][1]} (median {rb.get('median')}), "
                  f"likely votes {vb.get('likely', ['?', '?'])[0]}–{vb.get('likely', ['?', '?'])[1]}"
                  + (f" ({launch.get('percentile')}th percentile of past launches)" if launch.get("percentile") is not None else ""))
    if people.get("likely_share") is not None:
        md.append(f"- Members it resembles: {people.get('likely_count'):,} of {people.get('people_scored'):,} people we hold "
                  f"({people['likely_share']:.0%})")
    md += ["", "## Who votes"] + [f"- {x.get('name')}: {x.get('likely')} of {x.get('size')} resemble it "
                                  f"({x.get('lift', 0):.1f}× their usual share)" for x in segs]
    heads = reactions.get("headline")
    if heads:
        md += ["", "## What they'll say", f"- {heads}"]
    pts = ["We can't see your team's Product Hunt network until you launch, so most early votes will come from people who "
           "don't know you yet. The pitch and the first comment carry the launch."]
    if worry:
        pts.append(f"Answer this worry in the first comment, before anyone asks: “{worry}”")
    if question:
        pts.append(f"Put this answer on the page: “{question}”")
    if rb.get("likely"):
        pts.append("Treat the rank band as a wide guide: pre-launch rank prediction from a page alone is weak. "
                   "A real launch adds the hunter, the team and the competitors' finishes.")
    md += ["", "## Talking points for the founder"] + [f"{i}. {t}" for i, t in enumerate(pts, 1)]
    md += ["", "Simulated, not real comments or votes. Not on Product Hunt yet: no team network or competitor finishes."]
    return "\n".join(md)


@mcp.tool(structured_output=False)
async def usersim_ph_quick_run(ctx: Context, product_url: str = "", name: str = "", tagline: str = "",
                               description: str = "") -> str:
    """READER or ADMIN token. The website's Product Hunt "try a product" simulation as one call (about 15 seconds):
    who on Product Hunt the product resembles (segments, sizes, activity tiers), where it may land (percentile, likely
    rank and vote bands, with the tested accuracy of that estimate), simulated reactions by type of member, and the
    questions and concerns launch-day visitors are likely to raise. Give a public product_url, or name + tagline +
    description if the page needs JavaScript or a login. Simulated, not real comments; people are anonymous types.
    The website's caps apply (3 runs an hour and 10 a day per client address, 150 a day in total); every caller of
    this server shares one address, so expect to wait if others have just used it."""
    import asyncio

    denied = _needs(ctx, "reader")
    if denied:
        return denied
    if product_url:
        status, first = await asyncio.to_thread(_post_site_json, "/api/try/page", {"url": product_url[:2000]})
    elif name and description:
        status, first = await asyncio.to_thread(_post_site_json, "/api/try/text", {
            "name": name[:200], "tagline": tagline[:300], "description": description[:4000]})
    else:
        return _fail(S.SessionError("give a product_url, or name + description (tagline optional)"))
    token = first.get("token")
    if status != 200 or not token:
        hint = ""
        if status == 429:
            hint = " The website's quick-run caps are used up for now (3 an hour, 10 a day, 150 in total); try later."
        elif status == 422 and product_url:
            hint = " Try name + tagline + description instead of the URL."
        return _fail(S.SessionError(f"{first.get('error') or 'the quick run could not start'}.{hint}".replace("..", ".")))

    async def step(name_: str) -> dict[str, Any]:
        try:
            st, out = await asyncio.to_thread(_post_site_json, f"/api/try/{name_}", {"token": token}, 75.0)
        except Exception as exc:  # noqa: BLE001
            return {"error": f"{name_} failed: {exc}"}
        return out if st == 200 else {"error": out.get("error") or f"{name_} returned HTTP {st}"}

    # people and launch use no model and are safe together. The two model steps share one run record on the website
    # ("each LLM step can be spent once"), and run at the same moment one of them reported an expired run, so they go
    # one after the other.
    people, launch = await asyncio.gather(step("people"), step("launch"))
    reactions = await step("reactions")
    asks = await step("asks")
    card = quick_run_card(first.get("analysis") or {}, name, people, launch, reactions, asks)
    return json.dumps({
        "card_markdown": card,
        "analysis": first.get("analysis"),
        "who_it_resembles": people,
        "where_it_may_land": launch,
        "simulated_reactions": reactions,
        "likely_questions": asks,
        "caps": first.get("caps"),
        "runs_used_today": first.get("used_today"),
        "reading_note": "Simulated, not real comments or votes. Pre-launch rank prediction is weak: read the accuracy "
                        "and honesty fields before relying on any number.",
    }, indent=1)


# ---- launch card: the website's per-launch Product Hunt card (overview, who votes, what they'll say, competitors, why)

def _words(t: str) -> set[str]:
    import re

    return set(re.findall(r"[a-z0-9]{3,}", (t or "").lower()))


def _overlap(a: str, b: str) -> float:
    x, y = _words(a), _words(b)
    return len(x & y) / max(1, min(len(x), len(y)))


def _norm_name(t: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]", "", (t or "").lower())


def _host_stem(url: str) -> str:
    from urllib.parse import urlparse

    host = urlparse(url if "//" in (url or "") else "https://" + (url or "")).netloc.lower()
    host = host.removeprefix("www.")
    return _norm_name(host.split(".")[0]) if host else ""


def find_launch(launches: list[dict[str, Any]], product_url: str, name: str) -> dict[str, Any] | None:
    """The line-up launch this product is: exact name, or its slug / host name matching."""
    want = [w for w in (_norm_name(name), _host_stem(product_url)) if w]
    for x in launches:
        names = {_norm_name(x.get("name") or ""), _norm_name(x.get("slug") or "").removesuffix("2")}
        if any(w in names for w in want):
            return x
    for x in launches:
        n = _norm_name(x.get("name") or "")
        if any(len(w) >= 5 and (w in n or n in w) for w in want if n):
            return x
    return None


def _votes_pct(points: float) -> str:
    import math

    v = (math.exp(points) - 1) * 100
    return f"{'+' if v >= 0 else '−'}{abs(round(v))}% votes"


def launch_card(launch: dict[str, Any], d: dict[str, Any]) -> dict[str, Any]:
    """The card the website's Product Hunt page shows for one launch: tiles and the founder's talking points, built
    from the same per-launch data (mirrors exOverview in mvp/static/ph.html), plus a summary of each tab."""
    import math

    who, say, why, aud = d.get("who") or {}, d.get("say") or {}, d.get("why") or {}, d.get("audience") or {}
    items = (say.get("persona_panel") or {}).get("items") or []
    worry = next((x["concern"] for x in items if x.get("interest") == "high" and x.get("concern")), None) \
        or next((x["concern"] for x in items if x.get("concern")), None) or (say.get("top_concerns") or [None])[0]
    ask = next((q for q in say.get("top_questions") or [] if _overlap(q, worry or "") < 0.5), None)
    comps = (d.get("competitors") or {}).get("items") or []
    own = next((c for c in comps if _norm_name(c.get("name")) == _norm_name(launch.get("name"))), None)
    others = [c for c in comps if c is not own]
    best = sorted(others, key=lambda c: c.get("final_daily_rank") or 99)[0] if others else None
    gap = next((c for c in others if (c.get("commenters_complained") or [None])[0]), None)
    inputs = why.get("all_inputs") or why.get("top_drivers") or []
    up = max(inputs, key=lambda r: r.get("points", 0), default=None)
    down = min((r for r in inputs if r.get("points", 0) < 0), key=lambda r: r["points"], default=None)

    def strong(r: dict[str, Any] | None) -> bool:
        return bool(r) and abs(math.exp(r["points"]) - 1) >= 0.05

    f, pu = aud.get("follow_ties"), aud.get("power_users") or {}
    if not f:
        net = ("We can't see your team's Product Hunt network (your profiles aren't among the people we hold), so most "
               "early votes will come from people who don't know you yet. The pitch and the first comment carry the launch.")
    else:
        third = math.ceil(f["of"] / 3)
        tier = "top" if f["rank"] <= third else "bottom" if f["rank"] > math.floor(f["of"] * 2 / 3) else "middle"
        n = f"{round(f['value']):,}"
        net = {"top": f"You have one of today's biggest networks: {n} people we hold follow the hunter or makers "
                      f"(#{f['rank']} of the {f['of']} launches whose network we can see). Make sure they know it's live.",
               "middle": f"Your network is mid-sized for today: {n} followers we hold (#{f['rank']} of {f['of']}). "
                         "Votes beyond it depend on the pitch.",
               "bottom": f"Your network is one of today's smallest we can see ({n} followers we hold, #{f['rank']} of "
                         f"{f['of']}). Reach beyond it: the first comment and the gallery have to win strangers."}[tier]
    tp = next((p for p in (who.get("maker_past_backers"), who.get("hunter_past_backers"), who.get("team_past_backers"))
               if p and (p.get("n_held_people") or 0) >= 20), None)
    lean = next((x for x in (tp or {}).get("segments_by_lift") or [] if x.get("lift", 0) >= 1.3 and x.get("n", 0) >= 20), None)
    tlean = next((x for x in (tp or {}).get("topics_by_lift") or [] if x.get("lift", 0) >= 1.3), None)
    pts = [net]
    if lean:
        more = f" and upvote {tlean['topic']} launches more than most" if tlean else ""
        pts.append(f"People who voted for your earlier launches lean towards {lean['segment']} ({lean['lift']:.1f}× their "
                   f"usual share){more}. Speak to them first.")
    if pu.get("day_median") and pu.get("share", 0) / pu["day_median"] >= 1.5:
        pts.append(f"Your audience has more heavy upvoters than most launches today ({pu['share']:.0%} vs a typical "
                   f"{pu['day_median']:.0%}). They vote in the first hours, so be in the comments early.")
    if own:
        pts.append(f"Your earlier launch {own['name']} finished #{own.get('final_daily_rank')} with "
                   f"{round(own.get('final_votes') or 0)} votes.")
    if worry:
        pts.append(f"Answer this worry in the first comment, before anyone asks: “{worry}”")
    if ask:
        pts.append(f"Put this answer on the page: “{ask}”")
    if gap:
        pts.append(f"People disliked this in a similar product ({gap['name']}): “{gap['commenters_complained'][0]}” "
                   "Show how this one avoids it.")
    raw = d.get("raw") or {}
    if strong(down) and down["input"] == "team size" and raw.get("team size") is not None and raw["team size"] <= 2:
        k = raw["team size"]
        pts.append(f"{'No makers are' if k == 0 else 'Only 1 maker is' if k == 1 else 'Only 2 makers are'} listed on the "
                   f"launch. Launches that list the whole team do better in our model ({_votes_pct(down['points'])} "
                   "here): add the team as makers.")
    elif strong(down):
        pts.append(f"Weakest factor in our model: {down['input']} ({_votes_pct(down['points'])}).")
    tiles = {"top_worry": worry,
             "biggest_boost": ({"factor": up["input"], "effect": _votes_pct(up["points"])} if strong(up) else "No strong boost"),
             "closest_past_launch": ({"name": best["name"], "finished": best.get("final_daily_rank")} if best else None),
             "heavy_upvoters": ({"share": pu.get("share"), "typical_today": pu.get("day_median")} if pu.get("day_median") else None)}
    ph_url = f"https://www.producthunt.com/posts/{launch.get('slug')}" if launch.get("slug") else None
    md = [f"# {launch.get('name')}", launch.get("tagline") or "", "", "## Overview"]
    if worry:
        md.append(f"- Top worry: {worry}")
    md.append("- Biggest boost: " + (f"{up['input']} ({_votes_pct(up['points'])})" if strong(up) else "No strong boost"))
    if best:
        md.append(f"- {'Your earlier launch' if own else 'Closest past launch'}: "
                  f"{(own or best)['name']}" + (f", finished #{(own or best).get('final_daily_rank')}" if (own or best).get("final_daily_rank") else ""))
    if tiles["heavy_upvoters"]:
        md.append(f"- Heavy upvoters in its audience: {pu['share']:.0%} (typical launch today: {pu['day_median']:.0%})")
    md += ["", "## Talking points for the founder"] + [f"{i}. {t}" for i, t in enumerate(pts, 1)]
    md += ["", "Built only from the tabs here; each tab says how reliable it is."]
    if ph_url:
        md.append(f"[View on Product Hunt]({ph_url})")
    return {"launch": {"id": launch.get("id"), "name": launch.get("name"), "tagline": launch.get("tagline"),
                       "product_hunt_url": ph_url},
            "overview": tiles, "talking_points": pts,
            "who_votes": {"network": who.get("network"), "segments_by_lift": who.get("segments_by_lift"),
                          "group_mix": who.get("group_mix"), "expected_held_votes": who.get("expected_held_votes")},
            "what_theyll_say": {"persona_panel": items, "top_concerns": say.get("top_concerns"),
                                "top_questions": say.get("top_questions"), "reactions": say.get("reactions")},
            "competitors": comps, "why": {"top_drivers": why.get("top_drivers"), "all_inputs": inputs},
            "card_markdown": "\n".join(md)}


@mcp.tool(structured_output=False)
async def usersim_launch_card(ctx: Context, product_url: str = "", name: str = "", day: str = "") -> str:
    """READER or ADMIN token. The website's Product Hunt card for a product, as on the /ph page: overview (top worry,
    biggest boost, closest past launch, heavy upvoters vs a typical launch), who votes, what they'll say, competitors
    (closest past launches and how they finished), why, and talking points for the founder. Give the product's URL
    and/or name. If the product is one of the day's launches (day = YYYY-MM-DD Pacific, default today, then the last
    two days), you get its full card. If it is not on Product Hunt yet, use usersim_ph_quick_run for the pre-launch
    version (no team network or competitor finishes, because those need a real launch)."""
    import asyncio
    import re
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    denied = _needs(ctx, "reader")
    if denied:
        return denied
    if not (product_url or name):
        return _fail(S.SessionError("give a product_url and/or a name"))
    if day and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        return _fail(S.SessionError("day must look like 2026-11-22"))
    base = (os.environ.get("MVP_PH_SITE_BASE") or PH_SITE_BASE_DEFAULT).rstrip("/")
    today = datetime.now(ZoneInfo("America/Los_Angeles")).date()
    days = [day] if day else [str(today - timedelta(days=k)) for k in range(3)]
    try:
        for dd in days:
            page = await asyncio.to_thread(_fetch_site_json, f"{base}/api/ph/today?day={dd}")
            hit = find_launch(page.get("launches") or [], product_url, name)
            if not hit:
                continue
            ex = await asyncio.to_thread(_fetch_site_json, f"{base}/api/ph/explain?day={dd}")
            d = (ex.get("launches") or {}).get(str(hit["id"]))
            if not d:
                continue
            card = launch_card(hit, d)
            card["day"] = dd
            card["how_reliable"] = ex.get("labels")
            return json.dumps(card, indent=1)
    except Exception as exc:  # noqa: BLE001
        return _fail(S.SessionError(f"could not read the website's launch data: {exc}"))
    return _fail(S.SessionError(
        "that product is not among the launches on " + ", ".join(days) + ". The full card exists only for products on "
        "Product Hunt's line-up. For a product that has not launched, use usersim_ph_quick_run (the pre-launch version), "
        "or pass an earlier day."))


@mcp.tool(structured_output=False)
async def usersim_list_studies(ctx: Context, limit: int = 30) -> str:
    """READER or ADMIN token. The saved studies, newest first: id, product URL, status, phase, last update. Pass an id
    to usersim_get_report to read its full report. A reader or admin can read every study, not just their own."""
    denied = _needs(ctx, "reader")
    if denied:
        return denied
    from mvp.server import list_studies

    out = await list_studies(limit=max(1, min(int(limit), 100)))
    rows = [{k: r.get(k) for k in ("id", "url", "status", "phase", "updated_at", "agents", "persona_count",
                                   "task_count")} for r in out.get("studies", [])]
    return json.dumps({"studies": rows}, indent=1)


@mcp.tool(structured_output=False)
async def usersim_admin_overview(ctx: Context) -> str:
    """ADMIN token only. The server's current state: engine version, the limits in force and where they came from,
    how much anonymous spend has been used today, and how many tokens of each role are configured."""
    denied = _needs(ctx, "admin")
    if denied:
        return denied
    from mvp.sim_mcp import limits as L

    counts: dict[str, int] = {}
    for t in _TOKENS:
        r = _ROLES.get(t, "user")
        counts[r] = counts.get(r, 0) + 1
    return json.dumps({"limits": L.snapshot(), "tokens_by_role": counts,
                       "open_sessions": len(S._active())}, indent=1, default=str)


# ---------------------------------------------------------------- agent mode (review data only, no browser)


class AgentPersona(BaseModel):
    """The kind of user to predict for. Fill what you know; role matters most for the words."""

    model_config = ConfigDict(extra="allow")
    role: str = Field(description='Job title, e.g. "Marketing manager".')
    company_size: str | None = Field(default=None, description='e.g. "11-50 employees" or "Mid-Market".')
    industry: str | None = Field(default=None, description='e.g. "Marketing and Advertising".')
    time_used: str | None = Field(default=None, description='How long they have used the product: "trial", "<6 months", "6-12 months", "1-2 years" or "2+ years". A first-time user is "trial".')
    bio: str | None = Field(default=None, description="Optional one-line description.")


@mcp.tool(structured_output=False)
async def usersim_predict_experience(
    ctx: Context,
    product: str = Field(description='Product name as review sites list it, e.g. "Basecamp". The scrapers search by this name.'),
    persona: AgentPersona = Field(description="The kind of user to predict for."),
    product_url: str = Field(default="", description="Public URL of the product. Used to check that scraped reviews are of THIS product (not another with the same name); without it the product's own reviews are not used."),
    task: str = Field(default="", description="What this user is trying to get done (optional)."),
    competitors: list[str] | None = Field(default=None, description='Names of 1-3 real rivals, e.g. ["Asana", "Trello"]. Used for the rating prior and for complaint topics. Omit to have them discovered from product_url.'),
) -> str:
    """AGENT MODE: predict how this kind of user will experience the product from live review data. No browser.

    Returns expected ratings (overall, ease of use, recommend 0-10) set from the product's own recent G2/Capterra/TrustRadius/Gartner
    reviews shrunk toward its rivals', plus pros, cons and overall experience written from the
    most similar reviewers. The first call starts the scrapes (1-2 min) and may return status "pending": call
    again with the same arguments. For first-hand evidence use HUMAN MODE (usersim_start_session).
    """
    from mvp import agent_mode
    from mvp.sim_mcp import limits as L

    owner = _owner(ctx)
    try:
        if S.is_anon(owner):
            L.charge(owner, float(L.get("est_usd_per_prediction")), "predict_experience", dry=True)
    except L.CapExceeded as exc:
        return _cap_fail(exc)
    pdict = persona.model_dump(exclude_none=True) if isinstance(persona, BaseModel) else dict(persona or {})
    out = await agent_mode.predict_experience(product=product, url=product_url, persona=pdict, task=task,
                                              competitors=list(competitors or []))
    if out.get("status") == "ok" and S.is_anon(owner):
        try:
            L.charge(owner, float(L.get("est_usd_per_prediction")), "predict_experience")
        except L.CapExceeded as exc:
            return _cap_fail(exc)
    return json.dumps(out, indent=1, default=str)


# ---------------------------------------------------------------- human mode on top of agent mode


@mcp.tool(structured_output=False)
async def usersim_plan_human_run(
    ctx: Context,
    product: str = Field(description='Product name as review sites list it, e.g. "Basecamp".'),
    product_url: str = Field(description="Public URL of the product."),
    persona: str = Field(default="", description="One sentence: who the simulated user is."),
    competitors: list[str] | None = Field(default=None, description="1-3 rival names; omit to discover them from product_url."),
) -> str:
    """HUMAN MODE, step 1: the task to give the simulated user so the run adds signal on top of agent mode.

    Built from rivals' live review complaints: do the core job with 3+ items, two second-level features, then edit /
    reorganise (onboarding and pricing are already predictable from reviews). Returns start_session arguments and the
    observation format. May return status "pending" while rival scrapes run: call again."""
    from mvp import human_mode

    out = await human_mode.plan(product=product, url=product_url, persona=persona, competitors=list(competitors or []))
    return json.dumps(out, indent=1, default=str)


@mcp.tool(structured_output=False)
async def usersim_combine_human_run(
    ctx: Context,
    product: str = Field(description='Product name as review sites list it, e.g. "Basecamp".'),
    persona: AgentPersona = Field(description="The kind of user to predict for."),
    observations: list[dict[str, Any]] = Field(description='The run\'s observations: [{"kind": "product_friction" | "product_benefit" | "signup_friction" | "agent_failure", "what": "..."}].'),
    product_url: str = Field(default="", description="Public URL of the product."),
    task: str = Field(default="", description="What this user is trying to get done (optional)."),
    competitors: list[str] | None = Field(default=None, description="1-3 rival names; omit to discover them from product_url."),
) -> str:
    """HUMAN MODE, step 3: agent-mode prediction plus what the simulated user saw, in the amount that held up on real
    reviewers. Ratings stay agent mode's. With the product's own reviews, pros / cons / overall experience are rewritten
    with the run's product observations added (held out: cons recall +0.05); with none, at most one pro and one con
    change (setup, free-plan, pricing and support notes dropped). May return status "pending": call again."""
    from mvp import human_mode
    from mvp.sim_mcp import limits as L

    owner = _owner(ctx)
    try:
        if S.is_anon(owner):
            L.charge(owner, float(L.get("est_usd_per_prediction")), "combine_human_run", dry=True)
    except L.CapExceeded as exc:
        return _cap_fail(exc)
    pdict = persona.model_dump(exclude_none=True) if isinstance(persona, BaseModel) else dict(persona or {})
    out = await human_mode.combine(product=product, url=product_url, persona=pdict, task=task,
                                   observations=human_mode.parse_observations(observations),
                                   competitors=list(competitors or []))
    if out.get("status") == "ok" and S.is_anon(owner):
        try:
            L.charge(owner, float(L.get("est_usd_per_prediction")), "combine_human_run")
        except L.CapExceeded as exc:
            return _cap_fail(exc)
    return json.dumps(out, indent=1, default=str)


# ---------------------------------------------------------------- signup tools (shared core: mvp.signup_tools)


def _host(sim: S.SimSession) -> str:
    from urllib.parse import urlsplit

    return (urlsplit(sim.product_url).hostname or "").removeprefix("www.")


_STUDY_ACCOUNTS: dict[tuple[str, str], dict[str, Any]] = {}


def _study_account_for(sim: S.SimSession, owner: str) -> str | None:
    """One signup per site per study: later cells log in to the account the first cell created instead of signing up
    again (Oct 23 Smartsheet: 29 signups from 36 cells hit one shared Gmail inbox, the site mailed one confirmation and
    answered the rest with 500 / "already exists"). Returns the reuse reply for this cell, or None when this cell
    should sign up itself (it then becomes the site's account owner). A cell whose owner ended without a verified
    signup takes the account over, so one failed signup does not strand the rest."""
    from mvp.sim_mcp import limits as L
    from mvp.sim_mcp.report import signup_verified
    from mvp.sim_mcp.sessions import registrable_domain

    if not getattr(sim, "matrix", False) or not L.get("study_shared_accounts"):
        return None
    key = (sim.study.id, registrable_domain(_host(sim)))
    entry = _STUDY_ACCOUNTS.get(key)
    if not entry or entry["sid"] == sim.id:
        return None
    try:
        prev = S.get_session(entry["sid"], owner)
        entry["verified"] = entry["verified"] or signup_verified(prev.row)
        alive = not prev.closed
    except S.SessionError:
        alive = False
    if not entry["verified"] and not alive:
        _STUDY_ACCOUNTS.pop(key, None)  # the owner never got an account: this cell signs up (and owns it) instead
        return None
    out = json.loads(_reuse_account(sim, entry["sid"], owner))
    if entry["verified"]:
        out["next"] = ("A verified account for this site already exists in this study: log in with this email and "
                       "password. Do not sign up again. If the site emails a login code or link, read it with "
                       "usersim_wait_for_verification_code / _link.")
    else:
        out["next"] = ("Another simulated user is creating this site's account right now (one signup per site per study). "
                       "Try logging in with this email and password; if the site says there is no such account, wait about "
                       "a minute (usersim_act wait) and try again. Do not sign up again.")
    sim.row["shared_study_account"] = {"owner_cell": entry.get("cell"), "verified": bool(entry["verified"])}
    return json.dumps(out)


def _register_study_account(sim: S.SimSession) -> None:
    from mvp.sim_mcp import limits as L
    from mvp.sim_mcp.sessions import registrable_domain

    if getattr(sim, "matrix", False) and L.get("study_shared_accounts"):
        _STUDY_ACCOUNTS.setdefault((sim.study.id, registrable_domain(_host(sim))),
                                   {"sid": sim.id, "cell": sim.agent_id, "verified": False})


def _host_registry_account(sim: S.SimSession) -> str | None:
    """no_plus on a site that already holds this inbox's account: log in to it instead of signing up again (a site that
    treats dot-variants as one address ignores a second signup and sends no mail)."""
    import time

    saved = S.load_host_account(_host(sim))
    if not saved:
        return None
    from mvp.signup_inbox import GmailAliasInbox

    try:
        inbox = GmailAliasInbox.for_address(str(saved["address"]))
    except Exception:  # noqa: BLE001
        return None
    sim.inbox, sim.identity = inbox, dict(saved.get("identity") or {})
    sim.mail_since = time.time() - 30
    sim.row["login_email"] = inbox.address
    sim.row["reused_account_from"] = "host_registry"
    sim.row.pop("signup_email", None)  # the '+' identity issued first was never used: this run is a login, not a signup
    ident = {k: v for k, v in sim.identity.items() if k != "code"}
    return json.dumps({**ident, "reused_account": True,
                       "next": "This site already has an account for the shared signup inbox (it treats dot-variants of one address "
                               "as the same, so a new signup would be ignored and no mail would come). Log in with this email and "
                               "password instead of signing up. If it says no such account, pick the other data region on the "
                               "sign-in page (North America / European Union / Australia). Login codes or links the site mails "
                               "are read with usersim_wait_for_verification_code / _link."})


@mcp.tool(structured_output=False)
async def usersim_signup_identity(ctx: Context, session_id: str, no_plus: bool = False, same_account_as: str = "") -> str:
    """Fresh, never-used email alias (a real inbox UserSim reads) plus password, name and username for signing up.

    Same alias for the whole session. Sign up with this email only; never Google or GitHub sign-in.
    no_plus=true: the site rejected a "+" address; returns a fresh dot-variant address of the same inbox instead
    (replaces the earlier alias for this session).
    same_account_as=<session_id of your earlier session on the same site>: log in to the account that session
    created instead of signing up again (later study cells after a signup cell). Returns that email and password;
    login codes or magic links the site mails to it can be read with the wait tools in this session.
    """
    import asyncio
    import re
    import time

    from mvp.signup_tools import new_signup

    from mvp.sim_mcp import limits as L

    try:
        owner = _owner(ctx)
        sim = S.get_session(session_id, owner)
        if same_account_as:
            return _reuse_account(sim, same_account_as, owner)
        if sim.inbox is None:
            shared = _study_account_for(sim, owner)
            if shared:
                return shared
        shared_ok = not S.is_anon(owner) or bool(L.get("anon_allow_shared_aliases"))
        if no_plus and not shared_ok:
            # A dot-variant (or plain) address can be issued again to another session, which could then read this
            # session's mail. Callers without a token only get unique +tag aliases.
            raise S.SessionError("cap anon_allow_shared_aliases: no_plus addresses are not available without a token. "
                                 "This site rejects '+' aliases, so finish with outcome 'blocked' and say so")
        if no_plus and shared_ok and not sim.row.get("login_email"):
            # also when a '+' identity was already issued: the agent asks for no_plus after the site rejected it
            known = _host_registry_account(sim)
            if known:
                return known
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
            S.save_account(sim)
            _register_study_account(sim)
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


def _reuse_account(sim: S.SimSession, prev_id: str, owner: str) -> str:
    """Give this session the account (alias + password) an earlier session of the same caller created on the same
    site. The earlier session_id is the credential (random, returned only to its creator). Mail read here is only mail
    that arrives after this call, so earlier verification mail is not replayed."""
    import time

    from mvp.sim_mcp.sessions import registrable_domain

    if prev_id == sim.id:
        raise S.SessionError("same_account_as must be an EARLIER session's id, not this one")
    try:
        prev = S.get_session(prev_id, owner)
        if prev.inbox is None or not prev.identity:
            raise S.SessionError("that session never got a signup identity, so there is no account to log in to")
        inbox, identity, host, from_id = prev.inbox, dict(prev.identity), _host(prev), prev.agent_id or prev.id[:8]
    except S.SessionError:
        # The session is gone from memory (server restarted since): use the account it saved at signup.
        saved = S.load_account(prev_id, owner)
        if not saved:
            raise
        from mvp.signup_inbox import GmailAliasInbox

        inbox = GmailAliasInbox.for_address(str(saved["address"]))
        identity, host, from_id = dict(saved.get("identity") or {}), str(saved.get("host") or ""), str(saved.get("agent_id") or prev_id[:8])
    if registrable_domain(host) != registrable_domain(_host(sim)):
        raise S.SessionError(f"that account is for {host}, not {_host(sim)}")
    if sim.inbox is not None and sim.inbox.address != inbox.address:
        raise S.SessionError("this session already has its own signup alias; start a new session to log in instead")
    sim.inbox, sim.identity = inbox, identity
    sim.mail_since = time.time() - 30
    # Not a signup: the report and proof must not ask this run for a verified fresh signup.
    sim.row["login_email"] = inbox.address
    sim.row["reused_account_from"] = from_id
    sim.row.pop("signup_email", None)
    S.save_host_account(sim)  # a dot-variant account that works is the site's one account for this inbox
    ident = {k: v for k, v in sim.identity.items() if k != "code"}
    return json.dumps({**ident, "reused_account": True,
                       "next": "Log in with this email and password (not a new signup). If the site emails a login code "
                               "or magic link, read it with usersim_wait_for_verification_code / _link in this session."})


async def _wait(ctx: Context, session_id: str, timeout_s: int, want: str) -> str:
    import asyncio
    import time

    from mvp.signup_tools import wait_mail
    from mvp.sim_mcp import limits as L

    try:
        sim = S.get_session(session_id, _owner(ctx))
        if sim.inbox is None:
            raise S.SessionError("call usersim_signup_identity and submit the signup form first")
        # Many MCP clients give a tool call 60 s (Claude Code's default MCP_TOOL_TIMEOUT); Haiku asked for 180 s and the
        # client gave up first (study e7c5d942). Each call waits at most MVP_MCP_WAIT_MAX_S; the agent calls again.
        t = max(10, min(int(timeout_s or 45), int(L.get("wait_max_s"))))
        msg = await asyncio.to_thread(wait_mail, sim.inbox, _host(sim), since=sim.mail_since, timeout_s=t, seen=sim.mail_seen, want=want)
        sim.last_used = __import__("time").time()
        if not msg:
            diag = getattr(sim.inbox, "diagnose", None)
            if diag:
                try:  # what the inbox did receive meanwhile, so a missing mail can be traced (mail to another address?)
                    seen_mail = await asyncio.to_thread(diag, sim.mail_since)
                except Exception as exc:  # noqa: BLE001
                    seen_mail = [{"error": repr(exc)[:120]}]
                dbg = sim.row.setdefault("mail_debug", [])
                if len(dbg) < 10:
                    dbg.append({"at": round(time.time()), "alias": sim.inbox.address, "waited_s": t, "want": want,
                                "inbox_since_start": seen_mail})
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
                           "next": wait_next_hint(msg.get("code"), sim.mail_links)})
    except Exception as exc:  # noqa: BLE001
        return _fail(exc)


def wait_next_hint(code: Any, links: list[str]) -> str:
    """What to do with a found mail. Oct 18 (Clockify, KanbanFlow): a code-only mail said "open link 1" (a footer
    link or no link at all), which points an agent at the wrong step."""
    if code and not links:
        return f"type the code {code} into the site's code field and submit"
    if code:
        return (f"if the page has a code field, type the code {code} and submit; only if it asks you to click the "
                "emailed link, call usersim_open_verification_link with link_number=1")
    if links:
        return "to open a link call usersim_open_verification_link with link_number=1 (first link) rather than copying its URL"
    return "this mail has no code and no link: check the page for what it expects, or call this tool again for a newer mail"


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
    """Phone number for an SMS step (only if the site insists on one). Then call usersim_wait_for_sms_code.

    The number is shared, so it is leased to one session at a time (about 10 min, or until the session ends).
    If another simulated user holds it you get busy=true and retry_after_s: wait that long and call again.
    """
    import asyncio

    from mvp.sim_mcp import limits as L
    from mvp.sim_mcp import sms_lease

    try:
        owner = _owner(ctx)
        sim = S.get_session(session_id, owner)
        _sms_allowed(owner)
        if sim.closed:
            raise S.SessionError("session is closed; call usersim_get_report")
        from mvp.sms_provider import lease_number

        number = sim.sms_number or await asyncio.to_thread(lease_number, _host(sim))
        on_new = (lambda: L.count_sms_lease(owner)) if S.is_anon(owner) else None
        lease, new = sms_lease.acquire(sim.id, owner, float(L.get("sms_lease_s")), S.SESSIONS, on_new=on_new)
        sim.sms_number = number
        sim.row["sms_since"] = lease.started
        return json.dumps({"phone": number.phone, "lease_seconds_left": int(lease.expires - __import__("time").time()),
                           "lease": "new" if new else "renewed",
                           "next": "Type this number into the site, request the code, then call usersim_wait_for_sms_code. "
                                   "Only texts that arrive after this lease started are returned."})
    except sms_lease.Busy as exc:
        return json.dumps({"error": str(exc), "busy": True, "retry_after_s": exc.retry_s})
    except L.CapExceeded as exc:
        return _cap_fail(exc)
    except Exception as exc:  # noqa: BLE001
        return _fail(RuntimeError(f"no SMS number available: {exc}"))


@mcp.tool(structured_output=False)
async def usersim_wait_for_sms_code(ctx: Context, session_id: str, timeout_s: int = 45) -> str:
    """Wait for the SMS verification code sent to the number from usersim_signup_phone.

    Only works while this session holds the number's lease, and only returns codes from texts that arrived after
    the lease started. Each call waits at most ~50 s (MCP clients often time out at 60 s); if found is false, call again.
    """
    import asyncio
    import time

    from mvp.sim_mcp import limits as L
    from mvp.sim_mcp import sms_lease

    try:
        owner = _owner(ctx)
        sim = S.get_session(session_id, owner)
        _sms_allowed(owner)
        if sim.sms_number is None:
            raise S.SessionError("call usersim_signup_phone first")
        lease = sms_lease.held_by(sim.id, S.SESSIONS)
        if lease is None:
            raise S.SessionError("this session no longer holds the SMS number (the lease expired or another session has "
                                 "it). Call usersim_signup_phone again, then request a new code on the site")
        from mvp.sms_provider import wait_for_sms

        left = lease.expires - time.time()
        t = max(5, min(int(timeout_s or 45), int(L.get("wait_max_s")), int(left)))
        code = await asyncio.to_thread(wait_for_sms, sim.sms_number, timeout_s=t, newer_than=lease.started,
                                       skip=L.sms_denied, slack_s=0.0)
        if code:
            sim.row["sms_code_received"] = True
            return json.dumps({"found": True, "code": code})
        return json.dumps({"found": False, "code": None, "lease_seconds_left": max(0, int(lease.expires - time.time())),
                           "note": f"no SMS code yet (waited {t}s). Texts can take a minute: call again, or use the "
                                   "site's resend button"})
    except Exception as exc:  # noqa: BLE001
        return _fail(exc)


@mcp.tool(structured_output=False)
async def usersim_solve_captcha(ctx: Context, session_id: str) -> list[Any] | str:
    """Try to get past a captcha on the current page (the same solver path the website driver uses).

    Checkbox, slider and press-and-hold: try once like a person. Image grids: call this instead of clicking tiles.
    It tries the free audio route, then the paid solver when the server enables it (limits.json paid_captcha). The reply
    has captcha.paid with the ledger result and whether the page accepted the token.
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
            if calls[sim.page.url] > L_get("captcha_max_calls_per_page"):
                obs = await S.record_step(sim, kind="captcha", action_text="captcha attempt (refused: repeated)",
                                          args={}, thought="I try to get past the captcha again.", error="")
                return _obs_content(sim, obs, {"captcha": {"note": "already tried too many times on this page; calling again will not "
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
            if _paid_captcha_on() and state and (not state.get("token_ready") or state.get("challenge_open")):
                # Oct 23 Smartsheet: an image grid was open while captcha_state said token_ready (a non-empty
                # g-recaptcha-response field), so the paid solve never ran and agents clicked tiles for 90+ steps.
                result["paid"] = await _paid_token_logged(sim, state.get("kind") or "", info or {}, "solve_captcha")
            await S._settle(sim.page)
            paid = result.get("paid")
            obs = await S.record_step(sim, kind="captcha", action_text="captcha attempt",
                                      args={"paid": json.loads(json.dumps(paid, default=str))} if paid else {},
                                      thought="I try to get past the captcha.", error="")
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


async def _image_challenge_guard(sim: S.SimSession) -> dict | str | None:
    """While a reCAPTCHA image grid is open: buy a paid token (once per page load, up to the session cap) instead of
    letting the agent click tiles, count the steps spent there, and tell it to finish as blocked past
    limits.json captcha_stuck_steps (refuse further actions at twice that). Returns a note dict, a refusal
    string, or None."""
    from urllib.parse import urlsplit

    from mvp import captcha_spend as cs

    try:
        open_ = await S.recaptcha_challenge_open(sim.page)
    except Exception:  # noqa: BLE001
        return None
    if not open_:
        sim.row["captcha_stuck_run"] = 0
        return None
    run = sim.row["captcha_stuck_run"] = int(sim.row.get("captcha_stuck_run") or 0) + 1
    sim.row["captcha_challenge_steps"] = int(sim.row.get("captcha_challenge_steps") or 0) + 1
    limit = L_get("captcha_stuck_steps")
    host = (urlsplit(sim.product_url).hostname or "").removeprefix("www.")
    if (_paid_captcha_on() and _paid_allowed(sim) and host in cs.paid_hosts()
            and int(sim.row.get("capsolver_tries") or 0) < L_get("paid_captcha_max_tries")
            and sim.row.get("signup_email") and run % 4 == 1):
        # at steps 1, 5, 9 ... of one open grid, so a site that ignores the token does not eat the whole cap;
        # bypasses the once-per-page-load marker: an open image grid means the earlier token did not clear it
        sim.row["capsolver_tries"] = int(sim.row.get("capsolver_tries") or 0) + 1
        from mvp import captcha as cap

        out = await _paid_token_logged(sim, "recaptcha", await cap.detect_sitekey(sim.page) or {}, "act_image_challenge")
        sim.row["captcha_last_paid"] = out
    if not limit:
        return None
    if run >= 2 * limit:
        return ("captcha_stuck: an image challenge has blocked this page for %d steps. Do not click more tiles. "
                "Call usersim_finish with outcome 'blocked' and say a CAPTCHA stopped you." % run)
    if run >= limit:
        return {"steps_on_challenge": run,
                "next": "A CAPTCHA image grid has been open for %d steps. Stop clicking tiles: call usersim_solve_captcha "
                        "once more; if it is still there, call usersim_finish with outcome 'blocked'." % run}
    return None


async def _maybe_paid_presolve(sim: S.SimSession) -> dict | None:
    """Before a click on an approved paid host, if an invisible captcha has no token yet, get one first."""
    from urllib.parse import urlsplit

    from mvp import captcha_spend as cs

    if not _paid_captcha_on() or not _paid_allowed(sim):
        return None
    host = (urlsplit(sim.product_url).hostname or "").removeprefix("www.")
    if host not in cs.paid_hosts() or int(sim.row.get("capsolver_tries") or 0) >= L_get("paid_captcha_max_tries"):
        return None
    if not sim.row.get("signup_email"):
        return None  # only once the signup form is being filled
    state = await S.captcha_state(sim.page) or {}
    if not state:
        return None
    # a token in the field is not proof it works: the site may have just said the captcha failed (expired v3 token,
    # low score). Then pay for one even though the field is filled.
    if state.get("token_ready") and not state.get("challenge_open") and not await _captcha_rejected(sim.page):
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
        out = await _paid_token_logged(sim, kind, await cap.detect_sitekey(sim.page) or {}, "presolve")
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


def _paid_captcha_on() -> bool:
    from mvp.sim_mcp import limits as L

    return bool(L.get("paid_captcha"))


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

    if not _paid_captcha_on():
        return {"ok": False, "detail": "paid captcha solver is off (limits.json paid_captcha is false)"}
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


def _allow_paid_captcha_host(sim: S.SimSession) -> None:
    """The site under test may be paid for like the website driver's study sites (captcha_spend.allow_study_host). The
    MCP never called it, so only hosts in MVP_CAPTCHA_PAID_HOSTS were solved: Oct 23 Smartsheet smoke run, ledger
    reason host_not_paid, agent clicked image tiles until the spend cap. The per-site, total and balance caps still
    apply; MVP_CAPTCHA_PAY_STUDY_SITES=0 keeps the allowlist-only behaviour."""
    from mvp import captcha_spend as cs

    try:
        cs.allow_study_host(_host(sim))
    except Exception:  # noqa: BLE001
        pass


async def _paid_token_logged(sim: S.SimSession, kind: str, info: dict, via: str) -> dict:
    """_paid_token plus a per-attempt record for full visibility: what the ledger said (solved, cost, or the reason
    it refused), and whether the page took the token (challenge closed, token in the field, rejection banner,
    new url). Stored in sim.row["captcha_paid_log"], which lands in the study JSON next to capsolver_usd."""
    import asyncio
    import time

    from mvp import captcha_spend as cs

    cs.set_max_solves_per_attempt(L_get("paid_captcha_max_solves"))
    n0 = cs.ledger_count()
    url0 = getattr(sim.page, "url", "") or ""
    t0 = time.time()
    try:
        out = await _paid_token(sim, kind, info)
    except Exception as exc:  # noqa: BLE001
        out = {"ok": False, "detail": f"exception: {exc!r}"[:200]}
    after: dict[str, Any] = {}
    if isinstance(out, dict) and out.get("ok"):
        await asyncio.sleep(4)  # let the page react to the injected token and its callbacks
        try:
            st = await S.captcha_state(sim.page) or {}
            after = {"challenge_open": bool(st.get("challenge_open")), "token_ready": bool(st.get("token_ready")),
                     "rejected_banner": await _captcha_rejected(sim.page), "url_changed": getattr(sim.page, "url", "") != url0}
            after["site_accepted"] = bool(after["url_changed"] or (not after["challenge_open"] and not after["rejected_banner"]))
        except Exception as exc:  # noqa: BLE001
            after = {"error": repr(exc)[:120]}
    entry = {"ts": round(t0), "via": via, "url": url0[:200], "kind": kind, "result": out, "after": after,
             "ledger": cs.events_since(n0), "seconds": round(time.time() - t0, 1)}
    log = sim.row.setdefault("captcha_paid_log", [])
    if len(log) < 40:
        log.append(json.loads(json.dumps(entry, default=str)))
    if isinstance(out, dict):
        out = {**out, "after": after} if after else out
    return out


def L_get(key: str) -> int:
    from mvp.sim_mcp import limits as L

    return int(L.get(key))


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

    tokens = [t for t, _r in parse_tokens(token or "")]

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
    parsed = parse_tokens(token)
    _TOKENS[:] = [t for t, _r in parsed]
    _ROLES.clear()
    _ROLES.update({t: r for t, r in parsed})
    endpoint = _require_bearer(route.endpoint, token)
    app.router.routes.insert(0, Route("/mcp", endpoint=endpoint, methods=["GET", "POST", "DELETE"]))

    async def _limits(request: Any) -> Any:
        from mvp.secrets_store import snapshot as secrets_snapshot

        return JSONResponse({**L.snapshot(), "secrets": secrets_snapshot()})

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
