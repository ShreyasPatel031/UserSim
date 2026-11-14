"""Score nmakers_frozen.py: paired (frozen 00:05 - stored) top 3/5/10 on truth_daily.json (>= 10 ranked; unranked = misses),
day bootstrap 95% (4000). Days restricted to nights with a 00:05 read."""
import json, os, subprocess, sys
import numpy as np, pandas as pd
R = lambda p: os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", p)
P = pd.read_parquet(sys.argv[1] if len(sys.argv) > 1 else R("nmakers_frozen_preds.parquet")); P["id"] = P.id.astype(str)
T = json.loads(subprocess.run(["gsutil", "cat", "gs://usersim-bakeoff-347838016394/usersim_sim/results/web/truth_daily.json"], capture_output=True, text=True, check=True).stdout)["days"]
H, Dd = [], []
for d, g in P.groupby("day"):
    t = {str(i): r for i, r in T.get(d, {}).get("ranks", {}).items()}
    if len(t) < 10 or not g.has_0005.any(): continue
    H.append([[len(set(g.sort_values([c, "id"], ascending=[False, True]).id[:k]) & {i for i, r in t.items() if r <= k}) / k * 100 for k in (3, 5, 10)] for c in ("stored", "frozen")]); Dd.append(d)
H = np.array(H); D = H[:, 1] - H[:, 0]; rng = np.random.default_rng(0); n = len(H)
bs = np.array([D[rng.integers(0, n, n)].mean(0) for _ in range(4000)])
out = {"n_days": n, "days": Dd, "launches": int(len(P)), "with_0005": int(P.has_0005.sum()), "n_changed": int((P.n_stored != P.n_0005).sum()),
       "stored": H[:, 0].mean(0).round(1).tolist(), "frozen": H[:, 1].mean(0).round(1).tolist(), "diff": D.mean(0).round(1).tolist(),
       "ci_lo": np.percentile(bs, 2.5, 0).round(1).tolist(), "ci_hi": np.percentile(bs, 97.5, 0).round(1).tolist(),
       "per_day": {d: {"stored": H[i, 0].tolist(), "frozen": H[i, 1].tolist()} for i, d in enumerate(Dd)}}
print(json.dumps({k: v for k, v in out.items() if k not in ("per_day", "days")}, indent=1))
json.dump(out, open(R("nmakers_frozen.json"), "w"), indent=1)
