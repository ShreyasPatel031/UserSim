"""Which stories will appear in the live Hacker News top 10 today? All story types, no votes used as inputs.

Ground truth going forward: frontpage.py records the live top 30 every 5 minutes; a story is a hit if it was ever in
the top 10. HN keeps no rank history, so the backtest uses two proxies from Algolia: the day's top N stories by final
points (N = how many distinct stories reach the live top 10 in a day, measured from the recording), and Algolia's
front_page tag (reached the front page). Inputs are known when a story is posted (rank.features: title, text, link,
domain's and author's earlier stories, hour, day volume). Rolling monthly backtest like rank.py.

    python top10.py backtest [first_month] [N]
    python top10.py today [N]
"""
from __future__ import annotations

import json
import sys

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import Ridge

import rank as R
import store as S

GBM = dict(n_estimators=500, learning_rate=0.05, num_leaves=63, min_child_samples=50, subsample=0.8, subsample_freq=1,
           colsample_bytree=0.8, verbose=-1, random_state=0)


def stories() -> pd.DataFrame:
    p = S.read("hn_posts")
    p = p[p.get("tag_set") == "story"].drop_duplicates("post_id").sort_values("created_at_i").reset_index(drop=True)
    p["points"] = p.points.fillna(0).astype(float)
    p["month"] = p.day.str[:7]
    p["front_page"] = p.algolia_tags.fillna("").str.contains("front_page").astype(int)
    return p


def feats(p: pd.DataFrame) -> pd.DataFrame:
    f = R.features(p)
    t = p.title.fillna("")
    f["show_hn"] = t.str.startswith("Show HN").astype(int)
    f["ask_hn"] = t.str.startswith(("Ask HN", "Tell HN")).astype(int)
    f["year_tag"] = t.str.contains(r"\((19|20)\d\d\)").astype(int)
    f["pdf"] = t.str.contains(r"\[pdf\]", case=False).astype(int)
    return f


def text_scores(p, y, tr, te):
    doc = p.title.fillna("") + " " + p.url.fillna("").str.replace(r"https?://(www\.)?", "", regex=True).str.split("/").str[0]
    tf = TfidfVectorizer(min_df=5, ngram_range=(1, 2), sublinear_tf=True, max_features=300000)
    Xt = tf.fit_transform(doc[tr])
    folds = np.arange(tr.sum()) % 5
    oof = np.zeros(tr.sum())
    for k in range(5):
        oof[folds == k] = Ridge(alpha=3.0).fit(Xt[folds != k], y[tr][folds != k]).predict(Xt[folds == k])
    return oof, Ridge(alpha=3.0).fit(Xt, y[tr]).predict(tf.transform(doc[te]))


def day_hits(P: pd.DataFrame, col: str, n: int, rng) -> list[float]:
    out = []
    for _, g in P.groupby("day"):
        if len(g) < n:
            continue
        a = set(g.nlargest(n, "y").index)
        s = g[col] + rng.random(len(g)) * 1e-9
        out.append(len(a & set(s.nlargest(n).index)) / n)
    return out


def backtest(first: str = "2025-08", n: int = 40) -> None:
    p = stories()
    p = p[p.created_at_i < pd.Timestamp.now(tz="UTC").timestamp() - 3 * 86400].reset_index(drop=True)
    F = feats(p)
    y = np.log1p(p.points.to_numpy())
    out = []
    for m in sorted(x for x in p.month.unique() if x >= first):
        tr, te = (p.month < m).to_numpy(), (p.month == m).to_numpy()
        oof, txt = text_scores(p, y, tr, te)
        g = lgb.LGBMRegressor(**GBM).fit(F[tr].assign(text_score=oof), y[tr])
        out.append(pd.DataFrame({"day": p.day[te], "y": y[te], "front_page": p.front_page[te],
                                 "model": g.predict(F[te].assign(text_score=txt)), "text_only": txt}))
        print(m, flush=True)
    P = pd.concat(out)
    rng = np.random.default_rng(0)
    res = {"stories_per_day": round(float(P.groupby("day").size().mean()), 1), "test_days": int(P.day.nunique())}
    for k in sorted({10, 30, n}):
        res[f"random@{k}"] = round(float(np.mean([k / len(g) for _, g in P.groupby("day")])), 3)
        for col in ("model", "text_only"):
            res[f"{col}@{k}"] = R.boot(day_hits(P, col, k, rng))
    # front-page tag: share of the day's front-page stories found in the model's top (number of them) per day
    fp = [len(set(g[g.front_page == 1].index) & set(g.model.nlargest(int(g.front_page.sum())).index)) / g.front_page.sum()
          for _, g in P.groupby("day") if g.front_page.sum() > 0]
    res["front_page_recall_at_its_count"] = R.boot(fp)
    res["front_page_per_day"] = round(float(P.groupby("day").front_page.sum().mean()), 1)
    print(json.dumps(res, indent=1))
    imp = pd.Series(g.booster_.feature_importance("gain"), index=F.columns.tolist() + ["text_score"]).sort_values()[::-1]
    print("top features:", (imp / imp.sum()).round(3).head(10).to_dict())


def today(n: int = 40, day: str | None = None) -> pd.DataFrame:
    import stories as ST
    day = day or pd.Timestamp.now(tz="UTC").date().isoformat()
    t0 = int(pd.Timestamp(day, tz="UTC").timestamp())
    live = pd.DataFrame(ST.rows(t0, int(pd.Timestamp.now(tz="UTC").timestamp()) - t0 + 1)).assign(tag_set="story_partial")
    S.write("hn_posts", live)   # today so far (points not final; never used as inputs)
    p = stories()
    p = pd.concat([p[p.day != day], live.assign(points=0.0, month=day[:7], front_page=0)], ignore_index=True)
    p = p.drop_duplicates("post_id").sort_values("created_at_i").reset_index(drop=True)
    F = feats(p)
    y = np.log1p(p.points.to_numpy())
    tr = (p.created_at_i < pd.Timestamp.now(tz="UTC").timestamp() - 3 * 86400).to_numpy()
    te = (p.day == day).to_numpy()
    oof, txt = text_scores(p, y, tr, te)
    g = lgb.LGBMRegressor(**GBM).fit(F[tr].assign(text_score=oof), y[tr])
    o = p[te][["post_id", "created_at", "title", "url"]].assign(score=g.predict(F[te].assign(text_score=txt)))
    o = o.sort_values("score", ascending=False)
    S.write("hn_scores", o.head(n).assign(kind="forecast_top10", model="post_only_all_v1", forecast_day=day,
                                          rank=range(1, min(n, len(o)) + 1), made_on=S.now())
            [["kind", "model", "forecast_day", "rank", "post_id", "title", "score", "made_on"]])
    return o


if __name__ == "__main__":
    if sys.argv[1] == "backtest":
        backtest(*(sys.argv[2:3] or ["2025-08"]), *([int(sys.argv[3])] if len(sys.argv) > 3 else []))
    else:
        o = today(int(sys.argv[2]) if len(sys.argv) > 2 else 40)
        for i, r in enumerate(o.head(40).itertuples()):
            print(i + 1, r.created_at[11:16], r.title[:90])
