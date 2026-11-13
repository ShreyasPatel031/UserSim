"""Month-forward recalibration of the /try description band so the 80% band covers 80% (orchestrator 19:30Z Nov 13, part c).
Re-uses band_2025.py's month-forward OOF scores (exec'd; arms A0 = current 2026 ln(votes) ridge and A4 = 2025+2026 ln(votes)).
Band: score decile (cut points from earlier months' OOF scores) -> quantiles of the within-day rank percentile among earlier-month
launches in that decile. CURRENT = nominal 10th-90th quantiles, fit on the earlier months. RECAL = nominal level widened per test
month (grid 0.80..0.98) until coverage on the earlier months' own leave-one-month-out is >= 80% (conformal-style; test month never
used). Test: the 856 (Sep 1 - Nov 10) and the 130 fresh; coverage and mean width (share of the day's rank range). Counts only.
    python band_calib.py <scratchpad> <out dir>
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); src = open(os.path.join(HERE, "band_2025.py")).read()
src = src.replace('ARMS = {"A0 2026 ln(votes) [current]": (False, "y_ln"), "A1 2026 pct": (False, "y_pct"), "A2 2025+2026 pct": (True, "y_pct"), "A3 2025+2026 z ln(votes)": (True, "y_zln"), "A4 2025+2026 ln(votes)": (True, "y_ln")}',
                  'ARMS = {"A0 2026 ln(votes) [current]": (False, "y_ln"), "A4 2025+2026 ln(votes)": (True, "y_ln")}')
exec(src[src.index("import glob, json, os, subprocess, sys"):src.index("T6 = pd.read_parquet")])
T6 = pd.read_parquet(os.path.join(SP, "band_v2/test_pct.parquet"))[["id", "set"]]; T6["id"] = T6.id.astype(str)
B = A[(A.yr == 2026)].copy(); B["test"] = B.id.isin(set(T6.id)); setmap = dict(zip(T6.id, T6.set))
def band(train, test, col, lvl):
    cuts = np.quantile(train[col], np.linspace(0.1, 0.9, 9)); da, db = np.digitize(train[col], cuts), np.digitize(test[col], cuts)
    q = (1 - lvl) / 2; lo = {d: np.quantile(train.y_pct.to_numpy()[da == d], q) for d in range(10)}; hi = {d: np.quantile(train.y_pct.to_numpy()[da == d], 1 - q) for d in range(10)}
    l = np.array([lo[d] for d in db]); h = np.array([hi[d] for d in db]); t = test.y_pct.to_numpy(); return (l <= t) & (t <= h), h - l
res = {"design": __doc__.split("\n    python")[0]}
for a in ARMS:
    G = B[B[a].notna()]; out = {"current": [], "recal": []}; lv = {}
    for m in sorted(G[G.test].mon.unique()):
        tr = G[G.mon < m]; te = G[(G.mon == m) & G.test]
        if len(tr) < 200 or not len(te): continue
        c0, w0 = band(tr, te, a, 0.80)
        def loo(lvl):   # leave-one-month-out coverage on earlier months only
            cv = []
            for mm in sorted(tr.mon.unique())[1:]:
                c, _ = band(tr[tr.mon < mm], tr[tr.mon == mm], a, lvl); cv.append(c)
            return np.concatenate(cv).mean() if cv else 0
        lvl = next((x for x in np.round(np.arange(0.80, 0.99, 0.02), 2) if loo(x) >= 0.80), 0.98); lv[m] = float(lvl)
        c1, w1 = band(tr, te, a, lvl)
        out["current"].append(pd.DataFrame({"id": te.id, "cov": c0, "w": w0})); out["recal"].append(pd.DataFrame({"id": te.id, "cov": c1, "w": w1}))
    o = {"nominal level chosen per test month": lv}
    for k, v in out.items():
        D = pd.concat(v); D["set"] = D.id.map(setmap)
        for sub, S in (("856", D), ("fresh 130", D[D.set == "fresh"])):
            bs = [S.cov.to_numpy()[rng.integers(0, len(S), len(S))].mean() for _ in range(2000)]
            o[f"{k} | {sub}"] = {"coverage_80 [CI]": [round(float(S.cov.mean()) * 100, 1), round(float(np.percentile(bs, 2.5)) * 100, 1), round(float(np.percentile(bs, 97.5)) * 100, 1), len(S)],
                                 "mean width (share of day's rank range)": round(float(S.w.mean()) * 100, 1)}
    res[a] = o; print(a, json.dumps(o), flush=True)
json.dump(res, open(os.path.join(OUT, "band_calib.json"), "w"), indent=1, default=float)
