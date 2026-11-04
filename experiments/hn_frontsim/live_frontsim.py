"""Live-page HN simulator on hn_minute (orchestrator, Nov 2): every post judged at 15 min with the REAL pages read live.
Inputs at the judging moment t = birth + 15 min (all read by then; birth = HN's item time from the public API):
  early votes     the latest points seen on /newest or /news at or before t
  /newest exposure  position-weighted (1/sqrt rank) minutes on /newest p1-p2 in [birth, t], over minutes the feed read
  real front page  /news p1-p3 read in the 3 minutes before t: each post's rank, points and age -> its HN score; scores
                  by rank made isotonic (penalties count where they sit); projected forward with the QN growth table
  arrivals         posts that first reached the front page after the same clock time on a replayed earlier day
                  (QN-reconstructed days, as frontsim.py)
  quality prior    at-posting score when provided (hn_jobs/cache/live_atposting/), else the flat training prior
Dynamics, exposure, penalties and tempering: the October-fitted frontsim model (frontsim_model.pkl).
Calibration first (orchestrator): per-day sum of P(top 30) vs winners, simulated vs real top-30 reach within 24 h and
24 h points. Then Caught (flags = winners, interval by posting day). Labels: settled listwatch lists (48 h after the
list day), the posting day through 3 days later, as live_caught.py.
Per-day list threshold: besides the pooled isotonic P(top 30 | 24 h points), each draw compares the simulated 24 h
points with the replayed day's own threshold (the 24 h points of its weakest non-re-up top-30 post).

    HNCACHE=... HNMIN=<dir with box/ and vm/ hn_minute jsonl> python live_frontsim.py [draws]
"""
import glob, io, json, os, pickle, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
import numpy as np, pandas as pd
import frontsim as F

HNMIN = os.environ.get("HNMIN", os.path.expanduser("~/.usersim_sim/hn_minute"))
B = "gs://usersim-bakeoff-347838016394/usersim_sim/hn_jobs/cache"
HERE = os.path.dirname(os.path.abspath(__file__))
rng = np.random.default_rng(0)


def sync():
    for src, pre in (("box", f"{B}/feeder/hn_minute/"), ("vm", f"{B}/feeder/vm/hn_minute/")):
        os.makedirs(os.path.join(HNMIN, src), exist_ok=True)
        subprocess.run(["gsutil", "-m", "-q", "rsync", "-x", r"^(?!20).*", pre, os.path.join(HNMIN, src)], check=False)
    os.makedirs(os.path.join(HNMIN, "listwatch"), exist_ok=True)
    subprocess.run(["gsutil", "-m", "-q", "rsync", f"{B}/listwatch/", os.path.join(HNMIN, "listwatch")], check=False)
    os.makedirs(os.path.join(HNMIN, "live_atposting"), exist_ok=True)
    subprocess.run(["gsutil", "-m", "-q", "rsync", f"{B}/live_atposting/", os.path.join(HNMIN, "live_atposting")], check=False)


def load_minute():
    rows = []
    for f in sorted(glob.glob(os.path.join(HNMIN, "box", "20*.jsonl")) + glob.glob(os.path.join(HNMIN, "vm", "20*.jsonl"))):
        for line in open(f):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            rows.append((r["id"], r["list"], r["page"], r["rank"], r.get("points"), r["fetched_at"]))
    M = pd.DataFrame(rows, columns=["id", "list", "page", "rank", "points", "t"])
    M["t"] = (pd.to_datetime(M.t, utc=True) - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(seconds=1)
    M = M.assign(_m=M.t // 60).drop_duplicates(["list", "page", "id", "_m"])
    M["pos"] = (M.page - 1) * 30 + M["rank"]
    return M


def item_times(ids):
    """HN item creation time (public API), cached."""
    cf = os.path.join(HNMIN, "item_time.json")
    c = json.load(open(cf)) if os.path.exists(cf) else {}
    todo = [i for i in ids if str(i) not in c]

    def get(i):
        for _ in range(3):
            try:
                out = subprocess.run(["curl", "-s", "-m", "10", f"https://hacker-news.firebaseio.com/v0/item/{i}.json"], capture_output=True, text=True).stdout
                return i, json.loads(out).get("time")
            except Exception:
                time.sleep(1)
        return i, None
    with ThreadPoolExecutor(32) as ex:
        for i, t in ex.map(get, todo):
            if t:
                c[str(i)] = t
    json.dump(c, open(cf, "w"))
    return {int(k): v for k, v in c.items()}


def settled_lists():
    L = []
    for f in glob.glob(os.path.join(HNMIN, "listwatch", "*.jsonl")):
        L.append(pd.read_json(f, lines=True, dtype={"day": str}, convert_dates=False))
    L = pd.concat(L) if L else pd.DataFrame(columns=["day", "read_at", "rank", "post_id"])
    out = {}
    for d, g in L.groupby("day"):
        s = g[g.read_at >= pd.Timestamp(d, tz="UTC").timestamp() + 86400 + 48 * 3600]
        if len(s):
            s = s[s.read_at == s.read_at.max()]
            out[d] = set(s[s["rank"] <= 30].post_id)
    return out


def day_thresholds(M_):
    """24 h points of each QN-reconstructed training day's weakest top-30 post posted that day (no re-ups)."""
    s = F.load_stories(); qn, RK, EX, UP = F.load_qn()
    L = pd.concat([pd.read_json(os.path.join(F.CACHE, f), lines=True, dtype={"day": str}) for f in ("frontday.jsonl", "frontday_old.jsonl")])
    L = L[L["rank"] <= 30]
    p24 = pd.Series(UP[:, F.H24 - 1], index=qn.post_id.to_numpy())
    born_day = s.set_index("post_id").day
    out = {}
    for d, g in L.groupby("day"):
        g = g[g.post_id.map(born_day) == d]
        v = g.post_id.map(p24).dropna()
        if len(v) >= 15:
            out[d] = float(v.min())
    return out


def features(M, born, ids, front_born, judge_min=15):
    """per post at t = birth + judge_min: latest points and their age, /newest weighted minutes, the real front page."""
    from sklearn.isotonic import IsotonicRegression
    iso = IsotonicRegression(increasing=False)
    M = M.sort_values("t")
    by_id = {i: g for i, g in M[M.id.isin(set(ids))].groupby("id")}
    newest_min = np.sort(M[M.list == "newest"].t.unique() // 60)
    front = M[M.list == "front"]; ft = front.t.to_numpy()
    out = []
    for i in ids:
        b = born[i]; t = b + judge_min * 60
        g = by_id.get(i)
        w = g[(g.t <= t) & (g.t >= b - 60)] if g is not None else None
        if w is not None and len(w):
            last = w.iloc[-1]; sc, a0 = float(last.points or 1), max((last.t - b) / 60, 0.5)
            nw = w[w.list == "newest"]
            mins = np.searchsorted(newest_min, last.t // 60, side="right") - np.searchsorted(newest_min, b // 60)
            xw = float((1 / np.sqrt(nw.assign(_m=nw.t // 60).drop_duplicates("_m")["pos"].clip(lower=1))).sum()) / max(mins, 1) * a0 if mins else np.nan
        else:
            sc, a0, xw = np.nan, np.nan, np.nan
        lo, hi = np.searchsorted(ft, t - 180), np.searchsorted(ft, t, side="right")
        fp = front.iloc[lo:hi].drop_duplicates("pos", keep="last").sort_values("pos")
        fp = fp[fp.id.map(front_born).notna()]
        ce = np.zeros(90); ca = np.zeros(90, int); cr = np.zeros(90, int); nfront = len(fp)
        if nfront >= 60:              # every position 1-90 gets a score: read ranks, interpolated in between
            fp = fp[fp.pos <= 90]
            age = (t - fp.id.map(front_born).to_numpy(float)) / 3600
            raw = np.clip(fp.points.fillna(1).to_numpy(float) - 1, 0, None) ** 0.8 / (np.clip(age, 0, None) + 2) ** 1.8
            pos = fp.pos.to_numpy(float); eff = iso.fit_transform(pos, raw)
            grid = np.arange(1, 91)
            ce = np.interp(grid, pos, eff); ag = np.interp(grid, pos, age)
            ca = np.searchsorted(MOD.ab, ag); cr = np.searchsorted(MOD.rb, grid)
        out.append((sc, a0, xw, nfront, ce, ca, cr))
    return out


def simulate(Mo, born, score, a0, xw, CE, CA, CR, wday_class, test_day, pool, thr, D=200, z=None, judge_min=15):
    """frontsim.simulate_live with the real front page from hn_minute; returns P(top 30) pooled isotonic and by the
    replayed day's own list threshold, the share of draws reaching the top 30, and mean 24 h points."""
    from scipy.stats import poisson
    n = len(born); h_born = ((born // 3600) % 24).astype(int)
    has = np.isfinite(score); a0 = np.where(has, a0, 0.0); v0 = np.where(has, score - 1, 0.0)
    E0 = Mo.cum_new(a0, h_born); E0l = Mo.early_E(born, a0, np.where(has, xw, np.nan))
    scale = np.ones(n) if z is None or not Mo.b else np.exp(Mo.b * (np.asarray(z) - Mo.zc))
    pri = Mo.prior if z is None or not Mo.b else Mo.prior_u
    post = pri[None, :] * (poisson.pmf(np.round(v0)[:, None].astype(int), np.clip((Mo.kappa * E0l * scale)[:, None], 1e-9, None) * Mo.grid[None, :]) + 1e-300) ** Mo.tau
    post /= post.sum(1, keepdims=True); cdf = np.cumsum(post, 1)
    q = Mo.grid[np.minimum((cdf[:, None, :] < rng.random((n, D))[:, :, None]).sum(2), len(Mo.grid) - 1)] * scale[:, None]
    if getattr(Mo, "sigma", 0):
        q = q * np.exp(Mo.sigma * rng.standard_normal(q.shape))
    pen = np.exp(rng.choice(Mo.pen, (n, D)))
    td = pd.Timestamp(test_day)
    dd = rng.choice(len(pool), (n, D))
    shs = np.array([(td - pd.Timestamp(d)).days * 144 for d in pool])[dd]
    thr_d = np.array([thr[d] for d in pool])[dd]
    cs = ((born + judge_min * 60 - Mo.T0) // 600).astype(int)
    f0 = (np.floor(born / 600) + 1) * 600
    P = (1 + v0[:, None] + rng.poisson(q * np.clip(Mo.cum_new((f0 - born) / 60, h_born) - E0, 0, None)[:, None])).astype(float)
    cut_hist = cs[:, None] - shs; best = np.full((n, D), 91)
    for k in range(F.H24):
        tau = f0 + 600 * k; h = ((tau // 3600) % 24).astype(int); age = (tau - born) / 3600
        sc = np.clip(P - 1, 0, None) ** 0.8 / (age[:, None] + 2) ** 1.8 * pen
        slot = ((tau - Mo.T0) // 600).astype(int)
        dl = np.clip(slot - cs, 0, F.H24 + 1)
        ce = CE * Mo.RG[CA, CR, dl[:, None]]
        n_comp = (ce[:, None, :] > sc[..., None]).sum(-1)
        hs = np.clip(slot[:, None] - shs, 0, len(Mo.EFF) - 1)
        HJ = Mo.JJ[hs]; HE = Mo.EFF[hs]
        arr = (HJ >= 0) & (Mo.FIRST[np.maximum(HJ, 0)] > cut_hist[..., None])
        rank = 1 + n_comp + ((HE > sc[..., None]) & arr).sum(-1)
        e = np.where(rank <= 90, Mo.f_rank[np.clip(rank, 1, 90) - 1] * Mo.m_front[h][:, None], Mo.g_off[k + 1] * Mo.m_off[h][:, None])
        P += rng.poisson(q * e); best = np.minimum(best, rank)
    return (Mo.g.predict(np.log1p(P).ravel()).reshape(n, D).mean(1), (P >= thr_d).mean(1), (best <= 30).mean(1), np.median(P, 1), np.log1p(P).mean(1))


MOD = None


def replay(Mo, born, score, a0, xw, wday_class, test_day, pool, thr, D=200):
    """front page = the replayed earlier day's (isotonic curve per slot), as frontsim.Model.simulate."""
    n = len(born)
    p_iso, P = Mo.simulate(born, score, a0, wday_class, test_day, {wday_class: pool}, D, xw=xw)
    return p_iso, np.full(n, np.nan), Mo.last_top30, np.median(P, 1), np.log1p(P).mean(1)


def main(D=200):
    t0 = time.time(); sync()
    import __main__; __main__.Model = F.Model
    Mo = pickle.load(open(os.path.join(F.CACHE, "frontsim_model.pkl"), "rb"))
    # early-vote tempering for the prior in use (flat until an at-posting score exists), on posts Jul 14 - Oct 12
    s = F.load_stories(); s["z"] = 0.0; sc_, a0_ = F.early(s); xw_ = F.newest_exposure(s, a0_)
    Mo.b = 0.0; Mo.fit_early(s, sc_, a0_, xw_, "2026-10-12"); print("tempering (QN likelihood)", Mo.early_log, flush=True)
    # outcome calibration (calib_fit.py, Oct 2-9: real top-30 reach per post) replaces the QN-likelihood tempering
    cfile = os.environ.get("CALIB", os.path.join(HERE, "out", "calib_fit.json"))   # e.g. calib_2025_grid2_results.json
    cf = json.load(open(cfile))["best"]
    Mo.tau, Mo.kappa = cf["tau"], cf["kappa"]; Mo.grid = Mo.grid * cf["c"]; Mo.sigma = cf.get("sigma", 0.0); print("outcome calibration", cf, flush=True)
    M = load_minute()
    new = M[M.list == "newest"].sort_values("t")
    first = new.drop_duplicates("id")
    first = first[(first.pos <= 5) & (first.t >= M.t.min() + 600)]
    ids = first.id.tolist()
    front_ids = M[M.list == "front"].id.unique().tolist()
    born = item_times(sorted(set(ids) | set(front_ids)))
    P = pd.DataFrame({"id": [i for i in ids if i in born]}); P["born"] = P.id.map(born).astype(float)
    P["day"] = pd.to_datetime(P.born, unit="s", utc=True).dt.strftime("%Y-%m-%d")
    cov = M.assign(d=pd.to_datetime(M.t, unit="s", utc=True).dt.strftime("%Y-%m-%d")).groupby(["d", "list"]).t.apply(lambda x: x.floordiv(60).nunique()).unstack()
    full_days = [d for d in cov.index if cov.loc[d].get("newest", 0) >= 1300 and cov.loc[d].get("front", 0) >= 1000]
    print("feed minutes by day\n", cov, "\nfull days", full_days, flush=True)
    P = P[P.day.isin(full_days)].reset_index(drop=True)
    print(f"{len(P)} posts on full days, {time.time() - t0:.0f}s", flush=True)
    global MOD
    MOD = Mo
    fb = {i: born.get(i) for i in front_ids}
    ap = {}
    for f in glob.glob(os.path.join(HNMIN, "live_atposting", "*.parquet")):
        A = pd.read_parquet(f); ap.update(dict(zip(A.post_id, A.p_top30)))
    P["has_atposting"] = P.id.isin(ap)
    feats = features(M, born, P.id.tolist(), fb)
    P["score"], P["a0"], P["xw"], P["n_front"] = [np.array([f[j] for f in feats], float) for j in range(4)]
    CE = np.stack([f[4] for f in feats]); CA = np.stack([f[5] for f in feats]); CR = np.stack([f[6] for f in feats])
    print(f"features {time.time() - t0:.0f}s; snapshot by 15 min {np.isfinite(P.score).mean():.1%}, front page read {(P.n_front >= 80).mean():.1%} (80+ ranks); "
          f"at-posting score {P.has_atposting.mean():.1%}", flush=True)
    thr = day_thresholds(Mo)
    cls = lambda d: int(pd.Timestamp(d).dayofweek >= 5)
    okd = pd.Series(np.isfinite(Mo.ISO[:, 0]), index=pd.to_datetime(Mo.T0 + 600 * np.arange(len(Mo.ISO)), unit="s").strftime("%Y-%m-%d")).groupby(level=0).mean()
    good = [d for d in sorted(thr) if okd.get(d, 0) >= 0.9 and okd.get(str((pd.Timestamp(d) + pd.Timedelta(days=1)).date()), 0) >= 0.9]
    for c in ("p_iso", "p_thr", "sim_top30", "sim_p24", "sim_log1p"):
        P[c] = np.nan
    P["real_front"] = P.n_front >= 60
    for d in sorted(P.day.unique()):
        pool = [x for x in good if cls(x) == cls(d)]
        for rf in (True, False):
            m = ((P.day == d) & (P.real_front == rf)).to_numpy()
            if not m.any():
                continue
            if rf:
                r = simulate(Mo, P.born.to_numpy()[m], P.score.to_numpy()[m], P.a0.to_numpy()[m], P.xw.to_numpy()[m], CE[m], CA[m], CR[m], cls(d), d, pool, thr, D)
            else:                      # front page not read at t: the replayed earlier day only (frontsim.simulate)
                r = replay(Mo, P.born.to_numpy()[m], P.score.to_numpy()[m], P.a0.to_numpy()[m], P.xw.to_numpy()[m], cls(d), d, pool, thr, D)
            for c, v in zip(("p_iso", "p_thr", "sim_top30", "sim_p24", "sim_log1p"), r):
                P.loc[m, c] = v
        print(d, int(m.sum()), f"{time.time() - t0:.0f}s", flush=True)
    # real outcomes from the feed: reached the top 30 within 24 h, max points seen within 24 h (when 24 h have passed)
    end = M.t.max(); Mi = M.merge(P[["id", "born"]], on="id"); Mi = Mi[Mi.t <= Mi.born + 86400]
    P["done24"] = P.born + 86400 <= end
    P["real_top30"] = P.id.map(Mi[(Mi.list == "front") & (Mi.pos <= 30)].groupby("id").size()).fillna(0).gt(0)
    P["real_p24"] = P.id.map(Mi.groupby("id").points.max()).fillna(1)
    settled = settled_lists()
    P["settled"] = [all((pd.Timestamp(d) + pd.Timedelta(days=k)).strftime("%Y-%m-%d") in settled for k in range(4)) for d in P.day]
    P["y"] = [int(any(i in settled.get((pd.Timestamp(d) + pd.Timedelta(days=k)).strftime("%Y-%m-%d"), ()) for k in range(4))) for i, d in zip(P.id, P.day)]
    res = {"made_at": int(time.time()), "feed_end_utc": str(pd.Timestamp(end, unit="s")), "full_days": full_days, "posts": int(len(P)), "draws": D,
           "inputs": {"snapshot_by_15min": round(float(np.isfinite(P.score).mean()), 3), "front_page_80plus_ranks": round(float((P.n_front >= 80).mean()), 3), "real_front_used (60+ ranks)": round(float((P.n_front >= 60).mean()), 3),
                      "at_posting_score": round(float(P.has_atposting.mean()), 3), "prior": "flat (the live at-posting score is loaded for coverage only; not used in the prior)",
                      "early_votes_and_scale": f"outcome fit from {os.path.basename(cfile)}: tau {cf['tau']}, kappa {cf['kappa']}, c {cf['c']}, sigma {cf.get('sigma', 0)}"},
           "calibration_24h": {}, "caught": {}}
    Dn = P[P.done24]
    for d, g in Dn.groupby("day"):
        res["calibration_24h"][d] = {"posts_with_24h": int(len(g)), "reach_top30_real": round(float(g.real_top30.mean()), 4),
                                     "reach_top30_sim": round(float(g.sim_top30.mean()), 4), "sum_reach_real": int(g.real_top30.sum()),
                                     "sum_reach_sim": round(float(g.sim_top30.sum()), 1),
                                     "median_p24_real": float(g.real_p24.median()), "median_p24_sim (median over draws)": float(g.sim_p24.median()),
                                     "mean_log1p_p24_real": round(float(np.log1p(g.real_p24).mean()), 3), "mean_log1p_p24_sim": round(float(g.sim_log1p.mean()), 3),
                                     "note_real_p24": "max points seen in the feed within 24 h (undercounts posts that left /newest p2 and the front page)"}
        b = pd.cut(g.score, [0, 1, 2, 3, 1e9], labels=["1", "2", "3", "4+"])
        res["calibration_24h"][d]["reach_by_15min_score [real, sim, n]"] = {str(k): [round(float(x.real_top30.mean()), 3), round(float(x.sim_top30.mean()), 3), int(len(x))]
                                                                           for k, x in g.groupby(b, observed=True)}
    for d, g in P.groupby("day"):
        res["calibration_24h"].setdefault(d, {}).update(sum_P_isotonic=round(float(g.p_iso.sum()), 1), sum_P_day_threshold=round(float(g.p_thr.sum()), 1),
                                                        winners_so_far=int(g.y.sum()), lists_settled=bool(g.settled.all()))
    S_ = P[P.settled]
    if len(S_) and S_.y.sum():
        rq = lambda c: F.ci(F.caught_on(S_.rename(columns={}), S_[c] + 1e-12 * rng.random(len(S_))))
        S_ = S_.assign(pts15=np.nan_to_num(S_.score, nan=1))
        res["caught"] = {"winners": int(S_.y.sum()), "days": sorted(S_.day.unique()), "points at 15 min": rq("pts15"),
                         "simulator (isotonic)": rq("p_iso"), "simulator (day threshold)": rq("p_thr")}
    else:
        res["caught"] = "no posting day has its 4 list days settled yet"
    os.makedirs(os.path.join(HERE, "out"), exist_ok=True)
    P.drop(columns=[]).to_parquet(os.path.join(HERE, "out", "live_posts.parquet"), index=False)
    json.dump(res, open(os.path.join(HERE, "out", "live_frontsim" + ("_" + os.path.basename(cfile).replace(".json", "") if os.environ.get("CALIB") else "") + ".json"), "w"), indent=1)
    print(json.dumps(res, indent=1))

if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 200)
