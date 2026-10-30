"""Historical early upvotes from Quality News (news.social-protocols.org, social-protocols/quality-news): it crawls the
HN API every minute and its per-story stats page embeds the minute series (upvotesPlotData: time, upvotes, ...;
ranksPlotData: time, ranks on the top/new/... pages). Coverage starts around mid-2025; stories that end with ~1-3
points are mostly not kept (404).

For every story on the given days (newest first): upvotes, expected upvotes and best top-page rank at QN_AGES minutes
(default 15 / 30 / 60; QN_AGES=15,30,60,120,240,480 QN_OUT=qn_long.jsonl for the front-page work).
Polite: WORKERS threads, each pausing DELAY seconds after a request (~3 req/s). Appends to <cache>/qn_early.jsonl.

    python qn.py 2026-06-01 2026-09-30
"""
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests

import store as S

OUT = os.path.join(S.LOCAL, os.environ.get("QN_OUT", "qn_early.jsonl"))
AGES = [int(x) for x in os.environ.get("QN_AGES", "15,30,60").split(",")]   # minutes after posting
DELAY = float(os.environ.get("QN_DELAY", "0.5"))
WORKERS = int(os.environ.get("QN_WORKERS", "3"))   # ~3 requests/s in total: polite for a small volunteer site
_s = requests.Session()
_s.headers.update({"User-Agent": "atelier-research (HN early-vote backtest; ~2 req/s)"})


def parse(html: str, t0: int) -> dict:
    out = {}
    m = re.search(r"upvotesPlotData = \[(.*?)\];", html, re.S)
    # upvotesPlotData rows: time, upvotes, expected upvotes (from the ranks it was shown at), ...
    up = [(int(a), int(b), float(c)) for a, b, c in re.findall(r"\[(\d+),(\d+),([\d.eE+-]+)", m.group(1))] if m else []
    m = re.search(r"ranksPlotData = \[(.*?)\];", html, re.S)
    rk = [[int(x) for x in row.split(",")] for row in re.findall(r"\[(\d+(?:,\d+)+)\]", m.group(1))] if m else []
    for a in AGES:
        lim = t0 + a * 60
        u = [(v, e) for t, v, e in up if t <= lim]
        out[f"qn_up{a}"] = u[-1][0] if u else None
        out[f"qn_exp{a}"] = round(u[-1][1], 3) if u else None      # Quality News' upvote rate = upvotes / expected
        # columns: time, raw rank, "Top" rank, "New" rank, "Best" rank, ...; 91 = not on that page
        r = [row[2] for row in rk if row[0] <= lim and len(row) > 2 and 0 < row[2] < 91]
        out[f"qn_toprank{a}"] = min(r) if r else None
    out["qn_samples"] = len(up)
    return out


def main(a: str, b: str) -> None:
    import top100 as H
    p = H.stories()
    p = p[(p.day >= a) & (p.day <= b)].sort_values("created_at_i", ascending=False)
    done = {json.loads(l)["post_id"] for l in open(OUT)} if os.path.exists(OUT) else set()
    todo = [(int(r.post_id), int(r.created_at_i)) for r in p.itertuples() if r.post_id not in done]
    print(len(todo), "stories", flush=True)
    t_start, lock = time.time(), threading.Lock()

    def one(job):
        pid, t0 = job
        try:
            r = requests.get(f"https://news.social-protocols.org/stats?id={pid}", timeout=30, headers=_s.headers)
            rec = {"post_id": pid, "status": r.status_code, **(parse(r.text, t0) if r.status_code == 200 else {})}
        except requests.RequestException as exc:
            rec = {"post_id": pid, "status": -1, "error": str(exc)[:100]}
        with lock, open(OUT, "a") as f:
            f.write(json.dumps(rec) + "\n")
        time.sleep(DELAY)
    with ThreadPoolExecutor(WORKERS) as ex:
        for i, _ in enumerate(ex.map(one, todo)):
            if i % 1000 == 0:
                print(i, f"{time.time() - t_start:.0f}s", flush=True)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
