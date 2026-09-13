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


def _render_report_html(data: dict) -> str:
    """Server-rendered report so /report?study= works even if JS fails."""
    summary = data.get("summary") or {}
    if not isinstance(summary, dict) or not (
        summary.get("headline")
        or summary.get("recommendations")
        or summary.get("top_friction")
        or summary.get("segment_fit_score") is not None
    ):
        study_id = _escape_html(data.get("id"))
        return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>UserSim — Report</title>
<link rel="stylesheet" href="/static/styles.css?v=64" /></head><body>
<header class="site-header"><a class="logo" href="/">UserSim</a>
<a class="header-back" href="/">← Back to simulation</a></header>
<main class="main-url-first report-main"><p class="brief-empty">No summary on this study yet.
<a href="/live?study={study_id}">Open live view</a></p></main></body></html>"""

    def lis(items: object) -> str:
        rows = items if isinstance(items, list) else []
        if not rows:
            return "<li>—</li>"
        return "".join(f"<li>{_escape_html(x)}</li>" for x in rows)

    recs = summary.get("recommendations") or []
    rec_html = []
    for rec in recs if isinstance(recs, list) else []:
        if not isinstance(rec, dict):
            continue
        rec_html.append(
            '<div class="rec-card">'
            f'<span class="priority {_escape_html(rec.get("priority") or "medium")}">'
            f'{_escape_html(rec.get("priority") or "medium")}</span>'
            "<div>"
            f"<strong>{_escape_html(rec.get('action'))}</strong>"
            f'<p style="margin:0.25rem 0 0;color:var(--text-muted);font-size:0.9rem">'
            f"{_escape_html(rec.get('rationale'))}</p>"
            "</div></div>"
        )

    agents = data.get("agent_results") or []
    agent_html = []
    for r in agents if isinstance(agents, list) else []:
        if not isinstance(r, dict):
            continue
        friction = "".join(
            f"<li>{_escape_html(x)}</li>" for x in (r.get("friction_points") or [])
        ) or "<li>—</li>"
        easy = "".join(
            f"<li>{_escape_html(x)}</li>" for x in (r.get("what_was_easy") or [])
        ) or "<li>—</li>"
        agent_html.append(
            '<article class="agent-card">'
            f"<h3>{_escape_html(r.get('persona_name') or 'Simulated user')} — "
            f"{_escape_html(r.get('task_title') or 'Task')}</h3>"
            f'<div class="meta"><span class="tag difficulty-{_escape_html(r.get("difficulty") or "medium")}">'
            f'{_escape_html(r.get("difficulty") or "medium")}</span>'
            f'<span class="tag">would convert: {_escape_html(r.get("would_convert") or "?")}</span>'
            f'<span class="tag">{len(r.get("trace") or [])} steps</span></div>'
            f'<p style="margin-top:0.75rem">{_escape_html(r.get("product_feedback"))}</p>'
            f'<blockquote class="quote">"{_escape_html(r.get("quote"))}"</blockquote>'
            f'<div class="agent-lists"><div><h4>Friction</h4><ul>{friction}</ul></div>'
            f"<div><h4>Easy</h4><ul>{easy}</ul></div></div></article>"
        )

    title = (
        f"Executive summary — {_escape_html(data.get('url'))}"
        if data.get("url")
        else "Executive summary"
    )
    fit = summary.get("segment_fit_score")
    fit_txt = _escape_html(fit if fit is not None else "—")
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>UserSim — Report</title>
<link rel="stylesheet" href="/static/styles.css?v=64" />
</head><body>
<header class="site-header"><a class="logo" href="/">UserSim</a>
<a class="header-back" href="/">← Back to simulation</a></header>
<main class="main-url-first report-main">
<section id="results" class="results">
<section class="panel summary-panel">
<h2>{title}</h2>
<p id="headline" class="headline">{_escape_html(summary.get("headline"))}</p>
<div class="summary-grid">
<div><h4>Top friction</h4><ul>{lis(summary.get("top_friction"))}</ul></div>
<div><h4>Top strengths</h4><ul>{lis(summary.get("top_strengths"))}</ul></div>
</div>
<div class="fit-score"><span id="fit-score">{fit_txt}</span>
<div><strong>Segment fit</strong><p>{_escape_html(summary.get("segment_fit_rationale"))}</p></div></div>
<div class="conversion"><h4>Conversion outlook</h4><p>{_escape_html(summary.get("conversion_outlook") or "—")}</p></div>
<div class="recommendations"><h4>Recommendations</h4><div id="recommendations">{"".join(rec_html) or "—"}</div></div>
</section>
<section class="panel"><h2>Session recaps</h2>
<div class="agents-grid">{"".join(agent_html) or "<p>—</p>"}</div>
</section>
</section>
</main>
<footer><p>UserSim runs synthetic user simulations — a complement to, not a replacement for, real interviews.</p></footer>
</body></html>"""


@app.get("/report")
async def report_page(request: Request):
    """Serve report UI. When ?study= is set, SSR from GCS so links work without sessionStorage."""
    study_id = (request.query_params.get("study") or "").strip()
    if study_id:
        from mvp.study import STUDIES, load_study_from_gcs, study_to_dict

        data = None
        study = STUDIES.get(study_id)
        if study:
            data = study_to_dict(study)
        if not data or not data.get("summary"):
            remote = await asyncio.to_thread(load_study_from_gcs, study_id)
            if remote:
                data = remote
        if not data:
            raise HTTPException(status_code=404, detail="Study not found")
        return HTMLResponse(_render_report_html(data))

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

    url = _normalize_url(body.url)
    segment = (body.segment or body.customers or "").strip()
    if not segment:
        segment = (
            "Auto-research target customers from the product URL "
            "and invent a mixed panel of directed simulated users."
        )
    if body.test_mode and not (body.customers or body.segment):
        segment = "Curious first-time visitor"

    study = create_study(url, segment)
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

    want_stream = "text/event-stream" in (request.headers.get("accept") or "") or (
        request.headers.get("x-usersim-stream") == "1"
    )

    # Serverless: stream NDJSON so the brief (competitors / users / tasks) arrives
    # before browser agents finish — cuts perceived time-to-first-content.
    if IS_VERCEL or want_stream:
        # Pro plan GA max is 800s — give studies ~13 min (8–12 min typical)
        # with a little headroom for kill/persist cleanup.
        timeout_s = float(os.environ.get("MVP_STUDY_TIMEOUT_S", "780" if IS_VERCEL else "900"))
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

        async def _gen():
            task = asyncio.create_task(_runner())
            from mvp.study import STUDY_TASKS

            STUDY_TASKS[study.id] = task

            async def _keep(t: asyncio.Task) -> None:
                try:
                    await t
                except Exception:
                    pass
                finally:
                    STUDY_TASKS.pop(study.id, None)

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
            finally:
                # Keep the study alive after client disconnect / encode errors.
                if not task.done():
                    asyncio.create_task(_keep(task))
                else:
                    await task
                    STUDY_TASKS.pop(study.id, None)

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
    from mvp.study import STUDIES, load_study_from_gcs, study_to_dict

    study = STUDIES.get(study_id)
    if study:
        data = study_to_dict(study)
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
                data = {**data, **remote, "id": study_id}
                remote_live = data.get("live_sessions")
                local_steps = _live_step_count(local_live)
                remote_steps = _live_step_count(remote_live)
                if local_steps > remote_steps:
                    data["live_sessions"] = local_live
        data["live_sessions"] = await asyncio.to_thread(
            hydrate_live_sessions_from_gcs, study_id, data.get("live_sessions")
        )
        return data
    remote = await asyncio.to_thread(load_study_from_gcs, study_id)
    if remote:
        remote["live_sessions"] = await asyncio.to_thread(
            hydrate_live_sessions_from_gcs, study_id, remote.get("live_sessions")
        )
        return remote
    raise HTTPException(status_code=404, detail="Study not found")


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
    if not re.fullmatch(r"(?:step|bbox)_\d+\.png", filename):
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


@app.get("/blandai")
async def blandai_page() -> FileResponse:
    path = STATIC / "bakeoff.html"
    if not path.is_file():
        raise HTTPException(status_code=503, detail="Bland AI study viewer not bundled")
    return FileResponse(path)


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
