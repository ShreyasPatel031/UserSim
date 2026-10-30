"""HN favorites (each person's public list of favorited stories; the closest public thing to their upvotes) for the
most active early commenters. news.ycombinator.com/favorites?id=<person>&p=<n>, 30 stories a page, up to MAXP pages.
Fetch ladder: direct from the VM, one request per FAVS_DELAY seconds per worker; backs off when HN refuses and
stops after STOP_AFTER refusals in a row (no proxy credentials on this VM). Re-running skips people already fetched. Favorites are undated: use them only for stories posted before the test month.
Appends to <cache>/hn_favs.jsonl: {person, page, story_ids, status}.

    FAVS_DELAY=5 python favs.py [end_rank=5000] [workers=2] [start_rank=0]   # people ranked by early comments
"""
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests

import store as S

OUT = os.path.join(S.LOCAL, "hn_favs.jsonl")
MAXP = 10
DELAY = float(__import__("os").environ.get("FAVS_DELAY", "1.0"))   # seconds between requests per worker
STOP_AFTER = 20                                               # consecutive blocked pages before giving up
lock = threading.Lock()
state = {"blocked": 0}
_s = requests.Session()
_s.headers.update({"User-Agent": "atelier-research (HN favorites, ~1 req/s)"})


def fetch(person):
    out = []
    for n in range(1, MAXP + 1):
        if state["blocked"] >= STOP_AFTER:
            return
        try:
            r = _s.get("https://news.ycombinator.com/favorites", params={"id": person, "p": n}, timeout=30)
        except requests.RequestException:
            time.sleep(5)
            continue
        time.sleep(DELAY)
        if r.status_code in (403, 429, 503):
            with lock:
                state["blocked"] += 1
            time.sleep(min(600, 30 * 2 ** min(state["blocked"], 5)))   # back off harder while HN keeps refusing
            return                                                      # nothing written: retried on the next run
        with lock:
            state["blocked"] = 0
        ids = [int(x) for x in re.findall(r"<tr class=['\"]athing[^'\"]*['\"] id=['\"](\d+)['\"]", r.text)]
        out.append({"person": person, "page": n, "story_ids": ids, "status": r.status_code})
        if len(ids) < 30 or "morelink" not in r.text:
            break
    with lock, open(OUT, "a") as f:
        for o in out:
            f.write(json.dumps(o) + "\n")


def main(n=5000, workers=2, start=0):
    import pandas as pd
    import top100 as H
    p = H.stories()
    c = H.comments()
    born = pd.Series(p.created_at_i.to_numpy(), index=p.post_id)
    c = c[c.story_id.isin(born.index)]
    age = c.created_at_i - c.story_id.map(born).to_numpy()
    people = c[(age >= 0) & (age <= 3600)].person.value_counts().index[int(start):int(n)].tolist()
    done = {json.loads(l)["person"] for l in open(OUT)} if os.path.exists(OUT) else set()
    todo = [u for u in people if u not in done]
    print(len(todo), "people to fetch", flush=True)
    t0 = time.time()
    with ThreadPoolExecutor(int(workers)) as ex:
        for i, _ in enumerate(ex.map(fetch, todo)):
            if i % 200 == 0:
                print(i, f"{time.time() - t0:.0f}s blocked={state['blocked']}", flush=True)
            if state["blocked"] >= STOP_AFTER:
                print("HN is blocking this IP: stopped", flush=True)
                break


if __name__ == "__main__":
    main(*[int(x) for x in sys.argv[1:]])
