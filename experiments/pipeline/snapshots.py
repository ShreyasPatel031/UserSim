"""The one reader for hourly vote snapshots (the launch-day forecast uses this, never the raw table directly).
Deduplicated by default to one row per (launch_id, UTC hour), keeping the earliest snapshot in the hour: on Nov 1
2026 two recorders ran from 15:00 to 04:00 UTC and wrote every hour twice into the append-only warehouse table.
usage: from pipeline.snapshots import load; S = load()  (warehouse)   or load(files=[...jsonl])
Columns: day, at, hour (UTC hour, 'YYYY-MM-DDTHH'), hours_since_start, launch_id, name, votes, comments, rank_now,
fetched_at, late_min (late reads: hours_since_start corrected to the real read time; see fix_late)."""
import json
import pandas as pd


LATE_MIN = 2.0   # a row written this many minutes after its planned `at` is a late read


def fix_late(S):
    """`at` is the planned hour; the recorder writes `updated_at` right after the fetch. When a run is delayed (e.g. Nov 3
    22:00 UTC: rate-limited, slept 758 s, read at 22:12:39) the row still says 22:00. Adds fetched_at (= updated_at),
    late_min (fetched_at - at, minutes) and corrects hours_since_start to the real read time on late rows; `at` and
    `hour` stay the planned hour (the dedupe key)."""
    if "updated_at" not in S.columns:
        return S.assign(fetched_at=S["at"], late_min=0.0)
    at = pd.to_datetime(S["at"], utc=True, errors="coerce", format="ISO8601")
    fa = pd.to_datetime(S["updated_at"], utc=True, errors="coerce", format="ISO8601")
    late = ((fa - at).dt.total_seconds() / 60).fillna(0.0)
    S = S.assign(fetched_at=S["updated_at"], late_min=late.round(2))
    if "hours_since_start" in S.columns:
        hs = pd.to_numeric(S.hours_since_start, errors="coerce")
        S["hours_since_start"] = hs.where(late <= LATE_MIN, hs + late / 60).round(2)
    return S


def dedupe(S):
    S = S.assign(launch_id=S.launch_id.astype(str), hour=S["at"].astype(str).str[:13])
    return fix_late(S.sort_values("at").drop_duplicates(["launch_id", "hour"], keep="first").reset_index(drop=True))


def load(files=None, day_from=None, day_to=None, raw=False):
    if files:
        S = pd.DataFrame([json.loads(l) for f in files for l in open(f) if l.strip()])
    else:
        from . import warehouse as W
        S = W.query("SELECT * FROM vote_snapshots")
    if day_from:
        S = S[S.day >= day_from]
    if day_to:
        S = S[S.day <= day_to]
    return S if raw else dedupe(S)
