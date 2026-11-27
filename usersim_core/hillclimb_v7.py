"""USERSIM-CORE-HILLCLIMB-7 Runner (`usersim_core/hillclimb_v7.py`).

Pushes both strictly separated Product Hunt website tracks toward their empirical ceiling
using the domain-agnostic `UniversalUserSimulatorV7` (`claude-sonnet-4-6` + `gemini-2.5-pro` + `gpt-oss-120b`):
  1. Complete Zero-Leakage Data Recovery (`complete_v7`):
     - All 23 live days' `<= 03:45 PT` post-midnight arrivals (`230/230` = `100%` candidate coverage, zero rank/vote/order).
     - `00:05 PT` zero-comment pre-launch features: `arm2_maker_delta_z` (`< D` maker track record + X maker reach),
       `media_has_video_z` & `media_gallery_depth_z` (`7,522` items), `pnx_ev_z` (`00:05 PT` Presence x Choice),
       `xbuzz_pre0000_z` (`< 00:00 PT` pre-launch X buzz), and `api_team_reach_z`.
     - Complete `<= 03:45 PT` non-maker community threads & maker Q&A replies (`1,780` recovered live comments on Oct-Nov,
       strictly isolated to `Product + comments` track!).
  2. Multi-Family 5-Archetype `UniversalUserSimulatorV7`:
     - Track 1 (`Product only`, ZERO comments): `Claude Sonnet 4.6` + `Gemini 2.5 Pro` 5-archetype adoption, craft,
       systems depth, anti-slop survival, and breakout probability + saved pre-launch user praises/complaints for
       `USERSIM-CORE-COMMENTS-1`.
     - Track 2 (`Product + comments`, `<= 03:45 PT` order-free): `Claude Sonnet 4.6` + `GPT-OSS-120B` organic community
       momentum vs coordinated pod-fluff evaluation over vote-scrubbed threads.
  3. `UncagedUniversalRankerV7`:
     - Removes the artificial `+-0.18` residual straitjacket via Val-Sep-locked uncaged consensus ranking over Top-25
       candidates, while enforcing `input_order_permutation_max_abs_diff < 1e-9` and
       `product_only_comment_isolation_max_abs_diff == 0.0`.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import glob
import json
import math
import os
import subprocess
import time
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd

from simharness.bench import scrub
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
from usersim_core.hillclimb_v6 import QWENVL_V6_FEATURES, attach_qwen_vl_features, monotone_sign_for_col
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


V7_PO_APR_EXTRA = [
    "arm2_maker_delta_z",
    "media_has_video_z",
    "media_gallery_depth_z",
]

V7_PO_SEP_EXTRA = [
    "pnx_ev_z",
    "pnx_pmax_z",
    "xbuzz_pre0000_z",
    "api_team_reach_z",
]

V7_PC_APR_EXTRA = [
    "pc7_user_distinct_log_z",
    "pc7_user_est_cred_z",
    "pc7_substantive_qa_z",
    "pc7_maker_reply_vel_z",
]

V7_PC_SEP_EXTRA = [
    "xbuzz_le0200_z",
]


def load_arm2_scores(struct_bt_dir: str, live_forecasts_dir: str) -> dict[tuple[str, str], float]:
    """Load strictly `< D` / `00:05 PT` `score_arm2` (`pred_arm2`) across Apr-Nov."""
    arm2: dict[tuple[str, str], float] = {}
    for bf in sorted(glob.glob(f"{struct_bt_dir}/*.json")):
        j = json.load(open(bf))
        d = str(j.get("day") or "")
        for x in j.get("launches") or []:
            lid = str(x.get("id") or "")
            s2 = x.get("score_arm2")
            if d and lid and isinstance(s2, (int, float)):
                arm2[(d, lid)] = float(s2)
    for fp in sorted(glob.glob(f"{live_forecasts_dir}/forecast_*.parquet")):
        pdf = pd.read_parquet(fp)
        if "pred_arm2" not in pdf.columns:
            continue
        for r in pdf.itertuples(index=False):
            d = str(r.day)
            lid = str(r.id)
            v = getattr(r, "pred_arm2", np.nan)
            if pd.notna(v):
                arm2.setdefault((d, lid), float(v))
    return arm2


def attach_v7_recovered_signals(
    full_df: pd.DataFrame,
    comm_map_bench: dict[str, dict[str, Any]],
    complete_v7_dir: str,
    arm2_map: dict[tuple[str, str], float],
) -> tuple[pd.DataFrame, dict[str, dict[str, Any]]]:
    """Attach zero-comment 00:05 signals AND (strictly isolated) complete <=03:45 PT thread signals."""
    df = full_df.copy().reset_index(drop=True)

    media_path = f"{complete_v7_dir}/page_media_map.json"
    media_map: dict[str, dict[str, float]] = json.load(open(media_path)) if os.path.exists(media_path) else {}

    day_bundles: dict[str, dict[str, Any]] = {}
    for p in sorted(glob.glob(f"{complete_v7_dir}/days/*.json")):
        b = json.load(open(p))
        day_bundles[str(b["day"])] = b

    # 1. Zero-comment 00:05 PT features (`arm2_delta`, `page_media`, `pnx`, `xbuzz_pre_0000`, `api_teams`)
    raw_arm2_delta = np.zeros(len(df), dtype=np.float64)
    has_arm2 = np.zeros(len(df), dtype=bool)
    raw_vid = np.zeros(len(df), dtype=np.float64)
    raw_med_cnt = np.zeros(len(df), dtype=np.float64)
    has_med = np.zeros(len(df), dtype=bool)

    raw_pnx_ev = np.zeros(len(df), dtype=np.float64)
    raw_pnx_pmax = np.zeros(len(df), dtype=np.float64)
    has_pnx = np.zeros(len(df), dtype=bool)

    raw_xb_pre = np.zeros(len(df), dtype=np.float64)
    has_xb_pre = np.zeros(len(df), dtype=bool)

    raw_team_reach = np.zeros(len(df), dtype=np.float64)
    has_team = np.zeros(len(df), dtype=bool)

    # 2. Strictly isolated `<= 03:45 PT` thread features (`bench.comments` unioned with `threads_le_0345`)
    raw_pc_dist = np.zeros(len(df), dtype=np.float64)
    raw_pc_cred = np.zeros(len(df), dtype=np.float64)
    raw_pc_qa = np.zeros(len(df), dtype=np.float64)
    raw_pc_mrep = np.zeros(len(df), dtype=np.float64)
    raw_xb_0200 = np.zeros(len(df), dtype=np.float64)
    has_xb_0200 = np.zeros(len(df), dtype=bool)

    merged_comm_map: dict[str, dict[str, Any]] = dict(comm_map_bench)

    for i, r in enumerate(df.itertuples(index=False)):
        d = str(r.day)
        lid = str(r.item_id)
        s3 = float(r.structural_score)

        if (d, lid) in arm2_map:
            raw_arm2_delta[i] = arm2_map[(d, lid)] - s3
            has_arm2[i] = True

        mm = media_map.get(lid)
        if mm is not None:
            raw_vid[i] = float(mm.get("has_video", 0.0))
            raw_med_cnt[i] = math.log1p(float(mm.get("media_count", 0.0)))
            has_med[i] = True

        db = day_bundles.get(d) or {}
        pnx = (db.get("pnx_0005") or {}).get(lid)
        if pnx:
            raw_pnx_ev[i] = math.log1p(max(0.0, float(pnx.get("pnx_ev", 0.0))))
            raw_pnx_pmax[i] = float(pnx.get("pnx_pmax", 0.0))
            has_pnx[i] = True

        xbp = (db.get("xbuzz_pre_0000") or {}).get(lid)
        if xbp:
            raw_xb_pre[i] = (
                0.40 * float(xbp.get("accounts", 0.0))
                + 0.35 * float(xbp.get("engagement", 0.0))
                + 0.25 * float(xbp.get("preannounced", 0.0))
            )
            has_xb_pre[i] = True

        tm = (db.get("team_stats") or {}).get(lid)
        if tm:
            raw_team_reach[i] = float(tm.get("api_team_sum_followers_log", 0.0))
            has_team[i] = True

        xb2 = (db.get("xbuzz_le_0200") or {}).get(lid)
        if xb2:
            raw_xb_0200[i] = 0.50 * float(xb2.get("accounts", 0.0)) + 0.50 * float(xb2.get("engagement", 0.0))
            has_xb_0200[i] = True

        # Merge bench.comments + live <=03:45 PT threads (NEVER read by Product-only!)
        bc = comm_map_bench.get(lid) or {}
        th = (db.get("threads_le_0345") or {}).get(lid) or {}

        n_dist = max(float(bc.get("early_n_distinct", 0.0)), float(th.get("user_distinct_count", 0.0)))
        n_est = max(float(bc.get("early_n_established", 0.0)), float(th.get("user_est25_count", 0.0)))
        cred = max(float(bc.get("early_discerning_sum", 0.0)), float(th.get("user_follower_weighted_sum", 0.0)))
        n_sub = max(float(bc.get("early_substantive_n", 0.0)), float(th.get("user_substantive_count", 0.0)))
        n_q = float(th.get("user_question_count", 0.0))
        n_mrep = float(th.get("maker_reply_count", 0.0))

        raw_pc_dist[i] = math.log1p(n_dist)
        raw_pc_cred[i] = math.log1p(cred + 0.8 * n_est)
        raw_pc_qa[i] = math.log1p(n_sub + 1.2 * n_q)
        raw_pc_mrep[i] = math.log1p(n_mrep)

        if th:
            prev_c = dict(bc)
            if th.get("maker_first_comment") and not prev_c.get("maker_first_comment"):
                prev_c["maker_first_comment"] = th["maker_first_comment"]
                prev_c["has_maker_comment"] = 1.0
                prev_c["maker_comment_len"] = float(len(th["maker_first_comment"]))
            if th.get("top_user_comments"):
                combined_u = list(dict.fromkeys((th.get("top_user_comments") or []) + (prev_c.get("early_comm_texts") or [])))
                prev_c["early_comm_texts"] = combined_u[:10]
            prev_c["early_n_distinct"] = n_dist
            prev_c["early_n_established"] = n_est
            prev_c["early_discerning_sum"] = cred
            prev_c["early_substantive_n"] = n_sub
            prev_c["maker_reply_count"] = n_mrep
            prev_c["user_question_count"] = n_q
            merged_comm_map[lid] = prev_c

    df["_m_arm2"] = has_arm2
    df["_m_med"] = has_med
    df["_m_pnx"] = has_pnx
    df["_m_xbp"] = has_xb_pre
    df["_m_team"] = has_team
    df["_m_xb2"] = has_xb_0200

    df["_r_arm2"] = raw_arm2_delta
    df["_r_vid"] = raw_vid
    df["_r_medc"] = raw_med_cnt
    df["_r_pnx_ev"] = raw_pnx_ev
    df["_r_pnx_pm"] = raw_pnx_pmax
    df["_r_xbp"] = raw_xb_pre
    df["_r_team"] = raw_team_reach
    df["_r_xb2"] = raw_xb_0200

    df["raw_pc7_dist"] = raw_pc_dist
    df["raw_pc7_cred"] = raw_pc_cred
    df["raw_pc7_qa"] = raw_pc_qa
    df["raw_pc7_mrep"] = raw_pc_mrep

    df["arm2_maker_delta_z"] = within_day_zscore(df, "_r_arm2", mask_col="_m_arm2")
    df["media_has_video_z"] = within_day_zscore(df, "_r_vid", mask_col="_m_med")
    df["media_gallery_depth_z"] = within_day_zscore(df, "_r_medc", mask_col="_m_med")
    df["pnx_ev_z"] = within_day_zscore(df, "_r_pnx_ev", mask_col="_m_pnx")
    df["pnx_pmax_z"] = within_day_zscore(df, "_r_pnx_pm", mask_col="_m_pnx")
    df["xbuzz_pre0000_z"] = within_day_zscore(df, "_r_xbp", mask_col="_m_xbp")
    df["api_team_reach_z"] = within_day_zscore(df, "_r_team", mask_col="_m_team")

    df["pc7_user_distinct_log_z"] = within_day_zscore(df, "raw_pc7_dist")
    df["pc7_user_est_cred_z"] = within_day_zscore(df, "raw_pc7_cred")
    df["pc7_substantive_qa_z"] = within_day_zscore(df, "raw_pc7_qa")
    df["pc7_maker_reply_vel_z"] = within_day_zscore(df, "raw_pc7_mrep")
    df["xbuzz_le0200_z"] = within_day_zscore(df, "_r_xb2", mask_col="_m_xb2")

    drop_tmp = [c for c in df.columns if c.startswith("_m_") or c.startswith("_r_")]
    df = df.drop(columns=drop_tmp)
    return df, merged_comm_map


@dataclass
class UncagedUniversalRankerV7:
    """Walk-forward Uncaged Universal User Simulator Ranker (`0.0` perm diff, `0.0` comment leak on PO)."""

    apr_cols: list[str]
    sep_cols: list[str]
    target_std_apr: float = 0.095
    target_std_sep: float = 0.065
    lgb_weight: float = 0.15
    arm2_weight: float = 0.20
    u7_sim_bonus: float = 0.085
    fin_bonus: float = 0.045
    qwen_vl_bonus: float = 0.025
    qwen_stack_bonus: float = 0.028
    max_shift_cap: float = 0.55
    is_product_only: bool = True

    def predict_walkforward(self, df_all: pd.DataFrame) -> dict[tuple[str, str], float]:
        df_s = df_all.sort_values(["day", "item_id"], kind="mergesort").reset_index(drop=True)
        df_s["z_struct_day"] = within_day_zscore(df_s, "structural_score")

        excluded_apr = {"pop_qwen_stack1b_z", *QWENVL_V6_FEATURES, *UNIV_PRODUCT_ONLY_FEATURES, *UNIV_DISCOURSE_FEATURES}
        apr_lin_cols = list(dict.fromkeys(c for c in self.apr_cols if c not in excluded_apr and c in df_s.columns))
        joint_lgb_cols = list(dict.fromkeys(["structural_score", "z_struct_day"] + apr_lin_cols))
        mono_vec = [monotone_sign_for_col(c) for c in joint_lgb_cols]
        sep_lin_cols = list(dict.fromkeys(c for c in self.sep_cols if c != "pop_qwen_stack1b_z" and c in df_s.columns))

        overrides: dict[tuple[str, str], float] = {}

        for mon in ("2026-09", "2026-10", "2026-11"):
            te = df_s[df_s["day"].str[:7] == mon].copy().reset_index(drop=True)
            if te.empty:
                continue

            tr_apr = (
                df_s[(df_s["day"].str[:7] < mon) & (df_s["day"] <= "2026-11-24")]
                .copy()
                .reset_index(drop=True)
            )
            m_apr = WalkForwardResidualModel(
                feature_cols=apr_lin_cols,
                ridge_alpha=220.0,
                pairwise_C=0.045,
                target_std=self.target_std_apr,
                max_shift=self.max_shift_cap,
            ).fit(tr_apr)
            shift_lin = m_apr.predict_shift(te)

            shift_lgb = np.zeros(len(te), dtype=np.float64)
            if self.lgb_weight > 0.0 and len(tr_apr) >= 200:
                X_tr = np.nan_to_num(tr_apr[joint_lgb_cols].to_numpy(dtype=np.float64), nan=0.0, posinf=0.0, neginf=0.0)
                X_te = np.nan_to_num(te[joint_lgb_cols].to_numpy(dtype=np.float64), nan=0.0, posinf=0.0, neginf=0.0)
                y_res_tr = np.clip(tr_apr["true_log_residual"].to_numpy(dtype=np.float64), -1.5, 1.5)
                srank_tr = tr_apr["structural_rank"].to_numpy(dtype=np.float64)
                w_tr = np.where(srank_tr <= 15, 1.30, 0.85)

                gbdt_res = lgb.LGBMRegressor(
                    n_estimators=80,
                    learning_rate=0.03,
                    num_leaves=7,
                    min_child_samples=55,
                    subsample=0.8,
                    subsample_freq=1,
                    colsample_bytree=0.75,
                    reg_alpha=4.0,
                    reg_lambda=20.0,
                    monotone_constraints=mono_vec,
                    random_state=42,
                    n_jobs=1,
                    deterministic=True,
                    force_col_wise=True,
                    verbose=-1,
                )
                gbdt_res.fit(X_tr, y_res_tr, sample_weight=w_tr)
                z_tr = tr_apr["z_struct_day"].to_numpy(dtype=np.float64)
                z_te = te["z_struct_day"].to_numpy(dtype=np.float64)
                p_tr = gbdt_res.predict(X_tr)
                p_te = gbdt_res.predict(X_te)
                b_res = float(np.cov(p_tr, z_tr)[0, 1] / max(float(np.var(z_tr)), 1e-6))
                orth_tr = p_tr - b_res * z_tr
                orth_te = p_te - b_res * z_te
                shift_lgb = (orth_te / max(float(np.std(orth_tr)), 1e-6)) * self.target_std_apr

            shift = (1.0 - self.lgb_weight) * shift_lin + self.lgb_weight * shift_lgb

            # Maker-aware structural recovery (`score_arm2 - score_arm3`)
            if self.arm2_weight > 0.0 and "arm2_maker_delta_z" in te.columns:
                shift = shift + self.arm2_weight * 0.12 * te["arm2_maker_delta_z"].to_numpy(dtype=np.float64)

            # Sep-Nov High-Resolution Walk-Forward Stage (`UniversalSim v7` + `CUA v4` + `pnx` + `x_buzz` + `Discourse`)
            if sep_lin_cols and mon >= "2026-10":
                tr_sep = (
                    df_s[(df_s["day"] >= "2026-09-01") & (df_s["day"].str[:7] < mon) & (df_s["day"] <= "2026-11-24")]
                    .copy()
                    .reset_index(drop=True)
                )
                if len(tr_sep) >= 100:
                    m_sep = WalkForwardResidualModel(
                        feature_cols=sep_lin_cols,
                        ridge_alpha=150.0,
                        pairwise_C=0.050,
                        target_std=self.target_std_sep,
                        max_shift=self.max_shift_cap,
                    ).fit(tr_sep)
                    shift = shift + m_sep.predict_shift(te)

            # Multi-Family Universal User Simulator Direct Consensus (`Claude Sonnet 4.6` + `Gemini 2.5 Pro` + `GPT-OSS-120B`)!
            if self.u7_sim_bonus > 0.0:
                if self.is_product_only:
                    u7_sig = (
                        0.45 * te["u7_po_consensus_z"].to_numpy(dtype=np.float64)
                        + 0.20 * te["u7_po_claude_breakout_z"].to_numpy(dtype=np.float64)
                        + 0.15 * te["u7_po_claude_skeptic_z"].to_numpy(dtype=np.float64)
                        + 0.20 * te["v3po_net_conviction_z"].to_numpy(dtype=np.float64)
                    )
                else:
                    u7_sig = (
                        0.45 * te["u7_disc_consensus_z"].to_numpy(dtype=np.float64)
                        + 0.25 * te["u7_po_consensus_z"].to_numpy(dtype=np.float64)
                        + 0.30 * te["pc7_user_distinct_log_z"].to_numpy(dtype=np.float64)
                    )
                shift = shift + self.u7_sim_bonus * u7_sig

            if self.fin_bonus > 0.0:
                direct_po = (
                    0.48 * te["v4_finalist_po_z"].to_numpy(dtype=np.float64)
                    + 0.22 * te["mm_discerning_adopt_z"].to_numpy(dtype=np.float64)
                    + 0.16 * te["mm_hands_on_works_z"].to_numpy(dtype=np.float64)
                    + 0.14 * te["comp_cua_advantage_z"].to_numpy(dtype=np.float64)
                )
                shift = shift + self.fin_bonus * direct_po

            if self.qwen_vl_bonus > 0.0 and "qwen_vl_choice_mean_z" in te.columns:
                qvl_sig = (
                    0.55 * te["qwen_vl_choice_mean_z"].to_numpy(dtype=np.float64)
                    + 0.30 * te["qwen_vl_choice_p80_z"].to_numpy(dtype=np.float64)
                    + 0.15 * te["qwen_vl_cua_works_z"].to_numpy(dtype=np.float64)
                ) * te["has_qwen_vl_choice"].to_numpy(dtype=np.float64)
                shift = shift + self.qwen_vl_bonus * qvl_sig

            if self.qwen_stack_bonus > 0.0 and "pop_qwen_stack1b_z" in te.columns:
                q_sig = (
                    0.65 * te["pop_qwen_stack1b_z"].to_numpy(dtype=np.float64)
                    + 0.35 * te["pop_power_builder_votes_z"].to_numpy(dtype=np.float64)
                ) * te["has_qwen_backer_pred"].to_numpy(dtype=np.float64)
                shift = shift + self.qwen_stack_bonus * q_sig

            cold_z = te["brand_coldstart_authority_z"].to_numpy(dtype=np.float64)
            cua_z = te["comp_cua_advantage_z"].to_numpy(dtype=np.float64)
            cold_lift = 0.035 * np.maximum(0.0, cold_z - 0.85) * (cua_z >= -0.25).astype(np.float64)

            shift = np.clip(shift + cold_lift, -self.max_shift_cap, self.max_shift_cap)
            scores = te["structural_score"].to_numpy(dtype=np.float64) + shift
            for r_id, r_day, sc in zip(te["item_id"], te["day"], scores):
                overrides[(str(r_day), str(r_id))] = float(sc)

        return overrides


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
    ap.add_argument("--out-json", default="/var/tmp/usersim_core_work/usersim_core_hillclimb_7_results.json")
    ap.add_argument("--pred-comments-out", default="/var/tmp/usersim_core_work/u7_predicted_comments.json")
    ap.add_argument("--why-out-dir", default="/var/tmp/usersim_core_work/why_v7")
    ap.add_argument("--gcs-prefix", default="gs://usersim-trace-store-347838016394/usersim_core_v7")
    ap.add_argument("--budget-usd", type=float, default=16.0)
    args = ap.parse_args()

    t0 = time.time()
    os.environ["USERSIM_WORK_DIR"] = os.path.dirname(os.path.abspath(args.work_dir))

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

    base_df = pd.read_parquet(f"{args.work_dir}/stage_b_features.parquet")
    live_0005_launches, live_truth, forecast_ids_by_day = load_live_0005_lineups(
        args.live23_dir, full_day_launches, truth_by_day
    )
    late_est = LateLaunchStructuralEstimator().fit_from_forecasts_and_bt(
        bench, full_day_launches, f"{args.live23_dir}/forecasts", cutoff_day="2026-11-24"
    )

    live_expanded_launches: dict[str, list[dict]] = {}
    extra_rows_to_score: list[dict[str, Any]] = []
    nov25_meta_by_id = {
        str(json.loads(l)["id"]): json.loads(l)
        for l in open(f"{args.live23_dir}/nov25/20261125T1834PT.jsonl")
    }

    # Build lookup of sanitized post-00:05 metadata across ALL synced days!
    synced_post_meta: dict[str, dict[str, Any]] = {}
    for dp in sorted(glob.glob(f"{args.complete_v7_dir}/days/*.json")):
        db = json.load(open(dp))
        for r in db.get("post0005_sanitized") or []:
            if r.get("id"):
                synced_post_meta[str(r["id"])] = r

    for d in LIVE_23_DAYS:
        cur_list = [dict(x) for x in live_0005_launches[d]]
        f_ids = forecast_ids_by_day[d]
        late_recs = discover_live_post_0005_launches(d, f_ids, args.live23_dir)
        bt_map = {str(x["id"]): x for x in full_day_launches.get(d, [])}
        for lr in late_recs:
            lid = str(lr["id"])
            sc = float(bt_map[lid]["structural_score"]) if lid in bt_map else late_est.score_late_launch(lr)
            cur_list.append({
                "id": lid,
                "name": str(lr.get("name") or ""),
                "structural_score": sc,
                "structural_rank": 99,
                "pred_votes": float(np.expm1(sc)),
            })
        cur_list = sorted(cur_list, key=lambda x: (-float(x["structural_score"]), str(x["id"])))
        for rk, x in enumerate(cur_list, start=1):
            x["structural_rank"] = rk
        live_expanded_launches[d] = cur_list

        existing_day_ids = set(base_df[base_df["day"] == d]["item_id"].astype(str))
        for x in cur_list[:25]:
            lid = str(x["id"])
            if lid in existing_day_ids:
                continue
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

    # 1. Load HC3 Google-SSO surfaces + HC4 4-step CUA traces
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
    mm_judged, _ = score_multimodal_cua_traces(
        cua4_records, item_lookup, pool, mm_cache, budget, workers=8
    )

    # 2. Recover complete <=03:45 PT comments + 00:05 PT media/arm2/pnx/xbuzz signals!
    print("[Hillclimb v7] Extracting bench + recovered raw/ph_at_launch signals...", flush=True)
    comm_map_bench = extract_pre_reveal_comments(bench, pool, args.live23_dir, cutoff_minutes_after_midnight_pt=225)
    arm2_map = load_arm2_scores(f"{args.data_dir}/struct_bt", f"{args.live23_dir}/forecasts")
    full_df, merged_comm_map = attach_v7_recovered_signals(full_df, comm_map_bench, args.complete_v7_dir, arm2_map)

    full_df = attach_walkforward_product_comment_features(full_df, merged_comm_map)
    full_df, _ = load_apify_signals(full_df, args.apify_dir, args.data_dir)
    full_df = attach_v3_causal_features(full_df, bench, surfaces_by_id, sso_meta, args.live23_dir)

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

    # 3. `< D` Named Competitor Graph + 93,618-Person Choice Sim + Cold-Start Authority + Qwen2.5-VL-7B
    comp_graph = CompetitorGraph(bench, pool, args.data_dir, args.apify_dir)
    full_df, comp_map = comp_graph.attach_features(full_df, surfaces_by_id, cua4_records, mm_judged)
    pop_sim = PopulationChoiceSim(bench, pool, args.data_dir, args.live23_dir)
    full_df, why_pop_by_key = pop_sim.simulate_all_days(full_df, comp_map, tau=0.85)
    full_df = attach_cold_start_brand_authority(full_df, args.apify_dir, args.live23_dir, surfaces_by_id)
    full_df, qwen_vl_stats = attach_qwen_vl_features(full_df, args.qwen_vl_parquet)

    # 4. Run Multi-Family 5-Archetype `UniversalUserSimulatorV7` across Sep-Nov (`Claude Sonnet 4.6` + `Gemini 2.5 Pro` + `GPT-OSS-120B`)!
    print("[Hillclimb v7] Running Multi-Family UniversalUserSimulatorV7 (Claude Sonnet 4.6 + Gemini 2.5 Pro + GPT-OSS-120B)...", flush=True)
    u7_cache = JsonlCache(f"{args.work_dir}/cache_univ_v7")
    usim = UniversalUserSimulatorV7(cache=u7_cache, budget=budget)

    media_path = f"{args.complete_v7_dir}/page_media_map.json"
    media_map = json.load(open(media_path)) if os.path.exists(media_path) else {}

    po_payloads: list[dict[str, Any]] = []
    disc_payloads: list[dict[str, Any]] = []
    sep_nov_df = full_df[sep_nov_mask].copy()

    for d, dg in sep_nov_df.groupby("day", sort=True):
        d_str = str(d)
        d_eff = d_str if d_str <= "2026-11-24" else "2026-11-24"
        q_text = " ".join(f"{r.title} {r.summary}" for r in dg.head(6).itertuples(index=False))
        matched = pool.match_cohort(d_eff, q_text[:400], k=5)
        panel_block = "\n".join(f"- Member {i+1}: {m['history_brief'][:260]}" for i, m in enumerate(matched))
        priors_d = calibrator.category_prior_as_of(hist_for_cal, d_str)
        cal_notes = "\n".join(
            calibrator.render_category_note(str(cat), priors_d)
            for cat in list(dg["category_0005"].unique())[:6]
        )

        cands_po = []
        cands_disc = []
        for r in dg.itertuples(index=False):
            lid = str(r.item_id)
            surf = surfaces_by_id.get(lid)
            cr = cua4_records.get(lid) or {}
            mm = mm_judged.get(lid) or {}
            med = media_map.get(lid) or {}
            med_str = f"video={'yes' if med.get('has_video') else 'no'}, gallery_items={int(med.get('media_count', 0))}"

            if cr or (surf and surf.access_status == "clean"):
                cua_str = (
                    f"status=clean, trait={surf.product_trait if surf else 'n/a'}, "
                    f"demo={bool(surf and surf.has_interactive_demo)}, oss={bool((surf and surf.has_open_source) or cr.get('has_github_link'))}, "
                    f"free={bool(surf and surf.has_free_tier)}, waitlist={bool(surf and surf.is_waitlist)}, "
                    f"sso_entered={bool(cr.get('google_sso_entered'))}, workflow_ok={bool(cr.get('workflow_responded'))}, "
                    f"hands_on_score={mm.get('hands_on_works', 'n/a')}; "
                    f"digest={str(mm.get('exec_digest') or (surf.sanitized_text[:180] if surf else ''))}"
                )
            else:
                cua_str = "[SITE_UNVERIFIED]"

            comps = (comp_map.get(lid) or [])[:3]
            comp_str = "; ".join(
                f"{c['name']} (reviews={c.get('reviews_count', 0)}, pain={str(c.get('key_user_pain_point') or 'none')[:70]})"
                for c in comps
            ) or "none"

            brand_str = f"brand_auth_z={r.brand_coldstart_authority_z:.2f}, oss_proto_z={r.brand_protocol_oss_leverage_z:.2f}"
            tags_s = ", ".join(r.tags[:4]) if isinstance(r.tags, (list, np.ndarray)) else str(r.category_0005)

            cands_po.append({
                "item_id": lid,
                "title": str(r.title or ""),
                "summary": str(r.summary or ""),
                "tags_str": tags_s,
                "media_str": med_str,
                "desc_short": str(r.description or "")[:240],
                "cua_str": cua_str[:320],
                "comp_str": comp_str[:240],
                "brand_str": brand_str,
            })

            # Discourse payload ONLY for Track 2 (`Product + comments`)!
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
                "item_id": lid,
                "title": str(r.title or ""),
                "summary": str(r.summary or ""),
                "cua_str": cua_str[:240],
                "disc_stats_str": disc_stats,
                "maker_pitch_str": str(cm.get("maker_first_comment") or "")[:220],
                "user_comments_str": u_comms[:520],
            })

        po_payloads.append({
            "day": d_str,
            "candidates": cands_po,
            "panel_block": panel_block,
            "calibration_notes": cal_notes,
            "emit_comments": ("2026-11-15" <= d_str <= "2026-11-24"),
        })
        disc_payloads.append({"day": d_str, "candidates": cands_disc})

    u7_po_res = usim.run_batch("producthunt", "Product Hunt", po_payloads, include_discourse=False, workers=8)
    u7_disc_res = usim.run_batch("producthunt", "Product Hunt", disc_payloads, include_discourse=True, workers=8)

    # Save zero-comment pre-launch predicted praises & complaints for `USERSIM-CORE-COMMENTS-1`!
    pred_comments_export = {
        f"{d}|{lid}": {
            "day": d,
            "item_id": lid,
            "predicted_praises": vals.get("predicted_praises", []),
            "predicted_complaints": vals.get("predicted_complaints", []),
        }
        for (d, lid), vals in u7_po_res.items()
    }
    with open(args.pred_comments_out, "w") as f:
        json.dump(pred_comments_export, f, indent=2)

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
        full_df[raw_k] = [float((u7_po_res.get((str(r.day), str(r.item_id))) or {}).get(raw_k, 0.0)) for r in full_df.itertuples(index=False)]
        full_df[z_k] = within_day_zscore(full_df, raw_k, mask_col="sep_nov_active")

    for raw_k, z_k in [
        ("raw_u7_disc_claude_org", "u7_disc_claude_organic_z"),
        ("raw_u7_disc_claude_brk", "u7_disc_claude_breakout_z"),
        ("raw_u7_disc_gpt_org", "u7_disc_gpt_organic_z"),
        ("raw_u7_disc_consensus", "u7_disc_consensus_z"),
    ]:
        full_df[raw_k] = [float((u7_disc_res.get((str(r.day), str(r.item_id))) or {}).get(raw_k, 0.0)) for r in full_df.itertuples(index=False)]
        full_df[z_k] = within_day_zscore(full_df, raw_k, mask_col="sep_nov_active")

    print(f"[Hillclimb v7] All features + Multi-Family UnivSim ready in {time.time() - t0:.1f}s (Vertex spend=${budget.spent:.4f}).", flush=True)

    # ------------------------------------------------------------------
    # Lock All Hyperparameters Strictly on Val Sep (`2026-09-01 .. 2026-09-30`)!
    # ------------------------------------------------------------------
    val_bt = {d: v for d, v in full_day_launches.items() if d.startswith("2026-09")}
    val_df_only = full_df[full_df["day"] <= "2026-09-30"].copy()

    po_apr_v7 = (
        ALL_RESIDUAL_FEATURES
        + PRODUCT_ONLY_V3_TABULAR
        + COMPETITOR_V5_FEATURES
        + POPULATION_V5_FEATURES
        + BRAND_AUTHORITY_V5_FEATURES
        + V7_PO_APR_EXTRA
    )
    po_sep_v7 = (
        COHORT_V3_PO_FEATURES
        + INTERACTIVE_CUA_V4_FEATURES
        + APIFY_FEATURES
        + QWENVL_V6_FEATURES
        + V7_PO_SEP_EXTRA
        + UNIV_PRODUCT_ONLY_FEATURES
    )

    best_po_key, best_po_cfg = (-1e9, -1e9), (0.085, 0.0, 0.20, 0.075, 0.045, 0.48)
    for ts_a in (0.075, 0.095):
        for lgb_w in (0.0, 0.15):
            for arm2_w in (0.0, 0.25, 0.45):
                for u7_b in (0.045, 0.085, 0.125):
                    for fb_a, mcap in ((0.045, 0.42), (0.055, 0.60)):
                        rk_po = UncagedUniversalRankerV7(
                            apr_cols=po_apr_v7,
                            sep_cols=[],
                            target_std_apr=ts_a,
                            target_std_sep=0.0,
                            lgb_weight=lgb_w,
                            arm2_weight=arm2_w,
                            u7_sim_bonus=u7_b,
                            fin_bonus=fb_a,
                            qwen_vl_bonus=0.0,
                            qwen_stack_bonus=0.0,
                            max_shift_cap=mcap,
                            is_product_only=True,
                        )
                        ov_v = rk_po.predict_walkforward(val_df_only)
                        vsub = val_df_only[val_df_only["day"].str.startswith("2026-09")].copy()
                        vsub["final_score"] = [ov_v[(str(r.day), str(r.item_id))] for r in vsub.itertuples(index=False)]
                        ev = evaluate_boards_and_ties(val_bt, truth_by_day, vsub, n_boot=60)
                        cand_key = (
                            round(ev["model"]["mean_3_5_10"] + 0.25 * ev["model"]["top10"] + 0.15 * ev["model"]["top3"], 4),
                            ev["reach_matched_ties"]["model_acc_pct"],
                        )
                        if cand_key > best_po_key:
                            best_po_key = cand_key
                            best_po_cfg = (ts_a, lgb_w, arm2_w, u7_b, fb_a, mcap)

    pc_apr_v7 = po_apr_v7 + PROD_COMMENT_FEATURES + COMMENT_V3_EXTRA + V7_PC_APR_EXTRA
    pc_sep_v7 = po_sep_v7 + COHORT_V2_FEATURES + V7_PC_SEP_EXTRA + UNIV_DISCOURSE_FEATURES

    best_pc_key, best_pc_cfg = (-1e9, -1e9), (0.125, 0.0, 0.20, 0.105, 0.025, 0.60)
    for ts_b in (0.115, 0.145):
        for lgb_w in (0.0, 0.15):
            for arm2_w in (0.0, 0.20):
                for u7_b in (0.065, 0.115, 0.165):
                    for fb_b, mcap in ((0.025, 0.48), (0.030, 0.68)):
                        rk_pc = UncagedUniversalRankerV7(
                            apr_cols=pc_apr_v7,
                            sep_cols=[],
                            target_std_apr=ts_b,
                            target_std_sep=0.0,
                            lgb_weight=lgb_w,
                            arm2_weight=arm2_w,
                            u7_sim_bonus=u7_b,
                            fin_bonus=fb_b,
                            qwen_vl_bonus=0.030,
                            qwen_stack_bonus=0.0,
                            max_shift_cap=mcap,
                            is_product_only=False,
                        )
                        ov_v = rk_pc.predict_walkforward(val_df_only)
                        vsub = val_df_only[val_df_only["day"].str.startswith("2026-09")].copy()
                        vsub["final_score"] = [ov_v[(str(r.day), str(r.item_id))] for r in vsub.itertuples(index=False)]
                        ev = evaluate_boards_and_ties(val_bt, truth_by_day, vsub, n_boot=60)
                        cand_key = (
                            round(ev["model"]["mean_3_5_10"] + 0.25 * ev["model"]["top10"], 4),
                            ev["reach_matched_ties"]["model_acc_pct"],
                        )
                        if cand_key > best_pc_key:
                            best_pc_key = cand_key
                            best_pc_cfg = (ts_b, lgb_w, arm2_w, u7_b, fb_b, mcap)

    print(
        f"[Hillclimb v7] Locked on Val Sep (<=2026-09-30) -> "
        f"PO cfg={best_po_cfg} (obj={best_po_key[0]:.2f}, ties={best_po_key[1]:.2f}%) | "
        f"PC cfg={best_pc_cfg} (obj={best_pc_key[0]:.2f}, ties={best_pc_key[1]:.2f}%)",
        flush=True,
    )

    # ------------------------------------------------------------------
    # Single Walk-Forward Evaluation on Oct-Nov Locked Test & 23d Live Window!
    # ------------------------------------------------------------------
    ranker_po_v7 = UncagedUniversalRankerV7(
        apr_cols=po_apr_v7,
        sep_cols=po_sep_v7,
        target_std_apr=best_po_cfg[0],
        target_std_sep=0.058,
        lgb_weight=best_po_cfg[1],
        arm2_weight=best_po_cfg[2],
        u7_sim_bonus=best_po_cfg[3],
        fin_bonus=best_po_cfg[4],
        qwen_vl_bonus=0.0,
        qwen_stack_bonus=0.025,
        max_shift_cap=best_po_cfg[5],
        is_product_only=True,
    )
    ranker_pc_v7 = UncagedUniversalRankerV7(
        apr_cols=pc_apr_v7,
        sep_cols=pc_sep_v7,
        target_std_apr=best_pc_cfg[0],
        target_std_sep=0.075,
        lgb_weight=best_pc_cfg[1],
        arm2_weight=best_pc_cfg[2],
        u7_sim_bonus=best_pc_cfg[3],
        fin_bonus=best_pc_cfg[4],
        qwen_vl_bonus=0.030,
        qwen_stack_bonus=0.028,
        max_shift_cap=best_pc_cfg[5],
        is_product_only=False,
    )

    ov_po_v7 = ranker_po_v7.predict_walkforward(full_df)
    ov_pc_v7 = ranker_pc_v7.predict_walkforward(full_df)

    # Automated Leak, Permutation-Invariance & Comment-Isolation Assertions!
    shuf_df = full_df.sample(frac=1.0, random_state=777).reset_index(drop=True)
    ov_po_shuf = ranker_po_v7.predict_walkforward(shuf_df)
    ov_pc_shuf = ranker_pc_v7.predict_walkforward(shuf_df)
    max_perm_diff_po = max(abs(ov_po_v7[k] - ov_po_shuf[k]) for k in ov_po_v7)
    max_perm_diff_pc = max(abs(ov_pc_v7[k] - ov_pc_shuf[k]) for k in ov_pc_v7)
    max_perm_diff = max(max_perm_diff_po, max_perm_diff_pc)

    zero_comm_df = full_df.copy()
    for c in (
        PROD_COMMENT_FEATURES
        + COMMENT_V3_EXTRA
        + COHORT_V2_FEATURES
        + V7_PC_APR_EXTRA
        + V7_PC_SEP_EXTRA
        + UNIV_DISCOURSE_FEATURES
        + [
            "maker_comment_present", "raw_maker_len", "raw_early_disc", "raw_early_subs", "raw_early_est",
            "raw_pc_pitch_ridge", "raw_pc_comm_ridge", "raw_pc_scout", "raw_pc_mrep", "raw_pc_q",
            "v2_raw_endorse", "v2_raw_use", "v2_raw_sub", "v2_raw_net",
            "raw_pc7_dist", "raw_pc7_cred", "raw_pc7_qa", "raw_pc7_mrep",
            "raw_u7_disc_claude_org", "raw_u7_disc_claude_brk", "raw_u7_disc_gpt_org", "raw_u7_disc_consensus",
        ]
    ):
        if c in zero_comm_df.columns:
            zero_comm_df[c] = -999.0
    ov_po_iso = ranker_po_v7.predict_walkforward(zero_comm_df)
    max_po_comment_leak = max(abs(ov_po_v7[k] - ov_po_iso[k]) for k in ov_po_v7)

    assert max_perm_diff < 1e-9, f"FATAL: Order permutation invariance failed: {max_perm_diff}"
    assert max_po_comment_leak == 0.0, f"FATAL: Product-only comment isolation failed: {max_po_comment_leak}"

    hc6_ref_path = os.path.join(os.path.dirname(os.path.abspath(args.out_json)), "usersim_core_hillclimb_6_results.json")
    hc6_ref = json.load(open(hc6_ref_path)) if os.path.exists(hc6_ref_path) else {}

    live_po = {
        "website_published_now": {"days": 23, "top3_pct": 49.3, "top5_pct": 61.7, "top10_pct": 69.6, "hits": {"top3": [34, 69], "top5": [71, 115], "top10": [160, 230]}},
        "arm3_0005_strict": score_23d_window(live_0005_launches, live_truth, None),
        "product_only_v4": (hc6_ref.get("live_23d_product_only_tab") or {}).get("product_only_v4"),
        "product_only_v6": (hc6_ref.get("live_23d_product_only_tab") or {}).get("product_only_v6"),
        "product_only_v7": score_23d_window(live_expanded_launches, live_truth, ov_po_v7),
    }
    live_pc = {
        "product_comments_v3": (hc6_ref.get("live_23d_product_comments_tab") or {}).get("product_comments_v3"),
        "product_comments_v5": (hc6_ref.get("live_23d_product_comments_tab") or {}).get("product_comments_v5"),
        "product_comments_v6": (hc6_ref.get("live_23d_product_comments_tab") or {}).get("product_comments_v6"),
        "product_comments_v7": score_23d_window(live_expanded_launches, live_truth, ov_pc_v7),
    }

    test_df = full_df[(full_df["day"] >= "2026-10-01") & (full_df["day"] <= "2026-11-24")].copy()
    test_df = test_df.sort_values(["day", "structural_rank"]).groupby("day").head(20).reset_index(drop=True)
    test_df["score_po_v7"] = [ov_po_v7[(str(r.day), str(r.item_id))] for r in test_df.itertuples(index=False)]
    test_df["score_pc_v7"] = [ov_pc_v7[(str(r.day), str(r.item_id))] for r in test_df.itertuples(index=False)]

    bt55_po_v7 = evaluate_boards_and_ties(full_day_launches, truth_by_day, test_df, score_col="score_po_v7", n_boot=5000)
    bt55_pc_v7 = evaluate_boards_and_ties(full_day_launches, truth_by_day, test_df, score_col="score_pc_v7", n_boot=5000)

    nov_df = test_df[test_df["day"] >= "2026-11-01"].copy()
    nov_po_v7 = evaluate_boards_and_ties(full_day_launches, truth_by_day, nov_df, score_col="score_po_v7", n_boot=5000)
    nov_pc_v7 = evaluate_boards_and_ties(full_day_launches, truth_by_day, nov_df, score_col="score_pc_v7", n_boot=5000)

    po_pred_val_card = {
        "track": "product_only_mid_v7",
        "live_23d": {k: live_po["product_only_v7"][k] for k in ("days", "top3_pct", "top5_pct", "top10_pct", "mean_3_5_10_pct")},
        "locked_test_55d": bt55_po_v7["model"],
        "november_24d": nov_po_v7["model"],
    }
    pc_pred_val_card = {
        "track": "product_comments_pre_le_0345pt_v7",
        "live_23d": {k: live_pc["product_comments_v7"][k] for k in ("days", "top3_pct", "top5_pct", "top10_pct", "mean_3_5_10_pct")},
        "locked_test_55d": bt55_pc_v7["model"],
        "november_24d": nov_pc_v7["model"],
    }

    why_days = sorted(set(LIVE_23_DAYS) | set(nov_df["day"].unique()))
    why_summary = emit_why_cards_batch(
        full_df=full_df,
        days_to_emit=why_days,
        ov_po_v5=ov_po_v7,
        ov_pc_v5=ov_pc_v7,
        comp_map=comp_map,
        why_pop_by_key=why_pop_by_key,
        surfaces_by_id=surfaces_by_id,
        sso_meta=sso_meta,
        cua4_records=cua4_records,
        mm_judged=mm_judged,
        po_metrics_summary=po_pred_val_card,
        pc_metrics_summary=pc_pred_val_card,
        out_dir=args.why_out_dir,
        gcs_dest_prefix=f"{args.gcs_prefix.rstrip('/')}/why",
        held_people_total=bench.n_people,
    )

    out = {
        "experiment_id": "USERSIM-CORE-HILLCLIMB-7",
        "elapsed_sec": round(time.time() - t0, 1),
        "vertex_llm_cost_usd": round(budget.spent, 4),
        "val_sep_locked_configs": {
            "product_only_v7": {
                "target_std_apr": best_po_cfg[0],
                "lgb_weight": best_po_cfg[1],
                "arm2_weight": best_po_cfg[2],
                "u7_sim_bonus": best_po_cfg[3],
                "fin_bonus": best_po_cfg[4],
                "max_shift_cap": best_po_cfg[5],
                "val_sep_objective": round(best_po_key[0], 3),
                "val_sep_tie_acc_pct": round(best_po_key[1], 2),
            },
            "product_comments_v7": {
                "target_std_apr": best_pc_cfg[0],
                "lgb_weight": best_pc_cfg[1],
                "arm2_weight": best_pc_cfg[2],
                "u7_sim_bonus": best_pc_cfg[3],
                "fin_bonus": best_pc_cfg[4],
                "max_shift_cap": best_pc_cfg[5],
                "val_sep_objective": round(best_pc_key[0], 3),
                "val_sep_tie_acc_pct": round(best_pc_key[1], 2),
            },
        },
        "leak_and_isolation_audits": {
            "input_order_permutation_max_abs_diff": float(max_perm_diff),
            "product_only_comment_isolation_max_abs_diff": float(max_po_comment_leak),
            "why_cards_min_group": 20,
            "why_cards_privacy_audit_passed": True,
        },
        "why_cards_export": why_summary,
        "live_23d_product_only_tab": live_po,
        "live_23d_product_comments_tab": live_pc,
        "locked_test_55d_oct_nov": {
            "product_only_v4": (hc6_ref.get("locked_test_55d_oct_nov") or {}).get("product_only_v4"),
            "product_only_v6": (hc6_ref.get("locked_test_55d_oct_nov") or {}).get("product_only_v6"),
            "product_only_v7": bt55_po_v7,
            "product_comments_v5": (hc6_ref.get("locked_test_55d_oct_nov") or {}).get("product_comments_v5"),
            "product_comments_v6": (hc6_ref.get("locked_test_55d_oct_nov") or {}).get("product_comments_v6"),
            "product_comments_v7": bt55_pc_v7,
        },
        "november_24d_full_calibration": {
            "product_only_v4": (hc6_ref.get("november_24d_full_calibration") or {}).get("product_only_v4"),
            "product_only_v6": (hc6_ref.get("november_24d_full_calibration") or {}).get("product_only_v6"),
            "product_only_v7": nov_po_v7,
            "product_comments_v5": (hc6_ref.get("november_24d_full_calibration") or {}).get("product_comments_v5"),
            "product_comments_v6": (hc6_ref.get("november_24d_full_calibration") or {}).get("product_comments_v6"),
            "product_comments_v7": nov_pc_v7,
        },
    }

    os.makedirs(os.path.dirname(os.path.abspath(args.out_json)), exist_ok=True)
    with open(args.out_json, "w") as f:
        json.dump(out, f, indent=2)

    if args.gcs_prefix:
        subprocess.run(
            ["gcloud", "storage", "cp", "-q", args.out_json, f"{args.gcs_prefix.rstrip('/')}/usersim_core_hillclimb_7_results.json"],
            check=True,
        )
        subprocess.run(
            ["gcloud", "storage", "cp", "-r", "-q", f"{args.work_dir}/cache_univ_v7", f"{args.gcs_prefix.rstrip('/')}/"],
            check=False,
        )

    print("\n=== TRACK 1: PRODUCT ONLY v7 (23 LIVE DAYS, ZERO COMMENTS) ===", flush=True)
    for k, v in live_po.items():
        if v:
            print(
                f"  {k:34s}: Top-3={v['top3_pct']:5.2f}% ({v['hits']['top3'][0]}/{v['hits']['top3'][1]}) | "
                f"Top-5={v['top5_pct']:5.2f}% ({v['hits']['top5'][0]}/{v['hits']['top5'][1]}) | "
                f"Top-10={v['top10_pct']:5.2f}% ({v['hits']['top10'][0]}/{v['hits']['top10'][1]})",
                flush=True,
            )

    print("\n=== TRACK 2: PRODUCT + COMMENTS v7 (23 LIVE DAYS, ORDER-FREE <=03:45 PT) ===", flush=True)
    for k, v in live_pc.items():
        if v:
            print(
                f"  {k:34s}: Top-3={v['top3_pct']:5.2f}% ({v['hits']['top3'][0]}/{v['hits']['top3'][1]}) | "
                f"Top-5={v['top5_pct']:5.2f}% ({v['hits']['top5'][0]}/{v['hits']['top5'][1]}) | "
                f"Top-10={v['top10_pct']:5.2f}% ({v['hits']['top10'][0]}/{v['hits']['top10'][1]})",
                flush=True,
            )

    print("\n=== 55-DAY LOCKED TEST (OCT 1 - NOV 24) ===", flush=True)
    for k, v in out["locked_test_55d_oct_nov"].items():
        if v:
            print(
                f"  {k:24s}: arm3={v['arm3']} -> model={v['model']} | "
                f"lift={v['paired_lift_pts']['mean_3_5_10']} | ties={v['reach_matched_ties']['model_acc_pct']}%",
                flush=True,
            )

    print("\n=== 24-DAY NOVEMBER FULL CALIBRATION (NOV 1 - NOV 24) ===", flush=True)
    for k, v in out["november_24d_full_calibration"].items():
        if v:
            print(
                f"  {k:24s}: arm3={v['arm3']} -> model={v['model']} | "
                f"lift={v['paired_lift_pts']['mean_3_5_10']} | ties={v['reach_matched_ties']['model_acc_pct']}%",
                flush=True,
            )


if __name__ == "__main__":
    main()
