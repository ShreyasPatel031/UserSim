"""Pull Show HN posts, their top-level comments, each commenter's earlier comments and profile, and the product's
Wayback snapshot nearest the post day. Free public APIs only (Algolia HN Search, HN Firebase, Wayback); no scraping,
no proxies. Writes hn_posts, hn_comments, hn_people, hn_snapshots (append only; fetches only what is not stored yet).

    python experiments/hn_sim/fetch.py window 2026-10-01 2026-10-22     # every Show HN post in the window
    python experiments/hn_sim/fetch.py deep 30                          # top-level comments + people + snapshots
"""
from __future__ import annotations

import datetime as dt
import html
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import pandas as pd
import requests

sys.path.insert(0, __import__("os").path.dirname(__file__))
import store as S  # noqa: E402

ALGOLIA = "https://hn.algolia.com/api/v1"
FIREBASE = "https://hacker-news.firebaseio.com/v0"
WAYBACK = "https://archive.org/wayback/available"
HISTORY_KEEP = 50   # earlier comments stored per person per post (the card uses the last 50)
UA = {"User-Agent": "atelier-research (hn backtest; contact shreyas)"}
_s = requests.Session()
_s.headers.update(UA)


def get(url: str, params: dict | None = None, tries: int = 6) -> dict | None:
    for i in range(tries):
        try:
            r = _s.get(url, params=params, timeout=30)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(2 ** i)
                continue
            return None
        except (requests.RequestException, ValueError):
            time.sleep(2 ** i)
    return None


def text_of(h: str | None) -> str:
    """HN comment HTML to plain text."""
    t = re.sub(r"<p>", "\n\n", h or "")
    t = re.sub(r"<a [^>]*href=\"([^\"]+)\"[^>]*>.*?</a>", r"\1", t)
    return html.unescape(re.sub(r"<[^>]+>", "", t)).strip()


REPO_HOSTS = ("github.com", "gitlab.com", "codeberg.org", "bitbucket.org", "sr.ht", "pypi.org", "npmjs.com",
              "crates.io", "huggingface.co", "arxiv.org", "youtube.com", "youtu.be", "apps.apple.com",
              "play.google.com", "chromewebstore.google.com", "addons.mozilla.org", "news.ycombinator.com",
              "medium.com", "substack.com", "x.com", "twitter.com", "docs.google.com", "itch.io")


def link_kind(url: str | None) -> str:
    """Cheap first pass from the URL alone; coverage.py asks Gemini about the rest."""
    if not url:
        return "text_only"
    host = urlparse(url).netloc.lower().removeprefix("www.")
    for h in REPO_HOSTS:
        if host == h or host.endswith("." + h):
            return "repo_or_store" if h not in ("medium.com", "substack.com", "youtube.com", "youtu.be", "x.com",
                                                "twitter.com", "arxiv.org") else "content"
    return "web"


def window(start: str, end: str) -> pd.DataFrame:
    """Every Show HN post created in [start, end) (UTC days), one Algolia page per day."""
    have = S.read("hn_posts")
    seen = set(have["post_id"]) if len(have) else set()
    rows = []
    d = dt.date.fromisoformat(start)
    while d < dt.date.fromisoformat(end):
        a = int(dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc).timestamp())
        j = get(f"{ALGOLIA}/search_by_date", {"tags": "show_hn", "hitsPerPage": 1000,
                                              "numericFilters": f"created_at_i>={a},created_at_i<{a + 86400}"})
        for h in (j or {}).get("hits", []):
            pid = int(h["objectID"])
            if pid in seen:
                continue
            rows.append({"post_id": pid, "day": d.isoformat(), "created_at": h["created_at"],
                         "created_at_i": h["created_at_i"], "title": h.get("title"), "url": h.get("url"),
                         "text": text_of(h.get("story_text")), "author": h.get("author"),
                         "points": h.get("points"), "num_comments": h.get("num_comments") or 0,
                         "link_kind": link_kind(h.get("url")), "observed_on": S.now()})
        d += dt.timedelta(days=1)
        time.sleep(0.3)
    df = pd.DataFrame(rows)
    S.write("hn_posts", df)
    print(f"window {start}..{end}: {len(df)} new posts")
    return df


def thread(post: dict) -> list[dict]:
    """Top-level comments of a post (Algolia story_<id>, parent == post), dead/deleted excluded by Algolia."""
    out, page = [], 0
    while True:
        j = get(f"{ALGOLIA}/search", {"tags": f"comment,story_{post['post_id']}", "hitsPerPage": 1000, "page": page})
        hits = (j or {}).get("hits", [])
        for h in hits:
            if h.get("parent_id") == post["post_id"] and h.get("author") and h.get("comment_text"):
                out.append({"post_id": post["post_id"], "comment_id": int(h["objectID"]), "role": "thread",
                            "author": h["author"], "created_at_i": h["created_at_i"], "created_at": h["created_at"],
                            "text": text_of(h["comment_text"]), "story_id": post["post_id"],
                            "story_title": post["title"], "is_maker": h["author"] == post["author"],
                            "observed_on": S.now()})
        if not j or page + 1 >= j.get("nbPages", 1):
            break
        page += 1
    return out


def history(author: str, before: int, post_id: int) -> tuple[int, list[dict]]:
    """(number of comments the person wrote before `before`, their last HISTORY_KEEP of them)."""
    j = get(f"{ALGOLIA}/search_by_date", {"tags": f"comment,author_{author}", "hitsPerPage": HISTORY_KEEP,
                                          "numericFilters": f"created_at_i<{before}"})
    if not j:
        return -1, []
    rows = [{"post_id": post_id, "comment_id": int(h["objectID"]), "role": "history", "author": author,
             "created_at_i": h["created_at_i"], "created_at": h["created_at"], "text": text_of(h.get("comment_text")),
             "story_id": h.get("story_id"), "story_title": h.get("story_title"), "is_maker": False,
             "observed_on": S.now()} for h in j.get("hits", []) if h.get("comment_text")]
    return int(j.get("nbHits") or 0), rows


def profile(author: str) -> dict:
    u = get(f"{FIREBASE}/user/{author}.json") or {}
    return {"person": author, "created": u.get("created"), "about": text_of(u.get("about")),
            "karma_read_today": u.get("karma"), "observed_on": S.now()}


def snapshot(post: dict) -> dict:
    """Wayback capture nearest the post day (availability API, closest at or before the post when one exists)."""
    ts = dt.datetime.fromtimestamp(post["created_at_i"], dt.timezone.utc).strftime("%Y%m%d%H%M%S")
    j = get(WAYBACK, {"url": post["url"], "timestamp": ts}, tries=8)
    c = ((j or {}).get("archived_snapshots") or {}).get("closest") or {}
    snap_ts = c.get("timestamp")
    lag_h = None
    if snap_ts:
        st = dt.datetime.strptime(snap_ts, "%Y%m%d%H%M%S").replace(tzinfo=dt.timezone.utc)
        lag_h = round((st.timestamp() - post["created_at_i"]) / 3600, 1)
    return {"post_id": post["post_id"], "url": post["url"], "api_ok": j is not None, "snapshot_url": c.get("url"),
            "snapshot_ts": snap_ts, "snapshot_status": c.get("status"), "lag_hours": lag_h, "observed_on": S.now()}


def deep(n: int) -> None:
    """Top-level threads for every post with 10+ comments, then commenters' histories, profiles and snapshots for
    the n posts with the most top-level comments among those linking to a website (not a repo or store)."""
    posts = S.read("hn_posts").drop_duplicates("post_id")
    have = S.read("hn_comments")
    done = set(have.loc[have.role == "thread", "post_id"]) if len(have) else set()
    todo = posts[(posts.num_comments >= 10) & ~posts.post_id.isin(done)].to_dict("records")
    with ThreadPoolExecutor(8) as ex:
        th = [c for cs in ex.map(thread, todo) for c in cs]
    # posts with no top-level comments still need a marker so they are not refetched
    S.write("hn_comments", pd.DataFrame(th))
    print(f"threads: {len(todo)} posts, {len(th)} top-level comments")
    allc = S.read("hn_comments")
    tl = allc[(allc.role == "thread") & ~allc.is_maker].groupby("post_id").author.nunique()
    posts = posts.assign(top_level=posts.post_id.map(tl).fillna(0).astype(int))
    pick = posts[posts.link_kind == "web"].sort_values("top_level", ascending=False).head(n)
    print("deep posts:", len(pick), "top-level min", pick.top_level.min())

    hist_done = set(zip(allc.loc[allc.role == "history", "post_id"], allc.loc[allc.role == "history", "author"]))
    jobs = []
    for p in pick.to_dict("records"):
        th = allc[(allc.post_id == p["post_id"]) & (allc.role == "thread") & ~allc.is_maker]
        for a in th.author.unique():
            if (p["post_id"], a) not in hist_done:
                jobs.append((a, p["created_at_i"], p["post_id"]))
    counts, hrows = [], []
    with ThreadPoolExecutor(8) as ex:
        for (a, t, pid), (cnt, rows) in zip(jobs, ex.map(lambda j: history(*j), jobs)):
            counts.append({"post_id": pid, "author": a, "earlier_comments": cnt})
            hrows += rows
    S.write("hn_comments", pd.DataFrame(hrows))
    ppl = S.read("hn_people")
    known = set(ppl.person) if len(ppl) else set()
    authors = sorted({a for a, _, _ in jobs} - known)
    with ThreadPoolExecutor(8) as ex:
        prof = list(ex.map(profile, authors))
    pc = pd.DataFrame(counts)
    S.write("hn_people", pd.DataFrame(prof))
    # earlier-comment counts are per (post, person): stored as history-size rows in hn_people
    if len(pc):
        S.write("hn_people", pc.rename(columns={"author": "person"}).assign(kind="history_count",
                                                                            observed_on=S.now()))
    print(f"people: {len(jobs)} commenter-posts, {len(hrows)} history comments, {len(prof)} profiles")
    snaps = S.read("hn_snapshots")
    sdone = set(snaps.post_id) if len(snaps) else set()
    sn = []
    for p in pick.to_dict("records"):
        if p["post_id"] not in sdone:
            sn.append(snapshot(p))
            time.sleep(1.5)
    S.write("hn_snapshots", pd.DataFrame(sn))
    print(f"snapshots: {len(sn)} ({sum(bool(s['snapshot_url']) for s in sn)} found)")


if __name__ == "__main__":
    if sys.argv[1] == "window":
        window(sys.argv[2], sys.argv[3])
    elif sys.argv[1] == "deep":
        deep(int(sys.argv[2]))
