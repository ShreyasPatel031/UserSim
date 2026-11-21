#!/usr/bin/env python3
"""Vote coverage of the current store (population agent; a north-star metric from Nov 14; data quality, no experiment).

Definition (same as the Nov 13 headline): for a window of PT launch days, the share of all votes cast on those launches
(each launch's final `votes`) that come from held, complete people, capped at one vote per person per launch and at
the launch's displayed votes. A vote counts when the launch's post_id is in the person's upvote list (items +
items_earlier). Reported for all launches and the day's top 3 (daily_rank <= 3), with and without seeded people
(people whose entry route was a follower crawl of top launches' makers) and without flagged people (E5 ring flag
ph_discounted_likely; a column, nobody is deleted), plus:
  - over-count: launches where held upvoters exceed PH's displayed votes (count, and 3 post_ids for a check);
  - reads after launch day: held voters whose last Upvotes read is after the launch's PT day (only they can show it);
  - upvote_refresh audit: people with a refresh delta (upvotes.refresh*/delta* read_utc, or upvotes_refreshed_at from a whole-person
    refresh resave), median days since the last Upvotes read.
People are keyed by ph_user_id (file name only when the record has none). Launch facts come from tables/launches
parquet parts ordered by read time (initial backfill first, then the daily rereads; the latest read of a launch wins).
Counts only to stdout. Usage:
  vote_coverage.py VM_DIR COMPLETE_TSV LAUNCH_PARTS_DIR D0 D1 [D0 D1 ...] [--salt FILE --seeded-pids FILE --flagged-pids FILE]
"""
import datetime as dt
import glob
import hashlib
import json
import os
import sys
from collections import defaultdict

import pandas as pd


def launches(parts_dir):
    """id -> (day, votes, daily_rank, read_utc); parts read in read-time order so the latest read wins."""
    def read_time(f):
        df = pd.read_parquet(f, columns=["updated_at"])
        return str(df["updated_at"].max())
    files = sorted(glob.glob(os.path.join(parts_dir, "*.parquet")), key=read_time)
    L = {}
    for f in files:
        df = pd.read_parquet(f, columns=["id", "day", "votes", "daily_rank", "updated_at"])
        for r in df.itertuples(index=False):
            if r.votes is None or pd.isna(r.votes):
                continue
            L[str(r.id)] = (str(r.day), int(r.votes), None if pd.isna(r.daily_rank) else int(r.daily_rank), str(r.updated_at))
    return L


def main():
    a = sys.argv[1:]
    opt = {}
    for k in ("--salt", "--seeded-pids", "--flagged-pids"):
        if k in a:
            i = a.index(k)
            opt[k] = a[i + 1]
            a = a[:i] + a[i + 2:]
    vm, comp_tsv, parts = a[:3]
    wins = [(a[i], a[i + 1]) for i in range(3, len(a), 2)]
    salt = open(opt["--salt"]).read().strip() if "--salt" in opt else None
    seeded = {l.strip() for l in open(opt["--seeded-pids"]) if l.strip()} if "--seeded-pids" in opt else None
    flagged = {l.strip() for l in open(opt["--flagged-pids"]) if l.strip()} if "--flagged-pids" in opt else None  # E5 ring flag
    pid = (lambda h: "p_" + hashlib.sha256((salt + "producthunt:" + h.lower().lstrip("@")).encode()).hexdigest()[:16]) if salt else None
    L = launches(parts)
    comp = {l.split("\t")[0].strip().lower() for l in open(comp_tsv) if l.strip()}
    files = {}
    for fn in os.listdir(vm):
        if fn.endswith(".json"):
            k = fn[:-5].replace("_f1fix", "").lower()
            if k in comp and (k not in files or "_f1fix" in files[k]):
                files[k] = fn
    lo, hi = min(w[0] for w in wins), max(w[1] for w in wins)
    in_any = {i for i, v in L.items() if lo <= v[0] <= hi}
    voters = defaultdict(set)  # launch id -> person keys (ph_user_id)
    last_read, is_seeded, is_flagged, refreshed = {}, {}, {}, set()
    for h, fn in files.items():
        try:
            d = json.load(open(os.path.join(vm, fn)))
        except Exception:
            continue
        key = str(d.get("ph_user_id") or "") or f"file:{h}"
        u = d.get("upvotes") or {}
        last = str((d.get("run") or {}).get("finished_utc") or "")
        rt = str(d.get("upvotes_refreshed_at") or u.get("refreshed_at") or "")  # fleet 08:53Z Nov 16: whole-person refresh resave
        # 09:2xZ Nov 21: the fleet's finished_utc fix-up now stamps refresh saves with the refresh time, so rt is no
        # longer later than finished_utc; any upvotes_refreshed_at marks a refreshed person
        if rt:
            refreshed.add(key)
            last = max(last, rt)
        for kk, vv in u.items():  # upvote_refresh deltas (fleet job from Nov 14)
            if "refresh" in kk or "delta" in kk:
                for e in (vv if isinstance(vv, list) else [vv]):
                    if isinstance(e, dict):
                        t = str(e.get("read_utc") or e.get("read_at") or e.get("finished_utc") or "")
                        if t > last:
                            last = t
                            refreshed.add(key)
        last_read[key] = max(last, last_read.get(key, ""))
        if seeded is not None:
            is_seeded[key] = pid(h) in seeded
        if flagged is not None:
            is_flagged[key] = pid(h) in flagged
        for x in (u.get("items") or []) + (u.get("items_earlier") or []):
            p = str((x or {}).get("post_id") or "")
            if p in in_any:
                voters[p].add(key)
    out = {"complete_people": len(last_read), "seeded_people": sum(is_seeded.values()) if seeded is not None else None,
           "flagged_people": sum(is_flagged.values()) if flagged is not None else None}

    def share(ids, keep):
        V = sum(L[i][1] for i in ids)
        H = sum(min(sum(1 for k in voters[i] if keep(k)), L[i][1]) for i in ids)
        return round(H / V, 4) if V else None

    for d0, d1 in wins:
        ids = [i for i, v in L.items() if d0 <= v[0] <= d1]
        t3 = [i for i in ids if (L[i][2] or 99) <= 3]
        allk = lambda k: True
        nos = lambda k: not is_seeded.get(k, False)
        nof = lambda k: not is_flagged.get(k, False)
        cnt = lambda i, keep: sum(1 for k in voters[i] if keep(k))
        over = sorted((i for i in ids if len(voters[i]) > L[i][1]), key=lambda i: len(voters[i]) - L[i][1], reverse=True)
        over_by = {"with_all": len(over),
                   "without_seeded": sum(1 for i in ids if cnt(i, nos) > L[i][1]) if seeded is not None else None,
                   "without_flagged": sum(1 for i in ids if cnt(i, nof) > L[i][1]) if flagged is not None else None}
        after = held = 0
        for i in ids:
            nd = (dt.date.fromisoformat(L[i][0]) + dt.timedelta(days=1)).isoformat()
            end = f"{nd}T08:00:00Z"  # end of the PT launch day (safe bound across DST)
            for k in voters[i]:
                held += 1
                after += last_read.get(k, "") > end
        out[f"{d0}..{d1}"] = {
            "launches": len(ids), "votes": sum(L[i][1] for i in ids), "top3_launches": len(t3),
            "share_all": share(ids, allk), "share_top3": share(t3, allk),
            "share_all_without_seeded": share(ids, nos) if seeded is not None else None,
            "share_top3_without_seeded": share(t3, nos) if seeded is not None else None,
            "share_all_without_flagged": share(ids, nof) if flagged is not None else None,
            "share_top3_without_flagged": share(t3, nof) if flagged is not None else None,
            "launches_over_100pct": len(over), "top3_over_100pct": sum(1 for i in over if i in set(t3)),
            "launches_over_100pct_by_variant": over_by,
            "over_100pct_examples": [{"post_id": i, "held": len(voters[i]), "displayed": L[i][1]} for i in over[:3]],
            "held_person_launch_votes": held, "of_which_read_after_launch_day": after,
        }
    now = dt.datetime.now(dt.timezone.utc)
    ages = sorted((now - dt.datetime.fromisoformat(v.replace("Z", "+00:00"))).total_seconds() / 86400
                  for v in last_read.values() if v)
    out["upvote_refresh"] = {"complete_people": len(last_read), "people_with_refresh_delta": len(refreshed),
                             "median_days_since_last_upvotes_read": round(ages[len(ages) // 2], 2) if ages else None}
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
