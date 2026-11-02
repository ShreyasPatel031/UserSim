"""Decision metric (orchestrator, Nov 2): top-30 reach within 24 h on Oct 2-9 weekdays, AUC of the simulator's reach
probability vs the raw 15-min score (points of the latest /newest snapshot by 15 min; no snapshot = 0), paired, 95%
interval resampling days. Configs: stage 1 best (no dispersion) and stage 2 best (dispersion), optionally with the
at-posting prior (PRIOR=atposting: logit p_top30 of hn_jobs/cache/atposting_hist.parquet, prior refit on Sep 1-30).
    HNCACHE=... python calib_auc.py [label] -> out/calib_auc_<label>.json"""
import json, os, pickle, sys
import numpy as np, pandas as pd
from sklearn.metrics import roc_auc_score
import frontsim as F

HERE = os.path.dirname(os.path.abspath(__file__))


def auc_ci(y, s, ref, day, rng, B=2000):
    days = np.array(sorted(set(day))); idx = {d: np.nonzero(day == d)[0] for d in days}
    a, r = roc_auc_score(y, s), roc_auc_score(y, ref); bs = []
    for _ in range(B):
        ii = np.concatenate([idx[d] for d in rng.choice(days, len(days))])
        if y[ii].min() == y[ii].max():
            continue
        bs.append((roc_auc_score(y[ii], s[ii]), roc_auc_score(y[ii], ref[ii])))
    bs = np.array(bs)
    q = lambda x: [round(float(v), 3) for v in np.percentile(x, [2.5, 97.5])]
    return {"sim": [round(a, 3), q(bs[:, 0])], "score15": [round(r, 3), q(bs[:, 1])], "sim - score15": [round(a - r, 3), q(bs[:, 0] - bs[:, 1])]}


def main(label="dispersion", D=60):
    import __main__; __main__.Model = F.Model
    Mo = pickle.load(open(os.path.join(F.CACHE, "frontsim_model.pkl"), "rb"))
    s = F.load_stories(); s["z"] = 0.0; sc, a0 = F.early(s); xw = F.newest_exposure(s, a0)
    Mo.b = 0.0; Mo.fit_early(s, sc, a0, xw, "2026-10-12")
    use_ap = os.environ.get("PRIOR") == "atposting"
    if use_ap:   # prior q = exp(b (z - zc)) u with z = logit p_top30 (out of sample Sep 1 - Oct 14), fit on Sep 1-30
        from scipy.stats import poisson
        A = pd.read_parquet(os.path.join(F.CACHE, "atposting_hist.parquet"))
        zmap = pd.Series(np.log(np.clip(A.p_top30, 1e-5, 1 - 1e-5) / (1 - np.clip(A.p_top30, 1e-5, 1 - 1e-5))).to_numpy(), index=A.post_id.to_numpy())
        st = s[(s.day >= "2026-09-01") & (s.day <= "2026-09-30")].merge(Mo.vE, on="post_id")
        z = st.post_id.map(zmap).to_numpy(); ok = np.isfinite(z); st, z = st[ok], z[ok]
        Mo.zc = float(z.mean()); best = None
        for b in (0.25, 0.5, 0.75, 1.0, 1.5):
            Lb = poisson.pmf(np.round(st.v.to_numpy())[:, None].astype(int), np.clip((st.E.to_numpy() * np.exp(b * (z - Mo.zc)))[:, None], 1e-6, None) * Mo.grid[None, :]) + 1e-300
            w = np.full(len(Mo.grid), 1 / len(Mo.grid))
            for _ in range(300):
                p = Lb * w; p /= p.sum(1, keepdims=True); w = p.mean(0)
            ll = float(np.log((Lb * w).sum(1)).sum())
            if best is None or ll > best[0]:
                best = (ll, b, w)
        _, Mo.b, Mo.prior_u = best; print("at-posting prior b", Mo.b, flush=True)
    cf = json.load(open(os.path.join(HERE, "out", "calib_fit.json")))
    fits = sorted(cf["fits"], key=lambda f: -f["loglik"])
    configs = {"stage 1 (no dispersion)": next(f for f in fits if not f.get("sigma")), "stage 2 (dispersion)": fits[0]}
    qn, RK, EX, UP = F.load_qn()
    reach = pd.Series(np.nanmin(np.where(np.isnan(RK), 91, RK)[:, :F.H24], 1) <= 30, index=qn.post_id.to_numpy())
    okd = pd.Series(np.isfinite(Mo.ISO[:, 0]), index=pd.to_datetime(Mo.T0 + 600 * np.arange(len(Mo.ISO)), unit="s").strftime("%Y-%m-%d")).groupby(level=0).mean()
    good = [d for d in sorted(s.day.unique()) if okd.get(d, 0) >= 0.9 and okd.get(str((pd.Timestamp(d) + pd.Timedelta(days=1)).date()), 0) >= 0.9]
    test = [d for d in good if "2026-10-02" <= d <= "2026-10-09" and pd.Timestamp(d).dayofweek < 5]
    pool = [d for d in good if d < "2026-09-30" and pd.Timestamp(d).dayofweek < 5]
    T = s[s.day.isin(test)].reset_index(drop=True); y = T.post_id.map(reach).fillna(False).astype(bool).to_numpy().astype(int)
    sct, a0t = F.early(T); xwt = F.newest_exposure(T, a0t)
    zt = None
    if use_ap:
        zt = T.post_id.map(zmap).to_numpy(); zt = np.where(np.isfinite(zt), zt, Mo.zc)
    grid0 = Mo.grid.copy(); rng = np.random.default_rng(0)
    ref = np.nan_to_num(sct, nan=0) + 1e-6 * np.nan_to_num(-a0t, nan=0)   # ties: fewer minutes for the same points first
    res = {"label": label, "days": test, "posts": len(T), "real_reach": round(float(y.mean()), 4), "prior": "at-posting" if use_ap else "flat", "configs": {}}
    if use_ap:
        res["at_posting_alone"] = auc_ci(y, zt, ref, T.day.to_numpy(), rng)
    for name, f in configs.items():
        Mo.tau, Mo.kappa, Mo.grid, Mo.sigma = f["tau"], f["kappa"], grid0 * f["c"], f.get("sigma", 0.0)
        r = np.zeros(len(T))
        for d in test:
            m = (T.day == d).to_numpy()
            Mo.simulate(T.created_at_i.to_numpy(float)[m], sct[m], a0t[m], 0, d, {0: [x for x in pool if x <= str((pd.Timestamp(d) - pd.Timedelta(days=3)).date())]}, D,
                        z=None if zt is None else zt[m], xw=xwt[m])
            r[m] = Mo.last_top30
        res["configs"][name] = {"params": {k: f[k] for k in ("tau", "kappa", "c", "sigma") if k in f}, "reach_sim": round(float(r.mean()), 4),
                                "auc": auc_ci(y, r + 1e-9 * rng.random(len(r)), ref, T.day.to_numpy(), rng)}
        print(name, res["configs"][name], flush=True)
    Mo.grid = grid0
    json.dump(res, open(os.path.join(HERE, "out", f"calib_auc_{label}.json"), "w"), indent=1); print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "dispersion")
