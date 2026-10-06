"""The UserSim MCP endpoint (streamable HTTP at /mcp on the UserSim server).

The coding agent is the simulated user. Every tool here is served by the same
process that runs the website, so the prompt, action set, judge, proof checks
and report can't drift between clients.
"""

from __future__ import annotations

import json
from contextlib import AsyncExitStack
from typing import Any

from mcp.server.fastmcp import Context, FastMCP, Image
from mcp.server.transport_security import TransportSecuritySettings

from mvp.sim_mcp import sessions as S
from mvp.sim_mcp.report import build_report, finalize, report_markdown, watch_url

DEFAULT_DRIVER_MODEL = "haiku"

INSTRUCTIONS = f"""UserSim lets you act as a simulated user of a real web product, in a real cloud browser that UserSim runs and records.

Flow:
1. Get a PUBLIC product URL from the human (localhost won't work; a preview/staging deploy is fine). That is the only thing they must provide.
2. Draft a realistic persona (one or two sentences: who they are, what they know, why they are here) and ONE task, using the codebase / recent changes if helpful. Show both to the human and wait for approval.
3. Call usersim_start_session. Open the returned watch_url for the human (e.g. `open <url>` on macOS, `xdg-open <url>` on Linux) so they can watch the browser live.
4. Run the simulated user as a subagent with model "{DEFAULT_DRIVER_MODEL}" unless the human asked for another model. Give it the session_id, persona, task and the usersim_simulate_user prompt. It loops usersim_act until done, then calls usersim_finish.
5. Call usersim_get_report and summarise it for the human. The judge verdict and proof checks come from UserSim, not from the simulated user.
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
    if obs.get("error"):
        meta["action_error"] = obs["error"]
    if extra:
        meta.update(extra)
    return [json.dumps(meta), Image(data=S.jpeg(obs["png"]), format="jpeg")]


def _fail(exc: Exception) -> str:
    return json.dumps({"error": str(exc)})


@mcp.tool(structured_output=False)
async def usersim_start_session(product_url: str, task: str, persona: str, ctx: Context) -> list[Any] | str:
    """Open a real cloud browser on the product and start one simulated user.

    product_url: public URL (preview/staging deploys are fine; localhost is not reachable).
    task: one goal the persona is trying to achieve, in their words.
    persona: one or two sentences — who they are, what they know, why they're here.
    Ask the human to approve the persona and task before calling this.
    Returns session_id, watch_url (open it for the human), the rules, and the first screenshot.
    """
    try:
        sim = await S.start_session(product_url=product_url, task=task, persona=persona, client=_client_id(ctx))
    except S.SessionError as exc:
        return _fail(exc)
    except Exception as exc:  # noqa: BLE001
        return _fail(RuntimeError(f"could not open the browser: {exc}"))
    obs = await S.observe(sim)
    return _obs_content(
        sim,
        obs,
        {
            "study_id": sim.study.id,
            "watch_url": watch_url(sim.study.id),
            "rules": sim.rules(),
            "driver_model": DEFAULT_DRIVER_MODEL,
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
      {"type":"click","x":..,"y":..} · {"type":"double_click","x":..,"y":..} · {"type":"right_click","x":..,"y":..}
      {"type":"hover","x":..,"y":..} · {"type":"type","text":"...","submit":false} (types into the focused field; click it first)
      {"type":"key","keys":"Enter"|"Tab"|"Escape"|"Control+A"} · {"type":"scroll","dy":600,"x":..,"y":..} (dy>0 = down)
      {"type":"back"} · {"type":"wait","ms":1000} · {"type":"navigate","url":"..."} (same site only)
    thought: first-person, what you see / expect / find confusing. Recorded as research data.
    """
    try:
        sim = S.get_session(session_id)
        obs = await S.act(sim, action, thought)
        return _obs_content(sim, obs)
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
    rep = build_report(data)
    if data.get("status") != "complete":
        rep["note"] = "Study is not finished yet; call usersim_finish first."
    return json.dumps(rep, indent=1) if format == "json" else report_markdown(rep)


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


def mount(app: Any) -> None:
    """Serve POST/GET /mcp from the FastAPI app and run the MCP session manager with it."""
    from starlette.routing import Route

    inner = mcp.streamable_http_app()
    route = next(r for r in inner.routes if getattr(r, "path", "") == "/mcp")
    app.router.routes.insert(0, Route("/mcp", endpoint=route.endpoint, methods=["GET", "POST", "DELETE"]))

    @app.on_event("startup")
    async def _start_mcp() -> None:
        global _STACK
        _STACK = AsyncExitStack()
        await _STACK.enter_async_context(mcp.session_manager.run())

    @app.on_event("shutdown")
    async def _stop_mcp() -> None:
        if _STACK is not None:
            await _STACK.aclose()
