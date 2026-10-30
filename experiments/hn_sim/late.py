"""Late bloomers: a fifth of the real top-10 stories have no comments in their first hour and take off later
(second-chance pool, delayed shares). An hourly-refreshed daily forecast can see longer windows for older stories.
Builds early blocks for 2 / 4 / 8 hours (comments, top-level, distinct people, time of first comment; plus comments
in the latest hour of the window = current momentum) and scores them on the scoreboard months.

What a window means live: a story is scored with window W only once it is W old, so the W-hour row answers
"forecast made W hours after each story was posted". Reported per window so the trade-off is explicit.

    python late.py build
    python late.py run
"""
import json
import os
import sys

import lightgbm as lgb
import numpy as np
import pandas as pd

import rank as R
import store as S
import top10 as T
import top100 as H

WINS = (120, 240, 480)


def build():
    p = H.stories()
    c = H.comments()
    born = pd.Series(p.created_at_i.to_numpy(), index=p.post_id)
    c = c[c.story_id.isin(born.index)]
    c["age"] = c.created_at_i - c.story_id.map(born).to_numpy()
    c = c[c.age >= 0]
    for W in WINS:
        e = c[c.age <= W * 60]
        g = e.groupby("story_id")
        last = e[e.age > (W - 60) * 60].groupby("story_id").size()
        blk = pd.DataFrame({f"e{W}_all": g.size(), f"e{W}_top": g.top_level.sum(), f"e{W}_people": g.person.nunique(),
                            f"e{W}_first_s": g.age.min(), f"e{W}_lasthour": last})
        blk = blk.reindex(p.post_id)
        blk[f"e{W}_first_s"] = blk[f"e{W}_first_s"].fillna(W * 120)
        blk = blk.fillna(0).reset_index().rename(columns={"story_id": "post_id", "index": "post_id"})
        blk.to_parquet(os.path.join(H.CACHE, f"f_early{W}.parquet"), index=False)
        print("built", W, flush=True)


def run():
    H.BLOCK_FILES.update({f"early{W}": f"f_early{W}" for W in WINS})
    p = H.stories()
    p = p[(p.month >= "2023-03") & (p.month <= H.TEST[-1])].reset_index(drop=True)
    y = np.log1p(p.points.to_numpy())
    rk = p.groupby("day").points.rank(ascending=False, method="first").to_numpy()
    names = ["post", "early30", "who30", "early60", "who60", "submitter"] + [f"early{W}" for W in WINS]
    blk = {b: pd.read_parquet(os.path.join(H.CACHE, H.BLOCK_FILES[b] + ".parquet")).drop_duplicates("post_id")
           .set_index("post_id").reindex(p.post_id).reset_index(drop=True) for b in names}
    keep = (rk <= 100) | (np.random.default_rng(0).random(len(p)) < 0.25)
    texts = {m: T.text_scores(p, y, (p.month < m).to_numpy(), (p.month == m).to_numpy()) for m in H.TEST}
    rng = np.random.default_rng(0)
    rows = []
    base = ["post", "early30", "who30", "early60", "who60", "submitter"]
    for name, cols in (("60 min (base)", base), ("2 h", base + ["early120"]), ("4 h", base + ["early120", "early240"]),
                       ("8 h", base + ["early120", "early240", "early480"])):
        X = pd.concat([blk[b] for b in cols], axis=1)
        res = []
        for m in H.TEST:
            tr, te = (p.month < m).to_numpy(), (p.month == m).to_numpy()
            oof, txt = texts[m]
            c = lgb.LGBMClassifier(**{**H.GBM, "n_jobs": 4, "scale_pos_weight": 2})
            c.fit(X[tr].assign(text_score=oof)[keep[tr]], (rk[tr & keep] <= 100).astype(int))
            res.append(pd.DataFrame({"day": p.day[te].to_numpy(), "y": y[te],
                                     "s": c.predict_proba(X[te].assign(text_score=txt))[:, 1]}))
        P = pd.concat(res, ignore_index=True)
        r = {k: R.boot(T.day_hits(P, "s", k, rng)) for k in (100, 30, 10)}
        rows += [{"kind": "ladder", "variant": f"forecast age {name}", "k": k, "recall": v[0], "lo": v[1], "hi": v[2],
                  "data": "bq2023", "test": f"{H.TEST[0]}..{H.TEST[-1]}", "days": int(P.day.nunique()), "made_on": S.now()}
                 for k, v in r.items()]
        print(name, json.dumps(r), flush=True)
    S.write("hn_scores", pd.DataFrame(rows))


if __name__ == "__main__":
    {"build": build, "run": run}[sys.argv[1]]()
