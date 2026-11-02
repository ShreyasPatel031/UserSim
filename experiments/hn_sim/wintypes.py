"""Checkpoint 3 (at posting): model the three kinds of winners separately.
  fast    on the front page within 1 h of posting (Quality News rank) and on its posting day's / next day's list
  late    makes the posting day's or next day's list but was not on the front page by 1 h (late riser)
  reup    first makes a list 2+ days after posting (HN second-chance pool re-up)
Inputs added at posting, from posts that settled before this one (posted 10+ days earlier, lists from 2025):
  the domain's / site's / author's record of same-day wins, next-day wins and re-ups (counts and rates).
Scores compared on Sep 1 - Oct 14 (caught.py metric; flags = winners), paired by day:
  a  current Jul-Aug model (one classifier, any winner)
  b  a + type record
  c  one classifier per winner type (a + type record inputs), probabilities summed
  d  c blended 50/50 (ranks) with the 2025+ history model (the current best at posting is that blend with a)
Also: winners caught by type.

    python wintypes.py
"""
import os

import lightgbm as lgb
import numpy as np
import pandas as pd

import caught as C
import fine_io
import levers as LV
import odds_live as OL
import top100 as H

DAY = 86400
PRM = dict(n_estimators=600, learning_rate=0.03, num_leaves=31, min_child_samples=30, subsample=0.8, subsample_freq=1,
           colsample_bytree=0.8, verbose=-1, random_state=0)


def type_record(q_ids):
    """Per post: earlier posts (posted 10+ days before) with the same domain / site / author, by how they won."""
    p = H.stories()
    L = OL.lists()
    first = L[L["rank"] <= 30].groupby("post_id").day.min()
    lag = (pd.to_datetime(p.post_id.map(first)) - pd.to_datetime(p.day)).dt.days
    known = (p.day >= "2025-01-01").to_numpy()
    same = ((lag == 0) & known).astype(int).to_numpy()
    nextd = ((lag == 1) & known).astype(int).to_numpy()
    reup = ((lag >= 2) & known).astype(int).to_numpy()
    p = p.assign(dom=p.url.map(LV.host), site=p.url.map(LV.site))
    p.loc[~known, ["dom", "site", "author"]] = None
    out = None
    for key, pre in (("dom", "td"), ("site", "ts"), ("author", "ta")):
        ev = pd.DataFrame({"k": p[key], "t": p.created_at_i + 10 * DAY, "n": 1, "s": same, "x": nextd, "r": reup, "q": 0})
        qq = p[p.post_id.isin(q_ids)]
        qr = pd.DataFrame({"k": qq[key], "t": qq.created_at_i, "n": 0, "s": 0, "x": 0, "r": 0, "q": 1, "post_id": qq.post_id})
        a = pd.concat([ev.dropna(subset=["k"]), qr.dropna(subset=["k"])], ignore_index=True).sort_values(["t", "q"], kind="stable")
        g = a.groupby("k")
        r = pd.DataFrame({"post_id": a.post_id, f"{pre}_n": g.n.cumsum(), f"{pre}_same": g.s.cumsum(),
                          f"{pre}_next": g.x.cumsum(), f"{pre}_reup": g.r.cumsum()})[a.q.to_numpy() == 1]
        for c in ("same", "next", "reup"):
            r[f"{pre}_{c}_rate"] = r[f"{pre}_{c}"] / r[f"{pre}_n"].clip(lower=1)
        out = r if out is None else out.merge(r, on="post_id", how="outer")
    return out


def main():
    Q = C.Q
    TR = type_record(set(Q.post_id))
    Q = Q.merge(TR, on="post_id", how="left")
    C.Q = Q
    TRC = [c for c in TR.columns if c != "post_id"]
    # winner type labels (Jul-Oct)
    L = OL.lists()
    first = L[L["rank"] <= 30].groupby("post_id").day.min()
    lag = (pd.to_datetime(Q.post_id.map(first)) - pd.to_datetime(Q.day)).dt.days
    _, qs = fine_io.load()
    qb = {r.post_id: {"qn_f0": r.qn_f0, "qn_rank_10m": r.qn_rank_10m, "qn_up_10m": r.qn_up_10m, "qn_exp_10m": r.qn_exp_10m}
          for r in qs.itertuples()}
    vis = (OL.vote_feats(Q, qb, [60])[60].best_rank <= 30).to_numpy()
    y = Q.y.to_numpy()
    kind = np.where(y == 0, "none", np.where(lag >= 2, "reup", np.where(vis, "fast", "late")))
    yt = {k: (kind == k).astype(int) for k in ("fast", "late", "reup")}
    print("winner types, fit (Jul-Aug):", {k: int(v[C.fit].sum()) for k, v in yt.items()},
          "| test:", {k: int(v[C.te].sum()) for k, v in yt.items()}, flush=True)
    full = C.POST + C.KNN + C.EMB + C.CROWD
    sa = C.model(full)
    a = C.caught(sa)
    print(f"a  current Jul-Aug model: {C.ci(a)}", flush=True)
    sb = C.model(full + TRC)
    b = C.caught(sb)
    print(f"b  + type record (domain / site / author: same-day, next-day, re-up wins): {C.ci(b)}  vs a {C.diff(b, a)}", flush=True)
    X = Q[full + TRC]
    parts = {}
    for k, yy in yt.items():
        parts[k] = lgb.LGBMClassifier(**PRM).fit(X[C.fit], yy[C.fit]).predict_proba(X[C.te])[:, 1]
    sc = sum(parts.values())
    c = C.caught(sc)
    print(f"c  one model per winner type, summed: {C.ci(c)}  vs a {C.diff(c, a)}", flush=True)
    h = np.load(os.path.join(H.CACHE, "caught_hist2_test_scores.npy"))
    rk = lambda x: pd.Series(x).rank(pct=True).to_numpy()
    base = C.caught(0.5 * rk(sa) + 0.5 * rk(h))
    print(f"   current best at posting (a blended with the 2025+ model): {C.ci(base)}", flush=True)
    for name, s in (("b", sb), ("c", sc)):
        d = C.caught(0.5 * rk(s) + 0.5 * rk(h))
        print(f"d  {name} blended 50/50 with the 2025+ model: {C.ci(d)}  vs current best {C.diff(d, base)}", flush=True)
    # caught by type (flags = winners, over the test period)
    T = Q[C.te].assign(kind=kind[C.te])
    k_ = int(T.y.sum())
    for name, s in (("a", sa), ("c", sc), ("c+history", 0.5 * rk(sc) + 0.5 * rk(h))):
        f = pd.Series(s).rank(ascending=False, method="first").to_numpy() <= k_
        print(f"   caught by type, {name}: " + ", ".join(f"{t} {int((f & (T.kind == t).to_numpy()).sum())}/{int((T.kind == t).sum())}"
                                                       for t in ("fast", "late", "reup")), flush=True)


if __name__ == "__main__":
    main()
