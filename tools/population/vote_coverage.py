#!/usr/bin/env python3
"""Vote coverage of the current store (population agent, Nov 14; data quality, no experiment).

Definition (same as the Nov 13 headline): for a window of PT launch days, the share of all votes cast on those launches
(launch's final `votes`) that come from held, complete people, capped at one vote per person per launch, counting a
vote when the launch's post_id is in the person's upvote list (items + items_earlier) and the launch's day is in the
window. Reported for all launches, the day's top 3 (daily_rank <= 3), and launches outside a given seed set.
Also: how many of the held voters had their profile read after the launch day (only those can show the vote).

Launch facts: tables/launches parquet parts (initial backfill + daily 31-day rereads; the latest part per launch id wins).
Counts only to stdout. Usage:
  vote_coverage.py VM_DIR COMPLETE_TSV LAUNCH_PARTS_DIR D0 D1 [D0 D1 ...] [--seed-ids FILE]
"""
import glob
import json
import os
import sys
from collections import defaultdict

import pandas as pd


def launches(parts_dir):
    L = {}
    for f in sorted(glob.glob(os.path.join(parts_dir, "*.parquet"))):  # names sort by write time; later parts win
        df = pd.read_parquet(f, columns=["id", "day", "votes", "daily_rank"])
        for r in df.itertuples(index=False):
            if r.votes is None or pd.isna(r.votes):
                continue
            L[str(r.id)] = (str(r.day), int(r.votes), None if pd.isna(r.daily_rank) else int(r.daily_rank))
    return L


def main():
    a = sys.argv[1:]
    seed = set()
    if "--seed-ids" in a:
        i = a.index("--seed-ids")
        seed = {l.strip() for l in open(a[i + 1]) if l.strip()}
        a = a[:i] + a[i + 2:]
    vm, comp_tsv, parts = a[:3]
    wins = [(a[i], a[i + 1]) for i in range(3, len(a), 2)]
    L = launches(parts)
    comp = set()
    for l in open(comp_tsv):
        h = l.split("\t")[0].strip().lower()
        if h:
            comp.add(h)
    files = {}
    for fn in os.listdir(vm):
        if fn.endswith(".json"):
            k = fn[:-5].replace("_f1fix", "").lower()
            if k in comp and (k not in files or "_f1fix" in files[k]):
                files[k] = fn
    lo = min(w[0] for w in wins)
    hi = max(w[1] for w in wins)
    in_any = {pid for pid, (d, v, r) in L.items() if lo <= d <= hi}
    voters = defaultdict(set)      # launch id -> set of person keys
    read_after = defaultdict(set)  # launch id -> voters whose newest read finished after the launch day
    pulls_after = {}
    refreshed = set()
    for k, fn in files.items():
        try:
            d = json.load(open(os.path.join(vm, fn)))
        except Exception:
            continue
        u = d.get("upvotes") or {}
        fin = str((d.get("run") or {}).get("finished_utc") or "")
        for x in (u.get("items") or []) + (u.get("items_earlier") or []):
            pid = str((x or {}).get("post_id") or "")
            if pid in in_any:
                voters[pid].add(k)
        # upvote_refresh (fleet job from Nov 14): the newest read of the Upvotes tab is the latest of the whole-person
        # pull and any refresh delta's read time (any key under upvotes holding "refresh"/"delta" with a read time)
        last = fin
        for kk, vv in u.items():
            if "refresh" in kk or "delta" in kk:
                for e in (vv if isinstance(vv, list) else [vv]):
                    if isinstance(e, dict):
                        t = str(e.get("read_utc") or e.get("read_at") or e.get("finished_utc") or "")
                        if t > last:
                            last = t
                            refreshed.add(k)
        pulls_after[k] = last
    out = {"complete_people_in_store": len(files)}
    for d0, d1 in wins:
        ids = [pid for pid, (d, v, r) in L.items() if d0 <= d <= d1]
        V = sum(L[i][1] for i in ids)
        H = sum(min(len(voters[i]), L[i][1]) for i in ids)
        t3 = [i for i in ids if (L[i][2] or 99) <= 3]
        V3 = sum(L[i][1] for i in t3)
        H3 = sum(min(len(voters[i]), L[i][1]) for i in t3)
        ns = [i for i in ids if i not in seed] if seed else []
        Vn = sum(L[i][1] for i in ns)
        Hn = sum(min(len(voters[i]), L[i][1]) for i in ns)
        held = set().union(*[voters[i] for i in ids]) if ids else set()
        # read after launch day: the person's newest pull finished after the end of the launch's PT day (UTC+8 bound)
        after = 0
        for i in ids:
            import datetime as _dt
            nd = (_dt.date.fromisoformat(L[i][0]) + _dt.timedelta(days=1)).isoformat()
            day_end = f"{nd}T08:00:00Z"  # end of the PT launch day (00:00 PT next day = 07:00Z PDT / 08:00Z PST; 08:00Z is the safe bound)
            after += sum(1 for k in voters[i] if pulls_after.get(k, "") > day_end)
        out[f"{d0}..{d1}"] = {
            "launches": len(ids), "votes": V, "held_votes": H, "share_all": round(H / V, 4) if V else None,
            "top3_launches": len(t3), "share_top3": round(H3 / V3, 4) if V3 else None,
            "outside_seed_launches": len(ns) if seed else None,
            "share_outside_seed": round(Hn / Vn, 4) if seed and Vn else None,
            "held_voters": len(held), "held_votes_read_after_launch_day": after,
        }
    import datetime as _dt
    now = _dt.datetime.now(_dt.timezone.utc)
    ages = sorted((now - _dt.datetime.fromisoformat(v.replace("Z", "+00:00"))).total_seconds() / 86400
                  for v in pulls_after.values() if v)
    out["upvote_refresh"] = {"complete_people": len(files), "people_with_refresh_delta": len(refreshed),
                             "median_days_since_last_upvotes_read": round(ages[len(ages) // 2], 2) if ages else None}
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
