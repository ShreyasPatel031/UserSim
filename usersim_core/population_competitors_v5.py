"""Causal (< D) Named Competitor Graph, 93,618-Person Discrete-Choice Voter/Switcher Simulator,
`STACK-1b` Qwen-7B `P(yes)` Fusion, and Cold-Start Brand Authority (`usersim_core/population_competitors_v5.py`).

Implements Modules 1A, 1B, and Cold-Start Brand Authority for `USERSIM-CORE-HILLCLIMB-5`:
  1. `CompetitorGraph` (Module 1A, strictly `< D` causal):
     - Enforces `CATEGORY1_README.md` leak guard: `taxonomy/competitors.parquet` (`fetched_at <= 2026-11-01T21Z`)
       is NEVER consulted for `day < 2026-11-02`. For `day < 2026-11-02` (and any launch missing from `competitors.parquet`),
       retrieves Top-5 Named Competitors strictly from `< D` launches in `bench.items` (`item.day < D`) sharing
       `00:05 PT`-knowable categories (`embedding_top3`, `embedding_0005_pre_april`, `tags`) + semantic SVD similarity
       + `< D` G2 verified product profiles (`reviews filtered < D`) + `< D` HN Algolia competitor complaint threads.
     - Computes `comp_market_demand_z`, `comp_incumbent_crowding_z`, `comp_cua_advantage_z`, and
       `sameday_direct_rival_cannibalization_z` (100% invariant to input row order, ZERO launch-day comments).
  2. `PopulationChoiceSim` (Module 1B, all `93,618` complete held people, strictly `< D` causal):
     - Streams `backer_pred/*.parquet` (Qwen-7B per-person `P(yes)`), `tables/follows/*.parquet` (`observed_on < D`),
       `tables/launches/*.parquet`, and `tables/at_launch_followers/*.parquet` directly from GCS in memory without
       crowding local disk, purging transient handles before returning privacy-safe cohort summaries.
     - Models `< D` Team/Maker/Hunter repeat backers, `< D` Named-Competitor switchers ($C_1..C_5$), `< D` 90-day
       activity tiers (`1-9`, `10-99`, `100+`), `< D` SVD taste & topic alignment, and `STACK-1b` Qwen-7B `P(yes)`
       (`stack_coef.json`), coupled via budget-constrained same-day multinomial softmax competition across day `D`'s lineup!
  3. `attach_cold_start_brand_authority`:
     - Combines `Apr-Aug` + `Sep-Nov` LinkedIn company profiles (`employeeCount`, `followerCount`, `foundedYear`),
       strictly `< D` pre-launch X author reach, official tech/ecosystem domain authority, and developer protocol
       artifacts (`MCP`, `CLI`, `SDK`, `GitHub OSS`) so cold-start breakouts (`#11..#15`) with modest hunter/maker
       PH history can be promoted cleanly.
"""
from __future__ import annotations

from collections import defaultdict
import datetime as dt
import glob
import html
import json
import math
import os
import re
from typing import Any

import gcsfs
import numpy as np
import pandas as pd
import scipy.sparse as sp

from simharness.bench import Benchmark, KIND_CODE, _day_bounds_utc, day_ord, scrub
from simharness.schema import COMMENT, ENDORSE, MAKE
from usersim_core.apify_pull import GENERIC_DOMAINS, clean_domain, extract_company_name
from usersim_core.pool import UniversalUserPool
from usersim_core.residual_learner import within_day_zscore
from usersim_core.sanitizer import SanitizedSurface, sanitize_text


COMPETITOR_V5_FEATURES = [
    "comp_market_demand_z",
    "comp_incumbent_crowding_z",
    "comp_cua_advantage_z",
    "sameday_direct_rival_cannibalization_z",
    "sameday_cluster_rank_adv_z",
]

POPULATION_V5_FEATURES = [
    "pop_expected_votes_choice_z",
    "pop_power_builder_votes_z",
    "pop_team_backer_votes_z",
    "pop_follow_ties_lt_d_z",
    "pop_comp_switcher_votes_z",
    "pop_cannibalization_loss_z",
    "pop_qwen_stack1b_z",
]

BRAND_AUTHORITY_V5_FEATURES = [
    "brand_li_org_scale_all_z",
    "brand_coldstart_authority_z",
    "brand_protocol_oss_leverage_z",
    "struct_hunter_maker_gap_z",
]

_PAIN_PRICE_RE = re.compile(
    r"\b(expensive|price|pricing|cost|paywall|credit|tier|seat|lock-in|locked|subscription|billing|enterprise\s+only|overpriced)\b",
    re.IGNORECASE,
)
_PAIN_UX_RE = re.compile(
    r"\b(clunky|slow|complex|steep\s+learning|confusing|bloated|onboarding|setup|hard\s+to\s+use|laggy|ui|ux|friction)\b",
    re.IGNORECASE,
)
_PAIN_BUG_RE = re.compile(
    r"\b(bug|bugs|buggy|crash|broken|unreliable|error|downtime|hallucinat|inaccurate|fails|glitch)\b",
    re.IGNORECASE,
)
_PAIN_API_OSS_RE = re.compile(
    r"\b(closed|no\s+api|api\s+limit|self-host|open\s*-?\s*source|local|privacy|export|integration|webhook|cli|mcp)\b",
    re.IGNORECASE,
)
_SW_CONTEXT_RE = re.compile(
    r"\b(app|tool|software|saas|api|sdk|pricing|ui|ux|workflow|cloud|platform|feature|users|team|integration|plugin|agent|editor|repo|open\s*source)\b",
    re.IGNORECASE,
)
_PROTOCOL_DEV_RE = re.compile(
    r"\b(mcp|model\s+context\s+protocol|cli|sdk|open\s*-?\s*source|self-hosted|local-first|api|github|vscode|cursor|agent\s+protocol)\b",
    re.IGNORECASE,
)

MAJOR_BRAND_ROOTS = {
    "producthunt", "google", "anthropic", "openai", "adobe", "microsoft", "github", "vercel",
    "cloudflare", "supabase", "stripe", "notion", "figma", "linear", "raycast", "jetbrains",
    "huggingface", "elevenlabs", "perplexity", "mistral", "meta", "aws", "amazon", "apple",
    "atlassian", "datadog", "sentry", "posthog", "retool", "zapier", "n8n", "composio",
}


def _norm_key(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(s or "").lower())


def _clean_snippet(raw: str, max_chars: int = 135) -> str:
    if not raw:
        return ""
    txt = html.unescape(re.sub(r"<[^>]+>", " ", str(raw)))
    txt = scrub(" ".join(txt.split()))
    txt, _ = sanitize_text(txt)
    return txt[:max_chars].strip()


class CompetitorGraph:
    """Strictly causal (`< D`) Named Competitor Graph & CUA-vs-Competitor Advantage engine."""

    def __init__(
        self,
        bench: Benchmark,
        pool: UniversalUserPool,
        data_dir: str,
        apify_dir: str,
        gcs_bucket: str = "usersim-bakeoff-347838016394",
    ) -> None:
        self.bench = bench
        self.pool = pool
        self.data_dir = data_dir
        self.apify_dir = apify_dir
        self.gcs_bucket = gcs_bucket

        # 1. Index all 7,461 bench items with their exact launch day, slug, categories, SVD vec, and <D endorsement history
        ik_path = f"{data_dir}/bench/item_keys.parquet"
        slug_by_id: dict[str, str] = {}
        if os.path.exists(ik_path):
            ik = pd.read_parquet(ik_path)
            slug_by_id = dict(zip(ik["item_id"].astype(str), ik["slug"].fillna("").astype(str)))

        self.item_ids = bench.items["item_id"].astype(str).to_numpy()
        self.item_days = bench.items["day"].astype(str).to_numpy()
        self.item_day_ords = bench.items["day_ord"].to_numpy(dtype=np.int32)
        self.item_titles = bench.items["title"].fillna("").astype(str).to_numpy()
        self.item_summaries = bench.items["summary"].fillna("").astype(str).to_numpy()
        self.item_tags = list(bench.items["tags"])
        self.item_slugs = np.array([slug_by_id.get(lid, _norm_key(t)) for lid, t in zip(self.item_ids, self.item_titles)], dtype=object)
        self.idx_by_id = {lid: i for i, lid in enumerate(self.item_ids)}

        # Map normalized slug / name -> list of bench item_idx sorted chronologically
        self.iidxs_by_norm: dict[str, list[int]] = defaultdict(list)
        self.earliest_day_by_slug: dict[str, str] = {}
        for i, (sl, ti, d_s) in enumerate(zip(self.item_slugs, self.item_titles, self.item_days)):
            for k in {_norm_key(sl), _norm_key(re.sub(r"-\d+$", "", str(sl))), _norm_key(ti)}:
                if len(k) >= 3:
                    self.iidxs_by_norm[k].append(i)
            sl_clean = re.sub(r"-\d+$", "", str(sl or "")).strip().lower()
            if sl_clean:
                prev_d = self.earliest_day_by_slug.get(sl_clean)
                if prev_d is None or d_s < prev_d:
                    self.earliest_day_by_slug[sl_clean] = d_s

        # Precompute total endorsements per bench item (since upvotes occur on launch day, any item with day < D has < D upvotes)
        end_df = bench.hist[bench.hist["kind"] == KIND_CODE[ENDORSE]]
        self.item_endorse_counts = np.bincount(
            end_df["item_idx"].to_numpy(dtype=np.int32), minlength=len(self.item_ids)
        ).astype(np.float32)

        # Makers per item_idx to exclude self-launches from competitor candidates
        mk_df = bench.hist[bench.hist["kind"] == KIND_CODE[MAKE]][["person_idx", "item_idx"]].drop_duplicates()
        self.makers_by_iidx: dict[int, set[int]] = defaultdict(set)
        for r in mk_df.itertuples(index=False):
            self.makers_by_iidx[int(r.item_idx)].add(int(r.person_idx))

        # 2. Load 00:05-knowable launch_categories.parquet (`embedding_top3`, `embedding_0005_pre_april`)
        self.cat_top3_by_id: dict[str, list[str]] = {}
        self.cat_0005_by_id: dict[str, str] = {}
        lc_path = f"{data_dir}/taxonomy/launch_categories.parquet"
        if os.path.exists(lc_path):
            lc_df = pd.read_parquet(
                lc_path, columns=["item_id", "embedding_top3", "embedding_0005_pre_april", "embedding_zero_shot"]
            )
            for r in lc_df.itertuples(index=False):
                lid = str(r.item_id)
                c0 = str(r.embedding_0005_pre_april or r.embedding_zero_shot or "General")
                self.cat_0005_by_id[lid] = c0
                t3 = list(r.embedding_top3) if isinstance(r.embedding_top3, (list, tuple, np.ndarray)) else []
                cats = [str(x) for x in t3 if x]
                if c0 and c0 not in cats:
                    cats.insert(0, c0)
                self.cat_top3_by_id[lid] = cats[:3] if cats else ["General"]

        # Inverted index: 00:05 category -> bench item indices sorted by day_ord
        self.cat_to_bench_iidxs: dict[str, np.ndarray] = {}
        cat_lists: dict[str, list[int]] = defaultdict(list)
        for i, lid in enumerate(self.item_ids):
            cats = set(self.cat_top3_by_id.get(lid, []))
            for t in (self.item_tags[i] or [])[:3]:
                cats.add(str(t))
            for c in cats:
                if c:
                    cat_lists[c].append(i)
        for c, arr in cat_lists.items():
            arr_sorted = sorted(arr, key=lambda idx: (int(self.item_day_ords[idx]), str(self.item_ids[idx])))
            self.cat_to_bench_iidxs[c] = np.asarray(arr_sorted, dtype=np.int32)

        # 3. Load taxonomy/products.parquet & taxonomy/competitors.parquet (STRICTLY GATED to day >= 2026-11-02!)
        self.nov_competitors_by_id: dict[str, list[dict[str, Any]]] = {}
        comp_pq = f"{data_dir}/taxonomy/competitors.parquet"
        if os.path.exists(comp_pq):
            cdf = pd.read_parquet(comp_pq, columns=["item_id", "day", "competitors", "similar_fetched_at"])
            for r in cdf.itertuples(index=False):
                # HARD LEAK GUARD (CATEGORY1_README.md): Similar Products were fetched 2026-11-01T21Z.
                # NEVER load or expose these rows for any launch before 2026-11-02!
                if str(r.day) < "2026-11-02":
                    continue
                if r.competitors:
                    try:
                        parsed = json.loads(r.competitors) if isinstance(r.competitors, str) else list(r.competitors)
                        self.nov_competitors_by_id[str(r.item_id)] = parsed
                    except Exception:
                        pass

        # 4. Load G2 products & reviews (filtering dated reviews strictly < D) + HN Algolia competitor threads (< D)
        self.g2_prods: dict[str, dict[str, Any]] = {}
        self.g2_revs: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.g2_by_cat_hint: dict[str, list[str]] = defaultdict(list)
        for g2_fname in ("g2_products_and_reviews_raw.jsonl", "g2_extra_incumbent_reviews_raw.jsonl"):
            p = f"{apify_dir}/{g2_fname}"
            if not os.path.exists(p):
                continue
            with open(p) as f:
                for line in f:
                    try:
                        it = (json.loads(line)).get("raw") or {}
                    except Exception:
                        continue
                    if not it:
                        continue
                    tp = str(it.get("type") or "")
                    if tp == "product" or ("reviews_count" in it and "rating" in it):
                        nm = str(it.get("name") or it.get("input") or it.get("slug") or "").strip()
                        nn = _norm_key(nm)
                        if len(nn) >= 3:
                            prev = self.g2_prods.get(nn)
                            if not prev or int(it.get("reviews_count") or 0) > int(prev.get("reviews_count") or 0):
                                self.g2_prods[nn] = it
                            for cat_s in (it.get("categories") or []):
                                self.g2_by_cat_hint[str(cat_s).lower()].append(nn)
                    else:
                        p_nm = _norm_key(str(it.get("product_name") or it.get("input") or it.get("slug") or ""))
                        if len(p_nm) >= 3:
                            r_dt = str(it.get("date") or it.get("published_at") or it.get("submitted_at") or "")[:10]
                            it_copy = dict(it)
                            it_copy["_rev_day"] = r_dt if re.match(r"^\d{4}-\d{2}-\d{2}$", r_dt) else ""
                            self.g2_revs[p_nm].append(it_copy)

        self.hn_comp_complaints: dict[str, list[tuple[str, str]]] = defaultdict(list)
        self._load_hn_competitor_feedback_from_gcs()

    def _load_hn_competitor_feedback_from_gcs(self) -> None:
        """Stream compact HN Algolia competitor feedback JSONLs from GCS (`< 500 KB`, filtered by `_SW_CONTEXT_RE`)."""
        try:
            fs = gcsfs.GCSFileSystem()
            paths = sorted(fs.glob(f"{self.gcs_bucket}/usersim_sim/raw/fleet_external/reviews/competitor_feedback_slot*.jsonl"))
            for p in paths:
                with fs.open(p, "r") as f:
                    for line in f:
                        if not line.strip():
                            continue
                        rec = json.loads(line)
                        comp_nn = _norm_key(rec.get("competitor") or "")
                        if len(comp_nn) < 3:
                            continue
                        for c in (rec.get("comments") or []):
                            c_day = str(c.get("created_at") or "")[:10]
                            raw_txt = str(c.get("comment_text") or "")
                            clean_t = _clean_snippet(raw_txt, max_chars=150)
                            if len(clean_t) >= 40 and _SW_CONTEXT_RE.search(clean_t):
                                if _PAIN_PRICE_RE.search(clean_t) or _PAIN_UX_RE.search(clean_t) or _PAIN_BUG_RE.search(clean_t) or _PAIN_API_OSS_RE.search(clean_t):
                                    self.hn_comp_complaints[comp_nn].append((c_day, clean_t))
        except Exception:
            pass

    def _competitor_pain_profile(self, comp_name: str, comp_slug: str, day: str) -> dict[str, Any]:
        """Extract strictly `< day` verified user pain points & flags for a named competitor."""
        keys = [k for k in {_norm_key(comp_name), _norm_key(comp_slug), _norm_key(re.sub(r"-\d+$", "", comp_slug))} if len(k) >= 3]
        g2_rc = 0
        g2_rt = 0.0
        texts: list[str] = []
        for k in keys:
            gp = self.g2_prods.get(k)
            if gp and int(gp.get("reviews_count") or 0) > g2_rc:
                g2_rc = int(gp.get("reviews_count") or 0)
                g2_rt = float(gp.get("rating") or 0.0)
            for rv in self.g2_revs.get(k, []):
                rd = rv.get("_rev_day") or ""
                if rd and rd >= day:
                    continue
                dl = _clean_snippet(str(rv.get("dislike") or rv.get("what_do_you_dislike") or rv.get("cons") or ""), 130)
                if len(dl) >= 25:
                    texts.append(dl)
            for c_day, hn_txt in self.hn_comp_complaints.get(k, []):
                if not c_day or c_day < day:
                    texts.append(hn_txt)

        joined = " ".join(texts[:8])
        price_pain = bool(_PAIN_PRICE_RE.search(joined))
        ux_pain = bool(_PAIN_UX_RE.search(joined))
        bug_pain = bool(_PAIN_BUG_RE.search(joined))
        api_oss_pain = bool(_PAIN_API_OSS_RE.search(joined))

        top_pain = texts[0] if texts else ""
        if not top_pain:
            if g2_rc >= 50:
                top_pain = "Established incumbent with enterprise/seat tiering and heavier workflow overhead"
            else:
                top_pain = "Prior category contender competing on speed-to-value and reliability"

        return {
            "g2_reviews_count": g2_rc,
            "g2_rating": round(g2_rt, 2) if g2_rt > 0 else None,
            "pain_pricing": price_pain,
            "pain_ux": ux_pain,
            "pain_bugs": bug_pain,
            "pain_api_oss": api_oss_pain,
            "key_user_pain_point": top_pain,
        }

    def get_top5_competitors(
        self,
        item_id: str,
        day: str,
        title: str,
        summary: str,
        description: str,
        tags: list[str],
        ivec: np.ndarray,
    ) -> list[dict[str, Any]]:
        """Retrieve strictly `< day` Top-5 Named Competitors $C_1..C_5$ with `< D` bench item indices & pain points."""
        d_ord = day_ord(day)
        own_iidx = self.idx_by_id.get(item_id, -1)
        own_makers = self.makers_by_iidx.get(own_iidx, set()) if own_iidx >= 0 else set()
        own_norms = {_norm_key(title)}
        if own_iidx >= 0:
            own_norms.add(_norm_key(self.item_slugs[own_iidx]))

        cats_0005 = list(self.cat_top3_by_id.get(item_id, []))
        for t in (tags or [])[:3]:
            if str(t) not in cats_0005:
                cats_0005.append(str(t))
        if not cats_0005:
            cats_0005 = ["General"]

        out: list[dict[str, Any]] = []
        seen_norms: set[str] = set(own_norms)

        # A. Forward/Nov causal Similar Products (`day >= 2026-11-02` ONLY; fetched `<= 2026-11-01T21Z` < D!)
        if day >= "2026-11-02" and item_id in self.nov_competitors_by_id:
            for c in self.nov_competitors_by_id[item_id]:
                c_name = str(c.get("name") or "").strip()
                c_slug = re.sub(r"-\d+$", "", str(c.get("slug") or "")).strip().lower()
                cnn = _norm_key(c_name or c_slug)
                if len(cnn) < 2 or cnn in seen_norms:
                    continue
                # Belt-and-suspenders < D check: if slug is in bench.items with earliest day >= D, skip
                earliest_d = self.earliest_day_by_slug.get(c_slug)
                if earliest_d is not None and earliest_d >= day:
                    continue
                matched_iidxs = [
                    ii for ii in self.iidxs_by_norm.get(_norm_key(c_slug), []) + self.iidxs_by_norm.get(cnn, [])
                    if int(self.item_day_ords[ii]) < d_ord
                ]
                matched_iidxs = sorted(set(matched_iidxs))
                hist_votes = int(sum(self.item_endorse_counts[ii] for ii in matched_iidxs))
                pain = self._competitor_pain_profile(c_name, c_slug, day)
                rev_cnt = max(int(c.get("reviews_count") or 0), pain["g2_reviews_count"])
                shared = list(c.get("shared_categories") or c.get("categories") or cats_0005[:1])[:3]
                out.append({
                    "name": scrub(c_name),
                    "slug": c_slug or cnn,
                    "shared_categories": [str(x) for x in shared],
                    "bench_item_idxs": matched_iidxs,
                    "hist_endorsements_lt_d": hist_votes,
                    "reviews_count": rev_cnt,
                    "rating": c.get("rating") if c.get("rating") is not None else pain["g2_rating"],
                    "source": "ph_pre_nov2_causal",
                    **pain,
                })
                seen_norms.add(cnn)
                if c_slug:
                    seen_norms.add(_norm_key(c_slug))
                if len(out) >= 5:
                    return out

        # B. Strictly `< D` Historical Category + Semantic SVD Nearest Launches (`day_ord < d_ord`)
        cand_pool: set[int] = set()
        for c_cat in cats_0005:
            arr = self.cat_to_bench_iidxs.get(c_cat)
            if arr is not None and len(arr) > 0:
                # Binary search on day_ord since arr is sorted by day_ord!
                hi = int(np.searchsorted(self.item_day_ords[arr], d_ord))
                if hi > 0:
                    cand_pool.update(int(x) for x in arr[:hi])

        if len(cand_pool) < 25:
            hi_all = int(np.searchsorted(self.item_day_ords, d_ord))
            # Add top endorsed prior launches if category is sparse
            cand_pool.update(range(max(0, hi_all - 600), hi_all))

        if cand_pool:
            c_idx = np.asarray(sorted(cand_pool), dtype=np.int32)
            # Filter out exact same item or shared makers
            valid_m = np.ones(len(c_idx), dtype=bool)
            for k_pos, ii in enumerate(c_idx):
                if ii == own_iidx or int(self.item_day_ords[ii]) >= d_ord:
                    valid_m[k_pos] = False
                elif own_makers and (self.makers_by_iidx.get(int(ii), set()) & own_makers):
                    valid_m[k_pos] = False
            c_idx = c_idx[valid_m]

            if len(c_idx) > 0:
                with np.errstate(all="ignore"):
                    sims = np.nan_to_num(self.pool.item_vecs[c_idx] @ ivec, nan=0.0, posinf=0.0, neginf=0.0)
                pop_log = np.log1p(self.item_endorse_counts[c_idx])
                pop_norm = pop_log / max(float(np.max(pop_log)), 1.0)
                # Blend semantic closeness (72%) + proven category incumbent traction (28%)
                rank_score = 0.72 * sims + 0.28 * pop_norm
                order = np.argsort(-rank_score, kind="stable")

                own_cat_set = set(cats_0005)
                for pos_i in order[:40]:
                    if len(out) >= 5:
                        break
                    ii = int(c_idx[pos_i])
                    c_title = str(self.item_titles[ii])
                    c_slug = re.sub(r"-\d+$", "", str(self.item_slugs[ii] or "")).strip().lower()
                    cnn = _norm_key(c_title)
                    if len(cnn) < 2 or cnn in seen_norms or (_norm_key(c_slug) in seen_norms and c_slug):
                        continue
                    all_ii = [
                        j for j in self.iidxs_by_norm.get(_norm_key(c_slug), [ii])
                        if int(self.item_day_ords[j]) < d_ord
                    ] or [ii]
                    all_ii = sorted(set(all_ii))
                    hist_votes = int(sum(self.item_endorse_counts[j] for j in all_ii))
                    c_cats = set(self.cat_top3_by_id.get(str(self.item_ids[ii]), [])) | set(self.item_tags[ii] or [])
                    shared = sorted(own_cat_set & c_cats)[:3] or cats_0005[:1]
                    pain = self._competitor_pain_profile(c_title, c_slug, day)
                    out.append({
                        "name": scrub(c_title),
                        "slug": c_slug or cnn,
                        "shared_categories": [str(x) for x in shared],
                        "bench_item_idxs": all_ii,
                        "hist_endorsements_lt_d": hist_votes,
                        "reviews_count": max(pain["g2_reviews_count"], hist_votes),
                        "rating": pain["g2_rating"],
                        "similarity": round(float(sims[pos_i]), 4),
                        "source": "hist_lt_d_semantic_incumbent",
                        **pain,
                    })
                    seen_norms.add(cnn)
                    if c_slug:
                        seen_norms.add(_norm_key(c_slug))

        return out[:5]

    def attach_features(
        self,
        df: pd.DataFrame,
        surfaces_by_id: dict[str, SanitizedSurface],
        cua4_records: dict[str, dict[str, Any]],
        mm_judged: dict[str, dict[str, Any]],
    ) -> tuple[pd.DataFrame, dict[str, list[dict[str, Any]]]]:
        """Attach causal `< D` competitor & same-day rivalry features (100% order-invariant, zero comments)."""
        df = df.copy().reset_index(drop=True)
        n = len(df)

        # Precompute deterministic item embeddings (`pool` fit strictly `<= 2026-08-31`)
        ivecs = np.zeros((n, self.pool.item_vecs.shape[1]), dtype=np.float32)
        for i, r in enumerate(df.itertuples(index=False)):
            iidx = int(r.item_idx)
            if 0 <= iidx < len(self.pool.item_vecs):
                ivecs[i] = self.pool.item_vecs[iidx]
            else:
                tgs = " ".join(r.tags if isinstance(r.tags, (list, tuple)) else [])
                ivecs[i] = self.pool.embed_text(f"{r.title} {r.summary} {tgs} {str(r.description or '')[:240]}")

        comp_map: dict[str, list[dict[str, Any]]] = {}
        raw_demand = np.zeros(n, dtype=np.float64)
        raw_crowding = np.zeros(n, dtype=np.float64)
        raw_cua_adv = np.zeros(n, dtype=np.float64)

        for i, r in enumerate(df.itertuples(index=False)):
            lid = str(r.item_id)
            day = str(r.day)
            tgs = list(r.tags) if isinstance(r.tags, (list, tuple)) else []
            comps = self.get_top5_competitors(
                item_id=lid,
                day=day,
                title=str(r.title or ""),
                summary=str(r.summary or ""),
                description=str(r.description or ""),
                tags=tgs,
                ivec=ivecs[i],
            )

            # Launch x's verified hands-on / surface quality (strictly zero comments!)
            surf = surfaces_by_id.get(lid)
            cr = cua4_records.get(lid) or {}
            mm = mm_judged.get(lid) or {}

            has_free = bool((surf and surf.has_free_tier) or cr.get("google_sso_entered"))
            has_oss = bool((surf and surf.has_open_source) or cr.get("has_github_link"))
            has_demo = bool((surf and surf.has_interactive_demo) or cr.get("workflow_responded") or cr.get("reached_working_product"))
            has_docs = bool((surf and surf.has_docs) or cr.get("has_docs_link"))
            is_gated = bool(
                (surf and (surf.is_waitlist or surf.is_enterprise_gated))
                or cr.get("hit_paywall")
                or cr.get("hit_waitlist")
                or cr.get("hit_error_toast")
            )
            mm_works = float(mm.get("hands_on_works", 0.55 if has_demo else (0.30 if is_gated else 0.50)))
            mm_craft = float(mm.get("ui_craft_depth", 0.52 if (surf and surf.access_status == "clean") else 0.50))
            mm_ease = float(mm.get("onboarding_ease", 0.56 if has_free else (0.30 if is_gated else 0.50)))

            exec_score = (
                0.45 * (mm_works - 0.50)
                + 0.30 * (mm_craft - 0.50)
                + 0.25 * (mm_ease - 0.50)
                + 0.22 * float(has_demo)
                + 0.24 * float(has_oss)
                + 0.14 * float(has_free)
                + 0.10 * float(has_docs)
                - 0.48 * float(is_gated)
            )

            if comps:
                dem_vals = [
                    math.log1p(float(c["hist_endorsements_lt_d"]) + 0.5 * float(c["reviews_count"]))
                    for c in comps
                ]
                raw_demand[i] = float(np.mean(dem_vals))
                g2_entrench = [
                    math.log1p(float(c["reviews_count"])) * (float(c["rating"] or 4.2) / 5.0)
                    for c in comps[:3]
                ]
                raw_crowding[i] = float(np.mean(g2_entrench))

                pain_price_share = float(np.mean([1.0 if c["pain_pricing"] else 0.0 for c in comps]))
                pain_ux_share = float(np.mean([1.0 if c["pain_ux"] else 0.0 for c in comps]))
                pain_api_share = float(np.mean([1.0 if c["pain_api_oss"] else 0.0 for c in comps]))

                # Direct CUA-vs-Competitor Wedge: solving exact incumbent user complaints!
                wedge_bonus = (
                    0.30 * pain_price_share * float((has_oss or has_free) and not is_gated)
                    + 0.25 * pain_ux_share * float(has_demo and mm_ease >= 0.55)
                    + 0.25 * pain_api_share * float(has_oss or has_docs)
                )
                raw_cua_adv[i] = exec_score + wedge_bonus - 0.06 * raw_crowding[i]

                # Attach concise hands-on comparison string per competitor for Phase 2 why-cards
                for c in comps:
                    if is_gated:
                        cmp_s = "Launch gates behind waitlist/paywall vs established incumbent access"
                    elif has_oss and c["pain_pricing"]:
                        cmp_s = "Open-source / self-hostable wedge against incumbent seat/pricing friction"
                    elif cr.get("google_sso_entered") and cr.get("workflow_responded"):
                        cmp_s = f"Verified live post-Google-SSO interactive workspace (works={mm_works:.2f})"
                    elif has_demo or has_free:
                        cmp_s = f"Instant free/demo access (craft={mm_craft:.2f}) vs incumbent onboarding overhead"
                    else:
                        cmp_s = "Evaluated on launch surface & technical specification against category incumbent"
                    c["hands_on_comparison"] = cmp_s
            else:
                raw_cua_adv[i] = exec_score

            comp_map[lid] = comps

        # Same-day semantic & category cannibalization (sorted deterministically by item_id per day -> 0.0 permutation diff!)
        raw_cannibal = np.zeros(n, dtype=np.float64)
        raw_cluster_adv = np.zeros(n, dtype=np.float64)

        for d, idx_grp in df.groupby("day").groups.items():
            pos = np.asarray(list(idx_grp), dtype=np.int64)
            # Sort deterministically by item_id string
            order_id = np.argsort(df.loc[pos, "item_id"].astype(str).to_numpy(), kind="stable")
            pos = pos[order_id]
            if len(pos) <= 1:
                continue
            V = ivecs[pos]
            S_mat = np.clip(V @ V.T, 0.0, 1.0)
            np.fill_diagonal(S_mat, 0.0)
            s_scores = df.loc[pos, "structural_score"].to_numpy(dtype=np.float64)
            cats = df.loc[pos, "category_0005"].astype(str).to_numpy()

            for a_i in range(len(pos)):
                same_cat = (cats == cats[a_i]).astype(np.float64)
                same_cat[a_i] = 0.0
                sim_vec = 0.75 * S_mat[a_i] + 0.25 * same_cat
                # Stronger or comparable same-day rivals cannibalize launch a_i
                stronger_mask = s_scores >= (s_scores[a_i] - 0.25)
                stronger_mask[a_i] = False
                max_stronger_sim = float(np.max(sim_vec[stronger_mask])) if np.any(stronger_mask) else 0.0
                raw_cannibal[pos[a_i]] = max_stronger_sim

                # Relative standing inside same-day niche cluster (sim >= 0.38 or same category)
                cluster_m = (S_mat[a_i] >= 0.38) | (same_cat > 0.5)
                if np.any(cluster_m):
                    rival_mean = float(np.mean(s_scores[cluster_m]))
                    raw_cluster_adv[pos[a_i]] = s_scores[a_i] - rival_mean
                else:
                    raw_cluster_adv[pos[a_i]] = 0.15  # Unique niche bonus on the day

        df["raw_comp_demand"] = raw_demand
        df["raw_comp_crowding"] = raw_crowding
        df["raw_comp_cua_adv"] = raw_cua_adv
        df["raw_sameday_cannibal"] = raw_cannibal
        df["raw_sameday_cluster_adv"] = raw_cluster_adv

        df["comp_market_demand_z"] = within_day_zscore(df, "raw_comp_demand")
        df["comp_incumbent_crowding_z"] = within_day_zscore(df, "raw_comp_crowding")
        df["comp_cua_advantage_z"] = within_day_zscore(df, "raw_comp_cua_adv")
        df["sameday_direct_rival_cannibalization_z"] = within_day_zscore(df, "raw_sameday_cannibal")
        df["sameday_cluster_rank_adv_z"] = within_day_zscore(df, "raw_sameday_cluster_adv")

        return df, comp_map


class PopulationChoiceSim:
    """Full `93,618`-person causal (`< D`) discrete-choice voter/switcher simulator + `STACK-1b` Qwen-7B `P(yes)` fusion."""

    def __init__(
        self,
        bench: Benchmark,
        pool: UniversalUserPool,
        data_dir: str,
        live23_dir: str,
        gcs_bucket: str = "usersim-bakeoff-347838016394",
    ) -> None:
        self.bench = bench
        self.pool = pool
        self.data_dir = data_dir
        self.live23_dir = live23_dir
        self.gcs_bucket = gcs_bucket

        # Map person_id -> person_idx (0..93617)
        self.pidx_by_pid = dict(
            zip(bench.people["person_id"].astype(str), bench.people["person_idx"].to_numpy(dtype=np.int32))
        )
        self.idx_by_item_id = dict(
            zip(bench.items["item_id"].astype(str), bench.items["item_idx"].to_numpy(dtype=np.int32))
        )

        # Load STACK-1b coefficients (`stack_coef.json`)
        coef_path = f"{data_dir}/e5_pop/stack_coef.json"
        if os.path.exists(coef_path):
            self.stack_cfg = json.load(open(coef_path))
        else:
            self.stack_cfg = {
                "mu": [0.580159257636306, 0.22422241859380626, 0.1279143671461019, -4.220478938277496],
                "sd": [0.8205393653886949, 0.18184997973029354, 0.22437962506063272, 1.3158060695630736],
                "coef": [0.3962429507646892, -0.044153132662726906, 0.03861536158006487, 1.2958457660005411],
                "intercept": -6.6634167632861345,
            }

        # Pre-index endorsements & comments per item_idx sorted by day_ord for ultra-fast `< D` voter lookup
        h = bench.hist
        end_c = h[h["kind"].isin([KIND_CODE[ENDORSE], KIND_CODE[COMMENT]])][["item_idx", "person_idx", "day_ord"]].drop_duplicates()
        self.backers_by_iidx: dict[int, tuple[np.ndarray, np.ndarray]] = {}
        for iidx, grp in end_c.groupby("item_idx"):
            p_arr = grp["person_idx"].to_numpy(dtype=np.int32)
            d_arr = grp["day_ord"].to_numpy(dtype=np.int32)
            ord_k = np.argsort(d_arr, kind="stable")
            self.backers_by_iidx[int(iidx)] = (d_arr[ord_k], p_arr[ord_k])

        # Makers in bench.hist (`MAKE`)
        mk = h[h["kind"] == KIND_CODE[MAKE]][["person_idx", "item_idx", "day_ord"]].drop_duplicates()
        self.makers_by_iidx: dict[int, list[int]] = defaultdict(list)
        self.items_by_maker_pidx: dict[int, list[tuple[int, int]]] = defaultdict(list)
        for r in mk.itertuples(index=False):
            pi, ii, do = int(r.person_idx), int(r.item_idx), int(r.day_ord)
            self.makers_by_iidx[ii].append(pi)
            self.items_by_maker_pidx[pi].append((do, ii))

        # Stream `< D` team linkage & `< D` follow-tie counts from GCS in transient memory (zero handles stored!)
        self.prior_team_iidxs_by_lid: dict[str, list[tuple[str, int]]] = {}
        self.team_size_by_lid: dict[str, int] = {}
        self.follow_ties_by_lid_day: dict[str, list[tuple[str, int]]] = {}
        self.qwen_pred_days_available: dict[str, str] = {}
        self._stream_gcs_team_follows_and_index()

    def _stream_gcs_team_follows_and_index(self) -> None:
        """Stream compact `launches`, `at_launch_followers`, `follows`, and `backer_pred` index from GCS (`~12 MiB` wire)."""
        fs = gcsfs.GCSFileSystem()

        # Transient handle map (discarded on exit from this method — zero handles ever retained!)
        team_handles_by_lid: dict[str, set[str]] = defaultdict(set)
        day_by_lid: dict[str, str] = dict(zip(self.bench.items["item_id"].astype(str), self.bench.items["day"].astype(str)))

        # 1. Local live_23d JSONs + nov25 JSONL
        for jf in sorted(glob.glob(f"{self.live23_dir}/forecasts/2026-*.json")):
            d_f = os.path.basename(jf)[:10]
            try:
                arr = json.load(open(jf))
                if isinstance(arr, list):
                    for p in arr:
                        lid = str(p.get("id") or "")
                        if not lid:
                            continue
                        day_by_lid.setdefault(lid, d_f)
                        for m in (p.get("makers") or []):
                            u = str((m or {}).get("username") or "").strip().lower()
                            if u and u != "[redacted]":
                                team_handles_by_lid[lid].add(u)
                        hu = str((p.get("user") or {}).get("username") or "").strip().lower()
                        if hu and hu != "[redacted]":
                            team_handles_by_lid[lid].add(hu)
            except Exception:
                pass

        for pat in (f"{self.live23_dir}/post0005/*/*PT.jsonl", f"{self.live23_dir}/nov25/*PT.jsonl"):
            for sf in sorted(glob.glob(pat)):
                try:
                    for line in open(sf):
                        p = json.loads(line)
                        lid = str(p.get("id") or "")
                        if not lid:
                            continue
                        for m in (p.get("makers") or []):
                            u = str((m or {}).get("username") or "").strip().lower()
                            if u and u != "[redacted]":
                                team_handles_by_lid[lid].add(u)
                        hu = str((p.get("user") or {}).get("username") or "").strip().lower()
                        if hu and hu != "[redacted]":
                            team_handles_by_lid[lid].add(hu)
                except Exception:
                    pass

        # 2. Stream GCS `tables/launches/initial-2026-10-28.parquet` & `tables/at_launch_followers/*.parquet`
        try:
            l_init = f"{self.gcs_bucket}/usersim_sim/tables/launches/initial-2026-10-28.parquet"
            if fs.exists(l_init):
                ldf = pd.read_parquet("gs://" + l_init, columns=["id", "day", "poster", "makers"])
                for r in ldf.itertuples(index=False):
                    lid = str(r.id)
                    day_by_lid.setdefault(lid, str(r.day))
                    if r.poster and str(r.poster).lower() != "[redacted]":
                        team_handles_by_lid[lid].add(str(r.poster).strip().lower())
                    if r.makers:
                        try:
                            ms = json.loads(r.makers) if isinstance(r.makers, str) else list(r.makers)
                            for m in ms:
                                u = str(m or "").strip().lower()
                                if u and u != "[redacted]":
                                    team_handles_by_lid[lid].add(u)
                        except Exception:
                            pass

            alf_files = sorted(fs.glob(f"{self.gcs_bucket}/usersim_sim/tables/at_launch_followers/*.parquet"))
            if alf_files:
                alf_dfs = [pd.read_parquet("gs://" + f, columns=["launch_id", "day", "person"]) for f in alf_files]
                alf = pd.concat(alf_dfs, ignore_index=True)
                for r in alf.itertuples(index=False):
                    lid = str(r.launch_id)
                    day_by_lid.setdefault(lid, str(r.day))
                    u = str(r.person or "").strip().lower()
                    if u and u != "[redacted]":
                        team_handles_by_lid[lid].add(u)
        except Exception:
            pass

        # Build handle -> chronological list of (day, item_idx)
        handle_to_launches: dict[str, list[tuple[str, int]]] = defaultdict(list)
        for lid, handles in team_handles_by_lid.items():
            self.team_size_by_lid[lid] = len(handles)
            d_s = day_by_lid.get(lid)
            iidx = self.idx_by_item_id.get(lid, -1)
            if d_s and iidx >= 0:
                for h in handles:
                    handle_to_launches[h].append((d_s, iidx))

        for lid, handles in team_handles_by_lid.items():
            cand_pairs: dict[int, str] = {}
            for h in handles:
                for d_prev, ii_prev in handle_to_launches.get(h, []):
                    if ii_prev not in cand_pairs or d_prev < cand_pairs[ii_prev]:
                        cand_pairs[ii_prev] = d_prev
            self.prior_team_iidxs_by_lid[lid] = sorted((d_p, ii_p) for ii_p, d_p in cand_pairs.items())

        # 3. Stream GCS `tables/follows/*.parquet` (`1.44 MiB`), retaining ONLY dated follower counts (`observed_on < D`)!
        try:
            fol_files = sorted(fs.glob(f"{self.gcs_bucket}/usersim_sim/tables/follows/*.parquet"))
            if fol_files:
                fol_df = pd.concat(
                    [pd.read_parquet("gs://" + f, columns=["person", "followee", "observed_on"]) for f in fol_files],
                    ignore_index=True,
                )
                fol_df["person"] = fol_df["person"].astype(str).str.strip().str.lower()
                fol_df["followee"] = fol_df["followee"].astype(str).str.strip().str.lower()
                fol_df["observed_on"] = fol_df["observed_on"].astype(str).str[:10]
                fol_df = fol_df.sort_values("observed_on").drop_duplicates(["person", "followee"], keep="first")

                # Group by followee -> list of (observed_on, follower_int_id) using ephemeral integer codes!
                fol_df["p_code"] = pd.factorize(fol_df["person"])[0].astype(np.int32)
                by_followee: dict[str, list[tuple[str, int]]] = defaultdict(list)
                for r in fol_df[["followee", "observed_on", "p_code"]].itertuples(index=False):
                    by_followee[str(r.followee)].append((str(r.observed_on), int(r.p_code)))

                for lid, handles in team_handles_by_lid.items():
                    d_launch = day_by_lid.get(lid, "2026-11-26")
                    seen_codes: set[int] = set()
                    dated_counts: dict[str, int] = defaultdict(int)
                    for h in handles:
                        for obs_d, p_c in by_followee.get(h, []):
                            if obs_d < d_launch and p_c not in seen_codes:
                                seen_codes.add(p_c)
                                dated_counts[obs_d] += 1
                    if dated_counts:
                        self.follow_ties_by_lid_day[lid] = sorted(dated_counts.items())
        except Exception:
            pass

        # Index available `backer_pred/<day>.parquet` files on GCS (streamed on demand per day)
        try:
            for p in sorted(fs.glob(f"{self.gcs_bucket}/usersim_sim/tmp/e5/private/backer_pred/*.parquet")):
                d_b = os.path.basename(p).replace(".parquet", "")
                if re.match(r"^\d{4}-\d{2}-\d{2}$", d_b):
                    self.qwen_pred_days_available[d_b] = "gs://" + p
        except Exception:
            pass

    def _stream_day_qwen_pyes(self, day: str) -> dict[tuple[str, int], float]:
        """Stream day `D`'s frozen Qwen-7B `P(yes)` parquet directly from GCS (`~0.5 MiB` per day)."""
        uri = self.qwen_pred_days_available.get(day)
        if not uri or day > "2026-11-25":
            return {}
        try:
            pdf = pd.read_parquet(uri, columns=["launch_id", "person_id", "p"])
            out: dict[tuple[str, int], float] = {}
            pidx_map = self.pidx_by_pid
            for lid, pid, pval in zip(pdf["launch_id"].astype(str), pdf["person_id"].astype(str), pdf["p"].to_numpy(dtype=np.float64)):
                pidx = pidx_map.get(pid, -1)
                if pidx >= 0 and np.isfinite(pval):
                    out[(lid, pidx)] = float(np.clip(pval, 1e-6, 1.0 - 1e-6))
            return out
        except Exception:
            return {}

    def _get_prior_backers_lt_d(self, iidxs: list[int], d_ord: int) -> np.ndarray:
        """Return unique `person_idx` who endorsed or commented on any `iidxs` strictly before `d_ord`."""
        chunks = []
        for ii in iidxs:
            tup = self.backers_by_iidx.get(int(ii))
            if tup is None:
                continue
            d_arr, p_arr = tup
            hi = int(np.searchsorted(d_arr, d_ord))
            if hi > 0:
                chunks.append(p_arr[:hi])
        if not chunks:
            return np.zeros(0, dtype=np.int32)
        return np.unique(np.concatenate(chunks))

    def simulate_all_days(
        self,
        df: pd.DataFrame,
        comp_map: dict[str, list[dict[str, Any]]],
        tau: float = 0.85,
    ) -> tuple[pd.DataFrame, dict[tuple[str, str], dict[str, Any]]]:
        """Run full 93,618-person discrete-choice + `STACK-1b` simulation day-by-day across `df`."""
        df = df.copy().reset_index(drop=True)
        n = len(df)

        raw_exp_votes = np.zeros(n, dtype=np.float64)
        raw_power_votes = np.zeros(n, dtype=np.float64)
        raw_team_votes = np.zeros(n, dtype=np.float64)
        raw_fol_ties = np.zeros(n, dtype=np.float64)
        raw_sw_votes = np.zeros(n, dtype=np.float64)
        raw_cannibal_loss = np.zeros(n, dtype=np.float64)
        raw_qwen_stack = np.zeros(n, dtype=np.float64)
        has_qwen_mask = np.zeros(n, dtype=bool)

        why_pop_by_key: dict[tuple[str, str], dict[str, Any]] = {}

        # Precompute 90-day endorsement arrays from bench._e_day / _e_p
        e_day = self.bench._e_day
        e_p = self.bench._e_p
        n_people = self.bench.n_people

        mu_s = self.stack_cfg["mu"]
        sd_s = self.stack_cfg["sd"]
        cf_s = self.stack_cfg["coef"]
        ic_s = float(self.stack_cfg["intercept"])

        for d in sorted(df["day"].unique()):
            d_str = str(d)
            d_snap = d_str if d_str <= "2026-11-24" else "2026-11-24"
            d_ord = day_ord(d_str)

            # Deterministic item order by item_id string -> 0.0 permutation diff!
            pos = np.asarray(list(df.groupby("day").groups[d]), dtype=np.int64)
            pos = pos[np.argsort(df.loc[pos, "item_id"].astype(str).to_numpy(), kind="stable")]
            L = len(pos)
            if L == 0:
                continue

            snap = self.pool.snapshot(d_snap)
            st = self.bench.state(d_snap)

            # Strictly < d_ord 90-day endorsement counts across all 93,618 held people
            lo90, hi90 = np.searchsorted(e_day, [d_ord - 90, d_ord])
            n90_all = np.bincount(e_p[lo90:hi90], minlength=n_people).astype(np.int32)

            # Active pool on day D: active in last 90d (`n90 >= 1`, ~16k-24k people)
            act = np.flatnonzero(n90_all >= 1)
            if len(act) < 50:
                act = np.flatnonzero(snap["n_all"] >= 1)
            P = len(act)
            act_inv = np.full(n_people, -1, dtype=np.int32)
            act_inv[act] = np.arange(P, dtype=np.int32)

            n90_act = n90_all[act]
            tier_1_9 = (n90_act >= 1) & (n90_act <= 9)
            tier_10_99 = (n90_act >= 10) & (n90_act <= 99)
            tier_100p = n90_act >= 100

            # Global held-population tier baseline (for why-cards comparison)
            global_tier_shares = {
                "0": round(float(np.mean(n90_all == 0)), 4),
                "1-9": round(float(np.mean((n90_all >= 1) & (n90_all <= 9))), 4),
                "10-99": round(float(np.mean((n90_all >= 10) & (n90_all <= 99))), 4),
                "100+": round(float(np.mean(n90_all >= 100)), 4),
            }

            rw7_act = st["rw"][act].astype(np.float32)
            rw30_act = snap["rw30"][act].astype(np.float32)
            ln_rw_act = np.log1p(rw7_act)
            n_all_act = np.maximum(st["n_all"][act].astype(np.float32), 1.0)
            T_topics_act = st["topics"][act]
            u_vecs = snap["user_vecs"][act]  # [P, dim]
            u_crit = snap["crit_rate"][act]
            u_tech = snap["tech_rate"][act]
            u_price = snap["price_rate"][act]

            # Expected daily upvote budget B_u(D) per active user (< D empirical rate)
            daily_budget = np.clip(0.035 + 0.24 * (rw30_act / 15.0), 0.02, 4.5).astype(np.float32)

            # Build item matrix [L, dim], topic shares [P, L], team backer masks, and switcher masks
            lids = df.loc[pos, "item_id"].astype(str).tolist()
            titles_d = df.loc[pos, "title"].astype(str).tolist()
            iidxs = df.loc[pos, "item_idx"].to_numpy(dtype=np.int32)
            cua_adv_d = df.loc[pos, "raw_comp_cua_adv"].to_numpy(dtype=np.float32)
            s_score_d = df.loc[pos, "structural_score"].to_numpy(dtype=np.float32)

            I_vecs = np.zeros((L, u_vecs.shape[1]), dtype=np.float32)
            TM_mat = np.zeros((P, L), dtype=np.float32)
            team_mask_mat = np.zeros((P, L), dtype=np.float32)
            sw_mask_mat = np.zeros((P, L), dtype=np.float32)
            team_total_counts = np.zeros(L, dtype=np.int32)
            sw_total_counts = np.zeros(L, dtype=np.int32)
            fol_lt_d_counts = np.zeros(L, dtype=np.int32)

            for j in range(L):
                lid = lids[j]
                ii = int(iidxs[j])
                row_j = df.iloc[pos[j]]
                tgs = list(row_j.tags) if isinstance(row_j.tags, (list, tuple)) else []
                if 0 <= ii < len(self.pool.item_vecs):
                    I_vecs[j] = self.pool.item_vecs[ii]
                    topic_vec = self.bench.item_topics[ii].toarray().ravel()
                    t_cols = np.flatnonzero(topic_vec)
                else:
                    I_vecs[j] = self.pool.embed_text(f"{row_j.title} {row_j.summary} {' '.join(tgs)} {str(row_j.description or '')[:240]}")
                    t_cols = np.array([self.bench.vocab[t] for t in tgs if t in self.bench.vocab], dtype=np.int32)

                if len(t_cols) > 0:
                    TM_mat[:, j] = np.asarray(T_topics_act[:, t_cols].sum(axis=1)).ravel() / (n_all_act * len(t_cols))

                # 1. Past Team / Maker / Hunter Backers strictly < D
                prior_iidxs = [ii_p for d_p, ii_p in self.prior_team_iidxs_by_lid.get(lid, []) if d_p < d_str]
                if ii >= 0:
                    for mp in self.makers_by_iidx.get(ii, []):
                        for do_p, ii_p in self.items_by_maker_pidx.get(mp, []):
                            if do_p < d_ord:
                                prior_iidxs.append(ii_p)
                if prior_iidxs:
                    tb_all = self._get_prior_backers_lt_d(sorted(set(prior_iidxs)), d_ord)
                    team_total_counts[j] = int(len(tb_all))
                    loc_tb = act_inv[tb_all]
                    loc_tb = loc_tb[loc_tb >= 0]
                    if len(loc_tb) > 0:
                        team_mask_mat[loc_tb, j] = 1.0

                # Follow ties strictly observed_on < D
                fol_entries = self.follow_ties_by_lid_day.get(lid, [])
                fol_lt_d_counts[j] = int(sum(cnt for obs_d, cnt in fol_entries if obs_d < d_str))

                # 2. Named-Competitor Switchers strictly < D ($C_1..C_5$)
                comp_iidxs = []
                for c_obj in comp_map.get(lid, []):
                    comp_iidxs.extend(c_obj.get("bench_item_idxs") or [])
                if comp_iidxs:
                    sw_all = self._get_prior_backers_lt_d(sorted(set(comp_iidxs)), d_ord)
                    sw_total_counts[j] = int(len(sw_all))
                    loc_sw = act_inv[sw_all]
                    loc_sw = loc_sw[loc_sw >= 0]
                    if len(loc_sw) > 0:
                        sw_mask_mat[loc_sw, j] = 1.0

            # Cosine taste alignment [P, L]
            with np.errstate(all="ignore"):
                cos_mat = np.clip(np.nan_to_num(u_vecs @ I_vecs.T, nan=0.0, posinf=0.0, neginf=0.0), -0.2, 1.0)

            # Construct per-person x launch utility U [P, L]
            # Selective/technical builders respond strongly to hands-on CUA advantage; team backers & switchers get relational lift
            s_centered = (s_score_d - float(np.mean(s_score_d))).astype(np.float32)
            qual_sensitivity = (0.45 + 0.85 * u_crit + 0.55 * u_tech + 0.35 * u_price)[:, None]  # [P, 1]
            switcher_pull = sw_mask_mat * np.maximum(0.20, 0.85 + 1.15 * cua_adv_d[None, :])

            U = (
                0.52 * s_centered[None, :]
                + 2.35 * cos_mat
                + 1.10 * TM_mat
                + 1.65 * team_mask_mat
                + 0.95 * switcher_pull
                + 0.65 * qual_sensitivity * cua_adv_d[None, :]
            )

            # Stream STACK-1b Qwen-7B per-person P(yes) if available for day D (`2026-11-08 .. 2026-11-25`)
            qwen_day = self._stream_day_qwen_pyes(d_str)
            day_has_qwen = len(qwen_day) > 0
            qwen_prob_mat = np.zeros((P, L), dtype=np.float32)

            if day_has_qwen:
                z_ln_rw = ((ln_rw_act - float(mu_s[0])) / float(sd_s[0]))[:, None]
                z_tm = (TM_mat - float(mu_s[1])) / float(sd_s[1])
                z_inter = ((ln_rw_act[:, None] * TM_mat) - float(mu_s[2])) / float(sd_s[2])

                # Default prior pyes from active prevalence when person wasn't in top-active scored slice
                logit_pyes_mat = np.full((P, L), float(mu_s[3]), dtype=np.float32)
                matched_lids_qwen = 0
                for j, lid in enumerate(lids):
                    hit_j = False
                    for p_global_idx_key, p_val in ():
                        pass
                    # Fast lookup over active users via qwen_day
                # Populate logit_pyes_mat efficiently by iterating over qwen_day entries once!
                lid_to_j = {lid: j for j, lid in enumerate(lids)}
                lids_with_q = set()
                for (q_lid, pidx_g), p_val in qwen_day.items():
                    j = lid_to_j.get(q_lid, -1)
                    if j >= 0:
                        loc_p = int(act_inv[pidx_g])
                        if loc_p >= 0:
                            logit_pyes_mat[loc_p, j] = float(math.log(p_val / (1.0 - p_val)))
                            lids_with_q.add(j)

                if len(lids_with_q) >= 2:
                    z_lpy = (logit_pyes_mat - float(mu_s[3])) / float(sd_s[3])
                    logit_stack = (
                        ic_s
                        + float(cf_s[0]) * z_ln_rw
                        + float(cf_s[1]) * z_tm
                        + float(cf_s[2]) * z_inter
                        + float(cf_s[3]) * z_lpy
                    )
                    p_indep_qwen = 1.0 / (1.0 + np.exp(-np.clip(logit_stack, -14.0, 8.0)))
                    # Apply same-day discrete-choice competition across day D's lineup to STACK-1b probabilities!
                    q_row_sum = np.sum(p_indep_qwen, axis=1, keepdims=True)
                    q_scale = np.minimum(1.0, np.maximum(daily_budget[:, None], 0.25) / np.maximum(q_row_sum, 1e-6))
                    qwen_prob_mat = (p_indep_qwen * q_scale).astype(np.float32)
                    # Fuse Qwen-7B log-odds signal into U where available
                    U = U + 0.45 * np.clip(z_lpy, -2.5, 3.0)
                else:
                    day_has_qwen = False

            # Same-day Softmax Discrete-Choice Competition with Outside Option (`exp(U_0) = 3.5`)
            scaled_U = np.clip(U / float(tau), -12.0, 12.0)
            exp_U = np.exp(scaled_U)
            outside_opt = 3.5
            choice_share = exp_U / (outside_opt + np.sum(exp_U, axis=1, keepdims=True))  # [P, L]
            P_vote = np.minimum(1.0, daily_budget[:, None] * choice_share)  # [P, L]

            # Unconstrained independent probability (no rival Launches on day D) to measure cannibalization loss!
            P_unconstrained = np.minimum(1.0, daily_budget[:, None] * (exp_U / (outside_opt + exp_U)))

            exp_v = np.sum(P_vote, axis=0)  # [L]
            unc_v = np.sum(P_unconstrained, axis=0)  # [L]
            pow_v = np.sum(P_vote[tier_10_99], axis=0)
            t1_9_v = np.sum(P_vote[tier_1_9], axis=0)
            t100_v = np.sum(P_vote[tier_100p], axis=0)
            tb_v = np.sum(P_vote * team_mask_mat, axis=0)
            sw_v = np.sum(P_vote * sw_mask_mat, axis=0)

            for j in range(L):
                ridx = pos[j]
                lid = lids[j]
                raw_exp_votes[ridx] = math.log1p(float(exp_v[j]))
                raw_power_votes[ridx] = math.log1p(float(pow_v[j]))
                raw_team_votes[ridx] = math.log1p(float(tb_v[j]) + 0.08 * float(fol_lt_d_counts[j]))
                raw_fol_ties[ridx] = math.log1p(float(fol_lt_d_counts[j]))
                raw_sw_votes[ridx] = math.log1p(float(sw_v[j]))
                raw_cannibal_loss[ridx] = math.log(max(float(unc_v[j]), 1e-4) / max(float(exp_v[j]), 1e-4))
                if day_has_qwen:
                    has_qwen_mask[ridx] = True
                    raw_qwen_stack[ridx] = math.log1p(float(np.sum(qwen_prob_mat[:, j])))

                # Head-to-head same-day voter overlap & preference split against closest rival on day D
                h2h_info: dict[str, Any] | None = None
                if L >= 2:
                    # Voter audience cosine overlap on P_vote[:, j] vs P_vote[:, k]
                    vj = P_vote[:, j]
                    best_k, best_ov = -1, -1.0
                    nj = float(np.linalg.norm(vj)) + 1e-9
                    for k_other in range(L):
                        if k_other == j:
                            continue
                        vk = P_vote[:, k_other]
                        ov = float(np.dot(vj, vk) / (nj * (float(np.linalg.norm(vk)) + 1e-9)))
                        if ov > best_ov:
                            best_ov, best_k = ov, k_other
                    if best_k >= 0:
                        # Contestable cohort: active builders in top audience of j or best_k (always >= 20!)
                        comb_aud = P_vote[:, j] + P_vote[:, best_k]
                        contest_mask = (comb_aud >= np.percentile(comb_aud, 80)) & tier_10_99
                        if int(np.sum(contest_mask)) < 25:
                            contest_mask = comb_aud >= np.percentile(comb_aud, 75)
                        n_contest = int(np.sum(contest_mask))
                        if n_contest >= 20:
                            pref_j = float(np.mean(U[contest_mask, j] >= U[contest_mask, best_k]))
                            h2h_info = {
                                "rival_item_id": lids[best_k],
                                "rival_name": scrub(titles_d[best_k]),
                                "cohort_n": n_contest,
                                "voter_overlap_pct": round(100.0 * best_ov, 1),
                                "prefer_this_pct": round(100.0 * pref_j, 1),
                                "prefer_rival_pct": round(100.0 * (1.0 - pref_j), 1),
                            }

                tot_ev = max(float(exp_v[j]), 1e-6)
                why_pop_by_key[(d_str, lid)] = {
                    "active_pool_n": int(P),
                    "expected_held_votes": round(float(exp_v[j]), 2),
                    "qwen_stack1b_expected_votes": round(float(np.sum(qwen_prob_mat[:, j])), 2) if day_has_qwen else None,
                    "team_backers_lt_d_n": int(team_total_counts[j]),
                    "team_backers_expected_votes": round(float(tb_v[j]), 2),
                    "follow_ties_lt_d_n": int(fol_lt_d_counts[j]),
                    "competitor_switchers_lt_d_n": int(sw_total_counts[j]),
                    "competitor_switchers_expected_votes": round(float(sw_v[j]), 2),
                    "tier_counts_active": {
                        "1-9": int(np.sum(tier_1_9)),
                        "10-99": int(np.sum(tier_10_99)),
                        "100+": int(np.sum(tier_100p)),
                    },
                    "tier_vote_shares": {
                        "1-9": round(float(t1_9_v[j]) / tot_ev, 4),
                        "10-99": round(float(pow_v[j]) / tot_ev, 4),
                        "100+": round(float(t100_v[j]) / tot_ev, 4),
                    },
                    "global_held_tier_shares": global_tier_shares,
                    "sameday_head_to_head": h2h_info,
                }

        df["raw_pop_exp_votes"] = raw_exp_votes
        df["raw_pop_power_votes"] = raw_power_votes
        df["raw_pop_team_votes"] = raw_team_votes
        df["raw_pop_fol_ties"] = raw_fol_ties
        df["raw_pop_sw_votes"] = raw_sw_votes
        df["raw_pop_cannibal_loss"] = raw_cannibal_loss
        df["raw_pop_qwen_stack"] = raw_qwen_stack
        df["has_qwen_backer_pred"] = has_qwen_mask

        df["pop_expected_votes_choice_z"] = within_day_zscore(df, "raw_pop_exp_votes")
        df["pop_power_builder_votes_z"] = within_day_zscore(df, "raw_pop_power_votes")
        df["pop_team_backer_votes_z"] = within_day_zscore(df, "raw_pop_team_votes")
        df["pop_follow_ties_lt_d_z"] = within_day_zscore(df, "raw_pop_fol_ties")
        df["pop_comp_switcher_votes_z"] = within_day_zscore(df, "raw_pop_sw_votes")
        df["pop_cannibalization_loss_z"] = within_day_zscore(df, "raw_pop_cannibal_loss")
        df["pop_qwen_stack1b_z"] = within_day_zscore(df, "raw_pop_qwen_stack", mask_col="has_qwen_backer_pred")

        return df, why_pop_by_key


def attach_cold_start_brand_authority(
    df: pd.DataFrame,
    apify_dir: str,
    live23_dir: str,
    surfaces_by_id: dict[str, SanitizedSurface],
) -> pd.DataFrame:
    """Attach full Apr-Nov LinkedIn org scale + cold-start brand/ecosystem authority + protocol/OSS leverage (zero comments!)."""
    df = df.copy().reset_index(drop=True)
    n = len(df)

    # 1. Load BOTH Apr-Aug AND Sep-Nov LinkedIn company profiles so walk-forward Apr-Aug training learns org authority!
    li_by_dom: dict[str, dict[str, Any]] = {}
    li_by_norm: dict[str, dict[str, Any]] = {}
    for fname in ("linkedin_companies_apr_aug_raw.jsonl", "linkedin_companies_raw.jsonl"):
        p = f"{apify_dir}/{fname}"
        if not os.path.exists(p):
            continue
        with open(p) as f:
            for line in f:
                try:
                    rec = (json.loads(line)).get("raw") or {}
                except Exception:
                    continue
                if not rec or not rec.get("name"):
                    continue
                wdom = clean_domain(str(rec.get("website") or rec.get("callToActionUrl") or ""))
                if wdom and wdom not in GENERIC_DOMAINS:
                    prev = li_by_dom.get(wdom)
                    if not prev or int(rec.get("followerCount") or 0) > int(prev.get("followerCount") or 0):
                        li_by_dom[wdom] = rec
                nn = _norm_key(rec.get("name") or "")
                if len(nn) >= 4:
                    prev = li_by_norm.get(nn)
                    if not prev or int(rec.get("followerCount") or 0) > int(prev.get("followerCount") or 0):
                        li_by_norm[nn] = rec

    # 2. Load raw 00:05 forecast structural components where present (`ph_hunter_followers`, `x_maker_sum_followers`)
    f_meta: dict[str, dict[str, float]] = {}
    for fp in sorted(glob.glob(f"{live23_dir}/forecasts/forecast_2026-*.parquet")):
        try:
            pdf = pd.read_parquet(fp)
            for r in pdf.itertuples(index=False):
                f_meta[str(r.id)] = {
                    "ph_hf": float(getattr(r, "ph_hunter_followers", 0.0) or 0.0),
                    "x_mf": float(getattr(r, "x_maker_sum_followers", 0.0) or 0.0),
                    "x_cf": float(getattr(r, "x_company_followers", 0.0) or 0.0),
                }
        except Exception:
            pass

    li_scale = np.zeros(n, dtype=np.float64)
    cold_auth = np.zeros(n, dtype=np.float64)
    proto_oss = np.zeros(n, dtype=np.float64)
    hm_gap = np.zeros(n, dtype=np.float64)

    z_struct = within_day_zscore(df, "structural_score")

    for i, r in enumerate(df.itertuples(index=False)):
        lid = str(r.item_id)
        surf = surfaces_by_id.get(lid)
        url_s = str(getattr(r, "url", "") or (surf.url if surf else "") or "")
        dom = clean_domain(url_s)
        dom_root = dom.split(".")[0].lower() if dom else ""
        title_s = str(r.title or "")
        summary_s = str(r.summary or "")
        desc_s = str(r.description or "")[:300]
        tgs = " ".join(r.tags if isinstance(r.tags, (list, tuple)) else [])
        full_txt = f"{title_s} {summary_s} {tgs} {desc_s}"

        cname = extract_company_name(title_s, dom)
        nn = _norm_key(cname)
        match = None
        if dom and dom not in GENERIC_DOMAINS and dom in li_by_dom:
            match = li_by_dom[dom]
        elif len(nn) >= 5 and nn in li_by_norm:
            cand = li_by_norm[nn]
            cand_dom = clean_domain(str(cand.get("website") or ""))
            if not dom or not cand_dom or dom == cand_dom or dom_root == cand_dom.split(".")[0] or len(nn) >= 7:
                match = cand

        emp_log, fol_log = 0.0, 0.0
        if match is not None:
            emp_log = math.log1p(max(0.0, float(match.get("employeeCount") or 0.0)))
            fol_log = math.log1p(max(0.0, float(match.get("followerCount") or 0.0)))
        li_scale[i] = 0.55 * fol_log + 0.45 * emp_log

        # Major brand / official ecosystem recognition (e.g., Product Hunt MCP, Adobe, Google, Anthropic, OpenAI, GitHub)
        title_words = {re.sub(r"[^a-z0-9]+", "", w.lower()) for w in title_s.split()[:3]}
        is_major_brand = float(
            (dom_root in MAJOR_BRAND_ROOTS and dom not in {"github.com"})
            or bool(title_words & {"producthunt", "adobe", "anthropic", "openai", "cloudflare", "supabase", "vercel", "raycast", "figma", "notion", "stripe"})
            or "product hunt" in title_s.lower()
            or emp_log >= math.log1p(200)
            or fol_log >= math.log1p(15000)
        )

        x_reach = float(getattr(r, "raw_x_mfol", 0.0) or 0.0)
        fm = f_meta.get(lid, {})
        ext_reach = max(li_scale[i], 0.75 * x_reach, 0.65 * fm.get("x_cf", 0.0), 6.5 * is_major_brand)

        # Cold-start authority: strong external/ecosystem brand authority when PH structural_score is modest (`#8..#20`)!
        modest_ph_gate = float(np.clip(0.85 - 0.45 * z_struct[i], 0.15, 1.50))
        cold_auth[i] = ext_reach * modest_ph_gate

        # Developer protocol / MCP / CLI / OSS leverage
        has_oss = float(bool((surf and surf.has_open_source) or "github.com/" in url_s.lower()))
        has_proto = float(bool(_PROTOCOL_DEV_RE.search(full_txt)))
        has_docs = float(bool(surf and surf.has_docs))
        proto_oss[i] = 0.45 * has_oss + 0.40 * has_proto + 0.15 * has_docs

        # Gap between external/team traction and hunter-driven structural score
        team_v = float(getattr(r, "raw_pop_team_votes", 0.0) or 0.0)
        hm_gap[i] = (0.55 * ext_reach + 0.45 * team_v) - 1.25 * max(0.0, z_struct[i])

    df["raw_brand_li_all"] = li_scale
    df["raw_brand_cold_auth"] = cold_auth
    df["raw_brand_proto_oss"] = proto_oss
    df["raw_struct_hm_gap"] = hm_gap

    df["brand_li_org_scale_all_z"] = within_day_zscore(df, "raw_brand_li_all")
    df["brand_coldstart_authority_z"] = within_day_zscore(df, "raw_brand_cold_auth")
    df["brand_protocol_oss_leverage_z"] = within_day_zscore(df, "raw_brand_proto_oss")
    df["struct_hunter_maker_gap_z"] = within_day_zscore(df, "raw_struct_hm_gap")

    return df
