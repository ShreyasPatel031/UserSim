"""Anticipating stories before they are posted to HN, from outside feeds (Grok Bot backfill: Techmeme, lobste.rs,
Reddit, arXiv, press RSS, X; feeder/<source>/<day>.jsonl). Test: daily-list top-30 recall at 12:00 and 18:00 UTC with
and without feed candidates.

At forecast time T on day D, feed candidates = links first seen in a feed in the 48 h before T (arXiv: from its
listing time, the next weekday 00:00 UTC; Techmeme times are upper bounds) and not posted to HN before T (URL match).
Label: the link is posted to HN and that post is in D's real top 30. Inputs (all known at T): sources and mentions so
far, hours since first seen, Techmeme / lobste.rs / Reddit flags, the link's domain record (its HN stories' daily
top-30 hits before D), outcomes of the 30 most similar earlier HN titles (title embedding), hour of T. Counts read
by the feeder later (scores, likes) are NOT used.
HN candidates: the v4 hybrid (top-30 classifier probability). Merged list: top 30 by probability across both pools.
Train Jul 6 - Aug 31, test Sep 1 - Oct 16 (fully fetched days, as v4_t18.py); paired-by-day difference, 95% CI.

    python feeds_anticipate.py
"""
import datetime as dt
import glob
import json
import os
import re
from urllib.parse import urlsplit

import lightgbm as lgb
import numpy as np
import pandas as pd

import daily_v4 as V
import emb_io
import top100 as H
import v4_t18 as X

FEED_DIR = os.environ.get("FEED_DIR", os.path.join(H.CACHE, "feeder_backfill"))
TIMES = {"t12": 12, "t18": 6}
rng = np.random.default_rng(0)


def norm(u):
    if not isinstance(u, str) or not u:
        return None
    s = urlsplit(u.strip())
    h = s.netloc.lower().removeprefix("www.").removeprefix("m.")
    p = s.path.rstrip("/")
    if "arxiv.org" in h:
        p = re.sub(r"^/(abs|pdf|html)/", "/abs/", p)
        p = re.sub(r"v\d+$", "", p).removesuffix(".pdf")
    return h + p + ("?" + s.query if h == "youtube.com" and s.query else "")


def download():
    import store as S
    os.makedirs(FEED_DIR, exist_ok=True)
    n = 0
    for x in S._bucket().list_blobs(prefix="usersim_sim/hn_jobs/cache/feeder/"):
        parts = x.name.split("/")
        if len(parts) == 6 and parts[4] not in ("_code", "hn_minute", "favs", "requests") and parts[5] <= "2026-10-17.jsonl":
            os.makedirs(os.path.join(FEED_DIR, parts[4]), exist_ok=True)
            dst = os.path.join(FEED_DIR, parts[4], parts[5])
            if not os.path.exists(dst):
                x.download_to_filename(dst)
                n += 1
    print("feed files downloaded", n, flush=True)


def feed_items():
    rows = []
    for f in glob.glob(os.path.join(FEED_DIR, "*", "*.jsonl")):
        src = f.split("/")[-2]
        for line in open(f):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if str(r.get("mode", "")).startswith("live"):
                continue
            t = dt.datetime.fromisoformat(r["published_at"].replace("Z", "+00:00")).timestamp()
            if src == "arxiv":                                   # public at the next weekday's listing, 00:00 UTC
                d = dt.datetime.fromtimestamp(t, dt.UTC)
                t = (t // 86400 + 1 + (2 if d.weekday() == 4 else 1 if d.weekday() == 5 else 0)) * 86400
            for u in [r.get("url")] + (r.get("links") or []):
                k = norm(u)
                if k and "news.ycombinator.com" not in k:
                    rows.append((k, t, src, r.get("title") or ""))
    F = pd.DataFrame(rows, columns=["key", "t", "src", "title"])
    print("feed mentions", len(F), "links", F.key.nunique(), flush=True)
    return F


def embed_titles(titles):
    """Vertex text-embedding-005 for feed titles (cached by title), cost logged."""
    import google.auth.transport.requests
    import requests
    import embed as EM
    import store as S
    from auth import vertex_credentials
    path = os.path.join(H.CACHE, "feed_title_emb.parquet")
    have = pd.read_parquet(path) if os.path.exists(path) else pd.DataFrame(columns=["title", "emb"])
    todo = sorted(set(titles) - set(have.title))
    cred = vertex_credentials()
    cred.refresh(google.auth.transport.requests.Request())
    out, chars = [], 0
    for i in range(0, len(todo), 250):
        chunk = todo[i:i + 250]
        for attempt in range(5):
            r = requests.post(EM.URL, headers={"Authorization": f"Bearer {cred.token}"}, timeout=120,
                              json={"instances": [{"content": t[:2000] or "-", "task_type": "SEMANTIC_SIMILARITY"} for t in chunk]})
            if r.status_code == 200:
                break
            if r.status_code == 401:
                cred.refresh(google.auth.transport.requests.Request())
        E = np.array([x["embeddings"]["values"] for x in r.json()["predictions"]], np.float32)
        out.append(pd.DataFrame({"title": chunk, "emb": list(E / (np.linalg.norm(E, axis=1, keepdims=True) + 1e-9))}))
        chars += sum(len(t) for t in chunk)
    if out:
        have = pd.concat([have] + out, ignore_index=True)
        have.to_parquet(path, index=False)
        S.spend("hn_sim.feed_embed", chars / 1000 * EM.USD_PER_1K_CHARS, f"{len(todo)} feed titles, {chars} chars")
        print(f"embedded {len(todo)} feed titles, ${chars / 1000 * EM.USD_PER_1K_CHARS:.3f}", flush=True)
    return dict(zip(have.title, have.emb))


def main():
    download()
    F = feed_items()
    p = H.stories()
    p["key"] = p.url.map(norm)
    hn_first = p.dropna(subset=["key"]).groupby("key").created_at_i.min()
    L = V.lists()
    top30 = L[L["rank"] <= 30]
    key_of = p.set_index("post_id").key
    win = top30.assign(key=top30.post_id.map(key_of)).dropna(subset=["key"])
    win_day = win.groupby("key").day.apply(set)
    dom = lambda k: k.split("/")[0]
    win["dom"] = win.key.map(dom)
    dom_hits = win.groupby(["dom", "day"]).size().rename("n").reset_index()
    # content prior: outcomes of the 30 most similar earlier HN titles (as audience.py), for each feed title
    emb, ei = emb_io.load()
    past = p[p.post_id.isin(ei.index) & (p.points >= 3) & (p.day < "2026-07-01")]
    past = past.assign(_r=ei[past.post_id].to_numpy()).sort_values("_r")
    PE = np.asarray(emb[past._r.to_numpy()], np.float32)
    lp = np.log1p(past.points.to_numpy(np.float32))
    t30 = past.post_id.isin(set(top30.post_id)).to_numpy().astype(np.float32)
    first = F.sort_values("t").drop_duplicates("key")
    TE = embed_titles(first.title.tolist())
    knn = {}
    keys, titles = first.key.to_numpy(), first.title.to_numpy()
    for i in range(0, len(keys), 2000):
        E = np.stack([TE[t] for t in titles[i:i + 2000]]).astype(np.float32)
        S_ = E @ PE.T
        k = np.argpartition(-S_, 30, axis=1)[:, :30]
        for j, key in enumerate(keys[i:i + 2000]):
            knn[key] = (lp[k[j]].mean(), t30[k[j]].mean(), float(S_[j, k[j]].mean()))
    print("content prior for", len(knn), "links", flush=True)

    days = sorted(X.C.day.unique())
    rows = []
    Fs = F.sort_values("t")
    for d in days:
        t1 = pd.Timestamp(d, tz="UTC").timestamp() + 86400
        prior = dom_hits[dom_hits.day < d].groupby("dom").n.sum()
        for name, off in TIMES.items():
            T = t1 - off * 3600
            w = Fs[(Fs.t < T) & (Fs.t >= T - 48 * 3600)]
            if w.empty:
                continue
            g = w.groupby("key").agg(first_t=("t", "min"), n=("t", "size"), n_src=("src", "nunique"),
                                     techmeme=("src", lambda s: int((s == "techmeme").any())),
                                     lobsters=("src", lambda s: int((s == "lobsters").any())),
                                     reddit=("src", lambda s: int(s.str.startswith("reddit").any())),
                                     arxiv=("src", lambda s: int((s == "arxiv").any()))).reset_index()
            g = g[g.key.map(lambda k: hn_first.get(k, np.inf) >= T)]           # not on HN yet at T
            g["h_since"] = (T - g.first_t) / 3600
            g["dom_hits"] = g.key.map(lambda k: prior.get(dom(k), 0))
            kp = np.array([knn.get(k, (np.nan, np.nan, np.nan)) for k in g.key])
            g["knn_lp"], g["knn_t30"], g["knn_sim"] = kp[:, 0], kp[:, 1], kp[:, 2]
            g["y"] = g.key.map(lambda k: int(d in win_day.get(k, ()))).to_numpy()
            g["day"], g["T"] = d, name
            rows.append(g)
    FC = pd.concat(rows, ignore_index=True)
    FX = ["n", "n_src", "techmeme", "lobsters", "reddit", "arxiv", "h_since", "dom_hits", "knn_lp", "knn_t30", "knn_sim"]
    print("feed candidates per day:", FC.groupby(["T", "day"]).size().groupby("T").mean().round(0).to_dict(),
          "| real top-30 among them per day:", FC.groupby(["T", "day"]).y.sum().groupby("T").mean().round(2).to_dict(), flush=True)

    for name in TIMES:
        D = X.C[X.C[f"{name}_visible"] == 1]
        tr, te = D[D.day < "2026-09-01"], D[D.day >= "2026-09-01"]
        base = ["on_earlier_list", "text_score"] + [f"{name}_{c}" for c in list(V.VC) + ["stage1", "c_all", "c_last3h"]]
        clf = V.fit_top30(tr, base)
        hn = te[["day", "post_id", "real_rank", "on_earlier_list"]].assign(p=clf.predict_proba(te[base])[:, 1])
        hn.loc[hn.on_earlier_list == 1, "p"] = 0
        f = FC[FC["T"] == name]
        ftr, fte = f[f.day < "2026-09-01"], f[f.day >= "2026-09-01"]
        fm = lgb.LGBMClassifier(n_estimators=300, learning_rate=0.05, num_leaves=15, min_child_samples=20, verbose=-1,
                                random_state=0).fit(ftr[FX], ftr.y)
        fte = fte.assign(p=fm.predict_proba(fte[FX])[:, 1])
        a, b = [], []
        for d, g in hn.groupby("day"):
            real = (g.real_rank <= 30).sum() + 0                         # real top 30 visible on HN at T
            n_real = 30
            a.append(len(set(g[g.real_rank <= 30].post_id) & set(g.nlargest(30, "p").post_id)) / n_real)
            fd = fte[fte.day == d]
            pool = pd.concat([g.assign(kind="hn", y=(g.real_rank <= 30).astype(int))[["p", "y", "kind"]], fd[["p", "y"]].assign(kind="feed")])
            b.append(pool.nlargest(30, "p").y.sum() / n_real)
        a, b = np.array(a), np.array(b)
        d_ = b - a
        bt = [rng.choice(d_, len(d_)).mean() for _ in range(2000)]
        fp = fte.groupby("day").apply(lambda g: g.nlargest(5, "p").y.sum())
        print(f"{name}: real top 30 found, HN only {a.mean():.3f}; + feed candidates {b.mean():.3f}; difference "
              f"{d_.mean():+.3f} [{np.percentile(bt, 2.5):+.3f}, {np.percentile(bt, 97.5):+.3f}] over {len(a)} days; "
              f"feed winners available {fte.groupby('day').y.sum().mean():.2f}/day, in the feed model's top 5 {fp.mean():.2f}/day", flush=True)


if __name__ == "__main__":
    main()
