"""HN profiles (official Firebase API) for everyone with MIN+ early comments (first 60 min of a story) since 2023:
account creation time (fixed, so safe to use), whether the 'about' links an X/Twitter, GitHub or personal site.
Karma is today's value and is NOT used (it would leak later success). -> <cache>/hn_profiles.parquet

    python profiles.py [MIN=5]
"""
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

import store as S
from fetch import FIREBASE, get, text_of


def one(u: str) -> dict:
    d = get(f"{FIREBASE}/user/{u}.json") or {}
    about = text_of(d.get("about"))
    return {"person": u, "created": d.get("created"), "about_len": len(about),
            "about_x": int(bool(re.search(r"(twitter\.com|x\.com)/\w+", about))),
            "about_github": int("github.com/" in about), "about_url": int("http" in about),
            "submitted_n_today": len(d.get("submitted") or []), "observed_on": S.now()}


def main(minimum: int = 5) -> None:
    import top100 as H
    p = H.stories()
    c = H.comments()
    born = pd.Series(p.created_at_i.to_numpy(), index=p.post_id)
    c = c[c.story_id.isin(born.index)]
    age = c.created_at_i - c.story_id.map(born).to_numpy()
    e = c[(age >= 0) & (age <= 3600)]
    people = e.person.value_counts()
    people = people[people >= minimum].index.tolist()
    with ThreadPoolExecutor(32) as ex:
        rows = list(ex.map(one, people))
    D = pd.DataFrame(rows)
    D.to_parquet(os.path.join(S.LOCAL, "hn_profiles.parquet"), index=False)
    print(len(D), "profiles", D.created.isna().mean().round(3), "missing")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 5)
