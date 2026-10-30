"""Does training on more daily lists help? Stage-1 (comments, no votes) scores on every list day from STAGE1_END, for
two cached tables built with and without the 2023-2024 lists (daily_cache.py with DC_OUT / NO_OLDER).

    python more_days.py dc_with.parquet dc_without.parquet [from=2026-05-01]
"""
import json
import os
import sys

import pandas as pd

import rank as R
import top100 as H

FROM = sys.argv[3] if len(sys.argv) > 3 else "2026-05-01"
for f in sys.argv[1:3]:
    C = pd.read_parquet(os.path.join(H.CACHE, f))
    C = C[C.day >= FROM]
    for t in ("t12", "t18", "eod"):
        D = C[C[f"{t}_visible"] == 1]
        out = {}
        for k, n in ((30, 30), (10, 10), (10, 30)):
            v = [len(set(g[g.real_rank <= k].post_id) & set(g.nlargest(n, f"{t}_stage1").post_id)) / k for _, g in D.groupby("day")]
            out[f"real{k}_in_top{n}"] = R.boot(v)
        print(f, t, D.day.nunique(), "days", json.dumps(out), flush=True)
