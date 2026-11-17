#!/usr/bin/env python3
"""Upvotes: read past PH's signed-out offset-200 end with a search-term sweep.

Signed out, ProfileUpvotesQuery (and PH's own /@h/upvotes page when scrolled to its end) serves only offsets 0..199:
the page at offset 180 returns hasNextPage=false and offset 200 is empty, whatever the header says. The same query
with a search term (`query`) pages that term's matches to their own end with no 200 stop. So when the plain chain
ends short of the header, read single-character terms one after another, each to its own end, merging by post id,
until the union reaches the header or every term has been read. No account, no login.

Patches /opt/ph/reuse/paging_v2.py (whole pulls) and /opt/ph/reuse/ph_batch.py (repullupvotes mode).
"""
from __future__ import annotations

import os
import pathlib
import sys

# Off by default (orchestrator 07:06Z Nov 17): a sweep union is not the tab read to its end, so it can't make anyone complete.
if os.environ.get("PH_UPVOTES_SEARCH_SWEEP", "0") != "1":
    print("upvotes_search_sweep disabled (PH_UPVOTES_SEARCH_SWEEP != 1)")
    sys.exit(0)

MARK = "UPVOTES_SEARCH_SWEEP_PATCH"
root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path("/opt/ph/reuse")

HELPER = '''

SWEEP_TERMS = list("aeiornstlucdmphgybkfwvxzjq") + list("0123456789")  # UPVOTES_SEARCH_SWEEP_PATCH


async def upvotes_search_sweep(R, fetch, conn, add, header, cur, step=20, have=lambda: 0, over=lambda: False):
    """UPVOTES_SEARCH_SWEEP_PATCH: union of `query`=term pages, each term read to its own end (hasNextPage=false or
    an empty page). fetch(cursor, term) -> GraphQL data; conn(data) -> votedPosts connection; add(edges) -> new ids.
    ended: header_reached | all_terms | stopped | budget."""
    info = {"terms": [], "pages": 0, "ended": None}
    for t in SWEEP_TERMS:
        if have() >= header:
            info["ended"] = "header_reached"; break
        off, n_t, new_t = 0, 0, 0
        while True:
            if getattr(R, "stop", False): info["ended"] = "stopped"; return info
            if over(): info["ended"] = "budget"; return info
            c = conn(await fetch(cur(off), t)); info["pages"] += 1
            edges = c.get("edges") or []; n_t += len(edges); new_t += add(edges)
            if not edges or not (c.get("pageInfo") or {}).get("hasNextPage") or off > 2 * header + 1000: break
            off += step
        info["terms"].append([t, n_t, new_t])
    if info["ended"] is None:
        info["ended"] = "header_reached" if have() >= header else "all_terms"
    if getattr(R, "log", None): R.log("upvotes search sweep", have(), "of", header, "pages", info["pages"], "ended", info["ended"])
    return info
'''

PAGED_ANCHOR = '''        # 1640Z Data Feeder: upvotes end where the server ends (hasNextPage=false, ~200 signed-out); flag the signed-out cap
'''
PAGED_SWEEP = '''        sweep = None
        if op == "ProfileUpvotesQuery" and ended in ("server_end", "server_end_offset") and total and len(items) < total and not R.stop:  # UPVOTES_SEARCH_SWEEP_PATCH
            try:
                sweep = await upvotes_search_sweep(R, lambda c_, q_: R.gql(pages[0], op, **{var: c_}, **dict(extra, query=q_)), conn, add, total, cur, step, lambda: len(items), over)
            except Blocked as e:
                sweep = {"ended": "blocked"}; R.log("upvotes sweep stopped", e)
            except error_types as e:
                sweep = {"ended": "error"}; R.log("upvotes sweep error", str(e)[:200])
            npg += sweep.get("pages", 0)
            if sweep["ended"] == "budget": R.budget_hit = True
            ended = "server_end" if sweep["ended"] in ("header_reached", "all_terms") else "sweep_" + sweep["ended"]
'''

BATCH_ANCHOR = '''    old = {u["post_id"]: u for u in (res.get("upvotes") or {}).get("items") or []}
    ups = [post_item(n) for n in seen.values()]
'''
BATCH_SWEEP = '''    _sw = None
    if hdr and len(seen) < hdr and ended in ("empty_page", "hasNextPage_false", "no_endCursor", "no_new_3pages") and not R.stop:  # UPVOTES_SEARCH_SWEEP_PATCH
        from paging_v2 import upvotes_search_sweep as _upv_sweep
        def _sw_add(eds):
            k = 0
            for e in eds or []:
                n = (e or {}).get("node") or {}
                if n.get("id") and n["id"] not in seen: seen[n["id"]] = n; k += 1
            return k
        _sw = await _upv_sweep(R, lambda c_, q_: R.gql(p0, "ProfileUpvotesQuery", cursor=c_, query=q_), lambda dd: (dd.get("profile") or {}).get("votedPosts") or {}, _sw_add, hdr, P.cur, 20, lambda: len(seen), lambda: over_budget(R))
        pg += _sw.get("pages", 0)
        if R.stop: raise Blocked(R.blocks[-1]["what"] if R.blocks else "stopped")
        ended = {"budget": "budget", "header_reached": "server_end", "all_terms": "server_end"}.get(_sw["ended"], "search_sweep_" + _sw["ended"])
'''


def patch(path: pathlib.Path, edits: list[tuple[str, str]]) -> None:
    src = path.read_text()
    if MARK in src:
        print(f"{path.name}: upvotes_search_sweep already patched"); return
    for old, new in edits:
        if src.count(old) != 1:
            print(f"{path.name}: anchor not found, skipped: {old[:80]!r}"); return
        src = src.replace(old, new)
    path.write_text(src); print(f"{path.name}: upvotes_search_sweep patched")


patch(root / "paging_v2.py", [
    ("class _Stop(Exception):", HELPER.lstrip("\n") + "\n\nclass _Stop(Exception):"),
    (PAGED_ANCHOR, PAGED_SWEEP + PAGED_ANCHOR),
    ('if op == "ProfileUpvotesQuery" and ended in ("server_end", "server_end_offset") and total and len(items) < total:',
     'if op == "ProfileUpvotesQuery" and ended in ("server_end", "server_end_offset") and total and len(items) < total and not sweep:'),
    ('"trail_tail": trail[-3:], "next_cursor": nxt,', '"trail_tail": trail[-3:], "upvotes_sweep": sweep, "next_cursor": nxt,'),
])
patch(root / "ph_batch.py", [
    (BATCH_ANCHOR, BATCH_SWEEP + BATCH_ANCHOR),
    ('"paging": {"method": "endCursor_sequential", "pages": pg, "ended": ended, "trail_tail": trail[-3:]}}',
     '"paging": {"method": "endCursor_sequential" + ("+search_sweep" if _sw else ""), "pages": pg, "ended": ended, "trail_tail": trail[-3:], "upvotes_sweep": _sw}}'),
    ('ended in ("empty_page", "hasNextPage_false", "no_endCursor"):\n        res["upvotes"].update(upvotes_capped=True',
     'ended in ("empty_page", "hasNextPage_false", "no_endCursor") and not _sw:\n        res["upvotes"].update(upvotes_capped=True'),
])
