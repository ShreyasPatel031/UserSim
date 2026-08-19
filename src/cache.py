"""Disk cache for Vertex calls so v0.5 reruns do not rebill."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from config import RESULTS_DIR

CACHE_DIR = RESULTS_DIR / "cache" / "v05"


def cache_key(payload: dict) -> str:
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def get(payload: dict) -> dict | None:
    path = CACHE_DIR / f"{cache_key(payload)}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def put(payload: dict, value: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{cache_key(payload)}.json"
    path.write_text(json.dumps(value, ensure_ascii=True))
