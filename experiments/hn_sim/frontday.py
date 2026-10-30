"""HN's own daily list ("past" front page): news.ycombinator.com/front?day=YYYY-MM-DD, the page the user reads (stories
in front-page order for that day; 30 per page, p=2.. for more). Fetched politely (one request every 5 s) from the
VM for the given days, PAGES pages each. -> <cache>/frontday.jsonl {day, rank, post_id}

    python frontday.py 2026-05-01 2026-09-30 [pages=4]
"""
import datetime as dt
import json
import os
import re
import sys
import time

import requests

import store as S

OUT = os.path.join(S.LOCAL, "frontday.jsonl")
_s = requests.Session()
_s.headers.update({"User-Agent": "atelier-research (HN past front pages, 1 req / 5 s)"})


def main(a, b, pages=4):
    done = {json.loads(l)["day"] for l in open(OUT)} if os.path.exists(OUT) else set()
    d = dt.date.fromisoformat(a)
    while d <= dt.date.fromisoformat(b):
        if d.isoformat() not in done:
            rows = []
            for n in range(1, int(pages) + 1):
                r = _s.get("https://news.ycombinator.com/front", params={"day": d.isoformat(), "p": n}, timeout=30)
                time.sleep(5)
                if r.status_code != 200:
                    print(d, "status", r.status_code, flush=True)
                    time.sleep(60)
                    break
                ids = re.findall(r"<tr class=['\"]athing[^'\"]*['\"] id=['\"](\d+)['\"]", r.text)
                rows += [{"day": d.isoformat(), "rank": len(rows) + i + 1, "post_id": int(x)} for i, x in enumerate(ids)]
                if len(ids) < 30:
                    break
            with open(OUT, "a") as f:
                for x in rows:
                    f.write(json.dumps(x) + "\n")
            print(d, len(rows), flush=True)
        d += dt.timedelta(days=1)


if __name__ == "__main__":
    main(*sys.argv[1:])
