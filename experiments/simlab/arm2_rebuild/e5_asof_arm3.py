"""As-of 00:05 replay of arm 3 (arm 2 + arm3_feats A+B+C) vs arm 2 on the held 00:05 line-ups (same private roots as e5_asof_0005.py, mode
asof). Block A over the real 00:05 line-up; the day's launches are embedded fresh from the 00:05 text; history embeddings come from the
cache (EMB + EMB_IDS) or are embedded. Seeds 0-4 as h25_live. NORM env = plain | strong.   usage: python e5_asof_arm3.py <out dir> <day> ..."""
import glob, json, os, shutil, sys, time
os.environ.setdefault("LGB_THREADS", "2")
import numpy as np, pandas as pd, lightgbm as lgb
import features as F, model as M, run as RN, history_retrain as HR, arm3_feats as A3
REAL = os.path.abspath(F.D); H25 = os.environ["H25_SRC"]; OUT = sys.argv[1]; os.makedirs(OUT, exist_ok=True)
MP = ("ph_maker", "hist_maker", "hist_dayrank_hist_maker", "x_maker", "x_n_makers"); ID = {"ph_n_makers_new", "ph_maker_has_headline", "x_any_verified", "ph_self_hunted"}
P_ = dict(n_estimators=400, learning_rate=0.03, num_leaves=15, min_child_samples=20, subsample=0.8, subsample_freq=1, colsample_bytree=0.5, reg_lambda=1.0)
CE = np.load(os.environ["EMB"]); CI = list(pd.read_parquet(os.environ["EMB_IDS"]).id.astype(str)); CM = dict(zip(CI, range(len(CI))))
for d in sys.argv[2:]:
    t0 = time.time(); r = f"{os.environ['ROOTS']}/{d}_asof_1"
    if not os.path.isdir(r): print(json.dumps({"day": d, "skipped": "no root"})); continue
    F.D = r; df = RN.load_llm(F.build(include_today=True)); F.D = REAL; df["id"] = df.id.astype(str)
    old = df.day < "2026-01-01"
    df.loc[old, [c for c in df.columns if c.startswith(HR.OLD_NAN) or (c.startswith("llm_") and c not in ("llm_pitch", "llm_brand"))]] = np.nan
    df = df[~df.known].reset_index(drop=True)
    tod = (df.day == d) & df.is_today; E = np.zeros((len(df), 384), np.float32)
    have = np.array([(i in CM) and not t for i, t in zip(df.id, tod)])
    E[have] = CE[[CM[i] for i in df.id[have]]]; miss = ~have
    E[miss] = A3.embed(A3.text_of(df[miss]))
    X, NEW = A3.add_feats(df, E, norm=os.environ.get("NORM", "plain"), line_up=tod.values)
    tr, te = X[(~X.is_today) & (X.day < d)], X[tod.values].copy()
    tr, te = M.add_fold_feats(tr, te); src, _ = M.live_sources(tr, te, M.LIVE_SOURCES)
    cc = [c for c in M.cols(tr, src) if not c.startswith(MP) and c not in ID and c not in ("llm_site", "ph_month")]
    o = te[["id"]].copy(); o["day"] = d
    for nm, cols in (("pred_arm2", cc), ("pred_arm3", cc + NEW)):
        o[nm] = np.mean([lgb.LGBMRegressor(random_state=s, verbose=-1, n_jobs=M.N_JOBS, **P_).fit(tr[cols], tr.logv).predict(te[cols]) for s in range(5)], axis=0)
    o.to_parquet(f"{OUT}/{d}.parquet"); print(json.dumps({"day": d, "n": len(te), "embedded_fresh": int(miss.sum()), "seconds": round(time.time() - t0)}), flush=True)
