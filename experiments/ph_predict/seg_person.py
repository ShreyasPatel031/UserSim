"""Segment x attribute lifts as a person-level feature in the share model (orchestrator 07:50Z Nov 11), product-only.
Feature  segf(p, L) = mean over L's attributes (it9b binary + top-40 topics) of the TRAIN-period (Sep 1 - Oct 19) pooled
         lift of p's segment (segment_attr_pilot.py, K=SEG_K, voters); p's segment from pre-Sep behaviour; people
         without a segment get 0 (has_seg = 0).
Rows     it9b product-only rows (rows_tl_cp_attr_noctx/<d>.parquet: person x launch, p, y), Oct 20 - Nov 8, label filter.
Scorers  it9b      p (the deployed-research product-only share score)
         seg       segf alone
         it9b+seg  leave-one-DAY-out logistic on [logit p, segf, has_seg, segf*logit p] (weights from the other test days)
Metrics  per vote (a person-day's upvoted launch), within the person's line-up rows: Hit@1, Hit@3 (rank by score),
         AUC (share of the person's non-voted launches scored below it); all votes / cold-start votes / warm votes;
         populations: voters (all label-filtered voting person-days) and browsers (>= 3 votes that day and >= 5 active
         days in the 30 before d); restricted to people WITH a segment (the feature's population) and also all people.
         Paired bootstrap over person-days for it9b+seg - it9b.
usage: SIMBT=<dir> SEG_K=12 python seg_person.py -> results/seg_person_k<K>.json"""
import glob, json, os, pickle, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
WORK = os.environ["SIMBT"]; K = int(os.environ.get("SEG_K", "12"))
TEST0, D1 = "2026-10-20", "2026-11-08"


def main():
    from sklearn.linear_model import LogisticRegression
    import two_level as T
    ok, _ = T._label_maps()
    A = pickle.load(open(f"{WORK}/segattr_k{K}.pkl", "rb"))
    seg, ATTR, amat, lift, cold = A["seg"], A["ATTR"], A["amat"], A["lift_train"]["voters"], A["cold"]
    si = {a: i for i, a in enumerate(ATTR)}
    LA = {}
    for L, s in amat.items():
        ix = [si[a] for a in s if a in si]
        LA[L] = lift[:, ix].mean(1) if ix else np.zeros(K)
    E = pd.read_parquet(f"{WORK}/events_cp.parquet"); E["date"] = E.date.astype(str).str[:10]
    adays = E[["person", "date"]].drop_duplicates()
    parts = []
    for f in sorted(glob.glob(f"{WORK}/rows_tl_cp_attr_noctx/2026-*.parquet")):
        d = os.path.basename(f)[:10]
        if not (TEST0 <= d <= D1) or not os.path.basename(f) == f"{d}.parquet":
            continue
        X = pd.read_parquet(f, columns=["person", "id", "p", "y"]); X["id"] = X.id.astype(str)
        X = X[ok(X.person, d)].copy(); X["day"] = d
        nv = X.groupby("person").y.transform("sum"); X = X[nv > 0]
        cut = (pd.Timestamp(d) - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
        a30 = adays[(adays.date < d) & (adays.date >= cut)].groupby("person").size()
        X["browser"] = (X.groupby("person").y.transform("sum") >= 3) & (X.person.map(a30).fillna(0) >= 5)
        s = X.person.map(seg)
        X["has_seg"] = s.notna().astype(float)
        X["segf"] = [LA.get(L, np.zeros(K))[int(k)] if k == k else 0.0 for L, k in zip(X.id, s)]
        parts.append(X)
    X = pd.concat(parts, ignore_index=True)
    X["lp"] = np.log(X.p.clip(1e-6, 1 - 1e-6) / (1 - X.p.clip(1e-6, 1 - 1e-6)))
    X["segf_lp"] = X.segf * X.lp
    F = ["lp", "segf", "has_seg", "segf_lp"]
    X["comb"] = np.nan
    for d in X.day.unique():
        tr, te = X.day != d, X.day == d
        m = LogisticRegression(C=1.0, max_iter=500).fit(X.loc[tr, F], X.y[tr])
        X.loc[te, "comb"] = m.decision_function(X.loc[te, F])
    rng = np.random.default_rng(0)
    X["cold"] = X.id.isin(cold)
    X["pd"] = X.person + "|" + X.day

    def metrics(score):
        s = X[score].values + rng.random(len(X)) * 1e-9
        Y = X.assign(s=s)
        Y["rk"] = Y.groupby("pd").s.rank(ascending=False, method="first")
        V = Y[Y.y == 1][["pd", "id", "s", "rk", "cold", "browser", "has_seg"]]
        N = Y[Y.y == 0][["pd", "s"]]
        M = V.merge(N, on="pd", suffixes=("", "_n"))
        auc = (M.s_n < M.s).groupby([M.pd, M.id]).mean().rename("auc")
        return V.set_index(["pd", "id"]).join(auc).reset_index()

    R = {sc: metrics(sc) for sc in ("p", "segf", "comb")}
    res = {"K": K, "rows": int(len(X)), "person_days": int(X.pd.nunique()), "votes": int(X.y.sum()),
           "share_votes_with_segment": round(float(X[X.y == 1].has_seg.mean()), 3), "lr_coefs_note": "LODO logistic on " + ",".join(F), "table": {}}
    names = {"p": "it9b", "segf": "seg", "comb": "it9b+seg"}
    for pop, pm in (("voters", None), ("browsers", "browser")):
        for who in ("with_segment", "all_people"):
            for grp in ("all", "cold", "warm"):
                key = f"{pop} | {who} | {grp} votes"; row = {}
                base = None
                for sc, V in R.items():
                    m = np.ones(len(V), bool)
                    if pm: m &= V[pm].values
                    if who == "with_segment": m &= V.has_seg.values > 0
                    if grp == "cold": m &= V.cold.values
                    if grp == "warm": m &= ~V.cold.values
                    g = V[m]
                    row[names[sc]] = {"hit1": round(float((g.rk <= 1).mean()), 3), "hit3": round(float((g.rk <= 3).mean()), 3), "auc": round(float(g.auc.mean()), 3), "votes": int(len(g))}
                    if sc == "p": base = g.set_index(["pd", "id"])
                    if sc == "comb":
                        c = g.set_index(["pd", "id"]).join(base[["rk", "auc"]], rsuffix="_b")
                        pdk = c.index.get_level_values(0); u = pd.unique(pdk); gi = pd.Series(np.arange(len(u)), index=u)[pdk].values
                        dd = {"auc": (c.auc - c.auc_b).values, "hit1": ((c.rk <= 1).astype(float) - (c.rk_b <= 1).astype(float)).values}
                        out = {}
                        for k2, v in dd.items():
                            ok_ = ~np.isnan(v); v2, g2 = v[ok_], gi[ok_]
                            sums = np.bincount(g2, weights=v2, minlength=len(u)); cnt = np.bincount(g2, minlength=len(u))
                            bs = []
                            for _ in range(1000):
                                w = np.bincount(rng.integers(0, len(u), len(u)), minlength=len(u))
                                bs.append((w * sums).sum() / max(1, (w * cnt).sum()))
                            out[k2] = [round(float(v2.mean()), 3)] + [round(float(x), 3) for x in np.percentile(bs, [2.5, 97.5])]
                        row["it9b+seg - it9b"] = out
                res["table"][key] = row
    json.dump(res, open(os.path.join(HERE, "results", f"seg_person_k{K}.json"), "w"), indent=1)
    for k, v in res["table"].items():
        print(k, json.dumps(v))


if __name__ == "__main__":
    main()
