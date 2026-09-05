"""UserSim MVP — local API + frontpage."""

from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import json

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
    backend: str = Field(default="default", pattern="^(default)$")


def _normalize_url(raw: str) -> str:
    url = (raw or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="Product URL is required")
    if not re.match(r"^https?://", url, flags=re.I):
        url = "https://" + url
    return url


@app.get("/")
async def index() -> FileResponse:
    if not (STATIC / "index.html").is_file():
        raise HTTPException(status_code=503, detail="Frontend not bundled")
    return FileResponse(STATIC / "index.html")


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
    study.tasks_override = [t.strip() for t in body.tasks if t and t.strip()]
    if study.test_mode and not study.tasks_override:
        study.tasks_override = ["Browse the homepage and try to find something interesting to watch or try"]

    want_stream = "text/event-stream" in (request.headers.get("accept") or "") or (
        request.headers.get("x-usersim-stream") == "1"
    )

    # Serverless: stream NDJSON so the brief (competitors / users / tasks) arrives
    # before browser agents finish — cuts perceived time-to-first-content.
    if IS_VERCEL or want_stream:
        timeout_s = float(os.environ.get("MVP_STUDY_TIMEOUT_S", "180"))
        queue: asyncio.Queue[dict | None] = asyncio.Queue()

        def _push(study_obj, event: str = "progress") -> None:
            payload = study_to_dict(study_obj)
            payload["stream_event"] = event
            queue.put_nowait(payload)

        async def _runner() -> None:
            try:
                await asyncio.wait_for(
                    run_study(study.id, on_update=_push),
                    timeout=timeout_s,
                )
                final = study_to_dict(STUDIES[study.id])
                final["stream_event"] = "complete"
                await queue.put(final)
            except asyncio.TimeoutError:
                study_obj = STUDIES[study.id]
                study_obj.status = "error"
                study_obj.error = f"Study timed out after {int(timeout_s)}s"
                study_obj.phase = "Timed out"
                payload = study_to_dict(study_obj)
                payload["stream_event"] = "error"
                await queue.put(payload)
            except Exception as exc:  # noqa: BLE001
                study_obj = STUDIES[study.id]
                study_obj.status = "error"
                study_obj.error = (str(exc) or repr(exc))[:500]
                study_obj.phase = "Failed"
                payload = study_to_dict(study_obj)
                payload["stream_event"] = "error"
                await queue.put(payload)
            finally:
                await queue.put(None)

        async def _gen():
            task = asyncio.create_task(_runner())
            try:
                while True:
                    item = await queue.get()
                    if item is None:
                        break
                    yield json.dumps(item) + "\n"
            finally:
                await task

        return StreamingResponse(
            _gen(),
            media_type="application/x-ndjson",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    background.add_task(run_study, study.id)
    return {"study_id": study.id, "status": study.status}


@app.get("/api/studies/{study_id}")
async def get_study(study_id: str):
    from mvp.study import STUDIES, study_to_dict

    study = STUDIES.get(study_id)
    if not study:
        raise HTTPException(status_code=404, detail="Study not found")
    return study_to_dict(study)


@app.get("/api/studies/{study_id}/agents/{agent_id}/screenshots/{filename}")
async def get_agent_screenshot(study_id: str, agent_id: str, filename: str):
    if not re.fullmatch(r"(?:step|bbox)_\d+\.png", filename):
        raise HTTPException(status_code=400, detail="Invalid screenshot name")
    path = MVP_RUNS_DIR / study_id / agent_id / "screenshots" / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Screenshot not found")
    return FileResponse(path, media_type="image/png")


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
