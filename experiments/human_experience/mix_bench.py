"""Who will use a NEW product? Held-out check of agent mode's likely_users (the competitors' reviewer mix), model-free.

Every Capterra and G2 product with >= 100 reviews is treated as new: its own reviewers are the truth. Predictions:
  rivals   the reviewer mix of its 3 most-reviewed same-category products (what agent mode reports)
  global   the reviewer mix of every other product on that platform (no competitor data)
Score: total variation distance (0 = identical mix, 1 = disjoint) for role family, company size and industry.

    python mix_bench.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd

CTX = Path(os.environ.get("CTX_ROOT", "/home/user/UserSim-ctx"))
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(CTX / "experiments/staged_context"))
sys.path.insert(0, str(HERE))

import heldout_bench as HB  # noqa: E402

OUT = HERE / "results/mix_bench"
FIELDS = {"capterra": ["role_family", "size_fine", "industry"], "g2": ["role_family", "size3", "industry"]}


def dist(s: pd.Series) -> pd.Series:
    s = s.dropna()
    s = s[s.astype(str).str.lower() != "unknown"]
    return s.value_counts(normalize=True)


def tvd(p: pd.Series, q: pd.Series) -> float:
    i = p.index.union(q.index)
    return float(0.5 * (p.reindex(i, fill_value=0) - q.reindex(i, fill_value=0)).abs().sum())


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    d = HB.frame()
    rows = []
    for src, fields in FIELDS.items():
        dd = d[d.source == src]
        counts = dd.groupby("product").size()
        for p in counts[counts >= 100].index:
            cat = dd.loc[dd["product"] == p, "category"].iloc[0]
            comp = dd[(dd.category == cat) & (dd["product"] != p)]
            top = comp.groupby("product").size().sort_values(ascending=False).index[:3]
            if not len(top) or cat == "Other":
                continue
            own, riv, glob = dd[dd["product"] == p], comp[comp["product"].isin(top)], dd[dd["product"] != p]
            for f in fields:
                truth = dist(own[f])
                if truth.empty:
                    continue
                rows.append({"source": src, "product": p, "field": f.replace("size_fine", "size").replace("size3", "size"),
                             "rivals": tvd(dist(riv[f]), truth), "global": tvd(dist(glob[f]), truth)})
    R = pd.DataFrame(rows)
    R.to_csv(OUT / "per_product.csv", index=False)
    S = R.groupby(["source", "field"])[["rivals", "global"]].mean()
    S["rivals_better_share"] = R.assign(w=R.rivals < R["global"]).groupby(["source", "field"]).w.mean()
    S["products"] = R.groupby(["source", "field"]).size()
    S.to_csv(OUT / "summary.csv")
    print(S.round(3).to_string())


if __name__ == "__main__":
    main()
