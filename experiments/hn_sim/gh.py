"""GitHub signals for stories that link a repo, as of the moment the story was posted:
  repo age, stars before the post (stargazer list with starred_at; binary search over pages for big repos),
  stars in the 7 days before the post (pre-launch buzz), owner is an organisation.
Newest stories first. Token from $GH_TOKEN_FILE (never stored or logged). Appends rows to <cache>/gh_repos.jsonl.

    python gh.py [since=2025-06-01]
"""
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests

import store as S

TOK = open(os.environ["GH_TOKEN_FILE"]).read().strip()
H = {"Authorization": f"Bearer {TOK}", "Accept": "application/vnd.github.star+json", "X-GitHub-Api-Version": "2022-11-28"}
OUT = os.path.join(S.LOCAL, "gh_repos.jsonl")
lock = threading.Lock()
_s = requests.Session()


def gh(url, params=None):
    for i in range(5):
        r = _s.get(url, headers=H, params=params, timeout=30)
        if r.status_code == 200:
            return r.json()
        if r.status_code in (403, 429) and r.headers.get("x-ratelimit-remaining") == "0":
            time.sleep(max(5, int(r.headers.get("x-ratelimit-reset", time.time() + 60)) - time.time()))
            continue
        if r.status_code in (404, 451, 409):
            return None
        time.sleep(2 ** i)
    return None


def page(repo, n):
    return gh(f"https://api.github.com/repos/{repo}/stargazers", {"per_page": 100, "page": n}) or []


def stars_before(repo, total, t):
    """Number of stars with starred_at < t (exact for <=100 stars; page-level search otherwise, GitHub lists max 400 pages)."""
    iso = lambda x: pd.Timestamp(x["starred_at"]).timestamp()  # noqa: E731
    last = min((total + 99) // 100, 400)
    if last == 0:
        return 0, 0
    lo, hi = 1, last
    while lo < hi:                      # first page whose last star is at/after t
        mid = (lo + hi) // 2
        pg = page(repo, mid)
        if pg and iso(pg[-1]) < t:
            lo = mid + 1
        else:
            hi = mid
    pg = page(repo, lo)
    before = (lo - 1) * 100 + sum(1 for x in pg if iso(x) < t)
    week = sum(1 for x in pg if t - 7 * 86400 <= iso(x) < t)
    if total > 40000 and lo == last:
        before = -1                     # beyond GitHub's 400-page window: unknown
    return before, week


def one(row):
    repo, t, pid = row
    info = gh(f"https://api.github.com/repos/{repo}")
    rec = {"post_id": pid, "repo": repo, "ok": info is not None}
    if info:
        b, w = stars_before(repo, info.get("stargazers_count", 0), t)
        rec.update(repo_age_days=(t - pd.Timestamp(info["created_at"]).timestamp()) / 86400, stars_before=b,
                   stars_week_before=w, org=int((info.get("owner") or {}).get("type") == "Organization"))
    with lock, open(OUT, "a") as f:
        f.write(json.dumps(rec) + "\n")


def main(since="2025-06-01"):
    s = pd.read_parquet(os.path.join(S.LOCAL, "bq_stories.parquet"), columns=["post_id", "url", "day", "created_at_i"])
    s = s[(s.day >= since) & s.url.fillna("").str.match(r"https?://(www\.)?github\.com/[^/]+/[^/#?]+")]
    s = s.assign(repo=s.url.str.extract(r"github\.com/([^/]+/[^/#?]+)")[0].str.lower().str.replace(r"\.git$", "", regex=True))
    done = set()
    if os.path.exists(OUT):
        done = {json.loads(l)["post_id"] for l in open(OUT)}
    rows = [(r.repo, int(r.created_at_i), int(r.post_id)) for r in s.sort_values("created_at_i", ascending=False).itertuples()
            if r.post_id not in done]
    print(len(rows), "stories to fetch", flush=True)
    with ThreadPoolExecutor(12) as ex:
        for i, _ in enumerate(ex.map(one, rows)):
            if i % 1000 == 0:
                print(i, time.strftime("%H:%M"), flush=True)


if __name__ == "__main__":
    main(*sys.argv[1:])
