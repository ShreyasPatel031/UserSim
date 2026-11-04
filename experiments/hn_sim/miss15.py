"""Miss decomposition of the 15-min headline (light model: 2025 rows + content, Sep 1 - Oct 14, 28.0%; orchestrator
2026-11-04): every winner the headline did not flag, by bucket, with the oracle gain (points of Caught if every winner
in the bucket were flagged = missed in bucket / all winners).
Buckets: re-up (first listed 2+ days after posting); late riser (not on the front page within 1 h); fast (front page
within 1 h) split by what the model could see at 15 min: no recorder data (no /newest snapshot by 15 min), a snapshot
but no early signal (<= 2 points and no comments by 15 min), or an early signal but scored below the flag.

    python miss15.py
"""
import os

import numpy as np
import pandas as pd

import caught as C
import content_ft as CF
import top100 as H
import wb15 as W15

Q = C.Q
T = Q[C.te].reset_index(drop=True)
S = pd.read_parquet(os.path.join(H.CACHE, "wb25_scores.parquet"))
s = T.post_id.map(S[S.test == "sep1_oct14"].drop_duplicates("post_id").set_index("post_id")["2025 + 2026 rows + content"]).fillna(-1).to_numpy()
k = int(T.y.sum())
flag = pd.Series(s).rank(ascending=False, method="first").to_numpy() <= k
kind = CF.kinds(Q)[C.te]
V = W15.votes15(Q)[C.te].reset_index(drop=True)
c = pd.read_parquet(os.path.join(H.CACHE, "bq_comments.parquet"), columns=["story_id", "created_at_i"])
born = T.set_index("post_id").created_at_i
c = c[c.story_id.isin(born.index)]
lat = c.created_at_i - c.story_id.map(born).to_numpy()
cm15 = T.post_id.map(c[(lat >= 0) & (lat < 900)].groupby("story_id").size()).fillna(0).to_numpy()
w = T.y.to_numpy() == 1
snap = V.v_has.to_numpy() == 1
signal = (V.v_score.fillna(1).to_numpy() > 2) | (cm15 > 0)
bucket = np.select([kind == "reup", kind == "late", ~snap, ~signal],
                   ["re-up (first listed 2+ days after posting)", "late riser (not on the front page within 1 h)",
                    "fast, no recorder data by 15 min (no /newest snapshot)", "fast, snapshot but no early signal (<= 2 pts, 0 comments)"],
                   "fast, early signal but scored below the flag")
D = pd.DataFrame({"bucket": bucket, "w": w, "flag": flag, "month": T.day.str[:7].to_numpy()})
print(f"15-min headline (Sep 1 - Oct 14): {int((flag & w).sum())}/{k} = {(flag & w).sum() / k:.1%}; missed {int((~flag & w).sum())}")
tab = D[D.w].groupby("bucket").agg(winners=("w", "size"), caught=("flag", "sum"))
tab["missed"] = tab.winners - tab.caught
tab["oracle_gain_pts"] = (100 * tab.missed / k).round(1)
tab["caught_share"] = (tab.caught / tab.winners).round(3)
print(tab.sort_values("missed", ascending=False).to_string())
by_m = D[D.w & ~D.flag].groupby(["month", "bucket"]).size().unstack(0).fillna(0).astype(int)
print("\nmissed by month:\n" + by_m.to_string())
print(f"\n/newest snapshot by 15 min among winners: Sep {snap[w & (D.month == '2026-09').to_numpy()].mean():.1%}, "
      f"Oct {snap[w & (D.month == '2026-10').to_numpy()].mean():.1%}")
