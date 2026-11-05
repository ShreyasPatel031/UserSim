"""Checkpoint 1 (1 h), biggest error bucket = late risers (30.6 pts oracle). Fix: give the 1-h headline model (rank only +
history score + content large, Jul-Aug fit, 48.4%) the light 60-min model's score as an input. The light model (all 2025
+ 2026 rows, content, honest Wayback /newest votes and comments by 60 min) catches late risers 88 vs 56 but has no
front-page rank; as an input the headline model learns where to trust it.
Out of sample everywhere: Jul and Aug 2026 rows get cross-fitted light scores (light model trained on 2025 + 2026 rows up
to Aug 31 minus that month); Sep 1 - Oct 14 test rows get the light model trained on rows up to Aug 31.
Paired vs the headline on identical posts and flags; by winner type; Oct 2-14 subset.

    python stack60.py
"""
import os

os.environ["WB_AGE"] = "60"

import lightgbm as lgb  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import caught as C  # noqa: E402
import content_ft as CF  # noqa: E402
import fine_io  # noqa: E402
import odds_live as OL  # noqa: E402
import top100 as H  # noqa: E402
import wb25_train as WB  # noqa: E402
import wb_caught as W  # noqa: E402


def light_scores():
    Q, base_cols, y, is25 = WB.build()
    cols = base_cols + ["content"]
    out = pd.Series(np.nan, index=Q.post_id.to_numpy())
    upto = (Q.day <= "2026-08-31").to_numpy()
    for a, b in (("2026-07-01", "2026-07-31"), ("2026-08-01", "2026-08-31")):          # cross-fit Jul and Aug
        fold = ((Q.day >= a) & (Q.day <= b)).to_numpy()
        m = lgb.LGBMClassifier(**WB.PRM).fit(Q.loc[upto & ~fold, cols], y[upto & ~fold])
        out[Q.post_id[fold].to_numpy()] = m.predict_proba(Q.loc[fold, cols])[:, 1]
    te = ((Q.day >= "2026-09-01") & (Q.day <= "2026-10-14")).to_numpy()
    m = lgb.LGBMClassifier(**WB.PRM).fit(Q.loc[upto, cols], y[upto])
    out[Q.post_id[te].to_numpy()] = m.predict_proba(Q.loc[te, cols])[:, 1]
    return out[~out.index.duplicated()]


def main():
    LS = light_scores()
    Q = C.Q.merge(pd.read_parquet(os.path.join(H.CACHE, "hist_prior.parquet")), on="post_id", how="left")
    C.Q = Q
    Q["content"] = Q.post_id.map(pd.read_parquet(os.path.join(H.CACHE, "content_scores_large_jun30.parquet")).drop_duplicates("post_id").set_index("post_id").s)
    Q["light60"] = Q.post_id.map(LS)
    print(f"light score coverage: Jul-Aug {Q.light60[C.fit].notna().mean():.1%}, Sep-Oct {Q.light60[C.te].notna().mean():.1%}", flush=True)
    full = C.POST + C.KNN + C.EMB + C.CROWD + ["hist_prior", "content"]
    _, qs = fine_io.load()
    qb = {r.post_id: {"qn_f0": r.qn_f0, "qn_rank_10m": r.qn_rank_10m, "qn_up_10m": r.qn_up_10m, "qn_exp_10m": r.qn_exp_10m}
          for r in qs.itertuples()}
    R = C.honest(OL.vote_feats(Q, qb, [60])[60], 60, set(qb))[["rank_now", "best_rank"]]
    kind = CF.kinds(Q)[C.te]
    s0 = C.model(full, R)
    s1 = C.model(full + ["light60"], R)
    T = Q[C.te][["post_id", "day", "y"]].reset_index(drop=True)
    k = int(T.y.sum())
    c0, c1 = C.caught(s0), C.caught(s1)
    print(f"\nCaught at 1 h, Sep 1 - Oct 14 ({k} winners), identical posts and flags:", flush=True)
    for name, s, c in (("headline (rank + history + content)", s0, c0), ("+ light 60-min score as an input", s1, c1)):
        fl = pd.Series(s).rank(ascending=False, method="first").to_numpy() <= k
        types = ", ".join(f"{t} {int((fl & (kind == t)).sum())}/{int((kind == t).sum())}" for t in ("fast", "late", "reup"))
        print(f"   {name:40s} {C.ci(c)}" + ("" if c is c0 else f"  paired {C.diff(c, c0)}, pairwise {C.pairwise(s, s0)}") + f" | {types}", flush=True)
    oct_ = (T.day >= "2026-10-02").to_numpy()
    d0, d1 = C.caught(s0, oct_), C.caught(s1, oct_)
    print(f"   Oct 2-14 subset: {W.ci2(d0)} -> {W.ci2(d1)}, paired {W.ci2(d1, d0)}", flush=True)
    pd.DataFrame({"post_id": T.post_id, "headline": s0, "stack": s1}).to_parquet(os.path.join(H.CACHE, "stack60_scores.parquet"), index=False)


if __name__ == "__main__":
    main()
