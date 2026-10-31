"""What orders HN's daily list? For each listed day D with every candidate's 10-minute series (qn_fine_*.jsonl), rank
candidates by a rule computed only inside the UTC day D and score the overlap of its top 30 / top 10 with the real list.
Rules: exposure (sum of 1/rank per 10 min on the front page), minutes in the top 30 / top 10, best rank, points at the
end of D, points gained during D, and HN's formula at the end of D.

    python list_rule.py [from=2026-07-28] [to=2026-10-16]
"""
import json
import os
import sys

import numpy as np
import pandas as pd

import fine_io
import rank as R
import top100 as H

A = sys.argv[1] if len(sys.argv) > 1 else "2026-07-28"
B = sys.argv[2] if len(sys.argv) > 2 else "2026-10-16"
L = pd.read_json(os.path.join(H.CACHE, "frontday.jsonl"), lines=True, dtype={"day": str})
L = L.sort_values("rank").drop_duplicates(["day", "post_id"])
L = L[(L.day >= A) & (L.day <= B)]
q_all, q = fine_io.load()
RK = np.array([[x if x is not None else 91 for x in r] for r in q.qn_rank_10m], float)
UP = pd.DataFrame(list(q.qn_up_10m), dtype=float).ffill(axis=1).fillna(1).to_numpy()
F0 = q.qn_f0.to_numpy().astype(float)
born = q.post_id.map(H.stories().set_index("post_id").created_at_i).to_numpy().astype(float)
slot_t = F0[:, None] + 600 * (np.arange(216)[None, :] + 1)          # end time of each 10-minute slot

res = {}
for d, g in L.groupby("day"):
    t0 = pd.Timestamp(d, tz="UTC").timestamp()
    t1 = t0 + 86400
    inday = (slot_t > t0) & (slot_t <= t1)
    cand = np.flatnonzero(inday.any(1) & (born < t1))
    if len(cand) < 30:
        continue
    m = inday[cand]
    rk = np.where(m, RK[cand], 91)
    up = UP[cand]
    last = np.where(m, np.arange(216)[None, :], -1).max(1)
    first = np.where(m, np.arange(216)[None, :], 999).min(1)
    up_end = up[np.arange(len(cand)), last]
    up_start = np.where(first > 0, up[np.arange(len(cand)), np.maximum(first - 1, 0)], 1)
    age_end = (np.minimum(t1, slot_t[cand, last]) - born[cand]) / 3600
    rules = {
        "exposure (sum 1/rank)": np.where(rk < 91, 1 / rk, 0).sum(1),
        "time in top 30": (rk <= 30).sum(1),
        "time in top 10": (rk <= 10).sum(1),
        "best rank in day": -rk.min(1),
        "points at end of day": up_end,
        "points gained in day": up_end - up_start,
        "HN formula at end of day": (up_end - 1) / (age_end + 2) ** 1.8,
        "exposure x points gained": np.where(rk < 91, 1 / rk, 0).sum(1) * (up_end - up_start),
    }
    ids = q.post_id.to_numpy()[cand]
    real30, real10 = set(g[g["rank"] <= 30].post_id), set(g[g["rank"] <= 10].post_id)
    for name, v in rules.items():
        o = ids[np.argsort(-v, kind="stable")]
        res.setdefault(name, []).append((len(real30 & set(o[:30])) / 30, len(real10 & set(o[:10])) / 10))
for name, v in res.items():
    a = np.array(v)
    print(f"{name:28s} days {len(a)}  top30 {json.dumps(R.boot(a[:, 0]))}  top10 {json.dumps(R.boot(a[:, 1]))}", flush=True)
