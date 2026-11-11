"""False favourites (orchestrator 01:00Z Nov 12): a second-stage correction of the launch model's ranking for big-brand
sub-launches and similar picks the LM over-trusts, plus a calibration table for a website confidence flag.
Data: the PH agent's honest LM table (honest_preds.parquet: out-of-sample pre-launch prediction "honest", dailyRank), the
comment-forecast days (cf_rows, 238 days, the first month only trains -> 207 scored days, LM 63.0/69.3/75.0), warehouse
launches (name, makers, poster = hunter, topics).
Features, all known at 00:05: LM score, LM rank in the day, margin to the next LM pick, gap to the LM #3/#4 boundary,
line-up size; name patterns ("X by Brand", " for ", version number/"2.0"/"v3", "AI"); makers: number named, share of
"[REDACTED]" placeholders, poster is a maker; hunter's past hunts and past top-3 rate (launch days < d), team's past
launches and past top-3 rate; top topic (first listed topic, categorical, top 30 kept).
Model: LightGBM classifier on each day's LM top-8, target = finished top 3, month-forward (months < m). The day's top 8 are
re-ordered by the predicted P(top 3); positions 9+ keep LM order. Daily top 3/5/10 overlap with the final daily rank vs LM
only, paired by day, 4000 day-bootstrap draws. Calibration: hit rate of LM picks by LM rank and confidence bucket, and the
model's P(top 3) deciles vs observed.
    python false_favourites.py <cf dir: cf_rows.parquet honest_preds.parquet> <launches dir> <out.json>
"""
import glob, json, os, re, sys
import numpy as np, pandas as pd
import lightgbm as lgb

CFD, LDIR, OUT = sys.argv[1:4]; rng = np.random.default_rng(0)
days = sorted(pd.read_parquet(os.path.join(CFD, "cf_rows.parquet")).day.unique())
H = pd.read_parquet(os.path.join(CFD, "honest_preds.parquet"))[["id", "honest", "day", "dailyRank"]]; H["id"] = H.id.astype(str)
L = pd.concat([pd.read_parquet(f) for f in glob.glob(os.path.join(LDIR, "*.parquet"))]).sort_values("updated_at").drop_duplicates("id", keep="last")
L["id"] = L.id.astype(str)
L["mk"] = L.makers.map(lambda s: json.loads(s) if isinstance(s, str) and s.startswith("[") else [])
L["topic"] = L.topics.map(lambda s: (json.loads(s) or ["none"])[0] if isinstance(s, str) and s.startswith("[") else "none")
X = H[H.day.isin(days)].merge(L[["id", "name", "mk", "poster", "topic"]], on="id", how="left").dropna(subset=["honest", "dailyRank"])
X["top3"] = (X.dailyRank <= 3).astype(int)
g = X.groupby("day")
X["lm_rank"] = g.honest.rank(ascending=False, method="first"); X["n_day"] = g.id.transform("size")
X = X.sort_values(["day", "lm_rank"])
X["margin_next"] = X.honest - X.groupby("day").honest.shift(-1)
s3 = X[X.lm_rank == 3].set_index("day").honest; s4 = X[X.lm_rank == 4].set_index("day").honest
X["gap34"] = X.day.map(s3 - s4); X["to_boundary"] = X.honest - X.day.map((s3 + s4) / 2)
nm = X.name.fillna("")
X["by_brand"] = nm.str.contains(r"\bby\s+[A-Z]", regex=True).astype(int); X["for_x"] = nm.str.contains(r"\bfor\s+[A-Z]", regex=True).astype(int)
X["version"] = nm.str.contains(r"\b\d+(\.\d+)+\b|\bv\d+\b|\b\d\.0\b|\b(2|3|4|5)\b", regex=True).astype(int)
X["ai_name"] = nm.str.contains(r"\bAI\b", regex=True).astype(int); X["name_len"] = nm.str.len()
X["n_makers"] = X.mk.map(len); X["ph_share"] = X.mk.map(lambda m: np.mean([str(a).startswith("[") for a in m]) if m else 0.0)
X["named_makers"] = X.mk.map(lambda m: sum(not str(a).startswith("[") for a in m))
X["poster_is_maker"] = [int(str(p).lower() in {str(a).lower() for a in m}) for p, m in zip(X.poster, X.mk)]
# hunter and team history from all launches (launch days strictly before d)
A = L[L.daily_rank.notna()][["id", "day", "poster", "mk", "daily_rank"]].copy(); A["hit"] = (A.daily_rank <= 3).astype(int)
hp = {}
for p, gg in A.groupby("poster"): hp[p] = (gg.day.to_numpy(), gg.hit.to_numpy())
def hist(p, d):
    if p not in hp: return 0, np.nan
    dd, hh = hp[p]; m = dd < d; return int(m.sum()), (hh[m].mean() if m.any() else np.nan)
hh = [hist(p, d) for p, d in zip(X.poster, X.day)]; X["hunter_n"] = [a for a, _ in hh]; X["hunter_hit"] = [b for _, b in hh]
mrows = {}
for i, d, mk, h in zip(A.id, A.day, A.mk, A.hit):
    for m in mk:
        if not str(m).startswith("["): mrows.setdefault(str(m).lower(), []).append((d, h))
def team(mk, d):
    v = [(dd, h) for m in mk if not str(m).startswith("[") for dd, h in mrows.get(str(m).lower(), []) if dd < d]
    return len(v), (np.mean([h for _, h in v]) if v else np.nan)
tt = [team(m, d) for m, d in zip(X.mk, X.day)]; X["team_n"] = [a for a, _ in tt]; X["team_hit"] = [b for _, b in tt]
top_topics = X.topic.value_counts().index[:30]; X["topic_c"] = pd.Categorical(np.where(X.topic.isin(top_topics), X.topic, "other"))
FE = ["honest", "lm_rank", "margin_next", "gap34", "to_boundary", "n_day", "by_brand", "for_x", "version", "ai_name", "name_len",
      "n_makers", "ph_share", "named_makers", "poster_is_maker", "hunter_n", "hunter_hit", "team_n", "team_hit", "topic_c"]
X["m"] = X.day.str[:7]; X["p"] = np.nan
T8 = X.lm_rank <= 8
for mo in sorted(X.m.unique())[1:]:
    tr = T8 & (X.m < mo); te = T8 & (X.m == mo)
    clf = lgb.LGBMClassifier(n_estimators=200, learning_rate=0.03, num_leaves=7, min_child_samples=40, subsample=0.8, subsample_freq=1,
                             colsample_bytree=0.8, reg_lambda=5.0, verbose=-1, random_state=0).fit(X.loc[tr, FE], X.loc[tr, "top3"])
    X.loc[te, "p"] = clf.predict_proba(X.loc[te, FE])[:, 1]
S = X[X.m > sorted(X.m.unique())[0]].copy()
S["corr"] = np.where(S.lm_rank <= 8, 100 + S.p.fillna(0), -S.lm_rank)       # top 8 re-ordered by P(top3), rest keep LM order
S["lm"] = -S.lm_rank


def per(gd, col):
    return [len(set(gd.nlargest(k, col).id) & set(gd.nsmallest(k, "dailyRank").id)) / k * 100 for k in (3, 5, 10)]


def boot(v, B=4000):
    v = np.asarray(v, float); bs = np.array([v[rng.integers(0, len(v), len(v))].mean(0) for _ in range(B)])
    return [[round(float(v[:, j].mean()), 1), round(float(np.percentile(bs[:, j], 2.5)), 1), round(float(np.percentile(bs[:, j], 97.5)), 1)] for j in range(v.shape[1])]


A_ = np.array([per(gd, "lm") for _, gd in S.groupby("day")]); B_ = np.array([per(gd, "corr") for _, gd in S.groupby("day")])
res = {"design": __doc__.split("\n    python")[0], "days": int(S.day.nunique()),
       "LM only": dict(zip(["top3", "top5", "top10"], boot(A_))), "LM + second stage": dict(zip(["top3", "top5", "top10"], boot(B_))),
       "second stage minus LM (paired by day)": dict(zip(["top3", "top5", "top10"], boot(B_ - A_)))}
# calibration of LM picks
P3 = S[S.lm_rank <= 3].copy()
P3["conf"] = pd.qcut(P3.gap34, 3, labels=["low #3/#4 margin", "mid", "high"])
res["LM top-3 pick hit rate by LM rank"] = P3.groupby("lm_rank").top3.agg(["mean", "size"]).round(3).reset_index().to_dict("records")
res["LM top-3 pick hit rate by day margin tercile"] = P3.groupby("conf", observed=True).top3.agg(["mean", "size"]).round(3).reset_index().to_dict("records")
res["false-favourite flags among LM top-3 picks (hit rate, n)"] = {f: [round(float(P3[P3[f] == 1].top3.mean()), 3), int((P3[f] == 1).sum())] for f in ("by_brand", "version", "for_x", "ai_name")}
P8 = S[(S.lm_rank <= 8) & S.p.notna()].copy(); P8["dec"] = pd.qcut(P8.p, 5, duplicates="drop")
res["second-stage P(top3) quintiles vs observed (LM top 8)"] = [{"p_range": str(k), "mean_p": round(float(v.p.mean()), 3), "observed": round(float(v.top3.mean()), 3), "n": int(len(v))} for k, v in P8.groupby("dec", observed=True)]
P3p = P3.dropna(subset=["p"]); P3p["pc"] = pd.cut(P3p.p, [0, 0.3, 0.5, 0.7, 1.0])
res["LM top-3 picks by second-stage P(top3)"] = [{"p_bucket": str(k), "observed": round(float(v.top3.mean()), 3), "n": int(len(v))} for k, v in P3p.groupby("pc", observed=True)]
json.dump(res, open(OUT, "w"), indent=1, default=str)
print(json.dumps({k: v for k, v in res.items() if k != "design"}, indent=1, default=str))
