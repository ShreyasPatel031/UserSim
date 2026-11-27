"""Privacy-Safe Per-Launch Interpretability Cards (`usersim_core/why_cards_v5.py`).

Generates `results/web/why/`-compatible explainability JSONs (`<day>_mid.json` for `Product only` and
`<day>_pre.json` for `Product + comments` `<= 03:45 PT`) with four calibrated interpretability blocks:
  1. `named_competitors`: Top-3 `< D` named competitors (`name`, `slug`, `shared_categories`,
     `reviews_count`, `key_user_pain_point` from G2/HN, `hands_on_comparison` from 4-step CUA).
  2. `voter_population_breakdown`: Across `93,618` complete held people (`min_group = 20` strictly
     enforced; any segment with `0 < n < 20` is suppressed), reporting `team_and_hunter_backers`,
     `competitor_voters_and_switchers`, `activity_tier_mix` (`1-9`, `10-99`, `100+`), and
     `expected_held_votes` (plus `STACK-1b` Qwen-7B expected votes when available).
  3. `sameday_head_to_head_split`: Closest same-day audience rival (`cohort_n >= 20`, `voter_overlap_pct`,
     `prefer_this_pct` vs `prefer_rival_pct`, and human-readable reason).
  4. `cua_execution_proof`: Sanitized 4-step Pool B Camoufox + Google-SSO trace summary
     (`sso_entered`, `workflow_action`, `workflow_responded`, `hands_on_works`, `exec_digest`).

Enforces `AGENTS.md` privacy & observability rules:
  - `WHY_MIN_GROUP = 20`: zero group with `1 <= n < 20` is ever reported.
  - Zero person IDs (`p_...`), zero handles (`@...`), zero emails/credentials ever emitted.
  - Every card carries `measured_predictive_value` (exact backtest & live accuracy, days, window).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
from typing import Any

import numpy as np
import pandas as pd

from simharness.bench import _day_bounds_utc, scrub
from usersim_core.sanitizer import SanitizedSurface, sanitize_text

WHY_MIN_GROUP = 20

_PERSON_ID_RE = re.compile(r"\bp_[0-9a-f]{10,}\b", re.IGNORECASE)
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_RAW_HANDLE_RE = re.compile(r"(?<!\w)@(?!someone\b)[A-Za-z0-9_]{2,}")


def _privacy_gate_count(n: int, expected_votes: float | None = None) -> dict[str, Any]:
    """Enforce `WHY_MIN_GROUP = 20` strictly: counts in `1..19` are suppressed (`n_people = None`)."""
    n_int = int(n)
    if n_int == 0:
        out: dict[str, Any] = {"n_people": 0, "suppressed_lt_min_group": False}
        if expected_votes is not None:
            out["expected_votes"] = 0.0
        return out
    if n_int < WHY_MIN_GROUP:
        return {
            "n_people": None,
            "expected_votes": None if expected_votes is not None else None,
            "suppressed_lt_min_group": True,
            "min_group_threshold": WHY_MIN_GROUP,
        }
    out = {"n_people": n_int, "suppressed_lt_min_group": False}
    if expected_votes is not None:
        out["expected_votes"] = round(float(expected_votes), 2)
    return out


def _clean_public_str(s: str, item_day: str, max_len: int = 200) -> str:
    txt = scrub(str(s or ""))
    txt = _EMAIL_RE.sub("[redacted]", txt)
    txt = _PERSON_ID_RE.sub("[redacted]", txt)
    txt = _RAW_HANDLE_RE.sub("", txt)
    txt, _ = sanitize_text(txt, item_day=item_day)
    return " ".join(txt.split())[:max_len].strip()


def assert_why_card_privacy(doc: dict[str, Any]) -> None:
    """Hard audit assertion: zero person IDs, zero emails, zero raw @handles, and `min_group >= 20`."""
    raw_json = json.dumps(doc, ensure_ascii=False)
    assert doc.get("min_group") == WHY_MIN_GROUP, "min_group must equal 20"
    assert not _PERSON_ID_RE.search(raw_json), "FATAL PRIVACY LEAK: salted person_id found in why card!"
    assert not _EMAIL_RE.search(raw_json), "FATAL PRIVACY LEAK: email found in why card!"
    assert not _RAW_HANDLE_RE.search(raw_json), "FATAL PRIVACY LEAK: @handle found in why card!"

    # Recursively check every `n_people` and `cohort_n` key
    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if k in ("n_people", "cohort_n") and v is not None:
                    iv = int(v)
                    assert iv == 0 or iv >= WHY_MIN_GROUP, f"FATAL MIN_GROUP VIOLATION: {k}={iv} < {WHY_MIN_GROUP}"
                else:
                    _walk(v)
        elif isinstance(node, list):
            for elem in node:
                _walk(elem)

    _walk(doc)


def build_day_why_card(
    day: str,
    point: str,  # "mid" (Product only, 00:05+late, zero comments) or "pre" (Product + comments <= 03:45 PT)
    day_df: pd.DataFrame,
    scores_by_id: dict[str, float],
    comp_map: dict[str, list[dict[str, Any]]],
    why_pop_by_key: dict[tuple[str, str], dict[str, Any]],
    surfaces_by_id: dict[str, SanitizedSurface],
    sso_meta: dict[str, dict[str, Any]],
    cua4_records: dict[str, dict[str, Any]],
    mm_judged: dict[str, dict[str, Any]],
    measured_predictive_value: dict[str, Any],
    held_people_total: int = 93618,
    shadow: bool = True,
) -> dict[str, Any]:
    """Construct a complete, privacy-audited `<day>_<point>.json` interpretability document."""
    assert point in ("mid", "pre"), f"Unexpected point: {point}"
    start_utc, _ = _day_bounds_utc(day, "America/Los_Angeles")
    as_of_utc = start_utc + (pd.Timedelta(minutes=5) if point == "mid" else pd.Timedelta(minutes=225))
    now_iso = dt.datetime.now(dt.timezone.utc).isoformat()

    # Deterministic rank order by predicted score descending, tie-breaking by item_id
    rows = day_df.to_dict(orient="records")
    rows = sorted(
        rows,
        key=lambda r: (-float(scores_by_id.get(str(r["item_id"]), r["structural_score"])), str(r["item_id"])),
    )

    launches_out: dict[str, dict[str, Any]] = {}
    for pred_rank, r in enumerate(rows, start=1):
        lid = str(r["item_id"])
        final_sc = float(scores_by_id.get(lid, r["structural_score"]))
        struct_sc = float(r["structural_score"])
        delta_sc = final_sc - struct_sc

        # 1. Top-3 Named Competitors (`< D`)
        comps_raw = (comp_map.get(lid) or [])[:3]
        named_comps = []
        for c in comps_raw:
            named_comps.append({
                "name": _clean_public_str(c.get("name") or "", day, 80),
                "slug": re.sub(r"[^a-z0-9-]+", "", str(c.get("slug") or "").lower())[:60],
                "shared_categories": [str(x)[:60] for x in (c.get("shared_categories") or [])[:3]],
                "reviews_count": int(c.get("reviews_count") or 0),
                "hist_endorsements_lt_d": int(c.get("hist_endorsements_lt_d") or 0),
                "key_user_pain_point": _clean_public_str(c.get("key_user_pain_point") or "", day, 150),
                "hands_on_comparison": _clean_public_str(c.get("hands_on_comparison") or "", day, 160),
            })

        # 2. Voter Population Breakdown (`93,618` held people, `min_group >= 20`)
        pinfo = why_pop_by_key.get((day, lid)) or {}
        act_n = int(pinfo.get("active_pool_n") or 0)
        if 0 < act_n < WHY_MIN_GROUP:
            act_n = 0

        tb_gate = _privacy_gate_count(
            int(pinfo.get("team_backers_lt_d_n") or 0),
            pinfo.get("team_backers_expected_votes", 0.0),
        )
        fol_gate = _privacy_gate_count(int(pinfo.get("follow_ties_lt_d_n") or 0))
        sw_gate = _privacy_gate_count(
            int(pinfo.get("competitor_switchers_lt_d_n") or 0),
            pinfo.get("competitor_switchers_expected_votes", 0.0),
        )

        t_counts = pinfo.get("tier_counts_active") or {"1-9": 0, "10-99": 0, "100+": 0}
        t_shares = pinfo.get("tier_vote_shares") or {"1-9": 0.0, "10-99": 0.0, "100+": 0.0}
        safe_tier_mix = {}
        for tk in ("1-9", "10-99", "100+"):
            tc = int(t_counts.get(tk, 0))
            if tc >= WHY_MIN_GROUP:
                safe_tier_mix[tk] = {
                    "n_people": tc,
                    "expected_vote_share": round(float(t_shares.get(tk, 0.0)), 4),
                }
            else:
                safe_tier_mix[tk] = {"n_people": None, "expected_vote_share": None, "suppressed_lt_min_group": True}

        exp_votes_val = round(float(pinfo.get("expected_held_votes") or 0.0), 2) if act_n >= WHY_MIN_GROUP else None
        qwen_ev = pinfo.get("qwen_stack1b_expected_votes")

        voter_breakdown = {
            "active_90d_pool_n": act_n if act_n >= WHY_MIN_GROUP else None,
            "expected_held_votes": exp_votes_val,
            "qwen_stack1b_expected_votes": round(float(qwen_ev), 2) if (qwen_ev is not None and act_n >= WHY_MIN_GROUP) else None,
            "team_and_hunter_backers": tb_gate,
            "follow_ties_lt_d": fol_gate,
            "competitor_voters_and_switchers": sw_gate,
            "activity_tier_mix": safe_tier_mix,
            "all_held_people_tier_baseline": pinfo.get("global_held_tier_shares") or {},
        }

        # 3. Same-Day Head-to-Head Split (`cohort_n >= 20` strictly)
        h2h_raw = pinfo.get("sameday_head_to_head")
        sameday_h2h: dict[str, Any] | None = None
        if h2h_raw and int(h2h_raw.get("cohort_n") or 0) >= WHY_MIN_GROUP:
            r_name = _clean_public_str(h2h_raw.get("rival_name") or "", day, 80)
            p_this = float(h2h_raw.get("prefer_this_pct") or 50.0)
            p_riv = float(h2h_raw.get("prefer_rival_pct") or 50.0)
            ov_pct = float(h2h_raw.get("voter_overlap_pct") or 0.0)
            c_n = int(h2h_raw["cohort_n"])
            leader_str = "this launch" if p_this >= p_riv else r_name
            sameday_h2h = {
                "rival_item_id": str(h2h_raw.get("rival_item_id") or ""),
                "rival_name": r_name,
                "cohort_n": c_n,
                "voter_overlap_pct": ov_pct,
                "prefer_this_pct": p_this,
                "prefer_rival_pct": p_riv,
                "summary": (
                    f"Contested active builder cohort (n={c_n}, {ov_pct:.1f}% audience overlap with {r_name}): "
                    f"{p_this:.1f}% favor this launch vs {p_riv:.1f}% for {r_name} ({leader_str} leads)."
                ),
            }

        # 4. Sanitized 4-Step CUA Execution Proof
        cr = cua4_records.get(lid) or {}
        mm = mm_judged.get(lid) or {}
        sm = sso_meta.get(lid) or {}
        surf = surfaces_by_id.get(lid)

        sso_ent = bool(cr.get("google_sso_entered") or sm.get("sso_entered"))
        wf_act = _clean_public_str(str(cr.get("workflow_action") or ("google_sso_check" if sso_ent else "surface_dom_inspect")), day, 60)
        wf_resp = bool(cr.get("workflow_responded") or sm.get("post_sso_workspace"))
        h_works = round(float(mm["hands_on_works"]), 3) if "hands_on_works" in mm else None
        ui_craft = round(float(mm["ui_craft_depth"]), 3) if "ui_craft_depth" in mm else None
        dig = _clean_public_str(
            str(mm.get("exec_digest") or sm.get("post_sso_clean_summary") or (surf.sanitized_text[:140] if surf else "")),
            day,
            180,
        )
        cua_proof = {
            "inspected": bool(cr or sm or (surf and surf.access_status == "clean")),
            "access_status": str(cr.get("access_status") or (surf.access_status if surf else "unverified")),
            "product_trait": str(surf.product_trait if surf else "none"),
            "sso_entered": sso_ent,
            "workflow_action": wf_act,
            "workflow_responded": wf_resp,
            "hands_on_works": h_works,
            "ui_craft_depth": ui_craft,
            "has_open_source": bool((surf and surf.has_open_source) or cr.get("has_github_link")),
            "has_free_tier": bool((surf and surf.has_free_tier) or sso_ent),
            "exec_digest": dig or "Evaluated from launch specification; external URL unverified or neutral fallback.",
        }

        # Decomposed driver points for transparent UI attribution
        driver_points = {
            "structural_baseline_arm3": round(struct_sc, 4),
            "competitor_cua_advantage": round(0.045 * float(r.get("comp_cua_advantage_z", 0.0)), 4),
            "population_93k_choice_and_switchers": round(
                0.040 * float(r.get("pop_expected_votes_choice_z", 0.0))
                + 0.025 * float(r.get("pop_comp_switcher_votes_z", 0.0)),
                4,
            ),
            "brand_and_ecosystem_authority": round(0.045 * float(r.get("brand_coldstart_authority_z", 0.0)), 4),
            "hands_on_cua_and_cohort_panel": round(
                0.035 * float(r.get("v3po_net_conviction_z", 0.0))
                + 0.030 * float(r.get("mm_hands_on_works_z", 0.0))
                + 0.035 * float(r.get("v4_finalist_po_z", 0.0)),
                4,
            ),
            "sameday_rivalry_adjustment": round(-0.025 * float(r.get("sameday_direct_rival_cannibalization_z", 0.0)), 4),
        }
        if point == "pre":
            driver_points["pre_0345_order_free_comments"] = round(
                0.045 * float(r.get("pc_early_discerning_z", 0.0))
                + 0.035 * float(r.get("pc_scout_prior_z", 0.0))
                + 0.035 * float(r.get("v2_net_conviction_z", 0.0)),
                4,
            )

        launches_out[lid] = {
            "title": _clean_public_str(str(r.get("title") or ""), day, 100),
            "predicted_rank": pred_rank,
            "final_score": round(final_sc, 5),
            "structural_score": round(struct_sc, 5),
            "net_simulation_shift": round(delta_sc, 5),
            "named_competitors": named_comps,
            "voter_population_breakdown": voter_breakdown,
            "sameday_head_to_head_split": sameday_h2h,
            "cua_execution_proof": cua_proof,
            # Legacy `results/web/why/` top-level compatibility fields
            "expected_held_votes": {
                "value": exp_votes_val,
                "n_people": act_n if act_n >= WHY_MIN_GROUP else None,
                "note": "n_ehv_v5",
            },
            "held_backers": {
                "value": tb_gate["n_people"],
                "n_people": tb_gate["n_people"],
                "note": "n_backers_lt_d",
            },
            "audience_tiers": {
                "value": {
                    "this launch": {k: float(t_shares.get(k, 0.0)) for k in ("1-9", "10-99", "100+")},
                    "all held people": pinfo.get("global_held_tier_shares") or {},
                } if act_n >= WHY_MIN_GROUP else None,
                "n_people": act_n if act_n >= WHY_MIN_GROUP else None,
                "note": "n_tiers_v5",
            },
            "forecast_drivers": {
                "rank_explanation_model": pred_rank,
                "score": round(final_sc, 4),
                "points": driver_points,
            },
        }

    doc = {
        "schema_version": "usersim_core_why_v5",
        "as_of": as_of_utc.isoformat(),
        "written_at": now_iso,
        "shadow": bool(shadow),
        "min_group": WHY_MIN_GROUP,
        "day": day,
        "point": point,
        "track": "product_only" if point == "mid" else "product_comments_order_free_le_0345pt",
        "store_reads_before": start_utc.isoformat(),
        "held_people": int(held_people_total),
        "held_people_definition": (
            "Complete people in Benchmark store (all tabs read to Product Hunt's own end) with strictly < D activity"
        ),
        "measured_predictive_value": measured_predictive_value,
        "items": {
            "named_competitors": {
                "label": "Top-3 named competitors (< D) & CUA comparison",
                "unit": "competitors",
                "note": "n_comp",
            },
            "voter_population_breakdown": {
                "label": "93,618-person discrete-choice voter & switcher breakdown (groups >= 20 only)",
                "unit": "people",
                "note": "n_pop",
            },
            "sameday_head_to_head_split": {
                "label": "Same-day audience overlap & builder preference split",
                "unit": "percent",
                "note": "n_h2h",
            },
            "cua_execution_proof": {
                "label": "4-step Camoufox + Google-SSO hands-on product verification",
                "unit": "trace",
                "note": "n_cua",
            },
        },
        "notes": {
            "n_comp": "Strictly < D causal competitors; Nov 1 Similar Products never used for pre-Nov-2 days.",
            "n_pop": "All counts strictly enforce min_group >= 20 with zero person IDs or usernames.",
            "n_h2h": "Multinomial softmax choice competition across today's active 90-day builder cohort.",
            "n_cua": (
                "Zero comments used in Product-only ('mid'); order-free <= 03:45 PT scrubbed comments used in 'pre'."
            ),
        },
        "launches": launches_out,
    }

    assert_why_card_privacy(doc)
    return doc


def emit_why_cards_batch(
    full_df: pd.DataFrame,
    days_to_emit: list[str],
    ov_po_v5: dict[tuple[str, str], float],
    ov_pc_v5: dict[tuple[str, str], float],
    comp_map: dict[str, list[dict[str, Any]]],
    why_pop_by_key: dict[tuple[str, str], dict[str, Any]],
    surfaces_by_id: dict[str, SanitizedSurface],
    sso_meta: dict[str, dict[str, Any]],
    cua4_records: dict[str, dict[str, Any]],
    mm_judged: dict[str, dict[str, Any]],
    po_metrics_summary: dict[str, Any],
    pc_metrics_summary: dict[str, Any],
    out_dir: str,
    gcs_dest_prefix: str = "gs://usersim-trace-store-347838016394/usersim_core_v5/why",
    held_people_total: int = 93618,
) -> dict[str, Any]:
    """Write `<day>_mid.json` and `<day>_pre.json` cards, validate privacy on every file, and sync to GCS."""
    os.makedirs(out_dir, exist_ok=True)
    written_files: list[str] = []

    for d in sorted(set(days_to_emit)):
        sub = full_df[full_df["day"] == d].copy()
        if sub.empty:
            continue
        po_scores = {str(r.item_id): float(ov_po_v5.get((d, str(r.item_id)), r.structural_score)) for r in sub.itertuples(index=False)}
        pc_scores = {str(r.item_id): float(ov_pc_v5.get((d, str(r.item_id)), r.structural_score)) for r in sub.itertuples(index=False)}

        mid_doc = build_day_why_card(
            day=d,
            point="mid",
            day_df=sub,
            scores_by_id=po_scores,
            comp_map=comp_map,
            why_pop_by_key=why_pop_by_key,
            surfaces_by_id=surfaces_by_id,
            sso_meta=sso_meta,
            cua4_records=cua4_records,
            mm_judged=mm_judged,
            measured_predictive_value=po_metrics_summary,
            held_people_total=held_people_total,
            shadow=True,
        )
        pre_doc = build_day_why_card(
            day=d,
            point="pre",
            day_df=sub,
            scores_by_id=pc_scores,
            comp_map=comp_map,
            why_pop_by_key=why_pop_by_key,
            surfaces_by_id=surfaces_by_id,
            sso_meta=sso_meta,
            cua4_records=cua4_records,
            mm_judged=mm_judged,
            measured_predictive_value=pc_metrics_summary,
            held_people_total=held_people_total,
            shadow=True,
        )

        p_mid = os.path.join(out_dir, f"{d}_mid.json")
        p_pre = os.path.join(out_dir, f"{d}_pre.json")
        with open(p_mid, "w") as f:
            json.dump(mid_doc, f, indent=2)
        with open(p_pre, "w") as f:
            json.dump(pre_doc, f, indent=2)
        written_files.extend([p_mid, p_pre])

    if gcs_dest_prefix and written_files:
        subprocess.run(
            ["gcloud", "storage", "cp", "-q", *written_files, gcs_dest_prefix.rstrip("/") + "/"],
            check=True,
        )

    return {
        "days_emitted": len(set(days_to_emit)),
        "files_written": len(written_files),
        "min_group_enforced": WHY_MIN_GROUP,
        "privacy_assertions_passed": True,
        "gcs_destination": gcs_dest_prefix,
    }
