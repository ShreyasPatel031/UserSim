"""Resolve Product Hunt API bearer token from env or Secret Manager (never log the value)."""
from __future__ import annotations

import os
import subprocess


def _normalize_token(raw: str) -> str:
    t = (raw or "").strip()
    if not t:
        return ""
    if t.startswith("PH_TOKEN=") or t.startswith("PH_API_TOKEN="):
        return t.split("=", 1)[1].strip().strip('"').strip("'")
    return t


def api_token() -> str:
    t = _normalize_token(os.environ.get("PH_API_TOKEN") or os.environ.get("PH_API_DEV_TOKEN") or "")
    if t:
        return t
    secret = os.environ.get("PH_TOKEN_SECRET", "PH_API_TOKEN")
    proj = os.environ.get("GCP_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT") or ""
    cmd = ["gcloud", "secrets", "versions", "access", "latest", "--secret", secret]
    if proj:
        cmd.extend(["--project", proj])
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"PH API token: env unset and Secret Manager {secret} failed")
    raw = r.stdout
    for ln in raw.splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        if ln.startswith("PH_TOKEN=") or ln.startswith("PH_API_TOKEN="):
            return _normalize_token(ln)
    tok = _normalize_token(raw)
    if not tok:
        raise SystemExit(f"PH API token: empty secret {secret}")
    return tok