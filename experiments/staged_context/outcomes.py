"""All 8 Capterra outcomes, per person, for the 90 balanced CRM reviewers (Freshsales, Zoho CRM, Pipedrive).

Visible: role, industry, company size, time used, neutral task. Hidden: the person's ratings and review text.
Setups (gemini-2.5-flash): O0 person + product name; O1 + website; O2 + website + 20 competitor reviews.
Ratings scored directly; benefits / friction / choosing-switching reasons are extracted once per person from the
hidden text and matched to predictions by a blind judge (gemini-2.5-flash, 0/1/2 rubric).

    python experiments/staged_context/outcomes.py
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
import per_person as PP  # noqa: E402

OOUT = E.OUT / "outcomes"
SETUPS = {"O0": [], "O1": ["D"], "O2": ["D", "C"]}
RATINGS = {"ease_of_use_rating": (1, 5), "functionality_rating": (1, 5), "overall_rating": (1, 5),
           "value_for_money_rating": (1, 5), "recommendation_score": (0, 10)}
TEXT = {"benefits": ("pros", "general_comments"), "frictions": ("cons", "general_comments"),
        "choosing_switching_reasons": ("reasons_for_choosing", "reasons_for_switching")}
FLASH = "gemini-2.5-flash"

PRED = """A reviewer of {product} described this situation. Predict what THIS person reported in their review.
Their review is hidden; you only know the context below.

- Role: {role_title} (family: {role_family})
- Industry: {industry}
- Company size: {company_size_band}
- Time using {product}: {tenure_band}
- Task: {neutral_task}

Return JSON:
{{"ease_of_use_rating": 1-5, "functionality_rating": 1-5, "overall_rating": 1-5, "value_for_money_rating": 1-5,
 "recommendation_score": 0-10,
 "benefits": [up to 3 short specific things they liked],
 "frictions": [up to 3 short specific problems they hit],
 "choosing_switching_reasons": [up to 3 reasons they chose or switched to {product}],
 "switched_from": product name or null}}

Evidence:
"""

EXTRACT = """Extract what this reviewer explicitly wrote. Return JSON:
{{"benefits": [short specific positive points, max 4], "frictions": [short specific problems, max 4],
 "choosing_switching_reasons": [reasons they chose or switched, max 4]}}
"No cons"/"nothing" is not a friction. Empty lists are fine.

Liked (pros + comments): {pros}
Disliked (cons + comments): {cons}
Reasons for choosing/switching: {reasons}
"""

JUDGE = """Match predicted points to a reviewer's actual points (category: {cat}).
Score each pair: 2 = same specific point; 1 = same general area but vaguer; 0 = different.
Predicted:
{pred}
Actual:
{act}
Return {{"matches": [{{"pred": "P1", "act": "A2", "score": 2}}]}} listing only pairs scoring 1 or 2."""


def clean_list(x) -> list[str]:
    return [str(v).strip() for v in (x or []) if str(v).strip()][:4] if isinstance(x, list) else []


def num(x, lo, hi):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return min(max(v, lo), hi)


def main() -> None:
    cards = E.read_json(PP.POUT / "cases.json")["cases"]
    ans = {a["case_id"]: a for a in E.read_jsonl(PP.PHIDDEN / "answers.jsonl")}
    df, _ = E.load_capterra()
    rows = df.set_index("review_id")
    packs = {p: {k: E.read_json(PP.PPACKS / p / f"{k}.json") for k in "MDC"} for p in PP.PRODUCTS}

    def hidden(case):
        r = rows.loc[ans[case["case_id"]]["review_id"]]
        g = lambda c: "" if pd.isna(r[c]) else str(r[c])  # noqa: E731
        return r, {"pros": " ".join(filter(None, [g("pros"), g("general_comments")])),
                   "cons": " ".join(filter(None, [g("cons"), g("general_comments")])),
                   "reasons": " ".join(filter(None, [g("reasons_for_choosing"), g("reasons_for_switching")]))}

    def extract(case):
        _, h = hidden(case)
        rec = E.call_model("out_extract", FLASH, "You extract claims from reviews. Return JSON only.",
                           EXTRACT.format(**{k: v or "(none)" for k, v in h.items()}), temperature=0.0, seed=42,
                           max_tokens=4096, thinking_budget=512)
        j = rec.get("json") if isinstance(rec.get("json"), dict) else {}
        out = {k: clean_list(j.get(k)) for k in TEXT}
        if not h["reasons"]:
            out["choosing_switching_reasons"] = []
        return case["case_id"], out

    def predict(job):
        case, s = job
        user = PRED.format(**case) + "\n".join(
            f"## {E.PACK_HEADINGS[k]}\n{E.pack_text(k, packs[case['product']][k])}\n" for k in ["M"] + SETUPS[s])
        rec = E.call_model("out_predict", FLASH, MT.PRED_SYSTEM, user, temperature=E.PREDICT_TEMPERATURE, seed=1000,
                           max_tokens=8192, thinking_budget=1024, key_extra=f"{case['case_id']}|{s}")
        return case["case_id"], s, rec.get("json") if isinstance(rec.get("json"), dict) else {}

    with ThreadPoolExecutor(128) as pool:
        refs = dict(pool.map(extract, cards))
        preds = {(c, s): j for c, s, j in pool.map(predict, [(c, s) for c in cards for s in SETUPS])}

    def judge(job):
        cid, s, cat = job
        P, A = clean_list(preds[(cid, s)].get(cat))[:3], refs[cid][cat]
        if not P or not A:
            return cid, s, cat, []
        rec = E.call_model("out_judge", FLASH, "You are a strict evaluator. Return JSON only.",
                           JUDGE.format(cat=cat, pred="\n".join(f"P{i + 1}: {x}" for i, x in enumerate(P)),
                                        act="\n".join(f"A{i + 1}: {x}" for i, x in enumerate(A))),
                           temperature=0.0, seed=42, max_tokens=4096, thinking_budget=512)
        j = rec.get("json") if isinstance(rec.get("json"), dict) else {}
        return cid, s, cat, [m for m in (j.get("matches") or []) if isinstance(m, dict) and m.get("score") in (1, 2)]

    ids = [c["case_id"] for c in cards]
    with ThreadPoolExecutor(128) as pool:
        judged = {(c, s, cat): m for c, s, cat, m in pool.map(judge, [(c, s, cat) for c in ids for s in SETUPS for cat in TEXT])}

    # ratings baselines: attribute model per rating + competitor-pack average
    def attr_pred(col):
        train = df[~df.product_name.isin(PP.PRODUCTS)].dropna(subset=[col])
        tr = pd.DataFrame({"y": train[col], "role_family": train.reviewer_job_title.fillna("").map(E.role_family),
                           "company_size_band": train.reviewer_company_size, "tenure_band": train.reviewer_time_used_product,
                           "industry": train.reviewer_industry})
        mu, k = tr.y.mean(), 20.0
        eff = {f: ((tr.groupby(f).y.sum() + k * mu) / (tr.groupby(f).y.size() + k) - mu).to_dict()
               for f in ("role_family", "company_size_band", "tenure_band", "industry")}
        return {c["case_id"]: mu + sum(eff[f].get(c[f], 0.0) for f in eff) for c in cards}

    def spearman(x, y):
        return float(pd.Series(x).rank().corr(pd.Series(y).rank())) if len(set(x)) > 1 else None

    out = []
    for col, (lo, hi) in RATINGS.items():
        truth = {c["case_id"]: rows.loc[ans[c["case_id"]]["review_id"], col] for c in cards}
        ok = [c for c in ids if pd.notna(truth[c])]
        cands = {s: {c: num(preds[(c, s)].get(col), lo, hi) for c in ok} for s in SETUPS}
        attr = attr_pred(col)
        comp = {p: np.nanmean([rows.loc[x["review_id"], col] for x in packs[p]["C"]["items"]]) for p in PP.PRODUCTS}
        cands["BASE_competitor_avg"] = {c: comp[next(x["product"] for x in cards if x["case_id"] == c)] for c in ok}
        cands["BASE_attribute_model"] = {c: attr[c] for c in ok}
        for name, pr in cands.items():
            ks = [c for c in ok if pr[c] is not None]
            y, x = [truth[c] for c in ks], [pr[c] for c in ks]
            thr = 3 if hi == 5 else 6
            from per_person import auc
            out.append({"outcome": col, "setup": name, "n": len(ks), "mae": float(np.mean(np.abs(np.array(x) - np.array(y)))),
                        "spearman": spearman(x, y), "auc_low": auc([-v for v in x], [int(v <= thr) for v in y]),
                        "kind": "rating"})
    for cat in TEXT:
        for s in SETUPS:
            strict, partial, prec, n = [], [], [], 0
            for c in ids:
                A = refs[c][cat]
                P = clean_list(preds[(c, s)].get(cat))[:3]
                if not A:
                    continue
                n += 1
                m = judged[(c, s, cat)]
                best = {}
                for x in m:
                    best[x.get("act")] = max(best.get(x.get("act"), 0), x["score"])
                strict.append(sum(v == 2 for v in best.values()) / len(A))
                partial.append(sum(v >= 1 for v in best.values()) / len(A))
                if P:
                    prec.append(len({x.get("pred") for x in m if x["score"] == 2}) / len(P))
            out.append({"outcome": cat, "setup": s, "n": n, "recall_strict": float(np.mean(strict)) if strict else None,
                        "recall_partial": float(np.mean(partial)) if partial else None,
                        "precision_strict": float(np.mean(prec)) if prec else None, "kind": "text"})
    # switched_from tool
    sw = {c["case_id"]: rows.loc[ans[c["case_id"]]["review_id"], "switched_from"] for c in cards}
    for s in SETUPS:
        has = [c for c in ids if pd.notna(sw[c])]
        hit = [any(str(preds[(c, s)].get("switched_from") or "").lower() in t.lower() and preds[(c, s)].get("switched_from")
                   for t in str(sw[c]).split("|")) for c in has]
        said_none = [not preds[(c, s)].get("switched_from") for c in ids if pd.isna(sw[c])]
        out.append({"outcome": "switched_from", "setup": s, "n": len(has), "tool_hit_rate": float(np.mean(hit)) if hit else None,
                    "correct_none_rate": float(np.mean(said_none)) if said_none else None, "kind": "switch"})
    m = pd.DataFrame(out)
    OOUT.mkdir(parents=True, exist_ok=True)
    m.to_csv(OOUT / "metrics.csv", index=False)
    E.write_json(OOUT / "references.json", refs)
    E.write_jsonl(OOUT / "predictions.jsonl", [{"case_id": c, "setup": s, **j} for (c, s), j in preds.items()])
    pd.set_option("display.width", 220)
    for k, g in m.groupby("kind", sort=False):
        print(g.dropna(axis=1, how="all").round(3).to_string(index=False), "\n")
    print(f"spend ${E.spent_usd():.3f}")


if __name__ == "__main__":
    main()
