#!/usr/bin/env python3
"""Repair ph_batch.py SyntaxError from broken UPVOTES_PH_END_PATCH _uv line (unmatched ')' )."""
from __future__ import annotations

import pathlib
import sys

MARK = "UPVOTES_PH_END_SYNTAX_FIX"
root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path("/opt/ph/reuse")
pb = root / "ph_batch.py"
src = pb.read_text()
if MARK in src:
    print(f"{pb.name}: already fixed")
    sys.exit(0)
bad = (
    '    _uv = ((res.get("run") or {}).get("timing") or {}).get("upvotes", {}).get("paging") '
    'or getattr(R, "last_paging", None) or {})\n'
)
good = (
    "    _run = res.get(\"run\") or {}\n"
    "    _tm = _run.get(\"timing\") or {}\n"
    '    _uv = (_tm.get("upvotes") or {}).get("paging") or getattr(R, "last_paging", None) or {}\n'
)
if bad not in src:
  # try single-line variant only
    bad1 = '_uv = ((res.get("run") or {}).get("timing") or {}).get("upvotes", {}).get("paging") or getattr(R, "last_paging", None) or {})'
    if bad1 in src:
        src = src.replace(
            bad1,
            '_run = res.get("run") or {}\n'
            '    _tm = _run.get("timing") or {}\n'
            '    _uv = (_tm.get("upvotes") or {}).get("paging") or getattr(R, "last_paging", None) or {}',
            1,
        )
    else:
        print("broken _uv line not found", file=sys.stderr)
        sys.exit(1)
else:
    src = src.replace(bad, good, 1)
if "# UPVOTES_PH_END_SYNTAX_FIX" not in src:
    src = src.replace(
        "    if getattr(R, \"upv_capped\", False) and _uh > len(ups) and not _ph_end:  # UPVOTES_PH_END_PATCH",
        "    if getattr(R, \"upv_capped\", False) and _uh > len(ups) and not _ph_end:  # UPVOTES_PH_END_PATCH\n    # UPVOTES_PH_END_SYNTAX_FIX",
        1,
    )
pb.write_text(src)
compile(src, str(pb), "exec")
print(f"{pb.name}: {MARK}")