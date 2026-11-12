"""Browser/Vercel-light launch scorer for the website's "try a product URL" (orchestrator 23:50Z Nov 11).

Product-only model: ridge on log(1 + final votes) from inputs computable from a product page alone, with no PH history,
no followers, no LLM call and no embedder. The team / hunter / audience inputs of the full launch model are left out, which
is the same as scoring every product at the population's typical team ("population-median defaults"): the ridge
averages over them. Exported as plain JSON so a few lines of JS can score it.

Features (exact recipe in the JSON "recipe"):
  text   lowercase name + tagline + description + topics, tokens = /[a-z0-9]+/, unigrams and bigrams in the exported
         vocabulary; value = (1 + log tf) * idf, then the vector is L2-normalized (sklearn TfidfVectorizer, sublinear_tf)
  topic  one 0/1 input per exported PH topic name (exact match)
  len    log1p(len(description)), log1p(len(tagline)), number of topics
Output: score = intercept + sum(coef * x) (predicted log votes, a typical day). The band: the score's percentile among
historical launches' scores (held-out), and for that percentile decile the empirical final daily rank and votes
(10th / 50th / 90th percentile) on their own days.
Held-out accuracy (month-forward, trained on earlier months only): within-day Spearman, daily top 3/5/10, and the same for
the full honest launch model for reference.
usage: python web_launch_band.py -> results/web/launch_band.json (+ gs://.../results/web/launch_band.json)"""
import json, os, re, subprocess, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
B = "gs://usersim-bakeoff-347838016394/usersim_sim"
TOKEN = r"(?u)\b[a-z0-9]+\b"


def load():
    from pipeline import warehouse as W
    L = W.query("SELECT CAST(id AS VARCHAR) id, day, name, tagline, description, topics, votes, daily_rank FROM launches WHERE daily_rank IS NOT NULL AND votes IS NOT NULL", do_sync=False)
    L["tp"] = [json.loads(t) if t and t.startswith("[") else [] for t in L.topics]
    L["text"] = (L.name.fillna("") + ". " + L.tagline.fillna("") + ". " + L.description.fillna("") + " " + L.tp.str.join(" ")).str.lower()
    L["y"] = np.log1p(L.votes.astype(float))
    return L[L.day < pd.Timestamp.now(tz="America/Los_Angeles").strftime("%Y-%m-%d")].reset_index(drop=True)


def design(tr, te, top_topics, vocab=None, max_features=4000):
    from sklearn.feature_extraction.text import TfidfVectorizer
    from scipy import sparse
    vec = TfidfVectorizer(token_pattern=TOKEN, ngram_range=(1, 2), min_df=5, max_features=max_features, sublinear_tf=True, vocabulary=vocab)
    Xt = vec.fit_transform(tr.text); Xe = vec.transform(te.text)
    def dense(D):
        T = np.array([[float(t in s) for t in top_topics] for s in D.tp])
        Ln = np.c_[np.log1p(D.description.fillna("").str.len()), np.log1p(D.tagline.fillna("").str.len()), D.tp.str.len()]
        return np.c_[T, Ln]
    Dt, De = dense(tr), dense(te)
    mu, sd = Dt.mean(0), Dt.std(0) + 1e-9
    return vec, sparse.hstack([Xt, sparse.csr_matrix((Dt - mu) / sd)]).tocsr(), sparse.hstack([Xe, sparse.csr_matrix((De - mu) / sd)]).tocsr(), mu, sd


def topk(g, col, k):
    return len(set(g.nlargest(k, col).id) & set(g.nsmallest(k, "daily_rank").id)) / k * 100


def main():
    from sklearn.linear_model import Ridge
    from scipy.stats import spearmanr
    L = load(); L["mon"] = L.day.str[:7]
    top_topics = pd.Series([t for s in L.tp for t in s]).value_counts().head(80).index.tolist()
    # month-forward held-out scores
    L["oof"] = np.nan
    mons = sorted(L.mon.unique())
    for m in mons[2:]:
        tr, te = L[L.mon < m], L[L.mon == m]
        _, Xt, Xe, _, _ = design(tr, te, top_topics)
        L.loc[te.index, "oof"] = Ridge(alpha=3.0).fit(Xt, tr.y).predict(Xe)
    H = L.dropna(subset=["oof"])
    per = []
    for d, g in H.groupby("day"):
        if len(g) >= 10:
            per.append([spearmanr(g.oof, -g.daily_rank).correlation, topk(g, "oof", 3), topk(g, "oof", 5), topk(g, "oof", 10)])
    per = np.array(per)
    acc = {"days": int(len(per)), "months": [mons[2], mons[-1]], "within_day_spearman": round(float(np.nanmean(per[:, 0])), 3),
           "top3": round(float(per[:, 1].mean()), 1), "top5": round(float(per[:, 2].mean()), 1), "top10": round(float(per[:, 3].mean()), 1)}
    # band table: held-out score percentile decile -> final daily rank and votes
    H = H.copy(); H["pct"] = H.oof.rank(pct=True); H["dec"] = np.minimum((H.pct * 10).astype(int), 9)
    H["rank_pct_in_day"] = H.groupby("day").daily_rank.rank(pct=True)
    band = []
    for dcl, g in H.groupby("dec"):
        band.append({"decile": int(dcl), "score_min": round(float(g.oof.min()), 4), "score_max": round(float(g.oof.max()), 4),
                     "daily_rank_p10_p50_p90": [float(x) for x in np.percentile(g.daily_rank, [10, 50, 90])],
                     "votes_p10_p50_p90": [float(x) for x in np.percentile(g.votes, [10, 50, 90])],
                     "share_top3": round(float((g.daily_rank <= 3).mean()), 3), "share_top10": round(float((g.daily_rank <= 10).mean()), 3), "n": int(len(g))})
    cuts = [round(float(x), 4) for x in np.percentile(H.oof, np.arange(1, 100))]   # score -> percentile lookup
    # final model on everything
    vec, Xt, _, mu, sd = design(L, L.iloc[:1], top_topics)
    m = Ridge(alpha=3.0).fit(Xt, L.y)
    nv = len(vec.vocabulary_)
    terms = sorted(vec.vocabulary_, key=vec.vocabulary_.get)
    out = {"version": "2026-11-11", "trained_on": {"launches": int(len(L)), "days": [L.day.min(), L.day.max()]},
           "recipe": {"text": "lowercase(name + '. ' + tagline + '. ' + description + ' ' + topics.join(' '))",
                      "tokens": "regex /\\b[a-z0-9]+\\b/g on the lowercased text; features = the exported unigrams and bigrams (bigram = two consecutive tokens joined by one space)",
                      "tfidf": "x_t = (1 + ln(count_t)) * idf_t for terms in vocab with count > 0; then divide the text vector by its L2 norm",
                      "dense": "for each topic in topics_order: 1 if the product's topic list contains it exactly else 0; then log1p(len(description)), log1p(len(tagline)), number of topics; standardize each with dense_mean / dense_sd",
                      "score": "intercept + sum(text_coef[t] * x_t) + sum(dense_coef[j] * z_j)  (= predicted ln(1 + final votes))",
                      "band": "percentile = share of score_percentile_cuts below the score (0-99); decile = min(9, floor(percentile / 10)); report bands[decile]"},
           "vocab": {t: [round(float(vec.idf_[i]), 5), round(float(m.coef_[i]), 6)] for i, t in enumerate(terms)},
           "topics_order": top_topics, "dense_names": [f"topic:{t}" for t in top_topics] + ["log1p_desc_len", "log1p_tagline_len", "n_topics"],
           "dense_mean": [round(float(x), 6) for x in mu], "dense_sd": [round(float(x), 6) for x in sd],
           "dense_coef": [round(float(x), 6) for x in m.coef_[nv:]], "intercept": round(float(m.intercept_), 6),
           "score_percentile_cuts": cuts, "bands": band, "heldout_accuracy": acc,
           "caveat": "Product-only: no team, hunter, audience or launch-day line-up. A percentile band, not a forecast of one launch."}
    os.makedirs(os.path.join(HERE, "results", "web"), exist_ok=True)
    p = os.path.join(HERE, "results", "web", "launch_band.json"); json.dump(out, open(p, "w"))
    # self-check: re-score 200 launches with the exported JSON recipe and compare to sklearn
    def js_score(r):
        toks = re.findall(r"\b[a-z0-9]+\b", r.text); grams = toks + [a + " " + b for a, b in zip(toks, toks[1:])]
        cnt = pd.Series(grams).value_counts() if grams else pd.Series(dtype=float)
        x = {t: (1 + np.log(c)) * out["vocab"][t][0] for t, c in cnt.items() if t in out["vocab"]}
        nrm = np.sqrt(sum(v * v for v in x.values())) or 1.0
        s = out["intercept"] + sum(out["vocab"][t][1] * v / nrm for t, v in x.items())
        dz = [float(t in r.tp) for t in top_topics] + [np.log1p(len(r.description or "")), np.log1p(len(r.tagline or "")), len(r.tp)]
        return s + sum(c * (v - a) / b for c, v, a, b in zip(out["dense_coef"], dz, out["dense_mean"], out["dense_sd"]))
    S = L.sample(200, random_state=0)
    _, Xs, _, _, _ = design(L, S, top_topics)
    sk = m.predict(design(L, S, top_topics)[2])
    mine = np.array([js_score(r) for r in S.itertuples()])
    out_chk = float(np.abs(sk - mine).max())
    subprocess.run(["gsutil", "-q", "cp", p, f"{B}/results/web/launch_band.json"], check=True)
    print(json.dumps({"bytes": os.path.getsize(p), "vocab": nv, "heldout": acc, "recipe_max_abs_diff": round(out_chk, 6)}))


if __name__ == "__main__":
    main()
