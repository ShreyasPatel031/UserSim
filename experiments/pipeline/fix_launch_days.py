"""One-off: warehouse `launches` rows whose day differs from the launch's featuredAt Pacific day (204 launches from
Apr 27 - May 13 were stored on the day before). Appends corrected rows (snapshot table: the newest row per id wins).
The `events` log is append-only: upvote events for these launches stay dated by the old day (one day early); this is
recorded, not rewritten. Prints counts.
usage: python -m pipeline.fix_launch_days [--dry]"""
import glob, json, os, sys
import pandas as pd
from . import warehouse as W

HERE = os.path.dirname(os.path.abspath(__file__)); D = os.path.join(os.path.dirname(HERE), "ph_predict", "data", "days")
dry = "--dry" in sys.argv
canon = {}
for f in glob.glob(f"{D}/*.json"):
    for p in json.load(open(f)):
        if p.get("featuredAt"):
            canon[str(p["id"])] = pd.Timestamp(p["featuredAt"]).tz_convert("America/Los_Angeles").strftime("%Y-%m-%d")
L = W.query("SELECT * FROM launches")
L["id"] = L.id.astype(str)
bad = L[L.id.map(canon).notna() & (L.day != L.id.map(canon))].copy()
ev = W.query("SELECT count(*) n FROM events WHERE kind = 'upvote' AND CAST(launch_id AS VARCHAR) IN ({})".format(",".join(f"'{i}'" for i in bad.id) or "''")).n[0] if len(bad) else 0
print(json.dumps({"launch_rows_on_wrong_day": int(len(bad)), "upvote_events_dated_by_old_day": int(ev), "dry": dry}))
if len(bad) and not dry:
    bad["day"] = bad.id.map(canon)
    W.write("launches", bad.drop(columns=[c for c in ("updated_at",) if c in bad]))
