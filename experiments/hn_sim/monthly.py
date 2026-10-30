"""Monthly list: the month's top 30 / top 10 stories by final points (HN publishes daily lists only, so the monthly
list is defined by points, as on Product Hunt). Each story is scored once, at a forecast age (60 min or 8 h of
comments), by a model trained on earlier months; the month's stories are ranked by that score.
Score: share of the month's real top 30 / top 10 found in the model's top 30 / top 10 / top 100. Months 2026-05..09.

    python monthly.py
"""
import json
import os

import lightgbm as lgb
import numpy as np
import pandas as pd

import store as S
import top10 as T
import top100 as H

H.BLOCK_FILES.update({f"early{W}": f"f_early{W}" for W in (120, 240, 480)})
p = H.stories()
p = p[(p.month >= "2023-03") & (p.month <= H.TEST[-1])].reset_index(drop=True)
y = np.log1p(p.points.to_numpy())
mrk = p.groupby("month").points.rank(ascending=False, method="first").to_numpy()
base = ["post", "early30", "who30", "early60", "who60", "submitter"]
blk = {b: pd.read_parquet(os.path.join(H.CACHE, H.BLOCK_FILES[b] + ".parquet")).drop_duplicates("post_id")
       .set_index("post_id").reindex(p.post_id).reset_index(drop=True) for b in base + ["early120", "early240", "early480"]}
texts = {m: T.text_scores(p, y, (p.month < m).to_numpy(), (p.month == m).to_numpy()) for m in H.TEST}
rows = []
for age, cols in (("post only", ["post"]), ("60 min", base), ("8 h", base + ["early120", "early240", "early480"])):
    X = pd.concat([blk[b] for b in cols], axis=1)
    hits = {k: [] for k in ("real30_in_top30", "real10_in_top10", "real30_in_top100", "real10_in_top30")}
    for m in H.TEST:
        tr, te = (p.month < m).to_numpy(), (p.month == m).to_numpy()
        oof, txt = texts[m]
        # regression on log points: the monthly list compares stories across days, so the size of a hit matters
        reg = lgb.LGBMRegressor(**H.GBM).fit(X[tr].assign(text_score=oof), y[tr])
        s = reg.predict(X[te].assign(text_score=txt))
        order = p.post_id[te].to_numpy()[np.argsort(-s)]
        real = p.post_id[te].to_numpy()[np.argsort(mrk[te])]
        for k, (a, b) in {"real30_in_top30": (30, 30), "real10_in_top10": (10, 10), "real30_in_top100": (30, 100),
                          "real10_in_top30": (10, 30)}.items():
            hits[k].append(len(set(real[:a]) & set(order[:b])) / a)
    r = {k: round(float(np.mean(v)), 3) for k, v in hits.items()}
    r["per_month_real30_in_top30"] = [round(x, 2) for x in hits["real30_in_top30"]]
    print(age, json.dumps(r), flush=True)
    rows += [{"kind": "monthly_list", "variant": age, "metric": k, "value": v, "months": len(H.TEST), "made_on": S.now()}
             for k, v in r.items() if not k.startswith("per_month")]
S.write("hn_scores", pd.DataFrame(rows))
