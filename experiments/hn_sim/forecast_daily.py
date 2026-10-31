"""Live forecast of today's HN daily list (news.ycombinator.com/front?day=today), with the backtested v4 code path
(daily_v4.series / candidates / features).

    python forecast_daily.py train              # fit one ranker per forecast time on daily_v4.parquet -> fd_v4_models.pkl
    python forecast_daily.py now [top=30]       # forecast today's top 30 as of now -> forecast_daily/<day>/<HHMM>.json

Live inputs: candidates from Algolia (stories of the last 7 days with 5+ points; older than 72 h only if on HN's top 90
now), their Quality News 10-minute series (qn.parse with QN_FINE), and the last 7 days' lists (a story on an earlier
list cannot be on today's). The model for the forecast time nearest to now is used (votes/page inputs only).
"""
import json
import os
import pickle
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import requests

os.environ.setdefault("QN_FINE", "1")
import daily_v4 as V  # noqa: E402
import qn  # noqa: E402
import top100 as H  # noqa: E402

MODELS = os.path.join(H.CACHE, "fd_v4_models.pkl")
OUT = os.path.join(H.CACHE, "forecast_daily")
UA = {"User-Agent": "atelier-research (HN daily-list forecast)"}


def cols(t):
    return ["on_earlier_list"] + [f"{t}_{c}" for c in V.VC]


def train():
    C = pd.read_parquet(os.path.join(H.CACHE, "daily_v4.parquet"))
    models = {}
    for t in V.TIMES:
        D = C[C[f"{t}_visible"] == 1]
        models[t] = V.fit_rank(D, cols(t))
        print("trained", t, D.day.nunique(), "days", flush=True)
    pickle.dump(models, open(MODELS, "wb"))


def recent_stories(t_from: int) -> pd.DataFrame:
    out = []
    for lo in range(t_from, int(time.time()), 6 * 3600):        # 6-hour slices keep each query under Algolia's 1,000
        r = requests.get("https://hn.algolia.com/api/v1/search_by_date", timeout=30, params={
            "tags": "story", "hitsPerPage": 1000,
            "numericFilters": f"created_at_i>={lo},created_at_i<{lo + 6 * 3600},points>=5"}).json()
        out += [{"post_id": int(h["objectID"]), "title": h.get("title"), "url": h.get("url"), "points": h.get("points"),
                 "created_at_i": h["created_at_i"]} for h in r.get("hits", [])]
    return pd.DataFrame(out).drop_duplicates("post_id")


def earlier_lists(day: pd.Timestamp) -> set:
    ids = set()
    for k in range(1, 8):
        d = (day - pd.Timedelta(days=k)).strftime("%Y-%m-%d")
        for page in (1, 2, 3, 4):
            html = requests.get("https://news.ycombinator.com/front", params={"day": d, "p": page}, headers=UA, timeout=30).text
            ids |= {int(x) for x in re.findall(r"<tr class=['\"]athing[^'\"]*['\"] id=['\"](\d+)['\"]", html)}
            time.sleep(2)
    return ids


def now(top=30):
    models = pickle.load(open(MODELS, "rb"))
    T = time.time()
    day = pd.Timestamp(T, unit="s").normalize()
    t0 = day.timestamp()
    t1 = t0 + 86400
    st = recent_stories(int(t1 - 7 * 86400))
    top90 = set(requests.get("https://hacker-news.firebaseio.com/v0/topstories.json", timeout=30).json()[:90])
    st = st[(st.created_at_i >= t1 - 72 * 3600) | st.post_id.isin(top90)]
    print(len(st), "candidates; fetching Quality News series", flush=True)

    def one(row):
        r = requests.get(f"https://news.social-protocols.org/stats?id={row.post_id}", timeout=60, headers=qn._s.headers)
        return {"post_id": row.post_id, "status": r.status_code, **(qn.parse(r.text, int(row.created_at_i)) if r.status_code == 200 else {})}
    with ThreadPoolExecutor(3) as ex:
        q = pd.DataFrame(list(ex.map(one, st.itertuples())))
    q = q[(q.status == 200) & q.qn_up_10m.map(lambda x: isinstance(x, list))].reset_index(drop=True)
    S = V.series(q, q.post_id.map(st.set_index("post_id").created_at_i).to_numpy().astype(float))
    C = V.candidates(S, [day.strftime("%Y-%m-%d")])
    off = (t1 - T) / 3600
    name = min(V.TIMES, key=lambda k: abs(V.TIMES[k] - off))
    V.features(C, S, name, np.full(len(C), T))
    C["on_earlier_list"] = C.post_id.isin(earlier_lists(day)).astype(np.int8)
    C = C[C[f"{name}_visible"] == 1].copy()
    C["score"] = np.where(C.on_earlier_list == 1, -1e9, models[name].predict(C[cols(name)]))
    C = C.merge(st[["post_id", "title", "url"]], on="post_id", how="left").sort_values("score", ascending=False)
    res = {"day": day.strftime("%Y-%m-%d"), "made_at": pd.Timestamp(T, unit="s").isoformat(), "model": name,
           "top": [{"rank": i + 1, "post_id": int(r.post_id), "title": r.title, "url": r.url,
                    "points_now": float(r[f"{name}_points"]), "rank_now": float(r[f"{name}_rank_now"])}
                   for i, r in enumerate(C.head(top).itertuples())]}
    os.makedirs(os.path.join(OUT, res["day"]), exist_ok=True)
    path = os.path.join(OUT, res["day"], pd.Timestamp(T, unit="s").strftime("%H%M") + ".json")
    json.dump(res, open(path, "w"), indent=1)
    print("saved", path, flush=True)
    for x in res["top"][:top]:
        print(x["rank"], x["post_id"], x["title"])
    return res


if __name__ == "__main__":
    {"train": train, "now": lambda: now(int(sys.argv[2]) if len(sys.argv) > 2 else 30)}[sys.argv[1]]()
