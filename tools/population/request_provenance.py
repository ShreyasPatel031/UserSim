#!/usr/bin/env python3
"""Why each person was pulled: request provenance from every request batch list (population agent, Nov 13).

The pulls record when a person was fetched, not why (E5: without the route we cannot separate signal from selection).
This rebuilds the "why" from the request lists that fed the fleet and earlier pulls. One row per (person, batch it was
requested in): route, seed (the launch / day / list rank that put the person there, when the list says), batch file,
batch line rank, request time (= the batch object's creation time), earliest first per person.

Routes (by batch file):
  pool_nov2_base          the Data Feeder's Nov 1-2 pool (store_v1 persons, from ph_upvotes_full p1 / people_v3g)
  pool_addition           Data Feeder pool growth, ph_people_daily/<day>/pool_additions.jsonl (seed = its source: maker, ...)
  pool_upvote_refresh     requests/upvote_refresh_* (Nov 1 refresh lists of the pool)
  pilot                   pilot200 / pilot50 / people_live full_target
  data_feeder_need_list   population_data/master/need_list_<day>.txt (seed = tier + pull type)
  likely_voter_need_list / recent_upvoter_need_list / discovery_follower_of_makers / people_live_need_list
                          people_live need_list.jsonl (Nov 8), split by its own reason (discovery = follower of top-500
                          Oct 1-24 makers, a follower crawl)
  lastweek_launch_voter   last-week (Oct 29-Nov 4) voter priority lists (seed = votes in window when known)
  voternet_follow_graph   ranked by follow edges to known voters (seed = rank, score, edge sources)
  source_stratified       population/requests/source_strat_people.txt
  launch_team             makers + hunters of a launch (seed = launch day + slug(s) + role)
  recent_launch_linked    Nov 12 queue band 1: commenters / makers / hunters / followers of makers of recent top-10 launches
                          (seed = launch day:id/slug + link kind)
  need_list_queue         Nov 8 and Nov 12 queue bands built from the need lists
  completion              completion queue (saved but incomplete)
  repull_fix              re-pulls to fix a failed tab, build or gate (rerun_whole_*, fix_*, deep_list, offset re-page, ...)
  repull_gap              re-pull to restore data lost to the old overwrite merge
  upvote_refresh_complete one-tab upvote refresh of complete people
Usage: request_provenance.py SRC_DIR FILES_TSV LAUNCH_DIR POOL_DIR SALT STORE_V1_PERSONS OUT_PARQUET   (counts only to stdout)
"""
import collections
import glob
import hashlib
import json
import os
import re
import sys

import pandas as pd


def main():
    src, files_tsv, launch_dir, pool_dir, salt_f, v1_persons, out = sys.argv[1:8]
    salt = open(salt_f).read().strip()
    norm = lambda h: (h or "").strip().lstrip("@").lower()
    pid = lambda h: "p_" + hashlib.sha256((salt + "producthunt:" + norm(h)).encode()).hexdigest()[:16]
    assert pid("example_user") == "p_97eb5d57c445ef1f"
    ctime = {}
    for l in open(files_tsv):
        t, u = l.rstrip("\n").split("\t")
        ctime[u.rsplit("/", 1)[-1]] = t
    # backup copies carry the backup's time; use the original request time
    ORIG = {"queue.txt.bak_20261112T2300Z": "2026-11-08T20:42:33Z", "need_list.jsonl.bak_20261113T1105Z": "2026-11-08T17:20:03Z"}
    ctime.update({k: v for k, v in ORIG.items() if k in ctime})
    rows = []

    def add(p, route, seed, batch, rank):
        rows.append((p, route, seed, batch, rank, ctime.get(batch, "")))

    def handles(fn):
        out_ = []
        for l in open(os.path.join(src, fn), errors="replace"):
            if not l.strip() or l.startswith("#"):
                continue
            h = norm(re.split(r"[\t ,]", l.strip(), maxsplit=1)[0])
            if h and re.match(r"^[a-z0-9_.\-]+$", h):
                out_.append((h, l.rstrip("\n")))
        return out_
    # --- seeds that need other files ---
    lastweek_votes = {}
    if os.path.exists(f"{src}/lastweek_voters.tsv"):
        for h, l in handles("lastweek_voters.tsv"):
            p_ = l.split("\t")
            if len(p_) > 1 and p_[1].isdigit():
                lastweek_votes[h] = int(p_[1])
    voternet = {}
    for fn in glob.glob(f"{src}/candidates_voternet_*.jsonl"):
        for l in open(fn):
            try:
                d = json.loads(l)
            except Exception:
                continue
            voternet[norm(d.get("handle"))] = f"rank {d.get('rank')}; score {d.get('score')}; via {','.join(d.get('sources') or [])}"
    # launch links (who is tied to which launch): makers/hunters by slug, commenters by post id, followers of makers
    team, link = collections.defaultdict(set), collections.defaultdict(set)
    vm_follow = {}
    for d in sorted(os.listdir(launch_dir)):
        P = os.path.join(launch_dir, d)
        snap = [json.loads(l) for l in open(f"{P}/snap.jsonl")] if os.path.exists(f"{P}/snap.jsonl") else []
        top = sorted(snap, key=lambda x: (x.get("dailyRank") or 999))[:10]
        ids = {str(x["id"]): x.get("slug") for x in top}
        slugs = {x.get("slug") for x in top}
        if os.path.exists(f"{P}/makers_header.jsonl"):
            for l in open(f"{P}/makers_header.jsonl"):
                m = json.loads(l)
                h = norm(m.get("username"))
                for s in m.get("posts") or []:
                    team[h].add(f"{d}:{s}:{'+'.join(m.get('roles') or [])}")
                    if s in slugs:
                        link[h].add(f"{d}:{s}:maker_hunter")
        for f in glob.glob(f"{P}/2*.jsonl"):
            for l in open(f):
                try:
                    c = json.loads(l)
                except Exception:
                    continue
                if str(c.get("post_id")) in ids and c.get("username"):
                    link[norm(c["username"])].add(f"{d}:{ids[str(c['post_id'])]}:commenter")
    # --- per batch file ---
    for fn in sorted(os.listdir(src)):
        low = fn.lower()
        if low.startswith("candidates_voternet") or low == "lastweek_voters.tsv":
            continue
        if low.startswith("need_list_") and low.endswith(".txt"):  # Data Feeder master, person_id based
            for i, l in enumerate(open(f"{src}/{fn}")):
                p_ = l.rstrip("\n").split("\t")
                if len(p_) >= 6 and p_[1] == "person":
                    add(p_[2], "data_feeder_need_list", f"{p_[5].strip()}; {p_[3]}", fn, i)
            continue
        if low.startswith("need_list.jsonl"):
            for i, l in enumerate(open(f"{src}/{fn}")):
                try:
                    d = json.loads(l)
                except Exception:
                    continue
                p = d.get("person_id") if str(d.get("person_id", "")).startswith("p_") and not str(d.get("person_id")).endswith("_d") else pid(d.get("handle"))
                why = str(d.get("reason") or "")
                r = ("discovery_follower_of_makers" if "discovery" in why else "likely_voter_need_list" if "likely" in why
                     else "recent_upvoter_need_list" if "recent upvote" in why else "people_live_need_list")
                add(p, r, f"{d.get('tier')}; {why.split(';')[0]}" + (f"; lists {d.get('lists')}" if d.get("lists") else ""), fn, i)
            continue
        hs = handles(fn)
        for i, (h, line) in enumerate(hs):
            p = pid(h)
            if low.startswith("upvote_refresh"):
                r, s = "pool_upvote_refresh", ""
            elif low.startswith(("pilot", "full_target")):
                r, s = "pilot", ""
            elif "voternet" in low:
                r, s = "voternet_follow_graph", voternet.get(h, "")
            elif "lastweek" in low or low.startswith("priority_lastweek"):
                r, s = "lastweek_launch_voter", f"window Oct 29-Nov 4; votes {lastweek_votes[h]}" if h in lastweek_votes else "window Oct 29-Nov 4"
            elif "overnight" in low or "resume_interleaved" in low:
                if h in lastweek_votes:
                    r, s = "lastweek_launch_voter", f"window Oct 29-Nov 4; votes {lastweek_votes[h]}"
                elif h in voternet:
                    r, s = "voternet_follow_graph", voternet[h]
                else:
                    r, s = "repull_fix", "resume list"
            elif low.startswith("source_strat"):
                r, s = "source_stratified", line.split("\t", 1)[1] if "\t" in line else ""
            elif low.startswith("team_audience"):
                r, s = "launch_team", ";".join(sorted(team.get(h, [])))[:300]
            elif low.startswith(("queue_ranked", "queue.txt")) and "bak" not in low:
                band = line.split("\t")[1] if "\t" in line else ""
                if band == "1":
                    r, s = "recent_launch_linked", ";".join(sorted(link.get(h, []))) or "follower of a top-10 launch maker/hunter"
                elif band in ("2", "3"):
                    r, s = "need_list_queue", f"band {band}"
                else:
                    r, s = "need_list_queue", f"band {band or '?'} (prior queue)"
            elif low.startswith("queue.txt.bak"):
                r, s = "need_list_queue", "Nov 8 queue"
            elif low.startswith("completion_queue"):
                r, s = "completion", line.split("\t")[1] if "\t" in line else ""
            elif low.startswith("repull_gap"):
                r, s = "repull_gap", ""
            elif low.startswith("refresh_upvotes"):
                r, s = "upvote_refresh_complete", ""
            else:
                r, s = "repull_fix", ""
            add(p, r, s, fn, i)
    # pool membership
    v1 = pd.read_parquet(v1_persons)
    for p in v1.person_id:
        rows.append((p, "pool_nov2_base", "Data Feeder Nov 1-2 pool (ph_upvotes_full p1 / people_v3g)", "store_v1/persons.parquet", 0, "2026-11-02T00:00:00Z"))
    for f in sorted(glob.glob(f"{pool_dir}/*.jsonl")):
        day = os.path.basename(f)[:-6]
        for i, l in enumerate(open(f)):
            try:
                d = json.loads(l)
            except Exception:
                continue
            rows.append((pid(d.get("username")), "pool_addition", f"{day}; source {','.join(d.get('sources') or [d.get('source') or ''])}",
                         f"ph_people_daily/{day}/pool_additions.jsonl", i, d.get("added_at") or f"{day}T00:00:00Z"))
    df = pd.DataFrame(rows, columns=["person_id", "route", "seed", "batch_file", "batch_rank", "requested_utc"])
    df = df.sort_values(["person_id", "requested_utc", "batch_file", "batch_rank"]).drop_duplicates(["person_id", "route", "batch_file"])
    df.to_parquet(out, index=False)
    print(f"PROVENANCE rows={len(df):,} people={df.person_id.nunique():,} batches={df.batch_file.nunique()}")
    print("people by route (any batch):", df.groupby("route").person_id.nunique().sort_values(ascending=False).to_dict())


if __name__ == "__main__":
    main()
