"""Small cached reader for gs://usersim-bakeoff-347838016394/usersim_sim/ (TTL cache per object / listing)."""
from __future__ import annotations

import io
import json
import os
import threading
import time
from typing import Any

BUCKET = os.environ.get("PH_SITE_BUCKET", "usersim-bakeoff-347838016394")
ROOT = os.environ.get("PH_SITE_PREFIX", "usersim_sim")
_cache: dict[str, tuple[float, Any]] = {}
_lock = threading.Lock()


def _bucket():
    from mvp.gcs_store import _storage_client

    return _storage_client().bucket(BUCKET)


def _cached(key: str, ttl: float, fn):
    now = time.time()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
    val = fn()
    with _lock:
        _cache[key] = (now, val)
    return val


def list_names(prefix: str, ttl: float = 120) -> list[tuple[str, str]]:
    """[(name relative to ROOT, updated iso)] under ROOT/prefix."""
    def go():
        out = []
        for b in _bucket().client.list_blobs(BUCKET, prefix=f"{ROOT}/{prefix}"):
            out.append((b.name[len(ROOT) + 1:], b.updated.isoformat() if b.updated else ""))
        return out
    return _cached("ls:" + prefix, ttl, go)


def read_bytes(path: str, ttl: float = 300) -> bytes | None:
    def go():
        b = _bucket().blob(f"{ROOT}/{path}")
        try:
            return b.download_as_bytes()
        except Exception as exc:  # noqa: BLE001 - missing object = None
            if "404" in str(exc) or "No such object" in str(exc):
                return None
            raise
    return _cached("b:" + path, ttl, go)


def read_json(path: str, ttl: float = 300) -> Any:
    raw = read_bytes(path, ttl)
    return None if raw is None else json.loads(raw)


def read_jsonl(path: str, ttl: float = 300) -> list[dict]:
    raw = read_bytes(path, ttl)
    if raw is None:
        return []
    return [json.loads(x) for x in raw.decode("utf-8").splitlines() if x.strip()]


def read_parquet_cols(path: str, cols: list[str], ttl: float = 300) -> dict[str, list] | None:
    """Columns as python lists (pyarrow only; pandas is not in the Vercel bundle)."""
    import pyarrow.parquet as pq

    raw = read_bytes(path, ttl)
    if raw is None:
        return None
    t = pq.read_table(io.BytesIO(raw), columns=cols)
    return {c: t.column(c).to_pylist() for c in cols}


def write_json_cas(path: str, update, retries: int = 6) -> Any:
    """Read-modify-write with generation match (used for the try-a-URL usage counters)."""
    from google.api_core.exceptions import PreconditionFailed, NotFound

    blob = _bucket().blob(f"{ROOT}/{path}")
    for _ in range(retries):
        try:
            blob.reload()
            gen = blob.generation
            cur = json.loads(blob.download_as_bytes(if_generation_match=gen))
        except NotFound:
            gen, cur = 0, {}
        new = update(cur)
        try:
            blob.upload_from_string(json.dumps(new), content_type="application/json", if_generation_match=gen)
            return new
        except PreconditionFailed:
            time.sleep(0.2)
    raise RuntimeError("usage counter busy")
