"""Pre-reveal forecast from comments (orchestrator 20:45Z Nov 11). Before the ~04:00 PT reveal no vote count is visible,
but comments carry exact created_at, so the first hours of a launch day can be backtested over months.

Data (read-only, no new pulls)
  comments  raw/ph_predict_data/comments/page{1,1b,1c,2}.jsonl.gz: the launch page's own thread query (top 50 threads by
            votes + nested replies; page2 = threads 51-100 for some), parsed by ph_comments.parse; exact createdAt.
            Dedup on comment id. Comment votes are final-time (not dated): NOT used. No follower counts in this source.
  launches  warehouse launches (id, slug, day, daily_rank, makers, poster); the day's line-up = all ranked launches.
  LM        honest pre-launch launch-model prediction (tmp/e5/honest/honest_preds.parquet, column "honest", OOF), the
            offline stand-in for the 00:05 LM line (the live 00:05 forecasts only exist from Oct 25).
Days      launch days where >= COVER (0.8) of the ranked line-up is in the comment dump and has an honest prediction.
Cuts      T = 00:00 PT of the launch day + {1,2,3,4} h ("00:01 PT" start); features use comments with created_at <= T only.
Features  n_c (comments), n_top / n_rep (top-level / replies), n_team (comments by makers or hunter), u_out (unique
          non-team commenters), u_ver / u_prom (verified / prominent non-team commenters; account flags read at fetch
          time, a mild late read), u_prior (non-team commenters with a comment in the dump created before the day),
          u_tie (non-team commenters who earlier commented on a launch by one of this launch's makers/hunter),
          log share of the day's comments, lm (honest), n_day (line-up size), within-day ranks of n_c and lm.
Scorers   LM only; comment count only (n_c, LM breaks ties); combiner = LightGBM lambdarank and ridge (on log1p
          features, target = within-day relevance), month-forward: trained on all earlier months' days, scored on the
          month (first month only trains).
Metrics   daily top 3/5/10 overlap (as early_forecast.py), within-day Spearman; 95% day-bootstrap CIs; paired
          differences vs LM only.
usage: python comment_forecast.py -> results/comment_forecast.json + results/comment_forecast.md"""
import glob, gzip, json, os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
B = "gs://usersim-bakeoff-347838016394/usersim_sim"
WORK = os.environ.get("CF_WORK", "/tmp/cf")
COVER = float(os.environ.get("COVER", "0.8"))
CUTS = [1, 2, 3, 4]
LMF = ["lm", "r_lm", "n_day"]
FEATS = ["n_c", "n_top", "n_rep", "n_team", "u_out", "u_ver", "u_prom", "u_prior", "u_tie", "sh_c", "lm", "n_day", "r_c", "r_lm"]


def fetch():
    os.makedirs(WORK, exist_ok=True)
    for f in ("page1", "page1b", "page1c", "page2"):
        p = f"{WORK}/{f}.jsonl.gz"
        if not os.path.exists(p):
            os.system(f"gsutil -q cp {B}/raw/ph_predict_data/comments/{f}.jsonl.gz {p}")
    p = f"{WORK}/honest_preds.parquet"
    if not os.path.exists(p):
        os.system(f"gsutil -q cp {B}/tmp/e5/honest/honest_preds.parquet {p}")


def load_comments():
    import ph_comments as C
    rows, fetched = [], set()
    for f in ("page1", "page1b", "page1c", "page2"):
        for line in gzip.open(f"{WORK}/{f}.jsonl.gz"):
            x = json.loads(line)
            try:
                info, rr = C.parse(json.loads(x["html"]))
            except Exception:
                continue
            if not info["slug"]:
                continue
            fetched.add(info["slug"])
            for r in rr:
                rows.append((info["slug"], r["comment_id"], (r["username"] or "").lower(), r["created"], r["depth"],
                             bool(r["verified"]), bool(r["prominent"])))
    K = pd.DataFrame(rows, columns=["slug", "cid", "user", "created", "depth", "ver", "prom"]).drop_duplicates("cid")
    K["ts"] = pd.to_datetime(K.created, utc=True, errors="coerce")
    return K.dropna(subset=["ts"]), fetched


def build():
    from pipeline import warehouse as W
    fetch()
    K, fetched = load_comments()
    L = W.query("SELECT CAST(id AS VARCHAR) id, slug, day, daily_rank, makers, poster FROM launches WHERE daily_rank IS NOT NULL", do_sync=False)
    H = pd.read_parquet(f"{WORK}/honest_preds.parquet")[["id", "honest"]]; H["id"] = H.id.astype(str)
    L = L.merge(H, on="id", how="left")
    L["team"] = [set(json.loads(m) if m and m.startswith("[") else []) | ({p.lower()} if p else set()) for m, p in zip(L.makers, L.poster)]
    L["team"] = [{u.lower() for u in t if u} for t in L.team]
    L["inC"] = L.slug.isin(fetched)
    cov = L.groupby("day").agg(n=("id", "size"), inC=("inC", "mean"), hon=("honest", lambda s: s.notna().mean()))
    days = sorted(cov[(cov.inC >= COVER) & (cov.hon >= COVER)].index)
    stats = {"days_with_any_comment_dump": int((cov.inC > 0).sum()), "days_cover_ok": len(days),
             "day_range": [days[0], days[-1]] if days else None, "comments": int(len(K)), "launch_pages": len(fetched),
             "cover_rule": f">= {COVER} of the ranked line-up in the comment dump and with an honest prediction"}
    # day start = 00:00 PT of the launch day
    L["t0"] = [pd.Timestamp(d + " 00:00", tz="America/Los_Angeles").tz_convert("UTC") for d in L.day]
    K = K.merge(L[["slug", "id", "day", "t0", "team"]], on="slug")
    K["is_team"] = [u in t for u, t in zip(K.user, K.team)]
    # prior activity / ties: first-comment time per user, and per (user, maker) earliest commented-on time
    first = K.groupby("user").ts.min()
    TIE = {}   # user -> {maker: earliest time the user commented on one of that maker's launches}
    for u, t, ts, it in zip(K.user, K.team, K.ts, K.is_team):
        if it or not u:
            continue
        d_ = TIE.setdefault(u, {})
        for m in t:
            if m not in d_ or ts < d_[m]:
                d_[m] = ts
    X = []
    LL = L[L.day.isin(days)]
    Kd = {k: g for k, g in K[K.day.isin(days)].groupby("id")}
    for h in CUTS:
        for r in LL.itertuples():
            T = r.t0 + pd.Timedelta(hours=h)
            g = Kd.get(r.id)
            g = g[g.ts <= T] if g is not None else K.iloc[:0]
            out = g[~g.is_team]; us = out.user.unique()
            tie = sum(1 for u in us if any(ts < r.t0 for m, ts in TIE.get(u, {}).items() if m in r.team))
            X.append({"cut": h, "day": r.day, "id": r.id, "rank": r.daily_rank, "lm": r.honest,
                      "n_c": len(g), "n_top": int((g.depth == 0).sum()), "n_rep": int((g.depth > 0).sum()),
                      "n_team": int(g.is_team.sum()), "u_out": len(us),
                      "u_ver": int(out.drop_duplicates("user").ver.sum()), "u_prom": int(out.drop_duplicates("user").prom.sum()),
                      "u_prior": int(sum(first.get(u, T) < r.t0 for u in us)), "u_tie": tie})
    X = pd.DataFrame(X).dropna(subset=["lm"])
    X["n_day"] = X.groupby(["cut", "day"]).id.transform("size")
    X["sh_c"] = np.log((X.n_c + 0.5) / X.groupby(["cut", "day"]).n_c.transform(lambda s: (s + 0.5).sum()))
    X["r_c"] = X.groupby(["cut", "day"]).n_c.rank(pct=True)
    X["r_lm"] = X.groupby(["cut", "day"]).lm.rank(pct=True)
    return X, stats


def topk(g, col, k):
    return len(set(g.nlargest(k, col).id) & set(g.nsmallest(k, "rank").id)) / k * 100


def score_days(X, col):
    from scipy.stats import spearmanr
    out = {}
    for d, g in X.groupby("day"):
        out[d] = [topk(g, col, 3), topk(g, col, 5), topk(g, col, 10), spearmanr(g[col], -g["rank"]).correlation * 100]
    return pd.DataFrame(out, index=["top3", "top5", "top10", "spearman"]).T


def forward(X, kind, feats=None):
    """month-forward scores for one cut."""
    feats = feats or FEATS
    import lightgbm as lgb
    from sklearn.linear_model import Ridge
    X = X.sort_values(["day", "id"]).copy(); X["mon"] = X.day.str[:7]
    F = X[feats].copy()
    for c in ("n_c", "n_top", "n_rep", "n_team", "u_out", "u_ver", "u_prom", "u_prior", "u_tie", "n_day"):
        if c in F:
            F[c] = np.log1p(F[c])
    X["rel"] = np.clip(31 - X["rank"], 0, 30).astype(int)   # top-30 graded relevance
    X["y"] = -np.log(X["rank"])
    X["pred"] = np.nan
    mons = sorted(X.mon.unique())
    for m in mons[1:]:
        tr, te = X.mon < m, X.mon == m
        if kind == "lgb":
            Xt = X[tr]; grp = Xt.groupby("day", sort=False).size().loc[Xt.day.unique()].values
            mdl = lgb.LGBMRanker(n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=20,
                                 subsample=0.8, subsample_freq=1, colsample_bytree=0.8, verbose=-1, random_state=0)
            mdl.fit(F[tr], Xt.rel, group=grp)
            X.loc[te, "pred"] = mdl.predict(F[te])
        else:
            mu, sd = F[tr].mean(), F[tr].std() + 1e-9
            mdl = Ridge(alpha=10.0).fit((F[tr] - mu) / sd, X.y[tr])
            X.loc[te, "pred"] = mdl.predict((F[te] - mu) / sd)
    return X.dropna(subset=["pred"])


def boot(D, rng, B_=2000):
    v = D.values; n = len(v)
    bs = np.array([v[rng.integers(0, n, n)].mean(0) for _ in range(B_)])
    return [[round(float(v[:, j].mean()), 1), round(float(np.percentile(bs[:, j], 2.5)), 1), round(float(np.percentile(bs[:, j], 97.5)), 1)] for j in range(v.shape[1])]


def main():
    rng = np.random.default_rng(0)
    X, stats = build()
    X.to_parquet(f"{WORK}/cf_rows.parquet")
    res = {"stats": stats, "cuts": {}}
    md = ["# Pre-reveal forecast from comments (hours 0-4 PT), backtest", "",
          f"Days: {stats['days_cover_ok']} launch days ({stats['day_range'][0]} to {stats['day_range'][1]}) with >= {COVER:.0%} of the "
          f"ranked line-up in the comment dump and an honest pre-launch LM prediction; {stats['comments']:,} comments on "
          f"{stats['launch_pages']:,} launch pages. Scored months: all but the first (month-forward training).", "",
          "| cut (PT) | scorer | top 3 | top 5 | top 10 | Spearman | days |", "|---|---|---|---|---|---|---|"]
    for h in CUTS:
        Xh = X[X.cut == h].copy()
        Xh["cnt"] = Xh.n_c + 1e-6 * Xh.lm
        P = {"lgb": forward(Xh, "lgb"), "ridge": forward(Xh, "ridge"), "ridge_lm": forward(Xh, "ridge", LMF),
             "ridge_noflags": forward(Xh, "ridge", [f for f in FEATS if f not in ("u_ver", "u_prom")])}
        days = sorted(P["lgb"].day.unique())
        S = Xh[Xh.day.isin(days)]
        tabs = {"LM only": score_days(S, "lm"), "comment count only": score_days(S, "cnt"),
                "combiner (LightGBM)": score_days(P["lgb"], "pred"), "combiner (ridge)": score_days(P["ridge"], "pred"),
                "ablation: ridge, LM features only": score_days(P["ridge_lm"], "pred"),
                "ablation: ridge, no account flags": score_days(P["ridge_noflags"], "pred")}
        r = {"days": len(days)}
        base = tabs["LM only"]
        for nm, D in tabs.items():
            D = D.loc[days]
            r[nm] = dict(zip(["top3", "top5", "top10", "spearman"], boot(D, rng)))
            if nm != "LM only":
                r[nm + " - LM"] = dict(zip(["top3", "top5", "top10", "spearman"], boot(D - base.loc[days], rng)))
            c = r[nm]
            md.append(f"| 00:00+{h}h | {nm} | " + " | ".join(f"{c[k][0]:.1f} [{c[k][1]:.0f}, {c[k][2]:.0f}]" for k in ("top3", "top5", "top10", "spearman")) + f" | {len(days)} |")
            if nm != "LM only":
                c = r[nm + " - LM"]
                md.append(f"| | _minus LM_ | " + " | ".join(f"{c[k][0]:+.1f} [{c[k][1]:+.0f}, {c[k][2]:+.0f}]" for k in ("top3", "top5", "top10", "spearman")) + " | |")
        res["cuts"][f"+{h}h"] = r
    # descriptive: how many comments exist by each cut
    d = X.groupby("cut").agg(c_mean=("n_c", "mean"), zero=("n_c", lambda s: (s == 0).mean()))
    res["comments_by_cut"] = {f"+{k}h": {"mean_per_launch": round(float(v.c_mean), 2), "share_zero": round(float(v.zero), 3)} for k, v in d.iterrows()}
    md += ["", "Comments per launch by cut: " + "; ".join(f"+{k}h mean {v.c_mean:.1f}, {v.zero:.0%} with none" for k, v in d.iterrows()), "",
           "Leak checks: features use created_at <= T only; comment votes and follower counts (final-time) are not used; "
           "featured_at is not used; account verified/prominent flags are fetch-time (mild late read; u_ver/u_prom). "
           "Source limit: the page query returns the top 50 threads by votes (page2 = 51-100 for some), so early "
           "low-vote threads on very busy launches can be missing (counts biased low for those, not leaky).",
           "LM = honest pre-launch OOF prediction (the 00:05 live LM only exists from Oct 25)."]
    json.dump(res, open(os.path.join(HERE, "results", "comment_forecast.json"), "w"), indent=1)
    open(os.path.join(HERE, "results", "comment_forecast.md"), "w").write("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    main()
