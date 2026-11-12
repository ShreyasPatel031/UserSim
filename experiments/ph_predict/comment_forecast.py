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


_KC = {}


def load_comments():
    if "K" in _KC:
        return _KC["K"]
    _KC["K"] = _load_comments()
    return _KC["K"]


def _load_comments():
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
                rows.append((info["slug"], r["comment_id"], (r["username"] or "").lower(), str(r["user_id"] or ""), r["created"],
                             r["depth"], bool(r["verified"]), bool(r["prominent"])))
    K = pd.DataFrame(rows, columns=["slug", "cid", "user", "uid", "created", "depth", "ver", "prom"]).drop_duplicates("cid")
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
    # leak check (orchestrator 07:45Z Nov 12): our API reads name the winner's makers only after the day (the PH page shows the full team), so the warehouse maker list
    # (read later) recognises winners' maker comments as team and leaves other launches' redacted makers "outside".
    #   CF_TEAM=a  current rule: every named maker + hunter (read after the day)
    #   CF_TEAM=b  00:05-consistent: hunter + the single maker visible at 00:05 (the LAST entry of the maker list, if named)
    #   CF_TEAM=c  identity-free: no team split (team empty; u_out = all unique commenters, n_team = u_tie = 0)
    rule = os.environ.get("CF_TEAM", "a")
    if rule == "b":
        def vis(m, p):
            ms = json.loads(m) if m and m.startswith("[") else []
            last = (ms[-1] or "").lower() if ms else ""
            return ({last} if last and "redacted" not in last else set()) | ({p.lower()} if p else set())
        L["team"] = [vis(m, p) for m, p in zip(L.makers, L.poster)]
    elif rule == "c":
        L["team"] = [set() for _ in L.makers]
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
    # diagnostic: team vs outside early comments by final rank group under the active rule
    g4 = X[X.cut == 4].assign(grp=lambda x: np.select([x["rank"] == 1, x["rank"] <= 3, x["rank"] <= 10], ["#1", "#2-3", "#4-10"], "11+"))
    stats["team_rule"] = rule
    stats["by_rank_group_4h"] = g4.groupby("grp")[["n_c", "n_team", "u_out", "u_tie"]].mean().round(2).to_dict("index")
    stats["named_team_size"] = L[L.day.isin(days)].assign(grp=lambda x: np.select([x.daily_rank == 1, x.daily_rank <= 3, x.daily_rank <= 10], ["#1", "#2-3", "#4-10"], "11+")).groupby("grp").team.apply(lambda s: round(float(np.mean([len(t) for t in s])), 2)).to_dict()
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


LIVEF = [f for f in FEATS if f not in ("u_ver", "u_prom")]   # live comments carry no account flags
CNT = ("n_c", "n_top", "n_rep", "n_team", "u_out", "u_prior", "u_tie", "n_day")


def fit_live():
    """Ridge per cut on all backtest days, LM as -log(within-day LM rank) (the only form the live 00:05 LM has).
    -> results/comment_forecast_live_model.json (coefficients, scaling; no people)."""
    from sklearn.linear_model import Ridge
    X = pd.read_parquet(f"{WORK}/cf_rows.parquet")
    X["lm"] = -np.log(X.groupby(["cut", "day"]).lm.rank(ascending=False, method="first"))
    out = {"feats": LIVEF, "log1p": list(CNT), "lm": "-log(within-day 00:05 LM rank)", "cuts": {},
           "team_rule": os.environ.get("CF_TEAM", "a"), "lm_source": os.environ.get("CF_LM_NOTE", "honest_preds (leaked)")}
    for h in CUTS:
        Xh = X[X.cut == h]; F = Xh[LIVEF].copy()
        for c in CNT:
            F[c] = np.log1p(F[c])
        mu, sd = F.mean(), F.std() + 1e-9
        m = Ridge(alpha=10.0).fit((F - mu) / sd, -np.log(Xh["rank"]))
        out["cuts"][f"P{h}"] = {"coef": dict(zip(LIVEF, map(float, m.coef_))), "intercept": float(m.intercept_),
                                "mu": mu.round(6).to_dict(), "sd": sd.round(6).to_dict(), "days": int(Xh.day.nunique())}
    json.dump(out, open(os.environ.get("CF_MODEL_OUT", os.path.join(HERE, "results", "comment_forecast_live_model.json")), "w"), indent=1)
    print(json.dumps({k: v["days"] for k, v in out["cuts"].items()}))


def live(day, point):
    """P1..P4 = 00:00 PT of <day> + 1..4 h. Line-up: launches in live/posts_ts.jsonl snapshots <= T (fetch 200);
    comments: live/comments_ts.jsonl created_at <= T (dedup comment_id); team = makers + hunter from posts_ts; prior
    activity / ties from the backtest dump + earlier days' comments_ts; LM = the 00:05 launch_model forecast.
    -> results/early_forecast/<day>_<point>.json and gs://.../results/early_forecast/."""
    import subprocess, tempfile
    from early_forecast import lm_scores
    M = json.load(open(os.path.join(HERE, "results", "comment_forecast_live_model.json")))["cuts"]["P1" if point == "P0" else point]
    # identity-free model (orchestrator 08:30Z Nov 12; comment_forecast_v2_teamc.md): no team split, fitted over the clean LM;
    # it is pred_rank from Nov 12; the old named-team model is kept as pred_rank_rule_a
    MNF = None
    pnf = os.path.join(HERE, "results", "comment_forecast_live_model_nf.json")
    if os.path.exists(pnf):
        MNF = json.load(open(pnf))["cuts"]["P1" if point == "P0" else point]
    # P0 = 00:45 PT (orchestrator 02:15Z Nov 12): earliest useful pre-reveal point; the comment ridge uses P1's coefficients
    h = 0.75 if point == "P0" else int(point[1:]); t0 = pd.Timestamp(day + " 00:00", tz="America/Los_Angeles").tz_convert("UTC")
    T = t0 + pd.Timedelta(hours=h); now = pd.Timestamp.now(tz="UTC")
    if now < T:
        print(json.dumps({"day": day, "point": point, "status": f"point {T} not reached"})); return
    tmp = tempfile.mkdtemp(prefix="cf_")
    for f in ("posts_ts", "comments_ts", "people_ts"):
        r_ = subprocess.run(["gsutil", "-q", "cp", f"{B}/raw/ph_at_launch/{day}/live/{f}.jsonl", f"{tmp}/{f}.jsonl"])
        if r_.returncode:
            if f != "people_ts":
                raise RuntimeError(f"missing live/{f}.jsonl for {day}")
            open(f"{tmp}/{f}.jsonl", "w").close()   # optional: team ids then come from the dump map only
    team, ids, api, rv = {}, set(), {}, {}
    for l in open(f"{tmp}/posts_ts.jsonl"):
        r = json.loads(l)
        from early_forecast import pt_day   # day from featuredAt in PT (00:00 PT = 08:00:00Z is the new day; audit 05:00Z Nov 12)
        if r.get("fetch_status") != 200 or pt_day(r, day) != day:   # the line-up is fixed at 00:01 PT
            continue
        i = str(r["launch_id"]); ids.add(i)
        # the official API's own post.dailyRank, populated before the reveal; latest fetched by T (fetched_at, no look-ahead)
        fa = pd.Timestamp(r.get("fetched_at") or r["snapshot_ts"])
        if str(r.get("source", "")).startswith("ph_api_v2") and r.get("daily_rank_at_fetch") is not None and fa <= T:
            if i not in api or fa > api[i][0]:
                api[i] = (fa, float(r["daily_rank_at_fetch"]))
        if r.get("reviews_count") is not None and fa <= T and (i not in rv or fa > rv[i][0]):
            rv[i] = (fa, float(r["reviews_count"]))
    pid, pnames = {}, {}   # launch -> maker/hunter PH user ids (people_ts: user_id, role, launch_ids); username -> id
    for l in open(f"{tmp}/people_ts.jsonl"):
        r = json.loads(l)
        if r.get("user_id"):
            if r.get("username"):
                pnames[str(r["username"]).lower()] = str(r["user_id"])
            for i in r.get("launch_ids") or []:
                pid.setdefault(str(i), set()).add(str(r["user_id"]))
    C = []
    for l in open(f"{tmp}/comments_ts.jsonl"):
        r = json.loads(l)
        if r.get("created_at"):
            # identity = commenter_user_id: the live "username" field is one constant per launch, not the commenter
            C.append((str(r["launch_id"]), r.get("comment_id"), str(r.get("commenter_user_id") or r.get("user_id") or ""), r["created_at"], r.get("parent_id")))
    C = pd.DataFrame(C, columns=["id", "cid", "user", "created", "parent"]).drop_duplicates("cid")
    C["ts"] = pd.to_datetime(C.created, utc=True, errors="coerce"); C = C[(C.ts <= T) & C.id.isin(ids)]
    # history (users only, in memory): backtest dump + earlier live days
    fetch(); K, _ = load_comments()
    first = K[K.uid != ""].groupby("uid").ts.min().to_dict()
    name2id = dict(zip(K.user, K.uid))   # usernames -> PH user ids, from the dump (in memory only)
    name2id.update(pnames)
    from pipeline import warehouse as W
    L = W.query("SELECT CAST(id AS VARCHAR) id, slug, makers, poster FROM launches", do_sync=False)
    # teams: live posts_ts carries no makers; the warehouse launches row (loaded by the 00:05 run) does
    for i, m, p_ in zip(L.id, L.makers, L.poster):
        if i in ids:
            names = {u.lower() for u in (json.loads(m) if m and m.startswith("[") else []) + ([p_] if p_ else []) if u}
            # pred_rank: the TRAINING rule - team = named makers + hunter (placeholder makers count as outside), by username;
            # pred_rank_teamids: people_ts maker/hunter ids added (resolves placeholders; differs from training)
            rule = {name2id[u] for u in names if name2id.get(u)}
            team[i] = (names, rule, rule | pid.get(i, set()))
    tm = {sl: {u.lower() for u in (json.loads(m) if m and m.startswith("[") else []) + ([p] if p else []) if u} for sl, m, p in zip(L.slug, L.makers, L.poster)}
    TIE = {}
    for sl, u, uid, ts in zip(K.slug, K.user, K.uid, K.ts):
        if not uid:
            continue
        for m in tm.get(sl, ()):
            if m != u and (m not in TIE.setdefault(uid, {}) or ts < TIE[uid][m]):
                TIE[uid][m] = ts
    lm = lm_scores(day)
    if not lm:
        print(json.dumps({"day": day, "point": point, "status": "no 00:05 LM forecast for the day"})); return
    lmr = pd.Series({i: lm.get(i, np.nan) for i in ids}); lmr = -np.log(lmr.rank(ascending=False, method="first", na_option="bottom"))
    def featurise(which, M=M):
        rows = []
        for i in sorted(ids):
            g = C[C.id == i]; tnames, trule, tids = team.get(i, (set(), set(), set())); tset = trule if which == "rule" else tids
            if which == "none":   # identity-free: no team split
                tnames, tset = set(), set()
            it = g.user.isin(tset); out = g[~it]; us = [u for u in out.user.unique() if u]
            rows.append({"id": i, "n_c": len(g), "n_top": int(g.parent.isna().sum()), "n_rep": int(g.parent.notna().sum()),
                         "n_team": int(it.sum()), "u_out": len(us), "u_prior": int(sum(first.get(u, T) < t0 for u in us)),
                         "u_tie": sum(1 for u in us if any(ts < t0 for m, ts in TIE.get(u, {}).items() if m in tnames)),
                         "lm": float(lmr[i]), "lm_matched": i in lm})
        A = pd.DataFrame(rows); A["n_day"] = len(A)
        A["sh_c"] = np.log((A.n_c + 0.5) / (A.n_c + 0.5).sum()); A["r_c"] = A.n_c.rank(pct=True); A["r_lm"] = A.lm.rank(pct=True)
        F = A[LIVEF].copy()
        for c in CNT:
            F[c] = np.log1p(F[c])
        A["score"] = sum(((F[c] - M["mu"][c]) / max(M["sd"][c], 1e-9)) * M["coef"][c] for c in LIVEF if M["coef"][c] != 0) + M["intercept"]
        A["pred_rank"] = A.score.rank(ascending=False, method="first").astype(int)
        return A
    A = featurise("rule")
    A2 = featurise("ids").set_index("id")
    A["pred_rank_teamids"] = A.id.map(A2.pred_rank); A["u_out_teamids"] = A.id.map(A2.u_out)
    A["pred_rank_rule_a"] = A.pred_rank
    if MNF is not None:
        A3 = featurise("none", MNF).set_index("id")
        A["pred_rank"] = A.id.map(A3.pred_rank).astype(int); A["score"] = A.id.map(A3.score); A["u_out_all"] = A.id.map(A3.u_out)
    # orchestrator 21:05Z: write three scores per point - comment ridge, API pre-reveal rank, blend (mean of rank positions)
    A["api_rank"] = A.id.map(lambda i: api[i][1] if i in api else np.nan)
    A["pred_rank_api"] = (A.api_rank.fillna(999) - 1e-6 * A.lm).rank(method="first").astype(int)
    A["pred_rank_blend"] = ((A.pred_rank + A.pred_rank_api) / 2 - 1e-6 * A.lm).rank(method="first").astype(int)
    # orchestrator 01:30Z Nov 12: dated comment votes before the reveal, recorded as extra columns (pred_rank unchanged)
    try:
        import comment_votes as CV
        V = CV.features(day, T)
        if len(V):
            A = A.merge(V, on="id", how="left")
    except Exception as e:
        print("comment votes skipped:", repr(e)[:120], flush=True)
    for c in ("cv_sum", "cv_max", "cv_maker1", "cv_per_out", "cv_growth1h", "cv_snapshot"):
        if c not in A:
            A[c] = np.nan
    # orchestrator 00:40Z Nov 12: hidden votes bracketed by the weekly rank (estvotes.py); extra columns only
    try:
        import estvotes as EV
        E_, _ = EV.earlier_votes(day)
        X0 = EV.est_votes(day, T, E_); X1 = EV.est_votes(day, T - pd.Timedelta(hours=1), E_)
        if len(X0):
            X0 = X0.merge(X1[["id", "est_votes"]].rename(columns={"est_votes": "e1"}), on="id", how="left") if len(X1) else X0.assign(e1=np.nan)
            X0["est_vel60"] = X0.est_votes - X0.e1
            A = A.merge(X0[["id", "est_votes", "est_vel60", "weekly_rank"]], on="id", how="left")
    except Exception as e:
        print("est votes skipped:", repr(e)[:120], flush=True)
    for c in ("est_votes", "est_vel60", "weekly_rank"):
        if c not in A:
            A[c] = np.nan
    A["pred_rank_estvotes"] = (A.est_votes.fillna(-1) + 1e-6 * A.lm).rank(ascending=False, method="first").astype(int)
    # orchestrator 02:30Z Nov 12 (growth.md): expected day-end votes = est_votes x the fitted multiplier at T by position
    try:
        import growth
        A["exp_final_votes"] = growth.exp_final(A.set_index("id").est_votes, h, pd.Timestamp(day).dayofweek >= 5, "est").reindex(A.id).values
    except Exception as e:
        print("exp_final_votes skipped:", repr(e)[:120], flush=True); A["exp_final_votes"] = np.nan
    # orchestrator 02:00Z Nov 12 (api_depth.md): best LODO recipe on 6 days = weighted mean of rank positions of the API
    # pre-reveal rank and the 00:05 LM, w_api = 0.5 at P1 and 0.75 from P2 (chosen leave-one-day-out on every held-out day)
    w_api = 0.5 if point in ("P0", "P1") else 0.75
    lm_pos = A.lm.rank(ascending=False, method="first")
    if A.api_rank.notna().any():
        A["pred_rank_best"] = (w_api * A.pred_rank_api + (1 - w_api) * lm_pos + 1e-6 * lm_pos).rank(method="first").astype(int)
    else:
        A["pred_rank_best"] = lm_pos.astype(int)
    # best2 (late_builders.md): on weekends the early-hours vote order is least reliable -> w_api 0.5 at every point
    w2 = 0.5 if pd.Timestamp(day).dayofweek >= 5 else w_api
    A["pred_rank_best2"] = ((w2 * A.pred_rank_api + (1 - w2) * lm_pos + 1e-6 * lm_pos).rank(method="first").astype(int)
                            if A.api_rank.notna().any() else lm_pos.astype(int))
    # orchestrator 02:40Z Nov 12: recorded only (not used in any rank) so they accrue - self_hunted (hunter is one of the
    # makers, from the latest api_detail file stamped <= T; NaN when none yet) and has_prior_reviews (reviews_count > 0 in
    # the latest posts_ts row fetched <= T)
    A["has_prior_reviews"] = [float(rv[i][1] > 0) if i in rv else np.nan for i in A.id]
    sh, hid = {}, {}
    try:
        fl = subprocess.run(["gsutil", "ls", f"{B}/raw/ph_at_launch/{day}/api_detail/"], capture_output=True, text=True).stdout.split()
        stamp = lambda f: pd.Timestamp(pd.to_datetime(os.path.basename(f)[:13], format="%Y%m%dT%H%M")).tz_localize("America/Los_Angeles").tz_convert("UTC")
        fl = sorted([f for f in fl if f.endswith("PT.jsonl") and stamp(f) <= T], key=stamp)
        if fl:
            subprocess.run(["gsutil", "-q", "cp", fl[-1], f"{tmp}/api_detail.jsonl"], check=True)
            for l in open(f"{tmp}/api_detail.jsonl"):
                r = json.loads(l); mk = {str(m.get("id")) for m in (r.get("makers") or []) if isinstance(m, dict)}
                if r.get("id") is not None and r.get("userId") is not None:
                    sh[str(r["id"])] = float(str(r["userId"]) in mk); hid[str(r["id"])] = str(r["userId"])
    except Exception as e:
        print("self_hunted skipped:", repr(e)[:120], flush=True)
    A["self_hunted"] = [sh.get(i, np.nan) for i in A.id]
    # E5's early recipe (gs://.../tmp/e5/early/early_model_recipe_v1_lm_com.json; orchestrator 09:20Z Nov 12): ridge on the
    # clean LM (shadow pred_clean) + identity-free comment counts; team = first top-level comment author + hunter (api_detail
    # userId, when a read <= T exists). Live threads limited to the 20 earliest top-level threads (training dumps hold <= 20).
    A["pred_rank_e5"] = np.nan; A["e5_score"] = np.nan
    try:
        rp = os.path.join(HERE, "results", "early_model_recipe_v1_lm_com.json")
        sp = os.path.join(HERE, "results", "shadow_makerfix", f"{day}.json")
        if os.path.exists(rp) and os.path.exists(sp):
            RC = json.load(open(rp)); key = {"P0": "1h", "P1": "1h", "P2": "2h", "P3": "3h", "P4": "4h"}[point]; Rk = RC["per_T"][key]
            SF = pd.DataFrame(json.load(open(sp))["forecast"]); pc = dict(zip(SF.id.astype(str), SF.pred_clean)) if "pred_clean" in SF else {}
            if pc:
                start = t0 + pd.Timedelta(minutes=1); Tm = (T - start).total_seconds() / 60
                Cc = C.sort_values("ts").copy(); Cc["top"] = Cc.parent.isna()
                feats = []
                for i in A.id:
                    g = Cc[Cc.id == i]
                    tops = g[g.top]
                    keep = set(tops.cid.head(20)); g = g[g.cid.isin(keep) | g.parent.isin(keep)]
                    team_ids = {u for u in [tops.user.iloc[0] if len(tops) else None, hid.get(i)] if u}
                    nt = g[~g.user.isin(team_ids)]
                    first = nt.ts.min()
                    feats.append({"id": i, "honest": pc.get(i, np.nan), "c_tot": np.log1p(len(nt)), "c_top": np.log1p(int(nt.top.sum())),
                                  "c_rep": np.log1p(int((~nt.top).sum())), "c_auth": np.log1p(nt.user.nunique()),
                                  "c_last1h": np.log1p(int((nt.ts > T - pd.Timedelta(hours=1)).sum())), "n_nt": len(nt),
                                  "c_first_min": (first - start).total_seconds() / 60 if pd.notna(first) else Tm})
                E = pd.DataFrame(feats)
                E["honest"] = E.honest.fillna(E.honest.min() - 0.1 if E.honest.notna().any() else Rk["mean"]["honest"])
                E["lm_rank"] = E.honest.rank(ascending=False, method="first"); E["lineup"] = np.log(len(E))
                E["c_share"] = E.n_nt / max(E.n_nt.sum(), 1)
                E["e5_score"] = sum(((E[f] - Rk["mean"][f]) / Rk["sd"][f]) * Rk["coef"][f] for f in RC["features"]) + Rk["intercept"]
                E["pred_rank_e5"] = E.e5_score.rank(ascending=False, method="first").astype(int)
                A["pred_rank_e5"] = A.id.map(dict(zip(E.id, E.pred_rank_e5))); A["e5_score"] = A.id.map(dict(zip(E.id, E.e5_score)))
    except Exception as e:
        print("e5 recipe skipped:", repr(e)[:160], flush=True)
    # rank_clean_thread (orchestrator 09:20Z / 08:45Z Nov 12; thread_feats.md): the clean 00:05 LM + rank-neutral thread
    # maker features as of 00:05 PT (first top-level author vs hunter, pre-launch non-hunter commenters, first author's
    # earlier launches); a 00:05 forecast recorded in the P files (data cut 00:05 for the thread part)
    A["pred_rank_clean_thread"] = np.nan; A["pred_rank_best_mix_th"] = np.nan
    try:
        tp = os.path.join(HERE, "results", "thread_live_model.json"); sp = os.path.join(HERE, "results", "shadow_makerfix", f"{day}.json")
        if os.path.exists(tp) and os.path.exists(sp):
            TM = json.load(open(tp)); SF = pd.DataFrame(json.load(open(sp))["forecast"])
            pc = dict(zip(SF.id.astype(str), SF.pred_clean)) if "pred_clean" in SF else {}
            dp = f"{tmp}/daily.json"
            subprocess.run(["gsutil", "-q", "cp", f"{B}/raw/daily/{day}/{day}.json", dp])
            hun = {str(x["id"]): str((x.get("user") or {}).get("id") or "") for x in json.load(open(dp))} if os.path.exists(dp) else {}
            t5 = t0 + pd.Timedelta(minutes=5); C5 = C[C.ts <= t5].sort_values("ts")
            # first-author history by user id from the dump: launches where the id was the first top-level commenter or the hunter
            Kd = K.copy(); Kd["day"] = Kd.ts.dt.tz_convert("America/Los_Angeles").dt.strftime("%Y-%m-%d")
            Lr = W.query("SELECT slug, day, daily_rank, poster FROM launches WHERE daily_rank IS NOT NULL", do_sync=False)
            Lr["rp"] = Lr.groupby("day").daily_rank.rank(pct=True, ascending=False); rp = dict(zip(Lr.slug, Lr.rp)); ld = dict(zip(Lr.slug, Lr.day))
            fa_hist = {}
            for sl, g in Kd[Kd.depth == 0].sort_values("ts").groupby("slug"):
                u = g.uid.iloc[0]
                if u and sl in rp:
                    fa_hist.setdefault(u, []).append((ld[sl], rp[sl]))
            for sl, pu in zip(Lr.slug, Lr.poster):
                u = name2id.get(str(pu or "").lower())
                if u and sl in rp:
                    fa_hist.setdefault(u, []).append((ld[sl], rp[sl]))
            rows = []
            for i in A.id:
                g = C5[C5.id == i]; tops = g[g.parent.isna()]
                fa = tops.user.iloc[0] if len(tops) else None; h = hun.get(i, "")
                prev = [r for d_, r in set(fa_hist.get(fa, [])) if d_ < day] if fa else []
                rows.append({"id": i, "honest": pc.get(i, np.nan), "th_has_first": float(fa is not None),
                             "th_hunter_first": float(bool(fa) and fa == h), "th_n_pre": float(g[g.user != h].user.nunique()),
                             "th_fa_n": float(np.log1p(len(prev))), "th_fa_rel": (sum(prev) + 1.0) / (len(prev) + 2) if prev else 0.5})
            E = pd.DataFrame(rows)
            if E.honest.notna().any():
                E["honest"] = E.honest.fillna(E.honest.min() - 0.1)
                E["lm_r"] = E.honest.rank(pct=True); E["n_day"] = np.log(len(E))
                E["sc"] = sum(((E[f] - TM["mu"][f]) / TM["sd"][f]) * TM["coef"][f] for f in TM["feats"]) + TM["intercept"]
                A["pred_rank_clean_thread"] = A.id.map(dict(zip(E.id, E.sc.rank(ascending=False, method="first").astype(int))))
            # orchestrator (live th_n_pre gradient holds: 1.00 / 1.10 / 0.63 / 0.11 by final rank group on 6 live days):
            # pred_rank_best_mix with th_n_pre (non-hunter commenters by 00:05) as a tie-breaker, at P0 / P1 only
            if point in ("P0", "P1") and A.pred_rank_best_mix.notna().any():
                npre = dict(zip(E.id, E.th_n_pre))
                A["pred_rank_best_mix_th"] = A.assign(_n=A.id.map(npre).fillna(0)).sort_values(["pred_rank_best_mix", "_n", "id"], ascending=[True, False, True]).pipe(
                    lambda z: pd.Series(np.arange(1, len(z) + 1), index=z.index)).reindex(A.index)
    except Exception as e:
        print("clean_thread skipped:", repr(e)[:160], flush=True)
    # orchestrator 04:10Z Nov 12 (depth analysis; provisional, scored forward): pred_rank_depth = positions 1-5 from
    # pred_rank_best, positions 6+ by the equal-weight mean (w_api 0.5) of the API and LM positions; watch15 = our top 15
    # by pred_rank_best at P2-P4 (the final top 10 was inside it for 97% of launches from 02:00 PT)
    if A.api_rank.notna().any():
        eq = (0.5 * A.pred_rank_api + 0.5 * lm_pos + 1e-6 * lm_pos)
        top5 = A.pred_rank_best <= 5
        rest = eq[~top5].rank(method="first") + 5
        A["pred_rank_depth"] = A.pred_rank_best.where(top5, rest).astype(int)
    else:
        A["pred_rank_depth"] = A.pred_rank_best
    A["watch15"] = ((A.pred_rank_best <= 15) & (point in ("P2", "P3", "P4"))).astype(int)
    # orchestrator 07:10Z Nov 12: the same recipe with the CLEAN 00:05 model (shadow_makerfix rank_clean) as the LM prior;
    # replay on 6 days (best_clean_replay.json): P1 72.2 vs 66.7 top 3, P2 / P3 slightly below the published-LM recipe
    A["pred_rank_best_clean"] = np.nan; A["pred_rank_best_mix"] = np.nan
    try:
        sp = os.path.join(HERE, "results", "shadow_makerfix", f"{day}.json")
        if not os.path.exists(sp):
            subprocess.run(["gsutil", "-q", "cp", f"{B}/results/shadow_makerfix/{day}.json", sp])
        if os.path.exists(sp):
            SF = pd.DataFrame(json.load(open(sp))["forecast"])
            if "rank_clean" in SF and A.api_rank.notna().any():
                rc = dict(zip(SF.id.astype(str), SF.rank_clean))
                cpos = pd.Series([rc.get(i, 999) for i in A.id], index=A.index).rank(method="first")
                A["pred_rank_best_clean"] = (w_api * A.pred_rank_api + (1 - w_api) * cpos + 1e-6 * cpos).rank(method="first").astype(int)
                # orchestrator 10:35Z Nov 12: mix = hidden rank w_api, the rest split equally between the clean and published
                # 00:05 ranks; no tuning until 15 days
                A["pred_rank_best_mix"] = (w_api * A.pred_rank_api + (1 - w_api) / 2 * cpos + (1 - w_api) / 2 * lm_pos
                                           + 1e-6 * lm_pos).rank(method="first").astype(int)
    except Exception as e:
        print("best_clean skipped:", repr(e)[:120], flush=True)
    res = {"day": day, "point": point, "data_up_to": T.isoformat(), "method": "comments_ridge", "launches": int(len(A)),
           "lm_matched": int(A.lm_matched.sum()), "team_known": int(sum(1 for i in ids if team.get(i, (0, 0, 0))[1])), "team_rule": "named makers + hunter by username (training rule)", "comments": int(len(C)), "written_at": now.isoformat(),
           "api_ranked": int(A.api_rank.notna().sum()),
           "forecast": A.sort_values("pred_rank")[["id", "pred_rank", "pred_rank_api", "pred_rank_blend", "pred_rank_best", "pred_rank_best2", "pred_rank_depth", "watch15", "pred_rank_best_clean", "pred_rank_best_mix", "pred_rank_e5", "pred_rank_clean_thread", "pred_rank_best_mix_th", "e5_score", "pred_rank_rule_a", "pred_rank_teamids", "api_rank", "n_c", "u_out", "u_out_teamids", "u_tie", "lm", "score",
                                                   "cv_sum", "cv_max", "cv_maker1", "cv_per_out", "cv_growth1h", "cv_snapshot",
                                                   "pred_rank_estvotes", "est_votes", "est_vel60", "weekly_rank", "exp_final_votes", "self_hunted", "has_prior_reviews"]].round(4).to_dict("records")}
    if os.environ.get("CF_DRY"):   # retro / test run: local scratch only, never the live results folder or bucket
        res["dry_run"] = True; p = os.path.join(os.environ["CF_DRY"], f"{day}_{point}.json"); json.dump(res, open(p, "w"), indent=1)
    else:
        os.makedirs(os.path.join(HERE, "results", "early_forecast"), exist_ok=True)
        p = os.path.join(HERE, "results", "early_forecast", f"{day}_{point}.json"); json.dump(res, open(p, "w"), indent=1)
        subprocess.run(["gsutil", "-q", "cp", p, f"{B}/results/early_forecast/{day}_{point}.json"], check=True)
    print(json.dumps({k: v for k, v in res.items() if k != "forecast"}))


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "fit":
        fit_live()
    elif a and a[0] == "live":
        live(a[1], a[2])
    else:
        main()
