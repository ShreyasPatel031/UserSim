"""The one reader for hourly vote snapshots (the launch-day forecast uses this, never the raw table directly).
Deduplicated by default to one row per (launch_id, UTC hour), keeping the earliest snapshot in the hour: on Nov 1
2026 two recorders ran from 15:00 to 04:00 UTC and wrote every hour twice into the append-only warehouse table.
usage: from pipeline.snapshots import load; S = load()  (warehouse)   or load(files=[...jsonl])
Columns: day, at, hour (UTC hour, 'YYYY-MM-DDTHH'), hours_since_start, launch_id, name, votes, comments, rank_now."""
import json
import pandas as pd


def dedupe(S):
    S = S.assign(launch_id=S.launch_id.astype(str), hour=S["at"].astype(str).str[:13])
    return S.sort_values("at").drop_duplicates(["launch_id", "hour"], keep="first").reset_index(drop=True)


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
