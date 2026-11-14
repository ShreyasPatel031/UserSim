"""Review notes (orchestrator 16:44Z Nov 14), read-only, counts only. Each check loads features.py from the dir given (subprocess per copy).
  E1  clean root (today/<d> only): old and patched frames identical (columns, dtypes, order, values)
  E2  polluted root (all today files): patched frame == old frame on the clean root
  H2  synthetic root: a today row whose id is already in a labelled day is dropped by the patched build only
  H3  add_history on a synthetic frame: an unlabelled (NaN-vote) row never enters a hunter's history (patched), but does in the old copy
usage (VM, cwd ~/w/experiments/ph_predict): python3 test_equiv_hunks.py <old features dir> <new features dir> <real data dir> <d> <scratch dir>"""
import json, os, shutil, subprocess, sys
OLD, NEW, REAL, d, T = sys.argv[1:6]; REAL = os.path.realpath(REAL); os.makedirs(T, exist_ok=True)


def root(name, today_files, days_files=None, edit=None):
    r = f"{T}/{name}"; shutil.rmtree(r, ignore_errors=True); os.makedirs(f"{r}/days"); os.makedirs(f"{r}/today")
    for e in os.listdir(REAL):
        if e not in ("days", "today") and not e.startswith("build_cache"): os.symlink(os.path.realpath(f"{REAL}/{e}"), f"{r}/{e}")
    for fn in (days_files if days_files is not None else os.listdir(f"{REAL}/days")): os.symlink(os.path.realpath(f"{REAL}/days/{fn}"), f"{r}/days/{fn}")
    for fn in today_files: os.symlink(os.path.realpath(f"{REAL}/today/{fn}"), f"{r}/today/{fn}")
    if edit: edit(r)
    return r


def frame(fdir, r, inc, out):
    code = ("import sys, features as F; F.D = sys.argv[1]; inc = sys.argv[2]; inc = True if inc == 'True' else inc\n"
            "df = F.build(include_today=inc); df.to_pickle(sys.argv[3]); print(F.__file__)")
    p = subprocess.run([sys.executable, "-c", code, r, inc, out], env={**os.environ, "PYTHONPATH": f"{fdir}:."}, capture_output=True, text=True)
    assert p.returncode == 0, p.stderr[-800:]; assert p.stdout.strip().startswith(fdir), (fdir, p.stdout)
    import pandas as pd; return pd.read_pickle(out)


import pandas as pd, numpy as np
def same(a, b):
    a, b = a.reset_index(drop=True), b.reset_index(drop=True)
    if list(a.columns) != list(b.columns) or list(a.dtypes.astype(str)) != list(b.dtypes.astype(str)) or len(a) != len(b): return False
    return all(a[c].astype(str).equals(b[c].astype(str)) for c in a.columns)   # list / NaN-safe comparison


R = {}; tf = sorted(os.listdir(f"{REAL}/today"))
rc = root("clean", [f"{d}.json"]); rp = root("polluted", [f for f in tf if f[:10] <= d])
o_c, n_c, n_p = frame(OLD, rc, "True", f"{T}/o_c.pkl"), frame(NEW, rc, "True", f"{T}/n_c.pkl"), frame(NEW, rp, "True", f"{T}/n_p.pkl")
R["E1_clean_root_old_eq_new"] = same(o_c, n_c); R["E2_new_polluted_eq_old_clean"] = same(n_p, o_c)
n_s = frame(NEW, rp, d, f"{T}/n_s.pkl"); R["E3_date_string_eq_true"] = same(n_s, n_p)
# H2: today/<d2> = a copy of the newest labelled day's posts re-dated, with its first post's id set to an id from an earlier labelled day
days = sorted(os.listdir(f"{REAL}/days")); src_day, dup_day = days[-1], days[-3]; d2 = "2099-01-01"
def edit(r):
    posts = json.load(open(f"{REAL}/days/{src_day}")); dup = json.load(open(f"{REAL}/days/{dup_day}"))[0]["id"]
    posts[0]["id"] = dup; json.dump(posts, open(f"{r}/today/{d2}.json", "w")); R["_h2_posts"] = len(posts); R["_h2_dup_id_from"] = dup_day[:10]
    return dup
rh = root("h2", [], days[-5:-1], None); dup = edit(rh)
o_h, n_h = frame(OLD, rh, "True", f"{T}/o_h.pkl"), frame(NEW, rh, "True", f"{T}/n_h.pkl")
R["H2_old_today_rows"] = int(o_h.is_today.sum()); R["H2_new_today_rows"] = int(n_h.is_today.sum())
R["H2_pass"] = R["H2_new_today_rows"] == R["_h2_posts"] - 1 and R["H2_old_today_rows"] == R["_h2_posts"] and int((n_h.id.astype(str) == str(dup)).sum()) == 1
# H3: add_history directly on a synthetic frame
code3 = ("import numpy as np, pandas as pd, features as F, json\n"
         "X = pd.DataFrame({'id': ['a','b','c','x1','x2','x3'], 'day': ['2026-01-01','2026-01-02','2026-01-03']*2, 'votes': [100, np.nan, 50, 10, 10, 10],\n"
         " 'dailyRank': [1, np.nan, 2, 5, 6, 7], 'hunter_id': ['h','h','h','o','o','o'], 'maker_ids': [['m'],['m'],['m'],['q'],['q'],['q']], 'is_today': [False]*6})\n"
         "H = F.add_history(X).set_index('id'); print(json.dumps({'n': int(H.loc['c','hist_hunter_n']), 'rel_finite': bool(np.isfinite(H.loc['c','hist_hunter_rel'])), 'maker_n': int(H.loc['c','hist_maker_n'])}))")
for nm, fdir in (("old", OLD), ("new", NEW)):
    p = subprocess.run([sys.executable, "-c", code3], env={**os.environ, "PYTHONPATH": f"{fdir}:."}, capture_output=True, text=True); R[f"H3_{nm}"] = json.loads(p.stdout.strip().splitlines()[-1])
R["H3_pass"] = R["H3_new"] == {"n": 1, "rel_finite": True, "maker_n": 1} and R["H3_old"]["n"] == 2
for r in ("clean", "polluted", "h2"): shutil.rmtree(f"{T}/{r}", ignore_errors=True)
for f in ("o_c", "n_c", "n_p", "n_s", "o_h", "n_h"): os.remove(f"{T}/{f}.pkl")
ok = R["E1_clean_root_old_eq_new"] and R["E2_new_polluted_eq_old_clean"] and R["E3_date_string_eq_true"] and R["H2_pass"] and R["H3_pass"]
print(json.dumps(R)); print("PASS" if ok else "FAIL"); sys.exit(0 if ok else 1)
