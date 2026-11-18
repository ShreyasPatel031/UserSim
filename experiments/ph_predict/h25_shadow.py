"""Shadow line clean_nosite_h25 (orchestrator 03:51Z Nov 13 rule: freeze as a shadow column the same day it wins with a positive
interval; history_retrain on 95 days of 2025, 5 seeds: top 3 +3.0 [+1.1, +5.0], seed sd 0.6-0.7). Runs on the pipeline VM AFTER
makerfix_shadow.py (never 00:05-01:00 PT), read-only for everything deployed; isolated output so a failure cannot touch the main shadow.
Same training as makerfix_shadow's clean_nosite line (days < d, the 00:05 rows of data/today/<d>.json, add_fold_feats, live_sources,
5 seeds, same LightGBM params), but the training rows also hold the 2025 lists (history_retrain.build: private data dir, old-row
rules: promo_/busy_/x_/llm_* missing on 2025 rows) and ph_month is dropped. Also writes the 2026-only twin on the same columns
(pred_clean_nosite_pure: plain 2026 build, no 2025 anywhere, same columns) so the forward comparison isolates the 2025 effect.
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
    for fn in glob.glob(f"{real}/days/*.json") + HR.src_files(src_dir):
        dst = f"{root}/days/{os.path.basename(fn)}"
        if not os.path.exists(dst):
            os.symlink(os.path.abspath(fn), dst)
    F.D = root
    df = RN.load_llm(F.build(include_today=True)); df["id"] = df.id.astype(str)
    old = df.day < "2026-01-01"
    # arm 2 (orchestrator 04:39Z Nov 13; history_retrain arm 2: top 3 +3.9 [+1.6, +6.5] vs pure, rho +0.028): keep the Gemini-scored
    # 2025 llm_pitch / llm_brand (h25_llm.py private cache); arm 1 = every llm_* missing on 2025 rows (the original h25 line)
    df2 = df.copy()
    df.loc[old, [c for c in df.columns if c.startswith(HR.OLD_NAN) or c.startswith("llm_")]] = np.nan
    df2.loc[old, [c for c in df2.columns if c.startswith(HR.OLD_NAN) or (c.startswith("llm_") and c not in ("llm_pitch", "llm_brand"))]] = np.nan
    tr = df[(~df.is_today) & (df.day < d) & (~df.known)]
    a = df[df.is_today & (df.day == d) & (~df.known)].copy()
    if a.empty:
        print(json.dumps({"day": d, "status": "no 00:05 rows"})); return
    import lightgbm as lgb
    # twin (orchestrator 05:05Z decomposition, h25_stack.md): the comparison line must be PURE 2026 (no 2025 anywhere, i.e. hunter
    # history built without the 2025 lists), not the 2026 rows of the 2025-inclusive build (which scored worse than pure)
    F.D = real; dfo = RN.load_llm(F.build(include_today=True)); dfo["id"] = dfo.id.astype(str); F.D = root
    tro = dfo[(~dfo.is_today) & (dfo.day < d) & (~dfo.known)]; ao = dfo[dfo.is_today & (dfo.day == d) & (~dfo.known)].copy()
    P = {}
    tr2_ = df2[(~df2.is_today) & (df2.day < d) & (~df2.known)]
    for nm, trx, ax in (("h25", tr, a), ("h25llm", tr2_, a), ("pure", tro, ao)):
        tr2, te = M.add_fold_feats(trx, ax)
        src, _ = M.live_sources(tr2, te, M.LIVE_SOURCES)
        cols = M.cols(tr2, src)
        cn = [c for c in cols if not c.startswith(MS.MP) and c not in MS.ID and c not in ("llm_site", "ph_month")]
        P[nm] = np.mean([lgb.LGBMRegressor(n_estimators=400, learning_rate=0.03, num_leaves=15, min_child_samples=20, subsample=0.8, subsample_freq=1,
                                           colsample_bytree=0.5, reg_lambda=1.0, random_state=s, verbose=-1, n_jobs=M.N_JOBS).fit(tr2[cn], tr2.logv).predict(te[cn])
                         for s in range(5)], axis=0)
        P[nm + "_ids"] = te.id.astype(str).values
    out = pd.DataFrame({"id": P["h25_ids"], "pred_clean_nosite_h25": P["h25"]})
    out["pred_clean_nosite_pure"] = out.id.map(dict(zip(P["pure_ids"], P["pure"])))
    out["pred_clean_nosite_h25llm"] = out.id.map(dict(zip(P["h25llm_ids"], P["h25llm"])))
    out["rank_clean_nosite_h25llm"] = out.pred_clean_nosite_h25llm.rank(ascending=False, method="first")
    out["rank_clean_nosite_h25"] = out.pred_clean_nosite_h25.rank(ascending=False, method="first").astype(int)
    out["rank_clean_nosite_pure"] = out.pred_clean_nosite_pure.rank(ascending=False, method="first")
    res = {"day": d, "written_at": pd.Timestamp.now(tz="UTC").isoformat(), "inputs": "data/today/<d>.json (00:05 snapshot) only; training adds raw/ph_history/2025",
           "train_rows_2025": int(old[tr.index].sum()) if len(tr) else 0, "train_days_2025": int(tr[tr.day < "2026-01-01"].day.nunique()),
           "launches": int(len(out)), "frozen_rule": "approved 05:05Z Nov 13; corrected baseline (h25_stack.md, 145 days of 2025): vs pure top 3 +0.9 [-1.2, +3.3], rho +0.016 [+0.005, +0.028]",
           "forecast": out.sort_values("rank_clean_nosite_h25").round(4).to_dict("records")}
    os.makedirs(f"{RN.OUT}/shadow_h25", exist_ok=True)
    p = f"{RN.OUT}/shadow_h25/{d}.json"; json.dump(res, open(p, "w"), indent=1)
    print(p)


if __name__ == "__main__":
    main(sys.argv[1])
