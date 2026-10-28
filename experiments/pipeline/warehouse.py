"""The UserSim / Atelier warehouse: cleaned, append-only Parquet tables in Cloud Storage, queried with DuckDB.

Layout (see DATA.md for every table's columns):
  gs://usersim-bakeoff-347838016394/usersim_sim/tables/<table>/<part>.parquet
  - snapshot tables (people, launches, fetch_state, ...) hold one part per write; readers take the newest row per key
  - log tables (events, comments, forecasts, spend, pipeline_runs, ...) append one part per run, never rewritten
  gs://.../usersim_sim/raw/   immutable copies of raw fetches, by source and date

Any agent:  python -m pipeline.q "SELECT kind, count(*) FROM events GROUP BY 1"
In code:    from pipeline import warehouse as W; W.write("spend", df); W.query("SELECT ...")"""
import datetime as dt, os, subprocess, uuid
import duckdb, pandas as pd

BUCKET = os.environ.get("USERSIM_BUCKET", "gs://usersim-bakeoff-347838016394/usersim_sim")
LOCAL = os.environ.get("USERSIM_CACHE", os.path.join(os.path.expanduser("~"), ".usersim_sim"))
KEYS = {   # snapshot tables: newest row per key wins (column `updated_at`)
    "people": ["person"], "launches": ["id"], "fetch_state": ["person", "source"], "launch_state": ["launch_id", "source"],
}


def _gs(*args):
    return subprocess.run(["gsutil", "-q", "-m", *args], check=True, capture_output=True, text=True)


def write(table, df, part=None):
    """Append one part to a table (local cache + Cloud Storage). Adds updated_at if missing."""
    if df is None or not len(df):
        return None
    df = df.copy()
    if "updated_at" not in df:
        df["updated_at"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    part = part or f"{dt.datetime.now(dt.timezone.utc):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"
    os.makedirs(f"{LOCAL}/{table}", exist_ok=True)
    path = f"{LOCAL}/{table}/{part}.parquet"
    df.to_parquet(path, index=False)
    _gs("cp", path, f"{BUCKET}/tables/{table}/{part}.parquet")
    return path


def sync():
    """Pull every table from Cloud Storage into the local cache (only new or changed parts)."""
    os.makedirs(LOCAL, exist_ok=True)
    _gs("rsync", "-r", f"{BUCKET}/tables", LOCAL)


def connect(do_sync=True):
    """DuckDB connection with one view per table; snapshot tables are deduplicated to their newest row per key."""
    if do_sync:
        sync()
    con = duckdb.connect()
    for t in sorted(os.listdir(LOCAL)) if os.path.isdir(LOCAL) else []:
        if not any(f.endswith(".parquet") for f in os.listdir(f"{LOCAL}/{t}")):
            continue
        src = f"read_parquet('{LOCAL}/{t}/*.parquet', union_by_name=true)"
        if t in KEYS:
            k = ", ".join(KEYS[t])
            con.execute(f"CREATE VIEW {t} AS SELECT * EXCLUDE (_rn) FROM (SELECT *, row_number() OVER "
                        f"(PARTITION BY {k} ORDER BY updated_at DESC) AS _rn FROM {src}) WHERE _rn = 1")
        else:
            con.execute(f"CREATE VIEW {t} AS SELECT * FROM {src}")
    return con


def query(sql, do_sync=True):
    return connect(do_sync).execute(sql).df()


def table(name, do_sync=False):
    return query(f"SELECT * FROM {name}", do_sync)
