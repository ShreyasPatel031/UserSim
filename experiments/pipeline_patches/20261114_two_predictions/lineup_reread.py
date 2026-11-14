"""01:00 PT line-up re-read (UNDEPLOYED, bundle 12a; Shreyas's word first). The same official-API query today.py runs at 00:05 (featured,
newest, the PT day's window, on_day filter, dedup), saved to the bundle's own dir and to gs://.../raw/daily/<d>/lineup_0100.json next to
the 00:05 line-up (today_0005.json). Read-only; changes no pipeline file and no published file (never writes data/today/).
Adds {fetched_at, n, missing_vs_0005, new_vs_0005} to the log line so late-featured launches are visible.
usage (VM, cwd ~/w/experiments/ph_predict on sys.path, PH_TOKEN in env): python3 lineup_reread.py [YYYY-MM-DD]"""
import datetime as dt, json, os, subprocess, sys
from zoneinfo import ZoneInfo
sys.path.insert(0, "/home/agent/w/experiments/ph_predict")
import collect_ph as C
PT = ZoneInfo("America/Los_Angeles"); B = "gs://usersim-bakeoff-347838016394/usersim_sim"
d = dt.date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else dt.datetime.now(PT).date()
a = dt.datetime.combine(d, dt.time(0), PT).isoformat(); b = dt.datetime.combine(d + dt.timedelta(days=1), dt.time(0), PT).isoformat()
nodes, cur = [], None
while True:
    p, rem = C.gql({"a": a, "b": b, "c": cur}, C.Q_NEWEST)
    nodes += [e["node"] for e in p["edges"]]
    if not p["pageInfo"]["hasNextPage"]:
        break
    cur = p["pageInfo"]["endCursor"]
seen = set(); nodes = [n for n in nodes if not (str(n["id"]) in seen or seen.add(str(n["id"])))]
nodes = C.on_day(nodes, d)
out = {"day": str(d), "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "n": len(nodes), "nodes": nodes}
od = "/home/agent/w/tw12a/lineups"; os.makedirs(od, exist_ok=True); p_ = f"{od}/{d}_0100.json"; json.dump(out, open(p_, "w"))
subprocess.run(["gsutil", "-q", "cp", p_, f"{B}/raw/daily/{d}/lineup_0100.json"], check=True)
t0 = f"/home/agent/w/experiments/ph_predict/data/today/{d}.json"
ids0 = {str(n["id"]) for n in json.load(open(t0))} if os.path.exists(t0) else set(); ids1 = {str(n["id"]) for n in nodes}
print(json.dumps({"day": str(d), "n": len(nodes), "n_0005": len(ids0), "new_vs_0005": len(ids1 - ids0), "missing_vs_0005": len(ids0 - ids1), "api_remaining": rem}))
