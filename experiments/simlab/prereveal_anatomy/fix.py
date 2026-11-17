"""Pre-registered fix test (PREREG_fix.md, 6167a3bc): pin hidden top 3 instead of top 5; ridge (LODO) for the rest. Paired, same 14 days."""
import json, sys, numpy as np, pandas as pd
from sklearn.linear_model import Ridge
SP = sys.argv[1]; OUT = f"{SP}/pra/out"; D = pd.read_parquet(f"{OUT}/launch_rows.parquet"); FE = ["z_lpos", "z_move", "z_nc_rec", "z_clean"]; rng = np.random.default_rng(0)
days = sorted(D.day.unique()); res = {}; ords = {}
for d in days:
    tr = D[D.day != d]; m = Ridge(alpha=1.0).fit(tr[FE], tr.y); g = D[D.day == d].assign(s=lambda x: m.predict(x[FE])); truth = set
    for pin in (5, 3, 0):
        h = list(g.sort_values("pos").id[:pin]); rest = list(g[~g.id.isin(h)].sort_values("s", ascending=False).id); o = h + rest; ords[(d, pin)] = o
        res.setdefault(pin, {})[d] = [len(set(o[:k]) & set(g[g.final <= k].id)) / k * 100 for k in (3, 5, 10)]
    ords[(d, "hidden")] = list(g.sort_values("pos").id); res.setdefault("hidden", {})[d] = [len(set(ords[(d, "hidden")][:k]) & set(g[g.final <= k].id)) / k * 100 for k in (3, 5, 10)]
def ci(v, signed=False):
    v = np.asarray(v, float); b = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(2000)]; f = "+.1f" if signed else ".1f"
    return f"{v.mean():{f}} [{np.percentile(b, 2.5):{f}}, {np.percentile(b, 97.5):{f}}]"
O = {"days": len(days), "lines": {}, "paired_vs_published": {}}
for k, nm in ((5, "published: hidden top 5 pinned, ridge 6+"), (3, "FIX: hidden top 3 pinned, ridge 4+"), (0, "ridge for all slots (reference, not pre-registered)"), ("hidden", "hidden order alone (reference)")):
    A = np.array([res[k][d] for d in days]); O["lines"][nm] = {f"top{t}": ci(A[:, j]) for j, t in enumerate((3, 5, 10))}
base = np.array([res[5][d] for d in days])
for k, nm in ((3, "FIX minus published"), (0, "ridge-all minus published"), ("hidden", "hidden alone minus published")):
    A = np.array([res[k][d] for d in days]); O["paired_vs_published"][nm] = {f"top{t}": ci(A[:, j] - base[:, j], True) for j, t in enumerate((3, 5, 10))}
F = np.array([res[3][d] for d in days]); O["per_day_top10"] = {d: {"published": base[i, 2], "fix": F[i, 2]} for i, d in enumerate(days)}
O["days_fix_better_same_worse_top10"] = [int((F[:, 2] > base[:, 2]).sum()), int((F[:, 2] == base[:, 2]).sum()), int((F[:, 2] < base[:, 2]).sum())]
d_ = F[:, 2] - base[:, 2]; O["adopt"] = bool(np.percentile([d_[rng.integers(0, len(d_), len(d_))].mean() for _ in range(2000)], 2.5) > 0 and (F[:, 1] - base[:, 1]).mean() >= -2)
m = Ridge(alpha=1.0).fit(D[FE], D.y); O["ridge_weights_all_days"] = dict(zip(FE, np.round(m.coef_, 4))); O["ridge_intercept"] = round(float(m.intercept_), 4)
json.dump(O, open(f"{OUT}/fix_result.json", "w"), indent=1); print(json.dumps(O, indent=1))
