"""Is the per-launch shock inside our pool or outside it? (orchestrator, Nov 3, 19:50 UTC). Data we hold, no fetch.
Per launch, Jul–Oct (WIN), honest live set (HONEST_PREDS, column HONEST_COL):
  shock       = (log real votes − honest prediction), minus its day mean (within-day shock)
  pool_votes  = upvotes on the launch by people in our store (dated to the launch day), a lower bound: upvote
                histories are incomplete
  pool_share  = pool_votes / real votes
1. within-day Spearman of shock vs pool share, bootstrap over days (10,000); pooled too
2. the same for log1p(pool_votes) (day-demeaned), and the share of within-day shock variance explained by pool
   turnout (R² of a within-day regression of shock on day-demeaned log1p(pool_votes))
3. pool share by final daily rank bucket (1–3, 4–10, 11+) and by month, with n and bootstrap CIs
Caveat: pool people were largely found through comments on these launches, so pool share is partly made by how the
pool was built (selection), not only by who turned up.
usage: SIMLAB_DATA=data_v2 HONEST_PREDS=... python shock_pool.py -> results/shock_pool.json"""
import json, os, sys
import numpy as np, pandas as pd
from scipy.stats import spearmanr
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from simlab import store
import userbase_eval as UE

WIN = os.environ.get("WIN", "2026-07")


def boot_days(A, f, rng, n=10000):
    days = A.day.unique(); byd = {d: g for d, g in A.groupby("day")}
    est = f(A); bs = []
    for _ in range(n):
        S = pd.concat([byd[d] for d in rng.choice(days, len(days))])
        bs.append(f(S))
    bs = np.array([b for b in bs if b is not None and not np.isnan(b)])
    return [round(float(est), 4), [round(float(x), 4) for x in np.percentile(bs, [2.5, 97.5])], int(len(days))]


def main():
    rng = np.random.default_rng(0)
    os.environ.setdefault("HONEST_COL", "honest - live set")
    H = UE.honest()
    H = H[H.day >= WIN].copy()
    P, I, E = store.load()
    UE.need(E, ["person", "item", "kind"], "store events")
    U = E[E.kind == "upvote"].assign(item=lambda x: x["item"].astype(str))
    pv = U.groupby("item").person.nunique()
    H["real"] = np.expm1(H.logv).clip(lower=1)
    H["pool_votes"] = H.id.map(pv).fillna(0)
    H["pool_share"] = (H.pool_votes / H.real).clip(upper=1)
    H["shock"] = (H.logv - H.honest); H["shock"] -= H.groupby("day").shock.transform("mean")
    H["lpv"] = np.log1p(H.pool_votes); H["lpv_d"] = H.lpv - H.groupby("day").lpv.transform("mean")
    A = H[H.groupby("day").id.transform("size") >= 5]

    def wd(col):
        def f(S):
            r = [spearmanr(g[col], g.shock).correlation for _, g in S.groupby("day") if g[col].nunique() > 1]
            return float(np.nanmean(r)) if r else np.nan
        return f
    pooled = lambda col: (lambda S: spearmanr(S[col] - S.groupby("day")[col].transform("mean"), S.shock).correlation)
    def r2(S):
        x, y = S.lpv_d.values, S.shock.values
        b = (x @ y) / (x @ x) if (x @ x) > 0 else 0.0
        return 1 - ((y - b * x) ** 2).sum() / (y ** 2).sum()
    res = {"window": f"{WIN} on", "reference": os.environ["HONEST_COL"], "launches": int(len(A)), "days": int(A.day.nunique()),
           "launches_with_any_pool_vote": int((A.pool_votes > 0).sum()),
           "pool_share_overall": {"mean": round(float(A.pool_share.mean()), 4), "median": round(float(A.pool_share.median()), 4)},
           "caveat": "pool people were largely found through comments on these launches (selection); pool votes are a lower bound"}
    res["1_shock_vs_pool_share"] = {"within_day": boot_days(A, wd("pool_share"), rng), "pooled": boot_days(A, pooled("pool_share"), rng)}
    res["2_shock_vs_pool_votes"] = {"within_day": boot_days(A, wd("lpv"), rng), "pooled": boot_days(A, pooled("lpv"), rng),
                                    "within_day_R2_of_shock_on_pool_turnout": boot_days(A, r2, rng, 2000)}
    A = A.assign(bucket=pd.cut(A.dailyRank, [0, 3, 10, 1e9], labels=["1-3", "4-10", "11+"]), mon=A.day.str[:7])
    def cell(S):
        v = S.pool_share.values
        bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(5000)] if len(v) > 1 else [v.mean()]
        return {"n": int(len(v)), "mean_pool_share": round(float(v.mean()), 4), "ci95": [round(float(x), 4) for x in np.percentile(bs, [2.5, 97.5])],
                "median_pool_votes": float(S.pool_votes.median()), "median_real_votes": float(S.real.median()),
                "mean_shock": round(float(S.shock.mean()), 3)}
    res["3_by_rank_bucket"] = {str(b): cell(g) for b, g in A.groupby("bucket", observed=True)}
    res["3_by_month"] = {m: cell(g) for m, g in A.groupby("mon")}
    res["3_by_month_and_bucket"] = {f"{m} {b}": cell(g) for (m, b), g in A.groupby(["mon", "bucket"], observed=True)}
    json.dump(res, open(os.environ.get("OUT", "results/shock_pool.json"), "w"), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
