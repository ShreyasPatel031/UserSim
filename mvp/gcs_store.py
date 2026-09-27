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

# Studies left "running" in GCS after Browserbase/process death look zombie in /live.
STALE_RUNNING_MIN = float(os.environ.get("MVP_STALE_RUNNING_MIN", "10"))


def clear_list_cache() -> None:
    _LIST_CACHE.clear()
    try:
        with _LIST_LOCK:
            _LIST_STATE.update({"at": 0.0, "rows": None, "limit": 0})
    except NameError:
        pass


def _parse_iso(ts: str | None):
    if not ts:
        return None
    from datetime import datetime, timezone

    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None


def normalize_study_display(data: dict[str, Any]) -> dict[str, Any]:
    """Fix zombie running status for UI (GCS leftovers after kill / crash)."""
    if not isinstance(data, dict):
        return data
    out = dict(data)
    status = str(out.get("status") or "")
    if status not in {"running", "pending", "queued"}:
        return out
    if out.get("kill_requested"):
        out["status"] = "abandoned"
        out["phase"] = out.get("phase") if out.get("phase") == "Killed" else "Killed"
        return out

    from datetime import datetime, timezone

    updated = _parse_iso(out.get("updated_at"))
    if updated is not None:
        age_min = (datetime.now(timezone.utc) - updated).total_seconds() / 60.0
        if age_min >= STALE_RUNNING_MIN:
            out["status"] = "abandoned"
            out["phase"] = f"Stale (no updates for {int(age_min)}m)"
            live = out.get("live_sessions")
            if isinstance(live, dict):
                for sess in live.values():
                    if isinstance(sess, dict) and sess.get("status") in {
                        "running",
                        "starting",
                        "pending",
                        "summarizing",
                    }:
                        sess["status"] = "killed"
            elif isinstance(live, list):
                for sess in live:
                    if isinstance(sess, dict) and sess.get("status") in {
                        "running",
                        "starting",
                        "pending",
                        "summarizing",
                    }:
                        sess["status"] = "killed"
    return out


def abandon_running_studies_in_gcs(
    *,
    study_id: str | None = None,
    study_ids: list[str] | None = None,
    limit: int = 80,
) -> list[str]:
    """Persist abandoned status onto GCS study.json for killed/zombie runs.

    Prefer an explicit ``study_ids`` snapshot from kill time. Re-listing all
    "running" studies races newly started runs and falsely marks them killed.
    """
    from datetime import datetime, timezone

    abandoned: list[str] = []
    now = datetime.now(timezone.utc).isoformat()
    ids: list[str] = []
    if study_ids is not None:
        ids = [str(x) for x in study_ids if x]
    elif study_id:
        ids = [study_id]
    else:
        # Legacy fallback — still snapshot the list once up front.
        rows = list_mvp_studies(limit=limit)
        clear_list_cache()
        ids = [str(r.get("id") or "") for r in rows if r.get("id")]

    for sid in ids:
        if not sid:
            continue
        data = read_study_state(sid)
        if not isinstance(data, dict):
            continue
        status = str(data.get("status") or "")
        if status not in {"running", "pending", "queued"} and not data.get("kill_requested"):
            continue
        data["kill_requested"] = True
        data["status"] = "abandoned"
        data["phase"] = "Killed"
        data["error"] = data.get("error") or "Killed by operator"
        data["updated_at"] = now
        live = data.get("live_sessions")
        if isinstance(live, dict):
            for sess in live.values():
                if isinstance(sess, dict) and sess.get("status") in {
                    "running",
                    "starting",
                    "pending",
                    "summarizing",
                }:
                    sess["status"] = "killed"
        elif isinstance(live, list):
            for sess in live:
                if isinstance(sess, dict) and sess.get("status") in {
                    "running",
                    "starting",
                    "pending",
                    "summarizing",
                }:
                    sess["status"] = "killed"
            data["live_sessions"] = {
                str(s.get("agent_id") or i): s for i, s in enumerate(live) if isinstance(s, dict)
            }
        try:
            write_study_state(sid, data)
            abandoned.append(sid)
        except Exception as exc:  # noqa: BLE001
            print(f"abandon gcs {sid}: {exc}", flush=True)
    clear_list_cache()
    return abandoned

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


def study_summary_row(study_id: str, data: dict[str, Any], *, done: bool = False) -> dict[str, Any]:
    """One /live list row from a study payload (no live_sessions, a few hundred bytes)."""
    payload: dict[str, Any] = {"id": study_id}
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
    if done and status in {"running", "pending"}:
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
            "has_done": bool(done or status == "complete"),
            "kill_requested": bool(data.get("kill_requested")),
        }
    )
    return payload


def _display_row(row: dict[str, Any]) -> dict[str, Any]:
    out = normalize_study_display(dict(row))
    if out.get("status") == "abandoned":
        out["running_agents"] = 0
    return out


# id -> (study.json generation, summary row). Finished studies never change, so
# after the first pass a list costs one metadata listing and zero downloads.
_SUMMARY_CACHE: dict[str, tuple[Any, dict[str, Any]]] = {}
_LIST_STATE: dict[str, Any] = {"at": 0.0, "rows": None, "limit": 0, "refreshing": False}
_LIST_LOCK = __import__("threading").Lock()
_LIST_FRESH_S = 8.0
_LIST_SERVE_STALE_S = 300.0


def _glob_blobs(client: Any, bucket_name: str, prefix: str, leaf: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for blob in client.list_blobs(bucket_name, prefix=prefix, match_glob=f"{prefix}*/{leaf}"):
        parts = (blob.name or "")[len(prefix) :].split("/")
        if len(parts) == 2 and parts[1] == leaf:
            out[parts[0]] = blob
    return out


def _summary_for(study_id: str, blob: Any, summary_blob: Any | None, done: bool) -> dict[str, Any]:
    gen = getattr(blob, "generation", None) or getattr(blob, "updated", None)
    cached = _SUMMARY_CACHE.get(study_id)
    if cached is not None and cached[0] == gen:
        return cached[1]
    row: dict[str, Any] | None = None
    fresh_summary = (
        summary_blob is not None
        and getattr(summary_blob, "updated", None) is not None
        and getattr(blob, "updated", None) is not None
        and summary_blob.updated.timestamp() >= blob.updated.timestamp() - 5
    )
    if fresh_summary:
        try:
            data = json.loads(summary_blob.download_as_bytes().decode("utf-8"))
            if isinstance(data, dict) and data.get("id") == study_id:
                row = data
        except Exception:
            row = None
    if row is None:
        # No (or an older) summary.json: read study.json once and backfill the summary.
        row = {"id": study_id}
        try:
            data = json.loads(blob.download_as_bytes().decode("utf-8"))
            if isinstance(data, dict):
                row = study_summary_row(study_id, data, done=done)
                try:
                    gcs_upload_json(f"{study_gcs_root(study_id)}/summary.json", row)
                except Exception:
                    pass
        except Exception:
            pass
    if done:
        row = {**row, "has_done": True}
        if row.get("status") in {"running", "pending"}:
            row["status"] = "complete"
            row["phase"] = row.get("phase") or "Complete"
    if blob.updated is not None:
        row.setdefault("updated_at", blob.updated.isoformat())
    _SUMMARY_CACHE[study_id] = (gen, row)
    return row


def _build_study_list(limit: int) -> list[dict[str, Any]]:
    from concurrent.futures import ThreadPoolExecutor

    bucket_name, prefix = parse_gs_uri(f"{DEFAULT_GCS}/mvp_studies/")
    if not prefix.endswith("/"):
        prefix += "/"
    client = _storage_client()
    with ThreadPoolExecutor(max_workers=3) as pool:
        f_study = pool.submit(_glob_blobs, client, bucket_name, prefix, "study.json")
        f_summary = pool.submit(_glob_blobs, client, bucket_name, prefix, "summary.json")
        f_done = pool.submit(_glob_blobs, client, bucket_name, prefix, "done.json")
        studies = f_study.result()
        try:
            summaries = f_summary.result()
        except Exception:
            summaries = {}
        try:
            done_ids = set(f_done.result())
        except Exception:
            done_ids = set()
    ordered = sorted(
        studies.items(),
        key=lambda kv: kv[1].updated.timestamp() if kv[1].updated is not None else 0.0,
        reverse=True,
    )[: max(1, min(limit, 200))]
    with ThreadPoolExecutor(max_workers=16) as pool:
        rows = list(
            pool.map(
                lambda kv: _summary_for(kv[0], kv[1], summaries.get(kv[0]), kv[0] in done_ids),
                ordered,
            )
        )
    return [_display_row(r) for r in rows]


def _refresh_study_list(limit: int) -> list[dict[str, Any]]:
    rows = _build_study_list(limit)
    with _LIST_LOCK:
        _LIST_STATE.update({"at": time.monotonic(), "rows": rows, "limit": limit, "refreshing": False})
    return rows


def list_mvp_studies(*, limit: int = 40) -> list[dict[str, Any]]:
    """Recent studies under mvp_studies/*/study.json, newest first, as small summary rows.

    Lists only study.json / summary.json / done.json metadata (glob), then reads
    each study's small summary.json (written with every study.json). The old
    path listed every blob under mvp_studies/ (screenshots included) and
    downloaded every ~2MB study.json one by one, so /api/studies hit its 20s
    timeout. A recent list is served at once while a background refresh runs.
    """
    import threading

    now = time.monotonic()
    with _LIST_LOCK:
        rows = _LIST_STATE.get("rows")
        age = now - float(_LIST_STATE.get("at") or 0.0)
        enough = rows is not None and int(_LIST_STATE.get("limit") or 0) >= limit
        if enough and age < _LIST_FRESH_S:
            return rows[: max(1, min(limit, 200))]
        if enough and age < _LIST_SERVE_STALE_S:
            if not _LIST_STATE.get("refreshing"):
                _LIST_STATE["refreshing"] = True
                want = max(limit, int(_LIST_STATE.get("limit") or 0))

                def _bg() -> None:
                    try:
                        _refresh_study_list(want)
                    except Exception as exc:  # noqa: BLE001
                        print(f"study list refresh failed: {exc!r}", flush=True)
                        with _LIST_LOCK:
                            _LIST_STATE["refreshing"] = False

                threading.Thread(target=_bg, daemon=True).start()
            return rows[: max(1, min(limit, 200))]
    return _refresh_study_list(limit)[: max(1, min(limit, 200))]


def write_study_state(study_id: str, payload: dict[str, Any]) -> None:
    gcs_upload_json(f"{study_gcs_root(study_id)}/study.json", payload)
    # A small row for /api/studies so the list never downloads full study blobs.
    try:
        gcs_upload_json(f"{study_gcs_root(study_id)}/summary.json", study_summary_row(study_id, payload))
    except Exception as exc:  # noqa: BLE001
        print(f"summary write failed for {study_id}: {exc!r}", flush=True)


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
        if not frames:
            for step_no in range(0, 24):
                fr = gcs_download_json(f"{root}/live/{agent_id}/step_{step_no}.json")
                if not isinstance(fr, dict):
                    break
                frames.append(fr)
        if not frames:
            for name in ("step_0.png", "bbox_0.png"):
                raw = gcs_download_bytes(screenshot_gcs_uri(study_id, agent_id, name))
                if raw and len(raw) > 200:
                    frames = [
                        {
                            "step": 0,
                            "action": "Opened page",
                            "observation": "Landing page screenshot",
                            "screenshot_url": (
                                f"/api/studies/{study_id}/agents/{agent_id}/screenshots/{name}"
                            ),
                        }
                    ]
                    break
        if not frames:
            continue
        sess["trace"] = frames
        sess["num_steps"] = len(frames)
        sess["status"] = "running" if sess.get("status") in {None, "", "starting", "pending"} else sess["status"]
        last = frames[-1]
        sess["last_action"] = last.get("action") or sess.get("last_action") or ""
    _HYDRATE_CACHE[cache_key] = (now, live_sessions)
    return live_sessions

