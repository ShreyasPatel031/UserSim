"""How much does the 30-point vote cut leak? Stage 2 trained on summer days of the cut table (daily_cache.parquet), then
tested on fully fetched September days twice: with the cut (stories under 30 final points get the no-votes fill) and
without it (their real votes, from dc_nocut.parquet, built with VOTE_MIN_POINTS=0 DC_OUT=dc_nocut.parquet).

    python leak_check.py [split=2026-09-01]
"""
import json
import os
import sys

import pandas as pd

import daily_fast as F
import top100 as H

SPLIT = sys.argv[1] if len(sys.argv) > 1 else "2026-09-01"
N = pd.read_parquet(os.path.join(H.CACHE, "dc_nocut.parquet"))
for t in ("t12", "t18", "eod"):
    vc = [f"{t}_{c}" for c in F.V]
    fill = {f"{t}_v_points": 1, f"{t}_v_rank_now": 91, f"{t}_v_best_rank": 91, f"{t}_v_h_top30": 0, f"{t}_v_h_top10": 0,
            f"{t}_v_gain3h": 0}
    cols = [f"{t}_stage1", f"{t}_age_h", "prev_list_rank", "posted_before_d"] + vc
    prep = lambda X: X[X.day.isin(F.qdays) & (X[f"{t}_visible"] == 1)].assign(**{c: X[c].fillna(v) for c, v in fill.items()})
    D, Dn = prep(F.C), prep(N)
    m = F.fit_rank(D[D.day < SPLIT], cols)
    for name, te in (("cut", D[D.day >= SPLIT]), ("no cut", Dn[Dn.day >= SPLIT])):
        print(t, name, te.day.nunique(), "days", json.dumps(F.score(te.assign(s=m.predict(te[cols])), "s")), flush=True)
