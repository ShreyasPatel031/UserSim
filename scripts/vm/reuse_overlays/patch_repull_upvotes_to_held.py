#!/usr/bin/env python3
"""repullupvotes: page until first held upvote (overlap with stored items) or PH list end; no person byte/time budget."""
from __future__ import annotations

import pathlib
import sys

MARK = "REPULL_UPVOTES_TO_HELD_PATCH"
p = pathlib.Path("/opt/ph/reuse/ph_batch.py")
src = p.read_text()
if MARK in src:
    print("repull_upvotes_to_held already patched")
    sys.exit(0)

old_loop = """    seen = {}; endc = None; pg = 0; trail = []; ended = None; zn = 0; maxp = None  # 2020Z nocap2: no page cap; server end / budget only
    while not R.stop:
        if over_budget(R): ended = 'budget'; R.budget_hit = True; break
        dd = await R.gql(p0, "ProfileUpvotesQuery", cursor=endc, query=""); pg += 1
        c = (dd.get("profile") or {}).get("votedPosts") or {}; ed = c.get("edges") or []; pi = c.get("pageInfo") or {}
        new = 0
        for e in ed:
            n = (e or {}).get("node") or {}
            if n.get("id") and n["id"] not in seen: seen[n["id"]] = n; new += 1"""

new_loop = """    seen = {}; endc = None; pg = 0; trail = []; ended = None; zn = 0; maxp = None  # 2020Z nocap2: no page cap; server end / budget only
    old_ids = {u.get("post_id") for u in (res.get("upvotes") or {}).get("items") or [] if u.get("post_id")}  # {MARK}
    _refresh_no_budget = a.mode == "repullupvotes"
    _held_break = False
    while not R.stop:
        if not _refresh_no_budget and over_budget(R): ended = 'budget'; R.budget_hit = True; break
        dd = await R.gql(p0, "ProfileUpvotesQuery", cursor=endc, query=""); pg += 1
        c = (dd.get("profile") or {}).get("votedPosts") or {}; ed = c.get("edges") or []; pi = c.get("pageInfo") or {}
        new = 0
        for e in ed:
            n = (e or {}).get("node") or {}
            pid = n.get("id")
            if pid and pid in old_ids:
                if pid not in seen:
                    seen[pid] = n
                    new += 1
                ended = "first_held_upvote"
                _held_break = True
                break
            if n.get("id") and n["id"] not in seen: seen[n["id"]] = n; new += 1
        if _held_break: break"""

if old_loop not in src:
    print("pull_upvotes loop anchor not found", file=sys.stderr)
    sys.exit(1)
src = src.replace(old_loop, new_loop, 1)

old_budget_tail = """    if ended == "budget":  # 2020Z nocap2: split, never drop -> deep_list with resume cursor
        res["upvotes"].update(status="partial", truncated_budget=True); res["truncated_budget"] = ["upvotes"]; R.cursors = {"upvotes": endc}"""

new_budget_tail = """    if ended == "first_held_upvote":  # {MARK}
        res.setdefault("upvotes", {}).update(status="complete", refresh_to_held=True, ph_list_end="first_held_upvote")
    elif ended == "budget":  # 2020Z nocap2: split, never drop -> deep_list with resume cursor
        res["upvotes"].update(status="partial", truncated_budget=True); res["truncated_budget"] = ["upvotes"]; R.cursors = {"upvotes": endc}"""

if old_budget_tail not in src:
    print("budget tail anchor not found", file=sys.stderr)
    sys.exit(1)
src = src.replace(old_budget_tail, new_budget_tail, 1)

# Remove duplicate old= line if we now have old_ids only (old= still needed after loop)
p.write_text(src)
print("patched repull_upvotes_to_held")