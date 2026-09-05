"""GCS helpers for MVP fleet studies — client-library based (works on Vercel)."""

from __future__ import annotations

import json
import os
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

DEFAULT_GCS = os.environ.get(
    "MVP_GCS_PREFIX",
    os.environ.get("GCS_PREFIX", "gs://usersim-bakeoff-347838016394"),
).rstrip("/")


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


def write_study_state(study_id: str, payload: dict[str, Any]) -> None:
    gcs_upload_json(f"{study_gcs_root(study_id)}/study.json", payload)


def read_study_state(study_id: str) -> dict[str, Any] | None:
    data = gcs_download_json(f"{study_gcs_root(study_id)}/study.json")
    return data if isinstance(data, dict) else None


def screenshot_gcs_uri(study_id: str, agent_id: str, filename: str) -> str:
    return f"{study_gcs_root(study_id)}/screenshots/{agent_id}/{filename}"
