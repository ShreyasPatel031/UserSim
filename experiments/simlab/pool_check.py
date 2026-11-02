"""Does a better simulated person give better pool-level votes? For every launch, the simulation's expected picks from the
pool (psn_ev: sum over people active in the 30 days before of weight x p; psn_fans: the same over the 100 most likely)
against the real number of pool people who upvoted or commented on it on launch day. Within
each day: Spearman correlation, and whether the simulation's top 3 by pool picks matches the real top 3 by pool votes.
Sources are popscore's per-day files (each month scored by a model trained on the previous month: out of sample).
Paired bootstrap over days against the first source.
usage: SIMLAB_DATA=data_v2 python -m simlab.pool_check popscore popscore_tie popscore_tie2 [...] -> reports/pool_check.json"""
import glob, json, os, sys
import numpy as np, pandas as pd
from scipy.stats import spearmanr
from . import store

HERE = os.path.dirname(os.path.abspath(__file__))


def main(dirs):
    P, I, E = store.load()
    day = dict(zip(I.id.astype(str), I.day))
    E = E.assign(item=E.item.astype(str))
    real = E[E.item.map(day) == E.date].groupby("item").person.nunique()
    per = {}
    for d in dirs:
        F = sorted(glob.glob(os.path.join(HERE, "cache", d, "day_*.parquet")))
        S = pd.concat([pd.read_parquet(f) for f in F]); S["id"] = S.id.astype(str)
        S["real"] = S.id.map(real).fillna(0)
        rows = {}
        for dy, g in S.groupby("day"):
            if len(g) < 5 or g.real.sum() == 0:
                continue
            top = set(g.nlargest(3, "real").id)
            rows[dy] = {m: (spearmanr(g[c], g.real).correlation, len(set(g.nlargest(3, c).id) & top) / 3)
                        for m, c in (("ev", "psn_ev"), ("fans", "psn_fans"))}
        per[d] = rows
    days = sorted(set.intersection(*[set(v) for v in per.values()]))
    res = {"days": len(days), "from": days[0], "to": days[-1], "sources": {}}
    rng = np.random.default_rng(0); base = dirs[0]
    for d in dirs:
        r = {}
        for m in ("ev", "fans"):
            corr = np.array([per[d][x][m][0] for x in days]); hit = np.array([per[d][x][m][1] for x in days])
            r[m] = {"spearman": round(float(np.nanmean(corr)), 3), "top3_hit": round(100 * float(hit.mean()), 1)}
            if d != base:
                dc = corr - np.array([per[base][x][m][0] for x in days]); dh = hit - np.array([per[base][x][m][1] for x in days])
                bc = [np.nanmean(dc[rng.integers(0, len(dc), len(dc))]) for _ in range(5000)]
                bh = [dh[rng.integers(0, len(dh), len(dh))].mean() for _ in range(5000)]
                r[m]["vs_" + base] = {"spearman": [round(float(np.nanmean(dc)), 3), [round(float(x), 3) for x in np.percentile(bc, [2.5, 97.5])]],
                                      "top3_hit": [round(100 * float(dh.mean()), 1), [round(100 * float(x), 1) for x in np.percentile(bh, [2.5, 97.5])]]}
        res["sources"][d] = r
    json.dump(res, open(os.path.join(HERE, "reports", "pool_check.json"), "w"), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:])
