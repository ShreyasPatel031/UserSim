"""stdin: vm_scroll.py JSON lines for /@user/upvotes pages -> stdout: {username, status, scrolls, upvotes: [post ids]}
(all upvoted posts the page loaded while scrolling, newest first; raw page and responses not kept)."""
import json, re, sys

for l in sys.stdin:
    try:
        r = json.loads(l)
    except ValueError:
        continue
    u = r["url"].rsplit("/@", 1)[-1].split("/")[0]
    ids = []
    m = re.search(r'"votedPosts":\{"__typename":"PostConnection","edges":', r.get("html") or "")
    if m:
        conn, _ = json.JSONDecoder().raw_decode(r["html"], m.start() + len('"votedPosts":'))
        ids += [e["node"]["id"] for e in conn.get("edges") or []]

    def walk(o):
        if isinstance(o, dict):
            vp = o.get("votedPosts")
            if isinstance(vp, dict):
                ids.extend(e["node"]["id"] for e in vp.get("edges") or [] if e.get("node"))
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    for resp in r.get("responses") or []:
        walk(resp.get("body"))
    seen, out = set(), []
    for i in ids:
        if i not in seen:
            seen.add(i); out.append(i)
    print(json.dumps({"username": u, "status": r.get("status"), "scrolls": r.get("scrolls"), "error": r.get("error"), "upvotes": out}), flush=True)
