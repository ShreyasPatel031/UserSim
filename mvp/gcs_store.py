"""GCS helpers for MVP fleet studies — client-library based (works on Vercel)."""

from __future__ import annotations

import json
import os
import tempfile
import time
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

DEFAULT_GCS = os.environ.get(
    "MVP_GCS_PREFIX",
    os.environ.get("GCS_PREFIX", "gs://usersim-bakeoff-347838016394"),
).rstrip("/")

_LIST_CACHE: dict[str, tuple[float, list]] = {}
_HYDRATE_CACHE: dict[str, tuple[float, object]] = {}

def parse_gs_uri(uri: str) -> tuple[str, str]:
    raw = (uri or "").strip()
    if raw.startswith("gs://"):
        parsed = urlparse(raw)
        return parsed.netloc, parsed.path.lstrip("/")
    raise ValueError(f"Not a gs:// URI: {uri}")


@lru_cache(maxsize=1)
def _storage_client():
    from google.cloud import storage

    # A credential pointer inherited from secrets/env may not resolve on a
    # fleet copy; drop it so ADC can reach the instance service account.
    gac = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if gac and not Path(gac).is_file():
        os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)

    # Prefer explicit SA file when present (local); else ADC / VERTEX_ADC_JSON.
    sa = Path(__file__).resolve().parents[1] / "secrets" / "sa.json"
    if sa.is_file() and not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", str(sa))
    try:
        from auth import _materialize_adc_from_env

        _materialize_adc_from_env()
    except Exception:
        pass
    return storage.Client()


def gcs_upload_bytes(uri: str, data: bytes, *, content_type: str = "application/octet-stream") -> None:
    bucket_name, blob_name = parse_gs_uri(uri)
    client = _storage_client()
    blob = client.bucket(bucket_name).blob(blob_name)
    blob.upload_from_string(data, content_type=content_type)


def gcs_upload_json(uri: str, payload: Any) -> None:
    gcs_upload_bytes(
        uri,
        json.dumps(payload, default=str).encode("utf-8"),
        content_type="application/json",
    )


def gcs_upload_file(local: Path | str, uri: str, *, content_type: str | None = None) -> None:
    path = Path(local)
    bucket_name, blob_name = parse_gs_uri(uri)
    client = _storage_client()
    blob = client.bucket(bucket_name).blob(blob_name)
    kwargs = {}
    if content_type:
        kwargs["content_type"] = content_type
    blob.upload_from_filename(str(path), **kwargs)


def gcs_download_bytes(uri: str) -> bytes | None:
    try:
        bucket_name, blob_name = parse_gs_uri(uri)
        client = _storage_client()
        blob = client.bucket(bucket_name).blob(blob_name)
        if not blob.exists():
            return None
        return blob.download_as_bytes()
    except Exception:
        return None


def gcs_download_json(uri: str) -> dict[str, Any] | list[Any] | None:
    raw = gcs_download_bytes(uri)
    if raw is None:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        return None


def gcs_download_to_file(uri: str, dest: Path) -> bool:
    raw = gcs_download_bytes(uri)
    if raw is None:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(raw)
    return True


def gcs_list_prefix(prefix_uri: str) -> list[str]:
    bucket_name, prefix = parse_gs_uri(prefix_uri if prefix_uri.endswith("/") else prefix_uri + "/")
    # Allow callers to pass without trailing slash
    if not prefix_uri.endswith("/"):
        _, prefix = parse_gs_uri(prefix_uri)
        if prefix and not prefix.endswith("/"):
            # listing a "directory"
            prefix = prefix.rstrip("/") + "/"
    client = _storage_client()
    return [f"gs://{bucket_name}/{b.name}" for b in client.list_blobs(bucket_name, prefix=prefix)]


def study_gcs_root(study_id: str) -> str:
    return f"{DEFAULT_GCS}/mvp_studies/{study_id}"


def list_mvp_studies(*, limit: int = 40) -> list[dict[str, Any]]:
    """Recent studies under mvp_studies/*/study.json (GCS-backed, survives refresh)."""
    # Short TTL cache — Live dash polls every few seconds; full GCS scan is ~3s+.
    now = time.monotonic()
    cache_key = f"list:{limit}"
    cached = _LIST_CACHE.get(cache_key)
    if cached and now - cached[0] < 8.0:
        return cached[1]

    bucket_name, prefix = parse_gs_uri(f"{DEFAULT_GCS}/mvp_studies/")
    if not prefix.endswith("/"):
        prefix += "/"
    client = _storage_client()
    done_ids: set[str] = set()
    study_blobs: list[Any] = []
    for blob in client.list_blobs(bucket_name, prefix=prefix):
        name = blob.name or ""
        if name.endswith("/done.json"):
            parts = name[len(prefix) :].split("/")
            if len(parts) == 2:
                done_ids.add(parts[0])
        elif name.endswith("/study.json"):
            study_blobs.append(blob)

    rows: list[dict[str, Any]] = []
    for blob in study_blobs:
        name = blob.name or ""
        parts = name[len(prefix) :].split("/")
        if len(parts) != 2 or parts[1] != "study.json":
            continue
        study_id = parts[0]
        payload: dict[str, Any] = {"id": study_id}
        try:
            raw = blob.download_as_bytes()
            data = json.loads(raw.decode("utf-8"))
            if isinstance(data, dict):
                live = data.get("live_sessions") or []
                if isinstance(live, dict):
                    live_items = list(live.values())
                elif isinstance(live, list):
                    live_items = live
                else:
                    live_items = []
                steps = sum(len(s.get("trace") or []) for s in live_items if isinstance(s, dict))
                agents = len(live_items)
                running = sum(
                    1
                    for s in live_items
                    if isinstance(s, dict) and (s.get("status") or "") in {"running", "starting"}
                )
                status = data.get("status") or "unknown"
                phase = data.get("phase") or ""
                if study_id in done_ids and status in {"running", "pending"}:
                    status = "complete"
                    phase = phase or "Complete"
                elif status in {"running", "pending"}:
                    phase_l = phase.lower()
                    if "0 active" in phase_l and "done" in phase_l:
                        status = "complete"
                    elif agents == 0 and steps == 0 and study_id.startswith("e2e"):
                        status = "abandoned"
                        phase = phase or "E2E left mid-flight (no agents)"
                    elif agents and running == 0 and steps > 0 and "done" in phase_l:
                        status = "complete"
                payload.update(
                    {
                        "url": data.get("url"),
                        "segment": data.get("segment"),
                        "status": status,
                        "phase": phase,
                        "updated_at": data.get("updated_at"),
                        "agents": agents,
                        "steps": steps,
                        "running_agents": running,
                        "persona_count": len(data.get("personas") or []),
                        "task_count": len(data.get("tasks") or []),
                        "has_done": study_id in done_ids,
                    }
                )
        except Exception:
            pass
        if blob.updated is not None:
            payload.setdefault("updated_at", blob.updated.isoformat())
            payload["_sort"] = blob.updated.timestamp()
        else:
            payload["_sort"] = 0.0
        rows.append(payload)
    rows.sort(key=lambda r: float(r.get("_sort") or 0), reverse=True)
    for r in rows:
        r.pop("_sort", None)
    out = rows[: max(1, min(limit, 200))]
    _LIST_CACHE[cache_key] = (now, out)
    return out


def write_study_state(study_id: str, payload: dict[str, Any]) -> None:
    gcs_upload_json(f"{study_gcs_root(study_id)}/study.json", payload)


def read_study_state(study_id: str) -> dict[str, Any] | None:
    data = gcs_download_json(f"{study_gcs_root(study_id)}/study.json")
    return data if isinstance(data, dict) else None


def screenshot_gcs_uri(study_id: str, agent_id: str, filename: str) -> str:
    return f"{study_gcs_root(study_id)}/screenshots/{agent_id}/{filename}"

def hydrate_live_sessions_from_gcs(study_id: str, live_sessions: Any) -> Any:
    """Fill empty traces from per-agent GCS manifests so the UI can show screens
    even while the orchestrator is still provisioning other shards.
    """
    if not live_sessions:
        return live_sessions
    items: list[dict[str, Any]]
    as_dict = isinstance(live_sessions, dict)
    if as_dict:
        items = list(live_sessions.values())
    elif isinstance(live_sessions, list):
        items = live_sessions
    else:
        return live_sessions

    need = [
        s
        for s in items
        if isinstance(s, dict)
        and not (s.get("trace") or [])
        and (s.get("agent_id") or s.get("task_id"))
    ]
    if not need:
        return live_sessions

    cache_key = f"{study_id}:{len(need)}"
    cached = _HYDRATE_CACHE.get(cache_key)
    now = time.monotonic()
    if cached and now - cached[0] < 5.0:
        return cached[1]

    root = study_gcs_root(study_id)
    for sess in need:
        agent_id = sess.get("agent_id") or sess.get("task_id") or ""
        if not agent_id:
            continue
        manifest = gcs_download_json(f"{root}/live/{agent_id}/manifest.json")
        frames: list[dict[str, Any]] = []
        if isinstance(manifest, dict):
            frames = [f for f in (manifest.get("steps") or []) if isinstance(f, dict)]
        else:
            for step_no in range(0, 24):
                fr = gcs_download_json(f"{root}/live/{agent_id}/step_{step_no:03d}.json")
                if not isinstance(fr, dict):
                    break
                frames.append(fr)
        if not frames:
            continue
        sess["trace"] = frames
        sess["num_steps"] = len(frames)
        sess["status"] = "running" if sess.get("status") in {None, "", "starting", "pending"} else sess["status"]
        last = frames[-1]
        sess["last_action"] = last.get("action") or sess.get("last_action") or ""
    _HYDRATE_CACHE[cache_key] = (now, live_sessions)
    return live_sessions

