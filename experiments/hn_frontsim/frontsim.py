"""HN front-page dynamics simulator, scored on Caught at 15 min (Shreyas, Nov 2).

Each post is judged once, 15 minutes after posting, with what is known then: its latest Wayback /newest snapshot at or
before 15 min (score, age) and the posting time. The simulator rolls its next 24 h forward on HN's front page:
  quality      q: upvotes per unit of exposure (Quality News units: a typical post at a given rank and time gets 1x).
               Prior: nonparametric (NPMLE on a grid) over all training posts; posterior from the early votes:
               votes - 1 ~ Poisson(q * exposure so far on /newest).
  exposure     per 10 min, from Quality News' series (qn_exp_10m): by front-page rank (1-90) x hour of day, and off the
               front page (/newest and beyond) by age x hour.
  rank         HN's score (points - 1)^0.8 / (age_h + 2)^1.8 x the post's penalty, placed against the front page of a
               random earlier day (same clock time, same weekday/weekend class): that slot's scores by rank (isotonic in
               rank, so penalised posts count where they sat). Penalty per draw from the training residuals.
  votes        per 10 min ~ Poisson(q * exposure(rank, hour)); 24 h of steps.
  winner       P(made a daily top 30 | 24 h points), isotonic on training posts (includes later re-ups as they happen).
P(top 30) = mean over draws. Caught: flag k = #winners highest across the test period, share of winners flagged,
95% interval resampling posting days (caught.py / wb_caught.py conventions). Training (all fitted parts, front pages):
posts Jul 14 - Sep 30; test Oct 2-14 (dense /newest captures); front-page days drawn from Jul 15 .. test day - 3.
Leakage: the test post's own Quality News series is never read (it exists only for posts ending with 5+ points).

    HNCACHE=<dir with qn_full_*.jsonl, bq_stories.parquet, frontday*.jsonl, early_votes/> python frontsim.py [draws]
"""
import glob, json, os, sys, time
import numpy as np, pandas as pd
from sklearn.isotonic import IsotonicRegression

CACHE = os.environ.get("HNCACHE", os.path.expanduser("~/.usersim_sim"))
HERE = os.path.dirname(os.path.abspath(__file__))
TRAIN = ("2026-07-14", "2026-09-30")
TEST = ("2026-10-02", "2026-10-14")
NB = 216                      # Quality News 10-minute bins (36 h)
H24 = 144
rng = np.random.default_rng(0)
AT_COLS = []


def load_qn():
    rows = []
    for f in sorted(glob.glob(os.path.join(CACHE, "qn_full_*.jsonl"))):
        for line in open(f):
            try:
                rows.append(json.loads(line))
            except ValueError:
                pass
    q = pd.DataFrame(rows)
    q = q[(q.status == 200) & q.qn_up_10m.map(lambda x: isinstance(x, list))].drop_duplicates("post_id").reset_index(drop=True)
    RK = np.array([[x if x is not None else np.nan for x in r] for r in q.qn_rank_10m], float)
    EX = pd.DataFrame(list(q.qn_exp_10m), dtype=float).ffill(axis=1).fillna(0).to_numpy()
    UP = pd.DataFrame(list(q.qn_up_10m), dtype=float).ffill(axis=1).fillna(1).to_numpy()
    return q[["post_id", "qn_f0"]], RK, EX, UP


def load_stories():
    s = pd.read_parquet(os.path.join(CACHE, "bq_stories.parquet"), columns=["post_id", "title", "points", "created_at_i", "day"])
    s = s[s.title.notna()].drop_duplicates("post_id").drop(columns="title")
    s["points"] = s.points.fillna(0).astype(float)
    s = s[(s.day >= "2026-07-01") & (s.day <= "2026-10-14")].reset_index(drop=True)
    L = pd.concat([pd.read_json(os.path.join(CACHE, f), lines=True, dtype={"day": str}) for f in ("frontday.jsonl", "frontday_old.jsonl")])
    s["y"] = s.post_id.isin(set(L[L["rank"] <= 30].post_id)).astype(int)
    return s


def at_posting(s):
    """At-posting score z (no votes, no comments of the post): LightGBM on log1p(final points) over the HN agent's
    at-posting inputs (daily_cache: text_score + b_*, without the b_w30_/b_w60_ windows). Training stories
    (Jul 1 - Sep 30) get out-of-fold scores (5 folds by posting day); later stories a model fit on all of them."""
    import lightgbm as lgb
    X = s[["post_id", "day", "points"]]; cols = []
    for f in ("caught_post_feats.parquet", "daily_cache.parquet", "audience_feats.parquet", "crowd_v2_feats.parquet", "hist_prior.parquet"):
        if not os.path.exists(os.path.join(CACHE, f)):
            continue
        B = pd.read_parquet(os.path.join(CACHE, f))
        c = [x for x in B.columns if x != "post_id" and B[x].dtype != object and x not in cols
             and (f not in ("daily_cache.parquet", "caught_post_feats.parquet") or x == "text_score" or (x.startswith("b_") and not x.startswith(("b_w30_", "b_w60_"))))]
        if not c or B.post_id.isin(s.post_id[s.day >= TEST[0]]).sum() < 0.9 * (s.day >= TEST[0]).sum():
            print("at-posting: skip", f, "(does not cover the test days)", flush=True); continue
        X = X.merge(B[["post_id"] + c].drop_duplicates("post_id"), on="post_id", how="left"); cols += c
    print("at-posting inputs", len(cols), flush=True)
    AT_COLS[:] = cols
    prm = dict(n_estimators=500, learning_rate=0.03, num_leaves=31, min_child_samples=50, subsample=0.8, subsample_freq=1,
               colsample_bytree=0.8, verbose=-1, random_state=0)
    tr = (X.day <= TRAIN[1]).to_numpy(); y = np.log1p(X.points.to_numpy())
    z = np.full(len(X), np.nan)
    days = np.array(sorted(X.day[tr].unique())); fold = {d: i % 5 for i, d in enumerate(days)}
    f = X.day.map(fold).to_numpy()
    for i in range(5):
        a, b = tr & (f != i), tr & (f == i)
        z[b] = lgb.LGBMRegressor(**prm).fit(X.loc[a, cols], y[a]).predict(X.loc[b, cols])
    z[~tr] = lgb.LGBMRegressor(**prm).fit(X.loc[tr, cols], y[tr]).predict(X.loc[~tr, cols])
    return z


def newest_exposure(s, a0):
    """Exposure on /newest page 1 from posting to the snapshot age a0 (Wayback captures; direction A of wb15.py):
    position-weighted (1 / sqrt(rank)) share of the captures in [posting, posting + a0] that showed the post, times a0
    minutes. Only the captures' times and what they showed. NaN without a snapshot."""
    A = pd.read_json(os.path.join(CACHE, "early_votes", "early_snapshots.jsonl"), lines=True, convert_dates=False)
    N = A[A.page == "newest"]
    caps = np.sort((pd.to_datetime(N.capture_ts.astype(str), format="%Y%m%d%H%M%S", utc=True) - pd.Timestamp(0, tz="UTC")).dt.total_seconds().unique())
    N = N[N.age_min >= 0].assign(w=1 / np.sqrt(N["rank"].clip(lower=1)))
    born = s.created_at_i.to_numpy(float); a0 = np.asarray(a0, float)
    lim = pd.Series(a0, index=s.post_id.to_numpy()).groupby(level=0).first()
    N = N[N.age_min <= N.item_id.map(lim).fillna(-1)]
    wsum = s.post_id.map(N.groupby("item_id").w.sum()).fillna(0).to_numpy()
    ncap = np.searchsorted(caps, born + np.nan_to_num(a0) * 60, side="right") - np.searchsorted(caps, born)
    return np.where(np.isfinite(a0) & (ncap > 0), wsum / np.maximum(ncap, 1) * np.nan_to_num(a0), np.nan)


def early(s, a=15):
    A = pd.read_json(os.path.join(CACHE, "early_votes", "early_snapshots.jsonl"), lines=True, convert_dates=False)
    A = A[(A.page == "newest") & (A.age_min <= a) & (A.age_min >= 0)].sort_values("age_min").drop_duplicates("item_id", keep="last")
    A = A.set_index("item_id")
    return s.post_id.map(A.score).to_numpy(float), s.post_id.map(A.age_min).to_numpy(float)


class Model:
    def fit(self, s, qn, RK, EX, UP, z=None, nbins=20):
        born = qn.post_id.map(s.set_index("post_id").created_at_i).to_numpy(float)
        day = qn.post_id.map(s.set_index("post_id").day)
        tr = (day >= TRAIN[0]).to_numpy() & (day <= TRAIN[1]).to_numpy()
        f0 = qn.qn_f0.to_numpy(float)
        t = f0[:, None] + 600 * np.arange(NB)[None, :]
        hr = ((t // 3600) % 24).astype(int)
        dE = np.diff(np.concatenate([np.zeros((len(qn), 1)), EX], 1), axis=1)
        k = np.broadcast_to(np.arange(NB), RK.shape)
        # exposure: front (rank 1-90) = f(rank) * m(hour); off = g(age bin) * m_off(hour)
        on = tr[:, None] & (RK <= 90)
        df = pd.DataFrame({"r": RK[on].astype(int), "h": hr[on], "e": dE[on]})
        self.f_rank = df.groupby("r").e.mean().reindex(range(1, 91)).interpolate().to_numpy()
        self.m_front = (df.groupby("h").e.mean() / df.e.mean()).reindex(range(24)).to_numpy()
        off = tr[:, None] & ~(RK <= 90)
        do = pd.DataFrame({"k": k[off], "h": hr[off], "e": dE[off]})
        self.g_off = do.groupby("k").e.mean().reindex(range(NB)).interpolate().bfill().ffill().to_numpy()
        do["base"] = self.g_off[do.k]
        self.m_off = (do.groupby("h").e.sum() / do.groupby("h").base.sum()).reindex(range(24)).to_numpy()
        # cumulative /newest exposure by age in minutes before the first grid point (for the early-vote likelihood):
        # bin 0 = posting .. f0 (QN's first value); later bins add g_off
        r0 = tr & (RK[:, 0] > 90)
        lag = (f0 - born)[r0] / 60
        self.e0_per_min = float(np.nanmedian(EX[r0, 0] / np.clip(lag, 1, None)))
        # front pages: isotonic score by rank for every training slot (and the early test days, for later draws)
        self.slots = {}
        T0 = int(f0.min()); self.T0 = T0
        tt = t.astype(np.int64); age = (t - born[:, None]) / 3600
        raw = np.clip(UP - 1, 0, None) ** 0.8 / (np.clip(age, 0, None) + 2) ** 1.8
        m = RK <= 90
        jj = np.broadcast_to(np.arange(len(qn))[:, None], RK.shape)
        S = pd.DataFrame({"slot": tt[m], "r": RK[m].astype(int), "raw": raw[m], "j": jj[m]})
        S = S.sort_values(["slot", "r"]).drop_duplicates(["slot", "r"])
        nslot = int((tt.max() - T0) // 600) + 1
        ISO = np.full((nslot, 90), np.nan, np.float32); res = []
        # per slot: every front-page post's effective score (isotonic in rank, so penalties count) and its row
        self.EFF = np.zeros((nslot, 90), np.float32); self.JJ = np.full((nslot, 90), -1, np.int32)
        first = np.where(m.any(1), np.argmax(m, 1), NB)
        self.FIRST = ((tt[np.arange(len(qn)), np.minimum(first, NB - 1)] - T0) // 600).astype(np.int64)
        self.FIRST[first == NB] = 1 << 40
        self.qn_born, self.qn_f0, self.qn_RK, self.qn_UP = born, f0, RK, UP
        iso = IsotonicRegression(increasing=False)
        for slot, g in S.groupby("slot"):
            if len(g) < 45:
                continue
            fit = iso.fit_transform(g.r.to_numpy(float), g.raw.to_numpy())
            curve = np.interp(np.arange(1, 91), g.r.to_numpy(float), fit)
            ISO[(slot - T0) // 600] = curve
            si = (slot - T0) // 600; nn = min(len(g), 90)
            self.EFF[si, :nn] = fit[:nn]; self.JJ[si, :nn] = g.j.to_numpy()[:nn]
            if slot % 3600 == 0:
                res.append(np.log(np.clip(g.raw.to_numpy(), 1e-6, None)) - np.log(np.clip(fit, 1e-6, None)))
        self.ISO = ISO
        res = np.concatenate(res); self.pen = np.clip(res, -5, 0.5)
        # growth of a front-page post's HN score: median raw(k0 + d) / raw(k0) by age and rank at k0 (training posts)
        self.ab = np.array([1, 2, 3, 4, 6, 9, 13, 18, 24]); self.rb = np.array([3, 10, 20, 30, 45, 60, 90])
        RG = np.ones((len(self.ab) + 1, len(self.rb) + 1, H24 + 2), np.float32)
        ti, ki = np.nonzero(tr[:, None] & m & (k % 3 == 0) & (k < NB - H24 - 2))
        a_i = np.searchsorted(self.ab, age[ti, ki]); r_i = np.searchsorted(self.rb, RK[ti, ki])
        base = np.clip(raw[ti, ki], 1e-6, None)
        for dlt in range(1, H24 + 2):
            ratio = raw[ti, ki + dlt] / base
            G = pd.DataFrame({"a": a_i, "r": r_i, "x": ratio}).groupby(["a", "r"]).x.median()
            for (a_, r_), x in G.items():
                RG[a_, r_, dlt] = x
        self.RG = RG
        # quality prior (NPMLE on a grid) over all training stories
        st = s[(s.day >= TRAIN[0])]
        qi = qn.set_index("post_id")
        idx = pd.Series(np.arange(len(qn)), index=qn.post_id)
        has = st.post_id.isin(idx.index).to_numpy()
        ii = idx.reindex(st.post_id[has]).to_numpy()
        v = np.empty(len(st)); E = np.empty(len(st))
        v[has] = UP[ii, H24 - 1] - 1; E[has] = EX[ii, H24 - 1]
        h0 = ((st.created_at_i.to_numpy() // 3600) % 24).astype(int)
        off_tot = 10 * self.e0_per_min + np.array([self.g_off[:H24 - 1].sum()])[0]
        v[~has] = np.clip(st.points.to_numpy()[~has] - 1, 0, None); E[~has] = off_tot * self.m_off[h0[~has]]
        self.vE = pd.DataFrame({"post_id": st.post_id.to_numpy(), "v": v, "E": E})
        keep = (st.day <= TRAIN[1]).to_numpy(); st, v, E, has, h0 = st[keep], v[keep], E[keep], has[keep], h0[keep]
        ii = idx.reindex(st.post_id[has]).to_numpy()
        self.grid = np.concatenate([[1e-4], np.logspace(-3, 1.6, 90)])
        from scipy.stats import poisson
        Lk = poisson.pmf(np.round(v)[:, None].astype(int), np.clip(E[:, None], 1e-6, None) * self.grid[None, :]) + 1e-300

        def npmle(L):
            w = np.full(len(self.grid), 1 / len(self.grid))
            for _ in range(500):
                p = L * w; p /= p.sum(1, keepdims=True); w = p.mean(0)
            return w
        w = npmle(Lk); self.prior = w
        self.edges, self.priors = None, None
        self.b, self.zc = 0.0, 0.0
        if z is not None:                                   # q = exp(b (z - zc)) * u, u on the grid (NPMLE), b by likelihood
            zt = z[(s.day >= TRAIN[0]).to_numpy() & (s.day <= TRAIN[1]).to_numpy()]; self.zc = float(np.mean(zt))
            best = None
            for b in (0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5):
                sc_ = np.exp(b * (zt - self.zc))
                Lb = poisson.pmf(np.round(v)[:, None].astype(int), np.clip((E * sc_)[:, None], 1e-6, None) * self.grid[None, :]) + 1e-300
                wb = npmle(Lb); ll = float(np.log((Lb * wb).sum(1)).sum())
                if best is None or ll > best[0]:
                    best = (ll, b, wb)
            _, self.b, self.prior_u = best
        # P(daily top 30 | 24 h points): isotonic over training stories
        p24 = np.where(has, 0, 0.0); p24 = np.empty(len(st)); p24[has] = UP[ii, H24 - 1]; p24[~has] = st.points.to_numpy()[~has]
        self.g = IsotonicRegression(increasing=True, out_of_bounds="clip").fit(np.log1p(p24), st.y.to_numpy())
        self.train_info = {"stories": int(len(st)), "with_qn_series": int(has.sum()), "slots": int(np.isfinite(ISO[:, 0]).sum()),
                           "prior_mean_q": float((w * self.grid).sum()), "b_at_posting": self.b}
        return self

    tau, kappa, sigma = 1.0, 1.0, 0.0     # sigma: per-draw lognormal factor on the post's future quality (dispersion)

    def early_E(self, born, a0, xw):
        """exposure behind the early votes: /newest page-1 position-weighted minutes x the hour's traffic when known,
        else the average /newest exposure by age (QN units); kappa (fitted) converts units."""
        h = ((np.asarray(born) // 3600) % 24).astype(int)
        return np.where(np.isfinite(xw), xw * self.m_off[h] * self.k_new, self.cum_new(a0, h))

    def fit_early(self, s, sc, a0, xw, until_day):
        """Temper the early-vote likelihood (exponent tau, exposure scale kappa), fitted on posts with a /newest snapshot by
        15 min posted Jul 14 .. until_day (training + earlier test days whose outcomes are known) by the predictive
        likelihood of their later votes (24 h points - early points, exposure after)."""
        from scipy.stats import poisson
        st = s.assign(sc=sc, a0=a0, xw=xw)
        st = st[(st.day >= TRAIN[0]) & (st.day <= until_day) & np.isfinite(st.sc)].merge(self.vE, on="post_id")
        born = st.created_at_i.to_numpy(float); h = ((born // 3600) % 24).astype(int)
        v0 = st.sc.to_numpy() - 1
        if not hasattr(self, "k_new"):     # unit match: mean QN /newest exposure by 15 min per weighted minute
            ok = np.isfinite(st.xw.to_numpy())
            self.k_new = float(np.nanmean(self.cum_new(st.a0.to_numpy()[ok], h[ok])) / max(np.nanmean(st.xw.to_numpy()[ok] * self.m_off[h[ok]]), 1e-6))
        E0 = self.early_E(born, st.a0.to_numpy(), st.xw.to_numpy())
        scale = np.exp(self.b * (st.z.to_numpy() - self.zc)); pri = self.prior_u if self.b else self.prior
        vr = np.clip(st.v.to_numpy() - v0, 0, None); Er = np.clip(st.E.to_numpy() - self.cum_new(st.a0.to_numpy(), h), 1e-3, None)
        Lr = poisson.pmf(np.round(vr)[:, None].astype(int), (Er * scale)[:, None] * self.grid[None, :]) + 1e-300
        out = {}
        for k in (0.02, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 4.0):
            L0 = poisson.pmf(np.round(v0)[:, None].astype(int), np.clip(k * E0 * scale, 1e-9, None)[:, None] * self.grid[None, :]) + 1e-300
            for t in (0.0, 0.02, 0.05, 0.1, 0.2, 0.3, 0.5, 0.7, 1.0):
                po = pri[None, :] * L0 ** t; po /= po.sum(1, keepdims=True)
                out[(t, k)] = float(np.log((po * Lr).sum(1)).sum())
        (self.tau, self.kappa) = max(out, key=out.get)
        self.early_log = getattr(self, "early_log", {})
        self.early_log[until_day] = {"posts": int(len(st)), "with_newest_exposure": int(np.isfinite(st.xw).sum()), "tau": self.tau,
                                     "kappa": self.kappa, "ll_gain_vs_no_early_votes": round(out[(self.tau, self.kappa)] - out[(0.0, 1.0)], 1),
                                     "ll_gain_vs_untempered": round(out[(self.tau, self.kappa)] - out[(1.0, 1.0)], 1)}
        return self

    def cum_new(self, a_min, h):
        """expected /newest exposure from posting to age a (minutes)."""
        a = np.asarray(a_min, float)
        first = np.minimum(a, 10) * self.e0_per_min
        later = np.clip(a - 10, 0, None) / 10 * self.g_off[1]
        return (first + later) * self.m_off[h]

    def simulate(self, born, score, a0, wday_class, test_day, days_cls, D=200, z=None, xw=None):
        """born, score, a0 per post (score NaN -> no snapshot); returns P(top 30) per post."""
        n = len(born)
        h_born = ((born // 3600) % 24).astype(int)
        has = np.isfinite(score)
        a0 = np.where(has, a0, 0.0); v0 = np.where(has, score - 1, 0.0)
        # posterior over the grid
        from scipy.stats import poisson
        E0 = self.cum_new(a0, h_born)
        E0l = E0 if xw is None else self.early_E(born, a0, xw)
        scale = np.ones(n) if z is None or not self.b else np.exp(self.b * (np.asarray(z) - self.zc))
        pri = self.prior if z is None or not self.b else self.prior_u
        post = pri[None, :] * (poisson.pmf(np.round(v0)[:, None].astype(int), np.clip((self.kappa * E0l * scale)[:, None], 1e-9, None) * self.grid[None, :]) + 1e-300) ** self.tau
        post /= post.sum(1, keepdims=True)
        cdf = np.cumsum(post, 1)
        u = rng.random((n, D))
        q = self.grid[np.minimum((cdf[:, None, :] < u[:, :, None]).sum(2), len(self.grid) - 1)] * scale[:, None]
        if getattr(self, "sigma", 0):
            q = q * np.exp(getattr(self, "sigma", 0) * rng.standard_normal(q.shape))
        pen = np.exp(rng.choice(self.pen, (n, D)))
        # earlier front-page days of the same class
        td = pd.Timestamp(test_day)
        pool = [d for d in days_cls[wday_class] if pd.Timestamp(d) <= td - pd.Timedelta(days=3)]
        dd = rng.choice(len(pool), (n, D))
        shift = np.array([(td - pd.Timestamp(d)).days * 86400 for d in pool])[dd]
        f0 = (np.floor(born / 600) + 1) * 600
        P = 1 + v0[:, None] + rng.poisson(q * (self.cum_new(np.full(n, 0) + (f0 - born) / 60, h_born) - E0)[:, None].clip(0))
        P = P.astype(float)
        best = np.full((n, D), 91)
        for k in range(H24):
            tau = f0 + 600 * k
            h = ((tau // 3600) % 24).astype(int)
            age = (tau - born) / 3600
            sc = np.clip(P - 1, 0, None) ** 0.8 / (age[:, None] + 2) ** 1.8 * pen
            slot = ((tau[:, None] - shift - self.T0) // 600).astype(int)
            slot = np.clip(slot, 0, len(self.ISO) - 1)
            C = self.ISO[slot]                                    # n x D x 90
            ok = np.isfinite(C[..., 0])
            rank = 1 + (C > sc[..., None]).sum(-1)
            rank = np.where(ok, rank, 91)
            e = np.where(rank <= 90, self.f_rank[np.clip(rank, 1, 90) - 1] * self.m_front[h][:, None],
                         self.g_off[k + 1] * self.m_off[h][:, None])
            P += rng.poisson(q * e); best = np.minimum(best, rank)
        self.last_top30 = (best <= 30).mean(1)
        return self.g.predict(np.log1p(P).ravel()).reshape(n, D).mean(1), P


def simulate_live(M, born, score, a0, wday_class, test_day, days_cls, D=200, z=None, xw=None, judge_min=15):
    """As Model.simulate, but the front page is the real one at the judging moment (posts on it then: their effective
    scores, projected with the training growth table), plus arrivals replayed from an earlier same-class day (posts
    that first reached that day's front page after the same clock time)."""
    from scipy.stats import poisson
    n = len(born); h_born = ((born // 3600) % 24).astype(int)
    has = np.isfinite(score); a0 = np.where(has, a0, 0.0); v0 = np.where(has, score - 1, 0.0)
    E0 = M.cum_new(a0, h_born); E0l = E0 if xw is None else M.early_E(born, a0, xw)
    scale = np.ones(n) if z is None or not M.b else np.exp(M.b * (np.asarray(z) - M.zc))
    pri = M.prior if z is None or not M.b else M.prior_u
    post = pri[None, :] * (poisson.pmf(np.round(v0)[:, None].astype(int), np.clip((M.kappa * E0l * scale)[:, None], 1e-9, None) * M.grid[None, :]) + 1e-300) ** M.tau
    post /= post.sum(1, keepdims=True); cdf = np.cumsum(post, 1)
    u = rng.random((n, D))
    q = M.grid[np.minimum((cdf[:, None, :] < u[:, :, None]).sum(2), len(M.grid) - 1)] * scale[:, None]
    pen = np.exp(rng.choice(M.pen, (n, D)))
    td = pd.Timestamp(test_day)
    pool = [d for d in days_cls[wday_class] if pd.Timestamp(d) <= td - pd.Timedelta(days=3)]
    dd = rng.choice(len(pool), (n, D))
    shs = np.array([(td - pd.Timestamp(d)).days * 144 for d in pool])[dd]          # shift in slots
    # the real front page at the judging moment
    cs = ((born + judge_min * 60 - M.T0) // 600).astype(int)
    CJ = M.JJ[cs]; CE = M.EFF[cs].astype(float); ok = CJ >= 0
    cage = (M.T0 + 600 * cs[:, None] - M.qn_born[np.maximum(CJ, 0)]) / 3600
    crk = np.broadcast_to(np.arange(1, 91), CJ.shape)
    CA = np.searchsorted(M.ab, cage); CR = np.searchsorted(M.rb, crk)
    CE = np.where(ok, CE, 0.0)
    f0 = (np.floor(born / 600) + 1) * 600
    P = (1 + v0[:, None] + rng.poisson(q * (M.cum_new((f0 - born) / 60, h_born) - E0)[:, None].clip(0))).astype(float)
    cut_hist = cs[:, None] - shs
    best = np.full((n, D), 91)
    for k in range(H24):
        tau = f0 + 600 * k
        h = ((tau // 3600) % 24).astype(int)
        age = (tau - born) / 3600
        sc = np.clip(P - 1, 0, None) ** 0.8 / (age[:, None] + 2) ** 1.8 * pen
        slot = ((tau - M.T0) // 600).astype(int)
        dl = np.clip(slot - cs, 0, H24 + 1)
        ce = CE * M.RG[CA, CR, dl[:, None]]                                    # n x 90 projected real front page
        n_comp = (ce[:, None, :] > sc[..., None]).sum(-1)
        hs = np.clip(slot[:, None] - shs, 0, len(M.EFF) - 1)                   # n x D historical slots
        HJ = M.JJ[hs]; HE = M.EFF[hs]
        arr = (HJ >= 0) & (M.FIRST[np.maximum(HJ, 0)] > cut_hist[..., None])
        n_arr = ((HE > sc[..., None]) & arr).sum(-1)
        rank = 1 + n_comp + n_arr
        e = np.where(rank <= 90, M.f_rank[np.clip(rank, 1, 90) - 1] * M.m_front[h][:, None],
                     M.g_off[k + 1] * M.m_off[h][:, None])
        P += rng.poisson(q * e); best = np.minimum(best, rank)
    M.last_top30 = (best <= 30).mean(1)
    return M.g.predict(np.log1p(P).ravel()).reshape(n, D).mean(1), P


def caught_on(T, s):
    T = T.assign(s=s); k = int(T.y.sum())
    T["flag"] = T.s.rank(ascending=False, method="first") <= k
    g = T.groupby("day")
    return pd.DataFrame({"hit": g.apply(lambda x: int((x.flag & (x.y == 1)).sum())), "n": g.y.sum()})


def ci(c, ref=None, B=2000):
    r = np.random.default_rng(1); h, n = c.hit.to_numpy(), c.n.to_numpy()
    idx = [r.integers(0, len(c), len(c)) for _ in range(B)]
    if ref is None:
        b = [h[i].sum() / n[i].sum() for i in idx]
        return [round(h.sum() / n.sum(), 4), [round(float(np.percentile(b, 2.5)), 4), round(float(np.percentile(b, 97.5)), 4)]]
    h0 = ref.hit.to_numpy(); b = [(h[i].sum() - h0[i].sum()) / n[i].sum() for i in idx]
    return [round((h.sum() - h0.sum()) / n.sum(), 4), [round(float(np.percentile(b, 2.5)), 4), round(float(np.percentile(b, 97.5)), 4)]]


def main(D=200):
    t0 = time.time()
    s = load_stories(); qn, RK, EX, UP = load_qn()
    s["z"] = at_posting(s); print("at-posting model", f"{time.time() - t0:.0f}s", flush=True)
    import pickle
    mp = os.path.join(CACHE, "frontsim_model.pkl")
    if os.environ.get("REFIT") or not os.path.exists(mp):
        M = Model().fit(s, qn, RK, EX, UP, s.z.to_numpy()); pickle.dump(M, open(mp, "wb"))
    else:
        M = pickle.load(open(mp, "rb"))
    sc_all, a0_all = early(s); xw_all = newest_exposure(s, a0_all)
    M.fit_early(s, sc_all, a0_all, xw_all, TRAIN[1])
    print("fit", M.train_info, M.early_log, f"{time.time() - t0:.0f}s", flush=True)
    days = sorted(s.day.unique()); cls = lambda d: int(pd.Timestamp(d).dayofweek >= 5)
    okd = pd.Series(np.isfinite(M.ISO[:, 0]), index=pd.to_datetime(M.T0 + 600 * np.arange(len(M.ISO)), unit="s").strftime("%Y-%m-%d"))
    okd = okd.groupby(level=0).mean()
    good_front = {d for d in days if okd.get(d, 0) >= 0.9 and okd.get(str((pd.Timestamp(d) + pd.Timedelta(days=1)).date()), 0) >= 0.9}
    days_cls = {c: [d for d in days if d >= "2026-07-15" and cls(d) == c and d in good_front] for c in (0, 1)}
    print("replay pool", {c: len(v) for c, v in days_cls.items()}, flush=True)
    T = s[(s.day >= TEST[0]) & (s.day <= TEST[1])].reset_index(drop=True)
    sc, a0 = early(T); xw = newest_exposure(T, a0)
    out = {"p_sim_flat": np.zeros(len(T)), "p_sim": np.zeros(len(T)), "p_live": np.zeros(len(T)), "top30_sim": np.zeros(len(T)), "top30_live": np.zeros(len(T))}
    for d in sorted(T.day.unique()):
        m = (T.day == d).to_numpy(); args = (T.created_at_i.to_numpy(float)[m], sc[m], a0[m], cls(d), d, days_cls, D)
        M.fit_early(s, sc_all, a0_all, xw_all, max(TRAIN[1], str((pd.Timestamp(d) - pd.Timedelta(days=2)).date())))
        out["p_sim_flat"][m], _ = M.simulate(*args)
        out["p_sim"][m], _ = M.simulate(*args, z=T.z.to_numpy()[m], xw=xw[m]); out["top30_sim"][m] = M.last_top30
        out["p_live"][m], _ = simulate_live(M, *args, z=T.z.to_numpy()[m], xw=xw[m]); out["top30_live"][m] = M.last_top30
        print(d, int(m.sum()), f"{time.time() - t0:.0f}s", flush=True)
    for k, v in out.items():
        T[k] = v
    T["has_snap"] = np.isfinite(sc)
    os.makedirs(os.path.join(HERE, "out"), exist_ok=True)
    T[["post_id", "day", "y", "z", "p_sim", "p_sim_flat", "has_snap"]].to_parquet(os.path.join(HERE, "out", "frontsim_scores.parquet"), index=False)
    # comparisons (same posts, same flags count): at-posting alone, early votes alone, a LightGBM on at-posting + early
    # votes (trained Jul 1 - Sep 30 has no /newest snapshots, so it is fit forward on earlier test days: train <= d - 2)
    T["v_score"] = np.nan_to_num(sc, nan=0); T["v_rate"] = np.where(np.isfinite(sc), (sc - 1) / np.clip(a0, 1, None), -1)
    T["v_age"] = np.nan_to_num(a0, nan=-1)
    c = {k: caught_on(T, T[k] + 1e-12 * rng.random(len(T))) for k in ("z", "v_score", "p_sim_flat", "p_sim", "p_live")}
    res = {"train": M.train_info, "test_posts": int(len(T)), "winners": int(T.y.sum()), "draws": D,
           "snapshot_coverage": round(float(T.has_snap.mean()), 3),
           "calibration": {"sum_p_sim": round(float(T.p_sim.sum()), 1), "winners": int(T.y.sum())},
           "caught_15min": {"at-posting score alone": ci(c["z"]), "15-min score alone": ci(c["v_score"]),
                            "simulator, flat prior": ci(c["p_sim_flat"]), "simulator, at-posting prior": ci(c["p_sim"]),
                            "simulator, real front page at 15 min": ci(c["p_live"])},
           "simulator_vs_at_posting": ci(c["p_sim"], c["z"]), "real_front_vs_replayed_front": ci(c["p_live"], c["p_sim"])}
    res["at_posting_inputs"] = len(AT_COLS); res["early_fit_by_day"] = M.early_log
    res["replay_pool_days"] = {c: len(v) for c, v in days_cls.items()}
    # the real front page at t + 15 is reconstructable from Quality News only on some October days (90%+ of slots)
    live_days = sorted(d for d in T.day.unique() if okd.get(d, 0) >= 0.9)
    TL = T[T.day.isin(live_days)]
    if len(TL):
        cl = {k: caught_on(TL, TL[k] + 1e-12 * rng.random(len(TL))) for k in ("p_sim", "p_live", "z")}
        res["real_front_days"] = {"days": live_days, "winners": int(TL.y.sum()), "replayed front": ci(cl["p_sim"]),
                                  "real front": ci(cl["p_live"]), "real - replayed": ci(cl["p_live"], cl["p_sim"]),
                                  "at-posting alone": ci(cl["z"])}
    # realism: share of test posts that ever reach the top 30 (Quality News rank, the real one) vs the simulators
    qr = pd.Series(np.nanmin(np.where(np.isnan(RK), 91, RK)[:, :H24], 1), index=qn.post_id.to_numpy())
    real30 = T.post_id.map(qr).fillna(91).le(30)
    res["reach_top30_within_24h"] = {"real": round(float(real30.mean()), 4), "replayed front": round(float(T.top30_sim.mean()), 4),
                                     "real front": round(float(T.top30_live.mean()), 4),
                                     "among real winners": {"real": round(float(real30[T.y == 1].mean()), 4), "replayed front": round(float(T.top30_sim[T.y == 1].mean()), 4),
                                                            "real front": round(float(T.top30_live[T.y == 1].mean()), 4)}}
    wf = os.path.join(CACHE, "wb15_scores.parquet")
    if os.path.exists(wf):          # pair against the HN agent's 15-min reference (forward daily retrain, train <= d - 2)
        REF = "+ votes + who + exposure (direction A)"
        W = pd.read_parquet(wf)[["post_id", REF]].rename(columns={REF: "wb15"})
        T = T.merge(W, on="post_id", how="left"); assert T.wb15.notna().all()
        lg = lambda x: np.log(np.clip(x, 1e-6, 1 - 1e-6) / (1 - np.clip(x, 1e-6, 1 - 1e-6)))
        T["blend_equal"] = lg(T.wb15) + lg(T.p_sim)          # fixed before the run: equal weights on the logit scale
        # forward blend: logistic on [logit wb15, logit p_sim] fit on test days <= d - 2 (their outcomes are known by d)
        from sklearn.linear_model import LogisticRegression
        T["blend_fwd"] = np.nan; days_t = sorted(T.day.unique())
        for d in days_t:
            m = (T.day == d).to_numpy(); tr = (T.day <= str((pd.Timestamp(d) - pd.Timedelta(days=2)).date())).to_numpy()
            Xb = np.c_[lg(T.wb15), lg(T.p_sim)]
            if tr.sum() and T.y[tr].sum() >= 20:
                T.loc[m, "blend_fwd"] = LogisticRegression(C=1.0).fit(Xb[tr], T.y[tr]).decision_function(Xb[m])
            else:
                T.loc[m, "blend_fwd"] = T.blend_equal[m]
        cw = {k: caught_on(T, T[k]) for k in ("wb15", "blend_equal", "blend_fwd")}
        good = set(d for d, v in json.load(open(os.path.join(CACHE, "early_votes", "coverage_oct_daily.json"))).items() if v.get("pct_lt60", 0) >= 90)
        Tg = T[T.day.isin(good)]
        cg = {k: caught_on(Tg, Tg[k] + 1e-12 * rng.random(len(Tg))) for k in ("wb15", "p_sim", "blend_equal", "blend_fwd")}
        res["vs_wb15"] = {"wb15 (+ votes + who + exposure)": ci(cw["wb15"]),
                          "simulator alone - wb15": ci(c["p_sim"], cw["wb15"]),
                          "wb15 + simulator, equal logit blend": ci(cw["blend_equal"]), "  minus wb15": ci(cw["blend_equal"], cw["wb15"]),
                          "wb15 + simulator, forward blend": ci(cw["blend_fwd"]), "  minus wb15 ": ci(cw["blend_fwd"], cw["wb15"]),
                          "90%+ coverage days": {"days": len(set(Tg.day)), "winners": int(Tg.y.sum()), "wb15": ci(cg["wb15"]),
                                                 "simulator": ci(cg["p_sim"]), "equal blend - wb15": ci(cg["blend_equal"], cg["wb15"]),
                                                 "forward blend - wb15": ci(cg["blend_fwd"], cg["wb15"])}}
        T[["post_id", "day", "y", "z", "p_sim", "p_sim_flat", "wb15", "blend_equal", "blend_fwd"]].to_parquet(os.path.join(HERE, "out", "frontsim_scores.parquet"), index=False)
    print(json.dumps(res, indent=1))
    json.dump(res, open(os.path.join(HERE, "out", "frontsim.json"), "w"), indent=1)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 200)
