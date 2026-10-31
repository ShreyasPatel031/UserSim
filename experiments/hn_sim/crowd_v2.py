"""Crowd v2: the v2 individual model (twin_v2.py) run for a panel of real people over every new post, at posting time.

Panel: the PANEL most active commenters in the 180 days before CUT (profiles from data before CUT only). The v2
engagement model (personal signals only: closest past stories, mean taste, domain / submitter history, presence at
the posting hour) is trained on twin_v2_pairs.parquet days before CUT2 (Jul-Aug), then applied to each Jul 1 - Oct 14
post x every panel person. Per post:
  c2_sum      expected engagers (sum of P over the panel)
  c2_scout    the same over /new browsers (share of comments within 60 min of posting > 0.3)
  c2_top50    sum of the 50 highest P
  c2_n20      people with P > 0.2
Then the at-posting classifier (as audience.py): post features + nearest past titles + embedding (+ crowd v1) vs the
same + crowd v2, trained on posts Jul-Aug, tested Sep 1 - Oct 14; paired-by-day difference in winners caught.
-> <cache>/crowd_v2_feats.parquet

    python crowd_v2.py [panel=6000]
"""
import json
import os
import sys
import time
from urllib.parse import urlsplit

import lightgbm as lgb
import numpy as np
import pandas as pd
import scipy.sparse as sp
from sklearn.metrics import average_precision_score, roc_auc_score

import emb_io
import top100 as H

PANEL = int(sys.argv[1]) if len(sys.argv) > 1 else 6000
CUT, CUT2, END = "2026-07-01", "2026-09-01", "2026-10-14"
t_cut = pd.Timestamp(CUT, tz="UTC").timestamp()
HIST = 100
rng = np.random.default_rng(0)

emb, ei = emb_io.load()
p = H.stories().set_index("post_id")
dom = p.url.map(lambda u: urlsplit(u).netloc.lower().removeprefix("www.") if isinstance(u, str) and u else "self")

# ---- the v2 engagement model (personal signals only), trained on Jul-Aug pairs ---------------------------------
PERS = ["sim_mean", "sim_max", "sim_top5", "dom_share", "dom_n", "auth_n", "hour_p"]
pairs = pd.read_parquet(os.path.join(H.CACHE, "twin_v2_pairs.parquet"), columns=PERS + ["y", "day"])
pairs = pairs[pairs.day < CUT2]
model = lgb.LGBMClassifier(n_estimators=400, learning_rate=0.05, num_leaves=31, min_child_samples=50, subsample=0.8,
                           subsample_freq=1, colsample_bytree=0.8, verbose=-1, random_state=0).fit(pairs[PERS], pairs.y)
del pairs
print("v2 model trained", flush=True)

# ---- panel profiles, data before CUT -------------------------------------------------------------------------
c = pd.read_parquet(os.path.join(H.CACHE, "bq_comments.parquet"), columns=["person", "story_id", "created_at_i"])
c = c[(c.created_at_i < t_cut) & (c.created_at_i >= t_cut - 540 * 86400) & c.story_id.isin(ei.index)]
act = c[c.created_at_i >= t_cut - 180 * 86400].groupby("person").size()
panel = act.nlargest(PANEL).index
c = c[c.person.isin(panel)].sort_values("created_at_i")
pi = pd.Series(np.arange(len(panel)), index=panel)
n = len(panel)
w = np.exp(-(t_cut - c.created_at_i.to_numpy()) / (180 * 86400) * np.log(2)).astype(np.float32)
rp, rs = pi[c.person].to_numpy(), ei[c.story_id].to_numpy()
taste = np.zeros((n, 768), np.float32)
for k in range(0, len(rp), 300000):
    np.add.at(taste, rp[k:k + 300000], np.asarray(emb[rs[k:k + 300000]], np.float32) * w[k:k + 300000, None])
taste /= np.linalg.norm(taste, axis=1, keepdims=True) + 1e-9
# last HIST engaged stories per person -> one matrix (n*HIST x 768), padded with zeros
last = c.drop_duplicates(["person", "story_id"], keep="last").groupby("person").story_id.apply(lambda s: s.to_numpy()[-HIST:])
HM = np.zeros((n * HIST, 768), np.float16)
for person, ids in last.items():
    i = pi[person]
    HM[i * HIST:i * HIST + len(ids)] = emb[ei[ids].to_numpy()]
HMt = HM.astype(np.float32).T.copy()
del HM
# domain / submitter counts as sparse person x key matrices
c["dom"] = c.story_id.map(dom).to_numpy()
c["auth"] = c.story_id.map(p.author).fillna("").to_numpy()
dkeys = pd.Index(c.dom.unique())
akeys = pd.Index(c.auth.unique())
DM = sp.csr_matrix((np.ones(len(c), np.float32), (rp, dkeys.get_indexer(c.dom))), shape=(n, len(dkeys))).tocsc()
AM = sp.csr_matrix((np.ones(len(c), np.float32), (rp, akeys.get_indexer(c.auth))), shape=(n, len(akeys))).tocsc()
tot = np.asarray(DM.sum(1)).ravel()
hour = np.full((n, 24), 1.0, np.float32)
rb = c[c.created_at_i >= t_cut - 180 * 86400]
np.add.at(hour, (pi[rb.person].to_numpy(), ((rb.created_at_i // 3600) % 24).to_numpy()), 1)
hour /= hour.sum(1, keepdims=True)
c["lat"] = c.created_at_i - c.story_id.map(p.created_at_i).to_numpy()
scout = (c.assign(s=(c.lat >= 0) & (c.lat <= 3600)).groupby("person").s.mean().reindex(panel).fillna(0).to_numpy() > 0.3)
print(f"panel {n}; /new browsers {scout.sum()}; history matrix {HMt.shape}", flush=True)

# ---- apply to every post ------------------------------------------------------------------------------------------
q = p[(p.day >= CUT) & (p.day <= END) & p.index.isin(ei.index)]
if os.environ.get("CV2_LIMIT"):                                           # smoke test: a few posts, no evaluation
    q = q.iloc[:int(os.environ["CV2_LIMIT"])]
qids = q.index.to_numpy()
qh = ((q.created_at_i.to_numpy() // 3600) % 24).astype(int)
qd = dkeys.get_indexer(dom.reindex(qids).fillna("self"))
qa = akeys.get_indexer(q.author.fillna(""))
out = {k: np.zeros(len(q), np.float32) for k in ("c2_sum", "c2_scout", "c2_top50", "c2_n20")}
CH = 32
t0 = time.time()
for s0 in range(0, len(q), CH):
    sl = slice(s0, s0 + CH)
    E = np.asarray(emb[ei[qids[sl]].to_numpy()], np.float32)            # posts x 768
    m = len(E)
    S = (E @ HMt).reshape(m, n, HIST)                                     # posts x people x HIST
    S.partition(HIST - 5, axis=2)                                         # the 5 closest, unordered, at the end
    f = np.empty((m, n, len(PERS)), np.float32)
    f[:, :, 0] = E @ taste.T
    f[:, :, 1] = S[:, :, -5:].max(2)
    f[:, :, 2] = S[:, :, -5:].mean(2)
    for j in range(m):
        dn = DM[:, qd[sl][j]].toarray().ravel() if qd[sl][j] >= 0 else np.zeros(n, np.float32)
        an = AM[:, qa[sl][j]].toarray().ravel() if qa[sl][j] >= 0 else np.zeros(n, np.float32)
        f[j, :, 3] = dn / np.maximum(tot, 1)
        f[j, :, 4] = dn
        f[j, :, 5] = an
        f[j, :, 6] = hour[:, qh[sl][j]]
    P = model.predict_proba(f.reshape(-1, len(PERS)))[:, 1].reshape(m, n)
    out["c2_sum"][sl] = P.sum(1)
    out["c2_scout"][sl] = P[:, scout].sum(1)
    out["c2_top50"][sl] = np.sort(P, axis=1)[:, -50:].sum(1)
    out["c2_n20"][sl] = (P > 0.2).sum(1)
    if s0 % (CH * 300) == 0:
        print(f"{s0} / {len(q)} posts, {time.time() - t0:.0f}s", flush=True)
F = pd.DataFrame(out)
F["post_id"] = qids
F.to_parquet(os.path.join(H.CACHE, "crowd_v2_feats.parquet"), index=False)
print("saved crowd_v2_feats", F.shape, flush=True)
if os.environ.get("CV2_LIMIT"):
    print(F.describe().round(3).to_string())
    sys.exit(0)

# ---- at-posting evaluation (as audience.py) ------------------------------------------------------------------
A = pd.read_parquet(os.path.join(H.CACHE, "audience_feats.parquet"))
B = pd.read_parquet(os.path.join(H.CACHE, "daily_cache.parquet"))
bcols = [x for x in B.columns if x.startswith("b_") and not x.startswith(("b_w30_", "b_w60_"))]
B = B[["post_id", "text_score"] + bcols].drop_duplicates("post_id")
Q = q.reset_index()[["post_id", "day"]].merge(B, on="post_id", how="left").merge(A, on="post_id", how="left").merge(F, on="post_id", how="left")
L = pd.read_json(os.path.join(H.CACHE, "frontday.jsonl"), lines=True, dtype={"day": str})
Q["list_rank"] = Q.post_id.map(L.groupby("post_id")["rank"].min()).fillna(999)
tr, te = (Q.day < CUT2).to_numpy(), (Q.day >= CUT2).to_numpy()
POST = ["text_score"] + bcols
KNN = ["knn_lp", "knn_100", "knn_t30", "knn_sim"]
EMB = [f"emb{j}" for j in range(64)]
AUD = ["aud_sum", "aud_cube", "aud_fans", "scout_sum", "scout_cube", "scout_fans", "fans_any", "top50_sim"]
C2 = list(out)
SETS = {"post features (baseline)": POST, "best so far: + past titles + embedding + crowd v1": POST + KNN + EMB + AUD,
        "+ crowd v2 (individual model x panel)": POST + KNN + EMB + AUD + C2, "crowd v2 alone": C2}
per_day = {}
for top in (30, 10):
    y = (Q.list_rank <= top).to_numpy()
    for name, cols in SETS.items():
        mdl = lgb.LGBMClassifier(n_estimators=600, learning_rate=0.03, num_leaves=31, min_child_samples=30, subsample=0.8,
                                 subsample_freq=1, colsample_bytree=0.8, verbose=-1, random_state=0).fit(Q.loc[tr, cols], y[tr])
        s = mdl.predict_proba(Q.loc[te, cols])[:, 1]
        T = Q[te].assign(s=s, y=y[te])
        cap = T.groupby("day").apply(lambda g: g.nlargest(top, "s").y.sum() / max(g.y.sum(), 1))
        cap100 = T.groupby("day").apply(lambda g: g.nlargest(100, "s").y.sum() / max(g.y.sum(), 1))
        per_day[(top, name)] = cap
        print(json.dumps({"target": f"top {top}", "inputs": name, "AUC": round(roc_auc_score(y[te], s), 3),
                          "avg_precision": round(average_precision_score(y[te], s), 3),
                          f"winners_in_top{top}": round(cap.mean(), 3), "winners_in_top100": round(cap100.mean(), 3)}), flush=True)
    d = (per_day[(top, "+ crowd v2 (individual model x panel)")] - per_day[(top, "best so far: + past titles + embedding + crowd v1")]).to_numpy()
    boot = [rng.choice(d, len(d)).mean() for _ in range(2000)]
    print(f"  top {top}: crowd v2 vs best so far, winners caught per day: {d.mean():+.3f} [{np.percentile(boot, 2.5):+.3f}, {np.percentile(boot, 97.5):+.3f}]", flush=True)
