"""Content-to-collaborative cold-start user simulation (orchestrator track, Nov 11). Product-only: no team, maker, hunter,
follow or tie features anywhere. Variants fixed before scoring (log entry 2026-11-11 "cold-start pre-registration"):

  CF   collaborative item vectors from the co-upvote matrix (store_v3 upvotes of all pool people, launch-dated <= cutoff),
       log-weighted, TruncatedSVD k=64, item vectors L2-normalised.
  ENC  content encoder: ridge from the launch's text embedding (bge-small-en-v1.5 of cleaned name + tagline + description +
       topics) to its CF vector, trained on launches dated <= cutoff with >= 3 upvotes.
  V1 "cf_enc"   person vector = recency-weighted mean (half-life 60 d) of the vectors of their upvotes dated <= d-2 (CF vector
                if the item was in the fold's CF fit, else the encoder's vector); score = cos(person, ENC(text of L)).
  V2 "retrieval" score = recency-weighted mean of the top-5 text-embedding cosine similarities between L and the person's
                 past upvoted launches with text (dated <= d-2); also reported: V2max = max similarity.
  V3 "hybrid"   z(V1) + z(V2) within person-day.
Folds: Oct test days use cutoff Oct 18 (first test day - 2); Nov test days use cutoff Oct 30.
Description text is cleaned as in it9b (launch-day thank-you / badge sentences blanked; vote/rank numbers redacted).
Metrics (within each person's day line-up; activity plays no role): Hit@1 / Hit@3 on voting person-days, within-line-up AUC
(person-days with >= 1 positive and >= 1 negative); day-bootstrap 95% CIs; paired by day vs the E5 product-only baseline.

    python cold_start.py <workdir with v3/ launches/> <rows.parquet> <baseline_rows.parquet>
"""
import glob, json, os, re, sys
import numpy as np, pandas as pd
from scipy import sparse
from sklearn.decomposition import TruncatedSVD
from sklearn.linear_model import Ridge
from sklearn.metrics import roc_auc_score

W, ROWS, BASE = sys.argv[1:4]
OUT = os.path.join(W, "out"); os.makedirs(OUT, exist_ok=True)
rng = np.random.default_rng(0)
FOLDS = [("oct", "2026-10-18", "2026-10-20", "2026-10-31"), ("nov", "2026-10-30", "2026-11-01", "2026-11-30")]
HL = 60.0

# ---------- launches + cleaned text + embeddings
L = pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(os.path.join(W, "launches", "*.parquet")))], ignore_index=True)
L = L.sort_values("updated_at").drop_duplicates("id", keep="last").reset_index(drop=True)
BAD = re.compile(r"[^.!?\n]*(product of the (day|week|month)|golden kitty|thank(s| you) (for|everyone)|upvot|hunt(ed)? us|we('re| are) live|launch day)[^.!?\n]*[.!?]?", re.I)
NUM = re.compile(r"(#\s*\d+|\d[\d,.]*\s*(upvotes?|votes?|comments?|rank))", re.I)
def clean(t):
    t = BAD.sub(" ", str(t or "")); return NUM.sub(" ", t)
topics = L.topics.map(lambda s: ", ".join(json.loads(s)) if isinstance(s, str) and s.startswith("[") else "")
text = (L.name.fillna("") + ". " + L.tagline.fillna("").map(clean) + ". " + L.description.fillna("").map(clean).str[:1500] + " Topics: " + topics).tolist()
ef = os.path.join(OUT, "launch_text_emb.npy")
if os.path.exists(ef) and np.load(ef).shape[0] == len(L):
    E = np.load(ef)
else:
    from sentence_transformers import SentenceTransformer
    E = SentenceTransformer("BAAI/bge-small-en-v1.5", device="cpu").encode(text, batch_size=64, normalize_embeddings=True, show_progress_bar=False)
    np.save(ef, E)
lid = {x: i for i, x in enumerate(L.id)}; Lday = L.day.to_numpy()
print("launches", len(L), "emb", E.shape, flush=True)

# ---------- upvotes (all pool people), dated by launch day
ev = pd.read_parquet(os.path.join(W, "v3", "events.parquet"), columns=["person_id", "kind", "target_id", "extra"])
up = ev[ev.kind == "upvote"].drop(columns="kind"); del ev
up["vday"] = up.target_id.map(lambda x: Lday[lid[x]] if x in lid else None)
up["vday"] = up.vday.fillna(up.extra.str.extract(r'"launched_at": "(\d{4}-\d\d-\d\d)')[0])
up = up.dropna(subset=["vday"])[["person_id", "target_id", "vday"]].drop_duplicates()
print("dated upvotes", len(up), flush=True)

R = pd.read_parquet(ROWS); R["li"] = R.launch_id.map(lid)
B = pd.read_parquet(BASE)[["d", "person_id", "launch_id", "product_only"]]
R = R.merge(B, on=["d", "person_id", "launch_id"], how="left")
upg = {p: g for p, g in up.groupby("person_id") if p in set(R.person_id)}

for name, cut, te0, te1 in FOLDS:
    U = up[up.vday <= cut]
    users = {p: i for i, p in enumerate(U.person_id.unique())}; items = {t: i for i, t in enumerate(U.target_id.unique())}
    X = sparse.csr_matrix((np.ones(len(U)), (U.person_id.map(users), U.target_id.map(items))), shape=(len(users), len(items)))
    X.data = np.log1p(X.data); X = X.multiply(1 / np.sqrt(np.asarray(X.sum(0)).ravel() + 1)).tocsr()   # damp popular items
    svd = TruncatedSVD(64, random_state=0).fit(X)
    Q = (svd.components_.T * np.sqrt(svd.singular_values_)); Q /= np.linalg.norm(Q, axis=1, keepdims=True) + 1e-9
    cnt = np.asarray((X > 0).sum(0)).ravel()
    tr = [(lid[t], j) for t, j in items.items() if t in lid and cnt[j] >= 3 and Lday[lid[t]] <= cut]
    ti, tj = np.array([a for a, _ in tr]), np.array([b for _, b in tr])
    order = np.argsort(Lday[ti]); hold = order[-max(50, len(order) // 10):]; fit_ = order[:-len(hold)]   # held-out check: the latest 10%
    enc = Ridge(alpha=1.0).fit(E[ti[fit_]], Q[tj[fit_]])
    ph = enc.predict(E[ti[hold]]); ph /= np.linalg.norm(ph, axis=1, keepdims=True) + 1e-9
    hold_cos = float(np.mean(np.sum(ph * Q[tj[hold]], 1)))
    enc = Ridge(alpha=1.0).fit(E[ti], Q[tj])
    QE = enc.predict(E); QE /= np.linalg.norm(QE, axis=1, keepdims=True) + 1e-9          # content-predicted vector of every launch
    print(name, "users", len(users), "items", len(items), "encoder train", len(ti), "held-out cos", round(hold_cos, 3), flush=True)
    sub = R[(R.d >= te0) & (R.d <= te1)]
    for (p, d), x in sub.groupby(["person_id", "d"]):
        g = upg.get(p)
        if g is None: continue
        g = g[g.vday <= (pd.Timestamp(d) - pd.Timedelta(days=2)).strftime("%Y-%m-%d")]
        if not len(g): continue
        age = (pd.Timestamp(d) - pd.to_datetime(g.vday)).dt.days.to_numpy(); w = 0.5 ** (age / HL)
        vecs, ww, tix, tw = [], [], [], []
        for t, wi in zip(g.target_id, w):
            if t in items: vecs.append(Q[items[t]]); ww.append(wi)
            elif t in lid: vecs.append(QE[lid[t]]); ww.append(wi)
            if t in lid: tix.append(lid[t]); tw.append(wi)
        li = x.li.to_numpy()
        if vecs:
            u = np.average(np.array(vecs), axis=0, weights=ww); u /= np.linalg.norm(u) + 1e-9
            R.loc[x.index, "v1"] = QE[li] @ u
        if tix:
            S = E[li] @ E[np.array(tix)].T; tw = np.array(tw)
            k = min(5, S.shape[1]); top = np.argsort(-S, 1)[:, :k]
            R.loc[x.index, "v2"] = (np.take_along_axis(S, top, 1) * tw[top]).sum(1) / tw[top].sum(1)
            R.loc[x.index, "v2max"] = S.max(1)
    print(name, "scored", flush=True)

for c in ("v1", "v2", "v2max", "product_only"):
    R[c] = R[c].fillna(R.groupby(["d", "person_id"])[c].transform("mean")).fillna(0)
zs = lambda c: R.groupby(["d", "person_id"])[c].transform(lambda s: (s - s.mean()) / (s.std() + 1e-9))
R["v3"] = zs("v1") + zs("v2")


def per_day(s):
    pos = R.groupby(["d", "person_id"]).y.transform("sum"); n = R.groupby(["d", "person_id"]).y.transform("size")
    A = R[pos > 0].copy(); A["r"] = A.groupby(["d", "person_id"])[s].rank(ascending=False, method="first")
    h = A.groupby(["d", "person_id"]).apply(lambda g: pd.Series({"h1": float(g.y[g.r <= 1].sum() > 0), "h3": float(g.y[g.r <= 3].sum() > 0)}))
    Bq = R[(pos > 0) & (pos < n)]
    au = Bq.groupby(["d", "person_id"]).apply(lambda g: roc_auc_score(g.y, g[s]))
    return pd.DataFrame({"Hit@1": h.h1.groupby(level=0).mean(), "Hit@3": h.h3.groupby(level=0).mean(), "AUC": au.groupby(level=0).mean()})


def boot(v, B=4000):
    v = np.asarray(v, float); bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(B)]
    return [round(float(v.mean()), 4), round(float(np.percentile(bs, 2.5)), 4), round(float(np.percentile(bs, 97.5)), 4)]


res = {"rows": int(len(R)), "days": int(R.d.nunique()), "coverage_v1": float(R.v1.ne(0).mean()), "variants": {}}
base = per_day("product_only")
R["rand"] = rng.random(len(R)); res["random"] = {m: boot(v) for m, v in per_day("rand").items()}
res["E5 product-only baseline"] = {m: boot(v) for m, v in base.items()}
for s in ("v1", "v2", "v2max", "v3"):
    pdd = per_day(s)
    res["variants"][s] = {m: boot(pdd[m]) for m in pdd} | {f"{m} minus baseline (paired by day)": boot(pdd[m] - base[m]) for m in pdd}
R[["d", "launch_id", "y", "v1", "v2", "v3"]].to_parquet(os.path.join(OUT, "cold_start_rows.parquet"), index=False)
json.dump(res, open(os.path.join(OUT, "cold_start.json"), "w"), indent=1)
print(json.dumps(res, indent=1))
