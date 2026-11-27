"""Cross-Domain Generalizability Test 2: Real User Product Comments Ceiling (`usersim_core/comment_ceiling_v7.py`).

Evaluates whether `UniversalUserSimulatorV7` (run strictly BEFORE any real comments exist, in `Product only`
zero-comment mode) predicts what real human users actually praise, question, and complain about after launch,
measured on a "fraction of split-half human ceiling" scale (`CEILING-2` equal-list-size protocol):
  - Evaluates `Nov 15 - Nov 24` Product Hunt launches that received `>= 10` real non-maker user comments
    (pulled from full-day `raw/ph_at_launch/<day>/live/comments_ts.jsonl` + `api_comments`).
  - Splits real non-maker commenters into random halves A and B (`R = 8` resamples per launch):
      * Consensus Ground-Truth Themes & Complaint Themes extracted from Half B.
      * Scored at strictly EQUAL candidate count `K = 6` statements per launch across 3 arms:
          1. `human_split_half_ceiling`: `K = 6` real non-maker comments from Half A
          2. `plain_pitch_prompt`: `K = 6` reactions/worries from a plain launch-spec prompt (no CUA, no archetypes)
          3. `universal_sim_v7_product_only`: `K = 6` pre-launch praises + specific archetype complaints from
             `UniversalUserSimulatorV7` (`u7_predicted_comments.json`, zero real comments seen!)
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import subprocess
import time
from typing import Any

import gcsfs
import numpy as np

from simharness.bench import scrub
from simharness.models.llm import Budget, JsonlCache, VertexGemini
from usersim_core.late_and_comments import BOILERPLATE_PRAISE_RE, scrub_comment_text
from usersim_core.run_proof import load_raw_sources

BUCKET = "usersim-bakeoff-347838016394/usersim_sim"

EXTRACT_THEMES_PROMPT = """Extract the consensus points raised by real users in these product comments:
1. `all_themes`: up to 6 distinct substantive themes (praises, workflow questions, comparisons, or critiques).
2. `complaint_themes`: up to 4 distinct concrete complaints, worries, bugs, pricing pushbacks, or limitations raised.

COMMENTS:
{comments_block}

Return JSON ONLY:
{{"all_themes": ["..."], "complaint_themes": ["..."]}}"""

PLAIN_BASELINE_PROMPT = """Given this product's name, tagline, and description, write 6 concise 1-sentence user reactions (2 praises and 4 potential user concerns/questions):
Name: {title}
Tagline: {summary}
Description: {desc}

Return JSON ONLY:
{{"statements": ["...", "...", "...", "...", "...", "..."]}}"""

JUDGE_COVERAGE_PROMPT = """You are an objective evaluator comparing candidate statements B against ground-truth user themes A.
Mark `a_covered[i] = true` ONLY if at least one statement in B raises the SAME specific point/concern as `A[i]` (vague generic overlap does NOT count).
Mark `b_supported[j] = true` if candidate statement `B[j]` matches at least one real point in A.

GROUND-TRUTH THEMES A:
{themes_a}

CANDIDATE STATEMENTS B (count = {n_b}):
{cands_b}

Return JSON ONLY:
{{"a_covered": [true, ...], "b_supported": [true, ...]}}"""


def _parse_json(txt: str) -> dict[str, Any]:
    try:
        return json.loads(txt)
    except Exception:
        import re
        m = re.search(r"\{.*\}", txt or "", re.S)
        return json.loads(m.group(0)) if m else {}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="/var/tmp/usersim_core_work/data")
    ap.add_argument("--work-dir", default="/var/tmp/usersim_core_work/comment_ceiling_v7")
    ap.add_argument("--u7-comments-json", default="/var/tmp/usersim_core_work/u7_predicted_comments.json")
    ap.add_argument("--out-json", default="/var/tmp/usersim_core_work/usersim_core_comments_1_results.json")
    ap.add_argument("--gcs-prefix", default="gs://usersim-trace-store-347838016394/usersim_core_v7")
    ap.add_argument("--resamples", type=int, default=6)
    ap.add_argument("--max-launches", type=int, default=24)
    ap.add_argument("--budget-usd", type=float, default=3.5)
    args = ap.parse_args()

    t0 = time.time()
    os.makedirs(args.work_dir, exist_ok=True)
    fs = gcsfs.GCSFileSystem()
    bench = load_raw_sources(args.data_dir)[0]
    idx_by_id = dict(zip(bench.items["item_id"].astype(str), bench.items["item_idx"].astype(int)))

    u7_preds: dict[str, dict[str, Any]] = json.load(open(args.u7_comments_json))

    # Collect full-day non-maker substantive comments (> 25 chars) on Nov 15 - Nov 24 for launches in u7_preds!
    eval_days = [f"2026-11-{dd:02d}" for dd in range(15, 25)]
    qualified_launches: list[dict[str, Any]] = []

    for d in eval_days:
        cts = f"{BUCKET}/raw/ph_at_launch/{d}/live/comments_ts.jsonl"
        if not fs.exists(cts):
            continue
        by_post_user: dict[str, dict[str, list[str]]] = {}
        with fs.open(cts, "rt") as f:
            for line in f:
                if not line.strip():
                    continue
                r = json.loads(line)
                if r.get("is_maker") or r.get("is_hunter"):
                    continue
                pid = str(r.get("launch_id") or r.get("post_id") or "")
                uid = str(r.get("commenter_user_id") or r.get("user_id") or "")
                txt = scrub_comment_text(str(r.get("body") or ""))
                if len(txt) <= 28 or BOILERPLATE_PRAISE_RE.match(txt) or not pid or not uid:
                    continue
                by_post_user.setdefault(pid, {}).setdefault(uid, []).append(txt[:240])

        for pid, umap in sorted(by_post_user.items()):
            key = f"{d}|{pid}"
            if len(umap) >= 10 and key in u7_preds:
                u7_entry = u7_preds[key]
                u7_list = list(dict.fromkeys((u7_entry.get("predicted_praises") or []) + (u7_entry.get("predicted_complaints") or [])))
                if len(u7_list) >= 4:
                    iidx = idx_by_id.get(pid)
                    it = bench.item(iidx) if iidx is not None else None
                    qualified_launches.append({
                        "day": d,
                        "item_id": pid,
                        "title": scrub(it.title if it else pid),
                        "summary": scrub(it.summary if it else ""),
                        "desc": scrub((it.description if it else "")[:400]),
                        "users_comments": list(umap.values()),
                        "u7_statements": u7_list[:6],
                    })

    qualified_launches = qualified_launches[: args.max_launches]
    budget = Budget(cap_usd=args.budget_usd)
    cache = JsonlCache(f"{args.work_dir}/cache_ceiling_v7")
    flash = VertexGemini(model="gemini-2.5-flash", project="project-amer-scs-sandbox", region="global", temperature=0.0, budget=budget, max_out=1200)

    def _call_cached(ckey: tuple, prompt: str) -> dict[str, Any]:
        if ckey in cache:
            return cache[ckey]
        res = _parse_json(flash.call(prompt))
        if res:
            cache[ckey] = res
        return res

    K_EQUAL = 6

    def _score_launch(L: dict[str, Any]) -> dict[str, Any]:
        lid = L["item_id"]
        d = L["day"]
        plain_j = _call_cached(
            ("plain_v7", d, lid),
            PLAIN_BASELINE_PROMPT.format(title=L["title"], summary=L["summary"], desc=L["desc"]),
        )
        plain_stmts = [str(x)[:220] for x in (plain_j.get("statements") or [])][:K_EQUAL]
        u7_stmts = L["u7_statements"][:K_EQUAL]
        while len(u7_stmts) < K_EQUAL and plain_stmts:
            u7_stmts.append(u7_stmts[-1])

        rng = np.random.default_rng(abs(hash(f"{d}:{lid}")) % (2**31))
        u_groups = L["users_comments"]
        n_u = len(u_groups)

        arm_metrics: dict[str, dict[str, list[float]]] = {
            a: {"recall": [], "precision": [], "complaint_recall": []}
            for a in ("human_ceiling", "plain_prompt", "univ_sim_v7")
        }

        for r_idx in range(args.resamples):
            perm = rng.permutation(n_u)
            half_a = [u_groups[i][0] for i in perm[: n_u // 2]]
            half_b = [c for i in perm[n_u // 2 :] for c in u_groups[i][:2]]

            # Equal K = 6 real comments from Half A!
            human_cands = half_a[:K_EQUAL]
            b_block = "\n".join(f"- {c}" for c in half_b[:24])
            th_j = _call_cached(("themes_v7", d, lid, r_idx), EXTRACT_THEMES_PROMPT.format(comments_block=b_block))
            all_th = [str(x) for x in (th_j.get("all_themes") or []) if x][:6]
            comp_th = [str(x) for x in (th_j.get("complaint_themes") or []) if x][:4]
            if not all_th:
                continue

            for arm_name, cands in (
                ("human_ceiling", human_cands),
                ("plain_prompt", plain_stmts),
                ("univ_sim_v7", u7_stmts),
            ):
                if not cands:
                    continue
                jg = _call_cached(
                    ("jdg_all_v7", d, lid, r_idx, arm_name),
                    JUDGE_COVERAGE_PROMPT.format(
                        themes_a="\n".join(f"{i+1}. {t}" for i, t in enumerate(all_th)),
                        n_b=len(cands),
                        cands_b="\n".join(f"{i+1}. {t}" for i, t in enumerate(cands)),
                    ),
                )
                ac = [bool(v) for v in (jg.get("a_covered") or [])[: len(all_th)]]
                bs = [bool(v) for v in (jg.get("b_supported") or [])[: len(cands)]]
                if len(ac) == len(all_th) and bs:
                    arm_metrics[arm_name]["recall"].append(float(np.mean(ac)))
                    arm_metrics[arm_name]["precision"].append(float(np.mean(bs)))

                if comp_th:
                    jc = _call_cached(
                        ("jdg_cmp_v7", d, lid, r_idx, arm_name),
                        JUDGE_COVERAGE_PROMPT.format(
                            themes_a="\n".join(f"{i+1}. {t}" for i, t in enumerate(comp_th)),
                            n_b=len(cands),
                            cands_b="\n".join(f"{i+1}. {t}" for i, t in enumerate(cands)),
                        ),
                    )
                    cc = [bool(v) for v in (jc.get("a_covered") or [])[: len(comp_th)]]
                    if len(cc) == len(comp_th):
                        arm_metrics[arm_name]["complaint_recall"].append(float(np.mean(cc)))

        return {
            "day": d,
            "item_id": lid,
            "title": L["title"],
            "means": {
                a: {m: float(np.mean(vs)) if vs else np.nan for m, vs in md.items()}
                for a, md in arm_metrics.items()
            },
        }

    per_launch = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = [ex.submit(_score_launch, L) for L in qualified_launches]
        for fut in as_completed(futs):
            per_launch.append(fut.result())
    cache.roll()

    def _boot_ci(arr: list[float]) -> dict[str, Any]:
        clean = np.array([x for x in arr if np.isfinite(x)], dtype=np.float64) * 100.0
        if len(clean) < 2:
            return {"mean_pct": round(float(clean.mean()), 2) if len(clean) else None, "ci95": [None, None], "n": len(clean)}
        rng = np.random.default_rng(42)
        b = clean[rng.integers(0, len(clean), size=(4000, len(clean)))].mean(axis=1)
        return {
            "mean_pct": round(float(clean.mean()), 2),
            "ci95": [round(float(np.percentile(b, 2.5)), 2), round(float(np.percentile(b, 97.5)), 2)],
            "n": int(len(clean)),
        }

    summary_arms = {}
    for arm in ("human_ceiling", "plain_prompt", "univ_sim_v7"):
        summary_arms[arm] = {
            m: _boot_ci([x["means"][arm][m] for x in per_launch])
            for m in ("recall", "precision", "complaint_recall")
        }

    ceil_rec = summary_arms["human_ceiling"]["recall"]["mean_pct"] or 1.0
    ceil_prec = summary_arms["human_ceiling"]["precision"]["mean_pct"] or 1.0
    ceil_cmp = summary_arms["human_ceiling"]["complaint_recall"]["mean_pct"] or 1.0

    out = {
        "experiment_id": "USERSIM-CORE-COMMENTS-1",
        "protocol": f"Equal-size (K={K_EQUAL}) split-half real commenter ceiling ({args.resamples} resamples/launch, Nov 15-24)",
        "n_launches_scored": len(per_launch),
        "vertex_llm_cost_usd": round(budget.spent, 4),
        "elapsed_sec": round(time.time() - t0, 1),
        "arms": summary_arms,
        "fraction_of_human_ceiling": {
            "plain_prompt": {
                "theme_recall_ratio": round((summary_arms["plain_prompt"]["recall"]["mean_pct"] or 0.0) / ceil_rec, 3),
                "precision_ratio": round((summary_arms["plain_prompt"]["precision"]["mean_pct"] or 0.0) / ceil_prec, 3),
                "complaint_recall_ratio": round((summary_arms["plain_prompt"]["complaint_recall"]["mean_pct"] or 0.0) / ceil_cmp, 3),
            },
            "universal_sim_v7_product_only": {
                "theme_recall_ratio": round((summary_arms["univ_sim_v7"]["recall"]["mean_pct"] or 0.0) / ceil_rec, 3),
                "precision_ratio": round((summary_arms["univ_sim_v7"]["precision"]["mean_pct"] or 0.0) / ceil_prec, 3),
                "complaint_recall_ratio": round((summary_arms["univ_sim_v7"]["complaint_recall"]["mean_pct"] or 0.0) / ceil_cmp, 3),
            },
        },
    }
    with open(args.out_json, "w") as f:
        json.dump(out, f, indent=2)
    if args.gcs_prefix:
        subprocess.run(["gcloud", "storage", "cp", "-q", args.out_json, f"{args.gcs_prefix.rstrip('/')}/usersim_core_comments_1_results.json"], check=True)
    print(json.dumps(out, indent=2), flush=True)


if __name__ == "__main__":
    main()
