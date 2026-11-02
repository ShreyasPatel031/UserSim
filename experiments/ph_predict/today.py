"""Fetch the launches featured on a given (current) day into data/today/<date>.json — same fields as the
collector; their votes are not final and are never used as inputs."""
import json, os, sys, datetime as dt
from zoneinfo import ZoneInfo
import collect_ph as C

PT = ZoneInfo("America/Los_Angeles")   # Product Hunt's day: 00:00 Pacific, -07:00 in PDT and -08:00 in PST
d = dt.date.fromisoformat(sys.argv[1])
a = dt.datetime.combine(d, dt.time(0), PT).isoformat(); b = dt.datetime.combine(d + dt.timedelta(days=1), dt.time(0), PT).isoformat()
nodes, cur = [], None
while True:
    p, rem = C.gql({"a": a, "b": b, "c": cur}, C.Q_NEWEST)   # RANKING shifts while paging a live day
    nodes += [e["node"] for e in p["edges"]]
    if not p["pageInfo"]["hasNextPage"]:
        break
    cur = p["pageInfo"]["endCursor"]
seen = set(); nodes = [n for n in nodes if not (str(n["id"]) in seen or seen.add(str(n["id"])))]   # the list can shift while paging: keep each launch once
nodes = C.on_day(nodes, d)   # featured on this Pacific day only (the API window is on creation time)
os.makedirs(os.path.join(os.path.dirname(C.OUT), "today"), exist_ok=True)
json.dump(nodes, open(os.path.join(os.path.dirname(C.OUT), "today", f"{d}.json"), "w"))
print(d, len(nodes), "remaining", rem)
