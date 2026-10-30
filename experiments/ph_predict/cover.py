import numpy as np, pandas as pd
from simlab import popscore as PS
from buildcache import build_cached
import sys
E = PS.load()["E"]; E["item"] = E.item.astype(str)
n = E[E.date >= "2026-04-01"].groupby("item").person.nunique().rename("pool_votes").reset_index().rename(columns={"item": "id"})
df = build_cached(); df["id"] = df.id.astype(str)
A = df[["id", "day", "logv", "dailyRank"]].merge(n, on="id", how="left").fillna({"pool_votes": 0})
A["votes"] = np.expm1(A.logv)
A = A[(A.day >= "2026-04-01") & (A.day <= "2026-10-24")]
print("launches", len(A), "share of real votes cast by pool people:", round(A.pool_votes.sum() / A.votes.sum(), 3))
for lo, hi in ((1, 3), (4, 10), (11, 50)):
    g = A[(A.dailyRank >= lo) & (A.dailyRank <= hi)]
    print(f"rank {lo}-{hi}: median pool share {g.pool_votes.div(g.votes).median():.3f}, median votes {g.votes.median():.0f}")
from scipy.stats import spearmanr
print("within-day corr(pool votes actually cast, real votes):", round(np.nanmean([spearmanr(g.pool_votes, g.votes).correlation for _, g in A.groupby("day") if len(g) >= 8]), 3))
top = lambda g, c: set(g.nlargest(3, c).id)
print("oracle: top-3 recall if we knew exactly which pool people vote:", round(100*np.mean([len(top(g, "pool_votes") & top(g, "votes"))/3 for _, g in A.groupby("day") if len(g) >= 8]), 1))
