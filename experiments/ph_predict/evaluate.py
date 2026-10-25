"""Backtest: can we predict PH's Top Products lists (day / week / month, overall and per topic) without votes?

Expanding window: for each test month M, a LightGBM model trained on every launch before M scores M's launches.
The score ranks launches inside each list; recall@k = |predicted top k ∩ actual top k| / k, where the actual order
is PH's own dailyRank / weeklyRank / monthlyRank. Random guessing gets about k / n.

Also: source ablations (each group alone, all minus one), baselines, SHAP importance per feature, group and
product type. Writes out/metrics.json, out/report.md, out/predictions.csv.

    python experiments/ph_predict/evaluate.py
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import features as F  # noqa: E402

OUT = F.HERE / "out"
KS = (3, 5, 10)
PERIODS = {"day": ("day", "dailyRank"), "week": ("week", "weeklyRank"), "month": ("month", "monthlyRank")}
PARAMS = dict(n_estimators=500, learning_rate=0.03, num_leaves=15, min_child_samples=20, subsample=0.8,
              subsample_freq=1, colsample_bytree=0.7, reg_lambda=1.0, verbose=-1)
# Product types for "how factors change": first matching family wins.
FAMILIES = [("Developer", ["Developer Tools", "GitHub", "Open Source", "API", "Software Engineering", "No-Code"]),
            ("AI", ["Artificial Intelligence", "AI", "LLMs", "AI Agents", "Generative AI"]),
            ("Design", ["Design Tools", "Design", "3D Modeling", "Video", "Photography"]),
            ("Marketing & Sales", ["Marketing", "Sales", "SEO", "Social Media", "Growth Hacking", "Email Marketing"]),
            ("Productivity", ["Productivity", "Task Management", "Calendar", "Notes", "Writing"]),
            ("Consumer", ["Health & Fitness", "Lifestyle", "Education", "Travel", "Games", "Music", "Finance"])]


def family(topics: list[str]) -> str:
    for name, ts in FAMILIES:
        if any(t in ts for t in topics):
            return name
    return "Other"


def fit_predict(X: pd.DataFrame, y: pd.Series, train: np.ndarray, test: np.ndarray) -> np.ndarray:
    m = lgb.LGBMRegressor(**PARAMS).fit(X[train], y[train])
    return m.predict(X[test]), m


def backtest(df: pd.DataFrame, X: pd.DataFrame, cols: list[str], months: list[str]) -> pd.Series:
    """Out-of-sample score for every launch in the test months."""
    y = np.log1p(df.votes)
    score = pd.Series(np.nan, index=df.index)
    for m in months:
        train = (df.month < m).to_numpy()
        test = (df.month == m).to_numpy()
        if train.sum() < 200 or not test.any():
            continue
        score[test], _ = fit_predict(X[cols], y, train, test)
    return score


def recall_lists(df: pd.DataFrame, score: pd.Series, topic: str | None = None, complete_months=()) -> dict:
    """Mean recall@k per period, overall or within one topic's list."""
    d = df.assign(score=score).dropna(subset=["score"])
    if topic:
        d = d[d.topics.apply(lambda ts: topic in ts)]
    out = {}
    for period, (key, rank) in PERIODS.items():
        dd = d[d.month.isin(complete_months)] if period == "month" else d
        if period == "week":  # only weeks fully inside the scored data
            full = dd.groupby("week").day.nunique()
            dd = dd[dd.week.isin(full[full == 7].index)]
        for k in KS:
            rec, rnd = [], []
            for _, g in dd.groupby(key):
                g = g.dropna(subset=[rank])
                if len(g) < 2 * k:
                    continue
                actual = set(g.nsmallest(k, rank).id)
                pred = set(g.nlargest(k, "score").id)
                rec.append(len(actual & pred) / k)
                rnd.append(k / len(g))
            if rec:
                boot = np.random.default_rng(0).choice(rec, (1000, len(rec))).mean(axis=1)
                out[f"{period}@{k}"] = {"recall": round(float(np.mean(rec)), 3), "random": round(float(np.mean(rnd)), 3),
                                        "lists": len(rec), "ci95": [round(float(x), 3) for x in np.percentile(boot, [2.5, 97.5])]}
    return out


def shap_by(df: pd.DataFrame, X: pd.DataFrame, cols: list[str], groups: dict, months: list[str]) -> dict:
    y = np.log1p(df.votes)
    contrib = []
    for m in months:
        train, test = (df.month < m).to_numpy(), (df.month == m).to_numpy()
        if train.sum() < 200 or not test.any():
            continue
        _, model = fit_predict(X[cols], y, train, test)
        c = model.predict(X[cols][test], pred_contrib=True)[:, :-1]
        contrib.append(pd.DataFrame(np.abs(c), columns=cols, index=df.index[test]))
    c = pd.concat(contrib)
    fam = df.loc[c.index].topics.apply(family)
    g_of = {col: g for g, cs in groups.items() for col in cs}
    per_feature = c.mean().sort_values(ascending=False)
    per_group = c.T.groupby(lambda col: g_of[col]).sum().T
    by_family = per_group.groupby(fam).mean()
    by_family = by_family.div(by_family.sum(axis=1), axis=0).round(3)
    top_by_family = {f: c[fam == f].mean().sort_values(ascending=False).head(8).round(4).to_dict()
                     for f in fam.unique()}
    return {"top_features": per_feature.head(30).round(4).to_dict(),
            "group_share": (per_group.mean() / per_group.mean().sum()).round(3).sort_values(ascending=False).to_dict(),
            "group_share_by_family": by_family.to_dict(orient="index"),
            "top_features_by_family": top_by_family, "family_counts": fam.value_counts().to_dict()}


def factors_by_family(df: pd.DataFrame, X: pd.DataFrame, fam: pd.Series, cols: list[str]) -> dict:
    """Spearman correlation of each feature with log votes inside the same week, per product type: which factors
    go with doing well, and whether that differs by type."""
    y = np.log1p(df.votes)
    y = y - y.groupby(df.week).transform("mean")
    out = {}
    for f in ["(all types)"] + sorted(fam.unique()):
        m = np.ones(len(df), bool) if f == "(all types)" else (fam == f).to_numpy()
        xs = X.loc[m, cols]
        xs = xs - xs.groupby(df.week[m]).transform("mean")
        c = xs.corrwith(y[m], method="spearman").dropna()
        out[f] = {"n": int(m.sum()), "top": c.reindex(c.abs().sort_values(ascending=False).index).head(10).round(3).to_dict()}
    return out


def main() -> None:
    OUT.mkdir(exist_ok=True)
    df, X, groups = F.build()
    keep = df.complete.to_numpy()  # drop live (unfinished) days
    df, X = df[keep].reset_index(drop=True), X[keep].reset_index(drop=True)
    groups = {g: c for g, c in groups.items() if c}
    with_followers = [c for cs in groups.values() for c in cs]
    groups.pop("followers")  # headline model: no follower counts (today's counts include the launch's own effect)
    all_cols = [c for cs in groups.values() for c in cs]
    months = sorted(df.month.unique())
    test_months = [m for m in months if (df.month < m).sum() >= 200]
    last_day = df.day.max()
    complete = [m for m in test_months if m < last_day[:7]]
    print(f"{len(df)} launches {df.day.min()}..{last_day}; test months {test_months}; complete {complete}", flush=True)

    res: dict = {"n_launches": len(df), "days": [df.day.min(), last_day], "test_months": test_months,
                 "groups": {g: len(c) for g, c in groups.items()},
                 "coverage": {k: round(float(v), 3) for k, v in {
                     "site_loaded": (X.get("site_ok", 0) == 1).mean(),
                     "llm_scored": X.get("llm_novelty", np.nan * 0).notna().mean() if "llm_novelty" in X else 0,
                     "hn_story_before_launch": (X.get("hn_stories", 0) > 0).mean(),
                     "domain_age_known": X.get("domain_age_days", np.nan * 0).notna().mean() if "domain_age_days" in X else 0,
                     "github_repo": (X.get("github_repo_found", 0) == 1).mean(),
                     "maker_launched_before": (X.hist_maker_prior_launches > 0).mean()}.items()}}
    full = backtest(df, X, all_cols, test_months)
    res["full"] = recall_lists(df, full, complete_months=complete)
    res["full_with_followers"] = recall_lists(df, backtest(df, X, with_followers, test_months),
                                              complete_months=complete)
    test = full.notna()
    res["by_month"] = {m: {k: v["recall"] for k, v in recall_lists(df[df.month == m], full[df.month == m]).items()
                           if k.startswith(("day", "week"))} for m in test_months}
    res["spearman_day"] = round(float(df[test].assign(s=full).groupby("day").apply(
        lambda g: g.s.corr(-g.dailyRank, method="spearman")).mean()), 3)

    # Baselines (no model): single heuristics
    base = {"followers today (hunter+makers; leaky)": X.followers_hunter_log + X.followers_maker_sum_log}
    if "llm_p_top5" in X:
        base["llm p_top5 alone"] = X.llm_p_top5
    if "hist_lookalike_top10_rate" in X:
        base["look-alike earlier launches"] = X.hist_lookalike_top10_rate
    res["baselines"] = {k: recall_lists(df, v.where(test), complete_months=complete) for k, v in base.items()}

    # Source ablations
    res["only"], res["without"] = {}, {}
    fam = df.topics.apply(family)
    by_family: dict = defaultdict(dict)
    for g, cs in groups.items():
        only = backtest(df, X, cs, test_months)
        res["only"][g] = recall_lists(df, only, complete_months=complete)
        for f in fam.unique():  # each source alone, ranking a type's launches against each other per week
            by_family[f][g] = recall_lists(df[fam == f], only[fam == f], complete_months=complete).get("week@5")
        rest = [c for c in all_cols if c not in cs]
        res["without"][g] = recall_lists(df, backtest(df, X, rest, test_months), complete_months=complete)
        print("ablation", g, res["only"][g].get("day@5"), res["without"][g].get("day@5"), flush=True)

    by_family["(all types)"] = {g: r.get("week@5") for g, r in res["only"].items()}
    res["only_by_family"] = by_family
    res["factors_by_family"] = factors_by_family(df, X, fam, all_cols)

    # Topic lists
    topic_counts = pd.Series([t for ts in df[test].topics for t in ts]).value_counts()
    res["topics"] = {t: recall_lists(df, full, topic=t, complete_months=complete) for t in topic_counts.index[:15]}
    res["importance"] = shap_by(df, X, all_cols, groups, test_months)

    # The lists on PH's homepage right now (Oct 25): yesterday, last week, last month
    res["current_lists"] = current_lists(df, full)
    (OUT / "metrics.json").write_text(json.dumps(res, indent=1, default=str))
    df.assign(score=full)[["id", "name", "day", "week", "month", "topics", "dailyRank", "weeklyRank", "monthlyRank",
                           "score"]].to_csv(OUT / "predictions.csv", index=False)
    print(json.dumps(res["full"], indent=1))


def current_lists(df: pd.DataFrame, score: pd.Series) -> dict:
    d = df.assign(score=score).dropna(subset=["score"])
    last = d.day.max()
    weeks = d.groupby("week").day.nunique()
    last_week = max(w for w, n in weeks.items() if n == 7) if (weeks == 7).any() else None
    months = sorted(m for m in d.month.unique() if m < last[:7])
    out = {}
    for label, key, val, rank in (("yesterday", "day", last, "dailyRank"), ("last_week", "week", last_week, "weeklyRank"),
                                  ("last_month", "month", months[-1] if months else None, "monthlyRank")):
        if val is None:
            continue
        g = d[d[key] == val]
        actual = g.nsmallest(10, rank)
        pred = g.nlargest(10, "score")
        out[label] = {"period": val, "n_launches": len(g),
                      "actual_top10": actual.name.tolist(), "predicted_top10": pred.name.tolist(),
                      **{f"recall@{k}": len(set(actual.id[:k]) & set(pred.id[:k])) / k for k in KS}}
    return out


if __name__ == "__main__":
    main()
