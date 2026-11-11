"""Early-day forecast (orchestrator Nov 11): rank the day's launches at fixed points after the vote REVEAL, from data up
to that minute only.
  R0     the first 15-min snapshot (raw/ph_at_launch/<d>/live/posts_ts.jsonl) where vote counts are readable (sum of
         votes_at_fetch > 0; the hide flag can lag a snapshot); points R0, R0+1h, R0+2h, R0+4h
Features at point t (snapshots with snapshot_ts <= t only): votes at t, votes at R0, velocity (votes_t - votes_R0) per
hour since R0, comments at t, the 00:05 LM score (-log predicted_rank, forecasts table, model launch_model), hour of t
(PT), line-up size. Scorers: (a) raw votes at t; (b) LM + votes blend: z(log1p votes) + w z(LM), w by leave-one-day-out;
(c) LightGBM lambdarank on the features, leave-one-day-out. Labels: final daily_rank (warehouse launches).
usage: python early_forecast.py live <day> <point: R0|R1|R2|R4> [method]   -> writes results/early_forecast/<day>_<point>.json
       python early_forecast.py replay                                       -> results/early_forecast_replay.json
Counts and launch ids only."""
import glob, json, os, subprocess, sys, tempfile
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
B = "gs://usersim-bakeoff-347838016394/usersim_sim"
POINTS = {"R0": 0, "R1": 1, "R2": 2, "R4": 4}


def load_snaps(day, path=None):
    if path is None:
        tmp = tempfile.mkdtemp(prefix="ef_"); path = f"{tmp}/posts.jsonl"
        subprocess.run(["gsutil", "-q", "cp", f"{B}/raw/ph_at_launch/{day}/live/posts_ts.jsonl", path], check=True)
    rows = []
    for l in open(path):
        r = json.loads(l)
        if r.get("fetch_status") == 200 and str(r.get("day", day)) == day:
            rows.append((pd.Timestamp(r["snapshot_ts"]), str(r["launch_id"]), float(r.get("votes_at_fetch") or 0),
                         float(r.get("comments_count_at_fetch") or 0), bool(r.get("hide_votes_count"))))
    return pd.DataFrame(rows, columns=["ts", "id", "v", "c", "hid"])


def reveal(T):
    g = T.groupby("ts").agg(v=("v", "sum"), hid=("hid", "mean")).sort_index()
    ok = g[g.v > 0]   # first snapshot where the API returns vote counts (the hide flag can lag by a snapshot)
    return ok.index.min() if len(ok) else None


def features(T, t, R0, lm, day):
    A = T[T.ts <= t].sort_values("ts").groupby("id").last()[["v", "c"]]
    V0 = T[T.ts <= R0].sort_values("ts").groupby("id").v.last()
    A["v0"] = V0.reindex(A.index).fillna(0); hrs = max((t - R0).total_seconds() / 3600, 0.25)
    A["vel"] = (A.v - A.v0) / hrs
    A["lm"] = [lm.get(x, np.nan) for x in A.index]
    A["lm"] = A.lm.fillna(A.lm.min() - 1 if A.lm.notna().any() else 0)
    A["hour"] = t.tz_convert("America/Los_Angeles").hour + t.minute / 60; A["lineup"] = len(A)
    A["lv"] = np.log1p(A.v); A["lvel"] = np.log1p(A.vel.clip(lower=0)); A["lc"] = np.log1p(A.c)
    A["day"] = day
    return A.reset_index()


def lm_scores(day):
    from pipeline import warehouse as W
    F = W.query(f"SELECT CAST(launch_id AS VARCHAR) AS id, predicted_rank FROM forecasts WHERE model = 'launch_model' AND forecast_date = '{day}'", do_sync=False)
    return {r.id: -float(np.log(r.predicted_rank)) for r in F.itertuples()}


def z(x):
    x = np.asarray(x, float); return (x - x.mean()) / (x.std() + 1e-9)


def live(day, point, method="blend", w=None):
    T = load_snaps(day); R0 = reveal(T)
    if R0 is None:
        print(json.dumps({"day": day, "point": point, "status": "no reveal yet"})); return
    t = R0 + pd.Timedelta(hours=POINTS[point])
    now = pd.Timestamp.now(tz="UTC")
    if T.ts.max() < t:
        print(json.dumps({"day": day, "point": point, "status": f"point {t} not reached; latest snapshot {T.ts.max()}"})); return
    lm = lm_scores(day); A = features(T, t, R0, lm, day)
    if w is None:
        w = float(os.environ.get("EF_W", "0.5"))
    if method == "votes":
        A["score"] = A.lv + 1e-6 * A.lm
    else:
        A["score"] = z(A.lv) + w * z(A.lm)
    A["pred_rank"] = A.score.rank(ascending=False, method="first").astype(int)
    out = {"day": day, "point": point, "reveal_R0": R0.isoformat(), "data_up_to": t.isoformat(), "method": method, "w_lm": w,
           "launches": int(len(A)), "lm_matched": int(sum(1 for x in A.id if x in lm)), "written_at": now.isoformat(),
           "forecast": A.sort_values("pred_rank")[["id", "pred_rank", "v", "v0", "vel", "c", "lm", "score"]].round(4).to_dict("records")}
    os.makedirs(os.path.join(HERE, "results", "early_forecast"), exist_ok=True)
    p = os.path.join(HERE, "results", "early_forecast", f"{day}_{point}.json"); json.dump(out, open(p, "w"), indent=1)
    subprocess.run(["gsutil", "-q", "cp", p, f"{B}/results/early_forecast/{day}_{point}.json"], check=True)
    print(json.dumps({k: v for k, v in out.items() if k != "forecast"}))


if __name__ == "__main__":
    if sys.argv[1] == "live":
        live(sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else "blend")


def replay():
    """Replay on the hourly warehouse vote_snapshots (the pipeline's recorder) for days whose snapshots start before the
    reveal. Features as in live(); scorers LM-only (00:05 reference), votes, projected votes (v + vel x hours left to
    23:59 PT), blend (w by LODO), LightGBM lambdarank (LODO). Daily top 3/5/10 with day-bootstrap CIs; earliest point
    with all three >= 90. Weekly / monthly: at each day's R0+2h, cumulative final votes of the week's / month's earlier
    days + the day's projection, vs final weekly / monthly ranks."""
    from pipeline import warehouse as W
    import lightgbm as lgb
    rng = np.random.default_rng(0)
    D = W.query('SELECT "day" AS d, "at" AS t, launch_id AS id, votes AS v, comments AS c FROM vote_snapshots WHERE "day" >= \'2026-10-25\'', do_sync=False)
    D["ts"] = pd.to_datetime(D.t, utc=True); D["id"] = D.id.astype(str)
    L = W.query("SELECT CAST(id AS VARCHAR) AS id, day::VARCHAR AS day, daily_rank, weekly_rank, monthly_rank, votes FROM launches WHERE day::VARCHAR >= '2026-10-01'", do_sync=False)
    F = W.query("SELECT CAST(launch_id AS VARCHAR) AS id, forecast_date AS day, predicted_rank FROM forecasts WHERE model = 'launch_model'", do_sync=False)
    days = []
    for d, x in D.groupby("d"):
        s = x.groupby("ts").v.sum().sort_index(); nz = s[s > 0]
        if not len(nz) or s.index.min() >= nz.index.min() or (L[(L.day == d)].daily_rank.notna().sum() < 10) or not (F.day == d).any():
            continue   # need a zero-vote snapshot before the reveal, final ranks and an LM forecast
        days.append(d)
    rows = []
    for d in days:
        x = D[D.d == d].rename(columns={"v": "v", "c": "c"}); x["hid"] = False
        R0 = x.groupby("ts").v.sum().pipe(lambda s: s[s > 0].index.min())
        lm = {r.id: -float(np.log(r.predicted_rank)) for r in F[F.day == d].itertuples()}
        Ld = L[(L.day == d) & L.daily_rank.notna()]
        for p, h in POINTS.items():
            t = R0 + pd.Timedelta(hours=h)
            A = features(x[["ts", "id", "v", "c", "hid"]], t, R0, lm, d).set_index("id").reindex(Ld.id)
            A["lm"] = [lm.get(i, np.nan) for i in A.index]; A["lm"] = A.lm.fillna(A.lm.min() - 1)
            A[["v", "c", "v0", "vel", "lv", "lvel", "lc"]] = A[["v", "c", "v0", "vel", "lv", "lvel", "lc"]].fillna(0)
            A["hour"] = t.tz_convert("America/Los_Angeles").hour; A["lineup"] = len(A); A["day"] = d; A["point"] = p
            left = (pd.Timestamp(d).tz_localize("America/Los_Angeles") + pd.Timedelta(hours=24) - t).total_seconds() / 3600
            A["proj"] = np.log1p(A.v + A.vel.clip(lower=0) * left)
            A["rank"] = Ld.set_index("id").daily_rank; A["final"] = Ld.set_index("id").votes
            rows.append(A.reset_index())
    X = pd.concat(rows, ignore_index=True)
    X["lm_z"] = X.groupby(["day", "point"]).lm.transform(lambda s: (s - s.mean()) / (s.std() + 1e-9))
    X["lv_z"] = X.groupby(["day", "point"]).lv.transform(lambda s: (s - s.mean()) / (s.std() + 1e-9))
    X["pj_z"] = X.groupby(["day", "point"]).proj.transform(lambda s: (s - s.mean()) / (s.std() + 1e-9))

    def topk(g, col, k):
        return len(set(g.nlargest(k, col).id) & set(g.nsmallest(k, "rank").id)) / k * 100
    def dayscore(col, p, sub=None):
        return {d: [topk(g, col, k) for k in (3, 5, 10)] for d, g in X[X.point == p].groupby("day") if sub is None or d in sub}
    WG = [0, 0.1, 0.2, 0.3, 0.5, 0.75, 1.0, 1.5, 2.0]
    for p in POINTS:
        for d in days:   # LODO weight for the blend (votes and projected) and LightGBM
            m = (X.point == p) & (X.day != d); te = (X.point == p) & (X.day == d)
            for base, nm in (("lv_z", "blend"), ("pj_z", "blend_proj")):
                best = max(WG, key=lambda w: np.mean([np.mean([topk(g.assign(s=g[base] + w * g.lm_z), "s", k) for k in (3, 5, 10)]) for _, g in X[m].groupby("day")]))
                X.loc[te, nm] = X.loc[te, base] + best * X.loc[te, "lm_z"]; X.loc[te, nm + "_w"] = best
            tr = X[m].sort_values("day"); grp = tr.groupby("day").size().values
            fe = ["lv", "lvel", "lc", "lm_z", "proj", "lineup"]
            y = (tr["rank"].max() + 1 - tr["rank"]).clip(lower=0); y = np.clip(31 - tr["rank"], 0, 30).astype(int)
            mdl = lgb.LGBMRanker(n_estimators=150, learning_rate=0.05, num_leaves=7, min_child_samples=5, verbose=-1, label_gain=list(range(31)))
            mdl.fit(tr[fe], y, group=grp); X.loc[te, "gbm"] = mdl.predict(X.loc[te, fe])
    res = {"source": "warehouse vote_snapshots (hourly, the pipeline recorder); R0 = first hourly snapshot with votes > 0 (12:00Z on all days)",
           "days": days, "excluded": "Oct 31, Nov 1, Nov 6, Nov 7: snapshots start after the reveal; Nov 5: no snapshots; Nov 11: no final ranks yet",
           "points": {}, "earliest_all_ge_90": {}}
    def b(v):
        v = np.asarray(v, float)
        return [round(float(v.mean()), 1)] + [round(float(x), 1) for x in np.percentile([v[rng.integers(0, len(v), len(v))].mean() for _ in range(5000)], [2.5, 97.5])]
    for p in POINTS:
        r = {}
        for col, nm in (("lm", "LM 00:05 (reference)"), ("lv", "(a) votes"), ("proj", "(a2) projected votes"), ("blend", "(b) votes + LM blend"),
                        ("blend_proj", "(b2) projected + LM blend"), ("gbm", "(c) LightGBM rank LODO")):
            sc = dayscore(col, p); arr = np.array(list(sc.values()))
            r[nm] = {f"top{k}": b(arr[:, i]) for i, k in enumerate((3, 5, 10))}
            if col != "lm":
                ref = np.array(list(dayscore("lm", p).values()))
                r[nm]["delta_vs_LM"] = {f"top{k}": b(arr[:, i] - ref[:, i]) for i, k in enumerate((3, 5, 10))}
            r[nm]["per_day"] = {d: v for d, v in sc.items()}
        r["blend_w_chosen"] = X[X.point == p].groupby("day").blend_w.first().to_dict()
        res["points"][p] = r
    for nm in res["points"]["R0"]:
        if nm == "blend_w_chosen":
            continue
        hit = [p for p in POINTS if all(res["points"][p][nm][f"top{k}"][0] >= 90 for k in (3, 5, 10))]
        res["earliest_all_ge_90"][nm] = hit[0] if hit else "none by R0+4h"
    # weekly / monthly at R0+2h: cumulative final votes of earlier days in the period + today's projection (blend_proj scale -> votes)
    per = {"week": [], "month": []}
    Lr = L.copy(); Lr["wk"] = pd.to_datetime(Lr.day).dt.strftime("%G-W%V"); Lr["mo"] = Lr.day.str[:7]
    for d in days:
        g = X[(X.point == "R2") & (X.day == d)].set_index("id")
        today = np.expm1(g.proj)   # projected final votes from votes + velocity
        for kind, key, rk in (("week", "wk", "weekly_rank"), ("month", "mo", "monthly_rank")):
            pk = Lr[Lr.day == d][key].iloc[0]
            P = Lr[(Lr[key] == pk) & (Lr.day < d)][["id", "votes", rk]].copy(); P["est"] = P.votes
            T_ = Lr[(Lr.day == d)][["id", "votes", rk]].copy(); T_["est"] = T_.id.map(today)
            C = pd.concat([P, T_]).dropna(subset=["est"])
            truth = Lr[(Lr[key] == pk) & Lr[rk].notna()]
            if truth[rk].min() > 1 or len(truth) < 10:
                continue
            row = {"day": d, "period": pk}
            for k in (3, 5, 10):
                real = set(truth.nsmallest(k, rk).id); reach = len(real & set(C.id))
                row[f"top{k}"] = len(set(C.nlargest(k, "est").id) & real) / k * 100; row[f"top{k}_reachable"] = reach / k * 100
            per[kind].append(row)
    res["period_lists_at_R2"] = {kind: {"rows": v, **({f"top{k}": round(float(np.mean([r[f"top{k}"] for r in v])), 1) for k in (3, 5, 10)} if v else {})} for kind, v in per.items()}
    json.dump(res, open(os.path.join(HERE, "results", "early_forecast_replay.json"), "w"), indent=1, default=float)
    for p in POINTS:
        print(p, {nm: [v[f"top{k}"][0] for k in (3, 5, 10)] for nm, v in res["points"][p].items() if nm != "blend_w_chosen"})
    print("earliest", res["earliest_all_ge_90"]); print("periods", {k: {kk: vv for kk, vv in v.items() if kk != "rows"} for k, v in res["period_lists_at_R2"].items()})


if __name__ == "__main__" and sys.argv[1] == "replay":
    replay()
