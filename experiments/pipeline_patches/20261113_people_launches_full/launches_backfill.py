"""Bundle 10 one-off: add the new launch columns to every stored launch. Existing columns are taken from the warehouse as they
are now (so fix_launch_days.py's day corrections and settled ranks are kept); only the NEW columns come from the launch's
data/days/<d>.json record (pipeline.daily.launch_extra). Launches with no day-file record are left as they are. Counts only.
usage (VM, from experiments/): python3 -m pipeline.launches_backfill [--write]"""
import glob, json, os, sys
import pandas as pd
from . import daily as D, warehouse as W


def main(argv):
    ex = {}
    for f in sorted(glob.glob(f"{D.RAW}/days/*.json")):
        for p in json.load(open(f)):
            ex[str(p["id"])] = D.launch_extra(p)
    L = W.query("SELECT * FROM launches"); L["id"] = L.id.astype(str)
    L = L.drop(columns=[c for c in L.columns if c == "updated_at" or (ex and c in next(iter(ex.values())))])
    X = pd.DataFrame.from_dict(ex, orient="index"); X.index.name = "id"
    out = L.merge(X.reset_index(), on="id", how="inner")
    st = {"launches": int(len(L)), "with_day_record": int(len(out)), "cols_after": int(len(out.columns)) + 1, "write": "--write" in argv}
    if "--write" in argv and len(out):
        for i in range(0, len(out), 20000):
            W.write("launches", out.iloc[i:i + 20000])
    print(json.dumps(st)); return st


if __name__ == "__main__":
    main(sys.argv[1:])
