"""Live recorder (runs on hn-sim-1): the front page top 30 every 5 minutes, and every new story's points and comment
count when it is 15, 30 and 60 minutes old (official Firebase API). Early points are the strongest live signal and
exist nowhere historically, so they have to be recorded going forward. Tables: hn_frontpage, hn_early_points.

    python live.py
"""
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

import store as S
from fetch import FIREBASE, get
from frontpage import snap

AGES = (15, 30, 60)       # minutes
TOL = 150                  # seconds either side


def main():
    fp, ep, seen, last_fp, last_flush = [], [], set(), 0, time.time()
    while True:
        now = time.time()
        try:
            if now - last_fp >= 300:
                fp += snap()
                last_fp = now
            ids = get(f"{FIREBASE}/newstories.json") or []
            with ThreadPoolExecutor(16) as ex:
                items = list(ex.map(lambda i: get(f"{FIREBASE}/item/{i}.json") or {}, ids[:300]))
            for it in items:
                if not it.get("time"):
                    continue
                age = now - it["time"]
                for a in AGES:
                    if abs(age - a * 60) <= TOL and (it["id"], a) not in seen:
                        seen.add((it["id"], a))
                        ep.append({"item_id": it["id"], "age_min": a, "observed_at": int(now), "age_s": int(age),
                                   "points": it.get("score"), "comments": it.get("descendants"), "title": it.get("title"),
                                   "url": it.get("url"), "by": it.get("by"), "time": it["time"]})
            if now - last_flush >= 1800:
                S.write("hn_frontpage", pd.DataFrame(fp))
                S.write("hn_early_points", pd.DataFrame(ep))
                fp, ep, last_flush = [], [], now
                seen = {k for k in seen if k[1] == 60 or True} if len(seen) < 200000 else set()
        except Exception as exc:  # noqa: BLE001
            print("live error:", exc, flush=True)
        time.sleep(120)


if __name__ == "__main__":
    main()
