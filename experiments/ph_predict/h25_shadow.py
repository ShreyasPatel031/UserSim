"""Shadow line clean_nosite_h25 (orchestrator 03:51Z Nov 13 rule: freeze as a shadow column the same day it wins with a positive
interval; history_retrain on 95 days of 2025, 5 seeds: top 3 +3.0 [+1.1, +5.0], seed sd 0.6-0.7). Runs on the pipeline VM AFTER
makerfix_shadow.py (never 00:05-01:00 PT), read-only for everything deployed; isolated output so a failure cannot touch the main shadow.
Same training as makerfix_shadow's clean_nosite line (days < d, the 00:05 rows of data/today/<d>.json, add_fold_feats, live_sources,
5 seeds, same LightGBM params), but the training rows also hold the 2025 lists (history_retrain.build: private data dir, old-row
rules: promo_/busy_/x_/llm_* missing on 2025 rows) and ph_month is dropped. Also writes the 2026-only twin on the same columns
(pred_clean_nosite_noph) so the forward comparison isolates the 2025 effect.
usage (VM, from ph_predict): PYTHONPATH=~/w/mk:. H25_SRC=~/w/ph_history/2025 python3 ~/w/h25/h25_shadow.py <day>
-> results/shadow_h25/<day>.json (prints its path)"""
import json, os, sys
import numpy as np, pandas as pd
import features as F, model as M, run as RN
import makerfix_shadow as MS
import history_retrain as HR


def main(d):
    now = pd.Timestamp.now(tz="America/Los_Angeles")
    if now.strftime("%Y-%m-%d") == d and now.hour < 1:
        print(json.dumps({"day": d, "status": "before 01:00 PT; not running"})); return
    root = os.path.expanduser(os.environ.get("H25_DATA", "~/w/h25/data")); src_dir = os.environ.get("H25_SRC", os.path.expanduser("~/w/ph_history/2025"))
    real = F.D
    # same private dir as history_retrain.build, with data/today linked (include_today rows)
    os.makedirs(f"{root}/days", exist_ok=True)
    for e in os.listdir(real):
        if e != "days" and not e.startswith("build_cache") and not os.path.exists(f"{root}/{e}"):
            os.symlink(f"{real}/{e}", f"{root}/{e}")
    import glob
    for fn in glob.glob(f"{real}/days/*.json") + glob.glob(f"{src_dir}/*.json"):
        dst = f"{root}/days/{os.path.basename(fn)}"
        if not os.path.exists(dst):
            os.symlink(os.path.abspath(fn), dst)
    F.D = root
    df = RN.load_llm(F.build(include_today=True)); df["id"] = df.id.astype(str)
    old = df.day < "2026-01-01"
    df.loc[old, [c for c in df.columns if c.startswith(HR.OLD_NAN) or c.startswith("llm_")]] = np.nan
    tr = df[(~df.is_today) & (df.day < d) & (~df.known)]
    a = df[df.is_today & (df.day == d) & (~df.known)].copy()
    if a.empty:
        print(json.dumps({"day": d, "status": "no 00:05 rows"})); return
    import lightgbm as lgb
    P = {}
    for nm, trx in (("h25", tr), ("noph", tr[tr.day >= "2026-01-01"])):
        tr2, te = M.add_fold_feats(trx, a)
        src, _ = M.live_sources(tr2, te, M.LIVE_SOURCES)
        cols = M.cols(tr2, src)
        cn = [c for c in cols if not c.startswith(MS.MP) and c not in MS.ID and c not in ("llm_site", "ph_month")]
        P[nm] = np.mean([lgb.LGBMRegressor(n_estimators=400, learning_rate=0.03, num_leaves=15, min_child_samples=20, subsample=0.8, subsample_freq=1,
                                           colsample_bytree=0.5, reg_lambda=1.0, random_state=s, verbose=-1, n_jobs=M.N_JOBS).fit(tr2[cn], tr2.logv).predict(te[cn])
                         for s in range(5)], axis=0)
    out = pd.DataFrame({"id": te.id.astype(str).values, "pred_clean_nosite_h25": P["h25"], "pred_clean_nosite_noph": P["noph"]})
    out["rank_clean_nosite_h25"] = out.pred_clean_nosite_h25.rank(ascending=False, method="first").astype(int)
    out["rank_clean_nosite_noph"] = out.pred_clean_nosite_noph.rank(ascending=False, method="first").astype(int)
    res = {"day": d, "written_at": pd.Timestamp.now(tz="UTC").isoformat(), "inputs": "data/today/<d>.json (00:05 snapshot) only; training adds raw/ph_history/2025",
           "train_rows_2025": int(old[tr.index].sum()) if len(tr) else 0, "train_days_2025": int(tr[tr.day < "2026-01-01"].day.nunique()),
           "launches": int(len(out)), "frozen_rule": "history_retrain_probe 95 days, 5 seeds, top 3 +3.0 [+1.1, +5.0]",
           "forecast": out.sort_values("rank_clean_nosite_h25").round(4).to_dict("records")}
    os.makedirs(f"{RN.OUT}/shadow_h25", exist_ok=True)
    p = f"{RN.OUT}/shadow_h25/{d}.json"; json.dump(res, open(p, "w"), indent=1)
    print(p)


if __name__ == "__main__":
    main(sys.argv[1])
