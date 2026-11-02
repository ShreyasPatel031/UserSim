"""Second push on the pre-launch surge predictor: better targets and unused inputs (all dated before the launch day).
Targets:
  pool shock    log((real pool voters + 1) / (simulated pool picks + 1)), day mean removed (as shock_model.py)
  total surge   final log votes minus the pre-launch launch model (ctrl.py, out of sample), day mean removed; the
                target that matters for the leaderboard; exists for every launch since March, not only the pool's
New inputs:
  thist   team history on the total surge: for the makers (<= 30 launches each) and the hunter separately, mean,
          recency-weighted mean (60-day half-life), last and count of their earlier launches' total surge (every
          earlier launch since March, not only those with pool data)
  wvel    team history of intraday vote velocity from the Wayback homepage archive (raw/ph_homepage_archive):
          log1p(votes at capture) - log(hours since 00:00 PT) for earlier launches captured at hours 4-12, mean
  xpost   the makers' own X posts in the 7 days before launch (x_posts.jsonl.gz: up to 20 recent posts per handle):
          count, count mentioning Product Hunt or a launch, log engagement (likes + reposts + replies), and the ratio
          of that engagement to the maker's median per-post engagement in older posts
Steps (cumulative over the previous best set: launch inputs + turnout + pool-shock history + warm-up, shock_extra.py),
for each target: stage-1 within-day Spearman with a paired bootstrap over days vs the previous step.
Stage 2 (Jun-Oct, daily top 3/5/10, paired vs the launch model):
  sim + predicted pool shock     the simulation route (not simulation-only: the shock model uses launch inputs)
  launch model + predicted surge the launch model's prior plus the predicted total surge (a launch-model result)
usage: SIMLAB_DATA=data_v2 python -m simlab.shock_extra2 popscore_tie <wayback parsed.jsonl> -> reports/shock_extra2.json"""
import glob, gzip, json, os, re, sys
from collections import defaultdict
import numpy as np, pandas as pd
from scipy.stats import spearmanr
from . import store
from .shock_model import turnout, fit, canonical_days, dedupe, HERE, PH
from .shock_extra import boot, topk


def sp_day(A, col, tgt):
    return pd.Series({d: spearmanr(g[col], g[tgt]).correlation for d, g in A.groupby("day") if len(g) >= 5 and g[col].notna().sum() >= 5})


def team_lists(I, day):
    mk = {r.id: set(json.loads(r.makers)) - {""} for r in I.itertuples()}; hu = dict(zip(I.id, I.poster))
    made, hunted = defaultdict(list), defaultdict(list)
    for x in sorted(day, key=day.get):
        for m in mk[x]:
            made[m].append(x)
        if hu[x] and hu[x] not in mk[x]:
            hunted[hu[x]].append(x)
    def prior(x, d):
        lm = sorted({l for m in mk.get(x, ()) if len(made[m]) <= 30 for l in made[m] if day[l] < d}, key=day.get)
        lh = [l for l in hunted.get(hu.get(x), []) if day[l] < d] if hu.get(x) and hu.get(x) not in mk.get(x, ()) else []
        return lm, lh
    return prior, mk, hu


def hist_feats(A, prior, val, day, pre):
    od = lambda d: pd.Timestamp(d).toordinal(); out = []
    for x, d in zip(A.id, A.day):
        r = {}
        for tag, L in zip(("mk", "hu"), prior(x, d)):
            L = [l for l in L if l in val and not np.isnan(val[l])]
            if L:
                s = np.array([val[l] for l in L]); w = 0.5 ** (np.array([od(d) - od(day[l]) for l in L]) / 60)
                r.update({f"{pre}_{tag}_mean": s.mean(), f"{pre}_{tag}_wmean": float((s * w).sum() / w.sum()),
                          f"{pre}_{tag}_last": val[max(L, key=lambda l: day[l])], f"{pre}_{tag}_n": float(len(L))})
        out.append(r)
    return pd.DataFrame(out, index=A.index)


def main(src, wb_path):
    P, I, E = store.load(); canon = canonical_days()
    I = I.assign(id=I.id.astype(str)); I = I[I.day.values == I.id.map(canon).fillna(I.day).values].drop_duplicates("id")
    day = dict(zip(I.id, I.day))
    Ev = E.assign(item=E.item.astype(str)); Ev = Ev[Ev.item.map(day) == Ev.date]; R = Ev.groupby("item").person.nunique()
    S = dedupe(pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(os.path.join(HERE, "cache", src, "day_*.parquet")))]).assign(id=lambda x: x.id.astype(str)), canon)
    S["lS"] = np.log1p(S.psn_ev); S["shock"] = np.log((S.id.map(R).fillna(0) + 1) / (S.psn_ev + 1)); S["shock"] -= S.groupby("day").shock.transform("mean")
    cwd = os.getcwd(); os.chdir(PH); sys.path.insert(0, PH)
    try:
        from buildcache import build_cached
        import model as M
        B = dedupe(build_cached().assign(id=lambda x: x.id.astype(str)), canon)
        C = dedupe(pd.read_parquet("results/ctrl_preds.parquet").assign(id=lambda x: x.id.astype(str)), canon)
        tw = {}
        for f in glob.glob("data/days/*.json"):
            for p in json.load(open(f)):
                tw[str(p["id"])] = [(m.get("twitterUsername") or "").lower() for m in p.get("makers") or [] if isinstance(m, dict) and m.get("twitterUsername")]
        XP = {}
        for l in gzip.open("data/x_posts.jsonl.gz", "rt"):
            r = json.loads(l)
            if r.get("posts"):
                XP[r["handle"].lower()] = [(p.get("created_at") or "", p.get("text") or "", sum(float(p.get(k) or 0) for k in ("likes", "reposts", "replies"))) for p in r["posts"]]
    finally:
        os.chdir(cwd)
    inputs = M.cols(B, M.LIVE_SOURCES + M.PAGE_SOURCES); T0 = turnout(I, E)
    # total surge for every launch in ctrl (Mar-Oct)
    C["surge"] = C.logv - C["all"]; C["surge"] -= C.groupby("day").surge.transform("mean")
    surge = dict(zip(C.id, C.surge))
    A = C[["id", "day", "dailyRank", "logv", "all", "surge"]].merge(S[["id", "lS", "shock"]], on="id", how="left").merge(B[["id"] + inputs], on="id", how="left").merge(T0, on="id", how="left")
    A = A.sort_values("day").reset_index(drop=True)
    prior, mk, hu = team_lists(I, day)
    sh = dict(zip(A.id, A.shock))
    A = pd.concat([A, hist_feats(A, prior, sh, day, "h"), hist_feats(A, prior, surge, day, "th")], axis=1)
    # Wayback intraday velocity of earlier launches
    W = pd.read_json(wb_path, lines=True, dtype={"post_id": str, "capture_ts": str}); W = W[(W.capture_kind == "home") & (W.day.astype(str).str.len() == 10)]
    ts = pd.to_datetime(W.capture_ts, format="%Y%m%d%H%M%S", utc=True); st = pd.to_datetime(W.day).dt.tz_localize("America/Los_Angeles").dt.tz_convert("UTC")
    W["h"] = (ts - st).dt.total_seconds() / 3600; W = W[(W.h >= 4) & (W.h < 12) & (W.votes > 0)]
    W["vel"] = np.log1p(W.votes) - np.log(W.h); vel = W.groupby("post_id").vel.mean()
    vel = (vel - vel.groupby(vel.index.map(lambda x: day.get(x, ""))).transform("mean")).to_dict()
    A = pd.concat([A, hist_feats(A, prior, vel, day, "wv")], axis=1)
    # makers' X posts in the 7 days before launch
    rx = re.compile(r"product\s*hunt|producthunt|launch", re.I); X = []
    for x, d in zip(A.id, A.day):
        lo = (pd.Timestamp(d) - pd.Timedelta(days=7)).strftime("%Y-%m-%d"); posts, old = [], []
        for h in tw.get(x, []):
            for (c, t, e) in XP.get(h, []):
                (posts if lo <= c[:10] < d else old if c[:10] < lo else []).append((t, e))
        r = {}
        if any(h in XP for h in tw.get(x, [])):
            eng = sum(e for _, e in posts); med = np.median([e for _, e in old]) if old else np.nan
            r = {"xp_n7": float(len(posts)), "xp_launch7": float(sum(bool(rx.search(t)) for t, _ in posts)), "xp_eng7": np.log1p(eng),
                 "xp_ratio": (eng / max(len(posts), 1)) / (med + 1) if posts and not np.isnan(med) else np.nan}
        X.append(r)
    A = pd.concat([A, pd.DataFrame(X, index=A.index)], axis=1)
    res = {"source": src, "launches": int(len(A)),
           "coverage": {"thist_makers": round(float(A.get("th_mk_n", pd.Series(dtype=float)).notna().mean()), 3), "thist_hunter": round(float(A.get("th_hu_n", pd.Series(dtype=float)).notna().mean()), 3),
                        "pool_hist_makers": round(float(A.get("h_mk_n", pd.Series(dtype=float)).notna().mean()), 3),
                        "wvel_any": round(float(A.filter(like="wv_").notna().any(axis=1).mean()), 3), "xpost_any": round(float(A.filter(like="xp_").notna().any(axis=1).mean()), 3)}}
    m2 = A.th_mk_n >= 2 if "th_mk_n" in A else pd.Series(False, index=A.index)
    res["persistence_total_surge"] = {"makers_2plus": {"launches": int(m2.sum()), "spearman": round(float(spearmanr(A.loc[m2, "th_mk_mean"], A.loc[m2, "surge"]).correlation), 3)}}
    h2 = A.th_hu_n >= 2 if "th_hu_n" in A else pd.Series(False, index=A.index)
    res["persistence_total_surge"]["hunter_2plus"] = {"launches": int(h2.sum()), "spearman": round(float(spearmanr(A.loc[h2, "th_hu_mean"], A.loc[h2, "surge"]).correlation), 3)}
    warm = []   # shock_extra's warm-up block is cheap to recompute but borderline; keep the base as launch inputs + turnout + pool history
    base = inputs + [c for c in T0 if c != "id"] + [c for c in A if c.startswith("h_")]
    blocks = [("+ total-surge history", [c for c in A if c.startswith("th_")]), ("+ Wayback velocity history", [c for c in A if c.startswith("wv_")]),
              ("+ makers' X posts (7 days)", [c for c in A if c.startswith("xp_")])]
    A["mon"] = A.day.str[:7]; months = sorted(A.mon.unique()); rng = np.random.default_rng(0)
    res["targets"] = {}
    hats = {}
    for tgt in ("shock", "surge"):
        cols, prev, lines = list(base), None, {}
        steps = [("base", [])] + blocks
        for name, add in steps:
            cols = cols + add; hat = np.full(len(A), np.nan)
            ok = A[tgt].notna()
            for m in months[1:]:
                te = (A.mon == m).values
                tr = A[(A.mon < m) & ok]
                if len(tr) > 200:
                    hat[te] = fit(tr, A[te], cols, tgt)
            A[f"hat_{tgt}_{name}"] = hat
            spd = sp_day(A[ok & ~np.isnan(hat)], f"hat_{tgt}_{name}", tgt)
            line = {"inputs": len(cols), "spearman_within_day": round(float(spd.mean()), 3)}
            if prev is not None:
                line["vs_previous_step"] = boot(prev, spd, rng)
            lines[name] = line; prev = spd; hats[(tgt, name)] = f"hat_{tgt}_{name}"
        res["targets"][tgt] = lines
    # stage 2, Jun-Oct
    last = blocks[-1][0]
    A["lS_dayr"] = A.groupby("day").lS.rank(pct=True)
    rows = []
    for m in months:
        if m < "2026-06":
            continue
        te = A[A.mon == m].copy()
        for name in ("base", last):
            hs = hats[("shock", name)]; tr = A[(A.mon < m) & A[hs].notna() & A.lS.notna()]
            te[f"sim+shock {name}"] = fit(tr, te.assign(), ["lS", "lS_dayr", hs], "logv") if len(tr) > 200 else np.nan
            te[f"launch+surge {name}"] = te["all"] + te[hats[("surge", name)]]
        rows.append(te)
    T = pd.concat(rows); T = T[T.lS.notna()]
    res["stage2_jun_oct"] = {"launch model": [round(100 * float(topk(T, "all", k).mean()), 1) for k in (3, 5, 10)]}
    for c in [c for c in T if c.startswith(("sim+shock", "launch+surge"))]:
        res["stage2_jun_oct"][c] = {"top3_5_10": [round(100 * float(topk(T, c, k).mean()), 1) for k in (3, 5, 10)],
                                    **{f"top{k}_vs_launch_model": boot(topk(T, "all", k), topk(T, c, k), rng) for k in (3, 5, 10)}}
    json.dump(res, open(os.path.join(HERE, "reports", "shock_extra2.json"), "w"), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
