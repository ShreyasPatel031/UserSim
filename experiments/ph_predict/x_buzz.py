"""X (Twitter) buzz around each launch, from tweets that link or mention the product's own domain.

One Apify search per launch (apidojo/tweet-scraper, ~$0.40 per 1,000 tweets): "<domain> since:<day before>
until:<day after>", latest first, at most MAX_ITEMS tweets. Only tweets from 24 h before launch to 4 h after are
kept, and leaderboard tweets ("top 3 on Product Hunt", vote counts) are dropped, so nothing reflects the result.
Shared hosts (github.io, vercel.app, ...) are skipped. Writes cache/x/<id>.json; stops at MAX_TWEETS in total.

    APIFY_TOKEN=... python experiments/ph_predict/x_buzz.py
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import external as X  # noqa: E402
import features as F  # noqa: E402

OUT = F.CACHE / "x"
ACTOR = "https://api.apify.com/v2/acts/apidojo~tweet-scraper/run-sync-get-dataset-items"
MAX_ITEMS, MAX_TWEETS, PARALLEL = 30, 80_000, 12
SHARED = ("github.io", "vercel.app", "netlify.app", "pages.dev", "framer.website", "framer.ai", "webflow.io",
          "carrd.co", "notion.site", "replit.app", "lovable.app", "bolt.new", "itch.io", "gumroad.com", "substack.com")
LEADERBOARD = re.compile(r"top \d+ (products? )?on product ?hunt|product of the (day|week|month)|#\s?\d+ on product ?hunt|"
                         r"🔼|ranked #|today's top|leaderboard", re.I)
_lock = threading.Lock()
_total = {"tweets": 0}


def when(s: str) -> datetime:
    return datetime.strptime(s, "%a %b %d %H:%M:%S %z %Y")


def search(domain: str, t0: datetime) -> list[dict]:
    q = f"{domain} since:{(t0 - timedelta(days=1)).date()} until:{(t0 + timedelta(days=1)).date()}"
    r = requests.post(ACTOR, params={"token": os.environ["APIFY_TOKEN"], "timeout": 120}, timeout=150,
                      json={"searchTerms": [q], "maxItems": MAX_ITEMS, "sort": "Latest"})
    return [i for i in r.json() if isinstance(i, dict) and "text" in i]


def one(r: dict, web: dict) -> None:
    if _total["tweets"] >= MAX_TWEETS:
        return
    w = web.get(r["id"]) or {}
    _, domain = X.target(w.get("loaded_url") or "")
    if not domain or any(domain == s or domain.endswith("." + s) for s in SHARED):
        (OUT / f"{r['id']}.json").write_text(json.dumps({"id": r["id"], "searched": False}))
        return
    t0 = datetime.fromisoformat(r["t0"].replace("Z", "+00:00"))
    try:
        items = search(domain, t0)
    except Exception as e:  # keep going; the launch is retried on the next run
        print(r["id"], type(e).__name__, flush=True)
        return
    keep = []
    for i in items:
        t = when(i["createdAt"])
        if t0 - timedelta(hours=24) <= t <= t0 + timedelta(hours=4) and not LEADERBOARD.search(i["text"]):
            a = i.get("author") or {}
            keep.append({"t": t.isoformat(), "followers": a.get("followers"), "author": a.get("userName"),
                         "verified": a.get("isBlueVerified"), "prelaunch": t < t0, "reply": i.get("isReply"),
                         "lang": i.get("lang")})
    with _lock:
        _total["tweets"] += len(items)
    (OUT / f"{r['id']}.json").write_text(json.dumps({"id": r["id"], "searched": True, "domain": domain,
                                                     "fetched": len(items), "capped": len(items) >= MAX_ITEMS,
                                                     "tweets": keep}))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    df = F.load_posts()
    df = df[df.complete].sort_values("day", ascending=False)  # newest first
    t0 = {}
    for f in (F.CACHE / "ph_days").glob("*.json"):
        for e in json.loads(f.read_text())["edges"]:
            t0[e["node"]["id"]] = e["node"]["featuredAt"] or e["node"]["createdAt"]
    done = {p.stem for p in OUT.glob("*.json")}
    web = {p.stem: json.loads(p.read_text()) for p in (F.CACHE / "web").glob("*.json")}
    rows = [{"id": i, "t0": t0[i]} for i in df.id if i not in done and i in t0]
    print(f"{len(rows)} launches to search", flush=True)
    n = [0]

    def run(r):
        one(r, web)
        n[0] += 1
        if n[0] % 250 == 0:
            print(n[0], "tweets fetched so far", _total["tweets"], flush=True)

    with ThreadPoolExecutor(PARALLEL) as ex:
        list(ex.map(run, rows))
    print("done; tweets fetched", _total["tweets"], flush=True)


if __name__ == "__main__":
    main()
