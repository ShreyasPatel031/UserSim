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
  Then usersim_wait_for_verification_code or usersim_wait_for_verification_link (+ usersim_open_verification_link). Captcha in the way: solve it like a person (click the checkbox, drag the slider, press_and_hold), or call usersim_solve_captcha.
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


def _client_id(ctx: Context | None) -> str:
    try:
        req = ctx.request_context.request  # type: ignore[union-attr]
        fwd = (req.headers.get("x-forwarded-for") or "").split(",")[0].strip()
        return fwd or (req.client.host if req.client else "")
    except Exception:  # noqa: BLE001
        return ""


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
    if obs.get("alias_rejected"):
        meta["email_hint"] = "this site rejects '+' email aliases: call usersim_signup_identity with no_plus=true and use that address"
    if obs.get("captcha"):
        c = obs["captcha"]
        meta["captcha"] = {**c, "hint": "captcha token ready; submit" if c.get("token_ready") else
                           "invisible captcha: nothing to click or solve, it runs when you submit. If submitting does nothing, "
                           "look for an empty required field (filled:false) or an error message instead" if c.get("invisible") else
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
        study = S.create_matrix_study(product_url=product_url, competitors=comps, personas=personas, tasks=tasks)
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
async def usersim_finish_study(study_id: str) -> str:
    """Write the study report now from the cells that ran; cells never started are marked skipped.

    Only needed if some cells will not be run. Running cells must be finished first.
    """
    from mvp.study import STUDIES

    study = STUDIES.get(study_id)
    if study is None or getattr(study, "backend", "") != "mcp":
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
    try:
        sim = await S.start_session(
            product_url=product_url, task=task, persona=persona, client=_client_id(ctx), study_id=study_id, cell_id=cell_id
        )
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
async def usersim_observe(session_id: str) -> list[Any] | str:
    """Current screenshot, URL and title of the simulated user's browser, without acting."""
    try:
        sim = S.get_session(session_id)
        return _obs_content(sim, await S.observe(sim))
    except S.SessionError as exc:
        return _fail(exc)


@mcp.tool(structured_output=False)
async def usersim_act(session_id: str, action: dict[str, Any], thought: str) -> list[Any] | str:
    """Do ONE thing on the page, the way the persona would, and get the new screenshot.

    action (pixel coordinates in the screenshot):
      {"type":"click","x":..,"y":..} · {"type":"double_click","x":..,"y":..} · {"type":"triple_click","x":..,"y":..} (select a field's text) · {"type":"right_click","x":..,"y":..}
      {"type":"hover","x":..,"y":..} · {"type":"type","text":"...","x":..,"y":..,"submit":false} (clicks the field at x,y, clears it, types; omit x,y to type into the focused field)
    Each observation lists visible `fields` (kind, label, exact x,y, filled/checked): use those coordinates for form fields.
      {"type":"key","keys":"Enter"|"Tab"|"Escape"|"Control+A"} · {"type":"scroll","dy":600,"x":..,"y":..} (dy>0 = down)
      {"type":"back"} · {"type":"reload"} · {"type":"wait","ms":1000} · {"type":"navigate","url":"..."} (same site only)
      {"type":"select","x":..,"y":..,"option":"visible option text"} (dropdowns, native or custom; native popups never appear in screenshots, so pick from the `options` listed for that field in `fields`)
      {"type":"press_and_hold","x":..,"y":..,"ms":4000} (press-and-hold human checks)
      {"type":"drag","x":..,"y":..,"to_x":..,"to_y":..} (slider / puzzle captchas)
    Google / GitHub sign-in is blocked: always use the email signup.
    thought: first-person, what you see / expect / find confusing. Recorded as research data.
    """
    try:
        sim = S.get_session(session_id)
        extra = None
        if str((action or {}).get("type")) in {"click", "key"}:
            extra = await _maybe_paid_presolve(sim)
        obs = await S.act(sim, action, thought)
        return _obs_content(sim, obs, {"captcha_presolve": extra} if extra else None)
    except S.SessionError as exc:
        return _fail(exc)


@mcp.tool(structured_output=False)
async def usersim_finish(session_id: str, outcome: str, notes: str) -> str:
    """End the simulated user's session. outcome: completed | gave_up | blocked.

    notes: what was easy, what was hard, where the persona got confused, why they stopped.
    UserSim then closes the browser, runs its own judge and proof checks. Call usersim_get_report next.
    """
    try:
        sim = S.get_session(session_id)
    except S.SessionError as exc:
        return _fail(exc)
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
async def usersim_get_report(study_id: str, format: str = "markdown") -> str:
    """The study report: independent judge verdict, proof checks, friction, every step with screenshot links.

    format: "markdown" (default) or "json".
    """
    from mvp.study import STUDIES, load_local_study, load_study_from_gcs, study_to_dict

    live = STUDIES.get(study_id)
    data = study_to_dict(live) if live is not None else (load_local_study(study_id) or load_study_from_gcs(study_id))
    if not data:
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
async def usersim_signup_identity(session_id: str, no_plus: bool = False) -> str:
    """Fresh, never-used email alias (a real inbox UserSim reads) plus password, name and username for signing up.

    Same alias for the whole session. Sign up with this email only; never Google or GitHub sign-in.
    no_plus=true: the site rejected a "+" address; returns a fresh dot-variant address of the same inbox instead
    (replaces the earlier alias for this session).
    """
    import asyncio
    import re
    import time

    from mvp.signup_tools import new_signup

    try:
        sim = S.get_session(session_id)
        if no_plus and sim.inbox is not None and "+" in sim.inbox.address:
            sim.inbox = None
        if sim.inbox is None:
            tag = re.sub(r"[^a-z0-9]", "", _host(sim).split(".")[0])[:10] or "site"
            sim.inbox, sim.identity = await asyncio.to_thread(new_signup, _host(sim), tag, None, dotted=bool(no_plus))
            sim.mail_since = time.time() - 30
            sim.row["signup_email"] = sim.inbox.address
        ident = {k: v for k, v in sim.identity.items() if k != "code"}
        return json.dumps({**ident, "next": "Type these into the signup form, submit, then wait for the verification mail."})
    except Exception as exc:  # noqa: BLE001
        return _fail(exc)


async def _wait(session_id: str, timeout_s: int, want: str) -> str:
    import asyncio

    from mvp.signup_tools import wait_mail

    try:
        sim = S.get_session(session_id)
        if sim.inbox is None:
            raise S.SessionError("call usersim_signup_identity and submit the signup form first")
        t = max(10, min(int(timeout_s or 120), 240))
        msg = await asyncio.to_thread(wait_mail, sim.inbox, _host(sim), since=sim.mail_since, timeout_s=t, seen=sim.mail_seen, want=want)
        sim.last_used = __import__("time").time()
        if not msg:
            return json.dumps({"found": False, "note": f"no verification mail with a {want} in {t}s; check the form was submitted, or resend"})
        sim.mail_links = list(msg.get("links") or [])
        if msg.get("code"):
            sim.row["signup_code_used"] = True
        sim.row.setdefault("signup_mail", []).append({"subject": msg.get("subject"), "sender": msg.get("sender")})
        return json.dumps({"found": True, "subject": msg.get("subject"), "sender": msg.get("sender"),
                           "code": msg.get("code"), "links": sim.mail_links[:5], "link_texts": (msg.get("link_texts") or [])[:5]})
    except Exception as exc:  # noqa: BLE001
        return _fail(exc)


@mcp.tool(structured_output=False)
async def usersim_wait_for_verification_code(session_id: str, timeout_s: int = 120) -> str:
    """Wait for the signup email for this session's alias and return the verification code in it."""
    return await _wait(session_id, timeout_s, "code")


@mcp.tool(structured_output=False)
async def usersim_wait_for_verification_link(session_id: str, timeout_s: int = 120) -> str:
    """Wait for the signup email for this session's alias and return its verification links (best first)."""
    return await _wait(session_id, timeout_s, "link")


@mcp.tool(structured_output=False)
async def usersim_open_verification_link(session_id: str, url: str, thought: str = "I click the link in the email.") -> list[Any] | str:
    """Open a link returned by usersim_wait_for_verification_link in the browser (like clicking it in the email)."""
    try:
        sim = S.get_session(session_id)
        if url not in sim.mail_links:
            raise S.SessionError("only links returned by usersim_wait_for_verification_link can be opened")
        opened = sim.row.setdefault("opened_links", [])
        if url in opened:
            raise S.SessionError("this link was already opened; continue on the page (it is the current page)")
        opened.append(url)
        async with sim.lock:
            S._check_open(sim)
            err = ""
            try:
                await sim.page.goto(url, wait_until="domcontentloaded", timeout=30000)
            except Exception as exc:  # noqa: BLE001
                err = str(exc).splitlines()[0][:200]
            await S._settle(sim.page)
            obs = await S.record_step(sim, kind="navigate", action_text="open verification link from email",
                                      args={"url": url[:200]}, thought=thought, error=err)
        return _obs_content(sim, obs)
    except Exception as exc:  # noqa: BLE001
        return _fail(exc)


@mcp.tool(structured_output=False)
async def usersim_signup_phone(session_id: str) -> str:
    """Phone number for an SMS step (only if the site insists on one). Then call usersim_wait_for_sms_code."""
    import asyncio
    import time

    try:
        sim = S.get_session(session_id)
        from mvp.sms_provider import lease_number

        sim.sms_number = await asyncio.to_thread(lease_number, _host(sim))
        sim.row["sms_since"] = time.time()
        return json.dumps({"phone": sim.sms_number.phone})
    except Exception as exc:  # noqa: BLE001
        return _fail(RuntimeError(f"no SMS number available: {exc}"))


@mcp.tool(structured_output=False)
async def usersim_wait_for_sms_code(session_id: str, timeout_s: int = 90) -> str:
    """Wait for the SMS verification code sent to the number from usersim_signup_phone."""
    import asyncio

    try:
        sim = S.get_session(session_id)
        if sim.sms_number is None:
            raise S.SessionError("call usersim_signup_phone first")
        from mvp.sms_provider import wait_for_sms

        code = await asyncio.to_thread(wait_for_sms, sim.sms_number, timeout_s=max(15, min(int(timeout_s), 180)),
                                       newer_than=sim.row.get("sms_since"))
        return json.dumps({"found": bool(code), "code": code})
    except Exception as exc:  # noqa: BLE001
        return _fail(exc)


@mcp.tool(structured_output=False)
async def usersim_solve_captcha(session_id: str) -> list[Any] | str:
    """Try to get past a captcha on the current page (the same solver path the website driver uses).

    Prefer solving it yourself first like a person (checkbox click, drag, press_and_hold). This tries the free
    audio route for reCAPTCHA; a paid solver only runs when the server enables it (MVP_MCP_PAID_CAPTCHA=1).
    """
    import os

    try:
        sim = S.get_session(session_id)
        from mvp import captcha as cap

        async with sim.lock:
            S._check_open(sim)
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
            state = await S.captcha_state(sim.page) or {}
            if state.get("invisible") and not state.get("token_ready"):
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
    if (window.grecaptcha) {
      const g = window.grecaptcha;
      g.execute = () => Promise.resolve(token);
      if (g.enterprise) g.enterprise.execute = () => Promise.resolve(token);
      g.getResponse = () => token;
    }
  }
  return true;
}"""

_SITEKEY_JS = """(kind) => {
  const html = document.documentElement.outerHTML;
  if (kind === 'turnstile') {
    const el = document.querySelector('[data-sitekey]'); if (el) return el.getAttribute('data-sitekey');
    const m = html.match(/0x4[A-Za-z0-9_-]{18,}/); return m ? m[0] : '';
  }
  const s = [...document.scripts].map(x => x.src).find(u => /recaptcha.*render=/.test(u));
  if (s) { const k = new URL(s).searchParams.get('render'); if (k && k !== 'explicit') return k; }
  const f = [...document.querySelectorAll('iframe')].map(i => i.src).find(u => u.includes('/recaptcha/'));
  if (f) { const k = new URL(f).searchParams.get('k'); if (k) return k; }
  const m = html.match(/6L[A-Za-z0-9_-]{38}/); return m ? m[0] : '';
}"""


async def _maybe_paid_presolve(sim: S.SimSession) -> dict | None:
    """Before a click on an approved paid host, if an invisible captcha has no token yet, get one first."""
    from urllib.parse import urlsplit

    from mvp import captcha_spend as cs

    if os.environ.get("MVP_MCP_PAID_CAPTCHA") != "1":
        return None
    host = (urlsplit(sim.product_url).hostname or "").removeprefix("www.")
    if host not in cs.paid_hosts() or int(sim.row.get("capsolver_tries") or 0) >= 2:
        return None
    if not sim.row.get("signup_email"):
        return None  # only once the signup form is being filled
    state = await S.captcha_state(sim.page) or {}
    if not state or state.get("token_ready"):
        return None
    sim.row["capsolver_tries"] = int(sim.row.get("capsolver_tries") or 0) + 1
    from mvp import captcha as cap

    try:
        return await _paid_token(sim, state.get("kind") or "", await cap.detect_sitekey(sim.page) or {})
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "detail": repr(exc)[:200]}


async def _paid_token(sim: S.SimSession, kind: str, info: dict) -> dict:
    """Approved paid path (MVP_MCP_PAID_CAPTCHA=1): one CapSolver token through the metered ledger, injected
    the way the site's own widget would deliver it. Spend caps live in mvp.captcha_spend."""
    import asyncio
    from urllib.parse import urlsplit

    from mvp import captcha as cap
    from mvp import captcha_spend as cs

    host = (urlsplit(sim.product_url).hostname or "").removeprefix("www.")
    if not sim.row.get("capsolver_attempt"):
        sim.row["capsolver_attempt"] = cs.begin_inrun_attempt(host)
    cs.bind_signup(host, sim.row["capsolver_attempt"])
    sitekey = info.get("sitekey") or await sim.page.evaluate(_SITEKEY_JS, kind)
    if kind == "turnstile":
        ctype = "turnstile"
    else:  # invisible / score reCAPTCHA defaults to v3; a visible v2 widget keeps its detected type
        ctype = str(info.get("type") or "") if "v2" in str(info.get("type") or "") else (os.environ.get("MVP_MCP_RECAPTCHA_KIND") or "recaptcha_v3")
    if not sitekey:
        return {"ok": False, "detail": "no sitekey found"}
    before = cs.spent_usd()
    token = await asyncio.to_thread(cap.solve_sitekey, sitekey=sitekey, page_url=sim.page.url, captcha_type=ctype,
                                    action=os.environ.get("MVP_MCP_RECAPTCHA_ACTION") or None, timeout_s=120, blocking=True)
    cost = round(cs.spent_usd() - before, 5)
    sim.row["capsolver_usd"] = round(float(sim.row.get("capsolver_usd") or 0) + cost, 5)
    if not token:
        return {"ok": False, "type": ctype, "cost_usd": cost, "detail": "solver returned no token (see ledger)"}
    await sim.page.evaluate(_PAID_JS, [kind, token])
    return {"ok": True, "type": ctype, "cost_usd": cost, "detail": "token injected; submit the form now"}


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
    """Bearer token clients must send on /mcp. MVP_MCP_TOKEN, or the file at MVP_MCP_TOKEN_FILE. Empty = open."""
    tok = (os.environ.get("MVP_MCP_TOKEN") or "").strip()
    path = (os.environ.get("MVP_MCP_TOKEN_FILE") or "").strip()
    if not tok and path:
        try:
            with open(path) as fh:
                tok = fh.read().strip()
        except OSError:
            raise RuntimeError(f"MVP_MCP_TOKEN_FILE set but unreadable: {path}") from None
    return tok


def _require_bearer(endpoint: Any, token: str) -> Any:
    """ASGI wrapper: 401 unless 'Authorization: Bearer <token>' matches (constant-time)."""
    import hmac

    from starlette.responses import JSONResponse

    class Guarded:  # a class instance, so Starlette's Route treats it as a raw ASGI app
        async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
            await guarded(scope, receive, send)

    async def guarded(scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") == "http":
            headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers") or []}
            got = headers.get("authorization", "")
            if not (got.startswith("Bearer ") and hmac.compare_digest(got[7:].strip(), token)):
                await JSONResponse({"error": "missing or wrong bearer token"}, status_code=401,
                                   headers={"WWW-Authenticate": "Bearer"})(scope, receive, send)
                return
        await endpoint(scope, receive, send)

    return Guarded()


def mount(app: Any) -> None:
    """Serve POST/GET /mcp from the FastAPI app and run the MCP session manager with it."""
    from starlette.routing import Route

    inner = mcp.streamable_http_app()
    route = next(r for r in inner.routes if getattr(r, "path", "") == "/mcp")
    endpoint = route.endpoint
    token = _client_token()
    if token:
        endpoint = _require_bearer(endpoint, token)
    app.router.routes.insert(0, Route("/mcp", endpoint=endpoint, methods=["GET", "POST", "DELETE"]))

    @app.on_event("startup")
    async def _start_mcp() -> None:
        global _STACK
        _STACK = AsyncExitStack()
        await _STACK.enter_async_context(mcp.session_manager.run())

    @app.on_event("shutdown")
    async def _stop_mcp() -> None:
        if _STACK is not None:
            await _STACK.aclose()
