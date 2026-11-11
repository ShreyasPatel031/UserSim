"""Nonlinear version of the website bundle: the logistic head lost most of the learned scorer's gain in the Gemini space
(gemini256: logistic 0.623 vs LightGBM 0.692), so the LightGBM model is exported as flat tree arrays that evaluate in plain
numpy / JS (no LightGBM at runtime). Reuses gem768.npy and the bundle layout of gemini_bundle.py (Gemini-256 space).
Tree arrays (all trees concatenated; node ids are global): feat[int16] (-1 = leaf), thr[float32], left[int32], right[int32],
value[float32] (leaf output), roots[int32]; score = sum over trees of the reached leaf value (raw log-odds).
LightGBM's decision rule is x <= thr -> left (default_left for missing is irrelevant: features are never missing).
    python gemini_bundle_trees.py <uses2 dir> <gem dir>
"""
import json, os, re, sys, time
import numpy as np, pandas as pd
import lightgbm as lgb

D, G_ = sys.argv[1:3]; rng = np.random.default_rng(0)
P = pd.read_parquet(os.path.join(D, "export", "products.parquet")); pix = {s: i for i, s in enumerate(P.slug)}
Pe = pd.read_parquet(os.path.join(D, "export", "people.parquet"))
T = pd.read_parquet(os.path.join(D, "export", "eval_sets_lenmatched.parquet")).sample(4000, random_state=0)
uses = [sorted({pix[s] for k in ("stack", "review", "collection") for s in r[k] if s in pix}) for _, r in Pe.iterrows()]
# rebuild the exact `need` order of gemini_bundle.py
need = set(i for u in uses for i in u)
for t in T.itertuples():
    need |= {pix[t.heldout]} | {pix[s] for s in t.negatives} | {pix[s] for s in t.profile}
    if t.other_profile is not None: need |= {pix[s] for s in t.other_profile if s in pix}
need |= set(np.random.default_rng(0).choice(len(P), 3000, replace=False).tolist())
need = np.array(sorted(need)); G = np.load(os.path.join(G_, "gem768.npy")); assert len(G) == len(need)
gpos = {g: k for k, g in enumerate(need)}
E = G[:, :256].copy(); E /= np.linalg.norm(E, axis=1, keepdims=True) + 1e-9
rr = rng.choice(len(E), 2000, replace=False); hi = float(np.percentile(E[rr] @ E[rr[::-1]].T, 99))


def featv(v):
    vs = np.sort(v); return np.array([vs[-1], vs[-5:].mean(), v.mean(), (v > hi).mean(), np.log1p(len(v))], np.float32)


F, Y = [], []
for t in T.itertuples():
    cand = np.array([gpos[pix[t.heldout]]] + [gpos[pix[s]] for s in t.negatives]); prof = np.array([gpos[pix[s]] for s in t.profile])
    if not len(prof): continue
    S = E[cand] @ E[prof].T
    for k in range(len(cand)): F.append(featv(S[k]))
    Y += [1] + [0] * (len(cand) - 1)
F, Y = np.array(F), np.array(Y)
m = lgb.LGBMClassifier(n_estimators=200, learning_rate=0.05, num_leaves=15, min_child_samples=200, verbose=-1, random_state=0).fit(F, Y)
dm = m.booster_.dump_model()
feat, thr, left, right, val, roots = [], [], [], [], [], []
def walk(n):
    i = len(feat); feat.append(-1); thr.append(0.0); left.append(-1); right.append(-1); val.append(0.0)
    if "leaf_index" in n or "leaf_value" in n and "split_feature" not in n:
        val[i] = float(n["leaf_value"]); return i
    feat[i] = int(n["split_feature"]); thr[i] = float(n["threshold"])
    assert n.get("decision_type", "<=") == "<="
    l = walk(n["left_child"]); r = walk(n["right_child"]); left[i], right[i] = l, r; return i
for t in dm["tree_info"]: roots.append(walk(t["tree_structure"]))
feat, thr, left, right, val, roots = (np.array(feat, np.int16), np.array(thr, np.float32), np.array(left, np.int32), np.array(right, np.int32),
                                      np.array(val, np.float32), np.array(roots, np.int32))


def tree_score(X):
    out = np.zeros(len(X), np.float64)
    for r in roots:
        n = np.full(len(X), r)
        while True:
            f = feat[n]; leaf = f < 0
            if leaf.all(): break
            go = np.where(leaf, n, np.where(X[np.arange(len(X)), np.maximum(f, 0)] <= thr[n], left[n], right[n])); n = go
        out += val[n]
    return out


chk = rng.choice(len(F), 5000, replace=False)
diff = np.abs(tree_score(F[chk]) - m.booster_.predict(F[chk], raw_score=True)).max()
print("export check max abs diff", diff, "nodes", len(feat), flush=True)
z = dict(np.load(os.path.join(G_, "person_bundle_gemini.npz")))
assert int(z["dim"]) == 256, "bundle was built at another dim"
IE = z["item_emb"].astype(np.float32); ptr = z["person_ptr"]; idx = z["person_items"]


def person_feats(q):
    s = IE @ q; Fp = np.zeros((len(ptr) - 1, 5), np.float32); ok = np.zeros(len(ptr) - 1, bool)
    for j in range(len(ptr) - 1):
        v = s[idx[ptr[j]:ptr[j + 1]]]
        if len(v): Fp[j] = featv(v); ok[j] = True
    return Fp, ok


ref = E[[gpos[i] for i in need[:3000]]]
allsc = []
for q in ref[:1000]:
    Fp, ok = person_feats(q); s = tree_score(Fp); s[~ok] = -1e9; allsc.append(s)
thr99 = np.percentile(np.vstack(allsc), 99, axis=0).astype(np.float32)
t0 = time.time(); Fp, ok = person_feats(ref[0]); _ = tree_score(Fp); secs = time.time() - t0
z.update({"tree_feat": feat, "tree_thr": thr, "tree_left": left, "tree_right": right, "tree_value": val, "tree_roots": roots,
          "hi": np.float32(hi), "pct99_tree": thr99})
out = os.path.join(G_, "person_bundle_gemini.npz"); np.savez_compressed(out, **z)
info = {"export_max_abs_diff": float(diff), "nodes": int(len(feat)), "trees": int(len(roots)), "bytes": os.path.getsize(out), "score_seconds_numpy": round(secs, 3)}
json.dump(info, open(os.path.join(G_, "trees_info.json"), "w"), indent=1); print(info)
