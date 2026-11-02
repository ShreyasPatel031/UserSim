"""GitHub traction as a 15-min input (orchestrator, 2026-11-02): for posts linking a github.com repo, from the
stargazer list (starred_at; gh.py on hn-sim-1): repo age, stars before posting, in the 7 days / 24 h before, in the
first 15 min after posting, owner is an organisation. Coverage among winners by type, then Caught at 15 min per post
with these inputs added to the current 15-min model (votes + who + exposure), Oct 2-14 forward daily retrain, paired.

    python wb_gh.py      # needs <cache>/gh_repos.jsonl from the full gh.py run (since 2026-07-01)
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
import wb15 as W15
import wb_caught as W

GHC = ["gh_age_days", "gh_stars_before", "gh_week", "gh_day", "gh_after15", "gh_org", "gh_link"]


def gh_feats(Q):
    G = pd.read_json(os.path.join(H.CACHE, "gh_repos.jsonl"), lines=True).drop_duplicates("post_id", keep="last")
    G = G[G.ok == True].set_index("post_id")                        # noqa: E712
    out = pd.DataFrame(index=Q.index)
    for c, src in (("gh_age_days", "repo_age_days"), ("gh_stars_before", "stars_before"), ("gh_week", "stars_week_before"),
                   ("gh_day", "stars_day_before"), ("gh_after15", "stars_15min_after"), ("gh_org", "org")):
        out[c] = Q.post_id.map(G[src]) if src in G else np.nan
    out["gh_link"] = Q.url.fillna("").str.contains("github.com/").astype(int).to_numpy()
    return out


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
    base = pd.concat([Q[AT], R, CM[["cm_n", "cm_people", "cm_first"]], W15.votes15(Q), WHO, W15.expo15(Q)], axis=1)
    G = gh_feats(Q)
    L = OL.lists()
    first = L[L["rank"] <= 30].groupby("post_id").day.min()
    lag = (pd.to_datetime(Q.post_id.map(first)) - pd.to_datetime(Q.day)).dt.days.to_numpy()
    y = Q.y.to_numpy()
    kind = np.where(y == 0, "none", np.where(lag >= 2, "reup", np.where(vis60, "fast", "late")))
    days = sorted(d for d in Q.day.unique() if "2026-10-02" <= d <= "2026-10-14")
    sel = Q.day.isin(days).to_numpy()
    has = G.gh_stars_before.notna().to_numpy()
    print("posts with GitHub star data, Oct 2-14: " + ", ".join(
        f"{t} {int((has & sel & (kind == t)).sum())}/{int((sel & (kind == t)).sum())}" for t in ("fast", "late", "reup", "none")), flush=True)
    X1 = pd.concat([base, G], axis=1)
    s0, s1 = np.full(len(Q), np.nan), np.full(len(Q), np.nan)
    for d in days:
        tr = (Q.day <= (pd.Timestamp(d) - pd.Timedelta(days=2)).strftime("%Y-%m-%d")).to_numpy()
        te = (Q.day == d).to_numpy()
        s0[te] = lgb.LGBMClassifier(**W15.PRM).fit(base[tr], y[tr]).predict_proba(base[te])[:, 1]
        s1[te] = lgb.LGBMClassifier(**W15.PRM).fit(X1[tr], y[tr]).predict_proba(X1[te])[:, 1]
    T = Q[sel][["post_id", "day", "y"]].reset_index(drop=True)
    c0, c1 = W.caught_on(T, s0[sel]), W.caught_on(T, s1[sel])
    print(f"Caught at 15 min, Oct 2-14: votes + who + exposure {W.ci2(c0)}; + GitHub stars {W.ci2(c1)}; difference {W.ci2(c1, c0)}", flush=True)
    g = has[sel]
    if g.any() and T.y[g].sum() > 0:
        c0g, c1g = W.caught_on(T[g], s0[sel][g]), W.caught_on(T[g], s1[sel][g])
        print(f"   GitHub-linked posts only ({int(g.sum())}, {int(T.y[g].sum())} winners): {W.ci2(c0g)} -> {W.ci2(c1g)}", flush=True)


if __name__ == "__main__":
    main()
