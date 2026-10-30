"""Was the story's URL on Lobsters before it was posted to HN? Lobsters' public JSON (lobste.rs/newest/page/N.json,
25 stories a page, newest first), ~1 request/s. Uses only each Lobsters story's URL and creation time: never its
score (which grows after the HN post). Raw: <cache>/lobsters.jsonl. Block: f_lobsters.parquet.

    python lobsters.py fetch [stop_date=2022-12-01]
    python lobsters.py build
"""
import json
import os
import re
import sys
import time

import numpy as np
import pandas as pd
import requests

import store as S

RAW = os.path.join(S.LOCAL, "lobsters.jsonl")


def norm(u):
    u = re.sub(r"^https?://(www\.)?", "", str(u or "").strip().lower())
    return re.sub(r"[#?].*$", "", u).rstrip("/")


def fetch(stop="2022-12-01"):
    s = requests.Session()
    s.headers.update({"User-Agent": "atelier-research (~1 req/s)"})
    n, bad = 1, 0
    with open(RAW, "a") as f:
        while True:
            try:
                r = s.get(f"https://lobste.rs/newest/page/{n}.json", timeout=30)
                items = r.json() if r.status_code == 200 else None
            except (requests.RequestException, ValueError):
                items = None
            if not items:
                bad += 1
                if bad > 5:
                    break
                time.sleep(10)
                continue
            bad = 0
            for it in items:
                f.write(json.dumps({"url": it.get("url"), "created_at": it.get("created_at"),
                                    "short_id": it.get("short_id")}) + "\n")
            last = items[-1].get("created_at", "")
            if n % 100 == 0:
                print(n, last, flush=True)
            if last[:10] < stop:
                break
            n += 1
            time.sleep(1.0)
    print("pages", n, flush=True)


def build():
    import top100 as H
    p = H.stories()
    L = pd.read_json(RAW, lines=True).dropna(subset=["url"])
    L = L[L.url.astype(str).str.startswith("http")]
    L["key"] = L.url.map(norm)
    L["t"] = pd.to_datetime(L.created_at, utc=True).map(lambda x: x.timestamp())
    first = L.groupby("key").t.min()
    k = p.url.map(norm)
    lt = k.map(first)
    f = pd.DataFrame({"post_id": p.post_id})
    before = (lt < p.created_at_i).to_numpy()
    f["lob_before"] = before.astype(int)
    f["lob_lead_h"] = np.where(before, (p.created_at_i - lt) / 3600, np.nan)
    f.to_parquet(os.path.join(S.LOCAL, "f_lobsters.parquet"), index=False)
    print("lobsters block", f.shape, "on lobsters before HN:", int(before.sum()))


if __name__ == "__main__":
    fetch(*sys.argv[2:]) if sys.argv[1] == "fetch" else build()
