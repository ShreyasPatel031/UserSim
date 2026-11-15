import json, sys, numpy as np, pandas as pd
SP = sys.argv[1]; OUT = f"{SP}/kinds"; rng = np.random.default_rng(0)
L = pd.read_parquet(f"{OUT}/launches_k.parquet"); P = pd.read_parquet(f"{OUT}/people.parquet").set_index("person_id"); A = pd.read_parquet(f"{OUT}/attrs.parquet")
O = json.load(open(f"{OUT}/analysis.json")); kn = {k["id"]: k["name"] for k in O["kinds"]}
E = pd.read_parquet(f"{SP}/store_live/events.parquet", columns=["person_id", "kind", "target_id"])
U = E[E.kind == "upvote"][["person_id", "target_id"]].drop_duplicates(); U["target_id"] = U.target_id.astype(str)
U = U[U.target_id.isin(set(L.id[L.day < "2026-11-15"])) & U.person_id.isin(set(P.index))].reset_index(drop=True)
U["k"] = U.target_id.map(dict(zip(L.id, L.kind))); U["m"] = U.target_id.map(dict(zip(L.id, L.day.str[:7]))); n = U.groupby("person_id").size()
for K in (3, 5):
    U["t"] = U.person_id.map(P[f"t{K}"])
    print(f"\n=== taste k={K}: people", P[f"t{K}"].value_counts().sort_index().to_dict(), "votes", U.t.value_counts(normalize=True).sort_index().round(3).to_dict())
    print("cluster x month (share of the cluster's votes):"); print(pd.crosstab(U.t, U.m, normalize="index").round(2).to_string())
    # separation controlling for month: baseline = that month's mix
    def tv(z):
        ct = pd.crosstab(U.target_id.values, z); ct = ct[ct.sum(1) >= 30]; mix = ct.div(ct.sum(1), axis=0)
        mm = pd.crosstab(U.m.values, z, normalize="index"); base = mm.reindex(mix.index.map(dict(zip(L.id, L.day.str[:7])))).values
        return float((0.5 * np.abs(mix.values - base).sum(1)).mean())
    def perm():   # shuffle labels among votes WITHIN month
        z = U.t.values.copy()
        for m_, ix in U.groupby("m").indices.items(): z[ix] = rng.permutation(z[ix])
        return z
    o = tv(U.t.values); c = np.mean([tv(perm()) for _ in range(5)]); print("separation within month: observed", round(o, 4), "chance", round(c, 4), "ratio", round(o / c, 2))
    lt = pd.crosstab(U.t, U.k, normalize="index") / U.k.value_counts(normalize=True).sort_index().values; lt.columns = [kn[c] for c in lt.columns]
    print("cluster x product kind lift:"); print(lt.round(2).T.to_string())
    UA = U.join(A, on="person_id"); cols = ["developer", "founder", "marketer", "designer", "investor", "student", "has launched a product", "new account (< 1 year)", "veteran (5+ years)", "heavy voter (top 10%)"]
    pa = A.join(P[f"t{K}"]).groupby(f"t{K}")[cols].mean() / A[cols].mean(); print("cluster x attribute lift (per person):"); print(pa.round(2).T.to_string())
    print("median votes per person:", n.groupby(P[f"t{K}"].reindex(n.index)).median().to_dict())
# selective voters only (below the top 10% by votes): attribute x kind lift
sel = set(n[n < n.quantile(0.9)].index); Us = U[U.person_id.isin(sel)].join(A, on="person_id"); cols = ["developer", "founder", "marketer", "designer", "investor", "student", "product manager", "has launched a product", "new account (< 1 year)"]
ls = Us.groupby("k")[cols].mean() / Us[cols].mean(); ls.index = [kn[i] for i in ls.index]; print("\n=== selective voters (bottom 90% by votes;", len(Us), "votes): attribute x kind lift"); print(ls.round(2).to_string())
