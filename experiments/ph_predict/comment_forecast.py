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
    M = json.load(open(os.path.join(HERE, "results", "comment_forecast_live_model.json")))["cuts"]["P1" if point in ("P0", "P030") else ("P3" if point == "P345" else point)]
    # identity-free model (orchestrator 08:30Z Nov 12; comment_forecast_v2_teamc.md): no team split, fitted over the clean LM;
    # it is pred_rank from Nov 12; the old named-team model is kept as pred_rank_rule_a
    MNF = None
    pnf = os.path.join(HERE, "results", "comment_forecast_live_model_nf.json")
    if os.path.exists(pnf):
        MNF = json.load(open(pnf))["cuts"]["P1" if point in ("P0", "P030") else ("P3" if point == "P345" else point)]
    # P0 = 00:45 PT (orchestrator 02:15Z Nov 12): earliest useful pre-reveal point; the comment ridge uses P1's coefficients
    # P030 = 00:30 PT (orchestrator timing analysis Nov 12: light 0.25 hidden-rank blend already helps from 00:15)
    # P345 = 03:45 PT (orchestrator 02:39Z Nov 13): last pre-reveal read (reveal is 04:00 PT sharp); comment ridge uses P3's cut
    h = {"P0": 0.75, "P030": 0.5, "P345": 3.75}.get(point) or int(point[1:]); t0 = pd.Timestamp(day + " 00:00", tz="America/Los_Angeles").tz_convert("UTC")
    T = t0 + pd.Timedelta(hours=h); now = pd.Timestamp.now(tz="UTC")
    if now < T:
        print(json.dumps({"day": day, "point": point, "status": f"point {T} not reached"})); return
    tmp = tempfile.mkdtemp(prefix="cf_")
    comments_missing = False
    for f in ("posts_ts", "comments_ts", "people_ts"):
        r_ = 1 if (f == "comments_ts" and os.environ.get("CF_TEST_NO_COMMENTS")) else \
            subprocess.run(["gsutil", "-q", "cp", f"{B}/raw/ph_at_launch/{day}/live/{f}.jsonl", f"{tmp}/{f}.jsonl"]).returncode
        if r_:
            if f == "posts_ts":
                raise RuntimeError(f"missing live/{f}.jsonl for {day}")
            # orchestrator 09:18Z Nov 12: comments_ts missing -> write the file with every comment / thread column blank and
            # flagged (comments_missing), never another source
            comments_missing = comments_missing or f == "comments_ts"
            open(f"{tmp}/{f}.jsonl", "w").close()
    team, ids, api, rv = {}, set(), {}, {}
    snap_ids, inmax, hr_hist = {}, {}, []   # orchestrator QA 10:00Z Nov 12: inputs fetched <= T only; per-input max fetched_at recorded
    for l in open(f"{tmp}/posts_ts.jsonl"):
        r = json.loads(l)
        from early_forecast import pt_day   # day from featuredAt in PT (00:00 PT = 08:00:00Z is the new day; audit 05:00Z Nov 12)
        if r.get("fetch_status") != 200 or pt_day(r, day) != day:   # the line-up is fixed at 00:01 PT
            continue
        fa = pd.Timestamp(r.get("fetched_at") or r["snapshot_ts"])
        if fa > T:
            continue
        i = str(r["launch_id"]); ids.add(i); snap_ids.setdefault(str(r.get("snapshot_ts")), set()).add(i)
        inmax["posts"] = max(inmax.get("posts", fa), fa)
        # the official API's own post.dailyRank, populated before the reveal; latest fetched by T (fetched_at, no look-ahead)
        if str(r.get("source", "")).startswith("ph_api_v2") and r.get("daily_rank_at_fetch") is not None and fa <= T:
            hr_hist.append((fa, i, float(r["daily_rank_at_fetch"])))
            if i not in api or fa > api[i][0]:
                api[i] = (fa, float(r["daily_rank_at_fetch"]))
        if r.get("reviews_count") is not None and fa <= T and (i not in rv or fa > rv[i][0]):
            rv[i] = (fa, float(r["reviews_count"]))
    # orchestrator 23:03Z Nov 12: pre-cut ranking reads (~:58 / ~:28) in precut/<tag>_api.jsonl; the latest one fetched <= T
    # supplies the hidden rank (instead of the 15-min snapshot before the cut)
    pc_ = f"{tmp}/precut"; os.makedirs(pc_, exist_ok=True)
    subprocess.run(["gsutil", "-q", "-m", "cp", f"{B}/raw/ph_at_launch/{day}/precut/*_api.jsonl", pc_ + "/"], stderr=subprocess.DEVNULL)
    n_precut = 0
    for f_ in sorted(os.listdir(pc_)):
        for l in open(f"{pc_}/{f_}"):
            r = json.loads(l)
            if r.get("dailyRank") is None or not r.get("snapshot_at"):
                continue
            fa = pd.Timestamp(r["snapshot_at"]); i = str(r.get("id"))
            if fa > T or pt_day({"featuredAt": r.get("featuredAt"), "day": day}, day) != day:
                continue
            hr_hist.append((fa, i, float(r["dailyRank"])))
            if i not in api or fa > api[i][0]:
                api[i] = (fa, float(r["dailyRank"])); n_precut += 1
                inmax["posts"] = max(inmax.get("posts", fa), fa)
    withdrawn = []
    if snap_ids:   # a launch absent from the latest snapshot <= T was withdrawn: out of the line-up (and of scoring)
        last = snap_ids[max(snap_ids)]
        if len(last) >= 0.8 * len(ids):
            withdrawn = sorted(ids - last); ids = ids & last
    pid, pnames, phun = {}, {}, {}   # launch -> maker/hunter PH user ids (people_ts: user_id, role, launch_ids); username -> id
    for l in open(f"{tmp}/people_ts.jsonl"):
        r = json.loads(l)
        fp_ = r.get("fetched_at") or r.get("snapshot_ts")
        if fp_ and pd.Timestamp(fp_) > T:
            continue
        if r.get("user_id"):
            if r.get("username"):
                pnames[str(r["username"]).lower()] = str(r["user_id"])
            for i in r.get("launch_ids") or []:
                pid.setdefault(str(i), set()).add(str(r["user_id"]))
                if r.get("role") == "hunter":
                    phun[str(i)] = str(r["user_id"])
    C = []
    for l in open(f"{tmp}/comments_ts.jsonl"):
        r = json.loads(l)
        if r.get("created_at"):
            # identity = commenter_user_id: the live "username" field is one constant per launch, not the commenter
            C.append((str(r["launch_id"]), r.get("comment_id"), str(r.get("commenter_user_id") or r.get("user_id") or ""), r["created_at"], r.get("parent_id"),
                      r.get("fetched_at") or r.get("snapshot_ts")))
    # replies live in api_replies/<tag>.jsonl (comments_ts holds top-level comments only; the training dumps hold both)
    rd_ = f"{tmp}/replies"; os.makedirs(rd_, exist_ok=True)
    subprocess.run(["gsutil", "-q", "-m", "cp", f"{B}/raw/ph_at_launch/{day}/api_replies/*.jsonl", rd_ + "/"], stderr=subprocess.DEVNULL)
    n_rep_rows = 0
    for f_ in sorted(os.listdir(rd_)):
        for l in open(f"{rd_}/{f_}"):
            r = json.loads(l)
            if r.get("createdAt") and r.get("post_id"):
                C.append((str(r["post_id"]), r.get("comment_id"), str(r.get("commenter_user_id") or ""), r["createdAt"], r.get("parentId"), r.get("snapshot_at")))
                n_rep_rows += 1
    C = pd.DataFrame(C, columns=["id", "cid", "user", "created", "parent", "fetched"]).drop_duplicates("cid")
    C["ts"] = pd.to_datetime(C.created, utc=True, errors="coerce"); C["ft"] = pd.to_datetime(C.fetched, utc=True, errors="coerce")
    C = C[(C.ts <= T) & C.id.isin(ids) & (C.ft <= T)]
    if len(C):
        inmax["comments"] = C.ft.max()
    elif not comments_missing:
        comments_missing = "no comment fetched by the cut"   # capture starts ~01:30 PT: comment columns blank by design before it
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
    w_api = 0.25 if point == "P030" else (0.5 if point in ("P0", "P1") else 0.75)
    lm_pos = A.lm.rank(ascending=False, method="first")
    if A.api_rank.notna().any():
        A["pred_rank_best"] = (w_api * A.pred_rank_api + (1 - w_api) * lm_pos + 1e-6 * lm_pos).rank(method="first").astype(int)
    else:
        A["pred_rank_best"] = lm_pos.astype(int)
    # orchestrator timing analysis (Nov 12): at P0 a lighter 0.25 weight on the hidden rank as a shadow variant (LODO picks
    # 0.25 at 00:30, 0.5 at 01:00); scored forward next to pred_rank_best (0.5 at P0)
    A["pred_rank_best_w25"] = ((0.25 * A.pred_rank_api + 0.75 * lm_pos + 1e-6 * lm_pos).rank(method="first").astype(int)
                               if A.api_rank.notna().any() and point == "P0" else np.nan)
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
            RC = json.load(open(rp)); key = {"P030": "1h", "P0": "1h", "P1": "1h", "P2": "2h", "P3": "3h", "P345": "4h", "P4": "4h"}[point]; Rk = RC["per_T"][key]
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
    npre_th = None; th_missing = None; th_source = None; A["pred_rank_clean_thread"] = np.nan; A["pred_rank_best_mix_th"] = np.nan; A["pred_rank_clean_thread_z"] = np.nan; A["pred_rank_clean_stack"] = np.nan; A["pred_rank_clean_nosite_thread"] = np.nan; A["pred_rank_clean_nosite_tb"] = np.nan; A["pred_rank_mrep"] = np.nan; A["pred_rank_clean_nosite_hf"] = np.nan; A["pred_rank_h25_th"] = np.nan; A["pred_rank_readable_v2_th"] = np.nan
    try:
        tp = os.path.join(HERE, "results", "thread_live_model.json"); sp = os.path.join(HERE, "results", "shadow_makerfix", f"{day}.json")
        if os.path.exists(tp) and os.path.exists(sp):
            TM = json.load(open(tp)); SF = pd.DataFrame(json.load(open(sp))["forecast"])
            pc = dict(zip(SF.id.astype(str), SF.pred_clean)) if "pred_clean" in SF else {}
            dp = f"{tmp}/daily.json"
            subprocess.run(["gsutil", "-q", "cp", f"{B}/raw/daily/{day}/{day}.json", dp])
            hun = {str(x["id"]): str((x.get("user") or {}).get("id") or "") for x in json.load(open(dp))} if os.path.exists(dp) else {}
            wposter = dict(zip(*[W.query("SELECT CAST(id AS VARCHAR) id, lower(poster) p FROM launches", do_sync=False)[c] for c in ("id", "p")]))
            t5 = t0 + pd.Timedelta(minutes=5)
            # orchestrator 02:53Z Nov 13: th_n_pre (and the other 00:05 thread inputs) ONLY from the 00:07 PT read (fetched <= 00:12 PT);
            # if that read is missing, the thread inputs are MISSING (fall back to clean_nosite); the capped 01:30+ reads dropped
            # 21% of pre-launch comments and are never used for them
            # Nov 13: the "00:07" read actually landed at 00:15 PT, so the rule is the night's FIRST comment read (all rows fetched within
            # 5 min of the earliest fetch), provided it landed by 00:30 PT; never a later (capped 01:30+) read
            f0 = C.ft.min() if len(C) else pd.NaT
            ok0 = pd.notna(f0) and f0 <= t0 + pd.Timedelta(minutes=30)
            C5 = C[(C.ts <= t5) & (C.ft <= f0 + pd.Timedelta(minutes=5))].sort_values("ts") if ok0 else C.iloc[0:0]
            no007 = C5.empty
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
                fa = tops.user.iloc[0] if len(tops) else None
                # hunter id (orchestrator 09:16Z Nov 12): daily JSON post.user.id, else people_ts role=hunter, else warehouse poster -> id;
                # unknown -> thread features MISSING (filled with the day mean below), never "everyone is a non-hunter"
                h = hun.get(i) or phun.get(i) or name2id.get(wposter.get(i, ""), "")
                prev = [r for d_, r in set(fa_hist.get(fa, [])) if d_ < day] if fa else []
                rows.append({"id": i, "honest": pc.get(i, np.nan), "th_has_first": np.nan if no007 else float(fa is not None),
                             "th_hunter_first": float(bool(fa) and fa == h) if (h and not no007) else np.nan,
                             "th_n_pre": float(g[g.user != h].user.nunique()) if (h and not no007) else np.nan,
                             "th_fa_n": float(np.log1p(len(prev))), "th_fa_rel": (sum(prev) + 1.0) / (len(prev) + 2) if prev else 0.5})
            E = pd.DataFrame(rows); th_missing = int(E.th_n_pre.isna().sum()); th_source = "missing: no first comment read by 00:30 PT" if no007 else f"first comment read, fetched {f0.tz_convert('America/Los_Angeles').strftime('%H:%M:%S')} PT"
            if no007:   # constant inputs -> zero weight in the within-day z models; the columns then follow clean_nosite
                E["th_has_first"] = 0.0
            for f_ in ("th_hunter_first", "th_n_pre"):
                E[f_] = E[f_].fillna(E[f_].mean() if E[f_].notna().any() else TM["mu"][f_])
            if E.honest.notna().any():
                E["honest"] = E.honest.fillna(E.honest.min() - 0.1)
                E["lm_r"] = E.honest.rank(pct=True); E["n_day"] = np.log(len(E))
                E["sc"] = sum(((E[f] - TM["mu"][f]) / TM["sd"][f]) * TM["coef"][f] for f in TM["feats"]) + TM["intercept"]
                A["pred_rank_clean_thread"] = A.id.map(dict(zip(E.id, E.sc.rank(ascending=False, method="first").astype(int))))
                # orchestrator 08:29Z Nov 12 (stack): within-day z, alpha 10 (results/thread_live_model_z.json; thread_feats.md)
                zp = os.path.join(HERE, "results", "thread_live_model_z.json")
                if os.path.exists(zp):
                    import re
                    sl = {str(x["id"]): str(x.get("slug") or "") for x in json.load(open(dp))} if os.path.exists(dp) else {}
                    def _sn(s_):
                        m_ = re.search(r"-(\d+)$", re.sub(r"-[0-9a-f]{8,}$", "", s_))
                        return float(np.log(np.clip(int(m_.group(1)), 1, 50))) if m_ else 1.0
                    E["slug_num_l"] = E.id.map(lambda i: _sn(sl.get(i, "")))
                    # orchestrator 14:34Z Nov 12: candidate deploy model clean_nosite_thread = clean without llm_site (shadow
                    # pred_clean_nosite) + thread features, within-day z ridge (results/thread_live_model_z_nosite.json)
                    zn = os.path.join(HERE, "results", "thread_live_model_z_nosite.json")
                    pcn = dict(zip(SF.id.astype(str), SF.pred_clean_nosite)) if "pred_clean_nosite" in SF else {}
                    if os.path.exists(zn) and pcn:
                        En = E.assign(honest=E.id.map(pcn)); En["honest"] = En.honest.fillna(En.honest.min() - 0.1)
                        cn_ = json.load(open(zn))["models"]["clean_thread_z"]["coef"]
                        sn_ = sum(((En[f] - En[f].mean()) / En[f].std() if En[f].std() > 0 else En[f] * 0.0) * c for f, c in cn_.items())
                        A["pred_rank_clean_nosite_thread"] = A.id.map(dict(zip(En.id, sn_.rank(ascending=False, method="first").astype(int))))
                    # clean_nosite_tb (orchestrator 01:47Z Nov 13): clean_nosite order with positions 2-6 re-ordered by the frozen
                    # z(clean) + z(th_n_pre) score (results/frozen/clean_nosite_tb_20261113.json)
                    tbp = os.path.join(HERE, "results", "frozen", "clean_nosite_tb_20261113.json")
                    if os.path.exists(tbp) and pcn:
                        Et = E.assign(honest=E.id.map(pcn)); Et["honest"] = Et.honest.fillna(Et.honest.min() - 0.1)
                        tw = json.load(open(tbp))["coef"]; zz = lambda s_: (s_ - s_.mean()) / s_.std() if s_.std() > 0 else s_ * 0.0
                        Et["tb"] = tw["z_clean"] * zz(Et.honest) + tw["z_npre"] * zz(Et.th_n_pre)
                        o0 = Et.sort_values(["honest", "id"], ascending=[False, True]).id.tolist()
                        mid = Et[Et.id.isin(o0[1:6])].sort_values(["tb", "id"], ascending=[False, True]).id.tolist()
                        otb = o0[:1] + mid + o0[6:]
                        A["pred_rank_clean_nosite_tb"] = A.id.map({i: k + 1 for k, i in enumerate(otb)})
                    for nm_, mz in json.load(open(zp))["models"].items():
                        sc_ = sum(((E[f] - E[f].mean()) / E[f].std() if E[f].std() > 0 else E[f] * 0.0) * c for f, c in mz["coef"].items())
                        A["pred_rank_" + nm_] = A.id.map(dict(zip(E.id, sc_.rank(ascending=False, method="first").astype(int))))
            # orchestrator (live th_n_pre gradient holds: 1.00 / 1.10 / 0.63 / 0.11 by final rank group on 6 live days):
            # pred_rank_best_mix with th_n_pre (non-hunter commenters by 00:05) as a tie-breaker, at P0 / P1 only
            npre_th = dict(zip(E.id, E.th_n_pre))   # used after best_mix is computed (below)
            # orchestrator 02:53Z Nov 13 (maker_replies.md, 214-day LODO +1.9 [+0.8, +3.0] top 3 at 00:30): pred_rank_mrep at P030 =
            # frozen ridge on z(clean_nosite) + z(th_n_pre) + z(log1p distinct non-hunter commenters <= T) + z(log1p total comments
            # <= T) + z(log1p hunter replies <= T); team = hunter only (00:05-safe). results/frozen/maker_replies_20261113.json
            # P1 (orchestrator 02:57Z Nov 13): weights from the FULL-team 214-day fit (maker_replies_P1_fullteam_20261113.json); live team =
            # the 00:05-safe set: hunter + makers named with a real id in raw/daily/<d>/today_0005.json (redacted makers carry id 0)
            mrp = os.path.join(HERE, "results", "frozen", "maker_replies_P1_fullteam_20261113.json" if point == "P1" else "maker_replies_20261113.json")
            if (point in ("P030", "P1") or os.environ.get("MREP_TEST")) and os.path.exists(mrp) and "pred_clean_nosite" in SF:
                MW = json.load(open(mrp))["points"]["P1" if point == "P1" else "P030"]["coef"]; cnz = dict(zip(SF.id.astype(str), SF.pred_clean_nosite))
                hid = {i: (hun.get(i) or phun.get(i) or name2id.get(wposter.get(i, ""), "")) for i in A.id}
                team05 = {i: {hid[i]} - {""} for i in A.id}
                if point == "P1":
                    p05 = f"{tmp}/today_0005.json"
                    subprocess.run(["gsutil", "-q", "cp", f"{B}/raw/daily/{day}/today_0005.json", p05], stderr=subprocess.DEVNULL)
                    if os.path.exists(p05):
                        for x_ in json.load(open(p05)):
                            if str(x_.get("id")) in team05:
                                team05[str(x_["id"])] |= {str(m_.get("id")) for m_ in (x_.get("makers") or [])
                                                          if m_.get("id") and str(m_.get("id")) != "0" and m_.get("username") != "[REDACTED]"}
                Fm = pd.DataFrame({"id": A.id.values}); Fm["clean"] = Fm.id.map(cnz); Fm["clean"] = Fm.clean.fillna(Fm.clean.min() - 0.1)
                Fm["npre"] = Fm.id.map(npre_th).fillna(0)
                Fm["nu"] = np.log1p([C[(C.id == i) & (C.user != hid[i])].user.nunique() for i in Fm.id])
                Fm["nc"] = np.log1p([int((C.id == i).sum()) for i in Fm.id])
                Fm["mrep_h"] = np.log1p([int(((C.id == i) & (C.user == hid[i]) & C.parent.notna()).sum()) if hid[i] else 0 for i in Fm.id])
                Fm["mrep"] = np.log1p([int(((C.id == i) & C.user.isin(team05[i]) & C.parent.notna()).sum()) for i in Fm.id])
                zz_ = lambda s_: (s_ - s_.mean()) / s_.std() if s_.std() > 0 else s_ * 0.0
                sc_m = sum(zz_(Fm[f.replace("z_", "")]) * c for f, c in MW.items())
                A["pred_rank_mrep"] = A.id.map(dict(zip(Fm.id, sc_m.rank(ascending=False, method="first").astype(int))))
            # orchestrator 05:00Z Nov 13: clean_nosite_hf (top-10 candidate) at P030 = frozen ridge z(clean_nosite) + z(th_n_pre, 00:07 read)
            # + z(log1p hunter followersCount) with the follower count ONLY from the 00:05 read (raw/daily/<d>/today_0005.json)
            hfp = os.path.join(HERE, "results", "frozen", "clean_nosite_hf_20261113.json")
            if (point == "P030" or os.environ.get("HF_TEST")) and os.path.exists(hfp) and "pred_clean_nosite" in SF:
                p05h = f"{tmp}/today_0005_hf.json"
                subprocess.run(["gsutil", "-q", "cp", f"{B}/raw/daily/{day}/today_0005.json", p05h], stderr=subprocess.DEVNULL)
                if os.path.exists(p05h):
                    hfol = {str(x_.get("id")): (x_.get("user") or {}).get("followersCount") for x_ in json.load(open(p05h))}
                    HW = json.load(open(hfp))["coef"]; cnh = dict(zip(SF.id.astype(str), SF.pred_clean_nosite))
                    Fh = pd.DataFrame({"id": A.id.values}); Fh["clean"] = Fh.id.map(cnh); Fh["clean"] = Fh.clean.fillna(Fh.clean.min() - 0.1)
                    Fh["npre"] = Fh.id.map(npre_th).fillna(0)
                    Fh["hf"] = np.log1p(pd.to_numeric(Fh.id.map(hfol), errors="coerce")); Fh["hf"] = Fh.hf.fillna(Fh.hf.median() if Fh.hf.notna().any() else 0.0)
                    zzh = lambda s_: (s_ - s_.mean()) / s_.std() if s_.std() > 0 else s_ * 0.0
                    sch = sum(zzh(Fh[f.replace("z_", "")]) * c for f, c in HW.items())
                    A["pred_rank_clean_nosite_hf"] = A.id.map(dict(zip(Fh.id, sch.rank(ascending=False, method="first").astype(int))))
            # orchestrator 05:05Z Nov 13: h25 + th_n_pre at P030 (frozen results/frozen/h25_th_20261113.json; 214-day LODO top 5 +1.6 [+0.4, +2.8])
            h25p = os.path.join(HERE, "results", "shadow_h25", f"{day}.json"); h25w = os.path.join(HERE, "results", "frozen", "h25_th_20261113.json")
            if (point == "P030" or os.environ.get("HF_TEST")) and os.path.exists(h25p) and os.path.exists(h25w):
                H25 = pd.DataFrame(json.load(open(h25p))["forecast"]); h25 = dict(zip(H25.id.astype(str), H25.pred_clean_nosite_h25))
                Fq = pd.DataFrame({"id": A.id.values}); Fq["h25"] = Fq.id.map(h25); Fq["h25"] = Fq.h25.fillna(Fq.h25.min() - 0.1)
                Fq["npre"] = Fq.id.map(npre_th).fillna(0); QW = json.load(open(h25w))["coef"]
                zzq = lambda s_: (s_ - s_.mean()) / s_.std() if s_.std() > 0 else s_ * 0.0
                scq = sum(zzq(Fq[f.replace("z_", "")]) * c for f, c in QW.items())
                A["pred_rank_h25_th"] = A.id.map(dict(zip(Fq.id, scq.rank(ascending=False, method="first").astype(int))))
            # orchestrator 18:46Z Nov 13: readable v2 stumps + th_n_pre at P030 (frozen results/frozen/readable_v2_th_20261113.json;
            # 214 days: -1.2 [-3.4, +0.9] top 3 vs clean+th, not worse; the explanation model, scored forward)
            rdp = os.path.join(HERE, "results", "shadow_readable", f"{day}.json"); rdw = os.path.join(HERE, "results", "frozen", "readable_v2_th_20261113.json")
            if (point == "P030" or os.environ.get("HF_TEST")) and os.path.exists(rdp) and os.path.exists(rdw):
                RD = pd.DataFrame(json.load(open(rdp))["forecast"]); rd = dict(zip(RD.id.astype(str), RD.pred_readable_v2))
                Fr = pd.DataFrame({"id": A.id.values}); Fr["readable"] = Fr.id.map(rd); Fr["readable"] = Fr.readable.fillna(Fr.readable.min() - 0.1)
                Fr["npre"] = Fr.id.map(npre_th).fillna(0); RW = json.load(open(rdw))["coef"]
                zzr = lambda s_: (s_ - s_.mean()) / s_.std() if s_.std() > 0 else s_ * 0.0
                scr = sum(zzr(Fr[f.replace("z_", "")]) * c for f, c in RW.items())
                A["pred_rank_readable_v2_th"] = A.id.map(dict(zip(Fr.id, scr.rank(ascending=False, method="first").astype(int))))
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
    A["watch15"] = ((A.pred_rank_best <= 15) & (point in ("P2", "P3", "P345", "P4"))).astype(int)
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
                A["_mix_score"] = w_api * A.pred_rank_api + (1 - w_api) / 2 * cpos + (1 - w_api) / 2 * lm_pos
                A["pred_rank_best_mix"] = (A._mix_score + 1e-6 * lm_pos).rank(method="first").astype(int)
    except Exception as e:
        print("best_clean skipped:", repr(e)[:120], flush=True)
    # orchestrator 12:49Z Nov 12: best_thread = w_api x hidden API rank position + (1 - w_api) x clean_thread_z position
    # (scored shadow column; "best" unchanged; replay prior_blend.md: within 1-3 hits of published / clean on 6 days)
    A["pred_rank_best_thread"] = np.nan
    if "pred_rank_clean_thread_z" in A and A.pred_rank_clean_thread_z.notna().any() and A.pred_rank_api.notna().any():
        tz_ = A.pred_rank_clean_thread_z.rank(method="first")
        A["pred_rank_best_thread"] = (w_api * A.pred_rank_api + (1 - w_api) * tz_ + 1e-6 * tz_).rank(method="first").astype(int)
    # orchestrator 01:43Z Nov 13: forward lines at P1 / P2 / P3 (weights frozen in results/frozen/prereveal_hr_clean_20261113.json):
    #   hr          hidden rank as is (= pred_rank_api)
    #   hr_clean    frozen ridge on z(log hidden pos), z(move since 01:00), z(log1p comments), z(log1p commenters), z(clean_nosite)
    #   best        the published-LM blend (unchanged)
    #   best_cnosite  w_api x hidden pos + (1 - w_api) x clean_nosite pos
    A["pred_rank_hr"] = A.pred_rank_api; A["pred_rank_hr_clean"] = np.nan; A["pred_rank_best_cnosite"] = np.nan
    try:
        fzp = os.path.join(HERE, "results", "frozen", "prereveal_hr_clean_20261113.json")
        sp2 = os.path.join(HERE, "results", "shadow_makerfix", f"{day}.json")
        if point == "P345":
            fzp = os.path.join(HERE, "results", "frozen", "prereveal_hr_clean_P345_20261113.json")
        if point in ("P030", "P0", "P1", "P2", "P3", "P345") and os.path.exists(fzp) and os.path.exists(sp2) and A.pred_rank_api.notna().any():
            SF2 = pd.DataFrame(json.load(open(sp2))["forecast"])
            if "pred_clean_nosite" in SF2:
                cn = dict(zip(SF2.id.astype(str), SF2.pred_clean_nosite))
                Hh = pd.DataFrame(hr_hist, columns=["a", "id", "r"])
                p1 = Hh[Hh.a <= t0 + pd.Timedelta(hours=1)].sort_values("a").groupby("id").r.last()
                pos1 = pd.Series([p1.get(i, 999) for i in A.id], index=A.index).rank(method="first")
                posT = A.pred_rank_api.rank(method="first")
                cC = C.groupby("id").size(); cU = C.groupby("id").user.nunique()
                Z = pd.DataFrame({"lpos": np.log(posT), "move": np.log(pos1) - np.log(posT),
                                  "nc": np.log1p(A.id.map(cC).fillna(0)), "nu": np.log1p(A.id.map(cU).fillna(0)),
                                  "clean": A.id.map(cn)}, index=A.index)
                Z["clean"] = Z.clean.fillna(Z.clean.mean())
                zf_ = lambda s_: (s_ - s_.mean()) / s_.std() if s_.std() > 0 else s_ * 0.0
                fzw = json.load(open(fzp))["points"]["P1" if point in ("P030", "P0") else point]["coef"]   # P030 / P0 use P1's weights
                sc_ = sum(zf_(Z[f.replace("z_", "")]) * c for f, c in fzw.items())
                A["pred_rank_hr_clean"] = sc_.rank(ascending=False, method="first").astype(int)
                cpos_ = pd.Series([cn.get(i, -99) for i in A.id], index=A.index).rank(ascending=False, method="first")
                A["pred_rank_best_cnosite"] = (w_api * posT + (1 - w_api) * cpos_ + 1e-6 * cpos_).rank(method="first").astype(int)
    except Exception as e:
        print("hr_clean skipped:", repr(e)[:160], flush=True)
    # orchestrator 03:34Z Nov 13 (early_hidden.md, 7-day replay: top 10 +10.0 [+2.9, +18.6] at 00:30 vs clean_nosite + th_n_pre; top 3 not
    # better): pred_rank_eh at P030 = frozen ridge z(-log hidden pos) + z(clean_nosite) + z(th_n_pre, 00:07 read). A top-10 line.
    A["pred_rank_eh"] = np.nan
    try:
        ehp = os.path.join(HERE, "results", "frozen", "early_hidden_20261113.json"); sp3 = os.path.join(HERE, "results", "shadow_makerfix", f"{day}.json")
        if point == "P030" and os.path.exists(ehp) and os.path.exists(sp3) and A.pred_rank_api.notna().any():
            SF3 = pd.DataFrame(json.load(open(sp3))["forecast"])
            if "pred_clean_nosite" in SF3:
                cn3 = dict(zip(SF3.id.astype(str), SF3.pred_clean_nosite)); zz3 = lambda s_: (s_ - s_.mean()) / s_.std() if s_.std() > 0 else s_ * 0.0
                Z3 = pd.DataFrame({"lpos": -np.log(A.pred_rank_api.rank(method="first")), "clean": A.id.map(cn3),
                                   "npre": A.id.map(npre_th or {}).fillna(0)}, index=A.index)
                Z3["clean"] = Z3.clean.fillna(Z3.clean.min() - 0.1)
                w3 = json.load(open(ehp))["points"]["00:30"]["coef"]
                A["pred_rank_eh"] = sum(zz3(Z3[f.replace("z_", "")]) * c for f, c in w3.items()).rank(ascending=False, method="first").astype(int)
    except Exception as e:
        print("eh skipped:", repr(e)[:160], flush=True)
    # orchestrator 02:39Z Nov 13: hybrid at every pre-reveal point = top 5 from the plain hidden order, slots 6+ from hr_clean
    A["pred_rank_hybrid"] = np.nan
    if A.pred_rank_api.notna().any() and A.pred_rank_hr_clean.notna().any():
        h5 = A.sort_values(["pred_rank_api", "id"]).id.tolist()[:5]
        rest = [i for i in A.sort_values(["pred_rank_hr_clean", "id"]).id if i not in set(h5)]
        A["pred_rank_hybrid"] = A.id.map({i: k + 1 for k, i in enumerate(h5 + rest)})
    if npre_th is not None and point in ("P030", "P0", "P1") and A.pred_rank_best_mix.notna().any():
        # QA 10:00Z Nov 12: sorting the strict best_mix ranking never let the tie-break act; near-ties of the blended score
        # (same 0.5-rank-unit bucket) are now ordered by th_n_pre
        A["pred_rank_best_mix_th"] = A.assign(_n=A.id.map(npre_th).fillna(0), _b=np.floor(A._mix_score / 0.5)).sort_values(["_b", "_n", "pred_rank_best_mix"], ascending=[True, False, True]).pipe(
            lambda z: pd.Series(np.arange(1, len(z) + 1), index=z.index)).reindex(A.index)
    if comments_missing:   # blank every column that reads comments (identity-free ridge, old rule, team ids, thread lines, e5)
        for c_ in [c for c in A.columns if c in ("pred_rank", "pred_rank_rule_a", "pred_rank_teamids", "pred_rank_blend", "pred_rank_e5", "e5_score",
                   "pred_rank_clean_thread", "pred_rank_clean_thread_z", "pred_rank_clean_stack", "pred_rank_best_mix_th", "pred_rank_mrep", "n_c", "u_out",
                   "u_out_teamids", "u_tie", "score")]:
            A[c_] = np.nan
    sp_ = os.path.join(HERE, "results", "shadow_makerfix", f"{day}.json")
    if os.path.exists(sp_):
        inmax["clean_shadow"] = pd.Timestamp(json.load(open(sp_)).get("written_at") or pd.Timestamp(os.path.getmtime(sp_), unit="s", tz="UTC"))
    late = (now - T) > pd.Timedelta(minutes=90)
    dep = {"comments": ["pred_rank", "pred_rank_rule_a", "pred_rank_teamids", "pred_rank_blend", "pred_rank_e5", "pred_rank_clean_thread",
                        "pred_rank_clean_thread_z", "pred_rank_clean_stack", "pred_rank_best_mix_th", "pred_rank_best_thread", "pred_rank_clean_nosite_thread", "pred_rank_hr_clean", "pred_rank_clean_nosite_tb", "pred_rank_hybrid", "pred_rank_mrep"],
           "clean_shadow": ["pred_rank_best_clean", "pred_rank_best_mix", "pred_rank_best_mix_th", "pred_rank_e5", "pred_rank_clean_thread",
                            "pred_rank_clean_thread_z", "pred_rank_clean_stack", "pred_rank_best_thread", "pred_rank_clean_nosite_thread", "pred_rank_hr_clean", "pred_rank_best_cnosite", "pred_rank_clean_nosite_tb", "pred_rank_hybrid", "pred_rank_mrep", "pred_rank_eh", "pred_rank_clean_nosite_hf", "pred_rank_h25_th", "pred_rank_readable_v2_th"],
           "posts": ["pred_rank_api", "pred_rank_best", "pred_rank_best2", "pred_rank_best_w25", "pred_rank_depth", "pred_rank_estvotes", "pred_rank_hr"]}
    col_status = {}
    for src_, cols_ in dep.items():
        for c_ in cols_:
            t_ = inmax.get(src_)
            st_ = "blank" if t_ is None else ("backfilled (inputs fetched after the cut)" if t_ > T else ("late" if late else "live"))
            prev = col_status.get(c_, {}).get("status")
            if prev == "blank" or (prev and prev != "live" and st_ == "live"):
                st_ = prev
            col_status[c_] = {"status": st_, "inputs_fetched_max": {**col_status.get(c_, {}).get("inputs_fetched_max", {}), src_: t_.isoformat() if t_ is not None else None}}
    res = {"day": day, "point": point, "data_up_to": T.isoformat(), "method": "comments_ridge", "launches": int(len(A)),
           "column_status": col_status, "withdrawn_excluded": withdrawn, "reply_rows_read": n_rep_rows, "reply_rows_used": int(C.parent.notna().sum()), "precut_rank_rows": n_precut,
           "hidden_rank_note": "each point's hidden API rank is the latest posts_ts read fetched <= the cut (the 15-min snapshot before it)",
           "lm_matched": int(A.lm_matched.sum()), "team_known": int(sum(1 for i in ids if team.get(i, (0, 0, 0))[1])), "team_rule": "named makers + hunter by username (training rule)", "comments": int(len(C)), "comments_missing": comments_missing, "thread_hunter_missing": th_missing, "th_n_pre_source": th_source, "written_at": now.isoformat(),
           "api_ranked": int(A.api_rank.notna().sum()),
           "forecast": A.sort_values("pred_rank")[["id", "pred_rank", "pred_rank_api", "pred_rank_blend", "pred_rank_best", "pred_rank_best2", "pred_rank_best_w25", "pred_rank_depth", "watch15", "pred_rank_best_clean", "pred_rank_best_mix", "pred_rank_e5", "pred_rank_clean_thread", "pred_rank_clean_thread_z", "pred_rank_clean_stack", "pred_rank_clean_nosite_thread", "pred_rank_clean_nosite_tb", "pred_rank_best_thread", "pred_rank_hr", "pred_rank_hr_clean", "pred_rank_hybrid", "pred_rank_mrep", "pred_rank_eh", "pred_rank_clean_nosite_hf", "pred_rank_h25_th", "pred_rank_readable_v2_th", "pred_rank_best_cnosite", "pred_rank_best_mix_th", "e5_score", "pred_rank_rule_a", "pred_rank_teamids", "api_rank", "n_c", "u_out", "u_out_teamids", "u_tie", "lm", "score",
                                                   "cv_sum", "cv_max", "cv_maker1", "cv_per_out", "cv_growth1h", "cv_snapshot",
                                                   "pred_rank_estvotes", "est_votes", "est_vel60", "weekly_rank", "exp_final_votes", "self_hunted", "has_prior_reviews"]].round(4).astype(object).where(lambda z: z.notna(), None).to_dict("records")}
    if os.environ.get("CF_DRY"):   # retro / test run: local scratch only, never the live results folder or bucket
        res["dry_run"] = True; p = os.path.join(os.environ["CF_DRY"], f"{day}_{point}.json"); json.dump(res, open(p, "w"), indent=1)
    else:
        os.makedirs(os.path.join(HERE, "results", "early_forecast"), exist_ok=True)
        p = os.path.join(HERE, "results", "early_forecast", f"{day}_{point}.json"); json.dump(res, open(p, "w"), indent=1)
        subprocess.run(["gsutil", "-q", "cp", p, f"{B}/results/early_forecast/{day}_{point}.json"], check=True)
        import heartbeat; heartbeat.beat(f"pre_reveal {point}", day, T, "late" if late else ("comments_missing" if comments_missing else "ok"))
    print(json.dumps({k: v for k, v in res.items() if k != "forecast"}))


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "fit":
        fit_live()
    elif a and a[0] == "live":
        live(a[1], a[2])
    else:
        main()
