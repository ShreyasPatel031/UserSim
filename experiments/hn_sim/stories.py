"""Every HN story (all types, not only Show HN) from Algolia, one query per day, split while a
slice holds more than Algolia's 1,000-hit page. Keeps Algolia's tags, including front_page (the story reached the front page). Appends to hn_posts
with tag_set='story'; fetches only hours not stored yet.

    python stories.py 2025-02-01 2026-10-30
"""
from __future__ import annotations

import datetime as dt
import sys
import time

import pandas as pd

import store as S
from fetch import ALGOLIA, get, link_kind, text_of


def rows(a: int, span: int) -> list[dict]:
    """Stories created in [a, a+span); splits the span in four while Algolia reports more than one page of hits."""
    j = get(f"{ALGOLIA}/search_by_date", {"tags": "story", "hitsPerPage": 1000,
                                          "numericFilters": f"created_at_i>={a},created_at_i<{a + span}"})
    if j and j.get("nbHits", 0) > 1000 and span > 900:
        q = span // 4
        return [r for i in range(4) for r in rows(a + i * q, q if i < 3 else span - 3 * q)]
    return [{"post_id": int(h["objectID"]), "day": dt.datetime.fromtimestamp(h["created_at_i"], dt.timezone.utc).date().isoformat(),
             "created_at": h["created_at"], "created_at_i": h["created_at_i"], "title": h.get("title"),
             "url": h.get("url"), "text": text_of(h.get("story_text")), "author": h.get("author"),
             "points": h.get("points"), "num_comments": h.get("num_comments") or 0, "link_kind": link_kind(h.get("url")),
             "algolia_tags": ",".join(t for t in h.get("_tags", []) if not t.startswith(("author_", "story_"))),
             "tag_set": "story", "observed_on": S.now()} for h in (j or {}).get("hits", [])]


def main(start: str, end: str) -> None:
    have = S.read("hn_posts")
    have = have[have.get("tag_set") == "story"] if "tag_set" in have else have.iloc[:0]
    done_days = set(have.day) if len(have) else set()
    d = dt.date.fromisoformat(start)
    while d < dt.date.fromisoformat(end):
        if d.isoformat() not in done_days and d < dt.date.today():
            t0 = int(dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc).timestamp())
            got = rows(t0, 86400)
            S.write("hn_posts", pd.DataFrame(got))
            print(d, len(got), flush=True)
            time.sleep(0.2)
        d += dt.timedelta(days=1)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
