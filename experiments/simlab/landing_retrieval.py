"""Where would a product land? Retrieval of similar past launches vs the PH agent's product-only ridge (orchestrator 23:20Z
Nov 11). Base = web_launch_band.py's product-only ridge (TF-IDF 1-2 grams + top-80 topic flags + lengths, Ridge alpha 3,
target ln(1+votes), month-forward from the third month; 222 days with >= 10 launches), re-implemented on the same warehouse
launches table.
Retrieval features for launch L on day d (neighbours = launches dated strictly before d; excluded: same slug stem, same
name, any shared real maker/poster), embedding = gemini-embedding-001 256-d of "name. tagline. description[:800]":
  for k in 5, 10, 25: mean / median ln(1+votes), mean within-day rank percentile, share top 3, share top 10,
  similarity-weighted mean ln(1+votes); max similarity; topic base rates (first topic) over launches before d: mean
  ln(1+votes), share top 10, count.
Models (month-forward, same months): RIDGE+R = base design + standardised retrieval block; LGBM+R = LightGBM on retrieval
block + lengths + n_topics + the base ridge's held-out score; and on top of the FULL honest launch model (207 comment-forecast
days): ridge(honest LM + retrieval block), month-forward.
Metrics: within-day Spearman with -daily rank, daily top 3/5/10 overlap; paired by day vs the base, 4000 day-bootstrap draws.
Band calibration: rank band = 10th-90th percentile of final daily rank among earlier months' launches in the same score
decile (decile cut points from earlier months too); coverage = share of month-m launches whose true rank falls in the band.
    python landing_retrieval.py <launches dir> <honest_preds.parquet> <out dir>
"""
import glob, json, os, re, subprocess, sys, time, urllib.request
import numpy as np, pandas as pd
from scipy import sparse
from scipy.stats import spearmanr
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import Ridge
import lightgbm as lgb

LDIR, HON, OUT = sys.argv[1:4]; os.makedirs(OUT, exist_ok=True); rng = np.random.default_rng(0)
EMB = "https://us-central1-aiplatform.googleapis.com/v1/projects/project-amer-scs-sandbox/locations/us-central1/publishers/google/models/gemini-embedding-001:predict"
TOKEN = r"(?u)\b[a-z0-9]+\b"
_tok = {"t": "", "at": 0}


def token():
    if time.time() - _tok["at"] > 300:
        _tok["t"] = subprocess.check_output(["gcloud", "auth", "print-access-token"], text=True).strip(); _tok["at"] = time.time()
    return _tok["t"]


def embed(texts):
    out = []
    for i in range(0, len(texts), 200):
        for a in range(6):
            try:
                req = urllib.request.Request(EMB, json.dumps({"instances": [{"content": t[:2000], "task_type": "SEMANTIC_SIMILARITY"} for t in texts[i:i + 200]],
                                                              "parameters": {"outputDimensionality": 256}}).encode(), {"Authorization": "Bearer " + token(), "Content-Type": "application/json"})
                out.append(np.array([p["embeddings"]["values"] for p in json.load(urllib.request.urlopen(req, timeout=180))["predictions"]], np.float32)); break
            except Exception as e:  # noqa: BLE001
                print("retry", a, str(e)[:100], flush=True); time.sleep(4 * (a + 1))
    E = np.vstack(out); return E / (np.linalg.norm(E, axis=1, keepdims=True) + 1e-9)


L = pd.concat([pd.read_parquet(f) for f in glob.glob(os.path.join(LDIR, "*.parquet"))]).sort_values("updated_at").drop_duplicates("id", keep="last")
L = L[L.daily_rank.notna() & L.votes.notna() & (L.day < "2026-11-11")].copy().sort_values(["day", "id"]).reset_index(drop=True)
L["id"] = L.id.astype(str); L["tp"] = [json.loads(t) if isinstance(t, str) and t.startswith("[") else [] for t in L.topics]
L["text"] = (L.name.fillna("") + ". " + L.tagline.fillna("") + ". " + L.description.fillna("") + " " + L.tp.str.join(" ")).str.lower()
L["y"] = np.log1p(pd.to_numeric(L.votes, errors="coerce").astype(float)); L["rank"] = L.daily_rank.astype(float)
L["rpct"] = L.groupby("day")["rank"].rank(pct=True); L["mon"] = L.day.str[:7]; L["topic"] = L.tp.map(lambda t: t[0] if t else "none")
L["team"] = [{str(u).lower() for u in (json.loads(m) if isinstance(m, str) and m.startswith("[") else []) if u and not str(u).startswith("[")} | ({str(p).lower()} if p else set())
             for m, p in zip(L.makers, L.poster)]
L["stem"] = L.slug.str.replace(r"-\d+$", "", regex=True); L["lname"] = L.name.str.lower()
ef = os.path.join(OUT, "launch_emb256.npy")
if os.path.exists(ef) and np.load(ef).shape[0] == len(L): E = np.load(ef)
else: E = embed([f"{a}. {b}. {(c or '')[:800]}" for a, b, c in zip(L.name, L.tagline, L.description)]); np.save(ef, E)
print("launches", len(L), "emb", E.shape, flush=True)

# ---------- retrieval features
days = L.day.to_numpy(); y = L.y.to_numpy(); rp = L.rpct.to_numpy(); t3 = (L["rank"] <= 3).to_numpy(float); t10 = (L["rank"] <= 10).to_numpy(float)
KS = (5, 10, 25); F = {}
for i in range(len(L)):
    prev = np.flatnonzero(days < days[i])
    if len(prev) < 30: continue
    s = E[prev] @ E[i]; order = prev[np.argsort(-s)]; ss = np.sort(s)[::-1]
    keep, ks = [], []
    for j, sv in zip(order[:200], ss[:200]):
        if L.stem.iat[j] == L.stem.iat[i] or L.lname.iat[j] == L.lname.iat[i] or (L.team.iat[j] & L.team.iat[i]): continue
        keep.append(j); ks.append(sv)
        if len(keep) == max(KS): break
    keep, ks = np.array(keep), np.array(ks); f = {"r_maxsim": ks[0]}
    for k in KS:
        jj, ww = keep[:k], np.clip(ks[:k], 1e-3, None)
        f.update({f"r{k}_ymean": y[jj].mean(), f"r{k}_ymed": np.median(y[jj]), f"r{k}_rpct": rp[jj].mean(), f"r{k}_top3": t3[jj].mean(),
                  f"r{k}_top10": t10[jj].mean(), f"r{k}_yw": (y[jj] * ww).sum() / ww.sum()})
    tm = prev[L.topic.to_numpy()[prev] == L.topic.iat[i]]
    f.update({"t_ymean": y[tm].mean() if len(tm) else y[prev].mean(), "t_top10": t10[tm].mean() if len(tm) else t10[prev].mean(), "t_n": np.log1p(len(tm))})
    F[i] = f
R = pd.DataFrame.from_dict(F, orient="index"); RC = list(R.columns)
L = L.join(R); print("retrieval features for", len(R), flush=True)

# ---------- base ridge (web_launch_band design) and variants, month-forward
top_topics = pd.Series([t for s in L.tp for t in s]).value_counts().head(80).index.tolist()
def dense(D):
    return np.c_[np.array([[float(t in s) for t in top_topics] for s in D.tp]), np.log1p(D.description.fillna("").str.len()), np.log1p(D.tagline.fillna("").str.len()), D.tp.str.len()]
mons = sorted(L.mon.unique()); L["base"] = np.nan; L["ridgeR"] = np.nan; L["lgbR"] = np.nan
for m in mons[2:]:
    tr, te = L[L.mon < m], L[L.mon == m]
    vec = TfidfVectorizer(token_pattern=TOKEN, ngram_range=(1, 2), min_df=5, max_features=4000, sublinear_tf=True)
    Xt, Xe = vec.fit_transform(tr.text), vec.transform(te.text)
    Dt, De = dense(tr), dense(te); mu, sd = Dt.mean(0), Dt.std(0) + 1e-9
    A_t = sparse.hstack([Xt, sparse.csr_matrix((Dt - mu) / sd)]).tocsr(); A_e = sparse.hstack([Xe, sparse.csr_matrix((De - mu) / sd)]).tocsr()
    L.loc[te.index, "base"] = Ridge(alpha=3.0).fit(A_t, tr.y).predict(A_e)
    trr = tr[tr[RC[0]].notna()]; rmu, rsd = trr[RC].mean(), trr[RC].std() + 1e-9
    Rt = sparse.csr_matrix(((tr[RC] - rmu) / rsd).fillna(0).to_numpy()); Re = sparse.csr_matrix(((te[RC] - rmu) / rsd).fillna(0).to_numpy())
    L.loc[te.index, "ridgeR"] = Ridge(alpha=3.0).fit(sparse.hstack([A_t, Rt]).tocsr(), tr.y).predict(sparse.hstack([A_e, Re]).tocsr())
lg_cols = RC + ["base", "dlen", "tlen", "ntp"]
L["dlen"] = np.log1p(L.description.fillna("").str.len()); L["tlen"] = np.log1p(L.tagline.fillna("").str.len()); L["ntp"] = L.tp.str.len()
for m in mons[3:]:
    tr, te = L[(L.mon < m) & L.base.notna()], L[L.mon == m]
    L.loc[te.index, "lgbR"] = lgb.LGBMRegressor(n_estimators=400, learning_rate=0.03, num_leaves=15, min_child_samples=40, subsample=0.8, subsample_freq=1,
                                               colsample_bytree=0.8, verbose=-1, random_state=0).fit(tr[lg_cols], tr.y).predict(te[lg_cols])


def per_day(D, col):
    out = {}
    for d, g in D.groupby("day"):
        if len(g) >= 10 and g[col].notna().all():
            out[d] = [spearmanr(g[col], -g["rank"]).correlation * 100] + [len(set(g.nlargest(k, col).id) & set(g.nsmallest(k, "rank").id)) / k * 100 for k in (3, 5, 10)]
    return pd.DataFrame(out, index=["spearman", "top3", "top5", "top10"]).T


def boot(v, B=4000):
    v = np.asarray(v, float); bs = np.array([v[rng.integers(0, len(v), len(v))].mean(0) for _ in range(B)])
    return {k: [round(float(v[:, j].mean()), 1), round(float(np.percentile(bs[:, j], 2.5)), 1), round(float(np.percentile(bs, 97.5, axis=0)[j]), 1)] for j, k in enumerate(["spearman", "top3", "top5", "top10"])}


res = {"design": __doc__.split("\n    python")[0], "n_launches": int(len(L))}
B0 = per_day(L, "base"); res["days"] = int(len(B0)); res["base product-only ridge"] = boot(B0.values)
for c, nm in (("ridgeR", "ridge + retrieval"), ("lgbR", "LightGBM + retrieval")):
    D = per_day(L, c); j = D.index.intersection(B0.index)
    res[nm] = boot(D.loc[j].values); res[nm + " - base (paired)"] = boot((D.loc[j] - B0.loc[j]).values); res[nm + " days"] = int(len(j))
for k in KS:                                                       # retrieval alone
    D = per_day(L, f"r{k}_yw"); j = D.index.intersection(B0.index); res[f"retrieval only r{k}_yw"] = boot(D.loc[j].values)


# band calibration (month-forward: deciles and rank bands from earlier months)
def coverage(col):
    cov, n = 0, 0
    for m in mons[3:]:
        tr, te = L[(L.mon < m) & L[col].notna()], L[(L.mon == m) & L[col].notna()]
        if not len(te) or len(tr) < 500: continue
        cuts = np.percentile(tr[col], np.arange(10, 100, 10)); dt, de = np.searchsorted(cuts, tr[col]), np.searchsorted(cuts, te[col])
        lo = {d_: np.percentile(tr["rank"][dt == d_], 10) for d_ in range(10)}; hi = {d_: np.percentile(tr["rank"][dt == d_], 90) for d_ in range(10)}
        ok = [(lo[d_] <= r <= hi[d_]) for d_, r in zip(de, te["rank"])]; cov += sum(ok); n += len(ok)
    return round(cov / n, 3), n
res["band 10-90% coverage (target 0.80)"] = {"base": coverage("base"), "ridge + retrieval": coverage("ridgeR"), "LightGBM + retrieval": coverage("lgbR")}

# on top of the full honest launch model
H = pd.read_parquet(HON)[["id", "honest"]]; H["id"] = H.id.astype(str)
M = L.merge(H, on="id", how="inner"); M["full"] = np.nan; M["fullR"] = np.nan
cols = ["honest"] + RC
for m in sorted(M.mon.unique())[1:]:
    tr, te = M[(M.mon < m) & M[RC[0]].notna()], M[M.mon == m]
    mu, sd = tr[cols].mean(), tr[cols].std() + 1e-9
    M.loc[te.index, "fullR"] = Ridge(alpha=10.0).fit(((tr[cols] - mu) / sd).fillna(0), tr.y).predict(((te[cols] - mu) / sd).fillna(0))
    M.loc[te.index, "full"] = te.honest
F0 = per_day(M, "full"); F1 = per_day(M, "fullR"); j = F0.index.intersection(F1.index)
res["full LM only"] = boot(F0.loc[j].values); res["full LM + retrieval"] = boot(F1.loc[j].values)
res["full LM + retrieval - LM (paired)"] = boot((F1.loc[j] - F0.loc[j]).values); res["full days"] = int(len(j))
L[["id", "day", "base", "ridgeR", "lgbR"] + RC].to_parquet(os.path.join(OUT, "landing_rows.parquet"), index=False)
json.dump(res, open(os.path.join(OUT, "landing_retrieval.json"), "w"), indent=1)
print(json.dumps({k: v for k, v in res.items() if k != "design"}, indent=1))
