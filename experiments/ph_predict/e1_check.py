"""Independent re-check of E5's E1 v2 (offset model): the launch model's prediction as a Poisson offset, plus a LightGBM
correction on the page-free pool simulation (pna_ ev / reach), five audience inputs and day terms. Rebuilt here from the
PH agent's own inputs (ctrl_preds `all`, data/<sim>_features.json, build_cached) with E5's feature list; not E5's code.
Rolling monthly (train on earlier months, from Apr), 5 seeds. Variants:
  launch model        ctrl.py `all`
  offset control      the same Poisson offset model with day terms only (day_n, weekday, day_lm_sum): what refitting
                      on the launch prediction does by itself
  E1 v2               + pool (ev, day_pool_sum, day_reach) + audiences
Daily and weekly top 3/5/10, paired bootstrap over lists (10,000), vs the launch model and vs the control.
usage: SIMLAB_DATA=data_v2 python e1_check.py [pna] -> results/e1_check_<sim>.json"""
import json, os, sys
import numpy as np, pandas as pd, lightgbm as lgb
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from simlab import store
from buildcache import build_cached

AUD = ["ph_hunter_followers", "x_maker_sum_followers", "x_company_followers", "promo_reactions", "promo_posts"]
if os.environ.get("E1_HONEST") == "1":   # only the audience inputs the honest baseline keeps (follower counts and reactions were read later)
    AUD = ["promo_posts"]
RANK = {"day": "out_dailyRank", "week": "out_weeklyRank"}


def per_list(T, col, key, k):
    return pd.Series({g_: len(set(g.nlargest(k, col).id) & set(g[g[RANK[key]] <= k].id)) / k for g_, g in T.groupby(key) if (g[RANK[key]] <= k).sum() == k})


def boot(a, b, rng):
    ks = a.index.intersection(b.index); d = (b[ks] - a[ks]).values
    bs = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(10000)]
    return [round(100 * float(d.mean()), 1), [round(100 * float(x), 1) for x in np.percentile(bs, [2.5, 97.5])], int(len(d))]


def main(sim):
    P, I, E = store.load(); I = I.assign(id=I.id.astype(str))
    C = pd.read_parquet("results/ctrl_preds.parquet"); C["id"] = C.id.astype(str); C = C.drop_duplicates("id")
    if os.environ.get("OFFSET"):   # e.g. results/honest_preds.parquet:honest, the honest launch model in place of ctrl `all`
        f, col = os.environ["OFFSET"].split(":"); O = pd.read_parquet(f); O["id"] = O.id.astype(str)
        C = C.drop(columns="all").merge(O[["id", col]].rename(columns={col: "all"}), on="id")
    S = pd.DataFrame.from_dict(json.load(open(f"data/{sim}_features.json")), orient="index").rename_axis("id").reset_index()
    B = build_cached(); B["id"] = B.id.astype(str); B = B.drop_duplicates("id")
    A = (C[["id", "day", "logv", "all"]].merge(I[["id"] + list(RANK.values())], on="id")
         .merge(S[["id", f"{sim}_ev", f"{sim}_reach"]].rename(columns={f"{sim}_ev": "ev", f"{sim}_reach": "reach"}), on="id")
         .merge(B[["id"] + [c for c in AUD if c in B]], on="id", how="left"))
    A["mu0"] = np.expm1(A["all"]).clip(lower=0.5); A["y"] = np.expm1(A.logv).clip(lower=0)
    g = A.groupby("day")
    A["day_n"] = g.id.transform("size"); A["day_wd"] = pd.to_datetime(A.day).dt.weekday
    A["day_reach"] = g.reach.transform("mean"); A["day_pool_sum"] = g.ev.transform("sum"); A["day_lm_sum"] = g.mu0.transform("sum")
    A["week"] = pd.to_datetime(A.day).dt.strftime("%G-W%V"); A["mon"] = A.day.str[:7]
    V = {"offset control": ["day_n", "day_wd", "day_lm_sum"],
         "E1 v2": ["ev"] + [c for c in AUD if c in A] + ["day_n", "day_wd", "day_reach", "day_pool_sum", "day_lm_sum"]}
    out = []
    for m in sorted(A.mon.unique()):
        if m < "2026-05":
            continue
        tr, te = A[A.mon < m], A[A.mon == m].copy()
        for name, cols in V.items():
            raw = np.mean([lgb.train({"objective": "poisson", "learning_rate": 0.03, "num_leaves": 15, "min_data_in_leaf": 30, "feature_fraction": 0.8,
                                      "bagging_fraction": 0.8, "bagging_freq": 1, "seed": s, "verbose": -1, "num_threads": 8},
                                     lgb.Dataset(tr[cols], tr.y, init_score=np.log(tr.mu0)), num_boost_round=300).predict(te[cols], raw_score=True)
                           for s in range(5)], 0)
            te[name] = raw + np.log(te.mu0)
        out.append(te)
    T = pd.concat(out); rng = np.random.default_rng(0)
    res = {"sim": sim, "launches": len(T), "days": int(T.day.nunique()), "months_tested": sorted(T.mon.unique()),
           "audience_inputs": [c for c in AUD if c in A]}
    for key in ("day", "week"):
        for k in (3, 5, 10):
            lm, ctl, e1 = per_list(T, "all", key, k), per_list(T, "offset control", key, k), per_list(T, "E1 v2", key, k)
            res[f"{key} top{k}"] = {"launch model": round(100 * float(lm.mean()), 1), "offset control": round(100 * float(ctl.mean()), 1),
                                    "E1 v2": round(100 * float(e1.mean()), 1), "E1 v2 vs launch model": boot(lm, e1, rng),
                                    "E1 v2 vs control": boot(ctl, e1, rng),
                                    "months E1 v2 > launch model": (int(((e1 - lm).groupby(e1.index.str[:7]).mean() > 0).sum()) if key == "day" else None)}
    json.dump(res, open(f"results/e1_check_{sim}{'_' + os.environ['OFFSET'].split(':')[1] if os.environ.get('OFFSET') else ''}.json", "w"), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "pna")
