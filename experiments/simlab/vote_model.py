"""E1 v1: one generative model of a launch's votes as a sum over audiences (direction A of
docs/reviews/2026-11-02_direction_review.md), pre-launch only. For launch i:
  votes_i ~ Poisson(mu_i),  mu_i = pool_i + sum_k size_ik * conv_k(z_i) + browse_i
  pool_i    = a * S_i              S = the person simulation's expected pool picks (<src>_ev), a >= 0
  audiences k (sizes stored as log1p counts in the build; the glm uses counts): makers' PH followers, hunter's PH followers, makers' X followers, company X followers, pre-launch
            promotion reactions; conv_k(z) = exp(c_k + t_k . z), z = track record + page (standardised)
  browse_i  = exp(b0 + b . w)      homepage browsers: w = page quality, line-up size, weekday
Every component is a count on the vote scale, so a better pool simulation enters additively instead of competing
with reach inside one GBM. Two fits, rolling monthly (train on every earlier month, test the next):
  glm  the additive model above, Poisson likelihood, L-BFGS (torch, CPU)
  gbm  monotone additive LightGBM (Poisson objective; each input in its own interaction group; non-decreasing in the
       pool and in every audience size), 3 seeds
Pool source variants: none (no pool component), and each SRC given (default psx = current, psa = trained on all
earlier months). Scores on the launches every source covers: daily top 3/5/10 vs the real daily rank, paired by day
(10,000 resamples) against the same fit with the first source and against the launch model alone (ctrl.py `all`);
test Poisson log-likelihood per launch. Audience sizes are as fetched (undated), the same inputs the launch model uses.
usage: SIMLAB_DATA=data_v2 python -m simlab.vote_model psx psa -> reports/vote_model_<srcs>.json"""
import json, os, sys
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); PH = os.path.join(os.path.dirname(HERE), "ph_predict")
AUD = {"maker_ph": "ph_maker_sum_followers", "hunter_ph": "ph_hunter_followers", "maker_x": "x_maker_sum_followers",
       "company_x": "x_company_followers", "promo": "promo_reactions"}
Z = ["hist_maker_rel_max", "hist_hunter_rel", "hist_maker_n", "hist_hunter_n", "hist_maker_top5", "hist_hunter_top5",
     "ph_has_video", "ph_n_media", "promo_posts", "promo_cov", "promo_n_sources"]
W = ["ph_day_n_launches", "ph_weekday", "ph_has_video", "ph_n_media", "ph_n_topics"]


def load_inputs(srcs):
    cwd = os.getcwd(); os.chdir(PH)
    try:
        sys.path.insert(0, PH)
        from buildcache import build_cached
        B = build_cached(); B["id"] = B.id.astype(str)
        C = pd.read_parquet("results/ctrl_preds.parquet"); C["id"] = C.id.astype(str); C = C.drop_duplicates("id")
        S = {s: pd.DataFrame.from_dict(json.load(open(f"data/{s}_features.json")), orient="index")[[f"{s}_ev"]].rename(columns={f"{s}_ev": s})
             for s in srcs}
    finally:
        os.chdir(cwd)
    ps = [c for c in B.columns if c.startswith("ps_") and B[c].dtype != object and B[c].notna().mean() > 0.5]
    A = C[["id", "day", "dailyRank", "logv", "all"]].merge(B[["id", "votes"] + sorted(set(AUD.values()) | set(Z) | set(W) | set(ps))], on="id")
    for s, D in S.items():
        A = A.merge(D, left_on="id", right_index=True)
    A["votes"] = pd.to_numeric(A.votes, errors="coerce"); A = A[A.votes.notna()].copy()
    A["mon"] = A.day.str[:7]
    return A.reset_index(drop=True), ps


def fit_glm(tr, te, pool, ps):
    """The additive Poisson model; returns mu for te (and the fitted rates, for the report)."""
    import torch
    torch.manual_seed(0)
    zc, wc = Z + ps, W + ps
    mz, sz = tr[zc].mean(), tr[zc].std() + 1e-9; mw, sw = tr[wc].mean(), tr[wc].std() + 1e-9

    def tens(D):
        z = torch.tensor(((D[zc] - mz) / sz).fillna(0).clip(-5, 5).values, dtype=torch.float64)
        w = torch.tensor(((D[wc] - mw) / sw).fillna(0).clip(-5, 5).values, dtype=torch.float64)
        n = torch.tensor(np.expm1(D[list(AUD.values())].fillna(0).clip(lower=0, upper=14).values) / 1000.0, dtype=torch.float64)   # the build stores log1p counts
        s = torch.tensor(D[pool].fillna(0).clip(lower=0).values if pool else np.zeros(len(D)), dtype=torch.float64)
        return z, w, n, s
    z, w, n, s = tens(tr); y = torch.tensor(tr.votes.values, dtype=torch.float64)
    K = n.shape[1]
    P = {"a": torch.zeros(1, dtype=torch.float64, requires_grad=True), "c": torch.full((K,), -3.0, dtype=torch.float64, requires_grad=True),
         "t": torch.zeros((K, z.shape[1]), dtype=torch.float64, requires_grad=True), "b0": torch.tensor([np.log(tr.votes.median())], dtype=torch.float64, requires_grad=True),
         "b": torch.zeros(w.shape[1], dtype=torch.float64, requires_grad=True)}

    def mu(z, w, n, s):
        aud = (n * torch.exp((P["c"] + z @ P["t"].T).clamp(-12, 2))).sum(1)   # conversion at most e^2 = 7 votes per 1k
        return torch.nn.functional.softplus(P["a"]) * s + aud + torch.exp(P["b0"] + w @ P["b"]) + 1e-6
    opt = torch.optim.LBFGS(list(P.values()), lr=0.5, max_iter=500, line_search_fn="strong_wolfe")

    def closure():
        opt.zero_grad()
        m = mu(z, w, n, s)
        loss = (m - y * torch.log(m)).mean() + 1e-3 * ((P["t"] ** 2).sum() + (P["b"] ** 2).sum())
        loss.backward(); return loss
    for _ in range(3):
        opt.step(closure)
    with torch.no_grad():
        m_te = mu(*tens(te)).numpy()
        rates = {"pool_a": float(torch.nn.functional.softplus(P["a"])), **{f"conv_{k}_per_1k": float(np.exp(c)) * 1 for k, c in zip(AUD, P["c"].numpy())},
                 "browse_base": float(np.exp(P["b0"].item()))}
    return m_te, rates


def fit_gbm(tr, te, pool, ps):
    import lightgbm as lgb
    feats = ([pool] if pool else []) + list(AUD.values()) + sorted(set(Z + W + ps))
    mono = [1 if (f == pool or f in AUD.values()) else 0 for f in feats]
    out = []
    for seed in range(3):
        m = lgb.LGBMRegressor(objective="poisson", n_estimators=400, learning_rate=0.03, num_leaves=7, min_child_samples=30,
                              subsample=0.8, subsample_freq=1, colsample_bytree=0.8, random_state=seed, verbose=-1, n_jobs=8,
                              monotone_constraints=mono, interaction_constraints=[[i] for i in range(len(feats))])
        out.append(m.fit(tr[feats], tr.votes).predict(te[feats]))
    return np.mean(out, 0)


def topk(T, col, k):
    return pd.Series({d: len(set(g.nlargest(k, col).id) & set(g[g.dailyRank <= k].id)) / k for d, g in T.groupby("day") if (g.dailyRank <= k).sum() == k})


def paired(a, b, rng):
    ks = a.index.intersection(b.index); d = (b[ks] - a[ks]).values
    bs = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(10000)]
    return [round(100 * float(d.mean()), 1), [round(100 * float(x), 1) for x in np.percentile(bs, [2.5, 97.5])], int(len(d))]


def main(srcs):
    from scipy.stats import poisson
    A, ps = load_inputs(srcs)
    ps = ps[:8]   # a few page scores (the first fully covered ones), to keep the conversion model small
    months = sorted(A.mon.unique())
    variants = [("none", None)] + [(s, s) for s in srcs]
    preds, rates = [], {}
    for m in months[1:]:
        tr, te = A[A.mon < m], A[A.mon == m].copy()
        for name, pool in variants:
            te[f"glm_{name}"], r = fit_glm(tr, te, pool, ps); rates[f"{m} glm_{name}"] = r
            te[f"gbm_{name}"] = fit_gbm(tr, te, pool, ps)
        preds.append(te); print("month", m, "train", len(tr), "test", len(te), flush=True)
    T = pd.concat(preds)
    T.to_parquet(os.path.join(PH, "results", f"vote_model_{'_'.join(srcs)}.parquet"))
    rng = np.random.default_rng(0)
    cols = [f"{f}_{v}" for f in ("glm", "gbm") for v, _ in variants]
    res = {"launches": len(T), "days": int(T.day.nunique()), "months_tested": sorted(T.mon.unique()), "page_scores_used": ps, "scores": {}}
    lm = {k: topk(T, "all", k) for k in (3, 5, 10)}
    res["scores"]["launch model alone"] = {f"top{k}": round(100 * float(lm[k].mean()), 1) for k in (3, 5, 10)}
    for c in cols:
        r = {}
        for k in (3, 5, 10):
            cur = topk(T, c, k); r[f"top{k}"] = round(100 * float(cur.mean()), 1)
            r[f"top{k}_vs_launch_model"] = paired(lm[k], cur, rng)
            base = c.rsplit("_", 1)[0] + "_" + srcs[0]
            if c != base:
                r[f"top{k}_vs_{base}"] = paired(topk(T, base, k), cur, rng)
        r["loglik_per_launch"] = round(float(poisson.logpmf(T.votes.round(), np.clip(T[c], 1e-6, None)).mean()), 3)
        res["scores"][c] = r
    res["glm_rates_last_month"] = {k: {kk: round(v, 4) for kk, v in rates[k].items()} for k in rates if k.startswith(months[-1])}
    out = os.path.join(HERE, "reports", f"vote_model_{'_'.join(srcs)}.json")
    json.dump(res, open(out, "w"), indent=1); print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:] or ["psx", "psa"])
