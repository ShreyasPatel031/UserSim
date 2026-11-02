"""One-off repair: keep each launch in data/days only on its featuredAt Pacific day (collect_ph.on_day). 204 launches
created on day d but featured at 00:00 PT on d + 1 sat in both files (Apr 27/28, May 4/5, 6/7, 10/11, 13/14).
Originals are copied to data/days_backup_dedupe/ first. Prints what changed.
usage: python dedupe_days.py [--dry]"""
import datetime as dt, glob, json, os, shutil, sys
import collect_ph as C

dry = "--dry" in sys.argv
os.makedirs("data/days_backup_dedupe", exist_ok=True)
changed = []
for f in sorted(glob.glob("data/days/*.json")):
    d = dt.date.fromisoformat(os.path.basename(f)[:10]); L = json.load(open(f)); K = C.on_day(L, d)
    if len(K) != len(L):
        changed.append((f[-15:-5], len(L), len(K)))
        if not dry:
            shutil.copy(f, "data/days_backup_dedupe/" + os.path.basename(f))
            json.dump(K, open(f, "w"))
seen = {}
for f in sorted(glob.glob("data/days/*.json")):
    for p in json.load(open(f)):
        seen.setdefault(str(p["id"]), []).append(f[-15:-5])
print(json.dumps({"files_changed": changed, "launches_removed": sum(a - b for _, a, b in changed),
                  "ids_still_in_two_files": sum(len(v) > 1 for v in seen.values()), "dry": dry}))
