"""North star stage 1: Caught at 1 h after posting (per-post definition, caught.py), pushed with first-hour levers.
Each post is judged once, 60 min after its posting, with everything known by then. Same test posts, flags and
95% day intervals as caught.py; each lever with and without, paired by day.

Levers (all from the first 60 min, or person histories before Jul 1; posts without a Quality News series are
imputed as small posts, caught.honest, since a missing series reveals final points < 5):
  curve     the vote curve: points and rank at 10..60 min, front-page entry time, acceleration (last 20 min vs first
            40), points per expected view (Quality News exp), rank trajectory
  comments  comment velocity (by 15 / 30 / 60 min, last 20 min), commenters, first-comment delay, top-level share
  who       who comments early: each commenter's record before Jul 1 (share of stories they commented on within the
            first hour that made a daily top 30), mean / max / count of proven scouts among this post's commenters
  mech      HN ranking mechanics: gravity score (points-1)/(age_h+2)^1.8, rank vs what gravity predicts (penalty
            residual), off the front page despite points (likely flagged / penalised)
  outside   the link's mentions in outside feeds during its first hour (feeds_anticipate backfill)

    python caught1h.py
"""
import os

import numpy as np
import pandas as pd

import caught as C
import fine_io
import odds_live as OL
import top100 as H

A_MIN = int(os.environ.get("AGE_MIN", "60"))
CUT = pd.Timestamp("2026-07-01", tz="UTC").timestamp()
Q = C.Q
full = C.POST + C.KNN + C.EMB + C.CROWD


def curve(a):
    _, qs = fine_io.load()
    by = {r.post_id: r for r in qs.itertuples()}
    steps = list(range(10, a + 1, 10))
    rows = []
    for pid, born, fp in zip(Q.post_id, Q.created_at_i, Q.points.astype(float)):
        s = by.get(pid)
        # no series = the post ended with < 5 points (series were fetched only for 5+): constant 1 point, off the
        # front page, at every age (outcome-free; see caught.honest)
        r = {f"cv_p{m}": 1.0 for m in steps} | {f"cv_r{m}": 91 for m in steps}
        r |= {"cv_front_min": 999.0, "cv_top10_min": 999.0, "cv_n_front": 0}
        if s is not None:
            up = pd.Series(s.qn_up_10m, dtype=float).ffill().fillna(1).to_numpy()
            rk = np.array([x if x is not None else 91 for x in s.qn_rank_10m], float)
            ex = pd.Series(s.qn_exp_10m, dtype=float).ffill().fillna(0).to_numpy()
            for m in steps:
                k = int(np.clip((born + m * 60 - s.qn_f0) // 600, 0, len(up)))
                r[f"cv_p{m}"] = up[k - 1] if k > 0 else 1
                r[f"cv_r{m}"] = rk[k - 1] if k > 0 else 91
            k = int(np.clip((born + a * 60 - s.qn_f0) // 600, 0, len(up)))
            seen = rk[:k]
            r["cv_front_min"] = float((np.argmax(seen <= 30) + 1) * 10) if k and (seen <= 30).any() else 999.0
            r["cv_top10_min"] = float((np.argmax(seen <= 10) + 1) * 10) if k and (seen <= 10).any() else 999.0
            r["cv_n_front"] = int((seen <= 30).sum())
        rows.append(r)
    D = pd.DataFrame(rows, index=Q.index)
    p_last, p_mid, p_first = D.get(f"cv_p{a}"), D.get(f"cv_p{max(a - 20, 10)}"), D.get("cv_p10")
    D["cv_acc"] = (p_last - p_mid) - (p_mid - p_first) * 20 / max(a - 30, 10)
    D["cv_rank_trend"] = D[f"cv_r{a}"] - D[f"cv_r{max(a - 30, 10)}"]
    return D


def comments(a):
    c = pd.read_parquet(os.path.join(H.CACHE, "bq_comments.parquet"), columns=["person", "story_id", "created_at_i", "top_level"])
    born_all = H.stories().set_index("post_id").created_at_i
    # person record before Jul 1: share of stories they commented on in the first hour that made a daily top 30
    L = OL.lists()
    win = set(L[L["rank"] <= 30].post_id)
    old = c[(c.created_at_i < CUT) & (c.created_at_i >= pd.Timestamp("2025-01-15", tz="UTC").timestamp())]
    lat = old.created_at_i - old.story_id.map(born_all).to_numpy()
    old = old[(lat >= 0) & (lat <= 3600)].drop_duplicates(["person", "story_id"])
    old = old.assign(w=old.story_id.isin(win).astype(float))
    base = old.w.mean()
    g = old.groupby("person").w.agg(["sum", "count"])
    skill = (g["sum"] + 10 * base) / (g["count"] + 10)           # shrunk to the base rate
    proven = set(g[(g["count"] >= 20) & (skill > 2 * base)].index)
    print(f"early commenters with a record: {len(g)}; proven scouts (20+ early comments, 2x base hit rate): {len(proven)}", flush=True)
    born = Q.set_index("post_id").created_at_i
    cq = c[c.story_id.isin(born.index)]
    cq = cq.assign(lat=cq.created_at_i - cq.story_id.map(born).to_numpy())
    cq = cq[(cq.lat >= 0) & (cq.lat < a * 60)]
    cq = cq.assign(skill=cq.person.map(skill), proven=cq.person.isin(proven).astype(int))
    gg = cq.groupby("story_id")
    D = pd.DataFrame({
        "cm_n": gg.size(), "cm_n15": gg.lat.apply(lambda x: (x < 900).sum()), "cm_n30": gg.lat.apply(lambda x: (x < 1800).sum()),
        "cm_last20": gg.lat.apply(lambda x: (x >= (a - 20) * 60).sum()), "cm_people": gg.person.nunique(),
        "cm_first": gg.lat.min() / 60, "cm_top_share": gg.top_level.mean(),
    })
    W = pd.DataFrame({"who_mean": gg.skill.mean(), "who_max": gg.skill.max(), "who_n_known": gg.skill.count(),
                      "who_proven": gg.proven.sum(), "who_sum": gg.skill.sum()})
    D = D.reindex(Q.post_id).reset_index(drop=True).set_index(Q.index)
    D[["cm_n", "cm_n15", "cm_n30", "cm_last20", "cm_people"]] = D[["cm_n", "cm_n15", "cm_n30", "cm_last20", "cm_people"]].fillna(0)
    W = W.reindex(Q.post_id).reset_index(drop=True).set_index(Q.index)
    W[["who_n_known", "who_proven", "who_sum"]] = W[["who_n_known", "who_proven", "who_sum"]].fillna(0)
    return D, W


def mech(cv, a):
    pts, rk = cv[f"cv_p{a}"].fillna(1), cv[f"cv_r{a}"].fillna(91)
    g = (pts - 1) / (a / 60 + 2) ** 1.8
    M = pd.DataFrame({"mx_gravity": g}, index=Q.index)
    # rank gravity predicts, from the fit period: isotonic of rank on gravity score (by posting hour bucket)
    from sklearn.isotonic import IsotonicRegression
    ok = C.fit
    iso = IsotonicRegression(increasing=False, out_of_bounds="clip").fit(g[ok], np.minimum(rk[ok], 91))
    M["mx_rank_resid"] = rk - iso.predict(g)                     # > 0: lower than gravity says (penalty / flags)
    M["mx_dead_like"] = ((pts >= 10) & (rk >= 91)).astype(int)
    return M


def outside(a):
    import feeds_anticipate as FA
    F = FA.feed_items()
    keys = Q.url.map(FA.norm)
    by_key = {k: np.sort(g.t.to_numpy()) for k, g in F.groupby("key")}
    n = [0 if (t := by_key.get(k)) is None else int(np.searchsorted(t, b + a * 60) - np.searchsorted(t, b)) for k, b in zip(keys, Q.created_at_i)]
    return pd.DataFrame({"ot_feed_1h": n}, index=Q.index)


if __name__ == "__main__":
    a = A_MIN
    _, qs = fine_io.load()
    q_by_id = {r.post_id: {"qn_f0": r.qn_f0, "qn_rank_10m": r.qn_rank_10m, "qn_up_10m": r.qn_up_10m, "qn_exp_10m": r.qn_exp_10m}
               for r in qs.itertuples()}
    V = C.honest(OL.vote_feats(Q, q_by_id, [a])[a], a, set(q_by_id))
    print(f"posts with a Quality News series: test {Q.post_id[C.te].isin(q_by_id).mean():.1%}, "
          f"test winners {Q.post_id[C.te & (Q.y == 1).to_numpy()].isin(q_by_id).mean():.1%}", flush=True)
    CV = curve(a)
    CM, WHO = comments(a)
    MX = mech(CV, a)
    OT = outside(a)
    # leak check: can the vote inputs tell a real series from an imputed one, among posts with <= 4 points by now?
    import lightgbm as lgb
    from sklearn.metrics import roc_auc_score
    X = pd.concat([V, CV, MX], axis=1)
    has = Q.post_id.isin(q_by_id).to_numpy().astype(int)
    small = (V.points <= 4).to_numpy()
    m = lgb.LGBMClassifier(n_estimators=200, verbose=-1).fit(X[C.fit & small], has[C.fit & small])
    print(f"leak check: AUC telling a real from an imputed series among posts with <= 4 points at {a} min "
          f"(0.5 = no leak): {roc_auc_score(has[C.te & small], m.predict_proba(X[C.te & small])[:, 1]):.3f}", flush=True)
    base = C.caught(C.model(full, V))
    print(f"Caught at {a} min (current inputs: post + votes/rank now): {C.ci(base)}", flush=True)
    sets = {"curve": CV, "comments": CM, "who": WHO, "mech": MX, "outside": OT}
    for name, X in sets.items():
        s = C.caught(C.model(full, pd.concat([V, X], axis=1)))
        print(f"  + {name:10s} {C.ci(s)}  difference {C.diff(s, base)}", flush=True)
    s = C.caught(C.model(full, pd.concat([V] + list(sets.values()), axis=1)))
    print(f"  + all       {C.ci(s)}  difference {C.diff(s, base)}", flush=True)
    s2 = C.caught(C.model(full, pd.concat([V, CV, CM, WHO], axis=1)))
    print(f"  + curve, comments, who  {C.ci(s2)}  difference {C.diff(s2, base)}", flush=True)
    pd.concat([Q[["post_id"]], V, CV, CM, WHO, MX, OT], axis=1).to_parquet(os.path.join(H.CACHE, f"caught{a}_feats.parquet"), index=False)
