"""Usage pilot (Capterra only): for a NEW product, does adding data help predict who uses it, how long they stay,
and what they switched from?

Hidden answer per product = distributions over ALL its Capterra reviews (226-1,000 each):
  role family, company size band, industry (top 15 + other), time-used band, share who switched + top prior tools.
Setups (gemini-2.5-flash, same prompt, one call per product):
  U0 name + neutral category sentence   U1 + landing page   U2 + landing page + O*NET
  U3 + landing page + O*NET + 20 competitor reviews   U4 + landing page + 20 competitor reviews
Baselines (no AI): all other products' mix; same-category competitors' mix; the 20 competitor reviews' mix.
Score: total variation distance between predicted and actual mix (0 = identical, 1 = disjoint).

    python experiments/staged_context/usage.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import experiment as E  # noqa: E402

UOUT = E.OUT / "usage"
UPACKS = UOUT / "packs"
URLS = {
    "Freshsales": "https://www.freshworks.com/crm/sales/", "Zoho CRM": "https://www.zoho.com/crm/",
    "Pipedrive": "https://www.pipedrive.com/en", "Namely": "https://www.namely.com/",
    "Looker": "https://cloud.google.com/looker", "Wrike": "https://www.wrike.com/", "Basecamp": "https://basecamp.com/",
    "LiveAgent": "https://www.liveagent.com/", "Zoho Desk": "https://www.zoho.com/desk/",
    "Help Scout": "https://www.helpscout.com/", "Brevo": "https://www.brevo.com/", "Klaviyo": "https://www.klaviyo.com/",
    "BigCommerce": "https://www.bigcommerce.com/", "Smartsheet": "https://www.smartsheet.com/",
    "Freshdesk": "https://www.freshdesk.com/",
}  # Domo (405), Sage Intacct (403), Insightly (403) block automated requests and were dropped
SETUPS = {"U0": [], "U1": ["D"], "U2": ["D", "O"], "U3": ["D", "O", "C"], "U4": ["D", "C"]}
SEED = 42
SIZE_BANDS = ["Self-employed", "1-10 employees", "11-50 employees", "51-200 employees", "201-500 employees",
              "501-1,000 employees", "1,001-5,000 employees", "5,001-10,000 employees", "10,001+ employees"]
TENURE_BANDS = ["I used a free trial", "Less than 6 months", "6-12 months", "1-2 years", "2+ years"]
ROLE_FAMILIES = [f for f, _ in E.ROLE_FAMILIES]


def distributions(g: pd.DataFrame, industries: list[str]) -> dict:
    """Actual usage mix for a set of reviews."""
    def mix(values, labels):
        c = Counter(v for v in values if v in labels)
        n = sum(c.values())
        return {k: c[k] / n for k in labels} if n else {k: 0.0 for k in labels}
    roles = g.reviewer_job_title.fillna("").map(E.role_family)
    ind = g.reviewer_industry.fillna("").map(lambda x: x if x in industries else "Other")
    prior = g.switched_from.dropna().str.split("|").explode().str.strip()
    return {"role_family": mix(roles, ROLE_FAMILIES), "company_size": mix(g.reviewer_company_size, SIZE_BANDS),
            "industry": mix(ind, industries + ["Other"]), "time_used": mix(g.reviewer_time_used_product, TENURE_BANDS),
            "switched_share": float(g.switched_from.notna().mean()),
            "top_prior_tools": [k for k, _ in Counter(prior).most_common(5)]}


def _num(x) -> float:
    try:
        return max(float(x), 0.0)
    except (TypeError, ValueError):
        return 0.0


def tvd(p: dict, q: dict) -> float:
    p = {k: _num(v) for k, v in p.items()} if isinstance(p, dict) else {}
    keys = set(p) | set(q)
    sp, sq = sum(p.values()) or 1, sum(q.values()) or 1
    return 0.5 * sum(abs(p.get(k, 0) / sp - q.get(k, 0) / sq) for k in keys)


def score(pred: dict, actual: dict) -> dict:
    s = {f"{k}_tvd": tvd(pred.get(k) or {}, actual[k]) for k in ("role_family", "company_size", "industry", "time_used")}
    s["switched_share_abs_err"] = abs(_num(pred.get("switched_share")) - actual["switched_share"])
    tools = pred.get("top_prior_tools") if isinstance(pred.get("top_prior_tools"), list) else []
    pt = {str(x).lower() for x in tools[:5]}
    s["top_prior_tools_overlap"] = len(pt & {x.lower() for x in actual["top_prior_tools"]}) / 5
    return s


PROMPT = """Predict the user base of {product} as it would appear among its reviewers on a B2B software review site.
Base this only on the evidence below plus general knowledge. Give shares that sum to 1 within each group.

Return JSON:
{{"role_family": {{{roles}}},
 "company_size": {{{sizes}}},
 "industry": {{{inds}}},
 "time_used": {{{tenure}}},
 "switched_share": share of reviewers who switched to {product} from another tool (0-1),
 "top_prior_tools": [up to 5 product names reviewers most often switched from]}}
Role families: executive_owner, project_program_mgmt, product_mgmt, healthcare_wellness, software_it_engineering,
marketing_creative_content, sales_customer, operations_admin, finance_hr_legal, education_research_analysis,
consultant_freelance, general_team_mgmt (other managers/directors/leads), unknown.

Evidence:
"""


def keys(labels):
    return ", ".join(f'"{x}": share' for x in labels)


def main() -> None:
    df, meta = E.load_capterra()
    industries = df.reviewer_industry.value_counts().head(15).index.tolist()
    cat = df.groupby("product_name").product_category_group.first()
    counts = df.product_name.value_counts()
    packs, rows = {}, []

    def prep(item):
        p, url = item
        rows = []
        dest = E.CACHE / "pages" / f"usage_{p.replace(' ', '_')}.html"
        E.download(url, dest)
        sents, dropped = E.filter_sentences(E.page_text(dest.read_text(encoding="utf-8", errors="ignore")))
        D_items, _ = E.passages_from(p, "landing", sents, E.CAP_D_TARGET)
        D = {"items": [{**x, "product": p, "role": "target", "url": url} for x in D_items],
             "sources": [{"url": url, "html_sha256": E.sha(dest.read_bytes()), "sentences_dropped_by_filter": dropped}]}
        # the two largest same-category products are the competitors whose reviews form pack C
        peers = sorted((x for x in cat.index if cat[x] == cat[p] and x != p), key=lambda x: (-counts[x], x))[:2]
        citems = []
        for peer in peers:
            g = df[df.product_name == peer].to_dict("records")
            g = [{k: (None if isinstance(v, float) and np.isnan(v) else v) for k, v in r.items()} for r in g]
            g.sort(key=lambda r: E.sha(f"{SEED}|usageC|{peer}|{r['review_id']}"))
            for r in g[:10]:
                text, info = E.format_review(r, E.NAME_PATTERNS.get(p, rf"\b{p.split()[0].lower()}\b"))
                citems.append({"id": f"C:{r['review_id']}", "review_id": r["review_id"], "product": peer, "text": text, **info})
        seed = f"{p} is a {cat[p]} software product."
        pk = {"M": {"items": [{"id": f"M:{p}", "text": f"Product: {p}. {seed}"}]}, "D": D, "C": {"items": citems}}
        pk["O"] = E.onet_pack(p, D, seed)
        for k, v in pk.items():
            E.write_json(UPACKS / p / f"{k}.json", v)
        actual = distributions(df[df.product_name == p], industries)
        peer_all = df[(df.product_category_group == cat[p]) & (df.product_name != p)]
        bl = {"BASE_all_other_products": distributions(df[df.product_name != p], industries),
              "BASE_category_competitors": distributions(peer_all, industries),
              "BASE_20_competitor_reviews": distributions(df[df.review_id.isin([x["review_id"] for x in citems])], industries)}
        for name, d in bl.items():
            rows.append({"product": p, "setup": name, **score(d, actual)})
        return p, {**pk, "_actual": actual, "_peers": peers}, rows

    with ThreadPoolExecutor(len(URLS)) as pool:  # all products at once: page fetch + O*NET mapping
        for p, pk, r in pool.map(prep, URLS.items()):
            packs[p] = pk
            rows += r

    def run(job):
        p, s = job
        user = PROMPT.format(product=p, roles=keys(ROLE_FAMILIES + ["unknown"]), sizes=keys(SIZE_BANDS),
                             inds=keys(industries + ["Other"]), tenure=keys(TENURE_BANDS))
        user += "\n".join(f"## {E.PACK_HEADINGS[k]}\n{E.pack_text(k, packs[p][k])}\n" for k in ["M"] + SETUPS[s])
        rec = E.call_model("usage_predict", E.PREDICT_MODEL, "You forecast software user bases. Return JSON only.", user,
                           temperature=E.PREDICT_TEMPERATURE, seed=1000, max_tokens=8192, thinking_budget=1024,
                           key_extra=f"{p}|{s}")
        j = rec.get("json") if isinstance(rec.get("json"), dict) else {}
        if isinstance(j.get("role_family"), dict):
            j["role_family"].pop("unknown", None)
        return p, s, j, rec

    with ThreadPoolExecutor(len(URLS) * len(SETUPS)) as pool:  # every prediction at once
        results = list(pool.map(run, [(p, s) for p in URLS for s in SETUPS]))
    preds = []
    for p, s, j, rec in results:
        preds.append({"product": p, "setup": s, "prediction": j, "error": rec.get("error"), "cost_usd": rec["cost_usd"]})
        if j:
            rows.append({"product": p, "setup": s, **score(j, packs[p]["_actual"])})
    E.write_jsonl(UOUT / "predictions.jsonl", preds)
    E.write_json(UOUT / "actual.json", {p: {"actual": packs[p]["_actual"], "category": cat[p], "competitor_pack_from": packs[p]["_peers"],
                                           "reviews": int(counts[p])} for p in URLS})
    m = pd.DataFrame(rows)
    m.to_csv(UOUT / "metrics.csv", index=False)
    cols = [c for c in m.columns if c not in ("product", "setup")]
    summary = m.groupby("setup")[cols].mean()
    # paired: per product, does each AI setup beat the category-competitor baseline on each metric?
    base = m[m.setup == "BASE_category_competitors"].set_index("product")
    wins = {}
    for s in SETUPS:
        g = m[m.setup == s].set_index("product")
        wins[s] = {c: float(((g[c] > base.loc[g.index, c]) if c == "top_prior_tools_overlap"
                             else (g[c] < base.loc[g.index, c])).mean()) for c in cols}
    summary.to_csv(UOUT / "summary.csv")
    E.write_json(UOUT / "wins_vs_category_baseline.json", wins)
    pd.set_option("display.width", 220)
    print(summary.round(3).to_string())
    print(pd.DataFrame(wins).T.round(2).to_string())
    print(f"errors: {sum(bool(x['error']) for x in preds)}; spend ${E.spent_usd():.3f}")


if __name__ == "__main__":
    main()
