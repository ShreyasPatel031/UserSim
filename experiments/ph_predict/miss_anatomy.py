"""Error anatomy of the launch model's daily top-3 misses (queue item 8b, Nov 11): what kind of launches does the honest
pre-launch model under-rank? Generates hypotheses for the next features; it is not itself a model test.

Data  honest out-of-fold predictions (tmp/e5/honest/honest_preds.parquet, column "honest" = predicted log votes,
      Mar 1 - Oct 25), warehouse launches (topics, makers, poster, name, slug, tagline, description; history from Jan),
      exact-time comments (page dump, comment_forecast.load_comments).
Groups among each day's actual top 3: hit (predicted rank <= 3), near (4-10), miss (> 10); and false alarms (predicted
      top 3, finished > 10).
Attributes (all knowable at 00:05 except the comment ones, which are marked post-00:05):
  team_prev       earlier launches (since Jan) by any maker/hunter of this launch
  team_prev_top3  ... that finished daily top 3
  relaunch        the product name stem appeared on an earlier launch
  n_makers, self_hunted, hunter_prev (hunter's earlier hunted launches), weekday, lineup, desc_len, tagline_len,
  topic flags (top 12 topics), ai_topic
  c_4h, c_day     comments by 04:00 PT / by day end (post-00:05, reference only)
Residual view: r = logv - honest, centered within day; Spearman of r with each attribute, with day-bootstrap CI.
usage: python miss_anatomy.py -> results/miss_anatomy.json + results/miss_anatomy.md"""
import json, os, re, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)


def stem(name):
    n = re.sub(r"\b(v?\d+(\.\d+)*|2\.0|3\.0|ai|app|pro|beta|by .*)$", "", str(name).lower()).strip()
    return re.sub(r"[^a-z0-9]", "", n.split(" by ")[0])[:20]


def main():
    from pipeline import warehouse as W
    import comment_forecast as CF
    CF.fetch()
    H = pd.read_parquet(f"{CF.WORK}/honest_preds.parquet")[["id", "day", "honest", "dailyRank", "logv"]]; H["id"] = H.id.astype(str)
    L = W.query("SELECT CAST(id AS VARCHAR) id, slug, day, name, tagline, description, topics, poster, makers, daily_rank FROM launches WHERE daily_rank IS NOT NULL", do_sync=False)
    L["team"] = [{u.lower() for u in (json.loads(m) if m and m.startswith("[") else []) + ([p] if p else []) if u} for m, p in zip(L.makers, L.poster)]
    L["tp"] = [json.loads(t) if t and t.startswith("[") else [] for t in L.topics]
    L = L.sort_values("day").reset_index(drop=True)
    # history (earlier days only)
    seen_team, seen_top3, seen_hunter, seen_stem = {}, {}, {}, set()
    feats = []
    for d, g in L.groupby("day", sort=True):
        for r in g.itertuples():
            st = stem(r.name)
            feats.append({"id": r.id, "team_prev": sum(seen_team.get(u, 0) for u in r.team),
                          "team_prev_top3": sum(seen_top3.get(u, 0) for u in r.team),
                          "hunter_prev": seen_hunter.get((r.poster or "").lower(), 0), "relaunch": float(len(st) >= 3 and st in seen_stem),
                          "n_makers": len(r.team), "self_hunted": float((r.poster or "").lower() in {u.lower() for u in (json.loads(r.makers) if r.makers and r.makers.startswith("[") else [])}),
                          "desc_len": len(r.description or ""), "tagline_len": len(r.tagline or "")})
        for r in g.itertuples():   # update after the whole day (same-day launches are not history)
            for u in r.team:
                seen_team[u] = seen_team.get(u, 0) + 1
                if r.daily_rank <= 3:
                    seen_top3[u] = seen_top3.get(u, 0) + 1
            seen_hunter[(r.poster or "").lower()] = seen_hunter.get((r.poster or "").lower(), 0) + 1
            seen_stem.add(stem(r.name))
    Fe = pd.DataFrame(feats)
    X = H.merge(L[["id", "slug", "tp", "day"]].rename(columns={"day": "lday"}), on="id").merge(Fe, on="id")
    X["weekday"] = pd.to_datetime(X.day).dt.dayofweek.astype(float)
    X["lineup"] = X.groupby("day").id.transform("size").astype(float)
    top = pd.Series([t for ts in X.tp for t in ts]).value_counts().head(12).index.tolist()
    for t in top:
        X["topic:" + t] = [float(t in ts) for ts in X.tp]
    X["ai_topic"] = [float(any("artificial intelligence" in t.lower() or t.lower() in ("ai", "ai agents", "llm") for t in ts)) for ts in X.tp]
    # comments (post-00:05 reference)
    K, _ = CF.load_comments()
    K = K.merge(X[["slug", "day"]], on="slug")
    t0 = {d: pd.Timestamp(d + " 00:00", tz="America/Los_Angeles").tz_convert("UTC") for d in X.day.unique()}
    K["h"] = (K.ts - K.day.map(t0)).dt.total_seconds() / 3600
    X = X.join(K[K.h <= 4].groupby("slug").size().rename("c_4h"), on="slug").join(K[K.h <= 24].groupby("slug").size().rename("c_day"), on="slug")
    X[["c_4h", "c_day"]] = X[["c_4h", "c_day"]].fillna(0)
    X["prank"] = X.groupby("day").honest.rank(ascending=False, method="first")
    X["grp"] = np.where(X.dailyRank <= 3, np.where(X.prank <= 3, "hit", np.where(X.prank <= 10, "near", "miss")),
                        np.where((X.prank <= 3) & (X.dailyRank > 10), "false_alarm", "other"))
    X["resid"] = (X.logv - X.honest) - (X.logv - X.honest).groupby(X.day).transform("mean")
    attrs = ["team_prev", "team_prev_top3", "hunter_prev", "relaunch", "n_makers", "self_hunted", "desc_len", "tagline_len",
             "weekday", "lineup", "ai_topic"] + ["topic:" + t for t in top] + ["c_4h", "c_day"]
    G = X.groupby("grp")[attrs].mean().T.round(3)
    G["n"] = None
    cnt = X.grp.value_counts().to_dict()
    # residual Spearman with day bootstrap
    from scipy.stats import spearmanr
    rng = np.random.default_rng(0); days = X.day.unique(); byd = {d: g for d, g in X.groupby("day")}
    rs = {}
    for a in attrs:
        v = X[a] - X.groupby("day")[a].transform("mean")
        rho = spearmanr(v, X.resid).correlation
        bs = []
        for _ in range(300):
            s = pd.concat([byd[d] for d in rng.choice(days, len(days))])
            vv = s[a] - s.groupby("day")[a].transform("mean")
            bs.append(spearmanr(vv, s.resid).correlation)
        rs[a] = [round(float(rho), 3), round(float(np.nanpercentile(bs, 2.5)), 3), round(float(np.nanpercentile(bs, 97.5)), 3)]
    res = {"launches": int(len(X)), "days": int(X.day.nunique()), "groups": cnt, "group_means": G.drop(columns="n").to_dict(),
           "residual_spearman": rs}
    json.dump(res, open(os.path.join(HERE, "results", "miss_anatomy.json"), "w"), indent=1)
    md = ["# Error anatomy of the launch model's daily top-3 misses", "",
          f"{len(X):,} launches, {X.day.nunique()} days (honest out-of-fold, Mar 1 - Oct 25). Among each day's actual top 3: "
          f"hit {cnt.get('hit', 0)}, near (predicted 4-10) {cnt.get('near', 0)}, miss (predicted > 10) {cnt.get('miss', 0)}; "
          f"false alarms (predicted top 3, finished > 10) {cnt.get('false_alarm', 0)}.", "",
          "## Group means", "", "| attribute | hit | near | miss | false alarm | other |", "|---|---|---|---|---|---|"]
    for a in attrs:
        md.append(f"| {a} | " + " | ".join(f"{G.loc[a, g]:.2f}" if g in G.columns else "" for g in ("hit", "near", "miss", "false_alarm", "other")) + " |")
    md += ["", "## What the model under-predicts: Spearman of the within-day residual (log votes - prediction) with each "
           "attribute (within-day centered), 95% day-bootstrap", "", "| attribute | rho [CI] |", "|---|---|"]
    for a, v in sorted(rs.items(), key=lambda kv: -abs(kv[1][0])):
        md.append(f"| {a} | {v[0]:+.3f} [{v[1]:+.3f}, {v[2]:+.3f}] |")
    open(os.path.join(HERE, "results", "miss_anatomy.md"), "w").write("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    main()
