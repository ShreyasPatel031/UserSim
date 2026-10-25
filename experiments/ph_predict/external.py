"""Signals from outside Product Hunt, keyed by the launch's real domain (from the Apify crawl).

  hn.jsonl      Hacker News stories linking the domain (or GitHub repo) posted BEFORE the launch day (Algolia API)
  domain.jsonl  domain registration date (RDAP), as age in days on launch day

Ids already on disk are skipped.

    python experiments/ph_predict/external.py
"""

from __future__ import annotations

import json
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import features as F  # noqa: E402

SHARED_HOSTS = ("apps.apple.com", "play.google.com", "chromewebstore.google.com", "chrome.google.com",
                "huggingface.co", "x.com", "twitter.com", "linkedin.com", "notion.site", "vercel.app", "youtube.com")


def target(url: str) -> tuple[str, str]:
    """(search term for HN url field, registrable domain or '')."""
    u = re.sub(r"^https?://(www\.)?", "", (url or "").lower()).split("?")[0].rstrip("/")
    host = u.split("/")[0]
    if host == "github.com":
        return "/".join(u.split("/")[:3]), ""
    if not host or any(host == h or host.endswith("." + h) for h in SHARED_HOSTS):
        return "", ""
    parts = host.split(".")
    reg = ".".join(parts[-3:]) if len(parts) > 2 and parts[-2] in ("co", "com") else ".".join(parts[-2:])
    return reg, reg


def hn(term: str, before_ts: int) -> dict:
    r = requests.get("https://hn.algolia.com/api/v1/search", timeout=30, params={
        "query": term, "restrictSearchableAttributes": "url", "tags": "story", "hitsPerPage": 50,
        "numericFilters": f"created_at_i<{before_ts}"}).json()
    hits = [h for h in r.get("hits", []) if term in (h.get("url") or "").lower()]
    pts = [h.get("points") or 0 for h in hits]
    return {"stories": len(hits), "points_sum": sum(pts), "points_max": max(pts, default=0),
            "comments_sum": sum(h.get("num_comments") or 0 for h in hits)}


def rdap(domain: str) -> str | None:
    r = requests.get(f"https://rdap.org/domain/{domain}", timeout=30)
    if not r.ok:
        return None
    for e in r.json().get("events", []):
        if e.get("eventAction") == "registration":
            return e.get("eventDate")
    return None


def main() -> None:
    df = F.load_posts()
    web = {p.stem: json.loads(p.read_text()) for p in (F.CACHE / "web").glob("*.json")}
    outs = {k: F.CACHE / f"{k}.jsonl" for k in ("hn", "domain")}
    done = {k: {json.loads(l)["id"] for l in p.read_text().splitlines()} if p.exists() else set()
            for k, p in outs.items()}
    lock = threading.Lock()
    reg_cache: dict[str, str | None] = {}

    def write(kind: str, rec: dict) -> None:
        with lock, outs[kind].open("a") as f:
            f.write(json.dumps(rec) + "\n")

    def one(r: dict) -> None:
        w = web.get(r["id"])
        if not w or not w.get("loaded_url"):
            return
        term, domain = target(w["loaded_url"])
        day = datetime.fromisoformat(r["day"]).replace(tzinfo=timezone.utc)
        try:
            if r["id"] not in done["hn"]:
                write("hn", {"id": r["id"], **(hn(term, int(day.timestamp())) if term else
                                               {"stories": 0, "points_sum": 0, "points_max": 0, "comments_sum": 0})})
            if r["id"] not in done["domain"]:
                if domain and domain not in reg_cache:
                    reg_cache[domain] = rdap(domain)
                reg = reg_cache.get(domain) if domain else None
                regd = datetime.fromisoformat(reg.replace("Z", "+00:00")) if reg else None
                if regd and regd.tzinfo is None:
                    regd = regd.replace(tzinfo=timezone.utc)
                age = (day - regd).days if regd else None
                write("domain", {"id": r["id"], "age_days": age, "own_domain": int(bool(domain))})
        except Exception as e:  # one bad lookup must not stop the run
            print(r["id"], type(e).__name__, str(e)[:100], flush=True)

    rows = df.to_dict("records")
    print(len(rows), "launches", flush=True)
    with ThreadPoolExecutor(8) as ex:
        list(ex.map(one, rows))
    print("done", flush=True)


if __name__ == "__main__":
    main()
