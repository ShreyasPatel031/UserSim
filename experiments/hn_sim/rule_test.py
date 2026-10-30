"""Which summary of a story's day on the live front page reproduces HN's daily list (front?day=D)?

Data: Quality News hourly snapshots per story (qn.py: qn_hour0, qn_rank_by_hour = rank on HN's front page at the end of
each UTC hour, 91 = not on it; qn_up_by_hour = upvotes). For list day D, the candidates are every story with a rank
<= 30 in some hour inside D (00:00-24:00 UTC). Candidate rules, each computed only from the hours inside D:
  best_rank, hours_top30, hours_top10, exposure (sum of 1/rank), peak_points, points_end_of_day,
  snapshot_HH (the live page at the end of hour HH)
Scores per rule: membership (share of the real list's top 30 / all entries that are candidates, and vice versa),
overlap of top 30 / top 10, and Spearman correlation between the rule's order and the real order.

    python rule_test.py
"""
import json
import os

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

import store as S

C = S.LOCAL
q = pd.read_json(os.path.join(C, "qn_long3.jsonl"), lines=True)
q = q[q.status == 200].drop_duplicates("post_id")
L = pd.read_json(os.path.join(C, "frontday.jsonl"), lines=True, dtype={"day": str})

rows = []   # (post_id, unix hour end, rank, points)
for r in q.itertuples():
    if not isinstance(r.qn_rank_by_hour, list):
        continue
    for h, (rk, up) in enumerate(zip(r.qn_rank_by_hour, r.qn_up_by_hour)):
        if rk is not None:
            rows.append((r.post_id, r.qn_hour0 + (h + 1) * 3600, rk, up))
Hr = pd.DataFrame(rows, columns=["post_id", "t", "rank", "points"])
Hr["day"] = pd.to_datetime(Hr.t - 1, unit="s", utc=True).dt.strftime("%Y-%m-%d")
Hr["hour"] = pd.to_datetime(Hr.t - 1, unit="s", utc=True).dt.hour
covered_from = pd.to_datetime(q.qn_hour0.min(), unit="s", utc=True)
print("stories with hourly ranks:", q.post_id.nunique(), " hours from", covered_from, flush=True)

res = []
for d, real in L.groupby("day"):
    hd = Hr[Hr.day == d]
    if hd.hour.nunique() < 24 or pd.Timestamp(d, tz="UTC") < covered_from + pd.Timedelta(days=2):
        continue                                  # need full coverage of the day and of stories posted 2 days before
    real = real.sort_values("rank")
    on = hd[hd["rank"] <= 30]
    g = on.groupby("post_id")
    allh = hd.groupby("post_id")
    feats = pd.DataFrame({
        "best_rank": -g["rank"].min(),
        "hours_top30": g.size(),
        "hours_top10": hd[hd["rank"] <= 10].groupby("post_id").size(),
        "exposure": g["rank"].apply(lambda x: (1 / x).sum()),
        "peak_points": allh.points.max(),
        "points_end_of_day": allh.apply(lambda x: x.sort_values("t").points.iloc[-1]),
    }).loc[lambda x: x.index.isin(on.post_id)].fillna(0)
    for hh in range(24):
        snap = hd[(hd.hour == hh) & (hd["rank"] <= 30)].set_index("post_id")["rank"]
        feats[f"snapshot_{hh:02d}"] = -snap.reindex(feats.index).fillna(99)
    cand = set(feats.index)
    rl = real.post_id.tolist()
    r30, r10 = rl[:30], rl[:10]
    row = {"day": d, "real_n": len(rl), "candidates": len(cand),
           "real_in_candidates": np.mean([x in cand for x in rl]),
           "real30_in_candidates": np.mean([x in cand for x in r30]),
           "candidates_in_real": np.mean([x in set(rl) for x in cand])}
    for col in feats.columns:
        order = feats[col].sort_values(ascending=False, kind="mergesort").index.tolist()
        row[f"{col}|top30"] = len(set(order[:30]) & set(r30)) / 30
        row[f"{col}|top10"] = len(set(order[:10]) & set(r10)) / 10
        common = [x for x in rl if x in cand]
        if len(common) > 5:
            row[f"{col}|spearman"] = spearmanr(range(len(common)), [-feats[col][x] for x in common]).statistic
    res.append(row)
D = pd.DataFrame(res)
print("days tested:", len(D), D.day.min() if len(D) else "", D.day.max() if len(D) else "")
print("membership: real list entries that were on the live top 30 that day:", round(D.real_in_candidates.mean(), 3),
      "| real top 30:", round(D.real30_in_candidates.mean(), 3),
      "| live-top-30 stories that are on the real list:", round(D.candidates_in_real.mean(), 3),
      "| real list length", round(D.real_n.mean(), 1), "candidates", round(D.candidates.mean(), 1))
summ = []
for col in [c.split("|")[0] for c in D.columns if c.endswith("|top30")]:
    summ.append({"rule": col, "top30": D[f"{col}|top30"].mean(), "top10": D[f"{col}|top10"].mean(),
                 "spearman": D.get(f"{col}|spearman", pd.Series(dtype=float)).mean()})
Sm = pd.DataFrame(summ).sort_values("top30", ascending=False).round(3)
print(Sm.to_string(index=False))
S.write("hn_scores", Sm.assign(kind="list_rule", days=len(D), made_on=S.now()))
