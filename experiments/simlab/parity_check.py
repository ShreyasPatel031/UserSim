"""Live-vs-backtest input parity for the arm-2 00:05 model (orchestrator 17:34Z Nov 14; catches the next today-rows-type bug).
For day D build
  LIVE path      private root: days/ <= D-2 (labels the VM has at 00:05; D-1 closes minutes earlier and is a known, accepted difference),
                 today/ = only today/D.json, every other data entry as is, the 2025 lists added (h25_live path), F.build(include_today=D)
                 with the FIXED features.py (033d7bd7) -> rows is_today & day == D
  BACKTEST path  root with every days/ file (+ 2025), no today/ -> rows day == D (the frame the 183-day backtest scores; HR.build)
Both get the same arm-2 old-row rules. For each of arm 2's raw inputs (M.cols over LIVE_SOURCES minus the named-maker / ID / llm_site /
ph_month set), over launches present in both: share equal (|a-b| <= 1e-9, NaN==NaN), mean and p95 |diff| in SD units (SD over the
backtest day). Fold features (txt_ ridge, topic priors) depend on the training set and are compared after add_fold_feats with each path's
own training rows; reported separately.
Known differences (EXPECTED, not alerted): hunter / maker history and their day-rank transforms (D-1 not yet labelled), same-day / line-up
size counts (00:05 vs final featured list), fold features. Every other column with a differing share > ALERT_SHARE (default 0.0) is
UNEXPECTED -> exit 1.
Set change: an arm-2 LightGBM (3 seeds) trained on the backtest path's rows of months before D's month scores the backtest-path rows;
then each live column replaces its backtest column one at a time (and all together): changed top-3 / 5 / 10 members.
    python parity_check.py <code dir: ph_predict modules + fixed features.py> <data dir> <2025 lists dir> <day> [out json]"""
import os, sys, json, glob, shutil, tempfile
CODE, DATA, H25, D = sys.argv[1:5]; OUT = sys.argv[5] if len(sys.argv) > 5 else None
sys.path.insert(0, CODE); os.chdir(CODE)
import numpy as np, pandas as pd, lightgbm as lgb
import features as F, model as M, run as RN
OLD_NAN = ("promo_", "busy_", "x_")
MP = ("ph_maker", "hist_maker", "hist_dayrank_hist_maker", "x_maker", "x_n_makers"); ID = {"ph_n_makers_new", "ph_maker_has_headline", "x_any_verified", "ph_self_hunted"}
EXPECTED_PREFIX = ("hist_", "ph_hunter_n_same_day", "ph_day_n_launches", "txt_", "topic_prior")
ALERT = float(os.environ.get("ALERT_SHARE", "0.0")); TMP = tempfile.mkdtemp()
d2 = (pd.Timestamp(D) - pd.Timedelta(days=2)).strftime("%Y-%m-%d")
def root(name, live):
    r = f"{TMP}/{name}"; os.makedirs(f"{r}/days"); os.makedirs(f"{r}/today")
    for e in os.listdir(DATA):
        if e not in ("days", "today") and not e.startswith("build_cache"): os.symlink(f"{DATA}/{e}", f"{r}/{e}")
    for fn in glob.glob(f"{DATA}/days/*.json") + glob.glob(f"{H25}/*.json"):
        b = os.path.basename(fn)[:10]
        if not live or b <= d2: os.symlink(os.path.abspath(fn), f"{r}/days/{os.path.basename(fn)}")
    if live: os.symlink(f"{DATA}/today/{D}.json", f"{r}/today/{D}.json")
    return r
def frame(live):
    F.D = root("live" if live else "bt", live); df = RN.load_llm(F.build(include_today=D if live else False)); df["id"] = df.id.astype(str)
    old = df.day < "2026-01-01"
    df.loc[old, [c for c in df.columns if c.startswith(OLD_NAN) or (c.startswith("llm_") and c not in ("llm_pitch", "llm_brand"))]] = np.nan
    return df[~df.known]
L, B = frame(True), frame(False)
lt = L[L.is_today & (L.day == D)].set_index("id"); bt = B[(B.day == D) & ~B.is_today].set_index("id")
both = sorted(set(lt.index) & set(bt.index))
trB = B[(B.day < D) & ~B.is_today & (B.day.str[:7] < D[:7])]
src, _ = M.live_sources(trB, bt.reset_index(), M.LIVE_SOURCES)
cols = [c for c in M.cols(trB, src) if not c.startswith(MP) and c not in ID and c not in ("llm_site", "ph_month")]
raw = [c for c in cols if c in lt.columns and c in bt.columns]
res = {"day": D, "live rows": len(lt), "backtest rows": len(bt), "in both": len(both), "only live": len(set(lt.index) - set(bt.index)), "only backtest": len(set(bt.index) - set(lt.index)), "columns": {}}
for c in raw:
    a = pd.to_numeric(lt.loc[both, c], errors="coerce").astype(float); b = pd.to_numeric(bt.loc[both, c], errors="coerce").astype(float)
    eq = (np.isclose(a, b, atol=1e-9, rtol=0) | (a.isna() & b.isna())); sd = float(pd.to_numeric(bt[c], errors="coerce").std() or 1.0)
    dd = (a - b).abs() / (sd if sd > 0 else 1.0)
    res["columns"][c] = {"share_equal": round(float(eq.mean()), 3), "mean_abs_diff_sd": round(float(dd.mean()), 3) if dd.notna().any() else None,
                         "p95_abs_diff_sd": round(float(dd.quantile(.95)), 3) if dd.notna().any() else None, "nan_live": int(a.isna().sum()), "nan_backtest": int(b.isna().sum()),
                         "expected": c.startswith(EXPECTED_PREFIX)}
# fold features with each path's own training rows
trL = L[(~L.is_today) & (L.day <= d2)]
_, teL = M.add_fold_feats(trL, lt.loc[both].reset_index()); trB2, teB = M.add_fold_feats(trB, bt.loc[both].reset_index())
fold = [c for c in cols if c not in raw or c.startswith(("txt_", "topic_prior"))]
for c in [c for c in cols if c.startswith(("txt_", "topic_prior"))]:
    a, b = teL[c].astype(float).values, teB[c].astype(float).values; sd = float(trB2[c].std() or 1.0)
    res["columns"][c] = {"share_equal": round(float(np.mean(np.isclose(a, b, atol=1e-9))), 3), "mean_abs_diff_sd": round(float(np.nanmean(np.abs(a - b)) / sd), 3), "expected": True, "fold feature": True}
# set change: model on backtest path, swap live columns in
X = teB.copy(); Lx = teL.set_index("id").reindex(X.id)
ms = [lgb.LGBMRegressor(random_state=s, verbose=-1, n_jobs=M.N_JOBS, n_estimators=400, learning_rate=0.03, num_leaves=15, min_child_samples=20, subsample=0.8, subsample_freq=1,
                        colsample_bytree=0.5, reg_lambda=1.0).fit(trB2[cols], trB2.logv) for s in range(3)]
pr = lambda Z: np.mean([m.predict(Z[cols]) for m in ms], axis=0)
base = pr(X); order = lambda p: list(X.id.values[np.argsort(-p, kind="stable")])
ob = order(base); chg = {}
def ch(p):
    o = order(p); return [k - len(set(ob[:k]) & set(o[:k])) for k in (3, 5, 10)]
for c in cols:
    Z = X.copy(); Z[c] = Lx[c].values; v = ch(pr(Z))
    if any(v): chg[c] = v
Z = X.copy()
for c in cols: Z[c] = Lx[c].values
res["set change top3/5/10 (members changed) per swapped column (only nonzero)"] = chg; res["set change, all live columns together"] = ch(pr(Z))
unexp = {c: v for c, v in res["columns"].items() if not v.get("expected") and v["share_equal"] < 1 - ALERT}
res["UNEXPECTED differing columns"] = unexp; res["status"] = "ALERT" if unexp else "ok"
s = json.dumps(res, default=float)
if OUT: open(OUT, "w").write(s)
print(json.dumps({k: v for k, v in res.items() if k != "columns"}, default=float)); shutil.rmtree(TMP, ignore_errors=True)
sys.exit(1 if unexp else 0)
