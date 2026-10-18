"""Expand to 5 products x 5 reviewer cases, same recipe as the pack.

Products: Asana and ClickUp (their 4 pack cases + 1 more pack test review each) and three new self-serve
products (Notion, Smartsheet, Pipedrive: 5 new reviews each, 2 with overall 1-3 and 3 with 4-5, chosen by
SHA256(seed|review_id) among reviews with a job title, ease and functionality ratings and enough text).
Excludes every pack test, development and evidence id. A model drafts one neutral task per review from the
reported activity only; the evaluator audits them before any run (task_audit_v2.md).

Writes v2/inputs/cases.jsonl, v2/inputs/e2e_tasks.jsonl, v2/evidence/<product>.jsonl (10 evidence reviews per
product, also never test ids), and v2/evaluator_only/outcomes.jsonl. Review prose stays in gitignored files.
"""

from __future__ import annotations

import asyncio
import csv
import hashlib
import json
from pathlib import Path

import llm

HERE = Path(__file__).resolve().parent
PACK = HERE / "pack"
V2 = HERE / "v2"
SEED = "usersim-v2-5x5"
NEW = {"Notion": "https://www.notion.so/", "Smartsheet": "https://www.smartsheet.com/", "Pipedrive": "https://www.pipedrive.com/"}
URLS = {"Asana": "https://asana.com/", "ClickUp": "https://clickup.com/", **NEW}
TEXT = ["pros", "cons", "general_comments", "reasons_for_choosing", "reasons_for_switching"]
PROFILE = ["reviewer_job_title", "reviewer_industry", "reviewer_company_size", "reviewer_time_used_product"]
RATINGS = ["overall_rating", "ease_of_use_rating", "functionality_rating", "value_for_money_rating",
           "customer_support_rating", "recommendation_score"]


def h(rid: str) -> str:
    return hashlib.sha256(f"{SEED}|{rid}".encode()).hexdigest()


def num(v: str):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


TASK_SYS = """You turn one software review into a neutral, executable test task for a fresh free account.
Use only the ACTIVITY the reviewer reports doing (what they used the product for), never their opinions,
complaints, praise, workarounds, or any symptom. The task must be doable in a few minutes on a brand-new
free account with synthetic data named Demo Alpha, Demo Beta, Demo Gamma, with no invites to real people,
no purchases and no external messages. If the review names no concrete activity, return usable=false.
Reply with JSON only."""

TASK_FMT = """Product: {product}
Review:
{text}

JSON: {{"usable": true, "goal": "short neutral goal in the user's words",
 "fixture": "what to create or do, using only Demo Alpha/Beta/Gamma",
 "success_criteria": ["observable check 1", "observable check 2"],
 "activity_source_field": "pros|cons|general_comments|reasons_for_choosing|reasons_for_switching"}}"""


async def draft(product: str, review: dict) -> dict:
    text = "\n".join(f"{k}: {review.get(k) or ''}" for k in TEXT)
    res = await llm.call(TASK_FMT.format(product=product, text=text), system=TASK_SYS)
    return res["json"] or {"usable": False}


async def main() -> None:
    split = json.loads((PACK / "config/splits.json").read_text())
    used = set(split["test_review_ids"]) | set(split["development_review_ids"]) | {
        x for v in split["evidence_review_ids_by_product"].values() for x in v} | set(split.get("global_excluded_ids") or [])
    rows = list(csv.DictReader((PACK / "local_source/capterra_software_reviews.csv").open()))
    by_id = {r["review_id"]: r for r in rows}

    def eligible(r: dict) -> bool:
        return (r["review_id"] not in used and r["reviewer_job_title"].strip()
                and num(r["ease_of_use_rating"]) and num(r["functionality_rating"]) and num(r["overall_rating"])
                and len(" ".join(r[k] for k in TEXT)) >= 200)

    picks: dict[str, list[dict]] = {}
    for prod in NEW:
        pool = sorted((r for r in rows if r["product_name"] == prod and eligible(r)), key=lambda r: h(r["review_id"]))
        low = [r for r in pool if num(r["overall_rating"]) <= 3]
        high = [r for r in pool if num(r["overall_rating"]) >= 4]
        picks[prod] = low[:6] + high[:9]  # spares: drafts that come back unusable are skipped in order
    # Asana / ClickUp: the pack's 4 task cases + the next pack test review (by the same hash) without a task.
    outcomes = {o["case_id"]: o for o in map(json.loads, (PACK / "evaluator_only/outcomes.jsonl").open())}
    pack_cases = {c["case_id"]: c for c in map(json.loads, (PACK / "inputs/cases.jsonl").open())}
    pack_tasks = [json.loads(l) for l in (PACK / "inputs/e2e_tasks.jsonl").open()]
    tasked = {t["case_id"] for t in pack_tasks}
    extra = {}
    for prod in ["Asana", "ClickUp"]:
        spare = sorted((o for o in outcomes.values() if o["product"] == prod and o["case_id"] not in tasked),
                       key=lambda o: h(o["review_id"]))
        extra[prod] = spare

    V2.joinpath("inputs").mkdir(parents=True, exist_ok=True)
    V2.joinpath("evaluator_only").mkdir(parents=True, exist_ok=True)
    V2.joinpath("evidence").mkdir(parents=True, exist_ok=True)
    cases, tasks, outs = [], [], []

    for t in pack_tasks:
        if t["product"] in ("Asana", "ClickUp"):
            c = pack_cases[t["case_id"]]
            cases.append(c)
            tasks.append({**t, "source": "pack"})
            o = outcomes[t["case_id"]]
            outs.append({"case_id": t["case_id"], "product": t["product"], "review_id": o["review_id"],
                         "ratings": o["ratings"], "source": "pack"})

    async def add(prod: str, review: dict, case_id: str, source: str, need: int) -> bool:
        if sum(1 for t in tasks if t["product"] == prod) >= need:
            return False
        d = await draft(prod, review)
        if not d.get("usable") or not d.get("goal"):
            return False
        cases.append({"case_id": case_id, "product": prod, "url": URLS[prod],
                      "profile": {k: (review.get(k) or None) for k in PROFILE},
                      "profile_status": "recorded_reviewer_context_not_verified_identity"})
        tasks.append({"case_id": case_id, "product": prod, "goal": d["goal"], "source": source,
                      "goal_status": "neutral_reconstruction_from_review_not_original_task_instruction",
                      "fixture": {"instructions": d["fixture"], "status": "synthetic_test_assumption",
                                  "names": ["Demo Alpha", "Demo Beta", "Demo Gamma"]},
                      "success_criteria": d.get("success_criteria") or [],
                      "limits": {"max_minutes": 10, "max_actions": 40, "purchase_allowed": False},
                      "annotation_status": "assistant_draft_requires_goal_leakage_review",
                      "activity_source_field": d.get("activity_source_field")})
        outs.append({"case_id": case_id, "product": prod, "review_id": review["review_id"],
                     "ratings": {k: num(review.get(k)) for k in RATINGS}, "source": source})
        return True

    for prod in ["Asana", "ClickUp"]:
        for o in extra[prod]:
            if await add(prod, by_id[o["review_id"]], o["case_id"], "pack_test_untasked", 5):
                break
    for prod, revs in picks.items():
        low_done = high_done = 0
        for r in revs:
            is_low = num(r["overall_rating"]) <= 3
            if (is_low and low_done >= 2) or (not is_low and high_done >= 3):
                continue
            cid = "v2_" + h(r["review_id"])[:10]
            if await add(prod, r, cid, "v2_new", 5):
                low_done += is_low
                high_done += not is_low

    # Evidence reviews for new products: first 10 eligible by hash that are not picked as cases.
    picked = {o["review_id"] for o in outs}
    for prod in NEW:
        pool = sorted((r for r in rows if r["product_name"] == prod and r["review_id"] not in used
                       and r["review_id"] not in picked and num(r["ease_of_use_rating"])), key=lambda r: h("ev|" + r["review_id"]))
        V2.joinpath("evidence", f"{prod}.jsonl").write_text("".join(
            json.dumps({"evidence_id": r["review_id"], **{k: r[k] for k in ["product_name", *PROFILE, *TEXT,
                        "overall_rating", "ease_of_use_rating", "functionality_rating", "value_for_money_rating"]}},
                       ensure_ascii=False) + "\n" for r in pool[:10]))
    for prod in ["Asana", "ClickUp"]:
        src = PACK / "evidence/reviews" / f"{prod}.jsonl"
        V2.joinpath("evidence", f"{prod}.jsonl").write_text("".join(src.read_text().splitlines(True)[:10]))

    V2.joinpath("inputs/cases.jsonl").write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in cases))
    V2.joinpath("inputs/e2e_tasks.jsonl").write_text("".join(json.dumps(t, ensure_ascii=False) + "\n" for t in tasks))
    V2.joinpath("evaluator_only/outcomes.jsonl").write_text("".join(json.dumps(o) + "\n" for o in outs))
    from collections import Counter
    print(json.dumps({"cases": len(cases), "per_product": Counter(t["product"] for t in tasks)}))


if __name__ == "__main__":
    asyncio.run(main())
