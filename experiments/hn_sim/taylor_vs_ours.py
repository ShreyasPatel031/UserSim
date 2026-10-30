"""Our post-only model vs Taylor-style persona votes on the SAME balanced ballots (persona_vote.py output), and both
combined (rank average). Model trained on months before 2026-09 (the ballots are September days)."""
import os

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

import store as S
import top10 as T
import top100 as H

DAYS = ["2026-09-08", "2026-09-15", "2026-09-22"]
p = H.stories()
p = p[(p.month >= "2023-03") & (p.month <= "2026-09")].reset_index(drop=True)
y = np.log1p(p.points.to_numpy())
rk = p.groupby("day").points.rank(ascending=False, method="first").to_numpy()
F = pd.read_parquet(os.path.join(H.CACHE, "f_post.parquet")).drop_duplicates("post_id").set_index("post_id").reindex(p.post_id).reset_index(drop=True)
tr, te = (p.month < "2026-09").to_numpy(), (p.month == "2026-09").to_numpy()
oof, txt = T.text_scores(p, y, tr, te)
c = lgb.LGBMClassifier(**{**H.GBM, "scale_pos_weight": 2}).fit(F[tr].assign(text_score=oof), (rk[tr] <= 100).astype(int))
ours = pd.Series(c.predict_proba(F[te].assign(text_score=txt))[:, 1], index=p.post_id[te].to_numpy())
rows = []
for d in DAYS:
    b = pd.read_parquet(os.path.join(H.CACHE, f"taylor_{d}_1000.parquet"))
    b["ours"] = b.post_id.map(ours)
    b["both"] = b.votes.rank(pct=True) + b.ours.rank(pct=True)
    for col in ("votes", "ours", "both"):
        pred = b[col].rank(method="first", ascending=False) <= len(b) / 2
        rows.append({"day": d, "method": {"votes": "taylor_personas", "ours": "ours_post", "both": "both"}[col],
                     "accuracy": round(float((pred == (b.front == 1)).mean()), 3),
                     "auc": round(float(roc_auc_score(b.front, b[col])), 3)})
D = pd.DataFrame(rows)
print(D.to_string())
print(D.groupby("method")[["accuracy", "auc"]].mean().round(3).to_string())
S.write("hn_scores", D.assign(kind="taylor_vs_ours", made_on=S.now()))
