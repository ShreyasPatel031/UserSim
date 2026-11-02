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


def main():
    M = LC.load_minute()
    cov = M.assign(day=pd.to_datetime(M.t, unit="s", utc=True).dt.strftime("%Y-%m-%d")).groupby(["day", "list"]).t.nunique().unstack()
    print("recorder minutes read per UTC day:\n" + cov.to_string(), flush=True)
    t_start, t_last = int(M.t.min()), int(M.t.max())
    P = OL.recent_history()
    P = P[(P.created_at_i >= t_start) & (P.created_at_i <= t_last - 15 * 60)].reset_index(drop=True)
    P["day"] = pd.to_datetime(P.created_at_i, unit="s", utc=True).dt.strftime("%Y-%m-%d")
    # inputs at 15 min
    Mi = M[M.id.isin(set(P.post_id))].merge(P[["post_id", "created_at_i"]].rename(columns={"post_id": "id"}), on="id")
    w = Mi[(Mi.t >= Mi.created_at_i) & (Mi.t <= Mi.created_at_i + 15 * 60)].sort_values("t")
    last = w.drop_duplicates("id", keep="last").set_index("id")
    P["seen15"] = P.post_id.isin(last.index)
    P["pts15"] = P.post_id.map(w.groupby("id").points.max()).fillna(1)
    P["cm15"] = P.post_id.map(w.groupby("id").comments.max()).fillna(0)
    P["front15"] = P.post_id.map(w[w.list == "front"].groupby("id").pos.min()).fillna(999)
    # at-posting odds (deployed model), in batches
    S = OL.score(P[["post_id", "title", "url", "author", "created_at_i", "text"]].reset_index(drop=True), now=0)
    S = S.drop_duplicates("post_id").set_index("post_id")
    P["p_post"] = P.post_id.map(S.p_top30)
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
    P = P[P.day < time.strftime("%Y-%m-%d", time.gmtime())]                # only posting days already over
    out = {"made_at": int(time.time()), "provisional": True, "posts": int(len(P)), "winners_so_far": int(P.y.sum()),
           "seen_by_15min": round(float(P.seen15.mean()), 3), "days": {}}
    rk = lambda s: s.rank(pct=True)
    scores = {"votes at 15 min": P.pts15 + P.cm15 * 1e-3, "at-posting odds": P.p_post.fillna(0),
              "blend 50/50": 0.5 * rk(P.pts15 + P.cm15 * 1e-3) + 0.5 * rk(P.p_post.fillna(0))}
    for d, g in P.groupby("day"):
        out["days"][d] = {"posts": int(len(g)), "winners_so_far": int(g.y.sum()), "seen_by_15min": round(float(g.seen15.mean()), 3),
                          "winners_seen_by_15min": int((g.seen15 & (g.y == 1)).sum()),
                          "list_days_read": int(g.lists_read.iat[0]), "list_days_settled": int(g.lists_settled.iat[0])}
    print(f"PROVISIONAL live Caught at 15 min: {len(P)} posts, {int(P.y.sum())} winners so far, posting days "
          f"{sorted(P.day.unique())}; seen by the recorder within 15 min: {P.seen15.mean():.1%}", flush=True)
    for name, s in [(n, (s, None)) for n, s in scores.items()] + [(n + " | seen within 15 min only", (s, P.seen15.to_numpy())) for n, s in scores.items()]:
        s, keep = s
        T = P.assign(s=s.to_numpy())
        if keep is not None:
            T = T[keep]
        k = int(T.y.sum())
        T["flag"] = T.s.rank(ascending=False, method="first") <= k
        per = T.groupby("day").apply(lambda x: pd.Series({"hit": int((x.flag & (x.y == 1)).sum()), "n": int(x.y.sum())}))
        h, n = per.hit.to_numpy(), per.n.to_numpy()
        bs = [h[i].sum() / max(n[i].sum(), 1) for i in (rng.integers(0, len(per), len(per)) for _ in range(2000))]
        res = f"{h.sum() / max(n.sum(), 1):.1%} [{np.percentile(bs, 2.5):.1%}, {np.percentile(bs, 97.5):.1%}]"
        out[name] = res
        print(f"   {name:18s} {res}  (by day: " + ", ".join(f"{d} {a}/{b}" for d, a, b in zip(per.index, h, n)) + ")", flush=True)
    print(json.dumps(out["days"]), flush=True)
    path = os.path.join(os.path.dirname(__file__), "out", f"live15_{time.strftime('%Y-%m-%d', time.gmtime())}.json")
    json.dump(out, open(path, "w"), indent=1)
    LC.S._bucket().blob(f"usersim_sim/hn_jobs/cache/live15/{os.path.basename(path)}").upload_from_filename(path)


if __name__ == "__main__":
    main()
