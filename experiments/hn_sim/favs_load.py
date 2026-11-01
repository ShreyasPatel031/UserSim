"""All fetched HN favorites (feeder/favs/*.jsonl from Grok Bot + our hn_favs.jsonl) -> {person: array of story ids}.
Favorites are undated: callers keep only stories posted before their cut-off and treat them as a taste profile.

    python favs_load.py          # download and summarise
"""
import json
import os

import numpy as np

import store as S
import top100 as H

DIR = os.path.join(H.CACHE, "feeder_favs")


def download():
    os.makedirs(DIR, exist_ok=True)
    for x in S._bucket().list_blobs(prefix="usersim_sim/hn_jobs/cache/feeder/favs/"):
        if x.name.endswith(".jsonl"):
            x.download_to_filename(os.path.join(DIR, x.name.split("/")[-1]))


def load() -> dict:
    favs = {}
    files = [os.path.join(DIR, f) for f in sorted(os.listdir(DIR))] + [os.path.join(H.CACHE, "hn_favs.jsonl")]
    for f in files:
        if not os.path.exists(f):
            continue
        for line in open(f):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            favs.setdefault(r["person"], set()).update(int(i) for i in r.get("story_ids") or [])
    return {k: np.array(sorted(v)) for k, v in favs.items()}


if __name__ == "__main__":
    download()
    F = load()
    n = np.array([len(v) for v in F.values()])
    print(f"{len(F)} people; with favorites {(n > 0).sum()}; favorites {n.sum()}; median among those with any {np.median(n[n > 0]):.0f}")
