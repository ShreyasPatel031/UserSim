"""Fit the early-vote likelihood (tau, kappa) and the quality scale c by OUTCOME calibration instead of the QN
predictive likelihood: per-post binomial log-likelihood of real top-30 reach within 24 h given the simulated reach,
on Oct 2-9 weekdays (dense /newest snapshots, front page reconstructed by QN). Flat prior, replayed Jul-Sep fronts.
These days precede the live test (Nov 2+), so the fit is out of sample for live; for the October Caught test it is not.
    HNCACHE=... python calib_fit.py -> out/calib_fit.json"""
import itertools, json, os, pickle, sys
import numpy as np, pandas as pd
import frontsim as F

HERE = os.path.dirname(os.path.abspath(__file__))


def main(D=30):
    import __main__; __main__.Model = F.Model
    Mo = pickle.load(open(os.path.join(F.CACHE, "frontsim_model.pkl"), "rb"))
    s = F.load_stories(); s["z"] = 0.0; sc, a0 = F.early(s); xw = F.newest_exposure(s, a0)
    Mo.b = 0.0; Mo.fit_early(s, sc, a0, xw, "2026-10-12")          # sets k_new; tau/kappa overwritten below
    qn, RK, EX, UP = F.load_qn()
    reach = pd.Series(np.nanmin(np.where(np.isnan(RK), 91, RK)[:, :F.H24], 1) <= 30, index=qn.post_id.to_numpy())
    okd = pd.Series(np.isfinite(Mo.ISO[:, 0]), index=pd.to_datetime(Mo.T0 + 600 * np.arange(len(Mo.ISO)), unit="s").strftime("%Y-%m-%d")).groupby(level=0).mean()
    good = [d for d in sorted(s.day.unique()) if okd.get(d, 0) >= 0.9 and okd.get(str((pd.Timestamp(d) + pd.Timedelta(days=1)).date()), 0) >= 0.9]
    test = [d for d in good if "2026-10-02" <= d <= "2026-10-09" and pd.Timestamp(d).dayofweek < 5]
    pool = [d for d in good if d < "2026-09-30" and pd.Timestamp(d).dayofweek < 5]
    T = s[s.day.isin(test)].reset_index(drop=True); y = T.post_id.map(reach).fillna(False).astype(bool).to_numpy()
    sct, a0t = F.early(T); xwt = F.newest_exposure(T, a0t)
    sb = pd.cut(np.nan_to_num(sct, nan=0), [-1, 0.5, 1, 2, 3, 1e9], labels=["none", "1", "2", "3", "4+"])
    grid0 = Mo.grid.copy(); res = {"days": test, "posts": len(T), "real_reach": round(float(y.mean()), 4),
                                   "real_by_score": {str(k): round(float(y[sb == k].mean()), 3) for k in sb.categories}, "fits": []}
    for tau, kappa, c in itertools.product((0.3, 0.6, 1.0), (0.05, 0.2, 1.0), (0.15, 0.25, 0.4)):
        Mo.tau, Mo.kappa, Mo.grid = tau, kappa, grid0 * c
        r = np.zeros(len(T))
        for d in test:
            m = (T.day == d).to_numpy()
            Mo.simulate(T.created_at_i.to_numpy(float)[m], sct[m], a0t[m], 0, d, {0: [x for x in pool if x <= str((pd.Timestamp(d) - pd.Timedelta(days=3)).date())]}, D, xw=xwt[m])
            r[m] = Mo.last_top30
        pr = np.clip((r * D + 0.5) / (D + 1), 1e-3, 1 - 1e-3)
        ll = float(np.sum(y * np.log(pr) + (1 - y) * np.log(1 - pr)))
        f = {"tau": tau, "kappa": kappa, "c": c, "loglik": round(ll, 1), "reach_sim": round(float(r.mean()), 4),
             "sim_by_score": {str(k): round(float(r[sb == k].mean()), 3) for k in sb.categories}}
        res["fits"].append(f); print(f, flush=True)
    res["best"] = max(res["fits"], key=lambda f: f["loglik"])
    json.dump(res, open(os.path.join(HERE, "out", "calib_fit.json"), "w"), indent=1); print("BEST", res["best"])


if __name__ == "__main__":
    main()
