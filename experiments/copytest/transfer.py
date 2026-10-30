"""Does a click-rate scorer learned from real headline A/B tests (Upworthy) predict Product Hunt launches?
1. Retrain on more A/B pairs: 5-fold cross-validation grouped by test over exploratory + confirmatory pairs (accuracy
   on held-out tests), then fit on all of them.
2. Score every launch's tagline (and "name: tagline") with it.
3. Against real over-performance with reach held fixed (residual from ctrl.py's fixed-inputs model): rank correlation
   within day with a 95% interval, and accuracy on same-day pairs with matched reach (as matched_pairs.py).
usage: python transfer.py -> results/upw_transfer.json"""
import glob, json, os, sys
import numpy as np, pandas as pd
from scipy.stats import spearmanr
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold
from upworthy import pairs, EXT, HERE

PH = os.path.join(os.path.dirname(HERE), "ph_predict")


def main():
    from sentence_transformers import SentenceTransformer
    m = SentenceTransformer("BAAI/bge-small-en-v1.5", device="cpu")
    P = pd.concat([pairs(f"{EXT}/exploratory.csv"), pairs(f"{EXT}/confirmatory.csv")])
    heads = sorted(set(P.a) | set(P.b))
    E = dict(zip(heads, m.encode(heads, batch_size=256, normalize_embeddings=True, show_progress_bar=False)))
    X = np.stack([E[a] - E[b] for a, b in zip(P.a, P.b)]); y = P.a_wins.values
    accs = []
    for tr, te in GroupKFold(5).split(X, y, P.test):
        c = LogisticRegression(C=1.0, max_iter=3000).fit(np.vstack([X[tr], -X[tr]]), np.concatenate([y[tr], 1 - y[tr]]))
        accs.append((c.predict(X[te]) == y[te]).mean())
    clf = LogisticRegression(C=1.0, max_iter=3000).fit(np.vstack([X, -X]), np.concatenate([y, 1 - y]))
    res = {"ab_pairs": len(P), "ab_cv_acc_held_out_tests": round(100 * float(np.mean(accs)), 1)}
    # Product Hunt launches
    rows = []
    for f in sorted(glob.glob(f"{PH}/data/days/*.json")):
        for p in json.load(open(f)):
            rows.append({"id": str(p["id"]), "tag": p.get("tagline") or "", "nt": f"{p['name']}: {p.get('tagline') or ''}"})
    L = pd.DataFrame(rows).drop_duplicates("id")
    w = clf.coef_[0]
    L["upw_tag"] = m.encode(L.tag.tolist(), batch_size=256, normalize_embeddings=True, show_progress_bar=False) @ w
    L["upw_nt"] = m.encode(L.nt.tolist(), batch_size=256, normalize_embeddings=True, show_progress_bar=False) @ w
    json.dump({r.id: {"upw_tag": float(r.upw_tag), "upw_nt": float(r.upw_nt)} for r in L.itertuples()}, open(f"{PH}/data/upw_features.json", "w"))
    C = pd.read_parquet(f"{PH}/results/ctrl_preds.parquet").merge(L, on="id"); C["resid"] = C.logv - C.fixed
    rng = np.random.default_rng(0)
    for col in ("upw_tag", "upw_nt"):
        per = np.array([spearmanr(g[col], g.resid).correlation for _, g in C.groupby("day") if len(g) >= 8])
        bs = [rng.choice(per, len(per)).mean() for _ in range(2000)]
        pr, hits = [], []
        for _, g in C.groupby("day"):
            g = g.to_dict("records")
            for i, a in enumerate(g):
                for b in g[i + 1:]:
                    if abs(a["fixed"] - b["fixed"]) < 0.15 and a["logv"] != b["logv"] and a[col] != b[col]:
                        hits.append((a[col] > b[col]) == (a["logv"] > b["logv"]))
        res[col] = {"corr_with_over_performance": round(float(per.mean()), 3), "ci95": [round(float(np.percentile(bs, 2.5)), 3), round(float(np.percentile(bs, 97.5)), 3)],
                    "matched_pairs_acc": round(100 * float(np.mean(hits)), 1), "matched_pairs": len(hits)}
    json.dump(res, open(f"{PH}/results/upw_transfer.json", "w"), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
