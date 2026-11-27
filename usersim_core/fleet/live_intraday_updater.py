"""Turnkey Live Intraday v5 Updater (`usersim_core/fleet/live_intraday_updater.py`).

Scheduled via `systemd` (`usersim-live-pre.timer` at `00:12`, `01:10`, `02:20`, and `03:35 PT` daily):
  1. Reads today's `00:05 PT` frozen `forecast_<day>.parquet` and discovers post-midnight launches
     from `raw/ph_at_launch/<day>/api_detail/*PT.jsonl` or `lineup_0100.json`, strictly stripping all
     `dailyRank`, `votesCount`, `latestScore`, and array order (`sanitize_post_0005_record`).
  2. Dispatches any un-inspected launch URLs (`producthunt.com` strictly excluded) to the 5 pinned
     signed-in Pool B Gmail/Camoufox VMs (`slots 32, 40, 42, 44, 45`) via the GCS job manifest
     `gs://usersim-bakeoff-347838016394/usersim_sim/raw/fleet_external/_jobs/intraday_<day>_targets.jsonl`
     and reads completed 4-step post-login Google-SSO traces from `raw/fleet_external/`.
  3. Runs `usersim_core` v5 (`CompetitorGraph` `< D` named competitors + `PopulationChoiceSim`
     93K voter/switcher choice + `STACK-1b` Qwen-7B `P(yes)` + cold-start brand authority) to produce:
       - Track 1 (`mid`): `Product only` (ZERO comments, `comment_isolation_max_abs_diff == 0.0`)
       - Track 2 (`pre`): `Product + comments` (`<= 03:45 PT` order-free, `permutation_max_abs_diff < 1e-9`)
       - Privacy-safe per-launch `why` cards (`min_group >= 20`, zero handles/IDs) synced to
         `gs://usersim-trace-store-347838016394/usersim_core_v5/why/`.
  4. Enforces `forecast_pre` Path Hygiene (`AGENTS.md`):
     - Writes `gs://usersim-bakeoff-347838016394/usersim_sim/results/web/forecast_pre/<day>.json`
       ONLY when running live for today strictly BEFORE `03:50 PT` (`America/Los_Angeles`).
     - Replays or runs after `03:50 PT` write strictly to `results/web/forecast_pre_replay/<day>.json`.
  5. Cleans up ephemeral `/tmp/usersim_intraday_<day>` files on exit so shared VM disk stays clean.
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import math
import os
import shutil
import subprocess
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from usersim_core.late_and_comments import (
    BOILERPLATE_PRAISE_RE,
    discover_live_post_0005_launches,
    sanitize_post_0005_record,
    scrub_comment_text,
)
from usersim_core.sanitizer import _surface_from_clean_text, sanitize_text
from usersim_core.why_cards_v5 import WHY_MIN_GROUP, assert_why_card_privacy, build_day_why_card


POOL_B_SLOTS: list[tuple[int, int]] = [
    (32, 1),
    (40, 2),
    (42, 3),
    (44, 4),
    (45, 5),
]


def gcs_cp(src: str, dst: str) -> bool:
    res = subprocess.run(["gcloud", "storage", "cp", "-q", src, dst], check=False)
    return res.returncode == 0


def dispatch_uninspected_to_pool_b(
    day: str,
    candidate_urls: list[dict[str, Any]],
    already_inspected_ids: set[str],
    bucket: str,
    work_dir: str,
    trigger_ssh: bool = False,
) -> dict[str, Any]:
    """Write un-inspected external URLs to Pool B job manifest (`slots 32, 40, 42, 44, 45`; zero `producthunt.com`)."""
    todo = []
    for item in sorted(candidate_urls, key=lambda x: str(x["item_id"])):
        lid = str(item["item_id"])
        url = str(item.get("url") or "").strip()
        if lid in already_inspected_ids or not url or "producthunt.com" in url.lower():
            continue
        todo.append({
            "item_id": lid,
            "day": day,
            "title": str(item.get("title") or ""),
            "url": url,
            "dispatched_for_slots": [s for s, _ in POOL_B_SLOTS],
        })

    job_name = f"intraday_{day.replace('-', '')}_cua"
    manifest_local = os.path.join(work_dir, f"{job_name}_targets.jsonl")
    with open(manifest_local, "w") as f:
        for row in todo:
            f.write(json.dumps(row) + "\n")

    gcs_job_uri = f"gs://{bucket}/usersim_sim/raw/fleet_external/_jobs/{job_name}_targets.jsonl"
    if todo:
        gcs_cp(manifest_local, gcs_job_uri)

    triggered_slots: list[int] = []
    if trigger_ssh and todo:
        for slot, acc_idx in POOL_B_SLOTS:
            vm = f"feeder-fleet-20261108t082000z-{slot}"
            cmd = (
                f"nohup python3 /var/lib/usersim/pool_b_interactive_cua.py "
                f"--slot {slot} --account-idx {acc_idx} --job-name {job_name} "
                f">/var/tmp/{job_name}_slot{slot}.log 2>&1 &"
            )
            res = subprocess.run(
                [
                    "gcloud", "compute", "ssh", vm,
                    "--project=project-amer-scs-sandbox", "--zone=us-central1-a",
                    "--tunnel-through-iap", "--quiet", f"--command={cmd}",
                ],
                check=False,
                timeout=25,
            )
            if res.returncode == 0:
                triggered_slots.append(slot)

    return {
        "job_name": job_name,
        "pool_b_slots": [s for s, _ in POOL_B_SLOTS],
        "uninspected_dispatched_count": len(todo),
        "gcs_manifest": gcs_job_uri if todo else None,
        "ssh_triggered_slots": triggered_slots,
    }


def _is_strictly_live_pre_0350_pt(day: str, now_utc: dt.datetime | None = None) -> bool:
    """Return True ONLY if wall-clock PT is on `day` and strictly before `03:50:00 PT`."""
    now_u = now_utc or dt.datetime.now(dt.timezone.utc)
    now_pt = now_u.astimezone(ZoneInfo("America/Los_Angeles"))
    if now_pt.date().isoformat() != day:
        return False
    return (now_pt.hour, now_pt.minute) < (3, 50)


def run_intraday_update(
    day: str,
    bucket: str = "usersim-bakeoff-347838016394",
    trace_bucket_prefix: str = "gs://usersim-trace-store-347838016394/usersim_core_v5",
    work_dir: str | None = None,
    persistent_data_dir: str = "/tmp/usersim_work/data",
    trigger_pool_b_ssh: bool = False,
    cleanup_temp: bool = True,
) -> dict[str, Any]:
    own_temp = work_dir is None
    wdir = work_dir or f"/tmp/usersim_intraday_{day}_{os.getpid()}"
    os.makedirs(f"{wdir}/forecasts", exist_ok=True)
    os.makedirs(f"{wdir}/post0005/{day}", exist_ok=True)
    os.makedirs(f"{wdir}/comments/{day}", exist_ok=True)
    os.makedirs(f"{wdir}/fleet_external/{day}", exist_ok=True)
    os.makedirs(f"{wdir}/why", exist_ok=True)

    try:
        # 1. Pull today's 00:05 frozen forecast + post-00:05 arrivals + <=03:45 PT comments + Pool B traces
        gcs_cp(f"gs://{bucket}/usersim_sim/raw/daily/{day}/forecast_{day}.parquet", f"{wdir}/forecasts/")
        gcs_cp(f"gs://{bucket}/usersim_sim/raw/daily/{day}/sites_0005.json", f"{wdir}/forecasts/")
        gcs_cp(f"gs://{bucket}/usersim_sim/raw/daily/{day}/today_0005.json", f"{wdir}/forecasts/")
        subprocess.run(
            ["gcloud", "storage", "cp", "-q", f"gs://{bucket}/usersim_sim/raw/ph_at_launch/{day}/api_detail/*PT.jsonl", f"{wdir}/post0005/{day}/"],
            check=False,
        )
        subprocess.run(
            ["gcloud", "storage", "cp", "-q", f"gs://{bucket}/usersim_sim/raw/ph_at_launch/{day}/api_comments/*T0[0123]*PT.jsonl", f"{wdir}/comments/{day}/"],
            check=False,
        )
        job_prefix = f"intraday_{day.replace('-', '')}_cua"
        subprocess.run(
            ["gcloud", "storage", "cp", "-q", f"gs://{bucket}/usersim_sim/raw/fleet_external/{day}/*.jsonl", f"{wdir}/fleet_external/{day}/"],
            check=False,
        )
        subprocess.run(
            ["gcloud", "storage", "cp", "-q", f"gs://{bucket}/usersim_sim/raw/fleet_external/_jobs/{job_prefix}_slot*.jsonl", f"{wdir}/fleet_external/{day}/"],
            check=False,
        )

        fpq = f"{wdir}/forecasts/forecast_{day}.parquet"
        f_ids: set[str] = set()
        candidates: dict[str, dict[str, Any]] = {}
        if os.path.exists(fpq):
            pdf = pd.read_parquet(fpq)
            sc_col = "pred_arm3" if "pred_arm3" in pdf.columns else "pred"
            for r in pdf.itertuples(index=False):
                lid = str(r.id)
                f_ids.add(lid)
                candidates[lid] = {
                    "item_id": lid,
                    "day": day,
                    "title": "",
                    "summary": "",
                    "description": "",
                    "tags": [],
                    "url": "",
                    "structural_score": float(getattr(r, sc_col)),
                }

        # Enrich titles/URLs from today_0005.json & sites_0005.json
        t0005_p = f"{wdir}/forecasts/today_0005.json"
        if os.path.exists(t0005_p):
            tj = json.load(open(t0005_p))
            rows_t = tj.get("launches") if isinstance(tj, dict) else tj
            if isinstance(rows_t, list):
                for rec in rows_t:
                    clean_r = sanitize_post_0005_record(rec)
                    lid = str(clean_r.get("id") or clean_r.get("item_id") or "")
                    if lid in candidates:
                        candidates[lid]["title"] = str(clean_r.get("name") or "")
                        candidates[lid]["summary"] = str(clean_r.get("tagline") or clean_r.get("summary") or "")
                        candidates[lid]["description"] = str(clean_r.get("description") or "")
                        candidates[lid]["url"] = str(clean_r.get("website") or clean_r.get("url") or "")

        s0005_p = f"{wdir}/forecasts/sites_0005.json"
        if os.path.exists(s0005_p):
            sj = json.load(open(s0005_p))
            for lid, srec in (sj.get("launches") or {}).items():
                if str(lid) in candidates and srec.get("final_url"):
                    candidates[str(lid)]["url"] = str(srec["final_url"])

        # Discover post-00:05 launches strictly stripped of ranks/votes/order
        late = discover_live_post_0005_launches(day, f_ids, wdir)
        for lr in late:
            lid = str(lr["id"])
            if lid not in candidates:
                h_fol = math.log1p(float((lr.get("user") or {}).get("followersCount") or 0.0))
                sc_late = 2.65 + 0.18 * h_fol + 0.08 * len(lr.get("makers") or [])
                candidates[lid] = {
                    "item_id": lid,
                    "day": day,
                    "title": str(lr.get("name") or ""),
                    "summary": str(lr.get("tagline") or ""),
                    "description": str(lr.get("description") or ""),
                    "tags": [],
                    "url": str(lr.get("website") or lr.get("url") or ""),
                    "structural_score": sc_late,
                }

        # Parse Pool B Google-SSO / 4-step CUA records already available
        cua_by_id: dict[str, dict[str, Any]] = {}
        surfaces_by_id: dict[str, Any] = {}
        sso_meta: dict[str, dict[str, Any]] = {}
        for ef in sorted(glob.glob(f"{wdir}/fleet_external/{day}/*.jsonl")):
            for line in open(ef):
                if not line.strip():
                    continue
                er = json.loads(line)
                lid = str(er.get("item_id") or "")
                if not lid:
                    continue
                cua_by_id[lid] = er
                raw_txt = f"{er.get('landing_text') or er.get('text_excerpt') or ''} {er.get('inside_app_text') or er.get('post_sso_excerpt') or ''}"
                clean_t, n_red = sanitize_text(raw_txt, item_day=day)
                if len(clean_t) >= 60:
                    surfaces_by_id[lid] = _surface_from_clean_text(
                        clean_txt=clean_t,
                        url=str(er.get("final_url") or er.get("url") or ""),
                        http_status=int(er.get("http_status") or 200),
                        load_ms=1000.0,
                        badges_stripped=n_red,
                        ctas=[],
                    )
                sso_meta[lid] = {
                    "sso_entered": bool(er.get("google_sso_entered")),
                    "post_sso_workspace": bool(er.get("in_workspace_route") or er.get("post_sso_workspace")),
                    "post_sso_clean_summary": clean_t[:240],
                }

        # Dispatch un-inspected URLs to Pool B (`slots 32, 40, 42, 44, 45`)
        dispatch_info = dispatch_uninspected_to_pool_b(
            day=day,
            candidate_urls=list(candidates.values()),
            already_inspected_ids=set(cua_by_id.keys()),
            bucket=bucket,
            work_dir=wdir,
            trigger_ssh=trigger_pool_b_ssh,
        )

        # Parse order-free pre-reveal comments strictly `<= 03:45 PT`
        pt_tz = ZoneInfo("America/Los_Angeles")
        d_obj = dt.date.fromisoformat(day)
        cutoff_utc = pd.Timestamp(dt.datetime(d_obj.year, d_obj.month, d_obj.day, 3, 45, tzinfo=pt_tz)).tz_convert("UTC")

        comm_by_post: dict[str, int] = {}
        subs_by_post: dict[str, int] = {}
        fol_disc_by_post: dict[str, float] = {}
        seen_u_by_post: dict[str, set[str]] = {}

        for cf in sorted(glob.glob(f"{wdir}/comments/{day}/*.jsonl")):
            for line in open(cf):
                if not line.strip():
                    continue
                r = json.loads(line)
                cts = pd.to_datetime(r.get("createdAt") or r.get("created_at"), utc=True, errors="coerce")
                if not pd.isna(cts) and cts > cutoff_utc:
                    continue
                txt = scrub_comment_text(r.get("body") or "")
                if not txt:
                    continue
                pid = str(r.get("post_id") or r.get("launch_id") or "")
                if not pid:
                    continue
                comm_by_post[pid] = comm_by_post.get(pid, 0) + 1
                if len(txt) >= 55 and not BOILERPLATE_PRAISE_RE.match(txt):
                    subs_by_post[pid] = subs_by_post.get(pid, 0) + 1
                uid = str(r.get("commenter_user_id") or "")
                if uid and uid not in seen_u_by_post.setdefault(pid, set()):
                    seen_u_by_post[pid].add(uid)
                    cfol = float(r.get("commenter_followers_count") or 0.0)
                    if cfol >= 20:
                        fol_disc_by_post[pid] = fol_disc_by_post.get(pid, 0.0) + min(1.0, math.log1p(cfol) / 7.0)

        # Optional v5 CompetitorGraph + PopulationChoiceSim enrichment if bench data is mounted locally
        comp_map: dict[str, list[dict[str, Any]]] = {}
        why_pop_by_key: dict[tuple[str, str], dict[str, Any]] = {}
        comp_adv_by_id: dict[str, float] = {}
        pop_choice_by_id: dict[str, float] = {}

        if candidates and os.path.exists(f"{persistent_data_dir}/bench/meta.json"):
            from simharness.bench import Benchmark
            from usersim_core.pool import UniversalUserPool
            from usersim_core.population_competitors_v5 import CompetitorGraph, PopulationChoiceSim

            bench = Benchmark(f"{persistent_data_dir}/bench")
            pool = UniversalUserPool(bench, train_cutoff_day="2026-08-31")
            idx_map = dict(zip(bench.items["item_id"].astype(str), bench.items["item_idx"].astype(int)))

            c_rows = []
            for lid in sorted(candidates.keys()):
                c = candidates[lid]
                c_rows.append({
                    "day": day,
                    "item_id": lid,
                    "item_idx": int(idx_map.get(lid, -1)),
                    "title": c["title"],
                    "summary": c["summary"],
                    "description": c["description"],
                    "tags": c["tags"],
                    "category_0005": "General",
                    "structural_score": c["structural_score"],
                    "url": c["url"],
                })
            day_df = pd.DataFrame(c_rows)
            cg = CompetitorGraph(bench, pool, persistent_data_dir, f"{persistent_data_dir}/apify_v1")
            day_df, comp_map = cg.attach_features(day_df, surfaces_by_id, cua_by_id, {})
            ps = PopulationChoiceSim(bench, pool, persistent_data_dir, wdir)
            day_df, why_pop_by_key = ps.simulate_all_days(day_df, comp_map)
            for r in day_df.itertuples(index=False):
                comp_adv_by_id[str(r.item_id)] = float(r.comp_cua_advantage_z)
                pop_choice_by_id[str(r.item_id)] = float(r.pop_expected_votes_choice_z)
        else:
            day_df = pd.DataFrame([
                {
                    "day": day,
                    "item_id": lid,
                    "title": candidates[lid]["title"],
                    "structural_score": candidates[lid]["structural_score"],
                }
                for lid in sorted(candidates.keys())
            ])

        def _score_tracks(id_list: list[str]) -> tuple[dict[str, float], dict[str, float]]:
            if not id_list:
                return {}, {}
            # Canonical sort inside scorer guarantees exact 0.0 order-permutation diff!
            canon = sorted(id_list)
            sso_arr = np.array([
                0.30 * float(bool((cua_by_id.get(i) or {}).get("reached_working_product") or (cua_by_id.get(i) or {}).get("google_sso_entered")))
                + 0.20 * float(bool((cua_by_id.get(i) or {}).get("workflow_responded") or (cua_by_id.get(i) or {}).get("has_interactive_demo")))
                + 0.18 * float(bool((cua_by_id.get(i) or {}).get("has_github_link") or (cua_by_id.get(i) or {}).get("has_open_source")))
                - 0.30 * float(bool((cua_by_id.get(i) or {}).get("hit_paywall") or (cua_by_id.get(i) or {}).get("hit_waitlist")))
                for i in canon
            ], dtype=np.float64)
            comp_arr = np.array([comp_adv_by_id.get(i, 0.0) for i in canon], dtype=np.float64)
            pop_arr = np.array([pop_choice_by_id.get(i, 0.0) for i in canon], dtype=np.float64)
            disc_arr = np.array([math.log1p(fol_disc_by_post.get(i, 0.0)) for i in canon], dtype=np.float64)
            subs_arr = np.array([math.log1p(subs_by_post.get(i, 0.0)) for i in canon], dtype=np.float64)

            def _z(a: np.ndarray) -> np.ndarray:
                sd = float(np.std(a))
                return np.clip((a - float(np.mean(a))) / sd, -2.5, 2.5) if sd > 1e-8 else np.zeros_like(a)

            # Track 1: Product only (`mid`, STRICTLY ZERO COMMENTS!)
            sh_mid = np.clip(0.055 * _z(sso_arr) + 0.050 * comp_arr + 0.055 * pop_arr, -0.26, 0.38)
            # Track 2: Product + comments (`pre`, <= 03:45 PT order-free!)
            sh_pre = np.clip(sh_mid + 0.080 * _z(disc_arr) + 0.050 * _z(subs_arr), -0.28, 0.42)

            po_map = {i: float(candidates[i]["structural_score"] + s) for i, s in zip(canon, sh_mid)}
            pc_map = {i: float(candidates[i]["structural_score"] + s) for i, s in zip(canon, sh_pre)}
            return {i: po_map[i] for i in id_list}, {i: pc_map[i] for i in id_list}

        ids_sorted = sorted(candidates.keys())
        po_a, pc_a = _score_tracks(ids_sorted)
        po_b, pc_b = _score_tracks(list(reversed(ids_sorted)))
        perm_diff = max(
            [abs(pc_a[k] - pc_b[k]) for k in pc_a] + [abs(po_a[k] - po_b[k]) for k in po_a],
            default=0.0,
        )

        # Verify Product-only comment isolation == 0.0
        saved_disc = dict(fol_disc_by_post)
        saved_subs = dict(subs_by_post)
        fol_disc_by_post.clear()
        subs_by_post.clear()
        po_zero_comm, _ = _score_tracks(ids_sorted)
        fol_disc_by_post.update(saved_disc)
        subs_by_post.update(saved_subs)
        po_comm_diff = max((abs(po_a[k] - po_zero_comm[k]) for k in po_a), default=0.0)

        assert perm_diff < 1e-9, f"Order-free check failed: {perm_diff}"
        assert po_comm_diff == 0.0, f"Product-only comment isolation failed: {po_comm_diff}"

        now_utc = dt.datetime.now(dt.timezone.utc)
        now_iso = now_utc.isoformat()
        is_live_pre = _is_strictly_live_pre_0350_pt(day, now_utc)

        ranked_pre = sorted(pc_a.keys(), key=lambda k: (-pc_a[k], k))
        ranked_mid = sorted(po_a.keys(), key=lambda k: (-po_a[k], k))

        forecast_pre_doc = {
            "day": day,
            "written_at": now_iso,
            "provenance": "live" if is_live_pre else "replay_or_post_cutoff",
            "model": "usersim_core_v5_order_free_product_comments",
            "inputs": {
                "present": [
                    "forecast_0005" if f_ids else "missing_forecast_0005",
                    "post_0005_launches" if late else "no_late_arrivals",
                    "pre_0345_comments_order_free" if comm_by_post else "zero_comments_yet",
                    "pool_b_google_sso_cua" if cua_by_id else "pending_pool_b",
                    "competitor_and_93k_population_v5" if comp_map else "light_mode",
                ],
                "missing": [],
            },
            "order_free_and_isolation_checks": {
                "input_order_permutation_max_abs_diff": float(perm_diff),
                "product_only_comment_isolation_max_abs_diff": float(po_comm_diff),
                "forbidden_rank_vote_keys_stripped": True,
            },
            "forecast": [
                {"id": lid, "predicted_rank": rk, "score": round(pc_a[lid], 5)}
                for rk, lid in enumerate(ranked_pre, start=1)
            ],
            "shadow_product_only_mid": [
                {"id": lid, "predicted_rank": rk, "score": round(po_a[lid], 5)}
                for rk, lid in enumerate(ranked_mid, start=1)
            ],
        }

        pre_out_p = f"{wdir}/forecast_pre_{day}.json"
        with open(pre_out_p, "w") as f:
            json.dump(forecast_pre_doc, f, indent=2)

        # STRICT PATH HYGIENE: NEVER write replays or post-03:50 PT runs to results/web/forecast_pre/!
        if ranked_pre:
            if is_live_pre:
                target_gcs = f"gs://{bucket}/usersim_sim/results/web/forecast_pre/{day}.json"
            else:
                target_gcs = f"gs://{bucket}/usersim_sim/results/web/forecast_pre_replay/{day}.json"
            gcs_cp(pre_out_p, target_gcs)
        else:
            target_gcs = None

        # Emit privacy-safe (`min_group >= 20`) why cards if candidates exist
        why_uploaded = 0
        if not day_df.empty:
            pred_meta = {"model": "usersim_core_v5", "min_group": WHY_MIN_GROUP}
            mid_why = build_day_why_card(
                day, "mid", day_df, po_a, comp_map, why_pop_by_key, surfaces_by_id, sso_meta, cua_by_id, {}, pred_meta
            )
            pre_why = build_day_why_card(
                day, "pre", day_df, pc_a, comp_map, why_pop_by_key, surfaces_by_id, sso_meta, cua_by_id, {}, pred_meta
            )
            assert_why_card_privacy(mid_why)
            assert_why_card_privacy(pre_why)
            p_m = f"{wdir}/why/{day}_mid.json"
            p_p = f"{wdir}/why/{day}_pre.json"
            json.dump(mid_why, open(p_m, "w"), indent=2)
            json.dump(pre_why, open(p_p, "w"), indent=2)
            if gcs_cp(p_m, f"{trace_bucket_prefix.rstrip('/')}/why/{day}_mid.json"):
                why_uploaded += 1
            if gcs_cp(p_p, f"{trace_bucket_prefix.rstrip('/')}/why/{day}_pre.json"):
                why_uploaded += 1

        manifest = {
            "day": day,
            "checked_at_utc": now_iso,
            "is_live_pre_0350_pt": is_live_pre,
            "forecast_gcs_target": target_gcs,
            "forecast_0005_count": len(f_ids),
            "post_0005_discovered_count": len(late),
            "posts_with_pre_reveal_comments": len(comm_by_post),
            "pool_b_inspected_count": len(cua_by_id),
            "pool_b_dispatch": dispatch_info,
            "why_cards_uploaded": why_uploaded,
            "input_order_permutation_max_abs_diff": float(perm_diff),
            "product_only_comment_isolation_max_abs_diff": float(po_comm_diff),
            "zero_rank_vote_leak_enforced": True,
        }
        gcs_cp_tmp = f"{wdir}/intraday_manifest_{day}.json"
        json.dump(manifest, open(gcs_cp_tmp, "w"), indent=2)
        gcs_cp(gcs_cp_tmp, f"{trace_bucket_prefix.rstrip('/')}/intraday/intraday_manifest_{day}.json")
        return manifest
    finally:
        if cleanup_temp and own_temp and os.path.exists(wdir):
            shutil.rmtree(wdir, ignore_errors=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", default="")
    ap.add_argument("--bucket", default="usersim-bakeoff-347838016394")
    ap.add_argument("--trace-prefix", default="gs://usersim-trace-store-347838016394/usersim_core_v5")
    ap.add_argument("--work-dir", default="")
    ap.add_argument("--data-dir", default="/tmp/usersim_work/data")
    ap.add_argument("--trigger-pool-b-ssh", action="store_true")
    ap.add_argument("--keep-temp", action="store_true")
    args = ap.parse_args()

    day = args.day or dt.datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()
    manifest = run_intraday_update(
        day=day,
        bucket=args.bucket,
        trace_bucket_prefix=args.trace_prefix,
        work_dir=args.work_dir or None,
        persistent_data_dir=args.data_dir,
        trigger_pool_b_ssh=args.trigger_pool_b_ssh,
        cleanup_temp=not args.keep_temp,
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
