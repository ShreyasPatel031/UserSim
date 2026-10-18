"""The MCP package test: inputs = who the person is and what they are doing; outputs = their experience.

Same 90 balanced CRM reviewers (Freshsales, Zoho CRM, Pipedrive). Inputs: product, role, industry, company size,
time used, task, previous product (when the reviewer named one). Outputs: 6 ratings, likelihood to recommend, pros,
cons, overall experience in words.
  X0  agent alone: inputs only
  X1  agent + MCP package:
        (a) rating averages for people like them (role family, company size, time used) across 63 other products
        (b) same-category competitors' complaint-topic rates and rating averages
        (c) 8 competitor-product reviews from the most similar people (role > size > time used > industry)
  BASE_people_like_them  the averages in (a) used directly, no agent (ratings only)

    python experiments/staged_context/mix.py
"""

from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import experiment as E  # noqa: E402
import matched as MT  # noqa: E402
import outcomes as OC  # noqa: E402
import per_person as PP  # noqa: E402
import predictability as PR  # noqa: E402

XOUT = E.OUT / "mix"
RATINGS = {"ease_of_use_rating": (1, 5), "functionality_rating": (1, 5), "overall_rating": (1, 5),
           "value_for_money_rating": (1, 5), "customer_support_rating": (1, 5), "recommendation_score": (0, 10)}
FEATS = {"role_family": "role_family", "company_size_band": "reviewer_company_size",
         "tenure_band": "reviewer_time_used_product", "industry": "reviewer_industry"}
FLASH = OC.FLASH

PRED = """Predict how THIS person experienced {product}. Their review is hidden; you only know the context below.

- Product: {product}
- Role: {role_title} (family: {role_family})
- Industry: {industry}
- Company size: {company_size_band}
- Time using {product}: {tenure_band}
- Task: {neutral_task}
- Previous product / alternatives: {previous}

Return JSON:
{{"ease_of_use_rating": 1-5, "functionality_rating": 1-5, "overall_rating": 1-5, "value_for_money_rating": 1-5,
 "customer_support_rating": 1-5, "recommendation_score": 0-10,
 "pros": [up to 3 short specific things they liked], "cons": [up to 3 short specific things that frustrated them],
 "overall_experience": "2-3 sentences summarising their experience, written in third person"}}
{evidence}"""

OVERALL_JUDGE = """Compare a predicted summary of a person's software experience with what they actually wrote.
Score 2 = same overall sentiment AND same main point; 1 = same overall sentiment, different main point;
0 = different sentiment. Return {{"score": 0|1|2}}.
Predicted: {pred}
Actual: {act}"""


def main() -> None:
    cards = E.read_json(PP.POUT / "cases.json")["cases"]
    ans = {a["case_id"]: a for a in E.read_jsonl(PP.PHIDDEN / "answers.jsonl")}
    df, _ = E.load_capterra()
    rows = df.set_index("review_id")
    case_ids = {a["review_id"] for a in ans.values()}
    df["role_family"] = df.reviewer_job_title.fillna("").map(E.role_family)
    others = df[~df.product_name.isin(PP.PRODUCTS)]

    # (a) people-like-them averages: per attribute value, mean of each rating over the 63 other products
    seg = {f: others.groupby(col)[list(RATINGS)].agg(["mean", "count"]) for f, col in FEATS.items()}
    glob = others[list(RATINGS)].mean()

    def like_them(c) -> tuple[str, dict]:
        lines, est = [], {}
        for r in RATINGS:
            k, mu = 20.0, glob[r]
            dev = 0.0
            parts = []
            for f, col in FEATS.items():
                v = c[f]
                if v in seg[f].index:
                    m, n = seg[f].loc[v, (r, "mean")], seg[f].loc[v, (r, "count")]
                    dev += (m * n + k * mu) / (n + k) - mu
                    if f != "industry":
                        parts.append(f"{f.replace('_band', '')} '{v}': {m:.2f} (n={int(n)})")
            est[r] = float(np.clip(mu + dev, *RATINGS[r]))
            lines.append(f"- {r}: all reviewers {mu:.2f}; " + "; ".join(parts) + f"; combined estimate {est[r]:.2f}")
        unhappy = others.groupby("reviewer_time_used_product").overall_rating.apply(lambda s: (s <= 3).mean())
        lines.append(f"- share rating overall <=3 for time used '{c['tenure_band']}': {unhappy.get(c['tenure_band'], np.nan):.1%}")
        return "\n".join(lines), est

    # (b) competitor complaint-topic rates and ratings (same category, excluding the 3 targets)
    comp = df[(df.product_category_group == "CRM") & ~df.product_name.isin(PP.PRODUCTS)]
    cons = comp.cons.fillna("").str.lower()
    topic_lines = [f"- {k.replace('complaint_', '')}: {cons.str.contains(p, regex=True).mean():.1%} of reviews mention it"
                   for k, p in PR.TOPICS.items()]
    comp_ratings = "; ".join(f"{r} {comp[r].mean():.2f}" for r in RATINGS)
    comp_text = (f"Competitors: {', '.join(sorted(comp.product_name.unique()))} ({len(comp)} reviews).\n"
                 f"Average ratings: {comp_ratings}\nComplaint topics in their cons:\n" + "\n".join(topic_lines))

    # (c) 8 most similar people using competitor products
    pool = comp[~comp.review_id.isin(case_ids) & comp.pros.notna()].copy()

    def similar(c) -> str:
        s = (3 * (pool.role_family == c["role_family"]) + 2 * (pool.reviewer_company_size == c["company_size_band"])
             + (pool.reviewer_time_used_product == c["tenure_band"]) + (pool.reviewer_industry == c["industry"]))
        tie = pool.review_id.map(lambda i: E.sha(f"42|mix|{c['case_id']}|{i}"))
        top = pool.assign(_s=s, _t=tie).sort_values(["_s", "_t"], ascending=[False, True]).head(8)
        out = []
        for r in top.to_dict("records"):
            r = {k: (None if isinstance(v, float) and np.isnan(v) else v) for k, v in r.items()}
            text, _ = E.format_review(r, PP.NAME_PATTERNS[c["product"]])
            out.append(f"[{r['product_name']}]\n{text}")
        return "\n\n".join(out)

    packages, est = {}, {}
    for c in cards:
        lt, est[c["case_id"]] = like_them(c)
        packages[c["case_id"]] = ("\nData from the product-experience database:\n"
                                  f"## People like this person (other software products)\n{lt}\n\n"
                                  f"## Same-category competitors\n{comp_text}\n\n"
                                  f"## Reviews of competitor products by the most similar people\n{similar(c)}\n")

    def previous(c):
        r = rows.loc[ans[c["case_id"]]["review_id"]]
        vals = [str(r[x]) for x in ("switched_from", "alternatives_considered") if pd.notna(r[x])]
        return "; ".join(vals) if vals else "not stated"

    def predict(job):
        c, s = job
        user = PRED.format(**c, previous=previous(c), evidence=packages[c["case_id"]] if s == "X1" else "")
        rec = E.call_model("mix_predict", FLASH, MT.PRED_SYSTEM, user, temperature=E.PREDICT_TEMPERATURE, seed=1000,
                           max_tokens=8192, thinking_budget=1024, key_extra=f"{c['case_id']}|{s}")
        return c["case_id"], s, rec.get("json") if isinstance(rec.get("json"), dict) else {}

    refs = E.read_json(OC.OOUT / "references.json")  # benefits/frictions extracted once per person (outcomes.py)
    with ThreadPoolExecutor(128) as pool_ex:
        preds = {(c, s): j for c, s, j in pool_ex.map(predict, [(c, s) for c in cards for s in ("X0", "X1")])}

    def actual_words(cid):
        r = rows.loc[ans[cid]["review_id"]]
        return " ".join(str(r[x]) for x in ("review_title", "general_comments", "pros", "cons") if pd.notna(r[x]))

    def judge(job):
        cid, s, cat = job
        j = preds[(cid, s)]
        if cat == "overall_experience":
            rec = E.call_model("mix_judge", FLASH, "You are a strict evaluator. Return JSON only.",
                               OVERALL_JUDGE.format(pred=str(j.get("overall_experience") or ""), act=actual_words(cid)),
                               temperature=0.0, seed=42, max_tokens=2048, thinking_budget=512)
            v = (rec.get("json") or {}).get("score") if isinstance(rec.get("json"), dict) else None
            return cid, s, cat, v if v in (0, 1, 2) else None
        key = {"pros": "benefits", "cons": "frictions"}[cat]
        P, A = OC.clean_list(j.get(cat))[:3], refs[cid][key]
        if not P or not A:
            return cid, s, cat, ([] if A else None)
        rec = E.call_model("mix_judge", FLASH, "You are a strict evaluator. Return JSON only.",
                           OC.JUDGE.format(cat=key, pred="\n".join(f"P{i + 1}: {x}" for i, x in enumerate(P)),
                                           act="\n".join(f"A{i + 1}: {x}" for i, x in enumerate(A))),
                           temperature=0.0, seed=42, max_tokens=4096, thinking_budget=512)
        m = (rec.get("json") or {}).get("matches") if isinstance(rec.get("json"), dict) else []
        best = {}
        for x in m or []:
            if isinstance(x, dict) and x.get("score") in (1, 2):
                best[x.get("act")] = max(best.get(x.get("act"), 0), x["score"])
        return cid, s, cat, (sum(v == 2 for v in best.values()) / len(A), sum(v >= 1 for v in best.values()) / len(A))

    ids = [c["case_id"] for c in cards]
    with ThreadPoolExecutor(128) as pool_ex:
        judged = {(c, s, k): v for c, s, k, v in pool_ex.map(
            judge, [(c, s, k) for c in ids for s in ("X0", "X1") for k in ("pros", "cons", "overall_experience")])}

    out = []
    for r, (lo, hi) in RATINGS.items():
        truth = {c: rows.loc[ans[c]["review_id"], r] for c in ids}
        ok = [c for c in ids if pd.notna(truth[c])]
        for name, pr in (("X0", {c: OC.num(preds[(c, "X0")].get(r), lo, hi) for c in ok}),
                         ("X1", {c: OC.num(preds[(c, "X1")].get(r), lo, hi) for c in ok}),
                         ("BASE_people_like_them", {c: est[c][r] for c in ok})):
            ks = [c for c in ok if pr[c] is not None]
            y, x = np.array([truth[c] for c in ks]), np.array([pr[c] for c in ks])
            thr = 3 if hi == 5 else 6
            out.append({"output": r, "setup": name, "n": len(ks), "mae": float(np.abs(x - y).mean()),
                        "spearman": float(pd.Series(x).rank().corr(pd.Series(y).rank())),
                        "auc_unhappy": PP.auc(list(-x), [int(v <= thr) for v in y]),
                        "exact_or_within_half": float(np.mean(np.abs(x - y) <= (0.5 if hi == 5 else 1.0)))})
    for k in ("pros", "cons"):
        for s in ("X0", "X1"):
            v = [judged[(c, s, k)] for c in ids if judged[(c, s, k)] is not None]
            v = [x if isinstance(x, tuple) else (0.0, 0.0) for x in v]
            out.append({"output": k, "setup": s, "n": len(v), "recall_strict": float(np.mean([a for a, _ in v])),
                        "recall_partial": float(np.mean([b for _, b in v]))})
    for s in ("X0", "X1"):
        v = [judged[(c, s, "overall_experience")] for c in ids if judged[(c, s, "overall_experience")] is not None]
        out.append({"output": "overall_experience", "setup": s, "n": len(v),
                    "same_sentiment": float(np.mean([x >= 1 for x in v])), "same_sentiment_and_point": float(np.mean([x == 2 for x in v]))})
    m = pd.DataFrame(out)
    XOUT.mkdir(parents=True, exist_ok=True)
    m.to_csv(XOUT / "metrics.csv", index=False)
    E.write_jsonl(XOUT / "predictions.jsonl", [{"case_id": c, "setup": s, **j} for (c, s), j in preds.items()])
    E.write_json(XOUT / "example_package.json", {"case": cards[0], "package": packages[cards[0]["case_id"]]})
    pd.set_option("display.width", 220)
    print(m.round(3).to_string(index=False))
    print(f"spend ${E.spent_usd():.3f}")


if __name__ == "__main__":
    main()
