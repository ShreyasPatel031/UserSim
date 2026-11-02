"""Push the pre-launch shock predictor (shock_model.py stage 1) with data already in hand. All inputs dated before the
launch day. Blocks, added cumulatively to the stage-1 inputs (launch-model inputs + turnout):
  hist   team surge history: for the makers (<= 30 launches each) and the hunter separately, their earlier launches'
         within-day shock (mean, recency-weighted mean with a 60-day half-life, last, count), earlier pool turnout
         (log real pool voters), and earlier hour-2 non-team comments (log). First-timers: NaN, plus the topic mean below.
  comp   category appetite: within-day shocks of earlier launches of the launch's competitors (PH Similar Products,
         safe lists) and of its 10 nearest earlier launches by meaning (mean, max, most recent); topic mean shock over
         the 30 days before.
  ctx    launch-day context known before the day: line-up size, weekday, launches by the same hunter that day, and how
         many launches that day come from teams with a positive mean past shock.
  warm   warm-up in the 14 days before: the makers' and hunter's own Product Hunt actions (comments + upvotes), and the
         lead time between the post's creation and its featuring.
Persistence first: correlation of a team's mean past shock with its current shock, for teams with 2+ earlier launches.
Gate: stage-1 within-day Spearman, paired bootstrap over days vs the previous step; stage 2 daily top 3/5/10 (Jun-Oct,
simulation + predicted shock, within day) vs the launch model, reported.
usage: SIMLAB_DATA=data_v2 python -m simlab.shock_extra popscore_tie -> reports/shock_extra.json"""
import glob, json, os, sys
from collections import defaultdict
import numpy as np, pandas as pd
from scipy.stats import spearmanr
from . import store
from .shock_model import turnout, fit, canonical_days, dedupe, HERE, PH


def per_day_spearman(A, col):
    return pd.Series({d: spearmanr(g[col], g.shock).correlation for d, g in A.groupby("day") if len(g) >= 5 and g[col].notna().sum() >= 5})


def boot(a, b, rng):
    k = a.index.intersection(b.index); d = (b[k] - a[k]).dropna().values
    bs = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(5000)]
    return round(float(d.mean()), 3), [round(float(x), 3) for x in np.percentile(bs, [2.5, 97.5])]


def topk(T, col, k):
    return pd.Series({d: len(set(g.nlargest(k, col).id) & set(g[g.dailyRank <= k].id)) / k for d, g in T.groupby("day") if (g.dailyRank <= k).sum() == k})


def main(src):
    P, I, E = store.load(); canon = canonical_days()
    I = I.assign(id=I.id.astype(str)); I = I[I.day.values == I.id.map(canon).fillna(I.day).values].drop_duplicates("id")
    day = dict(zip(I.id, I.day))
    Ev = E.assign(item=E.item.astype(str)); Ev = Ev[Ev.item.map(day) == Ev.date]
    R = Ev.groupby("item").person.nunique()
    S = pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(os.path.join(HERE, "cache", src, "day_*.parquet")))]); S["id"] = S.id.astype(str)
    S = dedupe(S, canon)
    S["R"] = S.id.map(R).fillna(0); S["lS"] = np.log1p(S.psn_ev)
    S["shock"] = np.log((S.R + 1) / (S.psn_ev + 1)); S["shock"] -= S.groupby("day").shock.transform("mean")
    cwd = os.getcwd(); os.chdir(PH); sys.path.insert(0, PH)
    try:
        from buildcache import build_cached
        import model as M, launchday as LD
        B = dedupe(build_cached().assign(id=lambda x: x.id.astype(str)), canon)
        C = dedupe(pd.read_parquet("results/ctrl_preds.parquet").assign(id=lambda x: x.id.astype(str)), canon)
        CM = LD.comments()
        Z = np.load("data/emb.npz"); zid = [str(x) for x in Z["launch_ids"]]; V = Z["launch"] / np.linalg.norm(Z["launch"], axis=1, keepdims=True)
        PHL = json.load(open("data/ph_comp_lists.json"))
        created = {}
        for f in glob.glob("data/days/*.json"):
            for p in json.load(open(f)):
                if p.get("createdAt") and p.get("featuredAt"):
                    created[str(p["id"])] = (pd.Timestamp(p["featuredAt"]) - pd.Timestamp(p["createdAt"])).total_seconds() / 86400
    finally:
        os.chdir(cwd)
    inputs = M.cols(B, M.LIVE_SOURCES + M.PAGE_SOURCES); T0 = turnout(I, E)
    A = S[["id", "day", "lS", "shock", "R"]].merge(C[["id", "dailyRank", "logv", "all"]], on="id").merge(B[["id"] + inputs], on="id", how="left").merge(T0, on="id", how="left")
    c2 = CM[(~CM.team) & (CM.h < 2) & (CM.h >= -24)].groupby("id").size()
    A["c2"] = np.log1p(A.id.map(c2).fillna(0)); A["lR"] = np.log1p(A.R)
    A = A.sort_values("day").reset_index(drop=True)
    sh = dict(zip(A.id, A.shock)); lR = dict(zip(A.id, A.lR)); lc2 = dict(zip(A.id, A.c2)); dd = dict(zip(A.id, A.day))
    mk = {r.id: set(json.loads(r.makers)) - {""} for r in I.itertuples()}; hu = dict(zip(I.id, I.poster))
    made, hunted = defaultdict(list), defaultdict(list)
    for x in sorted(day, key=day.get):
        for m in mk[x]:
            made[m].append(x)
        if hu[x] and hu[x] not in mk[x]:
            hunted[hu[x]].append(x)
    od = lambda d: pd.Timestamp(d).toordinal()
    # ---- hist: team surge history
    H = []
    for x, d in zip(A.id, A.day):
        r = {}
        for tag, L in (("mk", sorted({l for m in mk.get(x, ()) if len(made[m]) <= 30 for l in made[m] if day[l] < d and l in sh})),
                       ("hu", [l for l in hunted.get(hu.get(x), []) if day[l] < d and l in sh] if hu.get(x) and hu.get(x) not in mk.get(x, ()) else [])):
            if L:
                s = np.array([sh[l] for l in L]); age = np.array([od(d) - od(day[l]) for l in L]); w = 0.5 ** (age / 60)
                last = max(L, key=lambda l: day[l])
                r.update({f"h_{tag}_mean": s.mean(), f"h_{tag}_wmean": float((s * w).sum() / w.sum()), f"h_{tag}_last": sh[last], f"h_{tag}_n": len(L),
                          f"h_{tag}_lR": float(np.mean([lR[l] for l in L])), f"h_{tag}_c2": float(np.mean([lc2[l] for l in L]))})
        H.append(r)
    A = pd.concat([A, pd.DataFrame(H)], axis=1)
    hist = [c for c in A if c.startswith("h_")]
    res = {"source": src, "launches": int(len(A))}
    pers = {}
    for tag in ("mk", "hu"):
        m = A[f"h_{tag}_n"] >= 2 if f"h_{tag}_n" in A else pd.Series(False, index=A.index)
        if m.sum() > 30:
            pers[tag] = {"launches": int(m.sum()), "spearman_mean_past_vs_current": round(float(spearmanr(A.loc[m, f"h_{tag}_mean"], A.loc[m, "shock"]).correlation), 3),
                         "spearman_wmean": round(float(spearmanr(A.loc[m, f"h_{tag}_wmean"], A.loc[m, "shock"]).correlation), 3)}
    res["persistence"] = pers
    # ---- comp: category appetite
    zix = {x: k for k, x in enumerate(zid)}; zday = np.array([day.get(x, "9999") for x in zid])
    topics = {r.id: json.loads(r.topics) for r in I.itertuples()}
    tday = defaultdict(list)
    for x, d, s0 in zip(A.id, A.day, A.shock):
        for t in topics.get(x, []):
            tday[t].append((d, s0))
    Cc = []
    for x, d in zip(A.id, A.day):
        r = {}
        ids = [i for i in (PHL.get(x, {}).get("ids", []) if PHL.get(x, {}).get("safe") else []) if i in sh and day.get(i, "9") < d]
        if ids:
            r.update({"cp_ph_mean": float(np.mean([sh[i] for i in ids])), "cp_ph_max": float(np.max([sh[i] for i in ids])), "cp_ph_last": sh[max(ids, key=lambda i: day[i])]})
        if x in zix:
            s0 = V @ V[zix[x]]; s0[zday >= d] = -9
            nb = [zid[k] for k in np.argsort(-s0)[:10] if s0[k] > -9 and zid[k] in sh]
            if nb:
                r.update({"cp_nn_mean": float(np.mean([sh[i] for i in nb])), "cp_nn_max": float(np.max([sh[i] for i in nb])), "cp_nn_last": sh[max(nb, key=lambda i: day[i])]})
        cut = (pd.Timestamp(d) - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
        tv = [s1 for t in topics.get(x, []) for d1, s1 in tday[t] if cut <= d1 < d]
        if tv:
            r["cp_topic30"] = float(np.mean(tv))
        Cc.append(r)
    A = pd.concat([A, pd.DataFrame(Cc)], axis=1)
    comp = [c for c in A if c.startswith("cp_")]
    # ---- ctx: launch-day context known before the day
    A["x_lineup"] = A.groupby("day").id.transform("size"); A["x_dow"] = pd.to_datetime(A.day).dt.dayofweek
    A["x_hunter_same_day"] = A.groupby(["day", A.id.map(hu)]).id.transform("size")
    pos = (A[["h_mk_mean", "h_hu_mean"]].max(axis=1) > 0).astype(float) if "h_hu_mean" in A else (A["h_mk_mean"] > 0).astype(float)
    A["x_strong_teams_day"] = pos.groupby(A.day).transform("sum") - pos
    ctx = ["x_lineup", "x_dow", "x_hunter_same_day", "x_strong_teams_day"]
    # ---- warm: the team's own PH activity in the 14 days before, and post lead time
    acts = E.groupby("person").date.apply(lambda s: np.sort(s.values)).to_dict()
    W = []
    for x, d in zip(A.id, A.day):
        cut = (pd.Timestamp(d) - pd.Timedelta(days=14)).strftime("%Y-%m-%d")
        n = lambda u: int(np.searchsorted(acts[u], d) - np.searchsorted(acts[u], cut)) if u in acts else 0
        W.append({"w_makers_act14": np.log1p(sum(n(m) for m in mk.get(x, ()))), "w_hunter_act14": np.log1p(n(hu.get(x))) if hu.get(x) else 0.0,
                  "w_lead_days": created.get(x, np.nan)})
    A = pd.concat([A, pd.DataFrame(W)], axis=1)
    warm = ["w_makers_act14", "w_hunter_act14", "w_lead_days"]
    res["lead_days_share_positive"] = round(float((A.w_lead_days > 0.01).mean()), 3)
    # ---- cumulative steps
    base = inputs + [c for c in T0 if c != "id"]
    steps = [("base (launch inputs + turnout)", base), ("+ hist", base + hist), ("+ comp", base + hist + comp),
             ("+ ctx", base + hist + comp + ctx), ("+ warm", base + hist + comp + ctx + warm), ("hist only + base, no comp/ctx/warm", base + hist)]
    A["mon"] = A.day.str[:7]; months = sorted(A.mon.unique()); rng = np.random.default_rng(0)
    out, prev = {}, None
    for name, cols in steps[:5]:
        hat = np.full(len(A), np.nan)
        for m in months[1:]:
            te = (A.mon == m).values
            hat[te] = fit(A[A.mon < m], A[te], cols, "shock")
        A["hat_" + name] = hat
        sp = per_day_spearman(A[A[f"hat_{name}"].notna()], f"hat_{name}")
        o = {"inputs": len(cols), "spearman_within_day": round(float(sp.mean()), 3)}
        if prev is not None:
            o["vs_previous_step"] = boot(prev, sp, rng)
        o["vs_base"] = boot(out[steps[0][0]]["_sp"], sp, rng) if out else None
        o["_sp"] = sp; out[name] = o; prev = sp
    # stage 2 per step: simulation + predicted shock (within day), Jun-Oct, daily top 3/5/10 vs launch model
    for name in list(out):
        A["d_" + name] = A.groupby("day")["hat_" + name].rank(pct=True); A["p_" + name] = A.lS + A["hat_" + name]
    A["lS_dayr"] = A.groupby("day").lS.rank(pct=True)
    rows = []
    for m in months[2:]:
        tr, te = A[(A.mon < m) & A[f"hat_{steps[0][0]}"].notna()], A[A.mon == m].copy()
        for name in out:
            te["s2_" + name] = fit(tr, te, ["lS", "lS_dayr", "hat_" + name, "d_" + name, "p_" + name], "logv")
        rows.append(te)
    T = pd.concat(rows)
    for name in out:
        o = out[name]; o["daily_top3_5_10"] = [round(100 * float(topk(T, "s2_" + name, k).mean()), 1) for k in (3, 5, 10)]
        a3 = topk(T, "all", 3); b3 = topk(T, "s2_" + name, 3); o["top3_vs_launch_model"] = boot(a3, b3, rng)
        if name != steps[0][0]:
            o["top3_vs_base_step"] = boot(topk(T, "s2_" + steps[0][0], 3), b3, rng)
    res["launch_model_daily_top3_5_10"] = [round(100 * float(topk(T, "all", k).mean()), 1) for k in (3, 5, 10)]
    res["steps"] = {k: {kk: v for kk, v in o.items() if kk != "_sp"} for k, o in out.items()}
    res["block_sizes"] = {"hist": len(hist), "comp": len(comp), "ctx": len(ctx), "warm": len(warm)}
    json.dump(res, open(os.path.join(HERE, "reports", "shock_extra.json"), "w"), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main(sys.argv[1])
