"""Winner type per post for any stories frame with post_id, day, y: fast (front page within 1 h), late riser, re-up
(first listed 2+ days after posting). Front page within 1 h from Quality News ranks (a label only, never an input);
posts without a series (all of 2025) are typed by list lag only: fast/late unknown -> 'late' is not assumed, 'win' used."""
import numpy as np
import pandas as pd

import fine_io
import odds_live as OL


def kinds_for(Q):
    _, qs = fine_io.load()
    qb = {r.post_id: {"qn_f0": r.qn_f0, "qn_rank_10m": r.qn_rank_10m, "qn_up_10m": r.qn_up_10m, "qn_exp_10m": r.qn_exp_10m}
          for r in qs.itertuples()}
    vis60 = (OL.vote_feats(Q, qb, [60])[60].best_rank <= 30).to_numpy()
    has = Q.post_id.isin(qb).to_numpy()
    L = OL.lists()
    first = L[L["rank"] <= 30].groupby("post_id").day.min()
    lag = (pd.to_datetime(Q.post_id.map(first)) - pd.to_datetime(Q.day)).dt.days.to_numpy()
    y = Q.y.to_numpy()
    return np.where(y == 0, "none", np.where(lag >= 2, "reup", np.where(~has, "win", np.where(vis60, "fast", "late"))))
