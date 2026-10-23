"""Crawl featured Product Hunt launches for one topic and one month.

Output is one JSON object per launch in data/producthunt/<topic>_<YYYY-MM>.jsonl
with launch outcomes (votes, comments, ranks), copy, topics, makers, gallery
media and the first page of comments, plus the product's real domain resolved
from Product Hunt's redirect link.

Auth (first match wins):
    PH_TOKEN                          developer / access token
    PH_CLIENT_ID + PH_CLIENT_SECRET   client-credentials token (public scope)

Rate limit: 6250 points per 15 min, 100 per request, 20 posts per page. The
crawler sleeps until the window resets when it runs low, and resumes from a
cursor checkpoint, so it is safe to interrupt and rerun.

    python scripts/ph_crawl.py --topic artificial-intelligence --month 2025-06
    python scripts/ph_crawl.py --topic developer-tools --month 2025-06 --top 100
"""

from __future__ import annotations

import argparse
import calendar
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import requests

API = "https://api.producthunt.com/v2/api/graphql"
TOKEN_URL = "https://api.producthunt.com/v2/oauth/token"
OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "producthunt"
LOW_WATER = 150  # points left at which we wait for the window to reset

QUERY = """
query($topic: String, $after: String, $first: Int, $from: DateTime, $to: DateTime) {
  posts(topic: $topic, featured: true, order: VOTES, first: $first, after: $after,
        postedAfter: $from, postedBefore: $to) {
    totalCount
    pageInfo { hasNextPage endCursor }
    edges { node {
      id slug name tagline description createdAt featuredAt website url
      votesCount commentsCount reviewsCount reviewsRating makerReplies
      dailyRank weeklyRank monthlyRank yearlyRank
      topics(first: 10) { edges { node { slug name } } }
      makers { username name headline followersCount isMaker }
      thumbnail { url }
      media { type url videoUrl }
      productLinks { type url }
      comments(first: 5) { totalCount edges { node {
        id body votesCount createdAt parentId } } }
    } }
  }
}
"""


def get_token() -> str:
    token = os.environ.get("PH_TOKEN")
    if token:
        return token
    cid, secret = os.environ.get("PH_CLIENT_ID"), os.environ.get("PH_CLIENT_SECRET")
    if not (cid and secret):
        sys.exit("Set PH_TOKEN, or PH_CLIENT_ID and PH_CLIENT_SECRET")
    resp = requests.post(
        TOKEN_URL,
        json={"client_id": cid, "client_secret": secret, "grant_type": "client_credentials"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def month_window(month: str) -> tuple[str, str]:
    year, mon = (int(p) for p in month.split("-"))
    last = calendar.monthrange(year, mon)[1]
    nxt_year, nxt_mon = (year + 1, 1) if mon == 12 else (year, mon + 1)
    return f"{year}-{mon:02d}-01T00:00:00Z", f"{nxt_year}-{nxt_mon:02d}-01T00:00:00Z"


def post(session: requests.Session, variables: dict) -> dict:
    """One GraphQL call that waits out the rate-limit window instead of failing."""
    for attempt in range(6):
        resp = session.post(API, json={"query": QUERY, "variables": variables}, timeout=60)
        remaining = int(resp.headers.get("x-rate-limit-remaining", 9999))
        reset = int(resp.headers.get("x-rate-limit-reset", 0))
        if resp.status_code == 429:
            wait = reset + 5 if reset else 60 * (attempt + 1)
            print(f"  rate limited, sleeping {wait}s", flush=True)
            time.sleep(wait)
            continue
        resp.raise_for_status()
        body = resp.json()
        if body.get("errors"):
            raise RuntimeError(body["errors"])
        if remaining <= LOW_WATER and reset:
            print(f"  {remaining} points left, sleeping {reset + 5}s for reset", flush=True)
            time.sleep(reset + 5)
        return body["data"]["posts"]
    raise RuntimeError("rate limit retries exhausted")


URL_RE = re.compile(r"https?://[^\s)\]>\"']+")


def description_domain(text: str | None) -> dict:
    """Fallback: first non-Product-Hunt link written in the launch description."""
    for url in URL_RE.findall(text or ""):
        host = (urlparse(url).hostname or "").removeprefix("www.")
        if host and "producthunt.com" not in host:
            return {"resolved_url": url.rstrip(".,"), "domain": host, "domain_source": "description"}
    return {}


def resolve_domain(row: dict) -> dict:
    """Follow Product Hunt's /r/ redirect to the product's real site.

    Product Hunt serves a Cloudflare challenge on /r/ links to non-browser
    clients, so this often fails; we then fall back to the description and
    otherwise leave domain empty rather than record producthunt.com.
    """
    info: dict = {"domain": None, "resolved_url": None, "domain_source": None}
    try:
        resp = requests.get(
            row.get("website"),
            allow_redirects=True,
            stream=True,
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0 (compatible; UserSim-research)"},
        )
        resp.close()
        host = (urlparse(resp.url).hostname or "").removeprefix("www.")
        if resp.status_code < 400 and host and "producthunt.com" not in host:
            return {"resolved_url": resp.url.split("?")[0], "domain": host, "domain_source": "redirect"}
        info["resolve_error"] = f"http_{resp.status_code}"
    except requests.RequestException as exc:
        info["resolve_error"] = type(exc).__name__
    info.update(description_domain(row.get("description")))
    return info


def flatten(node: dict) -> dict:
    node["topics"] = [e["node"] for e in node["topics"]["edges"]]
    comments = node["comments"]
    node["comments_total"] = comments["totalCount"]
    node["comments"] = [e["node"] for e in comments["edges"]]
    return node


def crawl(topic: str, month: str, top: int | None, out_path: Path) -> list[dict]:
    start, end = month_window(month)
    state_path = out_path.with_suffix(".cursor")
    rows: list[dict] = []
    cursor = None
    if out_path.exists() and state_path.exists():
        rows = [json.loads(line) for line in out_path.read_text().splitlines() if line]
        cursor = state_path.read_text().strip() or None
        print(f"resuming: {len(rows)} launches already saved", flush=True)

    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {get_token()}"
    seen = {r["id"] for r in rows}

    while True:
        page = post(session, {"topic": topic, "after": cursor, "first": 20, "from": start, "to": end})
        new = [flatten(e["node"]) for e in page["edges"] if e["node"]["id"] not in seen]
        with out_path.open("a") as fh:
            for row in new:
                fh.write(json.dumps(row) + "\n")
        rows.extend(new)
        seen.update(r["id"] for r in new)
        cursor = page["pageInfo"]["endCursor"]
        state_path.write_text(cursor or "")
        print(f"  {len(rows)}/{page['totalCount']} launches", flush=True)
        if not page["pageInfo"]["hasNextPage"] or (top and len(rows) >= top):
            break
    return rows[:top] if top else rows


def resolve_all(out_path: Path, workers: int = 8) -> None:
    rows = [json.loads(line) for line in out_path.read_text().splitlines() if line]
    todo = [r for r in rows if not r.get("domain_source")]
    with ThreadPoolExecutor(workers) as pool:
        for row, info in zip(todo, pool.map(resolve_domain, todo)):
            row.update(info)
    out_path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    by_source = {}
    for r in rows:
        by_source[r.get("domain_source")] = by_source.get(r.get("domain_source"), 0) + 1
    print(f"domains by source (None = unresolved): {by_source}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--topic", required=True, help="topic slug, e.g. artificial-intelligence")
    ap.add_argument("--month", required=True, help="YYYY-MM")
    ap.add_argument("--top", type=int, help="stop after the N most-voted featured launches")
    ap.add_argument("--no-resolve", action="store_true", help="skip real-domain resolution")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"{args.topic}_{args.month}.jsonl"
    rows = crawl(args.topic, args.month, args.top, out_path)
    if not args.no_resolve:
        resolve_all(out_path)
    print(f"{len(rows)} launches -> {out_path}")


if __name__ == "__main__":
    main()
