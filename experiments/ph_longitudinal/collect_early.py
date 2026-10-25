"""Early Product Hunt activity per launch: timestamps of its first 20 top-level comments (PH API).

Comments are timestamped, so "comments in the first hour / two hours" can be rebuilt for past launches exactly as
they would have looked that morning. One query per 20 featured launches of a day (~100 rate-limit points). Writes
cache/early_days/<day>.json; days on disk are skipped; newest first.

    PH_TOKEN=... python experiments/ph_longitudinal/collect_early.py 2025-10-01 2026-10-24
"""

from __future__ import annotations

import json
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import collect_ph as C  # noqa: E402

OUT = C.HERE / "cache" / "early_days"
QUERY = """query($after: DateTime!, $before: DateTime!, $cursor: String) {
  posts(first: 20, after: $cursor, featured: true, postedAfter: $after, postedBefore: $before, order: RANKING) {
    totalCount
    pageInfo { hasNextPage endCursor }
    edges { node { id createdAt featuredAt comments(last: 20, order: NEWEST) { edges { node { createdAt userId } } } } }
  }
}"""


def main(first: str, last: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    C.QUERY = QUERY  # reuse the paging / rate-limit handling of collect_ph
    toks, i = C.tokens(), 0
    day, start = date.fromisoformat(last), date.fromisoformat(first)
    while day >= start:
        path = OUT / f"{day}.json"
        if path.exists():
            day -= timedelta(days=1)
            continue
        posts, limits = C.fetch_day(day, toks[i % len(toks)])
        if not posts:
            i += 1
            if i % len(toks) == 0:
                time.sleep(int(limits.get("reset") or 60) + 5)
            continue
        rec = {n["node"]["id"]: {"t0": n["node"]["featuredAt"] or n["node"]["createdAt"],
                                 "comments": [c["node"] for c in n["node"]["comments"]["edges"]]}
               for n in posts["edges"]}
        path.write_text(json.dumps({"day": str(day), "fetched_at": datetime.now(C.PT).isoformat(), "posts": rec}))
        print(f"{day}: {len(rec)} launches, remaining {limits['remaining']}", flush=True)
        day -= timedelta(days=1)
        i += 1


if __name__ == "__main__":
    main(*sys.argv[1:3])
