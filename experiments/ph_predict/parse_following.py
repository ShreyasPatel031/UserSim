"""stdin: vmfetch JSON lines of /@user/following pages -> stdout: one small record per person (no raw page kept).
{username, followings, following: [[username, followersCount], ...] (first page, up to 20), has_more, status}"""
import json, re, sys

KEY = re.compile(r'"profile":\{"__typename":"User","id":"(\d+)","isTrashed":\w+,"followingsCount":(\d+),"following":')
for l in sys.stdin:
    try:
        r = json.loads(l)
    except ValueError:
        continue
    u = r["url"].rsplit("/@", 1)[-1].split("/")[0]
    h = r.get("html") or ""
    out = {"username": u, "status": r.get("status"), "route": r.get("route"), "bytes": len(h)}
    m = KEY.search(h)
    if m:
        dec = json.JSONDecoder()
        conn, _ = dec.raw_decode(h, m.end())
        out.update(followings=int(m.group(2)), has_more=conn["pageInfo"]["hasNextPage"],
                   following=[[e["node"]["username"], e["node"].get("followersCount")] for e in conn["edges"]])
    print(json.dumps(out), flush=True)
