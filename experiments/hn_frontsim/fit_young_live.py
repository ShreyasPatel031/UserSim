"""Selection check for the young-post entry penalty (orchestrator, Nov 4): the same table as fit_young.py, but measured
on the live hn_minute feed, which reads /newest and /news p1-p3 every minute for ALL posts (no Quality News 5+ point
selection). Per 10-minute slot: the real front page's HN scores by position (isotonic in position), each young post's
formula score, and its observed position (or off the front page). Days: full feed days only.
    HNCACHE=... HNMIN=... python fit_young_live.py -> young_pen_live.json"""
import json, os
import numpy as np, pandas as pd
from sklearn.isotonic import IsotonicRegression
import live_frontsim as LF
import fit_young as FY

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    M = LF.load_minute()
    new = M[M.list == "newest"].sort_values("t"); first = new.drop_duplicates("id"); first = first[(first.pos <= 5) & (first.t >= M.t.min() + 600)]
    ids = set(first.id); front_ids = set(M[M.list == "front"].id)
    born = LF.item_times(sorted(ids | front_ids))
    M = M.assign(slot=M.t // 600, born=M.id.map(born)); M = M[M.born.notna()]
    M["day"] = pd.to_datetime(M.t, unit="s", utc=True).dt.strftime("%Y-%m-%d")
    cov = M.groupby(["day", "list"]).t.apply(lambda x: x.floordiv(60).nunique()).unstack()
    full = [d for d in cov.index if cov.loc[d].get("newest", 0) >= 1300 and cov.loc[d].get("front", 0) >= 1000]
    M = M[M.day.isin(full)]
    iso = IsotonicRegression(increasing=False); rows = []
    for sl, g in M.groupby("slot"):
        fr = g[g.list == "front"].sort_values("t").drop_duplicates("pos", keep="last").sort_values("pos")
        fr = fr[fr.pos <= 90]
        if len(fr) < 60:
            continue
        t = sl * 600 + 300
        age_f = (t - fr.born.to_numpy(float)) / 3600
        raw_f = np.clip(fr.points.fillna(1).to_numpy(float) - 1, 0, None) ** 0.8 / (np.clip(age_f, 0, None) + 2) ** 1.8
        eff = iso.fit_transform(fr.pos.to_numpy(float), raw_f)
        curve = np.interp(np.arange(1, 91), fr.pos.to_numpy(float), eff)
        onfront = dict(zip(fr.id, fr.pos))
        y = g[g.id.isin(ids)].sort_values("t").drop_duplicates("id", keep="last")
        age = (t - y.born.to_numpy(float)) / 3600
        keep = (age > 0) & (age < FY.AB[-1])
        y, age = y[keep], age[keep]
        pts = y.points.fillna(1).to_numpy(float)
        raw = np.clip(pts - 1, 0, None) ** 0.8 / (age + 2) ** 1.8
        obs = np.array([onfront.get(i, 91) for i in y.id])
        effo = np.where(obs <= 90, curve[np.clip(obs, 1, 90) - 1], 0.5 * curve[89])
        pred = 1 + (curve[None, :] > raw[:, None]).sum(1)
        rows.append(pd.DataFrame({"pts": pts, "age": age, "raw": raw, "obs": obs, "pred": pred, "lr": np.log(np.clip(effo, 1e-6, None)) - np.log(np.clip(raw, 1e-6, None))}))
    D = pd.concat(rows); D = D[D.raw > 0]
    D["pb"] = np.searchsorted(FY.PB, D.pts, side="left"); D["ab"] = np.searchsorted(FY.AB, D.age, side="left")
    tab = D.groupby(["pb", "ab"]).lr.median().unstack(); n = D.groupby(["pb", "ab"]).size().unstack()
    out = {"points_upper_edges": FY.PB[1:], "age_upper_edges_h": FY.AB[1:], "days": full,
           "log_mult": [[None if (a not in tab.columns or p not in tab.index or pd.isna(tab.loc[p, a])) else round(float(tab.loc[p, a]), 3) for a in range(1, len(FY.AB))] for p in range(1, len(FY.PB))],
           "n": [[int(n.loc[p, a]) if (p in n.index and a in n.columns and not pd.isna(n.loc[p, a])) else 0 for a in range(1, len(FY.AB))] for p in range(1, len(FY.PB))],
           "fit": "live hn_minute, all /newest posts (no QN selection)"}
    q = D[(D.pred <= 30) & (D.age < 1)]
    out["share_in_top30_when_formula_says_top30_age_lt_1h_by_points"] = {str(k): [round(float((g.obs <= 30).mean()), 3), int(len(g))] for k, g in q.groupby(pd.cut(q.pts, [0, 3, 5, 10, 1e9]), observed=True)}
    q2 = D[D.pred <= 30]
    out["share_in_top30_when_formula_says_top30_by_age"] = {str(k): [round(float((g.obs <= 30).mean()), 3), int(len(g))] for k, g in q2.groupby(pd.cut(q2.age, FY.AB), observed=True)}
    json.dump(out, open(os.path.join(HERE, "young_pen_live.json"), "w"), indent=1)
    print(pd.DataFrame(out["log_mult"], index=[f"pts<={x}" for x in FY.PB[1:]], columns=[f"age<={x}h" for x in FY.AB[1:]]).round(2))
    print(pd.DataFrame(out["n"], index=[f"pts<={x}" for x in FY.PB[1:]], columns=[f"age<={x}h" for x in FY.AB[1:]]))
    print(json.dumps({k: out[k] for k in ("share_in_top30_when_formula_says_top30_age_lt_1h_by_points", "share_in_top30_when_formula_says_top30_by_age", "days")}, indent=1))


if __name__ == "__main__":
    main()
