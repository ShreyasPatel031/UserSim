"""UserSim MVP — local API + frontpage."""

from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, HttpUrl

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
    url: HttpUrl
    email: str | None = Field(default=None, max_length=200)
    segment: str | None = Field(default=None, max_length=2000)
    customers: str | None = Field(default=None, max_length=2000)
    competitors: list[str] = Field(default_factory=list)
    tasks: list[str] = Field(default_factory=list)
    test_mode: bool = False
    backend: str = Field(default="default", pattern="^(default|runloop)$")


@app.get("/")
async def index() -> FileResponse:
    if not (STATIC / "index.html").is_file():
        raise HTTPException(status_code=503, detail="Frontend not bundled")
    return FileResponse(STATIC / "index.html")


@app.get("/runloop")
async def runloop_page() -> FileResponse:
    path = STATIC / "runloop.html"
    if not path.is_file():
        raise HTTPException(status_code=503, detail="Runloop edition not bundled")
    return FileResponse(path)


@app.post("/api/studies")
async def start_study(body: StudyRequest, background: BackgroundTasks):
    from mvp.study import STUDIES, create_study, run_study, study_to_dict

    segment = (body.segment or body.customers or "").strip()
    if not segment:
        segment = (
            "Auto-research target customers from the product URL "
            "and invent a mixed panel of 6 personas."
        )
    if body.test_mode:
        segment = (body.customers or body.segment or "Curious first-time visitor").strip()
    if len(segment) < 8:
        raise HTTPException(status_code=400, detail="Segment / customers description is too short")

    study = create_study(str(body.url), segment)
    # Stash optional inputs for the upcoming agent-loop planner.
    study.email = body.email
    study.customers = body.customers
    study.test_mode = bool(body.test_mode)
    study.backend = body.backend
    study.competitors = (
        []
        if study.test_mode
        else [c.strip() for c in body.competitors if c and c.strip()]
    )
    study.tasks_override = [t.strip() for t in body.tasks if t and t.strip()]
    if study.test_mode and not study.tasks_override:
        study.tasks_override = ["Browse the homepage and try to find something interesting to watch or try"]
    # Serverless: no reliable background workers — run the study in this request
    # (requires Vercel Pro for maxDuration up to 300s; full studies may need a worker host).
    if IS_VERCEL:
        timeout_s = float(os.environ.get("MVP_STUDY_TIMEOUT_S", "90"))
        try:
            await asyncio.wait_for(run_study(study.id), timeout=timeout_s)
            return study_to_dict(STUDIES[study.id])
        except asyncio.TimeoutError:
            study = STUDIES[study.id]
            study.status = "error"
            study.error = f"Study timed out after {int(timeout_s)}s"
            study.phase = "Timed out"
            return JSONResponse(study_to_dict(study), status_code=504)
        except Exception as exc:  # noqa: BLE001
            study = STUDIES[study.id]
            study.status = "error"
            study.error = (str(exc) or repr(exc))[:500]
            study.phase = "Failed"
            return JSONResponse(study_to_dict(study), status_code=500)
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
