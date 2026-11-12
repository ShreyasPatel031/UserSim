"""Clean 00:05 model on the live days (orchestrator 06:40Z / 06:55Z Nov 12). Product Hunt names the day's #1 launch's makers
only after the day, so every input that needs a maker to be NAMED is leaky in rows read after the day: the deployed model
is trained on those leaky values and served 00:05 values (train/serve skew). Same frame as parity_live / config_parity
(features.build + llm), daily expanding refit on every finished day < d (the deployed cadence), test rows = the 00:05 rows
of each live day, LIVE_PARAMS (= ctrl.fit settings), 5 seeds, sources dropped by M.live_sources as live does.
Variants (train and serve use the same columns):
  deployed     M.cols(live sources) - the deployed configuration
  no_makerprof deployed minus every maker-profile input (ph_maker*, hist_maker*, hist_dayrank_hist_maker*, x_maker*, x_n_makers*)
  clean_v3     no_makerprof minus every other input that needs a named maker (ph_n_makers_new, ph_maker_has_headline,
               x_any_verified, ph_self_hunted); total maker count kept
  clean_v3_any clean_v3 + any_named = 1 if at least one maker is named (computed identically in train and serve: min(named, 1))
Output: results/clean_live_rows.parquet (day, id, rank, one column per variant)
usage (VM, from ph_predict): PYTHONPATH=~/w/mk nice python3 clean_live.py"""
import json, os
import numpy as np, pandas as pd
import features as F, model as M, run as RN

SEEDS = int(os.environ.get("SEEDS", "5"))
MP = ("ph_maker", "hist_maker", "hist_dayrank_hist_maker", "x_maker", "x_n_makers")
ID = {"ph_n_makers_new", "ph_maker_has_headline", "x_any_verified", "ph_self_hunted"}


def fit(tr, te, cols, seed):
    import lightgbm as lgb
    m = lgb.LGBMRegressor(n_estimators=400, learning_rate=0.03, num_leaves=15, min_child_samples=20, subsample=0.8, subsample_freq=1,
                          colsample_bytree=0.5, reg_lambda=1.0, random_state=seed, verbose=-1, n_jobs=M.N_JOBS)
    return m.fit(tr[cols], tr.logv).predict(te[cols])


def avg(tr, te, cols):
    return np.mean([fit(tr, te, cols, s) for s in range(SEEDS)], axis=0)


def any_named(df):
    def f(m):
        if not isinstance(m, (list, np.ndarray)):
            return np.nan
        return float(sum(1 for x in m if str(x) not in ("0", "", "None")) >= 1)
    return df.maker_ids.apply(f) if "maker_ids" in df else np.nan


def main():
    df = RN.load_llm(F.build(include_today=True)); df["any_named"] = any_named(df)
    days = sorted({os.path.basename(f)[:10] for f in os.listdir(f"{F.D}/today")})
    final = df[~df.is_today]; rows = []
    for d in days:
        fin = final[final.day == d]
        if fin.empty or fin.dailyRank.isna().all():
            continue
        a = df[df.is_today & (df.day == d) & ~df.known]
        tr = df[(~df.is_today) & (df.day < d) & (~df.known)]
        tr2, te = M.add_fold_feats(tr, a.copy())
        src, _ = M.live_sources(tr2, te, M.LIVE_SOURCES)
        cd = M.cols(tr2, src); cm = [c for c in cd if not c.startswith(MP)]; c3 = [c for c in cm if c not in ID]
        rk = fin.set_index(fin.id.astype(str)).dailyRank
        X = pd.DataFrame({"id": te.id.astype(str).values, "deployed": avg(tr2, te, cd), "no_makerprof": avg(tr2, te, cm),
                          "clean_v3": avg(tr2, te, c3), "clean_v3_any": avg(tr2, te, c3 + ["any_named"])})
        from sklearn.linear_model import Ridge
        rc = [c for c in c3 if tr2[c].astype(float).std() > 1e-6]   # near-constant columns explode at 00:05; clip z to +-5
        med = tr2[rc].median().fillna(0.0); Xtr = tr2[rc].astype(float).fillna(med); Xte = te[rc].astype(float).fillna(med)
        mu, sd = Xtr.mean(), Xtr.std().fillna(0.0) + 1e-9
        z = lambda X: ((X - mu) / sd).fillna(0.0).clip(-5, 5)
        X["clean_v3_ridge"] = Ridge(alpha=10.0).fit(z(Xtr), tr2.logv).predict(z(Xte))
        X["clean_v3_avg"] = X.clean_v3.rank(pct=True) + X.clean_v3_ridge.rank(pct=True)
        X["day"] = d; X["rank"] = X.id.map(rk); rows.append(X)
        print(json.dumps({"day": d, "launches": len(X), "cols": {"deployed": len(cd), "no_makerprof": len(cm), "clean_v3": len(c3)},
                          "any_named_test_mean": round(float(te.any_named.mean()), 2), "any_named_train_mean": round(float(tr2.any_named.mean()), 2)}), flush=True)
    R = pd.concat(rows, ignore_index=True); R.to_parquet(f"{RN.OUT}/" + os.environ.get("CL_OUT", "clean_live_rows.parquet"))
    print(json.dumps({"days": int(R.day.nunique()), "rows": int(len(R))}), flush=True)


if __name__ == "__main__":
    main()
