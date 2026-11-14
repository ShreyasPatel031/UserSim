"""Test for the today-rows fix (fails on features.py 981c5ded, passes on the patched copy). Counts only, read-only.
Builds the live frame exactly as forecast.py / h25_live do (include_today=True) on a data root whose today/ holds every stale file, and checks:
  1. the only today rows are the target day's (no unlabelled rows for days < d);
  2. every test-day launch whose hunter has a labelled earlier launch gets a finite hist_hunter_rel;
  3. ph_hunter_n_same_day on labelled rows equals the count from days/ alone.
usage (VM, cwd ~/w/experiments/ph_predict): PYTHONPATH=<features dir>:. python3 test_today_rows.py <data root> <d>"""
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
print("FAIL\n  " + "\n  ".join(fails) if fails else "PASS"); sys.exit(1 if fails else 0)
