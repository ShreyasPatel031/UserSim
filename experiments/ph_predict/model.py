"""Rolling-origin backtest: for each test month M, train on every launch before M, predict M.
Prediction = expected log votes (comparable across days, so it can rank day, week and month lists).
Scores recall@k against PH's own dailyRank / weeklyRank / monthlyRank and per-topic lists."""
import os
import json, sys, warnings
import numpy as np, pandas as pd, lightgbm as lgb
from scipy.stats import spearmanr
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import Ridge
from sklearn.neighbors import NearestNeighbors
import features as F

warnings.filterwarnings("ignore")
N_JOBS = int(os.environ.get("LGB_THREADS", "4"))  # 1 inside parallel folds: oversubscribed threads are very slow
SOURCES = ["ph", "hist", "txt", "web", "dom", "x", "hn", "comp", "topic", "llm", "cm"]
KS = (3, 5, 10)


def text_of(df):
    return (df.name + ". " + df.tagline + ". " + df.description + " " + df.topics.str.join(" ")).fillna("")


def add_fold_feats(tr, te):
    """Features that must be learned only from the training months (no peeking at test labels)."""
    tr, te = tr.copy(), te.copy()
    # txt_: ridge on TF-IDF of the pitch, out-of-fold on train
    vec = TfidfVectorizer(min_df=2, max_features=30000, ngram_range=(1, 2), sublinear_tf=True)
    Xtr, Xte = vec.fit_transform(text_of(tr)), vec.transform(text_of(te))
    y = tr.logv - tr.groupby("day").logv.transform("mean")
    oof = np.zeros(len(tr)); folds = np.array(pd.factorize(tr.day)[0]) % 4  # whole days per fold
    for k in range(4):
        m = Ridge(alpha=3.0).fit(Xtr[folds != k], y[folds != k]); oof[folds == k] = m.predict(Xtr[folds == k])
    tr["txt_ridge"], te["txt_ridge"] = oof, Ridge(alpha=3.0).fit(Xtr, y).predict(Xte)
    # web text ridge (homepage words)
    has = tr.web_text.fillna("").str.len() > 200
    if has.sum() > 100:
        wv = TfidfVectorizer(min_df=3, max_features=30000, sublinear_tf=True)
        Wtr, Wte = wv.fit_transform(tr.web_text.fillna("")), wv.transform(te.web_text.fillna(""))
        oof = np.zeros(len(tr))
        for k in range(4):
            m = Ridge(alpha=5.0).fit(Wtr[folds != k], y[folds != k]); oof[folds == k] = m.predict(Wtr[folds == k])
        tr["web_text_ridge"], te["web_text_ridge"] = oof, Ridge(alpha=5.0).fit(Wtr, y).predict(Wte)
        tr.loc[~has.values, "web_text_ridge"] = np.nan
        te.loc[(te.web_text.fillna("").str.len() <= 200).values, "web_text_ridge"] = np.nan
    # topic_: how each topic did in training months (relative to its day)
    ex = tr[["topics"]].assign(rel=y.values).explode("topics")
    tstat = ex.groupby("topics").rel.agg(["mean", "count"])
    tmean = (tstat["mean"] * tstat["count"] / (tstat["count"] + 20)).to_dict()
    for d in (tr, te):
        d["topic_prior_max"] = d.topics.apply(lambda ts: max([tmean.get(t, 0) for t in ts] or [0]))
        d["topic_prior_mean"] = d.topics.apply(lambda ts: np.mean([tmean.get(t, 0) for t in ts] or [0]))
        d["topic_is_ai"] = d.topics.apply(lambda ts: float("Artificial Intelligence" in ts))
        d["topic_is_dev"] = d.topics.apply(lambda ts: float("Developer Tools" in ts))
    # comp_: nearest earlier PH launches by pitch similarity -> how did they do (relative to their day)
    allx = vec.transform(text_of(pd.concat([tr, te])))
    alld = pd.concat([tr.day, te.day]).values
    rel_tr = y.values
    nn = NearestNeighbors(n_neighbors=min(30, Xtr.shape[0]), metric="cosine").fit(Xtr)
    dist, idx = nn.kneighbors(allx)
    trd = tr.day.values
    out = []
    for i in range(allx.shape[0]):
        ok = [j for j in idx[i] if trd[j] < alld[i]][:10]  # strictly earlier launches only
        out.append((np.mean(rel_tr[ok]) if ok else 0.0, np.max(rel_tr[ok]) if ok else 0.0,
                    1 - dist[i][0] if len(dist[i]) else 0))
    out = np.array(out)
    for d, sl in ((tr, slice(0, len(tr))), (te, slice(len(tr), None))):
        d["comp_nn_mean"], d["comp_nn_max"], d["comp_nn_sim"] = out[sl, 0], out[sl, 1], out[sl, 2]
    return tr, te


# Follower counts come from today, after the launch; a top launch earns its makers followers. Excluded from the
# headline model, kept in the "leaky" variant to show how much they would inflate the score.
LEAKY = {"ph_maker_max_followers", "ph_maker_sum_followers"}
INCLUDE_LEAKY = False


def cols(df, sources):
    return [c for c in df.columns if c.split("_")[0] in sources and c not in ("web_text",)
            and df[c].dtype != object and (INCLUDE_LEAKY or c not in LEAKY)]


def fit_predict(tr, te, sources, seed=0):
    c = cols(tr, sources)
    if not c:
        return np.random.default_rng(seed).random(len(te)), None, c
    m = lgb.LGBMRegressor(n_estimators=400, learning_rate=0.03, num_leaves=15, min_child_samples=20,
                          subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0,
                          random_state=seed, verbose=-1, n_jobs=N_JOBS)
    m.fit(tr[c], tr.logv)
    return m.predict(te[c]), m, c


def fit_rank(tr, te, sources, seed=0):
    """LambdaRank within each day (the daily list is a contest among that day's launches)."""
    c = cols(tr, sources)
    tr = tr.sort_values("day")
    rel = np.clip(11 - tr.dailyRank.values, 0, 10)
    m = lgb.LGBMRanker(n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=20, subsample=0.8,
                       subsample_freq=1, colsample_bytree=0.8, random_state=seed, verbose=-1, n_jobs=N_JOBS)
    m.fit(tr[c], rel, group=tr.groupby("day", sort=False).size().loc[tr.day.unique()].values)
    return m.predict(te[c])


PERIOD_FEATS = ["ph_hunter_followers", "hist_hunter_rel", "x_hunter_followers", "llm_brand", "ph_n_makers", "txt_ridge"]


def fit_list_clf(tr, te, period, rank_col, top):
    """Classifier for 'finished in the period's top N' (week: top 10, month: top 20), with each launch's standing
    on key signals within its week/month. Assumes the period's launches are known (their votes are not used)."""
    c = cols(tr, SOURCES)
    tr, te = tr.copy(), te.copy()
    for d in (tr, te):
        for f in PERIOD_FEATS:
            if f in d:
                d[f"per_{f}"] = d.groupby(period)[f].rank(pct=True)
    cw = c + [f"per_{f}" for f in PERIOD_FEATS if f in tr]
    clf = lgb.LGBMClassifier(n_estimators=400, learning_rate=0.03, num_leaves=15, min_child_samples=20, subsample=0.8,
                             subsample_freq=1, colsample_bytree=0.8, random_state=0, verbose=-1, n_jobs=N_JOBS)
    return clf.fit(tr[cw], (tr[rank_col] <= top).astype(int)).predict_proba(te[cw])[:, 1]


def recall_at(df, group, rank_col, k, score="pred", per_list=False):
    """Mean over groups of |predicted top-k ∩ actual top-k| / k. Actual top-k = PH's rank field (or votes)."""
    vals = []
    rng = np.random.default_rng(1)
    df = df.assign(_s=df[score].fillna(-1e3).values + rng.random(len(df)) * 1e-7)  # random tie-break: rows arrive in rank order
    score = "_s"
    for key, g in df.groupby(group):
        if len(g) < k or (group == "week" and g.day.nunique() < 7):  # only weeks fully inside the test span
            continue
        actual = set(g.nsmallest(k, rank_col).id) if rank_col else set(g.nlargest(k, "votes").id)
        vals.append(len(actual & set(g.nlargest(k, score).id)) / k)
    if per_list:
        return vals
    return (float(np.mean(vals)) if vals else np.nan), len(vals)


def ci(vals, n=2000, seed=0):
    """95% bootstrap interval of the mean over lists (days / weeks / months)."""
    if len(vals) < 2:
        return [np.nan, np.nan]
    b = np.random.default_rng(seed).choice(vals, (n, len(vals))).mean(1)
    return [float(np.percentile(b, 2.5)), float(np.percentile(b, 97.5))]


def evaluate(te, score="pred", with_ci=False):
    out = {}
    if with_ci:
        for per, col in (("day", "dailyRank"), ("week", "weeklyRank"), ("mon", "monthlyRank")):
            for k in KS:
                v = recall_at(te, per, col, k, score, per_list=True)
                out[f"{per}@{k}_ci"] = ci(v); out[f"{per}@{k}_n"] = len(v)
    for k in KS:
        out[f"day@{k}"] = recall_at(te, "day", "dailyRank", k, score)[0]
        out[f"week@{k}"] = recall_at(te, "week", "weeklyRank", k, score)[0]
        out[f"month@{k}"] = recall_at(te, "mon", "monthlyRank", k, score)[0]
    out["spearman_day"] = float(np.nanmean([spearmanr(g[score], -g.dailyRank)[0] for _, g in te.groupby("day")
                                            if g[score].nunique() > 1]))
    return out
