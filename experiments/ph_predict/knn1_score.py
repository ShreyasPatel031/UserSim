"""PH-KNN1, scoring (orchestrator 10:01Z Nov 23): does reweighting the inputs arm 3 already has beat arm 3?
Input: oos.parquet from knn1_vm.py (month-forward arm-3 replica arm3_ref, monotone refits arm3_mono / arm3_mono_add, all inputs).
Candidates, all walk-forward:
  (1) blend_k5 / blend_k62: within-day z(arm3_ref) - w * z(kNN), where kNN = mean final within-day percentile of the 15 nearest launches
      from EARLIER days only (5 = the MISS1 inputs, log1p, z-scored on earlier rows; 62 = every arm-3 input, z-scored on earlier rows, NaN -> 0).
      w is re-picked at each month start on scored days before that month only (grid, max mean of top 3/5/10; w = 0 with < 60 prior days).
  (2a) arm3_mono (promo_posts constrained; the other four MISS1 inputs are not arm-3 inputs), (2b) arm3_mono_add (the four added, all five +1).
Truth: final daily rank from the history frame (dailyRank), days with >= 10 ranked. Primary test: 2026 months (as the arm-3 decision);
2025 months are the replication. Paired day bootstrap 10,000, seed 0, against arm3_ref (the replica). Near-miss recovery: true top-3
launches at arm-3 rank 4-6 that a candidate moves into its top 3, and the cost (true top-3 launches arm 3 had in its top 3 that drop out).
Live check: blend_k5 on the frozen 00:05 parquets Nov 10-22 (published column as in MISS1), neighbours from the frame's earlier days,
w = the last walk-forward pick; how many of MISS1's 11 rank-4-6 misses move into the top 3, and the cost.
usage: python knn1_score.py <oos.parquet> <dir with f_<d>.parquet> -> results/knn_reweight_v1.json"""
import json, os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
K5 = ["ph_hunter_followers", "x_maker_sum_followers", "x_company_followers", "promo_reactions", "promo_posts"]
KS = (3, 5, 10); NN = 15; NB = 10000; GRID = [0, 0.1, 0.2, 0.3, 0.5, 0.75, 1.0, 1.5, 2.0]
NONIN = {"id", "day", "mon", "dailyRank", "votes", "arm3_ref", "arm3_mono", "arm3_mono_add", "n_inputs"}


def zday(s, day):
    g = s.groupby(day); return (s - g.transform("mean")) / g.transform("std").replace(0, 1).fillna(1)


def knn_walk(O, cols, log=False):
    """kNN score per row: mean pct of the NN nearest rows from earlier days (ranked rows only)."""
    X = O[cols].apply(pd.to_numeric, errors="coerce").astype(float)
    if log: X = np.log1p(X.clip(lower=0))
    out = pd.Series(np.nan, index=O.index); days = sorted(O.day.unique())
    lab = O.pct.notna().values
    for d in days:
        me = (O.day == d).values; prior = (O.day < d).values & lab
        if prior.sum() < 200: continue
        P = X[prior]; mu, sd = P.mean(), P.std(ddof=0).replace(0, 1).fillna(1)
        A = ((X[me] - mu) / sd).fillna(0).values; Bm = ((P - mu) / sd).fillna(0).values
        dist = (A ** 2).sum(1)[:, None] + (Bm ** 2).sum(1)[None, :] - 2 * A @ Bm.T
        nn = np.argpartition(dist, NN, 1)[:, :NN]; out[me] = O.pct.values[prior][nn].mean(1)
    return out


def day_scores(O, col, asc=False):
    r = {}
    for d, g in O.groupby("day"):
        g = g.sort_values([col, "id"], ascending=[asc, True]); top = g.id.tolist(); tr = g.set_index("id").dailyRank
        r[d] = {f"top{k}": 100.0 * sum(1 for i in top[:k] if tr[i] <= k) / k for k in KS}
    return pd.DataFrame(r).T


def main(oos, live_dir):
    O = pd.read_parquet(oos); O["id"] = O.id.astype(str); O["day"] = O.day.astype(str)
    nr = O.groupby("day").dailyRank.transform(lambda s: s.notna().sum()); O = O[nr >= 10].copy()
    O["pct"] = O.dailyRank / O.groupby("day").dailyRank.transform(lambda s: s.notna().sum())
    O = O[O.dailyRank.notna()].reset_index(drop=True)          # scored launches only (unranked = dropped from featured)
    inputs = [c for c in O.columns if c not in NONIN and c != "pct" and c not in K5[:4]]
    O["knn5"] = knn_walk(O, K5, log=True); O["knn62"] = knn_walk(O, inputs)
    O["z3"] = zday(O.arm3_ref, O.day)
    for k in ("knn5", "knn62"): O[f"zk_{k}"] = -zday(O[k], O.day)     # higher = better
    S = {c: day_scores(O, c) for c in ("arm3_ref", "arm3_mono", "arm3_mono_add")}
    mean3 = lambda D: D[[f"top{k}" for k in KS]].mean(1)
    for k in ("knn5", "knn62"):
        cand = {w: day_scores(O.assign(s=O.z3 + w * O[f"zk_{k}"].fillna(0)), "s") for w in GRID}
        picks, rows = {}, []
        for m in sorted(O.mon.unique()):
            prior = [d for d in S["arm3_ref"].index if d < f"{m}-01" and O.loc[O.day == d, f"zk_{k}"].notna().all()]
            w = max(GRID, key=lambda w: (mean3(cand[w].loc[prior]).mean(), -w)) if len(prior) >= 60 else 0.0
            picks[m] = w; rows.append(cand[w][cand[w].index.str.startswith(m)])
        S[f"blend_{k}"] = pd.concat(rows).sort_index(); S[f"blend_{k}"].attrs["w"] = picks
        O[f"s_blend_{k}"] = O.z3 + O.mon.map(picks) * O[f"zk_{k}"].fillna(0)
    rng = np.random.default_rng(0); res = {"tests": {}}
    for yr in ("2026", "2025"):
        days = [d for d in S["arm3_ref"].index if d.startswith(yr)]; T = {}
        for c, D in S.items():
            D = D.loc[[d for d in days if d in D.index]]
            T[c] = {"days": len(D), **{f"top{k}": round(float(D[f"top{k}"].mean()), 1) for k in KS}}
            if c != "arm3_ref":
                diff = D - S["arm3_ref"].loc[D.index]; idx = rng.integers(0, len(diff), (NB, len(diff)))
                for k in KS:
                    x = diff[f"top{k}"].values; bs = x[idx].mean(1)
                    T[c][f"d_top{k}"] = [round(float(x.mean()), 2), round(float(np.percentile(bs, 2.5)), 2), round(float(np.percentile(bs, 97.5)), 2)]
                if "w" in S[c].attrs: T[c]["w_by_month"] = {m: w for m, w in S[c].attrs["w"].items() if m.startswith(yr)}
        # near-miss recovery vs arm3_ref
        Y = O[O.day.str.startswith(yr)].copy(); Y["r3"] = Y.groupby("day").arm3_ref.rank(ascending=False, method="first")
        nm = {}
        for c in ("arm3_mono", "arm3_mono_add", "s_blend_knn5", "s_blend_knn62"):
            Y["rc"] = Y.groupby("day")[c].rank(ascending=False, method="first"); t3 = Y[Y.dailyRank <= 3]
            near = t3[(t3.r3 >= 4) & (t3.r3 <= 6)]; hit = t3[t3.r3 <= 3]
            nm[c] = {"near_misses_rank4_6": int(len(near)), "moved_into_top3": int((near.rc <= 3).sum()),
                     "arm3_hits": int(len(hit)), "hits_dropped": int((hit.rc > 3).sum()),
                     "net_top3_hits": int((t3.rc <= 3).sum() - (t3.r3 <= 3).sum())}
        T["near_miss"] = nm; res["tests"][yr] = T
    # replica sanity vs the stored arm-3 backtest predictions
    st = os.path.join(HERE, "results", "arm3_vs_arm2_preds.parquet")
    if os.path.exists(st):
        A = pd.read_parquet(st); A["id"] = A.id.astype(str); M_ = O.merge(A[["id", "arm3"]], on="id")
        res["replica_vs_stored_arm3"] = {"rows": int(len(M_)), "spearman": round(float(M_.arm3_ref.rank().corr(M_.arm3.rank())), 3)}
    # live check on the frozen parquets: MISS1's rank-4-6 misses
    w_last = S["blend_knn5"].attrs["w"][max(S["blend_knn5"].attrs["w"])]; live = []
    for f in sorted(os.listdir(live_dir)):
        if not f.startswith("f_"): continue
        d = f[2:12]; F = pd.read_parquet(os.path.join(live_dir, f)); F["id"] = F.id.astype(str)
        col = next(c for c in ("pred_arm3", "pred_arm2", "pred") if c in F and F[c].notna().mean() >= 0.9)
        prior = O[O.day < d]; Xp = np.log1p(prior[K5].apply(pd.to_numeric, errors="coerce").clip(lower=0)); mu, sd = Xp.mean(), Xp.std(ddof=0).replace(0, 1)
        A_ = ((np.log1p(F[K5].apply(pd.to_numeric, errors="coerce").clip(lower=0)) - mu) / sd).fillna(0).values; Bm = ((Xp - mu) / sd).fillna(0).values
        dist = (A_ ** 2).sum(1)[:, None] + (Bm ** 2).sum(1)[None, :] - 2 * A_ @ Bm.T; nn = np.argpartition(dist, NN, 1)[:, :NN]
        F["knn5"] = prior.pct.values[nn].mean(1)
        F["s"] = (F[col] - F[col].mean()) / (F[col].std() or 1) - w_last * (F.knn5 - F.knn5.mean()) / (F.knn5.std() or 1)
        F["r0"] = F[col].rank(ascending=False, method="first"); F["r1"] = F.s.rank(ascending=False, method="first"); F["day"] = d; live.append(F)
    L = pd.concat(live, ignore_index=True)
    T = json.loads(os.popen("gsutil cat gs://usersim-bakeoff-347838016394/usersim_sim/results/web/truth_daily.json").read())["days"]
    L["final"] = [T.get(d, {}).get("ranks", {}).get(i) for d, i in zip(L.day, L.id)]; t3 = L[L.final.notna() & (L.final.astype(float) <= 3)]
    near = t3[(t3.r0 >= 4) & (t3.r0 <= 6)]; hit = t3[t3.r0 <= 3]
    res["live_nov10_22_blend_knn5"] = {"w": w_last, "near_misses_rank4_6": int(len(near)), "moved_into_top3": int((near.r1 <= 3).sum()),
                                       "arm3_hits": int(len(hit)), "hits_dropped": int((hit.r1 > 3).sum()),
                                       "top3_hit_pct_published": round(100 * float((t3.r0 <= 3).sum()) / (3 * L.day.nunique()), 1),
                                       "top3_hit_pct_blend": round(100 * float((t3.r1 <= 3).sum()) / (3 * L.day.nunique()), 1)}
    res.update({"experiment": "PH-KNN1", "asked": "orchestrator 10:01Z Nov 23", "written_at": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"),
                "inputs_arm3": len(inputs), "k": NN, "grid": GRID,
                "leak_checks": "walk-forward only: arm-3 replica and monotone refits month-forward (train < month); kNN neighbours from earlier days only; "
                               "blend weight picked on earlier months only; no final votes, ranks or hidden-order reads among the inputs "
                               "(labels are read only as kNN targets of earlier days and as truth)"})
    json.dump(res, open(os.path.join(HERE, "results", "knn_reweight_v1.json"), "w"), indent=1, default=str)
    print(json.dumps(res, default=str)[:6000])


if __name__ == "__main__":
    main(*sys.argv[1:3])
