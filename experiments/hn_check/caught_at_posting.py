"""Caught at posting on Hacker News: each post scored with only what is known at its posting moment.
Caught for list day D = how many of the real top 30 of D are in our top 30 (posts ranked by at-posting score).
Train posts Jul 1 - Aug 31, test Sep 1 - Oct 14. Features (all from before the post): hour, weekday, title text
(TF-IDF -> SVD), Show/Ask HN, url/domain present, submitter's and domain's earlier posts and earlier top-30 count
(only lists of days before the post's day). Points/comments of the post itself are never used.
usage: python caught_at_posting.py <dir with bq_stories.parquet + frontday.jsonl>"""
import sys, os, re
import numpy as np, pandas as pd, lightgbm as lgb
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.decomposition import TruncatedSVD
from urllib.parse import urlparse

D = sys.argv[1]
s = pd.read_parquet(os.path.join(D, "bq_stories.parquet"))
s = s[(s.day >= "2026-05-01") & (s.day <= "2026-10-16")].copy(); s["title"] = s.title.fillna("").astype(str); s["author"] = s.author.fillna("").astype(str)
f = pd.read_json(os.path.join(D, "frontday.jsonl"), lines=True, dtype={"day": str})
top30 = f[f["rank"] <= 30]
first_list_day = top30.groupby("post_id").day.min()
s["y"] = s.post_id.isin(top30.post_id).astype(int)
s["list_day"] = s.post_id.map(first_list_day)
s["dom"] = s.url.fillna("").map(lambda u: (urlparse(u).netloc or "").lower().removeprefix("www."))
s["t"] = pd.to_datetime(s.created_at_i, unit="s", utc=True)
s["hour"] = s.t.dt.hour; s["wd"] = s.t.dt.weekday
s["show"] = s.title.str.startswith("Show HN").astype(int); s["ask"] = s.title.str.startswith("Ask HN").astype(int)
s["has_url"] = (s.dom != "").astype(int); s["tlen"] = s.title.str.len()
s = s.sort_values("created_at_i").reset_index(drop=True)

# prior counts per submitter / domain, using only earlier posts and only list results known before the post's day
def priors(key):
    n_prev = s.groupby(key).cumcount()
    # earlier top-30 hits whose list day is before this post's day
    hits = s[s.y == 1][[key, "list_day"]].dropna().sort_values("list_day")
    out = np.zeros(len(s))
    by = {k: g.list_day.values for k, g in hits.groupby(key)}
    for i, (k, d) in enumerate(zip(s[key].values, s.day.values)):
        v = by.get(k)
        if v is not None and k != "":
            out[i] = np.searchsorted(v, d)   # list days strictly before d
    return n_prev.values, out
s["sub_n"], s["sub_hits"] = priors("author")
s["dom_n"], s["dom_hits"] = priors("dom")
s.loc[s.dom == "", ["dom_n", "dom_hits"]] = 0
for k in ("sub", "dom"):
    s[f"{k}_rate"] = (s[f"{k}_hits"] + 0.05) / (s[f"{k}_n"] + 1)

tr = (s.day >= "2026-07-01") & (s.day <= "2026-08-31"); te = (s.day >= "2026-09-01") & (s.day <= "2026-10-14")
tf = TfidfVectorizer(min_df=5, ngram_range=(1, 2), max_features=60000, sublinear_tf=True).fit(s.title[tr])
svd = TruncatedSVD(64, random_state=0).fit(tf.transform(s.title[tr]))
E = svd.transform(tf.transform(s.title));
for j in range(E.shape[1]):
    s[f"e{j}"] = E[:, j]
F = ["hour", "wd", "show", "ask", "has_url", "tlen", "sub_n", "sub_hits", "sub_rate", "dom_n", "dom_hits", "dom_rate"] + [f"e{j}" for j in range(64)]
m = lgb.LGBMClassifier(n_estimators=800, learning_rate=0.03, num_leaves=63, min_child_samples=40, subsample=0.8, subsample_freq=1,
                       colsample_bytree=0.7, verbose=-1, random_state=0).fit(s.loc[tr, F], s.loc[tr, "y"])
s["p"] = 0.0; s.loc[te, "p"] = m.predict_proba(s.loc[te, F])[:, 1]
from sklearn.metrics import roc_auc_score
print("test posts", int(te.sum()), "AUC at posting", round(roc_auc_score(s.loc[te, "y"], s.loc[te, "p"]), 3))

rows = []
T = s[te | ((s.day >= "2026-08-29") & (s.day < "2026-09-01"))]   # earlier posts can be re-ups on early test days
for d in sorted(top30[(top30.day >= "2026-09-01") & (top30.day <= "2026-10-14")].day.unique()):
    real = set(top30[top30.day == d].post_id)
    same = T[T.day == d]; window = T[(T.day <= d) & (T.day >= (pd.Timestamp(d) - pd.Timedelta(days=2)).strftime("%Y-%m-%d"))]
    ours_same = set(same.nlargest(30, "p").post_id)
    ours_win = set(window[~window.post_id.isin(set(top30[top30.day < d].post_id))].nlargest(30, "p").post_id)
    rows.append({"day": d, "caught_same_day": len(real & ours_same) / 30, "caught_3day_window": len(real & ours_win) / 30,
                 "ceiling_same_day": len(real & set(same.post_id)) / 30})
R = pd.DataFrame(rows)
rng = np.random.default_rng(0)
for c in ("caught_same_day", "caught_3day_window", "ceiling_same_day"):
    bs = [rng.choice(R[c].values, len(R)).mean() for _ in range(4000)]
    print(f"{c:22s} {100*R[c].mean():5.1f}%  95% [{100*np.percentile(bs,2.5):.1f}, {100*np.percentile(bs,97.5):.1f}]  days {len(R)}")
imp = pd.Series(m.feature_importances_, F).sort_values(ascending=False).head(10); print(imp.to_string())
R.to_csv(os.path.join(D, "caught_at_posting_days.csv"), index=False)
