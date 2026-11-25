"""REVIEW-TRUTH-1 runner (see simharness/review_truth.py).

  python -m simharness.run_review_truth STAGE --work W --judge-src SIMLAB_DIR [--sync gs://...]
  stages: reviews (needs --records-glob --review-text --competitor-reviews), urls, fetch, truth, baseline, score, coverage

W holds review text and homepage text: private. Every model call is cached in W/llm_cache.jsonl (resumable).
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import glob
import hashlib
import json
import os
import re
import subprocess
import threading

import numpy as np
import pandas as pd

from simharness import review_truth as rt
from simharness.run_what_panel4 import USAGE, gemini, usd

_lk = threading.Lock()
MAX_REVIEWS = 40


def sync(paths, dest):
    if dest and paths:
        subprocess.run(["gsutil", "-q", "-m", "cp", *paths, dest.rstrip("/") + "/"], check=False)


class Cache:
    def __init__(self, path):
        self.path, self.d = path, {}
        if os.path.exists(path):
            for l in open(path):
                try:
                    x = json.loads(l)
                    self.d[x["k"]] = x["v"]
                except ValueError:
                    pass
        self.f = open(path, "a")

    def get(self, key, fn):
        if key in self.d:
            return self.d[key]
        v = fn()
        with _lk:
            self.d[key] = v
            self.f.write(json.dumps({"k": key, "v": v}) + "\n")
            self.f.flush()
        return v


def g(prompt, mt):
    try:
        return json.loads(gemini(prompt, mt, 0.0))
    except Exception:  # noqa: BLE001
        return None


# ------------------------------------------------------------------------------------------------ reviews
def stage_reviews(a):
    recs = rt.reviews_from_records(sorted(glob.glob(a.records_glob)))
    old = rt.reviews_from_older(a.review_text, a.competitor_reviews)
    R = rt.merge_reviews([recs, old])
    R[["product", "date", "rating", "text", "source"]].to_parquet(f"{a.work}/reviews_all.parquet")
    print(len(R), R["source"].value_counts().to_dict())


# ------------------------------------------------------------------------------------------------ fetch
def _visible_text(html_text: str) -> str:
    t = re.sub(r"(?is)<(script|style|noscript|svg|template)[^>]*>.*?</\1>", " ", html_text)
    t = re.sub(r"(?is)<!--.*?-->", " ", t)
    return rt.clean(t)


def stage_fetch(a):
    import httpx
    U = pd.read_parquet(f"{a.work}/products_urls.parquet")
    U = U[U["url"].notna()]
    R = pd.read_parquet(f"{a.work}/reviews_all.parquet")
    R = R[R["date"] >= rt.REVIEW_FROM]
    shingles = {}
    for p, grp in R.groupby("product"):
        s = set()
        for t in grp["text"]:
            w = re.findall(r"[a-z0-9']+", t.lower())
            s |= {" ".join(w[i:i + 8]) for i in range(max(len(w) - 7, 0))}
        shingles[p] = s

    def one(r):
        out = {"product": r.product, "url": r.url, "url_source": r.url_source,
               "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
        try:
            resp = httpx.get(r.url, follow_redirects=True, timeout=20,
                             headers={"User-Agent": "Mozilla/5.0 (compatible; research-fetch/1.0)", "Accept-Language": "en"})
            final = str(resp.url)
            out.update(status=resp.status_code, final_url=final)
            if "producthunt.com" in final:
                out.update(text="", drop="redirected_to_producthunt")
                return out
            text = _visible_text(resp.text)[:6000]
            out["text"] = text
            w = re.findall(r"[a-z0-9']+", text.lower())
            sh = {" ".join(w[i:i + 8]) for i in range(max(len(w) - 7, 0))}
            overlap = len(sh & shingles.get(r.product, set()))
            out["review_shingle_overlap"] = overlap
            widget = rt.REVIEW_WIDGET.search(text)
            out["review_widget_match"] = widget.group(0)[:80] if widget else None
            out["drop"] = ("http_error" if resp.status_code >= 400 else "too_short" if len(text) < 200 else
                           "quotes_a_review" if overlap > 0 else "review_widget" if widget else None)
        except Exception as e:  # noqa: BLE001
            out.update(status=-1, text="", drop="fetch_error:" + type(e).__name__)
        return out

    with cf.ThreadPoolExecutor(16) as ex:
        rows = list(ex.map(one, list(U.itertuples())))
    F = pd.DataFrame(rows)
    F.to_parquet(f"{a.work}/homepages.parquet")
    print(F["drop"].fillna("kept").value_counts().to_dict())
    sync([f"{a.work}/homepages.parquet"], a.sync)


# ------------------------------------------------------------------------------------------------ truth
def _prompts(a):
    RE = open(os.path.join(a.judge_src, "reactions_eval.py")).read()
    CE = open(os.path.join(a.judge_src, "complaints_eval.py")).read()
    CT = re.search(r'CT = """(.*?)"""', CE, re.S).group(1)
    CJ = re.search(r'CJ = """(.*?)"""', CE, re.S).group(1)
    JUDGE = re.search(r'JUDGE = """(.*?)"""', RE, re.S).group(1)
    return CT, CJ, JUDGE


def stage_truth(a):
    CT, _, _ = _prompts(a)
    R = pd.read_parquet(f"{a.work}/reviews_all.parquet")
    R = R[R["date"] >= rt.REVIEW_FROM].sort_values("date", ascending=False)
    n = R.groupby("product").size()
    prods = sorted(n[n >= 5].index)
    if a.limit:
        prods = prods[: a.limit]
    cache = Cache(f"{a.work}/llm_cache.jsonl")

    def consensus(kind, prompt_tmpl, c, p):
        ex = [[str(t) for t in ((cache.get(f"{kind}|{p}|{i}", lambda: g(prompt_tmpl.format(c=c), 1200)) or {}).get("themes") or [])][:6]
              for i in range(3)]
        if not any(ex):
            return [], ex
        lists = "\n".join(f"Extraction {i + 1}:\n" + "\n".join(f"- {t}" for t in e) for i, e in enumerate(ex))
        m = cache.get(f"{kind}_cons|{p}", lambda: g(rt.CONS.format(k=3, nfield="", shape='{"theme": "..."}', lists=lists), 1200))
        th = [str(t.get("theme") if isinstance(t, dict) else t) for t in ((m or {}).get("themes") or [])][:6]
        return th, ex

    def one(p):
        grp = R[R["product"] == p].head(MAX_REVIEWS)
        c = "\n".join(f"- {t[:400]}" for t in grp["text"])
        comp, exc = consensus("complaints", CT, c, p)
        likes, exl = consensus("likes", rt.LIKES_PROMPT, c, p)
        rating = pd.to_numeric(grp["rating"], errors="coerce")
        return {"product": p, "n_reviews_2025": int(n[p]), "n_reviews_used": int(len(grp)),
                "first_review": grp["date"].min(), "last_review": grp["date"].max(),
                "rating_mean": float(rating.mean()) if rating.notna().any() else None, "n_rated": int(rating.notna().sum()),
                "complaints": comp, "likes": likes, "complaint_extractions": json.dumps(exc), "like_extractions": json.dumps(exl)}

    with cf.ThreadPoolExecutor(10) as ex:
        rows = list(ex.map(one, prods))
    T = pd.DataFrame(rows)
    T["frozen_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    T.to_parquet(f"{a.work}/review_truth.parquet")
    print("products", len(T), "with complaints", int((T["complaints"].map(len) > 0).sum()), "with likes",
          int((T["likes"].map(len) > 0).sum()), "usd", usd())
    sync([f"{a.work}/review_truth.parquet", f"{a.work}/llm_cache.jsonl"], a.sync)


# ------------------------------------------------------------------------------------------------ baseline + score
def stage_baseline(a):
    _, CJ, JUDGE = _prompts(a)
    T = pd.read_parquet(f"{a.work}/review_truth.parquet").set_index("product")
    F = pd.read_parquet(f"{a.work}/homepages.parquet")
    F = F[F["drop"].isna() & F["product"].isin(T.index)]
    cache = Cache(f"{a.work}/llm_cache.jsonl")

    def one(r):
        page = r.text[:3000]
        pred = cache.get(f"baseline|{r.product}", lambda: g(rt.BASELINE.format(page=page), 1200)) or {}
        pc = [str(x) for x in (pred.get("complaints") or [])][:6]
        pl = [str(x) for x in (pred.get("likes") or [])][:6]
        tc, tl = list(T.loc[r.product, "complaints"]), list(T.loc[r.product, "likes"])
        out = {"product": r.product, "n_pred_complaints": len(pc), "n_pred_likes": len(pl)}
        runs = []
        for k in range(3):
            x = {}
            if tc and pc:
                j = cache.get(f"cj|{r.product}|{k}", lambda: g(CJ.format(a="\n".join(f"{i + 1}. {t}" for i, t in enumerate(tc)),
                                                                     b="\n".join(f"{i + 1}. {t}" for i, t in enumerate(pc))), 1200))
                if j and len(j.get("a_covered", [])) == len(tc):
                    x["complaint_recall"] = float(np.mean([bool(v) for v in j["a_covered"]]))
                    bm = j.get("b_matches", [])[:len(pc)]
                    if bm:
                        x["complaint_precision"] = float(np.mean([bool(v) for v in bm]))
            if tl and pl:
                j = cache.get(f"lj|{r.product}|{k}", lambda: g(JUDGE.format(a="\n".join(f"{i + 1}. {t}" for i, t in enumerate(tl)),
                                                                        b="\n".join(f"{i + 1}. {t}" for i, t in enumerate(pl))), 900))
                if j and len(j.get("a_covered", [])) == len(tl):
                    x["like_recall"] = float(np.mean([bool(v) for v in j["a_covered"]]))
                    x["like_precision"] = float(np.mean([bool(v) for v in j.get("b_present", [])[:len(pl)]]))
            runs.append(x)
        for m in ("complaint_recall", "complaint_precision", "like_recall", "like_precision"):
            v = [x[m] for x in runs if m in x]
            out[m] = float(np.mean(v)) if v else np.nan
        return out

    with cf.ThreadPoolExecutor(10) as ex:
        rows = list(ex.map(one, list(F.itertuples())))
    S = pd.DataFrame(rows)
    S.to_parquet(f"{a.work}/baseline_scores.parquet")
    print(S[["complaint_recall", "complaint_precision", "like_recall", "like_precision"]].mean().round(3).to_dict(), "usd", usd())
    sync([f"{a.work}/baseline_scores.parquet", f"{a.work}/llm_cache.jsonl"], a.sync)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["reviews", "fetch", "truth", "baseline"])
    ap.add_argument("--work", required=True)
    ap.add_argument("--judge-src", default="")
    ap.add_argument("--sync", default="")
    ap.add_argument("--records-glob", default="")
    ap.add_argument("--review-text", default="")
    ap.add_argument("--competitor-reviews", default="")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args(argv)
    os.makedirs(a.work, exist_ok=True)
    globals()[f"stage_{a.stage}"](a)


if __name__ == "__main__":
    main()
