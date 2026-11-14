"""Repro A14 (orchestrator 16:33Z Nov 14; live bug confirmed by PH ops): features.build(include_today=True) reads EVERY data/today/*.json,
so earlier nights' unlabelled 00:05 line-ups enter the frame and add_history / same-day counts use them.
Two private data roots for target day D over the same real data (symlinks; nothing written to the data):
  clean = days/ (< D) + today/D.json only        stale = days/ (< D) + every today/<d'>.json with d' <= D (as the VM folder stood)
Asserts, with the features.py given: (a) the target day's line-up rows (is_today, day D) have IDENTICAL hunter / maker history and same-day
counts in both roots; (b) no row without a label (is_today) other than day D's own line-up is present in the stale frame (or, if present, it
does not change any history input of labelled rows); (c) the target day's line-up still gets history (hist_hunter_n > 0 for some rows).
Exit 0 = fixed (all hold), 1 = bug present.
    python repro_A14.py <dir holding features.py (+ the ph_predict modules)> <real data dir> <day D> [<scratch dir>]"""
import sys, os, glob, json, shutil, tempfile
CODE, REAL, D = sys.argv[1:4]; TMP = sys.argv[4] if len(sys.argv) > 4 else tempfile.mkdtemp()
sys.path.insert(0, CODE); os.chdir(CODE)
import numpy as np, pandas as pd
import features as F
COLS = ["hist_hunter_n", "hist_hunter_rel", "hist_maker_n", "ph_hunter_n_same_day", "hist_dayrank_hist_hunter_n", "hist_dayrank_hist_hunter_rel"]
def root(name, stale):
    r = os.path.join(TMP, name); shutil.rmtree(r, ignore_errors=True); os.makedirs(f"{r}/days"); os.makedirs(f"{r}/today")
    for e in os.listdir(REAL):
        if e not in ("days", "today") and not e.startswith("build_cache"): os.symlink(f"{REAL}/{e}", f"{r}/{e}")
    for fn in glob.glob(f"{REAL}/days/*.json"):
        if os.path.basename(fn)[:10] < D: os.symlink(fn, f"{r}/days/{os.path.basename(fn)}")
    for fn in glob.glob(f"{REAL}/today/*.json"):
        b = os.path.basename(fn)[:10]
        if b == D or (stale and b < D): os.symlink(fn, f"{r}/today/{os.path.basename(fn)}")
    return r
out = {}
FR = {}
for nm, st in (("clean", False), ("stale", True)):
    F.D = root(nm, st); df = F.build(include_today=True); df["id"] = df.id.astype(str); FR[nm] = df
    out[f"{nm}: today files"] = len(os.listdir(f"{F.D}/today")); out[f"{nm}: unlabelled rows not on day D"] = int((df.is_today & (df.day != D)).sum())
cols = [c for c in COLS if c in FR["clean"] and c in FR["stale"]]
tc = FR["clean"][FR["clean"].is_today & (FR["clean"].day == D)].set_index("id")[cols].sort_index()
ts = FR["stale"][FR["stale"].is_today & (FR["stale"].day == D)].set_index("id")[cols].reindex(tc.index)
diff = {c: int((~np.isclose(tc[c].fillna(-999).astype(float), ts[c].fillna(-999).astype(float))).sum()) for c in cols}
# labelled training rows (< D) must not change either
lc = FR["clean"][~FR["clean"].is_today].set_index("id")[cols]; ls = FR["stale"][~FR["stale"].is_today].set_index("id")[cols].reindex(lc.index)
diff_tr = {c: int((~np.isclose(lc[c].fillna(-999).astype(float), ls[c].fillna(-999).astype(float))).sum()) for c in cols}
a = all(v == 0 for v in diff.values()); b = all(v == 0 for v in diff_tr.values()); c_ = bool((tc.get("hist_hunter_n", pd.Series([0])) > 0).any())
out.update({"day": D, "line-up rows": len(tc), "target rows differing (clean vs stale)": diff, "labelled training rows differing": diff_tr,
            "target line-up has history (hist_hunter_n > 0 somewhere)": c_, "A14 fixed": a and b and c_})
print(json.dumps(out)); sys.exit(0 if out["A14 fixed"] else 1)
