"""Individual simulation v2: one shared model of "would person P engage (comment) with story S", from several personal
signals, built only from each person's history before CUT. Train on held-out Jul-Aug, test Sep-Oct 14, on the same
panel and candidate design as twin_test.py (listed stories of the days the person was active; positives = commented).

Per (person, story):
  sim_mean     cosine to the person's recency-weighted mean taste
  sim_max      cosine to the closest of their last 200 engaged stories (several interests, not one average)
  sim_top5     mean of the 5 closest
  dom_share    share of their past engagement on this story's domain; dom_n = count
  auth_n       times they engaged with this story's submitter before
  hour_p       their presence at the story's posting hour (share of comments in that UTC hour)
  pop_final    the story's final points (not known at posting: shown separately, as the "popularity" reference)
Scored per person (AUC, median over people), and within popularity bands (stories of similar final points), which is
the honest "does personal taste add anything" number.

    python twin_v2.py [n=3000]
"""
import os
import sys
from urllib.parse import urlsplit

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

import emb_io
import top100 as H

N = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
CUT, MID, END = "2026-07-01", "2026-09-01", "2026-10-14"
t_cut = pd.Timestamp(CUT, tz="UTC").timestamp()
rng = np.random.default_rng(0)
emb, ei = emb_io.load()
p = H.stories().set_index("post_id")
dom = p.url.map(lambda u: urlsplit(u).netloc.lower().removeprefix("www.") if isinstance(u, str) and u else "self")
c = pd.read_parquet(os.path.join(H.CACHE, "bq_comments.parquet"), columns=["person", "story_id", "created_at_i"])
c = c[c.story_id.isin(ei.index)]
before = c[(c.created_at_i < t_cut) & (c.created_at_i >= t_cut - 540 * 86400)]
after = c[(c.created_at_i >= t_cut) & (c.created_at_i < pd.Timestamp(END, tz="UTC").timestamp() + 86400)]
act = before[before.created_at_i >= t_cut - 180 * 86400].groupby("person").size()
panel = act[act.index.isin(after.person.unique())].nlargest(N).index
pi = pd.Series(np.arange(len(panel)), index=panel)
b = before[before.person.isin(panel)].sort_values("created_at_i")
print("panel", len(panel), "history rows", len(b), flush=True)

# person profiles (before CUT only)
w = np.exp(-(t_cut - b.created_at_i.to_numpy()) / (180 * 86400) * np.log(2)).astype(np.float32)
rp, rs = pi[b.person].to_numpy(), ei[b.story_id].to_numpy()
taste = np.zeros((len(panel), 768), np.float32)
for k in range(0, len(rp), 300000):
    np.add.at(taste, rp[k:k + 300000], np.asarray(emb[rs[k:k + 300000]], np.float32) * w[k:k + 300000, None])
taste /= np.linalg.norm(taste, axis=1, keepdims=True) + 1e-9
last = b.drop_duplicates(["person", "story_id"], keep="last").groupby("person").story_id.apply(lambda s: s.to_numpy()[-200:])
b = b.assign(dom=b.story_id.map(dom).to_numpy(), auth=b.story_id.map(p.author).to_numpy())
dom_n = b.groupby(["person", "dom"]).size()
tot = b.groupby("person").size()
auth_n = b.groupby(["person", "auth"]).size()
hour = np.full((len(panel), 24), 1.0, np.float32)
rb = b[b.created_at_i >= t_cut - 180 * 86400]
np.add.at(hour, (pi[rb.person].to_numpy(), ((rb.created_at_i // 3600) % 24).to_numpy()), 1)
hour /= hour.sum(1, keepdims=True)

# candidates: listed stories of the days the person engaged (as twin_test.py)
L = pd.read_json(os.path.join(H.CACHE, "frontday.jsonl"), lines=True, dtype={"day": str})
L = L[(L.day >= CUT) & (L.day <= END) & L.post_id.isin(ei.index)].drop_duplicates("post_id")
day_of = L.set_index("post_id").day
by_day = L.groupby("day").post_id.apply(np.array)
a = after[after.person.isin(panel) & after.story_id.isin(day_of.index)]
rows = []
for person, g in a.groupby("person"):
    pos = np.unique(g.story_id.to_numpy())
    if len(pos) < 5:
        continue
    cand = np.unique(np.concatenate([by_day[d] for d in day_of[pos].unique()]))
    neg = np.setdiff1d(cand, pos)
    if len(neg) < 20:
        continue
    neg = rng.choice(neg, min(len(neg), 20 * len(pos)), replace=False)
    ids = np.concatenate([pos, neg])
    i = pi[person]
    S = np.asarray(emb[ei[ids].to_numpy()], np.float32)
    hist = np.asarray(emb[ei[last.get(person, np.array([], int))].to_numpy()], np.float32)
    sims = S @ hist.T if len(hist) else np.zeros((len(ids), 1), np.float32)
    srt = np.sort(sims, axis=1)
    d_ = dom.reindex(ids).fillna("self").to_numpy()
    au = p.author.reindex(ids).to_numpy()
    rows.append(pd.DataFrame({
        "person": person, "story_id": ids, "y": np.r_[np.ones(len(pos)), np.zeros(len(neg))],
        "day": day_of[ids].to_numpy(), "sim_mean": S @ taste[i], "sim_max": srt[:, -1], "sim_top5": srt[:, -5:].mean(1),
        "dom_n": [dom_n.get((person, x), 0) for x in d_],
        "auth_n": [auth_n.get((person, x), 0) for x in au],
        "hour_p": hour[i, ((p.created_at_i.reindex(ids).to_numpy() // 3600) % 24).astype(int)],
        "pop_final": np.log1p(p.points.reindex(ids).fillna(1).to_numpy())}))
D = pd.concat(rows, ignore_index=True)
D["dom_share"] = D.dom_n / D.person.map(tot).to_numpy()
D["pop_band"] = pd.qcut(D.pop_final.rank(method="first"), 10, labels=False)
print("pairs", len(D), "people", D.person.nunique(), flush=True)

PERS = ["sim_mean", "sim_max", "sim_top5", "dom_share", "dom_n", "auth_n", "hour_p"]
tr, te = D[D.day < MID], D[D.day >= MID].copy()


def fit(cols):
    m = lgb.LGBMClassifier(n_estimators=400, learning_rate=0.05, num_leaves=31, min_child_samples=50, subsample=0.8,
                           subsample_freq=1, colsample_bytree=0.8, verbose=-1, random_state=0)
    return m.fit(tr[cols], tr.y).predict_proba(te[cols])[:, 1]


def per_person(s, within_band=False):
    t = te.assign(s=s)
    out = []
    for _, g in t.groupby("person"):
        if within_band:
            v = [roc_auc_score(h.y, h.s) for _, h in g.groupby("pop_band") if h.y.nunique() == 2 and len(h) >= 10]
            if v:
                out.append(np.mean(v))
        elif g.y.nunique() == 2:
            out.append(roc_auc_score(g.y, g.s))
    return np.median(out), np.mean(np.array(out) > 0.7), len(out)


runs = {"v1: mean taste only": te.sim_mean.to_numpy(), "v2: personal signals (model)": fit(PERS),
        "popularity only (final points)": te.pop_final.to_numpy(), "v2 + popularity (model)": fit(PERS + ["pop_final"])}
print(f"test: {te.person.nunique()} people, Sep 1 - Oct 14")
for name, s in runs.items():
    med, share, n = per_person(s)
    medb, shareb, nb = per_person(s, True)
    print(f"  {name:32s} median AUC {med:.3f} (>0.7: {share:.0%}) | within popularity bands {medb:.3f} (>0.7: {shareb:.0%})", flush=True)
D.to_parquet(os.path.join(H.CACHE, "twin_v2_pairs.parquet"), index=False)
