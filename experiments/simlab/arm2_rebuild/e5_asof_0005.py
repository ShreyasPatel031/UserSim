"""E5 (orchestrator 12:55Z Nov 14): arm 2 and clean_nosite replayed AS OF 00:05 on the days with a held 00:05 line-up (data/today/<d>.json),
vs the same models on the backtest-style input (the day's final featured list, days/<d>.json, later text). For each day d a private data
root holds only what existed at 00:05: every non-day entry of the backup data (symlinks), days/ = 2026 day files < d (+ the 2025 lists for
arm 2), and EITHER today/<d>.json (mode "asof") OR days/<d>.json as a test day (mode "final"). Training rows = labelled days < d.
Model code = forecast.py (clean_nosite: add_fold_feats, live_sources, no named-maker inputs, no llm_site, P_, 5 seeds) and h25_live.py
(arm 2: old-row rules, ph_month dropped). LLM scores = the stored llm_*_gemini/<d>.json (one score per launch; the same in both modes).
Output: one parquet per (day, mode) with id, pred_clean, pred_arm2.     usage: python e5_asof_0005.py <out dir> <day> [<day> ...]"""
import glob, json, os, shutil, sys, time
os.environ.setdefault("LGB_THREADS", "2")
import numpy as np, pandas as pd, lightgbm as lgb
import features as F, model as M, run as RN, history_retrain as HR
REAL = os.path.abspath(F.D); H25 = os.environ["H25_SRC"]; OUT = sys.argv[1]; os.makedirs(OUT, exist_ok=True)
MP = ("ph_maker", "hist_maker", "hist_dayrank_hist_maker", "x_maker", "x_n_makers"); ID = {"ph_n_makers_new", "ph_maker_has_headline", "x_any_verified", "ph_self_hunted"}
P_ = dict(n_estimators=400, learning_rate=0.03, num_leaves=15, min_child_samples=20, subsample=0.8, subsample_freq=1, colsample_bytree=0.5, reg_lambda=1.0)
def root(d, mode, with25):
    r = f"{os.environ['ROOTS']}/{d}_{mode}_{int(with25)}"; shutil.rmtree(r, ignore_errors=True); os.makedirs(f"{r}/days"); os.makedirs(f"{r}/today")
    for e in os.listdir(REAL):
        if e not in ("days", "today") and not e.startswith("build_cache"): os.symlink(f"{REAL}/{e}", f"{r}/{e}")
    for fn in glob.glob(f"{REAL}/days/*.json"):
        b = os.path.basename(fn)[:10]
        if b < d or (mode == "final" and b == d): os.symlink(fn, f"{r}/days/{os.path.basename(fn)}")
    if mode == "asof": os.symlink(f"{REAL}/today/{d}.json", f"{r}/today/{d}.json")
    if mode == "asof_stale":   # the VM's data/today/ as it stood that night: every earlier 00:05 line-up file plus today's (orchestrator 16:33Z bug)
        for fn in glob.glob(f"{REAL}/today/*.json"):
            if os.path.basename(fn)[:10] <= d: os.symlink(fn, f"{r}/today/{os.path.basename(fn)}")
    if with25:
        for fn in glob.glob(f"{H25}/*.json"): os.symlink(os.path.abspath(fn), f"{r}/days/{os.path.basename(fn)}")
    return r
def fit(tr, te, arm2):
    tr, te = M.add_fold_feats(tr, te); src, _ = M.live_sources(tr, te, M.LIVE_SOURCES)
    cc = [c for c in M.cols(tr, src) if not c.startswith(MP) and c not in ID and c != "llm_site" and not (arm2 and c == "ph_month")]
    return np.mean([lgb.LGBMRegressor(random_state=s, verbose=-1, n_jobs=M.N_JOBS, **P_).fit(tr[cc], tr.logv).predict(te[cc]) for s in range(5)], axis=0), te
for d in sys.argv[2:]:
    for mode in os.environ.get("MODES", "asof,final").split(","):
        t0 = time.time(); res = {}
        for arm2 in (False, True):
            F.D = root(d, mode, arm2)
            df = RN.load_llm(F.build(include_today=mode.startswith("asof"))); df["id"] = df.id.astype(str); F.D = REAL
            if arm2:
                old = df.day < "2026-01-01"
                df.loc[old, [c for c in df.columns if c.startswith(HR.OLD_NAN) or (c.startswith("llm_") and c not in ("llm_pitch", "llm_brand"))]] = np.nan
            df = df[~df.known]
            te = df[(df.day == d) & (df.is_today if mode.startswith("asof") else ~df.is_today)].copy(); tr = df[(~df.is_today) & (df.day < d)]
            if te.empty: res = None; break
            p, te2 = fit(tr, te, arm2); res["pred_arm2" if arm2 else "pred_clean"] = dict(zip(te2.id, p))
            res.setdefault("n_launches", len(te)); res.setdefault("llm_pitch_present", int(te.llm_pitch.notna().sum()))
        if res is None: print(json.dumps({"day": d, "mode": mode, "skipped": "no line-up file for this mode"}), flush=True); continue
        o = pd.DataFrame({"id": list(res["pred_clean"])}); o["pred_clean"] = o.id.map(res["pred_clean"]); o["pred_arm2"] = o.id.map(res["pred_arm2"]); o["day"] = d; o["mode"] = mode
        o.to_parquet(f"{OUT}/{d}_{mode}.parquet")
        print(json.dumps({"day": d, "mode": mode, "n": res["n_launches"], "llm_pitch_present": res["llm_pitch_present"], "seconds": round(time.time() - t0)}), flush=True)
