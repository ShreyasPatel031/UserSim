"""Predict the launch-day shock before launch (E0 found 90% of the simulation's error is a per-launch shock).
Target: shock = log((R + 1) / (S + 1)) with the day's mean removed, where S is the simulation's expected pool picks
(popscore per-day files, out of sample) and R the real pool voters on launch day.
Inputs, all known before launch:
  launch-model inputs (build_cached, model.LIVE_SOURCES + PAGE_SOURCES), grouped by prefix: ph (audience counts),
  hist (track record), promo (pre-launch promotion), fol / seg (pool follows / segments of followers; undated), x, txt,
  topic, llm, comp, ps / vs / pf (page), ...
  turnout (new, launch level, from store events before the day): for the makers' and the hunter's earlier launches, the
  share of earlier backers who came back to each next launch (mk / hu), the number of distinct past backers, and how
  many of those past backers were active in the 30 days before (the reachable base).
Stage 1: LightGBM on the shock, rolling monthly (train on earlier months from Apr), 3 seeds -> shock_hat for May-Oct.
  Reported: within-day Spearman and R^2 of shock_hat vs the real shock; drop-one-group ablation.
Day level (for weekly / monthly boards): the raw shock's day mean (pool turnout that day vs the simulation) predicted
  from day-level inputs known before the day (line-up size, active pool size, line-up strength by the prior, weekday),
  rolling monthly over days; raw_hat = within-day shock_hat + day-level dshock_hat.
Duplicates: 204 launches sit in two consecutive data/days files; each is kept once, on its featuredAt (PT) day.
Stage 2: launch forecast from the simulation alone (log S, day standing) with and without shock_hat, and with the true
  shock (ceiling); LightGBM on final log votes, rolling monthly. Saved for lists_score.py (daily / weekly / monthly).
usage: SIMLAB_DATA=data_v2 python -m simlab.shock_model popscore_tie -> reports/shock_model.json, ph_predict/results/shock_preds.parquet"""
import json, os, sys
from collections import defaultdict
import numpy as np, pandas as pd, lightgbm as lgb
from scipy.stats import spearmanr
from . import store

HERE = os.path.dirname(os.path.abspath(__file__)); PH = os.path.join(os.path.dirname(HERE), "ph_predict")


def turnout(I, E):
    """Launch-level turnout features from events before each launch's day."""
    I = I.assign(id=I.id.astype(str)); day = dict(zip(I.id, I.day))
    mk = {r.id: set(json.loads(r.makers)) - {""} for r in I.itertuples()}; hu = dict(zip(I.id, I.poster))
    made, hunted = defaultdict(list), defaultdict(list)
    for x in sorted(day, key=day.get):
        for m in mk[x]:
            made[m].append(x)
        if hu[x] and hu[x] not in mk[x]:
            hunted[hu[x]].append(x)
    E = E.assign(item=E.item.astype(str)); E = E[E.item.isin(day)]
    back = {it: (g.date.values, g.person.values) for it, g in E.groupby("item")}
    act = E.groupby("person").date.apply(lambda s: np.sort(s.values)).to_dict()
    out = {}
    for x in day:
        d = day[x]; r = {}
        for tag, L in (("mk", sorted({l for m in mk[x] if len(made[m]) <= 30 for l in made[m] if day[l] < d}, key=day.get)),
                       ("hu", sorted({l for l in hunted.get(hu[x], []) if day[l] < d}, key=day.get) if hu[x] and hu[x] not in mk[x] else [])):
            seen, num, den = set(), 0, 0
            for l in L:
                b = back.get(l); B = set(b[1][b[0] < d]) if b is not None else set()
                den += len(seen); num += len(B & seen); seen |= B
            cut = (pd.Timestamp(d) - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
            live = sum(1 for u in seen if (a := act.get(u)) is not None and np.searchsorted(a, cut) < np.searchsorted(a, d))
            r.update({f"turn_{tag}_rate": num / den if den else np.nan, f"turn_{tag}_backers": np.log1p(len(seen)),
                      f"turn_{tag}_live": np.log1p(live), f"turn_{tag}_launches": float(len(L))})
        out[x] = r
    return pd.DataFrame.from_dict(out, orient="index").rename_axis("id").reset_index()


def canonical_days():
    """launch id -> its Product Hunt day (featuredAt in Pacific time). 204 launches sit in two consecutive data/days files
    (the earlier file's window took in the next day's 00:00 PDT launches: Apr 27/28, May 4/5, 6/7, 10/11, 13/14)."""
    import glob
    out = {}
    for f in glob.glob(os.path.join(PH, "data", "days", "*.json")):
        for p in json.load(open(f)):
            fa = p.get("featuredAt")
            if fa:
                out[str(p["id"])] = pd.Timestamp(fa).tz_convert("America/Los_Angeles").strftime("%Y-%m-%d")
    return out


def dedupe(df, canon):
    """Keep each launch once, on its canonical day when the frame has a day column."""
    if "day" in df:
        df = df[df.day.values == df.id.map(canon).fillna(df.day).values]
    return df.drop_duplicates("id")


def fit(tr, te, cols, y, seeds=3):
    return np.mean([lgb.LGBMRegressor(n_estimators=400, learning_rate=0.03, num_leaves=15, min_child_samples=30, subsample=0.8, subsample_freq=1,
                                      colsample_bytree=0.5, random_state=s, verbose=-1, n_jobs=8).fit(tr[cols], tr[y]).predict(te[cols]) for s in range(seeds)], 0)


def main(src):
    import glob
    P, I, E = store.load()
    day = dict(zip(I.id.astype(str), I.day))
    Ev = E.assign(item=E.item.astype(str)); Ev = Ev[Ev.item.map(day) == Ev.date]
    R = Ev.groupby("item").person.nunique()
    S = pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(os.path.join(HERE, "cache", src, "day_*.parquet")))]); S["id"] = S.id.astype(str)
    canon = canonical_days(); n0 = len(S); S = dedupe(S, canon)
    S["R"] = S.id.map(R).fillna(0); S["lS"] = np.log1p(S.psn_ev)
    S["raw"] = np.log((S.R + 1) / (S.psn_ev + 1)); S["dshock"] = S.groupby("day").raw.transform("mean")
    S["shock"] = S.raw - S.dshock   # within-day shock; dshock = the day's shared level (pool turnout that day vs the simulation)
    cwd = os.getcwd(); os.chdir(PH); sys.path.insert(0, PH)
    try:
        from buildcache import build_cached
        import model as M
        B = build_cached(); B["id"] = B.id.astype(str)
        C = pd.read_parquet("results/ctrl_preds.parquet"); C["id"] = C.id.astype(str)
    finally:
        os.chdir(cwd)
    B, C = dedupe(B, canon), dedupe(C, canon)
    inputs = M.cols(B, M.LIVE_SOURCES + M.PAGE_SOURCES)
    T = turnout(I, E)
    A = S[["id", "day", "lS", "shock", "raw", "dshock", "psn_reach", "psn_ev"]].merge(C[["id", "dailyRank", "logv", "all"]], on="id").merge(B[["id"] + inputs], on="id", how="left").merge(T, on="id", how="left")
    tcols = [c for c in T if c != "id"]
    if os.environ.get("EXTRA_FEATS"):   # extra launch-level inputs (parquet: id + columns), e.g. A1 team history; one group named after the file
        X = pd.read_parquet(os.environ["EXTRA_FEATS"]); X["id"] = X.id.astype(str)
        xcols = [c for c in X if c != "id"]
        A = A.merge(X, on="id", how="left")
    groups = defaultdict(list)
    for c in inputs:
        groups[c.split("_")[0]].append(c)
    groups = {k: v for k, v in groups.items() if len(v)}
    groups["turnout"] = tcols
    allc = inputs + tcols
    if os.environ.get("EXTRA_FEATS"):
        groups["extra"] = xcols; allc = allc + xcols
    A["mon"] = A.day.str[:7]; months = sorted(A.mon.unique())
    # stage 1: shock_hat, rolling monthly
    A["shock_hat"] = np.nan; abl = {g: np.full(len(A), np.nan) for g in groups}
    for m in months[1:]:
        tr, te = A[A.mon < m], A.mon == m
        A.loc[te, "shock_hat"] = fit(tr, A[te], allc, "shock")
        for g, cs in groups.items():
            abl[g][te.values] = fit(tr, A[te], [c for c in allc if c not in set(cs)], "shock", seeds=1)
    H = A[A.shock_hat.notna()]
    sp = lambda col: float(np.nanmean([spearmanr(g[col], g.shock).correlation for _, g in H.assign(**{col: H[col]}).groupby("day") if len(g) >= 5]))
    res = {"source": src, "launches": int(len(H)), "rows_dropped_as_duplicates": int(n0 - len(S)), "months": sorted(H.mon.unique()),
           "stage1": {"spearman_within_day": round(sp("shock_hat"), 3),
                      "r2": round(float(1 - ((H.shock - H.shock_hat) ** 2).sum() / ((H.shock - H.shock.mean()) ** 2).sum()), 3)}}
    H = H.assign(**{f"abl_{g}": abl[g][A.shock_hat.notna().values] for g in groups})
    base1 = float(np.nanmean([spearmanr(g.shock_hat, g.shock).correlation for _, g in H.groupby("day") if len(g) >= 5]))
    res["stage1"]["drop_one_group_spearman_loss"] = dict(sorted({g: round(base1 - float(np.nanmean([spearmanr(gg[f"abl_{g}"], gg.shock).correlation
                                                                                                        for _, gg in H.groupby("day") if len(gg) >= 5])), 3)
                                                                  for g in groups}.items(), key=lambda kv: -kv[1]))
    res["stage1"]["group_sizes"] = {g: len(v) for g, v in groups.items()}
    # day level: the day's shared shock from day-level inputs known before the day, rolling monthly over days
    Dd = A.groupby("day").agg(dshock=("dshock", "first"), n=("id", "size"), pool=("psn_reach", "mean"), lS_mean=("lS", "mean"), lS_max=("lS", "max"),
                              prior_mean=("all", "mean"), prior_max=("all", "max"), prior_top3=("all", lambda s: np.sort(s.values)[-3:].mean())).reset_index()
    Dd["dow"] = pd.to_datetime(Dd.day).dt.dayofweek; Dd["pool"] = np.log1p(Dd.pool); Dd["n"] = np.log(Dd.n); Dd["mon"] = Dd.day.str[:7]
    dcols = ["n", "pool", "lS_mean", "lS_max", "prior_mean", "prior_max", "prior_top3", "dow"]
    Dd["dshock_hat"] = np.nan
    for m in months[1:]:
        tr = Dd[Dd.mon < m]
        Dd.loc[Dd.mon == m, "dshock_hat"] = np.mean([lgb.LGBMRegressor(n_estimators=200, learning_rate=0.03, num_leaves=7, min_child_samples=10, random_state=s,
                                                                      verbose=-1).fit(tr[dcols], tr.dshock).predict(Dd[Dd.mon == m][dcols]) for s in range(3)], 0)
    Dh = Dd[Dd.dshock_hat.notna()]
    res["day_level"] = {"days": int(len(Dh)), "spearman_dshock_hat_vs_dshock": round(float(spearmanr(Dh.dshock_hat, Dh.dshock).correlation), 3),
                        "sd_dshock": round(float(Dd.dshock.std()), 3), "sd_within_day_shock": round(float(A.shock.std()), 3)}
    A = A.merge(Dd[["day"] + dcols + ["dshock_hat"]].rename(columns={c: "day_" + c for c in dcols}), on="day", how="left")
    A["raw_hat"] = A.shock_hat + A.dshock_hat
    # stage 2: simulation-only launch forecast with / without the predicted shock, and with the true shock (ceiling)
    for c in ("lS", "shock_hat", "shock"):
        A[c + "_dayr"] = A.groupby("day")[c].rank(pct=True)
    A["lS_plus_hat"] = A.lS + A.shock_hat; A["lS_plus_true"] = A.lS + A.shock
    A["lS_plus_raw_hat"] = A.lS + A.raw_hat; A["lS_plus_raw"] = A.lS + A.raw
    dc = ["day_" + c for c in dcols]
    V = {"sim": ["lS", "lS_dayr"], "sim + predicted shock": ["lS", "lS_dayr", "shock_hat", "shock_hat_dayr", "lS_plus_hat"],
         "sim + true shock (ceiling)": ["lS", "lS_dayr", "shock", "shock_dayr", "lS_plus_true"],
         "sim + predicted shock, cross-day": ["lS", "lS_dayr", "shock_hat", "shock_hat_dayr", "lS_plus_hat", "dshock_hat", "raw_hat", "lS_plus_raw_hat"] + dc,
         "sim + true shock, cross-day (ceiling)": ["lS", "lS_dayr", "shock", "shock_dayr", "lS_plus_true", "dshock", "raw", "lS_plus_raw"] + dc}
    out = []
    for m in months[2:]:
        tr, te = A[(A.mon < m) & A.shock_hat.notna() & A.dshock_hat.notna()], A[A.mon == m].copy()
        for name, cols in V.items():
            te[name] = fit(tr, te, cols, "logv")
        te["launch model"] = te["all"]
        out.append(te)
    O = pd.concat(out)
    O[["id", "day", "dailyRank", "logv", "launch model"] + list(V) + ["shock", "shock_hat", "dshock", "dshock_hat"]].to_parquet(os.path.join(PH, "results", "shock_preds.parquet"))
    json.dump(res, open(os.path.join(HERE, "reports", "shock_model.json"), "w"), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main(sys.argv[1])
