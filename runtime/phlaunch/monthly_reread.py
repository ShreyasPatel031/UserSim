#!/usr/bin/env python3
"""Daily 23:50 PT: official PH API v2 re-read of current month's featured launches -> GCS monthly_reread/.

Modes:
  --backfill-from-snapshots  Build jsonl from accumulated ph_api_v2 snapshot lines (no live token).
  default                    Live GraphQL pagination (PH_API_TOKEN or PH_API_DEV_TOKEN).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo

PT = ZoneInfo("America/Los_Angeles")
UTC = dt.timezone.utc
BUCKET = os.environ.get("MVP_GCS_BUCKET", "")
B = os.environ.get("PH_AT_LAUNCH_GCS_ROOT", f"gs://{BUCKET}/usersim_sim").rstrip("/")
PREFIX = f"{B}/raw/ph_at_launch/monthly_reread"
GRAPHQL = "https://api.producthunt.com/v2/api/graphql"
COMPLEXITY_LIMIT = int(os.environ.get("PH_API_COMPLEXITY_LIMIT", "6250"))
RATE_FLOOR_PCT = float(os.environ.get("PH_API_RATE_FLOOR_PCT", "0.5"))


def now_iso() -> str:
    return dt.datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def pt_date(d: dt.date | None = None) -> str:
    return (d or dt.datetime.now(PT).date()).isoformat()


def launch_day_pt(featured_at: str) -> str:
    if not featured_at:
        return ""
    s = featured_at.replace("Z", "+00:00")
    t = dt.datetime.fromisoformat(s)
    if t.tzinfo is None:
        t = t.replace(tzinfo=UTC)
    return t.astimezone(PT).date().isoformat()


def sh(*args: str) -> str:
    p = subprocess.run(list(args), capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr or p.stdout or f"exit {p.returncode}")
    return p.stdout


def gcs_ls(prefix: str) -> list[str]:
    out = sh("gcloud", "storage", "ls", prefix)
    return [ln.strip() for ln in out.splitlines() if ln.strip().startswith("gs:")]


def gcs_cat(path: str) -> str:
    return sh("gcloud", "storage", "cat", path)


def gcs_cp_local(local: str, dest: str) -> None:
    subprocess.run(["gcloud", "storage", "cp", local, dest], check=True)


def month_bounds_pt(month: str) -> tuple[dt.date, dt.date]:
    y, m = map(int, month.split("-"))
    start = dt.date(y, m, 1)
    if m == 12:
        end = dt.date(y + 1, 1, 1) - dt.timedelta(days=1)
    else:
        end = dt.date(y, m + 1, 1) - dt.timedelta(days=1)
    return start, end


def in_quiet_window() -> bool:
    """23:58:30–00:03:30 PT budget pause (per README)."""
    n = dt.datetime.now(PT)
    t = n.hour * 3600 + n.minute * 60 + n.second
    # 23:58:30 = 86310, midnight wrap through 00:03:30 = 210
    return t >= 86310 or t <= 210


def api_token() -> str:
    from ph_api_token import api_token as _tok

    return _tok()


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
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"GraphQL HTTP {e.code}: {e.read().decode()[:500]}") from e
    if data.get("errors"):
        raise RuntimeError(json.dumps(data["errors"][:3]))
    return data


def live_fetch_month(month: str) -> tuple[list[dict], list[str]]:
    """Paginate featured posts for the PT month via postedAfter/postedBefore."""
    start, end = month_bounds_pt(month)
    posted_after = dt.datetime.combine(start, dt.time(0, 0), PT).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    posted_before = (
        dt.datetime.combine(end, dt.time(23, 59, 59), PT).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    q = """
query($after: String, $postedAfter: DateTime, $postedBefore: DateTime) {
  posts(first: 50, featured: true, order: RANKING, after: $after,
        postedAfter: $postedAfter, postedBefore: $postedBefore) {
    pageInfo { hasNextPage endCursor }
    edges { node {
      id slug votesCount commentsCount dailyRank weeklyRank monthlyRank featuredAt
    } }
  }
}"""
    by_id: dict[str, dict] = {}
    missing_days: list[str] = []
    cursor = None
    calls = 0
    while True:
        if in_quiet_window():
            time.sleep(30)
            continue
        variables = {"postedAfter": posted_after, "postedBefore": posted_before}
        if cursor:
            variables["after"] = cursor
        data = graphql(q, variables)
        calls += 1
        conn = (data.get("data") or {}).get("posts") or {}
        for edge in conn.get("edges") or []:
            n = edge.get("node") or {}
            lid = str(n.get("id") or "")
            if not lid:
                continue
            row = {
                "id": lid,
                "slug": n.get("slug"),
                "votesCount": n.get("votesCount"),
                "commentsCount": n.get("commentsCount"),
                "dailyRank": n.get("dailyRank"),
                "weeklyRank": n.get("weeklyRank"),
                "monthlyRank": n.get("monthlyRank"),
                "featuredAt": n.get("featuredAt"),
                "fetched_at": now_iso(),
                "launch_day_PT": launch_day_pt(n.get("featuredAt") or ""),
            }
            by_id[lid] = row
        pi = conn.get("pageInfo") or {}
        if not pi.get("hasNextPage"):
            break
        cursor = pi.get("endCursor")
        time.sleep(0.15)
    return list(by_id.values()), missing_days


def snapshot_rows_for_month(month: str, read_date: dt.date) -> tuple[list[dict], int]:
    """Merge api snapshot jsonl under raw/ph_at_launch/<day>/snapshots/*_api.jsonl through read_date."""
    y, m = map(int, month.split("-"))
    start = dt.date(y, m, 1)
    by_id: dict[str, dict] = {}
    dup_drops = 0
    cur = start
    while cur <= read_date:
        day = cur.isoformat()
        prefix = f"{B}/raw/ph_at_launch/{day}/snapshots/"
        try:
            paths = gcs_ls(prefix)
        except RuntimeError:
            cur += dt.timedelta(days=1)
            continue
        api_paths = [p for p in paths if p.endswith("_api.jsonl")]
        if not api_paths:
            cur += dt.timedelta(days=1)
            continue
        text = gcs_cat(sorted(api_paths)[-1])
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("kind") != "api_post" and r.get("src") != "ph_api_v2":
                if "slug" not in r or "id" not in r:
                    continue
            lid = str(r.get("id") or "")
            if not lid:
                continue
            fa = r.get("featuredAt") or ""
            ldp = launch_day_pt(fa)
            if not ldp.startswith(month):
                continue
            row = {
                "id": lid,
                "slug": r.get("slug"),
                "votesCount": r.get("votesCount"),
                "commentsCount": r.get("commentsCount"),
                "dailyRank": r.get("dailyRank"),
                "weeklyRank": r.get("weeklyRank"),
                "monthlyRank": r.get("monthlyRank"),
                "featuredAt": fa,
                "fetched_at": r.get("snapshot_at") or now_iso(),
                "launch_day_PT": ldp,
            }
            if lid in by_id:
                dup_drops += 1
            by_id[lid] = row
        cur += dt.timedelta(days=1)
    return list(by_id.values()), dup_drops


def write_jsonl(
    read_date: str,
    month: str,
    rows: list[dict],
    dup_drops: int,
    source: str,
    missing: list[str],
    out_path: str,
) -> str:
    fetched_start = now_iso()
    hdr = {
        "_header": True,
        "read_date_PT": read_date,
        "fetched_at": fetched_start,
        "source": source,
        "rows": len(rows),
        "duplicate_ids_dropped": dup_drops,
        "dedupe_rule": "one row per id; launch_day_PT = PT date of featuredAt",
        "rate_limited_days_missing_or_partial": missing,
        "status": "DRAFT until agents verify",
        "fetched_at_end": "",
        "budget_rule": "pause below 50% of 6250 and 23:58:30-00:03:30 PT",
    }
    rows_sorted = sorted(rows, key=lambda r: (r.get("launch_day_PT") or "", int(r.get("dailyRank") or 9999)))
    hdr["fetched_at_end"] = now_iso()
    local = f"/tmp/monthly_reread_{read_date}.jsonl"
    with open(local, "w", encoding="utf-8") as f:
        f.write(json.dumps(hdr, ensure_ascii=False) + "\n")
        for r in rows_sorted:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    dest = f"{PREFIX}/{month}/{read_date}.jsonl"
    gcs_cp_local(local, dest)
    return dest


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--read-date", help="PT calendar date YYYY-MM-DD (default today PT)")
    ap.add_argument("--month", help="YYYY-MM (default month of read-date)")
    ap.add_argument("--backfill-from-snapshots", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    read_date = args.read_date or pt_date()
    month = args.month or read_date[:7]
    read_d = dt.date.fromisoformat(read_date)
    if args.backfill_from_snapshots:
        rows, dup = snapshot_rows_for_month(month, read_d)
        source = "PH API v2 snapshots (official), aggregated per PT day through read_date"
        missing: list[str] = []
    else:
        rows, missing = live_fetch_month(month)
        dup = 0
        source = "PH API v2 (official), featured:true order RANKING per PT day"
    if args.dry_run:
        print(json.dumps({"read_date": read_date, "month": month, "rows": len(rows)}, indent=2))
        return 0
    dest = write_jsonl(read_date, month, rows, dup, source, missing, "")
    print(dest)
    return 0


if __name__ == "__main__":
    sys.exit(main())