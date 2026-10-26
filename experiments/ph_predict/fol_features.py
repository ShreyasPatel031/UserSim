"""fol_: the poster's and builders' audience inside our ~19k sampled Product Hunt people (who follows them; lists read
Oct 25, so not dated), and how busy the poster is (launches they post the same day / last 7 days).
Output: data/fol_features.json"""
import glob, gzip, json, os
from collections import Counter
import numpy as np, pandas as pd

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def main():
    fol = Counter()
    for l in gzip.open(f"{D}/ph_following.jsonl.gz", "rt"):
        for u, _ in json.loads(l).get("following") or []:
            fol[u] += 1
    rows = []
    for fn in sorted(glob.glob(f"{D}/days/*.json")):
        day = os.path.basename(fn)[:10]
        for p in json.load(open(fn)):
            rows.append({"id": p["id"], "day": day, "hunter": (p.get("user") or {}).get("username"),
                         "makers": [m["username"] for m in p.get("makers") or []]})
    L = pd.DataFrame(rows)
    L["d"] = pd.to_datetime(L.day)
    same = L.groupby(["hunter", "day"]).id.transform("count")
    out = {}
    for r, s in zip(L.itertuples(), same):
        prev = L[(L.hunter == r.hunter) & (L.d < r.d) & (L.d >= r.d - pd.Timedelta(days=7))] if r.hunter else []
        mf = [fol[m] for m in r.makers if m != r.hunter]
        out[r.id] = {"fol_hunter": float(np.log1p(fol[r.hunter])), "fol_team": float(np.log1p(sum(mf))),
                     "fol_team_max": float(np.log1p(max(mf, default=0))),
                     "busy_same_day": int(s), "busy_7d": int(len(prev))}
    json.dump(out, open(f"{D}/fol_features.json", "w"))
    print(len(out), pd.DataFrame(out.values()).describe().T[["mean", "50%", "max"]].round(2))


if __name__ == "__main__":
    main()
