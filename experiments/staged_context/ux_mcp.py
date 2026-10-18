"""Product-experience package for any product URL + person, and the per-output strategy router.

    build_package(url, person, exclude_product=None) -> data sections + numeric estimates
    respond(url, person)                              -> what the MCP tool returns, per output, following ROUTER

The router (router.json, written by router_eval.py) says, for each output, which strategy won on dev products:
  averages        return the people-like-them estimate as the answer
  blend           return the estimate; the agent averages it with its own package-informed guess
  agent_full      give the agent the full package (averages + competitors + similar people's reviews)
  agent_averages  give the agent only the averages section
  agent_alone     return nothing for this output
"""

from __future__ import annotations

import json
import re
import sys
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import experiment as E  # noqa: E402
import predictability as PR  # noqa: E402

RATINGS = {"ease_of_use_rating": (1, 5), "functionality_rating": (1, 5), "overall_rating": (1, 5),
           "value_for_money_rating": (1, 5), "customer_support_rating": (1, 5), "recommendation_score": (0, 10)}
FEATS = {"role_family": "role_family", "company_size": "reviewer_company_size",
         "time_used": "reviewer_time_used_product", "industry": "reviewer_industry"}
ROUTER_PATH = E.OUT / "router" / "router.json"
SHRINK = 20.0


@lru_cache(maxsize=1)
def data() -> pd.DataFrame:
    df, _ = E.load_capterra()
    df["role_family"] = df.reviewer_job_title.fillna("").map(E.role_family)
    return df


CATEGORIES = None


def categories() -> list[str]:
    return sorted(data().product_category_group.unique())


def recorded_category(url: str) -> str | None:
    """Category router_eval recorded for a known product URL (pages change, so re-fetching would miss the call cache)."""
    import router_eval as RE  # noqa: PLC0415

    rec = E.read_json(E.OUT / "router" / "category_check.json")
    name = next((p for p, u in RE.URLS.items() if u == url), None)
    return (rec.get(name) or {}).get("classified") if name else None


def classify(url: str) -> dict:
    """Fetch the product page and map it to a Capterra category with the model (cached)."""
    known = recorded_category(url)
    if known:
        return {"category": known, "product_name": None, "page_text": ""}
    dest = E.CACHE / "pages" / f"mcp_{E.sha(url)[:12]}.html"
    E.download(url, dest)
    sents, _ = E.filter_sentences(E.page_text(dest.read_text(encoding="utf-8", errors="ignore")))
    text = " ".join(sents)[:6000]
    rec = E.call_model("mcp_classify", "gemini-2.5-flash", "You classify software products. Return JSON only.",
                       f"Product page ({url}):\n{text}\n\nWhich one category fits best? Options: {categories()}\n"
                       'Return {"category": one of the options, "product_name": str}',
                       temperature=0.0, seed=42, max_tokens=2048, thinking_budget=256)
    j = rec.get("json") if isinstance(rec.get("json"), dict) else {}
    cat = j.get("category") if j.get("category") in categories() else None
    return {"category": cat, "product_name": j.get("product_name"), "page_text": text}


def people_like_them(person: dict, exclude: str | None) -> dict:
    df = data()
    others = df[df.product_name != exclude] if exclude else df
    out = {"estimates": {}, "lines": []}
    for r, (lo, hi) in RATINGS.items():
        col = others[r]
        mu = col.mean()
        dev, parts = 0.0, []
        for key, fcol in FEATS.items():
            v = person.get(key)
            g = others.loc[others[fcol] == v, r].dropna()
            if len(g):
                dev += (g.sum() + SHRINK * mu) / (len(g) + SHRINK) - mu
                parts.append(f"{key} '{v}': {g.mean():.2f} (n={len(g)})")
        est = float(np.clip(mu + dev, lo, hi))
        out["estimates"][r] = est
        out["lines"].append(f"- {r}: all reviewers {mu:.2f}; " + "; ".join(parts) + f"; combined estimate {est:.2f}")
    unhappy = (others.overall_rating <= 3) | (others.recommendation_score <= 6)
    for key, fcol in FEATS.items():
        m = others[fcol] == person.get(key)
        if m.any():
            out["lines"].append(f"- unhappy share (overall<=3 or recommend<=6) for {key} '{person.get(key)}': "
                                f"{unhappy[m].mean():.1%} vs {unhappy.mean():.1%} overall")
    return out


def competitors(category: str | None, exclude: str | None) -> pd.DataFrame:
    df = data()
    comp = df[df.product_category_group == category] if category else df
    return comp[comp.product_name != exclude] if exclude else comp


def competitor_section(comp: pd.DataFrame) -> str:
    cons = comp.cons.fillna("").str.lower()
    topics = "\n".join(f"- {k.replace('complaint_', '')}: {cons.str.contains(p, regex=True).mean():.1%} mention it"
                       for k, p in PR.TOPICS.items())
    ratings = "; ".join(f"{r} {comp[r].mean():.2f}" for r in RATINGS)
    return (f"Competitors: {', '.join(sorted(comp.product_name.unique()))} ({len(comp)} reviews).\n"
            f"Average ratings: {ratings}\nComplaint topics in their cons:\n{topics}")


def similar_reviews(person: dict, comp: pd.DataFrame, k: int = 8, mask: str | None = None) -> str:
    pool = comp[comp.pros.notna()]
    s = (3 * (pool.role_family == person.get("role_family")) + 2 * (pool.reviewer_company_size == person.get("company_size"))
         + (pool.reviewer_time_used_product == person.get("time_used")) + (pool.reviewer_industry == person.get("industry")))
    tie = pool.review_id.map(lambda i: E.sha(f"42|sim|{json.dumps(person, sort_keys=True)}|{i}"))
    top = pool.assign(_s=s, _t=tie).sort_values(["_s", "_t"], ascending=[False, True]).head(k)
    out = []
    for r in top.to_dict("records"):
        r = {kk: (None if isinstance(v, float) and np.isnan(v) else v) for kk, v in r.items()}
        text, _ = E.format_review(r, mask)
        out.append(f"[{r['product_name']}]\n{text}")
    return "\n\n".join(out)


def build_package(url: str, person: dict, exclude_product: str | None = None, mask: str | None = None) -> dict:
    """exclude_product: drop the product's own reviews (evaluation / truly new product)."""
    cl = classify(url)
    comp = competitors(cl["category"], exclude_product)
    plt = people_like_them(person, exclude_product)
    return {"category": cl["category"], "estimates": plt["estimates"],
            "sections": {"averages": "## People like this person (other software products)\n" + "\n".join(plt["lines"]),
                         "competitors": "## Same-category competitors\n" + competitor_section(comp),
                         "similar_reviews": "## Reviews of competitor products by the most similar people\n"
                                            + similar_reviews(person, comp, mask=mask)}}


def respond(url: str, person: dict, exclude_product: str | None = None) -> dict:
    """The MCP tool response: per output, the data or estimate the router picked for it."""
    router = E.read_json(ROUTER_PATH)
    pkg = build_package(url, person, exclude_product)
    full = "\n\n".join(pkg["sections"].values())
    out = {"category": pkg["category"], "outputs": {}}
    for name, strat in router["strategy"].items():
        if strat == "averages" and name in pkg["estimates"]:
            out["outputs"][name] = {"strategy": strat, "estimate": round(pkg["estimates"][name], 2),
                                    "instruction": "Use this estimate as the prediction."}
        elif strat == "blend" and name in pkg["estimates"]:
            out["outputs"][name] = {"strategy": strat, "estimate": round(pkg["estimates"][name], 2),
                                    "instruction": "Predict using the context, then report the mean of your number and this estimate.",
                                    "context": full}
        elif strat == "agent_full":
            out["outputs"][name] = {"strategy": strat, "instruction": "Predict using this context.", "context": full}
        elif strat == "agent_averages":
            out["outputs"][name] = {"strategy": strat, "instruction": "Predict using this context.",
                                    "context": pkg["sections"]["averages"]}
        else:
            out["outputs"][name] = {"strategy": "agent_alone", "instruction": "No data improves this output; use your own judgement."}
    if "unhappy_risk" in router.get("risk", {}):
        r = router["risk"]["unhappy_risk"]
        est = pkg["estimates"]
        risk = {"strategy": r, "note": "likelihood the person rates overall<=3 or recommend<=6"}
        if r == "averages":
            risk["score"] = round(5 - est["overall_rating"] + (10 - est["recommendation_score"]) / 2, 3)
        else:
            risk["instruction"] = "Judge this from the context; low predicted overall/recommend means higher risk."
            risk["context"] = full if r == "agent_full" else pkg["sections"]["averages"]
        out["outputs"]["unhappy_risk"] = risk
    return out


def mask_for(product: str) -> str:
    return rf"\b{re.escape(product.split()[0].lower())}\b"
