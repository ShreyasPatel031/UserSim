"""Zero-Leakage Apify External Signal Extractor (`usersim_core/apify_features.py`).

Builds causal, leak-audited external features + grounding digests from the raw Apify pulls:
  1. Pre-launch X/Twitter (`x_prelaunch_tweets_raw.jsonl`):
     - HARD-ASSERTS `tweet_created_utc < day_start_utc(D)` (`00:00:00 PT` on launch day `D`).
       Any tweet timestamped at or after `00:00:00 PT` on day `D` is strictly rejected (`leaked_kept == 0`).
     - Computes pre-launch organic/founder tweet count, engagement (`likes + 2*retweets + 2*bookmarks`),
       and maximum author follower reach (`< D`).
  2. LinkedIn Company Footprint (`linkedin_companies_raw.jsonl`):
     - Matches LinkedIn company records by verified website domain or exact normalized company name
       (avoiding noisy fuzzy matches on generic English words).
     - Extracts employee headcount (`log1p`), LinkedIn company followers (`log1p`), founded year / maturity,
       and verified org indicator.
  3. G2 Verified Product & Category Incumbent Reviews (`g2_products_and_reviews_raw.jsonl`):
     - Extracts direct G2 product review footprint (filtering any dated reviews to `< D`) + maps
       `competitors.parquet` category incumbents to verified user pros/cons/switching pain points.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import re
from typing import Any

import numpy as np
import pandas as pd

from simharness.bench import _day_bounds_utc
from usersim_core.apify_pull import GENERIC_DOMAINS, clean_domain, extract_company_name
from usersim_core.residual_learner import within_day_zscore


def _norm_name(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(s or "").lower())


def load_apify_signals(
    df: pd.DataFrame,
    apify_dir: str,
    data_dir: str,
    day_tz: str = "America/Los_Angeles",
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Attach Apify X, LinkedIn, and G2 features + grounding digests onto `df` (`Sep-Nov` rows active, `<Sep` 0-centered)."""
    df = df.copy().reset_index(drop=True)
    stats: dict[str, Any] = {
        "x_raw_tweets_read": 0,
        "x_strictly_prelaunch_matched": 0,
        "x_postlaunch_rejected_by_gate": 0,
        "x_leaked_kept": 0,
        "linkedin_raw_profiles": 0,
        "linkedin_matched_launches": 0,
        "g2_raw_items": 0,
        "g2_products_indexed": 0,
        "g2_reviews_indexed": 0,
    }

    # Precompute day_start_utc(D) for every day in df
    day_starts = {d: _day_bounds_utc(str(d), day_tz)[0] for d in df["day"].unique()}

    # ------------------------------------------------------------------
    # 1. LinkedIn Company Matching (Domain match OR exact normalized company name)
    # ------------------------------------------------------------------
    li_by_domain: dict[str, dict] = {}
    li_by_norm: dict[str, dict] = {}
    li_path = f"{apify_dir}/linkedin_companies_raw.jsonl"
    if os.path.exists(li_path):
        with open(li_path) as f:
            for line in f:
                try:
                    rec = (json.loads(line)).get("raw") or {}
                except Exception:
                    continue
                if not rec or not rec.get("name"):
                    continue
                stats["linkedin_raw_profiles"] += 1
                wdom = clean_domain(str(rec.get("website") or rec.get("callToActionUrl") or ""))
                if wdom and wdom not in GENERIC_DOMAINS:
                    prev = li_by_domain.get(wdom)
                    if not prev or int(rec.get("followerCount") or 0) > int(prev.get("followerCount") or 0):
                        li_by_domain[wdom] = rec
                nn = _norm_name(rec.get("name") or "")
                if len(nn) >= 4:
                    prev = li_by_norm.get(nn)
                    if not prev or int(rec.get("followerCount") or 0) > int(prev.get("followerCount") or 0):
                        li_by_norm[nn] = rec

    li_emp = np.zeros(len(df), dtype=np.float64)
    li_fol = np.zeros(len(df), dtype=np.float64)
    li_est = np.zeros(len(df), dtype=np.float64)
    li_matched = np.zeros(len(df), dtype=bool)
    li_digests: list[str] = []

    for i, r in enumerate(df.itertuples(index=False)):
        dom = clean_domain(str(getattr(r, "url", "") or ""))
        cname = extract_company_name(str(r.title), dom)
        nn = _norm_name(cname)
        match = None
        if dom and dom not in GENERIC_DOMAINS and dom in li_by_domain:
            match = li_by_domain[dom]
        elif len(nn) >= 5 and nn in li_by_norm:
            cand = li_by_norm[nn]
            cand_dom = clean_domain(str(cand.get("website") or ""))
            # Accept exact name match if launch has no domain, or domains share root, or company name is distinctive (>=6 chars)
            if not dom or not cand_dom or dom == cand_dom or dom.split(".")[0] == cand_dom.split(".")[0] or len(nn) >= 7:
                match = cand

        if match is not None:
            stats["linkedin_matched_launches"] += 1
            li_matched[i] = True
            emp = float(match.get("employeeCount") or 0.0)
            fol = float(match.get("followerCount") or 0.0)
            f_yr = int((match.get("foundedOn") or {}).get("year") or 0) if isinstance(match.get("foundedOn"), dict) else 0
            li_emp[i] = math.log1p(max(0.0, emp))
            li_fol[i] = math.log1p(max(0.0, fol))
            li_est[i] = 1.0 if (emp >= 11 or (0 < f_yr <= 2025) or bool(match.get("pageVerified"))) else 0.0
            raw_inds = (match.get("industries") or [])[:2] if isinstance(match.get("industries"), list) else []
            inds = ", ".join(str(x.get("name") or "") if isinstance(x, dict) else str(x) for x in raw_inds if x)
            li_digests.append(
                f"LinkedIn Org: {match.get('name')} ({int(emp)} employees, {int(fol)} followers"
                + (f", founded {f_yr}" if f_yr else "")
                + (f", {inds}" if inds else "")
                + ")"
            )
        else:
            li_digests.append("")

    # ------------------------------------------------------------------
    # 2. Strictly Pre-Launch (< D 00:00 PT) X/Twitter Traction
    # ------------------------------------------------------------------
    x_qmap_path = f"{apify_dir}/x_query_map.json"
    lid_to_terms: dict[str, tuple[str, list[str], str]] = {}
    if os.path.exists(x_qmap_path):
        for entry in json.load(open(x_qmap_path)):
            lid_to_terms[str(entry["item_id"])] = (
                str(entry.get("domain") or "").lower(),
                [str(h).lower() for h in (entry.get("x_handles") or [])],
                str(entry.get("title") or "").lower(),
            )

    tweets_by_lid: dict[str, list[dict]] = {}
    x_path = f"{apify_dir}/x_prelaunch_tweets_raw.jsonl"
    df_day_by_lid = dict(zip(df["item_id"].astype(str), df["day"].astype(str)))

    if os.path.exists(x_path):
        with open(x_path) as f:
            for line in f:
                try:
                    outer = json.loads(line)
                    tw = outer.get("raw") or {}
                    cand_lids = [str(x) for x in (outer.get("_chunk_launch_ids") or [])]
                except Exception:
                    continue
                if not tw or not tw.get("text"):
                    continue
                stats["x_raw_tweets_read"] += 1
                c_at = pd.to_datetime(tw.get("createdAt"), utc=True, errors="coerce")
                if pd.isna(c_at):
                    continue

                txt_low = str(tw.get("text") or "").lower()
                # Also inspect expanded URLs inside entities if t.co shortened domain!
                ent_urls = []
                for uobj in ((tw.get("entities") or {}).get("urls") or []):
                    if isinstance(uobj, dict):
                        ent_urls.append(str(uobj.get("expanded_url") or uobj.get("display_url") or "").lower())
                full_hay = txt_low + " " + " ".join(ent_urls)
                author_u = str((tw.get("author") or {}).get("userName") or "").lower()

                for lid in cand_lids:
                    d_str = df_day_by_lid.get(lid)
                    if not d_str or d_str not in day_starts:
                        continue
                    dom_l, handles_l, title_l = lid_to_terms.get(lid, ("", [], ""))
                    matched_term = False
                    if dom_l and dom_l not in GENERIC_DOMAINS and len(dom_l) >= 5 and dom_l in full_hay:
                        matched_term = True
                    elif handles_l and (author_u in handles_l or any(f"@{h}" in txt_low for h in handles_l)):
                        matched_term = True
                    elif len(title_l) >= 6 and title_l in txt_low:
                        matched_term = True

                    if not matched_term:
                        continue

                    # HARD ZERO-LEAKAGE TIMESTAMP GATE: strictly < 00:00:00 PT on launch day D!
                    if c_at >= day_starts[d_str]:
                        stats["x_postlaunch_rejected_by_gate"] += 1
                        continue

                    assert c_at < day_starts[d_str], "FATAL: Post-launch X tweet passed pre-launch gate!"
                    tweets_by_lid.setdefault(lid, []).append(tw)
                    stats["x_strictly_prelaunch_matched"] += 1

    x_cnt = np.zeros(len(df), dtype=np.float64)
    x_eng = np.zeros(len(df), dtype=np.float64)
    x_max_fol = np.zeros(len(df), dtype=np.float64)
    x_digests: list[str] = []

    for i, r in enumerate(df.itertuples(index=False)):
        lid = str(r.item_id)
        tws = tweets_by_lid.get(lid) or []
        # Deduplicate by tweet id
        uniq_tw = {str(t.get("id") or k): t for k, t in enumerate(tws)}.values()
        tw_list = list(uniq_tw)
        if tw_list:
            eng = sum(
                float(t.get("likeCount") or 0)
                + 2.0 * float(t.get("retweetCount") or 0)
                + 2.0 * float(t.get("bookmarkCount") or 0)
                + float(t.get("quoteCount") or 0)
                for t in tw_list
            )
            mfol = max(float((t.get("author") or {}).get("followers") or 0.0) for t in tw_list)
            x_cnt[i] = math.log1p(len(tw_list))
            x_eng[i] = math.log1p(eng)
            x_max_fol[i] = math.log1p(mfol)
            x_digests.append(
                f"Pre-launch X (<D): {len(tw_list)} tweets, {int(eng)} weighted engagements, top author {int(mfol)} followers"
            )
        else:
            x_digests.append("")

    # ------------------------------------------------------------------
    # 3. G2 Verified Product & Category Incumbent Reviews
    # ------------------------------------------------------------------
    g2_prods: dict[str, dict] = {}
    g2_revs: dict[str, list[dict]] = {}
    for g2_fname in ("g2_products_and_reviews_raw.jsonl", "g2_extra_incumbent_reviews_raw.jsonl"):
        g2_path = f"{apify_dir}/{g2_fname}"
        if not os.path.exists(g2_path):
            continue
        with open(g2_path) as f:
            for line in f:
                try:
                    it = (json.loads(line)).get("raw") or {}
                except Exception:
                    continue
                if not it:
                    continue
                stats["g2_raw_items"] += 1
                tp = str(it.get("type") or "")
                if tp == "product" or ("reviews_count" in it and "rating" in it and "what_is" in it):
                    stats["g2_products_indexed"] += 1
                    for k_nm in (it.get("name"), it.get("input"), it.get("slug")):
                        nn = _norm_name(str(k_nm or ""))
                        if len(nn) >= 3:
                            prev = g2_prods.get(nn)
                            if not prev or int(it.get("reviews_count") or 0) > int(prev.get("reviews_count") or 0):
                                g2_prods[nn] = it
                else:
                    stats["g2_reviews_indexed"] += 1
                    p_nm = _norm_name(str(it.get("product_name") or it.get("input") or it.get("slug") or ""))
                    if len(p_nm) >= 3:
                        g2_revs.setdefault(p_nm, []).append(it)

    # Map launch -> competitors from taxonomy/competitors.parquet
    comp_by_lid: dict[str, list[str]] = {}
    comp_pq = f"{data_dir}/taxonomy/competitors.parquet"
    if os.path.exists(comp_pq):
        cdf = pd.read_parquet(comp_pq, columns=["item_id", "competitors"])
        for r in cdf.itertuples(index=False):
            if r.competitors:
                try:
                    arr = json.loads(r.competitors) if isinstance(r.competitors, str) else r.competitors
                    comp_by_lid[str(r.item_id)] = [str(c.get("name") or "") for c in arr if c.get("name")]
                except Exception:
                    pass

    g2_direct = np.zeros(len(df), dtype=np.float64)
    g2_comp_cov = np.zeros(len(df), dtype=np.float64)
    g2_digests: list[str] = []

    for i, r in enumerate(df.itertuples(index=False)):
        lid = str(r.item_id)
        dom = clean_domain(str(getattr(r, "url", "") or ""))
        cname = _norm_name(extract_company_name(str(r.title), dom))
        if len(cname) >= 5 and cname in g2_prods:
            gp = g2_prods[cname]
            rc = float(gp.get("reviews_count") or 0.0)
            rt = float(gp.get("rating") or 0.0)
            if rc >= 3:
                g2_direct[i] = math.log1p(rc) * (rt / 5.0 if rt > 0 else 0.85)

        comps = comp_by_lid.get(lid) or []
        comp_notes = []
        for c_nm in comps[:4]:
            cnn = _norm_name(c_nm)
            gp = g2_prods.get(cnn)
            if gp:
                rc = int(gp.get("reviews_count") or 0)
                rt = float(gp.get("rating") or 0.0)
                revs = g2_revs.get(cnn) or []
                dislike_snip = ""
                for rv in revs[:3]:
                    dl = str(rv.get("dislike") or rv.get("what_do_you_dislike") or rv.get("cons") or "").strip()
                    if len(dl) >= 20:
                        dislike_snip = " ".join(dl.split())[:110]
                        break
                comp_notes.append(
                    f"{gp.get('name')} (G2 {rt:.1f}/5, {rc} revs" + (f", pain: {dislike_snip}" if dislike_snip else "") + ")"
                )
        if comp_notes:
            g2_comp_cov[i] = float(len(comp_notes))
            g2_digests.append("Incumbents on G2: " + "; ".join(comp_notes[:2]))
        else:
            g2_digests.append("")

    # Only z-score Apify features on days where Apify was pulled (Sep 1 - Nov 25); Apr-Aug stay exact 0.0!
    apify_active = (df["day"] >= "2026-09-01").to_numpy()
    df["apify_active"] = apify_active
    df["raw_li_emp"] = li_emp
    df["raw_li_fol"] = li_fol
    df["raw_li_est"] = li_est
    df["raw_x_cnt"] = x_cnt
    df["raw_x_eng"] = x_eng
    df["raw_x_mfol"] = x_max_fol
    df["raw_g2_direct"] = g2_direct

    df["apify_li_employees_z"] = within_day_zscore(df, "raw_li_emp", mask_col="apify_active")
    df["apify_li_followers_z"] = within_day_zscore(df, "raw_li_fol", mask_col="apify_active")
    df["apify_li_established_z"] = within_day_zscore(df, "raw_li_est", mask_col="apify_active")
    df["apify_x_pre_tweets_z"] = within_day_zscore(df, "raw_x_cnt", mask_col="apify_active")
    df["apify_x_pre_engagement_z"] = within_day_zscore(df, "raw_x_eng", mask_col="apify_active")
    df["apify_x_author_reach_z"] = within_day_zscore(df, "raw_x_mfol", mask_col="apify_active")
    df["apify_g2_direct_z"] = within_day_zscore(df, "raw_g2_direct", mask_col="apify_active")

    ext_digests = []
    for i in range(len(df)):
        parts = [p for p in (li_digests[i], x_digests[i], g2_digests[i]) if p]
        ext_digests.append(" | ".join(parts) if parts else "[NO_EXTERNAL_FOOTPRINT_FOUND]")
    df["apify_external_digest"] = ext_digests

    return df, stats
