"""Score e5_tiebreak.py output. Days: >= 10 ranked launches. Tie rule at cut k (3 / 5 / 10): in arm 2's order (10-seed mean), if
pick k and pick k+1 differ by < thr predicted log-votes, the tie-breaker decides which of the two is inside the top k (NaN = no say).
Tie-breakers (higher = better): arm3, clean_nosite, readable, hist_hunter_rel, llm_pitch, meanrank (mean within-day rank of the others
available that year). SELECTION on 2025 only: grid thr x tie-breaker, objective = mean top-3 change vs arm 2 (ties -> smaller thr, then
list order). TEST once on 2026 (183-day rule): primary top 3 all days, secondary top 3 on near-tie days (cut-3 gap < chosen thr);
paired day bootstrap 10000.      python score_tiebreak.py <tiebreak parquet> <out json>"""
import json, sys
import numpy as np, pandas as pd
D = pd.read_parquet(sys.argv[1]); rng = np.random.default_rng(0)
TB = ["arm3", "clean_nosite", "readable", "hist_hunter_rel", "llm_pitch", "meanrank"]; THR = [0.01, 0.02, 0.037, 0.05, 0.075, 0.10]
def prep(g):
    g = g.sort_values(["arm2", "id"], ascending=[False, True]).reset_index(drop=True)
    av = [c for c in TB[:-1] if g[c].notna().any()]
    g["meanrank"] = -np.mean([g[c].rank(ascending=False, na_option="keep").fillna(len(g) / 2 + .5).values for c in av], axis=0)
    return g
days = {d: prep(g) for d, g in D.groupby("day") if g.dailyRank.notna().sum() >= 10}
def hits(g, k, tb=None, thr=0.0):
    pick = list(range(k)); changed = 0
    if tb is not None and len(g) > k and g.arm2[k - 1] - g.arm2[k] < thr:
        a, b = g[tb][k - 1], g[tb][k]
        if pd.notna(a) and pd.notna(b) and b > a: pick[k - 1] = k; changed = 1
    return float((g.dailyRank.values[pick] <= k).mean() * 100), changed
def tab(ds, tb, thr, k):
    r = np.array([[hits(days[d], k)[0], *hits(days[d], k, tb, thr)] for d in ds]); return r   # base, new, changed
def ci(x):
    b = [x[rng.integers(0, len(x), len(x))].mean() for _ in range(10000)]; return [round(float(x.mean()), 2), round(float(np.percentile(b, 2.5)), 2), round(float(np.percentile(b, 97.5)), 2)]
y25 = sorted(d for d in days if d < "2026"); y26 = sorted(d for d in days if d >= "2026")
grid = {}
for tb in TB:
    if tb == "clean_nosite": continue   # identical to arm 2 in 2025 (same training rows): cannot be chosen there
    for thr in THR:
        r = tab(y25, tb, thr, 3); grid[f"{tb} | {thr}"] = {"top3 change": round(float((r[:, 1] - r[:, 0]).mean()), 3), "picks changed %": round(float(r[:, 2].mean() * 100), 1)}
best = max(grid.items(), key=lambda kv: (kv[1]["top3 change"], -float(kv[0].split(" | ")[1]), -TB.index(kv[0].split(" | ")[0])))
TBc, THc = best[0].split(" | ")[0], float(best[0].split(" | ")[1])
out = {"2025 days": len(y25), "2026 days": len(y26), "2025 grid (top-3 change vs arm 2, picks changed % at cut 3)": grid,
       "2025 choice": {"tie-breaker": TBc, "threshold": THc, **best[1]}}
res = {}
for k in (3, 5, 10):
    r = tab(y26, TBc, THc, k); near = np.array([len(days[d]) > k and days[d].arm2[k - 1] - days[d].arm2[k] < THc for d in y26])
    res[f"top{k}"] = {"arm2 %": round(float(r[:, 0].mean()), 1), "with tie-breaker %": round(float(r[:, 1].mean()), 1), "change [CI]": ci(r[:, 1] - r[:, 0]),
                      "near-tie days": int(near.sum()), "near-tie days: arm2 % / with % ": [round(float(r[near, 0].mean()), 1), round(float(r[near, 1].mean()), 1)],
                      "near-tie days change [CI]": ci(r[near, 1] - r[near, 0]) if near.any() else None, "picks changed (days)": int(r[:, 2].sum()),
                      "picks changed % of days": round(float(r[:, 2].mean() * 100), 1)}
out["2026 test (183-day rule)"] = res
nt = np.array([days[d].arm2[2] - days[d].arm2[3] < 0.037 for d in y26])
out["check: 2026 near-tie at 0.037 (cut 3)"] = {"days": int(nt.sum()), "arm2 top3 % near / clear": [round(float(np.mean([hits(days[d], 3)[0] for d in np.array(y26)[nt]])), 1), round(float(np.mean([hits(days[d], 3)[0] for d in np.array(y26)[~nt]])), 1)]}
out["2026 all candidates at the chosen threshold, top 3 (not used for the choice)"] = {tb: ci((lambda r: r[:, 1] - r[:, 0])(tab(y26, tb, THc, 3))) for tb in TB}
json.dump(out, open(sys.argv[2], "w"), indent=1); print(json.dumps({k: v for k, v in out.items() if "grid" not in k}, indent=0))
