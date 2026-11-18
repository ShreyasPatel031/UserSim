import sys, os, json, glob; sys.path[:0] = ['..', '.']
import features as F, pandas as pd, numpy as np
vis = lambda mk: sum(1 for m in (mk or []) if str(m.get("id")) not in ("0", "", "None"))
rows = []
for fn in sorted(glob.glob(f"{F.D}/today/*.json")):
    d = os.path.basename(fn)[:10]; fd = f"{F.D}/days/{d}.json"
    if not os.path.exists(fd):
        continue
    t = {p["id"]: p for p in json.load(open(fn))}; f = {p["id"]: p for p in json.load(open(fd))}
    for i, p in t.items():
        if i in f:
            q = f[i]; rows.append(dict(day=d, v0=vis(p.get("makers")), n0=len(p.get("makers") or []), v1=vis(q.get("makers")), n1=len(q.get("makers") or []), rank=q.get("dailyRank")))
R = pd.DataFrame(rows); print("days", R.day.nunique(), "launches", len(R), R.day.min(), R.day.max())
print("total count same 00:05 vs final", round((R.n0 == R.n1).mean(), 3)); print("visible count same", round((R.v0 == R.v1).mean(), 3))
R["chg"] = R.v1 - R.v0; R["top"] = pd.cut(R["rank"], [0, 1, 3, 10, 1e9], labels=["#1", "2-3", "4-10", "11+"])
print(R.groupby("top", observed=True).agg(n=("chg", "size"), share_changed=("chg", lambda s: (s != 0).mean()), mean_chg=("chg", "mean"), v0=("v0", "mean"), v1=("v1", "mean")).round(2).to_string())
print("any visible at 00:05", round((R.v0 > 0).mean(), 3), "final", round((R.v1 > 0).mean(), 3))
# per file days in training (final reads): visible share by rank
D = [dict(rank=p.get("dailyRank"), v=vis(p.get("makers")), n=len(p.get("makers") or [])) for fn in glob.glob(f"{F.D}/days/2026-*.json") for p in json.load(open(fn))]
D = pd.DataFrame(D); D["top"] = pd.cut(D["rank"], [0, 1, 3, 10, 1e9], labels=["#1", "2-3", "4-10", "11+"])
print("final reads, all 2026:"); print(D.groupby("top", observed=True).agg(n=("v", "size"), any_visible=("v", lambda s: (s > 0).mean()), v=("v", "mean"), n_all=("n", "mean")).round(2).to_string())
