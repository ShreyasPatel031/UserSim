"""Tastemakers: which people's taste predicts that a launch will beat the launch model? Ridge regression of the launch
model's within-day error (real minus predicted standing) on every person's exposure-weighted appeal for the launch
(agg.py), trained on earlier months only and applied to the next month. The prediction is the tastemaker score.
Also tested: the same with log-vote error as the target. Scored on day/week/month lists as a blend on the baseline,
weight chosen on the other months.  usage: python -m simlab.tastemakers -> reports/tastemakers.json"""
import json, os
import numpy as np, pandas as pd
from sklearn.linear_model import Ridge
from . import harness as H

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    Z = np.load(f"{HERE}/cache/agg_features_appeal.npz")
    A = Z["appeal"].astype(np.float32); ids = [str(x) for x in Z["ids"]]
    keep = A.std(0) > 0; A = A[:, keep]
    A = A / (A.std(0) + 1e-6)
    B = H.baseline(); B = B[B.id.isin(ids)].copy()
    pos = {i: k for k, i in enumerate(ids)}
    B["res_rank"] = B.groupby("day").dailyRank.rank(pct=True, ascending=False) - B.groupby("day").base.rank(pct=True)
    B["res_log"] = np.log1p(B.votes) - B.base
    X = A[[pos[i] for i in B.id]]
    months = sorted(B.mon.unique()); res = {}
    for target in ("res_rank", "res_log"):
        for alpha in (1e3, 1e4, 1e5):
            col = f"tm_{target}_{int(alpha)}"; B[col] = np.nan
            for m0 in months[1:]:
                tr = ((B.mon < m0) & B[target].notna()).values; te = (B.mon == m0).values
                B.loc[te, col] = Ridge(alpha=alpha).fit(X[tr], B[target].values[tr]).predict(X[te])
    cols = [c for c in B.columns if c.startswith("tm_")]
    T = B.dropna(subset=cols).copy()
    groups = (("day", "dailyRank"), ("week", "weeklyRank"), ("mon", "monthlyRank"))
    grid = (0, 0.1, 0.2, 0.3, 0.5, 0.75, 1)
    for col in cols:
        for g, rc in groups:
            T["pb"] = T.groupby(g).base.rank(pct=True); T["px"] = T.groupby(g)[col].rank(pct=True)
            bl = pd.Series(index=T.index, dtype=float); ws = []
            for m0 in sorted(T.mon.unique()):
                tr, te = T[T.mon != m0], T[T.mon == m0]
                w = max(grid, key=lambda w: np.mean([H.recall(tr.assign(s=tr.pb + w * tr.px), "s", group=g, col=rc, k=k) for k in H.KS]))
                bl[te.index] = te.pb + w * te.px; ws.append(w)
            T["bl"] = bl
            for k in H.KS:
                res.setdefault(f"{g}@{k}", {"baseline": round(100 * H.recall(T, "base", group=g, col=rc, k=k), 1)})
                res[f"{g}@{k}"][f"+ {col}"] = round(100 * H.recall(T, "bl", group=g, col=rc, k=k), 1)
            res.setdefault("weights", {})[f"{col}|{g}"] = ws
    r, ci = H.residual(T, cols[0])
    res["launches"] = int(len(T)); res["months"] = sorted(T.mon.unique())
    json.dump(res, open(f"{HERE}/reports/tastemakers.json", "w"), indent=1)
    print(pd.DataFrame({k: v for k, v in res.items() if "@" in k}).T.to_string())
    print({k: sorted(set(v)) for k, v in res["weights"].items()})


if __name__ == "__main__":
    main()
