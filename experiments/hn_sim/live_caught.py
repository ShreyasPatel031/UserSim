"""Clean live test of Caught at 15 min / 1 h (no selection): Grok Bot's hn_minute recorder reads HN /news p1-3 (list "front"),
/newest and /pool, one page every ~12 s (/newest p1 about every 3-4 min) from 2026-10-31 02:13 UTC, so every post has observed votes and rank from its first minutes.

Posts: first seen on /newest within its top 5 (the first sighting is within ~4 min of posting; that time is the post's
birth). At age a: the latest points and comments seen at or before birth + a, best /news rank so far, minutes
on /news. Winners: in any settled daily top 30 (listwatch read 48 h+ after the list day ended) from the posting day
through 3 days later; only posting days whose 4 list days have all settled count. Flags = number of winners (pooled
over the scored days); Caught = winners flagged / winners; 95% interval resampling posting days.
Scores (no training on QN data, so no selection leak): points at age a; points with a front-page bonus.

    python live_caught.py
"""
import io
import json
import os

import numpy as np
import pandas as pd

import store as S

DIR = os.path.join(S.LOCAL, "hn_minute")
rng = np.random.default_rng(0)


def load_minute():
    b = S._bucket()
    os.makedirs(DIR, exist_ok=True)
    for x in b.list_blobs(prefix="usersim_sim/hn_jobs/cache/feeder/hn_minute/"):
        dst = os.path.join(DIR, x.name.split("/")[-1])
        if not os.path.exists(dst) or os.path.getsize(dst) != x.size:
            x.download_to_filename(dst)
    rows = []
    for f in sorted(os.listdir(DIR)):
        for line in open(os.path.join(DIR, f)):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            rows.append((r["id"], r["list"], r["page"], r["rank"], r.get("points"), r.get("comments"), r["fetched_at"]))
    M = pd.DataFrame(rows, columns=["id", "list", "page", "rank", "points", "comments", "t"])
    M["t"] = (pd.to_datetime(M.t, utc=True) - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(seconds=1)
    M["pos"] = (M.page - 1) * 30 + M["rank"]
    return M


def settled_lists():
    b = S._bucket()
    L = pd.concat([pd.read_json(io.StringIO(x.download_as_text()), lines=True, dtype={"day": str}, convert_dates=False)
                   for x in b.list_blobs(prefix="usersim_sim/hn_jobs/cache/listwatch/")])
    out = {}
    for d, g in L.groupby("day"):
        s = g[g.read_at >= pd.Timestamp(d, tz="UTC").timestamp() + 86400 + 48 * 3600]
        if len(s):
            s = s[s.read_at == s.read_at.max()]
            out[d] = set(s[s["rank"] <= 30].post_id)
    return out


def main():
    M = load_minute()
    cov = M.assign(day=pd.to_datetime(M.t, unit="s", utc=True).dt.strftime("%Y-%m-%d")).groupby(["day", "list"]).t.nunique().unstack()
    print("hn_minute coverage (minutes read per UTC day, of 1,440):\n" + cov.to_string(), flush=True)
    new = M[M.list == "newest"].sort_values("t")
    first = new.drop_duplicates("id")
    first = first[(first.pos <= 5) & (first.t >= M.t.min() + 600)]
    born = first.set_index("id").t
    settled = settled_lists()
    P = pd.DataFrame({"id": born.index, "born": born.to_numpy()})
    P["day"] = pd.to_datetime(P.born, unit="s", utc=True).dt.strftime("%Y-%m-%d")
    days_ok = {d for d in P.day.unique() if all((pd.Timestamp(d) + pd.Timedelta(days=k)).strftime("%Y-%m-%d") in settled for k in range(4))}
    print(f"hn_minute rows {len(M)}, posts {len(P)}, posting days {sorted(P.day.unique())}; settled list days {sorted(settled)}; "
          f"scorable posting days {sorted(days_ok)}", flush=True)
    if not days_ok:
        print("no posting day has all its list days settled yet", flush=True)
        return
    P = P[P.day.isin(days_ok)].reset_index(drop=True)
    P["y"] = [int(any(i in settled[(pd.Timestamp(d) + pd.Timedelta(days=k)).strftime("%Y-%m-%d")] for k in range(4)))
              for i, d in zip(P.id, P.day)]
    Mi = M[M.id.isin(set(P.id))].merge(P[["id", "born"]], on="id")
    Mi["age"] = (Mi.t - Mi.born) / 60
    for a in (15, 60):
        w = Mi[Mi.age <= a]
        g = w.groupby("id")
        f = pd.DataFrame({"pts": g.points.max(), "cm": g.comments.max(),
                          "best_news": w[w.list == "front"].groupby("id").pos.min(),
                          "min_news": w[w.list == "front"].groupby("id").t.nunique()}).reindex(P.id)
        f = f.fillna({"pts": 1, "cm": 0, "best_news": 999, "min_news": 0})
        for name, s in (("points", f.pts.to_numpy() + f.cm.to_numpy() * 1e-3),
                        ("points + front-page bonus", np.log1p(f.pts.to_numpy()) + (f.best_news.to_numpy() <= 30) * 1.0
                         + np.log1p(f.min_news.to_numpy()) * 0.3)):
            T = P.assign(s=s)
            k = int(T.y.sum())
            T["flag"] = T.s.rank(ascending=False, method="first") <= k
            d = T.groupby("day").apply(lambda x: pd.Series({"hit": int((x.flag & (x.y == 1)).sum()), "n": int(x.y.sum())}))
            h, n = d.hit.to_numpy(), d.n.to_numpy()
            bs = [h[i].sum() / n[i].sum() for i in (rng.integers(0, len(d), len(d)) for _ in range(2000))]
            print(f"live Caught at {a} min, {name}: {h.sum() / n.sum():.1%} [{np.percentile(bs, 2.5):.1%}, {np.percentile(bs, 97.5):.1%}] "
                  f"({len(P)} posts, {k} winners, {len(d)} posting days)", flush=True)


if __name__ == "__main__":
    main()
