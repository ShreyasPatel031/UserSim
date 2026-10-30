"""Makers' side of the X ties pilot: who replied to the makers' X posts? Public data via fxtwitter, no login, VM IP
(route 1). For each launch: the makers' posts in the 60 days before launch day (known before launch) and on launch day
(reported separately: those replies can come after the vote), every reply to them (conversation endpoint, up to 5
pages per post). Then: share of the launch's real Product Hunt voters (with an X handle) among the repliers, vs people
active on Product Hunt that day who did not vote for it (same jobs file as x_pilot.py).
usage: python -m simlab.x_makers jobs.json out.json [threads] -> reports/x_makers.json"""
import json, os, sys, time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
UA = {"User-Agent": "usersim research"}
WINDOW = 60


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


def posts(h, since, until):
    out, cursor = [], ""
    for _ in range(15):
        d = get(f"https://api.fxtwitter.com/2/profile/{h}/statuses" + (f"?cursor={cursor}" if cursor else ""))
        if not d or not d.get("results"):
            break
        oldest = None
        for p in d["results"]:
            try:
                ts = parsedate_to_datetime(p["created_at"]).strftime("%Y-%m-%d")
            except Exception:  # noqa: BLE001
                continue
            oldest = ts
            if since <= ts <= until and not p.get("reposted_by") and (p.get("author") or {}).get("screen_name", "").lower() == h:
                out.append({"id": p["id"], "date": ts, "replies": p.get("replies") or 0})
        cursor = (d.get("cursor") or {}).get("bottom")
        if not cursor or (oldest and oldest < since):
            break
    return out


def repliers(sid):
    who, cursor = set(), ""
    for _ in range(5):
        d = get(f"https://api.fxtwitter.com/2/conversation/{sid}" + (f"?cursor={cursor}" if cursor else ""))
        if not d:
            break
        for r in d.get("replies") or []:
            a = (r.get("author") or {}).get("screen_name")
            if a:
                who.add(a.lower())
        cursor = (d.get("cursor") or {}).get("bottom")
        if not cursor or not d.get("replies"):
            break
    return who


def one(j):
    day = j["day"]; since = (datetime.strptime(day, "%Y-%m-%d") - timedelta(days=WINDOW)).strftime("%Y-%m-%d")
    pre, launch, n_posts = set(), set(), 0
    for h in j["makers"]:
        h = h.lower()
        for p in posts(h, since, day):
            n_posts += 1
            if p["replies"]:
                (launch if p["date"] == day else pre).update(repliers(p["id"]) - {h})
    return {"id": j["id"], "day": day, "makers": j["makers"], "posts": n_posts, "pre": sorted(pre), "launch_day": sorted(launch)}


def main(jobs, out, threads=4):
    J = json.load(open(jobs))
    with ThreadPoolExecutor(threads) as ex:
        R = list(ex.map(one, J))
    json.dump(R, open(out, "w"))
    res = {"launches": len(J), "maker_posts": sum(r["posts"] for r in R), "repliers_pre": sum(len(r["pre"]) for r in R),
           "repliers_launch_day": sum(len(r["launch_day"]) for r in R)}
    for g in ("voters", "control"):
        n = pre = lday = either = 0
        for j, r in zip(J, R):
            P, L = set(r["pre"]), set(r["launch_day"])
            for h in j[g].values():
                h = h.lower(); n += 1; pre += h in P; lday += h in L; either += (h in P) or (h in L)
        res[g] = {"n": n, "replied_before_launch": pre, "replied_on_launch_day": lday, "either": either,
                  "share_before": round(pre / max(n, 1), 4), "share_either": round(either / max(n, 1), 4)}
    json.dump(res, open(f"{HERE}/reports/x_makers.json", "w"), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 4)
