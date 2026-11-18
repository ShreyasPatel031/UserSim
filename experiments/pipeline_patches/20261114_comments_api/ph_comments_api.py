"""Comments from the official Product Hunt API v2 (UNDEPLOYED fallback for the comments step while the page route is down).
Diagnosis 13:15Z Nov 14: since the Nov 12 run the DataImpulse proxy answers 407 (Proxy Authentication Required) for every host, so
every comment page (and every sites link) fails; the direct route gets a 139-byte block page. The API needs no proxy (PH_TOKEN).
Limits: the API redacts commenters (user id / username empty on 3 of 3 probed), so this gives per-launch comment COUNTS, timestamps,
reply structure and comment votes, but NOT people: the warehouse `comments` / `events` person rows and the people step's new-people list
cannot be filled from it. comment_forecast's nc (comment count) can; nu (distinct commenters) and team matching cannot.
usage: PH_TOKEN=... python3 ph_comments_api.py <slugs file> <out.jsonl>  -> one line per launch {slug, commentsCount, comments:[{id, created,
parent, votes}]}; paginated 50 per call; respects the API rate-limit headers (sleeps to reset when remaining < 200)."""
import json, os, sys, time, urllib.request

URL = "https://api.producthunt.com/v2/api/graphql"
Q = """query($s:String,$after:String){post(slug:$s){commentsCount comments(first:50,after:$after){pageInfo{hasNextPage endCursor}
edges{node{id createdAt votesCount parentId replies(first:50){edges{node{id createdAt votesCount}}}}}}}}"""


def call(v):
    req = urllib.request.Request(URL, json.dumps({"query": Q, "variables": v}).encode(),
                                 {"Authorization": "Bearer " + os.environ["PH_TOKEN"], "Content-Type": "application/json", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        rem = int(r.headers.get("X-Rate-Limit-Remaining", "9999")); reset = int(r.headers.get("X-Rate-Limit-Reset", "0"))
        body = json.loads(r.read())
    if rem < 200:
        time.sleep(reset + 5)
    return body


def one(slug):
    out, after, n = [], None, None
    for _ in range(40):
        b = call({"s": slug, "after": after}); p = (b.get("data") or {}).get("post")
        if not p:
            return {"slug": slug, "error": str(b.get("errors"))[:200]}
        n = p["commentsCount"]; c = p["comments"]
        for e in c["edges"]:
            x = e["node"]; out.append({"id": x["id"], "created": x["createdAt"], "parent": x.get("parentId"), "votes": x.get("votesCount")})
            out += [{"id": r["node"]["id"], "created": r["node"]["createdAt"], "parent": x["id"], "votes": r["node"].get("votesCount")}
                    for r in (x.get("replies") or {}).get("edges", [])]
        if not c["pageInfo"]["hasNextPage"]:
            break
        after = c["pageInfo"]["endCursor"]
    return {"slug": slug, "commentsCount": n, "comments": out}


if __name__ == "__main__":
    slugs = [l.strip() for l in open(sys.argv[1]) if l.strip()]
    with open(sys.argv[2], "w") as f:
        for s in slugs:
            f.write(json.dumps(one(s)) + "\n")
    print(json.dumps({"launches": len(slugs)}))
