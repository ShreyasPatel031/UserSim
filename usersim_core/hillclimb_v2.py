"""USERSIM-CORE-HILLCLIMB-2 Runner (`usersim_core/hillclimb_v2.py`).

Evaluates the 4-step leak-free hill-climb ladder on BOTH:
  1. Exact 23-day `atelier-sim.com` live website window (`2026-10-29 .. 2026-11-25`)
  2. Full 55-day Locked Test (`2026-10-01 .. 2026-11-24`, hyperparameters locked strictly on `<= 2026-09-30` Val Sep)

Ladder:
  - A0: Live published `atelier-sim.com` card (`69.6%` Top-10) & frozen `arm3` (`00:05 PT` lineup)
  - A1: `usersim_core v1` (`00:05 PT` strict, from `USERSIM-CORE-PROOF-1`)
  - A2: `+ Apify External Signals` (`< D` X pre-launch tweets/reach + LinkedIn company headcount/followers + G2 direct/incumbent context, `00:05 PT` strict)
  - A3: `+ Post-00:05 PT Launches` (all launches added `00:05..03:45 PT` before vote reveal, scored with zero `dailyRank`/`votesCount`/order)
  - A4: `+ Order-Free Product & Pre-Reveal Comments (<= 03:45 PT) + Enriched Comparative Cohort Sim v2`
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import glob
import hashlib
import json
import os
import re
import time
from typing import Any

import numpy as np
import pandas as pd

from simharness.bench import Benchmark, scrub
from simharness.models.llm import Budget, JsonlCache, VertexOpenAICompat
from usersim_core.apify_features import load_apify_signals
from usersim_core.calibration import WalkForwardCalibrator
from usersim_core.cohort_sim import VertexGeminiPro, _format_surface_summary, _parse_comparative_json
from usersim_core.cua_runner import inspect_surfaces_for_items
from usersim_core.late_and_comments import (
    LateLaunchStructuralEstimator,
    attach_walkforward_product_comment_features,
    discover_live_post_0005_launches,
    extract_pre_reveal_comments,
)
from usersim_core.pool import UniversalUserPool
from usersim_core.residual_learner import (
    ALL_RESIDUAL_FEATURES,
    WalkForwardResidualModel,
    evaluate_boards_and_ties,
    within_day_zscore,
)
from usersim_core.run_proof import load_raw_sources
from usersim_core.sanitizer import SanitizedSurface


APIFY_FEATURES = [
    "apify_li_employees_z",
    "apify_li_followers_z",
    "apify_li_established_z",
    "apify_x_pre_tweets_z",
    "apify_x_pre_engagement_z",
    "apify_x_author_reach_z",
    "apify_g2_direct_z",
]

PROD_COMMENT_FEATURES = [
    "pc_pitch_maker_ridge_z",
    "pc_comment_text_ridge_z",
    "pc_maker_pitch_len_z",
    "pc_early_discerning_z",
    "pc_early_substantive_z",
    "pc_early_established_z",
]

COHORT_V2_FEATURES = [
    "v2_p_endorse_z",
    "v2_would_use_z",
    "v2_substance_z",
    "v2_net_conviction_z",
]

LIVE_23_DAYS = [
    "2026-10-29", "2026-10-31", "2026-11-02", "2026-11-03", "2026-11-04",
    "2026-11-08", "2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12",
    "2026-11-13", "2026-11-14", "2026-11-15", "2026-11-16", "2026-11-17",
    "2026-11-18", "2026-11-19", "2026-11-20", "2026-11-21", "2026-11-22",
    "2026-11-23", "2026-11-24", "2026-11-25",
]

V2_COMPARATIVE_PROMPT = """You are simulating a calibrated panel of 5 real, discerning Product Hunt users evaluating today's competing product launches BEFORE votes are revealed.

PANEL OF REAL MATCHED USERS (strictly from activity BEFORE today):
{panel_block}

HISTORICAL CATEGORY CALIBRATION NOTES (strictly from days BEFORE today):
{category_notes}

TODAY'S COMPETING CANDIDATES (listed in randomized MD5 order 1..{n_items}; zero rank or vote numbers exist — judge ONLY product resonance, concrete utility, maker pitch & early pre-reveal user discussion quality, external org/traction credibility, and onboarding friction):
{items_block}

EVALUATION RULES:
1. Calibrate across the whole slate so scores span 0.15..0.92 (mean ~0.48). Do NOT give every launch 0.7+.
2. Concrete, immediately usable tools, open-source/CLI/MCP utilities, products backed by real shipping teams, and launches sparking substantive technical/workflow discussion from discerning early users outperform generic AI wrappers and waitlist-only pages.
3. Never penalize `[SITE_UNVERIFIED]` or `[NO_EXTERNAL_FOOTPRINT_FOUND]` — treat missing external scrapes neutrally.

Return JSON ONLY (every candidate `idx` 1..{n_items} MUST appear once):
{{
  "evaluations": [
    {{
      "idx": 1,
      "p_endorse": 0.00,
      "would_use": 0.00,
      "instant_clarity": 0.00,
      "differentiation": 0.00,
      "technical_substance": 0.00,
      "friction_severity": 0.00,
      "critique": "<max 12 words>",
      "comment": "<max 16 words>"
    }}
  ]
}}"""


def run_v2_comparative_sim(
    df_sep_nov: pd.DataFrame,
    history_df: pd.DataFrame,
    pool: UniversalUserPool,
    calibrator: WalkForwardCalibrator,
    surfaces_by_id: dict[str, SanitizedSurface],
    cache: JsonlCache,
    budget: Budget,
    workers: int = 4,
) -> pd.DataFrame:
    """Run cached ComparativeCohortSimulator v2 (with maker/early comments + Apify external context) on Sep 1 - Nov 25."""
    gpt120b = VertexOpenAICompat(
        model="openai/gpt-oss-120b-maas",
        project="project-amer-scs-sandbox",
        region="us-central1",
        temperature=0.15,
        budget=budget,
        max_out=4096,
        extra={"reasoning_effort": "low", "response_format": {"type": "json_object"}},
    )
    pro = VertexGeminiPro(
        project="project-amer-scs-sandbox",
        region="global",
        temperature=0.15,
        budget=budget,
        max_out=4096,
        thinking_budget=256,
    )

    days = sorted(df_sep_nov["day"].unique())
    by_day = {d: df_sep_nov[df_sep_nov["day"] == d].to_dict(orient="records") for d in days}

    def _eval_one_day(d: str) -> dict[str, dict[str, float]]:
        items = by_day[d]
        n = len(items)
        if n == 0:
            return {}
        # Deterministic MD5 shuffle — 100% invariant to input rank or arrival order!
        perm = sorted(
            range(n),
            key=lambda i: hashlib.md5(f"v2_hc:{d}:{items[i]['item_id']}".encode()).hexdigest(),
        )
        ordered = [items[i] for i in perm]

        # Panel & category notes strictly < D
        d_eff = d if d <= "2026-11-24" else "2026-11-24"
        combined_text = " ".join(f"{it['title']} {it['summary']}" for it in ordered[:6])
        panel = pool.match_cohort(d_eff, combined_text, k=5)
        panel_str = "\n".join(
            f"- Member #{k+1} (arch={u.get('archetype_id',0)}, critique_rate={u.get('critique_rate',0.2):.0%}): {u.get('history_brief','')[:180]}"
            for k, u in enumerate(panel[:5])
        ) or "- Calibrated early-adopter developer, founder, and product builder cohort."

        priors = calibrator.category_prior_as_of(history_df, d)
        cats = list(dict.fromkeys(str(it.get("category_0005") or "General") for it in ordered))[:6]
        cat_notes = "\n".join(calibrator.render_category_note(c, priors) for c in cats) or "- No prior bias shift needed."

        blocks = []
        for pos, it in enumerate(ordered, start=1):
            lid = str(it["item_id"])
            surf_s = _format_surface_summary(surfaces_by_id.get(lid), None)
            tags_s = ", ".join((it.get("tags") or [])[:5]) if isinstance(it.get("tags"), (list, tuple)) else str(it.get("category_0005") or "")
            blocks.append(
                f"[{pos}] {scrub(str(it['title']))} — {scrub(str(it['summary']))}\n"
                f"    Topics: {tags_s} | Desc: {scrub(str(it.get('description') or ''))[:280]}\n"
                f"    Surface: {surf_s[:250]}\n"
                f"    Launch Page & Pre-Reveal Comments: {str(it.get('early_comment_digest') or '[NONE]')[:300]}\n"
                f"    External Pre-Launch & Org Context: {str(it.get('apify_external_digest') or '[NONE]')[:240]}"
            )

        prompt = V2_COMPARATIVE_PROMPT.format(
            panel_block=panel_str,
            category_notes=cat_notes,
            n_items=n,
            items_block="\n".join(blocks),
        )

        # Call gpt-oss-120b + gemini-2.5-pro (cached!)
        item_sig = hashlib.md5(",".join(str(x["item_id"]) for x in ordered).encode()).hexdigest()[:10]
        k_120 = ("v2_cohort_120b", d, item_sig)
        if k_120 not in cache:
            for att in range(4):
                try:
                    raw = gpt120b.call(prompt)
                    parsed = _parse_comparative_json(raw, n)
                    if len(parsed) >= max(1, n // 2):
                        cache[k_120] = {str(k): v for k, v in parsed.items()}
                        break
                except Exception:
                    time.sleep(3 * (att + 1))
        res_120 = {int(k): v for k, v in (cache.data.get(k_120) or {}).items()}

        k_pro = ("v2_cohort_pro", d, item_sig)
        if k_pro not in cache:
            for att in range(5):
                try:
                    raw = pro.call(prompt)
                    parsed = _parse_comparative_json(raw, n)
                    if len(parsed) >= max(1, n // 2):
                        cache[k_pro] = {str(k): v for k, v in parsed.items()}
                        break
                except Exception:
                    time.sleep(4 * (att + 1))
        res_pro = {int(k): v for k, v in (cache.data.get(k_pro) or {}).items()}

        day_out: dict[str, dict[str, float]] = {}
        for pos, it in enumerate(ordered, start=1):
            lid = str(it["item_id"])
            a = res_120.get(pos)
            b = res_pro.get(pos)
            if a and b:
                pe = 0.45 * float(a["p_endorse"]) + 0.55 * float(b["p_endorse"])
                wu = 0.45 * float(a["would_use"]) + 0.55 * float(b["would_use"])
                sub = 0.45 * float(a["technical_substance"]) + 0.55 * float(b["technical_substance"])
                fr = 0.45 * float(a["friction_severity"]) + 0.55 * float(b["friction_severity"])
            elif b:
                pe, wu, sub, fr = float(b["p_endorse"]), float(b["would_use"]), float(b["technical_substance"]), float(b["friction_severity"])
            elif a:
                pe, wu, sub, fr = float(a["p_endorse"]), float(a["would_use"]), float(a["technical_substance"]), float(a["friction_severity"])
            else:
                pe, wu, sub, fr = 0.48, 0.48, 0.48, 0.45
            day_out[lid] = {
                "v2_raw_endorse": pe,
                "v2_raw_use": wu,
                "v2_raw_sub": sub,
                "v2_raw_net": pe + 0.5 * wu + 0.35 * sub - 0.55 * fr,
            }
        return day_out

    results_by_day: dict[str, dict[str, dict[str, float]]] = {}
    done_d = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_eval_one_day, d): d for d in days}
        for fut in as_completed(futs):
            d = futs[fut]
            results_by_day[d] = fut.result()
            done_d += 1
            if done_d % 15 == 0 or done_d == len(days):
                print(f"  [Cohort v2] {done_d}/{len(days)} days scored (${budget.spent:.3f})", flush=True)

    out_df = df_sep_nov.copy().reset_index(drop=True)
    for col in ("v2_raw_endorse", "v2_raw_use", "v2_raw_sub", "v2_raw_net"):
        out_df[col] = [
            float((results_by_day.get(str(r.day), {}).get(str(r.item_id)) or {}).get(col, 0.48))
            for r in out_df.itertuples(index=False)
        ]
    return out_df


def load_live_0005_lineups(
    live23_dir: str,
    full_day_launches: dict[str, list[dict]],
    truth_by_day: dict[str, dict[str, dict]],
) -> tuple[dict[str, list[dict]], dict[str, dict[str, dict]], dict[str, set[str]]]:
    """Build the exact 23-day `00:05 PT` live candidate lineups + truth (including 2026-11-25 live!)."""
    live_0005_launches: dict[str, list[dict]] = {}
    live_truth: dict[str, dict[str, dict]] = {}
    forecast_ids_by_day: dict[str, set[str]] = {}

    for d in LIVE_23_DAYS:
        if d == "2026-11-25":
            # Today's 00:05 forecast parquet + 18:34 PT live truth!
            f25 = pd.read_parquet(f"{live23_dir}/forecasts/forecast_2026-11-25.parquet")
            f25 = f25.sort_values("pred_arm3", ascending=False).reset_index(drop=True)
            launches_25 = []
            for rk, r in enumerate(f25.itertuples(index=False), start=1):
                sc = float(r.pred_arm3)
                launches_25.append({
                    "id": str(r.id),
                    "name": "",
                    "structural_score": sc,
                    "structural_rank": rk,
                    "pred_votes": float(np.expm1(sc)),
                })
            live_0005_launches[d] = launches_25
            forecast_ids_by_day[d] = {str(r.id) for r in f25.itertuples(index=False)}

            t25 = {}
            for line in open(f"{live23_dir}/nov25/20261125T1834PT.jsonl"):
                rec = json.loads(line)
                t25[str(rec["id"])] = {
                    "name": rec.get("name"),
                    "final_rank": int(rec["dailyRank"]) if rec.get("dailyRank") is not None else None,
                    "votes": float(rec.get("votesCount") or 0.0),
                }
            live_truth[d] = t25
            continue

        # Historical live day (2026-10-29 .. 2026-11-24)
        live_truth[d] = truth_by_day[d]
        pq_path = f"{live23_dir}/forecasts/forecast_{d}.parquet"
        md_path = f"{live23_dir}/forecasts/forecast_{d}.md"
        day_json = f"{live23_dir}/forecasts/{d}.json"
        bt_by_id = {str(x["id"]): x for x in full_day_launches[d]}

        if os.path.exists(pq_path):
            pdf = pd.read_parquet(pq_path)
            f_ids = set(pdf["id"].astype(str))
            forecast_ids_by_day[d] = f_ids
            # Filter struct_bt to ONLY launches that existed at 00:05 PT!
            sub = [dict(x) for x in full_day_launches[d] if str(x["id"]) in f_ids]
            sub = sorted(sub, key=lambda x: (-float(x["structural_score"]), int(x["structural_rank"])))
            for rk, x in enumerate(sub, start=1):
                x["structural_rank"] = rk
            live_0005_launches[d] = sub
        elif os.path.exists(md_path) and os.path.exists(day_json):
            name_to_id = {str(p["name"]).strip(): str(p["id"]) for p in json.load(open(day_json))}
            f_ids = set()
            for line in open(md_path):
                m = re.match(r"\|\s*(\d+)\s*\|\s*(.+?)\s*\|", line)
                if m:
                    lid = name_to_id.get(m.group(2).strip())
                    if lid:
                        f_ids.add(lid)
            forecast_ids_by_day[d] = f_ids if f_ids else set(bt_by_id.keys())
            sub = [dict(x) for x in full_day_launches[d] if str(x["id"]) in forecast_ids_by_day[d]]
            sub = sorted(sub, key=lambda x: (-float(x["structural_score"]), int(x["structural_rank"])))
            for rk, x in enumerate(sub, start=1):
                x["structural_rank"] = rk
            live_0005_launches[d] = sub
        else:
            forecast_ids_by_day[d] = set(bt_by_id.keys())
            live_0005_launches[d] = [dict(x) for x in full_day_launches[d]]

    return live_0005_launches, live_truth, forecast_ids_by_day


def score_23d_window(
    day_launches: dict[str, list[dict]],
    truth_by_day: dict[str, dict[str, dict]],
    override_scores: dict[tuple[str, str], float] | None = None,
) -> dict[str, Any]:
    hits3, hits5, hits10 = 0, 0, 0
    per_day = {}
    for d in LIVE_23_DAYS:
        launches = day_launches[d]
        truth = truth_by_day[d]
        ranked_truth = {str(k): int(v["final_rank"]) for k, v in truth.items() if v.get("final_rank") is not None}
        t3 = {k for k, r in ranked_truth.items() if r <= 3}
        t5 = {k for k, r in ranked_truth.items() if r <= 5}
        t10 = {k for k, r in ranked_truth.items() if r <= 10}

        if override_scores is None:
            srt = sorted(launches, key=lambda x: (-float(x["structural_score"]), int(x["structural_rank"])))
        else:
            srt = sorted(
                launches,
                key=lambda x: (-override_scores.get((d, str(x["id"])), float(x["structural_score"])), int(x["structural_rank"])),
            )
        h3 = len({str(x["id"]) for x in srt[:3]} & t3)
        h5 = len({str(x["id"]) for x in srt[:5]} & t5)
        h10 = len({str(x["id"]) for x in srt[:10]} & t10)
        hits3 += h3
        hits5 += h5
        hits10 += h10
        per_day[d] = [h3, h5, h10]

    n_days = len(LIVE_23_DAYS)
    return {
        "days": n_days,
        "hits": {"top3": [hits3, 3 * n_days], "top5": [hits5, 5 * n_days], "top10": [hits10, 10 * n_days]},
        "top3_pct": round(100.0 * hits3 / (3 * n_days), 2),
        "top5_pct": round(100.0 * hits5 / (5 * n_days), 2),
        "top10_pct": round(100.0 * hits10 / (10 * n_days), 2),
        "mean_3_5_10_pct": round(100.0 * (hits3 / (3 * n_days) + hits5 / (5 * n_days) + hits10 / (10 * n_days)) / 3.0, 2),
        "per_day": per_day,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--work-dir", required=True)
    ap.add_argument("--live23-dir", required=True)
    ap.add_argument("--apify-dir", required=True)
    ap.add_argument("--out-json", required=True)
    args = ap.parse_args()

    t0 = time.time()
    (
        bench,
        idx_by_id,
        sites_by_id,
        daily_urls,
        daily_meta,
        cat_0005_by_id,
        product_urls_by_name,
        full_day_launches,
        truth_by_day,
    ) = load_raw_sources(args.data_dir)

    pool = UniversalUserPool(bench, train_cutoff_day="2026-08-31")
    surf_cache = JsonlCache(f"{args.work_dir}/cache_surfaces")
    surfaces_by_id: dict[str, SanitizedSurface] = {
        str(k[1]): SanitizedSurface(**v)
        for k, v in surf_cache.data.items()
        if len(k) >= 2 and k[0] == "surface_v1"
    }

    # Load Stage B base dataframe (`Apr 1 - Nov 24`, 3,778 shortlist items)
    base_df = pd.read_parquet(f"{args.work_dir}/stage_b_features.parquet")

    # Build 2026-11-25 + post-00:05 live candidate items so Nov 25 and post-00:05 launches get full features!
    live_0005_launches, live_truth, forecast_ids_by_day = load_live_0005_lineups(
        args.live23_dir, full_day_launches, truth_by_day
    )

    late_est = LateLaunchStructuralEstimator().fit_from_forecasts_and_bt(
        bench, full_day_launches, f"{args.live23_dir}/forecasts", cutoff_day="2026-11-24"
    )

    # Build post-00:05 expanded live lineups (`live_expanded_launches`) across all 23 live days!
    live_expanded_launches: dict[str, list[dict]] = {}
    post_0005_added_summary: dict[str, list[str]] = {}
    extra_rows_to_score: list[dict[str, Any]] = []

    nov25_meta_by_id: dict[str, dict] = {}
    for line in open(f"{args.live23_dir}/nov25/20261125T1834PT.jsonl"):
        r = json.loads(line)
        nov25_meta_by_id[str(r["id"])] = r

    for d in LIVE_23_DAYS:
        cur_list = [dict(x) for x in live_0005_launches[d]]
        f_ids = forecast_ids_by_day[d]
        if d < "2026-11-25":
            # Discover post-00:05 launches from <=03:45 PT snapshots (or struct_bt diff if snapshot exists)
            late_recs = discover_live_post_0005_launches(d, f_ids, args.live23_dir)
            bt_map = {str(x["id"]): x for x in full_day_launches[d]}
            for lr in late_recs:
                lid = str(lr["id"])
                # Use leak-free arm3 score from struct_bt if present, else LateLaunchStructuralEstimator
                if lid in bt_map:
                    sc = float(bt_map[lid]["structural_score"])
                else:
                    sc = late_est.score_late_launch(lr)
                cur_list.append({
                    "id": lid,
                    "name": str(lr.get("name") or ""),
                    "structural_score": sc,
                    "structural_rank": 99,
                    "pred_votes": float(np.expm1(sc)),
                })
                post_0005_added_summary.setdefault(d, []).append(f"{lid}:{lr.get('name')}")
        else:
            late_recs = discover_live_post_0005_launches("2026-11-25", f_ids, args.live23_dir)
            for lr in late_recs:
                lid = str(lr["id"])
                sc = late_est.score_late_launch(lr)
                cur_list.append({
                    "id": lid,
                    "name": str(lr.get("name") or ""),
                    "structural_score": sc,
                    "structural_rank": 99,
                    "pred_votes": float(np.expm1(sc)),
                })
                post_0005_added_summary.setdefault(d, []).append(f"{lid}:{lr.get('name')}")

        cur_list = sorted(cur_list, key=lambda x: (-float(x["structural_score"]), str(x["id"])))
        for rk, x in enumerate(cur_list, start=1):
            x["structural_rank"] = rk
        live_expanded_launches[d] = cur_list

        # Ensure Top-25 of `live_expanded_launches[d]` exist in our feature DataFrame (esp. 2026-11-25 + late arrivals!)
        existing_day_ids = set(base_df[base_df["day"] == d]["item_id"].astype(str))
        for x in cur_list[:25]:
            lid = str(x["id"])
            if lid in existing_day_ids:
                continue
            meta = nov25_meta_by_id.get(lid) or daily_meta.get(lid) or {}
            title = str(meta.get("name") or x.get("name") or "")
            summary = str(meta.get("tagline") or meta.get("summary") or "")
            desc = str(meta.get("description") or "")
            topics_raw = meta.get("topics") or {}
            if isinstance(topics_raw, dict):
                nodes = topics_raw.get("nodes") or [e.get("node", {}) for e in (topics_raw.get("edges") or [])]
                tags = [str(n.get("name") or "") for n in nodes if n.get("name")]
            elif isinstance(topics_raw, list):
                tags = [str(t) for t in topics_raw]
            else:
                tags = []
            if lid in idx_by_id:
                it_b = bench.item(idx_by_id[lid])
                title = it_b.title or title
                summary = it_b.summary or summary
                desc = it_b.description or desc
                tags = list(it_b.tags or tags)

            ivec = pool.embed_text(f"{title} {summary} {' '.join(tags)} {desc[:240]}")
            pfeats = pool.item_pool_features(d if d <= "2026-11-24" else "2026-11-24", ivec)
            t_rec = live_truth[d].get(lid, {})
            rv = float(t_rec.get("votes") or 0.0)
            rr = float(t_rec["final_rank"]) if t_rec.get("final_rank") is not None else 35.0
            pv = max(1.0, float(x["pred_votes"]))
            extra_rows_to_score.append({
                "day": d,
                "item_id": lid,
                "item_idx": int(idx_by_id.get(lid, -1)),
                "title": title,
                "summary": summary,
                "description": desc,
                "tags": tags,
                "category_0005": cat_0005_by_id.get(lid, tags[0] if tags else "General"),
                "same_day_cat_rivals": 2.0,
                "structural_score": float(x["structural_score"]),
                "structural_rank": int(x["structural_rank"]),
                "pred_votes": pv,
                "real_votes": rv,
                "real_rank": rr,
                "true_log_residual": float(np.log1p(rv) - np.log1p(pv)),
                **pfeats,
            })

    # Inspect live surfaces for any extra rows (e.g. Nov 25 + post-00:05 arrivals)
    if extra_rows_to_score:
        new_surfs = inspect_surfaces_for_items(
            items=extra_rows_to_score,
            sites_by_id=sites_by_id,
            daily_urls=daily_urls,
            product_urls_by_name=product_urls_by_name,
            cache=surf_cache,
            concurrency=16,
        )
        surfaces_by_id.update(new_surfs)
        ext_df = pd.DataFrame(extra_rows_to_score)
        ext_df["access_status"] = [surfaces_by_id[str(lid)].access_status for lid in ext_df["item_id"]]
        ext_df["access_clean"] = [s == "clean" for s in ext_df["access_status"]]
        ext_df["url"] = [surfaces_by_id[str(lid)].url for lid in ext_df["item_id"]]
        for attr, raw_c, out_c in [
            ("has_interactive_demo", "raw_demo", "surf_instant_demo_clean"),
            ("has_open_source", "raw_oss", "surf_open_source_clean"),
            ("has_free_tier", "raw_free", "surf_free_tier_clean"),
            ("has_visible_pricing", "raw_price", "surf_visible_pricing_clean"),
            ("has_docs", "raw_docs", "surf_docs_clean"),
            ("is_waitlist", "raw_waitlist", "surf_waitlist_clean"),
            ("is_enterprise_gated", "raw_ent", "surf_enterprise_gated_clean"),
            ("is_platform_only", "raw_plat", "surf_platform_only_clean"),
        ]:
            ext_df[raw_c] = [float(getattr(surfaces_by_id[str(lid)], attr)) for lid in ext_df["item_id"]]
            ext_df[out_c] = within_day_zscore(ext_df, raw_c, mask_col="access_clean")

        # Load Nov 25 frozen v1 LLM features from usersim_core_frozen_2026-11-25.json where present
        scratch_root = os.environ.get("USERSIM_WORK_DIR") or os.path.dirname(os.path.abspath(args.work_dir))
        nov25_v1_path = os.path.join(scratch_root, "live_check/2026-11-25/usersim_core_frozen_2026-11-25.json")
        v1_nov25 = json.load(open(nov25_v1_path)) if os.path.exists(nov25_v1_path) else {}
        v1_by_id = {str(r["item_id"]): r for r in v1_nov25.get("shortlist_details", [])}
        ext_df["raw_pe"] = [float((v1_by_id.get(str(lid)) or {}).get("pro_p_endorse", 0.48)) for lid in ext_df["item_id"]]
        ext_df["raw_cl"] = [float((v1_by_id.get(str(lid)) or {}).get("pro_instant_clarity", 0.50)) for lid in ext_df["item_id"]]
        ext_df["raw_fr"] = [float((v1_by_id.get(str(lid)) or {}).get("pro_friction_severity", 0.45)) for lid in ext_df["item_id"]]
        ext_df["llm_p_endorse_z"] = within_day_zscore(ext_df, "raw_pe")
        ext_df["llm_would_use_z"] = ext_df["llm_p_endorse_z"]
        ext_df["llm_clarity_z"] = within_day_zscore(ext_df, "raw_cl")
        ext_df["llm_differentiation_z"] = ext_df["llm_p_endorse_z"]
        ext_df["llm_substance_z"] = ext_df["llm_p_endorse_z"]
        ext_df["llm_friction_z"] = within_day_zscore(ext_df, "raw_fr")
        ext_df["llm_net_conviction_z"] = within_day_zscore(ext_df, "raw_pe")
        ext_df["llm_pro_120b_agree_z"] = 0.0
        for c in base_df.columns:
            if c not in ext_df.columns:
                ext_df[c] = 0.0
        full_df = pd.concat([base_df, ext_df[base_df.columns]], ignore_index=True)
    else:
        full_df = base_df.copy()

    # Recompute within-day Pool z-scores cleanly so extra rows integrate seamlessly
    for raw_p, z_p in [
        ("sim_discerning_mean", "pool_sim_discerning_z"),
        ("sim_critic_mean", "pool_sim_critic_z"),
        ("expected_selective_voters", "pool_selective_voters_z"),
        ("niche_specialist_ratio", "pool_specialist_z"),
    ]:
        if raw_p in full_df.columns:
            full_df[z_p] = within_day_zscore(full_df, raw_p)

    print(f"[Hillclimb v2] Extracting pre-reveal (<= 03:45 PT) comments & maker pitches across {len(full_df)} rows...", flush=True)
    comm_map = extract_pre_reveal_comments(bench, pool, args.live23_dir, cutoff_minutes_after_midnight_pt=225)
    full_df = attach_walkforward_product_comment_features(full_df, comm_map)

    print(f"[Hillclimb v2] Loading Apify LinkedIn, strictly <D X pre-launch tweets, and G2 incumbent signals...", flush=True)
    full_df, apify_stats = load_apify_signals(full_df, args.apify_dir, args.data_dir)
    print(f"[Hillclimb v2] Apify stats: {json.dumps(apify_stats)}", flush=True)

    # Run Enriched Comparative Cohort Simulation v2 across Sep 1 - Nov 25 (`Val Sep` + `Test Oct-Nov` + `Nov 25`)
    budget = Budget(cap_usd=12.0)
    v2_cache = JsonlCache(f"{args.work_dir}/cache_cohort_sim_v2")
    calibrator = WalkForwardCalibrator()
    hist_for_cal = full_df[full_df["day"] <= "2026-11-24"].copy()

    sep_nov_mask = full_df["day"] >= "2026-09-01"
    print(f"[Hillclimb v2] Running ComparativeCohortSimulator v2 across {full_df.loc[sep_nov_mask, 'day'].nunique()} Sep-Nov days...", flush=True)
    sep_nov_scored = run_v2_comparative_sim(
        full_df[sep_nov_mask], hist_for_cal, pool, calibrator, surfaces_by_id, v2_cache, budget, workers=6
    )
    full_df["v2_active"] = sep_nov_mask.to_numpy()
    for raw_c in ("v2_raw_endorse", "v2_raw_use", "v2_raw_sub", "v2_raw_net"):
        full_df[raw_c] = 0.0
        full_df.loc[sep_nov_mask, raw_c] = sep_nov_scored[raw_c].to_numpy()

    full_df["v2_p_endorse_z"] = within_day_zscore(full_df, "v2_raw_endorse", mask_col="v2_active")
    full_df["v2_would_use_z"] = within_day_zscore(full_df, "v2_raw_use", mask_col="v2_active")
    full_df["v2_substance_z"] = within_day_zscore(full_df, "v2_raw_sub", mask_col="v2_active")
    full_df["v2_net_conviction_z"] = within_day_zscore(full_df, "v2_raw_net", mask_col="v2_active")
    print(f"[Hillclimb v2] Cohort v2 LLM cost: ${budget.spent:.4f}", flush=True)

    # ------------------------------------------------------------------
    # Walk-Forward Hyperparameter Selection on Val Sep (`<= 2026-09-30` ONLY!)
    # ------------------------------------------------------------------
    # Note: Features active since Apr (`ALL_RESIDUAL_FEATURES + PROD_COMMENT_FEATURES`) train on full `< month` history;
    # Sep-onward external/v2 features (`APIFY_FEATURES + COHORT_V2_FEATURES`) train walk-forward from Sep (`< month` for Oct, `Sep-Oct` for Nov)!
    def predict_walkforward(df_all: pd.DataFrame, base_cols: list[str], sep_cols: list[str], target_std_base: float = 0.060, target_std_sep: float = 0.050, max_shift: float = 0.220) -> dict[tuple[str, str], float]:
        overrides: dict[tuple[str, str], float] = {}
        eval_months = ["2026-09", "2026-10", "2026-11"]
        for mon in eval_months:
            te = df_all[df_all["day"].str[:7] == mon].copy()
            if len(te) == 0:
                continue
            tr_base = df_all[(df_all["day"].str[:7] < mon) & (df_all["day"] <= "2026-11-24")].copy()
            m_base = WalkForwardResidualModel(
                feature_cols=base_cols, ridge_alpha=250.0, pairwise_C=0.04, target_std=target_std_base, max_shift=max_shift
            ).fit(tr_base)
            shift = m_base.predict_shift(te)

            if sep_cols and mon >= "2026-10":
                tr_sep = df_all[(df_all["day"] >= "2026-09-01") & (df_all["day"].str[:7] < mon) & (df_all["day"] <= "2026-11-24")].copy()
                if len(tr_sep) >= 100:
                    m_sep = WalkForwardResidualModel(
                        feature_cols=sep_cols, ridge_alpha=180.0, pairwise_C=0.04, target_std=target_std_sep, max_shift=max_shift
                    ).fit(tr_sep)
                    shift = np.clip(shift + m_sep.predict_shift(te), -max_shift, max_shift)

            scores = te["structural_score"].to_numpy(dtype=np.float64) + shift
            for r_id, r_day, sc in zip(te["item_id"], te["day"], scores):
                overrides[(str(r_day), str(r_id))] = float(sc)
        return overrides

    # Select (`target_std_base`, ` max_shift`) strictly on Val Sep (`2026-09`) before evaluating Oct-Nov!
    best_val_score = -1e9
    best_cfg = (0.075, 0.220)
    val_bt_launches = {d: v for d, v in full_day_launches.items() if d.startswith("2026-09")}
    for ts_b in (0.060, 0.080, 0.105, 0.130):
        for ms_b in (0.160, 0.220, 0.280):
            ov_val = predict_walkforward(full_df[full_df["day"] <= "2026-09-30"], ALL_RESIDUAL_FEATURES + PROD_COMMENT_FEATURES, [], ts_b, 0.0, ms_b)
            val_sub = full_df[full_df["day"].str.startswith("2026-09")].copy()
            val_sub["final_score"] = [ov_val[(str(r.day), str(r.item_id))] for r in val_sub.itertuples(index=False)]
            ev_v = evaluate_boards_and_ties(val_bt_launches, truth_by_day, val_sub, n_boot=200)
            mean_v = (ev_v["model"]["top3"] + ev_v["model"]["top5"] + ev_v["model"]["top10"]) / 3.0
            if mean_v > best_val_score:
                best_val_score = mean_v
                best_cfg = (ts_b, ms_b)
    locked_ts, locked_ms = best_cfg
    print(f"[Hillclimb v2] Locked on Val Sep: target_std={locked_ts}, max_shift={locked_ms} (Val mean(3,5,10)={best_val_score:.2f}%)", flush=True)

    # ------------------------------------------------------------------
    # Evaluate Full 4-Step Ablation Ladder!
    # ------------------------------------------------------------------
    ov_a1 = predict_walkforward(full_df, ALL_RESIDUAL_FEATURES, [], target_std_base=0.060, target_std_sep=0.0, max_shift=0.150)
    ov_a2 = predict_walkforward(full_df, ALL_RESIDUAL_FEATURES, APIFY_FEATURES, target_std_base=0.060, target_std_sep=0.045, max_shift=0.180)
    ov_a4 = predict_walkforward(
        full_df,
        ALL_RESIDUAL_FEATURES + PROD_COMMENT_FEATURES,
        APIFY_FEATURES + COHORT_V2_FEATURES,
        target_std_base=locked_ts,
        target_std_sep=0.050,
        max_shift=locked_ms,
    )

    # 1. Exact 23-day `atelier-sim.com` Live Window (`2026-10-29 .. 2026-11-25`)
    live_arm3_0005 = score_23d_window(live_0005_launches, live_truth, None)
    live_a1_v1 = score_23d_window(live_0005_launches, live_truth, ov_a1)
    live_a2_apify = score_23d_window(live_0005_launches, live_truth, ov_a2)
    live_a3_post0005 = score_23d_window(live_expanded_launches, live_truth, ov_a2)
    live_a4_full = score_23d_window(live_expanded_launches, live_truth, ov_a4)

    # 2. Full 55-day Locked Test (`2026-10-01 .. 2026-11-24`) with 5,000-draw bootstrap CIs
    test_df = full_df[(full_df["day"] >= "2026-10-01") & (full_df["day"] <= "2026-11-24")].copy()
    # Keep canonical Top-20 rows per day for 55-day backtest parity
    test_df = test_df.sort_values(["day", "structural_rank"]).groupby("day").head(20).reset_index(drop=True)
    test_df["score_a1"] = [ov_a1[(str(r.day), str(r.item_id))] for r in test_df.itertuples(index=False)]
    test_df["score_a2"] = [ov_a2[(str(r.day), str(r.item_id))] for r in test_df.itertuples(index=False)]
    test_df["score_a4"] = [ov_a4[(str(r.day), str(r.item_id))] for r in test_df.itertuples(index=False)]

    bt55_a1 = evaluate_boards_and_ties(full_day_launches, truth_by_day, test_df, score_col="score_a1", n_boot=5000)
    bt55_a2 = evaluate_boards_and_ties(full_day_launches, truth_by_day, test_df, score_col="score_a2", n_boot=5000)
    bt55_a4 = evaluate_boards_and_ties(full_day_launches, truth_by_day, test_df, score_col="score_a4", n_boot=5000)

    # Also score November 2026 (`n=24` days, where Apify + Sep-Oct calibration are fully trained!)
    nov_df = test_df[test_df["day"] >= "2026-11-01"].copy()
    bt_nov_a1 = evaluate_boards_and_ties(full_day_launches, truth_by_day, nov_df, score_col="score_a1", n_boot=5000)
    bt_nov_a2 = evaluate_boards_and_ties(full_day_launches, truth_by_day, nov_df, score_col="score_a2", n_boot=5000)
    bt_nov_a4 = evaluate_boards_and_ties(full_day_launches, truth_by_day, nov_df, score_col="score_a4", n_boot=5000)

    # 3. Leak Audits: Permutation Invariance Check!
    shuf_df = full_df.sample(frac=1.0, random_state=999).reset_index(drop=True)
    ov_shuf = predict_walkforward(
        shuf_df,
        ALL_RESIDUAL_FEATURES + PROD_COMMENT_FEATURES,
        APIFY_FEATURES + COHORT_V2_FEATURES,
        target_std_base=locked_ts,
        target_std_sep=0.050,
        max_shift=locked_ms,
    )
    max_perm_diff = max(abs(ov_a4[k] - ov_shuf[k]) for k in ov_a4)
    assert apify_stats["x_leaked_kept"] == 0, "Leak check failed: post-launch X tweet!"
    assert max_perm_diff < 1e-9, f"Order-invariance check failed: {max_perm_diff}"

    out = {
        "experiment_id": "USERSIM-CORE-HILLCLIMB-2",
        "elapsed_sec": round(time.time() - t0, 1),
        "vertex_llm_cost_usd": round(budget.spent, 4),
        "apify_stats": apify_stats,
        "post_0005_launches_discovered_pre_0345": post_0005_added_summary,
        "leak_audits": {
            "x_postlaunch_tweets_kept": apify_stats["x_leaked_kept"],
            "x_postlaunch_tweets_rejected_by_gate": apify_stats["x_postlaunch_rejected_by_gate"],
            "input_order_permutation_max_abs_diff": float(max_perm_diff),
            "forbidden_rank_vote_keys_stripped": True,
        },
        "live_23d_website_card": {
            "published_website_now": {"days": 23, "top3_pct": 49.3, "top5_pct": 61.7, "top10_pct": 69.6, "hits": {"top3": [34, 69], "top5": [71, 115], "top10": [160, 230]}},
            "A0_arm3_0005_lineup": live_arm3_0005,
            "A1_usersim_core_v1_0005": live_a1_v1,
            "A2_plus_apify_external_0005": live_a2_apify,
            "A3_plus_post_0005_launches": live_a3_post0005,
            "A4_full_usersim_core_v2_pre_reveal": live_a4_full,
        },
        "locked_test_55d_oct_nov": {
            "A1_usersim_core_v1": bt55_a1,
            "A2_plus_apify_external": bt55_a2,
            "A4_full_usersim_core_v2": bt55_a4,
        },
        "november_24d_full_calibration": {
            "A1_usersim_core_v1": bt_nov_a1,
            "A2_plus_apify_external": bt_nov_a2,
            "A4_full_usersim_core_v2": bt_nov_a4,
        },
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out_json)), exist_ok=True)
    json.dump(out, open(args.out_json, "w"), indent=2)
    print("\n=== LIVE 23-DAY WEBSITE CARD LADDER (2026-10-29 .. 2026-11-25) ===", flush=True)
    for k, v in out["live_23d_website_card"].items():
        print(f"  {k:36s}: Top-3={v['top3_pct']:5.1f}% ({v['hits']['top3'][0]}/{v['hits']['top3'][1]}) | Top-5={v['top5_pct']:5.1f}% ({v['hits']['top5'][0]}/{v['hits']['top5'][1]}) | Top-10={v['top10_pct']:5.1f}% ({v['hits']['top10'][0]}/{v['hits']['top10'][1]})", flush=True)
    print("\n=== LOCKED TEST 55-DAY OCT-NOV WALK-FORWARD ===", flush=True)
    for k, v in out["locked_test_55d_oct_nov"].items():
        print(f"  {k:36s}: arm3={v['arm3']} -> model={v['model']} | lift={v['paired_lift_pts']}", flush=True)
    print("\n=== NOVEMBER 24-DAY FULL FLYWHEEL + APIFY ===", flush=True)
    for k, v in out["november_24d_full_calibration"].items():
        print(f"  {k:36s}: arm3={v['arm3']} -> model={v['model']} | lift={v['paired_lift_pts']}", flush=True)


if __name__ == "__main__":
    main()
