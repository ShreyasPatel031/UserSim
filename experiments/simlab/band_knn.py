"""Retrieval band for /try (orchestrator 02:32Z Nov 13). Predicted percentile-of-day = similarity-weighted mean of the 20 nearest EARLIER
launches' final within-day rank percentile (gemini-embedding-001 256-d, weights = cosine; neighbours dated strictly before the target day;
excluded: same slug stem after dropping "-N", same name, any shared named maker / poster), alone and averaged (rank-normalised within the
evaluated set) with the deployed band score. Test sets = band_v2's 856 (held Sep 1 - Oct 24 page reads + 130 fresh Oct 27 - Nov 10).
  page path: query = "name. tagline. page_excerpt[:800]" of the read (leak-stripped excerpt for fresh); deployed = B0 (band_v2 test_pct)
  PH path:   query = "name. tagline. description[:800]" (landing_retrieval's stored embedding); deployed = the product-only PH ridge
             re-implemented month-forward (landing_rows.base; the live launch_band.json is partly in-sample on these months)
Metrics: pooled Spearman with -rank, paired launch bootstrap vs deployed; thin split = top-1 cosine in the bottom third (per path).
Band calibration: 80% rank-percentile band from the score's decile (cut points and 10th / 90th percentiles of true percentile fit on the
other half: Sep <-> Oct + fresh), coverage and mean width.
    python band_knn.py <launches dir> <honest preds> <land dir> <scratchpad> <out dir>
"""
import os, sys, json, re
import numpy as np, pandas as pd
from scipy.stats import spearmanr
HERE = os.path.dirname(os.path.abspath(__file__)); LD, HON, LAND, SP, OUTK = sys.argv[1:6]
LR = open(os.path.join(HERE, "landing_retrieval.py")).read(); sys.argv = [sys.argv[0], LD, HON, LAND]
exec(LR[:LR.index('print("launches", len(L)')]); os.makedirs(OUTK, exist_ok=True); rng = np.random.default_rng(0)
L["v"] = 1 - (L["rank"] - 0.5) / L.groupby("day")["rank"].transform("count").clip(lower=L["rank"]); pos = {i: k for k, i in enumerate(L.id.astype(str))}
days = L.day.to_numpy(); V = L.v.to_numpy()
def knn(q, i, k=20):
    prev = np.flatnonzero(days < days[i]); s = E[prev] @ q; o = np.argsort(-s); keep, ws = [], []
    for t in o[:300]:
        j = prev[t]
        if L.stem.iat[j] == L.stem.iat[i] or L.lname.iat[j] == L.lname.iat[i] or (L.team.iat[j] & L.team.iat[i]): continue
        keep.append(j); ws.append(max(s[t], 0))
        if len(keep) == k: break
    ws = np.array(ws); return float((V[keep] * ws).sum() / ws.sum()), float(ws[0])
T = pd.read_parquet(os.path.join(SP, "band_v2/test_pct.parquet"))[["id", "set", "rank", "B0"]]; T = T[T.id.isin(pos)].reset_index(drop=True)
LRW = pd.read_parquet(os.path.join(LAND, "landing_rows.parquet"))[["id", "base"]]; LRW["id"] = LRW.id.astype(str); T = T.merge(LRW, on="id", how="left")
K = json.load(open(os.path.join(SP, "band_page/cache.json"))); FK = json.load(open(os.path.join(SP, "try_fixes/cache.json")))
LEAK = re.compile(r"(?i)product\s*hunt|product of the (day|week|month)|#\s*1\s*product|upvote"); RD = {}
for i, v in K.items():
    if "fail" not in v: RD[i] = v
for k, v in FK.items():
    if k.startswith("p|") and "read" in v: RD[k.split("|", 1)[1]] = v["read"] | {"page_excerpt": LEAK.sub(" ", v["read"].get("page_excerpt") or "")}
qtext = [f"{RD[i].get('name') or ''}. {RD[i].get('tagline') or ''}. {(RD[i].get('page_excerpt') or RD[i].get('summary') or '')[:800]}" for i in T.id]
ef = os.path.join(OUTK, "page_q_emb.npy")
QE = np.load(ef) if os.path.exists(ef) and np.load(ef).shape[0] == len(T) else embed(qtext); np.save(ef, QE)
for path in ("page", "ph"):
    kk = [knn(QE[r] if path == "page" else E[pos[i]], pos[i]) for r, i in enumerate(T.id)]
    T[f"knn_{path}"] = [a for a, _ in kk]; T[f"sim1_{path}"] = [b for _, b in kk]
T["dep_page"], T["dep_ph"] = T.B0, T.base
def boot(f, idx, n=2000):
    v = f(idx); bs = [f(idx[rng.integers(0, len(idx), len(idx))]) for _ in range(n)]; return [round(v, 3), round(float(np.percentile(bs, 2.5)), 3), round(float(np.percentile(bs, 97.5)), 3), len(idx)]
sp = lambda s, idx: spearmanr(s[idx], -T["rank"].to_numpy()[idx]).correlation
def calib(score, idx):
    tr = T.set.to_numpy() == "2026-09"; tv = 1 - T["rank"].to_numpy() / T["rank"].max(); truth = T.id.map(lambda i: L.v.iat[pos[i]]).to_numpy(); cov, wid = [], []
    for a, b in ((tr, ~tr), (~tr, tr)):
        cuts = np.quantile(score[a], np.linspace(0.1, 0.9, 9)); da, db = np.digitize(score[a], cuts), np.digitize(score[b], cuts)
        lo = {d: np.quantile(truth[a][da == d], 0.1) for d in range(10)}; hi = {d: np.quantile(truth[a][da == d], 0.9) for d in range(10)}
        for t, d in zip(truth[b], db): cov.append(lo[d] <= t <= hi[d]); wid.append(hi[d] - lo[d])
    return {"coverage_80": round(float(np.mean(cov)) * 100, 1), "mean_width_pct_of_day": round(float(np.mean(wid)) * 100, 1)}
res = {"design": __doc__.split("\n    python")[0]}
for path in ("page", "ph"):
    ok = T[f"dep_{path}"].notna().to_numpy(); n = len(T)
    rk = lambda c: T[c].rank(pct=True).to_numpy()
    S = {"deployed": rk(f"dep_{path}"), "knn20": rk(f"knn_{path}")}; S["blend (mean of ranks)"] = (S["deployed"] + S["knn20"]) / 2
    cut = np.nanpercentile(T[f"sim1_{path}"], 33.3)
    for sub, m in (("all 856", ok), ("fresh", ok & (T.set == "fresh").to_numpy()), ("held Sep-Oct", ok & (T.set != "fresh").to_numpy()),
                   ("thin neighbours (top-1 cos bottom third)", ok & (T[f"sim1_{path}"] < cut).to_numpy()), ("not thin", ok & (T[f"sim1_{path}"] >= cut).to_numpy())):
        idx = np.flatnonzero(m); o = {a: boot(lambda ii, s=s: sp(s, ii), idx) for a, s in S.items()}
        for a in ("knn20", "blend (mean of ranks)"): o[f"{a} - deployed"] = boot(lambda ii, s=S[a]: sp(s, ii) - sp(S["deployed"], ii), idx)
        res[f"{path}|{sub}"] = o
    res[f"{path}|thin_cut_cos"] = round(float(cut), 4)
    res[f"{path}|calibration (80% band, Sep <-> Oct+fresh cross-fit)"] = {a: calib(s, np.arange(n)) for a, s in S.items()}
T.to_parquet(os.path.join(OUTK, "band_knn_rows.parquet")); json.dump(res, open(os.path.join(OUTK, "band_knn.json"), "w"), indent=1, default=float)
for k, v in res.items():
    if k != "design": print(k, v)
