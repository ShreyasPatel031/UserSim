"""Why the live hourly daily-list forecast found 47-60% of the top 30 at 21:00 on Oct 31 / Nov 1 (backtest 80.2%)
(orchestrator, 2026-11-04). Replays the backtest code path (daily_v4 series / candidates / features at the live
forecast's own time T, same fd_v4 models) from Quality News series fetched now and cut at T, and classifies every real
top-30 post the live forecast missed.

    python diag_live21.py [HHMM=2105]
"""
import io
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import requests

os.environ.setdefault("QN_FINE", "1")
import daily_v4 as V  # noqa: E402
import forecast_daily as FD  # noqa: E402
import qn  # noqa: E402
import store as S  # noqa: E402
import top100 as H  # noqa: E402

DAYS = ["2026-10-31", "2026-11-01"]
HM = sys.argv[1] if len(sys.argv) > 1 else "2105"
b = S._bucket()
L = pd.concat([pd.read_json(io.StringIO(x.download_as_text()), lines=True, dtype={"day": str}, convert_dates=False)
               for x in b.list_blobs(prefix="usersim_sim/hn_jobs/cache/listwatch/")])


def real_top30(d):
    g = L[L.day == d]
    end = pd.Timestamp(d, tz="UTC").timestamp() + 86400
    s = g[g.read_at >= end + 48 * 3600]
    g = s if len(s) else g
    g = g[g.read_at == g.read_at.max()]
    return g[g["rank"] <= 30].set_index("post_id")["rank"]


def algolia(lo, hi):
    out = []
    for a in range(lo, hi, 6 * 3600):
        r = requests.get("https://hn.algolia.com/api/v1/search_by_date", timeout=30, params={
            "tags": "story", "hitsPerPage": 1000, "numericFilters": f"created_at_i>={a},created_at_i<{min(a + 6 * 3600, hi)},points>=5"}).json()
        out += [{"post_id": int(h["objectID"]), "title": h.get("title"), "points": h.get("points"), "created_at_i": h["created_at_i"]}
                for h in r.get("hits", [])]
        time.sleep(0.5)
    return pd.DataFrame(out).drop_duplicates("post_id")


def main():
    models = __import__("pickle").load(open(FD.MODELS, "rb"))
    t_lo = int(pd.Timestamp(DAYS[0], tz="UTC").timestamp()) + 86400 - 7 * 86400
    t_hi = int(pd.Timestamp(DAYS[-1], tz="UTC").timestamp()) + 86400
    st = algolia(t_lo, t_hi)
    reals = {d: real_top30(d) for d in DAYS}
    need = set(st.post_id) | set().union(*[set(r.index) for r in reals.values()])
    print(f"{len(need)} stories to fetch from Quality News", flush=True)

    def one(pid):
        born = st.set_index("post_id").created_at_i.get(pid)
        if born is None:
            it = requests.get(f"https://hacker-news.firebaseio.com/v0/item/{pid}.json", timeout=30).json() or {}
            born = it.get("time")
        try:
            r = requests.get(f"https://news.social-protocols.org/stats?id={pid}", timeout=60, headers=qn._s.headers)
            return {"post_id": pid, "born": born, "status": r.status_code, **(qn.parse(r.text, int(born)) if r.status_code == 200 and born else {})}
        except requests.RequestException:
            return {"post_id": pid, "born": born, "status": -1}
    with ThreadPoolExecutor(3) as ex:
        q = pd.DataFrame(list(ex.map(one, sorted(need))))
    ok = (q.status == 200) & q.get("qn_up_10m", pd.Series([None] * len(q))).map(lambda x: isinstance(x, list))
    noqn = set(q.post_id[~ok])
    q = q[ok].reset_index(drop=True)
    Sx = V.series(q, q.born.to_numpy().astype(float))
    out = {}
    for d in DAYS:
        live = json.loads(b.get_blob(f"usersim_sim/hn_jobs/cache/forecast_daily/{d}/{HM}.json").download_as_text())
        T = pd.Timestamp(live["made_at"]).tz_localize("UTC").timestamp() if pd.Timestamp(live["made_at"]).tzinfo is None else pd.Timestamp(live["made_at"]).timestamp()
        name = live["model"]
        live_top = [r["post_id"] for r in live["top"][:30]]
        live_pts = {r["post_id"]: r["points_now"] for r in live["top"][:30]}
        C = V.candidates(Sx, [d])
        V.features(C, Sx, name, np.full(len(C), T))
        earlier = set(L[(L.day < d) & (L.day >= (pd.Timestamp(d) - pd.Timedelta(days=7)).strftime("%Y-%m-%d")) & (L["rank"] <= 90)].post_id)
        C["on_earlier_list"] = C.post_id.isin(earlier).astype(np.int8)
        vis = C[C[f"{name}_visible"] == 1].copy()
        ranker, top30 = models[name]
        vis["score"] = np.where(vis.on_earlier_list == 1, -1e9, V.hybrid(vis.day, top30.predict_proba(vis[FD.cols(name)])[:, 1],
                                                                         ranker.predict(vis[FD.cols(name)])))
        vis = vis.sort_values("score", ascending=False)
        rep_top = list(vis.post_id.head(30))
        real = reals[d]
        rows = []
        born = dict(zip(q.post_id, q.born))
        pts_T = dict(zip(vis.post_id, vis[f"{name}_points"]))
        for pid in real.index:
            if pid in live_top:
                continue
            if pid in noqn:
                cause = "no Quality News series (even now)"
            elif born.get(pid, 0) >= T:
                cause = "posted after the forecast time"
            elif pid not in set(vis.post_id):
                cause = "not visible at T in the backtest rule either"
            elif pts_T.get(pid, 0) < 5:
                cause = "under 5 points at T (live candidate filter; backtest has none)"
            elif pid in rep_top:
                cause = "replay (backtest path) has it in its top 30, live did not: live input differed"
            else:
                cause = "replay misses it too (model miss)"
            rows.append({"post_id": pid, "real_rank": int(real[pid]), "cause": cause, "pts_at_T_replay": pts_T.get(pid)})
        M = pd.DataFrame(rows)
        common = [p for p in live_top if p in pts_T]
        lag = np.array([pts_T[p] - live_pts[p] for p in common])
        out[d] = {"live_found": len(set(live_top) & set(real.index)), "replay_found": len(set(rep_top) & set(real.index)),
                  "missed_by_live": len(M), "causes": M.cause.value_counts().to_dict(),
                  "live_top30_points_vs_replay_at_T": {"n": len(common), "median_replay_minus_live": float(np.median(lag)) if len(lag) else None,
                                                       "share_live_lower": float((lag > 0).mean()) if len(lag) else None}}
        print(d, json.dumps(out[d]), flush=True)
        print(M.sort_values("real_rank").to_string(index=False), flush=True)
    tot = pd.Series(dtype=int)
    for d in DAYS:
        tot = tot.add(pd.Series(out[d]["causes"]), fill_value=0)
    print("ALL causes:", tot.sort_values(ascending=False).astype(int).to_dict(), flush=True)


if __name__ == "__main__":
    main()
