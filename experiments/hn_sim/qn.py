"""Historical early upvotes from Quality News (news.social-protocols.org, social-protocols/quality-news): it crawls the
HN API every minute and its per-story stats page embeds the minute series (upvotesPlotData: time, upvotes, ...;
ranksPlotData: time, ranks on the top/new/... pages). Coverage starts around mid-2025; stories that end with ~1-3
points are mostly not kept (404).

For every story on the given days (newest first): upvotes and best top-page rank at 15 / 30 / 60 minutes.
Polite: one request every DELAY seconds. Appends to <cache>/qn_early.jsonl.

    python qn.py 2026-06-01 2026-09-30
"""
import json
import os
import re
import sys
import time

import pandas as pd
import requests

import store as S

OUT = os.path.join(S.LOCAL, "qn_early.jsonl")
DELAY = float(os.environ.get("QN_DELAY", "0.5"))
_s = requests.Session()
_s.headers.update({"User-Agent": "atelier-research (HN early-vote backtest; ~2 req/s)"})


def parse(html: str, t0: int) -> dict:
    out = {}
    m = re.search(r"upvotesPlotData = \[(.*?)\];", html, re.S)
    up = [(int(a), int(b)) for a, b in re.findall(r"\[(\d+),(\d+)", m.group(1))] if m else []
    m = re.search(r"ranksPlotData = \[(.*?)\];", html, re.S)
    rk = [[int(x) for x in row.split(",")] for row in re.findall(r"\[(\d+(?:,\d+)+)\]", m.group(1))] if m else []
    for a in (15, 30, 60):
        lim = t0 + a * 60
        u = [v for t, v in up if t <= lim]
        out[f"qn_up{a}"] = u[-1] if u else None
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
    t_start, nbytes = time.time(), 0
    for i, (pid, t0) in enumerate(todo):
        try:
            r = _s.get(f"https://news.social-protocols.org/stats?id={pid}", timeout=30)
            nbytes += len(r.content)
            rec = {"post_id": pid, "status": r.status_code, **(parse(r.text, t0) if r.status_code == 200 else {})}
        except requests.RequestException as exc:
            rec = {"post_id": pid, "status": -1, "error": str(exc)[:100]}
        with open(OUT, "a") as f:
            f.write(json.dumps(rec) + "\n")
        if i % 1000 == 0:
            print(i, f"{time.time() - t_start:.0f}s {nbytes / 1e9:.2f} GB", flush=True)
        time.sleep(DELAY)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
