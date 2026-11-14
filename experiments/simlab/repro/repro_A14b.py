"""Repro A14b (orchestrator 16:35Z Nov 14): edge cases of PH ops' today-rows fix (features.py 033d7bd7) vs current (981c5ded).
 (i)  tonight's today/<D>.json MISSING, older today files present: (a) days/ holds D-1 (normal after close), (b) days/ lacks D-1.
      Report which day the "today" rows carry; PASS only if no row is presented as today's line-up for a day other than D, i.e. the
      build yields either no is_today rows or only day-D rows (never yesterday's line-up as today's).
 (ii) today/<D>.json present AND days/ already holds D (re-run after labels): report today-row count (expected 0: skipped).
 (iii) clean root (today/ = only today/D.json): frame from old vs new features.py identical (all columns, NaN-equal).
    python repro_A14b.py <dir with ph_predict modules (old features.py)> <new features.py> <real data dir> <day D> <scratch dir>"""
import sys, os, glob, json, shutil, importlib.util
CODE, NEWF, REAL, D, TMP = sys.argv[1:6]
sys.path.insert(0, CODE); os.chdir(CODE)
import numpy as np, pandas as pd
def mod(path, name):
    s = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
OLD = mod(os.path.join(CODE, "features.py"), "features_old"); NEW = mod(NEWF, "features_new")
prev = (pd.Timestamp(D) - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
def root(name, days_lt, days_incl, todays):
    r = os.path.join(TMP, name); shutil.rmtree(r, ignore_errors=True); os.makedirs(f"{r}/days"); os.makedirs(f"{r}/today")
    for e in os.listdir(REAL):
        if e not in ("days", "today") and not e.startswith("build_cache"): os.symlink(f"{REAL}/{e}", f"{r}/{e}")
    for fn in glob.glob(f"{REAL}/days/*.json"):
        b = os.path.basename(fn)[:10]
        if b < days_lt or b in days_incl: os.symlink(fn, f"{r}/days/{os.path.basename(fn)}")
    for b in todays:
        if os.path.exists(f"{REAL}/today/{b}.json"): os.symlink(f"{REAL}/today/{b}.json", f"{r}/today/{b}.json")
    return r
def build(M, r):
    M.D = r
    try:
        df = M.build(include_today=True); t = df[df.is_today]
        return {"today rows": int(len(t)), "today days": sorted(t.day.unique().tolist())}, df
    except Exception as e:
        return {"error": f"{type(e).__name__}: {str(e)[:160]}"}, None
older = sorted(os.path.basename(f)[:10] for f in glob.glob(f"{REAL}/today/*.json") if os.path.basename(f)[:10] < D)
res = {}
for tag, days_lt in (("(i-a) D missing, days/ holds D-1", D), ("(i-b) D missing, days/ lacks D-1", prev)):
    r = root(tag[:4].strip("()").replace("-", "") + "x", days_lt, [], older)
    o, _ = build(OLD, r); n, _ = build(NEW, r)
    ok = ("error" in n) or n["today rows"] == 0 or n["today days"] == [D]
    res[tag] = {"old": o, "new": n, "PASS (never yesterday's line-up as today's)": ok}
r = root("rerun", D, [D], [D]); o, _ = build(OLD, r); n, _ = build(NEW, r)
res["(ii) today/D present and days/ holds D"] = {"old": o, "new": n}
r = root("cleanroot", D, [], [D]); o, dfo = build(OLD, r); n, dfn = build(NEW, r)
same = dfo is not None and dfn is not None and list(dfo.columns) == list(dfn.columns) and len(dfo) == len(dfn)
if same:
    a, b = dfo.reset_index(drop=True), dfn.reset_index(drop=True); badc = []
    for c in a.columns:
        x, y = a[c], b[c]
        try: eq = bool(((x == y) | (x.isna() & y.isna())).all())
        except Exception: eq = x.astype(str).equals(y.astype(str))
        if not eq: badc.append(c)
    same = not badc; res["(iii) clean root: columns differing old vs new"] = badc
res["(iii) clean root identical frame old vs new"] = same
print(json.dumps(res, default=str))
