"""Is the 00:05 launch model trained on a noisy target? (orchestrator 04:25Z Nov 12). The official daily rank is the order
of votes at midnight PT; the model regresses log1p of warehouse `votes`, read days or weeks later. Runs on the pipeline VM
(feature cache), read-only. Honest setup: build_cached, honest_cols(LIVE + PAGE), ctrl.fit settings, 5 seeds, month-forward
Mar - Nov (same folds as training_window.py). Only the training target changes; every variant is scored against the
official daily_rank.
Targets
  cur        log1p(warehouse votes) - the current target (= logv)
  mid        log1p(votes at midnight PT) where held (data/midnight_votes.parquet: Wayback launchDayScore from a capture
             after the day, Jul - Oct; live / hourly 00:01 PT reads, Oct 31 on), else logv; has_mid is reported, not an input
  rankcons   per day, the day's logv values sorted descending and re-assigned by official daily_rank (keeps the day's vote
             distribution, target order == truth on every day); launches without a rank keep logv
  neglogrank -log(daily_rank) (unranked: -log(day size + 1))
  pct        within-day normalised: 1 - (rank - 1) / (n - 1)
Also: how often the current target's within-day order disagrees with daily_rank (top-5 set, top-3 set, top-1).
usage (VM, from ph_predict): PYTHONPATH=~/w/mk PROCS=3 python3 target_exp.py -> results/target_exp_preds.parquet + _disagree.json"""
import json, multiprocessing as mp, os, time
os.environ.setdefault("LGB_THREADS", "1")
import numpy as np, pandas as pd, lightgbm as lgb
import model as M
from buildcache import build_cached
from ctrl import MONTHS as _M
from honest import honest_cols

MONTHS = list(_M) + ["2026-11"]
DF = {}
T = ["cur", "mid", "rankcons", "neglogrank", "pct"]
P0 = dict(n_estimators=400, learning_rate=0.03, num_leaves=15, min_child_samples=20, subsample=0.8, subsample_freq=1,
          colsample_bytree=0.5, reg_lambda=1.0, verbose=-1, n_jobs=1)


def targets(df):
    df = df.copy()
    mv = pd.read_parquet("data/midnight_votes.parquet"); mv["id"] = mv.id.astype(str)
    m = df.id.map(dict(zip(mv.id, mv.mid_votes)))
    df["has_mid"] = m.notna().astype(int)
    df["t_cur"] = df.logv
    df["t_mid"] = np.where(m.notna(), np.log1p(m.astype(float)), df.logv)
    df["t_rankcons"] = df.logv
    for d, g in df[df.dailyRank.notna()].groupby("day"):
        vals = np.sort(g.logv.values)[::-1]
        order = g.sort_values("dailyRank").index
        df.loc[order, "t_rankcons"] = vals
    n = df.groupby("day").id.transform("size")
    r = df.dailyRank.fillna(n + 1)
    df["t_neglogrank"] = -np.log(r)
    df["t_pct"] = 1 - (r - 1) / (n.clip(lower=2) - 1)
    return df


def job(a):
    m, seed = a
    df = DF["df"]
    tr, te = M.add_fold_feats(df[df.mon < m], df[df.mon == m])
    cols = honest_cols(M.cols(tr, M.LIVE_SOURCES + M.PAGE_SOURCES))
    out = {"id": te.id.values, "seed": seed}
    for t in T:
        out[t] = lgb.LGBMRegressor(random_state=seed, **P0).fit(tr[cols], tr[f"t_{t}"]).predict(te[cols])
    return pd.DataFrame(out)


def disagree(df):
    res = {"days": 0, "top1": 0, "top3_set": 0, "top5_set": 0, "by_month": {}}
    for d, g in df[df.dailyRank.notna()].groupby("day"):
        if (g.dailyRank <= 5).sum() < 5:
            continue
        v = g.sort_values("logv", ascending=False).id.tolist(); r = g.sort_values("dailyRank").id.tolist()
        res["days"] += 1
        res["top1"] += int(v[0] != r[0]); res["top3_set"] += int(set(v[:3]) != set(r[:3])); res["top5_set"] += int(set(v[:5]) != set(r[:5]))
        bm = res["by_month"].setdefault(d[:7], [0, 0]); bm[0] += 1; bm[1] += int(set(v[:5]) != set(r[:5]))
    return res


def main():
    t = time.time()
    df = build_cached(); df = df[~df.known].copy(); df["id"] = df.id.astype(str)
    if "mon" not in df:
        df["mon"] = df.day.str[:7]
    df = targets(df); DF["df"] = df
    dis = disagree(df); dis["has_mid_launches"] = int(df.has_mid.sum())
    json.dump(dis, open("results/target_exp_disagree.json", "w"), indent=1); print(json.dumps(dis), flush=True)
    jobs = [(m, s) for m in MONTHS for s in range(5) if len(df[df.mon < m]) > 200 and len(df[df.mon == m])]
    with mp.get_context("fork").Pool(int(os.environ.get("PROCS", "3"))) as pool:
        P = pd.concat(pool.map(job, jobs))
    A = P.groupby("id")[T].mean().reset_index().merge(df[["id", "day", "mon", "dailyRank", "logv", "has_mid"]], on="id")
    A["ref"] = A["cur"]
    A.to_parquet("results/target_exp_preds.parquet")
    print(json.dumps({"launches": int(len(A)), "days": int(A.day.nunique()), "seconds": round(time.time() - t)}), flush=True)


if __name__ == "__main__":
    main()
