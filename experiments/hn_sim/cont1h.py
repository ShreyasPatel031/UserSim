"""Checkpoint 1 (1 h) with the content model's score (content_ft.py, cut Jun 30: every Jul-Oct score out of sample)
as an extra input to the 47.2% model (caught1h.py with HIST=1 RANK_ONLY=1: post inputs + history score + rank only).
Paired, Sep 1 - Oct 14 (Jul-Aug fit), by winner type.

    python cont1h.py
"""
import os

os.environ["HIST"], os.environ["RANK_ONLY"] = "1", "1"

import numpy as np
import pandas as pd

import caught as C
import caught1h as C1  # noqa: F401  (adds hist_prior to C.Q)
import content_ft as CF
import fine_io
import odds_live as OL
import top100 as H

a = 60
pre = os.environ.get("CONTENT_PREFIX", "")            # "large_" = the ModernBERT-large scores
f = os.path.join(H.CACHE, f"content_scores_{pre}jun30.parquet")
if not os.path.exists(f):
    import store as S
    S._bucket().get_blob(CF.PFX + f"scores_{pre}jun30.parquet").download_to_filename(f)
print(f"content scores: {pre or 'base '}model, cut Jun 30", flush=True)
sc = pd.read_parquet(f).drop_duplicates("post_id").set_index("post_id").s
Q = C.Q
_, qs = fine_io.load()
qb = {r.post_id: {"qn_f0": r.qn_f0, "qn_rank_10m": r.qn_rank_10m, "qn_up_10m": r.qn_up_10m, "qn_exp_10m": r.qn_exp_10m}
      for r in qs.itertuples()}
V = C.honest(OL.vote_feats(Q, qb, [a])[a], a, set(qb))[["rank_now", "best_rank"]]
full = C1.full
kind = CF.kinds(Q)[C.te]
T = Q[C.te][["post_id", "day", "y"]].reset_index(drop=True)
s0 = C.model(full, V)
s1 = C.model(full, pd.concat([V, pd.DataFrame({"content": Q.post_id.map(sc).to_numpy()})], axis=1))
c0, c1 = C.caught(s0), C.caught(s1)
print(f"1 H (Sep 1 - Oct 14, {int(T.y.sum())} winners): rank-only + history {C.ci(c0)} | by type {CF.by_type(T, s0, kind)}", flush=True)
print(f"   + content model: {C.ci(c1)}, difference {C.diff(c1, c0)}, pairwise vs base {C.pairwise(s1, s0)} | "
      f"by type {CF.by_type(T, s1, kind)}", flush=True)
rk = lambda v: pd.Series(np.asarray(v, float)).rank(pct=True).to_numpy()
