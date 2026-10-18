"""Pick the best strategy per output on DEV products, then measure it on held-out TEST products.

180 real reviewers, natural (unbalanced) sample, 12 per product. Every product is treated as new: its own reviews are
excluded from every statistic and from the competitor pool. The URL path is exercised: each product's category comes
from classifying its live page, not from the dataset label.

    python experiments/staged_context/router_eval.py
"""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import experiment as E  # noqa: E402
import matched as MT  # noqa: E402
import per_person as PP  # noqa: E402
import usage as US  # noqa: E402
import ux_mcp as U  # noqa: E402

ROUT = E.OUT / "router"
EXTRA_URLS = {
    "Asana": "https://asana.com/", "monday.com AI Work Platform": "https://monday.com/", "Notion": "https://www.notion.com/",
    "HubSpot CRM": "https://www.hubspot.com/products/crm", "Salesforce Sales Cloud": "https://www.salesforce.com/sales/",
    "Zendesk Suite": "https://www.zendesk.com/", "Intercom": "https://www.intercom.com/", "Mailchimp": "https://mailchimp.com/",
    "ActiveCampaign": "https://www.activecampaign.com/", "Xero": "https://www.xero.com/us/", "FreshBooks": "https://www.freshbooks.com/",
    "BambooHR": "https://www.bamboohr.com/", "Rippling": "https://www.rippling.com/", "Shopify": "https://www.shopify.com/",
    "Wix": "https://www.wix.com/", "Microsoft Power BI": "https://www.microsoft.com/en-us/power-platform/products/power-bi",
    "Slack": "https://slack.com/", "Okta": "https://www.okta.com/", "LastPass": "https://www.lastpass.com/",
    "GitLab": "https://about.gitlab.com/",
}
URLS = {**US.URLS, **EXTRA_URLS}
# v1 chose on 5 products and picked "agent_alone" for pros; v2 chooses on these 25 (test set unchanged)
DEV = ["Pipedrive", "Wrike", "Help Scout", "Brevo", "Namely"] + list(EXTRA_URLS)
TEST = ["Freshsales", "Zoho CRM", "Looker", "Basecamp", "LiveAgent", "Zoho Desk", "Klaviyo", "BigCommerce", "Smartsheet", "Freshdesk"]
PER_PRODUCT = 12
FLASH = "gemini-2.5-flash"
CALLS = ("agent_alone", "agent_full", "agent_averages")

PRED = """Predict how THIS person experienced {product}. Their review is hidden; you only know the context below.

- Product: {product} ({url})
- Role: {role_title} (family: {role_family})
- Industry: {industry}
- Company size: {company_size}
- Time using {product}: {time_used}
- Task: {task}
- Previous product / alternatives: {previous}

Return JSON:
{{"ease_of_use_rating": 1-5, "functionality_rating": 1-5, "overall_rating": 1-5, "value_for_money_rating": 1-5,
 "customer_support_rating": 1-5, "recommendation_score": 0-10,
 "pros": [up to 3 short specific things they liked], "cons": [up to 3 short specific things that frustrated them],
 "overall_experience": "2-3 sentences summarising their experience, in third person"}}
{evidence}"""

EXTRACT = """From this review return JSON {{"task": neutral one-sentence description of the main thing they use the product
for, written as an instruction, with NO opinion or difficulty words; null if no concrete task is stated,
"benefits": [specific positive points, max 4], "frictions": [specific problems, max 4]}}. "No cons" is not a friction.
Review of {product}:
{text}"""

JUDGE = """Evaluate predictions of one reviewer's experience against what they actually wrote.
Score each pair 2 = same specific point, 1 = same general area but vaguer, 0 = different.
Predicted pros:
{pp}
Actual pros:
{ap}
Predicted cons:
{pc}
Actual cons:
{ac}
Predicted overall summary: {po}
Actual review text: {at}
Return {{"pros": [{{"pred": "P1", "act": "A1", "score": 2}}], "cons": [{{"pred": "P1", "act": "A1", "score": 1}}],
"overall": 2 if same sentiment AND same main point, 1 if same sentiment only, 0 otherwise}}. List only pairs scoring 1 or 2."""


def sample(df: pd.DataFrame) -> list[dict]:
    people = []
    for p in DEV + TEST:
        g = df[(df.product_name == p) & df.pros.notna() & df.overall_rating.notna()].copy()
        g = g[g.apply(lambda r: MT.context_ok({**r.to_dict(), "ease_of_use_rating": r.ease_of_use_rating}), axis=1)]
        g = g.assign(_h=g.review_id.map(lambda i: E.sha(f"42|router|{p}|{i}"))).sort_values("_h").head(PER_PRODUCT)
        for r in g.to_dict("records"):
            people.append({k: (None if isinstance(v, float) and np.isnan(v) else v) for k, v in r.items()})
    return people


def card(r: dict, task: str | None) -> dict:
    prev = "; ".join(str(r[x]) for x in ("switched_from", "alternatives_considered") if r.get(x)) or "not stated"
    return {"product": r["product_name"], "url": URLS[r["product_name"]], "role_title": E.clean(r["reviewer_job_title"]),
            "role_family": E.role_family(r["reviewer_job_title"]), "industry": r["reviewer_industry"],
            "company_size": r["reviewer_company_size"], "time_used": r["reviewer_time_used_product"],
            "task": task or "not stated", "previous": prev}


def main() -> None:
    df = U.data()
    people = sample(df)
    pool = ThreadPoolExecutor(128)

    def extract(r):
        text = E.review_for_extraction(r)
        rec = E.call_model("router_extract", FLASH, "You extract claims from reviews. Return JSON only.",
                           EXTRACT.format(product=r["product_name"], text=text), temperature=0.0, seed=42,
                           max_tokens=4096, thinking_budget=512)
        j = rec.get("json") if isinstance(rec.get("json"), dict) else {}
        task = j.get("task") if isinstance(j.get("task"), str) and not MT.LEAK.search(j.get("task") or "") else None
        return r["review_id"], {"task": task, "benefits": [str(x) for x in (j.get("benefits") or [])][:4],
                                "frictions": [str(x) for x in (j.get("frictions") or [])][:4]}

    refs = dict(pool.map(extract, people))
    cats = dict(pool.map(lambda p: (p, U.classify(URLS[p])["category"]), DEV + TEST))
    cards = {r["review_id"]: card(r, refs[r["review_id"]]["task"]) for r in people}
    pkgs = dict(pool.map(lambda r: (r["review_id"], U.build_package(URLS[r["product_name"]], {
        "role_family": cards[r["review_id"]]["role_family"], "company_size": r["reviewer_company_size"],
        "time_used": r["reviewer_time_used_product"], "industry": r["reviewer_industry"]},
        exclude_product=r["product_name"], mask=U.mask_for(r["product_name"]))), people))

    def predict(job):
        rid, s = job
        sec = pkgs[rid]["sections"]
        ev = {"agent_alone": "", "agent_full": "\nData:\n" + "\n\n".join(sec.values()),
              "agent_averages": "\nData:\n" + sec["averages"]}[s]
        rec = E.call_model("router_predict", FLASH, MT.PRED_SYSTEM, PRED.format(**cards[rid], evidence=ev),
                           temperature=E.PREDICT_TEMPERATURE, seed=1000, max_tokens=8192, thinking_budget=1024,
                           key_extra=f"{rid}|{s}")
        return rid, s, rec.get("json") if isinstance(rec.get("json"), dict) else {}

    preds = {(rid, s): j for rid, s, j in pool.map(predict, [(r["review_id"], s) for r in people for s in CALLS])}
    rows = {r["review_id"]: r for r in people}

    def judge(job):
        rid, s = job
        j, ref = preds[(rid, s)], refs[rid]
        lst = lambda x: [str(v) for v in x][:3] if isinstance(x, list) else []  # noqa: E731
        fmt = lambda xs, p: "\n".join(f"{p}{i + 1}: {x}" for i, x in enumerate(xs)) or "(none)"  # noqa: E731
        rec = E.call_model("router_judge", FLASH, "You are a strict evaluator. Return JSON only.", JUDGE.format(
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
                        "overall_experience": (ov == 2) if ov in (0, 1, 2) else None}

    judged = {(rid, s): v for rid, s, v in pool.map(judge, list(preds))}

    # candidate values per rating output
    def cand(rid, out, lo, hi):
        av = pkgs[rid]["estimates"][out]
        f = lambda s: U_num(preds[(rid, s)].get(out), lo, hi)  # noqa: E731
        c = {"averages": av, "agent_alone": f("agent_alone"), "agent_full": f("agent_full"), "agent_averages": f("agent_averages")}
        c["blend"] = (av + c["agent_full"]) / 2 if c["agent_full"] is not None else None
        return c

    rating_rows = []
    for r in people:
        rid = r["review_id"]
        for out, (lo, hi) in U.RATINGS.items():
            if r.get(out) is None:
                continue
            for s, v in cand(rid, out, lo, hi).items():
                if v is not None:
                    rating_rows.append({"rid": rid, "product": r["product_name"], "split": "dev" if r["product_name"] in DEV else "test",
                                        "output": out, "strategy": s, "pred": v, "y": r[out]})
    R = pd.DataFrame(rating_rows)
    R["abs_err"] = (R.pred - R.y).abs()
    text_rows = [{"rid": rid, "product": rows[rid]["product_name"], "split": "dev" if rows[rid]["product_name"] in DEV else "test",
                  "output": k, "strategy": s, "score": float(v)} for (rid, s), d in judged.items() for k, v in d.items() if v is not None]
    T = pd.DataFrame(text_rows)

    # unhappy risk: score = predicted shortfall on overall + recommend; label = overall<=3 or recommend<=6
    risk = []
    for r in people:
        rid = r["review_id"]
        if r.get("overall_rating") is None:
            continue
        y = int(r["overall_rating"] <= 3 or (r.get("recommendation_score") is not None and r["recommendation_score"] <= 6))
        co, cr = cand(rid, "overall_rating", 1, 5), cand(rid, "recommendation_score", 0, 10)
        for s in co:
            if co[s] is not None and cr[s] is not None:
                risk.append({"rid": rid, "split": "dev" if r["product_name"] in DEV else "test", "strategy": s,
                             "score": (5 - co[s]) + (10 - cr[s]) / 2, "y": y})
    K = pd.DataFrame(risk)

    def auc(g):
        return PP.auc(list(g.score), list(g.y))

    # choose on dev
    strategy = {}
    for out in U.RATINGS:
        d = R[(R.split == "dev") & (R.output == out)].groupby("strategy").abs_err.mean()
        strategy[out] = d.idxmin()
    for out in ("pros", "cons", "overall_experience"):
        d = T[(T.split == "dev") & (T.output == out)].groupby("strategy").score.mean()
        strategy[out] = d.idxmax()
    risk_dev = K[K.split == "dev"].groupby("strategy").apply(auc)
    router = {"strategy": strategy, "risk": {"unhappy_risk": risk_dev.idxmax()}, "chosen_on": DEV,
              "dev_scores": {"ratings_mae": R[R.split == "dev"].groupby(["output", "strategy"]).abs_err.mean().unstack().round(3).to_dict(),
                             "text": T[T.split == "dev"].groupby(["output", "strategy"]).score.mean().unstack().round(3).to_dict(),
                             "risk_auc": risk_dev.round(3).to_dict()}}
    ROUT.mkdir(parents=True, exist_ok=True)
    E.write_json(U.ROUTER_PATH, router)

    # report on test
    lines = []
    for out in U.RATINGS:
        g = R[(R.split == "test") & (R.output == out)].groupby("strategy").abs_err.mean()
        lines.append({"output": out, "metric": "error (lower better)", "agent_alone": g.get("agent_alone"),
                      "router_pick": strategy[out], "router": g.get(strategy[out]), "best_on_test": g.idxmin(), "best_value": g.min(),
                      "n": int((R[(R.split == 'test') & (R.output == out)].strategy == 'averages').sum())})
    for out in ("pros", "cons", "overall_experience"):
        g = T[(T.split == "test") & (T.output == out)].groupby("strategy").score.mean()
        lines.append({"output": out, "metric": "share matched (higher better)", "agent_alone": g.get("agent_alone"),
                      "router_pick": strategy[out], "router": g.get(strategy[out]), "best_on_test": g.idxmax(), "best_value": g.max(),
                      "n": int((T[(T.split == 'test') & (T.output == out)].strategy == 'agent_alone').sum())})
    kt = K[K.split == "test"].groupby("strategy").apply(auc)
    lines.append({"output": "unhappy_risk", "metric": "AUC (0.5 = chance)", "agent_alone": kt.get("agent_alone"),
                  "router_pick": router["risk"]["unhappy_risk"], "router": kt.get(router["risk"]["unhappy_risk"]),
                  "best_on_test": kt.idxmax(), "best_value": kt.max(),
                  "n": int((K[K.split == "test"].strategy == "agent_alone").sum())})
    rep = pd.DataFrame(lines)
    rep.to_csv(ROUT / "test_report.csv", index=False)
    R.to_csv(ROUT / "ratings_long.csv", index=False)
    T.to_csv(ROUT / "text_long.csv", index=False)
    E.write_json(ROUT / "category_check.json", {p: {"classified": cats[p], "dataset": df[df.product_name == p].product_category_group.iloc[0]}
                                               for p in DEV + TEST})
    pd.set_option("display.width", 220)
    print("router:", strategy, router["risk"])
    print(rep.round(3).to_string(index=False))
    print("test per-strategy rating error:\n", R[R.split == "test"].groupby(["output", "strategy"]).abs_err.mean().unstack().round(3))
    print("category check:", {p: v["classified"] == v["dataset"] for p, v in E.read_json(ROUT / "category_check.json").items()})
    print(f"spend ${E.spent_usd():.3f}")


def U_num(x, lo, hi):
    try:
        return min(max(float(x), lo), hi)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    main()
