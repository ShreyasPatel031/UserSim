#!/usr/bin/env python3
"""Shreyas / orchestrator 2026-11-17: Upvotes tab ends at PH hasNextPage=false (signed in/out).
Do not flag upvotes_capped for that end; record ph_list_end in paging. No search sweep changes here."""
from __future__ import annotations

import pathlib
import sys

MARK = "UPVOTES_PH_END_PATCH"
root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path("/opt/ph/reuse")

HELPER = '''

def trail_has_next_false(pg):  # UPVOTES_PH_END_PATCH
    tt = (pg or {}).get("trail_tail") or []
    if not tt:
        return False
    row = tt[-1]
    if len(row) >= 4:
        return row[3] is False
    if len(row) >= 3:
        return row[2] is False
    return False
'''


def one(path: pathlib.Path, edits: list[tuple[str, str]]) -> None:
    src = path.read_text()
    if MARK in src:
        print(f"{path.name}: already patched")
        return
    for old, new in edits:
        if src.count(old) != 1:
            print(f"{path.name}: anchor miss: {old[:72]!r}")
            sys.exit(1)
        src = src.replace(old, new)
    path.write_text(src)
    print(f"{path.name}: {MARK}")


one(
    root / "paging_v2.py",
    [
        (
            "        if op == \"ProfileUpvotesQuery\" and ended in (\"server_end\", \"server_end_offset\") and total and len(items) < total:  # full18f nocap2: flag any short signed-out end (stricter)\n            R.upv_capped = True",
            "        # UPVOTES_PH_END_PATCH: server_end = PH hasNextPage=false; not our cap\n"
            '        if op == "ProfileUpvotesQuery" and ended not in ("server_end", "server_end_offset", "complete") and total and len(items) < total:\n'
            "            R.upv_capped = True",
        ),
    ],
)

one(
    root / "ph_batch.py",
    [
        (
            "    if getattr(R, \"upv_capped\", False) and _uh > len(ups):  # 1955Z: only when the server endCursor chain itself ended short (no 190 heuristic)\n"
            "        res[\"upvotes\"].update(upvotes_capped=True, cap=len(ups), complete_not_visible=True, status=\"complete_not_visible\", limit_owner=\"PH\")",
            "    _run = res.get(\"run\") or {}\n"
            "    _tm = _run.get(\"timing\") or {}\n"
            "    _uv = (_tm.get(\"upvotes\") or {}).get(\"paging\") or getattr(R, \"last_paging\", None) or {}\n"
            "    _ph_end = _uv.get(\"ended\") in (\"server_end\", \"hasNextPage_false\") or trail_has_next_false(_uv)\n"
            "    if getattr(R, \"upv_capped\", False) and _uh > len(ups) and not _ph_end:  # UPVOTES_PH_END_PATCH\n"
            "        res[\"upvotes\"].update(upvotes_capped=True, cap=len(ups), complete_not_visible=True, status=\"complete_not_visible\", limit_owner=\"PH\")",
        ),
        (
            '    res["upvotes"] = {"header": hdr, "count": len(ups), "items": ups, "paging": {"method": "endCursor_sequential", "pages": pg, "ended": ended, "trail_tail": trail[-3:]}}',
            '    res["upvotes"] = {"header": hdr, "count": len(ups), "items": ups, "paging": {"method": "endCursor_sequential", "pages": pg, "ended": ended, "trail_tail": trail[-3:], "ph_list_end": ended == "hasNextPage_false", "ph_has_next_page_at_end": False if ended == "hasNextPage_false" else None}}',
        ),
        (
            '    if hdr and len(ups) < 0.98 * hdr and ended in ("empty_page", "hasNextPage_false", "no_endCursor"):\n'
            "        res[\"upvotes\"].update(upvotes_capped=True, cap=len(ups), complete_not_visible=True, status=\"complete_not_visible\", limit_owner=\"PH\")\n"
            '        res.setdefault("notes", []).append(f"upvotes: header {hdr}, server endCursor chain ended ({ended}) at {len(ups)} signed-out -> upvotes_capped, complete_not_visible")\n'
            '        res["upvotes"]["limit_owner"] = "PH (signed-out upvotes list ends ~200; PH\'s own limit, kept)"',
            '    if ended == "hasNextPage_false":  # UPVOTES_PH_END_PATCH\n'
            '        res["upvotes"].setdefault("paging", {})["ph_list_end"] = True\n'
            '        res["upvotes"].update(status="complete", ph_list_end="hasNextPage_false")\n'
            '    elif hdr and len(ups) < 0.98 * hdr and ended in ("empty_page", "no_endCursor", "no_new_3pages"):\n'
            "        res[\"upvotes\"].update(upvotes_capped=True, cap=len(ups), status=\"partial\", limit_owner=\"PH\")\n"
            '        res.setdefault("notes", []).append(f"upvotes: ended {ended} before PH list end at {len(ups)} of header {hdr}")',
        ),
    ],
)

pb = root / "ph_batch.py"
src = pb.read_text()
if "def trail_has_next_false" not in src:
    anchor = "async def pull_upvotes(R, pages, handle, a, cap):"
    if anchor not in src:
        print("pull_upvotes anchor missing", file=sys.stderr)
        sys.exit(1)
    src = src.replace(anchor, HELPER.lstrip("\n") + "\n" + anchor, 1)
    pb.write_text(src)