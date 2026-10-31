"""Record HN's daily list as it stands, every hour: news.ycombinator.com/front?day=<today> and <yesterday>, 4 pages
each (rank, id, points shown). The page is computed when it is read (order uses points at that moment), so only
recording it over time shows the list at a fixed hour. -> <cache>/listwatch/<day>.jsonl, pushed to the bucket.

    python listwatch.py            # loop forever
"""
import json
import os
import re
import time

import requests

import store as S

UA = {"User-Agent": "atelier-research (HN daily list, hourly)"}
OUT = os.path.join(S.LOCAL, "listwatch")


def read(day: str) -> list[dict]:
    rows, at = [], int(time.time())
    for page in (1, 2, 3, 4):
        h = requests.get("https://news.ycombinator.com/front", params={"day": day, "p": page}, headers=UA, timeout=30).text
        ids = re.findall(r"<tr class=['\"]athing[^'\"]*['\"] id=['\"](\d+)['\"]", h)
        pts = dict(re.findall(r'<span class="score" id="score_(\d+)">(\d+) point', h))
        rows += [{"read_at": at, "day": day, "rank": (page - 1) * 30 + i + 1, "post_id": int(x), "points": int(pts.get(x, 0))}
                 for i, x in enumerate(ids)]
        time.sleep(3)
    return rows


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    while True:
        try:
            now = time.time()
            for day in (time.strftime("%Y-%m-%d", time.gmtime(now)), time.strftime("%Y-%m-%d", time.gmtime(now - 86400))):
                rows = read(day)
                path = os.path.join(OUT, f"{day}.jsonl")
                with open(path, "a") as f:
                    f.writelines(json.dumps(r) + "\n" for r in rows)
                S._bucket().blob(f"usersim_sim/hn_jobs/cache/listwatch/{day}.jsonl").upload_from_filename(path)
            print(time.strftime("%H:%M", time.gmtime()), "recorded", flush=True)
        except Exception as exc:  # noqa: BLE001
            print("listwatch error:", exc, flush=True)
        time.sleep(3600 - time.time() % 3600 + 60)        # one minute past each hour
