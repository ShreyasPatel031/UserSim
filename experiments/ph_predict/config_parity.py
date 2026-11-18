"""Which difference between the deployed 00:05 launch model and the honest backtest model accounts for the live gap?
(orchestrator 03:35Z Nov 12). Runs on the pipeline VM like parity_live.py: same frame (features.build + llm), every live
day with a 00:05 snapshot (data/today/<d>.json) and final ranks, predicting the 00:05 rows (view "a" = the live condition).
Params are identical in all configs: M.LIVE_PARAMS (colsample 0.5) on fit_predict's defaults == E5's ctrl.fit settings.
Configs (5 seeds each; sources with inputs much emptier at 00:05 dropped by M.live_sources, as live does):
  a  live_daily            M.LIVE_SOURCES, train on every finished day < d (the deployed configuration)
  b  honest_daily          honest_cols(LIVE_SOURCES + PAGE_SOURCES), daily expanding
  c  honest_month          honest_cols(LIVE_SOURCES + PAGE_SOURCES), month-forward (train on days before d's month)
  d  live_month            M.LIVE_SOURCES, month-forward
  e  honest_nopage_daily   honest_cols(LIVE_SOURCES), daily expanding (splits "drop follower/follow/promo" from "add page")
Output: results/config_parity_rows.parquet (day, id, rank, one column per config)
usage (VM, from ph_predict): PYTHONPATH=~/w/mk nice python3 config_parity.py"""
import json, os
import numpy as np, pandas as pd
import features as F, model as M, run as RN
from honest import honest_cols

SEEDS = int(os.environ.get("SEEDS", "5"))


def _fit(tr, te, cols, seed):
    import lightgbm as lgb
    m = lgb.LGBMRegressor(n_estimators=400, learning_rate=0.03, num_leaves=15, min_child_samples=20, subsample=0.8, subsample_freq=1,
                          colsample_bytree=0.5, reg_lambda=1.0, random_state=seed, verbose=-1, n_jobs=M.N_JOBS)
    return m.fit(tr[cols], tr.logv).predict(te[cols])


def main():
    df = RN.load_llm(F.build(include_today=True))
    days = sorted({os.path.basename(f)[:10] for f in os.listdir(f"{F.D}/today")})
    final = df[~df.is_today]; rows = []
    for d in days:
        fin = final[final.day == d]
        if fin.empty or fin.dailyRank.isna().all():
            continue
        a = df[df.is_today & (df.day == d) & ~df.known]
        rk = fin.set_index(fin.id.astype(str)).dailyRank
        out = {"id": a.id.astype(str).values}
        for nm, cut in (("daily", df.day < d), ("month", df.day < d[:7] + "-01")):
            tr = df[(~df.is_today) & cut & (~df.known)]
            tr2, te = M.add_fold_feats(tr, a.copy())
            src_l, _ = M.live_sources(tr2, te, M.LIVE_SOURCES)
            src_lp, _ = M.live_sources(tr2, te, M.LIVE_SOURCES + M.PAGE_SOURCES)
            c_live = M.cols(tr2, src_l); c_hon = honest_cols(M.cols(tr2, src_lp)); c_hnp = honest_cols(c_live)
            if nm == "daily":
                out["live_daily"] = _avg(tr2, te, c_live); out["honest_daily"] = _avg(tr2, te, c_hon); out["honest_nopage_daily"] = _avg(tr2, te, c_hnp)
                ncols = {"live": len(c_live), "honest": len(c_hon), "honest_nopage": len(c_hnp)}
            else:
                out["live_month"] = _avg(tr2, te, c_live); out["honest_month"] = _avg(tr2, te, c_hon)
        X = pd.DataFrame(out); X["day"] = d; X["rank"] = X.id.map(rk); rows.append(X)
        print(json.dumps({"day": d, "launches": int(len(X)), "ranked": int(X["rank"].notna().sum()), "n_cols": ncols}), flush=True)
    R = pd.concat(rows, ignore_index=True); R.to_parquet(f"{RN.OUT}/config_parity_rows.parquet")
    print(json.dumps({"days": int(R.day.nunique()), "rows": int(len(R))}), flush=True)


def _avg(tr, te, cols):
    return np.mean([_fit(tr, te, cols, s) for s in range(SEEDS)], axis=0)


if __name__ == "__main__":
    main()
