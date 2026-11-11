"""Provisional live Caught at 15 min (Shreyas, 2026-11-02): every post since the per-minute recorder started
(2026-10-31 02:13 UTC; hn_minute box + VM union), judged once at 15 min with what was known then. The label is only
provisional: made any daily top 30 so far, using the latest listwatch read of each list day from the posting day
through 3 days later (settled = read 48 h+ after the day ended). Re-scored as lists settle; run daily.

Posts: Algolia (all stories, with created_at), posted from the recorder start up to 15 min before the latest read.
At 15 min: latest points and comments seen on /newest or /news at or before created + 15 min, best /news rank so far.
Scores (flags = winners among the scored posts; 95% interval resampling posting days):
  votes     points at 15 min (comments break ties)
  posting   the odds tool's at-posting P(top 30) (odds_live.score, the deployed model)
  blend     ranks of the two averaged 50/50 (fixed in advance)
Coverage reported: posts with a recorder sighting by 15 min, recorder minutes per day.

    python live15.py      # writes out/live15_<date>.json
"""
import json
import os
import time

import numpy as np
import pandas as pd

import live_caught as LC
import odds_live as OL

rng = np.random.default_rng(0)


AGES = (15, 60)
MIN_DAYS_MODEL = int(os.environ.get("LIVE_MIN_DAYS", "5"))   # leave-one-day-out model on recorder data from this many posting days


EXPO = ["expo_share", "expo_min", "expo_w", "vpe", "vpe_w", "vol_before30", "hour"]   # direction A (exposure)


def minute_feats(P, Mi, a, new_reads):
    """Per-minute vote features at age a (minutes): points and comments, when the 2nd / 3rd / 5th vote was first seen,
    votes per minute, front page (/news p1-3) entry time, best position and minutes on it, last /newest position and
    how fast the post is pushed down /newest.
    Exposure (direction A, DIRECTION_REVIEW_2026-11-02.md): share of the recorder's /newest reads in [0, a] that showed
    the post on /newest page 1, estimated minutes there, position-weighted minutes (1 / sqrt(position)), votes per
    exposure-minute (plain and weighted), posts submitted in the 30 min before, posting hour (UTC)."""
    w = Mi[(Mi.age >= 0) & (Mi.age <= a)].sort_values("t")
    g = w.groupby("id")
    out = pd.DataFrame(index=P.post_id)
    out["seen"] = out.index.isin(g.size().index).astype(int)
    out["pts"] = g.points.max().reindex(out.index).fillna(1)
    out["cm"] = g.comments.max().reindex(out.index).fillna(0)
    for k in (2, 3, 5):
        out[f"t{k}"] = w[w.points >= k].groupby("id").age.min().reindex(out.index).fillna(a + 30)
    out["rate"] = (out.pts - 1) / a
    fr = w[w.list == "front"]
    out["front_t"] = fr.groupby("id").age.min().reindex(out.index).fillna(a + 30)
    out["front_best"] = fr.groupby("id").pos.min().reindex(out.index).fillna(999)
    out["front_min"] = fr.groupby("id").t.nunique().reindex(out.index).fillna(0)
    nw = w[w.list == "newest"]
    lastn = nw.drop_duplicates("id", keep="last").set_index("id")
    out["new_pos"] = lastn.pos.reindex(out.index)
    out["new_push"] = (lastn.pos / lastn.age.clip(lower=1)).reindex(out.index)
    out["new_seen_min"] = nw.groupby("id").t.nunique().reindex(out.index).fillna(0)
    born = P.set_index("post_id").created_at_i
    n_reads = (np.searchsorted(new_reads, born.to_numpy() + a * 60, side="right") - np.searchsorted(new_reads, born.to_numpy()))
    out["new_reads"] = n_reads
    out["expo_share"] = (out.new_seen_min / np.maximum(n_reads, 1)).where(n_reads > 0)
    out["expo_min"] = out.expo_share * a
    pw = nw.assign(wt=1 / np.sqrt(nw.pos.clip(lower=1))).groupby("id").wt.sum().reindex(out.index).fillna(0)
    out["expo_w"] = (pw / np.maximum(n_reads, 1) * a).where(n_reads > 0)
    out["vpe"] = (out.pts - 1) / out.expo_min.clip(lower=0.5)
    out["vpe_w"] = (out.pts - 1) / out.expo_w.clip(lower=0.5)
    ct = np.sort(born.to_numpy())
    out["vol_before30"] = np.searchsorted(ct, born.to_numpy()) - np.searchsorted(ct, born.to_numpy() - 1800)
    out["hour"] = (born.to_numpy() // 3600) % 24
    return out.reset_index(drop=True)


def reup_clock(P, Mi, t_last, a=15, gap_h=3):
    """Direction B: an exposure event = the post's first /pool sighting, or a front-page sighting 3+ h after posting
    after 3+ h off the front page (a second-chance return). The post is judged again a minutes after its first event:
    points gained since the event, best front-page position and minutes on it in [event, event + a]."""
    ev = {}
    pool = Mi[Mi.list == "pool"].groupby("id").t.min()
    for pid, t in pool.items():
        ev[pid] = t
    fr = Mi[Mi.list == "front"].sort_values("t")
    for pid, g in fr.groupby("id"):
        t, born = g.t.to_numpy(), g.created_at_i.iat[0]
        prev = np.r_[born, t[:-1]]
        ret = t[(t - born >= gap_h * 3600) & (t - prev >= gap_h * 3600)]
        if len(ret):
            ev[pid] = min(ev.get(pid, np.inf), ret[0])
    E = pd.DataFrame({"id": list(ev), "t_ev": list(ev.values())})
    E = E[E.t_ev + a * 60 <= t_last]
    w = Mi.merge(E, on="id")
    before = w[w.t <= w.t_ev].sort_values("t").groupby("id").points.last()
    win = w[(w.t >= w.t_ev) & (w.t <= w.t_ev + a * 60)]
    out = pd.DataFrame(index=P.post_id)
    out["ev"] = out.index.isin(E.id).astype(int)
    out["ev_h"] = ((E.set_index("id").t_ev - P.set_index("post_id").created_at_i) / 3600).reindex(out.index)
    out["ev_gain"] = (win.groupby("id").points.max() - before.reindex(win.id.unique()).fillna(win.groupby("id").points.min())).reindex(out.index)
    wf = win[win.list == "front"]
    out["ev_front_best"] = wf.groupby("id").pos.min().reindex(out.index).fillna(999)
    out["ev_front_min"] = wf.groupby("id").t.nunique().reindex(out.index).fillna(0)
    return out.reset_index(drop=True)


def caught_line(T, name, out):
    k = int(T.y.sum())
    if k == 0:
        return
    T = T.assign(flag=T.s.rank(ascending=False, method="first") <= k)
    per = T.groupby("day").apply(lambda x: pd.Series({"hit": int((x.flag & (x.y == 1)).sum()), "n": int(x.y.sum())}))
    h, n = per.hit.to_numpy(), per.n.to_numpy()
    bs = [h[i].sum() / max(n[i].sum(), 1) for i in (rng.integers(0, len(per), len(per)) for _ in range(2000))]
    res = f"{h.sum() / max(n.sum(), 1):.1%} [{np.percentile(bs, 2.5):.1%}, {np.percentile(bs, 97.5):.1%}]"
    out[name] = res
    print(f"   {name:44s} {res}  (by day: " + ", ".join(f"{d} {a}/{b}" for d, a, b in zip(per.index, h, n)) + ")", flush=True)


BACKTEST = {15: 0.296, 60: 0.485}                      # posting-clock headlines on comparable inputs (Oct 2-14 / Sep-Oct)


def live_table(P, F, keep_idx, SC, top, days_after, out):
    """Running live table (orchestrator, 2026-11-04): per posting day, Caught at 15 min / 1 h with flags = that day's
    winners so far, the gap to the backtest, and the top 3 reasons the 15-min misses were missed."""
    T = P[["post_id", "day", "y"]].reset_index(drop=True)
    pick = lambda sc: sc.get("model + exposure (direction A)", sc["blend 50/50"])
    s15 = pick(SC[15])
    s60 = SC[60].get("model + votes blend (1 h fix)", pick(SC[60]))
    seen15 = F[15].iloc[keep_idx].seen.to_numpy() == 1
    front60 = F[60].iloc[keep_idx].front_best.to_numpy() < 999
    lag = np.array([next((k for k, x in enumerate(days_after(d)) if pid in top.get(x, ())), -1) for pid, d in zip(T.post_id, T.day)])
    print("\nLIVE TABLE (per posting day; flags = that day's winners so far; score = "
          f"{'per-minute model (direction A)' if 'model + exposure (direction A)' in SC[15] else 'blend 50/50'} at 15 min, "
          f"{'model + votes blend (1 h fix)' if 'model + votes blend (1 h fix)' in SC[60] else 'same'} at 1 h):", flush=True)
    print(f"   {'day':10s} {'seen15':>6s} {'lists settled':>13s} {'winners':>7s} {'15 min':>14s} {'gap':>6s} {'1 h':>14s} {'gap':>6s}  top miss reasons at 15 min", flush=True)
    rows = []
    for d, g in T.groupby("day"):
        i = g.index.to_numpy()
        k = int(g.y.sum())
        if k == 0:
            continue
        f15 = pd.Series(s15[i]).rank(ascending=False, method="first").to_numpy() <= k
        f60 = pd.Series(s60[i]).rank(ascending=False, method="first").to_numpy() <= k
        w = g.y.to_numpy() == 1
        c15, c60 = (f15 & w).sum() / k, (f60 & w).sum() / k
        miss = w & ~f15
        why = np.where(~seen15[i], "not seen by the recorder within 15 min",
              np.where(lag[i] >= 2, "re-up (first listed 2+ days after posting)",
              np.where(~front60[i], "late riser (not on the front page within 1 h)", "on the front page within 1 h, ranked below the cut")))
        reasons = pd.Series(why[miss]).value_counts().head(3)
        info = out["days"].get(d, {})
        rows.append({"day": d, "caught15": round(c15, 3), "caught60": round(c60, 3), "winners": k,
                     "gap15": round(c15 - BACKTEST[15], 3), "gap60": round(c60 - BACKTEST[60], 3), "miss_reasons": reasons.to_dict()})
        print(f"   {d:10s} {info.get('seen_by_15min', float('nan')):6.1%} {info.get('list_days_settled', 0):>9d} of 4 {k:7d} "
              f"{int((f15 & w).sum()):>3d}/{k:<3d} {c15:6.1%} {c15 - BACKTEST[15]:+6.1%} {int((f60 & w).sum()):>3d}/{k:<3d} {c60:6.1%} "
              f"{c60 - BACKTEST[60]:+6.1%}  " + "; ".join(f"{r} {n}" for r, n in reasons.items()), flush=True)
    out["live_table"] = rows


def main():
    M = LC.load_minute()
    cov = M.assign(day=pd.to_datetime(M.t, unit="s", utc=True).dt.strftime("%Y-%m-%d")).groupby(["day", "list"]).t.nunique().unstack()
    print("recorder minutes read per UTC day:\n" + cov.to_string(), flush=True)
    t_start, t_last = int(M.t.min()), int(M.t.max())
    P = OL.recent_history()
    P = P[(P.created_at_i >= t_start) & (P.created_at_i <= t_last - 60 * 60)].reset_index(drop=True)
    P["day"] = pd.to_datetime(P.created_at_i, unit="s", utc=True).dt.strftime("%Y-%m-%d")
    if os.environ.get("LIVE_INCLUDE_TODAY") != "1":                                   # default: only posting days already over
        P = P[P.day < time.strftime("%Y-%m-%d", time.gmtime())].reset_index(drop=True)
    # per-minute inputs at 15 min and 1 h (recorder sightings at or before created + age)
    Mi = M[M.id.isin(set(P.post_id))].merge(P[["post_id", "created_at_i"]].rename(columns={"post_id": "id"}), on="id")
    Mi["age"] = (Mi.t - Mi.created_at_i) / 60
    new_reads = np.sort(M[M.list == "newest"].t.unique())
    F = {age: minute_feats(P, Mi, age, new_reads) for age in AGES}
    P["seen15"] = F[15].seen.to_numpy().astype(bool)
    P["seen60"] = F[60].seen.to_numpy().astype(bool)
    P["pts15"], P["cm15"] = F[15].pts.to_numpy(), F[15].cm.to_numpy()
    # at-posting odds (deployed model), in batches
    import live_oct                                  # cached, 1,000-post batches in fresh processes (one big OL.score call ran out of memory)
    P["p_post"] = live_oct.odds_at_posting(P)
    # provisional labels
    L = pd.concat([pd.read_json(__import__("io").StringIO(x.download_as_text()), lines=True, dtype={"day": str}, convert_dates=False)
                   for x in LC.S._bucket().list_blobs(prefix="usersim_sim/hn_jobs/cache/listwatch/")])
    # reads sometimes miss pages (HN refuses some requests): use each day's latest read that has the whole top 30
    full = L[L["rank"] <= 30].groupby(["day", "read_at"]).size()
    full = full[full >= 30].reset_index()
    latest = full.groupby("day").read_at.max()
    top = {d: set(L[(L.day == d) & (L.read_at == latest[d]) & (L["rank"] <= 30)].post_id) for d in latest.index}
    settled = {d for d in latest.index if latest[d] >= pd.Timestamp(d, tz="UTC").timestamp() + 86400 + 48 * 3600}
    days_after = lambda d: [(pd.Timestamp(d) + pd.Timedelta(days=k)).strftime("%Y-%m-%d") for k in range(4)]
    P["y"] = [int(any(pid in top.get(x, ()) for x in days_after(d))) for pid, d in zip(P.post_id, P.day)]
    P["lists_read"] = [sum(x in top for x in days_after(d)) for d in P.day]
    P["lists_settled"] = [sum(x in settled for x in days_after(d)) for d in P.day]
    out = {"made_at": int(time.time()), "provisional": True, "posts": int(len(P)), "winners_so_far": int(P.y.sum()),
           "seen_by_15min": round(float(P.seen15.mean()), 3), "days": {}}
    rk = lambda x: pd.Series(np.asarray(x, float)).rank(pct=True).to_numpy()
    for d, g in P.groupby("day"):
        out["days"][d] = {"posts": int(len(g)), "winners_so_far": int(g.y.sum()), "seen_by_15min": round(float(g.seen15.mean()), 3),
                          "winners_seen_by_15min": int((g.seen15 & (g.y == 1)).sum()), "seen_by_1h": round(float(g.seen60.mean()), 3),
                          "winners_seen_by_1h": int((g.seen60 & (g.y == 1)).sum()),
                          "list_days_read": int(g.lists_read.iat[0]), "list_days_settled": int(g.lists_settled.iat[0])}
    cov15 = P.groupby("day").seen15.mean()
    FULL = sorted(d for d, v in cov15.items() if v >= 0.95)
    print(f"full-coverage posting days (>= 95% seen within 15 min): {FULL}", flush=True)
    out["full_coverage_days"] = FULL
    keep_idx = P.index.to_numpy()
    days = sorted(P.day.unique())
    print(f"PROVISIONAL live Caught: {len(P)} posts, {int(P.y.sum())} winners so far, posting days {days}", flush=True)
    SC = {}
    for age, label in ((60, "1 h (checkpoint 1)"), (15, "15 min (checkpoint 2)")):
        Fa = F[age].iloc[keep_idx].reset_index(drop=True)
        T = P[["day", "y"]].reset_index(drop=True)
        seen = Fa.seen.to_numpy() == 1
        votes = Fa.pts.to_numpy() + 3 * (Fa.front_best.to_numpy() < 999) + Fa.cm.to_numpy() * 1e-3
        odds = P.p_post.fillna(0).to_numpy()
        scores = {"votes (+ front page)": votes, "at-posting odds": odds, "blend 50/50": 0.5 * rk(votes) + 0.5 * rk(odds)}
        SC[age] = scores
        if len(days) >= MIN_DAYS_MODEL:                  # model on the recorder's own data, leave one posting day out
            import lightgbm as lgb
            X = pd.concat([Fa.drop(columns=["seen"]), pd.Series(odds, name="p_post")], axis=1)
            for mname, cols in (("model, no exposure inputs", [c for c in X.columns if c not in EXPO]),
                                ("model + exposure (direction A)", list(X.columns))):
                sm = np.zeros(len(T))
                for d in days:                           # leave one posting day out
                    te = (T.day == d).to_numpy()
                    sm[te] = lgb.LGBMClassifier(n_estimators=300, learning_rate=0.05, num_leaves=15, min_child_samples=20,
                                                verbose=-1, random_state=0).fit(X.loc[~te, cols], T.y[~te]).predict_proba(X.loc[te, cols])[:, 1]
                scores[mname] = sm
            if age == 60:                                # 1 h fix (late60_b.py, chosen on Nov 2-8): equal rank blend of the
                dd = T.day.to_numpy()                    # model and the votes score, ranked within each posting day
                bl = np.zeros(len(T))
                for d in days:
                    m = dd == d
                    bl[m] = 0.5 * rk(scores["model + exposure (direction A)"][m]) + 0.5 * rk(votes[m])
                scores["model + votes blend (1 h fix)"] = bl
        else:
            print(f"   [model on per-minute features: needs {MIN_DAYS_MODEL} posting days, have {len(days)}]", flush=True)
        print(f"Caught at {label}: seen by the recorder within {age} min: {seen.mean():.1%} of posts, "
              f"{int((seen & (T.y == 1).to_numpy()).sum())}/{int(T.y.sum())} winners", flush=True)
        for name, sc in scores.items():
            full = T.day.isin(FULL).to_numpy()                  # live headline (orchestrator 2026-11-04): days the
            if full.any():                                      # recorder saw >= 95% of posts within 15 min
                caught_line(T[full].assign(s=sc[full]), f"{age} min | FULL-COVERAGE days (headline) | {name}", out)
            caught_line(T.assign(s=sc), f"{age} min | all posts | {name}", out)
            caught_line(T[seen].assign(s=sc[seen]), f"{age} min | seen only | {name}", out)
    live_table(P, F, keep_idx, SC, top, days_after, out)
    # direction B: re-up clock (judged 15 min after the first /pool sighting or second-chance return to the front page)
    RC = reup_clock(P, Mi, t_last)
    cohort = RC.ev.to_numpy() == 1
    T = P[["day", "y"]].reset_index(drop=True)
    ev_score = RC.ev_gain.fillna(0).to_numpy() + 3 * (RC.ev_front_best.to_numpy() < 999) + RC.ev_front_min.to_numpy() * 0.01
    print(f"Re-up clock (direction B): posts with an exposure event {int(cohort.sum())} (median {np.nanmedian(RC.ev_h):.1f} h "
          f"after posting), winners among them {int(T.y[cohort].sum())} of {int(T.y.sum())}", flush=True)
    if cohort.any():
        caught_line(T[cohort].assign(s=ev_score[cohort]), "re-up clock | event cohort | gain + front page 15 min after the event", out)
        F15 = F[15].iloc[keep_idx].reset_index(drop=True)
        v15 = F15.pts.to_numpy() + 3 * (F15.front_best.to_numpy() < 999) + F15.cm.to_numpy() * 1e-3
        both = np.maximum(rk(v15), np.where(cohort, rk(np.where(cohort, ev_score, -1)), 0))
        caught_line(T.assign(s=v15), "15 min | all posts | posting clock only (votes + front page)", out)
        caught_line(T.assign(s=both), "15 min | all posts | posting clock + re-up clock (best of the two)", out)
    feats = pd.concat([P[["post_id", "day", "y", "p_post"]].reset_index(drop=True), RC.add_prefix("rc_")] +
                      [F[a].iloc[keep_idx].reset_index(drop=True).add_prefix(f"m{a}_") for a in AGES], axis=1)
    feats.to_parquet(os.path.join(os.path.dirname(__file__), "out", "live_minute_feats" + ("_today" if os.environ.get("LIVE_INCLUDE_TODAY") == "1" else "") + ".parquet"), index=False)
    print(json.dumps(out["days"]), flush=True)
    path = os.path.join(os.path.dirname(__file__), "out", f"live15_{time.strftime('%Y-%m-%d', time.gmtime())}.json")
    json.dump(out, open(path, "w"), indent=1)
    LC.S._bucket().blob(f"usersim_sim/hn_jobs/cache/live15/{os.path.basename(path)}").upload_from_filename(path)


if __name__ == "__main__":
    main()
