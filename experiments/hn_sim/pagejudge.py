"""At-posting lever: read the linked page and judge it the way an HN reader would (Gemini on Vertex only).

For each post: fetch its URL (plain HTTPS from this machine first; failures recorded), extract the visible text
(first ~6,000 characters), or use the post's own text for Ask/Show HN text posts. Gemini 2.5 Flash returns:
kind (launch / show_hn_product / research / postmortem / tutorial / opinion / news / rehash / other), novelty,
technical depth, title-vs-content match, HN fit (1-5 each), front_page_prob (0-100) and a short reason.
Show HN posts are judged as products. Caveat: pages are fetched now (Nov 2026), so an old post's page may have changed.

Pilot (default): every post of two test days (2026-09-15, 2026-09-16; ~2,280 posts). Cost and coverage logged to the
spend table. Evaluation on the pilot days: AUC of the judge for winners; and Caught on those days for the base
at-posting score vs the base blended with the judge (rank average, weight picked leave-one-day-out).

    python pagejudge.py [days=2026-09-15,2026-09-16]
    PJ_MODEL=lite python pagejudge.py 2026-07-01,2026-10-14 --range     # full run (needs the user's OK: ~$25)
Page text is cached in <cache>/page_text.jsonl (the pilot's first run did not keep it).
"""
import html
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import requests

import llm
import store as S
import top100 as H

DAYS = (sys.argv[1] if len(sys.argv) > 1 else "2026-09-15,2026-09-16").split(",")
if len(DAYS) == 2 and DAYS[0] > "2000" and "--range" in sys.argv:          # pagejudge.py 2026-07-01,2026-10-14 --range
    DAYS = [d.strftime("%Y-%m-%d") for d in pd.date_range(DAYS[0], DAYS[1])]
MODEL = {"flash": "gemini-2.5-flash", "lite": "gemini-2.5-flash-lite"}[os.environ.get("PJ_MODEL", "flash")]
OUT = os.path.join(H.CACHE, "pagejudge.jsonl" if MODEL.endswith("flash") else "pagejudge_lite.jsonl")
PAGES = os.path.join(H.CACHE, "page_text.jsonl")      # fetched page text, kept so a later run never refetches
_pages, _plock = {}, __import__("threading").Lock()
if os.path.exists(PAGES):
    for _x in open(PAGES):
        try:
            _r = json.loads(_x)
            _pages[_r["post_id"]] = (_r["fetch"], _r["text"])
        except ValueError:
            pass
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
SYSTEM = ("You are a long-time Hacker News reader who knows what the front page upvotes: novel technical work, "
          "deep write-ups, surprising results, honest postmortems, useful launches; and what it ignores: marketing, "
          "rehashes, thin news, listicles, paywalled fluff. Judge the linked page as that reader would, from its content. "
          "Show HN posts are products: judge the product and how it is presented. Answer in JSON only.")
PROMPT = """HN title: {title}
Link: {url}
Page text (may be truncated; empty if it could not be read):
<<<
{text}
>>>

Return JSON:
{{"kind": one of ["launch","show_hn_product","research","postmortem","tutorial","deep_dive","opinion","news","rehash","other"],
 "novelty": 1-5, "depth": 1-5, "title_matches": 1-5, "hn_fit": 1-5,
 "front_page_prob": 0-100 (chance this reaches HN's front page and gets a lot of upvotes),
 "reason": "<= 25 words"}}"""


def page_text(url):
    if not isinstance(url, str) or not url:
        return "none", ""
    try:
        r = requests.get(url, headers=UA, timeout=15, stream=True)
        raw = r.raw.read(1_500_000, decode_content=True)
        ct = r.headers.get("content-type", "")
        if r.status_code != 200:
            return f"http{r.status_code}", ""
        if "pdf" in ct:
            return "pdf", ""
        h = raw.decode(r.encoding or "utf-8", "replace")
    except Exception as exc:  # noqa: BLE001
        return type(exc).__name__, ""
    h = re.sub(r"(?is)<(script|style|noscript|svg|nav|footer|header)[^>]*>.*?</\1>", " ", h)
    t = html.unescape(re.sub(r"(?s)<[^>]+>", " ", h))
    t = re.sub(r"\s+", " ", t).strip()
    return ("ok" if len(t) > 200 else "thin"), t[:6000]


def cached_page(row):
    """Fetch once per post; blocked / failed fetches (403 etc.) are kept as missing and never retried."""
    if row.post_id in _pages:
        return _pages[row.post_id]
    st, text = page_text(row.url)
    with _plock:
        _pages[row.post_id] = (st, text)
        with open(PAGES, "a") as f:
            f.write(json.dumps({"post_id": int(row.post_id), "fetch": st, "text": text}) + "\n")
    return st, text


def judge(row):
    if isinstance(row.url, str) and row.url:
        st, text = cached_page(row)
    else:
        st, text = "self", html.unescape(re.sub(r"<[^>]+>", " ", row.text or ""))[:6000]
    j = llm.call("hn_pagejudge", PROMPT.format(title=row.title, url=row.url or "(text post)", text=text),
                 system=SYSTEM, model=MODEL, max_tokens=400)
    return {"post_id": int(row.post_id), "fetch": st, "chars": len(text), **{k: v for k, v in j.items() if k != "_usd"}}


def run(days):
    p = H.stories()
    q = p[p.day.isin(days)]
    done = set()
    if os.path.exists(OUT):
        done = {json.loads(x)["post_id"] for x in open(OUT)}
    todo = [r for r in q.itertuples() if r.post_id not in done]
    print(f"{len(q)} posts on {days}, {len(todo)} to judge", flush=True)
    with ThreadPoolExecutor(int(os.environ.get("PJ_THREADS", "16"))) as ex, open(OUT, "a") as f:
        for i, r in enumerate(ex.map(judge, todo)):
            f.write(json.dumps(r) + "\n")
            if i % 2000 == 0:
                print(i, f"${llm.spent():.3f}", flush=True)
    usd = llm.flush_spend("hn_sim.pagejudge", f"{MODEL} {days[0]}..{days[-1]}: {len(todo)} posts")
    print(f"spent ${usd:.3f} for {len(todo)} posts", flush=True)


def evaluate(days):
    import caught as C
    from sklearn.metrics import roc_auc_score
    J = pd.DataFrame([json.loads(x) for x in open(OUT)]).drop_duplicates("post_id")
    print("fetch status:", J.fetch.value_counts(normalize=True).round(3).to_dict(), flush=True)
    base = pd.Series(C.model(C.POST + C.KNN + C.EMB + C.CROWD), index=C.Q.post_id[C.te].to_numpy())
    T = C.Q[C.te & C.Q.day.isin(days).to_numpy()][["post_id", "day", "y"]].copy()
    T["base"] = base.reindex(T.post_id).to_numpy()
    T = T.merge(J, on="post_id", how="left")
    T["judge"] = pd.to_numeric(T.front_page_prob, errors="coerce")
    print(f"pilot posts {len(T)}, judged {T.judge.notna().mean():.1%}, winners {int(T.y.sum())}", flush=True)
    ok = T.judge.notna()
    print(f"AUC for winners: judge {roc_auc_score(T.y[ok], T.judge[ok]):.3f}; base {roc_auc_score(T.y, T.base):.3f}", flush=True)
    for c in ("novelty", "depth", "title_matches", "hn_fit"):
        v = pd.to_numeric(T[c], errors="coerce")
        print(f"  {c}: AUC {roc_auc_score(T.y[v.notna()], v[v.notna()]):.3f}", flush=True)
    print("winner rate by kind:", T.groupby("kind").y.agg(["mean", "size"]).round(3).to_dict("index"), flush=True)
    T["judge"] = T.judge.fillna(T.judge.median())
    rb, rj = T.base.rank(pct=True), T.judge.rank(pct=True)

    def caught_at(w):
        s = (1 - w) * rb + w * rj
        k = int(T.y.sum())
        return int(((s.rank(ascending=False, method="first") <= k) & (T.y == 1)).sum()) / k
    grid = np.linspace(0, 1, 11)
    loo = []
    for d in days:                                     # weight picked on the other pilot day(s)
        other = T.day != d
        def c_on(mask, w):
            s = ((1 - w) * rb + w * rj)[mask]
            y = T.y[mask]
            k = int(y.sum())
            return int(((s.rank(ascending=False, method="first") <= k) & (y == 1)).sum()) / max(k, 1)
        w = grid[int(np.argmax([c_on(other, g) for g in grid]))]
        loo.append((d, w, c_on(~other, 0.0), c_on(~other, w)))
    print(f"Caught on the pilot days: base {caught_at(0):.1%}; judge alone {caught_at(1):.1%}; "
          f"blend 50/50 {caught_at(0.5):.1%}", flush=True)
    for d, w, a, b in loo:
        print(f"  leave-one-day-out {d}: weight {w:.1f}, base {a:.1%} -> blend {b:.1%}", flush=True)


if __name__ == "__main__":
    run(DAYS)
    if "--range" not in sys.argv:
        evaluate(DAYS)
