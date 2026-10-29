"""Record the live Hacker News front page (official Firebase API) every few minutes: rank, id, points, comments, age.
This is the ground truth for "live top 10" (HN keeps no rank history, so it has to be collected going forward).
Rows buffer locally and go to the warehouse table hn_frontpage every flush.

    python frontpage.py [every_s=300] [flush_every=6]
"""
from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

import store as S
from fetch import FIREBASE, get

TOP = 30


def snap() -> list[dict]:
    ids = (get(f"{FIREBASE}/topstories.json") or [])[:TOP]
    at = int(time.time())
    with ThreadPoolExecutor(10) as ex:
        items = list(ex.map(lambda i: get(f"{FIREBASE}/item/{i}.json") or {}, ids))
    return [{"observed_at": at, "rank": r + 1, "item_id": i, "title": it.get("title"), "url": it.get("url"),
             "by": it.get("by"), "time": it.get("time"), "points": it.get("score"), "comments": it.get("descendants"),
             "type": it.get("type")} for r, (i, it) in enumerate(zip(ids, items))]


if __name__ == "__main__":
    every, flush = int(sys.argv[1]) if len(sys.argv) > 1 else 300, int(sys.argv[2]) if len(sys.argv) > 2 else 6
    buf, n = [], 0
    while True:
        try:
            buf += snap()
            n += 1
            if n % flush == 0 and buf:
                S.write("hn_frontpage", pd.DataFrame(buf))
                buf = []
        except Exception as exc:  # noqa: BLE001
            print("snap failed:", exc, flush=True)
        time.sleep(every)
