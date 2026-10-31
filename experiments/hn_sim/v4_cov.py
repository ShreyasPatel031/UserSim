"""v4 on fully fetched days only (every 5+ point story of the 7-day lookback has its whole-life series), while the
fetch is still running. Rebuilds daily_v4.parquet, then scores variants per forecast time.

    python v4_cov.py [split=2026-09-01] [times=t18,t21,eod] [min_cov=0.98]
"""
import json
import sys

import numpy as np
import pandas as pd

import daily_v4 as V
import fine_io
import top100 as H

SPLIT = sys.argv[1] if len(sys.argv) > 1 else "2026-09-01"
TS = (sys.argv[2] if len(sys.argv) > 2 else "t18,t21,eod").split(",")
MIN_COV = float(sys.argv[3]) if len(sys.argv) > 3 else 0.98
C = V.build("2026-07-06", "2026-10-16")
got = set(fine_io.load()[0].post_id)
p = H.stories()
p = p[p.points >= 5]
ok = set()
for d in sorted(C.day.unique()):
    t1 = pd.Timestamp(d, tz="UTC").timestamp() + 86400
    if p[(p.created_at_i >= t1 - 7 * 86400) & (p.created_at_i < t1)].post_id.isin(got).mean() >= MIN_COV:
        ok.add(d)
C = C[C.day.isin(ok)]
print("covered days: train", sum(d < SPLIT for d in ok), "test", sum(d >= SPLIT for d in ok), flush=True)
OLD = [c for c in V.VC if c not in ("rate", "rate60", "pts_per_h_page")]
for t in TS:
    D = C[C[f"{t}_visible"] == 1]
    tr, te = D[D.day < SPLIT], D[D.day >= SPLIT]
    cc = [f"{t}_stage1", f"{t}_c_all", f"{t}_c_last3h", "text_score"]
    print(f"{t}: real top 30 visible {(te.real_rank <= 30).sum() / te.day.nunique() / 30:.3f}", flush=True)
    for name, cols in (("v4 + comments", ["on_earlier_list"] + [f"{t}_{c}" for c in OLD] + cc),
                       ("+ upvote rate", ["on_earlier_list"] + [f"{t}_{c}" for c in V.VC] + cc)):
        s = np.where(te.on_earlier_list == 1, -1e9, V.fit_rank(tr, cols).predict(te[cols]))
        print(f"  {name:16s}", json.dumps(V.score(te.assign(s=s), "s")), flush=True)
