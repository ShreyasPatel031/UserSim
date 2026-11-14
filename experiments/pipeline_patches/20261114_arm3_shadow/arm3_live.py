"""Arm 3 as an UNDEPLOYED shadow column pred_arm3 for the 00:05 forecast (orchestrator 13:57Z Nov 14: deployed only on Shreyas's direct
word to PH ops). Same as h25_live.predict (private data dir with the 2025 lists, old-row rules, clean_nosite input set, ph_month dropped,
5 seeds, same LightGBM params) plus arm3_feats.add_feats (A over today's 00:05 line-up, B / C from days <= d-2).
Embedding cache: <cache dir>/arm3_emb.npz {ids, E} for launches of finished days (text from the day files); today's launches are always
embedded fresh from the 00:05 text. predict(day) -> (DataFrame(id, pred_arm3), info). ANY failure raises; the caller (forecast.py patch)
catches it, writes pred_arm3 = NaN and logs the reason, so the published arm-2 order is never touched.
Env: H25_DATA, H25_SRC as h25_live; ARM3_CACHE (default ~/w/arm3_live/cache); ARM3_NORM (plain | strong)."""
import glob, os, time
import numpy as np, pandas as pd
import features as F, model as M, run as RN
import history_retrain as HR
import arm3_feats as A3
import lightgbm as lgb
MP = ("ph_maker", "hist_maker", "hist_dayrank_hist_maker", "x_maker", "x_n_makers")
ID = {"ph_n_makers_new", "ph_maker_has_headline", "x_any_verified", "ph_self_hunted"}
P_ = dict(n_estimators=400, learning_rate=0.03, num_leaves=15, min_child_samples=20, subsample=0.8, subsample_freq=1, colsample_bytree=0.5, reg_lambda=1.0)


def _cache_embed(df, tod):
    cd = os.path.expanduser(os.environ.get("ARM3_CACHE", "~/w/arm3_live/cache")); os.makedirs(cd, exist_ok=True); p = f"{cd}/arm3_emb.npz"
    ids, C = (list(np.load(p, allow_pickle=True)["ids"]), np.load(p)["E"]) if os.path.exists(p) else ([], np.zeros((0, 384), np.float32))
    pos = {k: i for i, k in enumerate(ids)}; E = np.zeros((len(df), 384), np.float32)
    have = np.array([(i in pos) and not t for i, t in zip(df.id, tod)])
    if have.any(): E[have] = C[[pos[i] for i in df.id[have]]]
    miss = ~have; t0 = time.time()
    if miss.any(): E[miss] = A3.embed(A3.text_of(df[miss]))
    new = miss & ~tod   # cache finished days only (their text is final); today's rows are re-embedded each night from 00:05 text
    if new.any():
        ids2 = ids + list(df.id[new]); C2 = np.vstack([C, E[new]]); tmp = p + ".tmp.npz"
        np.savez(tmp, ids=np.array(ids2, dtype=object), E=C2); os.replace(tmp, p)
    return E, {"embedded": int(miss.sum()), "embed_s": round(time.time() - t0, 1), "cache_rows": len(ids) + int(new.sum())}


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
    df = df[~df.known & ((df.day < day) | (df.is_today & (df.day == day)))].reset_index(drop=True)
    tod = (df.is_today & (df.day == day)).values
    if not tod.any(): raise RuntimeError(f"arm3: no 00:05 line-up rows for {day}")
    E, einfo = _cache_embed(df, tod)
    X, NEW = A3.add_feats(df, E, norm=os.environ.get("ARM3_NORM", "plain"), line_up=tod)
    tr, te = X[~tod], X[tod].copy()
    tr, te = M.add_fold_feats(tr, te); src, _ = M.live_sources(tr, te, M.LIVE_SOURCES)
    cc = [c for c in M.cols(tr, src) if not c.startswith(MP) and c not in ID and c not in ("llm_site", "ph_month")] + NEW
    pred = np.mean([lgb.LGBMRegressor(random_state=s, verbose=-1, n_jobs=M.N_JOBS, **P_).fit(tr[cc], tr.logv).predict(te[cc]) for s in range(5)], axis=0)
    return pd.DataFrame({"id": te.id.values, "pred_arm3": pred}), {"inputs": len(cc), "new_feats": len(NEW), "model": f"{A3.MODEL}@{A3.REV[:8]}", **einfo}
