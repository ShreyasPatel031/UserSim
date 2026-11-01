"""At-posting lever inputs for caught.py, for posts Jul 1 - Oct 14 (everything known before the post's own posting time).

record  The domain's / site's / author's record on HN's real daily list (front?day=, from 2025-01): earlier posts,
        how many made a daily top 30 / top 10, best rank. An earlier post counts only once its list settled
        (posted 2+ days before this post).
feeds   Outside feeds before posting (Grok Bot backfill from Jul 1: Techmeme, lobste.rs, Reddit x4, arXiv, press RSS,
        X): the post's own link seen in a feed in the 7 days before posting (mentions, sources, hours since first
        seen, per-source flags), and the domain's feed mentions in the prior 24 h.
dayfit  Title / topic fit with that day's audience (title embeddings): similarity to the stories people commented
        on in the 6 h before posting (comment-weighted), the same against the prior 30 days (topic is hot now vs
        usually), similarity to the previous 2 days' real top 30, and the closest HN post in the prior 6 h.

    python levers.py        # writes <cache>/caught_levers.parquet
"""
import os
from urllib.parse import urlsplit

import numpy as np
import pandas as pd
import scipy.sparse as sp

import emb_io
import feeds_anticipate as FA
import odds_live as OL
import top100 as H

START, END = "2026-07-01", "2026-10-14"
DAY = 86400


def host(u):
    if not isinstance(u, str) or not u:
        return None
    return urlsplit(u.strip()).netloc.lower().removeprefix("www.").removeprefix("m.") or None


def site(u):
    h = host(u)
    if h in ("github.com", "medium.com", "gitlab.com", "twitter.com", "x.com", "youtube.com", "substack.com"):
        seg = urlsplit(u).path.strip("/").split("/")[0].lower()
        return f"{h}/{seg}" if seg else h
    return h


def prior_record(p, key, hit30, hit10, best, q_ids, prefix):
    """Per query post: earlier posts with the same key (posted 2+ days before), their list hits, best rank."""
    ev = pd.DataFrame({"k": p[key], "t": p.created_at_i + 2 * DAY, "n": 1, "h30": hit30, "h10": hit10, "best": best, "q": 0})
    qq = p[p.post_id.isin(q_ids)]
    qr = pd.DataFrame({"k": qq[key], "t": qq.created_at_i, "n": 0, "h30": 0, "h10": 0, "best": 999.0, "q": 1,
                       "post_id": qq.post_id})
    a = pd.concat([ev.dropna(subset=["k"]), qr.dropna(subset=["k"])], ignore_index=True).sort_values(["t", "q"], kind="stable")
    g = a.groupby("k")
    out = pd.DataFrame({"post_id": a.post_id, f"{prefix}_n": g.n.cumsum(), f"{prefix}_t30": g.h30.cumsum(),
                        f"{prefix}_t10": g.h10.cumsum(), f"{prefix}_best": g.best.cummin()})[a.q.to_numpy() == 1]
    out[f"{prefix}_t30_rate"] = out[f"{prefix}_t30"] / out[f"{prefix}_n"].clip(lower=1)
    return out


def record(p, q_ids):
    L = OL.lists().sort_values("rank").drop_duplicates("post_id").set_index("post_id")["rank"]
    rk = p.post_id.map(L).astype(float).fillna(999)
    known = p.day >= "2025-01-01"                     # lists start 2025-01; earlier posts don't count as "missed"
    hit30 = ((rk <= 30) & known).astype(int).to_numpy()
    hit10 = ((rk <= 10) & known).astype(int).to_numpy()
    best = rk.to_numpy()
    p = p.assign(dom=p.url.map(host), site=p.url.map(site))
    p.loc[p.day < "2025-01-01", ["dom", "site", "author"]] = None   # record window = list window
    out = None
    for key, pre in (("dom", "rd"), ("site", "rs"), ("author", "ra")):
        r = prior_record(p, key, hit30, hit10, best, q_ids, pre)
        out = r if out is None else out.merge(r, on="post_id", how="outer")
    return out


def feeds(q):
    FA.download()
    F = FA.feed_items()
    F["dom"] = F.key.str.split("/").str[0]
    q = q.assign(key=q.url.map(FA.norm), dom=q.url.map(host))
    by_key = {k: g for k, g in F.groupby("key")}
    dom_t = {d: np.sort(g.t.to_numpy()) for d, g in F.groupby("dom")}
    src_flags = ["techmeme", "lobsters", "reddit", "arxiv", "rss", "x"]
    rows = []
    for pid, k, d, t in zip(q.post_id, q.key, q.dom, q.created_at_i):
        r = {"post_id": pid, "fd_n": 0, "fd_src": 0, "fd_h_since": np.nan, **{f"fd_{s}": 0 for s in src_flags}}
        g = by_key.get(k)
        if g is not None:
            g = g[(g.t < t) & (g.t >= t - 7 * DAY)]
            if len(g):
                r["fd_n"], r["fd_src"], r["fd_h_since"] = len(g), g.src.nunique(), (t - g.t.min()) / 3600
                for s in src_flags:
                    r[f"fd_{s}"] = int(g.src.str.startswith(s).any())
        dt_ = dom_t.get(d)
        r["fd_dom_24h"] = 0 if dt_ is None else int(np.searchsorted(dt_, t) - np.searchsorted(dt_, t - DAY))
        rows.append(r)
    out = pd.DataFrame(rows)
    print(f"feeds: posts whose link was in a feed before posting {(out.fd_n > 0).mean():.2%}", flush=True)
    return out


def dayfit(p, q):
    emb, ei = emb_io.load()
    t0 = pd.Timestamp(START, tz="UTC").timestamp() - 31 * DAY
    t1 = pd.Timestamp(END, tz="UTC").timestamp() + DAY
    c = pd.read_parquet(os.path.join(H.CACHE, "bq_comments.parquet"), columns=["story_id", "created_at_i"])
    c = c[(c.created_at_i >= t0) & (c.created_at_i < t1) & c.story_id.isin(ei.index)]
    c["hr"] = ((c.created_at_i - t0) // 3600).astype(int)
    stories = np.sort(c.story_id.unique())
    sidx = pd.Series(np.arange(len(stories)), index=stories)
    nh = int((t1 - t0) // 3600) + 1
    M = sp.coo_matrix((np.ones(len(c), np.float32), (c.hr.to_numpy(), sidx[c.story_id].to_numpy())), shape=(nh, len(stories))).tocsr()
    S = np.asarray(emb[np.sort(ei[stories].to_numpy())], np.float32)     # rows ordered by ei row
    order = np.argsort(ei[stories].to_numpy())                            # map back to stories order
    SE = np.empty_like(S)
    SE[order] = S
    H6 = (M @ SE)                                                         # per hour: comment-weighted sum of story vectors
    cs = np.vstack([np.zeros((1, 768), np.float32), np.cumsum(H6, 0)])
    def window(h, w):
        v = cs[h] - cs[np.maximum(h - w, 0)]
        return v / (np.linalg.norm(v, axis=-1, keepdims=True) + 1e-9)
    L = OL.lists()
    top30 = L[L["rank"] <= 30].groupby("day").post_id.apply(list)
    qq = q[q.post_id.isin(ei.index)].reset_index(drop=True)
    QE = np.asarray(emb[ei[qq.post_id].to_numpy()], np.float32)
    hrs = ((qq.created_at_i - t0) // 3600).astype(int).to_numpy()        # hour bucket of posting; use hours before it
    now6 = window(hrs, 6)
    long30 = window(hrs, 30 * 24)
    out = pd.DataFrame({"post_id": qq.post_id, "af_now6": (QE * now6).sum(1), "af_30d": (QE * long30).sum(1)})
    out["af_hot"] = out.af_now6 - out.af_30d
    # previous 2 days' real top 30
    prev_max, prev_top3 = np.full(len(qq), np.nan), np.full(len(qq), np.nan)
    for d, idx in qq.groupby("day").groups.items():
        ids = [x for dd in (pd.Timestamp(d) - pd.Timedelta(days=k) for k in (1, 2)) for x in top30.get(dd.strftime("%Y-%m-%d"), []) if x in ei.index]
        if not ids:
            continue
        s = QE[idx] @ np.asarray(emb[np.sort(ei[ids].to_numpy())], np.float32).T
        prev_max[idx] = s.max(1)
        prev_top3[idx] = np.sort(s, 1)[:, -3:].mean(1)
    out["af_prev2_max"], out["af_prev2_top3"] = prev_max, prev_top3
    # closest HN post in the prior 6 h (title duplicates / same story racing)
    pt = qq.created_at_i.to_numpy()
    o = np.argsort(pt)
    near = np.full(len(qq), np.nan)
    j0 = 0
    for i in o:
        while pt[o[j0]] < pt[i] - 6 * 3600:
            j0 += 1
        js = o[j0:np.searchsorted(pt[o], pt[i])]
        if len(js):
            near[i] = float((QE[js] @ QE[i]).max())
    out["af_near6h"] = near
    print(f"dayfit: {len(out)} posts with embeddings", flush=True)
    return out


def main():
    p = H.stories()
    q = p[(p.day >= START) & (p.day <= END)].reset_index(drop=True)
    R = record(p, set(q.post_id))
    print("record done", len(R), flush=True)
    F = feeds(q)
    A = dayfit(p, q)
    out = q[["post_id"]].merge(R, on="post_id", how="left").merge(F, on="post_id", how="left").merge(A, on="post_id", how="left")
    out.to_parquet(os.path.join(H.CACHE, "caught_levers.parquet"), index=False)
    print("saved", out.shape, flush=True)


if __name__ == "__main__":
    main()
