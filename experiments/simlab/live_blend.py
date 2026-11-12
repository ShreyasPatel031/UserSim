"""Hidden pre-reveal rank blended with three 00:05 priors on the live days (orchestrator 08:34Z Nov 12, item 3). Counts only.
Days: live days with pre-reveal hidden-rank reads AND a clean live score (clean_live_rows3, clean_v3 daily expanding refit on 00:05
inputs): Nov 2, 3, 4, 8, 9, 10 (Nov 11 has no clean live row yet).
Hidden rank at cut T: latest official API dailyRank read <= T from warehouse vote_snapshots (hourly ~00:07, 01:00, 02:00 PT) and
live/posts_ts.jsonl daily_rank_at_fetch (15-min, Nov 4, 8, 9, 10); unranked -> after all ranked, ties broken by the prior.
Priors: published = forecasts table launch_model, first run of the day; clean = clean_v3 live; stack = clean_thread_z weights
(PH agent thread_live_model_z.json) on within-day z of [clean_v3, th_*], th_* from live comments_ts created <= 00:05 PT (hunter =
is_hunter flag or the launches poster; first-author history from earlier hunters and earlier live first authors only, a thinner
history than the backtest's; Nov 9 has no comments_ts -> its stack = clean).
NOTE: the stack prior is computed (th_* from live comments_ts) but NOT scored: the live comment authors cannot be matched to the
hunter (Nov 4 comments_ts carries no usernames; on Nov 10 no launches.poster appears among commenters), so th_n_pre counts the
hunter's own intro and is ~1 for every launch (top 3 vs rest 0.9 vs 0.9). The PH agent's live stack line matches by PH user id.
Blend: score = w * position(hidden) + (1 - w) * position(prior), ascending, tie -> prior; w = 0.25 / 0.5 / 0.75 at 00:30 / 01:00 / 02:00.
Truth: official final daily_rank. Day bootstrap over 6 days is shown but n is tiny.
    python live_blend.py <warehouse cache dir> <clean_live_rows3.parquet> <thread_live_model_z.json> <out dir>
"""
import glob, json, os, subprocess, sys, tempfile
import numpy as np, pandas as pd
WH, CLR, TZ, OUT = sys.argv[1:5]; os.makedirs(OUT, exist_ok=True); rng = np.random.default_rng(0)
BK = "gs://usersim-bakeoff-347838016394/usersim_sim"
rd = lambda t: pd.concat([pd.read_parquet(f) for f in glob.glob(f"{WH}/{t}/*.parquet")])
L = rd("launches").sort_values("updated_at").drop_duplicates("id", keep="last"); L["id"] = L.id.astype(str); L["daily_rank"] = pd.to_numeric(L.daily_rank, errors="coerce"); L = L[L.daily_rank.notna()]
L["poster"] = L.poster.fillna("").astype(str).str.lower()
V = rd("vote_snapshots"); V["at"] = pd.to_datetime(V["at"], utc=True); V["id"] = V.launch_id.astype(str)
F = rd("forecasts"); F = F[F.model == "launch_model"].copy(); F["id"] = F.launch_id.astype(str)
F = F.sort_values("made_on").groupby(["forecast_date", "id"]).first().reset_index()
C = pd.read_parquet(CLR); C["id"] = C.id.astype(str)
W = json.load(open(TZ))["models"]["clean_thread_z"]["coef"]
DAYS = ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-08", "2026-11-09", "2026-11-10"]
PRIORS = ("pub", "clean_v3")   # the stack line is not computable from held live data, see the note
CUTS = {"00:30": (0.5, 0.25), "01:00": (1.0, 0.5), "02:00": (2.0, 0.75)}
zf = lambda s: (s - s.mean()) / s.std() if s.std() > 0 else s * 0.0
tmp = tempfile.mkdtemp(prefix="lb_")
def live(d, f):
    p = f"{tmp}/{d}_{f}"
    if subprocess.run(["gsutil", "-q", "cp", f"{BK}/raw/ph_at_launch/{d}/live/{f}.jsonl", p], capture_output=True).returncode: return []
    return [json.loads(l) for l in open(p)]
fa_hist = {}  # first-author / hunter history: user -> [(day, within-day rank pct)]
for d, g in L[L.day < DAYS[0]].groupby("day"):
    rp = g.daily_rank.rank(pct=True, ascending=False)
    for u, r in zip(g.poster, rp):
        if u: fa_hist.setdefault(u, []).append((d, r))
rows, info = [], {}
for d in DAYS:
    g = L[L.day == d].copy(); g = g[g.id.isin(C[C.day == d].id)]
    g = g.merge(C[C.day == d][["id", "clean_v3"]], on="id")
    pub = F[F.forecast_date == d].set_index("id").predicted_rank; g["pub"] = -g.id.map(pub).fillna(999).astype(float)
    t0 = pd.Timestamp(d + " 00:00", tz="America/Los_Angeles").tz_convert("UTC"); t5 = t0 + pd.Timedelta(minutes=5)
    cm = live(d, "comments_ts"); post = {r["slug"]: str(r["launch_id"]) for r in live(d, "posts_ts") if r.get("slug")}
    K = pd.DataFrame(cm)
    th = {i: dict(th_has_first=0.0, th_hunter_first=0.0, th_n_pre=0.0, th_fa_n=0.0, th_fa_rel=0.5) for i in g.id}
    if len(K):
        K["id"] = K.launch_id.astype(str); K["ts"] = pd.to_datetime(K.created_at, utc=True, errors="coerce"); K = K[K.ts <= t5].drop_duplicates("comment_id")
        K["u"] = K.username.fillna("").astype(str).str.lower(); K = K.merge(g[["id", "poster"]], on="id")
        K["hun"] = K.is_hunter.fillna(False).astype(bool) | (K.u == K.poster)
        for i, k in K.groupby("id"):
            top = k[k.parent_id.isna()].sort_values("ts")
            fa = top.u.iat[0] if len(top) else None; hf = bool(top.hun.iat[0]) if len(top) else False
            prev = [r for (dd, r) in fa_hist.get(fa, []) if dd < d] if fa else []
            th[i] = dict(th_has_first=float(fa is not None), th_hunter_first=float(hf), th_n_pre=float(k[~k.hun].u.nunique()),
                         th_fa_n=float(np.log1p(len(prev))), th_fa_rel=(sum(prev) + 1.0) / (len(prev) + 2) if prev else 0.5)
    T = pd.DataFrame.from_dict(th, orient="index"); g = g.join(T, on="id")
    g["stack"] = W["honest"] * zf(g.clean_v3) + sum(W[c] * zf(g[c]) for c in T.columns)
    info[d] = {"launches": int(len(g)), "comments_ts": bool(len(K)), "th_n_pre_mean_top3": round(float(g[g.daily_rank <= 3].th_n_pre.mean()), 2), "th_n_pre_mean_rest": round(float(g[g.daily_rank > 3].th_n_pre.mean()), 2)}
    # hidden reads
    P = live(d, "posts_ts")
    H = pd.DataFrame([{"id": str(r["launch_id"]), "at": r["fetched_at"], "rk": r.get("daily_rank_at_fetch")} for r in P if r.get("fetch_status") == 200]) if P else pd.DataFrame(columns=["id", "at", "rk"])
    H = pd.concat([H, V[V.day == d].rename(columns={"rank_now": "rk"})[["id", "at", "rk"]]]); H["at"] = pd.to_datetime(H["at"], utc=True, format="mixed"); H["rk"] = pd.to_numeric(H.rk, errors="coerce"); H = H[H.rk.notna()]
    truth = set(g.nsmallest(3, "daily_rank").id), set(g.nsmallest(5, "daily_rank").id), set(g.nsmallest(10, "daily_rank").id)
    for cut, (h, w) in CUTS.items():
        T_ = t0 + pd.Timedelta(hours=h); hr = H[H["at"] <= T_].sort_values("at").groupby("id").rk.last()
        lastread = str(H[H["at"] <= T_]["at"].max())
        for pr in PRIORS:
            pp = g[pr].rank(ascending=False, method="first")
            hh = g.assign(_h=g.id.map(hr).fillna(999), _p=pp).sort_values(["_h", "_p"])._p; hpos = pd.Series(np.arange(1, len(g) + 1), index=hh.index)
            orders = {"prior": g.assign(s=pp).sort_values("s").id.tolist(), "hidden": g.loc[hh.index].id.tolist(),
                      "blend": g.assign(s=w * hpos + (1 - w) * pp, _p=pp).sort_values(["s", "_p"]).id.tolist()}
            for kind, o in orders.items():
                rows.append({"day": d, "cut": cut, "w": w, "prior": pr, "kind": kind, "read": lastread,
                             **{f"top{k}": len(set(o[:k]) & t) / k * 100 for k, t in zip((3, 5, 10), truth)}, "p1": float(o[0] in truth[0]) * 100})
R = pd.DataFrame(rows)
def bt(v):
    v = np.asarray(v, float); b = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(4000)]
    return [round(float(v.mean()), 1), round(float(np.percentile(b, 2.5)), 1), round(float(np.percentile(b, 97.5)), 1)]
out = {"design": __doc__.split("\n    python")[0], "days": info, "table": {}, "paired": {}}
for cut in CUTS:
    for pr in PRIORS:
        for kind in ("prior", "hidden", "blend"):
            s = R[(R.cut == cut) & (R.prior == pr) & (R.kind == kind)]
            out["table"][f"{cut} {pr} {kind}"] = {k: round(float(s[k].mean()), 1) for k in ("top3", "top5", "top10", "p1")} | {"hits_top3": int(round(s.top3.sum() * 3 / 100)), "days": int(len(s))}
    b = {pr: R[(R.cut == cut) & (R.prior == pr) & (R.kind == "blend")].set_index("day") for pr in PRIORS}
    for a, c in (("clean_v3", "pub"),):
        out["paired"][f"{cut} blend {a} - {c}"] = {k: bt(b[a][k] - b[c][k]) for k in ("top3", "top5", "top10")}
R.to_csv(os.path.join(OUT, "live_blend_rows.csv"), index=False)
json.dump(out, open(os.path.join(OUT, "live_blend.json"), "w"), indent=1)
for k, v in out["table"].items(): print(k, v)
for k, v in out["paired"].items(): print(k, v)
print(json.dumps(info))
