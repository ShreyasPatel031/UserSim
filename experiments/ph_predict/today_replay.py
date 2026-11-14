"""Today-rows bug replay (orchestrator 16:38Z Nov 14). Scratch only; counts / ids / scores, no names. Read-only on live data (symlinked roots).
For each live night d (today/<d>.json exists, Oct 26 - Nov 14) rebuild the 00:05 frame AS OF that night: days/ files <= d-2 (the ranks step
writes d-1 after the forecast) and
  MODE=polluted: every today/ file dated <= d, F.build(include_today=True) with the current features.py (981c5ded) - what ran that night;
  MODE=fixed:    today/<d>.json only, F.build(include_today=d) with the patched features.py (033d7bd7).
Models (train rows = labelled, not known; add_fold_feats + live_sources as forecast.py; 5 seeds, P_ = training_window P0):
  deployed      M.cols(live sources)            - the old full model (published Oct 26 - Nov 13; clean_live.py 'deployed')
  clean_nosite  minus maker-profile / named-maker inputs and llm_site - forecast.py's 'pred' (published Nov 14; the hybrid's z(clean) prior)
Writes <out>/today_replay_<MODE>.parquet (day, id, deployed, clean_nosite) and one json line per night.
usage (VM, cwd ~/w/experiments/ph_predict): MODE=fixed PYTHONPATH=<features dir>:. python3 today_replay.py <scratch dir> <out dir> [first] [last]"""
import json, os, sys, shutil
import numpy as np, pandas as pd
import lightgbm as lgb
import features as F, model as M, run as RN
MODE = os.environ["MODE"]; T, OUT = sys.argv[1], sys.argv[2]; first = sys.argv[3] if len(sys.argv) > 3 else "2026-10-26"
last = sys.argv[4] if len(sys.argv) > 4 else "2026-11-14"; os.makedirs(OUT, exist_ok=True)
REAL = os.path.realpath(F.D); MP = ("ph_maker", "hist_maker", "hist_dayrank_hist_maker", "x_maker", "x_n_makers")
ID = {"ph_n_makers_new", "ph_maker_has_headline", "x_any_verified", "ph_self_hunted"}
P_ = dict(n_estimators=400, learning_rate=0.03, num_leaves=15, min_child_samples=20, subsample=0.8, subsample_freq=1, colsample_bytree=0.5, reg_lambda=1.0)
print("features from", os.path.realpath(F.__file__), flush=True)
nights = sorted(os.path.basename(f)[:10] for f in os.listdir(f"{REAL}/today") if first <= f[:10] <= last)
rows = []
for d in nights:
    cut = (pd.Timestamp(d) - pd.Timedelta(days=2)).strftime("%Y-%m-%d"); r = f"{T}/root_{MODE}_{d}"
    if os.path.exists(r): shutil.rmtree(r)   # our own scratch root (symlinks only)
    os.makedirs(f"{r}/days"); os.makedirs(f"{r}/today")
    for e in os.listdir(REAL):
        if e not in ("days", "today") and not e.startswith("build_cache"): os.symlink(os.path.realpath(f"{REAL}/{e}"), f"{r}/{e}")
    for fn in os.listdir(f"{REAL}/days"):
        if fn[:10] <= cut: os.symlink(os.path.realpath(f"{REAL}/days/{fn}"), f"{r}/days/{fn}")
    for fn in os.listdir(f"{REAL}/today"):
        if (fn[:10] <= d) if MODE == "polluted" else (fn[:10] == d): os.symlink(os.path.realpath(f"{REAL}/today/{fn}"), f"{r}/today/{fn}")
    F.D = r
    try: df = RN.load_llm(F.build(include_today=True if MODE == "polluted" else d))
    finally: F.D = REAL
    df = df[~df.known]; tr = df[~df.is_today]; te = df[df.is_today & (df.day == d)]
    tr, te = M.add_fold_feats(tr, te.copy()); src, _ = M.live_sources(tr, te, M.LIVE_SOURCES)
    cd = M.cols(tr, src); cc = [c for c in cd if not c.startswith(MP) and c not in ID and c != "llm_site"]
    X = pd.DataFrame({"day": d, "id": te.id.astype(str).values})
    for nm, cols in (("deployed", cd), ("clean_nosite", cc)):
        X[nm] = np.mean([lgb.LGBMRegressor(random_state=s, verbose=-1, n_jobs=int(os.environ.get("LGB_THREADS", "3")), **P_).fit(tr[cols], tr.logv).predict(te[cols]) for s in range(5)], 0)
    rows.append(X); shutil.rmtree(r)
    print(json.dumps({"night": d, "mode": MODE, "train_days": int(tr.day.nunique()), "last_train_day": tr.day.max(), "test": len(te),
                      "stale_today_rows": int((df.is_today & (df.day < d)).sum()), "test_rel_nan": int(te.hist_hunter_rel.isna().sum())}), flush=True)
    pd.concat(rows).to_parquet(f"{OUT}/today_replay_{MODE}.parquet")
