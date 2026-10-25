"""Does judging the product predict what "who launched it" doesn't?

Network model: launch + people + history features only (expanding window, as in evaluate.py). Residual = actual log
votes minus its out-of-sample prediction. Then: Spearman of each product-judgment feature (LLM read, website) with
the residual, inside the same week, overall and per product type; and recall gain from adding them.
Writes out/residual.json.

    python experiments/ph_predict/residual.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evaluate as E  # noqa: E402
import features as F  # noqa: E402


def main() -> None:
    df, X, groups = F.build()
    keep = df.complete.to_numpy()
    df, X = df[keep].reset_index(drop=True), X[keep].reset_index(drop=True)
    months = sorted(df.month.unique())
    test_months = [m for m in months if m >= E.FIRST_TEST_MONTH]
    network = groups["launch"] + groups["people"] + groups["history"]
    product = groups["llm"] + groups["site"]
    net = E.backtest(df, X, network, test_months)
    both = E.backtest(df, X, network + product, test_months)
    test = net.notna()
    resid = (np.log1p(df.votes) - net)[test]
    resid = resid - resid.groupby(df.week[test]).transform("mean")
    fam = df.topics.apply(E.family)[test]
    out = {"recall_network_only": {k: v["recall"] for k, v in E.recall_lists(df, net).items() if k[:3] in ("day", "wee")},
           "recall_network_plus_product": {k: v["recall"] for k, v in E.recall_lists(df, both).items()
                                           if k[:3] in ("day", "wee")},
           "residual_corr": {}}
    for f in ["(all types)"] + sorted(fam.unique()):
        m = np.ones(len(resid), bool) if f == "(all types)" else (fam == f).to_numpy()
        xs = X.loc[test, product][m]
        c = xs.corrwith(resid[m], method="spearman").dropna()
        out["residual_corr"][f] = {"n": int(m.sum()),
                                   "top": c.reindex(c.abs().sort_values(ascending=False).index).head(6).round(3).to_dict()}
    (E.OUT / "residual.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
