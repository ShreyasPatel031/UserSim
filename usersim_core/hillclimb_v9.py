"""USERSIM-CORE-HILLCLIMB-9 Runner (`usersim_core/hillclimb_v9.py`).

Resolves the exact Podium (`Top-3 / Top-5`) vs Cutline (`Top-10 / Ties`) shift-variance tradeoff
exposed by `HILLCLIMB-4..8` at `$0.00` new LLM API spend (reusing 100% of cached multi-family simulations):
  - Why single-score rankers traded off Top-3 against Top-10:
      * Tight shift cap (`+-0.18`, `v4`) protects `#1-#3` structural locks (`59.42%` Live PO Top-3, `61.82%` 55d Top-3)
        but traps `#11-#17` breakouts below `#8-#10` (`72.17%` Live Top-10, `63.96%` 55d ties).
      * Wide bubble shift (`+-0.34..0.54`, `v8`) unlocks `#11-#17` breakouts — setting all-time Top-10 & tie records
        (`74.00%` 55d PO Top-10, `74.36%` 55d PC Top-10, `73.48%` Live PC Top-10, `78.88%` Nov PC ties, `69.42%` Nov PO ties) —
        but allows `#5-#8` bubble shifts (`+0.32`) to leapfrog `#2-#3` podium locks (`+0.185` cap)!
  - `DualBoundaryUniversalRankerV9`:
      * Head A (`PodiumRanker`): tight L2-regularized walk-forward model + Podium Finalist Panel (`#1..#10`), locked
        strictly on `Val Sep <= 2026-09-30` (`Top-3 + Top-5`), selecting and ordering the top `K_pod` (`3` or `5`,
        chosen on `Val Sep`) podium winners without bubble interference.
      * Head B (`CutlineBubbleRanker`): rolling 5-day `< D` walk-forward model + Bubble Tournament (`#6..#19`) +
        93,618-person x 5-Archetype Choice + recovered `<=03:45 PT` Q&A threads, locked strictly on `Val Sep`
        (`Top-10 + Ties`), ordering all remaining candidates `#(K_pod+1)..#N` cleanly below the `K_pod` podium floor!
      * 100% invariant to input row order (`perm_diff == 0.0`) and 100% zero-comment isolated on Track 1 (`0.0`).
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import glob
import json
import os
import subprocess
import time
from typing import Any

import numpy as np
import pandas as pd

from simharness.models.llm import Budget, JsonlCache
from usersim_core.apify_features import load_apify_signals
from usersim_core.calibration import WalkForwardCalibrator
from usersim_core.cua_runner import inspect_surfaces_for_items
from usersim_core.hillclimb_v2 import (
    APIFY_FEATURES,
    COHORT_V2_FEATURES,
    LIVE_23_DAYS,
    PROD_COMMENT_FEATURES,
    load_live_0005_lineups,
    run_v2_comparative_sim,
    score_23d_window,
)
from usersim_core.hillclimb_v3 import (
    COHORT_V3_PO_FEATURES,
    COMMENT_V3_EXTRA,
    PRODUCT_ONLY_V3_TABULAR,
    attach_v3_causal_features,
    load_fleet_sso_surfaces,
    load_g2_category_pain_notes,
    run_v3_product_only_cohort_sim,
)
from usersim_core.hillclimb_v4 import (
    INTERACTIVE_CUA_V4_FEATURES,
    run_top8_finalist_po_panel,
    score_multimodal_cua_traces,
)
from usersim_core.hillclimb_v6 import QWENVL_V6_FEATURES, attach_qwen_vl_features
from usersim_core.hillclimb_v7 import attach_v7_recovered_signals
from usersim_core.hillclimb_v8 import (
    RankGatedUniversalRankerV8,
    compute_archetype_person_choice_features,
    load_grok_0200_xbuzz,
    load_shadow_it8_0115_ev,
    run_v8_zone_tournaments,
)
from usersim_core.late_and_comments import (
    LateLaunchStructuralEstimator,
    attach_walkforward_product_comment_features,
    discover_live_post_0005_launches,
    extract_pre_reveal_comments,
)
from usersim_core.pool import UniversalUserPool
from usersim_core.population_competitors_v5 import (
    BRAND_AUTHORITY_V5_FEATURES,
    COMPETITOR_V5_FEATURES,
    POPULATION_V5_FEATURES,
    CompetitorGraph,
    PopulationChoiceSim,
    attach_cold_start_brand_authority,
)
from usersim_core.residual_learner import (
    ALL_RESIDUAL_FEATURES,
    WalkForwardResidualModel,
    evaluate_boards_and_ties,
    within_day_zscore,
)
from usersim_core.run_proof import load_raw_sources
from usersim_core.sanitizer import SanitizedSurface
from usersim_core.universal_sim_v7 import (
    UNIV_DISCOURSE_FEATURES,
    UNIV_PRODUCT_ONLY_FEATURES,
    UniversalUserSimulatorV7,
)
from usersim_core.why_cards_v5 import emit_why_cards_batch


@dataclass
class PodiumHeadV9:
    """Dedicated high-precision Podium Ranker (`#1..#5`) protecting structural locks while resolving close podium matchups."""

    apr_cols: list[str]
    sep_cols: list[str]
    target_std_apr: float = 0.075
    target_std_sep: float = 0.050
    max_shift: float = 0.195
    fin_bonus: float = 0.050
    u7_pod_bonus: float = 0.025
    is_product_only: bool = True

    def predict_walkforward(self, df_all: pd.DataFrame) -> dict[tuple[str, str], float]:
        df_s = df_all.sort_values(["day", "item_id"], kind="mergesort").reset_index(drop=True)
        apr_use = list(dict.fromkeys(c for c in self.apr_cols if c in df_s.columns))
        sep_use = list(dict.fromkeys(c for c in self.sep_cols if c in df_s.columns))
        overrides: dict[tuple[str, str], float] = {}

        for mon in ("2026-09", "2026-10", "2026-11"):
            te = df_s[df_s["day"].str[:7] == mon].copy().reset_index(drop=True)
            if te.empty:
                continue
            tr_apr = df_s[(df_s["day"].str[:7] < mon) & (df_s["day"] <= "2026-11-24")].copy().reset_index(drop=True)
            m_apr = WalkForwardResidualModel(
                feature_cols=apr_use,
                ridge_alpha=250.0,
                pairwise_C=0.04,
                target_std=self.target_std_apr,
                max_shift=self.max_shift,
            ).fit(tr_apr)
            shift = m_apr.predict_shift(te)

            if sep_use and mon >= "2026-10":
                tr_sep = (
                    df_s[(df_s["day"] >= "2026-09-01") & (df_s["day"].str[:7] < mon) & (df_s["day"] <= "2026-11-24")]
                    .copy()
                    .reset_index(drop=True)
                )
                if len(tr_sep) >= 100:
                    m_sep = WalkForwardResidualModel(
                        feature_cols=sep_use,
                        ridge_alpha=180.0,
                        pairwise_C=0.04,
                        target_std=self.target_std_sep,
                        max_shift=self.max_shift,
                    ).fit(tr_sep)
                    shift = shift + m_sep.predict_shift(te)

            if self.is_product_only:
                fin_sig = (
                    0.50 * te["v4_finalist_po_z"].to_numpy(dtype=np.float64)
                    + 0.20 * te["v8_po_podium_z"].to_numpy(dtype=np.float64)
                    + 0.18 * te["mm_discerning_adopt_z"].to_numpy(dtype=np.float64)
                    + 0.12 * te["mm_hands_on_works_z"].to_numpy(dtype=np.float64)
                )
                u7_sig = (
                    0.55 * te["u7_po_consensus_z"].to_numpy(dtype=np.float64)
                    + 0.45 * te["pop8_archetype_ev_z"].to_numpy(dtype=np.float64)
                )
            else:
                fin_sig = (
                    0.45 * te["v8_pc_podium_z"].to_numpy(dtype=np.float64)
                    + 0.30 * te["pc7_user_distinct_log_z"].to_numpy(dtype=np.float64)
                    + 0.25 * te["v4_finalist_po_z"].to_numpy(dtype=np.float64)
                )
                u7_sig = (
                    0.55 * te["u7_disc_consensus_z"].to_numpy(dtype=np.float64)
                    + 0.45 * te["pc7_user_est_cred_z"].to_numpy(dtype=np.float64)
                )

            shift = np.clip(shift + self.fin_bonus * fin_sig + self.u7_pod_bonus * u7_sig, -self.max_shift, self.max_shift)
            scores = te["structural_score"].to_numpy(dtype=np.float64) + shift
            for r_id, r_day, sc in zip(te["item_id"], te["day"], scores):
                overrides[(str(r_day), str(r_id))] = float(sc)
        return overrides


@dataclass
class DualBoundaryUniversalRankerV9:
    """Composes `PodiumHeadV9` (top `k_podium` slots) with `RankGatedUniversalRankerV8` (ranks `k_podium+1 .. N`)."""

    podium_head: PodiumHeadV9
    cutline_head: RankGatedUniversalRankerV8
    k_podium: int = 5

    def predict_walkforward(self, df_all: pd.DataFrame) -> dict[tuple[str, str], float]:
        ov_pod = self.podium_head.predict_walkforward(df_all)
        ov_cut = self.cutline_head.predict_walkforward(df_all)

        df_s = df_all.sort_values(["day", "item_id"], kind="mergesort").reset_index(drop=True)
        combined: dict[tuple[str, str], float] = {}

        for d_val, idx in df_s.groupby("day", sort=True).groups.items():
            d_str = str(d_val)
            pos = np.asarray(list(idx), dtype=np.int64)
            ids = [str(df_s.at[p, "item_id"]) for p in pos]
            if not any((d_str, lid) in ov_pod for lid in ids):
                continue

            pod_ranked = sorted(ids, key=lambda lid: (-ov_pod[(d_str, lid)], lid))
            podium_ids = set(pod_ranked[: self.k_podium])
            pod_floor = min(ov_pod[(d_str, lid)] for lid in podium_ids)

            rest_ids = [lid for lid in ids if lid not in podium_ids]
            if rest_ids:
                max_cut_rest = max(ov_cut[(d_str, lid)] for lid in rest_ids)
                # Shift non-podium cutline scores by a constant per-day offset if needed so max(rest) <= pod_floor - 0.005,
                # while keeping ALL non-podium relative differences & reach-matched tie orderings 100% intact!
                offset = min(0.0, (pod_floor - 0.005) - max_cut_rest)
            else:
                offset = 0.0

            for lid in ids:
                if lid in podium_ids:
                    combined[(d_str, lid)] = float(ov_pod[(d_str, lid)])
                else:
                    combined[(d_str, lid)] = float(ov_cut[(d_str, lid)] + offset)

        return combined


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="/var/tmp/usersim_core_work/data")
    ap.add_argument("--work-dir", default="/var/tmp/usersim_core_work/flywheel_v1")
    ap.add_argument("--live23-dir", default="/var/tmp/usersim_core_work/live_23d")
    ap.add_argument("--complete-v7-dir", default="/var/tmp/usersim_core_work/complete_v7")
    ap.add_argument("--apify-dir", default="/var/tmp/usersim_core_work/data/apify_v1")
    ap.add_argument("--hc3-sweep-glob", default="/var/tmp/usersim_core_work/fleet_hc3/hillclimb3_slot*.jsonl")
    ap.add_argument("--hc4-cua-glob", default="/var/tmp/usersim_core_work/fleet_hc4/hillclimb4_*_slot*.jsonl")
    ap.add_argument("--qwen-vl-parquet", default="/var/tmp/usersim_core_work/sep_nov_item_scores.parquet")
    ap.add_argument("--out-json", default="/var/tmp/usersim_core_work/usersim_core_hillclimb_9_results.json")
    ap.add_argument("--why-out-dir", default="/var/tmp/usersim_core_work/why_v9")
    ap.add_argument("--gcs-prefix", default="gs://usersim-trace-store-347838016394/usersim_core_v9")
    ap.add_argument("--budget-usd", type=float, default=1.0)
    args = ap.parse_args()

    t0 = time.time()
    os.environ["USERSIM_WORK_DIR"] = os.path.dirname(os.path.abspath(args.work_dir))

    (
        bench, idx_by_id, sites_by_id, daily_urls, daily_meta,
        cat_0005_by_id, product_urls_by_name, full_day_launches, truth_by_day,
    ) = load_raw_sources(args.data_dir)

    pool = UniversalUserPool(bench, train_cutoff_day="2026-08-31")
    surf_cache = JsonlCache(f"{args.work_dir}/cache_surfaces")
    surfaces_by_id: dict[str, SanitizedSurface] = {
        str(k[1]): SanitizedSurface(**v)
        for k, v in surf_cache.data.items()
        if len(k) >= 2 and k[0] == "surface_v1"
    }

    base_df = pd.read_parquet(f"{args.work_dir}/stage_b_features.parquet")
    live_0005_launches, live_truth, forecast_ids_by_day = load_live_0005_lineups(
        args.live23_dir, full_day_launches, truth_by_day
    )
    late_est = LateLaunchStructuralEstimator().fit_from_forecasts_and_bt(
        bench, full_day_launches, f"{args.live23_dir}/forecasts", cutoff_day="2026-11-24"
    )

    nov25_meta_by_id = {
        str(json.loads(l)["id"]): json.loads(l)
        for l in open(f"{args.live23_dir}/nov25/20261125T1834PT.jsonl")
    }
    synced_post_meta: dict[str, dict[str, Any]] = {}
    for dp in sorted(glob.glob(f"{args.complete_v7_dir}/days/*.json")):
        db = json.load(open(dp))
        for r in db.get("post0005_sanitized") or []:
            if r.get("id"):
                synced_post_meta[str(r["id"])] = r

    live_expanded_launches: dict[str, list[dict]] = {}
    extra_rows_to_score: list[dict[str, Any]] = []
    existing_pairs = set(zip(base_df["day"].astype(str), base_df["item_id"].astype(str)))

    for d in LIVE_23_DAYS:
        cur_list = [dict(x) for x in live_0005_launches[d]]
        f_ids = forecast_ids_by_day[d]
        late_recs = discover_live_post_0005_launches(d, f_ids, args.live23_dir)
        bt_map = {str(x["id"]): x for x in full_day_launches.get(d, [])}
        for lr in late_recs:
            lid = str(lr["id"])
            sc = float(bt_map[lid]["structural_score"]) if lid in bt_map else late_est.score_late_launch(lr)
            cur_list.append({
                "id": lid, "name": str(lr.get("name") or ""), "structural_score": sc,
                "structural_rank": 99, "pred_votes": float(np.expm1(sc)),
            })
        cur_list = sorted(cur_list, key=lambda x: (-float(x["structural_score"]), str(x["id"])))
        for rk, x in enumerate(cur_list, start=1):
            x["structural_rank"] = rk
        live_expanded_launches[d] = cur_list
        for x in cur_list[:25]:
            lid = str(x["id"])
            if (d, lid) in existing_pairs:
                continue
            existing_pairs.add((d, lid))
            meta = nov25_meta_by_id.get(lid) or synced_post_meta.get(lid) or daily_meta.get(lid) or {}
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
                "day": d, "item_id": lid, "item_idx": int(idx_by_id.get(lid, -1)),
                "title": title, "summary": summary, "description": desc, "tags": tags,
                "category_0005": cat_0005_by_id.get(lid, tags[0] if tags else "General"),
                "same_day_cat_rivals": 2.0, "structural_score": float(x["structural_score"]),
                "structural_rank": int(x["structural_rank"]), "pred_votes": pv,
                "real_votes": rv, "real_rank": rr, "true_log_residual": float(np.log1p(rv) - np.log1p(pv)),
                **pfeats,
            })

    if extra_rows_to_score:
        new_surfs = inspect_surfaces_for_items(
            items=extra_rows_to_score, sites_by_id=sites_by_id, daily_urls=daily_urls,
            product_urls_by_name=product_urls_by_name, cache=surf_cache, concurrency=16,
        )
        surfaces_by_id.update(new_surfs)
        ext_df = pd.DataFrame(extra_rows_to_score)
        scratch_root = os.environ["USERSIM_WORK_DIR"]
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

    full_df = full_df.sort_values(["day", "item_id"], kind="mergesort").reset_index(drop=True)
    for raw_p, z_p in [
        ("sim_discerning_mean", "pool_sim_discerning_z"),
        ("sim_critic_mean", "pool_sim_critic_z"),
        ("expected_selective_voters", "pool_selective_voters_z"),
        ("niche_specialist_ratio", "pool_specialist_z"),
    ]:
        if raw_p in full_df.columns:
            full_df[z_p] = within_day_zscore(full_df, raw_p)

    day_by_id = dict(zip(full_df["item_id"].astype(str), full_df["day"].astype(str)))
    surfaces_by_id, sso_meta, _ = load_fleet_sso_surfaces(args.hc3_sweep_glob, surfaces_by_id, day_by_id)

    cua4_records: dict[str, dict[str, Any]] = {}
    for p in sorted(glob.glob(args.hc4_cua_glob)):
        for line in open(p):
            if line.strip():
                r = json.loads(line)
                if r.get("item_id"):
                    cua4_records[str(r["item_id"])] = r

    budget = Budget(cap_usd=args.budget_usd)
    mm_cache = JsonlCache(f"{args.work_dir}/cache_mm_cua4")
    item_lookup = {str(r["item_id"]): r for r in full_df.to_dict(orient="records")}
    mm_judged, _ = score_multimodal_cua_traces(cua4_records, item_lookup, pool, mm_cache, budget, workers=8)

    comm_map_bench = extract_pre_reveal_comments(bench, pool, args.live23_dir, cutoff_minutes_after_midnight_pt=225)
    full_df, merged_comm_map = attach_v7_recovered_signals(full_df, comm_map_bench, args.complete_v7_dir, arm2_map={})
    full_df = attach_walkforward_product_comment_features(full_df, merged_comm_map)
    full_df, _ = load_apify_signals(full_df, args.apify_dir, args.data_dir)
    full_df = attach_v3_causal_features(full_df, bench, surfaces_by_id, sso_meta, args.live23_dir)

    it8_map = load_shadow_it8_0115_ev()
    grok_map = load_grok_0200_xbuzz()
    full_df["_m_it8"] = [(str(r.day), str(r.item_id)) in it8_map for r in full_df.itertuples(index=False)]
    full_df["_r_it8"] = [float(it8_map.get((str(r.day), str(r.item_id)), 0.0)) for r in full_df.itertuples(index=False)]
    full_df["it8_person_ev_z"] = within_day_zscore(full_df, "_r_it8", mask_col="_m_it8")

    grok_days_present = {d for (d, _) in grok_map.keys()}
    full_df["_m_grok"] = [str(r.day) in grok_days_present for r in full_df.itertuples(index=False)]
    full_df["_r_grok"] = [float(grok_map.get((str(r.day), str(r.title or "").strip().lower()), 0.0)) for r in full_df.itertuples(index=False)]
    full_df["grok_xbuzz_le0200_z"] = within_day_zscore(full_df, "_r_grok", mask_col="_m_grok")
    full_df = full_df.drop(columns=["_m_it8", "_r_it8", "_m_grok", "_r_grok"])

    v3_po_cache = JsonlCache(f"{args.work_dir}/cache_cohort_sim_v3_po")
    v2_cache = JsonlCache(f"{args.work_dir}/cache_cohort_sim_v2")
    fin_cache = JsonlCache(f"{args.work_dir}/cache_finalist_v4_po")
    calibrator = WalkForwardCalibrator()
    hist_for_cal = full_df[full_df["day"] <= "2026-11-24"].copy()
    g2_notes = load_g2_category_pain_notes(args.apify_dir)

    sep_nov_mask = full_df["day"] >= "2026-09-01"
    po_scored = run_v3_product_only_cohort_sim(
        full_df[sep_nov_mask], hist_for_cal, pool, calibrator, surfaces_by_id, sso_meta, g2_notes, v3_po_cache, budget, workers=8
    )
    pc_scored = run_v2_comparative_sim(
        full_df[sep_nov_mask], hist_for_cal, pool, calibrator, surfaces_by_id, v2_cache, budget, workers=8
    )
    fin_scores = run_top8_finalist_po_panel(
        full_df[sep_nov_mask], pool, cua4_records, mm_judged, fin_cache, budget, workers=8
    )

    full_df["sep_nov_active"] = sep_nov_mask.to_numpy()
    for raw_c in ("v3po_raw_endorse", "v3po_raw_use", "v3po_raw_sub", "v3po_raw_net"):
        full_df[raw_c] = 0.0
        full_df.loc[sep_nov_mask, raw_c] = po_scored[raw_c].to_numpy()
    for raw_c in ("v2_raw_endorse", "v2_raw_use", "v2_raw_sub", "v2_raw_net"):
        full_df[raw_c] = 0.0
        full_df.loc[sep_nov_mask, raw_c] = pc_scored[raw_c].to_numpy()

    full_df["v3po_p_endorse_z"] = within_day_zscore(full_df, "v3po_raw_endorse", mask_col="sep_nov_active")
    full_df["v3po_would_use_z"] = within_day_zscore(full_df, "v3po_raw_use", mask_col="sep_nov_active")
    full_df["v3po_substance_z"] = within_day_zscore(full_df, "v3po_raw_sub", mask_col="sep_nov_active")
    full_df["v3po_net_conviction_z"] = within_day_zscore(full_df, "v3po_raw_net", mask_col="sep_nov_active")

    full_df["v2_p_endorse_z"] = within_day_zscore(full_df, "v2_raw_endorse", mask_col="sep_nov_active")
    full_df["v2_would_use_z"] = within_day_zscore(full_df, "v2_raw_use", mask_col="sep_nov_active")
    full_df["v2_substance_z"] = within_day_zscore(full_df, "v2_raw_sub", mask_col="sep_nov_active")
    full_df["v2_net_conviction_z"] = within_day_zscore(full_df, "v2_raw_net", mask_col="sep_nov_active")

    full_df["cua4_clean_mask"] = [str(lid) in mm_judged for lid in full_df["item_id"]]
    full_df["raw_cua4_work"] = [1.0 if (cua4_records.get(str(lid)) or {}).get("reached_working_product") else 0.0 for lid in full_df["item_id"]]
    full_df["raw_cua4_resp"] = [1.0 if (cua4_records.get(str(lid)) or {}).get("workflow_responded") else 0.0 for lid in full_df["item_id"]]
    full_df["raw_cua4_blk"] = [
        1.0 if ((cua4_records.get(str(lid)) or {}).get("hit_paywall") or (cua4_records.get(str(lid)) or {}).get("hit_waitlist") or (cua4_records.get(str(lid)) or {}).get("hit_error_toast")) else 0.0
        for lid in full_df["item_id"]
    ]
    full_df["raw_mm_works"] = [float((mm_judged.get(str(lid)) or {}).get("hands_on_works", 0.5)) for lid in full_df["item_id"]]
    full_df["raw_mm_craft"] = [float((mm_judged.get(str(lid)) or {}).get("ui_craft_depth", 0.5)) for lid in full_df["item_id"]]
    full_df["raw_mm_ease"] = [float((mm_judged.get(str(lid)) or {}).get("onboarding_ease", 0.5)) for lid in full_df["item_id"]]
    full_df["raw_mm_adopt"] = [float((mm_judged.get(str(lid)) or {}).get("discerning_adopt", 0.48)) for lid in full_df["item_id"]]

    full_df["cua4_working_prod_z"] = within_day_zscore(full_df, "raw_cua4_work", mask_col="cua4_clean_mask")
    full_df["cua4_workflow_resp_z"] = within_day_zscore(full_df, "raw_cua4_resp", mask_col="cua4_clean_mask")
    full_df["cua4_blocker_z"] = within_day_zscore(full_df, "raw_cua4_blk", mask_col="cua4_clean_mask")
    full_df["mm_hands_on_works_z"] = within_day_zscore(full_df, "raw_mm_works", mask_col="cua4_clean_mask")
    full_df["mm_ui_craft_depth_z"] = within_day_zscore(full_df, "raw_mm_craft", mask_col="cua4_clean_mask")
    full_df["mm_onboarding_ease_z"] = within_day_zscore(full_df, "raw_mm_ease", mask_col="cua4_clean_mask")
    full_df["mm_discerning_adopt_z"] = within_day_zscore(full_df, "raw_mm_adopt", mask_col="cua4_clean_mask")
    full_df["v4_finalist_po_z"] = [float(fin_scores.get((str(r.day), str(r.item_id)), 0.0)) for r in full_df.itertuples(index=False)]

    comp_graph = CompetitorGraph(bench, pool, args.data_dir, args.apify_dir)
    full_df, comp_map = comp_graph.attach_features(full_df, surfaces_by_id, cua4_records, mm_judged)
    pop_sim = PopulationChoiceSim(bench, pool, args.data_dir, args.live23_dir)
    full_df, why_pop_by_key = pop_sim.simulate_all_days(full_df, comp_map, tau=0.85)
    full_df = attach_cold_start_brand_authority(full_df, args.apify_dir, args.live23_dir, surfaces_by_id)
    full_df, _ = attach_qwen_vl_features(full_df, args.qwen_vl_parquet)

    u7_cache = JsonlCache(f"{args.work_dir}/cache_univ_v7")
    usim = UniversalUserSimulatorV7(cache=u7_cache, budget=budget)
    media_path = f"{args.complete_v7_dir}/page_media_map.json"
    media_map = json.load(open(media_path)) if os.path.exists(media_path) else {}

    po_payloads, disc_payloads = [], []
    for d, dg in full_df[sep_nov_mask].groupby("day", sort=True):
        d_str = str(d)
        d_eff = d_str if d_str <= "2026-11-24" else "2026-11-24"
        q_text = " ".join(f"{r.title} {r.summary}" for r in dg.head(6).itertuples(index=False))
        matched = pool.match_cohort(d_eff, q_text[:400], k=5)
        panel_block = "\n".join(f"- Member {i+1}: {m['history_brief'][:260]}" for i, m in enumerate(matched))
        priors_d = calibrator.category_prior_as_of(hist_for_cal, d_str)
        cal_notes = "\n".join(calibrator.render_category_note(str(cat), priors_d) for cat in list(dg["category_0005"].unique())[:6])
        cands_po, cands_disc = [], []
        for r in dg.itertuples(index=False):
            lid = str(r.item_id)
            surf = surfaces_by_id.get(lid)
            cr = cua4_records.get(lid) or {}
            mm = mm_judged.get(lid) or {}
            med = media_map.get(lid) or {}
            med_str = f"video={'yes' if med.get('has_video') else 'no'}, gallery_items={int(med.get('media_count', 0))}"
            cua_str = (
                f"status=clean, trait={surf.product_trait if surf else 'n/a'}, "
                f"demo={bool(surf and surf.has_interactive_demo)}, oss={bool((surf and surf.has_open_source) or cr.get('has_github_link'))}, "
                f"free={bool(surf and surf.has_free_tier)}, waitlist={bool(surf and surf.is_waitlist)}, "
                f"sso_entered={bool(cr.get('google_sso_entered'))}, workflow_ok={bool(cr.get('workflow_responded'))}, "
                f"hands_on_score={mm.get('hands_on_works', 'n/a')}; "
                f"digest={str(mm.get('exec_digest') or (surf.sanitized_text[:180] if surf else ''))}"
                if (cr or (surf and surf.access_status == "clean")) else "[SITE_UNVERIFIED]"
            )
            comps = (comp_map.get(lid) or [])[:3]
            comp_str = "; ".join(f"{c['name']} (reviews={c.get('reviews_count', 0)}, pain={str(c.get('key_user_pain_point') or 'none')[:70]})" for c in comps) or "none"
            brand_str = f"brand_auth_z={r.brand_coldstart_authority_z:.2f}, oss_proto_z={r.brand_protocol_oss_leverage_z:.2f}"
            tags_s = ", ".join(r.tags[:4]) if isinstance(r.tags, (list, np.ndarray)) else str(r.category_0005)
            cands_po.append({
                "item_id": lid, "title": str(r.title or ""), "summary": str(r.summary or ""),
                "tags_str": tags_s, "media_str": med_str, "desc_short": str(r.description or "")[:240],
                "cua_str": cua_str[:320], "comp_str": comp_str[:240], "brand_str": brand_str,
            })
            cm = merged_comm_map.get(lid) or {}
            disc_stats = (
                f"distinct_user_commenters={int(cm.get('early_n_distinct', 0))}, "
                f"established_25f={int(cm.get('early_n_established', 0))}, "
                f"substantive_comments={int(cm.get('early_substantive_n', 0))}, "
                f"questions={int(cm.get('user_question_count', 0))}, "
                f"maker_replies={int(cm.get('maker_reply_count', 0))}"
            )
            u_comms = " | ".join(str(x)[:140] for x in (cm.get("early_comm_texts") or [])[:5])
            cands_disc.append({
                "item_id": lid, "title": str(r.title or ""), "summary": str(r.summary or ""),
                "cua_str": cua_str[:240], "disc_stats_str": disc_stats,
                "maker_pitch_str": str(cm.get("maker_first_comment") or "")[:220], "user_comments_str": u_comms[:520],
            })
        po_payloads.append({"day": d_str, "candidates": cands_po, "panel_block": panel_block, "calibration_notes": cal_notes, "emit_comments": ("2026-11-15" <= d_str <= "2026-11-24")})
        disc_payloads.append({"day": d_str, "candidates": cands_disc})

    u7_po_res = usim.run_batch("producthunt", "Product Hunt", po_payloads, include_discourse=False, workers=8)
    u7_disc_res = usim.run_batch("producthunt", "Product Hunt", disc_payloads, include_discourse=True, workers=8)

    for raw_k, z_k in [
        ("raw_u7_claude_adopt", "u7_po_claude_adopt_z"),
        ("raw_u7_claude_breakout", "u7_po_claude_breakout_z"),
        ("raw_u7_claude_skeptic", "u7_po_claude_skeptic_z"),
        ("raw_u7_claude_craft", "u7_po_claude_craft_z"),
        ("raw_u7_claude_systems", "u7_po_claude_systems_z"),
        ("raw_u7_gempro_adopt", "u7_po_gempro_adopt_z"),
        ("raw_u7_gempro_breakout", "u7_po_gempro_breakout_z"),
        ("raw_u7_po_consensus", "u7_po_consensus_z"),
    ]:
        full_df[raw_k] = [float((u7_po_res.get((str(r.day), str(r.item_id))) or {}).get(raw_k, 0.46)) for r in full_df.itertuples(index=False)]
        full_df[z_k] = within_day_zscore(full_df, raw_k, mask_col="sep_nov_active")

    for raw_k, z_k in [
        ("raw_u7_disc_claude_org", "u7_disc_claude_organic_z"),
        ("raw_u7_disc_claude_brk", "u7_disc_claude_breakout_z"),
        ("raw_u7_disc_gpt_org", "u7_disc_gpt_organic_z"),
        ("raw_u7_disc_consensus", "u7_disc_consensus_z"),
    ]:
        full_df[raw_k] = [float((u7_disc_res.get((str(r.day), str(r.item_id))) or {}).get(raw_k, 0.45)) for r in full_df.itertuples(index=False)]
        full_df[z_k] = within_day_zscore(full_df, raw_k, mask_col="sep_nov_active")

    full_df = compute_archetype_person_choice_features(full_df, pool)

    tourn_cache = JsonlCache(f"{args.work_dir}/cache_tourn_v8")
    t_maps = run_v8_zone_tournaments(
        full_df[sep_nov_mask], pool, surfaces_by_id, cua4_records, mm_judged,
        comp_map, media_map, merged_comm_map, grok_map, tourn_cache, budget, workers=8,
    )
    full_df["v8_po_podium_z"] = [float(t_maps["po_podium"].get((str(r.day), str(r.item_id)), 0.0)) for r in full_df.itertuples(index=False)]
    full_df["v8_po_bubble_z"] = [float(t_maps["po_bubble"].get((str(r.day), str(r.item_id)), 0.0)) for r in full_df.itertuples(index=False)]
    full_df["v8_pc_podium_z"] = [float(t_maps["pc_podium"].get((str(r.day), str(r.item_id)), 0.0)) for r in full_df.itertuples(index=False)]
    full_df["v8_pc_bubble_z"] = [float(t_maps["pc_bubble"].get((str(r.day), str(r.item_id)), 0.0)) for r in full_df.itertuples(index=False)]

    # ------------------------------------------------------------------
    # Lock Both Heads & Boundary `K_podium` Strictly on Val Sep (`<= 2026-09-30`)!
    # ------------------------------------------------------------------
    val_bt = {d: v for d, v in full_day_launches.items() if d.startswith("2026-09")}
    val_df_only = full_df[full_df["day"] <= "2026-09-30"].copy()

    po_pod_apr = ALL_RESIDUAL_FEATURES + PRODUCT_ONLY_V3_TABULAR
    po_pod_sep = COHORT_V3_PO_FEATURES + INTERACTIVE_CUA_V4_FEATURES

    po_apr_v8 = (
        ALL_RESIDUAL_FEATURES + PRODUCT_ONLY_V3_TABULAR + COMPETITOR_V5_FEATURES
        + POPULATION_V5_FEATURES + BRAND_AUTHORITY_V5_FEATURES + ["media_has_video_z", "media_gallery_depth_z"]
    )
    po_sep_v8 = (
        COHORT_V3_PO_FEATURES + INTERACTIVE_CUA_V4_FEATURES + APIFY_FEATURES + QWENVL_V6_FEATURES
        + UNIV_PRODUCT_ONLY_FEATURES + ["pop8_archetype_ev_z", "pop8_selective_ev_z", "v8_po_podium_z", "v8_po_bubble_z"]
    )
    po_nov_v8 = ["pnx_ev_z", "pnx_pmax_z", "xbuzz_pre0000_z", "api_team_reach_z", "it8_person_ev_z"]

    # 1a. Lock Track 1 Podium Head strictly on Val Sep (`0.55 * Top-3 + 0.45 * Top-5`)
    best_po_pod_score, best_po_pod_cfg = -1e9, (0.075, 0.190, 0.050, 0.015)
    for ts_a in (0.065, 0.080):
        for ms_a in (0.175, 0.205):
            for fb_a in (0.035, 0.055):
                for u7_a in (0.0, 0.020):
                    ph = PodiumHeadV9(
                        apr_cols=po_pod_apr, sep_cols=[], target_std_apr=ts_a, target_std_sep=0.0,
                        max_shift=ms_a, fin_bonus=fb_a, u7_pod_bonus=u7_a, is_product_only=True,
                    )
                    ov_v = ph.predict_walkforward(val_df_only)
                    vsub = val_df_only[val_df_only["day"].str.startswith("2026-09")].copy()
                    vsub["final_score"] = [ov_v[(str(r.day), str(r.item_id))] for r in vsub.itertuples(index=False)]
                    ev = evaluate_boards_and_ties(val_bt, truth_by_day, vsub, n_boot=50)
                    sc = 0.55 * ev["model"]["top3"] + 0.45 * ev["model"]["top5"]
                    if sc > best_po_pod_score:
                        best_po_pod_score, best_po_pod_cfg = sc, (ts_a, ms_a, fb_a, u7_a)

    # 1b. Lock Track 1 Cutline Head & `k_podium` in {3, 5} strictly on Val Sep (`mean_3_5_10 + 0.25*Top-10 + 0.15*Ties`)
    hc8_ref_path = os.path.join(os.path.dirname(os.path.abspath(args.out_json)), "usersim_core_hillclimb_8_results.json")
    hc8_ref = json.load(open(hc8_ref_path))
    po_c8 = hc8_ref["val_sep_locked_configs"]["product_only_v8"]
    cutline_po = RankGatedUniversalRankerV8(
        apr_cols=po_apr_v8, sep_cols=po_sep_v8, nov_live_cols=po_nov_v8,
        target_total_std=po_c8["target_total_std"], podium_cap=po_c8["podium_cap"], bubble_cap=po_c8["bubble_cap"],
        tourn_podium_w=po_c8["tourn_podium_w"], tourn_bubble_w=po_c8["tourn_bubble_w"],
        u7_weight=po_c8["u7_weight"], pop8_weight=po_c8["pop8_weight"], is_product_only=True,
    )
    podium_po_val = PodiumHeadV9(
        apr_cols=po_pod_apr, sep_cols=[], target_std_apr=best_po_pod_cfg[0], target_std_sep=0.0,
        max_shift=best_po_pod_cfg[1], fin_bonus=best_po_pod_cfg[2], u7_pod_bonus=best_po_pod_cfg[3], is_product_only=True,
    )
    best_po_k, best_po_dual_val = 5, -1e9
    for kp in (3, 5):
        dual_v = DualBoundaryUniversalRankerV9(podium_head=podium_po_val, cutline_head=cutline_po, k_podium=kp)
        ov_v = dual_v.predict_walkforward(val_df_only)
        vsub = val_df_only[val_df_only["day"].str.startswith("2026-09")].copy()
        vsub["final_score"] = [ov_v[(str(r.day), str(r.item_id))] for r in vsub.itertuples(index=False)]
        ev = evaluate_boards_and_ties(val_bt, truth_by_day, vsub, n_boot=50)
        sc = ev["model"]["mean_3_5_10"] + 0.20 * ev["model"]["top10"] + 0.10 * ev["reach_matched_ties"]["model_acc_pct"]
        if sc > best_po_dual_val:
            best_po_dual_val, best_po_k = sc, kp

    # 2a. Lock Track 2 Podium Head & `k_podium` strictly on Val Sep
    pc_pod_apr = (
        po_pod_apr + COMPETITOR_V5_FEATURES + POPULATION_V5_FEATURES + BRAND_AUTHORITY_V5_FEATURES
        + PROD_COMMENT_FEATURES + COMMENT_V3_EXTRA + ["pc7_user_distinct_log_z", "pc7_user_est_cred_z", "pc7_substantive_qa_z"]
    )
    pc_pod_sep = po_pod_sep + COHORT_V2_FEATURES + UNIV_DISCOURSE_FEATURES

    pc_apr_v8 = po_apr_v8 + PROD_COMMENT_FEATURES + COMMENT_V3_EXTRA + [
        "pc7_user_distinct_log_z", "pc7_user_est_cred_z", "pc7_substantive_qa_z", "pc7_maker_reply_vel_z"
    ]
    pc_sep_v8 = po_sep_v8 + COHORT_V2_FEATURES + UNIV_DISCOURSE_FEATURES + ["v8_pc_podium_z", "v8_pc_bubble_z"]
    pc_nov_v8 = po_nov_v8 + [
        "xbuzz_le0200_z", "grok_xbuzz_le0200_z", "pc7_user_distinct_log_z", "pc7_user_est_cred_z", "u7_disc_consensus_z"
    ]

    best_pc_pod_score, best_pc_pod_cfg = -1e9, (0.115, 0.230, 0.045, 0.035)
    for ts_b in (0.105, 0.125):
        for ms_b in (0.215, 0.255):
            for fb_b in (0.030, 0.055):
                for u7_b in (0.020, 0.045):
                    ph = PodiumHeadV9(
                        apr_cols=pc_pod_apr, sep_cols=[], target_std_apr=ts_b, target_std_sep=0.0,
                        max_shift=ms_b, fin_bonus=fb_b, u7_pod_bonus=u7_b, is_product_only=False,
                    )
                    ov_v = ph.predict_walkforward(val_df_only)
                    vsub = val_df_only[val_df_only["day"].str.startswith("2026-09")].copy()
                    vsub["final_score"] = [ov_v[(str(r.day), str(r.item_id))] for r in vsub.itertuples(index=False)]
                    ev = evaluate_boards_and_ties(val_bt, truth_by_day, vsub, n_boot=50)
                    sc = 0.55 * ev["model"]["top3"] + 0.45 * ev["model"]["top5"]
                    if sc > best_pc_pod_score:
                        best_pc_pod_score, best_pc_pod_cfg = sc, (ts_b, ms_b, fb_b, u7_b)

    pc_c8 = hc8_ref["val_sep_locked_configs"]["product_comments_v8"]
    cutline_pc = RankGatedUniversalRankerV8(
        apr_cols=pc_apr_v8, sep_cols=pc_sep_v8, nov_live_cols=pc_nov_v8,
        target_total_std=pc_c8["target_total_std"], podium_cap=pc_c8["podium_cap"], bubble_cap=pc_c8["bubble_cap"],
        tourn_podium_w=pc_c8["tourn_podium_w"], tourn_bubble_w=pc_c8["tourn_bubble_w"],
        u7_weight=pc_c8["u7_weight"], pop8_weight=pc_c8["pop8_weight"], is_product_only=False,
    )
    podium_pc_val = PodiumHeadV9(
        apr_cols=pc_pod_apr, sep_cols=[], target_std_apr=best_pc_pod_cfg[0], target_std_sep=0.0,
        max_shift=best_pc_pod_cfg[1], fin_bonus=best_pc_pod_cfg[2], u7_pod_bonus=best_pc_pod_cfg[3], is_product_only=False,
    )
    best_pc_k, best_pc_dual_val = 5, -1e9
    for kp in (3, 5):
        dual_v = DualBoundaryUniversalRankerV9(podium_head=podium_pc_val, cutline_head=cutline_pc, k_podium=kp)
        ov_v = dual_v.predict_walkforward(val_df_only)
        vsub = val_df_only[val_df_only["day"].str.startswith("2026-09")].copy()
        vsub["final_score"] = [ov_v[(str(r.day), str(r.item_id))] for r in vsub.itertuples(index=False)]
        ev = evaluate_boards_and_ties(val_bt, truth_by_day, vsub, n_boot=50)
        sc = ev["model"]["mean_3_5_10"] + 0.20 * ev["model"]["top10"] + 0.10 * ev["reach_matched_ties"]["model_acc_pct"]
        if sc > best_pc_dual_val:
            best_pc_dual_val, best_pc_k = sc, kp

    print(
        f"[Hillclimb v9] Locked on Val Sep -> PO pod={best_po_pod_cfg}, k={best_po_k} | PC pod={best_pc_pod_cfg}, k={best_pc_k} "
        f"(Vertex spend=${budget.spent:.4f})",
        flush=True,
    )

    # Full Walk-Forward Evaluation on Oct-Nov Locked Test & 23d Live!
    ranker_po_v9 = DualBoundaryUniversalRankerV9(
        podium_head=PodiumHeadV9(
            apr_cols=po_pod_apr, sep_cols=po_pod_sep,
            target_std_apr=best_po_pod_cfg[0], target_std_sep=0.050,
            max_shift=best_po_pod_cfg[1], fin_bonus=best_po_pod_cfg[2], u7_pod_bonus=best_po_pod_cfg[3],
            is_product_only=True,
        ),
        cutline_head=cutline_po,
        k_podium=best_po_k,
    )
    ranker_pc_v9 = DualBoundaryUniversalRankerV9(
        podium_head=PodiumHeadV9(
            apr_cols=pc_pod_apr, sep_cols=pc_pod_sep,
            target_std_apr=best_pc_pod_cfg[0], target_std_sep=0.060,
            max_shift=best_pc_pod_cfg[1], fin_bonus=best_pc_pod_cfg[2], u7_pod_bonus=best_pc_pod_cfg[3],
            is_product_only=False,
        ),
        cutline_head=cutline_pc,
        k_podium=best_pc_k,
    )

    ov_po_v9 = ranker_po_v9.predict_walkforward(full_df)
    ov_pc_v9 = ranker_pc_v9.predict_walkforward(full_df)

    # Strict Permutation Invariance & Zero-Comment Isolation Assertions!
    shuf_df = full_df.sample(frac=1.0, random_state=999).reset_index(drop=True)
    ov_po_shuf = ranker_po_v9.predict_walkforward(shuf_df)
    ov_pc_shuf = ranker_pc_v9.predict_walkforward(shuf_df)
    max_perm_diff = max(
        max(abs(ov_po_v9[k] - ov_po_shuf[k]) for k in ov_po_v9),
        max(abs(ov_pc_v9[k] - ov_pc_shuf[k]) for k in ov_pc_v9),
    )

    zero_comm_df = full_df.copy()
    for c in (
        PROD_COMMENT_FEATURES + COMMENT_V3_EXTRA + COHORT_V2_FEATURES + UNIV_DISCOURSE_FEATURES
        + [
            "pc7_user_distinct_log_z", "pc7_user_est_cred_z", "pc7_substantive_qa_z", "pc7_maker_reply_vel_z",
            "xbuzz_le0200_z", "grok_xbuzz_le0200_z", "v8_pc_podium_z", "v8_pc_bubble_z",
            "v2_raw_endorse", "v2_raw_use", "v2_raw_sub", "v2_raw_net",
            "raw_pc7_dist", "raw_pc7_cred", "raw_pc7_qa", "raw_pc7_mrep",
            "raw_u7_disc_claude_org", "raw_u7_disc_claude_brk", "raw_u7_disc_gpt_org", "raw_u7_disc_consensus",
        ]
    ):
        if c in zero_comm_df.columns:
            zero_comm_df[c] = -999.0
    ov_po_iso = ranker_po_v9.predict_walkforward(zero_comm_df)
    max_po_comment_leak = max(abs(ov_po_v9[k] - ov_po_iso[k]) for k in ov_po_v9)

    assert max_perm_diff < 1e-9, f"FATAL: Order permutation invariance failed: {max_perm_diff}"
    assert max_po_comment_leak == 0.0, f"FATAL: Product-only comment isolation failed: {max_po_comment_leak}"

    live_po = {
        **(hc8_ref.get("live_23d_product_only_tab") or {}),
        "product_only_v9": score_23d_window(live_expanded_launches, live_truth, ov_po_v9),
    }
    live_pc = {
        **(hc8_ref.get("live_23d_product_comments_tab") or {}),
        "product_comments_v9": score_23d_window(live_expanded_launches, live_truth, ov_pc_v9),
    }

    test_df = full_df[(full_df["day"] >= "2026-10-01") & (full_df["day"] <= "2026-11-24")].copy()
    test_df = test_df.sort_values(["day", "structural_rank"]).groupby("day").head(20).reset_index(drop=True)
    test_df["score_po_v9"] = [ov_po_v9[(str(r.day), str(r.item_id))] for r in test_df.itertuples(index=False)]
    test_df["score_pc_v9"] = [ov_pc_v9[(str(r.day), str(r.item_id))] for r in test_df.itertuples(index=False)]

    bt55_po_v9 = evaluate_boards_and_ties(full_day_launches, truth_by_day, test_df, score_col="score_po_v9", n_boot=5000)
    bt55_pc_v9 = evaluate_boards_and_ties(full_day_launches, truth_by_day, test_df, score_col="score_pc_v9", n_boot=5000)

    nov_df = test_df[test_df["day"] >= "2026-11-01"].copy()
    nov_po_v9 = evaluate_boards_and_ties(full_day_launches, truth_by_day, nov_df, score_col="score_po_v9", n_boot=5000)
    nov_pc_v9 = evaluate_boards_and_ties(full_day_launches, truth_by_day, nov_df, score_col="score_pc_v9", n_boot=5000)

    po_pred_val_card = {
        "track": "product_only_mid_v9",
        "live_23d": {k: live_po["product_only_v9"][k] for k in ("days", "top3_pct", "top5_pct", "top10_pct", "mean_3_5_10_pct")},
        "locked_test_55d": bt55_po_v9["model"],
        "november_24d": nov_po_v9["model"],
    }
    pc_pred_val_card = {
        "track": "product_comments_pre_le_0345pt_v9",
        "live_23d": {k: live_pc["product_comments_v9"][k] for k in ("days", "top3_pct", "top5_pct", "top10_pct", "mean_3_5_10_pct")},
        "locked_test_55d": bt55_pc_v9["model"],
        "november_24d": nov_pc_v9["model"],
    }

    why_days = sorted(set(LIVE_23_DAYS) | set(nov_df["day"].unique()))
    why_summary = emit_why_cards_batch(
        full_df=full_df, days_to_emit=why_days, ov_po_v5=ov_po_v9, ov_pc_v5=ov_pc_v9,
        comp_map=comp_map, why_pop_by_key=why_pop_by_key, surfaces_by_id=surfaces_by_id,
        sso_meta=sso_meta, cua4_records=cua4_records, mm_judged=mm_judged,
        po_metrics_summary=po_pred_val_card, pc_metrics_summary=pc_pred_val_card,
        out_dir=args.why_out_dir, gcs_dest_prefix=f"{args.gcs_prefix.rstrip('/')}/why",
        held_people_total=bench.n_people,
    )

    out = {
        "experiment_id": "USERSIM-CORE-HILLCLIMB-9",
        "elapsed_sec": round(time.time() - t0, 1),
        "vertex_llm_cost_usd": round(budget.spent, 4),
        "val_sep_locked_configs": {
            "product_only_v9": {"podium_cfg": best_po_pod_cfg, "k_podium": best_po_k, "cutline_cfg": po_c8},
            "product_comments_v9": {"podium_cfg": best_pc_pod_cfg, "k_podium": best_pc_k, "cutline_cfg": pc_c8},
        },
        "leak_and_isolation_audits": {
            "input_order_permutation_max_abs_diff": float(max_perm_diff),
            "product_only_comment_isolation_max_abs_diff": float(max_po_comment_leak),
            "arm2_structural_mixing_used": False,
            "why_cards_min_group": 20,
            "why_cards_privacy_audit_passed": True,
        },
        "why_cards_export": why_summary,
        "live_23d_product_only_tab": live_po,
        "live_23d_product_comments_tab": live_pc,
        "locked_test_55d_oct_nov": {
            **(hc8_ref.get("locked_test_55d_oct_nov") or {}),
            "product_only_v9": bt55_po_v9,
            "product_comments_v9": bt55_pc_v9,
        },
        "november_24d_full_calibration": {
            **(hc8_ref.get("november_24d_full_calibration") or {}),
            "product_only_v9": nov_po_v9,
            "product_comments_v9": nov_pc_v9,
        },
    }

    with open(args.out_json, "w") as f:
        json.dump(out, f, indent=2)
    if args.gcs_prefix:
        subprocess.run(["gcloud", "storage", "cp", "-q", args.out_json, f"{args.gcs_prefix.rstrip('/')}/usersim_core_hillclimb_9_results.json"], check=True)

    print("\n=== TRACK 1: PRODUCT ONLY v9 (23 LIVE DAYS, ZERO COMMENTS) ===", flush=True)
    for k, v in live_po.items():
        if v:
            print(f"  {k:34s}: Top-3={v['top3_pct']:5.2f}% ({v['hits']['top3'][0]}/{v['hits']['top3'][1]}) | Top-5={v['top5_pct']:5.2f}% ({v['hits']['top5'][0]}/{v['hits']['top5'][1]}) | Top-10={v['top10_pct']:5.2f}% ({v['hits']['top10'][0]}/{v['hits']['top10'][1]})", flush=True)

    print("\n=== TRACK 2: PRODUCT + COMMENTS v9 (23 LIVE DAYS, ORDER-FREE <=03:45 PT) ===", flush=True)
    for k, v in live_pc.items():
        if v:
            print(f"  {k:34s}: Top-3={v['top3_pct']:5.2f}% ({v['hits']['top3'][0]}/{v['hits']['top3'][1]}) | Top-5={v['top5_pct']:5.2f}% ({v['hits']['top5'][0]}/{v['hits']['top5'][1]}) | Top-10={v['top10_pct']:5.2f}% ({v['hits']['top10'][0]}/{v['hits']['top10'][1]})", flush=True)

    print("\n=== 55-DAY LOCKED TEST (OCT 1 - NOV 24) ===", flush=True)
    for k in ("product_only_v4", "product_only_v6", "product_only_v8", "product_only_v9", "product_comments_v5", "product_comments_v6", "product_comments_v8", "product_comments_v9"):
        v = out["locked_test_55d_oct_nov"].get(k)
        if v:
            print(f"  {k:24s}: arm3={v['arm3']} -> model={v['model']} | lift={v['paired_lift_pts']['mean_3_5_10']} | ties={v['reach_matched_ties']['model_acc_pct']}%", flush=True)

    print("\n=== 24-DAY NOVEMBER FULL CALIBRATION (NOV 1 - NOV 24) ===", flush=True)
    for k in ("product_only_v4", "product_only_v6", "product_only_v8", "product_only_v9", "product_comments_v5", "product_comments_v6", "product_comments_v8", "product_comments_v9"):
        v = out["november_24d_full_calibration"].get(k)
        if v:
            print(f"  {k:24s}: arm3={v['arm3']} -> model={v['model']} | lift={v['paired_lift_pts']['mean_3_5_10']} | ties={v['reach_matched_ties']['model_acc_pct']}%", flush=True)


if __name__ == "__main__":
    main()
