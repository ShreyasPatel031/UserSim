"""STRUCT-BT26 (orchestrator 14:33Z Nov 25): arm-3 month-forward replica for every 2026 day (the knn1_vm.py replica, spearman 0.995 vs the
stored arm-3 backtest), arm3_ref only (no monotone refits). Same frame, inputs, params and 5 seeds as arm3_live.predict; test month m trained
only on days before m. Scratch data root and cache only. Writes <out>/oos.parquet: id, day, mon, dailyRank, votes, arm3_ref, n_inputs.
--- original knn1_vm.py header follows ---
PH-KNN1, VM part (orchestrator 10:01Z Nov 23). Month-forward replica of the live arm 3 (arm3_live.predict: same frame, same input
set, same LightGBM params, 5 seeds) on every month with a training month before it, plus candidate (2): the same model refit with
monotone (+1) constraints on hunter followers, maker X followers, company X followers, promo reactions and promo posts. Only promo_posts
is a live arm-3 input (62 inputs; the other four are not used by arm 3), so (2a) arm3_mono constrains promo_posts only and (2b) arm3_mono_add
adds the four missing inputs and constrains all five.
Walk-forward: test month m is trained only on days before m's first day (2025 test months on 2025 days only). Fold features
(M.add_fold_feats) are learned on the training rows only. Labels (votes, dailyRank) are never inputs.
Runs on scratch copies (H25_DATA and ARM3_CACHE must point at scratch dirs; the live cache and data root are not touched).
Writes <out>/oos.parquet: id, day, mon, dailyRank, votes, arm3_ref, arm3_mono, arm3_mono_add, and every arm-3 input (+ the four added) of that month's model.
usage (VM, cwd ~/w/experiments/ph_predict): PYTHONPATH=$HOME/w/mk:.:$HOME/w/h25:$HOME/w/arm3_live H25_DATA=<scratch> H25_SRC=~/w/ph_history/2025
  ARM3_CACHE=<scratch cache> python3 knn1_vm.py <run day YYYY-MM-DD> <out dir>"""
import glob, json, os, sys, time
import numpy as np, pandas as pd
import lightgbm as lgb
import features as F, model as M, run as RN
import history_retrain as HR, arm3_feats as A3, arm3_live as AL, rootlink

DAY, OUT = sys.argv[1], sys.argv[2]; os.makedirs(OUT, exist_ok=True)
MONO = ["ph_hunter_followers", "x_maker_sum_followers", "x_company_followers", "promo_reactions", "promo_posts"]
assert "structbt" in os.environ["H25_DATA"], "H25_DATA must be a scratch dir"
assert "structbt" in os.environ.get("ARM3_CACHE", ""), "ARM3_CACHE must be a scratch copy"
t0 = time.time(); log = lambda **k: print(json.dumps({**k, "s": round(time.time() - t0)}), flush=True)
root = os.path.expanduser(os.environ["H25_DATA"]); src_dir = os.path.expanduser(os.environ["H25_SRC"]); real = F.D
rootlink.link_root(real, root, glob.glob(f"{src_dir}/*.json")); F.D = root
try:
    df = RN.load_llm(F.build(include_today=DAY))
finally:
    F.D = real
df["id"] = df.id.astype(str); old = df.day < "2026-01-01"
df.loc[old, [c for c in df.columns if c.startswith(HR.OLD_NAN) or (c.startswith("llm_") and c not in ("llm_pitch", "llm_brand"))]] = np.nan
df = df[~df.known.astype(bool) & (df.day < DAY) & ~df.is_today.astype(bool)].reset_index(drop=True)
E, einfo = AL._cache_embed(df, np.zeros(len(df), bool))
X, NEW = A3.add_feats(df, E, norm=os.environ.get("ARM3_NORM", "strong"), line_up=None)
X["mon"] = X.day.astype(str).str[:7]; old = (X.day < "2026-01-01").values
log(rows=len(X), days=int(X.day.nunique()), first=str(X.day.min()), last=str(X.day.max()), new_feats=len(NEW), **einfo)
fitp = lambda tr, te, cc, extra: np.mean([lgb.LGBMRegressor(random_state=s, verbose=-1, n_jobs=3, **AL.P_, **extra).fit(tr[cc], tr.logv).predict(te[cc]) for s in range(5)], 0)
parts = []
for m in sorted(X.mon.unique()):
    trm = (X.day < f"{m}-01").values & (old if m < "2026" else True); tem = (X.mon == m).values
    if tem.sum() == 0 or trm.sum() < 2000: continue
    tr, te = M.add_fold_feats(X[trm], X[tem]); src, _ = M.live_sources(tr, te, M.LIVE_SOURCES)
    cc = [c for c in M.cols(tr, src) if not c.startswith(AL.MP) and c not in AL.ID and c not in ("llm_site", "ph_month")] + NEW
    ref = fitp(tr, te, cc, {})
    P = te[["id", "day", "mon", "dailyRank", "votes"]].copy(); P["arm3_ref"] = ref; P["n_inputs"] = len(cc)
    if os.environ.get("SAVE_INPUTS_FROM") and m == os.environ["SAVE_INPUTS_FROM"][:7]:   # parity read (orchestrator 21:22Z Nov 25): the month's inputs
        te[te.day >= os.environ["SAVE_INPUTS_FROM"]][["id", "day"] + cc].to_parquet(os.path.join(OUT, "inputs_tail.parquet"), index=False)
    parts.append(P); log(month=m, train=int(trm.sum()), test=int(tem.sum()), inputs=len(cc))
O = pd.concat(parts, ignore_index=True)
for c in O.columns:
    if O[c].dtype == object and c not in ("id", "day", "mon"): O[c] = pd.to_numeric(O[c], errors="coerce")
O.to_parquet(os.path.join(OUT, "oos.parquet"), index=False); log(done=True, rows=len(O), months=int(O.mon.nunique()))
