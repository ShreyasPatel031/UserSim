"""Collect Product Hunt launches day by day from the PH GraphQL API (labels + launch metadata).

Per Pacific day: every featured launch (paged, 20 per page) with topics, media, links, hunter and makers -- the
candidate set, chosen by PH before any votes (on Oct 23 the day's top 20 by ranking were all featured). Labels
(dailyRank / weeklyRank / monthlyRank / votes) are stored next to the metadata but are never used as features. Days already on disk are skipped, so the script can be re-run.

    PH_TOKEN=... python experiments/ph_longitudinal/collect_ph.py 2025-10-01 2026-10-24
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

HERE = Path(__file__).resolve().parent
DAYS = HERE / "cache" / "ph_days"
ENDPOINT = "https://api.producthunt.com/v2/api/graphql"
PT = ZoneInfo("America/Los_Angeles")

USER = "id username name headline followersCount createdAt twitterUsername websiteUrl"
QUERY = """query($after: DateTime!, $before: DateTime!, $cursor: String) {
  posts(first: 20, after: $cursor, featured: true, postedAfter: $after, postedBefore: $before, order: RANKING) {
    totalCount
    pageInfo { hasNextPage endCursor }
    edges { node {
      id name slug tagline description url website createdAt featuredAt scheduledAt
      dailyRank weeklyRank monthlyRank votesCount commentsCount reviewsCount reviewsRating
      topics(first: 10) { edges { node { name slug } } }
      media { type url videoUrl }
      productLinks { type url }
      user { %s }
      makers { %s }
    } }
  }
}""" % (USER, USER)


def tokens() -> list[str]:
    out = [os.environ["PH_TOKEN"]] if os.environ.get("PH_TOKEN") else []
    cid, secret = os.environ.get("PH_CLIENT_ID"), os.environ.get("PH_CLIENT_SECRET")
    if cid and secret:
        r = requests.post("https://api.producthunt.com/v2/oauth/token", timeout=30,
                          json={"client_id": cid, "client_secret": secret, "grant_type": "client_credentials"})
        if r.ok:
            out.append(r.json()["access_token"])
    return out


def fetch_day(day: date, tok: str) -> tuple[dict, dict]:
    """All featured posts of the day (paged); {} when rate limited."""
    start = datetime(day.year, day.month, day.day, tzinfo=PT)
    variables = {"after": start.isoformat(), "before": (start + timedelta(days=1)).isoformat(), "cursor": None}
    out: dict = {}
    while True:
        page, limits = _page(variables, tok)
        if not page:
            return {}, limits
        if not out:
            out = {"featured_total": page["posts"]["totalCount"], "edges": []}
        out["edges"] += page["posts"]["edges"]
        if not page["posts"]["pageInfo"]["hasNextPage"]:
            return out, limits
        variables["cursor"] = page["posts"]["pageInfo"]["endCursor"]


def _page(variables: dict, tok: str) -> tuple[dict, dict]:
    r = requests.post(ENDPOINT, timeout=60, json={"query": QUERY, "variables": variables},
                      headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
    limits = {k: r.headers.get(f"x-rate-limit-{k}") for k in ("remaining", "reset")}
    if r.status_code == 429:
        return {}, limits
    r.raise_for_status()
    body = r.json()
    if body.get("errors"):
        raise RuntimeError(body["errors"])
    return body["data"], limits


def main(first: str, last: str) -> None:
    DAYS.mkdir(parents=True, exist_ok=True)
    toks = tokens()
    # Newest day first: the test period is ready first if the run is cut short.
    day, start, i = date.fromisoformat(last), date.fromisoformat(first), 0
    while day >= start:
        path = DAYS / f"{day}.json"
        if path.exists():
            day -= timedelta(days=1)
            continue
        tok = toks[i % len(toks)]
        posts, limits = fetch_day(day, tok)
        if not posts:
            wait = int(limits.get("reset") or 60) + 5
            print(f"{day}: rate limited on token {i % len(toks)}, waiting {wait}s", flush=True)
            i += 1
            if i % len(toks) == 0:
                time.sleep(wait)
            continue
        path.write_text(json.dumps({"day": str(day), "fetched_at": datetime.now(PT).isoformat(), **posts}))
        print(f"{day}: {len(posts['edges'])} featured, remaining {limits['remaining']}", flush=True)
        day -= timedelta(days=1)
        i += 1


if __name__ == "__main__":
    main(*sys.argv[1:3])
