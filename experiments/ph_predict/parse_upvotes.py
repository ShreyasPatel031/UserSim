"""stdin: vmfetch JSON lines of /@user/upvotes pages -> stdout: one small record per person (raw page not kept).
{username, status, route, votes_total, has_more, end_cursor, upvotes: [post ids, newest first (first page, up to 20)]}"""
import json, re, sys

KEY = re.compile(r'"votedPosts":\{"__typename":"PostConnection","edges":')
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
        conn, _ = json.JSONDecoder().raw_decode(h, m.start() + len('"votedPosts":'))
        out.update(upvotes=[e["node"]["id"] for e in conn.get("edges") or []],
                   has_more=(conn.get("pageInfo") or {}).get("hasNextPage"), end_cursor=(conn.get("pageInfo") or {}).get("endCursor"))
        t = re.search(r'"votesCount":(\d+)', h)
        out["votes_total"] = int(t.group(1)) if t else None
    print(json.dumps(out), flush=True)
