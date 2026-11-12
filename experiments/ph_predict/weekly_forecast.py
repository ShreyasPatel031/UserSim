"""Weekly north star (orchestrator 21:25Z Nov 11): forecast PH's final weekly top 3/5/10 at the end of each launch day.

Definition (checked on the warehouse): truth = the official weekly_rank field; it is close to final-vote order (within-week Spearman
with votes 0.99) over Monday 00:00 - Sunday 23:59 PT weeks (W-SUN periods fit best: fewest duplicate ranks); the
competitors are the week's daily-ranked launches (max weekly_rank ~= launches in our table per week). Complete weeks:
those with 7 launch days in the table.

Forecast at the end of day k (k = 1 Mon .. 7 Sun, 23:59 PT) for the launches of days 1..k, inputs as known then:
  final daily rank (fixed at the day's end), day of week, the day's line-up size, the honest pre-launch LM (OOF; Mar-Oct
  only), comments created by the day's end (page dump, created_at <= 23:59 PT of the launch day; days with dump cover),
  for launches of earlier days also their day of week (=age). No final votes (they include post-day growth).
  Day-end votes are dated only from Oct 31 (warehouse vote_snapshots), so they are a separate small check.
Scorers  (b) daily rank + day-of-week: expected log final votes by (daily rank, day of week) from earlier months
         (c) ridge on [log daily rank, dow one-hot, log line-up size, lm, log1p comments by day end, log1p unique
             commenters], month-forward; LightGBM lambdarank on the same, month-forward
         (a) day-end votes: only the week of Nov 2-8 (+ partial Nov 9-15), reported separately
Metrics  at each k: overlap of the predicted top-k (k = 3/5/10, among launched) with (i) the final weekly top-k among
         launched-so-far, (ii) the final weekly top-k of the whole week (the end-of-week call is k = 7); week-bootstrap CIs.
usage: python weekly_forecast.py -> results/weekly_forecast.json + results/weekly_forecast.md"""
import json, os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
WORK = os.environ.get("CF_WORK", "/tmp/cf")
DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def load():
    from pipeline import warehouse as W
    import comment_forecast as CF
    L = W.query("SELECT CAST(id AS VARCHAR) id, slug, day, daily_rank, weekly_rank, votes, makers, poster FROM launches WHERE daily_rank IS NOT NULL", do_sync=False)
    L["d"] = pd.to_datetime(L.day); L["wk"] = L.d.dt.to_period("W-SUN").astype(str); L["dow"] = L.d.dt.dayofweek
    nd = L.groupby("wk").day.nunique(); L = L[L.wk.map(nd) == 7].copy()
    L["n_day"] = L.groupby("day").id.transform("size")
    CF.fetch()
    H = pd.read_parquet(f"{CF.WORK}/honest_preds.parquet")[["id", "honest"]]; H["id"] = H.id.astype(str)
    L = L.merge(H, on="id", how="left")
    K, fetched = CF.load_comments()
    K = K.merge(L[["slug", "day", "makers", "poster"]], on="slug")
    end = {d: pd.Timestamp(d + " 23:59:59", tz="America/Los_Angeles").tz_convert("UTC") for d in L.day.unique()}
    K = K[K.ts <= K.day.map(end)]
    team = {sl: {u.lower() for u in (json.loads(m) if m and m.startswith("[") else []) + ([p] if p else []) if u} for sl, m, p in zip(L.slug, L.makers, L.poster)}
    K["out"] = [u not in team.get(s, ()) for u, s in zip(K.user, K.slug)]
    g = K.groupby("slug").agg(c_end=("cid", "size"), u_end=("user", lambda s: s.nunique()))
    L = L.join(g, on="slug"); L["inC"] = L.slug.isin(fetched)
    L["c_end"] = L.c_end.fillna(0); L["u_end"] = L.u_end.fillna(0)
    return L


def feats(X):
    F = pd.DataFrame({"ldr": np.log(X.daily_rank), "lnd": np.log(X.n_day), "lm": X.honest.fillna(X.honest.median()),
                      "lm_na": X.honest.isna().astype(float), "lc": np.log1p(X.c_end), "lu": np.log1p(X.u_end)}, index=X.index)
    for i in range(7):
        F[f"dow{i}"] = (X.dow == i).astype(float)
    return F


def score_all(L):
    import lightgbm as lgb
    from sklearn.linear_model import Ridge
    L = L.copy(); L["mon"] = L.wk.str[:7]   # month of the week's Monday
    L["y"] = np.log1p(L.votes); L["pb"] = np.nan; L["pr"] = np.nan; L["pl"] = np.nan
    mons = sorted(L.mon.unique()); F = feats(L)
    for m in mons[1:]:
        tr, te = L.mon < m, L.mon == m
        # (b) expected log final votes by (daily rank capped at 30, dow), shrunk to the rank-only mean
        T = L[tr].assign(r=L.daily_rank.clip(upper=30))
        a = T.groupby("r").y.mean(); b = T.groupby(["r", "dow"]).y.agg(["mean", "size"])
        b["e"] = (b["mean"] * b["size"] + 10 * a.reindex(b.index.get_level_values(0)).values) / (b["size"] + 10)
        r = L.loc[te, "daily_rank"].clip(upper=30)
        L.loc[te, "pb"] = [b.e.get((ri, di), a.get(ri, a.min())) for ri, di in zip(r, L.loc[te, "dow"])]
        mu, sd = F[tr].mean(), F[tr].std() + 1e-9
        L.loc[te, "pr"] = Ridge(alpha=3.0).fit((F[tr] - mu) / sd, L.y[tr]).predict((F[te] - mu) / sd)
        Xt = L[tr].sort_values("wk"); grp = Xt.groupby("wk", sort=False).size().values
        rel = np.clip(31 - Xt.weekly_rank, 0, 30).astype(int)
        mdl = lgb.LGBMRanker(n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=20, subsample=0.8,
                             subsample_freq=1, colsample_bytree=0.8, verbose=-1, random_state=0)
        mdl.fit(F.loc[Xt.index], rel, group=grp)
        L.loc[te, "pl"] = mdl.predict(F[te])
    return L.dropna(subset=["pb"])


def evalk(L, cols):
    """per week x day-k x scorer: [launched-only top3/5/10, whole-week top3/5/10]."""
    out = []
    for w, g in L.groupby("wk"):
        full = {k: set(g.nsmallest(k, "weekly_rank").id) for k in (3, 5, 10)}
        for kd in range(7):
            s = g[g.dow <= kd]
            sub = {k: set(s.nsmallest(k, "weekly_rank").id) for k in (3, 5, 10)}
            for nm, c in cols.items():
                p = {k: set(s.nlargest(k, c).id) for k in (3, 5, 10)}
                out.append({"wk": w, "k": kd, "scorer": nm, **{f"l{k}": len(p[k] & sub[k]) / k * 100 for k in (3, 5, 10)},
                            **{f"w{k}": len(p[k] & full[k]) / k * 100 for k in (3, 5, 10)},
                            **{f"reach{k}": len(full[k] & set(s.id)) / k * 100 for k in (3, 5, 10)}})
    return pd.DataFrame(out)


def boot(D, cols, rng, B_=2000):
    W_ = D.groupby("wk")[cols].mean(); v = W_.values; n = len(v)
    bs = np.array([v[rng.integers(0, n, n)].mean(0) for _ in range(B_)])
    return {c: [round(float(v[:, j].mean()), 1), round(float(np.percentile(bs[:, j], 2.5)), 1), round(float(np.percentile(bs[:, j], 97.5)), 1)] for j, c in enumerate(cols)}


def dayend_check(L):
    """(a) day-end votes from vote_snapshots (hourly, from Oct 31): latest snapshot at or before 23:59 PT of the launch day."""
    from pipeline import warehouse as W
    V = W.query('SELECT "day" AS d, "at" AS at, CAST(launch_id AS VARCHAR) id, votes FROM vote_snapshots', do_sync=False)
    V["at"] = pd.to_datetime(V["at"], utc=True)
    V["end"] = [pd.Timestamp(d + " 23:59:59", tz="America/Los_Angeles").tz_convert("UTC") for d in V.d]
    E = V[V["at"] <= V["end"]].sort_values("at").groupby("id").votes.last()
    X = L[L.id.isin(E.index)].copy(); X["v_end"] = X.id.map(E)
    X["ve"] = X.v_end + 1e-6 * (31 - X.daily_rank)
    X["fv"] = X.votes.astype(float)
    return X


def main():
    rng = np.random.default_rng(0)
    L = load()
    nweeks = int(L.wk.nunique())
    S = score_all(L)
    cols = {"(b) daily rank + day of week": "pb", "(c) ridge": "pr", "(c) LightGBM": "pl"}
    S["neg_dr"] = -S.daily_rank + 1e-6 * S.dow   # plain daily rank, ties broken by later day
    cols["daily rank only"] = "neg_dr"
    E = evalk(S, cols)
    res = {"definition": "truth = PH's official weekly_rank field (Mon 00:00 - Sun 23:59 PT); close to but NOT pure final-vote order (orchestrator 09:27Z Nov 12: final votes reproduce 3/4/10 of the official top 3/5/10 in Nov 2-8)",
           "complete_weeks": nweeks, "scored_weeks": int(S.wk.nunique()), "scored_range": [S.wk.min(), S.wk.max()], "table": {}}
    md = ["# Weekly forecast (PH weekly top 3/5/10), backtest", "",
          f"Truth = Product Hunt's official weekly_rank field (all scores below use it), weeks Monday 00:00 - Sunday 23:59 PT. It is close to, but not exactly, the order of final votes "
          f"(within-week Spearman of weekly_rank with final votes 0.99; W-SUN boundaries fit best). Complete weeks held: {nweeks} "
          f"(Jan 5 - Nov 8). Scored month-forward: {res['scored_weeks']} weeks ({S.wk.min()[:10]} .. {S.wk.max()[-10:]}).", "",
          "Inputs at the end of day k (23:59 PT): final daily rank (fixed at day end), day of week, line-up size, honest pre-launch "
          "LM (OOF, Mar-Oct; median-filled before), comments and unique commenters created by the launch day's end. No final votes.", "",
          "## End-of-week call (Sunday 23:59 PT), vs final weekly top k", "",
          "| scorer | top 3 | top 5 | top 10 |", "|---|---|---|---|"]
    for nm in cols:
        b = boot(E[(E.k == 6) & (E.scorer == nm)], ["w3", "w5", "w10"], rng)
        res["table"][f"end_of_week | {nm}"] = b
        md.append(f"| {nm} | " + " | ".join(f"{b[c][0]:.1f} [{b[c][1]:.0f}, {b[c][2]:.0f}]" for c in ("w3", "w5", "w10")) + " |")
    md += ["", "## By day of the week: (i) vs final weekly top k among launches so far; (ii) vs the whole week's final top k; "
           "(reach = share of the whole week's top k already launched)", "",
           "| end of | scorer | (i) top 3 / 5 / 10 | (ii) top 3 / 5 / 10 | reach 3 / 5 / 10 |", "|---|---|---|---|---|"]
    for kd in range(7):
        for nm in ("(b) daily rank + day of week", "(c) ridge"):
            D = E[(E.k == kd) & (E.scorer == nm)]
            b = boot(D, ["l3", "l5", "l10", "w3", "w5", "w10", "reach3", "reach5", "reach10"], rng, 500)
            res["table"][f"day{kd + 1} | {nm}"] = b
            md.append(f"| {DOW[kd]} | {nm} | " + " / ".join(f"{b[c][0]:.0f}" for c in ("l3", "l5", "l10")) + " | "
                      + " / ".join(f"{b[c][0]:.0f}" for c in ("w3", "w5", "w10")) + " | " + " / ".join(f"{b[c][0]:.0f}" for c in ("reach3", "reach5", "reach10")) + " |")
    # paired: ridge - (b) at end of week
    a = E[(E.k == 6) & (E.scorer == "(c) ridge")].set_index("wk")[["w3", "w5", "w10"]]
    bb = E[(E.k == 6) & (E.scorer == "(b) daily rank + day of week")].set_index("wk")[["w3", "w5", "w10"]]
    d = boot((a - bb).reset_index(), ["w3", "w5", "w10"], rng)
    res["table"]["end_of_week | ridge - (b)"] = d
    md += ["", "Paired, end of week, ridge - (b): " + ", ".join(f"top {c[1:]} {d[c][0]:+.1f} [{d[c][1]:+.0f}, {d[c][2]:+.0f}]" for c in ("w3", "w5", "w10"))]
    # (a) day-end votes, small
    X = dayend_check(L)
    md += ["", "## (a) Day-end votes (dated only from Oct 31; vote_snapshots)", ""]
    for w, g in X.groupby("wk"):
        full = g.weekly_rank
        r = {}
        for nm, c in (("day-end votes", "ve"), ("daily rank", None), ("final votes (oracle)", "fv")):
            sc = g[c] if c else -g.daily_rank + 1e-6 * g.dow
            r[nm] = [len(set(g.loc[sc.nlargest(k).index].id) & set(g.nsmallest(k, "weekly_rank").id)) / k * 100 for k in (3, 5, 10)]
        md.append(f"- week {w} ({g.day.nunique()} days, {len(g)} launches): " + "; ".join(f"{k} {v[0]:.0f}/{v[1]:.0f}/{v[2]:.0f}" for k, v in r.items()))
        res["table"][f"dayend | {w}"] = r
    json.dump(res, open(os.path.join(HERE, "results", "weekly_forecast.json"), "w"), indent=1)
    open(os.path.join(HERE, "results", "weekly_forecast.md"), "w").write("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    main()
