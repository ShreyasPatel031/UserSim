"""X ties pilot: did a launch's real Product Hunt voters interact with its makers on X in the 60 days before launch,
more than people active on Product Hunt that day who did not vote for it? Public posts only, no login (fxtwitter,
VM's own IP, route 1 of the fetch ladder). An X tie between a person and a maker, either way round, in the window:
  reply     one replied to the other
  quote     one quoted the other's post
  repost    one reposted the other's post
  mention   one @-mentioned the other in a post
Input: jobs JSON (launch, day, makers' X handles, voters and control people with their X handles, from Product Hunt
profile links). Fetch: each handle's recent posts once (up to 10 pages back to the earliest window start).
usage: python -m simlab.x_pilot fetch jobs.json posts.jsonl [threads] ; python -m simlab.x_pilot report jobs.json posts.jsonl
       [ties.json] -> reports/x_pilot.json"""
import json, os, re, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
UA = {"User-Agent": "usersim research"}
WINDOW = 60
lock = threading.Lock()


def get(url):
    for i in range(4):
        try:
            r = requests.get(url, headers=UA, timeout=30)
            if r.status_code == 429:
                time.sleep(20 * (i + 1)); continue
            return r.json() if r.status_code == 200 else None
        except Exception:  # noqa: BLE001
            time.sleep(3)
    return None


def targets(p):
    """Accounts this post interacts with, by kind (lowercase handles)."""
    out = set()
    a = ((p.get("author") or {}).get("screen_name") or "").lower()
    if p.get("reposted_by") and a:
        out.add(("repost", a))
    if (p.get("replying_to") or {}).get("screen_name"):
        out.add(("reply", p["replying_to"]["screen_name"].lower()))
    q = ((p.get("quote") or {}).get("author") or {}).get("screen_name")
    if q:
        out.add(("quote", q.lower()))
    for m in re.findall(r"@([A-Za-z0-9_]{1,15})", p.get("text") or ""):
        out.add(("mention", m.lower()))
    return sorted(out)


def fetch_one(job, f):
    h, since = job
    posts, reached, cursor = [], False, ""
    for _ in range(10):
        d = get(f"https://api.fxtwitter.com/2/profile/{h}/statuses" + (f"?cursor={cursor}" if cursor else ""))
        if not d or not d.get("results"):
            reached = True if d is not None else reached
            break
        oldest = None
        for p in d["results"]:
            try:
                ts = parsedate_to_datetime(p["created_at"]).strftime("%Y-%m-%d")
            except Exception:  # noqa: BLE001
                continue
            oldest = ts
            posts.append({"date": ts, "t": targets(p)})
        if oldest and oldest < since:
            reached = True; break
        cursor = (d.get("cursor") or {}).get("bottom")
        if not cursor:
            reached = True; break
    with lock:
        f.write(json.dumps({"handle": h, "since": since, "reached": reached, "posts": posts}) + "\n"); f.flush()


def fetch(jobs, out, threads=6):
    J = json.load(open(jobs)); need = {}
    for j in J:
        since = (datetime.strptime(j["day"], "%Y-%m-%d") - timedelta(days=WINDOW)).strftime("%Y-%m-%d")
        for h in j["makers"] + list(j["voters"].values()) + list(j["control"].values()):
            h = h.lower()
            need[h] = min(need.get(h, since), since)
    done = {json.loads(l)["handle"] for l in open(out)} if os.path.exists(out) else set()
    todo = [(h, s) for h, s in need.items() if h not in done]
    print("handles", len(need), "to fetch", len(todo), flush=True)
    with open(out, "a") as f, ThreadPoolExecutor(threads) as ex:
        for k, _ in enumerate(ex.map(lambda j: fetch_one(j, f), todo)):
            if k % 200 == 0:
                print(k, flush=True)


def report(jobs, posts, ties_out=None):
    J = json.load(open(jobs)); P = {}
    for l in open(posts):
        r = json.loads(l); P[r["handle"]] = r
    res = {"launches": len(J), "window_days": WINDOW}
    agg = {g: {"n": 0, "fetched": 0, "reached": 0, "any": 0, **{k: 0 for k in ("reply", "quote", "repost", "mention")}} for g in ("voters", "control")}
    ties = []
    for j in J:
        end = j["day"]; start = (datetime.strptime(end, "%Y-%m-%d") - timedelta(days=WINDOW)).strftime("%Y-%m-%d")
        mk = {h.lower() for h in j["makers"]}
        mk_out = {}   # what the makers did towards others in the window
        for h in mk:
            for p in (P.get(h) or {}).get("posts", []):
                if start <= p["date"] < end:
                    for kind, t in p["t"]:
                        mk_out.setdefault(t, set()).add(kind)
        for g in ("voters", "control"):
            for u, h in j[g].items():
                h = h.lower(); a = agg[g]; a["n"] += 1
                r = P.get(h)
                if not r or not r["posts"]:
                    continue
                a["fetched"] += 1; a["reached"] += bool(r["reached"])
                kinds = {kind for p in r["posts"] if start <= p["date"] < end for kind, t in p["t"] if t in mk} | mk_out.get(h, set())
                if kinds:
                    a["any"] += 1
                    for k in kinds:
                        a[k] += 1
                    ties.append({"launch": j["id"], "person": u, "group": g, "kinds": sorted(kinds)})
    for g, a in agg.items():
        a["share_with_x_tie_of_fetched"] = round(a["any"] / max(a["fetched"], 1), 4)
    res.update(agg)
    res["lift_voters_vs_control"] = round(agg["voters"]["share_with_x_tie_of_fetched"] / max(agg["control"]["share_with_x_tie_of_fetched"], 1e-9), 1) \
        if agg["control"]["any"] else None
    json.dump(res, open(f"{HERE}/reports/x_pilot.json", "w"), indent=1)
    if ties_out:
        json.dump(ties, open(ties_out, "w"))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    if sys.argv[1] == "fetch":
        fetch(sys.argv[2], sys.argv[3], int(sys.argv[4]) if len(sys.argv) > 4 else 6)
    else:
        report(sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else None)
