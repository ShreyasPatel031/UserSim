"""UserSim MVP — local API + frontpage."""

from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import json
from datetime import datetime, timezone

from mvp.paths import MVP_RUNS_DIR

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

STATIC = Path(__file__).resolve().parent / "static"
IS_VERCEL = bool(os.environ.get("VERCEL") or os.environ.get("VERCEL_ENV"))

app = FastAPI(title="UserSim MVP", version="0.1.0")


@app.on_event("startup")
async def _prime_browser_sessions() -> None:
    """Have a Browserbase session ready before the Run click."""
    if os.environ.get("MVP_A11Y_LOOP", "1").lower() in {"0", "false", "no"}:
        return
    from mvp.a11y_agent import prime_sessions

    # Idle primes sit inside the 25-session cap. A 24-agent study reuses any
    # primed session as one of the 24, so the default is zero extra sessions.
    raw = (os.environ.get("MVP_PRIME_SESSIONS") or "0").strip()
    try:
        prime_n = max(0, int(raw))
    except ValueError:
        prime_n = 0
    prime_sessions(prime_n)


@app.on_event("startup")
async def _recover_interrupted() -> None:
    """Studies a previous process left running are marked interrupted, and their browsers released."""
    from mvp.study import recover_interrupted_studies

    async def _run() -> None:
        try:
            fixed = await asyncio.to_thread(recover_interrupted_studies)
            if fixed:
                print(f"marked {len(fixed)} interrupted studies: {', '.join(f[:8] for f in fixed)}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"interrupted-study recovery failed: {exc!r}", flush=True)

    asyncio.get_running_loop().create_task(_run())

if STATIC.is_dir():
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
_TRACE_PUBLIC = ROOT / "public" / "bakeoff-traces"
if _TRACE_PUBLIC.is_dir() and not IS_VERCEL:
    app.mount(
        "/bakeoff-traces",
        StaticFiles(directory=_TRACE_PUBLIC),
        name="bakeoff_traces",
    )


@app.exception_handler(Exception)
async def unhandled_exception(_request, exc: Exception):
    return JSONResponse(
        {"detail": str(exc) or repr(exc), "status": "error"},
        status_code=500,
    )


class StudyRequest(BaseModel):
    url: str = Field(min_length=3, max_length=2000)
    email: str | None = Field(default=None, max_length=200)
    segment: str | None = Field(default=None, max_length=2000)
    customers: str | None = Field(default=None, max_length=2000)
    competitors: list[str] = Field(default_factory=list)
    tasks: list[str] = Field(default_factory=list)
    test_mode: bool = False
    skip_competitors: bool = False
    max_agents: int | None = Field(default=None, ge=1, le=75)
    backend: str = Field(default="default", pattern="^(default)$")


def _normalize_url(raw: str) -> str:
    url = (raw or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="Product URL is required")
    if not re.match(r"^https?://", url, flags=re.I):
        url = "https://" + url
    return url


async def _landing_url(url: str) -> str:
    """Where the product URL really lands (notion.so -> www.notion.com).

    Agents end on the redirected host. Keeping the pre-redirect host made
    every product run look like it had wandered to another site.
    """
    from urllib.parse import urlsplit

    import httpx

    try:
        async with httpx.AsyncClient(timeout=3.0, follow_redirects=True, headers={"user-agent": "Mozilla/5.0"}) as client:
            resp = await client.get(url)
        final = str(resp.url)
    except Exception:
        return url
    a = (urlsplit(url).hostname or "").removeprefix("www.")
    b = (urlsplit(final).hostname or "").removeprefix("www.")
    if not b or a == b:
        return url
    # Only follow a redirect to a different host, and keep the path the user typed.
    parts = urlsplit(url)
    return f"https://{urlsplit(final).hostname}{parts.path or '/'}"


def _study_list_key(url: str | None, study_id: str | None = None) -> str:
    """One sidebar row per product URL (host + path), not per historical run id."""
    from urllib.parse import urlparse

    raw = (url or "").strip()
    if not raw:
        return f"id:{(study_id or '').strip()}"
    try:
        p = urlparse(raw if re.match(r"^https?://", raw, flags=re.I) else "https://" + raw)
    except Exception:
        return f"id:{(study_id or raw).strip()}"
    host = (p.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = (p.path or "/").rstrip("/") or "/"
    return f"{host}{path}"


def _dedupe_studies_one_per_url(rows: list[dict]) -> list[dict]:
    """Keep a single latest run per product URL for /live."""
    rank = {
        "running": 0,
        "pending": 1,
        "queued": 2,
        "complete": 3,
        "error": 4,
        "abandoned": 5,
    }
    best: dict[str, dict] = {}
    for row in rows:
        key = _study_list_key(row.get("url"), str(row.get("id") or ""))
        cur = best.get(key)
        if cur is None:
            best[key] = row
            continue
        r_new = rank.get(str(row.get("status") or ""), 9)
        r_old = rank.get(str(cur.get("status") or ""), 9)
        if r_new < r_old:
            best[key] = row
            continue
        if r_new > r_old:
            continue
        if str(row.get("updated_at") or "") >= str(cur.get("updated_at") or ""):
            best[key] = row
    out = list(best.values())
    out.sort(key=lambda r: str(r.get("updated_at") or ""), reverse=True)
    return out


@app.get("/")
async def index() -> FileResponse:
    if not (STATIC / "index.html").is_file():
        raise HTTPException(status_code=503, detail="Frontend not bundled")
    return FileResponse(STATIC / "index.html")


@app.get("/live")
async def live_page() -> FileResponse:
    path = STATIC / "live.html"
    if not path.is_file():
        raise HTTPException(status_code=503, detail="Live dashboard not bundled")
    return FileResponse(path)


def _escape_html(value: object) -> str:
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _trace_anchor(agent_id: object, step: object) -> str:
    safe = re.sub(r"[^A-Za-z0-9_-]", "-", str(agent_id or "agent"))
    return f"trace-{safe}-{step}"


def _metrics_html(metrics: object) -> str:
    if not isinstance(metrics, dict) or not metrics.get("n"):
        return ""
    steps = metrics.get("median_steps")
    steps_txt = "—" if steps is None else f"{float(steps):.1f}"

    def _sec(value: object) -> str:
        if not isinstance(value, (int, float)):
            return "—"
        return f"{float(value):.1f}s"

    model = metrics.get("model") or ""
    provider = metrics.get("model_provider") or ""
    model_txt = " ".join(part for part in (str(model), str(provider)) if part).strip()
    model_html = f"<span>{_escape_html(model_txt)}</span>" if model_txt else ""
    changed_n = metrics.get("changed_page_n", metrics.get("left_start_n", 0))
    changed_pct = metrics.get("changed_page_pct", metrics.get("left_start_pct", 0))
    return (
        '<p class="stat-strip" id="work-metrics">'
        f"<span><strong>{steps_txt}</strong> median steps</span>"
        f"<span><strong>{changed_pct}%</strong> changed page state "
        f"({changed_n}/{metrics.get('n')})</span>"
        f"<span><strong>{metrics.get('task_success_rate', 0)}%</strong> task success on the final state "
        f"({metrics.get('task_success_n', 0)}/{metrics.get('n')})</span>"
        f"<span><strong>{_sec(metrics.get('step_latency_p50'))}</strong> step p50 / "
        f"<strong>{_sec(metrics.get('step_latency_p95'))}</strong> p95</span>"
        f"{model_html}"
        "</p>"
    )


def _render_report_html(data: dict) -> str:
    """Server-rendered report. Claims cite a real step screenshot and final URL."""
    data = _with_report_insights(data)
    summary = data.get("summary") or {}
    insights = summary.get("insights") if isinstance(summary, dict) else None
    if not isinstance(insights, dict) or not insights.get("headline"):
        study_id = _escape_html(data.get("id"))
        return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>UserSim — Report</title>
<link rel="stylesheet" href="/static/styles.css?v=65" /></head><body>
<header class="site-header"><a class="logo" href="/">UserSim</a>
<a class="header-back" href="/">← Back to simulation</a></header>
<main class="main-url-first report-main"><p class="brief-empty">No summary on this study yet.
<a href="/live?study={study_id}">Open live view</a></p></main></body></html>"""

    runs = {
        str(r.get("agent_id")): r
        for r in (data.get("agent_results") or [])
        if isinstance(r, dict) and r.get("agent_id")
    }

    def claim_cards(claims: object, kind: str) -> str:
        rows = claims if isinstance(claims, list) else []
        if not rows:
            label = "strength" if kind == "strength" else "weakness"
            return f'<p class="empty-claim">None. The traces do not support a specific {label}.</p>'
        cards = []
        for claim in rows:
            if not isinstance(claim, dict):
                continue
            cites = []
            for ev in claim.get("evidence") or []:
                if not isinstance(ev, dict):
                    continue
                anchor = _trace_anchor(ev.get("agent_id"), ev.get("step"))
                shot = ev.get("screenshot_url") or ""
                img = (
                    f'<a class="shot" href="#{anchor}"><img src="{_escape_html(shot)}" alt="Step { _escape_html(ev.get("step")) } screenshot" /></a>'
                    if shot
                    else ""
                )
                final = ev.get("final_url") or ""
                final_html = (
                    f'<a href="{_escape_html(final)}" target="_blank" rel="noopener">final URL</a>'
                    if final
                    else ""
                )
                cites.append(
                    '<div class="cite">'
                    f"{img}<div>"
                    f'<p class="who">{_escape_html(ev.get("persona_name"))} · {_escape_html(ev.get("task_title"))}</p>'
                    f'<p class="detail">{_escape_html(ev.get("detail") or ev.get("action"))}</p>'
                    f'<p class="links"><a href="#{anchor}">Open trace · step {_escape_html(ev.get("step"))}</a> {final_html}</p>'
                    "</div></div>"
                )
            cards.append(
                f'<article class="claim-card {kind}"><p>{_escape_html(claim.get("claim"))}</p>{"".join(cites)}</article>'
            )
        return "".join(cards)

    rows = insights.get("comparisons") or []
    body_rows = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        time = "—" if row.get("median_time_s") is None else f'{row.get("median_time_s")}s'
        steps = "—" if row.get("median_steps") is None else f'{float(row["median_steps"]):.1f}'
        pct = int(round(float(row.get("success_rate") or 0) * 100))
        p50 = "—" if row.get("step_latency_p50") is None else f'{row.get("step_latency_p50")}s'
        p95 = "—" if row.get("step_latency_p95") is None else f'{row.get("step_latency_p95")}s'
        changed = row.get("changed_page_pct", row.get("left_start_pct", 0))
        body_rows.append(
            "<tr>"
            f"<td>{_escape_html(row.get('site_label') or row.get('site_key'))}</td>"
            f"<td>{row.get('ok')}/{row.get('n')} ({pct}%)</td>"
            f"<td>{changed}%</td>"
            f"<td>{steps}</td><td>{p50}</td><td>{p95}</td><td>{time}</td>"
            f"<td>{row.get('friction_n') or 0}</td></tr>"
        )
    if insights.get("tie_note"):
        tie_html = f'<p id="tie-note" class="tie-note">{_escape_html(insights.get("tie_note"))}</p>'
    elif body_rows:
        tie_html = (
            '<p id="tie-note" class="tie-note">Task-success rates differ, so steps, time, and friction '
            "are listed beside the rates and are not used to break a tie.</p>"
        )
    else:
        tie_html = '<p id="tie-note" class="tie-note">No site comparison — the study has no finished runs.</p>'
    table = ""
    if body_rows:
        table = (
            '<div class="compare-wrap"><table id="compare-table"><thead><tr>'
            "<th>Site</th><th>Task success</th><th>Changed page</th><th>Median steps</th><th>Step p50</th><th>Step p95</th><th>Median time</th><th>Friction notes</th>"
            f"</tr></thead><tbody>{''.join(body_rows)}</tbody></table></div>"
        )

    # One trace section per cited agent step that has a screenshot.
    cited: list[tuple[str, int]] = []
    for bucket in ("strengths", "weaknesses"):
        for claim in insights.get(bucket) or []:
            if not isinstance(claim, dict):
                continue
            for ev in claim.get("evidence") or []:
                if isinstance(ev, dict) and ev.get("agent_id") is not None:
                    cited.append((str(ev["agent_id"]), int(ev.get("step") or 0)))
    traces = []
    seen_agents: set[str] = set()
    for agent_id, _step in cited:
        if agent_id in seen_agents:
            continue
        seen_agents.add(agent_id)
        run = runs.get(agent_id) or {}
        shots = [
            s
            for s in (run.get("trace") or [])
            if isinstance(s, dict) and s.get("screenshot_url") and isinstance(s.get("step"), int)
        ]
        if not shots:
            continue
        nav = " ".join(
            f'<a href="#{_trace_anchor(agent_id, s.get("step"))}">step {s.get("step")}</a>'
            for s in shots
        )
        final = run.get("final_url") or ""
        final_html = (
            f' · <a href="{_escape_html(final)}" target="_blank" rel="noopener">{_escape_html(final)}</a>'
            if final
            else ""
        )
        for shot in shots:
            anchor = _trace_anchor(agent_id, shot.get("step"))
            traces.append(
                f'<section id="{anchor}" class="panel trace-target">'
                f"<h2>Trace</h2>"
                f'<p class="section-sub">{_escape_html(run.get("persona_name"))} — '
                f'{_escape_html(run.get("task_title"))}{final_html}</p>'
                f'<p class="step-nav">{nav}</p>'
                f'<figure class="trace-shot"><img src="{_escape_html(shot.get("screenshot_url"))}" '
                f'alt="Step {shot.get("step")}" /></figure>'
                f'<p class="trace-action"><strong>Step {shot.get("step")}.</strong> '
                f'{_escape_html(shot.get("action"))}</p></section>'
            )

    note = insights.get("evidence_note") or ""
    note_html = f'<p id="evidence-note" class="evidence-note">{_escape_html(note)}</p>' if note else ""
    title = _escape_html(data.get("url") or "Study report")
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>UserSim — Report</title>
<link rel="stylesheet" href="/static/styles.css?v=65" />
<style>.trace-target{{display:none}}.trace-target:target{{display:block}}.cite a.shot{{display:block;padding:0;border:1px solid var(--border);border-radius:6px;background:#111;overflow:hidden}}.cite a.shot img{{width:112px;height:72px;object-fit:cover;object-position:top;display:block}}</style>
</head><body>
<header class="site-header"><a class="logo" href="/">UserSim</a>
<a class="header-back" href="/">← Back to simulation</a></header>
<main class="main-url-first report-main">
<section id="results" class="results">
<section class="panel summary-panel">
<h2 id="report-title">{title}</h2>
<p id="headline" class="headline">{_escape_html(insights.get("headline"))}</p>
{note_html}
{_metrics_html(insights.get("work_metrics"))}
<div class="insight-grid">
<div><h4>Strengths</h4>{claim_cards(insights.get("strengths"), "strength")}</div>
<div><h4>Weaknesses</h4>{claim_cards(insights.get("weaknesses"), "weakness")}</div>
</div>
<div id="compare-block"><h4>Site comparison</h4>{tie_html}{table}</div>
</section>
{"".join(traces)}
</section>
</main>
<footer><p>UserSim runs synthetic user simulations — a complement to, not a replacement for, real interviews.</p></footer>
</body></html>"""


@app.get("/report")
async def report_page(request: Request):
    """Generic study report. The page shell matches /blandai; data comes from the study API."""
    del request
    path = STATIC / "report.html"
    if not path.is_file():
        raise HTTPException(status_code=503, detail="Report page not bundled")
    return FileResponse(path)


@app.get("/api/studies")
async def list_studies(limit: int = 40):
    """List recent studies (in-memory first, then GCS) for the live dashboard."""
    from mvp.gcs_store import list_mvp_studies
    from mvp.study import STUDIES, study_to_dict

    rows: list[dict] = []
    seen: set[str] = set()
    # Local / current process runs first — /live should show what's actually running.
    for study in sorted(
        STUDIES.values(),
        key=lambda s: s.updated_at or s.created_at or "",
        reverse=True,
    ):
        data = study_to_dict(study)
        live = data.get("live_sessions") or []
        if isinstance(live, dict):
            live_items = list(live.values())
        else:
            live_items = list(live or [])
        rows.append(
            {
                "id": study.id,
                "url": study.url,
                "segment": study.segment,
                "status": study.status,
                "phase": study.phase,
                "updated_at": study.updated_at,
                "agents": len(live_items) or len(study.tasks or []),
                "steps": sum(len(s.get("trace") or []) for s in live_items if isinstance(s, dict)),
                "running_agents": sum(
                    1
                    for s in live_items
                    if isinstance(s, dict) and s.get("status") in {"running", "starting"}
                ),
                "persona_count": len(study.personas or []),
                "task_count": len(study.tasks or []),
                "has_done": study.status == "complete",
                "source": "memory",
            }
        )
        seen.add(study.id)

    # Pull enough GCS history that dedupe-by-URL still surfaces recent products
    # (mass kill rewrites many study.json blobs and can bury a fresh run).
    try:
        remote = await asyncio.wait_for(
            asyncio.to_thread(list_mvp_studies, limit=max(limit * 5, 100)),
            timeout=20.0,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"list_mvp_studies failed/timeout: {exc!r}", flush=True)
        remote = []
    for s in remote or []:
        sid = str((s or {}).get("id") or "")
        if not sid or sid in seen:
            continue
        s = dict(s)
        s.setdefault("source", "gcs")
        rows.append(s)
        seen.add(sid)

    rows.sort(key=lambda r: str(r.get("updated_at") or ""), reverse=True)
    # /live should show one row per product, not every historical GCS run.
    rows = _dedupe_studies_one_per_url(rows)
    return {"studies": rows[: max(1, min(limit, 100))]}


@app.post("/api/studies")
async def start_study(body: StudyRequest, background: BackgroundTasks, request: Request):
    from mvp.study import STUDIES, create_study, run_study, study_to_dict

    url = await _landing_url(_normalize_url(body.url))
    segment = (body.segment or body.customers or "").strip()
    if not segment:
        segment = (
            "Auto-research target customers from the product URL "
            "and invent a mixed panel of directed simulated users."
        )
    if body.test_mode and not (body.customers or body.segment):
        segment = "Curious first-time visitor"

    study = create_study(url, segment)
    # Count busy Browserbase sessions while the plan is written, so the
    # queue check before agents start costs nothing on a free project.
    from mvp.browser_slots import prefetch_count

    prefetch_count()
    # Stash optional inputs for the upcoming agent-loop planner.
    study.email = body.email
    study.customers = body.customers
    study.test_mode = bool(body.test_mode)
    # Browser agents use Gemini on Vertex (GCP). Live Chromium is Browserbase
    # when available; serverless falls back to grounded Vertex snapshots.
    study.backend = body.backend or "default"
    # Keep user-pinned competitors even in quick preview.
    study.competitors = [c.strip() for c in body.competitors if c and c.strip()]
    # Default: invent ~2 rivals when the box is blank (product + rivals in Products).
    # Only skip when the client explicitly opts out.
    study.skip_competitors = bool(body.skip_competitors)
    study.max_agents = int(body.max_agents or 0)
    study.tasks_override = [t.strip() for t in body.tasks if t and t.strip()]
    if study.test_mode and not study.tasks_override:
        study.tasks_override = ["Browse the homepage and try to find something interesting to watch or try"]
    if not study.tasks_override and os.environ.get("MVP_FAST_PLAN", "1") != "0":
        # A bare URL: one quick model call picks the tasks, rivals, and segment
        # so agents open pages within seconds instead of after ~20s of research.
        from mvp.fast_plan import plan_from_url

        plan = await plan_from_url(url)
        if plan:
            study.tasks_override = list(plan["tasks"])
            if not study.competitors and not study.skip_competitors:
                study.competitors = list(plan["competitors"])
            if not (body.segment or body.customers) and plan.get("segment"):
                study.segment = plan["segment"]

    want_stream = "text/event-stream" in (request.headers.get("accept") or "") or (
        "application/x-ndjson" in (request.headers.get("accept") or "")
    ) or (request.headers.get("x-usersim-stream") == "1")
    # Vercel serverless freezes the isolate when the HTTP handler returns, so a
    # fire-and-forget asyncio.create_task dies after ~seconds and leaves studies
    # stuck at "Writing tasks" with orphan Browserbase warms. Keep the study on
    # an open NDJSON stream whenever the client asks (the UI always does).
    # Local long-lived uvicorn can still use background+poll when the client
    # does not request a stream. Explicit MVP_ATTACH_STREAM=0/1 overrides.
    attach_env = (os.environ.get("MVP_ATTACH_STREAM") or "").strip().lower()
    if attach_env in {"0", "false", "no"}:
        attach_stream = False
    elif attach_env in {"1", "true", "yes"}:
        attach_stream = True
    else:
        attach_stream = bool(IS_VERCEL and want_stream)

    # Serverless: stream NDJSON so the brief (competitors / users / tasks) arrives
    # before browser agents finish — cuts perceived time-to-first-content.
    if attach_stream and (IS_VERCEL or want_stream):
        # One study budget. A full 24-agent Linear study finished in 128s.
        # The cap is 8 minutes.
        timeout_s = float(os.environ.get("MVP_STUDY_TIMEOUT_S", "480"))
        queue: asyncio.Queue[dict | None] = asyncio.Queue()

        def _push(study_obj, event: str = "progress") -> None:
            payload = study_to_dict(study_obj)
            payload["stream_event"] = event
            queue.put_nowait(payload)

        async def _abandon_timeout(study_obj, timeout_s: float) -> dict:
            """Persist abandoned state, kill zombie Browserbase, clear live UI."""
            from mvp.study import persist_study

            study_obj.kill_requested = True
            study_obj.status = "abandoned"
            study_obj.error = (
                f"Study timed out after {int(timeout_s)}s on Vercel — "
                "agents stopped and browsers released."
            )
            study_obj.phase = "Timed out"
            study_obj.updated_at = datetime.now(timezone.utc).isoformat()
            for sess in (study_obj.live_sessions or {}).values():
                if not isinstance(sess, dict):
                    continue
                if sess.get("status") in {
                    "running",
                    "starting",
                    "pending",
                    "summarizing",
                }:
                    sess["status"] = "killed"
                sess["live_active"] = False
                thoughts = list(sess.get("live_thoughts") or [])
                thoughts.append(
                    {
                        "at": study_obj.updated_at,
                        "text": "Timed out — live browser closed.",
                        "kind": "status",
                    }
                )
                sess["live_thoughts"] = thoughts[-24:]
                sess["last_action"] = "Timed out — browser closed"
            try:
                persist_study(study_obj)
            except Exception as persist_exc:  # noqa: BLE001
                print(f"timeout persist failed: {persist_exc!r}", flush=True)
            try:
                from mvp.kill_switch import kill_now_async

                await kill_now_async(
                    agents=True, vms=False, seeds=False, study_id=study_obj.id
                )
            except Exception as kill_exc:  # noqa: BLE001
                print(f"timeout kill failed: {kill_exc!r}", flush=True)
            # Re-persist after kill so GCS shows abandoned, not running.
            try:
                persist_study(study_obj)
            except Exception:
                pass
            payload = study_to_dict(study_obj)
            payload["stream_event"] = "error"
            return payload

        async def _runner() -> None:
            try:
                await asyncio.wait_for(
                    run_study(study.id, on_update=_push),
                    timeout=timeout_s,
                )
                final = study_to_dict(STUDIES[study.id])
                # GCP fleet may return early while Spot workers keep running.
                # Do NOT mark stream "complete" — client must poll until done.
                if final.get("status") in {"running", "starting", "pending"}:
                    final["stream_event"] = "detached"
                else:
                    final["stream_event"] = "complete"
                await queue.put(final)
            except asyncio.TimeoutError:
                study_obj = STUDIES[study.id]
                payload = await _abandon_timeout(study_obj, timeout_s)
                await queue.put(payload)
            except asyncio.CancelledError:
                # Should be rare — runner is detached from the HTTP stream.
                raise
            except Exception as exc:  # noqa: BLE001
                study_obj = STUDIES[study.id]
                study_obj.status = "error"
                study_obj.error = (str(exc) or repr(exc))[:500]
                study_obj.phase = "Failed"
                try:
                    from mvp.study import persist_study

                    persist_study(study_obj)
                except Exception:
                    pass
                payload = study_to_dict(study_obj)
                payload["stream_event"] = "error"
                await queue.put(payload)
            finally:
                await queue.put(None)
                STUDY_TASKS.pop(study.id, None)

        from mvp.study import STUDY_TASKS

        # Detach the runner from the HTTP request BEFORE streaming. Playwright /
        # browser fetch aborts were cancelling the request-scoped generator and
        # taking the study with it ("Killed by operator" at ~30s).
        task = asyncio.create_task(_runner(), name=f"study-{study.id}")
        STUDY_TASKS[study.id] = task

        async def _gen():
            try:
                while True:
                    item = await queue.get()
                    if item is None:
                        break
                    try:
                        yield json.dumps(item, default=str) + "\n"
                    except Exception:
                        # Never kill the study because one frame failed to encode.
                        continue
            except asyncio.CancelledError:
                # Client disconnected — study keeps running in STUDY_TASKS.
                return
            finally:
                # Do not cancel `task`. Agents must outlive the NDJSON stream.
                pass

        return StreamingResponse(
            _gen(),
            media_type="application/x-ndjson",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    from mvp.study import STUDY_TASKS

    async def _bg() -> None:
        try:
            await run_study(study.id)
        finally:
            STUDY_TASKS.pop(study.id, None)

    STUDY_TASKS[study.id] = asyncio.create_task(_bg())
    return {"study_id": study.id, "status": study.status}


class KillRequest(BaseModel):
    agents: bool = True
    vms: bool = False
    seeds: bool = False
    study_id: str | None = None


@app.get("/api/runtime/status")
async def runtime_status():
    from mvp.kill_switch import runtime_status as _status

    return await asyncio.to_thread(_status)


@app.post("/api/runtime/kill")
async def runtime_kill(body: KillRequest | None = None):
    """Kill Browserbase agents and/or UserSim VMs immediately."""
    from mvp.kill_switch import kill_now_async

    req = body or KillRequest()
    return await kill_now_async(
        agents=bool(req.agents),
        vms=bool(req.vms),
        seeds=bool(req.seeds),
        study_id=req.study_id,
    )


@app.get("/api/studies/{study_id}")
async def get_study(study_id: str):
    from mvp.gcs_store import hydrate_live_sessions_from_gcs
    from mvp.study import STUDIES, load_local_study, load_study_from_gcs, study_to_dict

    study = STUDIES.get(study_id)
    if study:
        data = study_to_dict(study)
        # A running study is served from memory. A GCS hydrate here holds the
        # request until the poll that should see the first click has already
        # missed the 10s clock.
        if data.get("status") in {"running", "pending", "starting"}:
            # Serve the stamps recorded when the page opened. Rewriting them
            # to this poll's time made page-open look ~10s after creation
            # once a finished agent row was merged back onto the live session,
            # and the harness aborted 23/24 studies that had already clicked.
            return data
        # In-memory live studies: return immediately. Hydrating GCS on every UI
        # poll while 6 Browserbase agents are writing was starving the event
        # loop (study GET timeouts / list 503s under parallel load).
        live = data.get("live_sessions") or {}
        if data.get("status") in {"running", "pending"} and live and _live_step_count(live) > 0:
            return data
        if data.get("status") in {"running", "pending"} and live:
            data["live_sessions"] = await asyncio.to_thread(
                hydrate_live_sessions_from_gcs, study_id, live
            )
            if _live_step_count(data.get("live_sessions")) > 0:
                return data
        # Merge fresher GCS state when fleet finished off-box / no local frames.
        if data.get("status") in {"running", "pending"} or not data.get("summary"):
            remote = await asyncio.to_thread(load_study_from_gcs, study_id)
            if remote:
                local_live = data.get("live_sessions")
                # Never let a stale GCS kill flag clobber a healthy in-memory run
                # (async abandon-all used to race newly started studies).
                if data.get("status") in {"running", "pending"} and not data.get(
                    "kill_requested"
                ):
                    remote = {
                        **remote,
                        "status": data.get("status"),
                        "phase": data.get("phase"),
                        "error": data.get("error"),
                        "kill_requested": False,
                    }
                data = {**data, **remote, "id": study_id}
                remote_live = data.get("live_sessions")
                local_steps = _live_step_count(local_live)
                remote_steps = _live_step_count(remote_live)
                if local_steps > remote_steps:
                    data["live_sessions"] = local_live
        data["live_sessions"] = await asyncio.to_thread(
            hydrate_live_sessions_from_gcs, study_id, data.get("live_sessions")
        )
        return _with_report_insights(data)
    remote = await asyncio.to_thread(load_study_from_gcs, study_id)
    if not remote:
        remote = load_local_study(study_id)
        if remote:
            return _with_report_insights(_interrupted_if_stale(remote))
    if remote:
        remote = _interrupted_if_stale(remote)
        remote["live_sessions"] = await asyncio.to_thread(
            hydrate_live_sessions_from_gcs, study_id, remote.get("live_sessions")
        )
        return _with_report_insights(remote)
    raise HTTPException(status_code=404, detail="Study not found")


def _interrupted_if_stale(data: dict) -> dict:
    """A saved study still marked running that no process is updating is shown as interrupted."""
    from mvp.study import looks_interrupted, mark_interrupted

    if looks_interrupted(data):
        return mark_interrupted(data)
    return data


def _with_report_insights(data: dict) -> dict:
    """Attach trace-cited insights whenever the study has runs.

    A finished study with no summary used to return one empty sentence.
    Partial runs still draw completion, steps, and time.
    """
    runs = [r for r in (data.get("agent_results") or []) if isinstance(r, dict)]
    if data.get("status") != "complete" and not runs:
        return data
    try:
        from mvp.report_insights import build_report_insights

        insights = build_report_insights(data)
    except Exception:
        return data
    summary = dict(data.get("summary") or {})
    summary["insights"] = insights
    if insights.get("headline"):
        summary["headline"] = insights["headline"]
    return {**data, "summary": summary}


def _live_step_count(live_sessions: object) -> int:
    if isinstance(live_sessions, dict):
        items = live_sessions.values()
    elif isinstance(live_sessions, list):
        items = live_sessions
    else:
        return 0
    total = 0
    for sess in items:
        if isinstance(sess, dict):
            total += len(sess.get("trace") or [])
    return total


@app.get("/api/studies/{study_id}/agents/{agent_id}/screenshots/{filename}")
async def get_agent_screenshot(study_id: str, agent_id: str, filename: str):
    if not re.fullmatch(r"(?:step|bbox)_\d+\.png|final\.png", filename):
        raise HTTPException(status_code=400, detail="Invalid screenshot name")
    names = [filename]
    m = re.fullmatch(r"(step|bbox)_(\d+)\.png", filename)
    if m:
        kind, num = m.group(1), m.group(2)
        names.append(("bbox" if kind == "step" else "step") + f"_{num}.png")
    from fastapi.responses import Response

    from mvp.gcs_store import gcs_download_bytes, screenshot_gcs_uri

    for name in names:
        path = MVP_RUNS_DIR / study_id / agent_id / "screenshots" / name
        if path.is_file() and path.stat().st_size > 200:
            resp = FileResponse(path, media_type="image/png")
            resp.headers["Cache-Control"] = "public, max-age=3600"
            return resp
        try:
            raw = gcs_download_bytes(screenshot_gcs_uri(study_id, agent_id, name))
        except Exception:
            raw = None
        if raw and len(raw) > 200:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw)
            except Exception:
                pass
            return Response(
                content=raw,
                media_type="image/png",
                headers={"Cache-Control": "public, max-age=3600"},
            )
    raise HTTPException(status_code=404, detail="Screenshot not found")


@app.post("/api/internal/live-frame")
async def post_live_frame(request: Request):
    """Seed → UI critical path. GCS archival happens on the seed in the background."""
    from mvp.live_frames import check_live_token, publish_live_frame

    form = await request.form()
    study_id = str(form.get("study_id") or "")
    agent_id = str(form.get("agent_id") or "")
    token = str(
        form.get("token")
        or request.headers.get("x-usersim-live-token")
        or ""
    )
    if not study_id or not agent_id:
        raise HTTPException(status_code=400, detail="study_id and agent_id required")
    if not check_live_token(study_id, token):
        raise HTTPException(status_code=401, detail="Invalid live token")

    step: dict = {}
    raw_step = form.get("step_json")
    if raw_step:
        try:
            step = json.loads(str(raw_step))
        except json.JSONDecodeError:
            step = {}
    png_bytes: bytes | None = None
    upload = form.get("png")
    if upload is not None and hasattr(upload, "read"):
        png_bytes = await upload.read()  # type: ignore[misc]
    elif isinstance(upload, (bytes, bytearray)):
        png_bytes = bytes(upload)

    if not png_bytes:
        raise HTTPException(status_code=400, detail="png required")

    step.setdefault("step", 0)
    step.setdefault("action", "Live frame")
    published = publish_live_frame(
        study_id=study_id, agent_id=agent_id, step=step, png=png_bytes
    )
    return {"ok": True, "screenshot_url": published.get("screenshot_url")}


@app.get("/health")
async def health():
    return {"ok": True}


@app.get("/recurse-study")
async def recurse_study_page() -> FileResponse:
    """Recurse.run competitive study — blandai-style dashboard (5x6x4 matrix)."""
    path = STATIC / "recurse_study.html"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="recurse_study.html missing")
    return FileResponse(path, media_type="text/html")


@app.get("/blandai")
async def blandai_page() -> FileResponse:
    path = STATIC / "bakeoff.html"
    if not path.is_file():
        raise HTTPException(status_code=503, detail="Bland AI study viewer not bundled")
    return FileResponse(path)


# Pretty share URL for the recurse.run full study (same pattern as /blandai).
_RECURSE_STUDY_ID = "e5daac85-b0f8-4425-a991-834d071ee823"


@app.get("/recurse")
async def recurse_page() -> FileResponse:
    path = STATIC / "recurse.html"
    if not path.is_file():
        raise HTTPException(status_code=503, detail="Recurse study viewer not bundled")
    return FileResponse(path)


@app.get("/api/recurse/analytics")
async def recurse_analytics():
    from mvp.recurse_study import analytics

    return analytics()


@app.get("/api/recurse/studies")
async def recurse_study_list():
    from mvp.recurse_study import studies

    return {"studies": studies()}


@app.get("/api/recurse/studies/{study_id}")
async def recurse_study_detail(study_id: str):
    from mvp.recurse_study import study

    if not re.fullmatch(r"p\d+", study_id):
        raise HTTPException(status_code=400, detail="Invalid study id")
    try:
        return study(study_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Study not found") from None


@app.get("/video-platforms")
async def video_platforms_page() -> FileResponse:
    path = STATIC / "video_platforms.html"
    if not path.is_file():
        raise HTTPException(status_code=503, detail="Video platform study viewer not bundled")
    return FileResponse(path)


@app.get("/api/video-platforms/results")
async def video_platform_results() -> FileResponse:
    path = Path(__file__).resolve().parent / "video_data" / "all_90_results.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Video platform results not found")
    return FileResponse(path, media_type="application/json")


@app.get("/api/video-study/analytics")
async def video_study_analytics():
    from mvp.video_study import analytics
    return analytics()


@app.get("/api/video-study/studies")
async def video_study_list():
    from mvp.video_study import studies
    return {"studies": studies()}


@app.get("/api/video-study/studies/{study_id}")
async def video_study_detail(study_id: str):
    from mvp.video_study import study
    if not re.fullmatch(r"p\d+_[a-z]+", study_id):
        raise HTTPException(status_code=400, detail="Invalid study id")
    try:
        return study(study_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Study not found") from None


@app.get("/bakeoff")
async def bakeoff_page_redirect():
    from fastapi.responses import RedirectResponse

    return RedirectResponse(url="/blandai", status_code=302)


@app.get("/api/bakeoff/studies")
async def list_bakeoff_studies():
    from mvp.bakeoff_view import list_studies

    return {"studies": list_studies()}


@app.get("/api/bakeoff/analytics")
async def get_bakeoff_analytics():
    from mvp.bakeoff_analytics import build_analytics

    return build_analytics()


@app.get("/api/bakeoff/studies/{study_id}")
async def get_bakeoff_study(study_id: str):
    from mvp.bakeoff_view import load_study

    if not re.fullmatch(r"[\w.-]+", study_id):
        raise HTTPException(status_code=400, detail="Invalid study id")
    try:
        return load_study(study_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Study not found") from None


@app.get("/api/bakeoff/traces/{trace_name}/final.png")
async def get_bakeoff_final_screenshot(trace_name: str):
    if not re.fullmatch(r"bu_\d+_[0-9a-f]+", trace_name):
        raise HTTPException(status_code=400, detail="Invalid trace id")
    path = _resolve_trace_asset(trace_name, "final.png")
    if not path:
        raise HTTPException(status_code=404, detail="Screenshot not found")
    return FileResponse(path, media_type="image/png")


@app.get("/api/bakeoff/traces/{trace_name}/screenshots/{filename}")
async def get_bakeoff_step_screenshot(trace_name: str, filename: str):
    if not re.fullmatch(r"bu_\d+_[0-9a-f]+", trace_name):
        raise HTTPException(status_code=400, detail="Invalid trace id")
    if not re.fullmatch(r"(?:step|bbox)_\d+\.png", filename):
        raise HTTPException(status_code=400, detail="Invalid screenshot name")
    path = _resolve_trace_asset(trace_name, f"screenshots/{filename}")
    if not path:
        raise HTTPException(status_code=404, detail="Screenshot not found")
    return FileResponse(path, media_type="image/png")


def _resolve_trace_asset(trace_name: str, rel: str) -> Path | None:
    candidates = [
        ROOT / "public" / "bakeoff-traces" / trace_name / rel,
        ROOT / "results" / "capability" / "traces" / trace_name / rel,
    ]
    for path in candidates:
        if path.is_file():
            return path
    return None
