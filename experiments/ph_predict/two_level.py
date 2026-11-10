"""Two-level simulation (docs/SIM_TWO_LEVEL_PLAN.md on claude/cool-volta-l5nuo4; orchestrator Nov 10 22:45Z).
Person level: P(complete person p upvotes launch L on day d), trained and tested only on COMPLETE people (store_v3
persons.complete), so non-votes are real negatives. Population level: launch EV = sum_p w_p * P(p, L), ranked per day.

Pieces (simlab.popscore TIE2 person model, same features as the deployed sim):
  prepare        complete people's upvote / comment events from store_v3 (person = salted id), launches from the warehouse.
                 Dating: an upvote with no vote time is dated on the launch's day and flagged (lday=True); comments use
                 their own time when exact / bounded / day quality. events_cp.parquet; events_cp_noflag.parquet drops
                 the flagged rows (sensitivity).
  train <m>      person model for month m on the previous month's rows, events dated before m-01 (honest retraining).
  day <d>        features from events dated before d only; every complete person active in the 30 days before d x the
                 day's line-up; labels attached afterwards from the full events (did p upvote L). Saves rows.
  score          person metrics (AUC, log-loss, Hit@3, voter recall@N) and population metrics (daily top 3/5/10, weekly,
                 Spearman of EV vs real votes), paired vs the deployed simulation (sim_v3_backtest wh, retrained) and
                 the launch model (forecasts table), with 95% intervals over days.
Weights (WEIGHTS env): act = popscore's activity share (deployed default); rep = act x a representativeness factor per
  activity tier so the weighted sample's vote volume per tier matches the real voter base seen on the window's launches.
Selection caveat: the complete set was pulled partly from the Oct 29-Nov 4 priority list (people who voted on those
  launches), so those days are reported apart as possibly selected (clean = Oct 20-28 and Nov 5-9).
usage: SIMBT=<dir> python two_level.py prepare | train <YYYY-MM> | day <YYYY-MM-DD> | score     (counts only)"""
import glob, json, os, shutil, subprocess, sys, tempfile
import numpy as np, pandas as pd
from scipy.stats import spearmanr

HERE = os.path.dirname(os.path.abspath(__file__)); EXP = os.path.dirname(HERE); sys.path.insert(0, EXP)
B = "gs://usersim-bakeoff-347838016394/usersim_sim"
WORK = os.environ.get("SIMBT", os.path.join(tempfile.gettempdir(), "simbt"))
VAR = os.environ.get("TL_VAR", "cp")              # cp | cp_noflag  (events used as HISTORY / features)
LABELS = os.environ.get("TL_LABELS", "cp")        # events used for labels (always the full set by default)
TAG = os.environ.get("TL_TAG", VAR)               # output tag (models_tl_<TAG>, rows_tl_<TAG>)
SELECTED = {d.strftime("%Y-%m-%d") for d in pd.date_range("2026-10-29", "2026-11-04")}


def sh(*a, check=False):
    return subprocess.run(list(a), capture_output=True, text=True, check=check)


def prepare():
    tmp = tempfile.mkdtemp(prefix="tl_")
    for f in ("events", "persons"):
        sh("gsutil", "-q", "cp", f"{B}/raw/population/store_v3/{f}.parquet", tmp, check=True)
    Pv = pd.read_parquet(f"{tmp}/persons.parquet"); comp = set(Pv[Pv.complete.astype(bool)].person_id)
    I = pd.read_parquet(f"{WORK}/items.parquet")   # from sim_v3_backtest prepare
    V = pd.read_parquet(f"{tmp}/events.parquet", columns=["person_id", "kind", "target_id", "ts_hi", "ts_quality"])
    V = V[V.kind.isin(["upvote", "comment"]) & V.person_id.isin(comp)].copy()
    V["item"] = V.target_id.astype(str); V = V[V.item.isin(set(I.id))]
    lday = dict(zip(I.id, I.day))
    own = V.ts_quality.isin(["exact", "bounded", "day"])
    t = V.ts_hi.dt.tz_convert("America/Los_Angeles").dt.strftime("%Y-%m-%d")
    V["date"] = np.where(own, np.maximum(t.fillna(""), V.item.map(lday)), V.item.map(lday))   # never before the launch day
    V["lday"] = ~own
    E = V.rename(columns={"person_id": "person"})[["person", "item", "date", "kind", "lday"]].drop_duplicates(["person", "item", "kind"])
    E.to_parquet(f"{WORK}/events_cp.parquet"); E[~E.lday].to_parquet(f"{WORK}/events_cp_noflag.parquet")
    up = E[E.kind == "upvote"]
    rep = {"complete_persons": len(comp), "events": len(E), "upvotes": len(up), "upvotes_launch_day_dated": int(up.lday.sum()),
           "people_with_events": int(E.person.nunique()), "noflag_events": int((~E.lday).sum())}
    json.dump(rep, open(f"{WORK}/tl_prepare.json", "w")); print(json.dumps(rep))


def _env():
    os.environ["TIE2"] = "1"
    for k in ("PAGE", "TASTE", "HERD", "PRESENCE", "TWIN", "COMP", "RECIP", "UPV_LAG", "TRAIN_ALL"):
        os.environ.pop(k, None)


def _load(before):
    I = pd.read_parquet(f"{WORK}/items.parquet")
    Eall = pd.read_parquet(f"{WORK}/events_{VAR}.parquet")
    Elab = pd.read_parquet(f"{WORK}/events_{LABELS}.parquet")
    E = Eall[(Eall.date < before) & Eall.item.isin(set(I[I.day < before].id))][["person", "item", "date", "kind"]]
    P = pd.DataFrame({"person": sorted(set(E.person))}).assign(follows="[]")
    return P, I, E, Elab


def _ps(P, I, E, work):
    from simlab import store, harness, popscore as PS
    store.RAW = os.path.join(WORK, "live"); store.load = lambda: (P, I, E)
    harness.baseline = lambda: pd.DataFrame({"id": I.id, "day": I.day, "base": 0.5})
    PS.WORK = work; os.makedirs(work, exist_ok=True); PS.load()
    return PS


def train(m):
    _env(); P, I, E, _ = _load(f"{m}-01")
    I = I[I.day < f"{m}-01"]
    PS = _ps(P, I, E, os.path.join(WORK, f"models_tl_{TAG}"))
    r = PS.train_month(m)
    json.dump({"max_event_date": E.date.max(), "events": len(E)}, open(os.path.join(WORK, f"models_tl_{TAG}", f"model_{m}.json"), "w"))
    print(json.dumps({"tag": TAG, "month": m, "train_rows": r[1], "pos_rate": round(r[2], 4), "events": len(E), "people": len(P)}))


def day(d):
    _env(); P, I, E, Eall = _load(d)
    I = I[I.day <= d]
    from simlab import choice
    PS = _ps(P, I, E, os.path.join(WORK, f"work_tl_{TAG}_{d}"))
    import pickle
    mdir = os.environ.get("TL_MODEL_DIR") or f"models_tl_{TAG}"   # e.g. models_wh: the deployed-style model as a person-level comparator
    art = pickle.load(open(os.path.join(WORK, mdir, f"model_{d[:7]}.pkl"), "rb"))
    D = choice.rows(day_from=d, day_to=d, all_people=True)
    D = PS.featurize(D, art["cf"], art["prior_cut"]); D, pc = PS.page_cols(D)
    D["p"] = art["model"].predict_proba(D[PS.FEATS + pc])[:, 1]
    lineup = set(I[I.day == d].id)
    lab = Eall[(Eall.kind == "upvote") & Eall.item.isin(lineup)]
    pos = set(zip(lab.person, lab.item))
    D["y"] = [int((u, x) in pos) for u, x in zip(D.person, D.id)]
    # voters among complete people who were not active in the 30 days before d have no row: count them for recall
    seen = set(D.person); unseen = lab[~lab.person.isin(seen)].groupby("item").size()
    os.makedirs(f"{WORK}/rows_tl_{TAG}", exist_ok=True)
    D[["person", "id", "w", "p", "y", "backed"]].assign(day=d).to_parquet(f"{WORK}/rows_tl_{TAG}/{d}.parquet")
    json.dump({str(k): int(v) for k, v in unseen.items()}, open(f"{WORK}/rows_tl_{TAG}/{d}_unseen.json", "w"))
    print(json.dumps({"tag": TAG, "day": d, "rows": len(D), "people": int(D.person.nunique()), "positives": int(D.y.sum()),
                      "voters_without_row": int(unseen.sum())}))


def boot(x, rng, n=10000):
    x = np.asarray(x, float); x = x[~np.isnan(x)]
    if len(x) < 2:
        return [round(float(x.mean()), 3) if len(x) else None, None, int(len(x))]
    b = [x[rng.integers(0, len(x), len(x))].mean() for _ in range(n)]
    return [round(float(x.mean()), 3), [round(float(v), 3) for v in np.percentile(b, [2.5, 97.5])], int(len(x))]


def tier_of(w, q):
    return np.digitize(w, q)


def rep_factors(prev, real_votes):
    """Tier factors fitted on PREVIOUS days only (rows of days < d): per activity tier, real votes the complete people
    cast / their weighted expected votes, scaled by the share of each launch's real total that complete people cast.
    Returns (tier cut points, factor per tier) or None when there are no previous days."""
    if prev is None or not len(prev):
        return None
    q = prev.w.quantile([1 / 3, 2 / 3]).values
    t = tier_of(prev.w, q)
    ev = prev.assign(t=t, e=prev.w * prev.p).groupby("t").e.sum()
    obs = prev.assign(t=t)[prev.y == 1].groupby("t").size()
    return q, {k: float(obs.get(k, 0)) / ev[k] if ev[k] > 0 else 1.0 for k in ev.index}


def rep_factor(R, real_votes):
    """Per activity tier (w terciles), real votes per tier / sample's weighted expected votes per tier, scaled so the
    weighted sample matches the real voter base's volume. real_votes: launch id -> real votes."""
    q = R.w.quantile([1 / 3, 2 / 3]).values
    R = R.assign(tier=np.digitize(R.w, q))
    share = R[R.y == 1].groupby("tier").size() / max((R.y == 1).sum(), 1)   # tier shares of complete people's votes
    tot = sum(real_votes.get(x, 0) for x in set(R.id))
    ev = R.assign(e=R.w * R.p).groupby("tier").e.sum()
    f = {t: (share.get(t, 0) * tot) / ev[t] if ev.get(t, 0) > 0 else 1.0 for t in ev.index}
    return R.tier.map(f).fillna(1.0)


def topk(g, col, k, asc=False):
    top = set(g[g["rank"] <= k].id)
    if len(top) < k or g[col].isna().any():
        return np.nan
    return len(set((g.nsmallest(k, col) if asc else g.nlargest(k, col)).id) & top) / k * 100


def score():
    from sklearn.metrics import roc_auc_score, log_loss
    from pipeline import warehouse as W
    files = sorted(glob.glob(f"{WORK}/rows_tl_{TAG}/*.parquet"))
    L = W.query("SELECT CAST(id AS VARCHAR) AS id, day::VARCHAR AS day, daily_rank, weekly_rank, votes FROM launches WHERE daily_rank IS NOT NULL")
    votes = dict(zip(L.id, L.votes)); rnk = dict(zip(L.id, L.daily_rank)); wrk = dict(zip(L.id, L.weekly_rank))
    Fc = W.query("SELECT launch_id AS id, forecast_date AS day, predicted_rank FROM forecasts WHERE model = 'launch_model'", do_sync=False)
    lm = {(r.day, str(r.id)): r.predicted_rank for r in Fc.itertuples()}
    dep = {}
    for f in glob.glob(f"{WORK}/scores_retrain/wh_*.parquet"):
        S = pd.read_parquet(f); dep.update({(r.day, str(r.id)): r.psn_ev for r in S.itertuples()})
    # E5 checks 2 and 3: a person's labels on d count only if their upvote list was read >= 2 days after d, and for lists
    # short of their header (signed-out cap) only from their oldest listed vote onward
    T = pd.read_parquet(f"{WORK}/tabs_v3.parquet"); T = T[T.tab == "upvotes"]
    read_day = dict(zip(T.person_id, pd.to_datetime(T.fetched_at, utc=True).dt.tz_convert("America/Los_Angeles").dt.strftime("%Y-%m-%d")))
    short = set(T[T["count"] < T.header.fillna(0) * 0.98].person_id)
    Eu = pd.read_parquet(f"{WORK}/events_cp.parquet"); Eu = Eu[Eu.kind == "upvote"]
    oldest = Eu.groupby("person").date.min().to_dict()
    filt_n = []
    per, pop, diag, prev_rows = [], [], [], []
    for f in files:
        d = os.path.basename(f)[:10]; R = pd.read_parquet(f); R["id"] = R.id.astype(str)
        d2 = (pd.Timestamp(d) + pd.Timedelta(days=2)).strftime("%Y-%m-%d")
        ok = R.person.map(lambda u: read_day.get(u, "0000") >= d2 and (u not in short or oldest.get(u, "9999") <= d))
        filt_n.append({"day": d, "people_before": int(R.person.nunique()), "people_after": int(R[ok].person.nunique())})
        R = R[ok].copy()
        if not len(R):
            continue
        raw = R.copy()
        if os.environ.get("WEIGHTS", "act") == "rep":
            fac = rep_factors(pd.concat(prev_rows[-7:]) if prev_rows else None, votes)   # previous 7 scored days only
            if fac is not None:
                q, fmap = fac
                R["w"] = R.w * pd.Series(tier_of(R.w, q), index=R.index).map(fmap).fillna(1.0)
        prev_rows.append(raw[["w", "p", "y"]])
        pw = R.groupby("person").w.first(); tot = pw.sum()
        diag.append({"day": d, "people": int(len(pw)), "rows": int(len(R)), "n_eff": float(tot ** 2 / (pw ** 2).sum()) if tot else 0,
                     "max_w_share": float(pw.max() / tot) if tot else 0, "top1pct_share": float(pw.nlargest(max(1, len(pw) // 100)).sum() / tot) if tot else 0})
        # weighted real votes vs real totals (E5 validation): sum_p w_p * y_pL per launch vs the launch's real votes
        wv = R.assign(e=R.w * R.y).groupby("id").e.sum()
        diag[-1]["spearman_weighted_real_vs_votes"] = float(spearmanr(wv.values, [votes.get(x, np.nan) for x in wv.index], nan_policy="omit").correlation) if len(wv) > 3 else None
        unseen = json.load(open(f[:-8] + "_unseen.json"))
        q = (R.w * R.p).clip(1e-6, 1 - 1e-6)   # E5 check 1: P(votes that day | pre-d activity) x P(picks L | votes)
        auc = roc_auc_score(R.y, q) if R.y.nunique() > 1 else np.nan
        ll = log_loss(R.y, q)
        g = R[R.groupby("person").y.transform("sum") > 0]
        top3 = g[g.groupby("person").p.rank(ascending=False, method="first") <= 3]
        hit3 = top3.groupby("person").y.max().mean() if len(top3) else np.nan
        rec, rp = [], []
        for x, gx in R.groupby("id"):
            n = int(gx.y.sum()) + int(unseen.get(x, 0))
            if n:
                rec.append(gx.nlargest(n, "p").y.sum() / n)
            m = int(gx.y.sum())   # voter R-precision (E5): of the launch's top-m scored people (m = its voters with a row), share who voted
            if m:
                rp.append(gx.assign(q=gx.w * gx.p).nlargest(m, "q").y.sum() / m)
        per.append({"day": d, "auc": auc, "logloss": ll, "hit3": hit3, "voter_recall": float(np.mean(rec)) if rec else np.nan,
                    "voter_rprec": float(np.mean(rp)) if rp else np.nan})
        ev = R.assign(e=R.w * R.p).groupby("id").e.sum()
        for x, e in ev.items():
            pop.append({"day": d, "id": x, "ev": e, "dep": dep.get((d, x)), "lm": lm.get((d, x)), "votes": votes.get(x), "rank": rnk.get(x), "wrank": wrk.get(x)})
    Pm = pd.DataFrame(per); Q = pd.DataFrame(pop).dropna(subset=["rank"])
    rng = np.random.default_rng(0)
    res = {"tag": TAG, "weights": os.environ.get("WEIGHTS", "act"), "days": sorted(Q.day.unique().tolist())}
    res["person"] = {k: boot(Pm[k].values, rng) for k in ("auc", "logloss", "hit3", "voter_recall", "voter_rprec")}
    res["label_filter"] = {"rule": "labels on d only for people whose upvote list was read >= d+2; short (signed-out capped) lists only from the oldest listed vote",
                           "per_day": filt_n}
    # E5 check 4: paired against E5's no-follow baseline per day (pop_by_day_nofol.csv, weighted EV columns)
    e5p = os.environ.get("E5_BASELINE")
    if e5p and os.path.exists(e5p):
        E5 = pd.read_csv(e5p).set_index("d")
        res["vs_e5_baseline"] = {}
        for k in (3, 5, 10):
            dd = [d for d in E5.index if d in set(Q.day) and d not in SELECTED]
            a = np.array([topk(Q[Q.day == d], "ev", k) for d in dd]); b = np.array([E5.loc[d, f"ev_w_top{k}"] * 100 for d in dd])
            res["vs_e5_baseline"][f"clean day top{k}"] = {"two_level": round(float(np.nanmean(a)), 1), "e5_nofol": round(float(np.nanmean(b)), 1), "delta": boot(a - b, rng), "days": len(dd)}

    def _unused(g, col, k, asc=False):
        top = set(g[g["rank"] <= k].id)
        if len(top) < k or g[col].isna().any():
            return np.nan
        return len(set((g.nsmallest(k, col) if asc else g.nlargest(k, col)).id) & top) / k * 100

    def block(days):
        out = {}
        for k in (3, 5, 10):
            a = np.array([topk(Q[Q.day == d], "ev", k) for d in days]); b = np.array([topk(Q[Q.day == d], "dep", k) for d in days])
            c = np.array([topk(Q[Q.day == d], "lm", k, asc=True) for d in days])
            m1 = ~np.isnan(a) & ~np.isnan(b); m2 = ~np.isnan(a) & ~np.isnan(c)
            out[f"day top{k}"] = {"two_level": round(float(np.nanmean(a)), 1), "deployed_sim": round(float(np.nanmean(b[m1])), 1) if m1.any() else None,
                                  "delta_vs_deployed": boot((a - b)[m1], rng), "launch_model": round(float(np.nanmean(c[m2])), 1) if m2.any() else None,
                                  "delta_vs_launch_model": boot((a - c)[m2], rng)}
        sp = [spearmanr(Q[Q.day == d].ev, Q[Q.day == d].votes).correlation for d in days if (Q.day == d).sum() > 3]
        spd = [spearmanr(Q[(Q.day == d) & Q.dep.notna()].ev, Q[(Q.day == d) & Q.dep.notna()].dep).correlation for d in days if ((Q.day == d) & Q.dep.notna()).sum() > 3]
        out["spearman_ev_votes"] = boot(sp, rng)
        out["spearman_deployed_votes"] = boot([spearmanr(Q[(Q.day == d) & Q.dep.notna()].dep, Q[(Q.day == d) & Q.dep.notna()].votes).correlation
                                               for d in days if ((Q.day == d) & Q.dep.notna()).sum() > 3], rng)
        return out
    alld = res["days"]; clean = [d for d in alld if d not in SELECTED]
    res["population_all_days"] = block(alld); res["population_clean_days"] = block(clean)
    res["clean_days"] = clean
    Dg = pd.DataFrame(diag)
    res["weights_diag"] = {"n_eff_median": round(float(Dg.n_eff.median()), 1), "people_median": int(Dg.people.median()),
                           "max_w_share_max": round(float(Dg.max_w_share.max()), 4), "top1pct_share_median": round(float(Dg.top1pct_share.median()), 3),
                           "spearman_weighted_real_vs_votes_median": round(float(Dg.spearman_weighted_real_vs_votes.median()), 3)}
    res["n_both_levels"] = {"person_days": int(Dg.people.sum()), "rows": int(Dg.rows.sum()), "days": len(Dg),
                            "note": "person metrics and launch EV use the same rows (complete people active in the 30 days before d x the line-up)"}
    res["model_max_event_date"] = {os.path.basename(m): json.load(open(m[:-4] + ".json")).get("max_event_date") if os.path.exists(m[:-4] + ".json") else None
                                   for m in glob.glob(f"{WORK}/models_tl_{TAG}/model_*.pkl")}
    res["follow_edges"] = "none (people get follows='[]'; no follow features enter)"
    Q["week"] = pd.to_datetime(Q.day).dt.strftime("%G-W%V")
    wk = {}
    for w, g in Q.groupby("week"):
        if g.day.nunique() < 7:
            continue
        for k in (3, 5, 10):
            top = set(g[g.wrank <= k].id)
            wk[f"{w} top{k}"] = {"two_level": len(set(g.nlargest(k, "ev").id) & top) / k * 100,
                                 "deployed_sim": len(set(g.dropna(subset=["dep"]).nlargest(k, "dep").id) & top) / k * 100}
    res["weekly"] = wk
    out = os.path.join(HERE, "results", f"two_level_{TAG}_{res['weights']}.json")
    json.dump(res, open(out, "w"), indent=1); print(json.dumps(res, indent=1))


def blend():
    """Hierarchical form (orchestrator Nov 10 23:52Z): launch score = z(launch-model score) + beta * z(log EV), within day.
    Launch-model score known at 00:05 PT: the honest backtest prediction (honest_preds 'honest', Oct 20-24) or the live
    forecast's predicted rank (forecasts table, Oct 25 on). beta chosen (a) leave-one-day-out over all scored days and
    (b) fitted on October days, tested on November days; criterion = mean of daily top 3 and top 5 hits."""
    from pipeline import warehouse as W
    L = W.query("SELECT CAST(id AS VARCHAR) AS id, day::VARCHAR AS day, daily_rank, votes FROM launches WHERE daily_rank IS NOT NULL")
    rnk = dict(zip(L.id, L.daily_rank))
    lm = {}
    hp = os.environ.get("HONEST_PREDS")
    if hp and os.path.exists(hp):
        H = pd.read_parquet(hp); H["id"] = H.id.astype(str)
        lm.update({(r.day, r.id): float(r.honest) for r in H.itertuples()})
    Fc = W.query("SELECT CAST(launch_id AS VARCHAR) AS id, forecast_date AS day, predicted_rank FROM forecasts WHERE model = 'launch_model'", do_sync=False)
    lm.update({(r.day, r.id): -float(np.log(r.predicted_rank)) for r in Fc.itertuples()})
    rows = []
    for f in sorted(glob.glob(f"{WORK}/rows_tl_{TAG}/*.parquet")):
        d = os.path.basename(f)[:10]; R = pd.read_parquet(f); R["id"] = R.id.astype(str)
        ev = R.assign(e=R.w * R.p).groupby("id").e.sum()
        for x, e in ev.items():
            rows.append({"day": d, "id": x, "ev": np.log1p(e * 1000), "lm": lm.get((d, x)), "rank": rnk.get(x)})
    Q = pd.DataFrame(rows).dropna(subset=["rank"])
    Q = Q[Q.groupby("day").lm.transform(lambda s: s.notna().all())]
    for c in ("ev", "lm"):
        g = Q.groupby("day")[c]; Q["z_" + c] = (Q[c] - g.transform("mean")) / (g.transform("std") + 1e-9)
    days = sorted(Q.day.unique()); betas = np.round(np.arange(0, 2.01, 0.1), 2)

    def hits(d, beta, k):
        g = Q[Q.day == d]; top = set(g[g["rank"] <= k].id)
        if len(top) < k:
            return np.nan
        return len(set(g.assign(s=g.z_lm + beta * g.z_ev).nlargest(k, "s").id) & top) / k * 100

    def crit(ds, beta):
        return np.nanmean([(hits(d, beta, 3) + hits(d, beta, 5)) / 2 for d in ds])
    rng = np.random.default_rng(0); res = {"tag": TAG, "days": days, "n_days": len(days)}
    lodo = {d: max(betas, key=lambda b: crit([x for x in days if x != d], b)) for d in days}
    for k in (3, 5, 10):
        a = np.array([hits(d, 0.0, k) for d in days]); b = np.array([hits(d, lodo[d], k) for d in days])
        res[f"lodo top{k}"] = {"launch_model": round(float(np.nanmean(a)), 1), "blend": round(float(np.nanmean(b)), 1), "delta": boot(b - a, rng)}
    res["lodo_beta"] = {d: float(v) for d, v in lodo.items()}
    octd = [d for d in days if d < "2026-11-01"]; novd = [d for d in days if d >= "2026-11-01"]
    bo = max(betas, key=lambda b: crit(octd, b)); res["oct_fit_beta"] = float(bo)
    for k in (3, 5, 10):
        a = np.array([hits(d, 0.0, k) for d in novd]); b = np.array([hits(d, bo, k) for d in novd])
        res[f"nov_test top{k}"] = {"launch_model": round(float(np.nanmean(a)), 1), "blend": round(float(np.nanmean(b)), 1), "delta": boot(b - a, rng), "days": len(novd)}
    json.dump(res, open(os.path.join(HERE, "results", f"two_level_blend_{TAG}.json"), "w"), indent=1); print(json.dumps(res, indent=1))


if __name__ == "__main__":
    c = sys.argv[1]
    {"prepare": lambda: prepare(), "train": lambda: train(sys.argv[2]), "day": lambda: day(sys.argv[2]), "score": lambda: score(),
     "blend": lambda: blend()}[c]()
