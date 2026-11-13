"""Within-day choice model for who-backs-it (orchestrator 18:28Z Nov 13). Same 15 test days / features as who_backs2.py (day_cols, exec'd).
P(person p backs launch L on day d) = min(1, k_p x s_pL), where
  k_p  = expected number of votes p casts that day, from HISTORY ONLY: p's mean daily vote count over the launch days in the 60 days
         before d (votes dated by launch day). ORACLE arms use the realised count (labelled oracle).
  s_pL = share of p's day going to L: softmax over the day's line-up of w . x_pL (conditional logit fit by L-BFGS on the 30 prior
         launch days, people who voted that day, multi-choice likelihood), or LambdaRank (LightGBM, one group per person-day) scores
         put through a softmax.
Feature sets: taste | taste + cf | taste + cf + team (back, hun, fol(undated)) | + clean prior (within-day z of the 00:05 clean score:
honest_preds_v2 on training days, clean_v3_nosite on test days; both are the clean family, known at 00:05).
Expected backers E(L) = sum_p P. Metrics: voter recall at N / 2N (N = round E), calibration (median E / displayed, Spearman), launch
top 3/5/10 by E vs the tie-averaged placebo (hunter + all named makers held, 200 tie draws) and vs clean, paired day bootstrap;
person-level top-3 hit (share of a voter's real picks that are in our top 3 for them). Counts only.
    python who_choice.py <store dir> <clean_live_rows_nosite.parquet> <launches dir> <salt dir> <honest_preds_v2.parquet> <out dir>
"""
import os, sys, json, time
HERE = os.path.dirname(os.path.abspath(__file__)); HP = sys.argv[5]; sys.argv = sys.argv[:5] + [sys.argv[6]]
src = open(os.path.join(HERE, "who_backs2.py")).read(); exec(src[src.index("import os, sys, json, time"):src.index("COLS = [")])
from scipy.optimize import minimize
from scipy.stats import spearmanr
import lightgbm as lgb
COLS = ["n30", "n90", "last", "taste", "fol", "hun", "back", "wk", "cf"]; ci = {c: k for k, c in enumerate(COLS)}
HN = pd.read_parquet(HP)[["id", "honest"]]; HN["id"] = HN.id.astype(str); prior_s = dict(zip(HN.id, HN.honest)); prior_s.update(dict(zip(C.id, C.clean_v3_nosite)))
lday_all = sorted(L.day.unique()); dcount = U.groupby(["person_id", "lday"]).size()
def kexp(people, d):
    w = [x for x in lday_all if x < d][-60:]; win = set(w)
    s = dcount[dcount.index.get_level_values(1).isin(win)].groupby(level=0).sum()
    return np.array([s.get(p, 0) / max(len(w), 1) for p in people])
def cube(d, lineup=None):
    """persons x launches x features for day d (+ clean prior column), restricted to the line-up."""
    r = day_cols(d)
    if r is None: return None
    act, out = r; ids = [i for i, _ in out if (lineup is None or i in lineup)]
    if not ids: return None
    X = np.stack([X for i, X in out if i in set(ids)], axis=1).astype(np.float32)   # P x L x 9
    pr = np.array([prior_s.get(i, np.nan) for i in ids], float); pr = np.where(np.isnan(pr), np.nanmean(pr) if np.isfinite(pr).any() else 0, pr)
    pz = (pr - pr.mean()) / (pr.std() or 1); X = np.concatenate([X, np.broadcast_to(pz[None, :, None], (X.shape[0], X.shape[1], 1))], axis=2)
    vot = U[U.lday == d].groupby("person_id").target_id.agg(set).to_dict()
    Y = np.array([[i in vot.get(p, ()) for i in ids] for p in act.index], np.float32)
    return act, ids, X, Y
FX = {"taste": ["taste"], "taste+cf": ["taste", "cf"], "taste+cf+team": ["taste", "cf", "back", "hun", "fol"], "taste+cf+team+prior": ["taste", "cf", "back", "hun", "fol", "prior"]}
FI = {**ci, "prior": 9}
t0 = time.time(); prior_days = [x for x in lday_all if x < DAYS[0]][-30:]; TR = {}
for d in prior_days + DAYS:
    c = cube(d)
    if c is None: continue
    act, ids, X, Y = c; keep = Y.sum(1) > 0; TR[d] = (X[keep], Y[keep])
print("train cubes", len(TR), round(time.time() - t0), flush=True)
TE = {d: cube(d, set(C[C.day == d].id)) for d in DAYS}; print("test cubes", round(time.time() - t0), flush=True)
def fit_logit(days, cols):
    Xs = [TR[d][0][:, :, [FI[c] for c in cols]] for d in days]; Ys = [TR[d][1] for d in days]
    def f(w):
        nll, g = 0.0, np.zeros(len(w))
        for X, Y in zip(Xs, Ys):
            z = X @ w; z -= z.max(1, keepdims=True); e = np.exp(z); s = e / e.sum(1, keepdims=True); k = Y.sum(1, keepdims=True)
            nll -= float((Y * np.log(s + 1e-12)).sum()); g -= ((Y - k * s)[:, :, None] * X).sum((0, 1))
        return nll + 0.01 * w @ w, g + 0.02 * w
    return minimize(f, np.zeros(len(cols)), jac=True, method="L-BFGS-B").x
def fit_rank(days, cols):
    Xs, ys, gs = [], [], []
    for d in days:
        X, Y = TR[d]; X = X[:, :, [FI[c] for c in cols]]; Xs.append(X.reshape(-1, X.shape[2])); ys.append(Y.reshape(-1)); gs += [X.shape[1]] * X.shape[0]
    m = lgb.LGBMRanker(objective="lambdarank", n_estimators=200, learning_rate=0.05, num_leaves=15, min_child_samples=50, verbose=-1)
    m.fit(np.vstack(Xs), np.concatenate(ys), group=gs); return m
D = C[C.day.isin(DAYS)].copy(); votes = dict(zip(L.id, pd.to_numeric(L.votes, errors="coerce")))
import glob, hashlib
SALT = open(os.path.join(SALTD, "salt")).read().strip(); pidf = lambda h: "p_" + hashlib.sha256((SALT + "producthunt:" + str(h).lower()).encode()).hexdigest()[:16]
def mk(m):
    try: return [x for x in json.loads(m) if x and not str(x).startswith("[")] if isinstance(m, str) and m.startswith("[") else []
    except Exception: return []
nteam = {i: sum(pidf(h) in COV for h in dict.fromkeys(([p] if isinstance(p, str) and p and not p.startswith("[") else []) + mk(m))) for i, p, m in zip(L.id, L.poster, L.makers)}
D["nt"] = D.id.map(nteam).fillna(0)
def dm(g, col):
    o = g.sort_values(col, ascending=False).id.tolist(); t = g.sort_values("rank").id.tolist(); return [len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)]
PL = np.zeros((len(DAYS), 3))
for r_ in range(200):
    D["s"] = D.nt + rng.random(len(D)) * 1e-3; PL += np.array([dm(D[D.day == d], "s") for d in DAYS]) / 200
CL = np.array([dm(D[D.day == d], "clean_v3_nosite") for d in DAYS])
def pdiff(a, b):
    df = a - b; bs = np.array([df[rng.integers(0, len(df), len(df))].mean(0) for _ in range(4000)])
    return [[round(float(df[:, j].mean()), 1), round(float(np.percentile(bs[:, j], 2.5)), 1), round(float(np.percentile(bs[:, j], 97.5)), 1)] for j in range(3)]
def lb(v):
    v = np.asarray(v, float); v = v[~np.isnan(v)]; bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(2000)]
    return [round(float(v.mean()) * 100, 1), round(float(np.percentile(bs, 2.5)) * 100, 1), round(float(np.percentile(bs, 97.5)) * 100, 1), len(v)]
res = {"design": __doc__.split("\n    python")[0], "days": DAYS, "train_days": len(prior_days), "placebo (tie-averaged) top3/5/10": PL.mean(0).round(1).tolist(),
       "clean_nosite top3/5/10": CL.mean(0).round(1).tolist()}
def evaluate(name, scorer):
    E, rec, ph = {}, [], []
    for d in DAYS:
        if TE[d] is None: continue
        act, ids, X, Y = TE[d]; S = scorer(d, X)   # P x L shares
        kh = kexp(act.index, d); ko = Y.sum(1)
        for kind, k in (("hist", kh), ("oracle", ko)):
            P = np.minimum(1.0, k[:, None] * S)
            for j, i in enumerate(ids):
                E.setdefault(kind, {})[i] = float(P[:, j].sum())
                if kind == "hist":
                    v = Y[:, j] > 0
                    if v.sum():
                        o = np.argsort(-P[:, j]); N = max(1, int(round(P[:, j].sum())))
                        rec.append((v[o[:N]].sum() / v.sum(), v[o[:2 * N]].sum() / v.sum()))
        vm = Y.sum(1) > 0
        if vm.any():
            top3 = np.argsort(-S[vm], axis=1)[:, :3]; Yv = Y[vm]
            ph += [Yv[r, top3[r]].sum() / Yv[r].sum() for r in range(len(Yv))]
    out = {}
    rec = np.array(rec)
    for kind in ("hist", "oracle"):
        D["E"] = D.id.map(E[kind]).fillna(0); A = np.array([dm(D[D.day == d], "E") for d in DAYS])
        cal = D[(D.E > 0)].assign(v=D.id.map(votes).astype(float)); cal = cal[cal.v > 0]
        out[kind if kind == "hist" else "ORACLE (realised vote count)"] = {"top3/5/10": A.mean(0).round(1).tolist(), "vs placebo": pdiff(A, PL), "vs clean": pdiff(A, CL),
            "calibration median E/displayed, Spearman": [round(float((cal.E / cal.v).median()), 3), round(float(spearmanr(cal.E, cal.v).correlation), 3)]}
    out["recall@N (hist k)"] = lb(rec[:, 0]); out["recall@2N (hist k)"] = lb(rec[:, 1]); out["person-level top-3 hit"] = lb(ph)
    res[name] = out; print(name, json.dumps(out), round(time.time() - t0), flush=True)
    json.dump(res, open(os.path.join(OUT, "who_choice.json"), "w"), indent=1, default=float)
def sm(z): z = z - z.max(1, keepdims=True); e = np.exp(z); return e / e.sum(1, keepdims=True)
for nm, cols in FX.items():
    W = {d: fit_logit([x for x in sorted(TR) if x < d][-30:], cols) for d in DAYS}
    evaluate(f"softmax: {nm}", lambda d, X, cols=cols, W=W: sm(X[:, :, [FI[c] for c in cols]] @ W[d]))
for nm in ("taste+cf+team", "taste+cf+team+prior"):
    cols = FX[nm]; M = {d: fit_rank([x for x in sorted(TR) if x < d][-30:], cols) for d in DAYS}
    evaluate(f"lambdarank: {nm}", lambda d, X, cols=cols, M=M: sm(M[d].predict(X[:, :, [FI[c] for c in cols]].reshape(-1, len(cols))).reshape(X.shape[0], X.shape[1])))
