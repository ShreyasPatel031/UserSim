"""Selection check for the early-vote response (orchestrator, Nov 4): refit tau, kappa, c (quality scale) and sigma
(future dispersion) on UNSELECTED data. Wayback /newest captures Jan-Jun 2025 (raw/hn_early_votes_2025/, outcome-
independent), outcome = made any daily top 30 (frontday_old.jsonl, 2025 lists). No Quality News selection anywhere in
the fit: the posts are every story with a /newest snapshot by 15 min; the label is the daily list.
Environment: the frontsim model (exposure by rank x hour, off-front by age, penalties, front pages) fitted on 2026
Jul-Sep; front pages replayed from 2026 weekdays / weekends at the same clock time (structure only, no 2025 outcome).
Objective: binomial log-likelihood of the daily-list label given the simulator's P(top 30) (isotonic g on 2026 training).
Report: real top-30 rate by 15-min score vs simulated, at the October outcome fit and at the 2025 fit.
    HNCACHE=... python calib_2025.py <wayback_2025 early_snapshots.jsonl> [n_posts] [workers] -> out/calib_2025.json"""
import itertools, json, os, pickle, sys
from multiprocessing import get_context
import numpy as np, pandas as pd
import frontsim as F

HERE = os.path.dirname(os.path.abspath(__file__))
G = None


def early25(T, path, a=15):
    A = pd.read_json(path, lines=True, convert_dates=False)
    N = A[A.page == "newest"]
    caps = np.sort((pd.to_datetime(N.capture_ts.astype(str), format="%Y%m%d%H%M%S", utc=True) - pd.Timestamp(0, tz="UTC")).dt.total_seconds().unique())
    E = N[(N.age_min <= a) & (N.age_min >= 0)].sort_values("age_min").drop_duplicates("item_id", keep="last").set_index("item_id")
    sc = T.post_id.map(E.score).to_numpy(float); a0 = T.post_id.map(E.age_min).to_numpy(float)
    W = N[N.age_min >= 0].assign(w=1 / np.sqrt(N["rank"].clip(lower=1)))
    lim = pd.Series(a0, index=T.post_id.to_numpy()).groupby(level=0).first()
    W = W[W.age_min <= W.item_id.map(lim).fillna(-1)]
    wsum = T.post_id.map(W.groupby("item_id").w.sum()).fillna(0).to_numpy()
    born = T.created_at_i.to_numpy(float)
    ncap = np.searchsorted(caps, born + np.nan_to_num(a0) * 60, side="right") - np.searchsorted(caps, born)
    xw = np.where(np.isfinite(a0) & (ncap > 0), wsum / np.maximum(ncap, 1) * np.nan_to_num(a0), np.nan)
    return sc, a0, xw


def init(state):
    global G
    G = state
    import __main__; __main__.Model = F.Model


def run_fit(params):
    tau, kappa, c, sig = params[:4]; ys = params[4] if len(params) > 4 else 1.0
    import copy
    M = copy.deepcopy(G["M"]); M.tau, M.kappa, M.sigma = tau, kappa, sig; M.grid = G["grid0"] * c
    M.pool_any = True        # 2025 posts replay 2026 front pages (structure only)
    M.start_at_judge = os.environ.get("START_JUDGE") == "1"
    if os.environ.get("FRONT_FIX") == "young":
        M.young = json.load(open(os.path.join(HERE, "young_pen.json"))); M.young_scale = ys
    F.rng = np.random.default_rng(1)
    T = G["T"]; p = np.zeros(len(T))
    for d, idx in G["by_day"].items():
        cls = int(pd.Timestamp(d).dayofweek >= 5)
        p[idx], _ = M.simulate(T.created_at_i.to_numpy(float)[idx], G["sc"][idx], G["a0"][idx], cls, d, {cls: G["pool"][cls]}, G["D"], xw=G["xw"][idx])
    y = T.y.to_numpy(); pr = np.clip(p, 1e-4, 1 - 1e-4)
    ll = float(np.sum(y * np.log(pr) + (1 - y) * np.log(1 - pr)))
    b = pd.cut(G["sc"], [0, 1, 2, 3, 1e9], labels=["1", "2", "3", "4+"])
    return {"tau": tau, "kappa": kappa, "c": c, "sigma": sig, "young_scale": ys, "loglik": round(ll, 1), "sum_p": round(float(p.sum()), 1), "winners": int(y.sum()),
            "sim_by_score": {str(k): round(float(p[b == k].mean()), 4) for k in b.categories}}


def main(path, n=20000, workers=12, D=30):
    import __main__; __main__.Model = F.Model
    M = pickle.load(open(os.path.join(F.CACHE, "frontsim_model.pkl"), "rb"))
    s26 = F.load_stories(); s26["z"] = 0.0; sc26, a026 = F.early(s26); xw26 = F.newest_exposure(s26, a026)
    M.b = 0.0; M.fit_early(s26, sc26, a026, xw26, "2026-09-30")          # unit constant k_new from 2026 training only
    s = pd.read_parquet(os.path.join(F.CACHE, "bq_stories.parquet"), columns=["post_id", "title", "points", "created_at_i", "day"])
    s = s[s.title.notna() & (s.day >= "2025-01-01") & (s.day <= "2025-06-30")].drop_duplicates("post_id").drop(columns="title").reset_index(drop=True)
    L = pd.read_json(os.path.join(F.CACHE, "frontday_old.jsonl"), lines=True, dtype={"day": str})
    s["y"] = s.post_id.isin(set(L[L["rank"] <= 30].post_id)).astype(int)
    sc, a0, xw = early25(s, path)
    keep = np.isfinite(sc); s, sc, a0, xw = s[keep].reset_index(drop=True), sc[keep], a0[keep], xw[keep]
    rng = np.random.default_rng(0); idx = np.sort(rng.choice(len(s), min(n, len(s)), replace=False))
    T, sc, a0, xw = s.iloc[idx].reset_index(drop=True), sc[idx], a0[idx], xw[idx]
    b = pd.cut(sc, [0, 1, 2, 3, 1e9], labels=["1", "2", "3", "4+"])
    res = {"posts_with_snapshot_le15": int(keep.sum()), "sample": len(T), "winners_in_sample": int(T.y.sum()),
           "real_by_score": {str(k): [round(float(T.y[b == k].mean()), 4), int((b == k).sum())] for k in b.categories},
           "outcome": "made any daily top 30 (2025 lists)", "fits": []}
    okd = pd.Series(np.isfinite(M.ISO[:, 0]), index=pd.to_datetime(M.T0 + 600 * np.arange(len(M.ISO)), unit="s").strftime("%Y-%m-%d")).groupby(level=0).mean()
    days26 = sorted(okd.index)
    good = [d for d in days26 if okd.get(d, 0) >= 0.9 and okd.get(str((pd.Timestamp(d) + pd.Timedelta(days=1)).date()), 0) >= 0.9 and "2026-07-15" <= d <= "2026-09-29"]
    pool = {c_: [d for d in good if int(pd.Timestamp(d).dayofweek >= 5) == c_] for c_ in (0, 1)}
    by_day = {d: np.nonzero((T.day == d).to_numpy())[0] for d in sorted(T.day.unique())}
    state = {"M": M, "grid0": M.grid.copy(), "T": T, "sc": sc, "a0": a0, "xw": xw, "pool": pool, "by_day": by_day, "D": D}
    oct_fit = (0.3, 0.2, 0.25, 1.0)
    grid = [oct_fit] + [g for g in itertools.product((0.3, 0.6, 1.0), (0.05, 0.2, 1.0), (0.1, 0.15, 0.25), (0.0, 1.0)) if g != oct_fit]
    if os.environ.get("GRID2"):   # beyond the first grid's edges (tau low, c high, sigma high)
        grid = [oct_fit] + [g for g in itertools.product((0.1, 0.2, 0.3), (0.1, 0.2, 0.5), (0.25, 0.35, 0.5), (1.0, 1.5, 2.0)) if g != oct_fit]
    if os.environ.get("FRONT_FIX") == "young":   # dynamics changed: refit the scale with the entry penalty and its strength
        grid = [g for g in itertools.product((0.1, 0.2, 0.3), (0.2, 0.5, 1.0), (0.25, 0.4, 0.6, 1.0), (1.0,), (0.5, 1.0))]
    if os.environ.get("SMOKE"):
        grid = grid[:2]
    with get_context("spawn").Pool(workers, initializer=init, initargs=(state,)) as P:
        for r in P.imap_unordered(run_fit, grid):
            res["fits"].append(r); print(r, flush=True)
    res["oct_fit"] = next((f for f in res["fits"] if (f["tau"], f["kappa"], f["c"], f["sigma"]) == oct_fit), None)
    res["best"] = max(res["fits"], key=lambda f: f["loglik"])
    os.makedirs(os.path.join(HERE, "out"), exist_ok=True)
    json.dump(res, open(os.path.join(HERE, "out", "calib_2025" + ("_grid2" if os.environ.get("GRID2") else "") + ("_startjudge" if os.environ.get("START_JUDGE") == "1" else "") + ("_young" if os.environ.get("FRONT_FIX") == "young" else "") + ".json"), "w"), indent=1)
    print("REAL", res["real_by_score"]); print("OCT", res["oct_fit"]); print("BEST", res["best"])


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 20000, int(sys.argv[3]) if len(sys.argv) > 3 else 12)
