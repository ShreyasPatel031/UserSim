"""Scratch dry run of the 00:05 path with the installed features.py (read-only on live data). Counts only.
Day = the newest data/today/ file (what tonight's build will see once today.py has written tonight's line-up). Scratch roots under <scratch>.
Checks: the 2026 build (forecast.py's frame) and arm 2 (arm2_live/h25_live.predict on a scratch H25_DATA root) each give exactly the day's
line-up rows, no stale today rows, hunters with labelled history all get a finite hist_hunter_rel, and arm 2 scores every launch.
usage (VM, cwd ~/w/experiments/ph_predict, PYTHONPATH unset): python3 dryrun_tonight.py <scratch dir>"""
import json, os, shutil, sys
sys.path.insert(0, os.path.expanduser("~/w/arm2_live"))
import features as F
T = sys.argv[1]; REAL = os.path.realpath(F.D); H25 = os.path.expanduser("~/w/h25/data")
d = max(f[:10] for f in os.listdir(f"{REAL}/today")); fails = []
df = F.build(include_today=True); te = df[df.is_today]
seen = set(df.hunter_id[~df.is_today & df.votes.notna()])
out = {"features": os.path.realpath(F.__file__), "day": d, "today_rows": len(te), "today_days": sorted(set(te.day)),
       "rel_nan_with_history": int((te.hunter_id.isin(seen) & te.hist_hunter_rel.isna()).sum())}
if set(te.day) != {d}: fails.append("2026 build: today rows not only the newest day")
if out["rel_nan_with_history"]: fails.append("2026 build: hist_hunter_rel NaN for hunters with history")
r = f"{T}/h25_dry"; shutil.rmtree(r, ignore_errors=True); os.makedirs(f"{r}/days")   # scratch root of symlinks (h25_live links into it)
for e in os.listdir(H25):
    if e == "days":
        for fn in os.listdir(f"{H25}/days"): os.symlink(os.path.realpath(f"{H25}/days/{fn}"), f"{r}/days/{fn}")
    elif not e.startswith("build_cache"): os.symlink(os.path.realpath(f"{H25}/{e}"), f"{r}/{e}")
os.environ["H25_DATA"] = r
import h25_live
PA, info = h25_live.predict(d)
out.update({"arm2_rows": len(PA), "arm2_nan": int(PA.pred_arm2.isna().sum()), "arm2_info": info})
if len(PA) != len(te) or out["arm2_nan"]: fails.append("arm 2: not every launch scored")
shutil.rmtree(r, ignore_errors=True)
print(json.dumps(out)); print("DRY RUN PASS" if not fails else "DRY RUN FAIL: " + "; ".join(fails)); sys.exit(1 if fails else 0)
