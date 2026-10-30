"""Score against HN's own daily list (news.ycombinator.com/front?day=D, frontday.py), the list a reader sees, instead
of the top-by-points stand-in. The list for day D also holds stories posted late on D-1, so the candidates for day D
are stories posted from D-1 12:00 UTC to the end of D, ranked by the model's score (pred_sep.parquet, Sep 2026).
Reports: share of the real list's top 10 / 30 in the model's top 10 / 30 / 100, and the same for the points stand-in."""
import os

import numpy as np
import pandas as pd

import rank as R
import store as S
import top100 as H

P = pd.read_parquet(os.path.join(H.CACHE, "pred_sep.parquet"))
F = pd.read_json(os.path.join(H.CACHE, "frontday.jsonl"), lines=True)
rows = []
for d, f in F.groupby("day"):
    t1 = pd.Timestamp(d, tz="UTC").timestamp() + 86400
    cand = P[(P.created_at_i >= t1 - 86400 * 1.5) & (P.created_at_i < t1)]
    if len(cand) < 500:
        continue
    order = cand.sort_values("score", ascending=False).post_id.tolist()
    real = f.sort_values("rank").post_id.tolist()
    pts = cand.sort_values("points", ascending=False).post_id.tolist()
    r = {"day": d, "in_pool": float(np.mean([x in set(cand.post_id) for x in real[:30]]))}
    for k in (10, 30):
        for n in (k, 30, 100):
            if n < k:
                continue
            r[f"real{k}_in_model{n}"] = len(set(real[:k]) & set(order[:n])) / k
        r[f"real{k}_in_pointsTop{k}"] = len(set(real[:k]) & set(pts[:k])) / k    # how close the stand-in label is
    rows.append(r)
D = pd.DataFrame(rows)
print("days", len(D), " share of real top-30 that is in the candidate pool:", round(D.in_pool.mean(), 3))
out = {c: R.boot(D[c].to_numpy()) for c in D.columns if c.startswith("real")}
for k, v in out.items():
    print(k, v)
S.write("hn_scores", pd.DataFrame([{"kind": "frontday_eval", "metric": k, "value": v[0], "lo": v[1], "hi": v[2],
                                    "days": len(D), "made_on": S.now()} for k, v in out.items()]))
