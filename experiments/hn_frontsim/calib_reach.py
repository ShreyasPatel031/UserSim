"""Calibrate a global quality scale c (q -> c q) so the replayed-front simulator's top-30 reach within 24 h matches the
real reach on training days (Sep 1-25 weekdays whose front page Quality News reconstructs; real reach from QN ranks,
complete for posts that reach the top 30). Flat prior and the early-vote tempering refit for it (posts to Sep 25).
    HNCACHE=... python calib_reach.py -> out/calib_reach.json"""
import json, os, pickle, sys
import numpy as np, pandas as pd
import frontsim as F

HERE = os.path.dirname(os.path.abspath(__file__))


def main(D=40, which="oct"):
    import __main__; __main__.Model = F.Model
    Mo = pickle.load(open(os.path.join(F.CACHE, "frontsim_model.pkl"), "rb"))
    s = F.load_stories(); s["z"] = 0.0; sc, a0 = F.early(s); xw = F.newest_exposure(s, a0)
    Mo.b = 0.0
    qn, RK, EX, UP = F.load_qn()
    reach = pd.Series(np.nanmin(np.where(np.isnan(RK), 91, RK)[:, :F.H24], 1) <= 30, index=qn.post_id.to_numpy())
    p24 = pd.Series(UP[:, F.H24 - 1], index=qn.post_id.to_numpy())
    okd = pd.Series(np.isfinite(Mo.ISO[:, 0]), index=pd.to_datetime(Mo.T0 + 600 * np.arange(len(Mo.ISO)), unit="s").strftime("%Y-%m-%d")).groupby(level=0).mean()
    good = [d for d in sorted(s.day.unique()) if okd.get(d, 0) >= 0.9 and okd.get(str((pd.Timestamp(d) + pd.Timedelta(days=1)).date()), 0) >= 0.9]
    if which == "sep":
        test = [d for d in good if "2026-09-01" <= d <= "2026-09-25" and pd.Timestamp(d).dayofweek < 5][:6]
        cut = "2026-08-31"
    else:        # October days with dense /newest snapshots whose front page QN reconstructs
        test = [d for d in good if "2026-10-02" <= d <= "2026-10-09" and pd.Timestamp(d).dayofweek < 5]
        cut = "2026-10-12"
    pool = [d for d in good if d < "2026-09-30" and pd.Timestamp(d).dayofweek < 5]
    Mo.fit_early(s, sc, a0, xw, cut)
    grid0 = Mo.grid.copy(); out = {"test_days": test, "pool_days": len(pool), "tempering": Mo.early_log}
    T = s[s.day.isin(test)].reset_index(drop=True)
    T["real_reach"] = T.post_id.map(reach).fillna(False).astype(bool); T["real_p24"] = T.post_id.map(p24).fillna(T.points)
    out["real"] = {"posts": len(T), "reach": round(float(T.real_reach.mean()), 4), "mean_log1p_p24": round(float(np.log1p(T.real_p24).mean()), 3)}
    sct, a0t = F.early(T); xwt = F.newest_exposure(T, a0t)
    out["real"]["with_snapshot"] = round(float(np.isfinite(sct).mean()), 3)   # Sep posts rarely have a snapshot: mostly prior-only, as most Oct posts were in training
    for c in (1.0, 0.6, 0.4, 0.25, 0.15):
        Mo.grid = grid0 * c; r, lp = [], []
        for d in test:
            m = (T.day == d).to_numpy()
            _, P = Mo.simulate(T.created_at_i.to_numpy(float)[m], sct[m], a0t[m], 0, d, {0: [x for x in pool if x <= str((pd.Timestamp(d) - pd.Timedelta(days=3)).date())]}, D, xw=xwt[m])
            r.append(Mo.last_top30); lp.append(np.log1p(P).mean(1))
        r, lp = np.concatenate(r), np.concatenate(lp)
        sb = pd.cut(np.nan_to_num(sct, nan=0), [-1, 0.5, 1, 2, 3, 1e9], labels=["none", "1", "2", "3", "4+"])
        byb = {str(k): [round(float(T.real_reach[sb == k].mean()), 3), round(float(r[(sb == k)].mean()), 3), int((sb == k).sum())] for k in sb.categories}
        out[f"c={c}"] = {"reach_by_15min_score [real, sim, n]": byb, "reach_sim": round(float(r.mean()), 4), "mean_log1p_p24_sim": round(float(lp.mean()), 3),
                         "reach_sim_among_real_reachers": round(float(r[T.real_reach.to_numpy()].mean()), 4)}
        print(c, out[f"c={c}"], flush=True)
    Mo.grid = grid0
    json.dump(out, open(os.path.join(HERE, "out", f"calib_reach_{which}.json"), "w"), indent=1); print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main(which=sys.argv[1] if len(sys.argv) > 1 else "oct")
