"""Launch categories, competitor sets and the structural model's miss by category (CATEGORY-1).

Inputs (private; paths passed in):
  similar      Product Hunt "Similar Products" per launch (JSON lines: launch_id, launch_slug, product_slug, launch_day,
               fetched_at, similar_products[{name, slug, tagline, url, rating, reviews_count, no_longer_online,
               categories[]}]). Every similar product carries Product Hunt's own categories for that product.
  taxonomy     category names with descriptions (JSON lines: group, name, description); partial list
  items        launch table (item_id, day, title, summary, description, tags) and item_keys (item_id, slug)

Launch -> category, in priority order:
  (a) ph_own            the launch's own product appears somewhere as a Similar Product: its Product Hunt categories
  (b) similar_majority  the categories of its Similar Products, counted; primary = most frequent, share = count / n
  (c) embedding         a bge-small classifier on name + tagline + description + topics: nearest category, where a
                        category is represented by its name + description and, when training launches are given, the
                        mean embedding of launches labelled with it before a cut-off date
Every launch gets (c) as well, because (c) is the only label knowable at 00:05 PT for a new launch.

Leak notes: Similar Products were read on Nov 1 2026, after most launches. The list (and the reviews counts) can
reflect what became popular later; labels from (a) / (b) are therefore not "known at 00:05" for past days.
"""
from __future__ import annotations

import json
import re
from collections import Counter

import numpy as np
import pandas as pd


# ------------------------------------------------------------------------------------------------ loading
def load_similar(path: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(launches, products). launches: one row per launch; products: one row per similar-product slug with its
    categories (the most frequent category list seen for that slug), reviews, rating, no_longer_online."""
    rows, prods = [], {}
    for line in open(path):
        r = json.loads(line)
        sims = r.get("similar_products") or []
        rows.append({"launch_id": str(r.get("launch_id")), "launch_slug": r.get("launch_slug") or "",
                     "product_slug": r.get("product_slug") or "", "launch_day": r.get("launch_day"),
                     "fetched_at": r.get("fetched_at"), "status": r.get("status"),
                     "similar": [x.get("slug") for x in sims if x.get("slug")]})
        for x in sims:
            s = x.get("slug")
            if not s:
                continue
            p = prods.setdefault(s, {"slug": s, "name": x.get("name"), "tagline": x.get("tagline"), "url": x.get("url"),
                                     "cat_lists": Counter(), "reviews_count": 0, "rating": None,
                                     "no_longer_online": False, "seen": 0})
            p["cat_lists"][tuple(x.get("categories") or [])] += 1
            p["reviews_count"] = max(p["reviews_count"], int(x.get("reviews_count") or 0))
            p["rating"] = x.get("rating") if x.get("rating") is not None else p["rating"]
            p["no_longer_online"] = p["no_longer_online"] or bool(x.get("no_longer_online"))
            p["seen"] += 1
    launches = pd.DataFrame(rows)
    for p in prods.values():
        p["categories"] = list(p.pop("cat_lists").most_common(1)[0][0])
    products = pd.DataFrame(list(prods.values()))
    return launches, products


def load_taxonomy(path: str) -> pd.DataFrame:
    return pd.DataFrame([json.loads(l) for l in open(path) if l.strip()])


def launch_text(row) -> str:
    desc = " ".join(str(row.description or "").split())[:600]
    tags = ", ".join(list(row.tags)[:6]) if row.tags is not None else ""
    return f"{row.title}. {row.summary}. {desc} Topics: {tags}".strip()


# ------------------------------------------------------------------------------------------------ (a) and (b)
def own_and_majority(launches: pd.DataFrame, products: pd.DataFrame) -> pd.DataFrame:
    """Per launch: own categories (a), majority category with share and full counts (b)."""
    cats = dict(zip(products["slug"], products["categories"]))
    out = []
    for r in launches.itertuples():
        own = cats.get(r.product_slug) or cats.get(r.launch_slug) or []
        cnt = Counter(c for s in r.similar for c in (cats.get(s) or []))
        n = len(r.similar)
        top = cnt.most_common()
        maj = top[0][0] if top else None
        out.append({"launch_id": r.launch_id, "own_categories": list(own), "n_similar": n,
                    "majority": maj, "majority_share": round(top[0][1] / n, 3) if top and n else None,
                    "majority_counts": json.dumps(dict(top[:6]))})
    return pd.DataFrame(out)


def primary_category(own: list, counts: dict, majority: str | None) -> tuple[str | None, str]:
    """(a) first: among the product's own categories the one its Similar Products share most; else (b)."""
    if own:
        best = max(own, key=lambda c: (counts.get(c, 0), -own.index(c)))
        return best, "ph_own"
    if majority:
        return majority, "similar_majority"
    return None, "none"


# ------------------------------------------------------------------------------------------------ (c)
class CategoryEmbedder:
    """Nearest-category classifier on bge-small embeddings.

    zero-shot: a category is "Category: <name>. <description>" (description only for the pasted categories).
    centroid:  alpha * name/description vector + (1 - alpha) * mean of training launches labelled with the category
               (training launches must all be dated before the launches it is applied to, for a fair validation)."""

    def __init__(self, categories: list[str], descriptions: dict, model: str = "BAAI/bge-small-en-v1.5"):
        from sentence_transformers import SentenceTransformer
        self.m = SentenceTransformer(model, device="cpu")
        self.categories = list(categories)
        texts = [f"Category: {c}. {descriptions.get(c, '')}".strip() for c in self.categories]
        self.C0 = self.encode(texts)
        self.C = self.C0.copy()

    def encode(self, texts: list[str]) -> np.ndarray:
        return np.asarray(self.m.encode(texts, batch_size=64, normalize_embeddings=True, show_progress_bar=False),
                          dtype=np.float32)

    def fit_centroids(self, X: np.ndarray, labels: list[str], alpha: float = 0.3, min_n: int = 1) -> "CategoryEmbedder":
        C = self.C0.copy()
        idx = {c: i for i, c in enumerate(self.categories)}
        lab = np.array([idx.get(l, -1) for l in labels])
        for i in range(len(self.categories)):
            m = lab == i
            if m.sum() >= min_n:
                mu = X[m].mean(0)
                v = alpha * self.C0[i] + (1 - alpha) * mu / (np.linalg.norm(mu) + 1e-9)
                C[i] = v / (np.linalg.norm(v) + 1e-9)
        self.C = C
        return self

    def scores(self, X: np.ndarray) -> np.ndarray:
        return X @ self.C.T

    def topk(self, X: np.ndarray, k: int = 3) -> tuple[list[list[str]], np.ndarray]:
        S = self.scores(X)
        o = np.argsort(-S, axis=1)[:, :k]
        return [[self.categories[j] for j in row] for row in o], np.take_along_axis(S, o, axis=1)


def day_bootstrap_mean(values: np.ndarray, days: np.ndarray, n_boot: int = 2000, seed: int = 0) -> dict:
    """Mean with a 95% interval from resampling days (clusters)."""
    v = np.asarray(values, dtype=float)
    names, inv = np.unique(days, return_inverse=True)
    s = np.bincount(inv, weights=v, minlength=len(names))
    c = np.bincount(inv, minlength=len(names)).astype(float)
    rng = np.random.default_rng(seed)
    bs = []
    for _ in range(n_boot):
        k = rng.integers(0, len(names), len(names))
        bs.append(s[k].sum() / max(c[k].sum(), 1.0))
    lo, hi = np.percentile(bs, [2.5, 97.5])
    return {"value": round(float(v.mean()), 4) if len(v) else None, "ci95": [round(float(lo), 4), round(float(hi), 4)],
            "n": int(len(v)), "days": int(len(names))}


# ------------------------------------------------------------------------------------------------ competitors
def competitor_set(launch_cats: list[str], primary: str | None, similar: list[str], own_slugs: set,
                   products: pd.DataFrame, by_cat_top: dict, k: int = 5) -> list[dict]:
    """PH Similar Products sharing a category with the launch (in PH's order), then the most-reviewed products of the
    primary category; products marked no_longer_online and the launch's own product are dropped."""
    P = products
    out, seen = [], set(own_slugs)
    lc = set(launch_cats)
    for s in similar:
        if s in seen or s not in P.index:
            continue
        p = P.loc[s]
        if p.no_longer_online:
            continue
        shared = sorted(lc & set(p.categories))
        if shared:
            out.append({"slug": s, "name": p["name"], "tagline": p.tagline, "url": p.url,
                        "reviews_count": int(p.reviews_count), "rating": p.rating, "categories": list(p.categories),
                        "shared_categories": shared, "source": "ph_similar_shared_category"})
            seen.add(s)
        if len(out) >= k:
            return out
    for s in by_cat_top.get(primary, []):
        if len(out) >= k:
            break
        if s in seen:
            continue
        p = P.loc[s]
        out.append({"slug": s, "name": p["name"], "tagline": p.tagline, "url": p.url,
                    "reviews_count": int(p.reviews_count), "rating": p.rating, "categories": list(p.categories),
                    "shared_categories": [primary], "source": "category_most_reviewed"})
        seen.add(s)
    return out


def category_top_reviewed(products: pd.DataFrame, per_cat: int = 30) -> dict:
    """category -> product slugs by reviews_count (online products only)."""
    P = products[~products["no_longer_online"].astype(bool)]
    out = {}
    for c, g in P.explode("categories").dropna(subset=["categories"]).groupby("categories"):
        out[c] = g.sort_values(["reviews_count", "seen"], ascending=False)["slug"].head(per_cat).tolist()
    return out


def norm_slug(s: str) -> str:
    return re.sub(r"-\d+$", "", str(s or ""))
