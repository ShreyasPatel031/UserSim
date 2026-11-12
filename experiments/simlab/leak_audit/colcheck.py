import sys, json, os
os.environ["HONEST"] = "0"
import numpy as np, pandas as pd
sys.path.insert(0, ".")
import model as M
from buildcache import build_cached
from honest import honest_cols
df = build_cached(); df = df[~df.known].copy(); df["id"] = df.id.astype(str)
cols = M.cols(df, M.LIVE_SOURCES + M.PAGE_SOURCES); hc = honest_cols(cols)
src = pd.Series([c.split("_")[0] for c in hc]).value_counts()
print("honest cols", len(hc), "by source", src.to_dict())
page = [c for c in hc if c.startswith(("llm_", "ps_", "pf_", "vs_"))]
print("llm/page cols", len(page), [c for c in page if c.startswith("llm_")], sorted({c.split("_")[0] for c in page}))
D = df[df.dailyRank.notna() & (df.day >= "2026-03-01")]
res = {}
for c in page:
    w = t3 = n = 0; cov = D[c].notna().mean()
    for d, g in D.groupby("day"):
        g = g[g[c].notna()]
        if len(g) < 5 or g.dailyRank.min() != 1: continue
        g = g.sample(frac=1, random_state=0); top = g.loc[(g[c] + np.random.default_rng(0).random(len(g)) * 1e-9).idxmax()] if g[c].nunique() > 2 else g.iloc[int(g[c].values.argmax())]; w += top.dailyRank == 1; t3 += top.dailyRank <= 3; n += 1
    res[c] = (round(100 * w / max(n, 1), 1), round(100 * t3 / max(n, 1), 1), n, round(float(cov), 2))
R = pd.DataFrame(res, index=["argmax_is_winner_pct", "argmax_top3_pct", "days", "coverage"]).T.sort_values("argmax_is_winner_pct", ascending=False)
print(R.head(15).to_string())
print("chance winner ~", round(100 * float((1 / D.groupby("day").size()).mean()), 1))
for c in [x for x in page if x.startswith("llm_")]:
    print(c, "spearman with -rank (within day mean)", round(float(D.groupby("day").apply(lambda g: g[c].rank().corr(-g.dailyRank.rank())).mean()), 3))

print("binary/ties: P(winner has value 1) vs P(rest), for top binary pf/ps/vs:")
for c in page:
    if D[c].dropna().isin([0,1]).all():
        a=D.loc[D.dailyRank==1,c].mean(); b=D.loc[D.dailyRank>3,c].mean()
        if abs(a-b)>0.15: print(c, round(a,2), round(b,2))
