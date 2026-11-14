import sys, json; sys.path.insert(0, "."); from score_rb import *
A = pd.read_parquet("robust.parquet"); n = A.groupby("day").dailyRank.apply(lambda s: s.notna().sum())
D183 = sorted(n[n >= 10].index); D214 = sorted(n.index)
def S(cols, days): return np.mean([sc(A, c).loc[days].values for c in cols], axis=0)
def pd_(X, Y):
    D = Y - X; b = np.array([D[rng.integers(0, len(D), len(D))].mean(0) for _ in range(3000)])
    return [[round(D[:, k].mean(), 1), round(np.percentile(b[:, k], 2.5), 1), round(np.percentile(b[:, k], 97.5), 1)] for k in range(3)]
out = {}
for lab, days in (("183 days (>=10 ranked)", D183), ("214 days (extra)", D214)):
    bc = S(["base|clean"], days); o = {"base clean": bc.mean(0).round(1).tolist()}
    for s in (2.5, 5): o[f"base noisy sd{s}"] = S([f"base|n{s}_d{k}" for k in range(3)], days).mean(0).round(1).tolist()
    for v in ["mono", "pct", "bin3", "bin5", "aug2.5", "aug5"]:
        vc = S([f"{v}|clean"], days); r = {"clean": vc.mean(0).round(1).tolist(), "clean - base clean": pd_(bc, vc)}
        for s in (2.5, 5):
            vn = S([f"{v}|n{s}_d{k}" for k in range(3)], days); bn = S([f"base|n{s}_d{k}" for k in range(3)], days)
            r[f"noisy sd{s} - base noisy sd{s}"] = pd_(bn, vn); r[f"noise loss sd{s} (noisy - own clean), top3"] = round(float((vn - vc)[:, 0].mean()), 1)
        o[v] = r
    out[lab] = o
json.dump(out, open("robust_score.json", "w"), indent=1, default=float); print(json.dumps(out, default=float))
