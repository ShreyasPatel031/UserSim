"""Directions B and C on the October backtest (Oct 2-14, forward daily retrain; DIRECTION_REVIEW_2026-11-02.md).

Exposure event: a post's return to the front page (Quality News rank <= 90) 3+ h after posting after 3+ h off it, from
the whole-life 10-minute rank series. Caveat: those series exist only for posts that ended with 5+ points; live data
says ~4% of posts ever on the front page and ~10% of posts with a /pool or return event end below 5, so a few
non-winning events are missing (small optimistic bias for B).

B  judged again 15 min after the event: rank at the event and 10 min later, points gained, age and hour at the event,
   plus the post's at-posting / 15-min inputs. Event model trained on events of posts posted 6+ days before the test day
   (their events and labels are known). Exposure clock per post: max(P at 15 min after posting, P at 15 min after the
   event). Reported beside the per-post headline (posting clock only).
C  predict "will get a second-chance return" at 15 min after posting (the 15-min inputs), forward retrain; its
   probability added as an input to the 15-min model. Per-post rule, compared with the current best (29.6%).

    python wb_reup.py     # needs wb15.py run first (wb15_scores.parquet)
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

PRM = W15.PRM
GAP = 18                      # 3 h in 10-min steps


def events(Q, qs):
    by = {r.post_id: r for r in qs.itertuples()}
    rows = []
    for pid, born in zip(Q.post_id, Q.created_at_i):
        s = by.get(pid)
        if s is None:
            continue
        rk = np.array([x if x is not None else 91 for x in s.qn_rank_10m], float)
        up = pd.Series(s.qn_up_10m, dtype=float).ffill().fillna(1).to_numpy()
        t = s.qn_f0 + 600 * np.arange(len(rk))
        on = rk <= 90
        for k in np.where(on)[0]:
            if t[k] - born < 3 * 3600:
                continue
            if on[max(0, k - GAP):k].any():
                continue
            k1 = min(k + 1, len(rk) - 1)
            rows.append({"post_id": pid, "ev_t": t[k], "ev_age_h": (t[k] - born) / 3600, "ev_hour": int(t[k] // 3600 % 24),
                         "ev_rank0": rk[k], "ev_rank10": rk[k1], "ev_pts0": up[k], "ev_gain10": up[k1] - up[max(k - 1, 0)]})
            break
    return pd.DataFrame(rows)


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
    V, XP = W15.votes15(Q), W15.expo15(Q)
    X15 = pd.concat([Q[AT], R, CM[["cm_n", "cm_people", "cm_first"]], V, WHO, XP], axis=1)
    E = events(Q, qs).set_index("post_id")
    ev = Q.post_id.isin(E.index).to_numpy()
    EV = E.reindex(Q.post_id).reset_index(drop=True)
    EV.index = Q.index
    L = OL.lists()
    first = L[L["rank"] <= 30].groupby("post_id").day.min()
    lag = (pd.to_datetime(Q.post_id.map(first)) - pd.to_datetime(Q.day)).dt.days.to_numpy()
    y = Q.y.to_numpy()
    kind = np.where(y == 0, "none", np.where(lag >= 2, "reup", np.where(vis60, "fast", "late")))
    days = sorted(d for d in Q.day.unique() if "2026-10-02" <= d <= "2026-10-14")
    sel = Q.day.isin(days).to_numpy()
    print(f"posts with a second-chance return (Jul-Oct): {ev.sum()} ({ev.mean():.1%}); win rate among them {y[ev].mean():.1%}; "
          f"median {np.nanmedian(EV.ev_age_h):.1f} h after posting", flush=True)
    print("   Oct 2-14 winners with an event, by type: " + ", ".join(
        f"{t} {int((sel & ev & (kind == t)).sum())}/{int((sel & (kind == t)).sum())}" for t in ("fast", "late", "reup")), flush=True)
    s15 = np.full(len(Q), np.nan)       # posting clock (votes + who + exposure), recomputed here for the same rows
    sB = np.full(len(Q), np.nan)        # event clock
    sC = np.full(len(Q), np.nan)        # posting clock + predicted second chance
    XE = pd.concat([X15, EV[["ev_age_h", "ev_hour", "ev_rank0", "ev_rank10", "ev_pts0", "ev_gain10"]]], axis=1)
    for d in days:
        tr = (Q.day <= (pd.Timestamp(d) - pd.Timedelta(days=2)).strftime("%Y-%m-%d")).to_numpy()
        tr6 = (Q.day <= (pd.Timestamp(d) - pd.Timedelta(days=6)).strftime("%Y-%m-%d")).to_numpy()
        te = (Q.day == d).to_numpy()
        s15[te] = lgb.LGBMClassifier(**PRM).fit(X15[tr], y[tr]).predict_proba(X15[te])[:, 1]
        # C: P(second-chance return) from the 15-min inputs (labels need 4+ days: train on posts 6+ days old)
        pc = lgb.LGBMClassifier(**PRM).fit(X15[tr6], ev[tr6].astype(int))
        pev = pd.Series(pc.predict_proba(X15)[:, 1], index=Q.index, name="p_return")
        # out-of-sample for the training rows of the 15-min model: rows older than 6 days were in pc's training;
        # use 3-fold predictions for them
        fold = np.arange(len(Q)) % 3
        for f in range(3):
            m = tr6 & (fold != f)
            pev[tr6 & (fold == f)] = lgb.LGBMClassifier(**PRM).fit(X15[m], ev[m].astype(int)).predict_proba(X15[tr6 & (fold == f)])[:, 1]
        XC = pd.concat([X15, pev], axis=1)
        sC[te] = lgb.LGBMClassifier(**PRM).fit(XC[tr], y[tr]).predict_proba(XC[te])[:, 1]
        # B: event model on events of posts 6+ days old
        m = tr6 & ev
        tem = te & ev
        if m.sum() > 50 and tem.any():
            sB[tem] = lgb.LGBMClassifier(**PRM).fit(XE[m], y[m]).predict_proba(XE[tem])[:, 1]
        print(f"  {d}: events in training {int(m.sum())}, on this day {int(tem.sum())}", flush=True)
    T = Q[sel][["post_id", "day", "y"]].reset_index(drop=True)
    k = int(T.y.sum())
    a = W.caught_on(T, s15[sel])
    b = W.caught_on(T, np.fmax(s15[sel], np.nan_to_num(sB[sel], nan=0)))
    c = W.caught_on(T, sC[sel])
    print(f"Caught at 15 min per post, Oct 2-14 ({k} winners): posting clock (votes + who + exposure) {W.ci2(a)}", flush=True)
    print(f"   C, + predicted second-chance return (per-post rule): {W.ci2(c)}  vs posting clock {W.ci2(c, a)}", flush=True)
    print(f"   B, exposure clock (each post also judged 15 min after its return; reported beside the headline): {W.ci2(b)}  "
          f"vs posting clock {W.ci2(b, a)}", flush=True)
    for name, s in (("posting clock", s15[sel]), ("C", sC[sel]), ("B exposure clock", np.fmax(s15[sel], np.nan_to_num(sB[sel], nan=0)))):
        f = pd.Series(s).rank(ascending=False, method="first").to_numpy() <= k
        print(f"   caught by type, {name}: " + ", ".join(f"{t} {int((f & (kind[sel] == t)).sum())}/{int((kind[sel] == t).sum())}"
                                                       for t in ("fast", "late", "reup")), flush=True)


if __name__ == "__main__":
    main()
