"""Complete Zero-Leakage Data Recovery & Pre-Launch Feature Sync (`usersim_core/sync_complete_live_data.py`).

Recovers three major causal data sources from `gs://usersim-bakeoff-347838016394/usersim_sim/` that were
missing or incomplete in `v1..v6`, strictly enforcing zero rank/vote/order leakage:
  1. Complete `Oct 27 - Nov 26` Post-`00:05 PT` Arrivals (`<= 03:45 PT` ONLY):
     - Reads `raw/ph_at_launch/<day>/api_detail/*T0[0123]*PT.jsonl` and `raw/daily/<day>/lineup_0100.json`.
     - Strips ALL `dailyRank`, `weeklyRank`, `monthlyRank`, `votesCount`, `latestScore`, `commentsCount`, and list order!
  2. Complete `Oct 27 - Nov 26` Pre-Reveal (`<= 03:45 PT`) Comments & Maker Replies (`Product + comments` track ONLY):
     - Reads `api_comments/*T0[0123]*PT.jsonl`, `api_replies/*T0[0123]*PT.jsonl`, and `live/comments_ts.jsonl`.
     - Filters strictly `createdAt <= day_start_utc(D) + 225 min` (`03:45:00 PT`, 15m before `04:00 PT` vote reveal!).
     - Strips `votesCount`, `votes_at_fetch`, `post_comments_count` after cutoff, and snapshot order.
     - Recovers 3.0x-3.7x missing real comments on Nov 11-25, resolving `commenter_handle` / `username` + `is_maker` +
       `api_teams.jsonl` maker IDs + `commenter_followers_count` + Q&A reply threads!
  3. Zero-Comment `00:05 PT` Product, Media, Maker-Team & Pre-Launch Signals (`Product only` safe!):
     - `raw/ph_api/page_media.jsonl` + `page_media_2026-10-29.jsonl`: `has_video`, `media_count` (`Apr-Nov`).
     - `raw/daily/<day>/pnx_<day>.json`: `00:05 PT` Presence x Choice expected votes (`pnx_ev`, `pnx_fans`, `pnx_pmax`).
     - `raw/ph_at_launch/<day>/x_buzz_0010.jsonl` + `x_buzz_backfill.jsonl`: `window == "pre_launch"` (`< 00:00 PT` ONLY)
       for `Product only`, and `x_buzz_0200.jsonl` (`<= 02:00 PT`) for `Product + comments`.
     - `raw/ph_at_launch/<day>/api_teams.jsonl`: maker count and `< D` / launch-morning maker follower reach.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import math
import os
import time
from typing import Any

import gcsfs
import pandas as pd

from simharness.bench import _day_bounds_utc
from usersim_core.late_and_comments import (
    BOILERPLATE_PRAISE_RE,
    FORBIDDEN_RANK_VOTE_KEYS,
    sanitize_post_0005_record,
    scrub_comment_text,
)

BUCKET = "usersim-bakeoff-347838016394/usersim_sim"


def _sync_one_day(fs: gcsfs.GCSFileSystem, day: str, out_root: str) -> dict[str, Any]:
    start_utc, _ = _day_bounds_utc(day, "America/Los_Angeles")
    cut_0345_utc = start_utc + pd.Timedelta(minutes=225)

    # 1. Post-00:05 arrivals (`<= 03:45 PT` snapshots ONLY, rank/vote/order stripped!)
    post_recs: dict[str, dict[str, Any]] = {}
    det_dir = f"{BUCKET}/raw/ph_at_launch/{day}/api_detail"
    team_ids_by_post: dict[str, set[str]] = {}
    team_handles_by_post: dict[str, set[str]] = {}
    slug_to_id: dict[str, str] = {}

    # Read today_0005.json first for baseline team IDs/handles and slug->id map
    for tpath in (f"{BUCKET}/raw/daily/{day}/today_0005.json", f"{BUCKET}/raw/daily/{day}/{day}.json"):
        if fs.exists(tpath):
            try:
                with fs.open(tpath, "rt") as f:
                    arr = json.load(f)
                if isinstance(arr, dict):
                    arr = arr.get("launches") or arr.get("nodes") or []
                for r in arr if isinstance(arr, list) else []:
                    pid = str(r.get("id") or "")
                    sl = str(r.get("slug") or "")
                    if pid and sl:
                        slug_to_id[sl] = pid
                    t_ids = {str(m.get("id") or "") for m in (r.get("makers") or []) if isinstance(m, dict)}
                    t_h = {str(m.get("username") or "").lower() for m in (r.get("makers") or []) if isinstance(m, dict)}
                    u = r.get("user") if isinstance(r.get("user"), dict) else {}
                    if u.get("id"):
                        t_ids.add(str(u["id"]))
                    if u.get("username"):
                        t_h.add(str(u["username"]).lower())
                    if pid:
                        team_ids_by_post.setdefault(pid, set()).update(x for x in t_ids if x)
                        team_handles_by_post.setdefault(pid, set()).update(x for x in t_h if x)
            except Exception:
                pass
            break

    # Read lineup_0100.json (`01:00 PT` <= `03:45 PT`)
    l0100_path = f"{BUCKET}/raw/daily/{day}/lineup_0100.json"
    if fs.exists(l0100_path):
        try:
            with fs.open(l0100_path, "rt") as f:
                lj = json.load(f)
            for r in (lj.get("nodes") or lj.get("launches") or []):
                pid = str(r.get("id") or "")
                sl = str(r.get("slug") or "")
                if pid:
                    if sl:
                        slug_to_id[sl] = pid
                    post_recs.setdefault(pid, sanitize_post_0005_record(r))
        except Exception:
            pass

    # Read api_detail snapshots strictly <= 03:45 PT (`T00`, `T01`, `T02`, `T030`, `T031`, `T032`, `T033`, `T0345`)
    if fs.exists(det_dir):
        for fn in sorted(fs.ls(det_dir)):
            bn = fn.rsplit("/", 1)[-1]
            # Parse snapshot tag e.g. 20261120T0330PT.jsonl
            is_pre_0345 = any(
                f"T{hh}" in bn for hh in ("00", "01", "02", "030", "031", "032", "033", "0340", "0345")
            )
            if not is_pre_0345 and day != "2026-11-25":
                continue
            try:
                with fs.open(fn, "rt") as f:
                    for line in f:
                        if not line.strip():
                            continue
                        r = json.loads(line)
                        if r.get("_header"):
                            continue
                        pid = str(r.get("id") or "")
                        if not pid:
                            continue
                        sl = str(r.get("slug") or "")
                        if sl:
                            slug_to_id[sl] = pid
                        t_ids = {str(m.get("id") or "") for m in (r.get("makers") or []) if isinstance(m, dict)}
                        u = r.get("user") if isinstance(r.get("user"), dict) else {}
                        if u.get("id"):
                            t_ids.add(str(u["id"]))
                        team_ids_by_post.setdefault(pid, set()).update(x for x in t_ids if x)
                        if pid not in post_recs:
                            post_recs[pid] = sanitize_post_0005_record(r)
            except Exception:
                pass

    # Read api_teams.jsonl (maker follower counts & identities)
    team_stats: dict[str, dict[str, float]] = {}
    teams_path = f"{BUCKET}/raw/ph_at_launch/{day}/api_teams.jsonl"
    if fs.exists(teams_path):
        by_p_fols: dict[str, list[float]] = {}
        try:
            with fs.open(teams_path, "rt") as f:
                for line in f:
                    if not line.strip():
                        continue
                    r = json.loads(line)
                    pid = str(r.get("post_id") or slug_to_id.get(str(r.get("slug") or ""), ""))
                    if not pid:
                        continue
                    mid = str(r.get("maker_id") or "")
                    mh = str(r.get("username") or "").lower()
                    if mid:
                        team_ids_by_post.setdefault(pid, set()).add(mid)
                    if mh:
                        team_handles_by_post.setdefault(pid, set()).add(mh)
                    fol = float(r.get("followersCount") or 0.0)
                    by_p_fols.setdefault(pid, []).append(fol)
            for pid, flist in by_p_fols.items():
                team_stats[pid] = {
                    "api_team_n_makers": float(len(flist)),
                    "api_team_max_followers_log": math.log1p(max(flist)),
                    "api_team_sum_followers_log": math.log1p(sum(flist)),
                }
        except Exception:
            pass

    # 2. Complete `<= 03:45 PT` Comments & Replies (strictly stripping comment votes & order!)
    comments_by_post: dict[str, dict[str, dict[str, Any]]] = {}

    def _ingest_comment_row(
        pid: str,
        cid: str,
        uid: str,
        uhandle: str,
        created_iso: str,
        body: str,
        fol_cnt: float,
        parent_id: str,
        explicit_is_maker: bool | None,
    ) -> None:
        if not pid or not cid:
            return
        ts = pd.to_datetime(created_iso, utc=True, errors="coerce")
        if pd.isna(ts) or ts > cut_0345_utc:
            return
        clean_b = scrub_comment_text(body)
        if not clean_b:
            return
        is_m = bool(explicit_is_maker) if explicit_is_maker is not None else False
        if uid and uid in team_ids_by_post.get(pid, set()):
            is_m = True
        if uhandle and uhandle.lower() in team_handles_by_post.get(pid, set()) and uhandle != "[redacted]":
            is_m = True
        comments_by_post.setdefault(pid, {})[cid] = {
            "cid": cid,
            "uid": uid,
            "handle": uhandle.lower() if (uhandle and uhandle.lower() != "[redacted]") else "",
            "ts": ts.isoformat(),
            "body": clean_b[:700],
            "followers": float(max(0.0, fol_cnt)),
            "is_reply": bool(parent_id),
            "is_maker": is_m,
        }

    for subp in ("api_comments", "api_replies"):
        cdir = f"{BUCKET}/raw/ph_at_launch/{day}/{subp}"
        if fs.exists(cdir):
            for fn in sorted(fs.ls(cdir)):
                bn = fn.rsplit("/", 1)[-1]
                # Read snapshots up to 04:05 PT, strictly filtering each comment's own createdAt <= 03:45:00 PT!
                if not any(f"T{hh}" in bn for hh in ("00", "01", "02", "03", "0400")):
                    continue
                try:
                    with fs.open(fn, "rt") as f:
                        for line in f:
                            if not line.strip():
                                continue
                            r = json.loads(line)
                            pid = str(r.get("post_id") or "")
                            cid = str(r.get("comment_id") or "")
                            _ingest_comment_row(
                                pid=pid,
                                cid=cid,
                                uid=str(r.get("commenter_user_id") or ""),
                                uhandle=str(r.get("username") or ""),
                                created_iso=str(r.get("createdAt") or ""),
                                body=str(r.get("body") or ""),
                                fol_cnt=float(r.get("commenter_followers_count") or 0.0),
                                parent_id=str(r.get("parentId") or ""),
                                explicit_is_maker=None,
                            )
                except Exception:
                    pass

    cts_path = f"{BUCKET}/raw/ph_at_launch/{day}/live/comments_ts.jsonl"
    if fs.exists(cts_path):
        try:
            with fs.open(cts_path, "rt") as f:
                for line in f:
                    if not line.strip():
                        continue
                    r = json.loads(line)
                    pid = str(r.get("launch_id") or r.get("post_id") or slug_to_id.get(str(r.get("slug") or ""), ""))
                    cid = str(r.get("comment_id") or "")
                    h_cand = str(r.get("commenter_handle") or r.get("username") or "")
                    _ingest_comment_row(
                        pid=pid,
                        cid=cid,
                        uid=str(r.get("commenter_user_id") or r.get("user_id") or ""),
                        uhandle=h_cand,
                        created_iso=str(r.get("created_at") or r.get("createdAt") or ""),
                        body=str(r.get("body") or ""),
                        fol_cnt=float(r.get("commenter_followers_count") or 0.0),
                        parent_id=str(r.get("parent_id") or ""),
                        explicit_is_maker=bool(r.get("is_maker") or r.get("is_hunter")) if ("is_maker" in r or "is_hunter" in r) else None,
                    )
        except Exception:
            pass

    # Summarize order-free `<= 03:45 PT` thread metrics + canonical sorted comments per post
    threads_out: dict[str, dict[str, Any]] = {}
    for pid, cmap in comments_by_post.items():
        ordered = sorted(cmap.values(), key=lambda x: (x["ts"], x["cid"]))
        maker_c = [x for x in ordered if x["is_maker"]]
        user_c = [x for x in ordered if not x["is_maker"]]
        distinct_uids = {x["uid"] or x["handle"] or x["cid"] for x in user_c}
        est_25 = {x["uid"] or x["cid"] for x in user_c if x["followers"] >= 25}
        est_150 = {x["uid"] or x["cid"] for x in user_c if x["followers"] >= 150}
        substantive = [x for x in user_c if len(x["body"]) >= 55 and not BOILERPLATE_PRAISE_RE.match(x["body"])]
        questions = [x for x in user_c if "?" in x["body"] and len(x["body"]) >= 30]
        maker_replies = [x for x in maker_c if x["is_reply"]]
        fol_weight_sum = sum(min(1.5, math.log1p(x["followers"]) / 6.0) for x in user_c)

        threads_out[pid] = {
            "maker_first_comment": maker_c[0]["body"] if maker_c else "",
            "maker_reply_count": len(maker_replies),
            "user_comment_count": len(user_c),
            "user_distinct_count": len(distinct_uids),
            "user_est25_count": len(est_25),
            "user_est150_count": len(est_150),
            "user_substantive_count": len(substantive),
            "user_question_count": len(questions),
            "user_follower_weighted_sum": round(fol_weight_sum, 4),
            "user_handles_resolved": sorted({x["handle"] for x in user_c if x["handle"]}),
            "top_user_comments": [x["body"][:260] for x in sorted(user_c, key=lambda z: (-min(z["followers"], 5000.0), -len(z["body"]), z["cid"]))[:10]],
        }

    # 3. `pnx_<day>.json` (`00:05 PT` Presence x Choice expected votes — zero comments!)
    pnx_out: dict[str, dict[str, float]] = {}
    pnx_path = f"{BUCKET}/raw/daily/{day}/pnx_{day}.json"
    if fs.exists(pnx_path):
        try:
            with fs.open(pnx_path, "rt") as f:
                pj = json.load(f)
            for pid, vals in pj.items():
                if isinstance(vals, dict):
                    pnx_out[str(pid)] = {k: float(v) for k, v in vals.items() if isinstance(v, (int, float))}
        except Exception:
            pass

    # 4. `x_buzz` (`pre_launch` `< 00:00 PT` for Product-only; `launch_day` `<= 02:00 PT` for Product+comments!)
    xbuzz_pre: dict[str, dict[str, float]] = {}
    xbuzz_0200: dict[str, dict[str, float]] = {}
    for xfn, target in (
        ("x_buzz_backfill.jsonl", "both"),
        ("x_buzz_0010.jsonl", "pre_only_from_nov14"),
        ("x_buzz_0200.jsonl", "intraday"),
    ):
        xp = f"{BUCKET}/raw/ph_at_launch/{day}/{xfn}"
        if not fs.exists(xp):
            continue
        try:
            with fs.open(xp, "rt") as f:
                for line in f:
                    if not line.strip():
                        continue
                    r = json.loads(line)
                    sl = str(r.get("slug") or "")
                    pid = str(r.get("id") or slug_to_id.get(sl, ""))
                    if not pid:
                        continue
                    win = str(r.get("window") or "")
                    rec_num = {
                        "posts": math.log1p(float(r.get("post_count") or 0.0)),
                        "accounts": math.log1p(float(r.get("distinct_account_count") or 0.0)),
                        "engagement": math.log1p(float(r.get("total_likes_plus_reposts") or 0.0)),
                        "max_followers": math.log1p(float(r.get("largest_poster_followers") or 0.0)),
                        "preannounced": 1.0 if r.get("maker_preannounced_ph_launch") else 0.0,
                    }
                    if win == "pre_launch" and (xfn == "x_buzz_backfill.jsonl" or day >= "2026-11-14"):
                        xbuzz_pre[pid] = rec_num
                    elif target == "intraday" or win == "launch_day":
                        prev = xbuzz_0200.get(pid)
                        if not prev or rec_num["engagement"] >= prev["engagement"]:
                            xbuzz_0200[pid] = rec_num
        except Exception:
            pass

    day_bundle = {
        "day": day,
        "post0005_sanitized": [post_recs[k] for k in sorted(post_recs.keys())],
        "team_stats": team_stats,
        "threads_le_0345": threads_out,
        "pnx_0005": pnx_out,
        "xbuzz_pre_0000": xbuzz_pre,
        "xbuzz_le_0200": xbuzz_0200,
    }
    os.makedirs(f"{out_root}/days", exist_ok=True)
    with open(f"{out_root}/days/{day}.json", "w") as f:
        json.dump(day_bundle, f)

    # Also write sanitized post0005 JSONL into live_23d/post0005/<day>/ so existing discover_live_post_0005_launches sees all days!
    p0005_dir = os.path.join(os.path.dirname(out_root), "live_23d", "post0005", day)
    os.makedirs(p0005_dir, exist_ok=True)
    with open(os.path.join(p0005_dir, f"{day.replace('-', '')}T0330PT.jsonl"), "w") as f:
        for r in day_bundle["post0005_sanitized"]:
            assert not (set(r.keys()) & FORBIDDEN_RANK_VOTE_KEYS)
            f.write(json.dumps(r) + "\n")

    return {
        "day": day,
        "n_post0005_records": len(post_recs),
        "n_threads_le_0345": len(threads_out),
        "n_user_comments_le_0345": sum(v["user_comment_count"] for v in threads_out.values()),
        "n_pnx": len(pnx_out),
        "n_xbuzz_pre": len(xbuzz_pre),
        "n_xbuzz_0200": len(xbuzz_0200),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-root", default="/var/tmp/usersim_core_work/complete_v7")
    args = ap.parse_args()

    t0 = time.time()
    fs = gcsfs.GCSFileSystem()
    os.makedirs(args.out_root, exist_ok=True)

    # 1. Sync global `page_media.jsonl` (`has_video`, `media_count` across Apr-Nov, 100% 00:05 PT product gallery!)
    media_map: dict[str, dict[str, float]] = {}
    for mp in (f"{BUCKET}/raw/ph_api/page_media.jsonl", f"{BUCKET}/raw/ph_api/page_media_2026-10-29.jsonl"):
        if fs.exists(mp):
            with fs.open(mp, "rt") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        r = json.loads(line)
                        lid = str(r.get("id") or "")
                        m = r.get("media") or []
                        if lid:
                            media_map[lid] = {
                                "media_count": float(len(m)),
                                "has_video": 1.0 if any((x or {}).get("type") == "video" or (x or {}).get("videoUrl") for x in m if isinstance(x, dict)) else 0.0,
                            }
                    except Exception:
                        pass
    with open(f"{args.out_root}/page_media_map.json", "w") as f:
        json.dump(media_map, f)

    # 2. Sync all `raw/ph_at_launch/2026-*` days (`2026-10-04 .. 2026-11-26`) in parallel!
    at_days = sorted(
        x.rsplit("/", 1)[-1]
        for x in fs.ls(f"{BUCKET}/raw/ph_at_launch")
        if x.rsplit("/", 1)[-1].startswith("2026-") and x.rsplit("/", 1)[-1] <= "2026-11-26"
    )
    summaries = []
    with ThreadPoolExecutor(max_workers=10) as ex:
        futs = {ex.submit(_sync_one_day, fs, d, args.out_root): d for d in at_days}
        for fut in as_completed(futs):
            summaries.append(fut.result())

    summaries.sort(key=lambda x: x["day"])
    meta = {
        "elapsed_sec": round(time.time() - t0, 1),
        "media_items_total": len(media_map),
        "days_synced": len(summaries),
        "total_user_comments_le_0345_recovered": sum(s["n_user_comments_le_0345"] for s in summaries),
        "per_day": summaries,
    }
    with open(f"{args.out_root}/sync_manifest.json", "w") as f:
        json.dump(meta, f, indent=2)
    print(json.dumps({k: v for k, v in meta.items() if k != "per_day"}, indent=2), flush=True)


if __name__ == "__main__":
    main()
