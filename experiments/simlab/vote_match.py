"""Vote-specific match (orchestrator 00:05Z Nov 12): can a person's UPVOTE history pick who upvotes a launch better than activity?
People: all complete pool people (store_v3) with >= 1 dated upvote before the launch day; also reported on the 5,096 website
bundle people. Test launches: the same 114 Aug-Oct launches as voters_eval.py (>= 30 voters among the 5,096). Upvotes are
dated by the voted launch's day; history = upvotes on launches dated strictly before the launch day.
Features per (person, launch), vectorised with a sparse person x launch matrix of prior upvotes:
  sim_soft  log-sum-exp (tau = 20) of gemini-256 cosine between the launch and the person's prior upvoted launches (soft top-k)
  sim_mean  mean cosine over prior upvotes
  topic     share of prior upvotes sharing a topic with the launch
  ties      prior upvotes on launches sharing a real maker/poster with the launch (log1p)
  activity  log1p prior upvotes; recency bucket (days since last prior upvote)
Scorers: SIM (sim_soft), PRODUCT (logistic on sim_soft, sim_mean, topic + activity), TIES (ties then activity), FULL (logistic
on all), fitted on May-Jul launches with >= 30 complete voters (negatives subsampled 20:1); controls RANDOM, ACTIVITY-MATCHED
(same activity decile x recency bucket as each top-K pick), MOST-ACTIVE. precision@100/500, launch-bootstrap 95% CIs, paired.
    python vote_match.py <v3 dir> <launches dir> <landing out dir (launch_emb256.npy)> <uses2 export> <out dir>
"""
import glob, json, os, sys
import numpy as np, pandas as pd
from scipy import sparse
from sklearn.linear_model import LogisticRegression

V3, LDIR, LAND, EXP, OUT = sys.argv[1:6]; os.makedirs(OUT, exist_ok=True); rng = np.random.default_rng(0)
L = pd.concat([pd.read_parquet(f) for f in glob.glob(os.path.join(LDIR, "*.parquet"))]).sort_values("updated_at").drop_duplicates("id", keep="last")
L = L[L.daily_rank.notna() & L.votes.notna() & (L.day < "2026-11-11")].copy().sort_values(["day", "id"]).reset_index(drop=True)   # landing_retrieval order
L["id"] = L.id.astype(str); E = np.load(os.path.join(LAND, "launch_emb256.npy")); assert len(E) == len(L)
L["tp"] = [set(json.loads(t)) if isinstance(t, str) and t.startswith("[") else set() for t in L.topics]
L["team"] = [{str(u).lower() for u in (json.loads(m) if isinstance(m, str) and m.startswith("[") else []) if u and not str(u).startswith("[")} | ({str(p).lower()} if p else set()) for m, p in zip(L.makers, L.poster)]
lix = {i: k for k, i in enumerate(L.id)}; ldays = L.day.to_numpy()
comp = set(pd.read_parquet(os.path.join(V3, "persons.parquet")).query("complete").person_id)
ev = pd.read_parquet(os.path.join(V3, "events.parquet"), columns=["person_id", "kind", "target_id"]).query("kind == 'upvote'")
ev = ev[ev.person_id.isin(comp)]; ev["target_id"] = ev.target_id.astype(str); ev = ev[ev.target_id.isin(lix)].drop_duplicates(["person_id", "target_id"])
people = sorted(ev.person_id.unique()); pix = {p: i for i, p in enumerate(people)}; NP = len(people)
M = sparse.csr_matrix((np.ones(len(ev)), (ev.person_id.map(pix), ev.target_id.map(lix))), shape=(NP, len(L)))
MT = M.T.tocsr()
Pe = pd.read_parquet(os.path.join(EXP, "people.parquet")); site_people = np.array([pix[p] for p in Pe.person_id if p in pix])
print("complete people with dated upvotes", NP, "upvotes", M.nnz, "site people in pool", len(site_people), flush=True)


def voters_of(k): return set(MT[k].indices.tolist())


def feats(k):
    d = ldays[k]; prior = (ldays < d).astype(float)
    s = E @ E[k]; Mp = M.multiply(prior).tocsr(); n = np.asarray(Mp.sum(1)).ravel()
    soft = np.log(Mp @ np.exp(20 * (s - 1)) + 1e-12) / 20 + 1; mean = (Mp @ s) / np.maximum(n, 1)
    tmatch = np.array([float(bool(t & L.tp.iat[k])) for t in L.tp]); topic = (Mp @ tmatch) / np.maximum(n, 1)
    tie = np.array([float(bool(t & L.team.iat[k])) for t in L.team]) if L.team.iat[k] else np.zeros(len(L)); tie[k] = 0
    ties = np.log1p(Mp @ (tie * prior))
    # recency: last prior upvote day
    lastday = np.full(NP, -1.0); dnum = pd.to_datetime(ldays).to_numpy().astype("datetime64[D]").astype(np.int64)
    Mpc = Mp.tocoo(); np.maximum.at(lastday, Mpc.row, dnum[Mpc.col])
    rec = np.where(lastday < 0, 9999, dnum[k] - lastday)
    X = np.c_[np.where(n > 0, soft, 0), mean, topic, ties, np.log1p(n), np.digitize(rec, [7, 30, 90])]
    return X, n


COLS = ["sim_soft", "sim_mean", "topic", "ties", "act", "rec"]
cnt = np.diff(MT.indptr)
train_k = [k for k in range(len(L)) if "2026-05-01" <= ldays[k] <= "2026-07-31" and cnt[k] >= 30]
Pe_ids = set(site_people.tolist())
test_k = [k for k in range(len(L)) if "2026-08-01" <= ldays[k] <= "2026-10-31" and len(voters_of(k) & Pe_ids) >= 30]
print("train launches", len(train_k), "test launches", len(test_k), flush=True)
Xs, ys = [], []
for k in rng.choice(train_k, min(120, len(train_k)), replace=False):
    X, n = feats(k); V = voters_of(k); ok = np.flatnonzero(n > 0); pos = [j for j in ok if j in V]; neg = rng.choice([j for j in ok if j not in V], min(len(ok), 20 * max(1, len(pos))), replace=False)
    Xs.append(X[pos + list(neg)]); ys += [1] * len(pos) + [0] * len(neg)
Xtr, ytr = np.vstack(Xs), np.array(ys); mu, sd = Xtr.mean(0), Xtr.std(0) + 1e-9
FULL = LogisticRegression(C=1.0, max_iter=2000).fit((Xtr - mu) / sd, ytr)
PI = [0, 1, 2, 4, 5]; PROD = LogisticRegression(C=1.0, max_iter=2000).fit(((Xtr - mu) / sd)[:, PI], ytr)
AI = [4, 5]; ACTREC = LogisticRegression(C=1.0, max_iter=2000).fit(((Xtr - mu) / sd)[:, AI], ytr)
print("FULL coef", dict(zip(COLS, np.round(FULL.coef_[0], 3))), flush=True)
rows = []
for k in test_k:
    X, n = feats(k); V = voters_of(k); Z = (X - mu) / sd
    sc = {"SIM": X[:, 0] + 1e-6 * X[:, 4], "PRODUCT": PROD.decision_function(Z[:, PI]), "TIES": X[:, 3] + 1e-3 * X[:, 4], "FULL": FULL.decision_function(Z), "MOST-ACTIVE": X[:, 4],
          "ACTREC": ACTREC.decision_function(Z[:, AI])}
    adec = np.searchsorted(np.percentile(X[:, 4], np.arange(10, 100, 10)), X[:, 4]); cell = {}
    for pool_name, pool in (("all complete", np.flatnonzero(n > 0)), ("site 5,096", site_people[n[site_people] > 0])):
        cell = {}
        for j in pool: cell.setdefault((adec[j], X[j, 5]), []).append(j)
        base = np.mean([j in V for j in pool])
        for K in (100, 500):
            r = {"launch": k, "pool": pool_name, "K": K, "base": base, "RANDOM": np.mean([j in V for j in rng.choice(pool, K, replace=False)])}
            for nm, s in sc.items():
                top = pool[np.argsort(-s[pool])[:K]]; r[nm] = np.mean([j in V for j in top])
                if nm == "FULL":
                    ts = set(top.tolist()); am = [rng.choice([x for x in cell[(adec[j], X[j, 5])] if x not in ts] or cell[(adec[j], X[j, 5])]) for j in top]
                    r["ACTIVITY-MATCHED (to FULL top)"] = np.mean([j in V for j in am])
            rows.append(r)
D = pd.DataFrame(rows)


def boot(v, B=4000):
    v = np.asarray(v, float); bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(B)]
    return [round(float(v.mean()) * 100, 2), round(float(np.percentile(bs, 2.5)) * 100, 2), round(float(np.percentile(bs, 97.5)) * 100, 2), int(len(v))]


res = {"design": __doc__.split("\n    python")[0], "people": NP, "train_launches": len(train_k), "test_launches": len(test_k), "coef_full": dict(zip(COLS, FULL.coef_[0].round(3).tolist()))}
for (pool, K), g in D.groupby(["pool", "K"]):
    cols = ["base", "RANDOM", "SIM", "PRODUCT", "TIES", "FULL", "ACTIVITY-MATCHED (to FULL top)", "MOST-ACTIVE", "ACTREC"]
    res[f"{pool} K{K}"] = {c: boot(g[c]) for c in cols} | {f"{c} - MOST-ACTIVE (paired)": boot(g[c] - g["MOST-ACTIVE"]) for c in ("SIM", "PRODUCT", "TIES", "FULL")} \
        | {"FULL - ACTIVITY-MATCHED (paired)": boot(g["FULL"] - g["ACTIVITY-MATCHED (to FULL top)"])} \
        | {f"{c} - ACTREC (paired)": boot(g[c] - g["ACTREC"]) for c in ("SIM", "PRODUCT", "TIES", "FULL")}
json.dump(res, open(os.path.join(OUT, "vote_match.json"), "w"), indent=1)
for k, v in res.items():
    if isinstance(v, dict) and "base" in v: print(k, {c: x[:3] for c, x in v.items()})

# ---------- export (product-only scorer) as an anonymous bundle for a "likely voters" view
# Rows = complete people with dated upvotes, shuffled; no ids. Each row's history = indices into the public launch table
# (upvoted launch embeddings). A per-person upvote list is a fingerprint: keep the bundle SERVER-SIDE and show aggregates only.
perm = rng.permutation(NP); Mr = M[perm].tocsr()
dnum = pd.to_datetime(ldays).to_numpy().astype("datetime64[D]").astype(np.int64)
topics_v = sorted({t for s in L.tp for t in s}); tix = {t: i for i, t in enumerate(topics_v)}
tp_ptr = np.r_[0, np.cumsum([len(s) for s in L.tp])]; tp_idx = np.array([tix[t] for s in L.tp for t in sorted(s)], np.int16)
last = np.full(NP, -1, np.int64); c = Mr.tocoo(); np.maximum.at(last, c.row, dnum[c.col])
bf = os.path.join(OUT, "voter_bundle_v1.npz")
np.savez_compressed(bf, launch_emb=E.astype(np.float16), launch_day_num=dnum.astype(np.int32), topic_ptr=tp_ptr.astype(np.int32), topic_idx=tp_idx,
                    topic_names=np.array(topics_v), person_ptr=Mr.indptr.astype(np.int64), person_launches=Mr.indices.astype(np.int16 if len(L) < 32767 else np.int32),
                    last_upvote_day_num=last.astype(np.int32), coef=PROD.coef_[0].astype(np.float32), intercept=np.float32(PROD.intercept_[0]),
                    mu=mu[PI].astype(np.float32), sd=sd[PI].astype(np.float32), feature_names=np.array([COLS[i] for i in PI]), tau=np.float32(20.0),
                    recency_bins=np.array([7, 30, 90], np.int32), model=np.array("gemini-embedding-001 SEMANTIC_SIMILARITY 256-d L2"))
# self-check on one test launch: bundle recipe vs in-script PRODUCT score
k = test_k[0]; Xk, nk = feats(k); ref = PROD.decision_function(((Xk - mu) / sd)[:, PI])[perm]
z = np.load(bf); q = z["launch_emb"].astype(np.float32)[k]; Eb = z["launch_emb"].astype(np.float32)
prior = z["launch_day_num"] < z["launch_day_num"][k]; s = Eb @ q
chk = []
for r_ in range(0, NP, max(1, NP // 300)):
    li = z["person_launches"][z["person_ptr"][r_]:z["person_ptr"][r_ + 1]]; li = li[prior[li]]
    if not len(li): continue
    ss = s[li]; soft = np.log(np.exp(20 * (ss - 1)).sum() + 1e-12) / 20 + 1
    tq = set(z["topic_idx"][z["topic_ptr"][k]:z["topic_ptr"][k + 1]].tolist())
    top = np.mean([bool(tq & set(z["topic_idx"][z["topic_ptr"][x]:z["topic_ptr"][x + 1]].tolist())) for x in li])
    lastp = max(z["launch_day_num"][li]); rec = np.digitize(z["launch_day_num"][k] - lastp, [7, 30, 90])
    f = (np.array([soft, ss.mean(), top, np.log1p(len(li)), rec]) - z["mu"]) / z["sd"]
    chk.append(abs(float(f @ z["coef"] + z["intercept"]) - ref[r_]))
    if len(chk) == 1: print("selfcheck row", r_, "bundle feats", np.round([soft, ss.mean(), top, np.log1p(len(li)), rec], 4), "script feats", np.round(Xk[perm[r_]][PI], 4), flush=True)
res["bundle"] = {"file": bf, "bytes": os.path.getsize(bf), "people": int(NP), "launches": int(len(L)), "selfcheck_max_abs_diff": round(float(max(chk)), 5),
                 "privacy": "anonymous shuffled rows, but each row is a list of public launch upvotes (a fingerprint): server-side only, show aggregates"}
json.dump(res, open(os.path.join(OUT, "vote_match.json"), "w"), indent=1); print(res["bundle"])
