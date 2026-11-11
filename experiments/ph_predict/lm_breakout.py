"""Breakout candidates inside the launch model (orchestrator Nov 11 02:05Z; pre-registered with E5). Each candidate is
added to the honest live LM input set and tested paired against it on the same folds: rolling monthly Mar-Oct, 5 seeds,
ctrl.py's LightGBM, daily top 3/5/10 per list, 10,000-draw day bootstrap of the paired difference (as honest.py).

Base   honest live set: model.cols(tr, LIVE_SOURCES) with HONEST=1, minus llm_full, after model.add_fold_feats.
C1     topic momentum, from launches dated d-8 .. d-2 (daily ranks settled): per topic of L the top-10 rate, mean log
       votes, n launches, and the topic's share of recent top 10s minus its share of recent launches; mean and max over
       L's topics.
C2     honest within-day context: for each of hist_maker_rel_max, hist_hunter_rel, hist_maker_top5, promo_posts, promo_cov,
       llm_pitch, ph_n_makers: within-day percentile, gap to the day's best, and the best other launch's value.
C3     team absolute track record over the makers' launches dated <= d-2: max and mean log votes, days since the team's
       last launch, ever top 3.
Every C1/C3 row records the latest launch day it used; the run asserts it is <= d-2 (count reported).
usage: LM_CACHE=<build_cache.pkl> python lm_breakout.py [C1|C2|C3 ...]  -> results/lm_breakout.json, results/lm_breakout_preds.parquet"""
import json, multiprocessing as mp, os, pickle, sys
os.environ.setdefault("LGB_THREADS", "1")
import numpy as np, pandas as pd
import model as M, run as RN
from ctrl import MONTHS, fit

CTX_COLS = ["hist_maker_rel_max", "hist_hunter_rel", "hist_maker_top5", "promo_posts", "promo_cov", "llm_pitch", "ph_n_makers"]
CHECK = {"rows": 0, "violations": 0}


def _cut(d, k):
    return (pd.Timestamp(d) - pd.Timedelta(days=k)).strftime("%Y-%m-%d")


def c1_topic(df):
    """Rank-based parts over launches dated d-8 .. d-2 (daily ranks settled); vote-based parts over d-14 .. d-7 only
    (E5 condition 1b: no vote snapshots before Oct, counts of launches a week old are nearly frozen)."""
    S = df[df.dailyRank.notna()][["day", "topics", "dailyRank", "votes"]].copy(); S["day"] = S.day.astype(str)
    S["lv"] = np.log1p(S.votes.astype(float)); S["t10"] = (S.dailyRank <= 10).astype(float)
    E = S.explode("topics").dropna(subset=["topics"])
    out = {}
    for d in sorted(df.day.astype(str).unique()):
        lo, hi = _cut(d, 8), _cut(d, 2); vlo, vhi = _cut(d, 14), _cut(d, 7)
        W = E[(E.day >= lo) & (E.day <= hi)]; V = E[(E.day >= vlo) & (E.day <= vhi)]
        CHECK["rows"] += 1
        CHECK["violations"] += int((len(W) and W.day.max() > hi) or (len(V) and V.day.max() > vhi))
        g = W.groupby("topics").agg(t10=("t10", "mean"), n=("t10", "size"), n10=("t10", "sum"))
        tot = max(1.0, g.n.sum()); tot10 = max(1.0, g.n10.sum())
        g["share_gap"] = g.n10 / tot10 - g.n / tot
        g = g.join(V.groupby("topics").lv.mean(), how="left")
        out[d] = g
    rows = []
    for r in df[["id", "day", "topics"]].itertuples():
        g = out[str(r.day)]; ts = [t for t in (r.topics or []) if t in g.index]
        if ts:
            x = g.loc[ts]
            rows.append({"id": r.id, "tm_t10_mean": x.t10.mean(), "tm_t10_max": x.t10.max(), "tm_lv_mean": x.lv.mean(), "tm_lv_max": x.lv.max(),
                         "tm_n_mean": x.n.mean(), "tm_gap_mean": x.share_gap.mean(), "tm_gap_max": x.share_gap.max()})
        else:
            rows.append({"id": r.id})
    return pd.DataFrame(rows)


def c3_team(df):
    S = df[df.dailyRank.notna()][["day", "maker_ids", "dailyRank", "votes"]].copy()
    S["lv"] = np.log1p(S.votes.astype(float))
    E = S.explode("maker_ids"); E = E[E.maker_ids.notna() & (E.maker_ids.astype(str) != "0")].sort_values("day")
    hist = {}
    for m, g in E.groupby("maker_ids"):
        hist[m] = (g.day.to_numpy(dtype=str), g.lv.to_numpy(float), g.dailyRank.to_numpy(float))
    rows = []
    for r in df[["id", "day", "maker_ids"]].itertuples():
        hi = _cut(r.day, 2); vhi = _cut(r.day, 7); lv, rk, last = [], [], None
        for m in {str(x) for x in (r.maker_ids or []) if str(x) != "0"}:
            if m in hist:
                dd, v, k = hist[m]; ok = dd <= hi
                if ok.any():
                    lv += list(v[dd <= vhi]); rk += list(k[ok]); last = str(max(last or "", str(max(dd[ok]))))   # votes: <= d-7 only
        CHECK["rows"] += 1; CHECK["violations"] += int(last is not None and last > hi)
        rows.append({"id": r.id, "tt_lv_max": max(lv) if lv else np.nan, "tt_lv_mean": float(np.mean(lv)) if lv else np.nan,
                     "tt_days_since": (pd.Timestamp(r.day) - pd.Timestamp(last)).days if last else np.nan,
                     "tt_ever_top3": float(min(rk) <= 3) if rk else np.nan, "tt_n": float(len(lv))})
    return pd.DataFrame(rows)


def lineup_0005():
    """Launch ids in each day's 00:05 PT forecast (raw/daily/<d>/forecast_<d>.parquet; exists from Oct 28)."""
    import subprocess, tempfile
    B = "gs://usersim-bakeoff-347838016394/usersim_sim/raw/daily"
    r = subprocess.run(["gsutil", "ls", f"{B}/*/forecast_*.parquet"], capture_output=True, text=True)
    out, tmp = {}, tempfile.mkdtemp()
    for p in r.stdout.split():
        d = p.rsplit("_", 1)[1][:10]; loc = f"{tmp}/{d}.parquet"
        subprocess.run(["gsutil", "-q", "cp", p, loc], check=True)
        F = pd.read_parquet(loc); col = "id" if "id" in F else [c for c in F.columns if c.endswith("id")][0]
        out[d] = set(F[col].astype(str))
    return out


def c2_ctx(df):
    """Standing in the day's field on honest inputs. Reference field = the 00:05 PT line-up where the capture exists
    (Oct 28 on, E5 condition 2), else the final featured list (flagged: c2_final_list = 1)."""
    L = lineup_0005(); CHECK["c2_days_0005"] = len([d for d in df.day.astype(str).unique() if d in L])
    rows = []
    for d, g in df.groupby(df.day.astype(str)):
        ref = g[g.id.astype(str).isin(L[d])] if d in L and g.id.astype(str).isin(L[d]).sum() >= 3 else g
        o = pd.DataFrame({"id": g.id.values, "c2_final_list": float(ref is g)})
        for c in CTX_COLS:
            if c not in g:
                continue
            rv = ref[c].dropna().values; x = g[c].values
            o[f"hc_pct_{c}"] = [np.mean(rv <= v) if len(rv) and not np.isnan(v) else np.nan for v in x]
            best = rv.max() if len(rv) else np.nan
            o[f"hc_gap_{c}"] = x - best
            def _bo(i, a=ref[c].values.astype(float), ids=ref.id.values):
                r_ = a[ids != i]; r_ = r_[~np.isnan(r_)]
                return r_.max() if len(r_) else np.nan
            others = [_bo(i) for i in g.id.values]
            o[f"hc_best_other_{c}"] = others
        rows.append(o)
    return pd.concat(rows)


CANDS = {"C1": c1_topic, "C2": c2_ctx, "C3": c3_team}


def job(a):
    m, tr, te, seed, names = a
    tr, te = M.add_fold_feats(tr, te)
    base = [c for c in M.cols(tr, M.LIVE_SOURCES) if c != "llm_full"]
    out = {"id": te.id.values, "seed": seed, "base": fit(tr, te, base, seed)}
    pref = {"C1": "tm_", "C2": "hc_", "C3": "tt_"}
    for n in names:
        extra = [c for c in tr.columns if c.startswith(pref[n])]
        out[n] = fit(tr, te, base + extra, seed)
    return pd.DataFrame(out), len(base)


def per_day(A, col, k):
    return pd.Series({d: len(set(g.nlargest(k, col).id) & set(g[g.dailyRank <= k].id)) / k for d, g in A.groupby("day") if (g.dailyRank <= k).sum() == k})


def main(names):
    df = pickle.load(open(os.environ["LM_CACHE"], "rb")); df = df[~df.known].copy()
    for n in names:
        df = df.merge(CANDS[n](df), on="id", how="left")
    jobs = [(m, tr, te, s, names) for m, tr, te in RN.folds(df, MONTHS + ["2026-11"]) for s in range(5)]
    with mp.get_context("fork").Pool(os.cpu_count()) as pool:
        out = pool.map(job, jobs)
    P = pd.concat([o[0] for o in out]); V = ["base"] + names
    A = P.groupby("id")[V].mean().reset_index().merge(df[["id", "day", "dailyRank", "logv"]], on="id")
    A = A[A.dailyRank.notna()]; A.to_parquet(f"results/lm_breakout{os.environ.get('LB_SUFFIX', '')}_preds.parquet")
    rng = np.random.default_rng(0)
    res = {"vote_rule": "vote-based parts only from launches dated <= d-7 (C1: d-14..d-7); rank-based <= d-2",
           "c2_lineup": "00:05 PT forecast line-up where it exists (Oct 28 on), else the final featured list (c2_final_list = 1)",
           "seeds": "5, predictions averaged", "base_inputs": out[0][1], "candidates": names, "assert_le_d_minus_2": CHECK, "launches": len(A), "days": int(A.day.nunique())}
    for win, lo, hi in (("Mar-Oct", "0", "2026-10-31"), ("Jul-Oct", "2026-07", "2026-10-31"), ("Oct20-Nov8", "2026-10-20", "2026-11-08")):
        U = A[(A.day >= lo) & (A.day <= hi)]; r = {}
        for k in (3, 5, 10):
            b = per_day(U, "base", k); line = {"base": round(100 * float(b.mean()), 1), "days": int(len(b))}
            for n in names:
                c = per_day(U, n, k); d = (c - b).dropna().values
                bs = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(10000)]
                line[n] = [round(100 * float(c.mean()), 1), round(100 * float(d.mean()), 1), [round(100 * float(x), 1) for x in np.percentile(bs, [2.5, 97.5])]]
            r[f"day top{k}"] = line
        res[win] = r
    # pre-registered keep rule (E5 Nov 11): top 3 or top 5 CI-positive on Mar-Oct, no k below -2 there, and Oct 20-Nov 8
    # point estimates not negative at top 3 and top 5
    res["keep"] = {}
    for n in names:
        mo, lv = res["Mar-Oct"], res["Oct20-Nov8"]
        ci_pos = any(mo[f"day top{k}"][n][2][0] > 0 for k in (3, 5))
        no_neg = all(mo[f"day top{k}"][n][1] >= -2 for k in (3, 5, 10))
        live_ok = all(lv[f"day top{k}"][n][1] >= 0 for k in (3, 5))
        res["keep"][n] = {"ci_positive_top3_or_5": ci_pos, "no_k_below_-2": no_neg, "live_top3_top5_not_negative": live_ok, "KEEP": ci_pos and no_neg and live_ok}
    json.dump(res, open(f"results/lm_breakout{os.environ.get('LB_SUFFIX', '')}.json", "w"), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:] or ["C1", "C2", "C3"])
