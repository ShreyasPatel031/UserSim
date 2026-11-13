"""Leak checks on the held-team increment (orchestrator 20:12Z Nov 13). Features from team_inc.py (exec'd, provenance store) plus:
  asof_any  held team members with >= 1 dated activity BEFORE the launch day (upvote on an earlier-dated launch, or an earlier team role)
  asof180   held team members whose account joined before the launch AND with >= 1 dated activity in the 180 days before the launch
Bases: clean_v3 (honest_preds_v2, Mar - Nov 10) and ARM 2 = PH ops' deployed rank_clean_nosite_h25llm scores ('both',
results/history_retrain_decomp_preds_arm2.parquet, Apr - Oct, 214 days). Month-forward ridge on within-day z (target z(-ln rank)),
base vs base + feature; paired top 3/5/10 day bootstrap; and by launch-age tercile (days before Nov 2: day terciles over the scored
days) the top-3 gain and the within-day partial Spearman of the feature with the base residual (base rank - final rank). Survivorship
predicts larger effects for older launches. Counts only.
    python team_inc2.py <store dir (with provenance)> <scratchpad> <arm2 parquet> <out dir>
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); A2P, OUT2 = sys.argv[3], sys.argv[4]; sys.argv = sys.argv[:3] + [OUT2]
src = open(os.path.join(HERE, "team_inc.py")).read(); exec(src[src.index("import glob, hashlib, json, os, sys"):src.index("L = pd.concat([L.reset_index(drop=True), pd.DataFrame([feats(r) for r in L.itertuples()])], axis=1)")])
JD = pd.to_datetime(P.set_index("person_id").joined, utc=True, errors="coerce") if "joined" in P else pd.Series(dtype=object)
def feats2(r):
    o = feats(r); held = [p for p in r.team if p in comp]; D = pd.Timestamp(r.day); d180 = (D - pd.Timedelta(days=180)).strftime("%Y-%m-%d"); a = b = 0
    for p in held:
        u = UD.get(p, np.array([])); before = u[u < r.day] if len(u) else u; rl = [x for x in roles.get(p, []) if x < r.day]
        if len(before) or rl: a += 1
        j = JD.get(p) if p in JD.index else None; jok = j is not None and pd.notna(j) and j.tz_convert(None) < D
        if jok and ((len(before) and (before >= d180).any()) or any(x >= d180 for x in rl)): b += 1
    o.update({"asof_any": a, "asof180": b}); return o
L = pd.concat([L.reset_index(drop=True), pd.DataFrame([feats2(r) for r in L.itertuples()])], axis=1)
FE = ["held_full", "held_indep", "active90", "estab", "asof_any", "asof180"]; z = lambda s: (s - s.mean()) / (s.std() or 1)
def dm(g, col):
    o = g.sort_values(col, ascending=False).id.tolist(); t = g.sort_values("rank").id.tolist(); return [len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)]
def ci(v, axis_cols=True):
    v = np.asarray(v, float); bs = np.array([v[rng.integers(0, len(v), len(v))].mean(0) for _ in range(4000)])
    if v.ndim == 1: return [round(float(v.mean()), 3), round(float(np.percentile(bs, 2.5)), 3), round(float(np.percentile(bs, 97.5)), 3), len(v)]
    return [[round(float(v[:, j].mean()), 1), round(float(np.percentile(bs[:, j], 2.5)), 1), round(float(np.percentile(bs[:, j], 97.5)), 1)] for j in range(v.shape[1])]
H = pd.read_parquet(f"{SP}/honest_preds_v2.parquet")[["id", "honest"]]; H["id"] = H.id.astype(str)
A2 = pd.read_parquet(A2P)[["id", "both"]]; A2["id"] = A2.id.astype(str)
res = {"design": __doc__.split("\n    python")[0]}
for bname, BS, col in (("clean_v3", H, "honest"), ("arm2 (deployed h25llm)", A2, "both")):
    M = L.merge(BS, on="id"); M = M[M.groupby("day").id.transform("count") >= 10].copy(); M["mon"] = M.day.str[:7]
    M["y"] = M.groupby("day")["rank"].transform(lambda r: z(-np.log(r))); M["zb"] = M.groupby("day")[col].transform(z)
    for f in FE: M["z_" + f] = M.groupby("day")[f].transform(lambda s: z(np.log1p(s)))
    M["resid"] = M.groupby("day")[col].rank(ascending=False) - M["rank"]
    mons = sorted(M.mon.unique()); arms = {"base": ["zb"], **{f: ["zb", "z_" + f] for f in FE}}
    for a, X in arms.items():
        M["p_" + a] = np.nan
        for m in mons[1:]:
            tr, te = M[M.mon < m], M[M.mon == m]; M.loc[te.index, "p_" + a] = Ridge(alpha=10).fit(tr[X], tr.y).predict(te[X])
    T = M[M.p_base.notna()]; days = sorted(T.day.unique()); terc = {d: k for k, part in enumerate(np.array_split(np.array(days), 3)) for d in part}
    B0 = np.array([dm(T[T.day == d], "p_base") for d in days]); o = {"days": len(days), "first/last day": [days[0], days[-1]], "base top3/5/10": B0.mean(0).round(1).tolist()}
    for f in FE:
        A = np.array([dm(T[T.day == d], "p_" + f) for d in days]); df = A - B0
        by = {}
        for k in range(3):
            ix = [i for i, d in enumerate(days) if terc[d] == k]; dd = [d for d in days if terc[d] == k]
            pc = []
            for d in dd:
                g = T[T.day == d]
                if g[f].nunique() > 1: pc.append(spearmanr(g[f], g.resid).correlation)
            by[f"tercile {k} ({dd[0]}..{dd[-1]}, oldest=0)"] = {"top3 gain": ci(df[ix, 0]), "mean within-day Spearman(feature, base residual)": ci(np.array(pc)) if len(pc) > 2 else None}
        o[f"+ {f}"] = {"top3/5/10": A.mean(0).round(1).tolist(), "vs base": ci(df), "launches > 0": int((T[f] > 0).sum()), "by launch age": by}
    res[f"base = {bname}"] = o; print(bname, json.dumps(o, default=float)[:3000], flush=True)
json.dump(res, open(os.path.join(OUT2, "team_inc2.json"), "w"), indent=1, default=float)
