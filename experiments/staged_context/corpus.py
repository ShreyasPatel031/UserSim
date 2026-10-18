"""Capterra + G2 in one frame, and package sections built from either source or both.

Common fields: source, product, category, role_family, size3 (G2's three bands; Capterra bands mapped), industry,
overall_rating, pros, cons. Capterra-only: size_fine, time_used, the other five ratings.
G2 products are mapped to Capterra categories by name (one model call, cached); 0.0 G2 stars are treated as missing.
"""

from __future__ import annotations

import json
import sys
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import experiment as E  # noqa: E402
import predictability as PR  # noqa: E402
import ux_mcp as U  # noqa: E402

G2_FILE = E.CACHE / "g2" / "g2_reviews.csv"
G2_REV = "d8a82cb52bbc95554bf7095148bae1becbdbb4e4"
SIZE3 = {"Self-employed": "Small-Business (50 or fewer emp.)", "1-10 employees": "Small-Business (50 or fewer emp.)",
         "11-50 employees": "Small-Business (50 or fewer emp.)", "51-200 employees": "Mid-Market (51-1000 emp.)",
         "201-500 employees": "Mid-Market (51-1000 emp.)", "501-1,000 employees": "Mid-Market (51-1000 emp.)",
         "1,001-5,000 employees": "Enterprise (> 1000 emp.)", "5,001-10,000 employees": "Enterprise (> 1000 emp.)",
         "10,001+ employees": "Enterprise (> 1000 emp.)"}
CAP_ONLY_RATINGS = [r for r in U.RATINGS if r != "overall_rating"]


def g2_categories(names: list[str]) -> dict:
    cats = U.categories() + ["Other"]
    rec = E.call_model("g2_categorize", "gemini-2.5-flash", "You classify software products. Return JSON only.",
                       f"Assign each product to one category from {cats}.\nProducts: {json.dumps(sorted(names))}\n"
                       'Return {"<product>": "<category>", ...}', temperature=0.0, seed=42, max_tokens=8192,
                       thinking_budget=512)
    j = rec.get("json") if isinstance(rec.get("json"), dict) else {}
    return {n: (j.get(n) if j.get(n) in cats else "Other") for n in names}


@lru_cache(maxsize=1)
def corpus() -> pd.DataFrame:
    c = U.data().copy()
    cap = pd.DataFrame({
        "source": "capterra", "rid": "C:" + c.review_id.astype(str), "product": c.product_name,
        "category": c.product_category_group, "role_family": c.role_family, "size_fine": c.reviewer_company_size,
        "size3": c.reviewer_company_size.map(SIZE3), "time_used": c.reviewer_time_used_product,
        "industry": c.reviewer_industry, "pros": c.pros, "cons": c.cons, **{r: c[r] for r in U.RATINGS}})
    E.download(f"https://huggingface.co/datasets/FreshCrawl/g2-software-reviews/resolve/{G2_REV}/g2_reviews.csv", G2_FILE)
    g = pd.read_csv(G2_FILE, low_memory=False)
    cat = g2_categories(sorted(g.product_name.unique()))
    # Capterra name for products both sites carry, so either source's copy is excluded when it is the target
    g2 = pd.DataFrame({
        "source": "g2", "rid": "G:" + g.review_id.astype(str), "product": g.product_name, "category": g.product_name.map(cat),
        "role_family": g.reviewer_title.fillna("").map(E.role_family), "size_fine": None, "size3": g.reviewer_company_size,
        "time_used": None, "industry": g.reviewer_industry, "pros": g.likes, "cons": g.dislikes,
        "overall_rating": g.star_rating.where(g.star_rating > 0),
        "title": g.reviewer_title, "problems_solved": g.problems_solved, "review_text": g.review_text,
        "structured": g.has_structured_split})
    for r in CAP_ONLY_RATINGS:
        g2[r] = np.nan
    return pd.concat([cap, g2], ignore_index=True)


def _attrs(source: str, person: dict) -> list[str]:
    if source == "g2":
        return ["role_family", "size3", "industry"]
    size = "size_fine" if person.get("size_fine") else "size3"  # G2 people only carry the three-band size
    return ["role_family", size, "time_used", "industry"]


@lru_cache(maxsize=None)
def _sums(src: str, attr: str | None, r: str):
    """sum/count of rating r per (attr value, product) for one source; attr None = per product only."""
    d = corpus()
    d = d[(d.source == src) & d[r].notna()]
    keys = ["product"] if attr is None else [attr, "product"]
    return d.groupby(keys)[r].agg(["sum", "count"])


def _stat(src, attr, value, r, exclude):
    t = _sums(src, attr, r)
    if attr is None:
        s_, n_ = t["sum"].sum(), t["count"].sum()
        if exclude in t.index:
            s_, n_ = s_ - t.loc[exclude, "sum"], n_ - t.loc[exclude, "count"]
        return s_, n_
    if value not in t.index.get_level_values(0):
        return 0.0, 0
    g = t.loc[value]
    s_, n_ = g["sum"].sum(), g["count"].sum()
    if exclude in g.index:
        s_, n_ = s_ - g.loc[exclude, "sum"], n_ - g.loc[exclude, "count"]
    return s_, n_


def estimates(person: dict, sources: set[str], exclude: str | None) -> tuple[dict, list[str]]:
    """Shrunk people-like-them estimate per rating, per source; merged = review-count-weighted mean of the sources."""
    per, lines = {}, []
    for src in sorted(sources):
        for r, (lo, hi) in U.RATINGS.items():
            s_all, n_all = _stat(src, None, None, r, exclude)
            if not n_all:
                continue
            mu, dev, parts = s_all / n_all, 0.0, []
            for a in _attrs(src, person):
                v = person.get(a)
                if v is None:
                    continue
                s_, n_ = _stat(src, a, v, r, exclude)
                if n_:
                    dev += (s_ + U.SHRINK * mu) / (n_ + U.SHRINK) - mu
                    parts.append(f"{a} '{v}': {s_ / n_:.2f} (n={int(n_)})")
            est = float(np.clip(mu + dev, lo, hi))
            per.setdefault(r, []).append((est, n_all))
            lines.append(f"- [{src}] {r}: all reviewers {mu:.2f}; " + "; ".join(parts) + f"; combined estimate {est:.2f}")
    est = {r: float(sum(e * n for e, n in v) / sum(n for _, n in v)) for r, v in per.items()}
    return est, lines


def sections(person: dict, category: str | None, sources: set[str], exclude: str | None, mask: str | None) -> dict:
    df = corpus()
    df = df[df.source.isin(sources)]
    est, lines = estimates(person, sources, exclude)
    comp = df[(df.category == category) & (df["product"] != exclude)] if category else df[df["product"] != exclude]
    cons = comp.cons.fillna("").str.lower()
    cons = cons[cons != ""]
    topics = "\n".join(f"- {k.replace('complaint_', '')}: {cons.str.contains(p, regex=True).mean():.1%} mention it"
                       for k, p in PR.TOPICS.items())
    rat = "; ".join(f"{r} {comp[r].mean():.2f}" for r in U.RATINGS if comp[r].notna().any())
    pool = comp[comp.pros.notna() & comp.cons.notna()]
    score = (3 * (pool.role_family == person.get("role_family"))
             + 2 * ((pool.size_fine == person.get("size_fine")) | (pool.size3 == person.get("size3")))
             + (pool.time_used == person.get("time_used")) + (pool.industry == person.get("industry")))
    # hash only the rows tied at or above the 8th-best score (hashing every candidate was the bottleneck)
    cut = score.nlargest(8).min() if len(score) else 0
    cand = pool[score >= cut].assign(_s=score[score >= cut])
    key = json.dumps(person, sort_keys=True, default=str)
    cand = cand.assign(_t=cand.rid.map(lambda i: E.sha(f"42|corp|{key}|{i}")))
    top = cand.sort_values(["_s", "_t"], ascending=[False, True]).head(8)
    revs = []
    for r in top.to_dict("records"):
        fields = [("Source", r["source"]), ("Role family", r["role_family"]), ("Company size", r["size_fine"] or r["size3"]),
                  ("Time used", r["time_used"]), ("Overall rating", r["overall_rating"]), ("Liked", r["pros"]), ("Disliked", r["cons"])]
        text = "\n".join(f"{k}: {E.clean(v)}" for k, v in fields if E.clean(v) and E.clean(v) != "nan")
        if mask:
            import re
            text = re.sub(mask, "[target product]", text, flags=re.I)
        revs.append(f"[{r['product']}]\n{text[:1000]}")
    src_label = " + ".join(sorted(sources))
    return {"estimates": est, "sections": {
        "averages": f"## People like this person (other software products; {src_label})\n" + "\n".join(lines),
        "competitors": f"## Same-category competitors ({src_label}): {', '.join(sorted(comp['product'].unique())[:25])}"
                       f" ({len(comp)} reviews)\nAverage ratings: {rat}\nComplaint topics in their cons:\n{topics}",
        "similar_reviews": "## Reviews of competitor products by the most similar people\n" + "\n\n".join(revs)}}
