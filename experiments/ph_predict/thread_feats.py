"""Rank-neutral maker identity from the launch thread (E5 / orchestrator 09:20Z Nov 12), backtest over the clean 00:05 LM.
Our API reads name a launch's makers fully only for the first post of a page, so maker identity from the API list is
leaky; the thread is not: the maker's intro (earliest top-level comment, usually posted before launch) exists for most
launches at 00:05, whatever their final rank. Features as of 00:05 PT of the launch day (comments created <= 00:05):
  th_has_first     an earliest top-level comment exists
  th_hunter_first  its author is the hunter (warehouse poster; the API never redacts the hunter)
  th_n_pre         distinct non-hunter authors of comments created before 00:05 (pre-launch comments are the team's)
  th_fa_n / th_fa_rel  the first author's earlier launches as first top-level commenter or hunter, strictly before the
                   day (count; smoothed mean within-day percentile of final rank, higher = better)
Stage 2: ridge month-forward on [clean LM (honest_preds_v2 OOF), its within-day rank, line-up size] + thread features,
target -log(daily rank); vs the same ridge without thread features and vs the clean LM alone. Paired day bootstrap.
Dump caveat: the thread dumps hold the top 20 top-level threads by votes, read after the day.
usage: python thread_feats.py -> results/thread_feats.md + .json"""
import json, os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
os.environ.setdefault("CF_WORK", "/tmp/claude-0/-home-user-UserSim/94f4f0ff-5cdc-5cbe-bb94-5c0d76cd2a8c/scratchpad/cmt_v2")
import comment_forecast as CF


def topk(g, col, k):
    return len(set(g.nlargest(k, col).id) & set(g.nsmallest(k, "rank").id)) / k * 100


def main():
    from pipeline import warehouse as W
    from sklearn.linear_model import Ridge
    rng = np.random.default_rng(0)
    K, fetched = CF.load_comments()
    L = W.query("SELECT CAST(id AS VARCHAR) id, slug, day, daily_rank, poster FROM launches WHERE daily_rank IS NOT NULL", do_sync=False)
    H = pd.read_parquet(os.path.join(HERE, "results", "honest_preds_v2.parquet"))[["id", "honest"]]; H["id"] = H.id.astype(str)
    L = L.merge(H, on="id", how="left"); L["poster"] = L.poster.fillna("").str.lower()
    L["t5"] = [pd.Timestamp(d + " 00:05", tz="America/Los_Angeles").tz_convert("UTC") for d in L.day]
    K = K.merge(L[["slug", "id", "day", "t5", "poster"]], on="slug")
    K = K[K.ts <= K.t5]   # as of 00:05 PT
    first = K[K.depth == 0].sort_values("ts").groupby("id").first()
    pre = K[K.user != K.poster].groupby("id").user.nunique()
    L["th_has_first"] = L.id.isin(first.index).astype(float)
    L["fa"] = L.id.map(first.user)
    L["th_hunter_first"] = ((L.fa == L.poster) & L.fa.notna()).astype(float)
    L["th_n_pre"] = L.id.map(pre).fillna(0)
    # first-author history: earlier launches where that person was the first top-level commenter or the hunter
    L["rp"] = L.groupby("day").daily_rank.rank(pct=True, ascending=False)
    ev = pd.concat([L[["fa", "day", "rp"]].rename(columns={"fa": "u"}), L[["poster", "day", "rp"]].rename(columns={"poster": "u"})]).dropna()
    ev = ev[ev.u != ""].drop_duplicates()
    hist = {u: g.sort_values("day")[["day", "rp"]].values for u, g in ev.groupby("u")}
    fn, fr = [], []
    for u, d in zip(L.fa, L.day):
        h = hist.get(u) if isinstance(u, str) and u else None
        if h is None:
            fn.append(0); fr.append(np.nan); continue
        prev = h[h[:, 0] < d]
        fn.append(len(prev)); fr.append((prev[:, 1].astype(float).sum() + 0.5 * 2) / (len(prev) + 2) if len(prev) else np.nan)
    L["th_fa_n"] = np.log1p(fn); L["th_fa_rel"] = fr
    L["inC"] = L.slug.isin(fetched)
    cov = L.groupby("day").agg(inC=("inC", "mean"), hon=("honest", lambda s: s.notna().mean()))
    days = sorted(cov[(cov.inC >= 0.8) & (cov.hon >= 0.8)].index)
    X = L[L.day.isin(days) & L.honest.notna()].copy(); X["rank"] = X.daily_rank
    X["lm_r"] = X.groupby("day").honest.rank(pct=True); X["n_day"] = np.log(X.groupby("day").id.transform("size"))
    X["th_fa_rel"] = X.th_fa_rel.fillna(0.5)
    TH = ["th_has_first", "th_hunter_first", "th_n_pre", "th_fa_n", "th_fa_rel"]
    BASE = ["honest", "lm_r", "n_day"]
    X["mon"] = X.day.str[:7]; X["y"] = -np.log(X["rank"])
    for nm, F in (("ridge_lm", BASE), ("ridge_lm_thread", BASE + TH)):
        X[nm] = np.nan
        for m in sorted(X.mon.unique())[1:]:
            tr, te = X.mon < m, X.mon == m
            mu, sd = X.loc[tr, F].mean(), X.loc[tr, F].std() + 1e-9
            X.loc[te, nm] = Ridge(alpha=3.0).fit((X.loc[tr, F] - mu) / sd, X.y[tr]).predict((X.loc[te, F] - mu) / sd)
    S = X.dropna(subset=["ridge_lm_thread"])
    def per_day(col):
        out = {}
        for d, g in S.groupby("day"):
            o = g.sort_values(col, ascending=False).id.tolist(); t = g.sort_values("rank").id.tolist()
            out[d] = [topk(g, col, 3), topk(g, col, 5), topk(g, col, 10), float(o[0] in set(t[:3])) * 100, float(o[0] == t[0]) * 100]
        return pd.DataFrame(out, index=["top3", "top5", "top10", "p1", "exact"]).T
    P = {c: per_day(c) for c in ("honest", "ridge_lm", "ridge_lm_thread")}
    def boot(v):
        v = np.asarray(v, float); b = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(4000)]
        return f"{v.mean():+.1f} [{np.percentile(b, 2.5):+.1f}, {np.percentile(b, 97.5):+.1f}]"
    by_grp = X.assign(g=np.select([X["rank"] == 1, X["rank"] <= 3, X["rank"] <= 10], ["#1", "#2-3", "#4-10"], "11+")).groupby("g")[TH].mean().round(3)
    md = [f"# Thread-position maker features over the clean LM ({S.day.nunique()} days, month-forward ridge)", "",
          "Feature means by final rank group (rank-neutral if flat):", "", by_grp.to_string(), "",
          "| scorer | top 3 | top 5 | top 10 | #1 in top 3 | exact winner |", "|---|---|---|---|---|---|"]
    for c, nm in (("honest", "clean LM alone"), ("ridge_lm", "ridge on LM features"), ("ridge_lm_thread", "ridge + thread features")):
        md.append(f"| {nm} | " + " | ".join(f"{P[c][k].mean():.1f}" for k in ("top3", "top5", "top10", "p1", "exact")) + " |")
    md += ["", "Thread minus LM-only ridge (paired day bootstrap): " + ", ".join(f"{k} {boot(P['ridge_lm_thread'][k] - P['ridge_lm'][k])}" for k in ("top3", "top5", "top10", "p1", "exact"))]
    # live model: the same ridge fitted on every backtest day (results/thread_live_model.json)
    F = BASE + TH; mu, sd = X[F].mean(), X[F].std() + 1e-9
    m = Ridge(alpha=3.0).fit((X[F] - mu) / sd, X.y)
    json.dump({"feats": F, "mu": mu.to_dict(), "sd": sd.to_dict(), "coef": dict(zip(F, map(float, m.coef_))), "intercept": float(m.intercept_),
               "days": int(X.day.nunique()), "honest": "honest_preds_v2 (clean_v3 OOF); live: shadow pred_clean"},
              open(os.path.join(HERE, "results", "thread_live_model.json"), "w"), indent=1)
    # orchestrator 08:29Z Nov 12 (stack): within-day z of every input and of the target -log(rank), ridge alpha 10, month-forward;
    # inputs known at 00:05 only: clean LM + thread (clean_thread_z) and + slug_num_l (clean_stack; productLinks / media wait for the 00:05 read)
    import re
    def slug_num(s):
        m = re.search(r"-(\d+)$", re.sub(r"-[0-9a-f]{8,}$", "", str(s)))
        return float(np.log(np.clip(int(m.group(1)), 1, 50))) if m else 1.0
    X["slug_num_l"] = X.slug.map(slug_num)
    zd = lambda c: X.groupby("day")[c].transform(lambda s: (s - s.mean()) / s.std() if s.std() > 0 else s * 0.0)
    ZF = {"clean_thread_z": ["honest"] + TH, "clean_stack": ["honest"] + TH + ["slug_num_l"]}
    for f in set(sum(ZF.values(), [])):
        X["z_" + f] = zd(f)
    X["z_y"] = zd("y")
    for nm, F in ZF.items():
        Fz = ["z_" + f for f in F]; X[nm] = np.nan
        for m in sorted(X.mon.unique())[1:]:
            tr, te = X.mon < m, X.mon == m
            X.loc[te, nm] = Ridge(alpha=10.0).fit(X.loc[tr, Fz], X.z_y[tr]).predict(X.loc[te, Fz])
    S = X.dropna(subset=["ridge_lm_thread"])
    for c in ZF:
        P[c] = per_day(c)
    md += ["", "## Within-day z, alpha 10 (orchestrator stack method)", "", "| scorer | top 3 | top 5 | top 10 | #1 in top 3 | exact winner |", "|---|---|---|---|---|---|"]
    for c in ("honest", *ZF):
        md.append(f"| {c} | " + " | ".join(f"{P[c][k].mean():.1f}" for k in ("top3", "top5", "top10", "p1", "exact")) + " |")
    for c in ZF:
        md.append(f"{c} minus clean LM alone (paired day bootstrap): " + ", ".join(f"{k} {boot(P[c][k] - P['honest'][k])}" for k in ("top3", "top5", "top10", "p1")))
    zm = {}
    for nm, F in ZF.items():
        r = Ridge(alpha=10.0).fit(X[["z_" + f for f in F]], X.z_y)
        zm[nm] = {"feats": F, "coef": dict(zip(F, map(float, r.coef_)))}
    json.dump({"score": "sum(coef[f] * z_f), z_f = (x - mean_day(x)) / std_day(x) over the line-up (0 if std 0); rank by score desc",
               "days": int(X.day.nunique()), "models": zm}, open(os.path.join(HERE, "results", "thread_live_model_z.json"), "w"), indent=1)
    open(os.path.join(HERE, "results", "thread_feats.md"), "w").write("\n".join(md) + "\n")
    json.dump({c: P[c].mean().round(2).to_dict() for c in P}, open(os.path.join(HERE, "results", "thread_feats.json"), "w"), indent=1)
    print("\n".join(md))


if __name__ == "__main__":
    main()
