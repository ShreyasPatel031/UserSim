"""Arm 2 (2025-trained, Gemini pitch/brand kept on 2025 rows) as the PUBLISHED 00:05 model (orchestrator call 19:06Z Nov 13 under AGENTS.md
"how models are chosen"; 214 days: top 3 60.7 vs clean_nosite 56.9, +3.9 [+1.4, +6.5]; last 107 +2.8 [-0.3, +5.9]). Same training as
h25_shadow.py's h25llm line: private data dir ~/w/h25/data (real data entries symlinked + raw/ph_history/2025 day lists), old-row rules
(promo_/busy_/x_/llm_* missing on 2025 rows except llm_pitch / llm_brand), ph_month dropped, clean_nosite input set (no named-maker inputs,
no llm_site), 5 seeds, same LightGBM params. predict(day) -> DataFrame(id, pred_arm2). Read-only for everything deployed."""
import glob, os
import numpy as np, pandas as pd
import features as F, model as M, run as RN
import history_retrain as HR
import lightgbm as lgb
MP = ("ph_maker", "hist_maker", "hist_dayrank_hist_maker", "x_maker", "x_n_makers")
ID = {"ph_n_makers_new", "ph_maker_has_headline", "x_any_verified", "ph_self_hunted"}
P_ = dict(n_estimators=400, learning_rate=0.03, num_leaves=15, min_child_samples=20, subsample=0.8, subsample_freq=1, colsample_bytree=0.5, reg_lambda=1.0)
# REPRODUCIBILITY (orchestrator 15:47Z Nov 14; undeployed): rows sorted by (day, id) before every fit (LightGBM bags by row position),
# deterministic / row-wise LightGBM with a fixed thread count, 20 seeds (REPRO_SEEDS), sha256 of the exact training / test inputs + versions.
import hashlib
REPRO_SEEDS = int(os.environ.get("REPRO_SEEDS", "20")); REPRO_JOBS = int(os.environ.get("REPRO_JOBS", "4"))
P_DET = dict(deterministic=True, force_row_wise=True, n_jobs=REPRO_JOBS)


def input_sha(X):
    return hashlib.sha256(pd.util.hash_pandas_object(X, index=False).values.tobytes()).hexdigest()[:16]


def predict(day):
    root = os.path.expanduser(os.environ.get("H25_DATA", "~/w/h25/data")); src_dir = os.path.expanduser(os.environ.get("H25_SRC", "~/w/ph_history/2025"))
    real = F.D; os.makedirs(f"{root}/days", exist_ok=True)
    for e in os.listdir(real):
        if e != "days" and not e.startswith("build_cache") and not os.path.exists(f"{root}/{e}"):
            os.symlink(f"{real}/{e}", f"{root}/{e}")
    for fn in glob.glob(f"{real}/days/*.json") + glob.glob(f"{src_dir}/*.json"):
        dst = f"{root}/days/{os.path.basename(fn)}"
        if not os.path.exists(dst): os.symlink(os.path.abspath(fn), dst)
    F.D = root
    try:
        df = RN.load_llm(F.build(include_today=True))
    finally:
        F.D = real
    df["id"] = df.id.astype(str); old = df.day < "2026-01-01"
    df.loc[old, [c for c in df.columns if c.startswith(HR.OLD_NAN) or (c.startswith("llm_") and c not in ("llm_pitch", "llm_brand"))]] = np.nan
    tr = df[(~df.is_today) & (df.day < day) & (~df.known)]; te = df[df.is_today & (df.day == day) & (~df.known)].copy()
    if te.empty or old[tr.index].sum() == 0: raise RuntimeError(f"arm2: today rows {len(te)}, 2025 training rows {int(old[tr.index].sum())}")
    tr, te = M.add_fold_feats(tr, te); src, _ = M.live_sources(tr, te, M.LIVE_SOURCES)
    tr = tr.sort_values(["day", "id"], kind="stable"); te = te.sort_values(["day", "id"], kind="stable")
    cc = [c for c in M.cols(tr, src) if not c.startswith(MP) and c not in ID and c not in ("llm_site", "ph_month")]
    pred = np.mean([lgb.LGBMRegressor(random_state=s, verbose=-1, **P_, **P_DET).fit(tr[cc], tr.logv).predict(te[cc]) for s in range(REPRO_SEEDS)], axis=0)
    import sklearn
    return pd.DataFrame({"id": te.id.astype(str).values, "pred_arm2": pred}), {"train_rows_2025": int(old[tr.index].sum()), "train_days": int(tr.day.nunique()), "inputs": len(cc),
        "seeds": REPRO_SEEDS, "sha_train": input_sha(tr[cc + ["logv"]]), "sha_test": input_sha(te[["id"] + cc]),
        "versions": {"lightgbm": lgb.__version__, "numpy": np.__version__, "pandas": pd.__version__, "sklearn": sklearn.__version__}}
