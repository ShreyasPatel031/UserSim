"""Score phase-B predictions: ratings, paired deltas, evidence baselines, qualitative matches.

Evaluator-only. Reads pack/evaluator_only. Never feeds anything back into
predict.py or run_exec.py.

Qualitative pipeline (automated, provisional; no human audit in this run):
  1. extract: up to three explicit benefit and three friction claims per hidden
     review, with exact source spans, plus a task-relevance flag decided from the
     task goal alone. Run before, and without, any prediction.
  2. match: each anonymous prediction (random id, no condition label) is matched
     one-to-one to the reference claims: 2 specific, 1 broad/partial, 0 none;
     a prediction the review explicitly contradicts is a disagreement; anything
     else unmentioned is unconfirmed.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import random
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import llm

HERE = Path(__file__).resolve().parent
PACK = HERE / "pack"
RES = HERE / "results"
TARGETS = ["ease_of_use_rating", "functionality_rating", "overall_rating", "value_for_money_rating"]
PRIMARY = ["ease_of_use_rating", "functionality_rating"]
CONTRASTS = [("B1", "B0"), ("B3", "B1"), ("B5", "B1"), ("B5", "B3"), ("B4", "B2"), ("B5", "B4")]
EXEC_CELLS = {"B2": ("base", "generic"), "B3": ("full", "generic"), "B4": ("base", "usersim"), "B5": ("full", "usersim")}
BLOCKED = {"environment_failure", "blocked_login_wall", "blocked_captcha", "blocked_site_error", "blocked_paid_plan"}


def jl(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def mae_rps(ps: list[float], y: int) -> tuple[float, float]:
    exp = sum((i + 1) * v for i, v in enumerate(ps))
    rps = sum((sum(ps[:k]) - int(y <= k)) ** 2 for k in range(1, 5)) / 4
    return abs(exp - y), rps


def evidence_baselines(core: list[str], gold: dict) -> list[dict]:
    """Empirical rating distributions of the C and T evidence rows used in each case's packet."""
    manifest = json.loads((HERE / "packets" / "manifest.json").read_text())
    rows = {}
    for prod in ["Asana", "Trello", "ClickUp"]:
        for r in jl(PACK / "evidence" / "reviews" / f"{prod}.jsonl"):
            rows[r["evidence_id"]] = r
    out = []
    for cid in core:
        for pack in ["C", "T"]:
            ids = manifest["cases"][cid]["packets"][pack]["evidence_ids"]
            for t in TARGETS:
                y = gold[cid]["ratings"][t]
                vals = [int(float(rows[i][t])) for i in ids if rows[i].get(t) not in (None, "")]
                if y is None or not vals:
                    continue
                ps = [(vals.count(k) + 0.5) / (len(vals) + 2.5) for k in range(1, 6)]
                m, r = mae_rps(ps, int(y))
                out.append({"baseline": f"evidence_{pack}_distribution", "case_id": cid, "target": t,
                            "mae": m, "rps": r, "n_evidence": len(vals)})
    return out


EXTRACT_SYS = """You extract explicit claims from one software review for an evaluation codebook.
Benefits: specific things the reviewer says work well for them. Frictions: specific problems,
missing capabilities or difficulties they report. Up to three of each, most specific first.
Each claim must be explicit in the text and carry an exact quoted span copied from the review.
Do not add generic praise or complaints that are not in the text. For each claim also say whether
it is relevant to the supplied task goal (judge from the goal only). JSON only."""


async def extract(review: dict, goal: str) -> dict:
    text = "\n".join(f"{k}: {review.get(k) or ''}" for k in
                     ["pros", "cons", "general_comments", "reasons_for_choosing", "reasons_for_switching"])
    prompt = (f"Product: {review['product_name']}\nTask goal: {goal}\n\nReview:\n{text}\n\n"
              'JSON: {"benefits": [{"id": "b1", "aspect": "..", "claim": "..", "span": "exact quote", "task_relevant": true}], '
              '"frictions": [{"id": "f1", "aspect": "..", "claim": "..", "span": "exact quote", "task_relevant": false}]}')
    res = await llm.call(prompt, system=EXTRACT_SYS)
    j = res["json"] or {}
    for kind in ["benefits", "frictions"]:
        for c in j.get(kind) or []:
            c["span_verified"] = bool(c.get("span")) and c["span"].lower() in text.lower()
    return {"labels": j, "usage": res["usage"], "model": res["model"], "model_version": res["model_version"]}


MATCH_SYS = """You compare predicted review claims against reference claims extracted from a real review.
Match one-to-one within each type (benefit to benefit, friction to friction).
Score 2: same specific aspect/object, direction and condition. Score 1: broadly the same aspect but
less specific or partly different. Score 0: no reference claim matches. A generic prediction such as
"confusing interface" must not score 2 against a specific missing-task problem.
Disagreement: the review text explicitly states the opposite of the prediction.
Otherwise an unmatched prediction is unconfirmed (not proven false). JSON only."""


async def match(pred: dict, ref: dict, review_text: str) -> dict:
    prompt = (
        f"Review text (for checking explicit contradictions):\n{review_text}\n\n"
        f"Reference claims:\n{json.dumps(ref, ensure_ascii=False)}\n\n"
        f"Predicted claims:\n{json.dumps({'benefits': pred['benefits'], 'frictions': pred['frictions']}, ensure_ascii=False)}\n\n"
        'JSON: {"benefits": [{"pred_index": 0, "ref_id": "b1 or null", "score": 2, "disagreement": false}], '
        '"frictions": [{"pred_index": 0, "ref_id": "f1 or null", "score": 0, "disagreement": false}]}'
    )
    res = await llm.call(prompt, system=MATCH_SYS)
    return {"matches": res["json"] or {}, "usage": res["usage"]}


def qual_metrics(match_j: dict, ref: dict, n_pred: dict, task_only: bool) -> dict:
    out = {}
    for kind in ["benefits", "frictions"]:
        refs = [c for c in ref.get(kind) or [] if not task_only or c.get("task_relevant")]
        ref_ids = {c["id"] for c in refs}
        best: dict[str, int] = {}
        dis = 0
        unconf = 0
        used = set()
        for m in match_j.get(kind) or []:
            rid = m.get("ref_id")
            if m.get("disagreement"):
                dis += 1
                continue
            if rid in ref_ids and rid not in used and int(m.get("score") or 0) > 0:
                used.add(rid)
                best[rid] = int(m["score"])
            elif not task_only:
                unconf += 1
        n = len(refs)
        out[kind] = {
            "n_ref": n,
            "n_pred": n_pred[kind],
            "strict_recall": (sum(1 for v in best.values() if v == 2) / n) if n else None,
            "partial_recall": (sum(1 for v in best.values() if v >= 1) / n) if n else None,
            "disagreements": dis,
            "unconfirmed": unconf if not task_only else None,
        }
    return out


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-qual", action="store_true")
    a = ap.parse_args()
    preds = jl(RES / "predictions.jsonl")
    gold = {g["case_id"]: g for g in jl(PACK / "evaluator_only" / "outcomes.jsonl")}
    tasks = {t["case_id"]: t for t in jl(PACK / "inputs" / "e2e_tasks.jsonl")}
    core = [c for c, t in tasks.items() if t["core_smoke_subset"]]
    raw = {r["review_id"]: r for r in jl(PACK / "evaluator_only" / "raw_test_reviews.jsonl")}

    # 1. The pack's own rating scorer.
    subprocess.run([sys.executable, "-I", str(PACK / "scripts" / "score_ratings.py"), str(RES / "predictions.jsonl"),
                    "--output", str(RES / "rating_metrics.csv")], check=True)

    # Execution status per prediction.
    status = {}
    for cell, (ctx, eng) in EXEC_CELLS.items():
        for cid in core:
            p = RES / "execution" / f"{cid}__{ctx}__{eng}.json"
            if p.exists():
                status[(cid, cell)] = json.loads(p.read_text())["status"]

    # 2. Case-level errors.
    case_err: dict[tuple, dict] = {}
    by_cell = defaultdict(dict)
    for r in preds:
        by_cell[r["condition"]][r["case_id"]] = r
        for t in TARGETS:
            y = gold[r["case_id"]]["ratings"][t]
            item = (r.get("ratings") or {}).get(t)
            if y is None or not item:
                continue
            m, rp = mae_rps(item["probabilities"], int(y))
            case_err[(r["condition"], r["case_id"], t)] = {"mae": m, "rps": rp}

    # 3. Qualitative.
    qual: dict[tuple, dict] = {}
    if not a.skip_qual:
        ref_path = RES / "qualitative_reference_labels.json"
        if ref_path.exists():
            refs = json.loads(ref_path.read_text())
        else:
            ex = await asyncio.gather(*(extract(raw[gold[c]["review_id"]], tasks[c]["goal"]) for c in core))
            refs = {c: e for c, e in zip(core, ex)}
            for e in refs.values():
                e["audit_status"] = "automated_provisional_no_human_audit"
            ref_path.write_text(json.dumps(refs, indent=1, ensure_ascii=False))
        mpath = RES / "qualitative_matches.json"
        matches = json.loads(mpath.read_text()) if mpath.exists() else {}
        todo = [(c, r) for c, r in ((r["case_id"], r) for r in preds)
                if c in core and f"{c}__{r['condition']}" not in matches]
        rng = random.Random(7)
        rng.shuffle(todo)  # judge order carries no condition information
        rev_text = {c: "\n".join(f"{k}: {raw[gold[c]['review_id']].get(k) or ''}" for k in
                                 ["pros", "cons", "general_comments", "reasons_for_choosing", "reasons_for_switching"])
                    for c in core}
        res = await asyncio.gather(*(match(r, refs[c]["labels"], rev_text[c]) for c, r in todo))
        for (c, r), m in zip(todo, res):
            matches[f"{c}__{r['condition']}"] = m
        mpath.write_text(json.dumps(matches, indent=1, ensure_ascii=False))
        for r in preds:
            c = r["case_id"]
            if c not in core:
                continue
            m = matches[f"{c}__{r['condition']}"]["matches"]
            n_pred = {"benefits": len(r["benefits"]), "frictions": len(r["frictions"])}
            qual[(r["condition"], c)] = {
                "all": qual_metrics(m, refs[c]["labels"], n_pred, False),
                "task": qual_metrics(m, refs[c]["labels"], n_pred, True),
            }

    def qscore(cell, cid, scope="all"):
        q = qual.get((cell, cid))
        if not q:
            return None
        vals = [q[scope][k]["partial_recall"] for k in ["benefits", "frictions"] if q[scope][k]["partial_recall"] is not None]
        return sum(vals) / len(vals) if vals else None

    def strict(cell, cid):
        q = qual.get((cell, cid))
        if not q:
            return None
        vals = [q["all"][k]["strict_recall"] for k in ["benefits", "frictions"] if q["all"][k]["strict_recall"] is not None]
        return sum(vals) / len(vals) if vals else None

    # 4. Paired deltas (negative error delta = first cell better).
    rows = []
    for x, y in CONTRASTS:
        for analysis in ["intent_to_run", "matched_successful_runs"]:
            for cid in core:
                if cid not in by_cell[x] or cid not in by_cell[y]:
                    continue
                sx, sy = status.get((cid, x)), status.get((cid, y))
                if analysis == "matched_successful_runs" and (sx in BLOCKED or sy in BLOCKED):
                    continue
                row = {"contrast": f"{x}-{y}", "analysis": analysis, "case_id": cid,
                       "product": gold[cid]["product"], "status_x": sx or "", "status_y": sy or ""}
                for t in TARGETS:
                    ex, ey = case_err.get((x, cid, t)), case_err.get((y, cid, t))
                    row[f"{t}_abs_err_delta"] = round(ex["mae"] - ey["mae"], 4) if ex and ey else ""
                    row[f"{t}_rps_delta"] = round(ex["rps"] - ey["rps"], 4) if ex and ey else ""
                qx, qy = qscore(x, cid), qscore(y, cid)
                row["qual_partial_recall_delta"] = round(qx - qy, 4) if qx is not None and qy is not None else ""
                sxq, syq = strict(x, cid), strict(y, cid)
                row["qual_strict_recall_delta"] = round(sxq - syq, 4) if sxq is not None and syq is not None else ""
                rows.append(row)
    # Denominators per contrast/analysis.
    den = defaultdict(int)
    for r in rows:
        den[(r["contrast"], r["analysis"])] += 1
    for r in rows:
        r["complete_case_n"] = den[(r["contrast"], r["analysis"])]
    with (RES / "paired_deltas.csv").open("w") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    # 5. Qualitative metrics table.
    qrows = []
    for (cell, cid), q in sorted(qual.items()):
        for scope in ["all", "task"]:
            for kind in ["benefits", "frictions"]:
                qrows.append({"condition": cell, "case_id": cid, "scope": scope, "type": kind, **q[scope][kind],
                              "audit_status": "automated_provisional"})
    if qrows:
        with (RES / "qualitative_metrics.csv").open("w") as f:
            w = csv.DictWriter(f, fieldnames=list(qrows[0]))
            w.writeheader()
            w.writerows(qrows)

    # 6. Evidence baselines.
    base = evidence_baselines(core, gold)
    with (RES / "evidence_baselines.csv").open("w") as f:
        w = csv.DictWriter(f, fieldnames=list(base[0]))
        w.writeheader()
        w.writerows(base)

    # 7. Summary per cell.
    summary = {}
    for cell in ["B0", "B1", "B2", "B3", "B4", "B5"]:
        cids = [c for c in core if c in by_cell[cell]]
        s = {"n": len(cids)}
        for t in TARGETS:
            errs = [case_err[(cell, c, t)] for c in cids if (cell, c, t) in case_err]
            s[f"{t}_mae"] = round(sum(e["mae"] for e in errs) / len(errs), 3) if errs else None
            s[f"{t}_rps"] = round(sum(e["rps"] for e in errs) / len(errs), 3) if errs else None
            s[f"{t}_n"] = len(errs)
        qs = [qscore(cell, c) for c in cids if qscore(cell, c) is not None]
        ss = [strict(cell, c) for c in cids if strict(cell, c) is not None]
        qt = [qscore(cell, c, "task") for c in cids if qscore(cell, c, "task") is not None]
        s["qual_partial_recall"] = round(sum(qs) / len(qs), 3) if qs else None
        s["qual_strict_recall"] = round(sum(ss) / len(ss), 3) if ss else None
        s["qual_task_partial_recall"] = round(sum(qt) / len(qt), 3) if qt else None
        dis = [sum(qual[(cell, c)]["all"][k]["disagreements"] for k in ["benefits", "frictions"]) for c in cids if (cell, c) in qual]
        unc = [sum(qual[(cell, c)]["all"][k]["unconfirmed"] for k in ["benefits", "frictions"]) for c in cids if (cell, c) in qual]
        npred = [len(by_cell[cell][c]["benefits"]) + len(by_cell[cell][c]["frictions"]) for c in cids]
        s["disagreement_rate"] = round(sum(dis) / sum(npred), 3) if dis and sum(npred) else None
        s["unconfirmed_rate"] = round(sum(unc) / sum(npred), 3) if unc and sum(npred) else None
        if cell in EXEC_CELLS:
            st = [status.get((c, cell)) for c in core]
            s["blocked_or_failed_env"] = sum(1 for x in st if x in BLOCKED)
            s["statuses"] = st
        s["forecast_cost_usd"] = round(sum(by_cell[cell][c]["usage"]["cost_usd"] for c in cids), 4)
        summary[cell] = s
    for b in ["evidence_C_distribution", "evidence_T_distribution"]:
        s = {}
        for t in TARGETS:
            e = [r for r in base if r["baseline"] == b and r["target"] == t]
            s[f"{t}_mae"] = round(sum(r["mae"] for r in e) / len(e), 3) if e else None
            s[f"{t}_rps"] = round(sum(r["rps"] for r in e) / len(e), 3) if e else None
            s[f"{t}_n"] = len(e)
        summary[b] = s
    (RES / "summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    asyncio.run(main())
