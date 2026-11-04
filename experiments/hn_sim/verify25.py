"""Verify a 2025 Wayback /newest early-votes file (Data Feeder): rows, duplicates, captures by month, coverage by 15 min,
and outcome independence (snapshot-by-15-min rate by final-points band; winners vs all).

    python verify25.py <bucket path of early_snapshots.jsonl> <first day> <last day>
"""
import os
import sys

import pandas as pd

import odds_live as OL
import store as S
import top100 as H

path, a, b_ = sys.argv[1], sys.argv[2], sys.argv[3]
f = os.path.join(H.CACHE, "early_votes", os.path.basename(os.path.dirname(path)) + "_" + os.path.basename(path))
os.makedirs(os.path.dirname(f), exist_ok=True)
S._bucket().get_blob(path).download_to_filename(f)
A = pd.read_json(f, lines=True, convert_dates=False)
print(f"rows {len(A)}, pages {A.page.value_counts().to_dict()}, duplicates (item_id, capture_ts, page) "
      f"{int(A.duplicated(['item_id', 'capture_ts', 'page']).sum())}")
print("captures by month:", A.assign(m=A.capture_ts.astype(str).str[:6]).groupby("m").capture_ts.nunique().to_dict())
N = A[(A.page == "newest") & (A.age_min >= 0) & (A.age_min <= 15)]
p = H.stories()
p = p[(p.day >= a) & (p.day <= b_)].copy()
L = OL.lists()
p["y"] = p.post_id.isin(set(L[L["rank"] <= 30].post_id))
p["snap"] = p.post_id.isin(set(N.item_id))
p["m"] = p.day.str[:7]
g = p.groupby("m")
print(pd.DataFrame({"posts": g.size(), "cov": g.snap.mean(), "cov_winners": p[p.y].groupby("m").snap.mean()}).round(3).to_string())
p["band"] = pd.cut(p.points, [-1, 1, 2, 4, 9, 49, 199, 1e9], labels=["1", "2", "3-4", "5-9", "10-49", "50-199", "200+"])
print("snapshot-by-15-min rate by final points:", p.groupby("band", observed=True).snap.mean().round(3).to_dict())
print(f"overall: posts {len(p)}, winners {int(p.y.sum())}, coverage {p.snap.mean():.1%}, winners {p.snap[p.y].mean():.1%}")
