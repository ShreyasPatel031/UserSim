#!/usr/bin/env python3
"""Population audit: copy run.timing tab paging onto each tab object as paging.ended (whole() only had it under run.timing)."""
from __future__ import annotations

import pathlib
import sys

MARK = "TAB_PAGING_EXPORT_PATCH"
p = pathlib.Path("/opt/ph/reuse/ph_batch.py")
if not p.exists():
    print("ph_batch.py missing; skip")
    sys.exit(0)
src = p.read_text()
if MARK in src:
    print("tab_paging_export already patched")
    sys.exit(0)

needle = '    res["run"] = {"wall_seconds": round(time.time() - R.t0, 1), "requests": R.reqs, "gql_calls": getattr(R, \'gql_calls\', 0), "html_fetches": getattr(R, \'html_fetches\', 0), "thread_navs": getattr(R, \'navs\', 0), "clicks": getattr(R, \'clicks\', 0),\n                  "blocks": R.blocks, "timing": timing, "finished_utc": now()}\n    return res\n\nasync def pull_tabs'
repl = (
    """    # TAB_PAGING_EXPORT_PATCH: Population expects res[tab].paging.ended (not only run.timing[tab].paging)
    for _pk in ("upvotes", "hunted", "following", "forums", "collections", "followers", "activity"):
        _tm = timing.get(_pk) or {}
        _pg = _tm.get("paging")
        if isinstance(res.get(_pk), dict) and _pg:
            res[_pk]["paging"] = _pg
        elif isinstance(res.get(_pk), dict) and _tm.get("skipped"):
            res[_pk]["paging"] = {"ended": _tm["skipped"], "method": "skipped"}
    if isinstance(res.get("reviews"), dict):
        _ex = getattr(R, "exh", {}) or {}
        if _ex.get("reviews"):
            res["reviews"]["paging"] = {"ended": "hasNextPage_false", "method": "ssr_detailed_reviews"}
        elif res["header"].get("reviews") == 0:
            res["reviews"]["paging"] = {"ended": "header_0", "method": "ssr_detailed_reviews"}
    if isinstance(res.get("stacks"), dict) and not res["stacks"].get("paging"):
        if getattr(R, "stacks_paging", None):
            res["stacks"]["paging"] = R.stacks_paging
        else:
            _ex = getattr(R, "exh", {}) or {}
            if _ex.get("stacks"):
                res["stacks"]["paging"] = {"ended": "hasNextPage_false", "method": "stacks_exhausted"}
    if isinstance(res.get("collections"), dict) and not res["collections"].get("paging"):
        _ch = res["header"].get("collections") or 0
        _got = len((res["collections"].get("items") or []))
        if _ch == 0:
            res["collections"]["paging"] = {"ended": "header_0", "method": "collections"}
        elif _got >= 0.98 * _ch:
            res["collections"]["paging"] = {"ended": "server_end", "method": "collections"}
    res["run"] = {"wall_seconds": round(time.time() - R.t0, 1), "requests": R.reqs, "gql_calls": getattr(R, 'gql_calls', 0), "html_fetches": getattr(R, 'html_fetches', 0), "thread_navs": getattr(R, 'navs', 0), "clicks": getattr(R, 'clicks', 0),
                  "blocks": R.blocks, "timing": timing, "finished_utc": now()}
    return res

async def pull_tabs"""
)
if needle not in src:
    print("tab_paging_export anchor not found", file=sys.stderr)
    sys.exit(1)
p.write_text(src.replace(needle, repl, 1))
print("patched tab_paging_export")