"""Checkpoint 2 push (15 min after posting), honest early votes from Wayback /newest (October archive).
Forward test: for each posting day d in Oct 2-14, train on posts from Jul 1 to d-2 (so October's dense snapshot days
enter training as they pass), score day d's posts at 15 min. Flags = winners over Oct 2-14 (caught per post).

Inputs at 15 min:
  base     at-posting (post, similar titles, embedding, crowd, history score, page judge) + front-page rank by 15 min
           (Quality News; honest) + comments by 15 min
  votes    every /newest snapshot by 15 min: latest score, its age, votes per minute, best score, snapshots seen,
           rank on /newest (how fast it is being pushed down = posting volume), best /news rank (Wayback)
  who      who commented in the first 15 min: their record before Jul 1 (caught1h.comments)
  ties     early commenters' ties to the submitter, their activity, newcomers (who_deep)
  chain    predicted 15-min score from at-posting inputs (CHAIN=1; did not add)
Reported per variant: Caught over all days and over 90%+ coverage days, paired by day vs base.

    python wb15.py
"""
import os

import lightgbm as lgb
import numpy as np
import pandas as pd

import caught as C
import caught1h as C1
import fine_io
import odds_live as OL
import pj_eval
import top100 as H
import wb_caught as W

A_MIN = 15
CHAIN = os.environ.get("CHAIN") == "1"            # the chained prediction did not add (+1.3 [-1.7, +4.2]); off by default
PRM = dict(n_estimators=500, learning_rate=0.03, num_leaves=31, min_child_samples=30, subsample=0.8, subsample_freq=1,
           colsample_bytree=0.8, verbose=-1, random_state=0)


def votes15(Q):
    A = pd.read_json(W.EV, lines=True, convert_dates=False)
    A = A[(A.age_min >= 0) & (A.age_min <= A_MIN)]
    N = A[A.page == "newest"].sort_values("age_min")
    g = N.groupby("item_id")
    last = N.drop_duplicates("item_id", keep="last").set_index("item_id")
    off = {"news": 0, "news_p2": 0, "news_p3": 0}     # Wayback rank is already the position (news_p2 = 31-60); no page offset
    F = A[A.page.isin(off)]
    front = (F["rank"] + F.page.map(off)).groupby(F.item_id).min()
    out = pd.DataFrame(index=Q.index)
    out["v_has"] = Q.post_id.isin(last.index).astype(int)
    out["v_score"] = Q.post_id.map(last.score)
    out["v_age"] = Q.post_id.map(last.age_min)
    out["v_rate"] = (out.v_score - 1) / out.v_age.clip(lower=1)
    out["v_best"] = Q.post_id.map(g.score.max())
    out["v_n"] = Q.post_id.map(g.size()).fillna(0)
    out["v_rank_new"] = Q.post_id.map(last["rank"])
    out["v_push"] = out.v_rank_new / out.v_age.clip(lower=1)          # positions lost per minute on /newest
    out["v_comments"] = Q.post_id.map(last.comments)
    out["v_front"] = Q.post_id.map(front)
    return out


def expo15(Q, a=A_MIN):
    """Direction A on the October archive: exposure on /newest page 1 in the first a minutes from Wayback captures.
    Of the captures of /newest in [posting, posting + a], the share that showed the post (page 1 = the 30 newest),
    position-weighted (1 / sqrt(rank)); estimated minutes there; votes per exposure-minute (plain and weighted); posts
    submitted in the 30 min before; posting hour. Only the captures' times and what they showed: no outcome."""
    A = pd.read_json(W.EV, lines=True, convert_dates=False)
    N = A[A.page == "newest"]
    ts = pd.to_datetime(N.capture_ts.astype(str), format="%Y%m%d%H%M%S", utc=True)
    caps = np.sort(((ts - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(seconds=1)).unique())   # epoch seconds (pandas 3: us)
    N = N[(N.age_min >= 0) & (N.age_min <= a)]
    born = Q.created_at_i.to_numpy()
    n_caps = np.searchsorted(caps, born + a * 60, side="right") - np.searchsorted(caps, born)
    g = N.groupby("item_id")
    seen = Q.post_id.map(g.size()).fillna(0).to_numpy()
    wsum = Q.post_id.map(N.assign(w=1 / np.sqrt(N["rank"].clip(lower=1))).groupby("item_id").w.sum()).fillna(0).to_numpy()
    last_score = Q.post_id.map(N.sort_values("age_min").drop_duplicates("item_id", keep="last").set_index("item_id").score)
    out = pd.DataFrame(index=Q.index)
    out["x_caps"] = n_caps
    out["x_share"] = np.where(n_caps > 0, seen / np.maximum(n_caps, 1), np.nan)
    out["x_min"] = out.x_share * a
    out["x_w"] = np.where(n_caps > 0, wsum / np.maximum(n_caps, 1) * a, np.nan)
    out["x_vpe"] = (last_score - 1) / out.x_min.clip(lower=0.5)
    out["x_vpe_w"] = (last_score - 1) / out.x_w.clip(lower=0.5)
    ct = np.sort(born)
    out["x_vol30"] = np.searchsorted(ct, born) - np.searchsorted(ct, born - 1800)
    out["x_hour"] = (born // 3600) % 24
    return out


def who_deep(Q, a=A_MIN):
    """Who commented in the first a minutes, beyond their scout record: their ties to the submitter before Jul 1
    (comments on the submitter's stories since 2025), their overall activity before Jul 1, newcomers."""
    cut = pd.Timestamp("2026-07-01", tz="UTC").timestamp()
    p = H.stories().set_index("post_id")
    c = pd.read_parquet(os.path.join(H.CACHE, "bq_comments.parquet"), columns=["person", "story_id", "created_at_i"])
    old = c[(c.created_at_i < cut) & (c.created_at_i >= pd.Timestamp("2025-01-01", tz="UTC").timestamp())]
    old = old.assign(sub=old.story_id.map(p.author).to_numpy())
    tie = old.groupby(["person", "sub"]).size()
    act = old.groupby("person").size()
    born = Q.set_index("post_id").created_at_i
    e = c[c.story_id.isin(born.index)]
    lat = e.created_at_i - e.story_id.map(born).to_numpy()
    e = e[(lat >= 0) & (lat < a * 60)].drop_duplicates(["person", "story_id"])
    e = e.assign(sub=e.story_id.map(p.author).to_numpy())
    e = e[e.person != e["sub"]]
    e["tie"] = tie.reindex(pd.MultiIndex.from_frame(e[["person", "sub"]])).fillna(0).to_numpy()
    e["act"] = act.reindex(e.person).fillna(0).to_numpy()
    g = e.groupby("story_id")
    D = pd.DataFrame({"wd_n": g.size(), "wd_tied": g.tie.apply(lambda x: (x > 0).sum()), "wd_tie_sum": g.tie.sum(),
                      "wd_act_mean": g.act.mean(), "wd_act_max": g.act.max(), "wd_new": g.act.apply(lambda x: (x == 0).sum())})
    D = D.reindex(Q.post_id)
    D.index = Q.index
    return D.fillna({"wd_n": 0, "wd_tied": 0, "wd_tie_sum": 0, "wd_new": 0})


def main():
    Q = C.Q.merge(pd.read_parquet(os.path.join(H.CACHE, "hist_prior.parquet")), on="post_id", how="left")
    Q = Q.merge(pj_eval.judge_feats(), on="post_id", how="left")
    AT = C.POST + C.KNN + C.EMB + C.CROWD + ["hist_prior"] + [c for c in Q.columns if c.startswith("pj_")]
    _, qs = fine_io.load()
    qb = {r.post_id: {"qn_f0": r.qn_f0, "qn_rank_10m": r.qn_rank_10m, "qn_up_10m": r.qn_up_10m, "qn_exp_10m": r.qn_exp_10m}
          for r in qs.itertuples()}
    R = C.honest(OL.vote_feats(Q, qb, [A_MIN])[A_MIN], A_MIN, set(qb))[["rank_now", "best_rank"]]
    C1.Q = Q
    CM, WHO = C1.comments(A_MIN)
    V = votes15(Q)
    y_s = np.log1p(V.v_score.where(V.v_age >= 10))                      # chain target: score at 10-15 min
    base = pd.concat([Q[AT], R, CM[["cm_n", "cm_people", "cm_first"]]], axis=1)
    WD = who_deep(Q)
    XP = expo15(Q)
    variants = {"base": base, "+ votes": pd.concat([base, V], axis=1), "+ votes + who": pd.concat([base, V, WHO], axis=1),
                "+ votes + who + ties/activity": pd.concat([base, V, WHO, WD], axis=1),
                "+ votes + who + exposure (direction A)": pd.concat([base, V, WHO, XP], axis=1)}
    days = sorted(d for d in Q.day.unique() if "2026-10-02" <= d <= "2026-10-14")
    scores = {k: np.full(len(Q), np.nan) for k in list(variants) + (["+ votes + who + chain"] if CHAIN else [])}
    for d in days:
        tr = (Q.day <= (pd.Timestamp(d) - pd.Timedelta(days=2)).strftime("%Y-%m-%d")).to_numpy()
        te = (Q.day == d).to_numpy()
        for k, X in variants.items():
            scores[k][te] = lgb.LGBMClassifier(**PRM).fit(X[tr], Q.y[tr]).predict_proba(X[te])[:, 1]
        if not CHAIN:
            print(f"  {d}: trained on {int(tr.sum())} posts", flush=True)
            continue
        # chain: predicted 15-min score from at-posting inputs, out-of-fold inside the training window
        ok = tr & y_s.notna().to_numpy()
        pr = np.full(len(Q), np.nan)
        fold = np.arange(len(Q)) % 3
        for f in range(3):
            m = ok & (fold != f)
            pr[tr & (fold == f)] = lgb.LGBMRegressor(**PRM).fit(Q.loc[m, AT], y_s[m]).predict(Q.loc[tr & (fold == f), AT])
        pr[te] = lgb.LGBMRegressor(**PRM).fit(Q.loc[ok, AT], y_s[ok]).predict(Q.loc[te, AT])
        X = pd.concat([variants["+ votes + who"], pd.Series(pr, index=Q.index, name="chain15")], axis=1)
        scores["+ votes + who + chain"][te] = lgb.LGBMClassifier(**PRM).fit(X[tr], Q.y[tr]).predict_proba(X[te])[:, 1]
        print(f"  {d}: trained on {int(tr.sum())} posts ({int(V.v_has[tr].sum())} with a /newest snapshot)", flush=True)
    sel = Q.day.isin(days).to_numpy()
    T = Q[sel][["post_id", "day", "y"]]
    good = T.day.isin(W.GOOD).to_numpy()
    print(f"Oct 2-14: {len(T)} posts, {int(T.y.sum())} winners; with a /newest snapshot by 15 min {V.v_has[sel].mean():.1%}", flush=True)
    for sub, keep in (("all days", np.ones(len(T), bool)), ("90%+ coverage days", good)):
        b = W.caught_on(T[keep], scores["base"][sel][keep])
        print(f"Caught at 15 min, {sub} ({T[keep].day.nunique()} days, {int(T.y[keep].sum())} winners): base {W.ci2(b)}", flush=True)
        for k in list(scores)[1:]:
            c = W.caught_on(T[keep], scores[k][sel][keep])
            print(f"   {k:24s} {W.ci2(c)}  vs base {W.ci2(c, b)}", flush=True)
        ref = W.caught_on(T[keep], scores["+ votes + who"][sel][keep])
        xp = W.caught_on(T[keep], scores["+ votes + who + exposure (direction A)"][sel][keep])
        print(f"   direction A: exposure vs votes + who, paired: {W.ci2(xp, ref)}", flush=True)
    pd.DataFrame({"post_id": T.post_id.to_numpy(), **{k: v[sel] for k, v in scores.items()}}).to_parquet(
        os.path.join(H.CACHE, "wb15_scores.parquet"), index=False)
    diagnose(Q, T, scores["+ votes + who"][sel], V[sel], R[sel], qb)


def diagnose(Q, T, s, V, R, qb):
    """Where the 15-min misses are: winner type (fast = on the front page by 1 h and listed the posting day or the
    next; late riser; re-up 2+ days later), and what fast winners look like on /newest at 15 min."""
    L = OL.lists()
    first = L[L["rank"] <= 30].groupby("post_id").day.min()
    lag = (pd.to_datetime(T.post_id.map(first)) - pd.to_datetime(T.day)).dt.days.to_numpy()
    sub = Q[Q.post_id.isin(T.post_id)].set_index("post_id").reindex(T.post_id).reset_index()
    vis60 = (OL.vote_feats(sub, qb, [60])[60].best_rank <= 30).to_numpy()
    y = T.y.to_numpy()
    kind = np.where(y == 0, "none", np.where(lag >= 2, "reup", np.where(vis60, "fast", "late")))
    k = int(y.sum())
    flag = pd.Series(s).rank(ascending=False, method="first").to_numpy() <= k
    print("15 min, + votes + who, caught by winner type: " + ", ".join(
        f"{t} {int((flag & (kind == t)).sum())}/{int((kind == t).sum())}" for t in ("fast", "late", "reup")), flush=True)
    has = V.v_has.to_numpy() == 1
    for t in ("fast", "late", "reup", "none"):
        m = (kind == t) & has
        if m.any():
            sc = V.v_score.to_numpy()[m]
            print(f"   {t:5s} with a snapshot by 15 min: {m.sum():5d}; score at the latest snapshot median {np.median(sc):.0f}, "
                  f"share >= 3 points {(sc >= 3).mean():.1%}, >= 5 {(sc >= 5).mean():.1%}; snapshot age median "
                  f"{np.median(V.v_age.to_numpy()[m]):.1f} min; on /news by 15 min {(V.v_front.to_numpy()[m] < 999).mean():.1%}; "
                  f"front rank by 15 min (QN) {(R.best_rank.to_numpy()[m] <= 30).mean():.1%}", flush=True)


if __name__ == "__main__":
    main()
