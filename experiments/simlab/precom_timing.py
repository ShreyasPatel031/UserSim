"""How early can the pre-launch commenter count exist? (orchestrator 23:25Z Nov 13). Counts only.
Thread dumps with comment createdAt (backtest: scratchpad cf/page*.jsonl.gz, loader from young_comm.py). Launch live = 00:00 PT of
the launch day (d0). Model definition (young_comm / early_stack): th_n_pre = distinct non-hunter commenters with createdAt <= d0 + 5 min.
Per launch, distinct non-hunter commenters with createdAt <= d0 + c, c in -60, -10, 0, +2, +5, +10, +15, +30 min (also non-team variant).
(1) share of the model's th_n_pre already present at each cut (sum over launches of count_c capped at th_n_pre / sum th_n_pre; and the
    share of launches with th_n_pre > 0 whose cut count equals it); mean within-day Spearman of count_c with th_n_pre.
(2) arm 2 (PH ops' history_retrain_decomp_preds_arm2 'both') + z(log1p count_c), month-forward ridge on within-day z (target
    z(-ln rank)), paired top 3/5/10 vs arm 2 alone, day bootstrap, per cut. Leak: only comments stamped at or before the cut.
    python precom_timing.py <scratchpad> <arm2 parquet> <out dir>
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); SP_, A2P, OUT_ = sys.argv[1:4]; sys.argv = [sys.argv[0], SP_, "", OUT_]
src = open(os.path.join(HERE, "young_comm.py")).read(); exec(src[src.index("import glob, gzip"):src.index("CUTS = {")])
from scipy.stats import spearmanr
CUT = [-60, -10, 0, 2, 5, 10, 15, 30]; rows = []
for i, c in com.items():
    r = L.iloc[i]; o = {"id": r.id}
    for m in CUT:
        lim = r.d0 + pd.Timedelta(minutes=m)
        o[f"c{m}"] = len({p for p, t in c.values() if t <= lim and p != r.h}); o[f"t{m}"] = len({p for p, t in c.values() if t <= lim and p not in r.team})
    rows.append(o)
X = pd.DataFrame(rows).merge(L[["id", "day", "daily_rank"]], on="id"); X["thp"] = X["c5"]
if os.environ.get("DUMP"): X[["id", "day", "c0", "t0"]].to_parquet(os.environ["DUMP"]); sys.exit(0)
A2 = pd.read_parquet(A2P)[["id", "both"]]; A2["id"] = A2.id.astype(str)
res = {"design": __doc__.split("\n    python")[0], "launches with thread dumps": len(X), "days": int(X.day.nunique()), "dump days": [X.day.min(), X.day.max()]}
def dsp(g, a, b):
    v = [spearmanr(x[a], x[b]).correlation for _, x in g.groupby("day") if len(x) >= 5 and x[a].nunique() > 1 and x[b].nunique() > 1]; return [round(float(np.mean(v)), 3), len(v)] if v else None
o1 = {"launches with th_n_pre > 0": int((X.thp > 0).sum()), "mean th_n_pre": round(float(X.thp.mean()), 2)}
for m in CUT:
    o1[f"{m:+d} min"] = {"share of th_n_pre present": round(float(np.minimum(X[f"c{m}"], X.thp).sum() / max(X.thp.sum(), 1)), 3),
        "launches (th_n_pre>0) already complete": round(float((X[X.thp > 0][f"c{m}"] >= X[X.thp > 0].thp).mean()), 3),
        "within-day Spearman with th_n_pre": dsp(X, f"c{m}", "thp"), "mean count (non-hunter / non-team)": [round(float(X[f"c{m}"].mean()), 2), round(float(X[f"t{m}"].mean()), 2)]}
res["(1) timing"] = o1
M = X.merge(A2, on="id"); M = M[M.groupby("day").id.transform("count") >= 10].copy(); M["mon"] = M.day.str[:7]; M["rank"] = M.daily_rank.astype(float)
z = lambda s: (s - s.mean()) / (s.std() or 1)
M["y"] = M.groupby("day")["rank"].transform(lambda r: z(-np.log(r))); M["zb"] = M.groupby("day").both.transform(z)
for m in CUT:
    for p in ("c", "t"): M[f"z{p}{m}"] = M.groupby("day")[f"{p}{m}"].transform(lambda s: z(np.log1p(s)))
mons = sorted(M.mon.unique()); ARMS = {"arm2": ["zb"], **{f"arm2 + non-hunter commenters @ {m:+d}": ["zb", f"zc{m}"] for m in CUT}, **{f"arm2 + non-team commenters @ {m:+d}": ["zb", f"zt{m}"] for m in (0, 2, 5, 30)}}
for a, Xc in ARMS.items():
    M["p_" + a] = np.nan
    for mo in mons[1:]:
        tr, te = M[M.mon < mo], M[M.mon == mo]; M.loc[te.index, "p_" + a] = Ridge(alpha=10).fit(tr[Xc], tr.y).predict(te[Xc])
T = M[M["p_arm2"].notna()]; days = sorted(T.day.unique())
def dm(g, col):
    o = g.sort_values(col, ascending=False).id.tolist(); t = g.sort_values("rank").id.tolist(); return [len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)]
def pdiff(A, B):
    df = A - B; bs = np.array([df[rng.integers(0, len(df), len(df))].mean(0) for _ in range(4000)])
    return [[round(float(df[:, j].mean()), 1), round(float(np.percentile(bs[:, j], 2.5)), 1), round(float(np.percentile(bs[:, j], 97.5)), 1)] for j in range(3)]
B0 = np.array([dm(T[T.day == d], "p_arm2") for d in days]); o2 = {"scored days": len(days), "first/last": [days[0], days[-1]], "launches": len(T), "arm2 top3/5/10": B0.mean(0).round(1).tolist()}
for a in list(ARMS)[1:]:
    A = np.array([dm(T[T.day == d], "p_" + a) for d in days]); o2[a] = {"top3/5/10": A.mean(0).round(1).tolist(), "vs arm2": pdiff(A, B0)}
res["(2) arm2 + commenters, month-forward"] = o2
os.makedirs(OUT_, exist_ok=True); json.dump(res, open(os.path.join(OUT_, "precom_timing.json"), "w"), indent=1, default=float); print(json.dumps({k: v for k, v in res.items() if k != "design"}, default=float))
