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
    S = df[df.dailyRank.notna()][["day", "topics", "dailyRank", "votes"]].copy(); S["day"] = S.day.astype(str)
    S["lv"] = np.log1p(S.votes.astype(float)); S["t10"] = (S.dailyRank <= 10).astype(float)
    E = S.explode("topics").dropna(subset=["topics"])
    out = {}
    for d in sorted(df.day.unique()):
        lo, hi = _cut(d, 8), _cut(d, 2)
        W = E[(E.day >= lo) & (E.day <= hi)]
        if len(W):
            CHECK["rows"] += 1; CHECK["violations"] += int(W.day.max() > hi)
        g = W.groupby("topics").agg(t10=("t10", "mean"), lv=("lv", "mean"), n=("t10", "size"), n10=("t10", "sum"))
        tot = max(1.0, g.n.sum()); tot10 = max(1.0, g.n10.sum())
        g["share_gap"] = g.n10 / tot10 - g.n / tot
        out[d] = g
    rows = []
    for r in df[["id", "day", "topics"]].itertuples():
        g = out[r.day]; ts = [t for t in (r.topics or []) if t in g.index]
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
        hi = _cut(r.day, 2); lv, rk, last = [], [], None
        for m in {str(x) for x in (r.maker_ids or []) if str(x) != "0"}:
            if m in hist:
                dd, v, k = hist[m]; ok = dd <= hi
                if ok.any():
                    lv += list(v[ok]); rk += list(k[ok]); last = str(max(last or "", str(max(dd[ok]))))
        CHECK["rows"] += 1; CHECK["violations"] += int(last is not None and last > hi)
        rows.append({"id": r.id, "tt_lv_max": max(lv) if lv else np.nan, "tt_lv_mean": float(np.mean(lv)) if lv else np.nan,
                     "tt_days_since": (pd.Timestamp(r.day) - pd.Timestamp(last)).days if last else np.nan,
                     "tt_ever_top3": float(min(rk) <= 3) if rk else np.nan, "tt_n": float(len(lv))})
    return pd.DataFrame(rows)


def c2_ctx(df):
    out = df[["id", "day"]].copy()
    for c in CTX_COLS:
        if c not in df:
            continue
        g = df.groupby("day")[c]
        out[f"hc_pct_{c}"] = g.rank(pct=True).values
        out[f"hc_gap_{c}"] = (df[c] - g.transform("max")).values
        # the best OTHER launch's value that day
        top2 = g.transform(lambda s: s.nlargest(2).iloc[-1] if s.notna().sum() > 1 else np.nan)
        out[f"hc_best_other_{c}"] = np.where(df[c] >= g.transform("max"), top2, g.transform("max"))
    return out.drop(columns=["day"])


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
    jobs = [(m, tr, te, s, names) for m, tr, te in RN.folds(df, MONTHS) for s in range(5)]
    with mp.get_context("fork").Pool(os.cpu_count()) as pool:
        out = pool.map(job, jobs)
    P = pd.concat([o[0] for o in out]); V = ["base"] + names
    A = P.groupby("id")[V].mean().reset_index().merge(df[["id", "day", "dailyRank", "logv"]], on="id")
    A = A[A.dailyRank.notna()]; A.to_parquet("results/lm_breakout_preds.parquet")
    rng = np.random.default_rng(0)
    res = {"base_inputs": out[0][1], "candidates": names, "assert_le_d_minus_2": CHECK, "launches": len(A), "days": int(A.day.nunique())}
    for win, lo in (("Mar-Oct", "0"), ("May-Oct", "2026-05"), ("Jul-Oct", "2026-07")):
        U = A[A.day >= lo]; r = {}
        for k in (3, 5, 10):
            b = per_day(U, "base", k); line = {"base": round(100 * float(b.mean()), 1), "days": int(len(b))}
            for n in names:
                c = per_day(U, n, k); d = (c - b).dropna().values
                bs = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(10000)]
                line[n] = [round(100 * float(c.mean()), 1), round(100 * float(d.mean()), 1), [round(100 * float(x), 1) for x in np.percentile(bs, [2.5, 97.5])]]
            r[f"day top{k}"] = line
        res[win] = r
    json.dump(res, open("results/lm_breakout.json", "w"), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:] or ["C1", "C2", "C3"])
