"""Public GitHub activity for self-linked handles (standing rule 1: free API, own VM, no login, polite, honour limits).
Input: a handle list file (GCS raw/population/requests/github_handles.txt, one per line; never committed).
Output (append, resumable): OUT_DIR/profiles.jsonl {handle, status, fetched_at, created_at, followers, following, public_repos}
                            OUT_DIR/events.jsonl   {handle, id, type, repo, created_at, fetched_at}
Unauthenticated limit is 60 requests/hour: 2 calls/person (profile + events page 1, up to 100 events, last 90 days) -> ~30 people/h.
Usage: python github_events.py HANDLES OUT_DIR
"""
import json, os, sys, time, urllib.error, urllib.request
from datetime import datetime, timezone

H, OUT = sys.argv[1], sys.argv[2]
os.makedirs(OUT, exist_ok=True)
UA = {"User-Agent": "usersim-research-population", "Accept": "application/vnd.github+json"}
now = lambda: datetime.now(timezone.utc).isoformat()


def get(url):
    while True:
        req = urllib.request.Request(url, headers=UA)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                rem, reset = int(r.headers.get("X-RateLimit-Remaining", 1)), int(r.headers.get("X-RateLimit-Reset", 0))
                body = json.load(r)
                if rem == 0:
                    time.sleep(max(0, reset - time.time()) + 5)
                return 200, body
        except urllib.error.HTTPError as e:
            if e.code in (403, 429) and (e.headers.get("Retry-After") or e.headers.get("X-RateLimit-Remaining") == "0"):
                wait = int(e.headers.get("Retry-After") or max(0, int(e.headers.get("X-RateLimit-Reset", 0)) - time.time()) + 5)
                print(f"rate limited, sleeping {wait}s", flush=True)
                time.sleep(wait)
                continue
            return e.code, None


done = set()
if os.path.exists(f"{OUT}/profiles.jsonl"):
    done = {json.loads(l)["handle"] for l in open(f"{OUT}/profiles.jsonl")}
handles = [h.strip().lower() for h in open(H) if h.strip()]
for h in handles:
    if h in done:
        continue
    st, p = get(f"https://api.github.com/users/{h}")
    row = {"handle": h, "status": st, "fetched_at": now()}
    if p:
        row.update({k: p.get(k) for k in ("created_at", "followers", "following", "public_repos", "type")})
    evs = []
    if st == 200:
        st2, evs = get(f"https://api.github.com/users/{h}/events/public?per_page=100")
        row["events_status"] = st2
        evs = evs or []
        f = now()
        with open(f"{OUT}/events.jsonl", "a") as o:
            for e in evs:
                o.write(json.dumps({"handle": h, "id": e.get("id"), "type": e.get("type"), "repo": (e.get("repo") or {}).get("name"),
                                    "created_at": e.get("created_at"), "fetched_at": f}) + "\n")
    row["events"] = len(evs)
    with open(f"{OUT}/profiles.jsonl", "a") as o:
        o.write(json.dumps(row) + "\n")
    time.sleep(1)
print("done", len(handles))
