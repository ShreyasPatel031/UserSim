"""Honest E1 retrain (Shreyas, Nov 2): the E1 v2 structure on the honest offset, with honest pre-launch inputs only.
Offset: the honest launch model (ph_predict/honest.py `honest`, out of sample: no follower counts, no follow lists, no
undated promo_), as a Poisson mean expm1(honest) rescaled on the training months.
Honest inputs only: the page-free pool simulation (pna_ expected picks), dated pre-launch promotion (promo_posts*,
promo_cov*), track record (hist_*), page (ps_, vs_, pf_) and day terms. No follower counts of any kind.
  control                 offset + day terms (the honest launch model calibrated per day)
  + pool                  + pna_ expected picks
  + promo                 + promo_posts* / promo_cov*
  + pool + promo + hist
  + all honest            + pool + promo + hist + page
Poisson LightGBM, rolling monthly (May–Oct), 5 seeds averaged, non-decreasing in the pool and the promotion counts.
Paired against the control by day / week (10,000 resamples); months better / tied / worse on daily top 3.
Decision rule fixed before the run: a variant adds daily value if daily top 3 vs the control has a 95% interval above 0.
usage: SIMLAB_DATA=data_v2 python -m simlab.e1_honest [path/to/honest_preds.parquet] -> reports/e1_honest.json"""
import json, os, sys
import numpy as np, pandas as pd
from . import vote_model2 as V

HERE = os.path.dirname(os.path.abspath(__file__))
PARAMS = dict(n_estimators=300, learning_rate=0.02, num_leaves=15, min_child_samples=30, subsample=0.8, subsample_freq=1, colsample_bytree=0.7)


def load(honest_path):
    cwd = os.getcwd(); os.chdir(V.PH); sys.path.insert(0, V.PH)
    try:
        from buildcache import build_cached
        B = build_cached(); B["id"] = B.id.astype(str)
        C = pd.read_parquet("results/ctrl_preds.parquet"); C["id"] = C.id.astype(str); C = C.drop_duplicates("id")
        P = pd.DataFrame.from_dict(json.load(open("data/pna_features.json")), orient="index")[["pna_ev", "pna_reach"]]
    finally:
        os.chdir(cwd)
    H = pd.read_parquet(honest_path); H["id"] = H.id.astype(str); H = H.drop_duplicates("id")
    promo = [c for c in B if c.startswith(("promo_posts", "promo_cov"))]
    hist = [c for c in B if c.startswith("hist_") and "follower" not in c]
    page = [c for c in B if c.startswith(("ps_", "vs_", "pf_")) and B[c].dtype != object and "follower" not in c]
    from . import store
    _, I, _ = store.load(); I = I.assign(id=I.id.astype(str))
    A = C[["id", "day", "dailyRank"]].merge(H[["id", "honest"]], on="id").merge(B[["id", "votes"] + promo + hist + page], on="id")
    A = A.merge(I[["id", "out_weeklyRank"]], on="id").merge(P, left_on="id", right_index=True)
    A["votes"] = pd.to_numeric(A.votes, errors="coerce"); A = A[A.votes.notna()].reset_index(drop=True)
    A["all"] = A["honest"]   # V.day_terms and the offset read `all`
    A["mon"] = A.day.str[:7]; A["week"] = pd.to_datetime(A.day).dt.strftime("%G-W%V")
    return V.day_terms(A, "pna"), promo, hist, page


def fit_seed(tr, te, feats, mono, seed):
    import lightgbm as lgb
    c = np.log(tr.votes.sum() / np.expm1(tr["all"]).sum())
    m = lgb.LGBMRegressor(objective="poisson", random_state=seed, verbose=-1, n_jobs=8, monotone_constraints=[1 if f in mono else 0 for f in feats], **PARAMS)
    m.fit(tr[feats], tr.votes, init_score=np.log(np.expm1(tr["all"]).clip(lower=0.5)) + c)
    return np.exp(m.predict(te[feats], raw_score=True) + np.log(np.expm1(te["all"]).clip(lower=0.5)) + c)


def main(honest_path):
    D, promo, hist, page = load(honest_path)
    mono = {"pna_ev"} | set(promo)
    variants = {"control": V.DAY, "+ pool": ["pna_ev"] + V.DAY, "+ promo": promo + V.DAY,
                "+ pool + promo + hist": ["pna_ev"] + promo + hist + V.DAY, "+ all honest": ["pna_ev"] + promo + hist + page + V.DAY}
    months = sorted(D.mon.unique()); parts = []
    for m in months[1:]:
        tr, te = D[D.mon < m], D[D.mon == m].copy()
        c = tr.votes.sum() / np.expm1(tr["all"]).sum(); te["mu_lm"] = np.expm1(te["all"]).clip(lower=0.5) * c
        for name, feats in variants.items():
            te[f"mu_{name}"] = np.mean([fit_seed(tr, te, feats, mono, s) for s in range(5)], 0)
        parts.append(te); print("month", m, flush=True)
    T = pd.concat(parts); rng = np.random.default_rng(0)
    res = {"launches": len(T), "days": int(T.day.nunique()), "weeks": int(T.week.nunique()), "months_tested": sorted(T.mon.unique()),
           "inputs": {"promo": promo, "hist": hist, "page": len(page)}, "decision_rule": "daily top 3 vs control, 95% interval above 0",
           "honest launch model alone": V.boards(T, "mu_lm", rng), "variants": {}}
    res["variants"]["control"] = {"scores": V.boards(T, "mu_control", rng), "vs_honest_launch_model": V.boards(T, "mu_control", rng, base="mu_lm")}
    for name in list(variants)[1:]:
        r = {"scores": V.boards(T, f"mu_{name}", rng)}
        r["vs_control"] = {k.replace("_vs_lm", ""): v for k, v in V.boards(T, f"mu_{name}", rng, base="mu_control").items() if k.endswith("_vs_lm")}
        mon = {m: (V.boards(g, f"mu_{name}", rng)["daily_top3"], V.boards(g, "mu_control", rng)["daily_top3"]) for m, g in T.groupby("mon")}
        r["daily_top3_months_better_tied_worse"] = [sum(a > b for a, b in mon.values()), sum(a == b for a, b in mon.values()), sum(a < b for a, b in mon.values())]
        r["adds_daily_value"] = bool(r["vs_control"]["daily_top3"][1][0] > 0)
        res["variants"][name] = r
    json.dump(res, open(os.path.join(HERE, "reports", "e1_honest.json"), "w"), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(V.PH, "results", "honest_preds.parquet"))
