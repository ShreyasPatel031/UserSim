"""Score person-simulation feature files (data/<src>_features.json) on the same launches, pre-launch, out of sample.
1. Pool check: per launch, the simulation's expected pool picks (<src>_ev, <src>_fans) vs the real number of pool people
   who upvoted or commented on launch day. Within day: Spearman, and top-3 hit of "most pool votes".
2. Launch model + simulation: LightGBM on final log votes from the launch model's prediction (ctrl.py `all`) plus the
   source's inputs (log1p) and their within-day percentiles, rolling monthly (train on earlier months), 3 seeds.
   Daily top 3/5/10.
Every source is restricted to the launches all sources share. Paired bootstrap over days (10,000) against the first
source, and for (2) also against the launch model alone.
usage: SIMLAB_DATA=data_v2 python sim_src_score.py pnx psg psv [...] -> results/sim_src_score_<srcs>.json"""
import json, os, sys
import numpy as np, pandas as pd, lightgbm as lgb
from scipy.stats import spearmanr
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from simlab import store


def load(p):
    D = pd.DataFrame.from_dict(json.load(open(f"data/{p}_features.json")), orient="index").rename_axis("id").reset_index()
    return D.rename(columns=lambda c: "s_" + c[len(p) + 1:] if c.startswith(p + "_") else c)


def b100(a, b, rng, scale=100):
    ks = a.index.intersection(b.index); d = (b[ks] - a[ks]).values
    bs = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(10000)]
    r = 3 if scale == 1 else 1
    return [round(scale * float(d.mean()), r), [round(scale * float(x), r) for x in np.percentile(bs, [2.5, 97.5])], int(len(d))]


def topk(T, col, k):
    return pd.Series({d: len(set(g.nlargest(k, col).id) & set(g[g.dailyRank <= k].id)) / k for d, g in T.groupby("day") if (g.dailyRank <= k).sum() == k})


def main(srcs):
    P, I, E = store.load(); I = I.assign(id=I.id.astype(str)); day = dict(zip(I.id, I.day))
    E = E.assign(item=E.item.astype(str)); real = E[E.item.map(day) == E.date].groupby("item").person.nunique()
    C = pd.read_parquet("results/ctrl_preds.parquet"); C["id"] = C.id.astype(str); C = C.drop_duplicates("id")
    S = {s: load(s) for s in srcs}
    ids = set(C.id)
    for D in S.values():
        ids &= set(D.id)
    base = C[C.id.isin(ids)][["id", "day", "dailyRank", "logv", "all"]].copy(); base["mon"] = base.day.str[:7]
    base["real"] = base.id.map(real).fillna(0)
    res = {"launches": len(base), "days": int(base.day.nunique()), "months": sorted(base.mon.unique())}
    rng = np.random.default_rng(0)
    # 1. pool check
    pc, sp, hit = {}, {}, {}
    for s, D in S.items():
        A = base.merge(D, on="id")
        for c in ("ev", "fans"):
            sp[(s, c)] = pd.Series({d: spearmanr(g["s_" + c], g.real).correlation for d, g in A.groupby("day") if len(g) >= 5 and g.real.sum() > 0})
            hit[(s, c)] = pd.Series({d: len(set(g.nlargest(3, "s_" + c).id) & set(g.nlargest(3, "real").id)) / 3 for d, g in A.groupby("day") if len(g) >= 5 and g.real.sum() > 0})
        pc[s] = {f"spearman_{c}": round(float(sp[(s, c)].mean()), 3) for c in ("ev", "fans")} | {f"pool_top3_{c}": round(100 * float(hit[(s, c)].mean()), 1) for c in ("ev", "fans")}
        if s != srcs[0]:
            for c in ("ev", "fans"):
                pc[s][f"spearman_{c}_vs_{srcs[0]}"] = b100(sp[(srcs[0], c)], sp[(s, c)], rng, 1)
                pc[s][f"pool_top3_{c}_vs_{srcs[0]}"] = b100(hit[(srcs[0], c)], hit[(s, c)], rng)
    res["pool_check"] = pc
    # 2. launch model + simulation
    preds = {}
    for s, D in S.items():
        A = base.merge(D, on="id"); sc = [c for c in A if c.startswith("s_")]
        for c in sc:
            if not c.endswith(("pmax", "share")):
                A[c] = np.log1p(A[c].clip(lower=0))
            A[c + "_dayr"] = A.groupby("day")[c].rank(pct=True)
        cols = ["all"] + sc + [c + "_dayr" for c in sc]; out = []
        for m in sorted(A.mon.unique())[1:]:
            tr, te = A[A.mon < m], A[A.mon == m].copy()
            te["p"] = np.mean([lgb.LGBMRegressor(n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=30, subsample=0.8, subsample_freq=1,
                                                 colsample_bytree=0.5, random_state=r, verbose=-1, n_jobs=8).fit(tr[cols], tr.logv).predict(te[cols]) for r in range(3)], 0)
            out.append(te)
        preds[s] = pd.concat(out)
    T0 = preds[srcs[0]]; lm = {"top%d" % k: round(100 * float(topk(T0, "all", k).mean()), 1) for k in (3, 5, 10)}
    L = {"launch model alone": lm}
    for s in srcs:
        r = {}
        for k in (3, 5, 10):
            cur = topk(preds[s], "p", k)
            r[f"top{k}"] = round(100 * float(cur.mean()), 1)
            r[f"top{k}_vs_launch_model"] = b100(topk(preds[s], "all", k), cur, rng)
            if s != srcs[0]:
                r[f"top{k}_vs_{srcs[0]}"] = b100(topk(T0, "p", k), cur, rng)
        L[f"launch model + {s}"] = r
    res["launch_level_daily"] = L
    json.dump(res, open(f"results/sim_src_score_{'_'.join(srcs)}.json", "w"), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:])
