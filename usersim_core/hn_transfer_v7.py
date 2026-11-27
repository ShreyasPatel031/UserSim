"""Cross-Domain Generalizability Test 1: Hacker News (`usersim_core/hn_transfer_v7.py`).

Plugs the exact same domain-agnostic `UniversalUserSimulatorV7` (`claude-sonnet-4-6` + `gemini-2.5-pro` +
`gpt-oss-120b`) into Hacker News (`tables/hn_posts`, `tables/hn_early_points`) with ZERO PH-specific code:
  - Train / Structural Baseline Fit: strictly `<= 2026-09-30` (`author <D prior`, `domain <D prior`,
    `link_kind`, `hour_utc`, and `title + URL domain` TF-IDF Ridge -> LightGBM structural score `S_hn(x)`).
  - Held-Out Test: `2026-10-01 .. 2026-10-25` days in `tables/hn_posts` & `tables/hn_early_points`.
  - Evaluates TWO strictly separated tracks on each day's Top-30 structural candidates:
      1. Track 1 (`Story Only, t=0`): ZERO comments, ZERO points — pure submission title/text + live URL
         surface inspection (`SanitizedSurface`) + `< D` author/domain priors + `UniversalUserSimulatorV7`.
      2. Track 2 (`Story + Early Discourse, t=30m`): adds strictly `age_min <= 30` early comment velocity
         (with points stripped so we test pure early community discussion + simulator!).
  - Reports paired Top-5 / Top-10 / Top-15 daily breakout capture & within-day Spearman correlation with
    `log1p(final_points)`, plus 5,000-draw day-clustered bootstrap 95% CIs!
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import time
from urllib.parse import urlparse

import gcsfs
import lightgbm as lgb
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scipy.stats import spearmanr
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import Ridge

from simharness.models.llm import Budget, JsonlCache
from usersim_core.cua_runner import inspect_surfaces_for_items
from usersim_core.residual_learner import WalkForwardResidualModel, within_day_zscore
from usersim_core.universal_sim_v7 import (
    UNIV_DISCOURSE_FEATURES,
    UNIV_PRODUCT_ONLY_FEATURES,
    UniversalUserSimulatorV7,
)

BUCKET = "usersim-bakeoff-347838016394/usersim_sim"


def _extract_domain(url: str) -> str:
    if not url:
        return "self.hn"
    try:
        netloc = urlparse(str(url)).netloc.lower()
        return netloc[4:] if netloc.startswith("www.") else (netloc or "self.hn")
    except Exception:
        return "self.hn"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work-dir", default="/var/tmp/usersim_core_work/hn_v7")
    ap.add_argument("--out-json", default="/var/tmp/usersim_core_work/usersim_core_hn_1_results.json")
    ap.add_argument("--gcs-prefix", default="gs://usersim-trace-store-347838016394/usersim_core_v7")
    ap.add_argument("--budget-usd", type=float, default=4.5)
    args = ap.parse_args()

    t0 = time.time()
    os.makedirs(args.work_dir, exist_ok=True)
    fs = gcsfs.GCSFileSystem()

    # 1. Stream 2026 HN posts (`2026-06-01 .. 2026-10-28`) from GCS `tables/hn_posts`
    post_files = sorted(x for x in fs.ls(f"{BUCKET}/tables/hn_posts") if x.endswith(".parquet"))
    frames = []
    for pf in post_files[-220:]:
        with fs.open(pf, "rb") as f:
            df_p = pq.read_table(
                f,
                columns=["post_id", "day", "created_at_i", "title", "url", "text", "author", "points", "num_comments", "link_kind"],
            ).to_pandas()
        df_p["day"] = df_p["day"].astype(str).str[:10]
        df_p = df_p[(df_p["day"] >= "2026-06-01") & (df_p["day"] <= "2026-10-28")]
        if not df_p.empty:
            frames.append(df_p)

    posts = pd.concat(frames, ignore_index=True)
    posts["post_id"] = posts["post_id"].astype(str)
    posts = posts.drop_duplicates("post_id", keep="last").sort_values(["day", "post_id"]).reset_index(drop=True)
    posts["points"] = pd.to_numeric(posts["points"], errors="coerce").fillna(1.0).clip(lower=1.0)
    posts["num_comments"] = pd.to_numeric(posts["num_comments"], errors="coerce").fillna(0.0).clip(lower=0.0)
    posts["log_points"] = np.log1p(posts["points"])
    posts["domain"] = [
        _extract_domain(u) if str(u or "") not in ("", "None", "nan") else "self.hn"
        for u in posts["url"]
    ]
    posts["hour_utc"] = ((pd.to_numeric(posts["created_at_i"], errors="coerce").fillna(0) % 86400) // 3600).astype(float)
    posts["is_show_hn"] = posts["title"].fillna("").str.startswith("Show HN").astype(float)
    posts["is_ask_hn"] = posts["title"].fillna("").str.startswith("Ask HN").astype(float)
    posts["is_github"] = posts["domain"].str.contains("github.com").astype(float)

    # 2. Stream `hn_early_points` (`age_min <= 30`, strictly stripping `points` & `toprank` -> ONLY early comments count!)
    early_comm_30m: dict[str, float] = {}
    ep_files = sorted(x for x in fs.ls(f"{BUCKET}/tables/hn_early_points") if x.endswith(".parquet"))
    for ef in ep_files[-160:]:
        with fs.open(ef, "rb") as f:
            ep = pq.read_table(f, columns=["item_id", "age_min", "comments"]).to_pandas()
        ep = ep[pd.to_numeric(ep["age_min"], errors="coerce").fillna(999) <= 32]
        if not ep.empty:
            grp = ep.groupby(ep["item_id"].astype(str))["comments"].max()
            for k, v in grp.items():
                if pd.notna(v):
                    early_comm_30m[str(k)] = max(early_comm_30m.get(str(k), 0.0), float(v))

    # 3. Walk-Forward `< D` Author & Domain Priors (100% strictly `< D`!)
    auth_sum: dict[str, float] = {}
    auth_cnt: dict[str, int] = {}
    dom_sum: dict[str, float] = {}
    dom_cnt: dict[str, int] = {}
    global_prior = float(posts[posts["day"] <= "2026-08-31"]["log_points"].mean())

    a_prior = np.zeros(len(posts), dtype=np.float64)
    a_posts_n = np.zeros(len(posts), dtype=np.float64)
    d_prior = np.zeros(len(posts), dtype=np.float64)

    for d, idx in posts.groupby("day", sort=True).groups.items():
        pos = np.asarray(list(idx), dtype=np.int64)
        for p_i in pos:
            au = str(posts.at[p_i, "author"] or "")
            dm = str(posts.at[p_i, "domain"] or "self.hn")
            ac = auth_cnt.get(au, 0)
            a_posts_n[p_i] = math.log1p(ac)
            a_prior[p_i] = (auth_sum.get(au, 0.0) + 5.0 * global_prior) / (ac + 5.0)
            dc = dom_cnt.get(dm, 0)
            d_prior[p_i] = (dom_sum.get(dm, 0.0) + 12.0 * global_prior) / (dc + 12.0)
        for p_i in pos:
            au = str(posts.at[p_i, "author"] or "")
            dm = str(posts.at[p_i, "domain"] or "self.hn")
            lp = float(posts.at[p_i, "log_points"])
            if au:
                auth_sum[au] = auth_sum.get(au, 0.0) + lp
                auth_cnt[au] = auth_cnt.get(au, 0) + 1
            dom_sum[dm] = dom_sum.get(dm, 0.0) + lp
            dom_cnt[dm] = dom_cnt.get(dm, 0) + 1

    posts["author_prior_lt_d"] = a_prior
    posts["author_posts_log_lt_d"] = a_posts_n
    posts["domain_prior_lt_d"] = d_prior
    posts["title_len"] = posts["title"].fillna("").str.len().astype(float)

    # 4. Fit Frozen HN Structural Model strictly on `<= 2026-08-31`!
    train_mask = posts["day"] <= "2026-08-31"
    vec = TfidfVectorizer(min_df=5, max_features=15000, ngram_range=(1, 2), sublinear_tf=True)
    txt_all = (posts["title"].fillna("") + " " + posts["domain"].fillna("")).tolist()
    X_txt_tr = vec.fit_transform([txt_all[i] for i in np.where(train_mask)[0]])
    txt_ridge = Ridge(alpha=6.0, random_state=42).fit(X_txt_tr, posts.loc[train_mask, "log_points"].to_numpy())
    posts["txt_ridge_pred"] = txt_ridge.predict(vec.transform(txt_all))

    struct_cols = [
        "author_prior_lt_d",
        "author_posts_log_lt_d",
        "domain_prior_lt_d",
        "txt_ridge_pred",
        "hour_utc",
        "title_len",
        "is_show_hn",
        "is_ask_hn",
        "is_github",
    ]
    hn_struct_lgb = lgb.LGBMRegressor(
        n_estimators=220,
        learning_rate=0.04,
        num_leaves=15,
        min_child_samples=40,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        n_jobs=1,
        deterministic=True,
        verbose=-1,
    ).fit(posts.loc[train_mask, struct_cols], posts.loc[train_mask, "log_points"])
    posts["structural_score"] = hn_struct_lgb.predict(posts[struct_cols])

    # Select Val (`2026-09-15 .. 2026-09-30`, 12 days) + Held-Out Test (`2026-10-01 .. 2026-10-20`, 18 days)
    # where days have >= 60 submissions AND `hn_early_points` coverage!
    eval_posts = posts[posts["day"] >= "2026-09-15"].copy()
    day_counts = eval_posts.groupby("day").size()
    valid_days = sorted(d for d, cnt in day_counts.items() if cnt >= 60)
    val_days = [d for d in valid_days if d <= "2026-09-30"][-10:]
    test_days = [d for d in valid_days if d >= "2026-10-01"][:16]
    chosen_days = val_days + test_days

    # Keep daily real rank across ALL submissions on each day, and shortlist Top-25 by `structural_score`!
    truth_by_day_hn: dict[str, dict[str, dict]] = {}
    full_day_hn: dict[str, list[dict]] = {}
    shortlist_rows = []

    for d in chosen_days:
        dg = posts[posts["day"] == d].copy()
        dg = dg.sort_values(["points", "post_id"], ascending=[False, True]).reset_index(drop=True)
        dg["real_rank"] = np.arange(1, len(dg) + 1, dtype=float)
        truth_by_day_hn[d] = {
            str(r.post_id): {"final_rank": int(r.real_rank), "votes": float(r.points)}
            for r in dg.itertuples(index=False)
        }
        dg_s = dg.sort_values(["structural_score", "post_id"], ascending=[False, True]).reset_index(drop=True)
        dg_s["structural_rank"] = np.arange(1, len(dg_s) + 1, dtype=int)
        full_day_hn[d] = [
            {
                "id": str(r.post_id),
                "name": str(r.title or ""),
                "structural_score": float(r.structural_score),
                "structural_rank": int(r.structural_rank),
                "pred_votes": float(np.expm1(r.structural_score)),
            }
            for r in dg_s.itertuples(index=False)
        ]
        top25 = dg_s.head(22).copy()
        for r in top25.itertuples(index=False):
            shortlist_rows.append({
                "day": d,
                "item_id": str(r.post_id),
                "title": str(r.title or ""),
                "summary": f"Domain: {r.domain}",
                "description": str(r.text or "")[:300],
                "url": str(r.url or ""),
                "domain": str(r.domain),
                "structural_score": float(r.structural_score),
                "structural_rank": int(r.structural_rank),
                "real_votes": float(r.points),
                "real_rank": float(r.real_rank),
                "true_log_residual": float(r.log_points - r.structural_score),
                "early_comm_30m": float(early_comm_30m.get(str(r.post_id), 0.0)),
                "has_early_30m": float(str(r.post_id) in early_comm_30m),
            })

    sl_df = pd.DataFrame(shortlist_rows).sort_values(["day", "item_id"], kind="mergesort").reset_index(drop=True)

    # 5. Live URL Surface Inspection (`SanitizedSurface`) on Top-22 HN contenders!
    surf_cache = JsonlCache(f"{args.work_dir}/cache_hn_surfaces")
    daily_urls = {str(r.item_id): str(r.url) for r in sl_df.itertuples(index=False) if str(r.url).startswith("http")}
    surfs = inspect_surfaces_for_items(
        items=sl_df.to_dict(orient="records"),
        sites_by_id={},
        daily_urls=daily_urls,
        product_urls_by_name={},
        cache=surf_cache,
        concurrency=16,
    )

    # 6. Run Zero-Rewrite `UniversalUserSimulatorV7` on Hacker News!
    budget = Budget(cap_usd=args.budget_usd)
    u7_cache = JsonlCache(f"{args.work_dir}/cache_hn_univ_v7")
    usim = UniversalUserSimulatorV7(cache=u7_cache, budget=budget)

    po_payloads = []
    disc_payloads = []
    panel_hn = (
        "- Member 1: Senior distributed systems & Rust/Linux engineer; upvotes deep technical postmortems, open-source tools, benchmarks; ignores PR fluff.\n"
        "- Member 2: Founder & Show HN builder; tests live demos/GitHub repos and rewards crisp self-hosted developer tools.\n"
        "- Member 3: Skeptical HN front-page regular; downranks SEO listicles, thin AI wrappers, and paywalled marketing blogs."
    )
    cal_hn = "On Hacker News, deep technical essays, genuine open-source repos with benchmarks, and primary-source discoveries break out; corporate marketing announcements and generic AI SaaS landing pages underperform."

    for d, dg in sl_df.groupby("day", sort=True):
        c_po = []
        c_disc = []
        for r in dg.itertuples(index=False):
            lid = str(r.item_id)
            sf = surfs.get(lid)
            cua_s = (
                f"status=clean, oss={sf.has_open_source}, docs={sf.has_docs}, demo={sf.has_interactive_demo}, waitlist={sf.is_waitlist}; excerpt={sf.sanitized_text[:200]}"
                if (sf and sf.access_status == "clean")
                else "[SITE_UNVERIFIED]"
            )
            c_po.append({
                "item_id": lid,
                "title": str(r.title),
                "summary": str(r.summary),
                "tags_str": "Show HN" if r.title.startswith("Show HN") else "HN Submission",
                "media_str": f"domain={r.domain}",
                "desc_short": str(r.description)[:200],
                "cua_str": cua_s,
                "comp_str": "HN front-page technical submissions",
                "brand_str": f"domain={r.domain}",
            })
            c_disc.append({
                "item_id": lid,
                "title": str(r.title),
                "summary": str(r.summary),
                "cua_str": cua_s[:180],
                "disc_stats_str": f"early_30m_comments={int(r.early_comm_30m)} (recorded={bool(r.has_early_30m)})",
                "maker_pitch_str": str(r.description)[:180],
                "user_comments_str": "(30m comment velocity signal)",
            })
        po_payloads.append({"day": str(d), "candidates": c_po, "panel_block": panel_hn, "calibration_notes": cal_hn})
        disc_payloads.append({"day": str(d), "candidates": c_disc})

    po_res = usim.run_batch("hackernews", "Hacker News", po_payloads, include_discourse=False, workers=8)
    disc_res = usim.run_batch("hackernews", "Hacker News", disc_payloads, include_discourse=True, workers=8)

    sl_df["active_mask"] = True
    for rk, zk in [
        ("raw_u7_claude_adopt", "u7_po_claude_adopt_z"),
        ("raw_u7_claude_breakout", "u7_po_claude_breakout_z"),
        ("raw_u7_claude_skeptic", "u7_po_claude_skeptic_z"),
        ("raw_u7_claude_systems", "u7_po_claude_systems_z"),
        ("raw_u7_gempro_adopt", "u7_po_gempro_adopt_z"),
        ("raw_u7_po_consensus", "u7_po_consensus_z"),
    ]:
        sl_df[rk] = [float((po_res.get((str(r.day), str(r.item_id))) or {}).get(rk, 0.45)) for r in sl_df.itertuples(index=False)]
        sl_df[zk] = within_day_zscore(sl_df, rk)

    sl_df["raw_early_30m_log"] = np.log1p(sl_df["early_comm_30m"].to_numpy(dtype=np.float64))
    sl_df["m_early_30m"] = sl_df["has_early_30m"].to_numpy(dtype=bool)
    sl_df["hn_early_comm30m_z"] = within_day_zscore(sl_df, "raw_early_30m_log", mask_col="m_early_30m")
    sl_df["raw_u7_disc_consensus"] = [
        float((disc_res.get((str(r.day), str(r.item_id))) or {}).get("raw_u7_disc_consensus", 0.45))
        for r in sl_df.itertuples(index=False)
    ]
    sl_df["u7_disc_consensus_z"] = within_day_zscore(sl_df, "raw_u7_disc_consensus")

    # Fit residual calibrator strictly on `val_days` (`<= 2026-09-30`), evaluate once on `test_days` (`Oct 2026`)!
    val_df = sl_df[sl_df["day"].isin(val_days)].copy().reset_index(drop=True)
    test_df = sl_df[sl_df["day"].isin(test_days)].copy().reset_index(drop=True)

    po_cols = ["u7_po_consensus_z", "u7_po_claude_systems_z", "u7_po_claude_skeptic_z", "u7_po_claude_breakout_z", "u7_po_gempro_adopt_z"]
    disc_cols = po_cols + ["hn_early_comm30m_z", "u7_disc_consensus_z"]

    m_po = WalkForwardResidualModel(feature_cols=po_cols, ridge_alpha=80.0, pairwise_C=0.06, target_std=0.35, max_shift=0.90).fit(val_df)
    m_disc = WalkForwardResidualModel(feature_cols=disc_cols, ridge_alpha=60.0, pairwise_C=0.08, target_std=0.55, max_shift=1.30).fit(val_df)

    test_df["score_story_only"] = m_po.score_df(test_df)
    test_df["score_story_early30m"] = m_disc.score_df(test_df)

    from usersim_core.residual_learner import evaluate_boards_and_ties

    ev_story_only = evaluate_boards_and_ties(full_day_hn, truth_by_day_hn, test_df, score_col="score_story_only", n_boot=5000)
    ev_story_disc = evaluate_boards_and_ties(full_day_hn, truth_by_day_hn, test_df, score_col="score_story_early30m", n_boot=5000)

    # Within-day Spearman correlation with true log(1+points) on Top-22 shortlist
    sp_base, sp_po, sp_disc = [], [], []
    for d, dg in test_df.groupby("day"):
        y = np.log1p(dg["real_votes"].to_numpy())
        sp_base.append(float(spearmanr(dg["structural_score"], y).correlation))
        sp_po.append(float(spearmanr(dg["score_story_only"], y).correlation))
        sp_disc.append(float(spearmanr(dg["score_story_early30m"], y).correlation))

    out = {
        "experiment_id": "USERSIM-CORE-HN-1",
        "domain": "hackernews",
        "val_days_n": len(val_days),
        "test_days_n": len(test_days),
        "test_window": f"{test_days[0]} .. {test_days[-1]}",
        "vertex_llm_cost_usd": round(budget.spent, 4),
        "elapsed_sec": round(time.time() - t0, 1),
        "within_day_spearman_log_points": {
            "hn_structural_baseline": round(float(np.mean(sp_base)), 4),
            "univ_sim_v7_story_only_t0": round(float(np.mean(sp_po)), 4),
            "univ_sim_v7_story_plus_30m_discourse": round(float(np.mean(sp_disc)), 4),
        },
        "heldout_oct_board_capture": {
            "story_only_t0_zero_comments": ev_story_only,
            "story_plus_30m_early_discourse": ev_story_disc,
        },
    }
    with open(args.out_json, "w") as f:
        json.dump(out, f, indent=2)
    if args.gcs_prefix:
        subprocess.run(["gcloud", "storage", "cp", "-q", args.out_json, f"{args.gcs_prefix.rstrip('/')}/usersim_core_hn_1_results.json"], check=True)
    print(json.dumps(out, indent=2), flush=True)


if __name__ == "__main__":
    main()
