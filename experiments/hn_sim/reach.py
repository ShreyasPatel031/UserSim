"""Submitter reach: HN profile of every story submitter (official Firebase API) and, where the 'about' names an
X/Twitter handle, X followers via fxtwitter (free, as experiments/ph_predict/external.py).
  reach    account age at post time (account creation is fixed), about length, links X / GitHub / a site  -> safe
  reach_x  X followers, tweets, X account age: TODAY's values, so they can carry later success: flagged variant
Raw rows: <cache>/reach_users.jsonl, <cache>/reach_x.jsonl. Blocks: f_reach.parquet, f_reach_x.parquet.

    python reach.py fetch        # profiles + X (resumable)
    python reach.py build
"""
import json
import os
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import requests

import store as S

U = os.path.join(S.LOCAL, "reach_users.jsonl")
X = os.path.join(S.LOCAL, "reach_x.jsonl")
lock = threading.Lock()
_s = requests.Session()
_s.headers.update({"User-Agent": "atelier-research"})
HANDLE = re.compile(r"(?:twitter\.com|x\.com)/(?:#!/)?@?([A-Za-z0-9_]{1,15})(?![A-Za-z0-9_])", re.I)
SKIP = {"intent", "share", "home", "search", "i", "hashtag"}


def get(url):
    for _ in range(3):
        try:
            r = _s.get(url, timeout=20)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 404:
                return None
        except (requests.RequestException, ValueError):
            pass
    return None


def done(path, key):
    return {json.loads(l)[key] for l in open(path)} if os.path.exists(path) else set()


def write(path, rec):
    with lock, open(path, "a") as f:
        f.write(json.dumps(rec) + "\n")


def user(u):
    import html as H
    d = get(f"https://hacker-news.firebaseio.com/v0/user/{u}.json") or {}
    about = H.unescape(re.sub(r"<[^>]+>", " ", d.get("about") or ""))
    hs = [h for h in HANDLE.findall(about) if h.lower() not in SKIP]
    write(U, {"person": u, "created": d.get("created"), "about_len": len(about), "x_handle": hs[0] if hs else None,
              "about_github": int("github.com/" in about), "about_url": int("http" in about)})


def xinfo(h):
    d = (get(f"https://api.fxtwitter.com/{h}") or {}).get("user") or {}
    write(X, {"handle": h, "followers": d.get("followers"), "tweets": d.get("tweets"), "joined": d.get("joined")})


def fetch():
    s = pd.read_parquet(os.path.join(S.LOCAL, "bq_stories.parquet"), columns=["author"])
    todo = sorted(set(s.author.dropna()) - done(U, "person"))
    print(len(todo), "submitters", flush=True)
    with ThreadPoolExecutor(24) as ex:
        for i, _ in enumerate(ex.map(user, todo)):
            if i % 20000 == 0:
                print("users", i, flush=True)
    us = pd.read_json(U, lines=True)
    hs = sorted(set(us.x_handle.dropna()) - done(X, "handle"))
    print(len(hs), "X handles", flush=True)
    with ThreadPoolExecutor(6) as ex:
        for i, _ in enumerate(ex.map(xinfo, hs)):
            if i % 2000 == 0:
                print("x", i, flush=True)


def build():
    import top100 as H
    p = H.stories()
    us = pd.read_json(U, lines=True).drop_duplicates("person").set_index("person")
    f = pd.DataFrame({"post_id": p.post_id})
    f["sub_acct_days"] = ((p.created_at_i - p.author.map(us.created)) / 86400).to_numpy()
    f["sub_about_len"] = p.author.map(us.about_len).to_numpy()
    f["sub_has_x"] = p.author.map(us.x_handle).notna().astype(int).to_numpy()
    f["sub_about_github"] = p.author.map(us.about_github).to_numpy()
    f["sub_about_url"] = p.author.map(us.about_url).to_numpy()
    f.to_parquet(os.path.join(S.LOCAL, "f_reach.parquet"), index=False)
    fx = pd.DataFrame({"post_id": p.post_id})
    if os.path.exists(X):
        xs = pd.read_json(X, lines=True).drop_duplicates("handle").set_index("handle")
        h = p.author.map(us.x_handle)
        fx["x_followers_today"] = np.log1p(h.map(xs.followers).astype(float)).to_numpy()
        fx["x_tweets_today"] = np.log1p(h.map(xs.tweets).astype(float)).to_numpy()
        joined = pd.to_datetime(h.map(xs.joined), errors="coerce", utc=True)
        fx["x_acct_days"] = ((p.created_at_i - joined.map(lambda t: t.timestamp() if pd.notna(t) else np.nan)) / 86400).to_numpy()
    fx.to_parquet(os.path.join(S.LOCAL, "f_reach_x.parquet"), index=False)
    print("reach blocks", f.shape, fx.shape, "with X followers:", fx.get("x_followers_today", pd.Series()).notna().sum())


if __name__ == "__main__":
    {"fetch": fetch, "build": build}[sys.argv[1]]()
