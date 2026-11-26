"""End-to-end staged proof runner for `USERSIM-CORE-PROOF-1`.

Stages:
  1. `stage_a`        ($0.00): Build leak-free 207-day dataset (Apr 1 - Nov 24, 2026), UniversalUserPool
                               features, pre-April 00:05 categories, walk-forward < D category priors,
                               and sanitized HTTP/cached product surfaces. Validate tabular lift on Val (Sep).
  2. `stage_b_cua`    (~$2.00): Run real multi-step Camoufox MCP browser sessions (`gemini-2.5-pro`) on
                               JS-only / close structural-tie shortlist launches, recording `CUA_TRACES`.
  3. `stage_b_cohort` (~$8.50): Run `ComparativeCohortSimulator` (`gpt-oss-120b` x2 + `gemini-2.5-pro`)
                               across all 207 days (4,140 launches), writing `SIM_FEEDBACK_RESIDUALS`.
  4. `stage_c_person` (~$3.00): Objective Task C real-comment person-specificity (`own_vs_other`, `match`,
                               paired vs item-only & Flash) + cross-domain Hacker News `wb15` transfer.
  5. `stage_lock`     ($0.00): Lock hyperparameters on Val (Sep), run walk-forward evaluation ONCE on
                               Locked Test (Oct 1 - Nov 24, n=55 days), run leak audits, and materialize
                               all 4 `FlywheelStore` Parquet tables.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import time
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from simharness.bench import Benchmark
from simharness.models.llm import Budget, JsonlCache
from usersim_core.calibration import WalkForwardCalibrator
from usersim_core.cohort_sim import ComparativeCohortSimulator
from usersim_core.cua_runner import CamoufoxCUARunner, inspect_surfaces_for_items, surfaces_to_cua_traces_df
from usersim_core.pool import UniversalUserPool
from usersim_core.residual_learner import (
    ALL_RESIDUAL_FEATURES,
    COHORT_LLM_FEATURES,
    POOL_FEATURES,
    SURFACE_CUA_FEATURES,
    WalkForwardResidualModel,
    evaluate_boards_and_ties,
    within_day_zscore,
)
from usersim_core.sanitizer import SanitizedSurface
from usersim_core.schema import FlywheelStore

TOPN = 20


def load_raw_sources(data_dir: str):
    bench = Benchmark(f"{data_dir}/bench")
    idx_by_id = dict(zip(bench.items["item_id"].astype(str), bench.items["item_idx"].astype(int)))

    sites_by_id: dict[str, dict] = {}
    with open(f"{data_dir}/sites/sites_ph.jsonl") as f:
        for line in f:
            r = json.loads(line)
            lid = str(r.get("item_id") or r.get("id") or "")
            if lid:
                sites_by_id[lid] = r

    daily_urls: dict[str, str] = {}
    daily_meta: dict[str, dict] = {}
    for p in sorted(glob.glob(f"{data_dir}/daily_0005/*/sites_0005.json")):
        j = json.load(open(p))
        for lid, rec in (j.get("launches") or {}).items():
            if rec.get("final_url"):
                daily_urls[str(lid)] = str(rec["final_url"])
    for p in sorted(glob.glob(f"{data_dir}/daily_0005/*/today_0005.json")):
        j = json.load(open(p))
        rows = j.get("launches") if isinstance(j, dict) else j
        if isinstance(rows, list):
            for rec in rows:
                lid = str(rec.get("id") or rec.get("item_id") or "")
                if lid:
                    daily_meta[lid] = rec

    cat_df = pd.read_parquet(f"{data_dir}/taxonomy/launch_categories.parquet")
    cat_0005_by_id = dict(
        zip(
            cat_df["item_id"].astype(str),
            cat_df["embedding_0005_pre_april"].fillna(cat_df["embedding_zero_shot"]).fillna("General").astype(str),
        )
    )

    prod_df = pd.read_parquet(f"{data_dir}/taxonomy/products.parquet")
    # Only unambiguous single-product name -> online URL mappings
    online = prod_df[(~prod_df["no_longer_online"].fillna(False)) & prod_df["url"].notna()].copy()
    online["name_low"] = online["name"].astype(str).str.strip().str.lower()
    counts = online["name_low"].value_counts()
    uniq_names = set(counts[counts == 1].index)
    uniq_sub = online[online["name_low"].isin(uniq_names)]
    product_urls_by_name = dict(zip(uniq_sub["name_low"], uniq_sub["url"].astype(str)))

    full_day_launches: dict[str, list[dict]] = {}
    truth_by_day: dict[str, dict[str, dict]] = {}
    for fp in sorted(glob.glob(f"{data_dir}/struct_bt/*.json")):
        j = json.load(open(fp))
        d = str(j["day"])
        if d < "2026-04-01" or d > "2026-11-24":
            continue
        truth = j.get("truth", {}).get("by_id", {})
        ranked = {str(k): v for k, v in truth.items() if v.get("final_rank") is not None}
        if len(ranked) < 10 or len(j.get("launches", [])) < 10:
            continue
        full_day_launches[d] = j["launches"]
        truth_by_day[d] = truth

    return (
        bench,
        idx_by_id,
        sites_by_id,
        daily_urls,
        daily_meta,
        cat_0005_by_id,
        product_urls_by_name,
        full_day_launches,
        truth_by_day,
    )


def run_stage_a(data_dir: str, work_dir: str) -> pd.DataFrame:
    os.makedirs(work_dir, exist_ok=True)
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
    ) = load_raw_sources(data_dir)

    print(f"[Stage A] Loaded {len(full_day_launches)} scored days (Apr 1 - Nov 24, 2026). Initializing UniversalUserPool...")
    pool = UniversalUserPool(bench, train_cutoff_day="2026-08-31")

    # Gather all Top-20 shortlist items across all 207 days
    shortlist_items: list[dict[str, Any]] = []
    for d in sorted(full_day_launches):
        l_sorted = sorted(full_day_launches[d], key=lambda x: int(x["structural_rank"]))[:TOPN]
        truth = truth_by_day[d]
        # Count 00:05-knowable category rivals across full day lineup
        day_cats = [cat_0005_by_id.get(str(x["id"]), "General") for x in full_day_launches[d]]
        cat_counts: dict[str, int] = {}
        for c in day_cats:
            cat_counts[c] = cat_counts.get(c, 0) + 1

        for x in l_sorted:
            lid = str(x["id"])
            title = str(x.get("name") or "")
            summary, desc, tags = "", "", []
            iidx = idx_by_id.get(lid)
            if iidx is not None:
                it_obj = bench.item(iidx)
                title = it_obj.title or title
                summary = it_obj.summary or ""
                desc = it_obj.description or ""
                tags = list(it_obj.tags or [])
            if lid in daily_meta:
                dm = daily_meta[lid]
                summary = summary or str(dm.get("tagline") or dm.get("summary") or "")
                desc = desc or str(dm.get("description") or "")
                if not tags and isinstance(dm.get("topics"), list):
                    tags = [str(t) for t in dm["topics"]]

            cat0 = cat_0005_by_id.get(lid)
            if not cat0:
                cat0 = tags[0] if tags else "General"

            t_rec = truth.get(lid, {})
            real_votes = float(t_rec.get("votes") or 0.0)
            real_rank = float(t_rec["final_rank"]) if t_rec.get("final_rank") is not None else 35.0
            pred_votes = max(1.0, float(x.get("pred_votes") or np.expm1(float(x["structural_score"]))))
            true_log_res = float(np.log1p(real_votes) - np.log1p(pred_votes))

            # Pool features (causal < D)
            if iidx is not None:
                pfeats = pool.item_pool_features(d, iidx)
            else:
                ivec = pool.embed_text(f"{title} {summary} {' '.join(tags)} {desc[:240]}")
                pfeats = pool.item_pool_features(d, ivec)

            shortlist_items.append({
                "day": d,
                "item_id": lid,
                "item_idx": int(iidx) if iidx is not None else -1,
                "title": title,
                "summary": summary,
                "description": desc,
                "tags": tags,
                "category_0005": cat0,
                "same_day_cat_rivals": float(max(0, cat_counts.get(cat0, 1) - 1)),
                "structural_score": float(x["structural_score"]),
                "structural_rank": int(x["structural_rank"]),
                "pred_votes": pred_votes,
                "real_votes": real_votes,
                "real_rank": real_rank,
                "true_log_residual": true_log_res,
                **pfeats,
            })

    print(f"[Stage A] Built {len(shortlist_items)} shortlist rows. Running leak-sanitized HTTP + cached surface inspection...")
    surf_cache = JsonlCache(f"{work_dir}/cache_surfaces")
    surfaces = inspect_surfaces_for_items(
        items=shortlist_items,
        sites_by_id=sites_by_id,
        daily_urls=daily_urls,
        product_urls_by_name=product_urls_by_name,
        cache=surf_cache,
        concurrency=28,
    )

    df = pd.DataFrame(shortlist_items)
    # Attach surface columns (0-centered when access_status != 'clean')
    acc_status = [surfaces[str(lid)].access_status for lid in df["item_id"]]
    df["access_status"] = acc_status
    df["access_clean"] = [s == "clean" for s in acc_status]
    df["url"] = [surfaces[str(lid)].url for lid in df["item_id"]]
    df["product_trait"] = [surfaces[str(lid)].product_trait for lid in df["item_id"]]
    df["badges_stripped_n"] = [int(surfaces[str(lid)].badges_stripped_n) for lid in df["item_id"]]

    for attr, col in [
        ("has_interactive_demo", "raw_demo"),
        ("has_open_source", "raw_oss"),
        ("has_free_tier", "raw_free"),
        ("has_visible_pricing", "raw_price"),
        ("has_docs", "raw_docs"),
        ("is_waitlist", "raw_waitlist"),
        ("is_enterprise_gated", "raw_ent"),
        ("is_platform_only", "raw_plat"),
    ]:
        df[col] = [float(getattr(surfaces[str(lid)], attr)) for lid in df["item_id"]]

    # Within-day z-scoring of clean surface indicators (unverified sites get exact 0.0!)
    for raw_c, out_c in [
        ("raw_demo", "surf_instant_demo_clean"),
        ("raw_oss", "surf_open_source_clean"),
        ("raw_free", "surf_free_tier_clean"),
        ("raw_price", "surf_visible_pricing_clean"),
        ("raw_docs", "surf_docs_clean"),
        ("raw_waitlist", "surf_waitlist_clean"),
        ("raw_ent", "surf_enterprise_gated_clean"),
        ("raw_plat", "surf_platform_only_clean"),
    ]:
        df[out_c] = within_day_zscore(df, raw_c, mask_col="access_clean")

    # Placeholder CUA features until stage_b_cua populates multi-step Camoufox traces
    df["cua_reached_value_clean"] = 0.0
    df["cua_friction_clean"] = 0.0

    # Pool within-day z-scores
    df["pool_sim_discerning_z"] = within_day_zscore(df, "sim_discerning_mean")
    df["pool_sim_critic_z"] = within_day_zscore(df, "sim_critic_mean")
    df["pool_selective_voters_z"] = within_day_zscore(df, "expected_selective_voters")
    df["pool_specialist_z"] = -within_day_zscore(df, "niche_specialist_ratio")  # lower entropy = sharper niche fit

    # Strictly causal (< D) walk-forward category residual prior
    cal = WalkForwardCalibrator(prior_strength=18.0)
    cat_priors_col = np.zeros(len(df), dtype=np.float64)
    for d in sorted(df["day"].unique()):
        priors = cal.category_prior_as_of(df, d)
        mask = df["day"] == d
        cat_priors_col[mask.to_numpy()] = [
            priors.get(str(c), {}).get("shrunk_log_resid", 0.0) for c in df.loc[mask, "category_0005"]
        ]
    df["cat_prior_shrunk_resid"] = cat_priors_col

    out_p = f"{work_dir}/stage_a_features.parquet"
    df.to_parquet(out_p, index=False)
    clean_pct = 100.0 * df["access_clean"].mean()
    clean_test_pct = 100.0 * df[df["day"] >= "2026-10-01"]["access_clean"].mean()
    print(f"[Stage A] Saved {out_p} in {time.time()-t0:.1f}s | Clean surfaces overall={clean_pct:.1f}%, Oct-Nov={clean_test_pct:.1f}%")

    # Validate Stage A (Pool + Surface only, $0 LLM cost) strictly on Val Sep (trained on Apr-Aug)
    tr = df[(df["day"] >= "2026-04-01") & (df["day"] <= "2026-08-31")].copy()
    va = df[(df["day"] >= "2026-09-01") & (df["day"] <= "2026-09-30")].copy()
    mod_a = WalkForwardResidualModel(POOL_FEATURES + SURFACE_CUA_FEATURES, ridge_alpha=150.0, scale_eta=0.30, max_shift=0.35).fit(tr)
    va["final_score"] = mod_a.score_df(va)
    val_res = evaluate_boards_and_ties(full_day_launches, truth_by_day, va, score_col="final_score", n_boot=2000)
    print("[Stage A Val Sep (n=28) Pool+Surface Only ($0)]:", json.dumps(val_res, indent=2))
    return df


def run_stage_b(data_dir: str, work_dir: str, budget_cap: float = 35.0, max_cua_sessions: int = 45) -> pd.DataFrame:
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
    ) = load_raw_sources(data_dir)
    pool = UniversalUserPool(bench, train_cutoff_day="2026-08-31")
    cal = WalkForwardCalibrator(prior_strength=18.0)

    df = pd.read_parquet(f"{work_dir}/stage_a_features.parquet")
    surf_cache = JsonlCache(f"{work_dir}/cache_surfaces")
    surfaces: dict[str, SanitizedSurface] = {}
    for r in df[["item_id", "day"]].itertuples(index=False):
        ckey = ("surface_v1", str(r[0]), str(r[1]))
        if ckey in surf_cache:
            surfaces[str(r[0])] = SanitizedSurface(**surf_cache[ckey])

    budget = Budget(cap_usd=budget_cap)
    cua_cache = JsonlCache(f"{work_dir}/cache_camoufox_cua")
    cua_runner = CamoufoxCUARunner(budget=budget, cache=cua_cache)

    # 1. Select high-leverage structural-tie / JS-only shortlist candidates for real Camoufox MCP browser sessions
    # Focus on Val (Sep) + Locked Test (Oct-Nov) rank #1..#12 contenders with URLs where JS rendering or live CUA adds signal
    cand_rows = df[
        (df["day"] >= "2026-09-01")
        & (df["structural_rank"] <= 12)
        & (df["url"].astype(str).str.len() > 8)
        & (df["access_status"].isin(["js_only", "clean"]))
    ].copy()
    # Prioritize js_only (SPA apps invisible to static HTTP!) first, then tightest structural score gaps
    cand_rows["is_js"] = (cand_rows["access_status"] == "js_only").astype(int)
    cand_rows = cand_rows.sort_values(["is_js", "structural_rank"], ascending=[False, True]).head(max_cua_sessions)

    print(f"[Stage B.1] Running {len(cand_rows)} real Camoufox MCP browser CUA sessions (`gemini-2.5-pro`)...")
    cua_by_id: dict[str, dict] = {}
    camoufox_rows: list[dict] = []
    for idx_c, row in enumerate(cand_rows.to_dict("records"), start=1):
        d = str(row["day"])
        lid = str(row["item_id"])
        iidx = int(row["item_idx"])
        cohort = pool.match_cohort(d, iidx if iidx >= 0 else f"{row['title']} {row['summary']}", k=1)
        user0 = cohort[0]
        trace_row = cua_runner.run_session(row, str(row["url"]), user0, max_steps=3)
        camoufox_rows.append(trace_row)
        if trace_row["access_status"] == "clean":
            cua_by_id[lid] = trace_row
        if idx_c % 10 == 0 or idx_c == len(cand_rows):
            print(
                f"  [Camoufox CUA] {idx_c}/{len(cand_rows)} sessions | clean={len(cua_by_id)} | cua_cost=${cua_runner.cost_usd:.2f}",
                flush=True,
            )

    # Save CUA_TRACES table via FlywheelStore
    store = FlywheelStore(f"{work_dir}/flywheel")
    cua_df = surfaces_to_cua_traces_df(df.to_dict("records"), surfaces, camoufox_rows=camoufox_rows)
    store.write("cua_traces", cua_df)
    print(f"[Stage B.1] Wrote {len(cua_df)} rows to FlywheelStore `cua_traces.parquet` ({len(camoufox_rows)} multi-step Camoufox sessions).")

    # Update df CUA columns where Camoufox recovered a clean interactive trace
    cua_val = np.zeros(len(df), dtype=np.float64)
    cua_fric = np.zeros(len(df), dtype=np.float64)
    has_cua_clean = np.zeros(len(df), dtype=bool)
    for i, lid in enumerate(df["item_id"].astype(str)):
        if lid in cua_by_id:
            cr = cua_by_id[lid]
            has_cua_clean[i] = True
            cua_val[i] = 1.0 if (cr.get("reached_value_moment") or cr.get("has_interactive_demo")) else 0.0
            cua_fric[i] = 1.0 if cr.get("product_trait") in ("waitlist_only", "card_required", "onboarding_broken") else 0.0
            if not df.loc[i, "access_clean"]:
                df.loc[i, "access_clean"] = True
                df.loc[i, "access_status"] = "clean"
    df["raw_cua_val"] = cua_val
    df["raw_cua_fric"] = cua_fric
    df["has_cua_clean"] = has_cua_clean
    df["cua_reached_value_clean"] = within_day_zscore(df, "raw_cua_val", mask_col="access_clean")
    df["cua_friction_clean"] = within_day_zscore(df, "raw_cua_fric", mask_col="access_clean")

    # 2. Build day payloads for ComparativeCohortSimulator (`gpt-oss-120b` x2 + `gemini-2.5-pro`) across ALL 207 days
    print(f"[Stage B.2] Preparing comparative cohort payloads for {df['day'].nunique()} days...")
    day_payloads: list[dict[str, Any]] = []
    for d, dg in df.groupby("day", sort=True):
        sl = dg.to_dict("records")
        # Match 5 discerning users to the day's representative topic centroid
        combined_text = " ".join(f"{r['title']} {r['summary']}" for r in sl[:10])
        panel = pool.match_cohort(str(d), combined_text, k=5)
        priors = cal.category_prior_as_of(df, str(d))
        uniq_cats = list(dict.fromkeys(str(r["category_0005"]) for r in sl))
        cat_notes = [cal.render_category_note(c, priors) for c in uniq_cats[:10]]
        day_surfs = {str(r["item_id"]): surfaces[str(r["item_id"])] for r in sl if str(r["item_id"]) in surfaces}
        day_cua = {str(r["item_id"]): cua_by_id[str(r["item_id"])] for r in sl if str(r["item_id"]) in cua_by_id}
        day_payloads.append({
            "day": str(d),
            "shortlist": sl,
            "cohort_panel": panel,
            "category_notes": cat_notes,
            "surfaces": day_surfs,
            "cua_by_id": day_cua,
        })

    cohort_cache = JsonlCache(f"{work_dir}/cache_cohort_sim")
    sim = ComparativeCohortSimulator(budget=budget, cache=cohort_cache, workers=4)
    merged_evals = sim.evaluate_days(day_payloads, use_pro=True, domain_label="Product Hunt")

    # Attach raw & within-day z-scored LLM cohort columns
    for key_src, col_raw in [
        ("p_endorse", "llm_p_endorse"),
        ("would_use", "llm_would_use"),
        ("instant_clarity", "llm_clarity"),
        ("differentiation", "llm_differentiation"),
        ("technical_substance", "llm_substance"),
        ("friction_severity", "llm_friction"),
        ("pro_120b_min", "llm_pro_120b_agree"),
    ]:
        df[col_raw] = [float(merged_evals[(str(d), str(lid))][key_src]) for d, lid in zip(df["day"], df["item_id"])]

    df["llm_net_conviction"] = (
        0.35 * df["llm_p_endorse"]
        + 0.30 * df["llm_would_use"]
        + 0.20 * df["llm_differentiation"]
        + 0.15 * df["llm_substance"]
        - 0.25 * df["llm_friction"]
    )
    df["predicted_critique"] = [str(merged_evals[(str(d), str(lid))]["critique"]) for d, lid in zip(df["day"], df["item_id"])]
    df["predicted_comment"] = [str(merged_evals[(str(d), str(lid))]["comment"]) for d, lid in zip(df["day"], df["item_id"])]

    for col_raw, col_z in [
        ("llm_p_endorse", "llm_p_endorse_z"),
        ("llm_would_use", "llm_would_use_z"),
        ("llm_clarity", "llm_clarity_z"),
        ("llm_differentiation", "llm_differentiation_z"),
        ("llm_substance", "llm_substance_z"),
        ("llm_friction", "llm_friction_z"),
        ("llm_net_conviction", "llm_net_conviction_z"),
        ("llm_pro_120b_agree", "llm_pro_120b_agree_z"),
    ]:
        df[col_z] = within_day_zscore(df, col_raw)

    out_b = f"{work_dir}/stage_b_features.parquet"
    df.to_parquet(out_b, index=False)

    # Materialize SIM_FEEDBACK_RESIDUALS & UNIVERSAL_USERS in FlywheelStore
    sim_rows = pd.DataFrame({
        "eval_id": [f"ph:{d}:{lid}:ens" for d, lid in zip(df["day"], df["item_id"])],
        "domain": "producthunt",
        "item_id": df["item_id"].astype(str),
        "day": df["day"].astype(str),
        "global_user_id": "cohort:top5_discerning_archetypes",
        "pool_similarity": df["sim_discerning_mean"].astype(np.float64),
        "evaluator_model": "ensemble:gpt-oss-120b+gemini-2.5-pro",
        "trace_id": [f"cua_{lid}" if lid in cua_by_id else f"surf_{lid}_{d}" for d, lid in zip(df["day"], df["item_id"])],
        "p_endorse": df["llm_p_endorse"].astype(np.float64),
        "would_use": df["llm_would_use"].astype(np.float64),
        "instant_clarity": df["llm_clarity"].astype(np.float64),
        "differentiation": df["llm_differentiation"].astype(np.float64),
        "technical_substance": df["llm_substance"].astype(np.float64),
        "friction_severity": df["llm_friction"].astype(np.float64),
        "predicted_comment": df["predicted_comment"].astype(str),
        "predicted_critique": df["predicted_critique"].astype(str),
        "structural_score": df["structural_score"].astype(np.float64),
        "structural_rank": df["structural_rank"].astype(np.float64),
        "real_score": df["real_votes"].astype(np.float64),
        "real_rank": df["real_rank"].astype(np.float64),
        "true_log_residual": df["true_log_residual"].astype(np.float64),
    })
    store.write("sim_feedback_residuals", sim_rows)
    u_df = pool.export_universal_users("2026-11-24", max_users=25000)
    store.write("universal_users", u_df)

    cost_summary = {
        "cua_gemini_pro_usd": round(cua_runner.cost_usd, 4),
        "cohort_gpt_120b_usd": round(sim.gpt120b.cost_usd, 4),
        "cohort_gemini_pro_usd": round(sim.pro.cost_usd, 4),
        "total_spent_usd": round(budget.spent, 4),
        "gpt_120b_stats": sim.gpt120b.stats(),
        "gemini_pro_stats": sim.pro.stats(),
    }
    with open(f"{work_dir}/stage_b_cost.json", "w") as f:
        json.dump(cost_summary, f, indent=2)
    print("[Stage B Complete] Cost summary:", json.dumps(cost_summary, indent=2))
    return df


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["a", "b"], required=True)
    ap.add_argument("--data", default="/Users/shreyaspatel/.gemini/antigravity/brain/9180c5fc-4f89-4408-aad0-3184e5de8475/scratch/data")
    ap.add_argument("--work", default="/Users/shreyaspatel/.gemini/antigravity/brain/9180c5fc-4f89-4408-aad0-3184e5de8475/scratch/flywheel_v1")
    ap.add_argument("--budget", type=float, default=35.0)
    ap.add_argument("--cua-sessions", type=int, default=45)
    args = ap.parse_args()

    if args.stage == "a":
        run_stage_a(args.data, args.work)
    elif args.stage == "b":
        run_stage_b(args.data, args.work, budget_cap=args.budget, max_cua_sessions=args.cua_sessions)
