"""Matched reviewer-task pilot: does UserSim execution reduce error in predicting a
historical reviewer's ease-of-use rating and friction?

Unit = one review. Visible: product, the reviewer's stated role/industry/size/tenure, and a
neutral description of their dominant stated task. Hidden: ease rating, pros/cons, frictions.

Conditions (same final predictor, same prompt template, same cases):
  A  model + product pages (D) + reviewer/task card
  B  A + occupational (O) + competitor-review (C) evidence
  C  B + observations from a generic agent executing the task
  D  B + observations from UserSim executing it with the reviewer/task context

Commands (repo root):
    python experiments/staged_context/matched.py select
    python experiments/staged_context/matched.py predict --conditions A,B
    python experiments/staged_context/matched.py execute --arm generic|usersim   # needs a product account per site
    python experiments/staged_context/matched.py predict --conditions C,D
    python experiments/staged_context/matched.py score
    python experiments/staged_context/matched.py report
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import experiment as E  # noqa: E402

MOUT = E.OUT / "matched"
MHIDDEN = MOUT / "hidden"
OBS = MOUT / "observations"
QUOTA = {"Asana": 7, "Trello": 7, "ClickUp": 6}
APP_URLS = {"Asana": "https://app.asana.com/", "Trello": "https://trello.com/", "ClickUp": "https://app.clickup.com/"}
CONDS = {"A": ["D"], "B": ["D", "O", "C"], "C": ["D", "O", "C"], "D": ["D", "O", "C"]}
OBS_ARM = {"C": "generic", "D": "usersim"}
# Evaluative wording a neutral task description must not contain (it would leak the hidden experience).
LEAK = re.compile(r"\b(eas(y|ier|ily)|hard|difficult|frustrat\w*|intuitive|confus\w*|simple|slow|fast|love\w*|hate\w*|"
                  r"great|annoy\w*|clunky|steep|struggl\w*|smooth\w*|seamless\w*|painful|issue\w*|problem\w*|bug\w*|"
                  r"limitation\w*|lack\w*|wish\w*|helpful|useful|efficient\w*|effective\w*)\b", re.I)


# ----------------------------------------------------------------------------- selection

SCREEN_SYSTEM = "You screen software reviews for an evaluation set. Return JSON only."
SCREEN_PROMPT = """Decide whether this {product} review states one clear, dominant task the reviewer uses the product for.
Criteria (all required for eligible=true):
- The task is explicitly stated in the review text (not inferred from job title or industry).
- It is a concrete activity with an object (e.g. "plan weekly social media posts across clients"), not generic praise
  ("organize everything", "manage projects" with nothing more specific).
- A person could attempt it in a fresh trial workspace of {product} within about 15 minutes.
If eligible, describe the task NEUTRALLY: what the person sets out to do, with context and purpose from the review,
WITHOUT any information about how it went (no ease, difficulty, speed, likes, dislikes, problems, features they
praised or missed). Write it as an instruction, e.g. "Set up a board to track each client's onboarding steps and assign owners."
Return {{"eligible": bool, "reason": str, "task": {{"action": str, "object": str, "context": str|null, "purpose": str|null}},
"neutral_task": str, "span": "verbatim substring of the review stating the task"}}

Review:
{review}
"""


def context_ok(r: dict) -> bool:
    return (E.role_family(r.get("reviewer_job_title")) != "unknown" and bool(E.clean(r.get("reviewer_company_size")))
            and bool(E.clean(r.get("reviewer_time_used_product"))) and bool(E.clean(r.get("reviewer_industry")))
            and r.get("ease_of_use_rating") in (1, 2, 3, 4, 5))


def case_card(r: dict, screen: dict) -> dict:
    return {
        "case_id": "case-" + E.sha("matched|" + r["review_id"])[:8],
        "product": r["product_name"],
        "role_title": E.clean(r.get("reviewer_job_title")),
        "role_family": E.role_family(r.get("reviewer_job_title")),
        "industry": E.clean(r.get("reviewer_industry")),
        "company_size_band": E.clean(r.get("reviewer_company_size")),
        "tenure_band": E.clean(r.get("reviewer_time_used_product")),
        "task": screen["task"],
        "neutral_task": screen["neutral_task"],
    }


def select(seed: int = 42) -> None:
    """Fresh rows only: evidence-pool reviews not used in any C/T pack (never dev/test). Screened in hash order;
    the screen sees prose for task clarity only. Ratings are used only to require that one exists."""
    splits = E.read_json(E.OUT / "splits.json")
    used = {x["review_id"] for t in E.PRODUCTS for k in ("C", "T") for x in E.read_json(E.PACKS / t / f"{k}.json")["items"]}
    df, _ = E.load_capterra()
    rows = {r["review_id"]: r for r in df.to_dict("records")}
    cards, hidden, log = [], [], []
    for p in E.PRODUCTS:
        ids = [x["review_id"] for x in splits["products"][p]["pool"] if x["review_id"] not in used]
        ids.sort(key=lambda i: E.sha(f"{seed}|matched|{p}|{i}"))
        n = 0
        for rid in ids:
            if n >= QUOTA[p]:
                break
            r = {k: (None if isinstance(v, float) and np.isnan(v) else v) for k, v in rows[rid].items()}
            if not context_ok(r):
                log.append({"review_id": rid, "product": p, "eligible": False, "reason": "missing context or rating"})
                continue
            text = E.review_for_extraction(r)
            rec = E.call_model("matched_screen", E.JUDGE_MODEL, SCREEN_SYSTEM,
                               SCREEN_PROMPT.format(product=p, review=text), temperature=0.0, seed=42, max_tokens=4096)
            s = rec.get("json") or {}
            ok = bool(s.get("eligible")) and isinstance(s.get("task"), dict) and bool(s.get("neutral_task"))
            reason = s.get("reason", rec.get("error"))
            if ok and LEAK.search(s["neutral_task"]):
                ok, reason = False, "neutral_task contained evaluative wording: " + LEAK.search(s["neutral_task"]).group(0)
            if ok and not E.span_ok(s.get("span", ""), text):
                ok, reason = False, "task span not verbatim"
            log.append({"review_id": rid, "product": p, "eligible": ok, "reason": reason})
            if not ok:
                continue
            card = case_card(r, s)
            cards.append(card)
            ref = E.extract_references_rows([r], p)[0]
            hidden.append({"case_id": card["case_id"], "review_id": rid, "product": p, "task_span": s["span"],
                           "ease_of_use_rating": int(r["ease_of_use_rating"]), "pros": r.get("pros"),
                           "cons": r.get("cons"), "benefits": ref["benefits"], "frictions": ref["frictions"],
                           "tasks": ref["tasks"], "reviewer_job_title": r.get("reviewer_job_title")})
            n += 1
    E.write_json(MOUT / "cases.json", {"seed": seed, "quota": QUOTA, "source": "evidence pool minus C/T pack rows",
                                       "screen_model": E.JUDGE_MODEL, "cases": cards})
    E.write_jsonl(MHIDDEN / "answers.jsonl", hidden)
    E.write_jsonl(MOUT / "screening_log.jsonl", log)
    print(f"selected {len(cards)} cases from {len(log)} screened rows")


# ----------------------------------------------------------------------------- execution (UserSim / generic agent)

GENERIC_PERSONA = {"id": "generic", "name": "A capable assistant", "bio": "You complete software tasks for a user."}


def usersim_persona(card: dict) -> dict:
    return {"id": card["case_id"], "name": card["role_title"],
            "bio": (f"{card['role_title']} in {card['industry']}, at a company of {card['company_size_band']}, "
                    f"who has used {card['product']} for {card['tenure_band']}.")}


async def _execute_one(card: dict, arm: str) -> dict:
    sys.path.insert(0, str(E.ROOT / "src"))
    sys.path.insert(0, str(E.ROOT))
    from mvp.browser_agent import run_browser_agent

    persona = GENERIC_PERSONA if arm == "generic" else usersim_persona(card)
    segment = "general users" if arm == "generic" else f"{card['role_family']} / {card['industry']}"
    return await run_browser_agent(study_id=f"matched-{arm}", agent_id=card["case_id"], url=APP_URLS[card["product"]],
                                   task_prompt=card["neutral_task"], persona=persona, segment=segment)


OBS_SYSTEM = "You summarize a browser agent's run into factual observations. Return JSON only."
OBS_PROMPT = """Summarize what happened when an agent attempted this task in {product}.
Task: {task}
Run: completed={completed}, steps={steps}, final_url={final_url}
Actions and results (in order):
{actions}

Report only what the run shows. Do not guess how a human would rate the product.
Return {{"completed": bool, "steps": int, "blockers": [str], "errors_or_retries": [str], "observations": [str]}}"""


def execute(arm: str) -> None:
    """Writes observations/{case_id}_{arm}.json. Any runner producing this schema can replace this one."""
    cards = E.read_json(MOUT / "cases.json")["cases"]
    for card in cards:
        out = OBS / f"{card['case_id']}_{arm}.json"
        if out.exists():
            continue
        try:
            run = asyncio.run(_execute_one(card, arm))
        except Exception as exc:  # noqa: BLE001
            E.write_json(OBS / f"{card['case_id']}_{arm}.error.json", {"error": f"{type(exc).__name__}: {exc}"})
            print(f"{card['case_id']} {arm}: {type(exc).__name__}: {exc}")
            continue
        acts = "\n".join(f"{i + 1}. {json.dumps(a, default=str)[:300]}" for i, a in enumerate(run.get("actions") or []))
        rec = E.call_model("matched_obs", E.PREDICT_MODEL, OBS_SYSTEM,
                           OBS_PROMPT.format(product=card["product"], task=card["neutral_task"], completed=run.get("completed"),
                                             steps=run.get("num_steps"), final_url=run.get("final_url"), actions=acts or "(none)"),
                           temperature=0.0, seed=42, max_tokens=4096)
        E.write_json(out, {"case_id": card["case_id"], "arm": arm, "summary": rec.get("json"), "run_dir": run.get("run_dir"),
                           "completed": run.get("completed"), "num_steps": run.get("num_steps")})


# ----------------------------------------------------------------------------- prediction

PRED_SYSTEM = ("You forecast a specific historical reviewer's reported experience of a software product from incomplete "
               "context. Never write a first-person testimonial. Return JSON only.")
PRED_PROMPT = """A reviewer of {product} described this situation. Predict the ease-of-use rating (1-5) they gave the product
in their review, and the specific frictions and benefits they most likely reported. Their review is hidden from you; you
only know the context below. Ratings on this site skew high; use the evidence, not a guess about the site.

Reviewer and task (as stated by the reviewer; normalized):
- Role: {role_title} (family: {role_family})
- Industry: {industry}
- Company size: {company_size_band}
- Time using {product}: {tenure_band}
- Task: {neutral_task}

Return {{"ease_of_use_probabilities_1_to_5": [p1, p2, p3, p4, p5],
"frictions": [{{"aspect": str, "claim": str, "basis_ids": [str]}}],
"benefits": [{{"aspect": str, "claim": str, "basis_ids": [str]}}], "rationale": str}}
Up to 3 frictions and 3 benefits; fewer is fine. Probabilities in [0,1] summing to 1. basis_ids name evidence items below.

Evidence:
"""


def obs_text(case_id: str, arm: str) -> str | None:
    f = OBS / f"{case_id}_{arm}.json"
    if not f.exists():
        return None
    o = E.read_json(f)["summary"] or {}
    return "\n".join([f"[X:{arm}] completed={o.get('completed')} steps={o.get('steps')}"] +
                     [f"- blocker: {b}" for b in o.get("blockers", [])] +
                     [f"- error/retry: {b}" for b in o.get("errors_or_retries", [])] +
                     [f"- {b}" for b in o.get("observations", [])])


def predict(conditions: list[str], reps: int) -> None:
    cards = E.read_json(MOUT / "cases.json")["cases"]
    path = MOUT / "predictions.jsonl"
    done = {(r["case_id"], r["condition"], r["replicate"]): r for r in E.read_jsonl(path)}
    for rep in range(1, reps + 1):
        for card in cards:
            packs = E.load_packs(card["product"])
            for c in conditions:
                if (card["case_id"], c, rep) in done and done[(card["case_id"], c, rep)]["valid"]:
                    continue
                parts = [PRED_PROMPT.format(**card)]
                for k in ["M"] + CONDS[c]:
                    parts.append(f"## {E.PACK_HEADINGS[k]}\n{E.pack_text(k, packs[k])}\n")
                if c in OBS_ARM:
                    ot = obs_text(card["case_id"], OBS_ARM[c])
                    if ot is None:
                        print(f"skip {card['case_id']} {c}: no {OBS_ARM[c]} observations (run `execute --arm {OBS_ARM[c]}`)")
                        continue
                    parts.append("## Observations from an agent attempting this task in the product today\n" + ot)
                user = "\n".join(parts)
                rec = E.call_model("matched_predict", E.PREDICT_MODEL, PRED_SYSTEM, user,
                                   temperature=E.PREDICT_TEMPERATURE, seed=1000 * rep, max_tokens=8192,
                                   key_extra=f"{card['case_id']}|{c}|{rep}")
                j = rec.get("json") or {}
                probs = j.get("ease_of_use_probabilities_1_to_5")
                valid = isinstance(probs, list) and len(probs) == 5 and all(isinstance(x, (int, float)) and 0 <= x <= 1 for x in probs) \
                    and abs(sum(probs) - 1) <= 0.02
                if valid:
                    j["ease_of_use_probabilities_1_to_5"] = [x / sum(probs) for x in probs]
                done[(card["case_id"], c, rep)] = {
                    "case_id": card["case_id"], "product": card["product"], "condition": c, "replicate": rep,
                    "valid": valid, "error": rec.get("error"), "tasks": [],
                    "ease_of_use_probabilities_1_to_5": j.get("ease_of_use_probabilities_1_to_5"),
                    "frictions": (j.get("frictions") or [])[:3], "benefits": (j.get("benefits") or [])[:3],
                    "rationale": j.get("rationale"), "input_tokens": rec["input_tokens"],
                    "output_tokens": rec["output_tokens"], "cost_usd": rec["cost_usd"]}
                E.write_jsonl(path, sorted(done.values(), key=lambda r: (r["replicate"], r["case_id"], r["condition"])))
    print(f"{sum(r['valid'] for r in done.values())}/{len(done)} valid predictions")


# ----------------------------------------------------------------------------- scoring


def score() -> None:
    answers = {a["case_id"]: a for a in E.read_jsonl(MHIDDEN / "answers.jsonl")}
    preds = [p for p in E.read_jsonl(MOUT / "predictions.jsonl") if p["valid"]]
    jpath = MOUT / "judgments.jsonl"
    judged = {(j["case_id"], j["condition"], j["replicate"]): j for j in E.read_jsonl(jpath)}
    rows = []
    for p in preds:
        a = answers[p["case_id"]]
        ref = {"tasks": [], "benefits": a["benefits"], "frictions": a["frictions"],
               "ease_of_use_rating": a["ease_of_use_rating"], "reviewer_job_title": a["reviewer_job_title"]}
        key = (p["case_id"], p["condition"], p["replicate"])
        if key not in judged or judged[key].get("error"):
            # anon id from case + condition hash; judge never sees the condition label
            j = E.judge_prediction({**p, "product": p["product"], "condition": p["case_id"] + p["condition"]}, [ref])
            judged[key] = {**j, "case_id": p["case_id"], "condition": p["condition"], "replicate": p["replicate"]}
            E.write_jsonl(jpath, list(judged.values()))
        m = E.product_metrics(p, judged[key], [ref])
        probs = p["ease_of_use_probabilities_1_to_5"]
        rows.append({"case_id": p["case_id"], "product": p["product"], "condition": p["condition"],
                     "replicate": p["replicate"], "hidden_rating": a["ease_of_use_rating"],
                     "pred_expected": m["ease_expected"], "abs_err": m["ease_mae"], "rps": m["ease_rps"],
                     "pred_mode": int(np.argmax(probs)) + 1,
                     "friction_recall_strict": m["friction_recall_strict"], "benefit_recall_strict": m["benefit_recall_strict"],
                     "contradiction_rate": m["contradiction_rate"], "n_hidden_frictions": len(a["frictions"]),
                     "cost_usd": p["cost_usd"] + judged[key]["cost_usd"]})
    # baselines: mean rating of the target product's evidence pool; competitor-pack distribution
    splits = E.read_json(E.OUT / "splits.json")
    df, _ = E.load_capterra()
    for cid, a in answers.items():
        pool_ids = {x["review_id"] for x in splits["products"][a["product"]]["pool"]} - {a["review_id"]}
        vals = df[df.review_id.isin(pool_ids)].ease_of_use_rating.dropna().astype(int).tolist()
        cvals = [int(x["ease_of_use_rating"]) for x in E.read_json(E.PACKS / a["product"] / "C.json")["items"]
                 if x.get("ease_of_use_rating") in (1, 2, 3, 4, 5)]
        for name, v in (("BASE_pool_mean", vals), ("BASE_C_pack_dist", cvals)):
            probs = [v.count(k) / len(v) for k in range(1, 6)]
            em = E.ease_metrics(probs, [a["ease_of_use_rating"]])
            rows.append({"case_id": cid, "product": a["product"], "condition": name, "replicate": 0,
                         "hidden_rating": a["ease_of_use_rating"], "pred_expected": em["ease_expected"],
                         "abs_err": em["ease_mae"], "rps": em["ease_rps"]})
    with (MOUT / "metrics.csv").open("w", newline="") as f:
        cols = sorted({k for r in rows for k in r}, key=lambda k: (k not in ("case_id", "product", "condition"), k))
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    print(f"scored {len(preds)} matched predictions")


def report() -> None:
    m = pd.read_csv(MOUT / "metrics.csv")
    model = m[m.condition.isin(list(CONDS))]
    per_case = model.groupby(["condition", "case_id"])[["abs_err", "rps", "friction_recall_strict", "contradiction_rate"]].mean()
    agg = per_case.groupby("condition").mean()
    L = ["# Matched reviewer-task pilot", "",
         "_Prediction of historical reviewer experience from incomplete context. Machine-extracted, machine-judged "
         "references; provisional._", "",
         f"Cases: {m.case_id.nunique()} (Asana/Trello/ClickUp quota {QUOTA}); hidden-rating distribution "
         f"{m.drop_duplicates('case_id').hidden_rating.value_counts().sort_index().to_dict()}", "",
         "| Condition | Rating abs. error ↓ | RPS ↓ | Friction recall ↑ | Reference disagreement ↓ | n cases |",
         "| --- | --- | --- | --- | --- | --- |"]
    for c in CONDS:
        if c in agg.index:
            r = agg.loc[c]
            n = per_case.loc[c].shape[0]
            L.append(f"| {c} | {E.fmt(r.abs_err)} | {E.fmt(r.rps)} | {E.fmt(r.friction_recall_strict)} | "
                     f"{E.fmt(r.contradiction_rate)} | {n} |")
        else:
            L.append(f"| {c} | not run | | | | 0 |")
    for c, g in m[~m.condition.isin(list(CONDS))].groupby("condition"):
        L.append(f"| {c} (no model) | {E.fmt(g.abs_err.mean())} | {E.fmt(g.rps.mean())} | n/a | n/a | {len(g)} |")
    L += ["", "## Paired deltas (same cases; negative error delta = first condition better)", "",
          "| Comparison | Δ abs. error | 95% case-bootstrap | Δ friction recall | n paired |", "| --- | --- | --- | --- | --- |"]
    rng = np.random.default_rng(42)
    for a, b in (("B", "A"), ("C", "B"), ("D", "B"), ("D", "C")):
        if a not in agg.index or b not in agg.index:
            L.append(f"| {a}−{b} | not run | | | 0 |")
            continue
        x, y = per_case.loc[a], per_case.loc[b]
        ids = x.index.intersection(y.index)
        d = (x.loc[ids].abs_err - y.loc[ids].abs_err).to_numpy()
        boot = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(2000)]
        fr = (x.loc[ids].friction_recall_strict - y.loc[ids].friction_recall_strict).dropna()
        L.append(f"| {a}−{b} | {E.fmt(d.mean())} | [{E.fmt(np.percentile(boot, 2.5))}, {E.fmt(np.percentile(boot, 97.5))}] | "
                 f"{E.fmt(fr.mean()) if len(fr) else 'n/a'} | {len(ids)} |")
    (MOUT / "report_tables.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("select")
    p = sub.add_parser("predict")
    p.add_argument("--conditions", default="A,B")
    p.add_argument("--repetitions", type=int, default=1)
    p = sub.add_parser("execute")
    p.add_argument("--arm", choices=["generic", "usersim"], required=True)
    sub.add_parser("score")
    sub.add_parser("report")
    a = ap.parse_args()
    if a.cmd == "select":
        select()
    elif a.cmd == "predict":
        predict(a.conditions.split(","), a.repetitions)
    elif a.cmd == "execute":
        execute(a.arm)
    elif a.cmd == "score":
        score()
    elif a.cmd == "report":
        report()


if __name__ == "__main__":
    main()
