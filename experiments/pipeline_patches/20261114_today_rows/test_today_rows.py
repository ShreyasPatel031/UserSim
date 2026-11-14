"""Test for the today-rows fix (fails on features.py 981c5ded, passes on the patched copy). Counts only, read-only.
Builds the live frame exactly as forecast.py / h25_live do (include_today=True) on a data root whose today/ holds every stale file, and checks:
  1. the only today rows are the target day's (no unlabelled rows for days < d);
  2. every test-day launch whose hunter has a labelled earlier launch gets a finite hist_hunter_rel;
  3. ph_hunter_n_same_day on labelled rows equals the count from days/ alone.
usage (VM, cwd ~/w/experiments/ph_predict): PYTHONPATH=<features dir>:. python3 test_today_rows.py <data root> <d> [<d2 with no today file>]"""
import os, sys
import numpy as np, pandas as pd
import features as F
F.D = sys.argv[1]; d = sys.argv[2]; print("features from", os.path.realpath(F.__file__))
df = F.build(include_today=True); lab = df[~df.is_today]
fails = []
stale = df[df.is_today & (df.day != d)]
if len(stale): fails.append(f"1: {len(stale)} today rows for days other than {d}")
te = df[df.is_today & (df.day == d)]; seen = set(lab.hunter_id[lab.votes.notna()])
bad = te[te.hunter_id.isin(seen) & te.hist_hunter_rel.isna()]
if len(bad): fails.append(f"2: {len(bad)} of {int(te.hunter_id.isin(seen).sum())} test launches with hunter history have hist_hunter_rel NaN")
ref = lab.groupby(["day", "hunter_id"]).id.transform("count")
nd = int((lab.ph_hunter_n_same_day != ref).sum())
if nd: fails.append(f"3: {nd} labelled rows with a same-day hunter count above the days/ count")
print({"today_rows": int(df.is_today.sum()), "test_rows": len(te), "labelled_nan_votes": int(lab.votes.isna().sum())})
print("FAIL\n  " + "\n  ".join(fails) if fails else "PASS")
if fails or len(sys.argv) <= 3: sys.exit(1 if fails else 0)
# 4. missing line-up (orchestrator 16:35Z): with no today/<d2>.json, an explicit-day build has no today rows (callers' empty-test-set path),
#    and the newest-file build never labels another day's line-up as <d2> (rows keep their own file date)
if len(sys.argv) > 3:
    d2 = sys.argv[3]; x = F.build(include_today=d2); y = F.build(include_today=True)
    r4 = {"explicit_today_rows": int(x.is_today.sum()), "newest_rows_dated_d2": int((y.is_today & (y.day == d2)).sum()), "newest_file_day": sorted(set(y.day[y.is_today]))}
    print(r4); ok4 = r4["explicit_today_rows"] == 0 and r4["newest_rows_dated_d2"] == 0
    print("PASS 4" if ok4 else "FAIL 4"); sys.exit(0 if ok4 else 1)
