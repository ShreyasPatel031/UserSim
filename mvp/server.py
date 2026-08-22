"""UserSim MVP — local API + frontpage."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, HttpUrl

from mvp.paths import MVP_RUNS_DIR

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mvp.study import STUDIES, create_study, run_study, study_to_dict  # noqa: E402

STATIC = Path(__file__).resolve().parent / "static"
IS_VERCEL = bool(os.environ.get("VERCEL") or os.environ.get("VERCEL_ENV"))

app = FastAPI(title="UserSim MVP", version="0.1.0")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


class StudyRequest(BaseModel):
    url: HttpUrl
    segment: str = Field(min_length=8, max_length=500)


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.post("/api/studies")
async def start_study(body: StudyRequest, background: BackgroundTasks):
    study = create_study(str(body.url), body.segment)
    # Serverless: no reliable background workers — run the study in this request
    # (requires Vercel Pro for maxDuration up to 300s; full studies may need a worker host).
    if IS_VERCEL:
        await run_study(study.id)
        return study_to_dict(STUDIES[study.id])
    background.add_task(run_study, study.id)
    return {"study_id": study.id, "status": study.status}


@app.get("/api/studies/{study_id}")
async def get_study(study_id: str):
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
