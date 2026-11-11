"""Cross-domain zero-shot (orchestrator Nov 11, (2)): the uses-trained learned taste scorer (S3np features: kNN sims over
bge-small/bge-base, topic rate, profile size; trained on the length-matched pop-matched uses tasks, no popularity) applied
AS-IS to upvoting launches: profile = the person's stack/review/collection items (product cards; items whose slug equals the
launch's slug are dropped), candidates = that day's line-up (launch text). PH 19-day rows, people with a uses profile.
Compared on the same person-days with the E5 upvote-trained taste logistic and a shuffled-uses-profile control.
    python cross_domain.py <uses2 dir> <workdir tl> <rows19> <e5_ref_rows19> <pinfo dir> <out.json>"""
import glob, json, os, sys, numpy as np, pandas as pd, lightgbm as lgb
U, W, ROWS, REF, PI, OUT = sys.argv[1:7]; rng = np.random.default_rng(0)
P = pd.read_parquet(U + "/export/products.parquet"); pix = {s: i for i, s in enumerate(P.slug)}
E1, E2 = np.load(U + "/emb_small_rich.npy"), np.load(U + "/emb_base_rich.npy")
ptop = {}
for f in glob.glob(os.path.join(PI, "*.json")):
    try: y = json.load(open(f))
    except Exception: continue
    t = {x.get("name") for x in (y.get("topics") or []) if isinstance(x, dict)}
    if y.get("slug") in pix and t: ptop[pix[y["slug"]]] = t
L = pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(os.path.join(W, "launches", "*.parquet")))], ignore_index=True)
L = L.sort_values("updated_at").drop_duplicates("id", keep="last").reset_index(drop=True); lid = {x: i for i, x in enumerate(L.id)}
LS, LB = np.load(W + "/out/launch_emb_small.npy"), np.load(W + "/out/launch_emb_base.npy")
LT = [set(json.loads(s)) if isinstance(s, str) and s.startswith("[") else set() for s in L.topics]; Lslug = L.slug.tolist()
COLS = ["s1_top1", "s1_top5", "s1_mean", "s2_top1", "s2_top5", "s2_mean", "topic_rate", "n_prof"]
def feats(cand_s, cand_b, cand_t, prof):
    n = len(cand_s); F = np.full((n, 8), np.nan)
    for j, (C, E) in enumerate(((cand_s, E1), (cand_b, E2))):
        S = C @ E[prof].T; Ss = np.sort(S, 1); k = min(5, S.shape[1])
        F[:, 3 * j], F[:, 3 * j + 1], F[:, 3 * j + 2] = Ss[:, -1], Ss[:, -k:].mean(1), S.mean(1)
    pt = [ptop.get(i, set()) for i in prof]; nt = sum(1 for t in pt if t) or 1
    F[:, 6] = [sum(1 for t in pt if t & ct) / nt if ct else np.nan for ct in cand_t]; F[:, 7] = np.log1p(len(prof))
    return F
# train S3np on the length-matched uses tasks (real profiles, pop-matched)
T = pd.read_parquet(U + "/export/eval_sets_lenmatched.parquet"); X, Y = [], []
for r in T.itertuples():
    cand = np.array([pix[r.heldout]] + [pix[s] for s in r.negatives]); prof = np.array([pix[s] for s in r.profile])
    X.append(feats(E1[cand], E2[cand], [ptop.get(c, set()) for c in cand], prof)); Y.append(np.r_[1, np.zeros(len(cand) - 1)])
m = lgb.LGBMClassifier(n_estimators=300, learning_rate=0.05, num_leaves=31, min_child_samples=200, subsample=0.8, subsample_freq=1,
                       colsample_bytree=0.8, verbose=-1).fit(np.concatenate(X), np.concatenate(Y))
print("uses model trained", flush=True)
PE = pd.read_parquet(U + "/export/people.parquet"); uses = {p: [pix[s] for k in ("stack", "review", "collection") for s in r[k] if s in pix] for p, r in zip(PE.person_id, PE.to_dict("records"))}
pl = list(uses)
R = pd.read_parquet(ROWS); R = R[R.person_id.isin(uses) & R.launch_id.isin(lid)].copy(); R["li"] = R.launch_id.map(lid)
R = R.merge(pd.read_parquet(REF)[["d", "person_id", "launch_id", "product_only"]], on=["d", "person_id", "launch_id"], how="left")
R = R[R.groupby(["d", "person_id"]).y.transform("sum") > 0]
for (p, d), x in R.groupby(["person_id", "d"]):
    li = x.li.to_numpy(); slugs = {Lslug[i] for i in li}
    for col, who_ in (("zs", p), ("zs_sh", pl[rng.integers(len(pl))])):
        prof = np.array([i for i in uses[who_] if P.slug[i] not in slugs])
        if len(prof) == 0: continue
        R.loc[x.index, col] = m.predict_proba(feats(LS[li], LB[li], [LT[i] for i in li], prof))[:, 1]
def per_day(s):
    D = R.dropna(subset=[s]).copy(); D["v"] = D[s] + rng.random(len(D)) * 1e-9
    D["r"] = D.groupby(["d", "person_id"]).v.rank(ascending=False, method="first")
    h = D.groupby(["d", "person_id"]).apply(lambda g: pd.Series({"h1": float(g.y[g.r <= 1].sum() > 0), "h3": float(g.y[g.r <= 3].sum() > 0),
        "auc": np.mean(g.v[g.y == 1].to_numpy()[:, None] > g.v[g.y == 0].to_numpy()[None, :]) if (g.y == 0).any() else np.nan}))
    return h.groupby(level=0).mean()
def boot(v, B=4000):
    v = np.asarray(v, float); v = v[~np.isnan(v)]; bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(B)]
    return [round(float(v.mean()), 4), round(float(np.percentile(bs, 2.5)), 4), round(float(np.percentile(bs, 97.5)), 4)]
R["rand"] = rng.random(len(R))
T_ = {s: per_day(s) for s in ("rand", "product_only", "zs", "zs_sh")}
res = {"voting_person_days": int(R.groupby(["d", "person_id"]).ngroups), "people": int(R.person_id.nunique()), "days": int(R.d.nunique())}
for s, t in T_.items(): res[s] = {k: boot(t[k]) for k in ("h1", "h3", "auc")}
res["zero-shot minus E5 upvote logistic (paired by day)"] = {k: boot(T_["zs"][k] - T_["product_only"][k]) for k in ("h1", "h3", "auc")}
res["zero-shot personal (zs - shuffled)"] = {k: boot(T_["zs"][k] - T_["zs_sh"][k]) for k in ("h1", "h3", "auc")}
json.dump(res, open(OUT, "w"), indent=1); print(json.dumps(res, indent=1))
