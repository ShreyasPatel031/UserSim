"""REVIEW-TRUTH-1: per-product truth from real Product Hunt reviews, and the homepage-only baseline it must beat.

Reviews (private inputs, read only):
  * verbatim person records (store records/part-*.parquet): every review on a held person's Reviews tab, with
    product slug, date, rating, text, positive / negative feedback, pros, cons;
  * simlab review_text.parquet and the competitor review file (older pulls), merged and de-duplicated.
Reviewer names and ids are never kept: rows carry product slug, date, rating and text only.

Truth per product (reviews dated on or after REVIEW_FROM, the day after Gemini 2.5 Flash's knowledge cutoff):
  * complaints: E5's complaint prompt (complaints_eval.CT), 3 extractions, merged with E5's consensus prompt
    (forward_says.CONS: keep themes present in >= 2 of 3);
  * likes: the same procedure with LIKES_PROMPT, the praise mirror of CT (same wording, critical -> positive);
  * rating: mean overall rating and the number of reviews.
The prompts say "comments on a product launch"; the reviews are passed in their place unchanged.

Baseline: a plain prompt that sees only the product's homepage text (fetched now, time recorded) lists the top
complaints and likes users would have. Scored with E5's CJ (complaints) and JUDGE (likes) judge prompts.
"""
from __future__ import annotations

import html
import json
import re

import pandas as pd

REVIEW_FROM = "2025-01-01"

LIKES_PROMPT = """Below are real user comments on a product launch (makers' own comments removed). Extract ONLY the positive themes:
praise, what users like, benefits they report, and reasons they recommend it. Ignore generic thanks and congratulations.
Return JSON {{"themes": ["<one specific sentence>", ...]}} with at most 6 themes, most frequent first (empty list if none).
Comments:
{c}"""

CONS = """Below are {k} independent extractions of themes from the same set of Product Hunt comments. Return only the themes that appear in at least 2 of the
{k} extractions (treat paraphrases of the same point as the same theme). For each, give one short wording{nfield}. JSON only: {{"themes": [{shape}, ...]}}
{lists}"""

BASELINE = """Here is the homepage text of a software product.
{page}

Predict what real users who have used this product say about it in reviews: the top complaints (problems, missing
features, frustrations) and the top likes (what they praise). JSON only:
{{"complaints": ["<one specific sentence>", ...], "likes": ["<one specific sentence>", ...]}} with at most 6 of each."""

_TAG = re.compile(r"<[^>]+>")
REVIEW_WIDGET = re.compile(r"(\b\d(\.\d)?\s*(out of 5|/ ?5)\b.{0,40}\b(stars?|rating|reviews?)\b|"
                           r"\b(customer|user)?\s*reviews?\b.{0,30}\b(on|from)\s+(product hunt|g2|capterra|trustpilot|app store|google play)\b|"
                           r"\b(read|see) (all|more)? ?reviews\b|\bwhat (our )?(users|customers) (say|are saying)\b|\btestimonials?\b)", re.I)


def clean(t) -> str:
    t = html.unescape(_TAG.sub(" ", str(t or "")))
    t = re.sub(r"@[A-Za-z0-9_.-]+", "@someone", t)
    return " ".join(t.split())


def reviews_from_records(paths: list[str]) -> pd.DataFrame:
    import pyarrow.parquet as pq
    rows = []
    for f in paths:
        for rj in pq.read_table(f, columns=["record_json"]).column(0).to_pylist():
            try:
                d = json.loads(rj)
            except (TypeError, ValueError):
                continue
            recs = [d] + [r for r in (d.get("earlier_records") or []) if isinstance(r, dict)]
            for r in recs:
                rv = r.get("reviews") or {}
                if not isinstance(rv, dict):
                    continue
                for it in (rv.get("items") or []) + (rv.get("items_earlier") or []):
                    if not isinstance(it, dict):
                        continue
                    slug = it.get("product") or ""
                    m = re.search(r"/products/([^/?#]+)", str(it.get("url") or ""))
                    if m:
                        slug = m.group(1)
                    parts = [it.get("text"), it.get("positive"), it.get("negative")]
                    pros = it.get("pros") if isinstance(it.get("pros"), list) else []
                    cons = it.get("cons") if isinstance(it.get("cons"), list) else []
                    body = " ".join(clean(p) for p in parts if p)
                    if pros:
                        body += " Pros: " + ", ".join(map(str, pros)) + "."
                    if cons:
                        body += " Cons: " + ", ".join(map(str, cons)) + "."
                    rows.append({"review_key": f"rec:{it.get('review_id')}", "product": slug, "date": str(it.get("date") or "")[:10],
                                 "rating": it.get("rating"), "text": body.strip(), "source": "records"})
    return pd.DataFrame(rows)


def reviews_from_older(review_text_path: str | None, competitor_path: str | None) -> pd.DataFrame:
    import gzip
    rows = []
    if review_text_path:
        t = pd.read_parquet(review_text_path)
        for r in t.itertuples():
            body = " ".join(clean(x) for x in (r.text, r.pros, r.cons) if isinstance(x, str) and x)
            rows.append({"review_key": None, "product": r.product, "date": str(r.date)[:10], "rating": r.rating, "text": body,
                         "source": "simlab_review_text"})
    if competitor_path:
        for line in gzip.open(competitor_path, "rt"):
            x = json.loads(line)
            for rv in x.get("reviews") or []:
                body = " ".join(clean(v) for v in (rv.get("text"), rv.get("pros"), rv.get("cons")) if isinstance(v, str) and v)
                rows.append({"review_key": None, "product": rv.get("product") or x.get("slug"), "date": str(rv.get("date") or "")[:10],
                             "rating": rv.get("rating"), "text": body, "source": "competitor_reviews"})
    return pd.DataFrame(rows)


def merge_reviews(frames: list[pd.DataFrame]) -> pd.DataFrame:
    r = pd.concat(frames, ignore_index=True)
    r["rating"] = pd.to_numeric(r["rating"], errors="coerce")
    r = r[r["text"].str.len() >= 20]
    r["norm"] = r["text"].str.lower().str.replace(r"[^a-z0-9]+", "", regex=True).str[:80]
    order = {"records": 0, "simlab_review_text": 1, "competitor_reviews": 2}
    r = r.assign(o=r["source"].map(order)).sort_values("o")
    r = r.drop_duplicates(["product", "norm"]).drop(columns=["o", "norm"])
    return r.reset_index(drop=True)
