"""Retrieval "who it resonates with" as a segment MIX (orchestrator 02:36Z Nov 13). Reuses who_learn.py's people, segments (site
index's 12 segments; a person's segment = nearest centroid of their upvote-topic shares from upvotes dated before the launch day) and
launches. Test = who_eval's page-read launches (Sep 1 - Nov 10) with >= 30 held (complete-store, >= 3 prior upvotes) voters.
Predicted mix for a target (queries = page read or PH description embedding, gemini-embedding-001 256-d):
  RETR20   similarity-weighted mean of the real voter segment shares of the 20 nearest EARLIER launches (>= 15 held voters, same slug
           stem excluded)
  GLOBAL   pooled segment shares of all held voters of launches dated before the target day
  TOPIC    mean voter mix of earlier launches sharing the target's first topic (>= 5 such launches, else GLOBAL)
Metrics per launch: Jensen-Shannon divergence (base 2) of predicted vs real mix (lower is better); top-2 over-indexed hit = overlap of the
predicted top 2 segments by (pred share / GLOBAL share) with the real top 2 by (real share / GLOBAL share) among segments with >= 3
voters, / 2. GLOBAL's top 2 = the two segments most often in the real top 2 over earlier launches (best constant list).
Paired launch bootstrap; replication = Sep vs Oct-Nov separately.
    python who_mix.py <ph-website worktree> <scratchpad> <who_eval out dir> <out dir>
"""
import os, sys, re
HERE = os.path.dirname(os.path.abspath(__file__))
WL = open(os.path.join(HERE, "who_learn.py")).read(); exec(WL[:WL.index('if os.environ.get("EXPORT")')])
from collections import Counter
SH = {k: VC[k] / VC[k].sum() for k in VC}; NV = {k: int(VC[k].sum()) for k in VC}
stem = L.slug.astype(str).str.replace(r"-\d+$", "", regex=True).to_numpy(); tp1 = [(json.loads(t) or ["none"])[0] if isinstance(t, str) and t.startswith("[") else "none" for t in L.topics]
pool = np.array([k for k in pool_ids]); pday = dnum[pool]
def jsd(p, q):
    p = p + 1e-9; q = q + 1e-9; p /= p.sum(); q /= q.sum(); m = (p + q) / 2
    return float(0.5 * (p * np.log2(p / m)).sum() + 0.5 * (q * np.log2(q / m)).sum())
def top2(v, mask=None):
    v = v.copy()
    if mask is not None: v[~mask] = -np.inf
    return set(np.argsort(-v)[:2].tolist())
rows = []
for qi, i in enumerate(S_all):
    k = lix[i]
    if k not in VC or NV[k] < 30: continue
    prev = pool[(pday < dnum[k]) & PEok & (stem[pool] != stem[k])]
    if len(prev) < 50: continue
    G = np.vstack([VC[j] for j in prev]).sum(0); G = G / G.sum()
    tt = [j for j in prev if tp1[j] == tp1[k]]; T_ = np.mean([SH[j] for j in tt], 0) if len(tt) >= 5 else G
    cnt = Counter(s for j in prev for s in top2(SH[j] / (G + 1e-9), VC[j] >= 3)); G2 = {s for s, _ in cnt.most_common(2)}
    real = SH[k]; rt = top2(real / (G + 1e-9), VC[k] >= 3); o = {"id": i, "mon": L.day.iat[k][:7], "nv": NV[k]}
    for path, Q in (("page", QP), ("ph", QH)):
        q = Q[qi]; PEp = np.vstack([emb_of[L.id.iat[j]] for j in prev]); s = PEp @ q; nb = np.argsort(-s)[:20]; w = np.clip(s[nb], 0, None)
        R = (np.vstack([SH[prev[j]] for j in nb]) * w[:, None]).sum(0) / w.sum()
        o[f"sim1_{path}"] = float(s[nb[0]])
        for nm, P in (("RETR20", R), ("GLOBAL", G), ("TOPIC", T_)):
            o[f"jsd_{nm}_{path}"] = jsd(P, real)
            pt = G2 if nm == "GLOBAL" else top2(P / (G + 1e-9))
            o[f"hit_{nm}_{path}"] = len(pt & rt) / 2
    rows.append(o)
D = pd.DataFrame(rows); print("test launches", len(D), D.mon.value_counts().to_dict(), flush=True)
def mb(v, scale=100):
    v = np.asarray(v, float); bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(2000)]
    return [round(float(v.mean()) * scale, 2), round(float(np.percentile(bs, 2.5)) * scale, 2), round(float(np.percentile(bs, 97.5)) * scale, 2), len(v)]
nall = sum(1 for i in S_all if lix[i] in VC and NV[lix[i]] >= 30)
res = {"design": __doc__.split("\n    python")[0], "coverage": {"page_read_launches_Sep_Nov": len(S_all), "with_30plus_held_voters": len(D),
       "share": round(len(D) / len(S_all), 3), "median_held_voters": int(D.nv.median())}}
for sub, m in (("all", D.mon != ""), ("Sep", D.mon == "2026-09"), ("Oct-Nov", D.mon >= "2026-10")):
    d = D[m]
    for path in ("page", "ph"):
        thin = d[f"sim1_{path}"] < np.percentile(D[f"sim1_{path}"], 33.3)
        o = {}
        for met, sc in (("jsd", 100), ("hit", 100)):
            for nm in ("RETR20", "GLOBAL", "TOPIC"): o[f"{met} {nm}"] = mb(d[f"{met}_{nm}_{path}"], sc)
            for ctl in ("GLOBAL", "TOPIC"): o[f"{met} RETR20 - {ctl}"] = mb(d[f"{met}_RETR20_{path}"] - d[f"{met}_{ctl}_{path}"], sc)
        o["jsd RETR20 - GLOBAL, thin third"] = mb((d[f"jsd_RETR20_{path}"] - d[f"jsd_GLOBAL_{path}"])[thin]) if thin.sum() > 10 else None
        res[f"{sub}|{path}"] = o
os.makedirs(OUT, exist_ok=True); json.dump(res, open(os.path.join(OUT, "who_mix.json"), "w"), indent=1, default=float)
for k, v in res.items():
    if k != "design": print(k, v)
