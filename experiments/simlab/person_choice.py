"""Person-day choice test on the grown store (orchestrator 01:56Z Nov 13). Complete people with >= 20 dated upvotes. A person-day = a person
who upvoted >= 1 launch of that day's line-up (launches with a clean 00:05 score, honest_preds_v2). Upvote DATES are the launch's day (the
store holds no real upvote timestamps: page-1 reads are bounded / snapshot), i.e. the vote is assumed to fall on the launch day.
For each voted launch: top-3 hit (ranked in the person's top 3 of the line-up) and ranking accuracy (share of the line-up's other
launches ranked below it). Pair model = logistic regression on (person-day, launch) rows, trained on days Mar 1 - Oct 19 (sample of
person-days), tested on Oct 20 - Nov 10. Feature blocks:
  a pop        within-day z of the clean 00:05 score
  b follows    the person follows the hunter or the first named maker (follow lists are undated snapshots: a possible leak)
  c backed     the person upvoted an earlier launch (strictly before the day) by the same hunter / first named maker
  d cf         topic-taste cosine (history before the day) + share of the person's 50 nearest co-voters (Jaccard on upvotes before
               Oct 20) who backed this launch's team before the day
  e all
Day bootstrap. If d / e clearly beat a: per-launch aggregation over held voters vs clean_nosite + th_n_pre is a follow-up.
    python person_choice.py <store dir> <launches dir> <salt dir> <honest_preds_v2.parquet> <out dir>
"""
import glob, hashlib, json, os, sys
import numpy as np, pandas as pd
from scipy import sparse
from sklearn.linear_model import LogisticRegression
V3, LDIR, SALTD, HP, OUT = sys.argv[1:6]; os.makedirs(OUT, exist_ok=True); rng = np.random.default_rng(0)
SALT = open(os.path.join(SALTD, "salt")).read().strip(); pid = lambda h: "p_" + hashlib.sha256((SALT + "producthunt:" + str(h).lower()).encode()).hexdigest()[:16]
L = pd.concat([pd.read_parquet(f) for f in glob.glob(os.path.join(LDIR, "*.parquet"))]).sort_values("updated_at").drop_duplicates("id", keep="last")
L = L[L.daily_rank.notna()].copy(); L["id"] = L.id.astype(str)
def fmk(m):
    try: ms = json.loads(m) if isinstance(m, str) and m.startswith("[") else []
    except Exception: ms = []
    ms = [x for x in ms if x and not str(x).startswith("[")]; return pid(ms[0]) if ms else None
L["hun"] = [pid(p) if isinstance(p, str) and p and not p.startswith("[") else None for p in L.poster]; L["mak"] = [fmk(m) for m in L.makers]
L["tops"] = [json.loads(s) if isinstance(s, str) and s.startswith("[") else [] for s in L.topics]
TOP = pd.Series([t for ts in L.tops for t in ts]).value_counts().index[:40].tolist(); TI = {t: i for i, t in enumerate(TOP)}
H = pd.read_parquet(HP)[["id", "honest", "day"]]; H["id"] = H.id.astype(str)
LU = L.merge(H[["id", "honest"]], on="id"); LU["pop"] = LU.groupby("day").honest.transform(lambda s: (s - s.mean()) / (s.std() or 1))
lday = dict(zip(L.id, L.day)); team = {i: {t for t in (h, m) if t} for i, h, m in zip(L.id, L.hun, L.mak)}
ltv = {i: np.bincount([TI[t] for t in ts if t in TI], minlength=len(TOP)).astype(np.float32) for i, ts in zip(L.id, L.tops)}
P = pd.read_parquet(os.path.join(V3, "persons.parquet")); COV = set(P[P.complete].person_id)
E = pd.read_parquet(os.path.join(V3, "events.parquet"), columns=["person_id", "kind", "target_id"]); E = E[E.person_id.isin(COV)]
U = E[E.kind == "upvote"].copy(); U["target_id"] = U.target_id.astype(str); U["lday"] = U.target_id.map(lday); U = U[U.lday.notna()].drop_duplicates(["person_id", "target_id"])
nup = U.groupby("person_id").size(); PEOPLE = set(nup[nup >= 20].index); U = U[U.person_id.isin(PEOPLE)]
FO = E[(E.kind == "follows") & E.person_id.isin(PEOPLE)]; fol = FO.groupby("person_id").target_id.agg(set).to_dict()
# backed teams: person -> {team: first day backed}
bt = {}
for p, t, d in zip(U.person_id, U.target_id, U.lday):
    for tm in team.get(t, ()):
        dd = bt.setdefault(p, {}); dd[tm] = min(dd.get(tm, d), d)
# co-vote neighbours from history before Oct 20
CUT = "2026-10-20"; hb = U[U.lday < CUT]; pl = sorted(PEOPLE); pix = {p: i for i, p in enumerate(pl)}; lix = {l: i for i, l in enumerate(sorted(hb.target_id.unique()))}
M = sparse.csr_matrix((np.ones(len(hb), np.float32), (hb.person_id.map(pix).values, hb.target_id.map(lix).values)), shape=(len(pl), len(lix)))
deg = np.asarray(M.sum(1)).ravel(); NB = {}
for s in range(0, len(pl), 2000):
    co = (M[s:s + 2000] @ M.T).toarray(); jac = co / (deg[s:s + 2000, None] + deg[None, :] - co + 1e-9)
    for k in range(co.shape[0]): jac[k, s + k] = 0
    top = np.argpartition(-jac, 50, axis=1)[:, :50]
    for k in range(co.shape[0]): NB[pl[s + k]] = [pl[j] for j in top[k] if jac[k, j] > 0]
print("people", len(PEOPLE), "upvotes", len(U), flush=True)
def taste(p, d, hist):
    h = hist.get(p)
    if h is None: return None
    v = sum((ltv.get(t, 0) for t, dd in h if dd < d and dd >= str(pd.Timestamp(d) - pd.Timedelta(days=180))[:10]), np.zeros(len(TOP), np.float32))
    n = np.linalg.norm(v); return v / n if n else None
hist = U.groupby("person_id").apply(lambda g: list(zip(g.target_id, g.lday))).to_dict()
def rows_for(day, persons):
    lu = LU[LU.day == day]; ids = lu.id.tolist(); pop = lu["pop"].values; voted = U[(U.lday == day) & U.person_id.isin(persons)].groupby("person_id").target_id.agg(set)
    X, y, g = [], [], []
    for p, vs in voted.items():
        vs = vs & set(ids)
        if not vs: continue
        tv = taste(p, day, hist); fs = fol.get(p, set()); b = bt.get(p, {}); nb = NB.get(p, [])
        for k, i in enumerate(ids):
            tm = team.get(i, set()); lv = ltv.get(i)
            f_fol = float(bool(tm & fs)); f_back = float(any(b.get(t, "9999") < day for t in tm))
            f_taste = float(tv @ (lv / (np.linalg.norm(lv) or 1))) if tv is not None and lv is not None else 0.0
            f_cf = float(np.mean([any(bt.get(q, {}).get(t, "9999") < day for t in tm) for q in nb])) if nb and tm else 0.0
            X.append([pop[k], f_fol, f_back, f_taste, f_cf]); y.append(int(i in vs)); g.append((p, day))
    return np.array(X, float), np.array(y), g
days = sorted(LU.day.unique()); train_days = [d for d in days if d < CUT][-60:]; test_days = [d for d in days if CUT <= d <= "2026-11-10"]
Xtr, ytr = [], []
for d in train_days:
    ps = set(rng.choice(sorted(PEOPLE), size=min(1500, len(PEOPLE)), replace=False))
    X, y, _ = rows_for(d, ps)
    if len(X): Xtr.append(X); ytr.append(y)
Xtr, ytr = np.vstack(Xtr), np.concatenate(ytr); print("train rows", len(Xtr), "positives", int(ytr.sum()), flush=True)
BL = {"a_pop": [0], "b_+follows": [0, 1], "c_+backed": [0, 2], "d_+cf": [0, 3, 4], "e_all": [0, 1, 2, 3, 4]}
mods = {k: LogisticRegression(max_iter=500).fit(Xtr[:, c], ytr) for k, c in BL.items()}
per = {k: {} for k in BL}; n_pd = 0; n_votes = 0
for d in test_days:
    X, y, g = rows_for(d, PEOPLE)
    if not len(X): continue
    G = pd.Series([f"{a}|{b}" for a, b in g]); n_pd += G.nunique(); n_votes += int(y.sum())
    for k, c in BL.items():
        s = mods[k].decision_function(X[:, c]); hits, accs = [], []
        for _, idx in G.groupby(G).groups.items():
            idx = np.array(list(idx)); ss, yy = s[idx], y[idx]; order = (-ss).argsort().argsort()
            for j in np.flatnonzero(yy == 1):
                hits.append(float(order[j] < 3)); others = np.delete(ss, j); accs.append(float((others < ss[j]).mean()) if len(others) else np.nan)
        per[k][d] = (np.mean(hits), np.nanmean(accs))
def boot(vals):
    v = np.array(vals); bs = [v[rng.integers(0, len(v), len(v))].mean(0) for _ in range(2000)]
    return [round(float(v.mean() * 100), 1), round(float(np.percentile(bs, 2.5) * 100), 1), round(float(np.percentile(bs, 97.5) * 100), 1)]
res = {"design": __doc__.split("\n    python")[0], "people": len(PEOPLE), "test_days": len(per["a_pop"]), "test_person_days": n_pd, "test_votes": n_votes,
       "upvote_dates": "launch day of the upvoted launch (no real upvote timestamps in the store)", "coef": {k: np.round(m.coef_[0], 3).tolist() for k, m in mods.items()}}
for k in BL:
    ds = sorted(per[k]); res[k] = {"top3_hit": boot([per[k][d][0] for d in ds]), "ranking_accuracy": boot([per[k][d][1] for d in ds])}
    if k != "a_pop": res[k + " - a_pop"] = {"top3_hit": boot([per[k][d][0] - per["a_pop"][d][0] for d in ds]), "ranking_accuracy": boot([per[k][d][1] - per["a_pop"][d][1] for d in ds])}
json.dump(res, open(os.path.join(OUT, "person_choice.json"), "w"), indent=1, default=float); print(json.dumps({k: v for k, v in res.items() if k != "design"}, default=float))
