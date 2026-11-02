"""Outside traction by 15 min (orchestrator, 2026-11-02): is the link already spreading elsewhere, timestamped strictly
before posting + 15 min? From the feeds backfill (Grok Bot: lobste.rs, Reddit r/programming, r/technology,
r/MachineLearning, r/LocalLLaMA, Techmeme, arXiv, press RSS, X sample, GitHub trending; Jul 1 - Oct 16):
  own link: mentions in the 7 days before posting + 15 min, sources, hours since first seen, per source flags
  domain: mentions of the domain in the 24 h before posting + 15 min
Techmeme and GitHub trending times are upper bounds (they can only make a mention look later, never earlier).
Coverage: how many late risers / winners / posts have any mention. Then Caught at 15 min per post with the inputs
added to the general 15-min model (wb15 "+ votes + who"), forward daily retrain on Oct 2-14, flags = winners, paired.

    python wb_outside.py
"""
import os

import lightgbm as lgb
import numpy as np
import pandas as pd

import caught as C
import caught1h as C1
import feeds_anticipate as FA
import fine_io
import levers as LV
import odds_live as OL
import pj_eval
import top100 as H
import wb15 as W15
import wb_caught as W

DAY = 86400
PRM = W15.PRM


def outside(Q, lead_s):
    F = FA.feed_items()
    F["dom"] = F.key.str.split("/").str[0]
    keys, doms = Q.url.map(FA.norm), Q.url.map(LV.host)
    by_key = {k: g for k, g in F.groupby("key")}
    dom_t = {d: np.sort(g.t.to_numpy()) for d, g in F.groupby("dom")}
    src = ["techmeme", "lobsters", "reddit", "arxiv", "rss", "x", "github"]
    rows = []
    for k, d, t in zip(keys, doms, Q.created_at_i + lead_s):
        r = {"os_n": 0, "os_src": 0, "os_h_since": np.nan, **{f"os_{s}": 0 for s in src}}
        g = by_key.get(k)
        if g is not None:
            g = g[(g.t < t) & (g.t >= t - 7 * DAY)]
            if len(g):
                r["os_n"], r["os_src"], r["os_h_since"] = len(g), g.src.nunique(), (t - g.t.min()) / 3600
                for s in src:
                    r[f"os_{s}"] = int(g.src.str.startswith(s).any())
        dt_ = dom_t.get(d)
        r["os_dom_24h"] = 0 if dt_ is None else int(np.searchsorted(dt_, t) - np.searchsorted(dt_, t - DAY))
        rows.append(r)
    return pd.DataFrame(rows, index=Q.index)


def main():
    Q = C.Q.merge(pd.read_parquet(os.path.join(H.CACHE, "hist_prior.parquet")), on="post_id", how="left")
    Q = Q.merge(pj_eval.judge_feats(), on="post_id", how="left")
    AT = C.POST + C.KNN + C.EMB + C.CROWD + ["hist_prior"] + [c for c in Q.columns if c.startswith("pj_")]
    _, qs = fine_io.load()
    qb = {r.post_id: {"qn_f0": r.qn_f0, "qn_rank_10m": r.qn_rank_10m, "qn_up_10m": r.qn_up_10m, "qn_exp_10m": r.qn_exp_10m}
          for r in qs.itertuples()}
    R = C.honest(OL.vote_feats(Q, qb, [15])[15], 15, set(qb))[["rank_now", "best_rank"]]
    vis60 = (OL.vote_feats(Q, qb, [60])[60].best_rank <= 30).to_numpy()
    C1.Q = Q
    CM, WHO = C1.comments(15)
    V = W15.votes15(Q)
    O = outside(Q, 15 * 60)
    L = OL.lists()
    first = L[L["rank"] <= 30].groupby("post_id").day.min()
    lag = (pd.to_datetime(Q.post_id.map(first)) - pd.to_datetime(Q.day)).dt.days.to_numpy()
    y = Q.y.to_numpy()
    kind = np.where(y == 0, "none", np.where(lag >= 2, "reup", np.where(vis60, "fast", "late")))
    days = sorted(d for d in Q.day.unique() if "2026-10-02" <= d <= "2026-10-14")
    sel = Q.day.isin(days).to_numpy()
    has = (O.os_n > 0).to_numpy()
    print("own link seen outside HN before posting + 15 min, Oct 2-14: " + ", ".join(
        f"{t} {int((has & sel & (kind == t)).sum())}/{int((sel & (kind == t)).sum())}" for t in ("fast", "late", "reup", "none")), flush=True)
    print(f"   all Jul-Oct posts: {has.mean():.1%}; by source (Oct 2-14 posts): " + ", ".join(
        f"{c[3:]} {int(O[c][sel].sum())}" for c in O.columns if c.startswith("os_") and c not in ("os_n", "os_src", "os_h_since", "os_dom_24h")), flush=True)
    base = pd.concat([Q[AT], R, CM[["cm_n", "cm_people", "cm_first"]], V, WHO], axis=1)
    with_o = pd.concat([base, O], axis=1)
    s0, s1 = np.full(len(Q), np.nan), np.full(len(Q), np.nan)
    for d in days:
        tr = (Q.day <= (pd.Timestamp(d) - pd.Timedelta(days=2)).strftime("%Y-%m-%d")).to_numpy()
        te = (Q.day == d).to_numpy()
        s0[te] = lgb.LGBMClassifier(**PRM).fit(base[tr], Q.y[tr]).predict_proba(base[te])[:, 1]
        s1[te] = lgb.LGBMClassifier(**PRM).fit(with_o[tr], Q.y[tr]).predict_proba(with_o[te])[:, 1]
    T = Q[sel][["post_id", "day", "y"]].reset_index(drop=True)
    good = T.day.isin(W.GOOD).to_numpy()
    k = int(T.y.sum())
    for sub, keep in (("all days", np.ones(len(T), bool)), ("90%+ coverage days", good)):
        c0, c1 = W.caught_on(T[keep], s0[sel][keep]), W.caught_on(T[keep], s1[sel][keep])
        print(f"Caught at 15 min, {sub}: votes + who {W.ci2(c0)}; + outside traction {W.ci2(c1)}; difference {W.ci2(c1, c0)}", flush=True)
    for name, s in (("votes + who", s0), ("+ outside", s1)):
        f = pd.Series(s[sel]).rank(ascending=False, method="first").to_numpy() <= k
        print(f"   caught by type, {name}: " + ", ".join(f"{t} {int((f & (kind[sel] == t)).sum())}/{int((kind[sel] == t).sum())}"
                                                       for t in ("fast", "late", "reup")), flush=True)


if __name__ == "__main__":
    main()
