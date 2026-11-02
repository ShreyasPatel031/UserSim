"""Same-link pair model (at posting). Content is identical when a link is posted twice, so what separates the winning
posting from the flop is the moment, the title wording and who posted it. Learn that from same-link pairs, then use it
as an at-posting input for every post.

Pairs: postings of the same normalised URL, 1+ day apart, exactly one of the two made a daily top 30, both posted
2025-01-15 .. 2026-06-30 (so the model is out-of-sample for every Jul-Oct post). A LambdaRank model with one group
per pair, on the context inputs only:
  moment     hour, weekday, posts that day / that hour so far, same host / same words in the last 6 h
  title      title score (text_score), length, words, question, Show HN / Ask HN
  submitter  their HN record (b_author_*), comments before, account age, real-list record (ra_*)
Reported: within-pair accuracy on held-out pairs (posted Jul-Oct), then Caught at posting (Sep 1 - Oct 14) with vs
without the context score as an input, and in the 50/50 blend with the 2025+ history model; paired by day.

    python pairs.py
"""
import os

import lightgbm as lgb
import numpy as np
import pandas as pd

import caught as C
import feeds_anticipate as FA
import levers as LV
import odds_live as OL
import top100 as H

CTX = ["b_hour", "b_dow", "b_day_n", "b_hour_n", "b_same_host_6h", "b_same_word_6h", "text_score", "b_title_len",
       "b_title_words", "b_question", "b_show_hn", "b_ask_hn", "b_author_n", "b_author_mean", "b_author_max",
       "b_author_top10_rate", "b_sub_comments_before", "b_sub_days_since_first_comment"]


def main():
    p = H.stories()
    p = p[(p.day >= "2025-01-15") & (p.day <= "2026-10-14")]
    p = p.assign(key=p.url.map(FA.norm))
    p = p[p.key.notna() & (p.key.str.len() > 8)].sort_values("created_at_i")
    L = OL.lists()
    win = set(L[L["rank"] <= 30].post_id)
    p["y"] = p.post_id.isin(win).astype(int)
    pairs = []
    for k, g in p.groupby("key"):
        if len(g) < 2:
            continue
        t, y, ids = g.created_at_i.to_numpy(), g.y.to_numpy(), g.post_id.to_numpy()
        for i in range(len(g) - 1):
            if t[i + 1] - t[i] >= 86400 and y[i] != y[i + 1]:
                pairs.append((ids[i], ids[i + 1], g.day.iat[i + 1]))
    P = pd.DataFrame(pairs, columns=["a", "b", "day"])
    ids = set(P.a) | set(P.b) | set(C.Q.post_id)
    B = pd.read_parquet(os.path.join(H.CACHE, "daily_cache.parquet"))
    B = B[B.post_id.isin(ids)][["post_id", "text_score"] + [c for c in CTX if c.startswith("b_")]].drop_duplicates("post_id")
    R = LV.record(H.stories(), ids)
    RA = [c for c in R.columns if c.startswith("ra_")]
    F = B.merge(R[["post_id"] + RA], on="post_id", how="left").set_index("post_id")
    cols = CTX + RA
    y_of = p.set_index("post_id").y
    tr_pairs = P[P.day < "2026-07-01"]
    ho_pairs = P[P.day >= "2026-07-01"]
    print(f"informative same-link pairs: train {len(tr_pairs)} (to Jun 30), held out {len(ho_pairs)} (Jul-Oct)", flush=True)

    def stack(PP):
        ids_ = np.ravel(PP[["a", "b"]].to_numpy())
        X = F.reindex(ids_)[cols]
        return X, y_of.reindex(ids_).to_numpy(), [2] * len(PP)
    Xt, yt, gt = stack(tr_pairs)
    rk = lgb.LGBMRanker(objective="lambdarank", n_estimators=400, learning_rate=0.03, num_leaves=15, min_child_samples=40,
                        subsample=0.8, subsample_freq=1, colsample_bytree=0.8, verbose=-1, random_state=0).fit(Xt, yt, group=gt)
    Xh, yh, _ = stack(ho_pairs)
    sh = rk.predict(Xh).reshape(-1, 2)
    yh = yh.reshape(-1, 2)
    acc = ((sh[:, 0] > sh[:, 1]) == (yh[:, 0] == 1)).mean()
    print(f"held-out pairs: the winning posting scored higher in {acc:.1%} (chance 50%)", flush=True)
    imp = pd.Series(rk.feature_importances_, index=cols).sort_values(ascending=False)
    print("top context inputs:", imp.head(8).to_dict(), flush=True)
    Q = C.Q
    Q["ctx_score"] = rk.predict(F.reindex(Q.post_id)[cols])
    C.Q = Q
    full = C.POST + C.KNN + C.EMB + C.CROWD
    s0, s1 = C.model(full), C.model(full + ["ctx_score"])
    a0, a1 = C.caught(s0), C.caught(s1)
    print(f"Caught at posting, Jul-Aug model: without {C.ci(a0)}; + same-link context score {C.ci(a1)}; difference {C.diff(a1, a0)}", flush=True)
    h = np.load(os.path.join(H.CACHE, "caught_hist2_test_scores.npy"))
    rkp = lambda x: pd.Series(x).rank(pct=True).to_numpy()
    b0, b1 = C.caught(0.5 * rkp(s0) + 0.5 * rkp(h)), C.caught(0.5 * rkp(s1) + 0.5 * rkp(h))
    print(f"Caught at posting, blend with the 2025+ model: without {C.ci(b0)}; with {C.ci(b1)}; difference {C.diff(b1, b0)}", flush=True)
    c = C.caught(Q.ctx_score[C.te].to_numpy())
    print(f"context score alone: {C.ci(c)}", flush=True)


if __name__ == "__main__":
    main()
