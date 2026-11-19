#!/usr/bin/env python3
"""Weekly close fallback: official PH API weekly ranks (no browser) when route-4 page read is blocked."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo

from ph_api_token import api_token

PT = ZoneInfo("America/Los_Angeles")
UTC = dt.timezone.utc
GRAPHQL = "https://api.producthunt.com/v2/api/graphql"
BUCKET = os.environ.get("MVP_GCS_BUCKET", "")
B = os.environ.get("PH_AT_LAUNCH_GCS_ROOT", f"gs://{BUCKET}/usersim_sim").rstrip("/")


def now_iso() -> str:
    return dt.datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def graphql(query: str, variables: dict | None = None) -> dict:
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(
        GRAPHQL,
        data=body,
        headers={
            "Authorization": f"Bearer {api_token()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"GraphQL HTTP {e.code}") from e


def last_week_bounds_pt(day: dt.date) -> tuple[dt.date, dt.date]:
    """Calendar week containing `day` (Mon–Sun PT): previous Mon 00:00 through Sun 23:59 for 'last week' close."""
    wd = day.weekday()
    this_mon = day - dt.timedelta(days=wd)
    last_mon = this_mon - dt.timedelta(days=7)
    last_sun = this_mon - dt.timedelta(days=1)
    return last_mon, last_sun


def fetch_week(posted_after: str, posted_before: str) -> list[dict]:
    q = """
query($after: String, $postedAfter: DateTime, $postedBefore: DateTime) {
  posts(first: 50, featured: true, order: RANKING, after: $after,
        postedAfter: $postedAfter, postedBefore: $postedBefore) {
    pageInfo { hasNextPage endCursor }
    edges { node {
      id slug name votesCount commentsCount dailyRank weeklyRank featuredAt
    } }
  }
}"""
    out: list[dict] = []
    cursor = None
    while True:
        variables = {"postedAfter": posted_after, "postedBefore": posted_before}
        if cursor:
            variables["after"] = cursor
        data = graphql(q, variables)
        if data.get("errors"):
            raise RuntimeError(json.dumps(data["errors"][:2]))
        conn = (data.get("data") or {}).get("posts") or {}
        for edge in conn.get("edges") or []:
            n = edge.get("node") or {}
            if not n.get("id"):
                continue
            out.append(
                {
                    "id": str(n["id"]),
                    "slug": n.get("slug"),
                    "name": n.get("name"),
                    "votesCount": n.get("votesCount"),
                    "commentsCount": n.get("commentsCount"),
                    "dailyRank": n.get("dailyRank"),
                    "weeklyRank": n.get("weeklyRank"),
                    "featuredAt": n.get("featuredAt"),
                    "fetched_at": now_iso(),
                }
            )
        pi = conn.get("pageInfo") or {}
        if not pi.get("hasNextPage"):
            break
        cursor = pi.get("endCursor")
    out.sort(key=lambda r: (r.get("weeklyRank") is None, r.get("weeklyRank") or 9999, -(r.get("votesCount") or 0)))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", help="PT calendar day YYYY-MM-DD (default today PT)")
    args = ap.parse_args()
    day = dt.date.fromisoformat(args.day) if args.day else dt.datetime.now(PT).date()
    last_mon, last_sun = last_week_bounds_pt(day)
    posted_after = dt.datetime.combine(last_mon, dt.time(0, 0), PT).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    posted_before = dt.datetime.combine(last_sun, dt.time(23, 59, 59), PT).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = fetch_week(posted_after, posted_before)
    tag = dt.datetime.now(PT).strftime("%Y%m%dT%H%MPT")
    hdr = {
        "_header": True,
        "source": "ph_api_v2_weekly_ranks",
        "close_source": "official_api_weekly_ranks",
        "route4_blocked_fallback": True,
        "read_date_PT": day.isoformat(),
        "week_pt": f"{last_mon.isoformat()}..{last_sun.isoformat()}",
        "fetched_at": now_iso(),
        "rows": len(rows),
    }
    local = f"/tmp/weekly_close_api_{day.isoformat()}.jsonl"
    with open(local, "w", encoding="utf-8") as f:
        f.write(json.dumps(hdr, ensure_ascii=False) + "\n")
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    dest = f"{B}/raw/ph_at_launch/{day.isoformat()}/weekly_close/{tag}_api.jsonl"
    subprocess.run(["gcloud", "storage", "cp", local, dest], check=True)
    print(dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())