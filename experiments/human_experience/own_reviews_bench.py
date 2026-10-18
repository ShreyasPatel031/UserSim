"""Does the product's OWN earlier reviews (by other people) improve the context agent's predictions, words included?

Same 420 Capterra reviewers, card, predictor prompt and judge as router_eval (agent_full is a cache hit). New evidence
appended to the agent_full package (rivals' averages, complaint topics, similar people's rival reviews):
  own_recent   the product's 8 most recent reviews dated before this person's review, plus the product's last-100
               rating averages shrunk to the category (k=10, from heldout_bench)
  own_similar  the same rating line, plus 8 of the product's last 200 earlier reviews by the most similar people
  own_only     people-like-them averages + own_similar, without the rival sections
No fitting happens here, so every person is held out (their own review is never in the evidence: earlier dates only).

    EXP_SPEND_CAP_USD=60 python own_reviews_bench.py
"""

from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

CTX = Path(os.environ.get("CTX_ROOT", "/home/user/UserSim-ctx"))
sys.path.insert(0, str(CTX / "experiments/staged_context"))

import experiment as E  # noqa: E402
import matched as MT  # noqa: E402
import router_eval as RE  # noqa: E402
import ux_mcp as U  # noqa: E402

HERE = Path(__file__).resolve().parent
OUT = HERE / "results/own_reviews_bench"
FLASH = RE.FLASH
CONDS = ["agent_full", "own_recent", "own_similar", "own_only"]
K, LAST = 10, 100


def own_section(r: dict, df: pd.DataFrame, card: dict, mode: str) -> str:
    own = df[(df.product_name == r["product_name"]) & (df.review_date < r["review_date"]) & (df.review_id != r["review_id"])]
    own = own.sort_values("review_date")
    cat = df[(df.product_category_group == r["product_category_group"]) & (df.product_name != r["product_name"])]
    lines = []
    for out in U.RATINGS:
        v = own[out].dropna().to_numpy()[-LAST:]
        prior = cat[out].mean()
        est = (v.sum() + K * prior) / (len(v) + K)
        lines.append(f"- {out}: last {len(v)} reviews of this product average {v.mean() if len(v) else float('nan'):.2f}; "
                     f"same-category rivals {prior:.2f}; combined estimate {est:.2f}")
    pool = own.tail(200 if mode == "similar" else 8)
    if mode == "similar":
        s = (3 * (pool.role_family == card["role_family"]) + 2 * (pool.reviewer_company_size == r["reviewer_company_size"])
             + (pool.reviewer_time_used_product == r["reviewer_time_used_product"]) + (pool.reviewer_industry == r["reviewer_industry"]))
        pool = pool.assign(_s=s).sort_values(["_s", "review_date"], ascending=[False, False]).head(8)
    revs = []
    for x in pool.to_dict("records"):
        x = {k: (None if isinstance(v, float) and np.isnan(v) else v) for k, v in x.items()}
        revs.append(E.format_review(x, None)[0])
    label = "most similar earlier reviewers" if mode == "similar" else "most recent earlier reviews"
    return (f"## This product's own earlier reviews (other people; {len(own)} available)\nRatings:\n" + "\n".join(lines)
            + f"\n\n{label.capitalize()}:\n" + "\n\n".join(revs))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    df = U.data()
    people = RE.sample(df)
    # the categories router_eval got from classifying the live pages (out/router/category_check.json); the page cache
    # isn't in the repo and re-fetched pages can come back empty, so reuse them for an identical agent_full package
    chk = E.read_json(E.OUT / "router" / "category_check.json")
    cat_of = {RE.URLS[p]: chk[p]["classified"] for p in RE.DEV + RE.TEST}
    U.classify = lambda url: {"category": cat_of[url], "product_name": None, "page_text": ""}
    pool = ThreadPoolExecutor(96)

    def extract(r):  # identical call to router_eval -> cache hit
        rec = E.call_model("router_extract", FLASH, "You extract claims from reviews. Return JSON only.",
                           RE.EXTRACT.format(product=r["product_name"], text=E.review_for_extraction(r)), temperature=0.0,
                           seed=42, max_tokens=4096, thinking_budget=512)
        j = rec.get("json") if isinstance(rec.get("json"), dict) else {}
        task = j.get("task") if isinstance(j.get("task"), str) and not MT.LEAK.search(j.get("task") or "") else None
        return r["review_id"], {"task": task, "benefits": [str(x) for x in (j.get("benefits") or [])][:4],
                                "frictions": [str(x) for x in (j.get("frictions") or [])][:4]}

    refs = dict(pool.map(extract, people))
    cards = {r["review_id"]: RE.card(r, refs[r["review_id"]]["task"]) for r in people}
    pkgs = dict(pool.map(lambda r: (r["review_id"], U.build_package(RE.URLS[r["product_name"]], {
        "role_family": cards[r["review_id"]]["role_family"], "company_size": r["reviewer_company_size"],
        "time_used": r["reviewer_time_used_product"], "industry": r["reviewer_industry"]},
        exclude_product=r["product_name"], mask=U.mask_for(r["product_name"]))), people))
    rows = {r["review_id"]: r for r in people}

    def evidence(rid, cond):
        sec, r = pkgs[rid]["sections"], rows[rid]
        if cond == "agent_full":
            return "\nData:\n" + "\n\n".join(sec.values())
        own = own_section(r, df, cards[rid], "recent" if cond == "own_recent" else "similar")
        if cond == "own_only":
            return "\nData:\n" + sec["averages"] + "\n\n" + own
        return "\nData:\n" + "\n\n".join(sec.values()) + "\n\n" + own

    def predict(job):
        rid, s = job
        rec = E.call_model("router_predict" if s == "agent_full" else "own_predict", FLASH, MT.PRED_SYSTEM,
                           RE.PRED.format(**cards[rid], evidence=evidence(rid, s)), temperature=E.PREDICT_TEMPERATURE,
                           seed=1000, max_tokens=8192, thinking_budget=1024, key_extra=f"{rid}|{s}")
        return rid, s, rec.get("json") if isinstance(rec.get("json"), dict) else {}

    preds = {(rid, s): j for rid, s, j in pool.map(predict, [(r["review_id"], s) for r in people for s in CONDS])}

    def judge(job):  # identical judge call to router_eval
        rid, s = job
        j, ref = preds[(rid, s)], refs[rid]
        lst = lambda x: [str(v) for v in x][:3] if isinstance(x, list) else []  # noqa: E731
        fmt = lambda xs, p: "\n".join(f"{p}{i + 1}: {x}" for i, x in enumerate(xs)) or "(none)"  # noqa: E731
        rec = E.call_model("router_judge", FLASH, "You are a strict evaluator. Return JSON only.", RE.JUDGE.format(
            pp=fmt(lst(j.get("pros")), "P"), ap=fmt(ref["benefits"], "A"), pc=fmt(lst(j.get("cons")), "P"),
            ac=fmt(ref["frictions"], "A"), po=str(j.get("overall_experience") or ""), at=E.review_for_extraction(rows[rid])),
            temperature=0.0, seed=42, max_tokens=4096, thinking_budget=512)
        g = rec.get("json") if isinstance(rec.get("json"), dict) else {}

        def recall(key, n):
            best = {}
            for m in g.get(key) or []:
                if isinstance(m, dict) and m.get("score") in (1, 2):
                    best[m.get("act")] = max(best.get(m.get("act"), 0), m["score"])
            return (sum(v == 2 for v in best.values()) / n) if n else None
        ov = g.get("overall")
        return rid, s, {"pros": recall("pros", len(ref["benefits"])), "cons": recall("cons", len(ref["frictions"])),
                        "overall_experience": float(ov == 2) if ov in (0, 1, 2) else None}

    judged = {(rid, s): v for rid, s, v in pool.map(judge, list(preds))}
    out = []
    for (rid, s), j in preds.items():
        r = rows[rid]
        row = {"rid": rid, "product": r["product_name"], "split": "dev" if r["product_name"] in RE.DEV else "test", "cond": s}
        for o, (lo, hi) in U.RATINGS.items():
            v = RE.U_num(j.get(o), lo, hi)
            row[f"{o}_pred"], row[f"{o}_y"] = v, r.get(o)
            row[f"{o}_abs_err"] = abs(v - r[o]) if v is not None and r.get(o) is not None else None
        row.update(judged[(rid, s)])
        out.append(row)
    M = pd.DataFrame(out)
    M.to_csv(OUT / "per_person.csv", index=False)
    cols = [c for c in M.columns if c.endswith("_abs_err")] + ["pros", "cons", "overall_experience"]
    S = M.groupby("cond")[cols].mean().loc[CONDS]
    S.to_csv(OUT / "summary.csv")
    pd.set_option("display.width", 250)
    print(S.round(3).T.to_string())
    print("\nTEST products only:\n", M[M.split == "test"].groupby("cond")[cols].mean().loc[CONDS].round(3).T.to_string())
    print(f"spend so far ${E.spent_usd():.2f}")


if __name__ == "__main__":
    main()
