"""Which Show HN posts make each day's top k (by final points)? Post-only model, rolling monthly backtest.

Mirrors experiments/ph_predict: every input is known when the post goes up; a post's own points and comments are
never inputs. History features use only posts created strictly before the post. Test month M is predicted by a model
trained only on posts before M. recall@k = |predicted top k ∩ actual top k| / k per UTC day; 95% bootstrap over days.
Ties: random tie-break (never row order).

    python rank.py [first_test_month]        # e.g. 2025-08
"""
from __future__ import annotations

import json
import re
import sys
from urllib.parse import urlparse

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import Ridge

import store as S

KS = (3, 10)


def posts() -> pd.DataFrame:
    p = S.read("hn_posts")
    p = p[p.get("kind").isna()] if "kind" in p else p
    p = p.drop_duplicates("post_id").sort_values("created_at_i").reset_index(drop=True)
    p["points"] = p.points.fillna(0).astype(float)
    p["month"] = p.day.str[:7]
    return p


def features(p: pd.DataFrame) -> pd.DataFrame:
    t = pd.to_datetime(p.created_at_i, unit="s", utc=True)
    f = pd.DataFrame(index=p.index)
    f["hour"], f["dow"] = t.dt.hour, t.dt.dayofweek
    # posts in the 24 h / 1 h before this one: known at post time, and the same for a past day and a live one
    ts = p.created_at_i.to_numpy()
    f["day_n"] = np.arange(len(p)) - np.searchsorted(ts, ts - 86400)
    f["hour_n"] = np.arange(len(p)) - np.searchsorted(ts, ts - 3600)
    title = p.title.fillna("").str.replace(r"^Show HN:\s*", "", regex=True)
    f["title_len"], f["title_words"] = title.str.len(), title.str.split().str.len()
    for k, rx in {"open_source": r"open.?source", "ai": r"\b(ai|llm|gpt|claude|gemini|agent)s?\b", "free": r"\bfree\b",
                  "i_built": r"\bi (built|made|wrote|created)\b", "game": r"\bgame\b", "rust": r"\brust\b",
                  "browser": r"\bbrowser\b", "dash": r"[–—-]", "question": r"\?"}.items():
        f[k] = title.str.contains(rx, case=False, regex=True).astype(int)
    f["text_len"] = p.text.fillna("").str.len()
    host = p.url.fillna("").map(lambda u: urlparse(u).netloc.lower().removeprefix("www."))
    f["no_url"] = (host == "").astype(int)
    f["github"] = host.str.endswith("github.com").astype(int)
    f["github_io"] = host.str.endswith("github.io").astype(int)
    f["subdomain"] = (host.str.count(r"\.") >= 2).astype(int)
    f["path_depth"] = p.url.fillna("").map(lambda u: len([x for x in urlparse(u).path.split("/") if x]))
    tld = host.str.extract(r"\.([a-z]+)$")[0].fillna("")
    for t_ in ("com", "dev", "io", "ai", "app", "org", "sh"):
        f[f"tld_{t_}"] = (tld == t_).astype(int)
    # author's and domain's earlier Show HN posts (strictly before this post)
    for key, name in ((p.author, "author"), (host.where(~host.isin(["", "github.com"]), None), "domain")):
        g = pd.DataFrame({"k": key, "t": p.created_at_i, "pts": np.log1p(p.points)}).reset_index()
        n_prev, max_prev, mean_prev = np.zeros(len(p)), np.full(len(p), np.nan), np.full(len(p), np.nan)
        for _, grp in g.dropna(subset=["k"]).groupby("k"):
            grp = grp.sort_values("t")
            pts, idx = grp.pts.to_numpy(), grp["index"].to_numpy()
            for j in range(1, len(grp)):
                n_prev[idx[j]] = j
                max_prev[idx[j]] = pts[:j].max()
                mean_prev[idx[j]] = pts[:j].mean()
        f[f"{name}_prev_n"], f[f"{name}_prev_max"], f[f"{name}_prev_mean"] = n_prev, max_prev, mean_prev
    return f


def recall(day: pd.Series, y: np.ndarray, s: np.ndarray, k: int, rng) -> list[float]:
    out = []
    df = pd.DataFrame({"day": day.to_numpy(), "y": y + rng.random(len(y)) * 1e-6, "s": s + rng.random(len(s)) * 1e-9})
    for _, g in df.groupby("day"):
        if len(g) >= k:
            out.append(len(set(g.nlargest(k, "y").index) & set(g.nlargest(k, "s").index)) / k)
    return out


def boot(x, n=5000, seed=0):
    x = np.asarray(x)
    m = np.random.default_rng(seed).choice(x, (n, len(x))).mean(1)
    return round(float(x.mean()), 3), round(float(np.percentile(m, 2.5)), 3), round(float(np.percentile(m, 97.5)), 3)


def backtest(first: str = "2025-08") -> pd.DataFrame:
    p = posts()
    p = p[p.created_at_i < pd.Timestamp.now(tz="UTC").timestamp() - 3 * 86400]   # final points only
    F = features(p)
    y = np.log1p(p.points.to_numpy())
    preds = []
    months = sorted(m for m in p.month.unique() if m >= first)
    for m in months:
        tr, te = (p.month < m).to_numpy(), (p.month == m).to_numpy()
        tf = TfidfVectorizer(min_df=5, ngram_range=(1, 2), sublinear_tf=True)
        Xt = tf.fit_transform(p.title[tr].fillna("") + " " + p.text[tr].fillna("").str[:300])
        rid = Ridge(alpha=3.0).fit(Xt, y[tr])
        txt = rid.predict(tf.transform(p.title[te].fillna("") + " " + p.text[te].fillna("").str[:300]))
        # out-of-fold text score for training rows (no row scores itself)
        oof = np.zeros(tr.sum())
        folds = np.arange(tr.sum()) % 5
        Xa = Xt
        for k in range(5):
            r2 = Ridge(alpha=3.0).fit(Xa[folds != k], y[tr][folds != k])
            oof[folds == k] = r2.predict(Xa[folds == k])
        Ftr, Fte = F[tr].assign(text_score=oof), F[te].assign(text_score=txt)
        gbm = lgb.LGBMRegressor(n_estimators=400, learning_rate=0.03, num_leaves=31, min_child_samples=40,
                                subsample=0.8, subsample_freq=1, colsample_bytree=0.8, verbose=-1, random_state=0)
        gbm.fit(Ftr, y[tr])
        preds.append(pd.DataFrame({"post_id": p.post_id[te], "day": p.day[te], "month": m, "y": y[te],
                                   "post_model": gbm.predict(Fte), "text_only": txt,
                                   "author_prev_max": Fte.author_prev_max.fillna(-1).to_numpy()}))
    P = pd.concat(preds, ignore_index=True)
    rng = np.random.default_rng(0)
    res = {}
    for k in KS:
        n_day = P.groupby("day").size()
        res[f"random@{k}"] = round(float(np.mean([k / n for n in n_day if n >= k])), 3)
        for col in ("post_model", "text_only", "author_prev_max"):
            res[f"{col}@{k}"] = boot(recall(P.day, P.y.to_numpy(), P[col].to_numpy(), k, rng))
    res["test_days"], res["test_months"] = int(P.day.nunique()), f"{months[0]}..{months[-1]}"
    print(json.dumps(res, indent=1))
    imp = pd.Series(gbm.booster_.feature_importance("gain"), index=Ftr.columns).sort_values(ascending=False)
    print("top features (last month's model, gain):", (imp / imp.sum()).round(3).head(12).to_dict())
    return P


if __name__ == "__main__":
    backtest(sys.argv[1] if len(sys.argv) > 1 else "2025-08")


def forecast(day: str, k: int = 10) -> pd.DataFrame:
    """Rank `day`'s posts so far with a model trained on every post with final points (3+ days old)."""
    p = posts()
    F = features(p)
    y = np.log1p(p.points.to_numpy())
    tr = (p.created_at_i < pd.Timestamp.now(tz="UTC").timestamp() - 3 * 86400).to_numpy()
    te = (p.day == day).to_numpy()
    tf = TfidfVectorizer(min_df=5, ngram_range=(1, 2), sublinear_tf=True)
    doc = p.title.fillna("") + " " + p.text.fillna("").str[:300]
    Xt = tf.fit_transform(doc[tr])
    folds = np.arange(tr.sum()) % 5
    oof = np.zeros(tr.sum())
    for f_ in range(5):
        oof[folds == f_] = Ridge(alpha=3.0).fit(Xt[folds != f_], y[tr][folds != f_]).predict(Xt[folds == f_])
    txt = Ridge(alpha=3.0).fit(Xt, y[tr]).predict(tf.transform(doc[te]))
    gbm = lgb.LGBMRegressor(n_estimators=400, learning_rate=0.03, num_leaves=31, min_child_samples=40, subsample=0.8,
                            subsample_freq=1, colsample_bytree=0.8, verbose=-1, random_state=0)
    gbm.fit(F[tr].assign(text_score=oof), y[tr])
    out = p[te][["post_id", "created_at", "title", "url", "points"]].assign(
        score=gbm.predict(F[te].assign(text_score=txt))).sort_values("score", ascending=False)
    S.write("hn_scores", out.head(k).assign(kind="forecast", model="post_only_v1", forecast_day=day,
                                            rank=range(1, min(k, len(out)) + 1), made_on=S.now())
            [["kind", "model", "forecast_day", "rank", "post_id", "title", "score", "made_on"]])
    return out
