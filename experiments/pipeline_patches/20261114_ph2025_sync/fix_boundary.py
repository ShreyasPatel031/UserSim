"""UNDEPLOYED. Applies collect_ph.on_day's rule to the history day lists (raw/ph_history/<year>/<day>.json, pulled by the Data Feeder with an
inclusive postedBefore): keep only posts whose featuredAt, in Pacific time, falls on the file's day. Writes filtered copies to <out dir>
(never in place) and prints counts per changed day. The 2026 store already applies on_day (collect_ph.py / today.py; dedupe_days.py fixed
the Apr-May files on Nov 2, originals kept in data/days_backup_dedupe/).
usage: python3 fix_boundary.py <in dir> <out dir>"""
import datetime as dt, glob, json, os, sys
from zoneinfo import ZoneInfo
PT = ZoneInfo("America/Los_Angeles"); src, out = sys.argv[1], sys.argv[2]; os.makedirs(out, exist_ok=True); ch = {}
for f in sorted(glob.glob(f"{src}/*.json")):
    d = dt.date.fromisoformat(os.path.basename(f)[:-5]); P = json.load(open(f))
    keep = [p for p in P if not p.get("featuredAt") or dt.datetime.fromisoformat(p["featuredAt"].replace("Z", "+00:00")).astimezone(PT).date() == d]
    if len(keep) != len(P):
        ch[str(d)] = {"before": len(P), "after": len(keep), "dropped_ranked": sum(1 for p in P if p not in keep and p.get("dailyRank"))}
    json.dump(keep, open(f"{out}/{os.path.basename(f)}", "w"))
print(json.dumps({"files": len(glob.glob(f"{src}/*.json")), "changed": ch}))
