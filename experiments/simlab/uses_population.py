"""User simulation at population level on the "uses or wants" channel (orchestrator 21:50Z Nov 11, item B).
Question: summed over people, does the per-person taste scorer rank PRODUCTS by real adoption (stack / review / collection
adds)? Stack and collection lists are undated snapshots, so a forward-in-time split is not possible for them; the test is
person-disjoint instead: people (the 5,096 uses-harness people) are split at random into halves A and B (5 seeds); the target
is adoption_B(P) = number of B people with P in their stack/review/collection lists. Nothing about B's uses enters any
predictor except through the leave-one-out taste profiles (P itself is removed from every B person's profile, as in the
person-level harness).
Universe: products with text and (>= 1 use among A people or >= 2 upvotes among all people) - defined without B's uses.
Predictors
  POP_A       adoption among A people (popularity of uses in the other half)                  [popularity baseline]
  TASTE       sum over B people of 1[P in the person's top-200 products by taste], taste = mean of the top-5 bge-base cosine
              similarities between P and the person's other uses items (S2 scorer of uses_v2)   [product-only: text + profiles]
  TASTE_UP    the same with the person's upvoted products as profile (cross-channel)
  UPV         upvotes of P among all people (PH context)
  COMB        ridge on log1p(POP_A, TASTE, TASTE_UP, UPV) (target log1p adoption,
              features from B), then applied - never sees adoption_B. (Fitted inside A: A1 adoption + A2 taste -> A2
              adoption, counts doubled to B's scale.)
Metrics over the universe: Spearman with adoption_B; top-decile precision (share of the predicted top 10% that is in the
actual top 10% of adoption_B, ties broken at random); also restricted to products with POP_A = 0 (cold for uses: popularity
can only tie). CIs: product bootstrap on seed 0 (1000 draws); seed spread reported.
    python uses_population.py <uses2 dir: export/products.parquet export/people.parquet emb_base_rich.npy> <out.json>
"""
import json, os, sys
import numpy as np, pandas as pd
from collections import Counter
from scipy.stats import spearmanr
from sklearn.linear_model import Ridge

D, OUT = sys.argv[1:3]; rng = np.random.default_rng(0); K = 200
P = pd.read_parquet(os.path.join(D, "export", "products.parquet")); Pe = pd.read_parquet(os.path.join(D, "export", "people.parquet"))
E = np.load(os.path.join(D, "emb_base_rich.npy")).astype(np.float32); pix = {s: i for i, s in enumerate(P.slug)}
uses = [sorted({pix[s] for k in ("stack", "review", "collection") for s in r[k] if s in pix}) for _, r in Pe.iterrows()]
ups = [sorted({pix[s] for s in r if s in pix}) for r in Pe.upvote]
upc = Counter(i for x in ups for i in x)
ever = set(i for x in uses for i in x) | {i for i, c in upc.items() if c >= 2}
Ucand = np.array(sorted(ever)); upos = {g: j for j, g in enumerate(Ucand)}; EU = E[Ucand]
print("people", len(Pe), "candidate products", len(Ucand), flush=True)


def topk_sets(profiles):
    out = []
    for prof in profiles:
        if not prof: out.append(np.array([], int)); continue
        S = EU @ E[prof].T                                   # |U| x n
        for j, g in enumerate(prof):                         # leave-one-out: the product itself is not in its own profile
            if g in upos: S[upos[g], j] = -1.0
        k = min(5, S.shape[1]); sc = np.partition(S, -k, axis=1)[:, -k:].mean(1) if S.shape[1] > k else S.mean(1)
        out.append(np.argpartition(-sc, K)[:K])
    return out


cache = os.path.join(D, "pop_topk.npz")
if os.path.exists(cache):
    z = np.load(cache, allow_pickle=True); TU, TV = list(z["TU"]), list(z["TV"])
else:
    TU = topk_sets(uses); print("taste uses done", flush=True); TV = topk_sets(ups); print("taste upvotes done", flush=True)
    np.savez(cache, TU=np.array(TU, dtype=object), TV=np.array(TV, dtype=object))
upv = np.array([upc.get(g, 0) for g in Ucand], float)


def counts(idx, sets):
    c = np.zeros(len(Ucand))
    for i in idx:
        for j in sets[i]: c[j] += 1
    return c


def adopt(idx):
    c = np.zeros(len(Ucand))
    for i in idx:
        for g in uses[i]:
            if g in upos: c[upos[g]] += 1
    return c


def metrics(pred, y, mask=None):
    if mask is not None: pred, y = pred[mask], y[mask]
    sp = spearmanr(pred, y).correlation
    n = max(1, len(y) // 10); jit = rng.random(len(y)) * 1e-6
    top_pred = set(np.argsort(-(pred + jit))[:n]); top_y = set(np.argsort(-(y + rng.random(len(y)) * 1e-6))[:n])
    return sp * 100, len(top_pred & top_y) / n * 100


res = {"design": __doc__.split("\n    python")[0], "people": len(Pe), "universe": int(len(Ucand)), "seeds": {}}
SEEDS = 5; boots = None
for seed in range(SEEDS):
    r = np.random.default_rng(seed).permutation(len(Pe)); A, B = r[: len(r) // 2], r[len(r) // 2:]
    yA, yB = adopt(A), adopt(B)
    feat = lambda half, other_y: np.c_[np.log1p(other_y), np.log1p(counts(half, TU)), np.log1p(counts(half, TV)), np.log1p(upv)]
    A1, A2 = A[: len(A) // 2], A[len(A) // 2:]              # the combiner is fitted inside A only (A1 -> A2), counts x2 to B's scale
    FB = feat(B, yA); yA1, yA2 = adopt(A1), adopt(A2)
    FA = np.c_[np.log1p(2 * yA1), np.log1p(2 * counts(A2, TU)), np.log1p(2 * counts(A2, TV)), np.log1p(upv)]
    pred = {"POP_A": FB[:, 0], "TASTE (product-only)": FB[:, 1], "TASTE_UP": FB[:, 2], "UPV (PH context)": FB[:, 3]}
    for nm, cols in (("COMB pop+taste", [0, 1]), ("COMB taste+upv (no uses popularity)", [1, 2, 3]), ("COMB all", [0, 1, 2, 3])):
        rg = Ridge(alpha=1.0).fit(FA[:, cols], np.log1p(2 * yA2)); pred[nm] = rg.predict(FB[:, cols])
    cold = yA == 0
    out = {}
    for nm, p in pred.items():
        out[nm] = {"all": metrics(p, yB), "cold (POP_A=0)": metrics(p, yB, cold)}
    out["share_universe_cold"] = float(cold.mean()); out["share_cold_with_B_adoption"] = float((yB[cold] > 0).mean())
    res["seeds"][seed] = out
    if seed == 0:
        bt = {nm: {"all": [], "cold": []} for nm in pred}; idx_all = np.arange(len(yB))
        for _ in range(300):
            s = rng.integers(0, len(yB), len(yB))
            for nm, p in pred.items():
                bt[nm]["all"].append(metrics(p[s], yB[s])); m = cold[s]; bt[nm]["cold"].append(metrics(p[s][m], yB[s][m]))
            for base in ("POP_A",):
                pass
        boots = {nm: {k: np.array(v) for k, v in d.items()} for nm, d in bt.items()}
        # paired differences vs POP_A on the same bootstrap draws
        res["seed0_ci"] = {nm: {k: [[round(float(np.percentile(v[:, j], q)), 1) for q in (2.5, 97.5)] for j in range(2)] for k, v in d.items()} for nm, d in boots.items()}
        res["seed0_diff_vs_POP_A_ci"] = {nm: {k: [[round(float(np.percentile(v[:, j] - boots["POP_A"][k][:, j], q)), 1) for q in (2.5, 97.5)] for j in range(2)] for k, v in d.items()} for nm, d in boots.items() if nm != "POP_A"}
    print(seed, json.dumps({k: v for k, v in out.items() if isinstance(v, dict)}), flush=True)
summ = {}
for nm in res["seeds"][0]:
    if not isinstance(res["seeds"][0][nm], dict): continue
    for k in ("all", "cold (POP_A=0)"):
        v = np.array([res["seeds"][s][nm][k] for s in range(SEEDS)])
        summ.setdefault(nm, {})[k] = {"spearman_mean": round(float(v[:, 0].mean()), 1), "spearman_seed_sd": round(float(v[:, 0].std()), 1),
                                       "top_decile_precision_mean": round(float(v[:, 1].mean()), 1), "top_decile_seed_sd": round(float(v[:, 1].std()), 1)}
res["summary"] = summ
json.dump(res, open(OUT, "w"), indent=1)
print(json.dumps(summ, indent=1)); print(json.dumps(res["seed0_ci"])); print(json.dumps(res["seed0_diff_vs_POP_A_ci"]))
