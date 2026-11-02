"""Live 15-min scoring with an October-trained model (orchestrator, 2026-11-02: don't wait for 5 live days).
Train on Oct 2-14 posts (Wayback /newest archive, dense captures; labels settled) with only inputs that the live
recorder also gives: the odds tool's at-posting P(top 30), /newest votes at the latest sighting by 15 min (score, its
age, votes per minute, rank on /newest, push-down rate, comments), best /news position by 15 min, exposure on /newest
page 1 (share of reads showing it, position-weighted minutes, votes per exposure-minute, posts in the 30 min before,
hour). Score every live post (hn_minute, per-minute reads) the same way; Caught at 15 min on each posting day, all
posts and seen-only, labels PROVISIONAL (top 30 so far).

    python live_oct.py
"""
import io
import json
import os
import time

import lightgbm as lgb
import numpy as np
import pandas as pd

import live_caught as LC
import odds_live as OL
import top100 as H

FEATS = ["p_post", "v_score", "v_age", "v_rate", "v_rank_new", "v_push", "v_comments", "v_front", "x_share", "x_w", "x_vpe",
         "x_vol30", "x_hour", "v_has"]
rng = np.random.default_rng(0)


def feats_from_sightings(P, S, reads, a=15):
    """P: post_id, created_at_i. S: sightings (id, t, list, pos, points, comments), list in {newest, front}.
    reads: sorted times of /newest reads (captures). Same definitions for the archive and the live recorder."""
    born = P.set_index("post_id").created_at_i
    S = S[S.id.isin(born.index)].copy()
    S["age"] = (S.t - S.id.map(born).to_numpy()) / 60
    S = S[(S.age >= 0) & (S.age <= a)]
    N = S[S.list == "newest"].sort_values("t")
    last = N.drop_duplicates("id", keep="last").set_index("id")
    out = pd.DataFrame({"post_id": P.post_id.to_numpy()})
    pid = out.post_id
    out["v_has"] = pid.isin(last.index).astype(int).to_numpy()
    out["v_score"] = pid.map(last.points).to_numpy()
    out["v_age"] = pid.map(last.age).to_numpy()
    out["v_rate"] = (out.v_score - 1) / out.v_age.clip(lower=1)
    out["v_rank_new"] = pid.map(last.pos).to_numpy()
    out["v_push"] = out.v_rank_new / out.v_age.clip(lower=1)
    out["v_comments"] = pid.map(last.comments).to_numpy()
    out["v_front"] = pid.map(S[S.list == "front"].groupby("id").pos.min()).to_numpy()
    b = born.reindex(pid).to_numpy()
    n_reads = np.searchsorted(reads, b + a * 60, side="right") - np.searchsorted(reads, b)
    seen = pid.map(N.groupby("id").t.nunique()).fillna(0).to_numpy()
    wsum = pid.map(N.assign(w=1 / np.sqrt(N.pos.clip(lower=1))).groupby("id").w.sum()).fillna(0).to_numpy()
    out["x_share"] = np.where(n_reads > 0, seen / np.maximum(n_reads, 1), np.nan)
    out["x_w"] = np.where(n_reads > 0, wsum / np.maximum(n_reads, 1) * a, np.nan)
    out["x_vpe"] = (out.v_score - 1) / (out.x_share * a).clip(lower=0.5)
    ct = np.sort(b)
    out["x_vol30"] = np.searchsorted(ct, b) - np.searchsorted(ct, b - 1800)
    out["x_hour"] = (b // 3600) % 24
    return out


def odds_at_posting(P):
    """The odds tool's at-posting P(top 30), cached per post. Each batch of 1,000 runs in a fresh process
    (python live_oct.py odds <file>): memory grows across OL.score calls inside one process."""
    import subprocess
    import sys
    path = os.path.join(H.CACHE, "odds_at_posting.parquet")
    part = path + ".partial"
    if os.path.exists(part):                          # keep work from an interrupted run
        old = pd.read_parquet(part)
        if os.path.exists(path):
            old = pd.concat([pd.read_parquet(path), old])
        old.drop_duplicates("post_id", keep="last").to_parquet(path, index=False)
        os.remove(part)
    while True:
        have = pd.read_parquet(path) if os.path.exists(path) else pd.DataFrame(columns=["post_id", "p_post"])
        todo = P[~P.post_id.isin(have.post_id)]
        if todo.empty:
            break
        tmp = os.path.join(H.CACHE, "odds_todo.parquet")
        todo.head(1000)[["post_id", "title", "url", "author", "created_at_i", "text"]].to_parquet(tmp, index=False)
        subprocess.run([sys.executable, "-W", "ignore", __file__, "odds", tmp], check=True)
        print(f"   odds at posting: {len(todo) - min(1000, len(todo))} left", flush=True)
    have = pd.read_parquet(path)
    return P.post_id.map(have.drop_duplicates("post_id").set_index("post_id").p_post).to_numpy()


def odds_batch(tmp):
    path = os.path.join(H.CACHE, "odds_at_posting.parquet")
    R = pd.read_parquet(tmp).reset_index(drop=True)
    R = R.assign(url=R.url.fillna(""), title=R.title.fillna(""), text=R.text.fillna(""))
    new = OL.score(R, now=0)[["post_id", "p_top30"]].rename(columns={"p_top30": "p_post"})
    if os.path.exists(path):
        new = pd.concat([pd.read_parquet(path), new]).drop_duplicates("post_id", keep="last")
    new.to_parquet(path, index=False)


def _unused(P):
    R = P[["post_id", "title", "url", "author", "created_at_i", "text"]].reset_index(drop=True)
    R = R.assign(url=R.url.fillna(""), title=R.title.fillna(""), text=R.text.fillna(""))
    S = OL.score(R, now=0)
    return P.post_id.map(S.drop_duplicates("post_id").set_index("post_id").p_top30).to_numpy()


def archive():
    p = H.stories()
    L = OL.lists()
    win = set(L[L["rank"] <= 30].post_id)
    Q = p[(p.day >= "2026-10-02") & (p.day <= "2026-10-14")][["post_id", "day"]]
    Q = Q.assign(y=Q.post_id.isin(win).astype(int))
    P = p[p.post_id.isin(Q.post_id)][["post_id", "title", "url", "author", "created_at_i", "text"]].reset_index(drop=True)
    A = pd.read_json(os.path.join(H.CACHE, "early_votes", "early_snapshots.jsonl"), lines=True, convert_dates=False)
    A["t"] = (pd.to_datetime(A.capture_ts.astype(str), format="%Y%m%d%H%M%S", utc=True) - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(seconds=1)
    off = {"news": 0, "news_p2": 30, "news_p3": 60}
    A = A[A.page.isin(["newest"] + list(off))]
    S = pd.DataFrame({"id": A.item_id, "t": A.t, "list": np.where(A.page == "newest", "newest", "front"),
                      "pos": A["rank"] + A.page.map(off).fillna(0), "points": A.score, "comments": A.comments})
    reads = np.sort(A[A.page == "newest"].t.unique())
    F = feats_from_sightings(P, S, reads)
    F["p_post"] = odds_at_posting(P)
    return F.merge(Q, on="post_id")


def live():
    import live15 as L15  # noqa: F401  (same label rules)
    M = LC.load_minute()
    t0, t1 = int(M.t.min()), int(M.t.max())
    P = OL.recent_history()
    P = P[(P.created_at_i >= t0) & (P.created_at_i <= t1 - 15 * 60)].reset_index(drop=True)
    P["day"] = pd.to_datetime(P.created_at_i, unit="s", utc=True).dt.strftime("%Y-%m-%d")
    P = P[P.day < time.strftime("%Y-%m-%d", time.gmtime())].reset_index(drop=True)
    S = M[M.list.isin(["newest", "front"])].rename(columns={})[["id", "t", "list", "pos", "points", "comments"]]
    reads = np.sort(M[M.list == "newest"].t.unique())
    F = feats_from_sightings(P, S, reads)
    F["p_post"] = odds_at_posting(P)
    L = pd.concat([pd.read_json(io.StringIO(x.download_as_text()), lines=True, dtype={"day": str}, convert_dates=False)
                   for x in LC.S._bucket().list_blobs(prefix="usersim_sim/hn_jobs/cache/listwatch/") if x.size > 0])
    full = L[L["rank"] <= 30].groupby(["day", "read_at"]).size()
    full = full[full >= 30].reset_index()
    latest = full.groupby("day").read_at.max()
    top = {d: set(L[(L.day == d) & (L.read_at == latest[d]) & (L["rank"] <= 30)].post_id) for d in latest.index}
    after = lambda d: [(pd.Timestamp(d) + pd.Timedelta(days=k)).strftime("%Y-%m-%d") for k in range(4)]
    F["day"] = P.day.to_numpy()
    F["y"] = [int(any(i in top.get(x, ()) for x in after(d))) for i, d in zip(P.post_id, P.day)]
    F["lists_read"] = [sum(x in top for x in after(d)) for d in P.day]
    return F


def caught_str(T, s):
    k = int(T.y.sum())
    if k == 0:
        return "no winners yet"
    f = pd.Series(s).rank(ascending=False, method="first").to_numpy() <= k
    hit = int((f & (T.y.to_numpy() == 1)).sum())
    return f"{hit / k:.1%} ({hit}/{k})"


def main():
    A = archive()
    print(f"archive Oct 2-14: {len(A)} posts, {int(A.y.sum())} winners, with a /newest sighting by 15 min {A.v_has.mean():.1%}", flush=True)
    m = lgb.LGBMClassifier(n_estimators=500, learning_rate=0.03, num_leaves=15, min_child_samples=30, subsample=0.8,
                           subsample_freq=1, colsample_bytree=0.8, verbose=-1, random_state=0).fit(A[FEATS], A.y)
    Lv = live()
    Lv["s"] = m.predict_proba(Lv[FEATS])[:, 1]
    Lv["s_votes"] = Lv.v_score.fillna(1) + 3 * Lv.v_front.notna()
    out = {"made_at": int(time.time()), "provisional": True, "days": {}}
    print("PROVISIONAL live Caught at 15 min, Oct-trained model (flags = winners per posting day):", flush=True)
    for d, g in Lv.groupby("day"):
        seen = g.v_has == 1
        r = {"posts": int(len(g)), "winners_so_far": int(g.y.sum()), "list_days_read": int(g.lists_read.iat[0]),
             "seen_by_15min": round(float(seen.mean()), 3), "winners_seen": int((seen & (g.y == 1)).sum()),
             "model_all": caught_str(g, g.s), "model_seen": caught_str(g[seen], g.s[seen]),
             "votes_all": caught_str(g, g.s_votes), "odds_all": caught_str(g, g.p_post.fillna(0))}
        out["days"][d] = r
        print(f"   {d}: {r}", flush=True)
    path = os.path.join(os.path.dirname(__file__), "out", f"live_oct_{time.strftime('%Y-%m-%d', time.gmtime())}.json")
    json.dump(out, open(path, "w"), indent=1)


def export_atposting(hist=False):
    """For E5's simulator: the deployed odds tool's at-posting P(top 30) for every live post since the recorder
    started (hn_jobs/cache/live_atposting/<day>.parquet: post_id, p_top30, made_at), and with hist=True for every
    Sep 1 - Oct 14 post (atposting_hist.parquet; the odds model was fit on Jul 1 - Aug 15 + isotonic on Aug 16-31,
    so these are out-of-sample)."""
    import store as S
    b = S._bucket()
    M = LC.load_minute()
    P = OL.recent_history()
    P = P[P.created_at_i >= int(M.t.min())].reset_index(drop=True)
    P["day"] = pd.to_datetime(P.created_at_i, unit="s", utc=True).dt.strftime("%Y-%m-%d")
    P["p_top30"] = odds_at_posting(P)
    now = int(time.time())
    for d, g in P.groupby("day"):
        f = os.path.join(H.CACHE, f"live_atposting_{d}.parquet")
        g[["post_id", "p_top30"]].assign(made_at=now).to_parquet(f, index=False)
        b.blob(f"usersim_sim/hn_jobs/cache/live_atposting/{d}.parquet").upload_from_filename(f)
        print(f"live_atposting/{d}.parquet: {len(g)} posts", flush=True)
    if hist:
        p = H.stories()
        Hh = p[(p.day >= "2026-09-01") & (p.day <= "2026-10-14")].reset_index(drop=True)
        Hh["p_top30"] = odds_at_posting(Hh)
        f = os.path.join(H.CACHE, "atposting_hist.parquet")
        Hh[["post_id", "day", "p_top30"]].to_parquet(f, index=False)
        b.blob("usersim_sim/hn_jobs/cache/atposting_hist.parquet").upload_from_filename(f)
        print(f"atposting_hist.parquet: {len(Hh)} posts", flush=True)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 2 and sys.argv[1] == "odds":
        odds_batch(sys.argv[2])
    elif len(sys.argv) > 1 and sys.argv[1] == "export":
        export_atposting(hist="hist" in sys.argv)
    else:
        main()
