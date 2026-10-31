"""18:00 UTC experiments on the cached v4 table (fully fetched days): add post / submitter / domain history inputs
from daily_cache.parquet (all known at posting time: hour, weekday, title, the submitter's and the domain's past
results, who commented in the first 30/60 min), and compare ranking objectives.

    python v4_t18.py [split=2026-09-01] [times=t18]
"""
import json
import os
import sys

import lightgbm as lgb
import numpy as np
import pandas as pd

import daily_v4 as V
import fine_io
import top100 as H

SPLIT = sys.argv[1] if len(sys.argv) > 1 else "2026-09-01"
TS = (sys.argv[2] if len(sys.argv) > 2 else "t18").split(",")
C = pd.read_parquet(os.path.join(H.CACHE, "daily_v4.parquet"))
q_all = fine_io.load()[0]
got = set(q_all.post_id[q_all.status.isin([200, 404])])
p = H.stories()
p5 = p[p.points >= 5]
ok = {d for d in C.day.unique() if p5[(p5.created_at_i >= pd.Timestamp(d, tz="UTC").timestamp() - 6 * 86400)
                                      & (p5.created_at_i < pd.Timestamp(d, tz="UTC").timestamp() + 86400)].post_id.isin(got).mean() >= 0.97}
C = C[C.day.isin(ok)]
B = pd.read_parquet(os.path.join(H.CACHE, "daily_cache.parquet"))
bcols = [c for c in B.columns if c.startswith("b_")]
B = B[["post_id"] + bcols].drop_duplicates("post_id")
C = C.merge(B, on="post_id", how="left")
POST = ["b_hour", "b_dow", "b_title_len", "b_title_words", "b_show_hn", "b_ask_hn", "b_no_url", "b_github", "b_pdf",
        "b_ai", "b_open_source", "b_i_built", "b_same_url_7d", "b_same_host_6h", "b_same_word_6h"]
WHO = ["b_author_n", "b_author_mean", "b_author_max", "b_author_top10_rate", "b_domain_n", "b_domain_mean",
       "b_domain_max", "b_domain_top10_rate", "b_sub_comments_before"]
EARLY = [c for c in bcols if c.startswith(("b_w30_", "b_w60_"))]


def fit(tr, cols, obj="lambdarank", seed=0):
    tr = tr.sort_values("day", kind="stable")
    grp = tr.groupby("day", sort=False).size().to_numpy()
    return lgb.LGBMRanker(objective=obj, n_estimators=400, learning_rate=0.05, num_leaves=15, min_child_samples=10,
                          subsample=0.8, subsample_freq=1, colsample_bytree=0.8, verbose=-1, random_state=seed,
                          label_gain=list(range(31))).fit(tr[cols], np.clip(31 - tr.real_rank, 0, 30).astype(int), group=grp)


def sc(te, s):
    r = V.score(te.assign(s=np.where(te.on_earlier_list == 1, -1e9, s)), "s")
    return {k.replace("real", "").replace("_in_", " in "): [round(x, 3) for x in v] for k, v in r.items() if k != "real10_in_top30"}


if __name__ == "__main__":
    for t in TS:
        D = C[C[f"{t}_visible"] == 1]
        tr, te = D[D.day < SPLIT], D[D.day >= SPLIT]
        base = ["on_earlier_list", "text_score"] + [f"{t}_{c}" for c in list(V.VC) + ["stage1", "c_all", "c_last3h"]]
        print(f"{t}: train {tr.day.nunique()} days, test {te.day.nunique()} days", flush=True)
        runs = {
            "1 v4 lambdarank (current)": lambda: fit(tr, base).predict(te[base]),
            "2 + post time / title": lambda: fit(tr, base + POST).predict(te[base + POST]),
            "3 + submitter & domain history": lambda: fit(tr, base + WHO).predict(te[base + WHO]),
            "4 + early commenters (30/60 min)": lambda: fit(tr, base + EARLY).predict(te[base + EARLY]),
            "5 + all of 2-4": lambda: fit(tr, base + POST + WHO + EARLY).predict(te[base + POST + WHO + EARLY]),
            "6 rank_xendcg objective": lambda: fit(tr, base, "rank_xendcg").predict(te[base]),
            "7 binary classifier": lambda: lgb.LGBMClassifier(n_estimators=400, learning_rate=0.05, num_leaves=15,
                                                              min_child_samples=10, subsample=0.8, subsample_freq=1,
                                                              colsample_bytree=0.8, verbose=-1, random_state=0)
            .fit(tr[base], tr.real_rank <= 30).predict_proba(te[base])[:, 1],
        }
        for name, f in runs.items():
            print(f"  {name:34s}", json.dumps(sc(te, f())), flush=True)
