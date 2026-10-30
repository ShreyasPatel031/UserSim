"""Which copy wins, learned from real A/B tests (Upworthy Research Archive: 32,487 headline experiments, CC BY 4.0,
https://osf.io/jd64p). Replicates the pairwise task in the LOLA paper (arXiv 2406.02611): within one test, two headline
arms (same image) whose click rates differ significantly (two-proportion z test, p < 0.05): which got the higher rate?
  train: exploratory packages; test: confirmatory packages (different tests)
  meaning: local sentence embeddings (bge-small), logistic regression on the embedding difference
  gemini:  Gemini 2.5 Flash asked which headline gets more clicks (zero-shot), on a sample of test pairs
Then transfer: the learned clickability score applied to Product Hunt "name - tagline" (results/upw_transfer.json is
written by transfer.py).
usage: python upworthy.py [n_gemini] -> results/upworthy.json, data/upw_model.npz"""
import json, os, random, re, sys
import numpy as np, pandas as pd
from scipy.stats import norm
from sklearn.linear_model import LogisticRegression

HERE = os.path.dirname(os.path.abspath(__file__))
EXT = os.path.expanduser("~/w/ext/upworthy")
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "ph_predict"))


def pairs(path):
    D = pd.read_csv(path, usecols=["clickability_test_id", "headline", "eyecatcher_id", "impressions", "clicks"]).dropna(subset=["headline"])
    D = D.groupby(["clickability_test_id", "headline", "eyecatcher_id"], as_index=False)[["impressions", "clicks"]].sum()
    D = D[D.impressions > 0]
    out = []
    for (t, img), g in D.groupby(["clickability_test_id", "eyecatcher_id"]):
        g = g.to_dict("records")
        for i in range(len(g)):
            for j in range(i + 1, len(g)):
                a, b = g[i], g[j]
                if a["headline"] == b["headline"]:
                    continue
                pa, pb = a["clicks"] / a["impressions"], b["clicks"] / b["impressions"]
                p = (a["clicks"] + b["clicks"]) / (a["impressions"] + b["impressions"])
                se = np.sqrt(p * (1 - p) * (1 / a["impressions"] + 1 / b["impressions"])) + 1e-12
                if 2 * (1 - norm.cdf(abs(pa - pb) / se)) < 0.05:
                    out.append((t, a["headline"], b["headline"], int(pa > pb)))
    return pd.DataFrame(out, columns=["test", "a", "b", "a_wins"])


def main(n_gem):
    from sentence_transformers import SentenceTransformer
    m = SentenceTransformer("BAAI/bge-small-en-v1.5", device="cpu")
    tr, te = pairs(f"{EXT}/exploratory.csv"), pairs(f"{EXT}/confirmatory.csv")
    print("significant pairs: train", len(tr), "test", len(te), flush=True)
    heads = sorted(set(tr.a) | set(tr.b) | set(te.a) | set(te.b))
    E = dict(zip(heads, m.encode(heads, batch_size=256, normalize_embeddings=True, show_progress_bar=False)))
    X = lambda P: np.stack([E[a] - E[b] for a, b in zip(P.a, P.b)])
    Xtr = np.vstack([X(tr), -X(tr)]); ytr = np.concatenate([tr.a_wins, 1 - tr.a_wins])    # both orders
    clf = LogisticRegression(C=1.0, max_iter=2000).fit(Xtr, ytr)
    acc = float((clf.predict(X(te)) == te.a_wins).mean())
    res = {"train_pairs": len(tr), "test_pairs": len(te), "test_tests": int(te.test.nunique()), "meaning_classifier_acc": round(100 * acc, 1)}
    np.savez(f"{HERE}/upw_model.npz", w=clf.coef_[0], b=clf.intercept_)
    if n_gem:
        import llm
        rnd = random.Random(0); S = te.sample(min(n_gem, len(te)), random_state=0); hit = []
        for r in S.itertuples():
            flip = rnd.random() < 0.5; x, y = (r.b, r.a) if flip else (r.a, r.b)
            txt = llm.call(f"Two headlines were A/B tested on the same audience. Which one got the higher click rate?\nA: {x}\nB: {y}\n"
                           'Reply with JSON only: {"winner": "A" or "B"}', max_tokens=50)
            mm = re.search(r'"winner"\s*:\s*"([AB])"', txt or "")
            if mm:
                hit.append((mm.group(1) == "A") == ((r.a_wins == 1) != flip))
        res["gemini_zero_shot_acc"] = round(100 * float(np.mean(hit)), 1); res["gemini_n"] = len(hit)
        res["gemini_usd"] = round(llm.USAGE["in"] / 1e6 * 0.30 + llm.USAGE["out"] / 1e6 * 2.50, 3)
    json.dump(res, open(f"{HERE}/upworthy.json", "w"), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 0)
