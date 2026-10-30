"""Does the linked page's content add to our model? (OpenPipe-style input.) Same test months as prior_eval
(2026-05..09), every variant trained from 2026-01, so the only difference is the page block.

Page block: out-of-fold text score (TF-IDF + ridge on page title + description + opening text, fit only on earlier
months), word count, has description, fetch failed / non-HTML, title differs from the HN title.
"""
import os

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import Ridge

import prior_eval as PE
import store as S
import top10 as T
import top100 as H

TEST = ["2026-05", "2026-06", "2026-07", "2026-08", "2026-09"]
pg = pd.read_json(os.path.join(H.CACHE, "pages.jsonl"), lines=True).drop_duplicates("post_id")
p = H.stories()
p = p[(p.month >= "2026-01") & (p.month <= TEST[-1])].reset_index(drop=True)
g = pg.set_index("post_id").reindex(p.post_id)
doc = (g.page_title.fillna("") + " " + g.desc.fillna("") + " " + g.text.fillna("")).reset_index(drop=True)
y = np.log1p(p.points.to_numpy())
rk = p.groupby("day").points.rank(ascending=False, method="first").to_numpy()
base = ["post", "early30", "who30", "early60", "who60"]
blk = {b: pd.read_parquet(os.path.join(H.CACHE, H.BLOCK_FILES[b] + ".parquet")).drop_duplicates("post_id")
       .set_index("post_id").reindex(p.post_id).reset_index(drop=True) for b in base}
extra = pd.DataFrame({"pg_words": g.words.to_numpy(), "pg_has_desc": (g.desc.fillna("") != "").astype(int).to_numpy(),
                      "pg_failed": (g.status.fillna(-1) != 200).astype(int).to_numpy(),
                      "pg_html": g.ctype.fillna("").str.contains("html").astype(int).to_numpy()})
print("pages fetched:", int(g.status.notna().sum()), "of", len(p), flush=True)
out = []
for m in TEST:
    tr, te = (p.month < m).to_numpy(), (p.month == m).to_numpy()
    oof, txt = T.text_scores(p, y, tr, te)
    tf = TfidfVectorizer(min_df=5, ngram_range=(1, 2), sublinear_tf=True, max_features=300000)
    Xt = tf.fit_transform(doc[tr])
    folds = np.arange(tr.sum()) % 5
    poof = np.zeros(tr.sum())
    for k in range(5):
        poof[folds == k] = Ridge(alpha=3.0).fit(Xt[folds != k], y[tr][folds != k]).predict(Xt[folds == k])
    ptxt = Ridge(alpha=3.0).fit(Xt, y[tr]).predict(tf.transform(doc[te]))
    res = {"day": p.day[te].to_numpy(), "y": y[te], "points": p.points[te].to_numpy(), "rk": rk[te]}
    for name, cols, page in (("ours_post", ["post"], False), ("ours_post+page", ["post"], True),
                             ("ours_60", base, False), ("ours_60+page", base, True)):
        X = pd.concat([blk[b] for b in cols], axis=1)
        Xtr, Xte = X[tr].assign(text_score=oof), X[te].assign(text_score=txt)
        if page:
            Xtr = pd.concat([Xtr.reset_index(drop=True), extra[tr].reset_index(drop=True)], axis=1).assign(page_score=poof)
            Xte = pd.concat([Xte.reset_index(drop=True), extra[te].reset_index(drop=True)], axis=1).assign(page_score=ptxt)
        c = lgb.LGBMClassifier(**{**H.GBM, "scale_pos_weight": 2}).fit(Xtr, (rk[tr] <= 100).astype(int))
        res[name] = c.predict_proba(Xte)[:, 1]
    out.append(pd.DataFrame(res))
    print("month", m, flush=True)
P = pd.concat(out, ignore_index=True)
S.write("hn_scores", pd.DataFrame(PE.evaluate(P, ["ours_post", "ours_post+page", "ours_60", "ours_60+page"], "pages")))
