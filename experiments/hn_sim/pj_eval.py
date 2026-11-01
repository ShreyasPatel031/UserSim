"""Page judge as a model input (pagejudge.py, Gemini 2.5 Flash-Lite over every Jul 1 - Oct 14 post).
Inputs: kind (one-hot), novelty, depth, title match, HN fit, front-page probability, whether the page was read.
  Checkpoint 3 (at posting): the Jul-Aug model with vs without the judge; and the 50/50 blend with the 2025+ history
  model (blend_hist.py) with vs without.
  Checkpoint 1 (1 h): rank-only + history score + who commented early, with vs without the judge.
Paired by day, flags = winners (caught.py).

    python pj_eval.py
"""
import json
import os

import numpy as np
import pandas as pd

import caught as C
import top100 as H

KINDS = ["launch", "show_hn_product", "research", "postmortem", "tutorial", "deep_dive", "opinion", "news", "rehash", "other"]


def judge_feats():
    J = pd.DataFrame([json.loads(x) for x in open(os.path.join(H.CACHE, "pagejudge_lite.jsonl"))]).drop_duplicates("post_id")
    F = pd.DataFrame({"post_id": J.post_id})
    for c in ("novelty", "depth", "title_matches", "hn_fit", "front_page_prob"):
        F[f"pj_{c}"] = pd.to_numeric(J[c], errors="coerce").to_numpy()
    for k in KINDS:
        F[f"pj_kind_{k}"] = (J.kind == k).astype(int).to_numpy()
    F["pj_read"] = (J.fetch == "ok").astype(int).to_numpy()
    return F


def main():
    F = judge_feats()
    C.Q = C.Q.merge(F, on="post_id", how="left").merge(pd.read_parquet(os.path.join(H.CACHE, "hist_prior.parquet")), on="post_id", how="left")
    PJ = [c for c in F.columns if c != "post_id"]
    print(f"judged: {C.Q.pj_front_page_prob.notna().mean():.1%} of posts; page read {C.Q.pj_read.mean():.1%}", flush=True)
    full = C.POST + C.KNN + C.EMB + C.CROWD
    s0 = C.model(full)
    s1 = C.model(full + PJ)
    b0, b1 = C.caught(s0), C.caught(s1)
    print(f"checkpoint 3, Jul-Aug model: without judge {C.ci(b0)}; with {C.ci(b1)}; difference {C.diff(b1, b0)}", flush=True)
    h = np.load(os.path.join(H.CACHE, "caught_hist2_test_scores.npy"))
    rk = lambda x: pd.Series(x).rank(pct=True).to_numpy()
    c0, c1 = C.caught(0.5 * rk(s0) + 0.5 * rk(h)), C.caught(0.5 * rk(s1) + 0.5 * rk(h))
    print(f"checkpoint 3, 50/50 blend with the 2025+ model: without judge {C.ci(c0)}; with {C.ci(c1)}; difference {C.diff(c1, c0)}", flush=True)
    # checkpoint 1: rank-only votes + history score + who commented early (caught1h features)
    X60 = pd.read_parquet(os.path.join(H.CACHE, "caught60_feats.parquet"))
    keep = ["post_id", "rank_now", "best_rank"] + [c for c in X60.columns if c.startswith("who_")]
    X60 = C.Q[["post_id"]].merge(X60[keep], on="post_id", how="left").drop(columns="post_id")
    X60.index = C.Q.index
    a0 = C.caught(C.model(full + ["hist_prior"], X60))
    a1 = C.caught(C.model(full + ["hist_prior"] + PJ, X60))
    print(f"checkpoint 1 (rank + history score + who): without judge {C.ci(a0)}; with {C.ci(a1)}; difference {C.diff(a1, a0)}", flush=True)


if __name__ == "__main__":
    main()
