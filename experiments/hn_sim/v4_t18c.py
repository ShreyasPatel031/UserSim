"""18:00 round 5: give the daily-list hybrid the at-posting content signals built for the per-post odds: outcomes of
the 30 most similar earlier titles (knn_*), title embedding (PCA 64), crowd v1 / v2 aggregates. Fully fetched days,
57 train / 46 test; paired-by-day difference vs the hybrid.

    python v4_t18c.py [times=t18,t21]
"""
import os
import sys

import numpy as np
import pandas as pd

import daily_v4 as V
import top100 as H
import v4_t18 as X

TS = (sys.argv[1] if len(sys.argv) > 1 else "t18,t21").split(",")
rng = np.random.default_rng(0)
A = pd.read_parquet(os.path.join(H.CACHE, "audience_feats.parquet"))
F2 = pd.read_parquet(os.path.join(H.CACHE, "crowd_v2_feats.parquet"))
KNN = ["knn_lp", "knn_100", "knn_t30", "knn_sim"]
EMB = [f"emb{j}" for j in range(64)]
AUD = ["aud_sum", "aud_cube", "aud_fans", "scout_sum", "scout_cube", "scout_fans", "fans_any", "top50_sim"]
C2 = ["c2_sum", "c2_scout", "c2_top50", "c2_n20"]
C = X.C.merge(A[["post_id"] + KNN + EMB + AUD], on="post_id", how="left").merge(F2, on="post_id", how="left")


def per_day(te, s):
    te = te.assign(s=np.where(te.on_earlier_list == 1, -1e9, s))
    return pd.Series({d: len(set(g[g.real_rank <= 30].post_id) & set(g.nlargest(30, "s").post_id)) / 30 for d, g in te.groupby("day")})


for t in TS:
    D = C[C[f"{t}_visible"] == 1]
    tr, te = D[D.day < "2026-09-01"], D[D.day >= "2026-09-01"]
    base = ["on_earlier_list", "text_score"] + [f"{t}_{c}" for c in list(V.VC) + ["stage1", "c_all", "c_last3h"]]

    def hyb(cols):
        return per_day(te, V.hybrid(te.day, V.fit_top30(tr, cols).predict_proba(te[cols])[:, 1], V.fit_rank(tr, cols).predict(te[cols])))
    a = hyb(base)
    print(f"{t}: hybrid {a.mean():.3f} (posts with content signals: {te.knn_lp.notna().mean():.0%})", flush=True)
    for name, cols in (("+ similar past titles", base + KNN), ("+ similar past titles + embedding", base + KNN + EMB),
                       ("+ crowd v1 + v2", base + AUD + C2), ("+ all content signals", base + KNN + EMB + AUD + C2)):
        b = hyb(cols)
        d = (b - a).to_numpy()
        bt = [rng.choice(d, len(d)).mean() for _ in range(2000)]
        print(f"  {name:36s} {b.mean():.3f} ({d.mean():+.3f} [{np.percentile(bt, 2.5):+.3f}, {np.percentile(bt, 97.5):+.3f}])", flush=True)
