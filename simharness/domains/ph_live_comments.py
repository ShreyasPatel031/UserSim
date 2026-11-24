"""Forward-day builder for Task C: a day's comments from the live launch-day stream, linked to held people the next
morning instead of waiting for a profile re-read.

Inputs for day D (all private, read-only; paths are passed in):
  stream   the day's live comment stream (JSON lines; one row per newly seen comment: comment_id, commenter_user_id,
           launch_id, parent_id, body (HTML), created_at)
  lineup   the day's launch list as captured at 00:05 PT (id, name, tagline, description, topics, makers, user)
  persons  the store's persons table (platform user id <-> salted person id, `complete`)

A comment row is kept when it is: unique by comment_id; top-level (no parent); written on D (the benchmark's day
time zone); by a complete held person; on a launch of D's 00:05 line-up; not by a maker or the hunter of that launch
(ids from the line-up); at least `min_chars` characters after cleaning; the first by that person on that launch.
Text is the comment body with HTML removed and @handles replaced.

Output (an overlay directory, loaded with Benchmark.add_overlays):
  items.parquet     item_id, day, title, summary, description, tags   (D's line-up, line-up fields only)
  comments.parquet  person_idx, item_id, item_idx (the benchmark row when the launch is already an item, else -1),
                    day_ord, ts, text
  meta.json         counts per filter step

Platform user ids, usernames and handles are used only inside this module to link rows; none is written out.
"""
from __future__ import annotations

import html
import json
import os
import re

import numpy as np
import pandas as pd

from simharness.bench import _day_bounds_utc, day_ord, scrub
from simharness.domains.producthunt import SKIP_TOPICS

_TAG = re.compile(r"<[^>]+>")
_BREAK = re.compile(r"<\s*(br|/p|/li|/div|/h\d)\s*/?\s*>", re.I)


def html_to_text(body) -> str:
    """Plain text from a comment body: tags removed, entities decoded, whitespace collapsed, @handles replaced."""
    t = _BREAK.sub(" ", str(body or ""))
    t = html.unescape(_TAG.sub("", t))
    return scrub(" ".join(t.split()))


def read_lineup(path: str, day: str) -> tuple[pd.DataFrame, dict]:
    """Items of the line-up (line-up fields only) and, per item_id, the platform ids of its makers and hunter
    (kept in memory to drop their comments; never written)."""
    posts = json.load(open(path))
    rows, team = [], {}
    for p in posts if isinstance(posts, list) else []:
        pid = str(p.get("id"))
        tags = [e["node"]["name"] for e in ((p.get("topics") or {}).get("edges") or [])
                if isinstance(e, dict) and isinstance(e.get("node"), dict) and e["node"].get("name")]
        rows.append({"item_id": pid, "day": day, "title": scrub(str(p.get("name") or "")),
                     "summary": scrub(str(p.get("tagline") or "")),
                     "description": scrub(" ".join(str(p.get("description") or "").split())),
                     "tags": [t for t in tags if t not in SKIP_TOPICS]})
        ids = {str(m["id"]) for m in (p.get("makers") or []) if isinstance(m, dict) and m.get("id") is not None}
        if isinstance(p.get("user"), dict) and p["user"].get("id") is not None:
            ids.add(str(p["user"]["id"]))
        team[pid] = ids
    return pd.DataFrame(rows, columns=["item_id", "day", "title", "summary", "description", "tags"]), team


def read_stream(path: str) -> pd.DataFrame:
    rows = []
    for line in open(path):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except ValueError:
            continue
        rows.append({"comment_id": str(r.get("comment_id")), "launch_id": str(r.get("launch_id")),
                     "uid": None if r.get("commenter_user_id") in (None, "") else str(r.get("commenter_user_id")),
                     "top_level": r.get("parent_id") in (None, "", "null"), "created_at": r.get("created_at"),
                     "body": r.get("body")})
    df = pd.DataFrame(rows, columns=["comment_id", "launch_id", "uid", "top_level", "created_at", "body"])
    df["ts"] = pd.to_datetime(df["created_at"], utc=True, errors="coerce")
    return df


def build_day(bench, day: str, stream_path: str, lineup_path: str, persons_path: str, min_chars: int = 15):
    """Returns (items, comments, report) for one day. `bench` may already hold earlier overlays."""
    items, team = read_lineup(lineup_path, day)
    s = read_stream(stream_path)
    rep = {"day": day, "stream_rows": int(len(s))}
    s = s.sort_values("ts").drop_duplicates("comment_id")
    rep["comments_in_stream"] = int(len(s))
    s = s[s["top_level"]]
    rep["top_level"] = int(len(s))
    start, end = _day_bounds_utc(day, bench.cfg.day_tz)
    s = s[(s["ts"] >= start) & (s["ts"] < end)]
    rep["written_on_the_day"] = int(len(s))
    persons = pd.read_parquet(persons_path, columns=["person_id", "ph_user_id", "complete"])
    persons = persons[persons["complete"].fillna(False).astype(bool) & persons["ph_user_id"].notna()]
    pidx = dict(zip(bench.people["person_id"], bench.people["person_idx"]))
    uid2idx = {str(u): int(pidx[p]) for u, p in zip(persons["ph_user_id"], persons["person_id"]) if p in pidx}
    s = s[s["uid"].isin(uid2idx)].copy()
    rep["by_complete_held_people"] = int(len(s))
    s = s[s["launch_id"].isin(team)]
    rep["on_a_lineup_launch"] = int(len(s))
    s = s[[u not in team[l] for u, l in zip(s["uid"], s["launch_id"])]]
    rep["not_by_maker_or_hunter"] = int(len(s))
    s["text"] = s["body"].map(html_to_text)
    s = s[s["text"].str.len() >= min_chars]
    rep["at_least_min_chars"] = int(len(s))
    s["person_idx"] = s["uid"].map(uid2idx).astype(np.int64)
    s = s.sort_values("ts").drop_duplicates(["person_idx", "launch_id"])
    rep["first_per_person_and_launch"] = int(len(s))
    known = dict(zip(bench.items["item_id"].astype(str), bench.items["item_idx"]))
    comments = pd.DataFrame({"person_idx": s["person_idx"].to_numpy().astype(np.int32),
                             "item_id": s["launch_id"].to_numpy(),
                             "item_idx": np.array([int(known.get(l, -1)) for l in s["launch_id"]], dtype=np.int32),
                             "day_ord": np.int32(day_ord(day)), "ts": s["ts"].to_numpy(), "text": s["text"].to_numpy()})
    comments["ts"] = pd.to_datetime(comments["ts"], utc=True)
    have = set(zip(bench.comments["person_idx"].to_numpy().tolist(), bench.comments["item_idx"].to_numpy().tolist()))
    dup = np.array([(int(p), int(i)) in have for p, i in zip(comments["person_idx"], comments["item_idx"])], dtype=bool)
    rep["already_in_benchmark"] = int(dup.sum())
    rep["new_rows"] = int((~dup).sum())
    rep["new_rows_people"] = int(comments.loc[~dup, "person_idx"].nunique())
    rep["lineup_launches"] = int(len(items))
    rep["lineup_launches_already_items"] = int(items["item_id"].isin(known).sum())
    return items, comments, rep


def write_overlay(out_dir: str, items: pd.DataFrame, comments: pd.DataFrame, report: dict) -> list[str]:
    os.makedirs(out_dir, exist_ok=True)
    items.to_parquet(f"{out_dir}/items.parquet")
    comments.to_parquet(f"{out_dir}/comments.parquet")
    with open(f"{out_dir}/meta.json", "w") as f:
        json.dump(report, f, indent=1)
    return [f"{out_dir}/items.parquet", f"{out_dir}/comments.parquet", f"{out_dir}/meta.json"]
