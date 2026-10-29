"""Warehouse writes for the Hacker News tables, same layout as pipeline/warehouse.py.

pipeline.warehouse shells out to gsutil, which needs a gcloud login. Cloud sessions only have the service-account JSON
that src/auth.py loads, so this writes the same Parquet parts with the Python storage client instead. Reads go through
pipeline.warehouse (DuckDB over the local cache), so W.query sees these tables too."""
from __future__ import annotations

import datetime as dt
import os
import sys
import uuid
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "experiments"))

BUCKET = "usersim-bakeoff-347838016394"
PREFIX = "usersim_sim/tables"
LOCAL = os.environ.get("USERSIM_CACHE", os.path.join(os.path.expanduser("~"), ".usersim_sim"))
TABLES = ("hn_posts", "hn_comments", "hn_people", "hn_snapshots", "sim_runs", "sim_comments", "judge_labels",
          "hn_scores", "spend")
_client = None


def _bucket():
    global _client
    if _client is None:
        from auth import vertex_credentials
        from google.cloud import storage
        _client = storage.Client(project=os.environ.get("GCP_PROJECT", "project-amer-scs-sandbox"),
                                 credentials=vertex_credentials())
    return _client.bucket(BUCKET)


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write(table: str, df: pd.DataFrame) -> str | None:
    """Append one part (local cache + Cloud Storage). Never rewrites old parts."""
    assert table in TABLES, table
    if df is None or not len(df):
        return None
    df = df.copy()
    if "updated_at" not in df:
        df["updated_at"] = now()
    part = f"{dt.datetime.now(dt.timezone.utc):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"
    os.makedirs(f"{LOCAL}/{table}", exist_ok=True)
    path = f"{LOCAL}/{table}/{part}.parquet"
    df.to_parquet(path, index=False)
    _bucket().blob(f"{PREFIX}/{table}/{part}.parquet").upload_from_filename(path)
    return path


def sync(tables=TABLES) -> None:
    """Pull parts of these tables that are not in the local cache yet."""
    b = _bucket()
    for t in tables:
        os.makedirs(f"{LOCAL}/{t}", exist_ok=True)
        for blob in b.client.list_blobs(b, prefix=f"{PREFIX}/{t}/"):
            dst = f"{LOCAL}/{t}/{blob.name.rsplit('/', 1)[1]}"
            if not os.path.exists(dst):
                blob.download_to_filename(dst)


def read(table: str, do_sync: bool = False) -> pd.DataFrame:
    if do_sync:
        sync((table,))
    d = Path(LOCAL) / table
    parts = sorted(d.glob("*.parquet")) if d.is_dir() else []
    return pd.concat([pd.read_parquet(p) for p in parts], ignore_index=True) if parts else pd.DataFrame()


def spend(step: str, usd: float, note: str, provider: str = "vertex") -> None:
    """Log money to the shared spend table (measured, never estimated)."""
    write("spend", pd.DataFrame([{"step": step, "provider": provider, "usd": float(usd), "note": note,
                                  "logged_on": dt.date.today().isoformat()}]))
