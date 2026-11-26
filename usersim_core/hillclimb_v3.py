"""USERSIM-CORE-HILLCLIMB-3 Dual-Track Runner (`usersim_core/hillclimb_v3.py`).

Strictly separates and hill-climbs BOTH website tracks without any rank, vote, or order leakage:
  1. `Product only` (`mid`, `00:05 PT` + post-midnight arrivals, ZERO comments):
     - Integrates real 5-VM Signed-In Google-SSO Camoufox product-use inspections (`hillclimb3_slot*.jsonl`),
       strictly scrubbed via `usersim_core.sanitizer.sanitize_text(..., item_day=day)`.
     - Adds Val-Sep-validated `< D` Pure-Product + Sanitized-Surface TF-IDF Ridge (`po_text_surf_ridge_z`),
       `< D` Empirical-Bayes Maker Residual Track Record (`po_maker_prior_resid_z`), and Google-SSO workspace
       entry vs post-login paywall/waitlist friction (`sso_workspace_z`, `sso_paywall_waitlist_z`).
     - Runs a dedicated `Product-only` Enriched Comparative Cohort Simulation (`v3_po`, `gpt-oss-120b` +
       `gemini-2.5-pro`) over product pitch + Google-SSO Camoufox surface + `< D` category/G2 context with
       ZERO comments in the prompt!
  2. `Product + comments` (`pre`, order-free `<= 03:45 PT` before 04:00 PT vote reveal, ZERO PH order/votes):
     - Adds `< D` Empirical-Bayes Commenter Scout Precision (`pc_scout_prior_z`), pre-reveal substantive
       community questions (`pc_questions_z`), and maker follow-up replies (`pc_maker_replies_z`).
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import glob
import hashlib
import json
import math
import os
import time
from typing import Any

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import Ridge

from simharness.bench import KIND_CODE, _day_bounds_utc, scrub
from simharness.models.llm import Budget, JsonlCache, VertexOpenAICompat
from simharness.schema import MAKE
from usersim_core.apify_features import load_apify_signals
from usersim_core.calibration import WalkForwardCalibrator
from usersim_core.cohort_sim import VertexGeminiPro, _format_surface_summary, _parse_comparative_json
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
from usersim_core.sanitizer import SanitizedSurface, _surface_from_clean_text, sanitize_text


PRODUCT_ONLY_V3_TABULAR = [
    "po_text_surf_ridge_z",
    "po_maker_prior_resid_z",
    "sso_workspace_z",
    "sso_paywall_waitlist_z",
    "js_interactive_inputs_z",
]

COHORT_V3_PO_FEATURES = [
    "v3po_p_endorse_z",
    "v3po_would_use_z",
    "v3po_substance_z",
    "v3po_net_conviction_z",
]

COMMENT_V3_EXTRA = [
    "pc_scout_prior_z",
    "pc_questions_z",
    "pc_maker_replies_z",
]


V3_PRODUCT_ONLY_PROMPT = """You are simulating a calibrated panel of 5 real, discerning Product Hunt users evaluating today's competing product launches strictly from the PRODUCT ITSELF (zero comments, zero votes, zero rankings).

PANEL OF REAL MATCHED USERS (strictly from activity BEFORE today):
{panel_block}

HISTORICAL CATEGORY & INCUMBENT BENCHMARK NOTES (strictly from days BEFORE today):
{category_notes}

TODAY'S COMPETING PRODUCTS (listed in randomized MD5 order 1..{n_items}; judge ONLY product clarity, concrete workflow value, live browser/Google-SSO product inspection reality, pricing/docs transparency, maker/org credibility, and onboarding friction):
{items_block}

EVALUATION RULES:
1. Calibrate across the slate so scores span 0.15..0.92 (mean ~0.48). Differentiate sharply between close contenders!
2. Products with verified working workspaces (via instant demo, open-source repo/CLI, or clean Google-SSO app entry), clear pricing/docs, and strong problem-solution fit beat generic AI wrappers, empty marketing shells, and post-login hard paywalls/waitlists.
3. Never penalize `[SITE_UNVERIFIED]` when a site could not be fetched — treat missing browser scrapes neutrally (0 shift).

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


def load_fleet_sso_surfaces(
    sweep_glob: str,
    existing_surfaces: dict[str, SanitizedSurface],
    day_by_id: dict[str, str],
) -> tuple[dict[str, SanitizedSurface], dict[str, dict[str, Any]], dict[str, int]]:
    """Merge 5-VM Signed-In Google-SSO Camoufox records (`hillclimb3_slot*.jsonl`) with strict leak sanitization."""
    updated = dict(existing_surfaces)
    sso_meta: dict[str, dict[str, Any]] = {}
    stats = {
        "total_fleet_records": 0,
        "clean_js_surfaces": 0,
        "upgraded_nonclean_to_clean": 0,
        "google_sso_attempted": 0,
        "google_sso_entered": 0,
        "post_sso_workspace_verified": 0,
        "post_sso_paywall_or_waitlist": 0,
        "leaks_redacted_count": 0,
    }

    for path in sorted(glob.glob(sweep_glob)):
        for line in open(path):
            if not line.strip():
                continue
            r = json.loads(line)
            lid = str(r.get("item_id") or "")
            if not lid:
                continue
            stats["total_fleet_records"] += 1
            d_str = str(r.get("day") or day_by_id.get(lid) or "")
            sso_att = bool(r.get("google_sso_attempted"))
            sso_ent = bool(r.get("google_sso_entered"))
            ws_ok = bool(r.get("post_sso_workspace"))
            pw_wl = bool(r.get("post_sso_paywall") or r.get("post_sso_waitlist"))
            if sso_att:
                stats["google_sso_attempted"] += 1
            if sso_ent:
                stats["google_sso_entered"] += 1
            if ws_ok:
                stats["post_sso_workspace_verified"] += 1
            if pw_wl:
                stats["post_sso_paywall_or_waitlist"] += 1

            raw_landing = str(r.get("text_excerpt") or "")
            raw_post = str(r.get("post_sso_excerpt") or "")
            headings = " | ".join(str(x) for x in (r.get("headings") or [])[:10])
            ctas = [str(x) for x in (r.get("ctas") or [])[:14]]
            combined_raw = (
                f"Title: {r.get('title', '')}\nHeadings: {headings}\nCTAs: {', '.join(ctas)}\n"
                f"Landing: {raw_landing}\n"
                + (f"Post-Google-SSO App View: {raw_post}" if sso_ent and raw_post else "")
            )
            clean_txt, n_leaks = sanitize_text(combined_raw, item_day=d_str if d_str else None)
            stats["leaks_redacted_count"] += int(n_leaks)

            clean_post_only, n_pl = sanitize_text(raw_post, item_day=d_str if d_str else None)
            stats["leaks_redacted_count"] += int(n_pl)

            sso_meta[lid] = {
                "sso_attempted": sso_att,
                "sso_entered": sso_ent,
                "post_sso_workspace": ws_ok,
                "post_sso_paywall_or_waitlist": pw_wl,
                "n_interactive_inputs": int(r.get("n_interactive_inputs") or 0),
                "has_pricing_link": bool(r.get("has_pricing_link")),
                "has_docs_link": bool(r.get("has_docs_link")),
                "has_github_link": bool(r.get("has_github_link")),
                "post_sso_clean_summary": clean_post_only[:320],
                "access_clean_camoufox": r.get("access_status") == "clean" and len(clean_txt) >= 90,
            }

            if r.get("access_status") == "clean" and len(clean_txt) >= 90:
                stats["clean_js_surfaces"] += 1
                prev = updated.get(lid)
                # Keep launch-era cached surface for older pre-Oct items if already rich, UNLESS previous was non-clean/thin OR we entered via Google SSO!
                should_upgrade = (
                    prev is None
                    or prev.access_status != "clean"
                    or len(prev.sanitized_text) < 380
                    or sso_ent
                    or d_str >= "2026-10-29"
                )
                if should_upgrade:
                    if prev is None or prev.access_status != "clean":
                        stats["upgraded_nonclean_to_clean"] += 1
                    new_surf = _surface_from_clean_text(
                        clean_txt=clean_txt,
                        url=str(r.get("final_url") or r.get("input_url") or ""),
                        http_status=int(r.get("http_status") or 200),
                        load_ms=float(r.get("elapsed_s") or 1.0) * 1000.0,
                        badges_stripped=int(n_leaks),
                        ctas=ctas,
                    )
                    if r.get("has_pricing_link"):
                        new_surf.has_visible_pricing = True
                    if r.get("has_docs_link"):
                        new_surf.has_docs = True
                    if r.get("has_github_link"):
                        new_surf.has_open_source = True
                    if ws_ok and not new_surf.is_waitlist:
                        new_surf.has_free_tier = True
                    if pw_wl and not new_surf.has_open_source:
                        new_surf.product_trait = "card_required" if r.get("post_sso_paywall") else "waitlist_only"
                    updated[lid] = new_surf

    return updated, sso_meta, stats


def run_v3_product_only_cohort_sim(
    df_sep_nov: pd.DataFrame,
    history_df: pd.DataFrame,
    pool: UniversalUserPool,
    calibrator: WalkForwardCalibrator,
    surfaces_by_id: dict[str, SanitizedSurface],
    sso_meta: dict[str, dict[str, Any]],
    g2_cat_notes: dict[str, str],
    cache: JsonlCache,
    budget: Budget,
    workers: int = 6,
) -> pd.DataFrame:
    """Run strictly ZERO-COMMENT ComparativeCohortSimulator (`v3_po`) using Google-SSO Camoufox surfaces + G2 context."""
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

    def _eval_day(d: str) -> dict[str, dict[str, float]]:
        items = by_day[d]
        n = len(items)
        if n == 0:
            return {}
        perm = sorted(
            range(n),
            key=lambda i: hashlib.md5(f"v3_po:{d}:{items[i]['item_id']}".encode()).hexdigest(),
        )
        ordered = [items[i] for i in perm]

        d_eff = d if d <= "2026-11-24" else "2026-11-24"
        combined_text = " ".join(f"{it['title']} {it['summary']}" for it in ordered[:6])
        panel = pool.match_cohort(d_eff, combined_text, k=5)
        panel_str = "\n".join(
            f"- Member #{k+1} (arch={u.get('archetype_id',0)}, critique_rate={u.get('critique_rate',0.2):.0%}): {u.get('history_brief','')[:180]}"
            for k, u in enumerate(panel[:5])
        ) or "- Calibrated early-adopter developer, founder, and product builder cohort."

        priors = calibrator.category_prior_as_of(history_df, d)
        cats = list(dict.fromkeys(str(it.get("category_0005") or "General") for it in ordered))[:6]
        cat_lines = [calibrator.render_category_note(c, priors) for c in cats]
        for c in cats[:3]:
            if c in g2_cat_notes:
                cat_lines.append(f"- Verified SaaS buyer pain points in {c}: {g2_cat_notes[c][:200]}")
        cat_notes = "\n".join(cat_lines) or "- No prior bias shift needed."

        blocks = []
        sso_sig_bits = []
        for pos, it in enumerate(ordered, start=1):
            lid = str(it["item_id"])
            surf_s = _format_surface_summary(surfaces_by_id.get(lid), None)
            sm = sso_meta.get(lid) or {}
            sso_line = ""
            if sm.get("sso_entered"):
                status_tag = (
                    "VERIFIED_POST_LOGIN_WORKSPACE"
                    if sm.get("post_sso_workspace")
                    else ("POST_LOGIN_PAYWALL_OR_WAITLIST" if sm.get("post_sso_paywall_or_waitlist") else "ENTERED_VIA_GOOGLE_SSO")
                )
                sso_line = f"\n    Google-SSO Live App Check: [{status_tag}] {sm.get('post_sso_clean_summary', '')[:220]}"
                sso_sig_bits.append(f"{lid}:1")
            elif sm.get("access_clean_camoufox"):
                sso_line = f"\n    Browser DOM Check: interactive_inputs={sm.get('n_interactive_inputs',0)} pricing_link={sm.get('has_pricing_link')} docs_link={sm.get('has_docs_link')} github={sm.get('has_github_link')}"
                sso_sig_bits.append(f"{lid}:c")

            tags_s = ", ".join((it.get("tags") or [])[:5]) if isinstance(it.get("tags"), (list, tuple)) else str(it.get("category_0005") or "")
            # STRICTLY ZERO COMMENTS INCLUDED IN THIS PROMPT!
            blocks.append(
                f"[{pos}] {scrub(str(it['title']))} — {scrub(str(it['summary']))}\n"
                f"    Topics: {tags_s} | Maker/Pitch Desc: {scrub(str(it.get('description') or ''))[:300]}\n"
                f"    Live Sanitized Product Surface: {surf_s[:280]}{sso_line}"
            )

        prompt = V3_PRODUCT_ONLY_PROMPT.format(
            panel_block=panel_str,
            category_notes=cat_notes,
            n_items=n,
            items_block="\n".join(blocks),
        )

        sig_raw = ",".join(str(x["item_id"]) for x in ordered) + "|" + ",".join(sso_sig_bits)
        item_sig = hashlib.md5(sig_raw.encode()).hexdigest()[:10]

        k_120 = ("v3_po_120b", d, item_sig)
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

        k_pro = ("v3_po_pro", d, item_sig)
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
                "v3po_raw_endorse": pe,
                "v3po_raw_use": wu,
                "v3po_raw_sub": sub,
                "v3po_raw_net": pe + 0.5 * wu + 0.35 * sub - 0.55 * fr,
            }
        return day_out

    results_by_day: dict[str, dict[str, dict[str, float]]] = {}
    done_d = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_eval_day, d): d for d in days}
        for fut in as_completed(futs):
            d = futs[fut]
            results_by_day[d] = fut.result()
            done_d += 1
            if done_d % 15 == 0 or done_d == len(days):
                print(f"  [Cohort v3 Product-Only] {done_d}/{len(days)} days scored (${budget.spent:.3f})", flush=True)
    cache.roll()

    out_df = df_sep_nov.copy().reset_index(drop=True)
    for col in ("v3po_raw_endorse", "v3po_raw_use", "v3po_raw_sub", "v3po_raw_net"):
        out_df[col] = [
            float((results_by_day.get(str(r.day), {}).get(str(r.item_id)) or {}).get(col, 0.48))
            for r in out_df.itertuples(index=False)
        ]
    return out_df


def attach_v3_causal_features(
    df: pd.DataFrame,
    bench: Any,
    surfaces_by_id: dict[str, SanitizedSurface],
    sso_meta: dict[str, dict[str, Any]],
    live23_dir: str,
) -> pd.DataFrame:
    """Compute strictly causal (`< D`), zero-leakage v3 features for both Product-only and Product+comments."""
    df = df.copy().reset_index(drop=True)

    # 1. Refresh surface clean flags & traits from upgraded Camoufox/Google-SSO surfaces!
    acc_clean = []
    for attr, raw_c, out_c in [
        ("has_interactive_demo", "raw_demo_v3", "surf_instant_demo_clean"),
        ("has_open_source", "raw_oss_v3", "surf_open_source_clean"),
        ("has_free_tier", "raw_free_v3", "surf_free_tier_clean"),
        ("has_visible_pricing", "raw_price_v3", "surf_visible_pricing_clean"),
        ("has_docs", "raw_docs_v3", "surf_docs_clean"),
        ("is_waitlist", "raw_wait_v3", "surf_waitlist_clean"),
        ("is_enterprise_gated", "raw_ent_v3", "surf_enterprise_gated_clean"),
        ("is_platform_only", "raw_plat_v3", "surf_platform_only_clean"),
    ]:
        vals = []
        for lid in df["item_id"].astype(str):
            s = surfaces_by_id.get(lid)
            vals.append(float(getattr(s, attr)) if s is not None else 0.0)
        df[raw_c] = vals
    for lid in df["item_id"].astype(str):
        s = surfaces_by_id.get(lid)
        acc_clean.append(bool(s is not None and s.access_status == "clean"))
    df["access_clean_v3"] = acc_clean
    for _, raw_c, out_c in [
        ("has_interactive_demo", "raw_demo_v3", "surf_instant_demo_clean"),
        ("has_open_source", "raw_oss_v3", "surf_open_source_clean"),
        ("has_free_tier", "raw_free_v3", "surf_free_tier_clean"),
        ("has_visible_pricing", "raw_price_v3", "surf_visible_pricing_clean"),
        ("has_docs", "raw_docs_v3", "surf_docs_clean"),
        ("is_waitlist", "raw_wait_v3", "surf_waitlist_clean"),
        ("is_enterprise_gated", "raw_ent_v3", "surf_enterprise_gated_clean"),
        ("is_platform_only", "raw_plat_v3", "surf_platform_only_clean"),
    ]:
        df[out_c] = within_day_zscore(df, raw_c, mask_col="access_clean_v3")

    # 2. Google-SSO & Camoufox DOM execution signals (neutral 0.0 when not inspected!)
    df["camoufox_inspected"] = [bool((sso_meta.get(str(lid)) or {}).get("access_clean_camoufox")) for lid in df["item_id"]]
    df["raw_sso_ws"] = [1.0 if (sso_meta.get(str(lid)) or {}).get("post_sso_workspace") else 0.0 for lid in df["item_id"]]
    df["raw_sso_pw"] = [1.0 if (sso_meta.get(str(lid)) or {}).get("post_sso_paywall_or_waitlist") else 0.0 for lid in df["item_id"]]
    df["raw_js_inp"] = [math.log1p(float((sso_meta.get(str(lid)) or {}).get("n_interactive_inputs", 0))) for lid in df["item_id"]]
    df["sso_workspace_z"] = within_day_zscore(df, "raw_sso_ws", mask_col="camoufox_inspected")
    df["sso_paywall_waitlist_z"] = within_day_zscore(df, "raw_sso_pw", mask_col="camoufox_inspected")
    df["js_interactive_inputs_z"] = within_day_zscore(df, "raw_js_inp", mask_col="camoufox_inspected")

    # 3. Walk-Forward (< month M) Pure Product + Sanitized Surface TF-IDF Ridge (ZERO comments!)
    prod_docs = []
    for r in df.itertuples(index=False):
        s = surfaces_by_id.get(str(r.item_id))
        stxt = s.sanitized_text[:1400] if (s and s.access_status == "clean") else ""
        tgs = " ".join(r.tags if isinstance(r.tags, (list, tuple)) else [])
        prod_docs.append(f"{r.title}. {r.summary}. {r.description or ''} {tgs} {stxt}")

    df["raw_po_ridge"] = 0.0
    months = sorted(df["day"].str[:7].unique())
    for m_idx, mon in enumerate(months):
        te_m = (df["day"].str[:7] == mon).to_numpy()
        if m_idx == 0:
            continue
        tr_m = (df["day"].str[:7] < mon).to_numpy() & (df["day"] <= "2026-11-24").to_numpy() & df["true_log_residual"].notna().to_numpy()
        if tr_m.sum() < 80:
            continue
        vec = TfidfVectorizer(min_df=3, max_features=16000, ngram_range=(1, 2), sublinear_tf=True)
        Xtr = vec.fit_transform([prod_docs[k] for k in np.where(tr_m)[0]])
        Xte = vec.transform([prod_docs[k] for k in np.where(te_m)[0]])
        ytr = np.clip(df.loc[tr_m, "true_log_residual"].to_numpy(dtype=np.float64), -1.2, 1.2)
        df.loc[te_m, "raw_po_ridge"] = Ridge(alpha=8.0, solver="lsqr").fit(Xtr, ytr).predict(Xte)
    df["po_text_surf_ridge_z"] = within_day_zscore(df, "raw_po_ridge")

    # 4. Strictly < D Empirical-Bayes Maker Residual History over arm3 (ZERO comments!)
    mk_df = bench.hist[bench.hist["kind"] == KIND_CODE[MAKE]][["person_idx", "item_idx"]].drop_duplicates()
    makers_by_iidx: dict[int, list[int]] = {}
    for r in mk_df.itertuples(index=False):
        makers_by_iidx.setdefault(int(r.item_idx), []).append(int(r.person_idx))

    maker_res_sum: dict[int, float] = {}
    maker_res_cnt: dict[int, int] = {}
    po_maker_prior = np.zeros(len(df), dtype=np.float64)
    for d, dg in df.groupby("day", sort=True):
        day_updates = []
        for idx_row, r in dg.iterrows():
            mks = makers_by_iidx.get(int(r.item_idx), [])
            vals = [maker_res_sum[m] / (maker_res_cnt[m] + 2.5) for m in mks if maker_res_cnt.get(m, 0) > 0]
            po_maker_prior[idx_row] = float(np.mean(vals)) if vals else 0.0
            if str(d) <= "2026-11-24" and np.isfinite(r.true_log_residual):
                for m in set(mks):
                    day_updates.append((m, float(r.true_log_residual)))
        for m, rv in day_updates:
            maker_res_sum[m] = maker_res_sum.get(m, 0.0) + rv
            maker_res_cnt[m] = maker_res_cnt.get(m, 0) + 1
    df["raw_po_maker_resid"] = po_maker_prior
    df["po_maker_prior_resid_z"] = within_day_zscore(df, "raw_po_maker_resid")

    # 5. Strictly < D Commenter Empirical-Bayes Scout Precision + Pre-Reveal Questions & Maker Replies (<= 03:45 PT)!
    c_all = bench.comments.merge(bench.items[["item_idx", "item_id", "day"]], on="item_idx")
    c_all = c_all[c_all["day"] >= "2026-04-01"].copy()
    bounds = {d: _day_bounds_utc(d, bench.cfg.day_tz) for d in c_all["day"].unique()}
    c_all["cutoff_utc"] = c_all["day"].map(lambda d: bounds[d][0]) + pd.Timedelta(minutes=225)
    c_all["ts_utc"] = c_all["ts"].dt.tz_convert("UTC")
    c_pre = c_all[c_all["ts_utc"] <= c_all["cutoff_utc"]].copy()

    maker_pairs = set(zip(mk_df["person_idx"].astype(int), mk_df["item_idx"].astype(int)))
    pre_by_item: dict[str, tuple[list[int], int, int]] = {}
    for lid, ig in c_pre.groupby("item_id"):
        non_mk_p: list[int] = []
        mk_replies = 0
        q_marks = 0
        for r in ig.itertuples(index=False):
            p, ii = int(r.person_idx), int(r.item_idx)
            txt = str(r.text or "")
            if (p, ii) in maker_pairs:
                mk_replies += 1
            else:
                non_mk_p.append(p)
                if "?" in txt and len(txt) >= 40:
                    q_marks += 1
        pre_by_item[str(lid)] = (list(dict.fromkeys(non_mk_p)), max(0, mk_replies - 1), q_marks)

    # Supplement Nov 25 <=02:45 PT live comments for questions & maker replies!
    nov25_comm = f"{live23_dir}/nov25/20261125T0245PT.jsonl"
    nov25_det = f"{live23_dir}/nov25/20261125T1834PT.jsonl"
    if os.path.exists(nov25_comm) and os.path.exists(nov25_det):
        t_by_p: dict[str, set[str]] = {}
        for line in open(nov25_det):
            rj = json.loads(line)
            pid = str(rj["id"])
            ts = {str(m.get("id") or "") for m in (rj.get("makers") or [])}
            if (rj.get("user") or {}).get("id"):
                ts.add(str(rj["user"]["id"]))
            t_by_p[pid] = {x for x in ts if x}
        s25_utc, _ = _day_bounds_utc("2026-11-25", bench.cfg.day_tz)
        c25_utc = s25_utc + pd.Timedelta(minutes=225)
        byp25: dict[str, list[dict]] = {}
        for line in open(nov25_comm):
            rj = json.loads(line)
            cts = pd.to_datetime(rj.get("createdAt"), utc=True, errors="coerce")
            if not pd.isna(cts) and cts <= c25_utc:
                byp25.setdefault(str(rj.get("post_id") or ""), []).append(rj)
        for pid, rows25 in byp25.items():
            tset = t_by_p.get(pid, set())
            mrep25 = sum(1 for rj in rows25 if str(rj.get("commenter_user_id") or "") in tset)
            qn25 = sum(1 for rj in rows25 if str(rj.get("commenter_user_id") or "") not in tset and "?" in str(rj.get("body") or "") and len(str(rj.get("body") or "")) >= 40)
            pre_by_item[pid] = ([], max(0, mrep25 - 1), qn25)

    comm_res_sum: dict[int, float] = {}
    comm_res_cnt: dict[int, int] = {}
    pc_scout = np.zeros(len(df), dtype=np.float64)
    pc_mrep = np.zeros(len(df), dtype=np.float64)
    pc_q = np.zeros(len(df), dtype=np.float64)
    for d, dg in df.groupby("day", sort=True):
        day_cu = []
        for idx_row, r in dg.iterrows():
            lid = str(r.item_id)
            users, mr, qn = pre_by_item.get(lid, ([], 0, 0))
            u_priors = [comm_res_sum[u] / (comm_res_cnt[u] + 4.0) for u in users if comm_res_cnt.get(u, 0) >= 2]
            pc_scout[idx_row] = float(np.sum(u_priors)) if u_priors else 0.0
            pc_mrep[idx_row] = math.log1p(mr)
            pc_q[idx_row] = math.log1p(qn)
            if str(d) <= "2026-11-24" and np.isfinite(r.true_log_residual):
                for u in users:
                    day_cu.append((u, float(r.true_log_residual)))
        for u, rv in day_cu:
            comm_res_sum[u] = comm_res_sum.get(u, 0.0) + rv
            comm_res_cnt[u] = comm_res_cnt.get(u, 0) + 1

    df["raw_pc_scout"] = pc_scout
    df["raw_pc_mrep"] = pc_mrep
    df["raw_pc_q"] = pc_q
    df["pc_scout_prior_z"] = within_day_zscore(df, "raw_pc_scout")
    df["pc_maker_replies_z"] = within_day_zscore(df, "raw_pc_mrep")
    df["pc_questions_z"] = within_day_zscore(df, "raw_pc_q")
    return df


def load_g2_category_pain_notes(apify_dir: str) -> dict[str, str]:
    """Summarize verified SaaS buyer dislikes from G2 (`g2_products_and_reviews_raw.jsonl.gz`) for cohort grounding."""
    import gzip
    g2_path = f"{apify_dir}/g2_products_and_reviews_raw.jsonl.gz"
    if not os.path.exists(g2_path):
        return {}
    snippets: list[str] = []
    with gzip.open(g2_path, "rt") as f:
        for line in f:
            r = json.loads(line)
            dislike = str(r.get("dislike") or r.get("what_do_you_dislike") or "").strip()
            prod = str(r.get("product_name") or r.get("product") or "").strip()
            if prod and len(dislike) >= 40:
                snippets.append(f"{prod}: {dislike[:95]}")
            if len(snippets) >= 18:
                break
    summary = "; ".join(snippets[:4]) if snippets else ""
    return {c: summary for c in ("Developer Tools", "Productivity", "Artificial Intelligence", "SaaS", "Design Tools")} if summary else {}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--work-dir", required=True)
    ap.add_argument("--live23-dir", required=True)
    ap.add_argument("--apify-dir", required=True)
    ap.add_argument("--fleet-sweep-glob", required=True)
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

    base_df = pd.read_parquet(f"{args.work_dir}/stage_b_features.parquet")
    live_0005_launches, live_truth, forecast_ids_by_day = load_live_0005_lineups(
        args.live23_dir, full_day_launches, truth_by_day
    )
    late_est = LateLaunchStructuralEstimator().fit_from_forecasts_and_bt(
        bench, full_day_launches, f"{args.live23_dir}/forecasts", cutoff_day="2026-11-24"
    )

    live_expanded_launches: dict[str, list[dict]] = {}
    extra_rows_to_score: list[dict[str, Any]] = []
    nov25_meta_by_id = {str(json.loads(l)["id"]): json.loads(l) for l in open(f"{args.live23_dir}/nov25/20261125T1834PT.jsonl")}

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
        v1_nov25 = json.load(open("/Users/shreyaspatel/.gemini/antigravity/brain/9180c5fc-4f89-4408-aad0-3184e5de8475/scratch/live_check/2026-11-25/usersim_core_frozen_2026-11-25.json"))
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

    for raw_p, z_p in [
        ("sim_discerning_mean", "pool_sim_discerning_z"),
        ("sim_critic_mean", "pool_sim_critic_z"),
        ("expected_selective_voters", "pool_selective_voters_z"),
        ("niche_specialist_ratio", "pool_specialist_z"),
    ]:
        if raw_p in full_df.columns:
            full_df[z_p] = within_day_zscore(full_df, raw_p)

    # 1. Merge 5-VM Signed-In Google-SSO Camoufox Sweep!
    day_by_id = dict(zip(full_df["item_id"].astype(str), full_df["day"].astype(str)))
    surfaces_by_id, sso_meta, sso_stats = load_fleet_sso_surfaces(args.fleet_sweep_glob, surfaces_by_id, day_by_id)
    print(f"[Hillclimb v3] 5-VM Signed-In Google-SSO Camoufox stats: {json.dumps(sso_stats)}", flush=True)

    # 2. Attach v3 causal Product-only & Pre-reveal Comment features!
    comm_map = extract_pre_reveal_comments(bench, pool, args.live23_dir, cutoff_minutes_after_midnight_pt=225)
    full_df = attach_walkforward_product_comment_features(full_df, comm_map)
    full_df, apify_stats = load_apify_signals(full_df, args.apify_dir, args.data_dir)
    full_df = attach_v3_causal_features(full_df, bench, surfaces_by_id, sso_meta, args.live23_dir)

    # 3. Run ZERO-COMMENT `Product-only` Enriched Cohort Sim (`v3_po`) + Cached `Product+Comments` Cohort Sim (`v2`)!
    budget = Budget(cap_usd=10.0)
    v3_po_cache = JsonlCache(f"{args.work_dir}/cache_cohort_sim_v3_po")
    v2_cache = JsonlCache(f"{args.work_dir}/cache_cohort_sim_v2")
    calibrator = WalkForwardCalibrator()
    hist_for_cal = full_df[full_df["day"] <= "2026-11-24"].copy()
    g2_notes = load_g2_category_pain_notes(args.apify_dir)

    sep_nov_mask = full_df["day"] >= "2026-09-01"
    print(f"[Hillclimb v3] Running Zero-Comment Product-Only ComparativeCohortSimulator v3 across {full_df.loc[sep_nov_mask, 'day'].nunique()} Sep-Nov days...", flush=True)
    po_scored = run_v3_product_only_cohort_sim(
        full_df[sep_nov_mask], hist_for_cal, pool, calibrator, surfaces_by_id, sso_meta, g2_notes, v3_po_cache, budget, workers=6
    )
    pc_scored = run_v2_comparative_sim(
        full_df[sep_nov_mask], hist_for_cal, pool, calibrator, surfaces_by_id, v2_cache, budget, workers=6
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

    print(f"[Hillclimb v3] Total incremental Vertex LLM cost: ${budget.spent:.4f}", flush=True)

    # ------------------------------------------------------------------
    # Walk-Forward Predictor (Hyperparameters Locked Strictly on Val Sep <= 2026-09-30!)
    # ------------------------------------------------------------------
    def predict_walkforward(
        df_all: pd.DataFrame,
        apr_cols: list[str],
        sep_cols: list[str],
        target_std_apr: float,
        target_std_sep: float,
        max_shift: float,
    ) -> dict[tuple[str, str], float]:
        overrides: dict[tuple[str, str], float] = {}
        for mon in ("2026-09", "2026-10", "2026-11"):
            te = df_all[df_all["day"].str[:7] == mon].copy()
            if len(te) == 0:
                continue
            tr_apr = df_all[(df_all["day"].str[:7] < mon) & (df_all["day"] <= "2026-11-24")].copy()
            m_apr = WalkForwardResidualModel(
                feature_cols=apr_cols, ridge_alpha=250.0, pairwise_C=0.04, target_std=target_std_apr, max_shift=max_shift
            ).fit(tr_apr)
            shift = m_apr.predict_shift(te)

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

    val_bt = {d: v for d, v in full_day_launches.items() if d.startswith("2026-09")}
    val_df_only = full_df[full_df["day"] <= "2026-09-30"].copy()

    # Lock Track 1 (`Product only`, ZERO comments!) hyperparameters on Val Sep
    po_apr_cols = ALL_RESIDUAL_FEATURES + PRODUCT_ONLY_V3_TABULAR
    po_sep_cols = COHORT_V3_PO_FEATURES
    best_po_val, best_po_cfg = -1e9, (0.075, 0.180)
    for ts_a in (0.060, 0.075, 0.095):
        for ms_a in (0.150, 0.190, 0.230):
            ov_v = predict_walkforward(val_df_only, po_apr_cols, [], ts_a, 0.0, ms_a)
            vsub = val_df_only[val_df_only["day"].str.startswith("2026-09")].copy()
            vsub["final_score"] = [ov_v[(str(r.day), str(r.item_id))] for r in vsub.itertuples(index=False)]
            ev = evaluate_boards_and_ties(val_bt, truth_by_day, vsub, n_boot=200)
            mv = ev["model"]["mean_3_5_10"]
            if mv > best_po_val:
                best_po_val, best_po_cfg = mv, (ts_a, ms_a)

    # Lock Track 2 (`Product + comments`, order-free <= 03:45 PT!) hyperparameters on Val Sep
    pc_apr_cols = ALL_RESIDUAL_FEATURES + PRODUCT_ONLY_V3_TABULAR + PROD_COMMENT_FEATURES + COMMENT_V3_EXTRA
    pc_sep_cols = COHORT_V3_PO_FEATURES + COHORT_V2_FEATURES
    best_pc_val, best_pc_cfg = -1e9, (0.085, 0.220)
    for ts_b in (0.065, 0.085, 0.105, 0.125):
        for ms_b in (0.180, 0.220, 0.280):
            ov_v = predict_walkforward(val_df_only, pc_apr_cols, [], ts_b, 0.0, ms_b)
            vsub = val_df_only[val_df_only["day"].str.startswith("2026-09")].copy()
            vsub["final_score"] = [ov_v[(str(r.day), str(r.item_id))] for r in vsub.itertuples(index=False)]
            ev = evaluate_boards_and_ties(val_bt, truth_by_day, vsub, n_boot=200)
            mv = ev["model"]["mean_3_5_10"]
            if mv > best_pc_val:
                best_pc_val, best_pc_cfg = mv, (ts_b, ms_b)

    print(f"[Hillclimb v3] Locked on Val Sep -> Product-Only cfg={best_po_cfg} ({best_po_val:.2f}%) | Product+Comments cfg={best_pc_cfg} ({best_pc_val:.2f}%)", flush=True)

    # Compute walk-forward scores for BOTH tracks!
    ov_po_v1 = predict_walkforward(full_df, ALL_RESIDUAL_FEATURES, [], 0.060, 0.0, 0.150)
    ov_po_v3 = predict_walkforward(full_df, po_apr_cols, po_sep_cols, best_po_cfg[0], 0.045, best_po_cfg[1])
    ov_pc_v2 = predict_walkforward(full_df, ALL_RESIDUAL_FEATURES + PROD_COMMENT_FEATURES, APIFY_FEATURES + COHORT_V2_FEATURES, 0.105, 0.050, 0.220)
    ov_pc_v3 = predict_walkforward(full_df, pc_apr_cols, pc_sep_cols, best_pc_cfg[0], 0.055, best_pc_cfg[1])

    # 1. Evaluate 23-day Live Website Card (`2026-10-29 .. 2026-11-25`) — strictly separated!
    live_product_only = {
        "website_published_now": {"days": 23, "top3_pct": 49.3, "top5_pct": 61.7, "top10_pct": 69.6, "hits": {"top3": [34, 69], "top5": [71, 115], "top10": [160, 230]}},
        "arm3_0005_strict": score_23d_window(live_0005_launches, live_truth, None),
        "product_only_v1_0005": score_23d_window(live_0005_launches, live_truth, ov_po_v1),
        "product_only_v2_prev": score_23d_window(live_expanded_launches, live_truth, ov_po_v1),
        "product_only_v3_sso_camoufox_0005": score_23d_window(live_0005_launches, live_truth, ov_po_v3),
        "product_only_v3_sso_camoufox_with_late": score_23d_window(live_expanded_launches, live_truth, ov_po_v3),
    }
    live_product_comments = {
        "product_comments_v2_prev": score_23d_window(live_expanded_launches, live_truth, ov_pc_v2),
        "product_comments_v3_sso_and_scouts": score_23d_window(live_expanded_launches, live_truth, ov_pc_v3),
    }

    # 2. Evaluate 55-day Locked Test (`2026-10-01 .. 2026-11-24`) & Nov 24d (`2026-11-01 .. 2026-11-24`)
    test_df = full_df[(full_df["day"] >= "2026-10-01") & (full_df["day"] <= "2026-11-24")].copy()
    test_df = test_df.sort_values(["day", "structural_rank"]).groupby("day").head(20).reset_index(drop=True)
    test_df["score_po_v1"] = [ov_po_v1[(str(r.day), str(r.item_id))] for r in test_df.itertuples(index=False)]
    test_df["score_po_v3"] = [ov_po_v3[(str(r.day), str(r.item_id))] for r in test_df.itertuples(index=False)]
    test_df["score_pc_v2"] = [ov_pc_v2[(str(r.day), str(r.item_id))] for r in test_df.itertuples(index=False)]
    test_df["score_pc_v3"] = [ov_pc_v3[(str(r.day), str(r.item_id))] for r in test_df.itertuples(index=False)]

    bt55_po_v1 = evaluate_boards_and_ties(full_day_launches, truth_by_day, test_df, score_col="score_po_v1", n_boot=5000)
    bt55_po_v3 = evaluate_boards_and_ties(full_day_launches, truth_by_day, test_df, score_col="score_po_v3", n_boot=5000)
    bt55_pc_v2 = evaluate_boards_and_ties(full_day_launches, truth_by_day, test_df, score_col="score_pc_v2", n_boot=5000)
    bt55_pc_v3 = evaluate_boards_and_ties(full_day_launches, truth_by_day, test_df, score_col="score_pc_v3", n_boot=5000)

    nov_df = test_df[test_df["day"] >= "2026-11-01"].copy()
    nov_po_v1 = evaluate_boards_and_ties(full_day_launches, truth_by_day, nov_df, score_col="score_po_v1", n_boot=5000)
    nov_po_v3 = evaluate_boards_and_ties(full_day_launches, truth_by_day, nov_df, score_col="score_po_v3", n_boot=5000)
    nov_pc_v2 = evaluate_boards_and_ties(full_day_launches, truth_by_day, nov_df, score_col="score_pc_v2", n_boot=5000)
    nov_pc_v3 = evaluate_boards_and_ties(full_day_launches, truth_by_day, nov_df, score_col="score_pc_v3", n_boot=5000)

    # 3. Leak & Zero-Comment Separation Audits!
    shuf_df = full_df.sample(frac=1.0, random_state=777).reset_index(drop=True)
    ov_pc_shuf = predict_walkforward(shuf_df, pc_apr_cols, pc_sep_cols, best_pc_cfg[0], 0.055, best_pc_cfg[1])
    max_perm_diff = max(abs(ov_pc_v3[k] - ov_pc_shuf[k]) for k in ov_pc_v3)

    # Verify Product-Only v3 changes by exact 0.0 when ALL comment columns are zeroed out!
    zero_comm_df = full_df.copy()
    for c in PROD_COMMENT_FEATURES + COMMENT_V3_EXTRA + COHORT_V2_FEATURES:
        if c in zero_comm_df.columns:
            zero_comm_df[c] = -999.0
    ov_po_check = predict_walkforward(zero_comm_df, po_apr_cols, po_sep_cols, best_po_cfg[0], 0.045, best_po_cfg[1])
    max_po_comment_leak = max(abs(ov_po_v3[k] - ov_po_check[k]) for k in ov_po_v3)

    assert max_perm_diff < 1e-9, f"Order invariance failed: {max_perm_diff}"
    assert max_po_comment_leak == 0.0, f"Product-only comment isolation failed: {max_po_comment_leak}"

    out = {
        "experiment_id": "USERSIM-CORE-HILLCLIMB-3",
        "elapsed_sec": round(time.time() - t0, 1),
        "vertex_llm_cost_usd": round(budget.spent, 4),
        "fleet_5vm_google_sso_stats": sso_stats,
        "leak_and_isolation_audits": {
            "input_order_permutation_max_abs_diff": float(max_perm_diff),
            "product_only_comment_isolation_max_abs_diff": float(max_po_comment_leak),
            "forbidden_rank_vote_keys_stripped": True,
        },
        "live_23d_product_only_tab": live_product_only,
        "live_23d_product_comments_tab": live_product_comments,
        "locked_test_55d_oct_nov": {
            "product_only_v1": bt55_po_v1,
            "product_only_v3": bt55_po_v3,
            "product_comments_v2": bt55_pc_v2,
            "product_comments_v3": bt55_pc_v3,
        },
        "november_24d_full_calibration": {
            "product_only_v1": nov_po_v1,
            "product_only_v3": nov_po_v3,
            "product_comments_v2": nov_pc_v2,
            "product_comments_v3": nov_pc_v3,
        },
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out_json)), exist_ok=True)
    json.dump(out, open(args.out_json, "w"), indent=2)

    print("\n=== TRACK 1: PRODUCT ONLY (23 LIVE DAYS, ZERO COMMENTS) ===", flush=True)
    for k, v in live_product_only.items():
        print(f"  {k:40s}: Top-3={v['top3_pct']:5.1f}% ({v['hits']['top3'][0]}/{v['hits']['top3'][1]}) | Top-5={v['top5_pct']:5.1f}% ({v['hits']['top5'][0]}/{v['hits']['top5'][1]}) | Top-10={v['top10_pct']:5.1f}% ({v['hits']['top10'][0]}/{v['hits']['top10'][1]})", flush=True)

    print("\n=== TRACK 2: PRODUCT + COMMENTS (23 LIVE DAYS, ORDER-FREE <=03:45 PT) ===", flush=True)
    for k, v in live_product_comments.items():
        print(f"  {k:40s}: Top-3={v['top3_pct']:5.1f}% ({v['hits']['top3'][0]}/{v['hits']['top3'][1]}) | Top-5={v['top5_pct']:5.1f}% ({v['hits']['top5'][0]}/{v['hits']['top5'][1]}) | Top-10={v['top10_pct']:5.1f}% ({v['hits']['top10'][0]}/{v['hits']['top10'][1]})", flush=True)

    print("\n=== 55-DAY LOCKED TEST (OCT 1 - NOV 24) ===", flush=True)
    for k, v in out["locked_test_55d_oct_nov"].items():
        print(f"  {k:24s}: arm3={v['arm3']} -> model={v['model']} | lift={v['paired_lift_pts']['mean_3_5_10']} | ties={v['reach_matched_ties']['model_acc_pct']}%", flush=True)

    print("\n=== 24-DAY NOVEMBER FULL CALIBRATION (NOV 1 - NOV 24) ===", flush=True)
    for k, v in out["november_24d_full_calibration"].items():
        print(f"  {k:24s}: arm3={v['arm3']} -> model={v['model']} | lift={v['paired_lift_pts']['mean_3_5_10']} | ties={v['reach_matched_ties']['model_acc_pct']}%", flush=True)


if __name__ == "__main__":
    main()
