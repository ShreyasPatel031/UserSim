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


# ------------------------------------------------------------------------------------------------ ties (TIES-1)
def _pt_day(ts: pd.Series) -> pd.Series:
    return ts.dt.tz_convert("America/Los_Angeles").dt.strftime("%Y-%m-%d")


def build_tie_tables(bench, store_dir: str, items_v2_path: str, daily_dir: str, target_days: list[str]) -> dict:
    """Team, backing and follow tables for tie features (simharness.ties.TieData.from_tables).

    Sources, all private and read-only:
      daily_dir/<day>__0005.json   the day's launch list as captured at 00:05 PT (id, makers[], user = hunter);
      daily_dir/<day>__day.json    the same list captured later that day (days without a 00:05 capture)
      items_v2_path                launches up to the item table's cut-off: poster and makers as names
      store_dir/persons.parquet    salted person id <-> platform user id (links a team member to a held person)
      store_dir/events.parquet     launched / hunted (dated exactly), upvote, comment, follows (undated snapshots)

    The TARGET launch's team (the launch being predicted) is taken ONLY from that day's capture, 00:05 when it
    exists. Teams of EARLIER launches use every source. Names and platform ids are turned into integer entity
    numbers here and are not returned; nothing in the output identifies a person.

    Launches outside the benchmark item table enter only when a held person's launched / hunted event dates them
    (exact time); a held person's upvote on such a launch is then dated by that launch day, as everywhere else.
    """
    import glob as _glob
    from simharness.bench import KIND_CODE, day_ord
    from simharness.schema import COMMENT as _C, ENDORSE as _E

    ent: dict[str, int] = {}

    def eid(key: str) -> int:
        if key not in ent:
            ent[key] = len(ent)
        return ent[key]

    # 1. daily captures: (platform id, name) pairs and teams
    name2id, daily = {}, {}
    for f in sorted(_glob.glob(os.path.join(daily_dir, "*__*.json"))):
        day, kind = os.path.basename(f)[:-5].split("__")
        try:
            posts = json.load(open(f))
        except ValueError:
            continue
        rows = []
        for p in posts if isinstance(posts, list) else []:
            members = [m for m in (p.get("makers") or []) if isinstance(m, dict)]
            hunter = p.get("user") if isinstance(p.get("user"), dict) else None
            team = []
            for m, role in [(m, "maker") for m in members] + ([(hunter, "hunter")] if hunter else []):
                if m.get("id") is None:
                    continue
                if m.get("username"):
                    name2id[str(m["username"]).lower()] = str(m["id"])
                team.append((str(m["id"]), role))
            rows.append((str(p.get("id")), team))
        daily.setdefault(day, {})[kind] = rows

    def key_for_name(name: str) -> str:
        n = str(name).lower()
        return "id:" + name2id[n] if n in name2id else "u:" + n

    item_idx = dict(zip(bench.items["item_id"].astype(str), bench.items["item_idx"]))
    item_day = bench.items["day_ord"].to_numpy()
    n_items = len(bench.items)
    hist_edges, target_team, target_src = [], {}, {}
    for day, kinds in daily.items():
        use = kinds.get("0005") or kinds.get("day") or []
        for pid, team in use:
            if pid in item_idx:
                li = int(item_idx[pid])
                ents = sorted({eid("id:" + m) for m, _ in team})
                hist_edges += [(li, e) for e in ents]
                if day in target_days and bench.items["day"].iloc[li] == day:
                    target_team[li] = np.array(ents, dtype=np.int64)
                    target_src[li] = "0005" if "0005" in kinds else "same-day capture"
    # 2. item table (names)
    v2 = pd.read_parquet(items_v2_path, columns=["id", "poster", "makers"])
    for pid, poster, makers in zip(v2["id"].astype(str), v2["poster"], v2["makers"]):
        if pid not in item_idx:
            continue
        li = int(item_idx[pid])
        try:
            ms = json.loads(makers or "[]")
        except (TypeError, ValueError):
            ms = []
        for n in set([poster] if poster else []) | {m for m in ms if isinstance(m, str) and m}:
            hist_edges.append((li, eid(key_for_name(n))))
    # 3. store: persons and their launched / hunted events
    persons = pd.read_parquet(os.path.join(store_dir, "persons.parquet"), columns=["person_id", "ph_user_id"])
    persons = persons.dropna(subset=["ph_user_id"])
    pid2ent = {p: eid("id:" + str(u)) for p, u in zip(persons["person_id"], persons["ph_user_id"])}
    pidx = dict(zip(bench.people["person_id"], bench.people["person_idx"]))
    ev = pq.read_table(os.path.join(store_dir, "events.parquet"),
                       columns=["person_id", "kind", "target_id", "ts_lo", "ts_quality"],
                       filters=[("platform", "=", "producthunt"), ("kind", "in", ["launched", "hunted", "upvote"])]
                       ).to_pandas()
    mk = ev[ev["kind"].isin(["launched", "hunted"]) & ev["person_id"].isin(pid2ent)].copy()
    mk = mk[mk["ts_lo"].notna()]
    mk["day_ord"] = _pt_day(mk["ts_lo"]).map(day_ord)
    mk["post"] = mk["target_id"].astype(str)
    extra_posts = sorted(set(mk["post"]) - set(item_idx))
    extra_idx = {p: n_items + k for k, p in enumerate(extra_posts)}
    first_day = mk.groupby("post")["day_ord"].min()
    launch_day = np.concatenate([item_day, first_day.reindex(extra_posts).to_numpy()]).astype(np.int64)
    mk["launch"] = mk["post"].map(lambda p: item_idx.get(p, extra_idx.get(p)))
    mk["entity"] = mk["person_id"].map(pid2ent)
    hist_edges += list(zip(mk["launch"].astype(int), mk["entity"].astype(int)))
    made = mk[mk["person_id"].isin(pidx)]
    made = pd.DataFrame({"person_idx": made["person_id"].map(pidx).astype(np.int64),
                         "launch": made["launch"].astype(np.int64)}).drop_duplicates()
    # 4. backings: benchmark history (endorse + comment, with an event day) + upvotes on the extra launches
    h = bench.hist[bench.hist["kind"].isin([KIND_CODE[_E], KIND_CODE[_C]])]
    evd = h["day_ord"].to_numpy().astype(np.int64)
    ts = h["ts"]
    is_c = (h["kind"] == KIND_CODE[_C]).to_numpy() & ts.notna().to_numpy()
    if is_c.any():
        cd = _pt_day(ts[is_c]).map(day_ord).to_numpy()
        evd[is_c] = np.maximum(evd[is_c], cd)
    back = pd.DataFrame({"person_idx": h["person_idx"].to_numpy().astype(np.int64),
                         "launch": h["item_idx"].to_numpy().astype(np.int64), "event_day": evd,
                         "endorse": (h["kind"] == KIND_CODE[_E]).to_numpy()})
    up = ev[(ev["kind"] == "upvote") & ev["person_id"].isin(pidx) & ev["target_id"].isin(extra_idx)]
    upx = pd.DataFrame({"person_idx": up["person_id"].map(pidx).astype(np.int64),
                        "launch": up["target_id"].map(extra_idx).astype(np.int64)})
    upx["event_day"] = launch_day[upx["launch"].to_numpy()]
    upx["endorse"] = True
    back = pd.concat([back, upx], ignore_index=True).drop_duplicates(["person_idx", "launch", "endorse"])
    del ev
    # 5. follows (undated): complete person -> entity, entity -> complete person
    need = set()
    for a in target_team.values():
        need.update(a.tolist())
    ent2pid = {}
    for p, e in pid2ent.items():
        ent2pid.setdefault(e, p)
    team_pids = {ent2pid[e] for e in need if e in ent2pid}
    fo = pq.read_table(os.path.join(store_dir, "events.parquet"), columns=["person_id", "target_id"],
                       filters=[("platform", "=", "producthunt"), ("kind", "=", "follows")],
                       read_dictionary=["person_id", "target_id"]).to_pandas()
    a = fo[fo["target_id"].isin(team_pids) & fo["person_id"].isin(pidx)]
    f_pe = pd.DataFrame({"person_idx": a["person_id"].astype(str).map(pidx).astype(np.int64),
                         "entity": a["target_id"].astype(str).map(pid2ent).astype(np.int64)}).drop_duplicates()
    b = fo[fo["person_id"].isin(team_pids) & fo["target_id"].isin(pidx)]
    f_ep = pd.DataFrame({"entity": b["person_id"].astype(str).map(pid2ent).astype(np.int64),
                         "person_idx": b["target_id"].astype(str).map(pidx).astype(np.int64)}).drop_duplicates()
    has_following = set(fo["person_id"].astype(str)[fo["person_id"].isin(team_pids)].unique())
    del fo
    ent_person = np.full(len(ent), -1, dtype=np.int64)
    for p, e in pid2ent.items():
        if p in pidx:
            ent_person[e] = pidx[p]
    team = pd.DataFrame(sorted(set(hist_edges)), columns=["launch", "entity"])
    tt = pd.DataFrame([(li, int(e), target_src[li]) for li, es in target_team.items() for e in es],
                      columns=["item_idx", "entity", "source"])
    n_need = len(need)
    cov = {"target_launches_with_team": len(target_team),
           "target_team_members": n_need,
           "members_resolved_to_a_store_person": int(sum(e in ent2pid for e in need)),
           "members_who_are_complete_held_people": int(sum(ent_person[e] >= 0 for e in need)),
           "members_with_a_following_list_in_store": int(sum(ent2pid.get(e) in has_following for e in need)),
           "launches_total": int(len(launch_day)), "launches_outside_item_table": int(len(extra_posts)),
           "team_edges": int(len(team)), "backings": int(len(back)),
           "target_source_counts": pd.Series(list(target_src.values())).value_counts().to_dict()}
    return {"launch_day": launch_day, "team": team, "target_team": tt, "made": made, "back": back,
            "follows_person_entity": f_pe, "follows_entity_person": f_ep, "ent_person": ent_person, "coverage": cov}
