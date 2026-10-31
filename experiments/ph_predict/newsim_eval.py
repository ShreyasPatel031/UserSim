"""Simulation for new products: does adding a new team's audience (hunter ties, competitor ties, outside reach) close
the gap to the launch model, above all on first-time teams? Rolling monthly (train earlier months, test the next,
Jul-Oct), 3 seeds, same predictions for every metric. Simulation versions use simulation outputs and audience counts
only (no launch-level inputs beyond the audience's size):
  sim            pst_ person simulation (page + taste) + tpd_ reach x page conversion (tonight's best)
  sim+ties       + pool people tied through the hunter, the makers and the 5 nearest earlier competitors
  sim+reach      + outside audience: makers' and hunter's Product Hunt followers, makers' X followers
  sim+ties+reach both
  STAGE=2 adds the rest of the audience, one block at a time on top of sim+reach (launch-model inputs that describe
  the audience's size or warm-up, nothing about the page or text):
    +record      the hunter's and makers' earlier launches (hist_: how they did, how many)
    +promo       pre-launch promotion (promo_: posts, reactions, press / Reddit / HN coverage before launch day)
    +poolfol     pool people who follow the team (fol_; follows are undated)
    +x           X reach (x_maker_max_followers, x_company_followers)
    +audience    all four
  launch only    ctrl.py launch model, all inputs
Metrics: within day, among first-time teams / repeat teams: higher of 2, winner of 3, rank corr.; all launches:
daily top 3 / 5 / 10.
usage: python newsim_eval.py -> results/newsim_eval.json"""
import glob, json, os
import numpy as np, pandas as pd, lightgbm as lgb
from scipy.stats import spearmanr
from newteam_eval_lib import first_time


def load(p):
    return pd.DataFrame.from_dict(json.load(open(f"data/{p}_features.json")), orient="index").rename_axis("id").reset_index()


C = pd.read_parquet("results/ctrl_preds.parquet"); C["id"] = C.id.astype(str)
A = C[["id", "day", "dailyRank", "logv", "all"]].merge(load("pst"), on="id").merge(load("tpd"), on="id").merge(load("nsa"), on="id")
for c in [c for c in A if c.startswith("pst_") and not c.endswith("pmax")]:
    A[c] = np.log1p(A[c])
base = [c for c in A if c.startswith(("pst_", "tpd_"))]
ties = ["nsa_team_ties", "nsa_hunter_ties", "nsa_comp_ties", "nsa_active"]
reach = ["nsa_ph_makers", "nsa_ph_hunter", "nsa_x_makers"]
V = {"sim": base, "sim+ties": base + ties, "sim+reach": base + reach, "sim+ties+reach": base + ties + reach}
if os.environ.get("STAGE") == "2":
    from buildcache import build_cached
    B = build_cached(); B["id"] = B.id.astype(str)
    blocks = {"+record": [c for c in B if c.startswith("hist_")], "+promo": [c for c in B if c.startswith("promo_")],
              "+poolfol": [c for c in B if c.startswith("fol_")], "+x": [c for c in ("x_maker_max_followers", "x_company_followers") if c in B]}
    A = A.merge(B[["id"] + sorted({c for v in blocks.values() for c in v})], on="id", how="left")
    V = {"sim+reach": base + reach}
    for k, v in blocks.items():
        V["sim+reach" + k] = base + reach + v
    V["sim+reach+audience"] = base + reach + sorted({c for v in blocks.values() for c in v})
    print({k: len(v) for k, v in blocks.items()}, flush=True)
    if os.environ.get("STAGE3") == "1":   # standing in the day's line-up, and the page as a direct conversion input
        from ctrl import group
        import model as M
        aud = V["sim+reach+audience"]
        for c in aud:
            A[c + "_dayr"] = A.groupby("day")[c].rank(pct=True)
        page = [c for c in M.cols(B, M.LIVE_SOURCES + M.PAGE_SOURCES) if group(c) == "page"]
        A = A.merge(B[["id"] + [c for c in page if c not in A]], on="id", how="left")
        V = {"sim+reach+audience": aud, "+day standing": aud + [c + "_dayr" for c in aud], "+page": aud + page,
             "+day standing+page": aud + [c + "_dayr" for c in aud] + page}
        if os.environ.get("STAGE4") == "1":   # what is left in the launch model: each remaining input group on top
            best = aud + [c + "_dayr" for c in aud] + page
            rest = [c for c in M.cols(B, M.LIVE_SOURCES + M.PAGE_SOURCES) if c not in set(best)]
            fams = {}
            for c in rest:
                fams.setdefault(c.split("_")[0], []).append(c)
            A = A.merge(B[["id"] + [c for c in rest if c not in A]], on="id", how="left")
            V = {"best": best, **{f"+{k} ({len(v)})": best + v for k, v in sorted(fams.items()) if len(v) >= 1}}
            print({k: len(v) for k, v in fams.items()}, flush=True)
        if os.environ.get("STAGE5") == "1":   # comparison with competitors (cmp_features.py), for the simulation and the launch model
            best = aud + [c + "_dayr" for c in aud] + page
            C5 = pd.DataFrame.from_dict(json.load(open("data/cmp_features.json")), orient="index").rename_axis("id").reset_index()
            cmp = [c for c in C5 if c.startswith("cmp_")]
            A = A.merge(C5, on="id", how="left")
            for c in cmp:
                A[c + "_dayr"] = A.groupby("day")[c].rank(pct=True)
            cmpr = cmp + [c + "_dayr" for c in cmp]
            V = {"sim best": best, "sim best + competitors": best + cmpr, "launch pred + competitors": ["all"] + cmpr}
            json.dump(cmp, open("results/cmp_inputs.json", "w"))
A["mon"] = A.day.str[:7]; out = []
for m in sorted(A.mon.unique())[1:]:
    tr, te = A[A.mon < m], A[A.mon == m].copy()
    for name, cols in V.items():
        te[name] = np.mean([lgb.LGBMRegressor(n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=30, subsample=0.8, subsample_freq=1,
                                              colsample_bytree=0.5, random_state=s, verbose=-1, n_jobs=8).fit(tr[cols], tr.logv).predict(te[cols]) for s in range(3)], 0)
    out.append(te)
T = pd.concat(out).rename(columns={"all": "launch only"}); T["first_time"] = T.id.map(first_time())
P = list(V) + ["launch only"]; rng = np.random.default_rng(0)
if os.environ.get("SAVE") == "1":   # per-launch predictions and the simulation's inputs, for worked examples
    T[["id", "day", "dailyRank", "logv", "first_time"] + P + [c for c in T if c.startswith(("nsa_", "tpd_", "pst_"))]].to_parquet("results/newsim_preds.parquet")
res = {"months_tested": sorted(T.mon.unique())}
for name, flag in (("first-time teams", True), ("repeat teams", False)):
    S = T[T.first_time == flag]; r = {"launches": len(S)}
    pair, trip, corr = {p: [] for p in P}, {p: [] for p in P}, {p: [] for p in P}
    for _, g in S.groupby("day"):
        g = g.reset_index(drop=True)
        for i in range(len(g)):
            for j in range(i + 1, len(g)):
                if g.logv[i] != g.logv[j]:
                    for p in P:
                        pair[p].append((g[p][i] > g[p][j]) == (g.logv[i] > g.logv[j]))
        if len(g) >= 3:
            for _ in range(min(20, len(g))):
                k = g.loc[rng.choice(len(g), 3, replace=False)]
                if k.logv.nunique() == 3:
                    for p in P:
                        trip[p].append(k[p].idxmax() == k.logv.idxmax())
        if len(g) >= 5:
            for p in P:
                corr[p].append(spearmanr(g[p], g.logv).correlation)
    for p in P:
        r[p] = {"pairs": round(100 * float(np.mean(pair[p])), 1), "groups3": round(100 * float(np.mean(trip[p])), 1), "corr": round(float(np.nanmean(corr[p])), 3)}
    res[name] = r
hit = lambda g, c, k: len(set(g.nlargest(k, c).id) & set(g[g.dailyRank <= k].id)) / k
res["all launches, daily top 3/5/10"] = {p: [round(100 * float(np.mean([hit(g, p, k) for _, g in T.groupby("day") if (g.dailyRank <= k).sum() == k])), 1)
                                              for k in (3, 5, 10)] for p in P}
json.dump(res, open(f"results/newsim_eval{'_stage5' if os.environ.get('STAGE5') == '1' else '_stage4' if os.environ.get('STAGE4') == '1' else '_stage3' if os.environ.get('STAGE3') == '1' else '_stage2' if os.environ.get('STAGE') == '2' else ''}.json", "w"), indent=1); print(json.dumps(res, indent=1))
