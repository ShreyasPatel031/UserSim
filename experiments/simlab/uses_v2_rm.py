"""Uses v2, steps S2-S4, on the RICH-MATCHED sets (eval_sets_richmatched.parquet; see uses_richmatched.py). Same design as
uses_v2.py (fixed before running), only the candidate sets change:
  S2  mean top-5 cosine, bge-base on rich text
  S3np / S3  LightGBM (person-disjoint 2-fold, trained on pop-matched tasks) on kNN features (S1+S2 sims, topic rate,
             profile size) without / with popularity
  S4np / S4  + who the person is: headline+bio embedding similarity (small, base), text length, 9 role keyword flags
Paired by person against S0 (card text, bge-small centroid). Primary: pop-matched AUC / Hit@10.
    python uses_v2_rm.py <uses2 dir> <products_info dir>"""
import glob, json, os, re, sys
import numpy as np, pandas as pd
D, PI = sys.argv[1:3]; rng = np.random.default_rng(2)
P = pd.read_parquet(D + "/export/products.parquet"); ix = {s: i for i, s in enumerate(P.slug)}; pop = P["pop"].to_numpy()
R = pd.read_parquet(D + "/export/eval_sets_richmatched.parquet"); PE = pd.read_parquet(D + "/export/people.parquet")
E0, E1, E2 = (np.load(D + f) for f in ("/emb_small_card.npy", "/emb_small_rich.npy", "/emb_base_rich.npy"))
topics = {}
for f in glob.glob(os.path.join(PI, "*.json")):
    try: y = json.load(open(f))
    except Exception: continue
    tp = {t.get("name") for t in (y.get("topics") or []) if isinstance(t, dict)}
    if y.get("slug") in ix and tp: topics[ix[y["slug"]]] = tp
ROLES = {"dev": r"develop|engineer|programm|coder|software|full.?stack|backend|frontend|devops|\bcto\b",
         "design": r"design|\bux\b|\bui\b|creative|artist", "market": r"market|growth|seo|content|brand|social media",
         "founder": r"founder|\bceo\b|entrepreneur|indie ?hacker|maker|builder|bootstrap", "product": r"product manager|\bpm\b|product lead|head of product",
         "data_ai": r"\bai\b|machine learning|\bml\b|data scien|llm|research", "sales": r"sales|\bbd\b|business develop|revenue",
         "student": r"student|universit|college|learning", "invest": r"invest|\bvc\b|angel|partner at"}
who = dict(zip(PE.person_id, PE.headline_bio.fillna("")))
pids = sorted(who); pix = {p: i for i, p in enumerate(pids)}
from sentence_transformers import SentenceTransformer
W1 = SentenceTransformer("BAAI/bge-small-en-v1.5", device="cpu").encode([who[p] or "-" for p in pids], batch_size=128, normalize_embeddings=True, show_progress_bar=False)
W2 = SentenceTransformer("BAAI/bge-base-en-v1.5", device="cpu").encode([who[p] or "-" for p in pids], batch_size=128, normalize_embeddings=True, show_progress_bar=False)
roles = {p: [float(bool(re.search(r, who[p], re.I))) for r in ROLES.values()] for p in pids}
mine = {p: {ix[s] for k in ("stack", "review", "collection", "upvote") for s in r[k] if s in ix} for p, r in zip(PE.person_id, PE.to_dict("records"))}
rows = []
for ti, r in enumerate(R.itertuples()):
    cand = np.array([ix[r.heldout]] + [ix[s] for s in r.negatives]); prof = np.array([ix[s] for s in r.profile]); n = len(cand)
    f = {"task": np.full(n, ti), "pidx": np.full(n, pix[r.person_id]), "kind": r.neg_kind, "type": r.type, "hr": r.heldout_rich, "y": np.r_[1, np.zeros(n - 1)]}
    f["pop"] = np.log1p(pop[cand] - np.array([c in mine[r.person_id] for c in cand]))
    for nm, E in (("s0", E0), ("s1", E1), ("s2", E2)):
        S = E[cand] @ E[prof].T; Ss = np.sort(S, 1); k = min(5, S.shape[1])
        f[nm + "_top1"], f[nm + "_top5"], f[nm + "_mean"] = Ss[:, -1], Ss[:, -k:].mean(1), S.mean(1)
    pt = [topics.get(i, set()) for i in prof]; nt = sum(1 for x in pt if x) or 1
    f["topic_rate"] = np.array([sum(1 for x in pt if x & topics[c]) / nt if c in topics else np.nan for c in cand])
    f["n_prof"] = np.full(n, np.log1p(len(prof)))
    pi = pix[r.person_id]; f["who_s"] = E1[cand] @ W1[pi]; f["who_b"] = E2[cand] @ W2[pi]; f["who_len"] = np.full(n, float(len(who[r.person_id])))
    for k_, v in zip(ROLES, roles[r.person_id]): f["role_" + k_] = np.full(n, v)
    rows.append(pd.DataFrame(f))
X = pd.concat(rows, ignore_index=True); print("rows", len(X), flush=True)
import lightgbm as lgb
fold = (X.pidx % 2).to_numpy()
base = ["s1_top1", "s1_top5", "s1_mean", "s2_top1", "s2_top5", "s2_mean", "topic_rate", "n_prof"]
whof = ["who_s", "who_b", "who_len"] + ["role_" + r for r in ROLES]
FS = {"S3np": base, "S3": base + ["pop"], "S4np": base + whof, "S4": base + ["pop"] + whof}
for nm, cols in FS.items():
    X[nm] = np.nan
    for k in (0, 1):
        tr = (fold != k) & (X.kind == "pop_matched").to_numpy(); te = fold == k
        m = lgb.LGBMClassifier(n_estimators=300, learning_rate=0.05, num_leaves=31, min_child_samples=200, subsample=0.8, subsample_freq=1,
                               colsample_bytree=0.8, verbose=-1).fit(X.loc[tr, cols], X.y[tr])
        X.loc[te, nm] = m.predict_proba(X.loc[te, cols])[:, 1]
X["S0"], X["S1"], X["S2"], X["POP"] = X.s0_top5, X.s1_top5, X.s2_top5, X["pop"]
def per_task(s):
    v = X[s].to_numpy(float) + rng.random(len(X)) * 1e-9; task = X.task.to_numpy(); y = X.y.to_numpy()
    start = np.r_[0, np.flatnonzero(np.diff(task)) + 1]; size = np.diff(np.r_[start, len(X)])
    tgt = np.repeat(v[start], size); neg = y == 0
    above = np.add.reduceat((v > tgt) & neg, start); below = np.add.reduceat((v < tgt) & neg, start)
    first = X.iloc[start]
    return pd.DataFrame({"auc": below / (size - 1), "h10": (above + 1 <= 10).astype(float), "h1": (above == 0).astype(float),
                         "pidx": first.pidx.to_numpy(), "kind": first.kind.to_numpy(), "hr": first.hr.to_numpy(), "type": first.type.to_numpy()})
def boot(v, B=2000):
    v = np.asarray(v, float); bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(B)]
    return [round(float(v.mean()), 4), round(float(np.percentile(bs, 2.5)), 4), round(float(np.percentile(bs, 97.5)), 4)]
T = {s: per_task(s) for s in ("POP", "S0", "S1", "S2", "S3np", "S3", "S4np", "S4")}
res = {}
for kind in ("pop_matched", "random"):
    for sub in ("all", "heldout rich"):
        out = {}
        sel = lambda d: d[(d.kind == kind) & (d.hr if sub == "heldout rich" else True)]
        b = sel(T["S0"]).groupby("pidx").auc.mean(); bh = sel(T["S0"]).groupby("pidx").h10.mean()
        for s, d in T.items():
            g = sel(d).groupby("pidx")[["auc", "h10", "h1"]].mean()
            out[s] = {"auc": boot(g.auc), "h10": boot(g.h10), "h1": boot(g.h1)}
            if s != "S0": out[s]["auc-S0"] = boot((g.auc - b).dropna()); out[s]["h10-S0"] = boot((g.h10 - bh).dropna())
        res[f"{kind} | {sub}"] = out
json.dump(res, open(D + "/uses_v2_rm.json", "w"), indent=1); print(json.dumps(res, indent=1))
