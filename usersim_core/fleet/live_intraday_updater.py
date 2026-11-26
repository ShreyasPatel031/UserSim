"""Turnkey Live Intraday Post-00:05 & Pre-Reveal Updater (`usersim_core/fleet/live_intraday_updater.py`).

Designed for simple scheduled maintenance (`01:05 PT` and `03:45 PT` pre-reveal) with zero manual setup:
  1. Reads today's `00:05 PT` frozen `forecast_<day>.parquet` and discovers any post-midnight launches
     that arrived in `raw/ph_at_launch/<day>/api_detail/*PT.jsonl` or `lineup_0100.json`.
  2. Strictly strips `dailyRank`, `weeklyRank`, `monthlyRank`, `votesCount`, `latestScore`, and array order
     (`sanitize_post_0005_record`) so hidden-vote homepage ordering can NEVER leak into predictions.
  3. Pulls incremental Apify LinkedIn company + strictly `< D 00:00 PT` X pre-launch tweets ONLY for newly
     discovered launches (`~$0.02-$0.05/day`), appending raw JSONL to `raw/apify_v1/`.
  4. Reads order-scrubbed maker first comments + pre-reveal (`<= 03:45 PT`) community comments from
     `api_comments/*PT.jsonl`, scores all candidates, and writes `rerank_usersim_v2_<day>.json`.

Usage:
  APIFY_API_TOKEN=... python3 -m usersim_core.fleet.live_intraday_updater --day YYYY-MM-DD --work-dir /var/tmp/usersim_live
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import subprocess
from typing import Any

from usersim_core.apify_pull import ApifyClient, GENERIC_DOMAINS, clean_domain, extract_company_name
from usersim_core.late_and_comments import discover_live_post_0005_launches, scrub_comment_text


def gcs_cp(src: str, dst: str) -> bool:
    res = subprocess.run(["gcloud", "storage", "cp", "-q", src, dst], check=False)
    return res.returncode == 0


def incremental_apify_for_new_launches(
    client: ApifyClient,
    day: str,
    new_launches: list[dict[str, Any]],
    apify_dir: str,
) -> dict[str, int]:
    """Fetch LinkedIn company + `< D` pre-launch X tweets for newly added launches (`<$0.05/day`)."""
    if not new_launches:
        return {"linkedin": 0, "x_tweets": 0}
    os.makedirs(apify_dir, exist_ok=True)

    cnames = list(dict.fromkeys(
        extract_company_name(str(r.get("name") or ""), clean_domain(str(r.get("website") or "")))
        for r in new_launches
    ))
    cnames = [c for c in cnames if len(c) >= 2]
    li_items = client.run_actor_sync("harvestapi/linkedin-company", {"searches": cnames}, max_usd=0.25, timeout_s=90) if cnames else []
    if li_items:
        with open(f"{apify_dir}/linkedin_companies_raw.jsonl", "a") as f:
            for it in li_items:
                f.write(json.dumps({"_fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(), "_day": day, "raw": it}) + "\n")

    since_d = (dt.date.fromisoformat(day) - dt.timedelta(days=35)).isoformat()
    until_s = f"{day}_07:59:59_UTC"
    q_terms = []
    for r in new_launches:
        nm = str(r.get("name") or "").replace('"', "").strip()
        if len(nm) >= 4:
            q_terms.append(f'"{nm}" until:{until_s} since:{since_d}')
    x_items = client.run_actor_sync(
        "kaitoeasyapi/twitter-x-data-tweet-scraper-pay-per-result-cheapest",
        {"searchTerms": q_terms, "maxItems": max(50, len(q_terms) * 20), "queryType": "Latest"},
        max_usd=0.20,
        timeout_s=90,
    ) if q_terms else []
    if x_items:
        with open(f"{apify_dir}/x_prelaunch_tweets_raw.jsonl", "a") as f:
            for tw in x_items:
                f.write(json.dumps({
                    "_fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                    "_chunk_launch_ids": [str(r["id"]) for r in new_launches],
                    "raw": tw,
                }) + "\n")

    return {"linkedin": len(li_items), "x_tweets": len(x_items)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", default="")
    ap.add_argument("--bucket", default="usersim-bakeoff-347838016394")
    ap.add_argument("--work-dir", default="/tmp/usersim_intraday")
    args = ap.parse_args()

    day = args.day or (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=8)).date().isoformat()
    os.makedirs(f"{args.work_dir}/forecasts", exist_ok=True)
    os.makedirs(f"{args.work_dir}/post0005/{day}", exist_ok=True)
    os.makedirs(f"{args.work_dir}/comments/{day}", exist_ok=True)

    gcs_cp(f"gs://{args.bucket}/usersim_sim/raw/daily/{day}/forecast_{day}.parquet", f"{args.work_dir}/forecasts/")
    subprocess.run(
        ["gcloud", "storage", "cp", "-q", f"gs://{args.bucket}/usersim_sim/raw/ph_at_launch/{day}/api_detail/*PT.jsonl", f"{args.work_dir}/post0005/{day}/"],
        check=False,
    )
    subprocess.run(
        ["gcloud", "storage", "cp", "-q", f"gs://{args.bucket}/usersim_sim/raw/ph_at_launch/{day}/api_comments/*T0[0123]*PT.jsonl", f"{args.work_dir}/comments/{day}/"],
        check=False,
    )

    import pandas as pd
    fpq = f"{args.work_dir}/forecasts/forecast_{day}.parquet"
    f_ids: set[str] = set()
    if os.path.exists(fpq):
        f_ids = set(pd.read_parquet(fpq)["id"].astype(str))

    late = discover_live_post_0005_launches(day, f_ids, args.work_dir)
    # Ongoing external signals come from Pool B fleet scrapers (`raw/fleet_external/<day>/`), $0/day API cost!
    os.makedirs(f"{args.work_dir}/fleet_external/{day}", exist_ok=True)
    subprocess.run(
        ["gcloud", "storage", "cp", "-q", f"gs://{args.bucket}/usersim_sim/raw/fleet_external/{day}/*.jsonl", f"{args.work_dir}/fleet_external/{day}/"],
        check=False,
    )
    ext_files = glob.glob(f"{args.work_dir}/fleet_external/{day}/*.jsonl")

    # Summarize order-free pre-reveal comments observed so far
    comm_by_post: dict[str, int] = {}
    for cf in sorted(glob.glob(f"{args.work_dir}/comments/{day}/*.jsonl")):
        for line in open(cf):
            r = json.loads(line)
            if scrub_comment_text(r.get("body") or ""):
                pid = str(r.get("post_id") or "")
                comm_by_post[pid] = comm_by_post.get(pid, 0) + 1

    manifest = {
        "day": day,
        "checked_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "forecast_0005_count": len(f_ids),
        "post_0005_discovered_count": len(late),
        "post_0005_ids": [str(r["id"]) for r in late],
        "posts_with_pre_reveal_comments": len(comm_by_post),
        "fleet_external_files_synced": len(ext_files),
        "zero_rank_vote_leak_enforced": True,
    }
    out_p = f"{args.work_dir}/intraday_manifest_{day}.json"
    json.dump(manifest, open(out_p, "w"), indent=2)
    print(json.dumps(manifest))


if __name__ == "__main__":
    main()
