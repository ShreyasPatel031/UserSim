"""Walk-forward score of v4 on the cached table (daily_v4.parquet): each test month (from START) is scored by rankers
trained on every day before that month, as the live model would be retrained.

    python v4_walk.py [start=2026-09-01] [times=all]
"""
import json
import os
import sys

import numpy as np
import pandas as pd

import daily_v4 as V
import rank as R
import top100 as H

START = sys.argv[1] if len(sys.argv) > 1 else "2026-09-01"
TS = sys.argv[2].split(",") if len(sys.argv) > 2 else list(V.TIMES)
C = pd.read_parquet(os.path.join(H.CACHE, "daily_v4.parquet"))
months = sorted({d[:7] for d in C.day if d >= START})
for t in TS:
    vc = [f"{t}_{c}" for c in V.VC]
    out = {}
    for name, cols in (("votes/page", ["on_earlier_list"] + vc),
                       ("+ comments", ["on_earlier_list"] + vc + [f"{t}_stage1", f"{t}_c_all", f"{t}_c_last3h", "text_score"])):
        P = []
        for m in months:
            D = C[C[f"{t}_visible"] == 1]
            tr, te = D[D.day < m + "-01"], D[D.day.str.startswith(m)]
            s = V.fit_rank(tr, cols).predict(te[cols])
            P.append(te.assign(s=np.where(te.on_earlier_list == 1, -1e9, s)))
        P = pd.concat(P)
        out[name] = {k: [round(x, 3) for x in v] for k, v in V.score(P, "s").items()}
    print(t, P.day.nunique(), "days", json.dumps(out), flush=True)
