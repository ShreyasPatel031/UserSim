"""Runs on the VM. stdin: JSON lines {handle, until} (until = launch day minus 14 days, YYYY-MM-DD). Pages back through
the handle's recent posts on fxtwitter until a post is older than `until` (max 10 pages), and writes one JSON line per
handle: {handle, profile, posts: [{id, created_at, text, likes, reposts, replies, quotes, views, bookmarks}]}."""
import json, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime
import requests

lock = threading.Lock()
UA = {"User-Agent": "ph-predict research"}


def get(url):
    for i in range(3):
        try:
            r = requests.get(url, headers=UA, timeout=30)
            if r.status_code == 429:
                time.sleep(20 * (i + 1)); continue
            return r.json() if r.status_code == 200 else None
        except Exception:  # noqa: BLE001
            time.sleep(3)
    return None


def one(job):
    h, until = job["handle"], job["until"]
    out = {"handle": h, "profile": (get(f"https://api.fxtwitter.com/{h}") or {}).get("user"), "posts": []}
    cursor = ""
    for _ in range(10):
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
            out["posts"].append({k: p.get(k) for k in ("id", "text", "likes", "reposts", "replies", "quotes", "views", "bookmarks")}
                                | {"created_at": ts, "author": (p.get("author") or {}).get("screen_name")})
        cursor = (d.get("cursor") or {}).get("bottom")
        if not cursor or (oldest and oldest < until):
            break
    with lock:
        sys.stdout.write(json.dumps(out) + "\n"); sys.stdout.flush()


if __name__ == "__main__":
    jobs = [json.loads(l) for l in sys.stdin if l.strip()]
    with ThreadPoolExecutor(int(sys.argv[1]) if len(sys.argv) > 1 else 6) as ex:
        list(ex.map(one, jobs))
