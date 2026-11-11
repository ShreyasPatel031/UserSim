"""Deployable learned taste scorer for the website (bge-small only, no PH topics, no popularity, no who-text), and the
population-level check redone with it.
Training data: the leak-controlled uses harness (eval_sets_lenmatched: popularity- and length-matched negatives, 40,038 tasks).
Features per (person, product), from bge-small-en-v1.5 rich-text embeddings: top1, top5-mean, mean and share > 0.8 of the
cosine similarities to the person's profile items, log1p profile size. LightGBM, person-disjoint 2-fold for the reported AUC
(plus the shuffled-profile control: the same task scored with another person's profile -> personal = AUC - shuffled AUC);
the final model is refitted on all tasks and saved as a text file.
Population check: identical to uses_population.py, with "wants it" = product in the person's top-200 by the learned score.
    python uses_learned_small.py <uses2 dir> <outdir>
"""
import json, os, sys
import numpy as np, pandas as pd
import lightgbm as lgb
from collections import Counter
from scipy.stats import spearmanr
from sklearn.linear_model import Ridge

D, OUT = sys.argv[1:3]; os.makedirs(OUT, exist_ok=True); rng = np.random.default_rng(0)
P = pd.read_parquet(os.path.join(D, "export", "products.parquet")); pix = {s: i for i, s in enumerate(P.slug)}
E = np.load(os.path.join(D, "emb_small_rich.npy")).astype(np.float32)
T = pd.read_parquet(os.path.join(D, "export", "eval_sets_lenmatched.parquet"))
FE = ["top1", "top5", "mean", "hi", "n_prof"]


def feats(prof_idx, cand_idx):
    S = E[cand_idx] @ E[prof_idx].T; Ss = np.sort(S, 1); k = min(5, S.shape[1])
    return np.c_[Ss[:, -1], Ss[:, -k:].mean(1), S.mean(1), (S > 0.8).mean(1), np.full(len(cand_idx), np.log1p(len(prof_idx)))]


rows, ctrl = [], []
for t in T.itertuples():
    cand = np.array([pix[t.heldout]] + [pix[s] for s in t.negatives]); prof = np.array([pix[s] for s in t.profile])
    if not len(prof): continue
    f = feats(prof, cand); y = np.r_[1, np.zeros(len(cand) - 1)]
    rows.append(pd.DataFrame(np.c_[f, y, np.full(len(y), t.task)], columns=FE + ["y", "task"]).assign(person=t.person_id))
    op = np.array([pix[s] for s in t.other_profile if s in pix]) if t.other_profile is not None and len(t.other_profile) else None
    if op is not None and len(op):
        ctrl.append(pd.DataFrame(np.c_[feats(op, cand), y, np.full(len(y), t.task)], columns=FE + ["y", "task"]).assign(person=t.person_id))
X = pd.concat(rows, ignore_index=True); C = pd.concat(ctrl, ignore_index=True)
print("rows", len(X), "control rows", len(C), flush=True)
people = X.person.unique(); fold_of = {p: i % 2 for i, p in enumerate(rng.permutation(people))}
X["fold"] = X.person.map(fold_of); C["fold"] = C.person.map(fold_of)
PARAMS = dict(n_estimators=300, learning_rate=0.05, num_leaves=31, min_child_samples=200, subsample=0.8, subsample_freq=1, colsample_bytree=0.8, verbose=-1, random_state=0)
X["s"] = np.nan; C["s"] = np.nan
for k in (0, 1):
    m = lgb.LGBMClassifier(**PARAMS).fit(X.loc[X.fold != k, FE], X.y[X.fold != k])
    X.loc[X.fold == k, "s"] = m.predict_proba(X.loc[X.fold == k, FE])[:, 1]; C.loc[C.fold == k, "s"] = m.predict_proba(C.loc[C.fold == k, FE])[:, 1]


def task_auc(Z, col):
    out = {}
    for tk, g in Z.groupby("task"):
        v = g[col].to_numpy(); yy = g.y.to_numpy(); tgt = v[yy == 1][0]; neg = v[yy == 0]
        out[tk] = ((neg < tgt).sum() + 0.5 * (neg == tgt).sum()) / len(neg)
    return pd.Series(out)


def pboot(Z, a, B=2000):
    g = pd.DataFrame({"p": Z.groupby("task").person.first(), "a": a}).groupby("p").a.mean().to_numpy()
    bs = [g[rng.integers(0, len(g), len(g))].mean() for _ in range(B)]
    return [round(float(g.mean()), 4), round(float(np.percentile(bs, 2.5)), 4), round(float(np.percentile(bs, 97.5)), 4), int(len(g))]


a_l, a_c, a_s2 = task_auc(X, "s"), task_auc(C, "s"), task_auc(X, "top5")
j = a_l.index.intersection(a_c.index)
res = {"design": __doc__.split("\n    python")[0], "person_level": {
    "learned_small AUC": pboot(X, a_l), "top5 (S2-small) AUC": pboot(X, a_s2),
    "learned_small shuffled-profile AUC": pboot(C, a_c), "personal (AUC - shuffled), paired": pboot(X[X.task.isin(j)], (a_l[j] - a_c[j]))}}
print(json.dumps(res["person_level"]), flush=True)
final = lgb.LGBMClassifier(**PARAMS).fit(X[FE], X.y); final.booster_.save_model(os.path.join(OUT, "taste_small_lgb.txt"))

# ---------- population check with the learned score
Pe = pd.read_parquet(os.path.join(D, "export", "people.parquet"))
uses = [sorted({pix[s] for k in ("stack", "review", "collection") for s in r[k] if s in pix}) for _, r in Pe.iterrows()]
ups = [sorted({pix[s] for s in r if s in pix}) for r in Pe.upvote]; upc = Counter(i for x in ups for i in x)
Uc = np.array(sorted(set(i for x in uses for i in x) | {i for i, c in upc.items() if c >= 2})); upos = {g: k for k, g in enumerate(Uc)}
EU = E[Uc]; K = 200; bst = final.booster_; TL = []
for prof in uses:
    if not prof: TL.append(np.array([], int)); continue
    S = EU @ E[prof].T
    for jx, g in enumerate(prof):
        if g in upos: S[upos[g], jx] = -1.0
    Ss = np.sort(S, 1); k = min(5, S.shape[1])
    F = np.c_[Ss[:, -1], Ss[:, -k:].mean(1), S.mean(1), (S > 0.8).mean(1), np.full(len(Uc), np.log1p(len(prof) - 1))]
    sc = bst.predict(F); TL.append(np.argpartition(-sc, K)[:K])
print("learned top-200 done", flush=True)
upv = np.array([upc.get(g, 0) for g in Uc], float)
cnt = lambda idx: np.bincount(np.concatenate([TL[i] for i in idx] + [np.array([], int)]).astype(int), minlength=len(Uc)).astype(float)
def adopt(idx):
    c = np.zeros(len(Uc))
    for i in idx:
        for g in uses[i]: c[upos[g]] += 1
    return c
def metr(p, y, m=None):
    if m is not None: p, y = p[m], y[m]
    n = max(1, len(y) // 10)
    tp = set(np.argsort(-(p + rng.random(len(p)) * 1e-6))[:n]); ty = set(np.argsort(-(y + rng.random(len(y)) * 1e-6))[:n])
    return [spearmanr(p, y).correlation * 100, len(tp & ty) / n * 100]
pop = {}
for seed in range(5):
    r = np.random.default_rng(seed).permutation(len(Pe)); A, B = r[: len(r) // 2], r[len(r) // 2:]
    yA, yB = adopt(A), adopt(B); cold = yA == 0; tl = np.log1p(cnt(B))
    A1, A2 = A[: len(A) // 2], A[len(A) // 2:]; yA1, yA2 = adopt(A1), adopt(A2)
    rg = Ridge(alpha=1.0).fit(np.c_[np.log1p(2 * yA1), np.log1p(2 * cnt(A2))], np.log1p(2 * yA2))
    comb = rg.predict(np.c_[np.log1p(yA), tl])
    for nm, p in (("POP_A", np.log1p(yA)), ("TASTE learned_small", tl), ("COMB pop+learned", comb)):
        pop.setdefault(nm, []).append(metr(p, yB) + metr(p, yB, cold))
res["population"] = {nm: {"all spearman": round(float(np.mean([v[0] for v in L_])), 1), "all top-decile": round(float(np.mean([v[1] for v in L_])), 1),
                          "cold spearman": round(float(np.nanmean([v[2] for v in L_])), 1), "cold top-decile": round(float(np.mean([v[3] for v in L_])), 1),
                          "cold top-decile seed sd": round(float(np.std([v[3] for v in L_])), 1)} for nm, L_ in pop.items()}
json.dump(res, open(os.path.join(OUT, "uses_learned_small.json"), "w"), indent=1)
print(json.dumps(res["population"], indent=1))
