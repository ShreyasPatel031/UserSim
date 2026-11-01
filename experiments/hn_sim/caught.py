"""North star: Caught at posting. Each post is scored at its posting moment with only what is known then (title, URL,
submitter, time, its domain / author record, outside signals before posting; no votes or comments of the post).
Winners = posts that made any daily top 30 (any day). Flag as many test posts as there are winners (highest scores
across the test period); Caught = winners flagged / all winners (ceiling 100%; re-ups count at their posting time).
Holdout: posts Sep 1 - Oct 14; model fit on posts Jul 1 - Aug 31; 95% bootstrap interval resampling posting days.
Extras (labelled as including early votes): the same ranking with each post's score at 15 min / 1 h / 3 h of age.
Input sets (levers) are scored with and without, paired by day.

    python caught.py            # the current at-posting inputs, ceiling, extras
    python caught.py levers     # each lever with and without (needs levers.py and TIES_POST_ONLY=1 ties.py)
"""
import json
import os
import sys

import lightgbm as lgb
import numpy as np
import pandas as pd

import fine_io
import odds_live as OL
import top100 as H

rng = np.random.default_rng(0)
p = H.stories()
q = p[(p.day >= "2026-07-01") & (p.day <= "2026-10-14")].reset_index(drop=True)
B = pd.read_parquet(os.path.join(H.CACHE, "daily_cache.parquet"))
bcols = [x for x in B.columns if x.startswith("b_") and not x.startswith(("b_w30_", "b_w60_"))]
B = B[["post_id", "text_score"] + bcols].drop_duplicates("post_id")
A = pd.read_parquet(os.path.join(H.CACHE, "audience_feats.parquet"))
F2 = pd.read_parquet(os.path.join(H.CACHE, "crowd_v2_feats.parquet"))
Q = q.merge(B, on="post_id", how="left").merge(A, on="post_id", how="left").merge(F2, on="post_id", how="left")
L = OL.lists().sort_values("rank").drop_duplicates(["day", "post_id"])
real = L[L["rank"] <= 30].groupby("day").post_id.apply(set)
POST = ["text_score"] + bcols
KNN = ["knn_lp", "knn_100", "knn_t30", "knn_sim"]
EMB = [f"emb{j}" for j in range(64)]
CROWD = ["aud_sum", "aud_cube", "aud_fans", "scout_sum", "scout_cube", "scout_fans", "fans_any", "top50_sim", "c2_sum", "c2_scout", "c2_top50", "c2_n20"]
Q["y"] = Q.post_id.isin(set(L[L["rank"] <= 30].post_id)).astype(int)     # made any daily top 30 (training label)
fit, te = (Q.day < "2026-09-01").to_numpy(), (Q.day >= "2026-09-01").to_numpy()


def caught(scores, mask=None):
    """North star (user, 2026-11-01): every test post judged once at its posting moment; winners = posts that made any
    daily top 30; flag as many posts as there are winners (highest at-posting scores across the test period).
    Returns per posting day: (winners flagged, winners)."""
    T = Q[te].assign(s=scores)
    if mask is not None:                                   # mask over the test rows (series-only sensitivity)
        T = T[mask]
    k = int(T.y.sum())
    T["flag"] = T.s.rank(ascending=False, method="first") <= k
    g = T.groupby("day")
    return pd.DataFrame({"hit": g.apply(lambda x: int((x.flag & (x.y == 1)).sum())), "n": g.y.sum()})


def boot_idx(n):
    return [rng.integers(0, n, n) for _ in range(2000)]


BOOT = None


def ci(c):
    """Caught = winners flagged / winners; 95% interval resampling posting days."""
    global BOOT
    BOOT = BOOT or boot_idx(len(c))
    h, n = c.hit.to_numpy(), c.n.to_numpy()
    b = [h[i].sum() / n[i].sum() for i in BOOT]
    return f"{h.sum() / n.sum():.1%} [{np.percentile(b, 2.5):.1%}, {np.percentile(b, 97.5):.1%}]"


def diff(c, ref):
    h, n, h0 = c.hit.to_numpy(), c.n.to_numpy(), ref.hit.to_numpy()
    b = [(h[i].sum() - h0[i].sum()) / n[i].sum() for i in BOOT]
    return f"{(h.sum() - h0.sum()) / n.sum():+.1%} [{np.percentile(b, 2.5):+.1%}, {np.percentile(b, 97.5):+.1%}]"


def honest(V, a, ids, how="const"):
    """Quality News series were fetched only for posts that ended with 5+ points, so a missing series reveals the
    outcome. Posts without a series get votes at age a imputed as: "const" (headline, outcome-free) 1 point at every
    age; "ramp" 1 + (final - 1) * min(1, a / 60) (final < 5; uses the outcome, sensitivity only); "max" the final
    points. Always rank 91 (not on the front page). The exposure-based rate (only in series) is dropped for everyone."""
    V = V.drop(columns=[c for c in ("rate",) if c in V]).copy()
    miss = ~Q.post_id.isin(ids).to_numpy()
    fp = Q.points.to_numpy(float)
    if how == "const":
        fp = np.ones_like(fp)
    imp = 1 + (fp - 1) * min(1.0, a / 60) if how == "ramp" else fp
    imp30 = 1 + (fp - 1) * min(1.0, max(a - 30, 0) / 60) if how == "ramp" else fp
    V.loc[miss, "points"] = imp[miss]
    V.loc[miss, "rank_now"], V.loc[miss, "best_rank"] = 91, 91
    V.loc[miss, "gain30"] = (imp - imp30)[miss]
    return V


def model(cols, extra=None, rows=None):
    X = Q[cols] if extra is None else pd.concat([Q[cols], extra], axis=1)
    if rows is not None:                                   # train only on these rows (series-only sensitivity)
        m = lgb.LGBMClassifier(n_estimators=600, learning_rate=0.03, num_leaves=31, min_child_samples=30, subsample=0.8,
                               subsample_freq=1, colsample_bytree=0.8, verbose=-1, random_state=0).fit(X[fit & rows], Q.y[fit & rows])
        return m.predict_proba(X[te])[:, 1]
    m = lgb.LGBMClassifier(n_estimators=600, learning_rate=0.03, num_leaves=31, min_child_samples=30, subsample=0.8,
                           subsample_freq=1, colsample_bytree=0.8, verbose=-1, random_state=0).fit(X[fit], Q.y[fit])
    return m.predict_proba(X[te])[:, 1]


def levers():
    """Each lever with and without, paired by day, on top of the current at-posting inputs."""
    global Q
    Lv = pd.read_parquet(os.path.join(H.CACHE, "caught_levers.parquet"))
    T = pd.read_parquet(os.path.join(H.CACHE, "tie_post_feats.parquet"))
    Q = Q.merge(Lv, on="post_id", how="left").merge(T, on="post_id", how="left")
    REC = [c for c in Lv.columns if c.startswith(("rd_", "rs_", "ra_"))]
    FEED = [c for c in Lv.columns if c.startswith("fd_")]
    FIT = [c for c in Lv.columns if c.startswith("af_")]
    TIES = [c for c in T.columns if c != "post_id"]
    OLD_REC = [c for c in POST if c.startswith(("b_author_", "b_domain_"))]
    OLD_SUB = [c for c in POST if c.startswith("b_sub_")]
    full = POST + KNN + EMB + CROWD
    base = caught(model(full))
    print(f"current at posting: {ci(base)}", flush=True)

    def vs(name, cols, ref, ref_s):
        s = caught(model(cols))
        print(f"  {name:62s} {ci(s)}  difference {diff(s, ref_s)}", flush=True)
        return s
    print("1. submitter history and network", flush=True)
    vs("without submitter history (b_sub_*, b_author_*)", [c for c in full if c not in OLD_SUB + OLD_REC[:4]], "current", base)
    vs("+ tie network (ties.py)", full + TIES, "current", base)
    print("2. domain and author track record", flush=True)
    vs("without any domain / author record", [c for c in full if c not in OLD_REC], "current", base)
    vs("+ record on the real daily list (domain, site, author)", full + REC, "current", base)
    print("3. outside feeds before posting", flush=True)
    vs("+ feeds (own link seen before posting, domain buzz)", full + FEED, "current", base)
    print("4. title / topic fit with that day's audience", flush=True)
    vs("+ day fit (6 h comment topics, previous 2 days' top 30, nearest post)", full + FIT, "current", base)
    print("all levers", flush=True)
    vs("+ all four", full + TIES + REC + FEED + FIT, "current", base)
    print(f"feeds coverage: posts with own link in a feed before posting {(Q[te].fd_n > 0).mean():.1%}; "
          f"among real top 30 {(Q[te & (Q.y == 1).to_numpy()].fd_n > 0).mean():.1%}", flush=True)


def simvotes():
    """Person simulation -> expected early votes, used at posting. Stage 1 predicts the post's points and best rank at
    15 / 60 min from what is known at posting: the simulated audience (crowd v1/v2: /new browsers and readers online at
    that hour, their taste vs the title), the submitter's tie network, the day's topic fit, plus post features.
    Out-of-fold on the fit period (5 blocks of days), fit-period model for the test. Stage 2 adds the predicted early
    votes to the at-posting classifier; Caught with and without, paired by day."""
    global Q
    from scipy.stats import spearmanr
    Lv = pd.read_parquet(os.path.join(H.CACHE, "caught_levers.parquet"))
    T = pd.read_parquet(os.path.join(H.CACHE, "tie_post_feats.parquet"))
    Q = Q.merge(Lv, on="post_id", how="left").merge(T, on="post_id", how="left")
    SIM = CROWD + [c for c in T.columns if c != "post_id"] + [c for c in Lv.columns if c.startswith("af_")]
    _, qs = fine_io.load()
    q_by_id = {r.post_id: {"qn_f0": r.qn_f0, "qn_rank_10m": r.qn_rank_10m, "qn_up_10m": r.qn_up_10m, "qn_exp_10m": r.qn_exp_10m}
               for r in qs.itertuples()}
    V = OL.vote_feats(Q, q_by_id, [15, 60])
    days = np.array(sorted(set(Q.day[fit])))
    block = pd.Series(np.arange(len(days)) * 5 // len(days), index=days)
    fold = Q.day.map(block).to_numpy()
    full = POST + KNN + EMB + CROWD
    base = caught(model(full))
    print(f"current at posting: {ci(base)}", flush=True)
    for inputs_name, X_cols in (("simulated audience only", SIM), ("simulated audience + post", list(dict.fromkeys(full + SIM)))):
        preds = {}
        for a in (15, 60):
            for tgt in ("points", "best_rank"):
                y = np.log1p(V[a][tgt].to_numpy()) if tgt == "points" else -np.log1p(V[a][tgt].fillna(999).to_numpy())
                ok = ~np.isnan(y)
                pr = np.full(len(Q), np.nan)
                reg = dict(n_estimators=400, learning_rate=0.05, num_leaves=31, min_child_samples=30, subsample=0.8,
                           subsample_freq=1, colsample_bytree=0.8, verbose=-1, random_state=0)
                for f in range(5):
                    tr_ = fit & ok & (fold != f)
                    pr[fit & (fold == f)] = lgb.LGBMRegressor(**reg).fit(Q.loc[tr_, X_cols], y[tr_]).predict(Q.loc[fit & (fold == f), X_cols])
                pr[te] = lgb.LGBMRegressor(**reg).fit(Q.loc[fit & ok, X_cols], y[fit & ok]).predict(Q.loc[te, X_cols])
                m_ = te & ok
                print(f"  [{inputs_name}] predicted {tgt} at {a} min vs real (test, Spearman): {spearmanr(pr[m_], y[m_])[0]:.3f}", flush=True)
                preds[f"sim_{tgt}_{a}"] = pr
        P = pd.DataFrame(preds, index=Q.index)
        s = caught(model(full, P))
        print(f"  + expected early votes from {inputs_name:28s} {ci(s)}  difference {diff(s, base)}", flush=True)


def history():
    """More training history: post features + real-list record, trained on posts from 2025-01-15 / 2026-01-01 /
    2026-07-01 up to Aug 31 (the lists start 2025-01). Same test posts and metric."""
    import levers as LV
    pa = H.stories()
    pa = pa[(pa.day >= "2025-01-15") & (pa.day <= "2026-10-14")].reset_index(drop=True)
    R = LV.record(H.stories(), set(pa.post_id))
    Bh = pd.read_parquet(os.path.join(H.CACHE, "daily_cache.parquet"))[["post_id", "text_score"] + bcols].drop_duplicates("post_id")
    Qh = pa[["post_id", "day"]].merge(Bh, on="post_id", how="left").merge(R, on="post_id", how="left")
    Qh["y"] = Qh.post_id.isin(set(L[L["rank"] <= 30].post_id)).astype(int)
    REC = [c for c in R.columns if c != "post_id"]
    test_ids = Q.post_id[te]
    Xte = Qh.set_index("post_id").reindex(test_ids)
    ref = None
    for start in ("2026-07-01", "2026-01-01", "2025-01-15"):
        for name, cols in (("post", POST), ("post + real-list record", POST + REC)):
            tr_ = Qh[(Qh.day >= start) & (Qh.day < "2026-09-01")]
            m = lgb.LGBMClassifier(n_estimators=800, learning_rate=0.03, num_leaves=63, min_child_samples=50, subsample=0.8,
                                   subsample_freq=1, colsample_bytree=0.8, verbose=-1, random_state=0).fit(tr_[cols], tr_.y)
            s = caught(m.predict_proba(Xte[cols])[:, 1])
            ref = s if ref is None else ref
            print(f"  train from {start} ({len(tr_)} posts, {int(tr_.y.sum())} winners), {name:24s} {ci(s)}  vs first {diff(s, ref)}", flush=True)


if __name__ == "__main__" and "history" in sys.argv[1:]:
    history()
elif __name__ == "__main__" and "levers" in sys.argv[1:]:
    levers()
elif __name__ == "__main__" and "simvotes" in sys.argv[1:]:
    simvotes()
elif __name__ == "__main__":
    full = POST + KNN + EMB + CROWD
    base = caught(model(full))
    print(f"test posts {te.sum()}, winners {int(base.n.sum())} over {len(base)} posting days; flags = winners", flush=True)
    print(f"Caught at posting: {ci(base)}  (random flags: {base.n.sum() / te.sum():.1%})", flush=True)
    for name, cols in (("post features only", POST), ("+ similar past titles", POST + KNN), ("+ embedding", POST + KNN + EMB)):
        s = caught(model(cols))
        print(f"  {name:28s} {ci(s)}  vs full {diff(s, base)}", flush=True)
    _, qs = fine_io.load()
    q_by_id = {r.post_id: {"qn_f0": r.qn_f0, "qn_rank_10m": r.qn_rank_10m, "qn_up_10m": r.qn_up_10m, "qn_exp_10m": r.qn_exp_10m}
               for r in qs.itertuples()}
    V = OL.vote_feats(Q, q_by_id, [15, 60, 180])
    ids = set(q_by_id)
    from sklearn.metrics import roc_auc_score
    has = Q.post_id.isin(ids).to_numpy()
    print(f"series coverage: test posts {has[te].mean():.1%}, test winners {has[te & (Q.y == 1).to_numpy()].mean():.1%}", flush=True)
    for a, label in ((15, "15 min"), (60, "1 h"), (180, "3 h")):
        out = []
        for how in ("rank-only", "const", "ramp"):
            Vh = honest(V[a], a, ids, "const")
            if how == "rank-only":                     # points dropped: a post ending < 5 points is truly off the front page
                Vh = Vh[["rank_now", "best_rank"]]
            else:
                Vh = honest(V[a], a, ids, how)
            s = caught(model(full, Vh))
            lk = lgb.LGBMClassifier(n_estimators=200, verbose=-1).fit(Vh[fit], has[fit])
            auc = roc_auc_score(has[te], lk.predict_proba(Vh[te])[:, 1])
            out.append(f"{how} imputation {ci(s)} (leak check AUC {auc:.3f})")
        so = caught(model(full, V[a].drop(columns="rate"), rows=has), mask=has[te])
        out.append(f"series-only {ci(so)}")
        print(f"Caught at {label}: " + "; ".join(out), flush=True)
