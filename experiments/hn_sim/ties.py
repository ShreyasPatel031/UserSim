"""Tie strength on HN (the Product Hunt finding: who you are connected to beats content taste). Data before CUT only.

Ties of person P to submitter S, from comments since 2025-01 (bq_comments.parquet, replies.parquet):
  t_cmt     P commented on S's stories (recency-weighted, half-life 180 d)
  t_rep     P replied directly to S's comments or stories
  t_back    S replied to P / commented on P's stories (reciprocity)
  t_share   (t_cmt + t_rep) / P's weighted activity (share of P's history spent on S)
1. Individual: twin_v2_pairs.parquet (person, story, engaged?) + ties to the story's submitter; train Jul-Aug, test
   Sep 1 - Oct 14; median per-person AUC overall and within popularity bands: content taste (+ favorites) vs
   ties vs both.
2. At posting: per post, the submitter's tie network: people with any tie (n_tied), their expected presence at the
   posting hour (sum of rate x hour share), /new browsers among them, reciprocal ties, strongest tie; added to the
   best at-posting inputs (as competition.py); paired-by-day difference in winners caught.

    python ties.py
"""
import json
import os

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

import top100 as H

CUT, CUT2, END = "2026-07-01", "2026-09-01", "2026-10-14"
t_cut = pd.Timestamp(CUT, tz="UTC").timestamp()
rng = np.random.default_rng(0)
POST_ONLY = os.environ.get("TIES_POST_ONLY") == "1"         # only build and save the per-post tie network (for caught.py)
p = H.stories().set_index("post_id")
author = p.author

# ---- ties before CUT ------------------------------------------------------------------------------------------
c = pd.read_parquet(os.path.join(H.CACHE, "bq_comments.parquet"), columns=["person", "story_id", "created_at_i"])
c = c[(c.created_at_i < t_cut) & (c.created_at_i >= pd.Timestamp("2025-01-01", tz="UTC").timestamp())]
c["sub"] = c.story_id.map(author).to_numpy()
c = c[c["sub"].notna() & (c["sub"] != c.person)]
c["w"] = np.exp(-(t_cut - c.created_at_i.to_numpy()) / (180 * 86400) * np.log(2))
r = pd.read_parquet(os.path.join(H.CACHE, "replies.parquet"))
r = r[(r.t < t_cut) & (r.person != r.parent_author)]
r["w"] = np.exp(-(t_cut - r.t.to_numpy()) / (180 * 86400) * np.log(2))
t_cmt = c.groupby(["person", "sub"]).w.sum()
t_rep = r.groupby(["person", "parent_author"]).w.sum().rename_axis(["person", "sub"])
act = c.groupby("person").w.sum().add(r.groupby("person").w.sum(), fill_value=0)
back = t_cmt.add(t_rep, fill_value=0)
t_back = back.copy()
t_back.index = t_back.index.swaplevel()                                  # (sub, person) -> S's ties to P
t_back = t_back.rename_axis(["person", "sub"])
print(f"tie pairs: commented-on {len(t_cmt)}, replied-to {len(t_rep)}", flush=True)


def tie_feats(persons, subs):
    idx = pd.MultiIndex.from_arrays([persons, subs])
    f = pd.DataFrame({"t_cmt": t_cmt.reindex(idx).fillna(0).to_numpy(), "t_rep": t_rep.reindex(idx).fillna(0).to_numpy(),
                      "t_back": t_back.reindex(idx).fillna(0).to_numpy()})
    f["t_share"] = (f.t_cmt + f.t_rep) / np.maximum(act.reindex(persons).fillna(0).to_numpy(), 1e-3)
    return f


# ---- 1. individual ----------------------------------------------------------------------------------------------
if not POST_ONLY:
    D = pd.read_parquet(os.path.join(H.CACHE, "twin_v2_pairs.parquet"))
    D = pd.concat([D.reset_index(drop=True), tie_feats(D.person.to_numpy(), author.reindex(D.story_id).to_numpy())], axis=1)
    TIE = ["t_cmt", "t_rep", "t_back", "t_share"]
    CONTENT = ["sim_mean", "sim_max", "sim_top5", "dom_share", "dom_n", "hour_p"] + [x for x in D.columns if x.startswith("fav_")] + (["n_favs"] if "n_favs" in D else [])
    tr, te = D[D.day < CUT2], D[D.day >= CUT2]
    print(f"pairs with any tie to the submitter: {(D[TIE[:3]].sum(1) > 0).mean():.2%}; among engaged pairs: {(D[D.y == 1][TIE[:3]].sum(1) > 0).mean():.2%}", flush=True)


    def fit(cols):
        m = lgb.LGBMClassifier(n_estimators=400, learning_rate=0.05, num_leaves=31, min_child_samples=50, subsample=0.8,
                               subsample_freq=1, colsample_bytree=0.8, verbose=-1, random_state=0)
        return m.fit(tr[cols], tr.y).predict_proba(te[cols])[:, 1]


    def per_person(s, band=False):
        t = te.assign(s=s)
        out = []
        for _, g in t.groupby("person"):
            if band:
                v = [roc_auc_score(h.y, h.s) for _, h in g.groupby("pop_band") if h.y.nunique() == 2 and len(h) >= 10]
                if v:
                    out.append(np.mean(v))
            elif g.y.nunique() == 2:
                out.append(roc_auc_score(g.y, g.s))
        return np.median(out)


    print("individual (median per-person AUC | within popularity bands):", flush=True)
    for name, cols in (("content taste (+ favorites)", CONTENT), ("ties to the submitter (old: auth_n only)", ["auth_n"]),
                       ("ties to the submitter (new)", TIE + ["auth_n"]), ("content + ties", CONTENT + TIE + ["auth_n"]),
                       ("content + ties + popularity", CONTENT + TIE + ["auth_n", "pop_final"])):
        s = fit(cols)
        print(f"  {name:42s} {per_person(s):.3f} | {per_person(s, True):.3f}", flush=True)

# ---- 2. at posting ----------------------------------------------------------------------------------------------
cm = pd.read_parquet(os.path.join(H.CACHE, "bq_comments.parquet"), columns=["person", "story_id", "created_at_i"])
cm = cm[(cm.created_at_i < t_cut) & (cm.created_at_i >= t_cut - 180 * 86400)]
rate = cm.groupby("person").size() / 180
hr = cm.assign(h=(cm.created_at_i // 3600) % 24).groupby(["person", "h"]).size().unstack(fill_value=0)
hr = (hr + 1).div((hr + 1).sum(1), axis=0)
lat = cm.created_at_i - cm.story_id.map(p.created_at_i).to_numpy()
scout = (cm.assign(s=(lat >= 0) & (lat <= 3600)).groupby("person").s.mean() > 0.3)
E = t_cmt.add(t_rep, fill_value=0).reset_index().rename(columns={0: "w"})
E.columns = ["person", "sub", "w"]
E = E[E.w > 0]
E["rate"] = E.person.map(rate).fillna(0).to_numpy()
E["scout"] = E.person.map(scout).fillna(False).to_numpy()
E["recip"] = t_back.reindex(pd.MultiIndex.from_frame(E[["person", "sub"]])).fillna(0).to_numpy() > 0
q = p[(p.day >= CUT) & (p.day <= END)].reset_index()[["post_id", "author", "created_at_i", "day"]]
q["h"] = (q.created_at_i // 3600) % 24
by_sub = {s: g for s, g in E.groupby("sub")}
rows = []
for pid, s, h in zip(q.post_id, q.author, q.h):
    g = by_sub.get(s)
    if g is None:
        rows.append((pid, 0, 0.0, 0, 0, 0.0, 0.0))
        continue
    pres = g.rate.to_numpy() * hr.reindex(g.person)[h].fillna(1 / 24).to_numpy()
    rows.append((pid, len(g), float((pres * np.log1p(g.w.to_numpy())).sum()), int(g.scout.sum()), int(g.recip.sum()),
                 float(g.w.max()), float(pres.sum())))
T = pd.DataFrame(rows, columns=["post_id", "tie_n", "tie_present_w", "tie_scouts", "tie_recip", "tie_max", "tie_present"])
TIES = [x for x in T.columns if x != "post_id"]
print(f"posts with any tie network: {(T.tie_n > 0).mean():.1%}", flush=True)
T.to_parquet(os.path.join(H.CACHE, "tie_post_feats.parquet"), index=False)
if POST_ONLY:
    raise SystemExit

A = pd.read_parquet(os.path.join(H.CACHE, "audience_feats.parquet"))
B = pd.read_parquet(os.path.join(H.CACHE, "daily_cache.parquet"))
bcols = [x for x in B.columns if x.startswith("b_") and not x.startswith(("b_w30_", "b_w60_"))]
B = B[["post_id", "text_score"] + bcols].drop_duplicates("post_id")
F2 = pd.read_parquet(os.path.join(H.CACHE, "crowd_v2_feats.parquet"))
Q = q[["post_id", "day"]].merge(B, on="post_id", how="left").merge(A, on="post_id", how="left").merge(F2, on="post_id", how="left").merge(T, on="post_id", how="left")
L = pd.read_json(os.path.join(H.CACHE, "frontday.jsonl"), lines=True, dtype={"day": str})
Q["list_rank"] = Q.post_id.map(L.groupby("post_id")["rank"].min()).fillna(999)
trp, tep = (Q.day < CUT2).to_numpy(), (Q.day >= CUT2).to_numpy()
BEST = (["text_score"] + bcols + ["knn_lp", "knn_100", "knn_t30", "knn_sim"] + [f"emb{j}" for j in range(64)]
        + ["aud_sum", "aud_cube", "aud_fans", "scout_sum", "scout_cube", "scout_fans", "fans_any", "top50_sim"]
        + ["c2_sum", "c2_scout", "c2_top50", "c2_n20"])
per_day = {}
for top in (30, 10):
    y = (Q.list_rank <= top).to_numpy()
    for name, cols in (("best so far", BEST), ("+ submitter tie network", BEST + TIES), ("tie network alone", TIES)):
        m = lgb.LGBMClassifier(n_estimators=600, learning_rate=0.03, num_leaves=31, min_child_samples=30, subsample=0.8,
                               subsample_freq=1, colsample_bytree=0.8, verbose=-1, random_state=0).fit(Q.loc[trp, cols], y[trp])
        s = m.predict_proba(Q.loc[tep, cols])[:, 1]
        P = Q[tep].assign(s=s, y=y[tep])
        cap = P.groupby("day").apply(lambda g: g.nlargest(top, "s").y.sum() / max(g.y.sum(), 1))
        per_day[(top, name)] = cap
        print(json.dumps({"target": f"top {top}", "inputs": name, "AUC": round(roc_auc_score(y[tep], s), 3),
                          "avg_precision": round(average_precision_score(y[tep], s), 3), f"winners_in_top{top}": round(cap.mean(), 3)}), flush=True)
    d = (per_day[(top, "+ submitter tie network")] - per_day[(top, "best so far")]).to_numpy()
    boot = [rng.choice(d, len(d)).mean() for _ in range(2000)]
    print(f"  top {top}: + ties vs best, winners caught per day {d.mean():+.3f} [{np.percentile(boot, 2.5):+.3f}, {np.percentile(boot, 97.5):+.3f}]", flush=True)
