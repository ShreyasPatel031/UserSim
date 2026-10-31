"""Fetch the launches featured on a given (current) day into data/today/<date>.json — same fields as the
collector; their votes are not final and are never used as inputs."""
import json, os, sys, datetime as dt
import collect_ph as C

d = dt.date.fromisoformat(sys.argv[1])
a, b = f"{d}T00:00:00-07:00", f"{d + dt.timedelta(days=1)}T00:00:00-07:00"
nodes, cur = [], None
while True:
    p, rem = C.gql({"a": a, "b": b, "c": cur})
    nodes += [e["node"] for e in p["edges"]]
    if not p["pageInfo"]["hasNextPage"]:
        break
    cur = p["pageInfo"]["endCursor"]
seen = set(); nodes = [n for n in nodes if not (str(n["id"]) in seen or seen.add(str(n["id"])))]   # the list can shift while paging: keep each launch once
os.makedirs(os.path.join(os.path.dirname(C.OUT), "today"), exist_ok=True)
json.dump(nodes, open(os.path.join(os.path.dirname(C.OUT), "today", f"{d}.json"), "w"))
print(d, len(nodes), "remaining", rem)
