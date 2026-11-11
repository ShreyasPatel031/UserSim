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
    if os.environ.get("TL_FOL") == "1":
        os.environ["FOLLOW"] = "baseline"   # adds fol_team, fol_team_n, pre_comment_this to FEATS (set before import)
    for k in ("PAGE", "TASTE", "HERD", "PRESENCE", "TWIN", "COMP", "RECIP", "UPV_LAG", "TRAIN_ALL"):
        os.environ.pop(k, None)


def _load(before):
    I = pd.read_parquet(f"{WORK}/items.parquet")
    Eall = pd.read_parquet(f"{WORK}/events_{VAR}.parquet")
    Elab = pd.read_parquet(f"{WORK}/events_{LABELS}.parquet")
    E = Eall[(Eall.date < before) & Eall.item.isin(set(I[I.day < before].id))][["person", "item", "date", "kind"]]
    P = pd.DataFrame({"person": sorted(set(E.person))}).assign(follows="[]")
    return P, I, E, Elab


def lm_pct():
    """Launch-model score known at 00:05 PT, as a within-day percentile: the honest backtest prediction (honest_preds
    'honest', rolling monthly, out of sample; through Oct 25) and the live forecast (forecasts table, Oct 25 on)."""
    path = os.path.join(WORK, "lm_pct.parquet")
    if os.path.exists(path):
        M = pd.read_parquet(path)
    else:
        from pipeline import warehouse as W
        rows = []
        hp = os.environ.get("HONEST_PREDS")
        if hp and os.path.exists(hp):
            H = pd.read_parquet(hp); rows.append(pd.DataFrame({"day": H.day.astype(str), "id": H.id.astype(str), "s": H.honest.astype(float), "src": "honest"}))
        F = W.query("SELECT CAST(launch_id AS VARCHAR) AS id, forecast_date AS day, predicted_rank FROM forecasts WHERE model = 'launch_model'")
        rows.append(pd.DataFrame({"day": F.day, "id": F.id, "s": -np.log(F.predicted_rank.astype(float)), "src": "live"}))
        M = pd.concat(rows)
        M = M[~M.duplicated(["day", "id"], keep="last")]      # live wins where both exist (Oct 25)
        M["lm_pct"] = M.groupby(["day", "src"]).s.rank(pct=True)
        M[["day", "id", "lm_pct"]].to_parquet(path)
    return {(d, i): v for d, i, v in zip(M.day, M.id, M.lm_pct)}


def _ps(P, I, E, work):
    from simlab import store, harness, popscore as PS
    store.RAW = os.path.join(WORK, "live"); store.load = lambda: (P, I, E)
    harness.baseline = lambda: pd.DataFrame({"id": I.id, "day": I.day, "base": 0.5})
    PS.WORK = work; os.makedirs(work, exist_ok=True); PS.load()
    if os.environ.get("TL_FOL") == "1":   # iteration 4: dated follow edges only (E5, Nov 11 00:40Z)
        import hashlib
        from pipeline import warehouse as W
        sl = sh("gsutil", "cat", f"{B}/raw/population/_salt", check=True).stdout.strip()
        F = W.query("SELECT lower(person) AS p, lower(followee) AS f, observed_on::VARCHAR AS o FROM follows WHERE observed_on = '2026-10-26'")
        F["pid"] = ["p_" + hashlib.sha256((sl + "producthunt:" + u).encode()).hexdigest()[:16] for u in F.p]
        fol = F.groupby("pid").f.apply(set).to_dict(); seen = "2026-10-26"
        g = PS.load(); dd = g["day"]; C = g["E"][g["E"].kind == "comment"]
        precom = {(u, x) for u, x, t in zip(C.person, C.item, C.date) if x in dd and str(t)[:10] < dd[x]}
        team_lc = {x: {str(m).lower() for m in ms if m} for x, ms in g["team"].items()}
        def follow_features(D):
            ok = (D.day > seen).values   # an edge counts only on days after the read that saw it
            n = [len(fol.get(u, set()) & team_lc.get(x, set())) if o else 0 for u, x, o in zip(D.person, D.id, ok)]
            D["fol_team_n"] = np.array(n, dtype=float); D["fol_team"] = (D.fol_team_n > 0).astype(float)
            D["pre_comment_this"] = [float((u, x) in precom) for u, x in zip(D.person, D.id)]
            return D
        PS.follow_features = follow_features
        PS.G["fol_people"] = set(fol)
    if os.environ.get("TL_UNCOND") == "1":   # iteration 5 (E5 Nov 11): unconditional P(votes on L | pre-d history)
        from simlab import choice                # trained on all-people rows (everyone active in the 30 days before d),
        def train_rows(M):                       # with the activity share w as a feature instead of a multiplier
            cut = PS.month_start(M, 0)
            D = choice.rows(day_from=cut, day_to=PS.month_end(M), all_people=True)
            rng = np.random.default_rng(0)
            if os.environ.get("TL_NEG") == "1":   # E5's scheme: every person-day; voting days keep all positives + 8 negatives
                pv = D.groupby("g").y.transform("sum") > 0   # per positive (reweighted), non-voting days kept at 5% (weight 20)
                u = rng.random(len(D))
                vd = D[pv]; npos = vd.groupby("g").y.transform("sum"); nneg = vd.groupby("g").y.transform(lambda s: (s == 0).sum())
                pk = np.minimum(1.0, 8 * npos / nneg.clip(lower=1))
                kv = (vd.y == 1) | (u[pv.values] < pk)
                V = vd[kv].assign(sw=np.where(vd.y[kv] == 1, 1.0, 1.0 / pk[kv]))
                nd = D[~pv]; gk = nd.g.unique(); gk = set(rng.permutation(gk)[:max(1, int(0.05 * len(gk)))])
                N = nd[nd.g.isin(gk)].assign(sw=20.0)
                D = pd.concat([V, N]).copy()
            else:
                keep = set()
                for d, g in D.groupby("day"):
                    keep |= {u + "|" + d for u in rng.permutation(list(g.person.unique()))[:600]}
                D = D[D.g.isin(keep)].copy(); D["sw"] = 1.0
            D = PS.featurize(D, PS.fit_cf(cut), cut); D, pc = PS.page_cols(D)
            return D[["person", "day", "id", "y", "sw"] + PS.FEATS + pc].reset_index(drop=True)
        PS.train_rows = train_rows
        def train_month(m):   # same as popscore.train_month, with the sample weights
            import lightgbm as lgb, pickle
            prev = PS.month_start(m, 1); cf = PS.fit_cf(prev)
            D = pd.concat([train_rows(M) for M in PS.train_months(m)], ignore_index=True)
            mdl = lgb.LGBMClassifier(n_estimators=300, learning_rate=0.05, num_leaves=15, min_child_samples=50, verbose=-1, n_jobs=1)
            pc = [c for c in D.columns if c not in ["person", "day", "id", "y", "sw"] + PS.FEATS]
            mdl.fit(D[PS.FEATS + pc], D.y, sample_weight=D.sw)
            pickle.dump({"model": mdl, "cf": cf, "prior_cut": prev}, open(f"{PS.WORK}/model_{m}.pkl", "wb"))
            return m, len(D), float(np.average(D.y, weights=D.sw))
        PS.train_month = train_month
        base_u = PS.page_cols
        Ev = PS.load()["E"]; Ev = Ev[Ev.kind.isin(["upvote", "comment"])]
        act = {u: np.array(sorted(set(map(str, g.date.astype(str).str[:10]))), dtype="datetime64[D]") for u, g in Ev.groupby("person")}
        def recency(u, d):   # E5 Nov 11: P(active) from recency, not only the 30-day share; all from dates before d
            a = act.get(u); t = np.datetime64(d, "D")
            if a is None:
                return (999.0, 0.0, 0.0, 0.0, 0.0)
            a = a[a < t]
            if not len(a):
                return (999.0, 0.0, 0.0, 0.0, 0.0)
            gap = (t - a).astype(int)
            return (float(gap.min()), float((gap <= 7).sum()), float(np.log1p((gap <= 30).sum())), float(np.log1p(len(a))), float(gap.max()))
        def page_cols_u(D, _b=base_u):
            D, pc = _b(D)
            key = D.person + "|" + D.day
            R = {k: recency(*k.split("|", 1)) for k in key.unique()}
            M = np.array([R[k] for k in key])
            D = D.assign(w_act=D.w.astype(float), days_since=M[:, 0], act_7=M[:, 1], log_act_30=M[:, 2], log_act_all=M[:, 3], tenure=M[:, 4],
                         dow=pd.to_datetime(D.day).dt.dayofweek.astype(float))
            return D, list(pc) + ["w_act", "days_since", "act_7", "log_act_30", "log_act_all", "tenure", "dow"]
        PS.page_cols = page_cols_u
    if os.environ.get("TL_PRIOR") == "1":   # iteration 7 (pre-registered with E5, Nov 11): launch priors from settled ranks only
        pri = launch_priors(I); base_p = PS.page_cols
        cols = ["team_prior_n", "team_best_rank", "team_mean_inv_rank", "team_top10_rate", "topic_top10_rate", "topic_mean_inv_rank", "topic_n_launches"]
        def page_cols_p(D, _b=base_p):
            D, pc = _b(D)
            M = np.array([pri.get(str(x), [np.nan] * len(cols)) for x in D.id], dtype=float)
            for k, c in enumerate(cols):
                D[c] = M[:, k]
            return D, list(pc) + cols
        PS.page_cols = page_cols_p
    if os.environ.get("TL_LM") == "1":   # iteration 3: launch-model pull as a person-model feature (NaN where unknown)
        lm = lm_pct(); base = PS.page_cols
        def page_cols(D, _b=base):
            D, pc = _b(D)
            D = D.assign(lm_pct=[lm.get((d, str(x)), np.nan) for d, x in zip(D.day, D.id)])
            return D, list(pc) + ["lm_pct"]
        PS.page_cols = page_cols
    return PS


def SFX():
    return "_recal" if os.environ.get("TL_RECAL") == "1" else ""


def launch_priors(I):
    """Per launch L on day d: team (makers + hunter) history over launches dated <= d-2 (daily rank settled) and topic form
    over launches dated d-8 .. d-2. Ranks from the warehouse launches table; nothing dated d-1 or later enters."""
    from pipeline import warehouse as W
    R = W.query("SELECT CAST(id AS VARCHAR) AS id, daily_rank FROM launches WHERE daily_rank IS NOT NULL", do_sync=False)
    rk = dict(zip(R.id, R.daily_rank.astype(float)))
    J = I.assign(id=I.id.astype(str)).sort_values("day")
    J["team"] = [({str(m).lower() for m in json.loads(mk or "[]") if m} | ({str(p).lower()} if p else set())) for mk, p in zip(J.makers, J.poster)]
    J["tops"] = [json.loads(t or "[]") for t in J.topics]
    J["rank"] = J.id.map(rk)
    days = sorted(J.day.unique()); by_day = {d: g for d, g in J.groupby("day")}
    out = {}
    hist_team = {}   # person -> list of (rank, launch day) of launches settled so far (dated <= d-2)
    checks = {"rows": 0, "violations": 0}
    added = set()
    for d in days:
        cut = (pd.Timestamp(d) - pd.Timedelta(days=2)).strftime("%Y-%m-%d")
        for dd in days:
            if dd > cut:
                break
            if dd in added:
                continue
            added.add(dd)
            for r in by_day[dd].itertuples():
                if not np.isnan(r.rank):
                    for u in r.team:
                        hist_team.setdefault(u, []).append((r.rank, dd))
        lo = (pd.Timestamp(d) - pd.Timedelta(days=8)).strftime("%Y-%m-%d")
        win = J[(J.day >= lo) & (J.day <= cut) & J["rank"].notna()]
        tf = {}
        for t, rr, dd in zip(win.tops, win["rank"], win.day):
            for x in t:
                tf.setdefault(x, []).append((rr, dd))
        for r in by_day[d].itertuples():
            used = [dd for u in r.team for _, dd in hist_team.get(u, [])] + [dd for x in r.tops for _, dd in tf.get(x, [])]
            checks["rows"] += 1; checks["violations"] += int(bool(used) and max(used) > cut)   # E5: max(prior launch day) <= d-2
            rs = [v for u in r.team for v, _ in hist_team.get(u, [])]
            a = np.array(rs) if rs else None
            tt = [np.array([v for v, _ in tf[x]]) for x in r.tops if x in tf]
            out[r.id] = [float(len(rs)), float(a.min()) if a is not None else np.nan, float((1 / a).mean()) if a is not None else np.nan,
                         float((a <= 10).mean()) if a is not None else np.nan,
                         float(np.mean([(v <= 10).mean() for v in tt])) if tt else np.nan,
                         float(np.mean([(1 / v).mean() for v in tt])) if tt else np.nan,
                         float(np.mean([len(v) for v in tt])) if tt else 0.0]
    assert checks["violations"] == 0, checks
    os.makedirs(os.path.join(WORK, f"rows_tl_{TAG}"), exist_ok=True)
    json.dump(checks, open(os.path.join(WORK, f"rows_tl_{TAG}", "prior_assert.json"), "w"))
    return out

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
    if os.environ.get("TL_UNCOND") == "1":   # p is already unconditional: EV = sum p, person metrics on p
        D["w"] = 1.0
    lineup = set(I[I.day == d].id)
    lab = Eall[(Eall.kind == "upvote") & Eall.item.isin(lineup)]
    pos = set(zip(lab.person, lab.item))
    D["y"] = [int((u, x) in pos) for u, x in zip(D.person, D.id)]
    fol_cov = None
    if os.environ.get("TL_FOL") == "1":
        fp = PS.G.get("fol_people", set()); ppl = set(D.person)
        fol_cov = {"people_with_dated_edges": len(ppl & fp) if d > "2026-10-26" else 0, "people": len(ppl),
                   "rows_fol_team": int(D.fol_team.sum()) if "fol_team" in D else 0}
    # voters among complete people who were not active in the 30 days before d have no row: count them for recall
    seen = set(D.person); unseen = lab[~lab.person.isin(seen)].groupby("item").size()
    os.makedirs(f"{WORK}/rows_tl_{TAG}", exist_ok=True)
    D[["person", "id", "w", "p", "y", "backed"]].assign(day=d).to_parquet(f"{WORK}/rows_tl_{TAG}/{d}.parquet")
    if os.environ.get("TL_UNCOND") == "1" and os.environ.get("TL_SAVEX", "1") == "1":   # feature matrix for the choice model (it8)
        X = D[PS.FEATS + pc].astype("float32"); X.insert(0, "id", D.id.astype(str).values); X.insert(0, "person", D.person.values)
        X["y"] = D.y.values.astype("int8"); X.to_parquet(f"{WORK}/rows_tl_{TAG}/X_{d}.parquet")
    json.dump({str(k): int(v) for k, v in unseen.items()}, open(f"{WORK}/rows_tl_{TAG}/{d}_unseen.json", "w"))
    if fol_cov is not None:
        json.dump(fol_cov, open(f"{WORK}/rows_tl_{TAG}/{d}_fol.json", "w"))
    print(json.dumps({"tag": TAG, "day": d, "rows": len(D), "people": int(D.person.nunique()), "positives": int(D.y.sum()),
                      "voters_without_row": int(unseen.sum()), "follow_coverage": fol_cov}))


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
    files = sorted(f for f in glob.glob(f"{WORK}/rows_tl_{TAG}/*.parquet") if os.path.basename(f)[:2] == "20")
    D0, D1 = os.environ.get("TL_FROM", "2026-10-20"), os.environ.get("TL_TO", "2026-11-08")
    allfiles = files; files = [f for f in files if D0 <= os.path.basename(f)[:10] <= D1]   # scored days; earlier files feed TL_RECAL only
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
    filt_n, dump = [], []
    per, pop, diag, prev_rows = [], [], [], []
    recal = None
    if os.environ.get("TL_RECAL") == "1":   # E5 (ii): one isotonic map per month fold, P's within-day percentile -> P(vote),
        from sklearn.isotonic import IsotonicRegression   # fit on the previous month's label-filtered rows only
        recal = {}
        def _filt(R, d):
            d2 = (pd.Timestamp(d) + pd.Timedelta(days=2)).strftime("%Y-%m-%d")
            return R[R.person.map(lambda u: read_day.get(u, "0000") >= d2 and (u not in short or oldest.get(u, "9999") <= d))]
        for mon in sorted({os.path.basename(f)[:7] for f in files}):
            prev = (pd.Timestamp(mon + "-01") - pd.Timedelta(days=1)).strftime("%Y-%m")
            fit = [f for f in allfiles if os.path.basename(f)[:7] == prev]
            X = []
            for f in fit:
                R = pd.read_parquet(f, columns=["person", "p", "y"]); R["x"] = R.p.rank(pct=True)   # same key as the test days
                R = _filt(R, os.path.basename(f)[:10])
                X.append(R[["x", "y"]])
            X = pd.concat(X)
            recal[mon] = IsotonicRegression(out_of_bounds="clip", y_min=1e-6).fit(X.x, X.y)
            recal.setdefault("_fit", {})[mon] = {"fit_month": prev, "fit_days": len(fit), "fit_rows": int(len(X)), "fit_pos_rate": round(float(X.y.mean()), 5)}
    for f in files:
        d = os.path.basename(f)[:10]; R = pd.read_parquet(f); R["id"] = R.id.astype(str)
        if recal is not None:   # percentile over the whole day's rows (before the label filter, as known at 00:05)
            R["p"] = recal[d[:7]].predict(R.p.rank(pct=True).values)
        d2 = (pd.Timestamp(d) + pd.Timedelta(days=2)).strftime("%Y-%m-%d")
        ok = R.person.map(lambda u: read_day.get(u, "0000") >= d2 and (u not in short or oldest.get(u, "9999") <= d))
        filt_n.append({"day": d, "people_before": int(R.person.nunique()), "people_after": int(R[ok].person.nunique())})
        R = R[ok].copy()
        if not len(R) or filt_n[-1]["people_after"] < 0.5 * filt_n[-1]["people_before"]:   # E5: drop days that lose half their people
            filt_n[-1]["dropped"] = True
            continue
        raw = R.copy()
        if os.environ.get("WEIGHTS", "act") == "rep":
            fac = rep_factors(pd.concat(prev_rows[-7:]) if prev_rows else None, votes)   # previous 7 scored days only
            if fac is not None:
                q, fmap = fac
                R["w"] = R.w * pd.Series(tier_of(R.w, q), index=R.index).map(fmap).fillna(1.0)
        prev_rows.append(raw[["w", "p", "y"]])
        if os.environ.get("TL_DUMP") and d not in SELECTED:   # E5 (b): label-filtered clean-day rows for like-for-like scoring
            dump.append(raw[["person", "id", "w", "y"]].assign(d=d).rename(columns={"person": "person_id", "id": "launch_id"}))
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
        rec, rp, rpp = [], [], []
        for x, gx in R.groupby("id"):
            n = int(gx.y.sum()) + int(unseen.get(x, 0))
            if n:
                rec.append(gx.nlargest(n, "p").y.sum() / n)
            m = int(gx.y.sum())   # voter R-precision (E5): of the launch's top-m scored people (m = its voters with a row), share who voted
            if m:
                rp.append(gx.assign(q=gx.w * gx.p).nlargest(m, "q").y.sum() / m)
                rpp.append(gx.nlargest(m, "p").y.sum() / m)   # E5 Nov 11: rank by P (w is a population weight, EV only)
        per.append({"day": d, "auc": auc, "logloss": ll, "hit3": hit3, "voter_recall": float(np.mean(rec)) if rec else np.nan,
                    "voter_rprec": float(np.mean(rp)) if rp else np.nan, "voter_rprec_p": float(np.mean(rpp)) if rpp else np.nan})
        ev = R.assign(e=R.w * R.p).groupby("id").e.sum(); orc = R.groupby("id").y.sum()   # oracle (E5): sum of the sample's real votes, w = 1
        for x, e in ev.items():
            pop.append({"day": d, "id": x, "ev": e, "orc": orc.get(x, 0) + 1e-6 * e, "dep": dep.get((d, x)), "lm": lm.get((d, x)), "votes": votes.get(x), "rank": rnk.get(x), "wrank": wrk.get(x)})
    if dump:
        pd.concat(dump)[["d", "person_id", "launch_id", "w", "y"]].to_parquet(os.environ["TL_DUMP"], index=False)
    Pm = pd.DataFrame(per); Q = pd.DataFrame(pop).dropna(subset=["rank"])
    rng = np.random.default_rng(0)
    res = {"tag": TAG, "weights": os.environ.get("WEIGHTS", "act"), "days": sorted(Q.day.unique().tolist())}
    res["person"] = {k: boot(Pm[k].values, rng) for k in ("auc", "logloss", "hit3", "voter_recall", "voter_rprec", "voter_rprec_p")}
    cl = Pm[~Pm.day.isin(SELECTED)]
    res["person_rprec_p_split"] = {"clean": boot(cl.voter_rprec_p.values, rng), "oct_clean": boot(cl[cl.day < "2026-11-01"].voter_rprec_p.values, rng),
                                   "nov_clean": boot(cl[cl.day >= "2026-11-01"].voter_rprec_p.values, rng),
                                   "note": "hit3 and voter_recall already rank by P; voter_rprec (w*P) kept for reference"}
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
            o = np.array([topk(Q[Q.day == d], "orc", k) for d in days])
            m1 = ~np.isnan(a) & ~np.isnan(b); m2 = ~np.isnan(a) & ~np.isnan(c)
            out[f"day top{k}"] = {"two_level": round(float(np.nanmean(a)), 1), "deployed_sim": round(float(np.nanmean(b[m1])), 1) if m1.any() else None,
                                  "delta_vs_deployed": boot((a - b)[m1], rng), "launch_model": round(float(np.nanmean(c[m2])), 1) if m2.any() else None,
                                  "delta_vs_launch_model": boot((a - c)[m2], rng),
                                  "oracle_sample_votes": round(float(np.nanmean(o)), 1), "oracle_on_lm_days": round(float(np.nanmean(o[m2])), 1) if m2.any() else None}
        sp = [spearmanr(Q[Q.day == d].ev, Q[Q.day == d].votes).correlation for d in days if (Q.day == d).sum() > 3]
        spd = [spearmanr(Q[(Q.day == d) & Q.dep.notna()].ev, Q[(Q.day == d) & Q.dep.notna()].dep).correlation for d in days if ((Q.day == d) & Q.dep.notna()).sum() > 3]
        out["spearman_ev_votes"] = boot(sp, rng)
        out["spearman_oracle_votes"] = boot([spearmanr(Q[Q.day == d].orc, Q[Q.day == d].votes).correlation for d in days if (Q.day == d).sum() > 3], rng)
        out["oracle_per_day"] = {d: [topk(Q[Q.day == d], "orc", k) for k in (3, 5, 10)] for d in days}
        out["two_level_per_day"] = {d: [topk(Q[Q.day == d], "ev", k) for k in (3, 5, 10)] for d in days}
        out["spearman_deployed_votes"] = boot([spearmanr(Q[(Q.day == d) & Q.dep.notna()].dep, Q[(Q.day == d) & Q.dep.notna()].votes).correlation
                                               for d in days if ((Q.day == d) & Q.dep.notna()).sum() > 3], rng)
        return out
    alld = res["days"]; clean = [d for d in alld if d not in SELECTED]
    res["population_all_days"] = block(alld); res["population_clean_days"] = block(clean)
    res["population_oct_clean"] = block([d for d in clean if d < "2026-11-01"])
    res["population_nov_clean"] = block([d for d in clean if d >= "2026-11-01"])
    res["population_clean_without_nov7_8"] = block([d for d in clean if d not in ("2026-11-07", "2026-11-08")])
    # E5 item 4: does the person-sum EV explain what the launch model gets wrong? within-day Spearman of EV with
    # (real standing - LM standing), on days where every launch has an LM score; day-bootstrap CI
    rs = []
    for d in alld:
        g = Q[(Q.day == d)]
        if g.lm.isna().any() or len(g) < 5:
            continue
        resid = g.votes.rank(pct=True) - (-g.lm).rank(pct=True)   # lm holds the predicted rank (lower = better)
        rs.append(spearmanr(g.ev, resid).correlation)
    res["ev_vs_lm_residual_spearman"] = boot(rs, rng)
    res["clean_days"] = clean
    Q.to_parquet(f"{WORK}/pop_{TAG}{SFX()}.parquet")   # launch-level EV per day, read by `resid`
    Dg = pd.DataFrame(diag)
    res["n_eff_per_day"] = {r["day"]: round(r["n_eff"], 1) for r in diag}
    res["weights_diag"] = {"n_eff_median": round(float(Dg.n_eff.median()), 1), "people_median": int(Dg.people.median()),
                           "max_w_share_max": round(float(Dg.max_w_share.max()), 4), "top1pct_share_median": round(float(Dg.top1pct_share.median()), 3),
                           "spearman_weighted_real_vs_votes_median": round(float(Dg.spearman_weighted_real_vs_votes.median()), 3)}
    res["n_both_levels"] = {"person_days": int(Dg.people.sum()), "rows": int(Dg.rows.sum()), "days": len(Dg),
                            "note": "person metrics and launch EV use the same rows (complete people active in the 30 days before d x the line-up)"}
    pa = f"{WORK}/rows_tl_{TAG}/prior_assert.json"
    if os.path.exists(pa):
        res["prior_assert"] = json.load(open(pa))
    res["model_max_event_date"] = {os.path.basename(m): json.load(open(m[:-4] + ".json")).get("max_event_date") if os.path.exists(m[:-4] + ".json") else None
                                   for m in glob.glob(f"{WORK}/models_tl_{TAG}/model_*.pkl")}
    if os.environ.get("TL_FOL") == "1":
        res["follow_edges"] = {"rule": "only edges seen in the warehouse read observed 2026-10-26, used on days after it (no position propagation)",
                               "coverage_per_day": {os.path.basename(f)[:10]: json.load(open(f)) for f in sorted(glob.glob(f"{WORK}/rows_tl_{TAG}/*_fol.json"))}}
    else:
        res["follow_edges"] = "none (no follow features enter)"
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
    if recal is not None:
        res["recal_fit"] = recal["_fit"]
    out = os.path.join(HERE, "results", f"two_level_{TAG}{'_recal' if recal is not None else ''}_{res['weights']}.json")
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
    for f in sorted(f for f in glob.glob(f"{WORK}/rows_tl_{TAG}/*.parquet") if os.path.basename(f)[:2] == "20"):
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


def resid():
    """E5 Nov 11 01:35Z: the raw corr(EV, real - LM) is biased negative whenever EV correlates with the LM, so test EV's
    information beyond the LM honestly, on every day where the LM (honest backtest through Oct 24, live forecast from Oct 25)
    covers >= 90% of the scored line-up; launches without an LM score are dropped from that day.
    (a) partial Spearman: within day, rank(EV) residualised on rank(LM) by OLS, correlated with (real - LM) standing.
    (b) within-day regression of real standing (pct) on LM pct + EV pct, EV coefficient (pooled, day-bootstrap CI).
    (c) blend: within-day rank of LM pct + w * EV pct, w from a grid chosen leave-one-ISO-week-out (criterion mean of
        top 3 and top 5 hits), top 3/5/10 paired by day against the LM alone. Reads pop_<TAG>.parquet from `score`."""
    from pipeline import warehouse as W
    Q = pd.read_parquet(f"{WORK}/pop_{TAG}{SFX()}.parquet")
    lm = {}
    hp = os.environ.get("HONEST_PREDS")
    if hp and os.path.exists(hp):
        H = pd.read_parquet(hp); H["id"] = H.id.astype(str)
        lm.update({(str(r.day), r.id): float(r.honest) for r in H.itertuples()})
    Fc = W.query("SELECT CAST(launch_id AS VARCHAR) AS id, forecast_date::VARCHAR AS day, predicted_rank FROM forecasts WHERE model = 'launch_model'")
    lm.update({(r.day, r.id): -float(np.log(r.predicted_rank)) for r in Fc.itertuples()})   # higher = better
    Q["lms"] = [lm.get((d, x)) for d, x in zip(Q.day, Q.id)]
    cov = Q.groupby("day").lms.apply(lambda s: s.notna().mean())
    days = sorted(cov[cov >= 0.9].index)
    Q = Q[Q.day.isin(days) & Q.lms.notna()].copy()
    g = Q.groupby("day")
    Q["r_real"] = g.votes.rank(pct=True); Q["r_lm"] = g.lms.rank(pct=True); Q["r_ev"] = g.ev.rank(pct=True)
    rng = np.random.default_rng(0); res = {"tag": TAG, "days": days, "n_days": len(days),
                                           "lm_coverage": {d: round(float(cov[d]), 3) for d in days}}
    ps, raw = [], []
    for d, x in Q.groupby("day"):
        if len(x) < 5:
            continue
        b = np.polyfit(x.r_lm, x.r_ev, 1); ev_res = x.r_ev - np.polyval(b, x.r_lm)
        ps.append(spearmanr(ev_res, x.r_real - x.r_lm).correlation); raw.append(spearmanr(x.ev, x.r_real - x.r_lm).correlation)
    res["raw_residual_spearman"] = {"mean_ci_n": boot(raw, rng), "n_days": len(raw)}
    res["partial_spearman"] = {"mean_ci_n": boot(ps, rng), "n_days": len(ps)}
    res["spearman_ev_lm"] = {"mean_ci_n": boot([spearmanr(x.ev, x.lms).correlation for _, x in Q.groupby("day") if len(x) >= 5], rng)}

    def coef(ds):
        x = Q[Q.day.isin(ds)]; A = np.c_[np.ones(len(x)), x.r_lm, x.r_ev]
        return np.linalg.lstsq(A, x.r_real.values, rcond=None)[0]
    c = coef(days); bs = []
    for _ in range(2000):
        bs.append(coef(list(rng.choice(days, len(days))))[2])
    res["regression_real_on_lm_ev"] = {"coef_lm": round(float(c[1]), 3), "coef_ev": round(float(c[2]), 3),
                                       "coef_ev_ci": [round(float(np.percentile(bs, 2.5)), 3), round(float(np.percentile(bs, 97.5)), 3)], "n_days": len(days)}
    Q["week"] = pd.to_datetime(Q.day).dt.strftime("%G-W%V")
    ws = np.round(np.arange(0, 1.51, 0.05), 2)

    def hits(d, w, k):
        x = Q[Q.day == d]; top = set(x[x["rank"] <= k].id)
        if len(top) < k:
            return np.nan
        return len(set(x.assign(s=x.r_lm + w * x.r_ev).nlargest(k, "s").id) & top) / k * 100

    def crit(ds, w):
        return np.nanmean([(hits(d, w, 3) + hits(d, w, 5)) / 2 for d in ds])
    wk_of = dict(zip(Q.day, Q.week)); chosen = {}
    for wk in sorted(set(wk_of.values())):
        tr = [d for d in days if wk_of[d] != wk]
        chosen[wk] = float(max(ws, key=lambda w: crit(tr, w)))
    for k in (3, 5, 10):
        a = np.array([hits(d, 0.0, k) for d in days]); b = np.array([hits(d, chosen[wk_of[d]], k) for d in days])
        m = ~np.isnan(a) & ~np.isnan(b)
        res[f"blend_lowo top{k}"] = {"launch_model": round(float(a[m].mean()), 1), "blend": round(float(b[m].mean()), 1),
                                     "delta": boot((b - a)[m], rng), "n_days": int(m.sum())}
    res["blend_w_by_held_out_week"] = chosen
    json.dump(res, open(os.path.join(HERE, "results", f"two_level_resid_{TAG}{SFX()}.json"), "w"), indent=1); print(json.dumps(res, indent=1))


ACT_COLS = ["w_act", "days_since", "act_7", "log_act_30", "log_act_all", "tenure", "dow"]


def _label_maps():
    T = pd.read_parquet(f"{WORK}/tabs_v3.parquet"); T = T[T.tab == "upvotes"]
    read_day = dict(zip(T.person_id, pd.to_datetime(T.fetched_at, utc=True).dt.tz_convert("America/Los_Angeles").dt.strftime("%Y-%m-%d")))
    short = set(T[T["count"] < T.header.fillna(0) * 0.98].person_id)
    Eu = pd.read_parquet(f"{WORK}/events_cp.parquet"); Eu = Eu[Eu.kind == "upvote"]
    oldest = Eu.groupby("person").date.min().to_dict()
    def ok(persons, d):
        d2 = (pd.Timestamp(d) + pd.Timedelta(days=2)).strftime("%Y-%m-%d")
        return persons.map(lambda u: read_day.get(u, "0000") >= d2 and (u not in short or oldest.get(u, "9999") <= d)).values
    return ok, Eu


def choice():
    """Iteration 8 (pre-registered with E5, Nov 11): EV(L) = sum_p A_p * K_p * S_pL. A = P(any vote on the line-up | pre-d),
    K = E[# voted | active] (poisson), S = within-person-day share over the line-up (binary LightGBM on active person-days,
    normalised). Each part fitted on the previous month's label-filtered rows of the base tag (TL_BASE, default cp_unc;
    its X_<d>.parquet feature matrices); writes rows_tl_<TAG>/<d>.parquet for `score` with p = min(1, AKS), w = AKS / p
    (so EV = sum w*p is unclipped), and the parts' own test-day fits to results/two_level_choice_parts_<TAG>.json."""
    import lightgbm as lgb
    from sklearn.metrics import roc_auc_score, mean_poisson_deviance
    base = os.environ.get("TL_BASE", "cp_unc"); src = f"{WORK}/rows_tl_{base}"
    ok, Eu = _label_maps()
    up = {u: np.array(sorted(g.date.astype(str).str[:10]), dtype="datetime64[D]") for u, g in Eu.groupby("person")}
    def mean_daily(u, d):   # the person's mean upvotes per active upvote day, before d
        a = up.get(u)
        if a is None:
            return np.nan
        a = a[a < np.datetime64(d, "D")]
        return float(len(a) / len(np.unique(a))) if len(a) else np.nan
    def load(d, filt=True):
        X = pd.read_parquet(f"{src}/X_{d}.parquet")
        if filt:
            X = X[ok(X.person, d)]
        taste = [c for c in X.columns if c not in ["person", "id", "y"] + ACT_COLS]
        g = X.groupby("person")
        for c in taste:   # within-person-day contrasts over the line-up
            X[c + "_dm"] = X[c] - g[c].transform("mean"); X[c + "_rk"] = g[c].rank(pct=True)
        X["lineup_n"] = float(X.id.nunique())
        P = g.agg(**{c: (c, "first") for c in ACT_COLS}, k=("y", "sum")).reset_index()
        P["lineup_n"] = X.lineup_n.iloc[0]; P["a"] = (P.k > 0).astype(int)
        P["mean_daily"] = [mean_daily(u, d) for u in P.person]
        return X, P, taste
    days_all = sorted(os.path.basename(f)[2:12] for f in glob.glob(f"{src}/X_*.parquet"))
    test = [d for d in days_all if os.environ.get("TL_FROM", "2026-10-20") <= d <= os.environ.get("TL_TO", "2026-11-08")]
    A_COLS = ACT_COLS + ["lineup_n"]; K_COLS = A_COLS + ["mean_daily"]
    models, parts, rep = {}, [], {"base": base, "fit": {}}
    os.makedirs(f"{WORK}/rows_tl_{TAG}", exist_ok=True)
    for mon in sorted({d[:7] for d in test}):
        prev = (pd.Timestamp(mon + "-01") - pd.Timedelta(days=1)).strftime("%Y-%m")
        fit = [d for d in days_all if d[:7] == prev]
        Xs, Ps = [], []
        for d in fit:
            X, P, taste = load(d)
            Ps.append(P); Xs.append(X[X.person.isin(set(P[P.a == 1].person))])
        Xf, Pf = pd.concat(Xs), pd.concat(Ps)
        scols = taste + [c + s for c in taste for s in ("_dm", "_rk")] + ["lineup_n"]
        mA = lgb.LGBMClassifier(n_estimators=300, learning_rate=0.05, num_leaves=15, min_child_samples=50, verbose=-1, n_jobs=2).fit(Pf[A_COLS], Pf.a)
        act = Pf[Pf.a == 1]
        mK = lgb.LGBMRegressor(objective="poisson", n_estimators=300, learning_rate=0.05, num_leaves=15, min_child_samples=50, verbose=-1, n_jobs=2).fit(act[K_COLS], act.k)
        mS = lgb.LGBMClassifier(n_estimators=300, learning_rate=0.05, num_leaves=15, min_child_samples=50, verbose=-1, n_jobs=2).fit(Xf[scols], Xf.y)
        models[mon] = (mA, mK, mS, scols)
        rep["fit"][mon] = {"fit_month": prev, "fit_days": len(fit), "person_days": int(len(Pf)), "active_rate": round(float(Pf.a.mean()), 4),
                           "share_rows": int(len(Xf)), "mean_k_active": round(float(act.k.mean()), 3)}
    clipped = 0; total = 0
    for d in test:
        mA, mK, mS, scols = models[d[:7]]
        X, P, _ = load(d, filt=False)   # every row is scored (as at 00:05); the label filter applies in `score`
        P["A"] = mA.predict_proba(P[A_COLS])[:, 1]; P["K"] = np.maximum(mK.predict(P[K_COLS]), 1.0)   # K >= 1 given active
        X["s"] = mS.predict_proba(X[scols])[:, 1]; X["S"] = X.s / X.groupby("person").s.transform("sum")
        X = X.merge(P[["person", "A", "K"]], on="person")
        q = X.A * X.K * X.S; p = np.minimum(1.0, q); clipped += int((q > 1).sum()); total += len(q)
        R = pd.DataFrame({"person": X.person, "id": X.id, "w": (q / p).values, "p": p.values, "y": X.y.astype(int).values, "backed": 0.0, "day": d})
        R.to_parquet(f"{WORK}/rows_tl_{TAG}/{d}.parquet")
        import shutil
        shutil.copy(f"{src}/{d}_unseen.json", f"{WORK}/rows_tl_{TAG}/{d}_unseen.json")
        # parts' own fits on the test day, label-filtered
        m = ok(P.person, d); Pt = P[m]; Xt = X[ok(X.person, d)]
        at = Pt[Pt.a == 1]
        top1 = Xt[Xt.person.isin(set(at.person))].sort_values("S", ascending=False).groupby("person").y.first()
        parts.append({"day": d, "A_auc": float(roc_auc_score(Pt.a, Pt.A)) if Pt.a.nunique() > 1 else np.nan,
                      "K_poisson_dev": float(mean_poisson_deviance(at.k, at.K)) if len(at) else np.nan,
                      "K_poisson_dev_const": float(mean_poisson_deviance(at.k, np.full(len(at), max(1.0, at.k.mean())))) if len(at) else np.nan,
                      "S_top1_acc": float(top1.mean()) if len(top1) else np.nan, "active_people": int(len(at))})
    Pp = pd.DataFrame(parts); rng = np.random.default_rng(0)
    rep["parts"] = {c: boot(Pp[c].values, rng) for c in ("A_auc", "K_poisson_dev", "K_poisson_dev_const", "S_top1_acc")}
    rep["parts_per_day"] = parts; rep["clipped_rows"] = clipped; rep["rows"] = total
    json.dump(rep, open(os.path.join(HERE, "results", f"two_level_choice_parts_{TAG}.json"), "w"), indent=1, default=float)
    print(json.dumps({k: v for k, v in rep.items() if k != "parts_per_day"}, default=float))

if __name__ == "__main__":
    c = sys.argv[1]
    {"prepare": lambda: prepare(), "train": lambda: train(sys.argv[2]), "day": lambda: day(sys.argv[2]), "score": lambda: score(),
     "blend": lambda: blend(), "resid": lambda: resid(), "choice": lambda: choice()}[c]()
