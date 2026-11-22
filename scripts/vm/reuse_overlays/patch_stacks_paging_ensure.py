#!/usr/bin/env python3
"""Ensure res.stacks.paging.ended on every whole() save (Population audit); idempotent booster after TAB_PAGING_EXPORT."""
from __future__ import annotations

import pathlib
import sys

MARK = "STACKS_PAGING_ENSURE_PATCH"
p = pathlib.Path("/opt/ph/reuse/ph_batch.py")
src = p.read_text()
if MARK in src:
    print("stacks_paging_ensure already patched")
    sys.exit(0)
if "TAB_PAGING_EXPORT_PATCH" not in src:
    print("tab_paging_export missing; run patch_ph_batch_tab_paging_export first", file=sys.stderr)
    sys.exit(1)

old = """    if isinstance(res.get("stacks"), dict) and not res["stacks"].get("paging"):
        if getattr(R, "stacks_paging", None):
            res["stacks"]["paging"] = R.stacks_paging
        else:
            _ex = getattr(R, "exh", {}) or {}
            if _ex.get("stacks"):
                res["stacks"]["paging"] = {"ended": "hasNextPage_false", "method": "stacks_exhausted"}"""
new = f"""    if isinstance(res.get("stacks"), dict) and not res["stacks"].get("paging"):
        _sh = res["header"].get("stacks")
        _got = len(res["stacks"].get("items") or [])
        if not _sh:
            res["stacks"]["paging"] = {{"ended": "header_0", "method": "stacks"}}
        elif getattr(R, "stacks_paging", None):
            res["stacks"]["paging"] = dict(R.stacks_paging)
            res["stacks"]["paging"].setdefault("ended", "hasNextPage_false")
        elif (getattr(R, "exh", {{}}) or {{}}).get("stacks"):
            res["stacks"]["paging"] = {{"ended": "hasNextPage_false", "method": "stacks_gql", "got": _got, "header": _sh}}
        elif "stacks" in (getattr(R, "trunc", None) or []):
            res["stacks"]["paging"] = {{"ended": "truncated_budget", "method": "stacks", "got": _got, "header": _sh}}
        else:
            res["stacks"]["paging"] = {{"ended": "server_end", "method": "stacks", "got": _got, "header": _sh}}
    # {MARK}"""
if old not in src:
  # booster only: insert before res["run"] after collections block if stacks block absent
    anchor = "    res[\"run\"] = {\"wall_seconds\": round(time.time() - R.t0, 1)"
    if anchor not in src or MARK in src:
        print("stacks_paging_ensure: no anchor", file=sys.stderr)
        sys.exit(1)
    insert = """
    if isinstance(res.get("stacks"), dict) and not res["stacks"].get("paging"):
        _sh = res["header"].get("stacks")
        _got = len(res["stacks"].get("items") or [])
        if not _sh:
            res["stacks"]["paging"] = {"ended": "header_0", "method": "stacks"}
        elif getattr(R, "stacks_paging", None):
            res["stacks"]["paging"] = dict(R.stacks_paging)
            res["stacks"]["paging"].setdefault("ended", "hasNextPage_false")
        elif (getattr(R, "exh", {}) or {}).get("stacks"):
            res["stacks"]["paging"] = {"ended": "hasNextPage_false", "method": "stacks_gql", "got": _got, "header": _sh}
        elif "stacks" in (getattr(R, "trunc", None) or []):
            res["stacks"]["paging"] = {"ended": "truncated_budget", "method": "stacks", "got": _got, "header": _sh}
        else:
            res["stacks"]["paging"] = {"ended": "server_end", "method": "stacks", "got": _got, "header": _sh}
    # STACKS_PAGING_ENSURE_PATCH
"""
    src = src.replace(anchor, insert + anchor, 1)
else:
    src = src.replace(old, new, 1)
p.write_text(src)
print("patched stacks_paging_ensure")