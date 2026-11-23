#!/usr/bin/env python3
"""When PH_REPULL_POST_CLOSE_CALIBRATE=1, repullupvotes scrolls past held watermark to list end (post-close new votes)."""
from __future__ import annotations

import pathlib
import sys

MARK = "POST_CLOSE_CALIBRATE_PATCH"
p = pathlib.Path("/opt/ph/reuse/ph_batch.py")
src = p.read_text()
if MARK in src:
    print("post_close_calibrate already patched")
    sys.exit(0)
if "first_held_upvote" not in src:
    print("first_held_upvote refresh path missing", file=sys.stderr)
    sys.exit(1)

held_anchor = """    _refresh_no_budget = a.mode == "repullupvotes"
    _held_break = False"""

held_repl = """    _refresh_no_budget = a.mode == "repullupvotes"
    _held_break = False
    _scroll_past_held = a.mode == "repullupvotes" and __import__("os").environ.get("PH_REPULL_POST_CLOSE_CALIBRATE", "0") == "1"  # POST_CLOSE_CALIBRATE_PATCH"""

if held_anchor not in src:
    print("held_break anchor not found", file=sys.stderr)
    sys.exit(1)
src = src.replace(held_anchor, held_repl, 1)

old_break = """                ended = "first_held_upvote"
                _held_break = True
                break"""

new_break = """                if _scroll_past_held:
                    R._refresh_past_held = True
                else:
                    ended = "first_held_upvote"
                    _held_break = True
                    break"""

if old_break not in src:
    print("held break tail not found", file=sys.stderr)
    sys.exit(1)
src = src.replace(old_break, new_break, 1)

old_loop_break = """        if _held_break: break"""

new_loop_break = """        if _held_break and not _scroll_past_held: break"""

if old_loop_break not in src:
    print("loop held break not found", file=sys.stderr)
    sys.exit(1)
src = src.replace(old_loop_break, new_loop_break, 1)

for end_anchor in (
    """    if ended == "first_held_upvote":  # REPULL_UPVOTES_TO_HELD_PATCH
        res.setdefault("upvotes", {}).update(status="complete", refresh_to_held=True, ph_list_end="first_held_upvote")""",
    """    if ended == "first_held_upvote":  # {MARK}
        res.setdefault("upvotes", {}).update(status="complete", refresh_to_held=True, ph_list_end="first_held_upvote")""",
):
    if end_anchor in src:
        end_repl = end_anchor + """
    elif a.mode == "repullupvotes" and getattr(R, "_refresh_past_held", False) and not ended:  # POST_CLOSE_CALIBRATE_PATCH
        ended = "watermark_passed"
        res.setdefault("upvotes", {}).update(status="complete", refresh_past_held=True, ph_list_end="watermark_passed")"""
        src = src.replace(end_anchor, end_repl, 1)
        break
else:
    print("first_held tail not found", file=sys.stderr)
    sys.exit(1)

p.write_text(src)
print("patched post_close_calibrate")