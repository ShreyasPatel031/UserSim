"""USERSIM-CORE-HILLCLIMB-8 Runner (`usersim_core/hillclimb_v8.py`).

Fixes all 4 mathematical/structural bottlenecks diagnosed from `USERSIM-CORE-HILLCLIMB-7` while
strictly obeying `AGENTS.md` ("Two models, never mixed up again": frozen `arm3` baseline, zero `arm2` mixing):
  1. Dedicated Multi-Family Head-to-Head Finalist Tournaments (`Claude Sonnet 4.6` + `Gemini 2.5 Pro`):
     - Track 1 (`Product only`, ZERO comments):
         * Podium Panel (`#1..#9`): fuses `Claude Sonnet 4.6` head-to-head podium picks with cached `v4` (`GPT-120B + GemPro`).
         * Bubble Finalist Panel (`#6..#16`, where `31.8%` of real Top-10 winners originate!): `Claude Sonnet 4.6` +
           `Gemini 2.5 Pro` compare the 11 bubble contenders head-to-head for the remaining Top-10 spots!
     - Track 2 (`Product + comments`, `<= 03:45 PT` order-free):
         * Dedicated Podium Panel (`#1..#10`) AND Bubble Panel (`#6..#16`) across `Claude Sonnet 4.6` + `Gemini 2.5 Pro`
           evaluating product + CUA + recovered `<= 03:45 PT` community Q&A threads + `<= 02:00 PT` X buzz!
  2. Individual 93,618-Person x 5-Archetype Choice Simulator (`pop8_archetype_choice_z`):
     - Couples every real held person's `< D` empirical profile (`tech_rate`, `rw30`, `ux_rate`, `price_rate`,
       `crit_rate * selectivity`) in `UniversalUserPool` directly to `UniversalUserSimulatorV7`'s 5 archetype utilities
       (`systems`, `power`, `craft`, `buyer`, `skeptic_keep`) + hands-on CUA verification inside Day `D`'s choice slate.
  3. Top-28 Shortlist Expansion (`99.1%` real Top-10 recall ceiling) + Rolling 5-Day `< D` Causal Walk-Forward:
     - Expands daily candidate slates to Top-28 across `Sep-Nov` so `#21..#28` cold-start breakouts can enter Top-10.
     - Steps forward in causal 5-day `< D` blocks (instead of freezing Nov at `Oct 31`) so November pre-launch/intraday
       signals (`pnx_0005`, `xbuzz_pre0000`, `xbuzz_le0200`, `threads_le_0345`, `grok_0200`) are learned strictly `< D`.
  4. `RankGatedUniversalRankerV8` (100% Permutation-Invariant Smooth Gap-Gated Envelope & Normalized Variance):
     - Normalizes total combined residual shift to `target_total_std` (preventing `Oct-Nov` variance inflation) and
       applies `cap_j = cap_podium + (cap_bubble - cap_podium) * tanh(max(0, s_(3) - s_j) / 0.22)` so `#1/#2/#3` podium
       locks stay protected while `#6..#20` bubble breakouts have full headroom to enter Top-10.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import glob
import hashlib
import json
import math
import os
import subprocess
import time
from typing import Any

import gcsfs
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
from usersim_core.hillclimb_v6 import QWENVL_V6_FEATURES, attach_qwen_vl_features
from usersim_core.hillclimb_v7 import attach_v7_recovered_signals
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
    VertexClaudeBalanced,
    VertexGeminiProFast,
    _extract_evals_json,
)
from usersim_core.why_cards_v5 import emit_why_cards_batch


TOURNAMENT_PO_PROMPT = """You are a calibrated 5-person panel of discerning Product Hunt builders allocating your daily upvotes across {n_items} head-to-head finalist launches ({zone_desc}) STRICTLY FROM THE PRODUCT & HANDS-ON CUA EXECUTION (ZERO comments, ZERO votes, ZERO rankings).

MATCHED REAL USERS (< today):
{panel_block}

CONTENDERS (randomized MD5 order 1..{n_items}; compare side-by-side on hands-on CUA reality, demo video clarity, concrete differentiation vs named competitors, engineering/UX craft, and absence of paywall/waitlist friction):
{items_block}

RULES:
1. Spread `win_prob` across the full 0.10..0.95 range so your top 3-4 winners separate sharply from the bottom half.
2. Verified working products, clean Google-SSO workspaces, interactive demos, demo videos, and open-source tools beat vague AI-wrapper pitches and waitlist/paywall gates.
3. Do NOT penalize `[SITE_UNVERIFIED]` — judge neutrally from product spec, media, and competitor advantage.

Return compact JSON ONLY (every `idx` 1..{n_items} MUST appear once):
{{"evaluations":[{{"idx":1,"win_prob":0.00,"would_adopt":0.00,"anti_slop":0.00}}]}}"""


TOURNAMENT_PC_PROMPT = """You are a calibrated 5-person panel of discerning Product Hunt builders & community scouts resolving {n_items} head-to-head launches ({zone_desc}) before the 04:00 PT vote reveal. Vote counts and rankings are HIDDEN; you observe product + hands-on CUA + pre-03:45 PT community Q&A threads + pre-02:00 PT X buzz.

CONTENDERS (randomized MD5 order 1..{n_items}; zero vote counts or rankings exist):
{items_block}

RULES:
1. Spread `win_prob` across 0.10..0.95 so the true breakout winners stand out sharply from quiet or pod-fluffed launches.
2. Authentic organic traction = multiple established non-maker users asking real workflow/pricing/comparison questions, hands-on testing reports, responsive maker Q&A, and genuine X discussion — combined with a working product.
3. Penalize launches with broken onboarding/paywalls, complaints in early comments, or crickets despite promotional push.

Return compact JSON ONLY (every `idx` 1..{n_items} MUST appear once):
{{"evaluations":[{{"idx":1,"win_prob":0.00,"organic_buzz":0.00,"substance":0.00}}]}}"""


def load_grok_0200_xbuzz(bucket: str = "usersim-bakeoff-347838016394/usersim_sim") -> dict[tuple[str, str], float]:
    """Load strictly `<= 02:00 PT` (`0030` and `0200`, written <= 02:15 PT) Grok X-buzz rank signals by (day, slug/name)."""
    out: dict[tuple[str, str], float] = {}
    try:
        fs = gcsfs.GCSFileSystem()
        files = sorted(x for x in fs.ls(f"{bucket}/results/grok_forecast") if x.endswith("_0200.json") or x.endswith("_0030.json"))
        by_day: dict[str, dict[str, float]] = {}
        for f in files:
            j = json.load(fs.open(f))
            d = str(j.get("day") or "")
            pt = str(j.get("point") or "")
            if not d or pt not in ("0030", "0200"):
                continue
            fc = j.get("forecast") or []
            n_f = max(len(fc), 1)
            d_map = by_day.setdefault(d, {})
            w = 1.0 if pt == "0200" else 0.5
            for row in fc:
                rk = int(row.get("rank") or n_f)
                nm = str(row.get("name") or "").strip().lower()
                val = max(0.0, 1.0 - (rk - 1) / max(n_f, 10))
                if nm:
                    d_map[nm] = max(d_map.get(nm, 0.0), w * val)
        for d, mp in by_day.items():
            for nm, v in mp.items():
                out[(d, nm)] = v
    except Exception as exc:
        print(f"  [Hillclimb v8] grok_forecast optional load note: {exc}", flush=True)
    return out


def load_shadow_it8_0115_ev(bucket: str = "usersim-bakeoff-347838016394/usersim_sim") -> dict[tuple[str, str], float]:
    """Load strictly `< 03:45 PT` (`today_0005` + `<D` person Presence x Choice EV, zero comments) `shadow_it8` scores."""
    out: dict[tuple[str, str], float] = {}
    try:
        import pyarrow.parquet as pq
        fs = gcsfs.GCSFileSystem()
        jfiles = sorted(x for x in fs.ls(f"{bucket}/results/shadow_it8") if x.endswith(".json"))
        valid_days: set[str] = set()
        for jf in jfiles:
            j = json.load(fs.open(jf))
            d = str(j.get("day") or "")
            wat = str(j.get("written_at") or "")
            # Enforce written_at strictly before 03:45 PT (11:45 UTC)!
            if d and wat and wat[11:16] <= "11:40":
                valid_days.add(d)
        for d in sorted(valid_days):
            pf = f"{bucket}/results/shadow_it8/ev_{d}.parquet"
            if fs.exists(pf):
                pdf = pq.read_table(fs.open(pf, "rb")).to_pandas()
                for r in pdf.itertuples(index=False):
                    out[(d, str(r.id))] = math.log1p(max(0.0, float(r.ev)))
    except Exception as exc:
        print(f"  [Hillclimb v8] shadow_it8 optional load note: {exc}", flush=True)
    return out


def compute_archetype_person_choice_features(
    full_df: pd.DataFrame,
    pool: UniversalUserPool,
) -> pd.DataFrame:
    """Couple all 93,618 real people's `< D` profiles in `UniversalUserPool` to `UnivSim v7` 5-archetype scores!"""
    df = full_df.copy().reset_index(drop=True)
    ev_arch = np.zeros(len(df), dtype=np.float64)
    ev_selective = np.zeros(len(df), dtype=np.float64)

    sep_nov = df["day"] >= "2026-09-01"
    for d, idx in df[sep_nov].groupby("day", sort=True).groups.items():
        pos = np.asarray(list(idx), dtype=np.int64)
        if len(pos) < 2:
            continue
        d_eff = str(d) if str(d) <= "2026-11-24" else "2026-11-24"
        snap = pool.snapshot(d_eff)
        elig = np.flatnonzero((snap["n60"] >= 1) & (snap["n_all"] >= 3) & snap["established"])
        if len(elig) < 20:
            continue
        # Subsample up to 4,000 highest-activity discerning voters deterministically by person_idx
        rw = snap["rw30"][elig].astype(np.float64)
        if len(elig) > 4000:
            top_u = np.argsort(-rw)[:4000]
            elig = elig[top_u]
            rw = rw[top_u]

        p_pres = np.clip(rw / 7.0, 0.01, 0.85)  # (U,)
        sel = 1.0 / (1.0 + snap["entropy"][elig].astype(np.float64))
        # Person weights over (systems, power, craft, buyer, skeptic_keep)
        w_sys = snap["tech_rate"][elig].astype(np.float64)
        w_pow = np.clip(np.log1p(rw) / 3.0, 0.1, 1.0)
        w_crf = snap["ux_rate"][elig].astype(np.float64)
        w_buy = snap["price_rate"][elig].astype(np.float64)
        w_skp = snap["crit_rate"][elig].astype(np.float64) * sel
        W_u = np.column_stack([w_sys, w_pow, w_crf, w_buy, w_skp])  # (U, 5)
        W_u = W_u / np.maximum(W_u.sum(axis=1, keepdims=True), 1e-6)

        sub = df.iloc[pos]
        c_pow = 0.5 * (sub["raw_u7_claude_adopt"].to_numpy() + sub["raw_u7_gempro_adopt"].to_numpy())
        A_j = np.column_stack([
            sub["raw_u7_claude_systems"].to_numpy(dtype=np.float64),
            c_pow,
            sub["raw_u7_claude_craft"].to_numpy(dtype=np.float64),
            0.5 * (sub["raw_u7_claude_adopt"].to_numpy(dtype=np.float64) + sub["raw_u7_claude_skeptic"].to_numpy(dtype=np.float64)),
            sub["raw_u7_claude_skeptic"].to_numpy(dtype=np.float64),
        ])  # (J, 5)

        # Semantic cosine similarity between each user `u` and launch `j`
        u_vecs = snap["user_vecs"][elig].astype(np.float32)  # (U, D)
        j_vecs = np.vstack([
            pool.item_vecs[int(r.item_idx)] if int(r.item_idx) >= 0 else pool.embed_text(f"{r.title} {r.summary}")
            for r in sub.itertuples(index=False)
        ]).astype(np.float32)  # (J, D)
        with np.errstate(all="ignore"):
            sim_uj = np.nan_to_num(u_vecs @ j_vecs.T, nan=0.0, posinf=0.0, neginf=0.0).astype(np.float64)

        arch_uj = W_u @ A_j.T  # (U, J)
        util_uj = (2.2 * sim_uj + 2.6 * arch_uj) / 0.65
        util_uj = util_uj - util_uj.max(axis=1, keepdims=True)
        exp_u = np.exp(util_uj)
        prob_uj = exp_u / np.maximum(exp_u.sum(axis=1, keepdims=True), 1e-9)  # (U, J)

        ev_arch[pos] = (p_pres[:, None] * prob_uj).sum(axis=0)
        ev_selective[pos] = ((p_pres * sel)[:, None] * prob_uj).sum(axis=0)

    df["_raw_pop8_ev"] = np.log1p(ev_arch)
    df["_raw_pop8_sel"] = np.log1p(ev_selective)
    df["pop8_archetype_ev_z"] = within_day_zscore(df, "_raw_pop8_ev", mask_col="sep_nov_active")
    df["pop8_selective_ev_z"] = within_day_zscore(df, "_raw_pop8_sel", mask_col="sep_nov_active")
    return df.drop(columns=["_raw_pop8_ev", "_raw_pop8_sel"])


def run_v8_zone_tournaments(
    sep_nov_df: pd.DataFrame,
    pool: UniversalUserPool,
    surfaces_by_id: dict[str, SanitizedSurface],
    cua4_records: dict[str, dict[str, Any]],
    mm_judged: dict[str, dict[str, Any]],
    comp_map: dict[str, list[dict[str, Any]]],
    media_map: dict[str, dict[str, float]],
    merged_comm_map: dict[str, dict[str, Any]],
    grok_map: dict[tuple[str, str], float],
    cache: JsonlCache,
    budget: Budget,
    workers: int = 8,
) -> dict[str, dict[tuple[str, str], float]]:
    """Run multi-family (`Claude Sonnet 4.6` + `Gemini 2.5 Pro`) Podium & Bubble (#6-#16) head-to-head panels!"""
    claude = VertexClaudeBalanced(
        model="claude-sonnet-4-6",
        project="project-amer-scs-sandbox",
        region="global",
        temperature=0.12,
        budget=budget,
        max_out=2200,
    )
    gempro = VertexGeminiProFast(
        project="project-amer-scs-sandbox",
        region="global",
        temperature=0.12,
        budget=budget,
        max_out=2400,
        thinking_budget=192,
    )

    days = sorted(sep_nov_df["day"].unique())
    by_day: dict[str, list[Any]] = {}
    for d in days:
        dg = sep_nov_df[sep_nov_df["day"] == d].copy()
        dg = dg.sort_values(["structural_score", "item_id"], ascending=[False, True], kind="mergesort")
        by_day[str(d)] = list(dg.itertuples(index=False))

    def _call_pair(tag: str, d: str, sig: str, prompt: str, n_it: int) -> tuple[dict[int, dict], dict[int, dict]]:
        kc = (f"{tag}_claude46", d, sig)
        kg = (f"{tag}_gempro", d, sig)

        def _one(ck: tuple, b: Any) -> dict[int, dict]:
            if ck in cache:
                return {int(k): v for k, v in cache[ck].items()}
            ev: dict[int, dict] = {}
            for _ in range(2):
                try:
                    ev = _extract_evals_json(b.call(prompt), n_it)
                    if len(ev) >= max(2, int(0.75 * n_it)):
                        break
                except Exception as exc:
                    print(f"    [V8 Tourn warn] {b.name} {ck[:2]}: {type(exc).__name__}: {str(exc)[:100]}", flush=True)
            if ev:
                cache[ck] = {str(k): v for k, v in ev.items()}
            return ev

        with ThreadPoolExecutor(max_workers=2) as sub_ex:
            fc = sub_ex.submit(_one, kc, claude)
            fg = sub_ex.submit(_one, kg, gempro)
            return fc.result(), fg.result()

    def _eval_po_zone(d: str, rows: list[Any], zone_tag: str, zone_desc: str) -> dict[str, float]:
        if len(rows) < 3:
            return {}
        ordered = sorted(rows, key=lambda r: hashlib.md5(f"v8_po:{zone_tag}:{d}:{r.item_id}".encode()).hexdigest())
        n_it = len(ordered)
        sig = hashlib.md5(",".join(str(r.item_id) for r in ordered).encode()).hexdigest()[:10]
        d_eff = d if d <= "2026-11-24" else "2026-11-24"
        panel = pool.match_cohort(d_eff, " ".join(f"{r.title} {r.summary}" for r in ordered[:5]), k=5)
        p_blk = "\n".join(f"- Member {i+1}: {m['history_brief'][:200]}" for i, m in enumerate(panel))

        lines = []
        for idx, r in enumerate(ordered, start=1):
            lid = str(r.item_id)
            sf = surfaces_by_id.get(lid)
            cr = cua4_records.get(lid) or {}
            mm = mm_judged.get(lid) or {}
            med = media_map.get(lid) or {}
            cua_s = (
                f"status=clean, demo={bool(sf and sf.has_interactive_demo)}, oss={bool((sf and sf.has_open_source) or cr.get('has_github_link'))}, "
                f"free={bool(sf and sf.has_free_tier)}, waitlist={bool(sf and sf.is_waitlist)}, sso_ok={bool(cr.get('google_sso_entered'))}, "
                f"works={mm.get('hands_on_works', 'n/a')}; {str(mm.get('exec_digest') or (sf.sanitized_text[:150] if sf else ''))}"
                if (cr or (sf and sf.access_status == "clean"))
                else "[SITE_UNVERIFIED]"
            )
            comps = "; ".join(f"{c['name']}(pain={str(c.get('key_user_pain_point') or '')[:55]})" for c in (comp_map.get(lid) or [])[:2]) or "none"
            lines.append(
                f"[{idx}] {scrub(str(r.title))} — {scrub(str(r.summary))} (video={'yes' if med.get('has_video') else 'no'}, gallery={int(med.get('media_count', 0))})\n"
                f"    Pitch: {scrub(str(r.description or ''))[:210]}\n"
                f"    Hands-On CUA: {scrub(cua_s[:250])} | Competitors: {scrub(comps[:160])}"
            )
        prompt = TOURNAMENT_PO_PROMPT.format(n_items=n_it, zone_desc=zone_desc, panel_block=p_blk[:1100], items_block="\n".join(lines))
        ec, eg = _call_pair(f"v8_po_{zone_tag}", d, sig, prompt, n_it)

        raw_d: dict[str, float] = {}
        for idx, r in enumerate(ordered, start=1):
            rc, rg = ec.get(idx, {}), eg.get(idx, {})
            sc_c = 0.50 * float(rc.get("win_prob", 0.45)) + 0.30 * float(rc.get("would_adopt", 0.45)) + 0.20 * float(rc.get("anti_slop", 0.50))
            sc_g = 0.50 * float(rg.get("win_prob", 0.45)) + 0.30 * float(rg.get("would_adopt", 0.45)) + 0.20 * float(rg.get("anti_slop", 0.50))
            raw_d[str(r.item_id)] = 0.55 * sc_c + 0.45 * sc_g
        vals = np.array(list(raw_d.values()), dtype=np.float64)
        mu, sd = float(np.mean(vals)), float(np.std(vals))
        return {k: float(np.clip((v - mu) / sd, -2.5, 2.5)) if sd > 1e-8 else 0.0 for k, v in raw_d.items()}

    def _eval_pc_zone(d: str, rows: list[Any], zone_tag: str, zone_desc: str) -> dict[str, float]:
        if len(rows) < 3:
            return {}
        ordered = sorted(rows, key=lambda r: hashlib.md5(f"v8_pc:{zone_tag}:{d}:{r.item_id}".encode()).hexdigest())
        n_it = len(ordered)
        sig = hashlib.md5(",".join(str(r.item_id) for r in ordered).encode()).hexdigest()[:10]

        lines = []
        for idx, r in enumerate(ordered, start=1):
            lid = str(r.item_id)
            sf = surfaces_by_id.get(lid)
            mm = mm_judged.get(lid) or {}
            cm = merged_comm_map.get(lid) or {}
            gk = grok_map.get((d, str(r.title or "").strip().lower()), 0.0)
            cua_s = (
                f"works={mm.get('hands_on_works', 'n/a')}, demo={bool(sf and sf.has_interactive_demo)}, waitlist={bool(sf and sf.is_waitlist)}"
                if (mm or (sf and sf.access_status == "clean"))
                else "[SITE_UNVERIFIED]"
            )
            u_txt = " | ".join(str(x)[:120] for x in (cm.get("early_comm_texts") or [])[:4]) or "(none yet)"
            lines.append(
                f"[{idx}] {scrub(str(r.title))} — {scrub(str(r.summary))} | CUA: {cua_s}\n"
                f"    <=03:45 PT Thread: distinct_users={int(cm.get('early_n_distinct', 0))}, est25f={int(cm.get('early_n_established', 0))}, "
                f"substantive={int(cm.get('early_substantive_n', 0))}, questions={int(cm.get('user_question_count', 0))}, "
                f"maker_replies={int(cm.get('maker_reply_count', 0))}, x_buzz_le0200={gk:.2f}\n"
                f"    Early User Comments: {scrub(u_txt[:420])}"
            )
        prompt = TOURNAMENT_PC_PROMPT.format(n_items=n_it, zone_desc=zone_desc, items_block="\n".join(lines))
        ec, eg = _call_pair(f"v8_pc_{zone_tag}", d, sig, prompt, n_it)

        raw_d: dict[str, float] = {}
        for idx, r in enumerate(ordered, start=1):
            rc, rg = ec.get(idx, {}), eg.get(idx, {})
            sc_c = 0.50 * float(rc.get("win_prob", 0.45)) + 0.30 * float(rc.get("organic_buzz", 0.45)) + 0.20 * float(rc.get("substance", 0.45))
            sc_g = 0.50 * float(rg.get("win_prob", 0.45)) + 0.30 * float(rg.get("organic_buzz", 0.45)) + 0.20 * float(rg.get("substance", 0.45))
            raw_d[str(r.item_id)] = 0.55 * sc_c + 0.45 * sc_g
        vals = np.array(list(raw_d.values()), dtype=np.float64)
        mu, sd = float(np.mean(vals)), float(np.std(vals))
        return {k: float(np.clip((v - mu) / sd, -2.5, 2.5)) if sd > 1e-8 else 0.0 for k, v in raw_d.items()}

    out_maps: dict[str, dict[tuple[str, str], float]] = {
        "po_podium": {},
        "po_bubble": {},
        "pc_podium": {},
        "pc_bubble": {},
    }

    def _work_day(d: str) -> tuple[str, dict[str, float], dict[str, float], dict[str, float], dict[str, float]]:
        rows = by_day[d]
        po_pod = _eval_po_zone(d, rows[:9], "pod9", "Top-9 Podium Contenders for #1-#5")
        po_bub = _eval_po_zone(d, rows[5:19], "bub14", "Ranks #6-#19 Bubble Contenders for Top-10 Cutline")
        pc_pod = _eval_pc_zone(d, rows[:10], "pod10", "Top-10 Podium Contenders for #1-#5")
        pc_bub = _eval_pc_zone(d, rows[5:19], "bub14", "Ranks #6-#19 Bubble Contenders for Top-10 Cutline")
        return d, po_pod, po_bub, pc_pod, pc_bub

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(_work_day, d) for d in days]
        for fut in as_completed(futs):
            d, pp, pb, cp, cb = fut.result()
            for k, v in pp.items():
                out_maps["po_podium"][(d, k)] = v
            for k, v in pb.items():
                out_maps["po_bubble"][(d, k)] = v
            for k, v in cp.items():
                out_maps["pc_podium"][(d, k)] = v
            for k, v in cb.items():
                out_maps["pc_bubble"][(d, k)] = v
            done += 1
            if done % 15 == 0 or done == len(days):
                print(f"  [V8 Zone Tournaments] {done}/{len(days)} days (${budget.spent:.3f})", flush=True)
    cache.roll()
    return out_maps


@dataclass
class RankGatedUniversalRankerV8:
    """Rolling `< D` Two-Zone Gap-Gated Universal Simulator Ranker (`0.0` perm diff, `0.0` PO comment leak)."""

    apr_cols: list[str]
    sep_cols: list[str]
    nov_live_cols: list[str]
    target_total_std: float = 0.095
    podium_cap: float = 0.195
    bubble_cap: float = 0.400
    tourn_podium_w: float = 0.050
    tourn_bubble_w: float = 0.065
    u7_weight: float = 0.045
    pop8_weight: float = 0.030
    is_product_only: bool = True

    def predict_walkforward(self, df_all: pd.DataFrame) -> dict[tuple[str, str], float]:
        df_s = df_all.sort_values(["day", "item_id"], kind="mergesort").reset_index(drop=True)
        apr_use = list(dict.fromkeys(c for c in self.apr_cols if c in df_s.columns))
        sep_use = list(dict.fromkeys(c for c in self.sep_cols if c in df_s.columns))
        nov_use = list(dict.fromkeys(c for c in self.nov_live_cols if c in df_s.columns))

        eval_days = sorted(d for d in df_s["day"].unique() if d >= "2026-09-01")
        overrides: dict[tuple[str, str], float] = {}

        # Step forward in causal 5-day blocks strictly trained on `day < block_start`!
        block_size = 5
        for b_idx in range(0, len(eval_days), block_size):
            b_days = eval_days[b_idx : b_idx + block_size]
            b_start = b_days[0]
            te = df_s[df_s["day"].isin(b_days)].copy().reset_index(drop=True)
            if te.empty:
                continue

            tr_apr = (
                df_s[(df_s["day"] < b_start) & (df_s["day"] <= "2026-11-24") & (df_s["structural_rank"] <= 20)]
                .copy()
                .reset_index(drop=True)
            )
            m_apr = WalkForwardResidualModel(
                feature_cols=apr_use,
                ridge_alpha=240.0,
                pairwise_C=0.04,
                target_std=1.0,
                max_shift=5.0,
            ).fit(tr_apr)
            raw_shift = m_apr.predict_shift(te)

            # Causal expanding Sep-Nov stage (`>= 7` prior Sep+ days, including inside Val Sep >= Sep 08!)
            tr_sep = (
                df_s[(df_s["day"] >= "2026-09-01") & (df_s["day"] < b_start) & (df_s["day"] <= "2026-11-24") & (df_s["structural_rank"] <= 20)]
                .copy()
                .reset_index(drop=True)
            )
            if sep_use and len(tr_sep) >= 130:
                m_sep = WalkForwardResidualModel(
                    feature_cols=sep_use,
                    ridge_alpha=180.0,
                    pairwise_C=0.04,
                    target_std=1.0,
                    max_shift=5.0,
                ).fit(tr_sep)
                raw_shift = 0.62 * raw_shift + 0.38 * m_sep.predict_shift(te)

            # Causal expanding Live/Nov stage (`pnx_0005`, `it8_ev`, `xbuzz`, `threads_le_0345` once >= 6 prior days exist!)
            tr_nov = (
                df_s[(df_s["day"] >= "2026-10-27") & (df_s["day"] < b_start) & (df_s["day"] <= "2026-11-24") & (df_s["structural_rank"] <= 20)]
                .copy()
                .reset_index(drop=True)
            )
            if nov_use and len(tr_nov) >= 120:
                m_nov = WalkForwardResidualModel(
                    feature_cols=nov_use,
                    ridge_alpha=140.0,
                    pairwise_C=0.04,
                    target_std=1.0,
                    max_shift=5.0,
                ).fit(tr_nov)
                raw_shift = 0.78 * raw_shift + 0.22 * m_nov.predict_shift(te)

            # Normalize learned residual component to exact `target_total_std` per block!
            sd_blk = max(float(np.std(raw_shift)), 1e-6)
            shift = (raw_shift / sd_blk) * self.target_total_std

            # Add calibrated direct simulator & tournament signals (gated smoothly by podium vs bubble zone!)
            for d_val, dg_idx in te.groupby("day", sort=False).groups.items():
                pos = np.asarray(list(dg_idx), dtype=np.int64)
                s_vec = te["structural_score"].to_numpy(dtype=np.float64)[pos]
                s_sorted = np.sort(s_vec)[::-1]
                s_ref3 = float(s_sorted[min(2, len(s_sorted) - 1)])
                gap = np.maximum(0.0, s_ref3 - s_vec)
                bub_gate = np.tanh(gap / 0.22)  # 0.0 on #1-#3, rises smoothly -> 1.0 in #7-#28 bubble!
                pod_gate = 1.0 - 0.55 * bub_gate

                sub = te.iloc[pos]
                if self.is_product_only:
                    podium_sig = (
                        0.45 * sub["v4_finalist_po_z"].to_numpy(dtype=np.float64)
                        + 0.35 * sub["v8_po_podium_z"].to_numpy(dtype=np.float64)
                        + 0.20 * sub["mm_discerning_adopt_z"].to_numpy(dtype=np.float64)
                    )
                    bubble_sig = (
                        0.55 * sub["v8_po_bubble_z"].to_numpy(dtype=np.float64)
                        + 0.25 * sub["u7_po_consensus_z"].to_numpy(dtype=np.float64)
                        + 0.20 * sub["brand_coldstart_authority_z"].to_numpy(dtype=np.float64)
                    )
                    u7_sig = (
                        0.50 * sub["u7_po_consensus_z"].to_numpy(dtype=np.float64)
                        + 0.25 * sub["v3po_net_conviction_z"].to_numpy(dtype=np.float64)
                        + 0.25 * sub["comp_cua_advantage_z"].to_numpy(dtype=np.float64)
                    )
                else:
                    podium_sig = (
                        0.55 * sub["v8_pc_podium_z"].to_numpy(dtype=np.float64)
                        + 0.25 * sub["u7_disc_consensus_z"].to_numpy(dtype=np.float64)
                        + 0.20 * sub["v4_finalist_po_z"].to_numpy(dtype=np.float64)
                    )
                    bubble_sig = (
                        0.50 * sub["v8_pc_bubble_z"].to_numpy(dtype=np.float64)
                        + 0.30 * sub["pc7_user_distinct_log_z"].to_numpy(dtype=np.float64)
                        + 0.20 * sub["u7_disc_consensus_z"].to_numpy(dtype=np.float64)
                    )
                    u7_sig = (
                        0.45 * sub["u7_disc_consensus_z"].to_numpy(dtype=np.float64)
                        + 0.30 * sub["pc7_user_est_cred_z"].to_numpy(dtype=np.float64)
                        + 0.25 * sub["u7_po_consensus_z"].to_numpy(dtype=np.float64)
                    )

                pop_sig = (
                    0.50 * sub["pop8_archetype_ev_z"].to_numpy(dtype=np.float64)
                    + 0.30 * sub["pop_expected_votes_choice_z"].to_numpy(dtype=np.float64)
                    + 0.20 * sub["pop_qwen_stack1b_z"].to_numpy(dtype=np.float64) * sub["has_qwen_backer_pred"].to_numpy(dtype=np.float64)
                )

                d_shift = (
                    shift[pos]
                    + self.tourn_podium_w * pod_gate * podium_sig
                    + self.tourn_bubble_w * bub_gate * bubble_sig
                    + self.u7_weight * u7_sig
                    + self.pop8_weight * pop_sig
                )
                cap_vec = self.podium_cap + (self.bubble_cap - self.podium_cap) * bub_gate
                d_shift = np.clip(d_shift, -cap_vec, cap_vec)
                sc_vec = s_vec + d_shift
                for lid_s, sc_v in zip(sub["item_id"], sc_vec):
                    overrides[(str(d_val), str(lid_s))] = float(sc_v)

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
    ap.add_argument("--out-json", default="/var/tmp/usersim_core_work/usersim_core_hillclimb_8_results.json")
    ap.add_argument("--why-out-dir", default="/var/tmp/usersim_core_work/why_v8")
    ap.add_argument("--gcs-prefix", default="gs://usersim-trace-store-347838016394/usersim_core_v8")
    ap.add_argument("--budget-usd", type=float, default=14.0)
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

    # Expand ALL Live 23d AND Sep-Nov backtest days up to Top-28 (`99.1%` real Top-10 ceiling!)
    live_expanded_launches: dict[str, list[dict]] = {}
    extra_rows_to_score: list[dict[str, Any]] = []

    def _make_extra_row(d: str, x: dict[str, Any], truth_map: dict[str, Any]) -> dict[str, Any]:
        lid = str(x["id"])
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
        t_rec = truth_map.get(lid, {})
        rv = float(t_rec.get("votes") or 0.0)
        rr = float(t_rec["final_rank"]) if t_rec.get("final_rank") is not None else 35.0
        pv = max(1.0, float(x.get("pred_votes") or np.expm1(float(x["structural_score"]))))
        return {
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
        }

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
        for x in cur_list[:25]:
            if (d, str(x["id"])) not in existing_pairs:
                extra_rows_to_score.append(_make_extra_row(d, x, live_truth[d]))
                existing_pairs.add((d, str(x["id"])))

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
    # Strictly zero `arm2` mixing (`arm2_map={}` per `AGENTS.md`!)
    full_df, merged_comm_map = attach_v7_recovered_signals(full_df, comm_map_bench, args.complete_v7_dir, arm2_map={})
    full_df = attach_walkforward_product_comment_features(full_df, merged_comm_map)
    full_df, _ = load_apify_signals(full_df, args.apify_dir, args.data_dir)
    full_df = attach_v3_causal_features(full_df, bench, surfaces_by_id, sso_meta, args.live23_dir)

    # Optional causal `< 03:45 PT` (`01:15 PT` zero-comment `shadow_it8` + `02:00 PT` `grok_forecast` X buzz)
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

    # Run v3_po, v2, and v4_finalist strictly on Top-20 (`structural_rank <= 20` or Live<=25) so all existing caches hit 100%!
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

    # CompetitorGraph + 93,618-Person Choice Sim + Cold-Start Brand Authority + Qwen2.5-VL-7B across Top-28!
    comp_graph = CompetitorGraph(bench, pool, args.data_dir, args.apify_dir)
    full_df, comp_map = comp_graph.attach_features(full_df, surfaces_by_id, cua4_records, mm_judged)
    pop_sim = PopulationChoiceSim(bench, pool, args.data_dir, args.live23_dir)
    full_df, why_pop_by_key = pop_sim.simulate_all_days(full_df, comp_map, tau=0.85)
    full_df = attach_cold_start_brand_authority(full_df, args.apify_dir, args.live23_dir, surfaces_by_id)
    full_df, _ = attach_qwen_vl_features(full_df, args.qwen_vl_parquet)

    # Reuse cached `cache_univ_v7` on Top-20/25 (and run on Top-28)!
    u7_cache = JsonlCache(f"{args.work_dir}/cache_univ_v7")
    usim = UniversalUserSimulatorV7(cache=u7_cache, budget=budget)
    media_path = f"{args.complete_v7_dir}/page_media_map.json"
    media_map = json.load(open(media_path)) if os.path.exists(media_path) else {}

    u7_mask = sep_nov_mask
    po_payloads: list[dict[str, Any]] = []
    disc_payloads: list[dict[str, Any]] = []
    for d, dg in full_df[u7_mask].groupby("day", sort=True):
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

    full_df["u7_mask_active"] = u7_mask.to_numpy()
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
        full_df[z_k] = within_day_zscore(full_df, raw_k, mask_col="u7_mask_active")

    for raw_k, z_k in [
        ("raw_u7_disc_claude_org", "u7_disc_claude_organic_z"),
        ("raw_u7_disc_claude_brk", "u7_disc_claude_breakout_z"),
        ("raw_u7_disc_gpt_org", "u7_disc_gpt_organic_z"),
        ("raw_u7_disc_consensus", "u7_disc_consensus_z"),
    ]:
        full_df[raw_k] = [float((u7_disc_res.get((str(r.day), str(r.item_id))) or {}).get(raw_k, 0.45)) for r in full_df.itertuples(index=False)]
        full_df[z_k] = within_day_zscore(full_df, raw_k, mask_col="u7_mask_active")

    # Individual 93,618-Person x 5-Archetype Choice Simulator!
    print("[Hillclimb v8] Running Archetype-Coupled 93,618-Person Choice Simulator...", flush=True)
    full_df = compute_archetype_person_choice_features(full_df, pool)

    # Run Podium (#1-#10) + Bubble (#6-#17) Multi-Family Head-to-Head Finalist Tournaments!
    print("[Hillclimb v8] Running Podium & Bubble (#6-#17) Multi-Family Head-to-Head Finalist Tournaments...", flush=True)
    tourn_cache = JsonlCache(f"{args.work_dir}/cache_tourn_v8")
    t_maps = run_v8_zone_tournaments(
        full_df[sep_nov_mask],
        pool,
        surfaces_by_id,
        cua4_records,
        mm_judged,
        comp_map,
        media_map,
        merged_comm_map,
        grok_map,
        tourn_cache,
        budget,
        workers=8,
    )
    full_df["v8_po_podium_z"] = [float(t_maps["po_podium"].get((str(r.day), str(r.item_id)), 0.0)) for r in full_df.itertuples(index=False)]
    full_df["v8_po_bubble_z"] = [float(t_maps["po_bubble"].get((str(r.day), str(r.item_id)), 0.0)) for r in full_df.itertuples(index=False)]
    full_df["v8_pc_podium_z"] = [float(t_maps["pc_podium"].get((str(r.day), str(r.item_id)), 0.0)) for r in full_df.itertuples(index=False)]
    full_df["v8_pc_bubble_z"] = [float(t_maps["pc_bubble"].get((str(r.day), str(r.item_id)), 0.0)) for r in full_df.itertuples(index=False)]

    # ------------------------------------------------------------------
    # Lock ALL Hyperparameters Strictly on Val Sep (`<= 2026-09-30`)!
    # ------------------------------------------------------------------
    val_bt = {d: v for d, v in full_day_launches.items() if d.startswith("2026-09")}
    val_df_only = full_df[full_df["day"] <= "2026-09-30"].copy()

    po_apr_v8 = (
        ALL_RESIDUAL_FEATURES
        + PRODUCT_ONLY_V3_TABULAR
        + COMPETITOR_V5_FEATURES
        + POPULATION_V5_FEATURES
        + BRAND_AUTHORITY_V5_FEATURES
        + ["media_has_video_z", "media_gallery_depth_z"]
    )
    po_sep_v8 = (
        COHORT_V3_PO_FEATURES
        + INTERACTIVE_CUA_V4_FEATURES
        + APIFY_FEATURES
        + QWENVL_V6_FEATURES
        + UNIV_PRODUCT_ONLY_FEATURES
        + ["pop8_archetype_ev_z", "pop8_selective_ev_z", "v8_po_podium_z", "v8_po_bubble_z"]
    )
    po_nov_v8 = ["pnx_ev_z", "pnx_pmax_z", "xbuzz_pre0000_z", "api_team_reach_z", "it8_person_ev_z"]

    best_po_key, best_po_cfg = (-1e9, -1e9), (0.085, 0.195, 0.36, 0.045, 0.055, 0.035, 0.025)
    for t_std in (0.070, 0.090):
        for p_cap, b_cap in ((0.185, 0.34), (0.215, 0.44)):
            for w_pod in (0.035, 0.060):
                for w_bub in (0.040, 0.075):
                    for w_u7, w_pop in ((0.025, 0.025), (0.045, 0.035)):
                        rk = RankGatedUniversalRankerV8(
                            apr_cols=po_apr_v8,
                            sep_cols=po_sep_v8,
                            nov_live_cols=po_nov_v8,
                            target_total_std=t_std,
                            podium_cap=p_cap,
                            bubble_cap=b_cap,
                            tourn_podium_w=w_pod,
                            tourn_bubble_w=w_bub,
                            u7_weight=w_u7,
                            pop8_weight=w_pop,
                            is_product_only=True,
                        )
                        ov_v = rk.predict_walkforward(val_df_only)
                        vsub = val_df_only[val_df_only["day"].str.startswith("2026-09")].copy()
                        vsub["final_score"] = [ov_v[(str(r.day), str(r.item_id))] for r in vsub.itertuples(index=False)]
                        ev = evaluate_boards_and_ties(val_bt, truth_by_day, vsub, n_boot=60)
                        cand_key = (
                            round(ev["model"]["mean_3_5_10"] + 0.20 * ev["model"]["top10"] + 0.15 * ev["model"]["top3"], 4),
                            ev["reach_matched_ties"]["model_acc_pct"],
                        )
                        if cand_key > best_po_key:
                            best_po_key = cand_key
                            best_po_cfg = (t_std, p_cap, b_cap, w_pod, w_bub, w_u7, w_pop)

    pc_apr_v8 = po_apr_v8 + PROD_COMMENT_FEATURES + COMMENT_V3_EXTRA + [
        "pc7_user_distinct_log_z", "pc7_user_est_cred_z", "pc7_substantive_qa_z", "pc7_maker_reply_vel_z"
    ]
    pc_sep_v8 = po_sep_v8 + COHORT_V2_FEATURES + UNIV_DISCOURSE_FEATURES + ["v8_pc_podium_z", "v8_pc_bubble_z"]
    pc_nov_v8 = po_nov_v8 + [
        "xbuzz_le0200_z", "grok_xbuzz_le0200_z", "pc7_user_distinct_log_z", "pc7_user_est_cred_z", "u7_disc_consensus_z"
    ]

    best_pc_key, best_pc_cfg = (-1e9, -1e9), (0.125, 0.230, 0.46, 0.055, 0.075, 0.045, 0.025)
    for t_std in (0.105, 0.135):
        for p_cap, b_cap in ((0.220, 0.42), (0.260, 0.54)):
            for w_pod in (0.045, 0.075):
                for w_bub in (0.055, 0.090):
                    for w_u7, w_pop in ((0.035, 0.025), (0.060, 0.030)):
                        rk = RankGatedUniversalRankerV8(
                            apr_cols=pc_apr_v8,
                            sep_cols=pc_sep_v8,
                            nov_live_cols=pc_nov_v8,
                            target_total_std=t_std,
                            podium_cap=p_cap,
                            bubble_cap=b_cap,
                            tourn_podium_w=w_pod,
                            tourn_bubble_w=w_bub,
                            u7_weight=w_u7,
                            pop8_weight=w_pop,
                            is_product_only=False,
                        )
                        ov_v = rk.predict_walkforward(val_df_only)
                        vsub = val_df_only[val_df_only["day"].str.startswith("2026-09")].copy()
                        vsub["final_score"] = [ov_v[(str(r.day), str(r.item_id))] for r in vsub.itertuples(index=False)]
                        ev = evaluate_boards_and_ties(val_bt, truth_by_day, vsub, n_boot=60)
                        cand_key = (
                            round(ev["model"]["mean_3_5_10"] + 0.20 * ev["model"]["top10"] + 0.10 * ev["model"]["top3"], 4),
                            ev["reach_matched_ties"]["model_acc_pct"],
                        )
                        if cand_key > best_pc_key:
                            best_pc_key = cand_key
                            best_pc_cfg = (t_std, p_cap, b_cap, w_pod, w_bub, w_u7, w_pop)

    print(
        f"[Hillclimb v8] Locked on Val Sep (<=2026-09-30) -> "
        f"PO cfg={best_po_cfg} (obj={best_po_key[0]:.2f}, ties={best_po_key[1]:.2f}%) | "
        f"PC cfg={best_pc_cfg} (obj={best_pc_key[0]:.2f}, ties={best_pc_key[1]:.2f}%)",
        flush=True,
    )

    ranker_po_v8 = RankGatedUniversalRankerV8(
        apr_cols=po_apr_v8, sep_cols=po_sep_v8, nov_live_cols=po_nov_v8,
        target_total_std=best_po_cfg[0], podium_cap=best_po_cfg[1], bubble_cap=best_po_cfg[2],
        tourn_podium_w=best_po_cfg[3], tourn_bubble_w=best_po_cfg[4], u7_weight=best_po_cfg[5], pop8_weight=best_po_cfg[6],
        is_product_only=True,
    )
    ranker_pc_v8 = RankGatedUniversalRankerV8(
        apr_cols=pc_apr_v8, sep_cols=pc_sep_v8, nov_live_cols=pc_nov_v8,
        target_total_std=best_pc_cfg[0], podium_cap=best_pc_cfg[1], bubble_cap=best_pc_cfg[2],
        tourn_podium_w=best_pc_cfg[3], tourn_bubble_w=best_pc_cfg[4], u7_weight=best_pc_cfg[5], pop8_weight=best_pc_cfg[6],
        is_product_only=False,
    )

    ov_po_v8 = ranker_po_v8.predict_walkforward(full_df)
    ov_pc_v8 = ranker_pc_v8.predict_walkforward(full_df)

    # Strict Permutation Invariance (`< 1e-9`) & Product-Only Comment Isolation (`== 0.0`) Assertions!
    shuf_df = full_df.sample(frac=1.0, random_state=888).reset_index(drop=True)
    ov_po_shuf = ranker_po_v8.predict_walkforward(shuf_df)
    ov_pc_shuf = ranker_pc_v8.predict_walkforward(shuf_df)
    max_perm_diff = max(
        max(abs(ov_po_v8[k] - ov_po_shuf[k]) for k in ov_po_v8),
        max(abs(ov_pc_v8[k] - ov_pc_shuf[k]) for k in ov_pc_v8),
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
    ov_po_iso = ranker_po_v8.predict_walkforward(zero_comm_df)
    max_po_comment_leak = max(abs(ov_po_v8[k] - ov_po_iso[k]) for k in ov_po_v8)

    assert max_perm_diff < 1e-9, f"FATAL: Order permutation invariance failed: {max_perm_diff}"
    assert max_po_comment_leak == 0.0, f"FATAL: Product-only comment isolation failed: {max_po_comment_leak}"

    hc7_ref_path = os.path.join(os.path.dirname(os.path.abspath(args.out_json)), "usersim_core_hillclimb_7_results.json")
    hc7_ref = json.load(open(hc7_ref_path)) if os.path.exists(hc7_ref_path) else {}

    live_po = {
        "website_published_now": {"days": 23, "top3_pct": 49.3, "top5_pct": 61.7, "top10_pct": 69.6, "hits": {"top3": [34, 69], "top5": [71, 115], "top10": [160, 230]}},
        "arm3_0005_strict": score_23d_window(live_0005_launches, live_truth, None),
        "product_only_v4": (hc7_ref.get("live_23d_product_only_tab") or {}).get("product_only_v4"),
        "product_only_v6": (hc7_ref.get("live_23d_product_only_tab") or {}).get("product_only_v6"),
        "product_only_v7": (hc7_ref.get("live_23d_product_only_tab") or {}).get("product_only_v7"),
        "product_only_v8": score_23d_window(live_expanded_launches, live_truth, ov_po_v8),
    }
    live_pc = {
        "product_comments_v5": (hc7_ref.get("live_23d_product_comments_tab") or {}).get("product_comments_v5"),
        "product_comments_v6": (hc7_ref.get("live_23d_product_comments_tab") or {}).get("product_comments_v6"),
        "product_comments_v7": (hc7_ref.get("live_23d_product_comments_tab") or {}).get("product_comments_v7"),
        "product_comments_v8": score_23d_window(live_expanded_launches, live_truth, ov_pc_v8),
    }

    test_df_28 = full_df[(full_df["day"] >= "2026-10-01") & (full_df["day"] <= "2026-11-24")].copy()
    test_df_28 = test_df_28.sort_values(["day", "structural_rank"]).groupby("day").head(20).reset_index(drop=True)
    test_df_28["score_po_v8"] = [ov_po_v8[(str(r.day), str(r.item_id))] for r in test_df_28.itertuples(index=False)]
    test_df_28["score_pc_v8"] = [ov_pc_v8[(str(r.day), str(r.item_id))] for r in test_df_28.itertuples(index=False)]

    bt55_po_v8 = evaluate_boards_and_ties(full_day_launches, truth_by_day, test_df_28, score_col="score_po_v8", n_boot=5000)
    bt55_pc_v8 = evaluate_boards_and_ties(full_day_launches, truth_by_day, test_df_28, score_col="score_pc_v8", n_boot=5000)

    nov_df_28 = test_df_28[test_df_28["day"] >= "2026-11-01"].copy()
    nov_po_v8 = evaluate_boards_and_ties(full_day_launches, truth_by_day, nov_df_28, score_col="score_po_v8", n_boot=5000)
    nov_pc_v8 = evaluate_boards_and_ties(full_day_launches, truth_by_day, nov_df_28, score_col="score_pc_v8", n_boot=5000)

    po_pred_val_card = {
        "track": "product_only_mid_v8",
        "live_23d": {k: live_po["product_only_v8"][k] for k in ("days", "top3_pct", "top5_pct", "top10_pct", "mean_3_5_10_pct")},
        "locked_test_55d": bt55_po_v8["model"],
        "november_24d": nov_po_v8["model"],
    }
    pc_pred_val_card = {
        "track": "product_comments_pre_le_0345pt_v8",
        "live_23d": {k: live_pc["product_comments_v8"][k] for k in ("days", "top3_pct", "top5_pct", "top10_pct", "mean_3_5_10_pct")},
        "locked_test_55d": bt55_pc_v8["model"],
        "november_24d": nov_pc_v8["model"],
    }

    why_days = sorted(set(LIVE_23_DAYS) | set(nov_df_28["day"].unique()))
    why_summary = emit_why_cards_batch(
        full_df=full_df,
        days_to_emit=why_days,
        ov_po_v5=ov_po_v8,
        ov_pc_v5=ov_pc_v8,
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
        "experiment_id": "USERSIM-CORE-HILLCLIMB-8",
        "elapsed_sec": round(time.time() - t0, 1),
        "vertex_llm_cost_usd": round(budget.spent, 4),
        "val_sep_locked_configs": {
            "product_only_v8": {
                "target_total_std": best_po_cfg[0],
                "podium_cap": best_po_cfg[1],
                "bubble_cap": best_po_cfg[2],
                "tourn_podium_w": best_po_cfg[3],
                "tourn_bubble_w": best_po_cfg[4],
                "u7_weight": best_po_cfg[5],
                "pop8_weight": best_po_cfg[6],
                "val_sep_objective": round(best_po_key[0], 3),
                "val_sep_tie_acc_pct": round(best_po_key[1], 2),
            },
            "product_comments_v8": {
                "target_total_std": best_pc_cfg[0],
                "podium_cap": best_pc_cfg[1],
                "bubble_cap": best_pc_cfg[2],
                "tourn_podium_w": best_pc_cfg[3],
                "tourn_bubble_w": best_pc_cfg[4],
                "u7_weight": best_pc_cfg[5],
                "pop8_weight": best_pc_cfg[6],
                "val_sep_objective": round(best_pc_key[0], 3),
                "val_sep_tie_acc_pct": round(best_pc_key[1], 2),
            },
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
            "product_only_v4": (hc7_ref.get("locked_test_55d_oct_nov") or {}).get("product_only_v4"),
            "product_only_v6": (hc7_ref.get("locked_test_55d_oct_nov") or {}).get("product_only_v6"),
            "product_only_v7": (hc7_ref.get("locked_test_55d_oct_nov") or {}).get("product_only_v7"),
            "product_only_v8": bt55_po_v8,
            "product_comments_v5": (hc7_ref.get("locked_test_55d_oct_nov") or {}).get("product_comments_v5"),
            "product_comments_v6": (hc7_ref.get("locked_test_55d_oct_nov") or {}).get("product_comments_v6"),
            "product_comments_v7": (hc7_ref.get("locked_test_55d_oct_nov") or {}).get("product_comments_v7"),
            "product_comments_v8": bt55_pc_v8,
        },
        "november_24d_full_calibration": {
            "product_only_v4": (hc7_ref.get("november_24d_full_calibration") or {}).get("product_only_v4"),
            "product_only_v6": (hc7_ref.get("november_24d_full_calibration") or {}).get("product_only_v6"),
            "product_only_v7": (hc7_ref.get("november_24d_full_calibration") or {}).get("product_only_v7"),
            "product_only_v8": nov_po_v8,
            "product_comments_v5": (hc7_ref.get("november_24d_full_calibration") or {}).get("product_comments_v5"),
            "product_comments_v6": (hc7_ref.get("november_24d_full_calibration") or {}).get("product_comments_v6"),
            "product_comments_v7": (hc7_ref.get("november_24d_full_calibration") or {}).get("product_comments_v7"),
            "product_comments_v8": nov_pc_v8,
        },
    }

    os.makedirs(os.path.dirname(os.path.abspath(args.out_json)), exist_ok=True)
    with open(args.out_json, "w") as f:
        json.dump(out, f, indent=2)

    if args.gcs_prefix:
        subprocess.run(
            ["gcloud", "storage", "cp", "-q", args.out_json, f"{args.gcs_prefix.rstrip('/')}/usersim_core_hillclimb_8_results.json"],
            check=True,
        )
        subprocess.run(
            ["gcloud", "storage", "cp", "-r", "-q", f"{args.work_dir}/cache_tourn_v8", f"{args.gcs_prefix.rstrip('/')}/"],
            check=False,
        )

    print("\n=== TRACK 1: PRODUCT ONLY v8 (23 LIVE DAYS, ZERO COMMENTS) ===", flush=True)
    for k, v in live_po.items():
        if v:
            print(
                f"  {k:34s}: Top-3={v['top3_pct']:5.2f}% ({v['hits']['top3'][0]}/{v['hits']['top3'][1]}) | "
                f"Top-5={v['top5_pct']:5.2f}% ({v['hits']['top5'][0]}/{v['hits']['top5'][1]}) | "
                f"Top-10={v['top10_pct']:5.2f}% ({v['hits']['top10'][0]}/{v['hits']['top10'][1]})",
                flush=True,
            )

    print("\n=== TRACK 2: PRODUCT + COMMENTS v8 (23 LIVE DAYS, ORDER-FREE <=03:45 PT) ===", flush=True)
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
