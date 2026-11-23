"""Product Hunt adapter: the population store + launch items -> the four harness tables.

Inputs (all private, read-only; paths are passed in, nothing is hard-coded here):
  persons.parquet   one row per salted person: `complete` (whole-person rule)
  tabs.parquet      per (person, tab): `fetched_at` of the newest read (the Upvotes tab gives `observed_until`)
  events.parquet    upvote / comment / review / follows / launched / hunted events; `target_id` is a post id or
                    "launch:<slug>"; upvotes are mostly undated snapshots (`ts_quality` = snapshot)
  items.parquet     launches: id, slug, day, name, tagline, description, topics (JSON list), out_dailyRank, out_votes
  records/part-*.parquet (optional) verbatim person records; used only to recover comment TEXT by comment id

Documented choices (also returned in DomainTables.notes):
  * Upvotes carry no time. An upvote is attributed to the launch's own day. The leak rule (history for day D uses
    launches with day < D) is therefore exact for "which launches", but a late upvote on an older launch cast after D
    can still enter the history for D. This is small (most upvotes land on launch day) and is stated, not hidden.
  * Follow edges are snapshots (undated): they are NOT emitted, because using them would leak follows made after D.
  * Only events that join to a launch in `items` are emitted (others cannot be dated by launch day).
  * Reviews target products, not launches; they are kept only when they join to a launch id/slug.
  * observed_until = fetched_at of the person's Upvotes tab. A person not read after day D is not a valid negative
    for a launch on D; the benchmark builder drops such people from D's candidate pool.
"""
from __future__ import annotations

import glob
import json
import os
from typing import Iterable

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from simharness.schema import COMMENT, ENDORSE, MAKE, REVIEW, DomainTables, STRUCTURAL

# Event-like tags are not interests (same list as the site's person index).
SKIP_TOPICS = {"Vercel Day", "OpenAI Day", "YC Application", "Pitch NYC", "Pitch Berlin", "Pitch Tel Aviv",
               "Pitch Singapore", "Alpha", "Tech", "GitHub"}

KIND_MAP = {"upvote": ENDORSE, "comment": COMMENT, "review": REVIEW, "launched": MAKE, "hunted": MAKE}


def _topics(s) -> list[str]:
    try:
        tl = json.loads(s or "[]")
    except (TypeError, ValueError):
        tl = []
    return [t for t in tl if t not in SKIP_TOPICS]


def load_items(*paths: str) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """ITEMS and OUTCOMES tables, plus a target-id -> item_id resolver map. Later paths win on duplicate ids."""
    frames = [pd.read_parquet(p, columns=["id", "slug", "day", "name", "tagline", "description", "topics",
                                          "out_dailyRank", "out_votes"]) for p in paths]
    it = pd.concat(frames, ignore_index=True)
    it["id"] = it["id"].astype(str)
    it = it.drop_duplicates("id", keep="last").sort_values(["day", "id"]).reset_index(drop=True)
    items = pd.DataFrame({
        "item_id": it["id"], "day": it["day"].astype(str), "title": it["name"].fillna(""),
        "summary": it["tagline"].fillna(""), "description": it["description"].fillna(""),
        "tags": it["topics"].map(_topics), "slug": it["slug"].fillna(""),
    })
    outcomes = pd.DataFrame({"item_id": it["id"], "final_score": it["out_votes"].astype(float),
                             "final_rank": it["out_dailyRank"].astype(float)})
    resolve = dict(zip(items["item_id"], items["item_id"]))
    resolve.update({"launch:" + s: i for s, i in zip(items["slug"], items["item_id"]) if s})
    return items, outcomes, resolve


def load_people(persons_path: str, tabs_path: str) -> pd.DataFrame:
    p = pd.read_parquet(persons_path, columns=["person_id", "complete"])
    t = pd.read_parquet(tabs_path, columns=["person_id", "tab", "fetched_at"])
    t = t[t["tab"] == "upvotes"].groupby("person_id")["fetched_at"].max()
    p["observed_until"] = p["person_id"].map(t)
    p["complete"] = p["complete"].fillna(False).astype(bool)
    return p


def extract_comment_texts(record_files: Iterable[str]) -> pd.DataFrame:
    """comment_id -> text from verbatim records (activity items, earlier items and earlier records).

    Only (person_id, comment_id, text, ts) is kept: author names / usernames inside the records are dropped here."""
    rows = []

    def take(pid, it):
        if not isinstance(it, dict):
            return
        cid, text, ts = it.get("comment_id"), it.get("text"), it.get("datetime")
        sub = it.get("subject")
        if isinstance(sub, dict) and sub.get("__typename") == "Comment":  # raw GraphQL activity node
            cid, text, ts = sub.get("id"), sub.get("bodyText") or text, it.get("occurredAt")
        if cid and text:
            rows.append((pid, str(cid), str(text), ts))

    for f in record_files:
        t = pq.read_table(f, columns=["person_id", "record_json"])
        for pid, rj in zip(t.column("person_id").to_pylist(), t.column("record_json").to_pylist()):
            try:
                d = json.loads(rj)
            except (TypeError, ValueError):
                continue
            recs = [d] + [r for r in (d.get("earlier_records") or []) if isinstance(r, dict)]
            for r in recs:
                a = r.get("activity") or {}
                if not isinstance(a, dict):
                    continue
                for key in ("items", "items_earlier"):
                    for it in a.get(key) or []:
                        take(pid, it)
    df = pd.DataFrame(rows, columns=["person_id", "comment_id", "text", "ts"])
    if df.empty:
        return df
    df["len"] = df["text"].str.len()
    df = df.sort_values("len").drop_duplicates(["person_id", "comment_id"], keep="last").drop(columns="len")
    df["ts"] = pd.to_datetime(df["ts"], utc=True, errors="coerce")
    return df.reset_index(drop=True)


def load_events(events_path: str, resolve: dict, item_day: dict, persons: set | None = None,
                comment_texts: pd.DataFrame | None = None) -> pd.DataFrame:
    cols = ["person_id", "platform", "kind", "target_id", "ts_lo", "ts_quality", "extra"]
    e = pq.read_table(events_path, columns=cols,
                      filters=[("platform", "=", "producthunt"), ("kind", "in", list(KIND_MAP))]).to_pandas()
    if persons is not None:
        e = e[e["person_id"].isin(persons)]
    e["item_id"] = e["target_id"].map(resolve)
    e = e.dropna(subset=["item_id"])
    e["kind"] = e["kind"].map(KIND_MAP)
    e["day"] = e["item_id"].map(item_day)
    exact = e["ts_quality"].isin(["exact", "day", "bounded"])
    e["ts"] = e["ts_lo"].where(exact)
    e["ts_quality"] = np.where(exact, e["ts_quality"], "item_day")
    e["text"] = None
    is_c = e["kind"] == COMMENT
    if comment_texts is not None and len(comment_texts) and is_c.any():
        cid = e.loc[is_c, "extra"].map(lambda s: (json.loads(s) or {}).get("comment_id") if isinstance(s, str) else None)
        key = e.loc[is_c, "person_id"] + "|" + cid.astype(str)
        tx = dict(zip(comment_texts["person_id"] + "|" + comment_texts["comment_id"], comment_texts["text"]))
        e.loc[is_c, "text"] = key.map(tx).values
    out = e[["person_id", "kind", "item_id", "day", "ts", "ts_quality", "text"]]
    # One endorsement per (person, item): duplicates come from items vs items_earlier.
    end = out[out["kind"] == ENDORSE].drop_duplicates(["person_id", "item_id"])
    rest = out[out["kind"] != ENDORSE].drop_duplicates(["person_id", "kind", "item_id", "ts", "text"])
    return pd.concat([end, rest], ignore_index=True)


def build_tables(store_dir: str, item_paths: list[str], records_glob: str | None = None,
                 comment_texts: pd.DataFrame | None = None, complete_only: bool = True) -> DomainTables:
    items, outcomes, resolve = load_items(*item_paths)
    people = load_people(os.path.join(store_dir, "persons.parquet"), os.path.join(store_dir, "tabs.parquet"))
    keep = set(people.loc[people["complete"], "person_id"]) if complete_only else None
    if comment_texts is None and records_glob:
        comment_texts = extract_comment_texts(sorted(glob.glob(records_glob)))
    events = load_events(os.path.join(store_dir, "events.parquet"), resolve,
                         dict(zip(items["item_id"], items["day"])), keep, comment_texts)
    notes = {
        "endorse_dating": "upvotes are undated snapshots; attributed to the launch day (item_day)",
        "follows": "excluded: follow edges are undated snapshots and would leak follows made after D",
        "joinable_only": "only events whose target joins to a launch in items are emitted",
        "observed_until": "Upvotes tab fetched_at; people not read after D are dropped from D's pool",
        "comment_text": ("joined from verbatim records by (person, comment_id)" if comment_texts is not None
                         else "not available (no records given)"),
        "structural": "not loaded here; pass the frozen arm-3 scores via load_structural()",
    }
    return DomainTables(items=items, events=events, people=people, outcomes=outcomes,
                        structural=STRUCTURAL.empty(), notes=notes).validate()


def load_structural(path: str, model_version: str) -> pd.DataFrame:
    """Frozen structural scores: a parquet/CSV with item_id, day, score (and optionally frozen_at)."""
    df = pd.read_parquet(path) if path.endswith(".parquet") else pd.read_csv(path)
    df["item_id"] = df["item_id"].astype(str)
    df["model_version"] = model_version
    return STRUCTURAL.validate(df)
