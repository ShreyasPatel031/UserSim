"""GitHub traction BEFORE posting as an at-posting input (orchestrator, 2026-11-04): for repo links, new stars the day
before / 7 / 30 days before the posting day and repo age (wb_gh.gh_feats: Data Feeder's daily star counts, days strictly
before the posting day). Added to the Jul-Aug at-posting model inside the current headline 3-way blend (Jul-Aug model +
2025+ history + content model large, equal weights, 26.1%); paired, Sep 1 - Oct 14 and Oct 2 - 14 separately.

    python gh_post.py
"""
import os

import numpy as np
import pandas as pd

import caught as C
import content_ft as CF
import top100 as H
import wb_caught as W
import wb_gh as G


def main():
    Q = C.Q
    rk = lambda v: pd.Series(np.asarray(v, float)).rank(pct=True).to_numpy()
    T = Q[C.te][["post_id", "day", "y"]].reset_index(drop=True)
    h = np.load(os.path.join(H.CACHE, "caught_hist2_test_scores.npy"))
    ca = T.post_id.map(pd.read_parquet(os.path.join(H.CACHE, "content_scores_large_aug30.parquet")).drop_duplicates("post_id").set_index("post_id").s).fillna(-99).to_numpy()
    GF = G.gh_feats(Q)
    base = C.model(C.POST + C.KNN + C.EMB + C.CROWD)
    withgh = C.model(C.POST + C.KNN + C.EMB + C.CROWD, extra=GF.reset_index(drop=True))
    s0 = (rk(base) + rk(h) + rk(ca)) / 3
    s1 = (rk(withgh) + rk(h) + rk(ca)) / 3
    kind = CF.kinds(Q)[C.te]
    has = (GF.gh_known == 1).to_numpy()[C.te]
    print(f"test posts with GitHub star history: {has.mean():.1%} (winners {has[T.y.to_numpy() == 1].mean():.1%}); "
          f"winners by type with stars: " + ", ".join(f"{t} {int((has & (kind == t)).sum())}/{int((kind == t).sum())}" for t in ("fast", "late", "reup")), flush=True)
    c0, c1 = C.caught(s0), C.caught(s1)
    print(f"At posting, Sep 1 - Oct 14: headline 3-way blend {C.ci(c0)}; + GitHub stars before posting {C.ci(c1)}, "
          f"paired {C.diff(c1, c0)}", flush=True)
    for name, m in (("Oct 2 - 14", (T.day >= "2026-10-02").to_numpy()),):
        d0, d1 = C.caught(s0, m), C.caught(s1, m)
        print(f"   {name}: {W.ci2(d0)} -> {W.ci2(d1)}, paired {W.ci2(d1, d0)}", flush=True)


if __name__ == "__main__":
    main()
