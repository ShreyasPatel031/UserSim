"""Checkpoints 1 and 2 (1 h, 15 min) with honest early votes: Wayback captures of news.ycombinator.com/newest (Grok Bot,
raw/hn_early_votes/early_snapshots.jsonl). /newest lists every new story whatever its outcome, so having a snapshot
does not depend on the result (unlike the Quality News 5+ point fetch). Verified: created_at on the page equals
BigQuery's for 100% of rows (within 60 s); early score <= final points for 99.99%.

Inputs at age a (each post judged once, a minutes after posting):
  at posting   post features, similar titles, embedding, crowd, history score (hist_prior: trained to Jun 30)
  honest       rank on the front page so far (Quality News; a post ending < 5 points is truly off it), comments by a
  early votes  the latest /newest snapshot at or before a: score, rank on /newest, comments, its age, votes per minute,
               best /news rank seen in Wayback captures of /news p1-3;
               none = no snapshot yet (a Wayback timing accident, not the outcome)
Two tests, each with and without early votes, paired by day, flags = winners in the test set:
  A  train Jul 1 - Sep 30 (6-10% of posts have a snapshot), test Oct 2-14 (dense captures)
  B  train Jul 1 - Oct 8, test Oct 9-14 (more snapshot posts in training)
Caveat: lists are known to Oct 16, so a late re-up of an Oct 13-14 post is not yet labelled.

    python wb_caught.py
"""
import os

import lightgbm as lgb
import numpy as np
import pandas as pd

import caught as C
import fine_io
import odds_live as OL
import top100 as H

rng = np.random.default_rng(0)
EV = os.path.join(H.CACHE, "early_votes", "early_snapshots.jsonl")
_cov = __import__("json").load(open(os.path.join(H.CACHE, "early_votes", "coverage_oct_daily.json")))
GOOD = {d for d, v in _cov.items() if v.get("pct_lt60", 0) >= 90}


def early(Q, a):
    A = pd.read_json(EV, lines=True, convert_dates=False)
    A = A[(A.age_min <= a) & (A.age_min >= 0)]
    E = A[A.page == "newest"].sort_values("age_min")
    off = {"news": 0, "news_p2": 0, "news_p3": 0}     # Wayback rank is already the position (news_p2 = 31-60); no page offset
    F = A[A.page.isin(off)]
    front = (F["rank"] + F.page.map(off)).groupby(F.item_id).min()      # best /news rank seen by age a (Wayback)
    last = E.drop_duplicates("item_id", keep="last").set_index("item_id")
    out = pd.DataFrame(index=Q.index)
    m = Q.post_id.map(last.score)
    out["ev_has"] = m.notna().astype(int)
    out["ev_score"] = m
    out["ev_rank_new"] = Q.post_id.map(last["rank"])
    out["ev_comments"] = Q.post_id.map(last.comments)
    out["ev_age"] = Q.post_id.map(last.age_min)
    out["ev_rate"] = (out.ev_score - 1) / out.ev_age.clip(lower=1)
    out["ev_front_best"] = Q.post_id.map(front)
    return out


def comments_by(Q, a):
    c = pd.read_parquet(os.path.join(H.CACHE, "bq_comments.parquet"), columns=["story_id", "created_at_i"])
    born = Q.set_index("post_id").created_at_i
    c = c[c.story_id.isin(born.index)]
    lat = c.created_at_i - c.story_id.map(born).to_numpy()
    n = c[(lat >= 0) & (lat < a * 60)].groupby("story_id").size()
    return pd.DataFrame({"cm_n": Q.post_id.map(n).fillna(0).to_numpy()}, index=Q.index)


def caught_on(T, s):
    T = T.assign(s=s)
    k = int(T.y.sum())
    T["flag"] = T.s.rank(ascending=False, method="first") <= k
    g = T.groupby("day")
    return pd.DataFrame({"hit": g.apply(lambda x: int((x.flag & (x.y == 1)).sum())), "n": g.y.sum()})


def ci2(c, ref=None):
    h, n = c.hit.to_numpy(), c.n.to_numpy()
    idx = [rng.integers(0, len(c), len(c)) for _ in range(2000)]
    if ref is None:
        b = [h[i].sum() / n[i].sum() for i in idx]
        return f"{h.sum() / n.sum():.1%} [{np.percentile(b, 2.5):.1%}, {np.percentile(b, 97.5):.1%}]"
    h0 = ref.hit.to_numpy()
    b = [(h[i].sum() - h0[i].sum()) / n[i].sum() for i in idx]
    return f"{(h.sum() - h0.sum()) / n.sum():+.1%} [{np.percentile(b, 2.5):+.1%}, {np.percentile(b, 97.5):+.1%}]"


def main():
    Q = C.Q.merge(pd.read_parquet(os.path.join(H.CACHE, "hist_prior.parquet")), on="post_id", how="left")
    AT = C.POST + C.KNN + C.EMB + C.CROWD + ["hist_prior"]
    _, qs = fine_io.load()
    q_by_id = {r.post_id: {"qn_f0": r.qn_f0, "qn_rank_10m": r.qn_rank_10m, "qn_up_10m": r.qn_up_10m, "qn_exp_10m": r.qn_exp_10m}
               for r in qs.itertuples()}
    prm = dict(n_estimators=600, learning_rate=0.03, num_leaves=31, min_child_samples=30, subsample=0.8, subsample_freq=1,
               colsample_bytree=0.8, verbose=-1, random_state=0)
    for a, label in ((15, "15 min"), (60, "1 h")):
        R = C.honest(OL.vote_feats(Q, q_by_id, [a])[a], a, set(q_by_id))[["rank_now", "best_rank"]]
        X0 = pd.concat([Q[AT], R, comments_by(Q, a)], axis=1)
        E = early(Q, a)
        X1 = pd.concat([X0, E], axis=1)
        for name, tr_end, te_from in (("A: train Jul-Sep, test Oct 2-14", "2026-10-01", "2026-10-02"),
                                      ("B: train Jul 1-Oct 8, test Oct 9-14", "2026-10-09", "2026-10-09")):
            tr = (Q.day < tr_end).to_numpy()
            te = (Q.day >= te_from).to_numpy()
            T = Q[te][["post_id", "day", "y"]]
            cov = E.ev_has[te]
            s0 = lgb.LGBMClassifier(**prm).fit(X0[tr], Q.y[tr]).predict_proba(X0[te])[:, 1]
            s1 = lgb.LGBMClassifier(**prm).fit(X1[tr], Q.y[tr]).predict_proba(X1[te])[:, 1]
            print(f"{label} | {name}: test posts {te.sum()}, winners {int(T.y.sum())}; with a /newest snapshot by {label}: "
                  f"posts {cov.mean():.1%}, winners {cov[(T.y == 1).to_numpy()].mean():.1%}; training posts with one "
                  f"{E.ev_has[tr].mean():.1%}", flush=True)
            for sub, keep in (("all days", np.ones(len(T), bool)), ("days with 90%+ /newest coverage", T.day.isin(GOOD).to_numpy())):
                c0, c1 = caught_on(T[keep], s0[keep]), caught_on(T[keep], s1[keep])
                print(f"   {sub} ({T[keep].day.nunique()} days, {int(T.y[keep].sum())} winners): without early votes {ci2(c0)}; "
                      f"with {ci2(c1)}; difference {ci2(c1, c0)}", flush=True)


if __name__ == "__main__":
    main()
