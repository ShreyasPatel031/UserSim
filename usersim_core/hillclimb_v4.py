"""USERSIM-CORE-HILLCLIMB-4 Runner (`usersim_core/hillclimb_v4.py`).

Evaluates 4-Step Interactive Post-Login Google-SSO CUA Testing + Multimodal `gemini-2.5-pro`
Screenshot/Trace Judging + Focused Top-8 Finalist Head-to-Head Panel on:
  - Track 1: `Product only` (`mid`, `00:05 PT` + post-midnight arrivals, STRICTLY ZERO COMMENTS)
  - Track 2: `Product + comments` (`pre`, order-free `<= 03:45 PT` comments, ZERO PH rank/votes/order)
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import glob
import hashlib
import json
import math
import os
import re
import time
from typing import Any

import httpx
import numpy as np
import pandas as pd

from simharness.bench import scrub
from simharness.models.llm import Budget, JsonlCache, VertexOpenAICompat, _VertexAuth
import usersim_core.cohort_sim  # noqa: F401 - installs _sa_vertex_token
from usersim_core.apify_features import load_apify_signals
from usersim_core.calibration import WalkForwardCalibrator
from usersim_core.cohort_sim import VertexGeminiPro, _parse_comparative_json
from usersim_core.cua_runner import inspect_surfaces_for_items
from usersim_core.hillclimb_v2 import (
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
from usersim_core.sanitizer import SanitizedSurface, sanitize_text


INTERACTIVE_CUA_V4_FEATURES = [
    "cua4_working_prod_z",
    "cua4_workflow_resp_z",
    "cua4_blocker_z",
    "mm_hands_on_works_z",
    "mm_ui_craft_depth_z",
    "mm_onboarding_ease_z",
    "mm_discerning_adopt_z",
    "v4_finalist_po_z",
]


MULTIMODAL_CUA_PROMPT = """You are a discerning software engineer & product builder evaluating a live interactive browser session on a newly launched product (ZERO votes, ZERO comments, ZERO rankings exist).

MATCHED USER PERSONA (strictly prior history):
{persona_brief}

PRODUCT CLAIMED AT LAUNCH:
Name: {title}
Tagline: {summary}
Description: {desc}

4-STEP LIVE BROWSER & GOOGLE-SSO EXECUTION TRACE (sanitized):
- Entry CTA clicked: {cta_clicked}
- Google SSO attempted: {sso_attempted} | Entered post-login app via Google SSO: {sso_entered}
- Interactive action executed inside app/demo: {workflow_action} | App DOM responded dynamically: {workflow_responded}
- Landed in workspace route: {in_workspace} | Reached working product/repo: {working_prod}
- Blockers hit: hard_paywall={hit_paywall}, waitlist_wall={hit_waitlist}, error_toast={hit_error}
- Docs/API link: {has_docs} | Pricing link: {has_pricing} | GitHub OSS link: {has_github} | Code blocks: {code_blocks}
- Step trace: {steps_json}
- Landing DOM excerpt: {landing_clean}
- Inside-App / Step-3 DOM excerpt: {inside_clean}
- Pricing page excerpt: {pricing_clean}

Evaluate strictly from the screenshots (if attached) and the hands-on browser execution trace:
1. Did a real working product, post-SSO workspace, interactive playground, or substantive open-source tool actually work hands-on vs a static marketing shell, broken wrapper, or waitlist/paywall gate?
2. Rate visual & engineering craft depth (0.10 = generic template/wrapper, 0.90 = high-craft, cohesive, real tool).

Reply in JSON ONLY:
{{
  "hands_on_works": 0.00,
  "ui_craft_depth": 0.00,
  "onboarding_ease": 0.00,
  "discerning_adopt": 0.00,
  "exec_digest": "<max 22 words factual hands-on finding: what worked, post-SSO workspace reality, or blocker>"
}}"""


FINALIST_TOP8_PO_PROMPT = """You are a calibrated 5-person panel of discerning Product Hunt builders selecting the TOP 3 winners among today's 8 strongest product contenders strictly from PRODUCT & HANDS-ON INTERACTIVE EXECUTION (ZERO comments, ZERO votes, ZERO rankings).

PANEL OF REAL MATCHED USERS (< D):
{panel_block}

TODAY'S {n_items} FINALIST PRODUCTS (randomized MD5 order 1..{n_items}; compare them head-to-head on real hands-on workflow execution, post-Google-SSO workspace quality, UI/engineering craft, instant utility, and absence of waitlist/paywall friction):
{items_block}

RULES:
1. Spread `win_conviction` across 0.15..0.95 so your #1, #2, #3 picks stand out clearly from #5..#{n_items}.
2. Hands-on verified working workspaces, interactive demos, and high-craft developer/workflow tools beat vague marketing pages, hard paywalls, and generic wrappers.
3. Treat `[NOT_INTERACTIVELY_TESTED]` neutrally (judge from pitch & surface without penalty).

Return JSON ONLY (every `idx` 1..{n_items} once):
{{
  "evaluations": [
    {{
      "idx": 1,
      "p_endorse": 0.00,
      "would_use": 0.00,
      "technical_substance": 0.00,
      "friction_severity": 0.00
    }}
  ]
}}"""


def score_multimodal_cua_traces(
    cua_records: dict[str, dict[str, Any]],
    item_lookup: dict[str, dict[str, Any]],
    pool: UniversalUserPool,
    cache: JsonlCache,
    budget: Budget,
    project: str = "project-amer-scs-sandbox",
    workers: int = 12,
) -> tuple[dict[str, dict[str, Any]], dict[str, int]]:
    """Judge 4-step interactive traces + safe screenshots with multimodal `gemini-2.5-pro`."""
    url = f"https://aiplatform.googleapis.com/v1/projects/{project}/locations/global/publishers/google/models/gemini-2.5-pro:generateContent"
    price_in, price_out = 1.25, 10.00

    stats = {
        "total_cua4_records": len(cua_records),
        "clean_sessions": 0,
        "sso_attempted": 0,
        "sso_entered": 0,
        "workflow_actions_triggered": 0,
        "workflow_dom_responded": 0,
        "reached_working_product": 0,
        "paywall_or_waitlist_or_error": 0,
        "screenshots_judged": 0,
        "sanitized_leaks_redacted": 0,
    }

    clean_inputs: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    for lid, rec in sorted(cua_records.items()):
        if rec.get("google_sso_attempted"):
            stats["sso_attempted"] += 1
        if rec.get("google_sso_entered"):
            stats["sso_entered"] += 1
        if str(rec.get("workflow_action") or "none") != "none":
            stats["workflow_actions_triggered"] += 1
        if rec.get("workflow_responded"):
            stats["workflow_dom_responded"] += 1
        if rec.get("reached_working_product"):
            stats["reached_working_product"] += 1
        if rec.get("hit_paywall") or rec.get("hit_waitlist") or rec.get("hit_error_toast"):
            stats["paywall_or_waitlist_or_error"] += 1
        if rec.get("access_status") == "clean":
            stats["clean_sessions"] += 1
            if rec.get("landing_jpg_b64") or rec.get("inside_jpg_b64"):
                stats["screenshots_judged"] += 1
            clean_inputs.append((lid, rec, item_lookup.get(lid, {})))

    def _judge_one(args_t: tuple[str, dict[str, Any], dict[str, Any]]) -> tuple[str, dict[str, Any]]:
        lid, rec, it = args_t
        day = str(rec.get("day") or it.get("day") or "2026-11-01")
        l_clean, nl1 = sanitize_text(str(rec.get("landing_text") or ""), item_day=day)
        i_clean, nl2 = sanitize_text(str(rec.get("inside_app_text") or ""), item_day=day)
        p_clean, nl3 = sanitize_text(str(rec.get("pricing_text") or ""), item_day=day)
        st_clean, nl4 = sanitize_text(json.dumps(rec.get("steps_trace") or []), item_day=day)
        n_red = int(nl1 + nl2 + nl3 + nl4)

        ckey = ("mm_cua4_pro_v1", lid, day)
        if ckey in cache:
            cached_d = dict(cache[ckey])
            cached_d["n_redacted"] = n_red
            return lid, cached_d

        d_eff = day if day <= "2026-11-24" else "2026-11-24"
        title = scrub(str(it.get("title") or ""))
        summary = scrub(str(it.get("summary") or ""))
        desc = scrub(str(it.get("description") or ""))[:280]
        matched = pool.match_cohort(d_eff, f"{title} {summary}", k=1)
        p_brief = matched[0]["history_brief"][:320] if matched else "Discerning software builder & early adopter."

        prompt = MULTIMODAL_CUA_PROMPT.format(
            persona_brief=p_brief,
            title=title,
            summary=summary,
            desc=desc,
            cta_clicked=str(rec.get("cta_clicked") or "none"),
            sso_attempted=bool(rec.get("google_sso_attempted")),
            sso_entered=bool(rec.get("google_sso_entered")),
            workflow_action=str(rec.get("workflow_action") or "none"),
            workflow_responded=bool(rec.get("workflow_responded")),
            in_workspace=bool(rec.get("in_workspace_route")),
            working_prod=bool(rec.get("reached_working_product")),
            hit_paywall=bool(rec.get("hit_paywall")),
            hit_waitlist=bool(rec.get("hit_waitlist")),
            hit_error=bool(rec.get("hit_error_toast")),
            has_docs=bool(rec.get("has_docs_link")),
            has_pricing=bool(rec.get("has_pricing_link")),
            has_github=bool(rec.get("has_github_link")),
            code_blocks=int(rec.get("code_blocks_n") or 0),
            steps_json=st_clean[:500],
            landing_clean=l_clean[:850],
            inside_clean=i_clean[:950],
            pricing_clean=p_clean[:400],
        )

        parts: list[dict[str, Any]] = []
        # Attach screenshots ONLY if sanitizer found zero PH badge leaks on that page!
        if nl1 == 0 and rec.get("landing_jpg_b64"):
            parts.append({"inlineData": {"mimeType": "image/jpeg", "data": rec["landing_jpg_b64"]}})
        if nl2 == 0 and rec.get("inside_jpg_b64"):
            parts.append({"inlineData": {"mimeType": "image/jpeg", "data": rec["inside_jpg_b64"]}})
        parts.append({"text": prompt})

        worst = 0.020
        budget.reserve(worst)
        body = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 380,
                "responseMimeType": "application/json",
                "thinkingConfig": {"thinkingBudget": 128},
            },
        }
        parsed_out = {
            "hands_on_works": 0.50,
            "ui_craft_depth": 0.50,
            "onboarding_ease": 0.50,
            "discerning_adopt": 0.48,
            "exec_digest": "",
        }
        for att in range(3):
            try:
                r = httpx.post(
                    url,
                    json=body,
                    timeout=45.0,
                    headers={"Authorization": f"Bearer {_VertexAuth.token()}", "Content-Type": "application/json"},
                )
                r.raise_for_status()
                dj = r.json()
                um = dj.get("usageMetadata", {})
                ti = int(um.get("promptTokenCount", 0))
                to = int(um.get("candidatesTokenCount", 0)) + int(um.get("thoughtsTokenCount", 0))
                actual = ti * price_in / 1e6 + to * price_out / 1e6
                budget.settle("mm_cua4:gemini-2.5-pro", worst, actual)
                txt = "".join(p.get("text", "") for p in ((dj.get("candidates") or [{}])[0].get("content") or {}).get("parts") or [])
                m = re.search(r"\{.*\}", txt, re.S)
                if m:
                    j = json.loads(m.group(0))
                    clean_dig, _ = sanitize_text(str(j.get("exec_digest") or ""), item_day=day)
                    parsed_out = {
                        "hands_on_works": float(np.clip(float(j.get("hands_on_works", 0.5)), 0.0, 1.0)),
                        "ui_craft_depth": float(np.clip(float(j.get("ui_craft_depth", 0.5)), 0.0, 1.0)),
                        "onboarding_ease": float(np.clip(float(j.get("onboarding_ease", 0.5)), 0.0, 1.0)),
                        "discerning_adopt": float(np.clip(float(j.get("discerning_adopt", 0.48)), 0.0, 1.0)),
                        "exec_digest": clean_dig[:200],
                    }
                break
            except Exception:
                if att == 2:
                    budget.settle("mm_cua4:gemini-2.5-pro", worst, 0.0)
                else:
                    time.sleep(2 * (att + 1))

        cache[ckey] = parsed_out
        out_with_red = dict(parsed_out)
        out_with_red["n_redacted"] = n_red
        return lid, out_with_red

    judged: dict[str, dict[str, Any]] = {}
    done_n = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(_judge_one, item_t) for item_t in clean_inputs]
        for fut in as_completed(futs):
            lid, res = fut.result()
            stats["sanitized_leaks_redacted"] += int(res.pop("n_redacted", 0))
            judged[lid] = res
            done_n += 1
            if done_n % 50 == 0 or done_n == len(clean_inputs):
                print(f"  [Multimodal CUA v4] {done_n}/{len(clean_inputs)} sessions judged (${budget.spent:.3f})", flush=True)
    cache.roll()
    return judged, stats


def run_top8_finalist_po_panel(
    df_sep_nov: pd.DataFrame,
    pool: UniversalUserPool,
    cua_records: dict[str, dict[str, Any]],
    mm_judged: dict[str, dict[str, Any]],
    cache: JsonlCache,
    budget: Budget,
    workers: int = 8,
) -> dict[tuple[str, str], float]:
    """Focused head-to-head Zero-Comment Top-8 Finalist Panel (`gpt-oss-120b` + `gemini-2.5-pro`) for Top-3/Top-5 separation."""
    gpt120b = VertexOpenAICompat(
        model="openai/gpt-oss-120b-maas",
        project="project-amer-scs-sandbox",
        region="us-central1",
        temperature=0.12,
        budget=budget,
        max_out=2500,
        extra={"reasoning_effort": "low", "response_format": {"type": "json_object"}},
    )
    pro = VertexGeminiPro(
        project="project-amer-scs-sandbox",
        region="global",
        temperature=0.12,
        budget=budget,
        max_out=2500,
        thinking_budget=256,
    )

    days = sorted(df_sep_nov["day"].unique())
    # Select Top-10 structural contenders per day (deterministic by structural_score + item_id — 100% invariant to input row order!)
    top_by_day: dict[str, list[dict[str, Any]]] = {}
    for d in days:
        sub = df_sep_nov[df_sep_nov["day"] == d].to_dict(orient="records")
        sub = sorted(sub, key=lambda r: (-float(r["structural_score"]), str(r["item_id"])))[:9]
        top_by_day[d] = sub

    def _eval_day(d: str) -> dict[str, float]:
        items = top_by_day[d]
        n = len(items)
        if n < 3:
            return {}
        perm = sorted(range(n), key=lambda i: hashlib.md5(f"v4_fin:{d}:{items[i]['item_id']}".encode()).hexdigest())
        ordered = [items[i] for i in perm]

        d_eff = d if d <= "2026-11-24" else "2026-11-24"
        panel = pool.match_cohort(d_eff, " ".join(f"{x['title']} {x['summary']}" for x in ordered[:5]), k=5)
        panel_str = "\n".join(
            f"- Member #{k+1} (critique_rate={u.get('critique_rate',0.2):.0%}): {u.get('history_brief','')[:160]}"
            for k, u in enumerate(panel[:5])
        )

        blocks = []
        sig_parts = []
        for pos, it in enumerate(ordered, start=1):
            lid = str(it["item_id"])
            cr = cua_records.get(lid) or {}
            mm = mm_judged.get(lid) or {}
            if mm:
                cua_line = (
                    f"Hands-On 4-Step Browser Test: sso_entered={bool(cr.get('google_sso_entered'))}, "
                    f"action={cr.get('workflow_action','none')}, dom_responded={bool(cr.get('workflow_responded'))}, "
                    f"works_score={mm['hands_on_works']:.2f}, craft={mm['ui_craft_depth']:.2f}, "
                    f"ease={mm['onboarding_ease']:.2f} | Finding: {mm.get('exec_digest','')}"
                )
                sig_parts.append(f"{lid}:{mm['hands_on_works']:.2f}")
            else:
                cua_line = "[NOT_INTERACTIVELY_TESTED]"
                sig_parts.append(f"{lid}:na")
            tgs = ", ".join((it.get("tags") or [])[:5]) if isinstance(it.get("tags"), (list, tuple)) else ""
            blocks.append(
                f"[{pos}] {scrub(str(it['title']))} — {scrub(str(it['summary']))}\n"
                f"    Topics: {tgs} | Pitch: {scrub(str(it.get('description') or ''))[:260]}\n"
                f"    {cua_line}"
            )

        prompt = FINALIST_TOP8_PO_PROMPT.format(
            panel_block=panel_str,
            n_items=n,
            items_block="\n".join(blocks),
        )
        sig = hashlib.md5(("|".join(sig_parts)).encode()).hexdigest()[:10]

        k120 = ("v4_fin_120b", d, sig)
        if k120 not in cache:
            for att in range(3):
                try:
                    p120 = _parse_comparative_json(gpt120b.call(prompt), n)
                    if len(p120) >= max(2, n // 2):
                        cache[k120] = {str(k): v for k, v in p120.items()}
                        break
                except Exception:
                    time.sleep(2 * (att + 1))
        r120 = {int(k): v for k, v in (cache.data.get(k120) or {}).items()}

        kpro = ("v4_fin_pro", d, sig)
        if kpro not in cache:
            for att in range(4):
                try:
                    ppro = _parse_comparative_json(pro.call(prompt), n)
                    if len(ppro) >= max(2, n // 2):
                        cache[kpro] = {str(k): v for k, v in ppro.items()}
                        break
                except Exception:
                    time.sleep(3 * (att + 1))
        rpro = {int(k): v for k, v in (cache.data.get(kpro) or {}).items()}

        out_d: dict[str, float] = {}
        for pos, it in enumerate(ordered, start=1):
            lid = str(it["item_id"])
            a, b = r120.get(pos), rpro.get(pos)
            if a and b:
                pe = 0.40 * float(a["p_endorse"]) + 0.60 * float(b["p_endorse"])
                wu = 0.40 * float(a["would_use"]) + 0.60 * float(b["would_use"])
                sb = 0.40 * float(a["technical_substance"]) + 0.60 * float(b["technical_substance"])
                fr = 0.40 * float(a["friction_severity"]) + 0.60 * float(b["friction_severity"])
            elif b:
                pe, wu, sb, fr = float(b["p_endorse"]), float(b["would_use"]), float(b["technical_substance"]), float(b["friction_severity"])
            elif a:
                pe, wu, sb, fr = float(a["p_endorse"]), float(a["would_use"]), float(a["technical_substance"]), float(a["friction_severity"])
            else:
                continue
            out_d[lid] = pe + 0.50 * wu + 0.35 * sb - 0.55 * fr
        return out_d

    scores_out: dict[tuple[str, str], float] = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_eval_day, d): d for d in days}
        for fut in as_completed(futs):
            d = futs[fut]
            res_d = fut.result()
            if len(res_d) >= 3:
                vals = np.array(list(res_d.values()), dtype=np.float64)
                mu, sd = float(np.mean(vals)), float(np.std(vals))
                if sd > 1e-8:
                    for lid, v in res_d.items():
                        scores_out[(d, lid)] = float(np.clip((v - mu) / sd, -2.5, 2.5))
    cache.roll()
    return scores_out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--work-dir", required=True)
    ap.add_argument("--live23-dir", required=True)
    ap.add_argument("--apify-dir", required=True)
    ap.add_argument("--hc3-sweep-glob", required=True)
    ap.add_argument("--hc4-cua-glob", required=True)
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

    # 1. Load Hill-Climb v3 surfaces + Hill-Climb v4 4-Step Interactive CUA records!
    day_by_id = dict(zip(full_df["item_id"].astype(str), full_df["day"].astype(str)))
    surfaces_by_id, sso_meta, _ = load_fleet_sso_surfaces(args.hc3_sweep_glob, surfaces_by_id, day_by_id)

    cua4_records: dict[str, dict[str, Any]] = {}
    for p in sorted(glob.glob(args.hc4_cua_glob)):
        for line in open(p):
            if line.strip():
                r = json.loads(line)
                if r.get("item_id"):
                    cua4_records[str(r["item_id"])] = r

    budget = Budget(cap_usd=6.0)
    mm_cache = JsonlCache(f"{args.work_dir}/cache_mm_cua4")
    item_lookup = {str(r["item_id"]): r for r in full_df.to_dict(orient="records")}

    print(f"[Hillclimb v4] Judging {len(cua4_records)} 4-step interactive CUA traces + screenshots with multimodal Gemini 2.5 Pro...", flush=True)
    mm_judged, cua4_stats = score_multimodal_cua_traces(
        cua4_records, item_lookup, pool, mm_cache, budget, workers=12
    )
    print(f"[Hillclimb v4] 4-Step Interactive CUA Stats: {json.dumps(cua4_stats)}", flush=True)

    # 2. Attach v3 + v4 features!
    comm_map = extract_pre_reveal_comments(bench, pool, args.live23_dir, cutoff_minutes_after_midnight_pt=225)
    full_df = attach_walkforward_product_comment_features(full_df, comm_map)
    full_df, _ = load_apify_signals(full_df, args.apify_dir, args.data_dir)
    full_df = attach_v3_causal_features(full_df, bench, surfaces_by_id, sso_meta, args.live23_dir)

    # Load cached v3_po and v2 cohort scores ($0.00 cached!) + run focused Top-8 Finalist Head-to-Head Panel!
    v3_po_cache = JsonlCache(f"{args.work_dir}/cache_cohort_sim_v3_po")
    v2_cache = JsonlCache(f"{args.work_dir}/cache_cohort_sim_v2")
    fin_cache = JsonlCache(f"{args.work_dir}/cache_finalist_v4_po")
    calibrator = WalkForwardCalibrator()
    hist_for_cal = full_df[full_df["day"] <= "2026-11-24"].copy()
    g2_notes = load_g2_category_pain_notes(args.apify_dir)

    sep_nov_mask = full_df["day"] >= "2026-09-01"
    po_scored = run_v3_product_only_cohort_sim(
        full_df[sep_nov_mask], hist_for_cal, pool, calibrator, surfaces_by_id, sso_meta, g2_notes, v3_po_cache, budget, workers=6
    )
    pc_scored = run_v2_comparative_sim(
        full_df[sep_nov_mask], hist_for_cal, pool, calibrator, surfaces_by_id, v2_cache, budget, workers=6
    )

    print(f"[Hillclimb v4] Running Zero-Comment Top-9 Finalist Head-to-Head Panel across Sep-Nov...", flush=True)
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

    # Attach 4-step Interactive CUA + Multimodal Pro + Finalist z-scores (0.0 neutral when not inspected!)
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

    print(f"[Hillclimb v4] Total Vertex LLM cost: ${budget.spent:.4f}", flush=True)

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
        fin_bonus: float = 0.0,
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
                    shift = shift + m_sep.predict_shift(te)

            if fin_bonus > 0.0:
                # Zero-parameter / Val-Sep-calibrated head-to-head tie-breaker among Top-9 contenders + hands-on works!
                direct_sig = (
                    0.55 * te["v4_finalist_po_z"].to_numpy(dtype=np.float64)
                    + 0.25 * te["mm_discerning_adopt_z"].to_numpy(dtype=np.float64)
                    + 0.20 * te["mm_hands_on_works_z"].to_numpy(dtype=np.float64)
                )
                shift = shift + fin_bonus * direct_sig

            shift = np.clip(shift, -max_shift, max_shift)
            scores = te["structural_score"].to_numpy(dtype=np.float64) + shift
            for r_id, r_day, sc in zip(te["item_id"], te["day"], scores):
                overrides[(str(r_day), str(r_id))] = float(sc)
        return overrides

    val_bt = {d: v for d, v in full_day_launches.items() if d.startswith("2026-09")}
    val_df_only = full_df[full_df["day"] <= "2026-09-30"].copy()

    po_apr_cols = ALL_RESIDUAL_FEATURES + PRODUCT_ONLY_V3_TABULAR
    po_sep_cols = COHORT_V3_PO_FEATURES + INTERACTIVE_CUA_V4_FEATURES

    # Lock (`target_std_apr`, `max_shift`, `fin_bonus`) strictly on Val Sep (`2026-09`)!
    best_po_val, best_po_cfg = -1e9, (0.075, 0.190, 0.045)
    for ts_a in (0.065, 0.080):
        for ms_a in (0.170, 0.210):
            for fb_a in (0.0, 0.035, 0.055, 0.075):
                ov_v = predict_walkforward(val_df_only, po_apr_cols, [], ts_a, 0.0, ms_a, fin_bonus=fb_a)
                vsub = val_df_only[val_df_only["day"].str.startswith("2026-09")].copy()
                vsub["final_score"] = [ov_v[(str(r.day), str(r.item_id))] for r in vsub.itertuples(index=False)]
                ev = evaluate_boards_and_ties(val_bt, truth_by_day, vsub, n_boot=200)
                mv = ev["model"]["mean_3_5_10"]
                if mv > best_po_val:
                    best_po_val, best_po_cfg = mv, (ts_a, ms_a, fb_a)

    pc_apr_cols = po_apr_cols + PROD_COMMENT_FEATURES + COMMENT_V3_EXTRA
    pc_sep_cols = po_sep_cols + COHORT_V2_FEATURES
    best_pc_val, best_pc_cfg = -1e9, (0.105, 0.220, 0.025)
    for ts_b in (0.095, 0.115):
        for ms_b in (0.200, 0.240):
            for fb_b in (0.0, 0.025, 0.045):
                ov_v = predict_walkforward(val_df_only, pc_apr_cols, [], ts_b, 0.0, ms_b, fin_bonus=fb_b)
                vsub = val_df_only[val_df_only["day"].str.startswith("2026-09")].copy()
                vsub["final_score"] = [ov_v[(str(r.day), str(r.item_id))] for r in vsub.itertuples(index=False)]
                ev = evaluate_boards_and_ties(val_bt, truth_by_day, vsub, n_boot=200)
                mv = ev["model"]["mean_3_5_10"]
                if mv > best_pc_val:
                    best_pc_val, best_pc_cfg = mv, (ts_b, ms_b, fb_b)

    print(f"[Hillclimb v4] Locked on Val Sep -> Product-Only cfg={best_po_cfg} ({best_po_val:.2f}%) | Product+Comments cfg={best_pc_cfg} ({best_pc_val:.2f}%)", flush=True)

    ov_po_v3 = predict_walkforward(full_df, po_apr_cols, COHORT_V3_PO_FEATURES, 0.075, 0.045, 0.150, fin_bonus=0.0)
    ov_po_v4 = predict_walkforward(full_df, po_apr_cols, po_sep_cols, best_po_cfg[0], 0.050, best_po_cfg[1], fin_bonus=best_po_cfg[2])
    ov_pc_v3 = predict_walkforward(full_df, pc_apr_cols, COHORT_V3_PO_FEATURES + COHORT_V2_FEATURES, 0.125, 0.055, 0.220, fin_bonus=0.0)
    ov_pc_v4 = predict_walkforward(full_df, pc_apr_cols, pc_sep_cols, best_pc_cfg[0], 0.055, best_pc_cfg[1], fin_bonus=best_pc_cfg[2])

    # 1. Live 23-day Website Window (`Oct 29 - Nov 25`)
    live_po = {
        "website_published_now": {"days": 23, "top3_pct": 49.3, "top5_pct": 61.7, "top10_pct": 69.6, "hits": {"top3": [34, 69], "top5": [71, 115], "top10": [160, 230]}},
        "arm3_0005_strict": score_23d_window(live_0005_launches, live_truth, None),
        "product_only_v3": score_23d_window(live_expanded_launches, live_truth, ov_po_v3),
        "product_only_v4_interactive_cua": score_23d_window(live_expanded_launches, live_truth, ov_po_v4),
    }
    live_pc = {
        "product_comments_v3": score_23d_window(live_expanded_launches, live_truth, ov_pc_v3),
        "product_comments_v4_interactive_cua": score_23d_window(live_expanded_launches, live_truth, ov_pc_v4),
    }

    # 2. Locked Test (`55d Oct-Nov` & `24d Nov`)
    test_df = full_df[(full_df["day"] >= "2026-10-01") & (full_df["day"] <= "2026-11-24")].copy()
    test_df = test_df.sort_values(["day", "structural_rank"]).groupby("day").head(20).reset_index(drop=True)
    test_df["score_po_v3"] = [ov_po_v3[(str(r.day), str(r.item_id))] for r in test_df.itertuples(index=False)]
    test_df["score_po_v4"] = [ov_po_v4[(str(r.day), str(r.item_id))] for r in test_df.itertuples(index=False)]
    test_df["score_pc_v3"] = [ov_pc_v3[(str(r.day), str(r.item_id))] for r in test_df.itertuples(index=False)]
    test_df["score_pc_v4"] = [ov_pc_v4[(str(r.day), str(r.item_id))] for r in test_df.itertuples(index=False)]

    bt55_po_v3 = evaluate_boards_and_ties(full_day_launches, truth_by_day, test_df, score_col="score_po_v3", n_boot=5000)
    bt55_po_v4 = evaluate_boards_and_ties(full_day_launches, truth_by_day, test_df, score_col="score_po_v4", n_boot=5000)
    bt55_pc_v3 = evaluate_boards_and_ties(full_day_launches, truth_by_day, test_df, score_col="score_pc_v3", n_boot=5000)
    bt55_pc_v4 = evaluate_boards_and_ties(full_day_launches, truth_by_day, test_df, score_col="score_pc_v4", n_boot=5000)

    nov_df = test_df[test_df["day"] >= "2026-11-01"].copy()
    nov_po_v3 = evaluate_boards_and_ties(full_day_launches, truth_by_day, nov_df, score_col="score_po_v3", n_boot=5000)
    nov_po_v4 = evaluate_boards_and_ties(full_day_launches, truth_by_day, nov_df, score_col="score_po_v4", n_boot=5000)
    nov_pc_v3 = evaluate_boards_and_ties(full_day_launches, truth_by_day, nov_df, score_col="score_pc_v3", n_boot=5000)
    nov_pc_v4 = evaluate_boards_and_ties(full_day_launches, truth_by_day, nov_df, score_col="score_pc_v4", n_boot=5000)

    # 3. Leak & Zero-Comment Isolation Audits!
    shuf_df = full_df.sample(frac=1.0, random_state=444).reset_index(drop=True)
    ov_pc_shuf = predict_walkforward(shuf_df, pc_apr_cols, pc_sep_cols, best_pc_cfg[0], 0.055, best_pc_cfg[1], fin_bonus=best_pc_cfg[2])
    max_perm_diff = max(abs(ov_pc_v4[k] - ov_pc_shuf[k]) for k in ov_pc_v4)

    zero_comm_df = full_df.copy()
    for c in PROD_COMMENT_FEATURES + COMMENT_V3_EXTRA + COHORT_V2_FEATURES:
        if c in zero_comm_df.columns:
            zero_comm_df[c] = -999.0
    ov_po_iso = predict_walkforward(zero_comm_df, po_apr_cols, po_sep_cols, best_po_cfg[0], 0.050, best_po_cfg[1], fin_bonus=best_po_cfg[2])
    max_po_comment_leak = max(abs(ov_po_v4[k] - ov_po_iso[k]) for k in ov_po_v4)

    assert max_perm_diff < 1e-9, f"Permutation invariance failed: {max_perm_diff}"
    assert max_po_comment_leak == 0.0, f"Product-only comment isolation failed: {max_po_comment_leak}"

    # Sample top post-SSO / interactive discoveries to show concrete product-testing proof!
    sample_interactive_findings = []
    for lid, rec in sorted(cua4_records.items()):
        mm = mm_judged.get(lid)
        if mm and (rec.get("google_sso_entered") or rec.get("workflow_responded")):
            it = item_lookup.get(lid, {})
            sample_interactive_findings.append({
                "day": rec.get("day"),
                "item_id": lid,
                "title": it.get("title"),
                "sso_entered": bool(rec.get("google_sso_entered")),
                "workflow_action": rec.get("workflow_action"),
                "workflow_responded": bool(rec.get("workflow_responded")),
                "hands_on_works": mm["hands_on_works"],
                "ui_craft_depth": mm["ui_craft_depth"],
                "exec_digest": mm["exec_digest"],
            })

    out = {
        "experiment_id": "USERSIM-CORE-HILLCLIMB-4",
        "elapsed_sec": round(time.time() - t0, 1),
        "vertex_llm_cost_usd": round(budget.spent, 4),
        "interactive_cua_4step_stats": cua4_stats,
        "sample_interactive_findings": sample_interactive_findings[:20],
        "leak_and_isolation_audits": {
            "input_order_permutation_max_abs_diff": float(max_perm_diff),
            "product_only_comment_isolation_max_abs_diff": float(max_po_comment_leak),
            "screenshots_guarded_by_zero_ph_badge_check": True,
        },
        "live_23d_product_only_tab": live_po,
        "live_23d_product_comments_tab": live_pc,
        "locked_test_55d_oct_nov": {
            "product_only_v3": bt55_po_v3,
            "product_only_v4": bt55_po_v4,
            "product_comments_v3": bt55_pc_v3,
            "product_comments_v4": bt55_pc_v4,
        },
        "november_24d_full_calibration": {
            "product_only_v3": nov_po_v3,
            "product_only_v4": nov_po_v4,
            "product_comments_v3": nov_pc_v3,
            "product_comments_v4": nov_pc_v4,
        },
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out_json)), exist_ok=True)
    json.dump(out, open(args.out_json, "w"), indent=2)

    print("\n=== TRACK 1: PRODUCT ONLY (23 LIVE DAYS, ZERO COMMENTS) ===", flush=True)
    for k, v in live_po.items():
        print(f"  {k:40s}: Top-3={v['top3_pct']:5.1f}% ({v['hits']['top3'][0]}/{v['hits']['top3'][1]}) | Top-5={v['top5_pct']:5.1f}% ({v['hits']['top5'][0]}/{v['hits']['top5'][1]}) | Top-10={v['top10_pct']:5.1f}% ({v['hits']['top10'][0]}/{v['hits']['top10'][1]})", flush=True)

    print("\n=== TRACK 2: PRODUCT + COMMENTS (23 LIVE DAYS, ORDER-FREE <=03:45 PT) ===", flush=True)
    for k, v in live_pc.items():
        print(f"  {k:40s}: Top-3={v['top3_pct']:5.1f}% ({v['hits']['top3'][0]}/{v['hits']['top3'][1]}) | Top-5={v['top5_pct']:5.1f}% ({v['hits']['top5'][0]}/{v['hits']['top5'][1]}) | Top-10={v['top10_pct']:5.1f}% ({v['hits']['top10'][0]}/{v['hits']['top10'][1]})", flush=True)

    print("\n=== 55-DAY LOCKED TEST (OCT 1 - NOV 24) ===", flush=True)
    for k, v in out["locked_test_55d_oct_nov"].items():
        print(f"  {k:24s}: arm3={v['arm3']} -> model={v['model']} | lift={v['paired_lift_pts']['mean_3_5_10']} | ties={v['reach_matched_ties']['model_acc_pct']}%", flush=True)

    print("\n=== 24-DAY NOVEMBER FULL CALIBRATION (NOV 1 - NOV 24) ===", flush=True)
    for k, v in out["november_24d_full_calibration"].items():
        print(f"  {k:24s}: arm3={v['arm3']} -> model={v['model']} | lift={v['paired_lift_pts']['mean_3_5_10']} | ties={v['reach_matched_ties']['model_acc_pct']}%", flush=True)


if __name__ == "__main__":
    main()
