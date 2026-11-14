import sys, json; sys.path.insert(0, "."); from score_rb import *
A = pd.read_parquet("abc.parquet"); n = A.groupby("day").dailyRank.apply(lambda s: s.notna().sum())
D183 = sorted(n[n >= 10].index); L90 = D183[-90:]; D214 = sorted(n.index)
def S(cols, days): return np.mean([sc(A, c).loc[days].values for c in cols], axis=0)
def d_(a, b, days):
    X, Y = S(a, days), S(b, days); D = Y - X; bs = np.array([D[rng.integers(0, len(D), len(D))].mean(0) for _ in range(5000)])
    return [[round(D[:, k].mean(), 1), round(np.percentile(bs[:, k], 2.5), 1), round(np.percentile(bs[:, k], 97.5), 1)] for k in range(3)]
drop = [f"abc_drop_d{k}" for k in range(3)]
out = {"PRIMARY: abc - base, top 10, 183 days": d_(["base"], ["abc"], D183)[2], "SECONDARY: abc - base, top 3, last 90 of 183 days": d_(["base"], ["abc"], L90)[0],
       "base 183": S(["base"], D183).mean(0).round(1).tolist(), "abc 183": S(["abc"], D183).mean(0).round(1).tolist(),
       "abc - base 183 (t3/t5/t10)": d_(["base"], ["abc"], D183), "abc - base last 90": d_(["base"], ["abc"], L90), "abc - base 214 (extra)": d_(["base"], ["abc"], D214),
       "abc_drop(6% line-up removal) - base 183": d_(["base"], drop, D183), "abc_drop - base last 90": d_(["base"], drop, L90),
       "EXTRA a_only - base 183": d_(["base"], ["a_only"], D183), "EXTRA a_only - base last 90": d_(["base"], ["a_only"], L90),
       "last 90 window": [L90[0], L90[-1]]}
mo = {}
for m in sorted({d[:7] for d in D183}):
    dd = [d for d in D183 if d[:7] == m]; mo[m] = (S(["abc"], dd) - S(["base"], dd)).mean(0).round(1).tolist()
out["abc - base by month (183)"] = mo
p = out["PRIMARY: abc - base, top 10, 183 days"]; s2 = out["SECONDARY: abc - base, top 3, last 90 of 183 days"]
out["verdict"] = {"primary": "PASS" if p[1] > 0 else "FAIL", "secondary": "PASS" if s2[1] > 0 else "FAIL"}
json.dump(out, open("abc_score.json", "w"), indent=1, default=float); print(json.dumps(out, default=float))
