import json, glob, collections
import numpy as np
agg = collections.defaultdict(lambda: collections.defaultdict(list))
for f in sorted(glob.glob("data/days/*.json")):
    d = f.split("/")[-1][:10]
    if d < "2026-03-01": continue
    for p in json.load(open(f)):
        r = p.get("dailyRank")
        if r is None: continue
        g = "1" if r == 1 else "2-3" if r <= 3 else "4-10" if r <= 10 else "11+"
        mk = p.get("makers") or []
        agg[g]["n_makers"].append(len(mk))
        agg[g]["any_maker"].append(float(len(mk) > 0))
        if mk:
            agg[g]["share_createdAt"].append(np.mean([bool(m.get("createdAt")) for m in mk]))
            agg[g]["share_twitter"].append(np.mean([bool(m.get("twitterUsername")) for m in mk]))
            agg[g]["n_keys"].append(np.mean([len([k for k, v in m.items() if v not in (None, "", [])]) for m in mk]))
        agg[g]["redacted_maker"].append(float(any(str(m.get("username", "")).startswith("[") or m.get("id") in (None, "0") for m in mk)))
for g in ("1", "2-3", "4-10", "11+"):
    print(g, {k: round(float(np.mean(v)), 3) for k, v in agg[g].items()}, len(agg[g]["n_makers"]))
ex = json.load(open(sorted(glob.glob("data/days/2026-06-1*.json"))[0]))
for p in sorted(ex, key=lambda p: p.get("dailyRank") or 99)[:4]:
    print(p.get("dailyRank"), [sorted(k for k, v in m.items() if v not in (None, "", [])) for m in (p.get("makers") or [])[:2]])
