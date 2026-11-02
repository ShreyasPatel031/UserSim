"""At posting: combine the models that each moved Caught by +0.5 to +1 (none significant alone).
Members (all scored on Sep 1 - Oct 14, trained before Sep 1; caught.py metric, flags = winners):
  jul    Jul-Aug model, all at-posting inputs (21.4%)
  hist   2025+ history model (caught.py history2; 22.4%)
  pj     jul + page judge (22.1%)
  type   jul + type record (wintypes.py; 22.3%)
  all    one Jul-Aug model with every input (+ page judge + type record + history score)
Equal-weight rank averages, weights fixed in advance; compared with the current best (jul + hist 50/50, 23.2%), paired.

    python ens_post.py
"""
import os

import numpy as np
import pandas as pd

import caught as C
import pj_eval
import top100 as H
import wintypes as WT


def main():
    Q = C.Q.merge(pj_eval.judge_feats(), on="post_id", how="left")
    Q = Q.merge(pd.read_parquet(os.path.join(H.CACHE, "hist_prior.parquet")), on="post_id", how="left")
    TR = WT.type_record(set(Q.post_id))
    Q = Q.merge(TR, on="post_id", how="left")
    C.Q = Q
    PJ = [c for c in Q.columns if c.startswith("pj_")]
    TRC = [c for c in TR.columns if c != "post_id"]
    full = C.POST + C.KNN + C.EMB + C.CROWD
    S = {"jul": C.model(full), "hist": np.load(os.path.join(H.CACHE, "caught_hist2_test_scores.npy")),
         "pj": C.model(full + PJ), "type": C.model(full + TRC), "all": C.model(full + PJ + TRC + ["hist_prior"])}
    rk = lambda x: pd.Series(x).rank(pct=True).to_numpy()
    for k, s in S.items():
        print(f"member {k:5s} {C.ci(C.caught(s))}", flush=True)
    best = C.caught(0.5 * rk(S["jul"]) + 0.5 * rk(S["hist"]))
    print(f"current best (jul + hist): {C.ci(best)}", flush=True)
    for name, ks in (("jul + hist + pj + type", ["jul", "hist", "pj", "type"]), ("hist + pj + type", ["hist", "pj", "type"]),
                     ("all + hist", ["all", "hist"]), ("all five", list(S))):
        c = C.caught(np.mean([rk(S[k]) for k in ks], axis=0))
        print(f"ensemble {name:24s} {C.ci(c)}  vs current best {C.diff(c, best)}", flush=True)


if __name__ == "__main__":
    main()
