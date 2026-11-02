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
        ids, h = [], ""
        for wait in (0, 15, 45, 120):                     # HN refuses some reads (rate limit): retry a page that came back empty
            time.sleep(wait)
            try:
                r = requests.get("https://news.ycombinator.com/front", params={"day": day, "p": page}, headers=UA, timeout=30)
                h = r.text if r.status_code == 200 else ""
            except requests.RequestException:
                h = ""
            ids = re.findall(r"<tr class=['\"]athing[^'\"]*['\"] id=['\"](\d+)['\"]", h)
            if ids:
                break
        pts = dict(re.findall(r'<span class="score" id="score_(\d+)">(\d+) point', h))
        rows += [{"read_at": at, "day": day, "rank": (page - 1) * 30 + i + 1, "post_id": int(x), "points": int(pts.get(x, 0))}
                 for i, x in enumerate(ids)]
        time.sleep(5)
    return rows


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    while True:
        try:
            now = time.time()
            # today and the 3 days before: a list counts as settled once read 48 h+ after its day ended
            for day in [time.strftime("%Y-%m-%d", time.gmtime(now - k * 86400)) for k in range(4)]:
                rows = read(day)
                path = os.path.join(OUT, f"{day}.jsonl")
                with open(path, "a") as f:
                    f.writelines(json.dumps(r) + "\n" for r in rows)
                S._bucket().blob(f"usersim_sim/hn_jobs/cache/listwatch/{day}.jsonl").upload_from_filename(path)
            print(time.strftime("%H:%M", time.gmtime()), "recorded", flush=True)
        except Exception as exc:  # noqa: BLE001
            print("listwatch error:", exc, flush=True)
        time.sleep(3600 - time.time() % 3600 + 60)        # one minute past each hour
