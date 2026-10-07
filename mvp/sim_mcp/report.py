"""Judge, proof checks, and the report an MCP run hands back to the coding agent.

The judge and the proof read only what the server recorded (screenshots, URLs,
page text, executed actions). The driver's own "I finished" is shown next to
the verdict, never used as the verdict.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

from mvp.paths import MVP_RUNS_DIR
from mvp.sim_mcp.sessions import AGENT_ID, DRIVER, SimSession, close

OUTCOMES = ("completed", "gave_up", "blocked", "abandoned")


def _public_base() -> str:
    return (os.environ.get("MVP_PUBLIC_BASE_URL") or "https://usersim.vercel.app").rstrip("/")


def watch_url(study_id: str) -> str:
    return f"{_public_base()}/?study={study_id}"


def report_url(study_id: str) -> str:
    return f"{_public_base()}/report?study={study_id}"


# ---------------------------------------------------------------- judge


def signup_evidence(row: dict[str, Any]) -> str:
    """Server-observed signup facts for the judge and proof (inbox reads, links opened, URL path)."""
    lines = []
    if row.get("signup_email"):
        lines.append(f"- Fresh signup alias issued by the server: {row['signup_email']}")
    for m in row.get("signup_mail") or []:
        lines.append(f"- Verification email received at that alias: subject {m.get('subject')!r} from {m.get('sender')!r}")
    trace = row.get("trace") or []

    for u in row.get("opened_links") or []:
        if _opened_verifies(row, u):
            lines.append("- The verification link from that email was opened in the browser, so the email address is verified")
        else:
            lines.append(f"- A NON-verification link (help / welcome / tracking) from that email was opened: {u.split('?')[0][:80]}")
    if row.get("opened_links") is None and any("verification link" in str(t.get("action") or t.get("action_text") or "") for t in trace):
        lines.append("- The verification link from that email was opened in the browser")
    if row.get("signup_code_used"):
        lines.append("- The verification code from that email was handed to the agent to enter")
    urls = []
    for t in trace:
        u = str(t.get("url") or "")
        if u and (not urls or urls[-1] != u):
            urls.append(u.split("?")[0])
    if urls:
        lines.append("- URL path of the run (query strings removed): " + " -> ".join(urls[-8:]))
    return "\n".join(lines)


_SIGNUP_TASK_RE = __import__("re").compile(
    r"sign ?up|create (?:a |an |your |a new )?(?:new )?account|register|registration|verify your email", __import__("re").I)


def is_signup_goal(row: dict[str, Any]) -> bool:
    """The run was a signup: the server issued a signup alias, or the task asks for an account."""
    if row.get("signup_email"):
        return True
    task = str(row.get("task_prompt") or "")
    if __import__("re").search(r"without (?:creating|signing|making|registering|an account|a signup|sign)", task, __import__("re").I):
        return False
    return bool(_SIGNUP_TASK_RE.search(task))


def frame_unrendered(png: bytes) -> bool:
    """Nothing usable painted: a flat frame, or a blank page with only a spinner / one short line.

    Measures the share of pixels that differ from the dominant colour. A leftover dim modal backdrop
    over real content keeps that share well above the bar (Litlyx: 0.5-1.3%); a white page with a
    spinner does not (FormBold: 0.02-0.03%). Size-independent (frames are compared at 1280x800).
    """
    import io

    from PIL import Image

    try:
        im = Image.open(io.BytesIO(png)).convert("L")
    except Exception:  # noqa: BLE001
        return True
    if im.size != (1280, 800):
        im = im.resize((1280, 800))
    hist = im.histogram()
    mode = max(range(256), key=lambda i: hist[i])
    off = sum(c for v, c in enumerate(hist) if abs(v - mode) >= 4)
    return off / (1280 * 800) < 0.0015


def _opened_verifies(row: dict[str, Any], url: str) -> bool:
    from mvp.signup_inbox import verification_link

    return verification_link(url, (row.get("opened_link_texts") or {}).get(url, ""),
                             chain=(row.get("opened_link_chains") or {}).get(url))


def signup_verified(row: dict[str, Any]) -> bool:
    trace = row.get("trace") or []
    mail = bool(row.get("signup_mail"))

    links = row.get("opened_links")
    if links is None:  # older rows: fall back to the trace
        opened = any("verification link" in str(t.get("action") or t.get("action_text") or "") for t in trace)
    else:  # the opened link has to verify: its URL, its anchor text in the mail, or its redirect chain
        opened = any(_opened_verifies(row, u) for u in links)
    typed_code = bool(row.get("signup_code_used"))
    return bool(row.get("signup_email")) and mail and (opened or typed_code)


async def judge_run(study_id: str, row: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """(verdict, status). status is 'ok', 'no_screenshot', or 'error: …' — never a silent pass."""
    from mvp.e2e2_gates import coerce_verdict, judge_goal_screenshot, judge_signed_in

    path = MVP_RUNS_DIR / study_id / str(row.get("agent_id") or AGENT_ID) / "screenshots" / "final.png"
    if not path.is_file():
        return coerce_verdict({"goal_reached": False, "reason": "no final screenshot"}), "no_screenshot"
    try:
        raw = await asyncio.wait_for(
            asyncio.to_thread(
                judge_goal_screenshot,
                path.read_bytes(),
                task=str(row.get("task_prompt") or ""),
                start_url=str(row.get("site_url") or ""),
                final_url=str(row.get("final_url") or ""),
                dom=str(row.get("final_dom") or ""),
                evidence=signup_evidence(row),
            ),
            timeout=float(os.environ.get("MVP_PAGE_VERDICT_TIMEOUT_S", "45")),
        )
    except Exception as exc:  # noqa: BLE001
        reason = f"judge failed: {exc!r}"[:200]
        verdict = coerce_verdict({"goal_reached": False, "reason": reason})
        verdict["unverified"] = True
        return verdict, f"error: {reason}"
    png = path.read_bytes()
    if (isinstance(raw, dict) and not raw.get("goal_reached") and not raw.get("signed_in_app_page")
            and not raw.get("page_loading") and not frame_unrendered(png)
            and is_signup_goal(row) and signup_verified(row)):
        # The goal judge ties signed_in_app_page to the task wording; ask the signed-in question on its own.
        try:
            second = await asyncio.wait_for(
                asyncio.to_thread(judge_signed_in, png, final_url=str(row.get("final_url") or ""),
                                  account_email=str(row.get("signup_email") or "")),
                timeout=float(os.environ.get("MVP_PAGE_VERDICT_TIMEOUT_S", "45")),
            )
        except Exception as exc:  # noqa: BLE001
            second = {"signed_in": False, "evidence": f"second look failed: {exc!r}"[:120]}
        raw = dict(raw, signed_in_app_page=bool(second.get("signed_in")))
        raw["signed_in_check"] = second
    verdict = apply_hard_rules(row, coerce_verdict(raw), raw, png)
    if isinstance(raw, dict) and raw.get("signed_in_check"):
        verdict["signed_in_check"] = raw["signed_in_check"]
    verdict["checked_at_ts"] = time.time()
    return verdict, "ok"


def apply_hard_rules(row: dict[str, Any], verdict: dict[str, Any], raw: Any, png: bytes) -> dict[str, Any]:
    """Server-side rules the vision judge cannot overrule.

    1. A final page that is blank, loading or only a spinner never reaches a goal.
    2. A signup goal never passes unless signup_verified (the verify mail's link/code was really used).
    3. Otherwise a signed-in app page after a verified signup counts (the judge is often too literal).
    """
    signed_in = isinstance(raw, dict) and bool(raw.get("signed_in_app_page"))
    loading = isinstance(raw, dict) and bool(raw.get("page_loading"))
    verdict["signed_in_app_page"] = signed_in
    signup = is_signup_goal(row)
    verified = signup and signup_verified(row)
    unrendered = frame_unrendered(png)
    if unrendered or loading:
        verdict["page_unrendered"] = True
        if verdict.get("goal_reached"):
            verdict["goal_reached"] = False
            verdict["reason"] = ("Final page is blank / still loading (spinner), so the goal is not shown. Judge note: "
                                 + str(verdict.get("reason") or ""))
        return verdict
    if signup and not verified:
        if verdict.get("goal_reached"):
            verdict["goal_reached"] = False
            verdict["reason"] = ("Signup not email-verified: the server never saw the verification link or code used. "
                                 "Judge note: " + str(verdict.get("reason") or ""))
        verdict["signup_verified"] = False
        return verdict
    if signup:
        verdict["signup_verified"] = True
    if not verdict.get("goal_reached") and signed_in and verified:
        verdict["goal_reached"] = True
        verdict["reason"] = "Signed-in app page after server-observed email verification. Judge note: " + str(verdict.get("reason") or "")
    return verdict


# ---------------------------------------------------------------- proof


def _shot_ok(study_id: str, agent_id: str, step: dict[str, Any]) -> bool:
    from mvp.opening_shot import png_bytes_ok

    name = str(step.get("screenshot_url") or "").rsplit("/", 1)[-1]
    if not name:
        return False
    path = MVP_RUNS_DIR / study_id / agent_id / "screenshots" / name
    try:
        raw = path.read_bytes()
    except OSError:
        return False
    return png_bytes_ok(raw) and not frame_unrendered(raw)


def _same_registrable(row: dict[str, Any]) -> bool:
    """talk.example.com redirecting to example.com is still the assigned product."""
    from urllib.parse import urlsplit

    from mvp.e2e2_gates import opened_url_of
    from mvp.sim_mcp.sessions import registrable_domain

    a = urlsplit(str(row.get("site_url") or "")).hostname or ""
    b = urlsplit(str(opened_url_of(row) or "")).hostname or ""
    return bool(a and b) and registrable_domain(a) == registrable_domain(b)


def proof_checks(study: dict[str, Any], row: dict[str, Any], judge_status: str) -> dict[str, Any]:
    """Did a real browser on the real product do real actions that a person could watch?

    Same gate functions the website's e2e2 harness uses, sized for one agent.
    """
    from mvp.e2e2_gates import beyond_first_screen, has_click_type_scroll, opened_on_assigned_site

    steps = [s for s in row.get("trace") or [] if isinstance(s, dict) and isinstance(s.get("step"), int)]
    aid = str(row.get("agent_id") or AGENT_ID)
    bad_shots = [s["step"] for s in steps if not _shot_ok(str(study.get("id")), aid, s)]
    site = row.get("site_url")
    checks = [
        ("opened_on_product", opened_on_assigned_site(row) or _same_registrable(row),
         f"opened {row.get('page_url') or '?'} for {site}", f"opened {row.get('page_url') or '?'}, which is NOT the product {site}"),
        ("real_action", has_click_type_scroll(row), "at least one click, type, or scroll ran on the page",
         "no click, type, or scroll ever ran on the page"),
        ("screenshots_real", bool(steps) and not bad_shots, f"{len(steps)} steps, every screenshot shows a rendered page",
         f"{len(steps)} steps; blank, spinner-only or missing screenshots at steps {bad_shots or 'all (no steps)'}"),
        ("beyond_first_screen", beyond_first_screen(row, str(site or "")), "URL or page content changed from the opening page",
         "URL and page content never changed from the opening page"),
        ("live_view_offered", bool(row.get("live_view_url")), "Browserbase live view was available to watch",
         "no Browserbase live view URL was recorded"),
        ("judge_ran", judge_status == "ok", "independent judge ran: ok", f"independent judge did not run cleanly: {judge_status}"),
        ("not_degraded", not study.get("test_mode") and study.get("driver") == DRIVER, "real browser run, not snapshot / test mode",
         f"degraded run (test_mode={bool(study.get('test_mode'))}, driver={study.get('driver')!r})"),
    ]
    if row.get("signup_email") or is_signup_goal(row):
        checks.append(("signup_verified", signup_verified(row),
                       "server saw the verification email for the fresh alias and its verify link/code was used",
                       "NOT verified: no verification email was seen, or no verify link/code from it was used"))
    out = [{"name": n, "pass": bool(ok), "detail": dp if ok else df} for n, ok, dp, df in checks]
    return {"pass": all(c["pass"] for c in out), "checks": out}


# ---------------------------------------------------------------- finalize


async def finalize(sim: SimSession, *, outcome: str, notes: str) -> dict[str, Any]:
    """Close the browser, judge, run proof, write the study as complete. Caller holds sim.lock."""
    from mvp.study import finish_clocks, log_activity, persist_study, study_to_dict

    if sim.closed and (sim.study.status in {"complete", "error"} or (sim.matrix and sim.row.get("status") in {"complete", "error"})):
        return study_to_dict(sim.study)
    outcome = outcome if outcome in OUTCOMES else "gave_up"
    study = sim.study
    study.phase = "Judging the run"
    try:
        from mvp.sim_mcp.sessions import settle_final

        await settle_final(sim)
    except Exception:  # noqa: BLE001
        pass
    await close(sim, reason=f"finished: {outcome}")
    row = sim.row
    row["status"] = "complete"
    row["driver_outcome"] = outcome
    row["driver_notes"] = (notes or "").strip()[:4000]
    verdict, judge_status = await judge_run(study.id, row)
    row["page_verdict"] = verdict
    result = {
        k: row.get(k)
        for k in (
            "agent_id", "persona_id", "persona_name", "persona_bio", "task_id", "task_title", "task_prompt",
            "site_key", "site_url", "site_label", "num_steps", "final_url", "final_dom",
            "final_screenshot_url", "phase_ms", "first_action_at_ts",
        )
    }
    result.update(
        {
            "mode": "mcp",
            "driver": DRIVER,
            "status": "complete",
            "agent_claimed_done": outcome == "completed",
            "driver_outcome": outcome,
            "page_verdict": verdict,
            "completed": bool(verdict.get("goal_reached")),
            "feedback": row["driver_notes"],
            "trace": row.get("trace") or [],
        }
    )
    if sim.matrix:
        payload = study_to_dict(study)
        proof = proof_checks(payload, row, judge_status)
        result["mcp_proof"] = proof
        result["judge_status"] = judge_status
        row["mcp_proof"] = proof
        study.agent_results = [r for r in study.agent_results if r.get("agent_id") != sim.agent_id] + [result]
        from mvp.sim_mcp.sessions import matrix_phase

        study.phase = matrix_phase(study)
        log_activity(study, "agents", f"{row.get('persona_name')} on {row.get('site_label')}: {outcome}; judge {judge_status}; proof pass={proof['pass']}", agent_id=sim.agent_id)
        await maybe_finish_study(study)
        return study_to_dict(study)
    study.agent_results = [result]
    payload = study_to_dict(study)
    proof = proof_checks(payload, row, judge_status)
    study.summary = {
        "headline": _headline(verdict, outcome, proof),
        "driver": DRIVER,
        "proof": proof,
        "judge_status": judge_status,
    }
    study.status = "complete"
    study.phase = "Complete"
    log_activity(study, "complete", f"MCP run finished ({outcome}); judge: {judge_status}; proof pass={proof['pass']}")
    finish_clocks(study)
    await asyncio.to_thread(persist_study, study)
    return study_to_dict(study)


def _headline(verdict: dict[str, Any], outcome: str, proof: dict[str, Any]) -> str:
    if not proof["pass"]:
        failed = ", ".join(c["name"] for c in proof["checks"] if not c["pass"])
        return f"Run did not pass proof checks ({failed}); treat findings as unverified."
    if verdict.get("goal_reached"):
        return "The simulated user reached the goal."
    return f"The simulated user did not reach the goal ({outcome.replace('_', ' ')})."


# ---------------------------------------------------------------- report


def build_report(study: dict[str, Any]) -> dict[str, Any]:
    """Structured report for the coding agent, from a saved study."""
    sid = str(study.get("id") or "")
    results = [r for r in study.get("agent_results") or [] if isinstance(r, dict)]
    sessions = [s for s in study.get("live_sessions") or [] if isinstance(s, dict)]
    run = results[0] if results else (sessions[0] if sessions else {})
    summary = study.get("summary") or {}
    verdict = run.get("page_verdict") or {}
    base = _public_base()
    steps = []
    for s in run.get("trace") or []:
        if not isinstance(s, dict) or not isinstance(s.get("step"), int):
            continue
        shot = str(s.get("screenshot_url") or "")
        steps.append(
            {
                "step": s["step"],
                "action": s.get("action"),
                "thought": s.get("thought") or "",
                "url": s.get("url"),
                "error": s.get("error") or "",
                "screenshot": f"{base}{shot}" if shot.startswith("/") else shot,
            }
        )
    friction = [
        {"step": s["step"], "what": s["thought"] or s["error"], "url": s["url"], "screenshot": s["screenshot"]}
        for s in steps
        if s["error"]
        or any(w in s["thought"].lower() for w in ("confus", "can't", "cannot", "unclear", "stuck", "where is", "not sure", "frustrat", "expected", "error"))
    ]
    return {
        "study_id": sid,
        "status": study.get("status"),
        "headline": summary.get("headline") or study.get("phase"),
        "product_url": study.get("url"),
        "persona": run.get("persona_bio") or study.get("segment"),
        "task": run.get("task_prompt"),
        "judge": {
            "goal_reached": bool(verdict.get("goal_reached")),
            "reason": verdict.get("reason") or "",
            "unverified": bool(verdict.get("unverified")) or summary.get("judge_status", "ok") != "ok",
        },
        "driver_claim": {"outcome": run.get("driver_outcome"), "notes": run.get("feedback") or run.get("driver_notes") or ""},
        "proof": summary.get("proof") or {"pass": False, "checks": [], "note": "not finished"},
        "num_steps": len(steps),
        "steps": steps,
        "friction": friction,
        "links": {"watch": watch_url(sid), "report": report_url(sid)},
        "engine_version": study.get("engine_version"),
        "config_hash": study.get("config_hash"),
        "total_time_s": study.get("total_time_s"),
    }


def report_markdown(rep: dict[str, Any]) -> str:
    j, proof = rep["judge"], rep["proof"]
    lines = [
        f"# UserSim report — {rep.get('product_url')}",
        "",
        f"**{rep.get('headline')}**",
        "",
        f"- Persona: {rep.get('persona')}",
        f"- Task: {rep.get('task')}",
        f"- Judge (independent): {'goal reached' if j['goal_reached'] else 'goal NOT reached'}"
        + (" — UNVERIFIED" if j["unverified"] else "")
        + f" — {j['reason']}",
        f"- Simulated user said: {rep['driver_claim'].get('outcome')} — {rep['driver_claim'].get('notes') or '(no notes)'}",
        f"- Steps: {rep['num_steps']} · time: {rep.get('total_time_s')}s",
        f"- Proof: {'PASS' if proof.get('pass') else 'FAIL'}",
    ]
    for c in proof.get("checks") or []:
        lines.append(f"  - {'✓' if c['pass'] else '✗'} {c['name']}: {c['detail']}")
    if rep["friction"]:
        lines += ["", "## Friction"]
        for f in rep["friction"]:
            lines.append(f"- Step {f['step']} ({f['url']}): {f['what']} — [screenshot]({f['screenshot']})")
    lines += ["", "## Steps"]
    for s in rep["steps"]:
        err = f" — error: {s['error']}" if s["error"] else ""
        thought = f" — “{s['thought']}”" if s["thought"] else ""
        lines.append(f"{s['step']}. {s['action']} @ {s['url']}{thought}{err} — [screenshot]({s['screenshot']})")
    lines += [
        "",
        f"Watch / replay: {rep['links']['watch']}",
        f"Full report: {rep['links']['report']}",
        f"Engine: {rep.get('engine_version')} · config {rep.get('config_hash')}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------- multi-run studies

_TERMINAL_ROWS = {"complete", "done", "error", "skipped"}
_FINISHING: set[str] = set()


async def maybe_finish_study(study: Any, *, force: bool = False) -> bool:
    """When every cell has ended (or force), run the website's end-of-study pipeline once.

    Runs in the background so the last simulated user's usersim_finish returns at once.
    Cells never started are marked skipped. Returns True if the finish was started.
    """
    rows = list(study.live_sessions.values())
    if study.id in _FINISHING or study.status != "running":
        return False
    if not force and any(r.get("status") not in _TERMINAL_ROWS for r in rows):
        return False
    from mvp.sim_mcp.sessions import SESSIONS

    if force and any(s.study is study and not s.closed for s in SESSIONS.values()):
        raise RuntimeError("some simulated users are still running; finish them first")
    _FINISHING.add(study.id)
    for r in rows:
        if r.get("status") not in _TERMINAL_ROWS:
            r["status"] = "skipped"
            r["live_active"] = False
    study.phase = "Writing the report"
    asyncio.get_running_loop().create_task(_finish_matrix(study))
    return True


async def _finish_matrix(study: Any) -> None:
    from mvp.study import finish_study, log_activity, persist_study

    try:
        await finish_study(study)
        proofs = [r.get("mcp_proof") or {} for r in study.agent_results]
        study.summary = {
            **(study.summary or {}),
            "driver": DRIVER,
            "mcp_proof": {
                "runs": len(proofs),
                "passed": sum(1 for p in proofs if p.get("pass")),
                "failed_runs": [r.get("agent_id") for r in study.agent_results if not (r.get("mcp_proof") or {}).get("pass")],
            },
        }
        await asyncio.to_thread(persist_study, study)
    except Exception as exc:  # noqa: BLE001
        print(f"[mcp] finishing study {study.id} failed: {exc!r}", flush=True)
        study.status = "error"
        study.error = f"report failed: {exc!r}"[:500]
        log_activity(study, "error", study.error)
        await asyncio.to_thread(persist_study, study)
    finally:
        _FINISHING.discard(study.id)


def build_study_report(study: dict[str, Any]) -> dict[str, Any]:
    """Multi-run study: the website report's headline plus one line per cell."""
    sid = str(study.get("id") or "")
    summary = study.get("summary") or {}
    by_id = {r.get("agent_id"): r for r in study.get("agent_results") or [] if isinstance(r, dict)}
    rows = [s for s in study.get("live_sessions") or [] if isinstance(s, dict)]
    cells = []
    for row in rows:
        res = by_id.get(row.get("agent_id")) or {}
        verdict = res.get("page_verdict") or row.get("page_verdict") or {}
        cells.append(
            {
                "cell_id": row.get("agent_id"),
                "site": row.get("site_label"),
                "persona": row.get("persona_name"),
                "task": row.get("task_prompt"),
                "status": row.get("status"),
                "goal_reached": bool(verdict.get("goal_reached")) if verdict else None,
                "judge_reason": verdict.get("reason") or "",
                "proof_pass": (res.get("mcp_proof") or {}).get("pass"),
                "steps": row.get("num_steps") or 0,
                "driver_outcome": res.get("driver_outcome"),
            }
        )
    return {
        "study_id": sid,
        "status": study.get("status"),
        "phase": study.get("phase"),
        "headline": summary.get("verdict_summary") or summary.get("headline") or study.get("phase"),
        "product_url": study.get("url"),
        "competitors": study.get("competitors") or [],
        "summary": {k: summary.get(k) for k in ("headline", "verdict_summary", "recommendations", "strengths", "weaknesses") if summary.get(k)},
        "proof": summary.get("mcp_proof") or {},
        "cells": cells,
        "links": {"watch": watch_url(sid), "report": report_url(sid)},
        "engine_version": study.get("engine_version"),
        "config_hash": study.get("config_hash"),
    }


def study_report_markdown(rep: dict[str, Any]) -> str:
    lines = [f"# UserSim study — {rep.get('product_url')}", "", f"**{rep.get('headline')}**", ""]
    if rep["status"] != "complete":
        lines += [f"Status: {rep['status']} — {rep.get('phase')}", ""]
    proof = rep.get("proof") or {}
    if proof:
        lines.append(f"Proof: {proof.get('passed')}/{proof.get('runs')} runs passed")
    lines += ["", "| Site | Persona | Task | Judge | Proof | Steps |", "|---|---|---|---|---|---|"]
    for c in rep["cells"]:
        judge = "—" if c["goal_reached"] is None else ("reached" if c["goal_reached"] else "NOT reached")
        pr = "—" if c["proof_pass"] is None else ("pass" if c["proof_pass"] else "FAIL")
        lines.append(f"| {c['site']} | {c['persona']} | {c['task']} | {judge} | {pr} | {c['steps']} |")
    lines += ["", f"Full report (same page as a website study): {rep['links']['report']}", f"Watch / replay: {rep['links']['watch']}"]
    return "\n".join(lines)


def is_matrix(study: dict[str, Any]) -> bool:
    rows = study.get("live_sessions") or []
    # A 1x1x1 study is shaped exactly like the one-run report, so either reader works for it.
    return study.get("backend") == "mcp" and (len(rows) > 1 or any(r.get("agent_id") != AGENT_ID for r in rows if isinstance(r, dict)))
