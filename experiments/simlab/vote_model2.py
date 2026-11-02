"""E1 v2: the generative vote model containing the launch model (direction A, docs/reviews/2026-11-02_direction_review.md),
pre-launch only. Poisson LightGBM on final votes, rolling monthly (train on every earlier month, test the next), 3 seeds.
Variants (pool source SRC, default psa):
  lm            the launch model alone (ctrl.py `all`, out of sample; mu = expm1(all), rescaled on the training months)
  off           starts from the launch model (init score = log of its mu) and learns multiplicative corrections from the
                pool (S = <src>_ev), the audience sizes (PH followers of makers / hunter, X followers, promotion) and a
                day-level term (line-up size, weekday, the day's pool reach and summed pool picks, the day's summed
                launch-model votes); non-decreasing in the pool and in every audience size
  off+maker     + per-maker / per-hunter conversion from their earlier launches (days strictly before): how far each
                earlier launch beat the launch model (log residual) and its pool shock (log((R+1)/(S+1)) less the day's
                mean, as E0), as shrunk means (sum / (n + 2): a first-timer gets the prior 0) plus counts
  off+maker-pool  the same without the pool (ablation)
  full+maker    no offset: the launch model's own 207 inputs + pool + audiences + day + maker terms, learned jointly
Scores, every variant on the same launches: daily and weekly top 3/5/10 on Product Hunt's real ranks (out_dailyRank,
out_weeklyRank; weeks Monday-Sunday) and test Poisson log-likelihood per launch, each paired against the launch model
alone (bootstrap over days / weeks, 10,000).
usage: SIMLAB_DATA=data_v2 python -m simlab.vote_model2 [psa] [psx ...] -> reports/vote_model2_<srcs>.json, ph_predict/results/vote_model2_<srcs>.parquet"""
import json, os, sys
from collections import defaultdict
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); PH = os.path.join(os.path.dirname(HERE), "ph_predict")
AUD = ["ph_maker_sum_followers", "ph_hunter_followers", "x_maker_sum_followers", "x_company_followers", "promo_reactions", "promo_posts"]
DAY = ["day_n", "day_wd", "day_reach", "day_pool_sum", "day_lm_sum"]
MAKER = ["mk_res", "mk_n", "mk_last", "mk_pshock", "hu_res", "hu_n", "hu_last", "hu_pshock"]
K_PRIOR = 2.0


def load(srcs):
    cwd = os.getcwd(); os.chdir(PH); sys.path.insert(0, PH)
    try:
        import model as M
        from buildcache import build_cached
        B = build_cached(); B["id"] = B.id.astype(str)
        lmc = M.cols(B, M.LIVE_SOURCES + M.PAGE_SOURCES)
        C = pd.read_parquet("results/ctrl_preds.parquet"); C["id"] = C.id.astype(str); C = C.drop_duplicates("id")
        S = {s: pd.DataFrame.from_dict(json.load(open(f"data/{s}_features.json")), orient="index")[[f"{s}_ev", f"{s}_reach"]] for s in srcs}
    finally:
        os.chdir(cwd)
    from . import store
    P, I, E = store.load(); I = I.assign(id=I.id.astype(str))
    A = C[["id", "day", "dailyRank", "logv", "all"]].merge(B[["id", "votes"] + sorted(set(lmc + AUD) - {"id", "votes"})], on="id")
    A = A.merge(I[["id", "out_weeklyRank", "makers", "poster"]], on="id")
    for s, D in S.items():
        A = A.merge(D, left_on="id", right_index=True)
    A["votes"] = pd.to_numeric(A.votes, errors="coerce"); A = A[A.votes.notna()].reset_index(drop=True)
    A["mon"] = A.day.str[:7]
    # real pool voters on launch day (for the earlier launches' pool shock only)
    day = dict(zip(I.id, I.day)); E = E.assign(item=E.item.astype(str))
    A["R"] = A.id.map(E[E.item.map(day) == E.date].groupby("item").person.nunique()).fillna(0)
    return A, [c for c in lmc if c in A.columns]


def day_terms(A, src):
    g = A.groupby("day")
    A["day_n"] = g.id.transform("size"); A["day_wd"] = pd.to_datetime(A.day).dt.weekday
    A["day_reach"] = g[f"{src}_reach"].transform("mean"); A["day_pool_sum"] = g[f"{src}_ev"].transform("sum")
    A["day_lm_sum"] = np.expm1(A["all"]).groupby(A.day).transform("sum")
    return A


def maker_terms(A, src):
    """Per launch, from earlier launches (strictly earlier days) of the same makers / hunter: shrunk mean log residual
    vs the launch model, the last residual, count, and shrunk mean pool shock. Makers listed on >30 launches are left out."""
    A = A.sort_values("day").reset_index(drop=True)
    res = (np.log1p(A.votes) - A["all"]).values
    ps = np.log((A.R + 1) / (A[f"{src}_ev"] + 1)); ps = (ps - ps.groupby(A.day).transform("mean")).values
    mk = [set(json.loads(m)) - {""} for m in A.makers]; hu = A.poster.fillna("").values
    count = defaultdict(int)
    for ms in mk:
        for m in ms:
            count[m] += 1
    hist_m, hist_h = defaultdict(list), defaultdict(list)   # person -> [(residual, pool shock)] of finished launches
    out = {c: np.zeros(len(A)) for c in MAKER}
    days = A.day.values; i = 0
    while i < len(A):
        j = i
        while j < len(A) and days[j] == days[i]:
            j += 1
        for k in range(i, j):   # features from launches of earlier days only
            ms = [m for m in mk[k] if count[m] <= 30]
            for pre, H in (("mk", [r for m in ms for r in hist_m[m]]), ("hu", hist_h[hu[k]] if hu[k] and hu[k] not in mk[k] else [])):
                n = len(H)
                out[f"{pre}_n"][k] = n
                out[f"{pre}_res"][k] = sum(r for r, _ in H) / (n + K_PRIOR)
                out[f"{pre}_pshock"][k] = sum(p for _, p in H) / (n + K_PRIOR)
                out[f"{pre}_last"][k] = H[-1][0] if n else 0.0
        for k in range(i, j):   # then this day's launches become history
            for m in mk[k]:
                hist_m[m].append((res[k], ps[k]))
            if hu[k] and hu[k] not in mk[k]:
                hist_h[hu[k]].append((res[k], ps[k]))
        i = j
    for c, v in out.items():
        A[c] = v
    return A


def fit(tr, te, feats, mono, offset):
    import lightgbm as lgb
    kw = dict(objective="poisson", n_estimators=300, learning_rate=0.02, num_leaves=15, min_child_samples=30, subsample=0.8,
              subsample_freq=1, colsample_bytree=0.7, verbose=-1, n_jobs=8, monotone_constraints=[1 if f in mono else 0 for f in feats])
    out = []
    for seed in range(3):
        m = lgb.LGBMRegressor(random_state=seed, **kw)
        if offset:
            c = np.log(tr.votes.sum() / np.expm1(tr["all"]).sum())   # rescale the launch model's mean on the training months
            m.fit(tr[feats], tr.votes, init_score=np.log(np.expm1(tr["all"]).clip(lower=0.5)) + c)
            out.append(np.exp(m.predict(te[feats], raw_score=True) + np.log(np.expm1(te["all"]).clip(lower=0.5)) + c))
        else:
            out.append(m.fit(tr[feats], tr.votes).predict(te[feats]))
    return np.mean(out, 0)


def boards(T, col, rng, base=None):
    from scipy.stats import poisson
    r = {}
    for board, key, rank in (("daily", "day", "dailyRank"), ("weekly", "week", "out_weeklyRank")):
        for k in (3, 5, 10):
            s = {g: len(set(d.nlargest(k, col).id) & set(d[d[rank] <= k].id)) / k for g, d in T.groupby(key) if (d[rank] <= k).sum() == k}
            s = pd.Series(s); r[f"{board}_top{k}"] = round(100 * float(s.mean()), 1)
            if base is not None:
                b = pd.Series({g: len(set(d.nlargest(k, base).id) & set(d[d[rank] <= k].id)) / k for g, d in T.groupby(key) if (d[rank] <= k).sum() == k})
                d = (s - b).values; bs = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(10000)]
                r[f"{board}_top{k}_vs_lm"] = [round(100 * float(d.mean()), 1), [round(100 * float(x), 1) for x in np.percentile(bs, [2.5, 97.5])], len(d)]
    ll = pd.Series(poisson.logpmf(T.votes.round(), np.clip(T[col], 1e-6, None)), index=T.index)
    r["loglik"] = round(float(ll.mean()), 3)
    if base is not None:
        llb = pd.Series(poisson.logpmf(T.votes.round(), np.clip(T["mu_lm"], 1e-6, None)), index=T.index)
        d = (ll - llb).groupby(T.day).mean().values; bs = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(10000)]
        r["loglik_vs_lm"] = [round(float(d.mean()), 3), [round(float(x), 3) for x in np.percentile(bs, [2.5, 97.5])], len(d)]
    return r


def main(srcs):
    A, lmc = load(srcs)
    A["week"] = pd.to_datetime(A.day).dt.strftime("%G-W%V")
    res = {"launches": None, "variants": {}}
    T_all = []
    for src in srcs:
        D = maker_terms(day_terms(A.copy(), src), src); pool = f"{src}_ev"
        V = {"off": ([pool] + AUD + DAY, True), "off+maker": ([pool] + AUD + DAY + MAKER, True),
             "off+maker-pool": (AUD + DAY + MAKER, True), "full+maker": (sorted(set(lmc + [pool] + AUD + DAY + MAKER)), False)}
        months = sorted(D.mon.unique()); out = []
        for m in months[1:]:
            tr, te = D[D.mon < m], D[D.mon == m].copy()
            c = tr.votes.sum() / np.expm1(tr["all"]).sum(); te["mu_lm"] = np.expm1(te["all"]).clip(lower=0.5) * c
            for name, (feats, off) in V.items():
                te[f"mu_{name}|{src}"] = fit(tr, te, feats, set([pool] + AUD), off)
            out.append(te); print(src, "month", m, "train", len(tr), "test", len(te), flush=True)
        T = pd.concat(out); T_all.append(T)
    T = T_all[0]
    for X in T_all[1:]:
        T = T.merge(X[["id"] + [c for c in X if c.startswith("mu_") and "|" in c]], on="id")
    res["launches"] = len(T); res["days"] = int(T.day.nunique()); res["weeks"] = int(T.week.nunique()); res["months_tested"] = sorted(T.mon.unique())
    rng = np.random.default_rng(0)
    res["variants"]["launch model alone"] = boards(T, "mu_lm", rng)   # mu_lm ranks exactly as the launch model's own prediction
    for c in [c for c in T if c.startswith("mu_") and "|" in c]:
        res["variants"][c[3:]] = boards(T, c, rng, base="mu_lm")
    T.drop(columns=["makers", "poster"]).to_parquet(os.path.join(PH, "results", f"vote_model2_{'_'.join(srcs)}.parquet"))
    json.dump(res, open(os.path.join(HERE, "reports", f"vote_model2_{'_'.join(srcs)}.json"), "w"), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:] or ["psa"])
