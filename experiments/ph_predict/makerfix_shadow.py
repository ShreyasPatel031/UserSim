"""Shadow fix for placeholder maker ids at 00:05 (parity_live.md, Nov 11). Runs by hand on the pipeline VM after 01:00 PT
(never 00:05-01:00 PT), read-only for everything deployed. Same training as the live forecast (days < d, model.LIVE_SOURCES,
live_sources() on the 00:05 rows, LIVE_PARAMS, 5 seeds); test rows = data/today/<d>.json (the 00:05 snapshot) only.
  unfixed   the 00:05 rows as they are (a replay of live with today's code)
  makerfix  for launches whose 00:05 maker ids include a placeholder ("0", empty, None), every maker-derived input
            (hist_maker*, hist_dayrank_hist_maker*, ph_maker*, ph_n_makers*, ph_dayrank_ph_n_makers, x_n_makers*) is set
            to missing (LightGBM's missing branch) instead of the value joined on the placeholder id
  clean     (orchestrator 06:40Z / 07:10Z Nov 12; replaces the nollm line) the deployed model trained and served WITHOUT
            every input that needs a named maker (our API v2 reads return makers redacted at 00:05 and name the day's #1 makers in later reads, so these inputs are
            leaky in training rows): maker-profile inputs (ph_maker*, hist_maker*, hist_dayrank_hist_maker*, x_maker*,
            x_n_makers*) and ph_n_makers_new, ph_maker_has_headline, x_any_verified, ph_self_hunted; total maker count kept.
            Live days (clean_live.md): 61.9 / 67.1 / 76.4 vs deployed 57.1 / 64.3 / 76.4 on 14 days
usage (VM): /opt/exp/bin/python3 makerfix_shadow.py <day> -> results/shadow_makerfix/<day>.json (prints its path)"""
import json, os, sys
import numpy as np, pandas as pd
import features as F, model as M, run as RN

MP = ("ph_maker", "hist_maker", "hist_dayrank_hist_maker", "x_maker", "x_n_makers")
ID = {"ph_n_makers_new", "ph_maker_has_headline", "x_any_verified", "ph_self_hunted"}
MAKER = lambda c: c.startswith(("hist_maker", "hist_dayrank_hist_maker", "ph_maker", "ph_n_makers", "ph_dayrank_ph_n_makers", "x_n_makers"))


def main(d):
    now = pd.Timestamp.now(tz="America/Los_Angeles")
    # TW_EARLY=1 (bundle 12, timed writes on the VM): allowed from 00:20 PT once the pipeline's forecast parquet exists (tw.sh checks it)
    if now.strftime("%Y-%m-%d") == d and now.hour < 1 and os.environ.get("TW_EARLY") != "1":
        print(json.dumps({"day": d, "status": "before 01:00 PT; not running"})); return
    df = RN.load_llm(F.build(include_today=True))
    tr = df[(~df.is_today) & (df.day < d) & (~df.known)]
    a = df[df.is_today & (df.day == d) & (~df.known)].copy()
    if a.empty:
        print(json.dumps({"day": d, "status": "no 00:05 rows"})); return
    ph = a.maker_ids.apply(lambda m: (not m) or any(str(x) in ("0", "", "None") for x in m))
    tr2, te = M.add_fold_feats(tr, a)
    src, dropped = M.live_sources(tr2, te, M.LIVE_SOURCES)
    cols = M.cols(tr2, src); mc = [c for c in cols if MAKER(c)]
    fx = te.copy(); fx.loc[ph.values, mc] = np.nan
    models = [M.fit_predict(tr2, te, src, seed=s, **M.LIVE_PARAMS)[1] for s in range(5)]
    p0 = np.mean([m.predict(te[cols]) for m in models], axis=0); p1 = np.mean([m.predict(fx[cols]) for m in models], axis=0)
    import lightgbm as lgb
    cc = [c for c in cols if not c.startswith(MP) and c not in ID]
    p2 = np.mean([lgb.LGBMRegressor(n_estimators=400, learning_rate=0.03, num_leaves=15, min_child_samples=20, subsample=0.8, subsample_freq=1,
                                    colsample_bytree=0.5, reg_lambda=1.0, random_state=s, verbose=-1, n_jobs=M.N_JOBS).fit(tr2[cc], tr2.logv).predict(te[cc])
                  for s in range(5)], axis=0)
    # orchestrator 13:34Z Nov 12: clean_nosite = the clean line without llm_site (homepage text fetched after launch in the backtest)
    cn = [c for c in cc if c != "llm_site"]
    p3 = np.mean([lgb.LGBMRegressor(n_estimators=400, learning_rate=0.03, num_leaves=15, min_child_samples=20, subsample=0.8, subsample_freq=1,
                                    colsample_bytree=0.5, reg_lambda=1.0, random_state=s, verbose=-1, n_jobs=M.N_JOBS).fit(tr2[cn], tr2.logv).predict(te[cn])
                  for s in range(5)], axis=0)
    out = pd.DataFrame({"id": te.id.astype(str).values, "pred_unfixed": p0, "pred_makerfix": p1, "pred_clean": p2, "pred_clean_nosite": p3, "placeholder": ph.values})
    out["rank_clean_nosite"] = out.pred_clean_nosite.rank(ascending=False, method="first").astype(int)
    out["rank_unfixed"] = out.pred_unfixed.rank(ascending=False, method="first").astype(int)
    out["rank_makerfix"] = out.pred_makerfix.rank(ascending=False, method="first").astype(int)
    out["rank_clean"] = out.pred_clean.rank(ascending=False, method="first").astype(int)
    # orchestrator 08:30Z Nov 12: rank-average of the clean LightGBM and a ridge on the same clean columns
    from sklearn.linear_model import Ridge
    # near-constant training columns (e.g. comp_nn_sim) explode at 00:05 (z ~ -1e9): drop them, clip z to +-5
    rc = [c for c in cc if tr2[c].astype(float).std() > 1e-6]
    med = tr2[rc].median().fillna(0.0); Xtr = tr2[rc].astype(float).fillna(med); Xte = te[rc].astype(float).fillna(med)
    mu, sd = Xtr.mean(), Xtr.std().fillna(0.0) + 1e-9
    z = lambda X: ((X - mu) / sd).fillna(0.0).clip(-5, 5)
    out["pred_clean_ridge"] = Ridge(alpha=10.0).fit(z(Xtr), tr2.logv).predict(z(Xte))
    out["rank_clean_lgb"] = out.rank_clean
    out["rank_clean_avg"] = (out.pred_clean.rank(pct=True) + out.pred_clean_ridge.rank(pct=True)).rank(ascending=False, method="first").astype(int)
    res = {"day": d, "written_at": pd.Timestamp.now(tz="UTC").isoformat(), "inputs": "data/today/<d>.json (00:05 snapshot) only",
           "launches": int(len(out)), "placeholder_launches": int(ph.sum()), "maker_cols": mc, "sources": src, "dropped": dropped,
           "clean_cols": cc, "clean_dropped": sorted(set(cols) - set(cc)),
           "forecast": out.sort_values("rank_makerfix").round(4).to_dict("records")}
    os.makedirs(f"{RN.OUT}/shadow_makerfix", exist_ok=True)
    p = f"{RN.OUT}/shadow_makerfix/{d}.json"; json.dump(res, open(p, "w"), indent=1, default=bool)
    print(p)


if __name__ == "__main__":
    main(sys.argv[1])
