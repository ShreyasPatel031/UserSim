"""Front-page entry of young posts (Nov 4): HN holds back young, low-point posts more than its score formula implies.
On Quality News training series (Jul 14 - Sep 30), young posts (< 6 h) that the formula ranks in the top 30 against the
slot's front page are actually there 41% of the time at < 15 min (58% after 1-2 h), and only 9% with <= 3 points.
Fit a multiplier on the HN score by (points, age): median over observations of log(effective score at the observed rank
/ formula score), off-front observations censored at half the rank-90 score. Applied in the simulators as
score * exp(m(points, age)) before ranking (frontsim.young_mult).
    HNCACHE=... python fit_young.py -> young_pen.json"""
import json, os, pickle
import numpy as np, pandas as pd
import frontsim as F

PB = [0, 2, 3, 5, 10, 20, 1e9]          # points bins (upper edges)
AB = [0, 0.25, 0.5, 1, 2, 4, 6]         # age bins in hours (beyond 6 h: no penalty)


def main():
    import __main__; __main__.Model = F.Model
    Mo = pickle.load(open(os.path.join(F.CACHE, "frontsim_model.pkl"), "rb"))
    s = F.load_stories(); qn, RK, EX, UP = F.load_qn()
    born = qn.post_id.map(s.set_index("post_id").created_at_i).to_numpy(float); day = qn.post_id.map(s.set_index("post_id").day)
    tr = ((day >= "2026-07-14") & (day <= "2026-09-30")).to_numpy()
    f0 = qn.qn_f0.to_numpy(float); t = f0[:, None] + 600 * np.arange(F.NB)[None, :]
    age = (t - born[:, None]) / 3600
    raw = np.clip(UP - 1, 0, None) ** 0.8 / (np.clip(age, 0, None) + 2) ** 1.8
    slot = np.clip(((t - Mo.T0) // 600).astype(int), 0, len(Mo.ISO) - 1)
    m = tr[:, None] & (age > 0) & (age < AB[-1]) & np.isfinite(Mo.ISO[slot, 0]) & ~np.isnan(UP) & (raw > 0)
    ii, kk = np.nonzero(m)
    cur = Mo.ISO[slot[ii, kk]]
    obs = np.where(np.isnan(RK[ii, kk]), 91, RK[ii, kk]).astype(int)
    eff = np.where(obs <= 90, cur[np.arange(len(obs)), np.clip(obs, 1, 90) - 1], 0.5 * cur[:, 89])
    D = pd.DataFrame({"pb": np.searchsorted(PB, UP[ii, kk], side="left"), "ab": np.searchsorted(AB, age[ii, kk], side="left"),
                      "lr": np.log(np.clip(eff, 1e-6, None)) - np.log(raw[ii, kk])})
    tab = D.groupby(["pb", "ab"]).lr.median().unstack()
    n = D.groupby(["pb", "ab"]).size().unstack()
    out = {"points_upper_edges": PB[1:], "age_upper_edges_h": AB[1:], "log_mult": [[None if pd.isna(tab.get(a, {}).get(p)) else round(float(tab.loc[p, a]), 3)
                                                                               for a in range(1, len(AB))] for p in range(1, len(PB))],
           "n": [[int(n.loc[p, a]) if (p in n.index and a in n.columns and not pd.isna(n.loc[p, a])) else 0 for a in range(1, len(AB))] for p in range(1, len(PB))],
           "fit": "Quality News training series Jul 14 - Sep 30 2026, ages < 6 h"}
    json.dump(out, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "young_pen.json"), "w"), indent=1)
    print(pd.DataFrame(out["log_mult"], index=[f"pts<={x}" for x in PB[1:]], columns=[f"age<={x}h" for x in AB[1:]]).round(2))
    print(pd.DataFrame(out["n"], index=[f"pts<={x}" for x in PB[1:]], columns=[f"age<={x}h" for x in AB[1:]]))


if __name__ == "__main__":
    main()
